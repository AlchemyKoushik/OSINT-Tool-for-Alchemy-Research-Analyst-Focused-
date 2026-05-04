import asyncio
import logging
import re
import warnings
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

try:
    from ddgs import DDGS
except Exception:
    try:
        from duckduckgo_search import DDGS
    except Exception:
        DDGS = None  # type: ignore[assignment]
        logger = logging.getLogger(__name__)
        logger.warning("DDG Search client not installed")

from config.settings import settings
from services.external_client import call_search, call_search_sync
from services.memory_service import get_domain_authority_boosts, update_query_memory
from services.location_service import (
    LocationContext,
    assess_location_relevance,
    build_location_topic_key,
    should_keep_search_result,
)

logger = logging.getLogger(__name__)

DEBUG = True
SEARCH_TIMEOUT_SECONDS = settings.EXTERNAL_TIMEOUT_SECONDS
SEARCH_MAX_RETRIES = settings.EXTERNAL_MAX_RETRIES
MAX_RESULTS_PER_QUERY = 6
MAX_CONCURRENT_REQUESTS = 4
TOTAL_URL_CAP = 8
MIN_SNIPPET_LENGTH = 50
CURRENT_YEAR = datetime.now(timezone.utc).year
YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
HIGH_VALUE_DOMAINS = (".gov", ".edu", ".org")
CONSULTING_DOMAINS = ("mckinsey", "deloitte", "pwc", "kpmg", "bain", "bcg")
HIGH_VALUE_KEYWORDS = ("report", "analysis", "market", "outlook", "research", "forecast")
GOVERNMENT_KEYWORDS = ("government", "ministry", "department", "agency", "official", "public sector", "policy")
NEWS_KEYWORDS = ("news", "latest", "coverage", "journal", "press")
SPAM_MARKERS = ("spam", "clickbait", "coupon", "promo", "affiliate", "sponsored", "deal", "advertorial")
SOCIAL_DOMAINS = (
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "medium.com",
    "pinterest.com",
    "reddit.com",
    "tiktok.com",
    "x.com",
    "youtube.com",
)


def _log(message: str) -> None:
    logger.info("%s", message)


