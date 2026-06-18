import asyncio
import hashlib
import io
import json
import logging
import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from config.settings import settings
from services.external_client import call_scraper
from services.location_service import (
    LocationContext,
    assess_location_relevance,
    should_keep_scraped_content,
)
from services.crawlers import (
    CrawlResultPayload,
    crawler_result_to_dict,
    estimate_entity_coverage,
    get_shared_crawl4ai_crawler,
    get_shared_playwright_fallback_crawler,
)
from services.security.url_guard import assert_public_url
from services.storage_service import read_from_r2, upload_to_r2

try:
    from pypdf import PdfReader
except ImportError:
    try:
        from PyPDF2 import PdfReader  # type: ignore[no-redef]
    except ImportError:
        PdfReader = None  # type: ignore[assignment]

SCRAPLING_IMPORT_ERRORS: List[str] = []
try:
    from scrapling.fetchers import Fetcher
except Exception as exc:
    Fetcher = None  # type: ignore[assignment]
    SCRAPLING_IMPORT_ERRORS.append(f"Fetcher: {exc}")

try:
    from scrapling.fetchers import DynamicFetcher
except Exception as exc:
    DynamicFetcher = None  # type: ignore[assignment]
    SCRAPLING_IMPORT_ERRORS.append(f"DynamicFetcher: {exc}")

try:
    from scrapling.fetchers import StealthyFetcher
except Exception as exc:
    StealthyFetcher = None  # type: ignore[assignment]
    SCRAPLING_IMPORT_ERRORS.append(f"StealthyFetcher: {exc}")

SCRAPLING_IMPORT_ERROR = "Scrapling import failed: " + "; ".join(SCRAPLING_IMPORT_ERRORS)
if Fetcher is not None or DynamicFetcher is not None or StealthyFetcher is not None:
    SCRAPLING_IMPORT_ERROR = ""

logger = logging.getLogger(__name__)

DEBUG = True
SCRAPE_TIMEOUT_SECONDS = min(settings.EXTERNAL_TIMEOUT_SECONDS, 8)
SCRAPE_MAX_RETRIES = max(1, min(int(settings.SCRAPER_MAX_RETRIES), settings.EXTERNAL_MAX_RETRIES))
MAX_CONCURRENT_REQUESTS = max(1, min(int(settings.SCRAPER_MAX_CONCURRENT_REQUESTS), 8))
TOTAL_URL_CAP = 200
MIN_PDF_CONTENT_LENGTH = 500
MIN_WEB_CONTENT_LENGTH = 180
SCRAPLING_TIMEOUT_SECONDS = 8
CRAWL4AI_MIN_CONTENT_LENGTH = max(120, settings.CRAWL4AI_MIN_CONTENT_LENGTH)
SCRAPE_BATCH_DELAY_SECONDS = max(0.0, float(settings.SCRAPE_BATCH_DELAY_SECONDS))
SCRAPE_BATCH_JITTER_SECONDS = max(0.0, float(settings.SCRAPE_BATCH_JITTER_SECONDS))
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
TOKEN_PATTERN = re.compile(r"\b[a-z0-9]{4,}\b")
SECTION_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "trends": ("trend", "trends", "innovation", "outlook", "forecast", "adoption", "shift", "growth"),
    "drivers": ("driver", "drivers", "demand", "factor", "factors", "incentive", "policy", "catalyst"),
    "challenges": ("challenge", "challenges", "risk", "risks", "constraint", "constraints", "barrier", "barriers"),
    "competitive_landscape": ("competitive", "competition", "players", "vendors", "providers", "market share", "leaders"),
    "competitive landscape": ("competitive", "competition", "players", "vendors", "providers", "market share"),
    "company_profile": ("company", "profile", "headquarters", "investor", "about", "business", "products", "services"),
    "company profile": ("company", "profile", "headquarters", "investor", "about", "business", "products", "services"),
}
STOPWORDS = {
    "about",
    "analysis",
    "and",
    "for",
    "from",
    "industry",
    "into",
    "market",
    "report",
    "section",
    "that",
    "the",
    "their",
    "these",
    "this",
    "topic",
    "with",
}
BLOCKED_REFERENCE_DOMAINS = (
    "wikipedia.org",
    "wikimedia.org",
    "wikia.com",
    "fandom.com",
)


def _log(message: str) -> None:
    logger.info("%s", message)


def _error_message(exc: Exception) -> str:
    message = str(exc).strip()
    message = re.sub(r"([?&]token=)[^&\s']+", r"\1<redacted>", message)
    return message or exc.__class__.__name__


def _extract_domain(url: str) -> str:
    parsed = urlparse(str(url).strip())
    domain = parsed.netloc.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def _is_blocked_reference_domain(domain: str) -> bool:
    return any(domain == blocked or domain.endswith(f".{blocked}") for blocked in BLOCKED_REFERENCE_DOMAINS)


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized[:60] or "source"


def _filename_seed(title: str, url: str, fallback: str) -> str:
    parsed = urlparse(url)
    path_name = (parsed.path or "").rstrip("/").split("/")[-1]
    path_stem = path_name.rsplit(".", 1)[0] if path_name else ""
    seed = title.strip() or path_stem.strip() or _extract_domain(url) or fallback
    return _slugify(seed)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_html_text(html: str) -> str:
    if not html.strip():
        return ""

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "aside", "form", "svg"]):
        tag.extract()

    root = soup.find("main") or soup.find("article") or soup.find("body") or soup
    segments: List[str] = []
    seen_segments = set()

    for element in root.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        text = _normalize_whitespace(element.get_text(" ", strip=True))
        if len(text) < 40:
            continue
        lowered = text.lower()
        if lowered in seen_segments:
            continue
        seen_segments.add(lowered)
        segments.append(text)

    if not segments:
        return _normalize_whitespace(root.get_text(separator="\n", strip=True))

    return "\n\n".join(segments).strip()


def _extract_body_text(html: str) -> str:
    if not html.strip():
        return ""

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "aside", "form", "svg"]):
        tag.extract()

    root = soup.find("main") or soup.find("article") or soup.find("body") or soup
    return _normalize_whitespace(root.get_text(separator="\n", strip=True))


def _extract_metadata_summary(html: str) -> str:
    if not html.strip():
        return ""

    soup = BeautifulSoup(html, "html.parser")
    candidates: List[str] = []
    seen = set()

    def _push(value: str) -> None:
        normalized = _normalize_whitespace(value)
        lowered = normalized.lower()
        if len(normalized) < 20 or lowered in seen:
            return
        seen.add(lowered)
        candidates.append(normalized)

    if soup.title and soup.title.string:
        _push(str(soup.title.string))

    for attrs in (
        {"name": "description"},
        {"property": "og:description"},
        {"name": "twitter:description"},
    ):
        meta_tag = soup.find("meta", attrs=attrs)
        if meta_tag and meta_tag.get("content"):
            _push(str(meta_tag.get("content")))

    for tag_name in ("h1", "h2"):
        for element in soup.find_all(tag_name, limit=3):
            _push(element.get_text(" ", strip=True))

    return "\n\n".join(candidates).strip()


