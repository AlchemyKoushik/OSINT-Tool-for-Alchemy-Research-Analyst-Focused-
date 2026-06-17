import asyncio
import logging
import random
import re
import warnings
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote, urlparse

import httpx

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
MAX_RESULTS_PER_QUERY = 20
MAX_CONCURRENT_REQUESTS = 4
TOTAL_URL_CAP = 200
MIN_SNIPPET_LENGTH = 50
DDG_MAX_RESULTS_PER_QUERY = 30
SERPAPI_MAX_RESULTS_PER_QUERY = 20
CURRENT_YEAR = datetime.now(timezone.utc).year
YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9&/%+\-]{1,}")
QUOTED_PHRASE_PATTERN = re.compile(r'"([^"]+)"')
SEARCH_BACKENDS = ("auto", "html", "lite")
SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
HIGH_VALUE_DOMAINS = (".gov", ".edu", ".org")
CONSULTING_DOMAINS = ("mckinsey", "deloitte", "pwc", "kpmg", "bain", "bcg")
HIGH_VALUE_KEYWORDS = ("report", "analysis", "market", "outlook", "research", "forecast")
GOVERNMENT_KEYWORDS = ("government", "ministry", "department", "agency", "official", "public sector", "policy")
NEWS_KEYWORDS = ("news", "latest", "coverage", "journal", "press")
SPAM_MARKERS = ("spam", "clickbait", "coupon", "promo", "affiliate", "sponsored", "deal", "advertorial")
GENERIC_QUERY_TOKENS = {
    "about",
    "analysis",
    "best",
    "business",
    "companies",
    "company",
    "competitors",
    "coverage",
    "developments",
    "forecast",
    "forecasts",
    "insights",
    "key",
    "latest",
    "leaders",
    "leading",
    "major",
    "market",
    "markets",
    "news",
    "outlook",
    "overview",
    "player",
    "players",
    "profile",
    "profiles",
    "ranking",
    "rankings",
    "recent",
    "report",
    "reports",
    "research",
    "share",
    "top",
    "trend",
    "trends",
}
GENERIC_RESULT_TITLE_MARKERS = (
    "cookie policy",
    "privacy policy",
    "terms of service",
    "contact us",
    "sign in",
    "subscribe",
    "careers",
    "jobs",
)
RANKING_ONLY_WORKFLOWS = {"competitive_landscape", "company_profile", "company_research"}
COMPETITIVE_LANDSCAPE_DISCOVERY_WORKFLOWS = {"competitive_landscape", "competitive_landscape_discovery"}
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
BLOCKED_REFERENCE_DOMAINS = (
    "wikipedia.org",
    "wikimedia.org",
    "wikia.com",
    "fandom.com",
)
COMPETITOR_DISCOVERY_SIGNAL_WEIGHTS = {
    "company profile": 4,
    "company profiles": 4,
    "company website": 4,
    "official website": 4,
    "our company": 4,
    "about us": 3,
    "press release": 4,
    "announces": 4,
    "launches": 4,
    "expands": 4,
    "acquires": 4,
    "portfolio": 3,
    "regional companies": 3,
    "private companies": 3,
    "private company": 3,
    "startup": 3,
    "startups": 3,
    "challenger": 3,
    "emerging": 2,
    "niche": 2,
    "specialist": 2,
    "local companies": 2,
    "vendor ecosystem": 1,
    "association": 1,
    "conference": 1,
    "directory": 1,
    "event": 1,
    "exhibitor": 1,
    "member": 1,
    "membership": 1,
    "participant": 1,
    "vendor list": 1,
}
LOW_VALUE_COMPETITIVE_PAGE_MARKERS = (
    "login",
    "log in",
    "member login",
    "members only",
    "sign in",
    "subscribe",
    "subscription",
    "cookie policy",
    "privacy policy",
    "terms of service",
    "contact us",
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


def _is_blocked_reference_domain(domain: str) -> bool:
    return any(domain == blocked or domain.endswith(f".{blocked}") for blocked in BLOCKED_REFERENCE_DOMAINS)


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


def _normalize_query_variant(query: str) -> str:
    return re.sub(r"\s+", " ", str(query or "").strip())


def _normalized_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _tokenize_text(value: str) -> List[str]:
    return [match.group(0) for match in TOKEN_PATTERN.finditer(_normalized_text(value))]


def _extract_quoted_phrases(query: str) -> List[str]:
    phrases: List[str] = []
    seen = set()
    for match in QUOTED_PHRASE_PATTERN.findall(str(query or "")):
        normalized = _normalized_text(match)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        phrases.append(normalized)
    return phrases


def _extract_query_terms(query: str) -> Tuple[Set[str], Set[str]]:
    quoted_phrases = _extract_quoted_phrases(query)
    anchor_terms: Set[str] = set()
    for phrase in quoted_phrases:
        anchor_terms.update(token for token in _tokenize_text(phrase) if token not in GENERIC_QUERY_TOKENS)

    all_terms = {
        token
        for token in _tokenize_text(query)
        if token not in GENERIC_QUERY_TOKENS and not YEAR_PATTERN.fullmatch(token)
    }
    if anchor_terms:
        all_terms.update(anchor_terms)
    return all_terms, anchor_terms


def _uses_ranking_only_relevance(workflow: str | None) -> bool:
    return str(workflow or "").strip().lower() in RANKING_ONLY_WORKFLOWS


def _is_competitive_landscape_search_mode(workflow: str | None) -> bool:
    return str(workflow or "").strip().lower() in COMPETITIVE_LANDSCAPE_DISCOVERY_WORKFLOWS


def _search_concurrency_for_workflow(workflow: str | None) -> int:
    normalized_workflow = str(workflow or "").strip().lower()
    if normalized_workflow == "company_research":
        return 1
    if normalized_workflow == "competitive_landscape_discovery":
        return 1
    if normalized_workflow in {"competitive_landscape", "company_profile"}:
        return 2
    return MAX_CONCURRENT_REQUESTS


def _result_sort_key(item: Dict[str, Any], *, workflow: str | None = None) -> tuple[int, ...]:
    if _is_competitive_landscape_search_mode(workflow):
        return (
            int(item.get("competitor_discovery_signal_score", 0)),
            int(item.get("location_score", 0)),
            int(item.get("temporal_boost", 0)),
            int(item.get("query_overlap_count", 0)),
            int(item.get("anchor_overlap_count", 0)),
            int(item.get("rank_score", 0)),
            int(item.get("score", 0)),
        )
    if _uses_ranking_only_relevance(workflow):
        return (
            int(item.get("location_score", 0)),
            int(item.get("rank_score", 0)),
            int(item.get("temporal_boost", 0)),
            int(item.get("score", 0)),
        )
    return (
        int(item.get("query_relevance_score", 0)),
        int(item.get("domain_quality_score", 0)),
        int(item.get("location_score", 0)),
        int(item.get("rank_score", 0)),
        int(item.get("temporal_boost", 0)),
        int(item.get("score", 0)),
    )


def _build_query_variants(query: str) -> List[str]:
    variants: List[str] = []
    seen = set()

    for candidate in (
        query,
        re.sub(r"\b20\d{2}\b", " ", query),
    ):
        normalized = _normalize_query_variant(candidate)
        normalized_key = normalized.lower()
        if not normalized or normalized_key in seen:
            continue
        seen.add(normalized_key)
        variants.append(normalized)

    return variants


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


def _domain_quality_score(domain: str, source_type: str, combined: str) -> int:
    score = 0
    if any(domain.endswith(tld) for tld in HIGH_VALUE_DOMAINS):
        score += 3
    if any(consulting_domain in domain for consulting_domain in CONSULTING_DOMAINS):
        score += 3
    if any(keyword in combined or keyword in domain for keyword in GOVERNMENT_KEYWORDS):
        score += 2
    if any(keyword in combined or keyword in domain for keyword in NEWS_KEYWORDS):
        score += 1
    if source_type == "report":
        score += 2
    elif source_type == "news":
        score += 1
    elif source_type == "blog":
        score -= 2
    elif source_type == "low_value":
        score -= 4
    if any(marker in combined or marker in domain for marker in SPAM_MARKERS):
        score -= 3
    return score


def _competitor_discovery_signal_score(title: str, snippet: str, url: str) -> int:
    combined = f"{title} {snippet} {unquote(url)}".lower()
    score = 0
    for marker, weight in COMPETITOR_DISCOVERY_SIGNAL_WEIGHTS.items():
        if marker in combined:
            score += int(weight)
    return min(score, 12)


def _looks_like_low_value_competitive_page(title: str, snippet: str, url: str) -> bool:
    combined = f"{title} {snippet} {unquote(url)}".lower()
    return any(marker in combined for marker in LOW_VALUE_COMPETITIVE_PAGE_MARKERS)


def _score_query_relevance(
    *,
    query: str,
    title: str,
    snippet: str,
    url: str,
    source_type: str,
) -> Dict[str, Any]:
    query_terms, anchor_terms = _extract_query_terms(query)
    title_terms = set(_tokenize_text(title))
    snippet_terms = set(_tokenize_text(snippet))
    url_terms = set(_tokenize_text(unquote(url)))
    combined_terms = title_terms | snippet_terms | url_terms
    quoted_phrases = _extract_quoted_phrases(query)
    normalized_combined = _normalized_text(" ".join((title, snippet, url)))

    matched_terms = query_terms & combined_terms
    matched_anchor_terms = anchor_terms & combined_terms
    exact_phrase_match = any(phrase and phrase in normalized_combined for phrase in quoted_phrases)
    title_overlap = len(query_terms & title_terms)
    snippet_overlap = len(query_terms & snippet_terms)
    url_overlap = len(query_terms & url_terms)

    score = 0
    if exact_phrase_match:
        score += 8
    score += min(title_overlap, 4) * 2
    score += min(snippet_overlap, 4)
    score += min(url_overlap, 2)
    if matched_anchor_terms:
        score += min(len(matched_anchor_terms), 3) * 2
    if source_type in {"government", "report", "news"} and matched_terms:
        score += 1
    if not matched_terms:
        score -= 5
    elif title_overlap == 0 and snippet_overlap <= 1:
        score -= 2
    if anchor_terms and not matched_anchor_terms and not exact_phrase_match:
        score -= 4

    return {
        "query_terms": sorted(query_terms),
        "anchor_terms": sorted(anchor_terms),
        "matched_terms": sorted(matched_terms),
        "matched_anchor_terms": sorted(matched_anchor_terms),
        "query_overlap_count": len(matched_terms),
        "anchor_overlap_count": len(matched_anchor_terms),
        "title_overlap_count": title_overlap,
        "snippet_overlap_count": snippet_overlap,
        "url_overlap_count": url_overlap,
        "exact_query_phrase_match": exact_phrase_match,
        "query_relevance_score": score,
    }


def _score_result(
    result: Dict[str, Any],
    authority_boosts: Dict[str, int],
    freshness: str,
    query: str,
    *,
    workflow: str | None = None,
) -> Dict[str, Any]:
    url = str(result.get("url", "")).strip()
    title = str(result.get("title", "")).strip()
    snippet = str(result.get("snippet", "")).strip()
    domain = _extract_domain(url)
    source_type = _classify_source_type(url, title, snippet)
    temporal_boost, detected_years = _compute_temporal_boost(title, snippet, freshness)
    combined = f"{title} {snippet}".lower()
    relevance_payload = _score_query_relevance(
        query=query,
        title=title,
        snippet=snippet,
        url=url,
        source_type=source_type,
    )
    domain_quality = _domain_quality_score(domain, source_type, combined)

    score = 0
    if any(keyword in combined for keyword in HIGH_VALUE_KEYWORDS):
        score += 2
    score += int(authority_boosts.get(domain, 0))
    score += domain_quality
    rank_score = score + temporal_boost + int(relevance_payload["query_relevance_score"])
    competitor_discovery_signal = (
        _competitor_discovery_signal_score(title, snippet, url)
        if _is_competitive_landscape_search_mode(workflow)
        else 0
    )

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
        "domain_quality_score": domain_quality,
        "competitor_discovery_signal_score": competitor_discovery_signal,
        **relevance_payload,
    }


