import asyncio
import hashlib
import io
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from config.settings import settings
from services.location_service import (
    LocationContext,
    assess_location_relevance,
    should_keep_scraped_content,
)
from services.storage_service import read_from_r2, upload_to_r2

try:
    from pypdf import PdfReader
except ImportError:
    try:
        from PyPDF2 import PdfReader  # type: ignore[no-redef]
    except ImportError:
        PdfReader = None  # type: ignore[assignment]

try:
    from scrapling.fetchers import DynamicFetcher, Fetcher, StealthyFetcher
    SCRAPLING_IMPORT_ERROR = ""
except Exception as exc:
    DynamicFetcher = None  # type: ignore[assignment]
    Fetcher = None  # type: ignore[assignment]
    StealthyFetcher = None  # type: ignore[assignment]
    SCRAPLING_IMPORT_ERROR = f"Scrapling import failed: {exc}"

logger = logging.getLogger(__name__)

DEBUG = True
SCRAPE_TIMEOUT_SECONDS = 10
SCRAPE_MAX_RETRIES = 2
MAX_CONCURRENT_REQUESTS = 2
TOTAL_URL_CAP = 25
MIN_CONTENT_LENGTH = 500
SCRAPLING_TIMEOUT_SECONDS = 10
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
TOKEN_PATTERN = re.compile(r"\b[a-z0-9]{4,}\b")
SECTION_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "trends": ("trend", "trends", "innovation", "outlook", "forecast", "adoption", "shift", "growth"),
    "drivers": ("driver", "drivers", "demand", "factor", "factors", "incentive", "policy", "catalyst"),
    "challenges": ("challenge", "challenges", "risk", "risks", "constraint", "constraints", "barrier", "barriers"),
    "competitive landscape": ("competitive", "competition", "players", "vendors", "providers", "market share"),
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


def _log(message: str) -> None:
    logger.info(message)
    if DEBUG:
        print(message)