def _extract_image_url(html: str, page_url: str) -> str:
    if not html.strip():
        return ""

    soup = BeautifulSoup(html, "html.parser")

    for attrs in (
        {"property": "og:image"},
        {"name": "og:image"},
        {"property": "twitter:image"},
        {"name": "twitter:image"},
    ):
        meta_tag = soup.find("meta", attrs=attrs)
        if meta_tag and meta_tag.get("content"):
            candidate = str(meta_tag.get("content")).strip()
            if candidate:
                return urljoin(page_url, candidate)

    for img in soup.find_all("img", limit=12):
        candidate = str(img.get("src") or "").strip()
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered.startswith("data:"):
            continue
        if any(marker in lowered for marker in ("logo", "icon", "sprite", "avatar")):
            continue
        return urljoin(page_url, candidate)

    return ""


def _tokenize(text: str) -> List[str]:
    return [token for token in TOKEN_PATTERN.findall(text.lower()) if token not in STOPWORDS]


def _section_tokens(section: str) -> List[str]:
    normalized_section = section.strip().lower()
    return list(SECTION_KEYWORDS.get(normalized_section, ())) or _tokenize(normalized_section)


def _is_relevant_content(title: str, content: str, topic: str, section: str) -> bool:
    combined = f"{title} {content}".lower()
    topic_tokens = _tokenize(topic)
    section_tokens = _section_tokens(section)

    if not topic_tokens:
        return False

    topic_hits = sum(1 for token in set(topic_tokens) if token in combined)
    required_topic_hits = 1 if len(set(topic_tokens)) <= 2 else 2
    topic_ok = topic.strip().lower() in combined or topic_hits >= required_topic_hits

    if not section_tokens:
        return topic_ok

    section_ok = section.strip().lower() in combined or any(token in combined for token in set(section_tokens))
    return topic_ok and section_ok


def _scrape_candidate_priority(result: Dict[str, Any]) -> tuple[int, ...]:
    return (
        int(result.get("competitor_discovery_signal_score", 0)),
        int(result.get("location_score", 0)),
        int(result.get("domain_quality_score", 0)),
        int(result.get("query_relevance_score", 0)),
        int(result.get("rank_score", 0)),
        int(result.get("temporal_boost", 0)),
        1 if str(result.get("source_type", "")).strip() in {"government", "report", "news"} else 0,
    )


def _content_signature(text: str) -> str:
    normalized = _normalize_whitespace(text[:500]).lower()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest() if normalized else ""


def _is_probable_pdf_url(url: str) -> bool:
    lower_url = str(url).strip().lower()
    return lower_url.endswith(".pdf") or ".pdf?" in lower_url


async def _extract_pdf_content(content: bytes) -> str:
    if PdfReader is None:
        logger.warning("PDF parser is unavailable. Skipping PDF extraction.")
        return ""

    try:
        reader = PdfReader(io.BytesIO(content))
        parts: List[str] = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                parts.append(page_text)
        return "\n".join(parts).strip()
    except Exception as exc:
        logger.warning("PDF extraction failed: %s", exc)
        return ""


async def _download_pdf(url: str, client: httpx.AsyncClient) -> Tuple[str, bytes, str]:
    try:
        assert_public_url(url)
    except ValueError as exc:
        return "", b"", str(exc)
    response = await call_scraper(
        "download_pdf",
        lambda: client.get(url, timeout=SCRAPE_TIMEOUT_SECONDS, follow_redirects=True),
        fallback=None,
        timeout=SCRAPE_TIMEOUT_SECONDS,
        max_retries=SCRAPE_MAX_RETRIES,
        context={"url": url},
    )
    if response is None:
        return "", b"", "PDF download failed."

    try:
        response.raise_for_status()
        raw_content = response.content
        extracted = await _extract_pdf_content(raw_content)
        if len(_normalize_whitespace(extracted)) < MIN_PDF_CONTENT_LENGTH:
            raise ValueError("PDF content too short after extraction.")
        return extracted, raw_content, ""
    except Exception as exc:
        return "", b"", _error_message(exc)


def _looks_like_access_challenge(text: str) -> bool:
    normalized = _normalize_whitespace(text).lower()
    if not normalized:
        return False
    markers = (
        "captcha",
        "enable javascript",
        "verify you are human",
        "access denied",
        "too many requests",
        "temporarily blocked",
        "bot detection",
        "cf-chl",
        "cloudflare",
    )
    return any(marker in normalized for marker in markers)


async def _scrape_with_httpx_payload(url: str, client: httpx.AsyncClient) -> Tuple[str, str, str]:
    try:
        assert_public_url(url)
    except ValueError as exc:
        return "", "", str(exc)

    response = await call_scraper(
        "direct_http_request",
        lambda: client.get(
            url,
            timeout=SCRAPE_TIMEOUT_SECONDS,
            follow_redirects=True,
        ),
        fallback=None,
        timeout=SCRAPE_TIMEOUT_SECONDS,
        max_retries=SCRAPE_MAX_RETRIES,
        context={"url": url},
    )
    if response is None:
        return "", "", "Direct HTTP request failed."

    try:
        response.raise_for_status()
        if "text/html" not in str(response.headers.get("content-type", "")).lower():
            return "", "", "Direct HTTP request returned non-HTML content."

        image_url = _extract_image_url(response.text, url)
        text = _extract_html_text(response.text)
        normalized_text = _normalize_whitespace(text)
        if len(normalized_text) >= MIN_WEB_CONTENT_LENGTH and not _looks_like_access_challenge(normalized_text):
            return text, image_url, ""

        fallback_body_text = _extract_body_text(response.text)
        normalized_fallback_text = _normalize_whitespace(fallback_body_text)
        if len(normalized_fallback_text) >= MIN_WEB_CONTENT_LENGTH and not _looks_like_access_challenge(normalized_fallback_text):
            logger.info(
                "Direct HTTP accepted via fallback body extraction url=%s chars=%s",
                url,
                len(normalized_fallback_text),
            )
            return fallback_body_text, image_url, ""

        metadata_summary = _extract_metadata_summary(response.text)
        normalized_metadata_summary = _normalize_whitespace(metadata_summary)
        if len(normalized_metadata_summary) >= MIN_WEB_CONTENT_LENGTH and not _looks_like_access_challenge(normalized_metadata_summary):
            logger.info(
                "Direct HTTP accepted via metadata summary url=%s chars=%s",
                url,
                len(normalized_metadata_summary),
            )
            return metadata_summary, image_url, ""

        if _looks_like_access_challenge(normalized_text or normalized_fallback_text or normalized_metadata_summary):
            return "", image_url, "Direct HTTP response appears to be a bot challenge."

        return "", image_url, "Direct HTTP returned insufficient content."
    except Exception as exc:
        return "", "", _error_message(exc)