def _is_quality_result(
    result: Dict[str, Any],
    *,
    ranking_only_relevance: bool = False,
    workflow: str | None = None,
) -> bool:
    url = str(result.get("url", "")).strip()
    snippet = str(result.get("snippet", "")).strip()
    domain = str(result.get("domain", "")).strip() or _extract_domain(url)
    source_type = str(result.get("source_type", "")).strip()
    title = str(result.get("title", "")).strip().lower()
    query_overlap_count = int(result.get("query_overlap_count", 0))
    anchor_overlap_count = int(result.get("anchor_overlap_count", 0))
    exact_query_phrase_match = bool(result.get("exact_query_phrase_match"))
    query_relevance_score = int(result.get("query_relevance_score", 0))
    domain_quality_score = int(result.get("domain_quality_score", 0))
    discovery_signal_score = int(result.get("competitor_discovery_signal_score", 0))

    if not url or len(snippet) < MIN_SNIPPET_LENGTH:
        return False
    if _is_blocked_reference_domain(domain):
        return False
    if _is_social_or_low_value_domain(domain):
        return False
    if source_type == "low_value":
        return False
    if _is_competitive_landscape_search_mode(workflow):
        if _looks_like_low_value_competitive_page(title, snippet, url):
            return False
        if any(marker in title for marker in GENERIC_RESULT_TITLE_MARKERS) and discovery_signal_score == 0:
            return False
        if (
            query_overlap_count == 0
            and anchor_overlap_count == 0
            and not exact_query_phrase_match
            and discovery_signal_score == 0
            and source_type in {"blog", "general"}
            and domain_quality_score <= 0
        ):
            return False
        if query_relevance_score <= -8 and domain_quality_score <= 0 and discovery_signal_score == 0:
            return False
        return True
    if ranking_only_relevance:
        return True
    if any(marker in title for marker in GENERIC_RESULT_TITLE_MARKERS):
        return False
    if not exact_query_phrase_match and anchor_overlap_count == 0 and query_overlap_count == 0:
        return False
    if query_relevance_score <= -5 and domain_quality_score <= 0:
        return False
    if query_overlap_count <= 1 and source_type in {"blog", "general"} and domain_quality_score <= 0:
        return False
    return True