def _error_message(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__


def _extract_domain(url: str) -> str:
    parsed = urlparse(str(url).strip())
    domain = parsed.netloc.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


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
    last_error = "Unknown PDF download error"

    for attempt in range(1, SCRAPE_MAX_RETRIES + 2):
        try:
            response = await client.get(url, timeout=SCRAPE_TIMEOUT_SECONDS, follow_redirects=True)
            response.raise_for_status()
            raw_content = response.content
            extracted = await _extract_pdf_content(raw_content)
            if len(_normalize_whitespace(extracted)) < MIN_CONTENT_LENGTH:
                raise ValueError("PDF content too short after extraction.")
            return extracted, raw_content, ""
        except Exception as exc:
            last_error = _error_message(exc)
            logger.warning("PDF download failed for %s on attempt %s: %s", url, attempt, last_error)
            if attempt <= SCRAPE_MAX_RETRIES:
                await asyncio.sleep(min(2 ** (attempt - 1), 4))

    return "", b"", last_error


async def _scrape_with_scrapedo(url: str, client: httpx.AsyncClient) -> Tuple[str, str]:
    if not settings.SCRAPEDO_KEY.strip():
        return "", "SCRAPEDO_KEY is not configured."

    params = {
        "token": settings.SCRAPEDO_KEY,
        "url": url,
        "render": "true",
        "waitUntil": "domcontentloaded",
        "blockResources": "true",
    }
    last_error = "Unknown Scrape.do error"

    for attempt in range(1, SCRAPE_MAX_RETRIES + 2):
        try:
            response = await client.get(
                "https://api.scrape.do/",
                params=params,
                timeout=SCRAPE_TIMEOUT_SECONDS,
                follow_redirects=True,
            )
            response.raise_for_status()
            text = _extract_html_text(response.text)
            if len(_normalize_whitespace(text)) < MIN_CONTENT_LENGTH:
                raise ValueError("Scrape.do returned insufficient content.")
            return text, ""
        except Exception as exc:
            last_error = _error_message(exc)
            logger.warning("Scrape.do failed for %s on attempt %s: %s", url, attempt, last_error)
            if attempt <= SCRAPE_MAX_RETRIES:
                await asyncio.sleep(min(2 ** (attempt - 1), 4))

    return "", last_error


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
            if len(_normalize_whitespace(extracted)) >= MIN_CONTENT_LENGTH:
                return extracted
        except Exception as exc:
            errors.append(_error_message(exc))

    raise RuntimeError("; ".join(errors) or "Scrapling is unavailable.")


async def _scrape_with_scrapling(url: str) -> Tuple[str, str]:
    if Fetcher is None and DynamicFetcher is None and StealthyFetcher is None:
        return "", SCRAPLING_IMPORT_ERROR or "Scrapling is not installed."

    loop = asyncio.get_running_loop()
    try:
        # Scrapling is sync, so keep it off the event loop and cap the await with a hard timeout.
        content = await asyncio.wait_for(
            loop.run_in_executor(None, _scrape_with_scrapling_sync, url),
            timeout=SCRAPLING_TIMEOUT_SECONDS,
        )
        return content, ""
    except Exception as exc:
        error_message = _error_message(exc)
        logger.warning("Scrapling fallback failed for %s: %s", url, error_message)
        return "", error_message


def _artifact_counts(artifacts: List[Dict[str, Any]]) -> Dict[str, int]:
    return {
        "total_artifacts": len(artifacts),
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
        "location_score": 0,
        "location_matches": [],
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

    _log(f"[SCRAPER] Start: {url}")
    async with semaphore:
        try:
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

            scrapedo_text, scrapedo_error = await _scrape_with_scrapedo(url, client)
            if not scrapedo_text:
                scrapling_text, scrapling_error = await _scrape_with_scrapling(url)
                content = scrapling_text
                final_error = scrapling_error or scrapedo_error
            else:
                content = scrapedo_text
                final_error = ""

            normalized_content = _normalize_whitespace(content)
            if len(normalized_content) < MIN_CONTENT_LENGTH:
                raise RuntimeError(final_error or "Content too short after scraping.")

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
            _log(f"[SCRAPER] Success: {url}")
            return {
                "artifact_id": artifact_id,
                "artifact_type": "web",
                "source_type": source_type,
                "url": url,
                "title": title,
                "query": query,
                "domain": _extract_domain(url),
                "status": "success",
                "error": "",
                "binary_key": "",
                "text_key": text_key,
                "binary_path": "",
                "text_path": text_key,
                "text_available": True,
                "text_chars": len(content),
                "content_signature": _content_signature(content),
                "location_score": int(location_payload.get("location_score", 0)),
                "location_matches": list(location_payload.get("location_matches", [])),
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

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    timeout = httpx.Timeout(SCRAPE_TIMEOUT_SECONDS)
    limits = httpx.Limits(max_connections=MAX_CONCURRENT_REQUESTS, max_keepalive_connections=MAX_CONCURRENT_REQUESTS)

    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=timeout, limits=limits, follow_redirects=True) as client:
        tasks = [
            scrape_url(result, topic, section, resolved_location_context, session_id, client, semaphore, index)
            for index, result in enumerate(deduplicated_results, start=1)
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    artifacts: List[Dict[str, Any]] = []
    completed = 0
    total = len(deduplicated_results)

    for result, task_result in zip(deduplicated_results, raw_results):
        completed += 1
        _log(f"[PROGRESS] {completed}/{total}")
        if isinstance(task_result, Exception):
            logger.exception("Unhandled scrape task failure for %s", result.get("url", ""))
            artifacts.append(
                _empty_artifact(
                    artifact_id=f"src_{completed:02d}",
                    artifact_type="web",
                    source_type=str(result.get("source_type", "general")),
                    url=str(result.get("url", "")),
                    title=str(result.get("title", "")),
                    query=str(result.get("query", "")),
                    error=_error_message(task_result),
                )
            )
            continue
        artifacts.append(task_result)

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

    structured_pages: List[Dict[str, str]] = []
    for artifact in deduplicated_artifacts:
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
        if len(_normalize_whitespace(content)) < MIN_CONTENT_LENGTH:
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
            }
        )

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
) -> Dict[str, Any]:
    combined_results: List[Dict[str, Any]] = []
    for result in (search_results or []) + (pdf_results or []) + (web_results or []):
        if isinstance(result, dict):
            combined_results.append(dict(result))

    _log(f"[SCRAPER] Queue size: {len(combined_results[:TOTAL_URL_CAP])}")
    return await scrape_all(combined_results, topic, section, session_id, location_context=location_context)


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

        if len(_normalize_whitespace(text_content)) < MIN_CONTENT_LENGTH:
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
            }
        )

    return saved_sources