async def _scrape_with_scrapedo(url: str, client: httpx.AsyncClient) -> Tuple[str, str]:
    try:
        assert_public_url(url)
    except ValueError as exc:
        return "", str(exc)
    if not settings.SCRAPEDO_KEY.strip():
        return "", "SCRAPEDO_KEY is not configured."

    params = {
        "token": settings.SCRAPEDO_KEY,
        "url": url,
        "render": "true",
        "waitUntil": "domcontentloaded",
        "blockResources": "true",
    }
    response = await call_scraper(
        "scrape_do_request",
        lambda: client.get(
            "https://api.scrape.do",
            params=params,
            timeout=SCRAPE_TIMEOUT_SECONDS,
            follow_redirects=True,
        ),
        fallback=None,
        timeout=SCRAPE_TIMEOUT_SECONDS,
        max_retries=SCRAPE_MAX_RETRIES,
        context={"url": url},
    )
    if response is None:
        return "", "Scrape.do request failed."

    try:
        response.raise_for_status()
        text = _extract_html_text(response.text)
        normalized_text = _normalize_whitespace(text)
        if len(normalized_text) >= MIN_WEB_CONTENT_LENGTH:
            return text, ""

        fallback_body_text = _extract_body_text(response.text)
        if len(fallback_body_text) >= MIN_WEB_CONTENT_LENGTH:
            logger.info(
                "Scrape.do primary accepted via fallback body extraction url=%s chars=%s",
                url,
                len(fallback_body_text),
            )
            return fallback_body_text, ""

        metadata_summary = _extract_metadata_summary(response.text)
        if len(metadata_summary) >= MIN_WEB_CONTENT_LENGTH:
            logger.info(
                "Scrape.do primary accepted via metadata summary url=%s chars=%s",
                url,
                len(metadata_summary),
            )
            return metadata_summary, ""

        return "", "Scrape.do returned insufficient content."
    except Exception as exc:
        return "", _error_message(exc)


async def _scrape_with_scrapedo_payload(url: str, client: httpx.AsyncClient) -> Tuple[str, str, str]:
    try:
        assert_public_url(url)
    except ValueError as exc:
        return "", "", str(exc)
    if not settings.SCRAPEDO_KEY.strip():
        return "", "", "SCRAPEDO_KEY is not configured."

    params = {
        "token": settings.SCRAPEDO_KEY,
        "url": url,
        "render": "true",
        "waitUntil": "domcontentloaded",
        "blockResources": "true",
    }
    response = await call_scraper(
        "scrape_do_request",
        lambda: client.get(
            "https://api.scrape.do",
            params=params,
            timeout=SCRAPE_TIMEOUT_SECONDS,
            follow_redirects=True,
        ),
        fallback=None,
        timeout=SCRAPE_TIMEOUT_SECONDS,
        max_retries=SCRAPE_MAX_RETRIES,
        context={"url": url},
    )
    if response is None:
        return "", "", "Scrape.do request failed."

    try:
        response.raise_for_status()
        text = _extract_html_text(response.text)
        image_url = _extract_image_url(response.text, url)
        normalized_text = _normalize_whitespace(text)
        if len(normalized_text) >= MIN_WEB_CONTENT_LENGTH:
            return text, image_url, ""

        fallback_body_text = _extract_body_text(response.text)
        if len(fallback_body_text) >= MIN_WEB_CONTENT_LENGTH:
            logger.info(
                "Scrape.do primary accepted via fallback body extraction url=%s chars=%s",
                url,
                len(fallback_body_text),
            )
            return fallback_body_text, image_url, ""

        metadata_summary = _extract_metadata_summary(response.text)
        if len(metadata_summary) >= MIN_WEB_CONTENT_LENGTH:
            logger.info(
                "Scrape.do primary accepted via metadata summary url=%s chars=%s",
                url,
                len(metadata_summary),
            )
            return metadata_summary, image_url, ""

        return "", image_url, "Scrape.do returned insufficient content."
    except Exception as exc:
        return "", "", _error_message(exc)


def _scrapling_markup(page: Any) -> str:
    try:
        if hasattr(page, "css"):
            body_html = page.css("body").get()
            if body_html:
                return str(body_html)
    except Exception:
        pass

    for attr_name in ("html", "content", "text"):
        attr_value = getattr(page, attr_name, "")
        if attr_value:
            return str(attr_value)

    try:
        return str(page.get()) if hasattr(page, "get") else str(page)
    except Exception:
        return str(page)


def _call_scrapling_fetcher(fetcher: Any, url: str) -> Any:
    if fetcher is Fetcher:
        return fetcher.get(
            url,
            timeout=SCRAPLING_TIMEOUT_SECONDS,
            follow_redirects=True,
        )

    fetch_method = getattr(fetcher, "fetch", None) or getattr(fetcher, "get", None)
    if fetch_method is None:
        raise RuntimeError(f"Unsupported Scrapling fetcher: {fetcher}")

    return fetch_method(
        url,
        timeout=SCRAPLING_TIMEOUT_SECONDS * 1000,
        headless=True,
        disable_resources=True,
        block_ads=True,
    )


def _scrape_with_scrapling_sync(url: str) -> str:
    errors: List[str] = []
    fetchers = [Fetcher, DynamicFetcher, StealthyFetcher]

    for fetcher in fetchers:
        if fetcher is None:
            continue
        try:
            page = _call_scrapling_fetcher(fetcher, url)
            extracted = _extract_html_text(_scrapling_markup(page))
            if len(_normalize_whitespace(extracted)) >= MIN_WEB_CONTENT_LENGTH:
                return extracted
        except Exception as exc:
            errors.append(_error_message(exc))

    raise RuntimeError("; ".join(errors) or "Scrapling is unavailable.")


def _scrapling_markup_from_url_sync(url: str) -> str:
    errors: List[str] = []
    fetchers = [Fetcher, DynamicFetcher, StealthyFetcher]

    for fetcher in fetchers:
        if fetcher is None:
            continue
        try:
            page = _call_scrapling_fetcher(fetcher, url)
            markup = _scrapling_markup(page)
            if markup and markup.strip():
                return markup
        except Exception as exc:
            errors.append(_error_message(exc))

    raise RuntimeError("; ".join(errors) or "Scrapling is unavailable.")