def _should_keep_result_for_workflow(result: Dict[str, Any], context: LocationContext, workflow: str | None = None) -> bool:
    if not _is_competitive_landscape_search_mode(workflow):
        return should_keep_search_result(result, context)
    if context.is_global:
        return True

    has_location_match = bool(result.get("has_location_match"))
    location_score = int(result.get("location_score", 0))
    generic_unrelated = bool(result.get("generic_unrelated"))
    domain_relevance = bool(result.get("domain_relevance"))
    discovery_signal_score = int(result.get("competitor_discovery_signal_score", 0))
    query_overlap_count = int(result.get("query_overlap_count", 0))
    domain_quality_score = int(result.get("domain_quality_score", 0))

    if generic_unrelated:
        return False
    if context.preference == "country_specific":
        return (
            has_location_match
            or domain_relevance
            or discovery_signal_score > 0
            or query_overlap_count > 0
            or domain_quality_score > 0
            or location_score >= 1
        )
    return has_location_match or domain_relevance or discovery_signal_score > 0 or location_score >= 0


def _max_results_per_query_for_workflow(workflow: str | None) -> int:
    return 30 if _is_competitive_landscape_search_mode(workflow) else MAX_RESULTS_PER_QUERY


def _total_url_cap_for_workflow(workflow: str | None) -> int:
    return 260 if _is_competitive_landscape_search_mode(workflow) else TOTAL_URL_CAP


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