def _error_message(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__


def test_ddg() -> bool:
    if DDGS is None:
        logger.error("DDG Search FAILED: duckduckgo_search not installed")
        return False

    try:
        results = call_search_sync(
            "ddg_startup_test",
            lambda: _run_ddg_search_sync("test query", 2),
            fallback=[],
            timeout=SEARCH_TIMEOUT_SECONDS,
            max_retries=SEARCH_MAX_RETRIES,
            context={"query": "test query"},
        )
        if not results:
            raise RuntimeError("DDG startup test returned no results.")
        logger.info("DDG Search: SUCCESS")
        return True
    except Exception as exc:
        error_message = _error_message(exc)
        logger.error("DDG Search FAILED: %s", error_message)
        return False


def _normalize_freshness(freshness: str) -> str:
    return freshness if freshness in {"low", "high"} else "high"


def _extract_domain(url: str) -> str:
    parsed = urlparse(url.strip())
    domain = parsed.netloc.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def _is_social_or_low_value_domain(domain: str) -> bool:
    return any(domain == blocked or domain.endswith(f".{blocked}") for blocked in SOCIAL_DOMAINS)


def _normalize_raw_result(result: Dict[str, Any]) -> Dict[str, str]:
    return {
        "url": str(
            result.get("url")
            or result.get("href")
            or result.get("link")
            or result.get("source")
            or ""
        ).strip(),
        "title": str(
            result.get("title")
            or result.get("headline")
            or result.get("name")
            or ""
        ).strip(),
        "snippet": str(
            result.get("snippet")
            or result.get("body")
            or result.get("description")
            or result.get("text")
            or ""
        ).strip(),
    }


def _extract_years(text: str) -> List[int]:
    years = {int(match) for match in YEAR_PATTERN.findall(text)}
    return sorted(year for year in years if 2000 <= year <= CURRENT_YEAR + 1)


def _compute_temporal_boost(title: str, snippet: str, freshness: str) -> Tuple[int, List[int]]:
    combined_text = f"{title} {snippet}"
    years = _extract_years(combined_text)
    if not years:
        return 0, []

    newest_year = max(years)
    if freshness == "high":
        if newest_year >= CURRENT_YEAR - 1:
            return 3, years
        if newest_year >= CURRENT_YEAR - 3:
            return 2, years
        return 1, years

    if newest_year >= CURRENT_YEAR - 1:
        return 1, years
    return 0, years


def _classify_source_type(url: str, title: str, snippet: str) -> str:
    domain = _extract_domain(url)
    combined = f"{title} {snippet}".lower()

    if _is_social_or_low_value_domain(domain):
        return "low_value"
    if any(domain.endswith(tld) for tld in HIGH_VALUE_DOMAINS) or any(keyword in combined or keyword in domain for keyword in GOVERNMENT_KEYWORDS):
        return "government"
    if any(consulting_domain in domain for consulting_domain in CONSULTING_DOMAINS):
        return "report"
    if any(keyword in combined for keyword in HIGH_VALUE_KEYWORDS):
        return "report"
    if any(keyword in combined or keyword in domain for keyword in NEWS_KEYWORDS):
        return "news"
    if "blog" in combined or "blog" in domain:
        return "blog"
    return "general"


def _score_result(result: Dict[str, Any], authority_boosts: Dict[str, int], freshness: str) -> Dict[str, Any]:
    url = str(result.get("url", "")).strip()
    title = str(result.get("title", "")).strip()
    snippet = str(result.get("snippet", "")).strip()
    domain = _extract_domain(url)
    source_type = _classify_source_type(url, title, snippet)
    temporal_boost, detected_years = _compute_temporal_boost(title, snippet, freshness)
    combined = f"{title} {snippet}".lower()

    score = 0
    if any(domain.endswith(tld) for tld in HIGH_VALUE_DOMAINS):
        score += 3
    if any(consulting_domain in domain for consulting_domain in CONSULTING_DOMAINS):
        score += 3
    if any(keyword in combined or keyword in domain for keyword in GOVERNMENT_KEYWORDS):
        score += 2
    if any(keyword in combined for keyword in HIGH_VALUE_KEYWORDS):
        score += 2
    if any(keyword in combined or keyword in domain for keyword in NEWS_KEYWORDS):
        score += 1
    if source_type == "blog":
        score -= 1
    if source_type == "low_value":
        score -= 4
    if any(marker in combined or marker in url or marker in domain for marker in SPAM_MARKERS):
        score -= 3
    score += int(authority_boosts.get(domain, 0))
    rank_score = score + temporal_boost

    return {
        "url": url,
        "title": title,
        "snippet": snippet,
        "domain": domain,
        "source_type": source_type,
        "score": score,
        "rank_score": rank_score,
        "temporal_boost": temporal_boost,
        "detected_years": detected_years,
    }


def _is_quality_result(result: Dict[str, Any]) -> bool:
    url = str(result.get("url", "")).strip()
    snippet = str(result.get("snippet", "")).strip()
    domain = str(result.get("domain", "")).strip() or _extract_domain(url)
    source_type = str(result.get("source_type", "")).strip()

    if not url or len(snippet) < MIN_SNIPPET_LENGTH:
        return False
    if _is_social_or_low_value_domain(domain):
        return False
    if source_type == "low_value":
        return False
    return True


def _deduplicate_urls(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    unique_results: List[Dict[str, Any]] = []
    seen_urls = set()

    for result in results:
        url = str(result.get("url", "")).strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        unique_results.append(result)

    return unique_results


def _run_ddg_search_sync(
    query: str,
    max_results: int,
    timelimit: str | None = None,
    backend: str = "auto",
) -> List[Dict[str, Any]]:
    if DDGS is None:
        raise RuntimeError("DDG Search client not installed")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        with DDGS() as ddgs:
            kwargs: Dict[str, Any] = {"max_results": max_results, "backend": backend}
            if timelimit:
                kwargs["timelimit"] = timelimit
            return list(ddgs.text(query, **kwargs))


async def get_search_results(
    query: str,
    freshness: str = "high",
    location_context: LocationContext | None = None,
) -> List[Dict[str, Any]]:
    normalized_query = query.strip()
    freshness_level = _normalize_freshness(freshness)
    resolved_location_context = location_context or LocationContext()
    authority_boosts = get_domain_authority_boosts()
    _log(f"[SEARCH] Query: {normalized_query}")
    raw_results = await call_search(
        "ddg_search",
        lambda: asyncio.to_thread(
            _run_ddg_search_sync,
            normalized_query,
            MAX_RESULTS_PER_QUERY,
            None,
            "auto",
        ),
        fallback=[],
        timeout=SEARCH_TIMEOUT_SECONDS,
        max_retries=SEARCH_MAX_RETRIES,
        context={"query": normalized_query},
    )
    if not raw_results:
        _log(f"[SEARCH] Failed: {normalized_query} | error=no results")
        return []

    annotated_results: List[Dict[str, Any]] = []
    for result in raw_results:
        base_result = _score_result(_normalize_raw_result(result), authority_boosts, freshness_level)
        location_payload = assess_location_relevance(
            url=str(base_result.get("url", "")),
            title=str(base_result.get("title", "")),
            text=str(base_result.get("snippet", "")),
            context=resolved_location_context,
        )
        annotated_results.append(
            {
                **base_result,
                **location_payload,
                "query": normalized_query,
                "location_label": resolved_location_context.label,
            }
        )

    filtered_results = [result for result in annotated_results if _is_quality_result(result)]
    filtered_results = [result for result in filtered_results if should_keep_search_result(result, resolved_location_context)]
    filtered_results = _deduplicate_urls(filtered_results)
    filtered_results.sort(
        key=lambda item: (
            int(item.get("location_score", 0)),
            int(item.get("rank_score", 0)),
            int(item.get("temporal_boost", 0)),
            int(item.get("score", 0)),
        ),
        reverse=True,
    )
    limited_results = filtered_results[:MAX_RESULTS_PER_QUERY]
    _log(f"[SEARCH] Results: {len(limited_results)} | query={normalized_query}")
    return limited_results


async def search_queries(
    topic: str,
    queries: List[str],
    freshness: str = "high",
    location_context: LocationContext | None = None,
) -> Dict[str, Any]:
    resolved_location_context = location_context or LocationContext()
    deduplicated_queries: List[str] = []
    seen_queries = set()
    for query in queries:
        normalized_query = re.sub(r"\s+", " ", query.strip())
        if not normalized_query or normalized_query.lower() in seen_queries:
            continue
        seen_queries.add(normalized_query.lower())
        deduplicated_queries.append(normalized_query)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def _bounded_search(query: str) -> List[Dict[str, Any]]:
        async with semaphore:
            return await get_search_results(
                query,
                freshness=freshness,
                location_context=resolved_location_context,
            )

    tasks = [_bounded_search(query) for query in deduplicated_queries]
    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    aggregated_results: List[Dict[str, Any]] = []
    query_performance: Dict[str, Dict[str, float]] = {}
    completed = 0
    total = len(deduplicated_queries)

    for query, results in zip(deduplicated_queries, results_list):
        completed += 1
        _log(f"[PROGRESS] {completed}/{total}")
        if isinstance(results, Exception):
            logger.exception("Search task failed for query %s", query)
            query_performance[query] = {"count": 0, "avg_score": 0.0}
            continue

        query_scores = [
            float(result.get("rank_score", 0)) + float(result.get("location_score", 0))
            for result in results
        ]
        query_performance[query] = {
            "count": len(results),
            "avg_score": round(sum(query_scores) / len(query_scores), 2) if query_scores else 0.0,
        }
        aggregated_results.extend(results)

    update_query_memory(build_location_topic_key(topic, resolved_location_context), query_performance)

    deduplicated_results = _deduplicate_urls(aggregated_results)
    deduplicated_results.sort(
        key=lambda item: (
            int(item.get("location_score", 0)),
            int(item.get("rank_score", 0)),
            int(item.get("temporal_boost", 0)),
            int(item.get("score", 0)),
        ),
        reverse=True,
    )
    capped_results = deduplicated_results[:TOTAL_URL_CAP]
    _log(f"[SEARCH] Aggregated unique results: {len(capped_results)}")

    return {
        "queries": deduplicated_queries,
        "results": capped_results,
        "query_performance": query_performance,
    }