async def _scrape_with_scrapling(url: str) -> Tuple[str, str]:
    try:
        assert_public_url(url)
    except ValueError as exc:
        return "", str(exc)
    if Fetcher is None and DynamicFetcher is None and StealthyFetcher is None:
        return "", SCRAPLING_IMPORT_ERROR or "Scrapling is not installed."

    loop = asyncio.get_running_loop()
    try:
        # Scrapling is sync, so keep it off the event loop and route it through the shared retry wrapper.
        content = await call_scraper(
            "scrapling_fallback",
            lambda: loop.run_in_executor(None, _scrape_with_scrapling_sync, url),
            fallback="",
            timeout=SCRAPLING_TIMEOUT_SECONDS,
            max_retries=SCRAPE_MAX_RETRIES,
            context={"url": url},
        )
        if not content:
            raise RuntimeError("Scrapling returned no content.")
        return content, ""
    except Exception as exc:
        error_message = _error_message(exc)
        logger.warning("Scrapling fallback failed for %s: %s", url, error_message)
        return "", error_message


async def _scrape_with_scrapling_payload(url: str) -> Tuple[str, str, str]:
    try:
        assert_public_url(url)
    except ValueError as exc:
        return "", "", str(exc)
    if Fetcher is None and DynamicFetcher is None and StealthyFetcher is None:
        return "", "", SCRAPLING_IMPORT_ERROR or "Scrapling is not installed."

    loop = asyncio.get_running_loop()
    try:
        raw_markup = await call_scraper(
            "scrapling_fallback",
            lambda: loop.run_in_executor(None, _scrapling_markup_from_url_sync, url),
            fallback="",
            timeout=SCRAPLING_TIMEOUT_SECONDS,
            max_retries=SCRAPE_MAX_RETRIES,
            context={"url": url},
        )
        if not raw_markup:
            raise RuntimeError("Scrapling returned no content.")

        content = _extract_html_text(raw_markup)
        if len(_normalize_whitespace(content)) < MIN_WEB_CONTENT_LENGTH:
            raise RuntimeError("Scrapling returned insufficient content.")
        return content, _extract_image_url(raw_markup, url), ""
    except Exception as exc:
        error_message = _error_message(exc)
        logger.warning("Scrapling fallback failed for %s: %s", url, error_message)
        return "", "", error_message


async def _scrape_with_existing_stack_payload(url: str, client: httpx.AsyncClient) -> CrawlResultPayload:
    started_at = time.perf_counter()
    direct_text, direct_image_url, direct_error = await _scrape_with_httpx_payload(url, client)
    if direct_text:
        return CrawlResultPayload(
            url=url,
            markdown=direct_text,
            raw_markdown=direct_text,
            clean_markdown=direct_text,
            plain_text=direct_text,
            crawler_used="httpx_direct",
            crawl_duration_ms=int((time.perf_counter() - started_at) * 1000),
            image_url=direct_image_url,
            error="",
        ).ensure_metrics()

    scrapling_text, scrapling_image_url, scrapling_error = await _scrape_with_scrapling_payload(url)
    if scrapling_text:
        return CrawlResultPayload(
            url=url,
            markdown=scrapling_text,
            raw_markdown=scrapling_text,
            clean_markdown=scrapling_text,
            plain_text=scrapling_text,
            crawler_used="scrapling",
            crawl_duration_ms=int((time.perf_counter() - started_at) * 1000),
            fallback_triggered=True,
            image_url=scrapling_image_url or direct_image_url,
            error="",
        ).ensure_metrics()

    playwright_crawler = await get_shared_playwright_fallback_crawler()
    playwright_result = await playwright_crawler.crawl(url)
    if playwright_result.is_success:
        playwright_result.fallback_triggered = True
        if not playwright_result.image_url:
            playwright_result.image_url = direct_image_url or scrapling_image_url
        return playwright_result.ensure_metrics()

    scrapedo_text, scrapedo_image_url, scrapedo_error = await _scrape_with_scrapedo_payload(url, client)
    if scrapedo_text:
        return CrawlResultPayload(
            url=url,
            markdown=scrapedo_text,
            raw_markdown=scrapedo_text,
            clean_markdown=scrapedo_text,
            plain_text=scrapedo_text,
            crawler_used="scrapedo",
            crawl_duration_ms=int((time.perf_counter() - started_at) * 1000),
            fallback_triggered=True,
            image_url=scrapedo_image_url or direct_image_url or scrapling_image_url,
            error="",
        ).ensure_metrics()

    combined_errors = [message for message in (direct_error, scrapling_error, playwright_result.error, scrapedo_error) if message]
    return CrawlResultPayload(
        url=url,
        crawler_used="legacy_scraper",
        crawl_duration_ms=int((time.perf_counter() - started_at) * 1000),
        error=" | ".join(combined_errors) or "All web scraping methods failed.",
    ).ensure_metrics()


def _crawl_quality_is_sufficient(payload: CrawlResultPayload) -> bool:
    if not payload.is_success:
        return False
    if payload.content_length < CRAWL4AI_MIN_CONTENT_LENGTH:
        return False
    return payload.extraction_quality_score >= float(settings.CRAWL4AI_QUALITY_THRESHOLD)


def _is_probably_dynamic_page(payload: CrawlResultPayload) -> bool:
    metadata_blob = json.dumps(payload.metadata, ensure_ascii=True).lower() if payload.metadata else ""
    text = f"{payload.plain_text}\n{payload.markdown}\n{metadata_blob}".lower()
    dynamic_markers = (
        "enable javascript",
        "loading",
        "please wait",
        "app shell",
        "__next",
        "reactroot",
        "chunk.js",
    )
    return any(marker in text for marker in dynamic_markers)


def _benchmark_crawler_outputs(primary: CrawlResultPayload, secondary: CrawlResultPayload) -> Dict[str, Any]:
    return {
        "primary": crawler_result_to_dict(primary),
        "secondary": crawler_result_to_dict(secondary),
        "content_length_delta": int(primary.content_length) - int(secondary.content_length),
        "quality_score_delta": round(float(primary.extraction_quality_score) - float(secondary.extraction_quality_score), 4),
        "entity_coverage": {
            "primary": estimate_entity_coverage(primary.plain_text),
            "secondary": estimate_entity_coverage(secondary.plain_text),
        },
        "duration_delta_ms": int(primary.crawl_duration_ms) - int(secondary.crawl_duration_ms),
    }


async def _run_crawl4ai_pipeline(url: str) -> CrawlResultPayload:
    crawl4ai_crawler = await get_shared_crawl4ai_crawler()
    primary = await crawl4ai_crawler.crawl(url)
    if _crawl_quality_is_sufficient(primary) and not _is_probably_dynamic_page(primary):
        return primary

    playwright_crawler = await get_shared_playwright_fallback_crawler()
    fallback = await playwright_crawler.crawl(url)
    if fallback.is_success:
        fallback.fallback_triggered = True
        return fallback.ensure_metrics()

    primary.fallback_triggered = True
    return primary.ensure_metrics()