def _serpapi_location(context: LocationContext) -> str:
    if context.is_global:
        return ""
    return str(context.value or context.label or "").strip()


def _run_serpapi_search_sync(
    query: str,
    max_results: int,
    location_context: LocationContext,
) -> List[Dict[str, Any]]:
    api_key = settings.SERPAPI_KEY.strip()
    if not api_key:
        return []

    params: Dict[str, Any] = {
        "engine": "google",
        "q": query,
        "api_key": api_key,
        "num": max(1, min(max_results, SERPAPI_MAX_RESULTS_PER_QUERY)),
        "hl": "en",
        "output": "json",
    }
    location = _serpapi_location(location_context)
    if location:
        params["location"] = location

    response = httpx.get(SERPAPI_ENDPOINT, params=params, timeout=SEARCH_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(str(payload.get("error")))

    normalized_results: List[Dict[str, Any]] = []
    effective_cap = max(1, min(max_results, SERPAPI_MAX_RESULTS_PER_QUERY))
    for result in list(payload.get("organic_results", []))[:effective_cap]:
        if not isinstance(result, dict):
            continue
        normalized_results.append(
            {
                "url": str(result.get("link") or result.get("url") or "").strip(),
                "title": str(result.get("title") or "").strip(),
                "snippet": str(result.get("snippet") or result.get("description") or "").strip(),
            }
        )
    return normalized_results


def _filter_backend_results(
    raw_results: List[Dict[str, Any]],
    *,
    normalized_query: str,
    authority_boosts: Dict[str, int],
    freshness_level: str,
    resolved_location_context: LocationContext,
    workflow: str | None = None,
) -> Dict[str, Any]:
    annotated_results: List[Dict[str, Any]] = []
    ranking_only_relevance = _uses_ranking_only_relevance(workflow)
    per_query_cap = _max_results_per_query_for_workflow(workflow)
    for result in raw_results:
        base_result = _score_result(
            _normalize_raw_result(result),
            authority_boosts,
            freshness_level,
            normalized_query,
            workflow=workflow,
        )
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

    filtered_results = [
        result
        for result in annotated_results
        if _is_quality_result(result, ranking_only_relevance=ranking_only_relevance, workflow=workflow)
    ]
    quality_filtered_count = len(filtered_results)
    location_filtered_results = [
        result for result in filtered_results if _should_keep_result_for_workflow(result, resolved_location_context, workflow)
    ]
    filtered_results = [
        result for result in filtered_results if _should_keep_result_for_workflow(result, resolved_location_context, workflow)
    ]
    filtered_results = _deduplicate_urls(filtered_results)
    filtered_results.sort(
        key=lambda item: _result_sort_key(item, workflow=workflow),
        reverse=True,
    )
    capped_results = filtered_results[:per_query_cap]
    return {
        "results": capped_results,
        "diagnostics": {
            "raw_results": len(raw_results),
            "quality_pass_results": quality_filtered_count,
            "location_pass_results": len(location_filtered_results),
            "deduplicated_results": len(filtered_results),
            "returned_results": len(capped_results),
            "filtered_results": max(0, len(raw_results) - len(capped_results)),
            "capped_out_results": max(0, len(filtered_results) - len(capped_results)),
        },
    }


def _run_ddg_search_resilient_sync(
    query: str,
    *,
    authority_boosts: Dict[str, int],
    freshness_level: str,
    resolved_location_context: LocationContext,
    workflow: str | None = None,
    max_results: int,
) -> List[Dict[str, Any]]:
    last_error: Exception | None = None

    for query_variant in _build_query_variants(query):
        for backend in SEARCH_BACKENDS:
            try:
                raw_results = _run_ddg_search_sync(
                    query_variant,
                    max_results,
                    None,
                    backend,
                )
                filtered_payload = _filter_backend_results(
                    raw_results,
                    normalized_query=query,
                    authority_boosts=authority_boosts,
                    freshness_level=freshness_level,
                    resolved_location_context=resolved_location_context,
                    workflow=workflow,
                )
                filtered_results = list(filtered_payload.get("results", []))
                logger.info(
                    "[SEARCH] Backend=%s variant=%s raw=%s filtered=%s | query=%s",
                    backend,
                    "exact" if query_variant == query else "relaxed",
                    len(raw_results),
                    len(filtered_results),
                    query,
                )
                if filtered_results:
                    filtered_payload.setdefault("diagnostics", {})
                    filtered_payload["diagnostics"].update(
                        {
                            "provider": f"ddg_{backend}",
                            "provider_requested_cap": max_results,
                            "provider_effective_cap": max(1, min(max_results, DDG_MAX_RESULTS_PER_QUERY)),
                            "provider_supported_cap": DDG_MAX_RESULTS_PER_QUERY,
                        }
                    )
                    return filtered_payload
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "[SEARCH] Backend failed backend=%s variant=%s | query=%s | error=%s",
                    backend,
                    "exact" if query_variant == query else "relaxed",
                    query,
                    _error_message(exc),
                )

    if last_error is not None:
        raise RuntimeError(f"All DDG backends failed or returned unusable results: {_error_message(last_error)}")
    raise RuntimeError("All DDG backends returned zero usable results.")