def _artifact_counts(artifacts: List[Dict[str, Any]]) -> Dict[str, int]:
    return {
        "total_artifacts": len(artifacts),
        "success_count": sum(1 for artifact in artifacts if artifact.get("status") == "success"),
        "usable_text_count": sum(1 for artifact in artifacts if bool(artifact.get("text_available"))),
        "failed_count": sum(1 for artifact in artifacts if artifact.get("status") == "failed"),
        "filtered_count": sum(1 for artifact in artifacts if artifact.get("status") == "filtered_out"),
    }


def _empty_artifact(
    *,
    artifact_id: str,
    artifact_type: str,
    source_type: str,
    url: str,
    title: str,
    query: str,
    error: str,
    status: str = "failed",
) -> Dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "source_type": source_type,
        "url": url,
        "title": title,
        "query": query,
        "domain": _extract_domain(url),
        "status": status,
        "error": error,
        "binary_key": "",
        "text_key": "",
        "binary_path": "",
        "text_path": "",
        "text_available": False,
        "text_chars": 0,
        "content_signature": "",
        "scrape_method": "",
        "crawler_used": "",
        "crawl_duration_ms": 0,
        "content_length": 0,
        "markdown_length": 0,
        "fallback_triggered": False,
        "extraction_quality_score": 0.0,
        "raw_markdown_key": "",
        "clean_markdown_key": "",
        "markdown_key": "",
        "metadata_key": "",
        "structured_content_key": "",
        "crawler_benchmark": {},
        "location_score": 0,
        "location_matches": [],
        "image_url": "",
    }


async def scrape_url(
    result: Dict[str, Any],
    topic: str,
    section: str,
    location_context: LocationContext,
    session_id: str,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    index: int,
) -> Dict[str, Any]:
    url = str(result.get("url", "")).strip()
    title = str(result.get("title", "")).strip()
    source_type = str(result.get("source_type", "general")).strip() or "general"
    query = str(result.get("query", "")).strip()
    artifact_id = f"src_{index:02d}"

    if not url:
        return _empty_artifact(
            artifact_id=artifact_id,
            artifact_type="web",
            source_type=source_type,
            url=url,
            title=title,
            query=query,
            error="Missing URL.",
        )
    try:
        assert_public_url(url)
    except ValueError as exc:
        return _empty_artifact(
            artifact_id=artifact_id,
            artifact_type="pdf" if _is_probable_pdf_url(url) else "web",
            source_type=source_type,
            url=url,
            title=title,
            query=query,
            error=str(exc),
            status="filtered_out",
        )
    if _is_blocked_reference_domain(_extract_domain(url)):
        return _empty_artifact(
            artifact_id=artifact_id,
            artifact_type="pdf" if _is_probable_pdf_url(url) else "web",
            source_type=source_type,
            url=url,
            title=title,
            query=query,
            error="Blocked low-signal reference domain.",
            status="filtered_out",
        )

    _log(f"[SCRAPER] Start: {url}")
    async with semaphore:
        try:
            wave_index = max(0, (index - 1) % max(1, MAX_CONCURRENT_REQUESTS))
            if wave_index:
                await asyncio.sleep((0.08 * wave_index) + random.uniform(0.0, 0.08))
            if _is_probable_pdf_url(url):
                extracted_text, raw_content, pdf_error = await _download_pdf(url, client)
                if not extracted_text:
                    raise RuntimeError(pdf_error or "PDF scrape failed.")

                location_payload = assess_location_relevance(
                    url=url,
                    title=title,
                    text=extracted_text,
                    context=location_context,
                )
                if not _is_relevant_content(title, extracted_text, topic, section):
                    return _empty_artifact(
                        artifact_id=artifact_id,
                        artifact_type="pdf",
                        source_type=source_type,
                        url=url,
                        title=title,
                        query=query,
                        error="Filtered out by topic/section relevance.",
                        status="filtered_out",
                    )
                if not should_keep_scraped_content(location_payload, location_context):
                    return _empty_artifact(
                        artifact_id=artifact_id,
                        artifact_type="pdf",
                        source_type=source_type,
                        url=url,
                        title=title,
                        query=query,
                        error="Filtered out by location relevance.",
                        status="filtered_out",
                    )

                file_seed = _filename_seed(title, url, artifact_id)
                binary_key = await asyncio.to_thread(
                    upload_to_r2,
                    session_id,
                    f"{index:02d}_{file_seed}.pdf",
                    raw_content,
                )
                text_key = await asyncio.to_thread(
                    upload_to_r2,
                    session_id,
                    f"{index:02d}_{file_seed}.txt",
                    extracted_text,
                )
                if not binary_key or not text_key:
                    raise RuntimeError("Artifact storage failed for PDF source.")
                _log(f"[SCRAPER] Success: {url}")
                return {
                    "artifact_id": artifact_id,
                    "artifact_type": "pdf",
                    "source_type": source_type,
                    "url": url,
                    "title": title,
                    "query": query,
                    "domain": _extract_domain(url),
                    "status": "success",
                    "error": "",
                    "binary_key": binary_key,
                    "text_key": text_key,
                    "binary_path": binary_key,
                    "text_path": text_key,
                    "text_available": True,
                    "text_chars": len(extracted_text),
                    "content_signature": _content_signature(extracted_text),
                    "location_score": int(location_payload.get("location_score", 0)),
                    "location_matches": list(location_payload.get("location_matches", [])),
                }

            crawl_result: CrawlResultPayload
            crawler_benchmark: Dict[str, Any] = {}
            if settings.USE_CRAWL4AI and settings.COMPARE_CRAWLERS:
                crawl_result, legacy_result = await asyncio.gather(
                    _run_crawl4ai_pipeline(url),
                    _scrape_with_existing_stack_payload(url, client),
                )
                crawler_benchmark = _benchmark_crawler_outputs(crawl_result, legacy_result)
            elif settings.USE_CRAWL4AI:
                crawl_result = await _run_crawl4ai_pipeline(url)
            elif settings.COMPARE_CRAWLERS:
                legacy_result, crawl4ai_result = await asyncio.gather(
                    _scrape_with_existing_stack_payload(url, client),
                    _run_crawl4ai_pipeline(url),
                )
                crawl_result = legacy_result
                crawler_benchmark = _benchmark_crawler_outputs(legacy_result, crawl4ai_result)
            else:
                crawl_result = await _scrape_with_existing_stack_payload(url, client)

            if not crawl_result.is_success:
                raise RuntimeError(crawl_result.error or "All web scraping methods failed.")

            content = crawl_result.plain_text
            markdown_content = crawl_result.markdown or content
            raw_markdown = crawl_result.raw_markdown or markdown_content
            clean_markdown = crawl_result.clean_markdown or markdown_content
            metadata_json = json.dumps(crawl_result.metadata, ensure_ascii=False, indent=2) if crawl_result.metadata else ""
            structured_content = crawl_result.structured_content
            image_url = crawl_result.image_url
            scrape_method = crawl_result.crawler_used or "legacy_scraper"

            normalized_content = _normalize_whitespace(content)
            if len(normalized_content) < MIN_WEB_CONTENT_LENGTH:
                raise RuntimeError("Content too short after scraping.")

            location_payload = assess_location_relevance(
                url=url,
                title=title,
                text=normalized_content,
                context=location_context,
            )
            if not _is_relevant_content(title, normalized_content, topic, section):
                return _empty_artifact(
                    artifact_id=artifact_id,
                    artifact_type="web",
                    source_type=source_type,
                    url=url,
                    title=title,
                    query=query,
                    error="Filtered out by topic/section relevance.",
                    status="filtered_out",
                )
            if not should_keep_scraped_content(location_payload, location_context):
                return _empty_artifact(
                    artifact_id=artifact_id,
                    artifact_type="web",
                    source_type=source_type,
                    url=url,
                    title=title,
                    query=query,
                    error="Filtered out by location relevance.",
                    status="filtered_out",
                )

            file_seed = _filename_seed(title, url, artifact_id)
            text_key = await asyncio.to_thread(
                upload_to_r2,
                session_id,
                f"{index:02d}_{file_seed}.txt",
                content,
            )
            markdown_key = await asyncio.to_thread(
                upload_to_r2,
                session_id,
                f"{index:02d}_{file_seed}.md",
                markdown_content,
            )
            raw_markdown_key = await asyncio.to_thread(
                upload_to_r2,
                session_id,
                f"{index:02d}_{file_seed}.raw.md",
                raw_markdown,
            )
            clean_markdown_key = await asyncio.to_thread(
                upload_to_r2,
                session_id,
                f"{index:02d}_{file_seed}.clean.md",
                clean_markdown,
            )
            metadata_key = await asyncio.to_thread(
                upload_to_r2,
                session_id,
                f"{index:02d}_{file_seed}.metadata.json",
                metadata_json or "{}",
            )
            structured_content_key = ""
            if structured_content.strip():
                structured_content_key = await asyncio.to_thread(
                    upload_to_r2,
                    session_id,
                    f"{index:02d}_{file_seed}.structured.txt",
                    structured_content,
                ) or ""
            if not text_key:
                raise RuntimeError("Artifact storage failed for web source.")
            resolved_title = title or crawl_result.title or str(crawl_result.metadata.get("title", "")).strip()
            logger.info(
                "crawler_metrics url=%s crawler_used=%s duration_ms=%s content_length=%s markdown_length=%s fallback_triggered=%s quality_score=%.3f",
                url,
                crawl_result.crawler_used,
                crawl_result.crawl_duration_ms,
                crawl_result.content_length,
                crawl_result.markdown_length,
                crawl_result.fallback_triggered,
                crawl_result.extraction_quality_score,
            )
            _log(f"[SCRAPER] Success: {url}")
            return {
                "artifact_id": artifact_id,
                "artifact_type": "web",
                "source_type": source_type,
                "url": url,
                "title": resolved_title,
                "query": query,
                "domain": _extract_domain(url),
                "status": "success",
                "error": crawl_result.error,
                "binary_key": "",
                "text_key": text_key,
                "binary_path": "",
                "text_path": text_key,
                "text_available": True,
                "text_chars": len(content),
                "content_signature": _content_signature(content),
                "scrape_method": scrape_method,
                "crawler_used": crawl_result.crawler_used,
                "crawl_duration_ms": int(crawl_result.crawl_duration_ms),
                "content_length": int(crawl_result.content_length),
                "markdown_length": int(crawl_result.markdown_length),
                "fallback_triggered": bool(crawl_result.fallback_triggered),
                "extraction_quality_score": float(crawl_result.extraction_quality_score),
                "markdown_key": markdown_key or "",
                "raw_markdown_key": raw_markdown_key or "",
                "clean_markdown_key": clean_markdown_key or "",
                "metadata_key": metadata_key or "",
                "structured_content_key": structured_content_key,
                "crawler_benchmark": crawler_benchmark,
                "location_score": int(location_payload.get("location_score", 0)),
                "location_matches": list(location_payload.get("location_matches", [])),
                "image_url": image_url,
            }
        except Exception as exc:
            error_message = _error_message(exc)
            logger.warning("Scrape failed for %s: %s", url, error_message)
            _log(f"[SCRAPER] Failed: {url} | {error_message}")
            return _empty_artifact(
                artifact_id=artifact_id,
                artifact_type="pdf" if _is_probable_pdf_url(url) else "web",
                source_type=source_type,
                url=url,
                title=title,
                query=query,
                error=error_message,
            )