def _run_serpapi_search_resilient_sync(
    query: str,
    *,
    authority_boosts: Dict[str, int],
    freshness_level: str,
    resolved_location_context: LocationContext,
    workflow: str | None = None,
    max_results: int,
) -> List[Dict[str, Any]]:
    if not settings.SERPAPI_KEY.strip():
        return []

    last_error: Exception | None = None
    for query_variant in _build_query_variants(query):
        try:
            raw_results = _run_serpapi_search_sync(
                query_variant,
                max_results,
                resolved_location_context,
            )
            filtered_payload = _filter_backend_results(
                raw_results,
                normalized_query=query,
                authority_boosts=authority_boosts,
                freshness_level=freshness_level,
                resolved_location_context=resolved_location_context,
                workflow=workflow,
            )
            filtered_results = list(filtered_payload.get("results", []))
            logger.info(
                "[SEARCH] Backend=serpapi variant=%s raw=%s filtered=%s | query=%s",
                "exact" if query_variant == query else "relaxed",
                len(raw_results),
                len(filtered_results),
                query,
            )
            if filtered_results:
                filtered_payload.setdefault("diagnostics", {})
                filtered_payload["diagnostics"].update(
                    {
                        "provider": "serpapi",
                        "provider_requested_cap": max_results,
                        "provider_effective_cap": max(1, min(max_results, SERPAPI_MAX_RESULTS_PER_QUERY)),
                        "provider_supported_cap": SERPAPI_MAX_RESULTS_PER_QUERY,
                    }
                )
                return filtered_payload
        except Exception as exc:
            last_error = exc
            logger.warning(
                "[SEARCH] Backend failed backend=serpapi variant=%s | query=%s | error=%s",
                "exact" if query_variant == query else "relaxed",
                query,
                _error_message(exc),
            )

    if last_error is not None:
        raise RuntimeError(f"SerpAPI failed or returned unusable results: {_error_message(last_error)}")
    return []