async def _scrape_batch(
    results: List[Dict[str, Any]],
    topic: str,
    section: str,
    session_id: str,
    location_context: LocationContext | None = None,
    start_index: int = 1,
    timeout_seconds: float | None = None,
) -> Dict[str, Any]:
    resolved_location_context = location_context or LocationContext()
    deduplicated_results: List[Dict[str, Any]] = []
    seen_urls = set()
    for result in results:
        url = str(result.get("url", "")).strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduplicated_results.append(result)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    timeout = httpx.Timeout(SCRAPE_TIMEOUT_SECONDS)
    limits = httpx.Limits(max_connections=MAX_CONCURRENT_REQUESTS, max_keepalive_connections=MAX_CONCURRENT_REQUESTS)

    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=timeout, limits=limits, follow_redirects=True) as client:
        indexed_tasks = [
            (
                result,
                index,
                asyncio.create_task(
                    scrape_url(result, topic, section, resolved_location_context, session_id, client, semaphore, index)
                ),
            )
            for index, result in enumerate(deduplicated_results, start=start_index)
        ]
        tasks = [task for _, _, task in indexed_tasks]
        if timeout_seconds is None:
            done, pending = await asyncio.wait(tasks)
        else:
            done, pending = await asyncio.wait(tasks, timeout=max(1.0, timeout_seconds))
        for pending_task in pending:
            pending_task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    artifacts: List[Dict[str, Any]] = []
    completed = 0
    total = len(deduplicated_results)

    timed_out = bool(pending)
    for result, index, task in indexed_tasks:
        completed += 1
        _log(f"[PROGRESS] {completed}/{total}")
        if task not in done:
            artifacts.append(
                _empty_artifact(
                    artifact_id=f"src_{index:02d}",
                    artifact_type="pdf" if _is_probable_pdf_url(str(result.get("url", ""))) else "web",
                    source_type=str(result.get("source_type", "general")),
                    url=str(result.get("url", "")),
                    title=str(result.get("title", "")),
                    query=str(result.get("query", "")),
                    error="Timed out before batch completion.",
                )
            )
            continue
        try:
            task_result = task.result()
        except asyncio.CancelledError:
            artifacts.append(
                _empty_artifact(
                    artifact_id=f"src_{index:02d}",
                    artifact_type="pdf" if _is_probable_pdf_url(str(result.get("url", ""))) else "web",
                    source_type=str(result.get("source_type", "general")),
                    url=str(result.get("url", "")),
                    title=str(result.get("title", "")),
                    query=str(result.get("query", "")),
                    error="Cancelled before batch completion.",
                )
            )
            continue
        except Exception as task_exc:
            logger.exception("Unhandled scrape task failure for %s", result.get("url", ""))
            artifacts.append(
                _empty_artifact(
                    artifact_id=f"src_{index:02d}",
                    artifact_type="web",
                    source_type=str(result.get("source_type", "general")),
                    url=str(result.get("url", "")),
                    title=str(result.get("title", "")),
                    query=str(result.get("query", "")),
                    error=_error_message(task_exc),
                )
            )
            continue
        artifacts.append(task_result)

    structured_pages: List[Dict[str, str]] = []
    for artifact in artifacts:
        if artifact.get("status") != "success" or not bool(artifact.get("text_available")):
            continue
        text_key = str(artifact.get("text_key") or artifact.get("text_path") or "").strip()
        if not text_key:
            continue
        try:
            content = (await asyncio.to_thread(read_from_r2, text_key)).decode("utf-8", errors="ignore").strip()
        except Exception as exc:
            logger.warning("Failed to read stored artifact from R2 %s: %s", text_key, exc)
            continue
        if len(_normalize_whitespace(content)) < MIN_WEB_CONTENT_LENGTH:
            continue
        structured_pages.append(
            {
                "title": str(artifact.get("title", "")).strip(),
                "url": str(artifact.get("url", "")).strip(),
                "content": content,
                "source_type": str(artifact.get("source_type", "")).strip() or str(artifact.get("artifact_type", "web")).strip(),
                "artifact_type": str(artifact.get("artifact_type", "")).strip() or "web",
                "artifact_path": text_key,
                "location_score": int(artifact.get("location_score", 0)),
                "location_matches": list(artifact.get("location_matches", [])),
                "image_url": str(artifact.get("image_url", "")).strip(),
                "crawler_used": str(artifact.get("crawler_used", "")).strip(),
                "crawl_duration_ms": int(artifact.get("crawl_duration_ms", 0)),
                "content_length": int(artifact.get("content_length", 0)),
                "markdown_length": int(artifact.get("markdown_length", 0)),
                "fallback_triggered": bool(artifact.get("fallback_triggered", False)),
                "extraction_quality_score": float(artifact.get("extraction_quality_score", 0.0)),
                "markdown_key": str(artifact.get("markdown_key", "")).strip(),
                "raw_markdown_key": str(artifact.get("raw_markdown_key", "")).strip(),
                "clean_markdown_key": str(artifact.get("clean_markdown_key", "")).strip(),
                "metadata_key": str(artifact.get("metadata_key", "")).strip(),
                "structured_content_key": str(artifact.get("structured_content_key", "")).strip(),
                "crawler_benchmark": dict(artifact.get("crawler_benchmark", {}) or {}),
            }
        )

    if timed_out:
        logger.warning(
            "Scrape batch reached timeout with partial completions topic=%s section=%s completed=%s total=%s",
            topic,
            section,
            len(done),
            total,
        )

    return {
        "artifacts": artifacts,
        "pages": structured_pages,
        "timed_out": timed_out,
    }


async def scrape_all(
    results: List[Dict[str, Any]],
    topic: str,
    section: str,
    session_id: str,
    location_context: LocationContext | None = None,
) -> Dict[str, Any]:
    resolved_location_context = location_context or LocationContext()
    deduplicated_results: List[Dict[str, Any]] = []
    seen_urls = set()
    for result in results[:TOTAL_URL_CAP]:
        url = str(result.get("url", "")).strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduplicated_results.append(result)
    deduplicated_results.sort(key=_scrape_candidate_priority, reverse=True)

    batch_payload = await _scrape_batch(
        deduplicated_results,
        topic,
        section,
        session_id,
        location_context=resolved_location_context,
        start_index=1,
    )
    artifacts = list(batch_payload.get("artifacts", []))

    seen_signatures = set()
    deduplicated_artifacts: List[Dict[str, Any]] = []
    for artifact in artifacts:
        signature = str(artifact.get("content_signature", "")).strip()
        if artifact.get("status") == "success" and signature and signature in seen_signatures:
            artifact["status"] = "filtered_out"
            artifact["error"] = "Duplicate content removed."
            artifact["text_available"] = False
            artifact["text_key"] = ""
            artifact["text_path"] = ""
            artifact["text_chars"] = 0
        elif artifact.get("status") == "success" and signature:
            seen_signatures.add(signature)
        deduplicated_artifacts.append(artifact)

    structured_pages = list(batch_payload.get("pages", []))

    manifest_payload = {
        "topic": topic,
        "section": section,
        "artifact_dir": f"sessions/{session_id}/",
        "counts": _artifact_counts(deduplicated_artifacts),
        "artifacts": deduplicated_artifacts,
    }
    manifest_key = await asyncio.to_thread(
        upload_to_r2,
        session_id,
        "manifest.json",
        json.dumps(manifest_payload, indent=2),
    )

    return {
        "artifact_dir": f"sessions/{session_id}/",
        "manifest_path": manifest_key,
        "manifest_key": manifest_key,
        "artifacts": deduplicated_artifacts,
        "counts": _artifact_counts(deduplicated_artifacts),
        "pages": structured_pages,
        "manifest": manifest_payload,
    }


async def collect_research_artifacts(
    topic: str,
    section: str,
    session_id: str,
    location_context: LocationContext | None = None,
    pdf_results: Optional[List[Dict[str, Any]]] = None,
    web_results: Optional[List[Dict[str, Any]]] = None,
    search_results: Optional[List[Dict[str, Any]]] = None,
    batch_size: int = 25,
    target_usable_text_count: int = 20,
    max_duration_seconds: int = 90,
) -> Dict[str, Any]:
    combined_results: List[Dict[str, Any]] = []
    for result in (search_results or []) + (pdf_results or []) + (web_results or []):
        if isinstance(result, dict):
            combined_results.append(dict(result))

    deduplicated_candidates: List[Dict[str, Any]] = []
    seen_urls = set()
    for result in combined_results[:TOTAL_URL_CAP]:
        url = str(result.get("url", "")).strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduplicated_candidates.append(result)
    deduplicated_candidates.sort(key=_scrape_candidate_priority, reverse=True)

    _log(f"[SCRAPER] Queue size: {len(deduplicated_candidates)}")

    aggregated_artifacts: List[Dict[str, Any]] = []
    aggregated_pages: List[Dict[str, str]] = []
    start_time = asyncio.get_running_loop().time()
    effective_batch_size = max(1, min(batch_size, TOTAL_URL_CAP))

    for batch_start in range(0, len(deduplicated_candidates), effective_batch_size):
        elapsed_seconds = asyncio.get_running_loop().time() - start_time
        if elapsed_seconds >= max_duration_seconds:
            logger.warning(
                "Scrape budget exhausted before batch start topic=%s section=%s elapsed=%.2fs budget=%ss",
                topic,
                section,
                elapsed_seconds,
                max_duration_seconds,
            )
            break

        batch_results = deduplicated_candidates[batch_start : batch_start + effective_batch_size]
        logger.info(
            "Scrape batch start topic=%s section=%s batch=%s batch_size=%s elapsed=%.2fs",
            topic,
            section,
            (batch_start // effective_batch_size) + 1,
            len(batch_results),
            elapsed_seconds,
        )
        remaining_budget = max_duration_seconds - elapsed_seconds
        batch_payload = await _scrape_batch(
            batch_results,
            topic,
            section,
            session_id,
            location_context=location_context,
            start_index=batch_start + 1,
            timeout_seconds=max(1.0, remaining_budget),
        )
        aggregated_artifacts.extend(list(batch_payload.get("artifacts", [])))
        aggregated_pages.extend(list(batch_payload.get("pages", [])))

        current_counts = _artifact_counts(aggregated_artifacts)
        logger.info(
            "Scrape batch complete topic=%s section=%s usable=%s success=%s failed=%s filtered=%s",
            topic,
            section,
            current_counts["usable_text_count"],
            current_counts["success_count"],
            current_counts["failed_count"],
            current_counts["filtered_count"],
        )
        if bool(batch_payload.get("timed_out")):
            logger.warning(
                "Scrape batch timed out topic=%s section=%s batch=%s partial_success=%s remaining_budget=%.2fs",
                topic,
                section,
                (batch_start // effective_batch_size) + 1,
                current_counts["usable_text_count"],
                remaining_budget,
            )
        if current_counts["usable_text_count"] >= target_usable_text_count:
            logger.info(
                "Scrape early stop reached target usable text topic=%s section=%s usable=%s target=%s",
                topic,
                section,
                current_counts["usable_text_count"],
                target_usable_text_count,
            )
            break
        if batch_start + effective_batch_size < len(deduplicated_candidates):
            batch_delay = SCRAPE_BATCH_DELAY_SECONDS + random.uniform(0.0, SCRAPE_BATCH_JITTER_SECONDS)
            if batch_delay > 0:
                await asyncio.sleep(batch_delay)

    seen_signatures = set()
    deduplicated_artifacts: List[Dict[str, Any]] = []
    for artifact in aggregated_artifacts:
        signature = str(artifact.get("content_signature", "")).strip()
        if artifact.get("status") == "success" and signature and signature in seen_signatures:
            artifact["status"] = "filtered_out"
            artifact["error"] = "Duplicate content removed."
            artifact["text_available"] = False
            artifact["text_key"] = ""
            artifact["text_path"] = ""
            artifact["text_chars"] = 0
        elif artifact.get("status") == "success" and signature:
            seen_signatures.add(signature)
        deduplicated_artifacts.append(artifact)

    manifest_payload = {
        "topic": topic,
        "section": section,
        "artifact_dir": f"sessions/{session_id}/",
        "counts": _artifact_counts(deduplicated_artifacts),
        "artifacts": deduplicated_artifacts,
    }
    manifest_key = await asyncio.to_thread(
        upload_to_r2,
        session_id,
        "manifest.json",
        json.dumps(manifest_payload, indent=2),
    )

    return {
        "artifact_dir": f"sessions/{session_id}/",
        "manifest_path": manifest_key,
        "manifest_key": manifest_key,
        "artifacts": deduplicated_artifacts,
        "counts": _artifact_counts(deduplicated_artifacts),
        "pages": aggregated_pages,
        "manifest": manifest_payload,
    }


def load_saved_sources(artifacts: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    saved_sources: List[Dict[str, str]] = []
    for artifact in artifacts:
        if artifact.get("status") != "success" or not bool(artifact.get("text_available")):
            continue

        text_key = str(artifact.get("text_key") or artifact.get("text_path") or "").strip()
        if not text_key:
            continue

        try:
            text_content = read_from_r2(text_key).decode("utf-8", errors="ignore").strip()
        except Exception as exc:
            logger.warning("Failed to read stored artifact %s: %s", text_key, exc)
            continue

        if len(_normalize_whitespace(text_content)) < MIN_WEB_CONTENT_LENGTH:
            continue

        saved_sources.append(
            {
                "url": str(artifact.get("url", "")).strip(),
                "title": str(artifact.get("title", "")).strip(),
                "content": text_content,
                "artifact_type": str(artifact.get("artifact_type", "")).strip() or "web",
                "source_type": str(artifact.get("source_type", "")).strip() or "general",
                "artifact_path": text_key,
                "location_score": int(artifact.get("location_score", 0)),
                "location_matches": list(artifact.get("location_matches", [])),
                "image_url": str(artifact.get("image_url", "")).strip(),
                "crawler_used": str(artifact.get("crawler_used", "")).strip(),
                "crawl_duration_ms": int(artifact.get("crawl_duration_ms", 0)),
                "content_length": int(artifact.get("content_length", 0)),
                "markdown_length": int(artifact.get("markdown_length", 0)),
                "fallback_triggered": bool(artifact.get("fallback_triggered", False)),
                "extraction_quality_score": float(artifact.get("extraction_quality_score", 0.0)),
                "markdown_key": str(artifact.get("markdown_key", "")).strip(),
                "raw_markdown_key": str(artifact.get("raw_markdown_key", "")).strip(),
                "clean_markdown_key": str(artifact.get("clean_markdown_key", "")).strip(),
                "metadata_key": str(artifact.get("metadata_key", "")).strip(),
                "structured_content_key": str(artifact.get("structured_content_key", "")).strip(),
                "crawler_benchmark": dict(artifact.get("crawler_benchmark", {}) or {}),
            }
        )

    return saved_sources