async def get_search_results(
    query: str,
    freshness: str = "high",
    location_context: LocationContext | None = None,
    workflow: str | None = None,
) -> Dict[str, Any]:
    normalized_query = query.strip()
    freshness_level = _normalize_freshness(freshness)
    resolved_location_context = location_context or LocationContext()
    authority_boosts = get_domain_authority_boosts()
    max_results = _max_results_per_query_for_workflow(workflow)
    _log(f"[SEARCH] Query: {normalized_query}")
    if settings.SERPAPI_KEY.strip():
        serpapi_payload = await call_search(
            "serpapi_search",
            lambda: asyncio.to_thread(
                _run_serpapi_search_resilient_sync,
                normalized_query,
                authority_boosts=authority_boosts,
                freshness_level=freshness_level,
                resolved_location_context=resolved_location_context,
                workflow=workflow,
                max_results=max_results,
            ),
            fallback={"results": [], "diagnostics": {}},
            timeout=SEARCH_TIMEOUT_SECONDS,
            max_retries=SEARCH_MAX_RETRIES,
            context={"query": normalized_query, "location": resolved_location_context.label},
        )
        serpapi_results = list((serpapi_payload or {}).get("results", []))
        if serpapi_results:
            _log(f"[SEARCH] Results: {len(serpapi_results)} | provider=serpapi | query={normalized_query}")
            return {
                "results": serpapi_results,
                "diagnostics": dict((serpapi_payload or {}).get("diagnostics", {})),
            }
        logger.warning("[SEARCH] SerpAPI returned no usable results. Falling back to DDG backends. query=%s", normalized_query)

    filtered_payload = await call_search(
        "ddg_search",
        lambda: asyncio.to_thread(
            _run_ddg_search_resilient_sync,
            normalized_query,
            authority_boosts=authority_boosts,
            freshness_level=freshness_level,
            resolved_location_context=resolved_location_context,
            workflow=workflow,
            max_results=max_results,
        ),
        fallback={"results": [], "diagnostics": {}},
        timeout=SEARCH_TIMEOUT_SECONDS,
        max_retries=SEARCH_MAX_RETRIES,
        context={"query": normalized_query},
    )
    filtered_results = list((filtered_payload or {}).get("results", []))
    if not filtered_results:
        _log(f"[SEARCH] Failed: {normalized_query} | error=no results")
        return {
            "results": [],
            "diagnostics": dict((filtered_payload or {}).get("diagnostics", {})),
        }
    _log(f"[SEARCH] Results: {len(filtered_results)} | query={normalized_query}")
    return {
        "results": filtered_results,
        "diagnostics": dict((filtered_payload or {}).get("diagnostics", {})),
    }


async def search_queries(
    topic: str,
    queries: List[str],
    freshness: str = "high",
    location_context: LocationContext | None = None,
    workflow: str | None = None,
) -> Dict[str, Any]:
    resolved_location_context = location_context or LocationContext()
    ranking_only_relevance = _uses_ranking_only_relevance(workflow)
    deduplicated_queries: List[str] = []
    seen_queries = set()
    for query in queries:
        normalized_query = re.sub(r"\s+", " ", query.strip())
        if not normalized_query or normalized_query.lower() in seen_queries:
            continue
        seen_queries.add(normalized_query.lower())
        deduplicated_queries.append(normalized_query)

    effective_concurrency = _search_concurrency_for_workflow(workflow)
    semaphore = asyncio.Semaphore(effective_concurrency)

    async def _bounded_search(query: str, query_index: int) -> List[Dict[str, Any]]:
        async with semaphore:
            if effective_concurrency < MAX_CONCURRENT_REQUESTS:
                await asyncio.sleep(min(0.15 * query_index, 0.6) + random.uniform(0.0, 0.1))
            return await get_search_results(
                query,
                freshness=freshness,
                location_context=resolved_location_context,
                workflow=workflow,
            )

    tasks = [_bounded_search(query, index) for index, query in enumerate(deduplicated_queries)]
    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    aggregated_results: List[Dict[str, Any]] = []
    query_performance: Dict[str, Dict[str, float]] = {}
    search_diagnostics = {
        "raw_results": 0,
        "quality_pass_results": 0,
        "location_pass_results": 0,
        "deduplicated_results": 0,
        "returned_results": 0,
        "capped_out_results": 0,
        "provider_requested_cap": 0,
        "provider_effective_cap": 0,
        "provider_supported_cap": 0,
        "providers_used": [],
    }
    completed = 0
    total = len(deduplicated_queries)

    for query, payload in zip(deduplicated_queries, results_list):
        completed += 1
        _log(f"[PROGRESS] {completed}/{total}")
        if isinstance(payload, Exception):
            logger.exception("Search task failed for query %s", query)
            query_performance[query] = {"count": 0, "avg_score": 0.0}
            continue
        results = list((payload or {}).get("results", []))
        diagnostics = dict((payload or {}).get("diagnostics", {}))
        search_diagnostics["raw_results"] += int(diagnostics.get("raw_results", 0))
        search_diagnostics["quality_pass_results"] += int(diagnostics.get("quality_pass_results", 0))
        search_diagnostics["location_pass_results"] += int(diagnostics.get("location_pass_results", 0))
        search_diagnostics["deduplicated_results"] += int(diagnostics.get("deduplicated_results", 0))
        search_diagnostics["returned_results"] += int(diagnostics.get("returned_results", 0))
        search_diagnostics["capped_out_results"] += int(diagnostics.get("capped_out_results", 0))
        search_diagnostics["provider_requested_cap"] = max(
            int(search_diagnostics.get("provider_requested_cap", 0)),
            int(diagnostics.get("provider_requested_cap", 0)),
        )
        search_diagnostics["provider_effective_cap"] = max(
            int(search_diagnostics.get("provider_effective_cap", 0)),
            int(diagnostics.get("provider_effective_cap", 0)),
        )
        search_diagnostics["provider_supported_cap"] = max(
            int(search_diagnostics.get("provider_supported_cap", 0)),
            int(diagnostics.get("provider_supported_cap", 0)),
        )
        provider_name = str(diagnostics.get("provider", "")).strip()
        if provider_name and provider_name not in search_diagnostics["providers_used"]:
            search_diagnostics["providers_used"].append(provider_name)

        if ranking_only_relevance:
            query_scores = [
                float(result.get("rank_score", 0)) + float(result.get("location_score", 0))
                for result in results
            ]
        else:
            query_scores = [
                float(result.get("rank_score", 0))
                + float(result.get("location_score", 0))
                + float(result.get("query_relevance_score", 0))
                + float(result.get("domain_quality_score", 0))
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
        key=lambda item: _result_sort_key(item, workflow=workflow),
        reverse=True,
    )
    capped_results = deduplicated_results[: _total_url_cap_for_workflow(workflow)]
    _log(f"[SEARCH] Aggregated unique results: {len(capped_results)}")

    return {
        "queries": deduplicated_queries,
        "results": capped_results,
        "query_performance": query_performance,
        "diagnostics": {
            **search_diagnostics,
            "unique_results": len(deduplicated_results),
            "capped_results": len(capped_results),
            "filtered_results": max(0, search_diagnostics["raw_results"] - len(capped_results)),
            "search_mode": "competitive_landscape" if _is_competitive_landscape_search_mode(workflow) else "default",
        },
    }

