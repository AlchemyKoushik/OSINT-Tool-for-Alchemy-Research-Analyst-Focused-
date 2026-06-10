from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Sequence

from openai import AsyncOpenAI

from config.settings import settings
from models.response_models import (
    CompetitiveLandscapeProfileResponse,
    ExampleExtractionResponse,
    ExampleSearchQueryResponse,
    ExtractedExample,
)
from services.content_processor import prepare_processed_content
from services.example_validation_service import attach_examples_to_insights
from services.external_client import call_openai
from services.location_service import LocationContext
from services.openai_service import can_use_openai, ensure_min_output_tokens, extract_validated_examples_from_evidence
from services.prompt_builder import (
    build_company_profile_extraction_payload,
    build_example_search_query_system_prompt,
    build_example_search_query_user_prompt,
    build_recent_company_developments_payload,
    build_trend_example_extraction_payload,
)
from services.scraper_service import collect_research_artifacts, load_saved_sources
from services.search_service import search_queries
from services.source_attribution_service import attach_sources_to_items

logger = logging.getLogger(__name__)

MAX_EXAMPLE_RESEARCH_QUERIES = 8
MAX_EXAMPLE_RESULTS = 24
MAX_TRENDS_WITH_EXAMPLE_RESEARCH = settings.MAX_TRENDS_WITH_EXAMPLE_RESEARCH
MAX_EXAMPLES_PER_TREND = 5
MAX_CONCURRENT_TREND_RESEARCH = 2
EXAMPLE_QUERY_MODEL_NAME = settings.OPENAI_QUERY_MODEL or settings.OPENAI_SUPPORT_MODEL or "gpt-4.1-mini"
EXAMPLE_QUERY_TIMEOUT_SECONDS = 30
EXAMPLE_QUERY_MAX_RETRIES = 1
COMPANY_PROFILE_MODEL_NAME = settings.OPENAI_ANALYSIS_MODEL or "gpt-5.5"
COMPANY_PROFILE_TIMEOUT_SECONDS = 45
COMPANY_PROFILE_MAX_RETRIES = 1
COMPANY_PROFILE_MAX_CHARS_PER_SOURCE = 2800
COMPANY_PROFILE_MAX_SOURCES = 8
COMPANY_PROFILE_MIN_LENIENT_CHARS = 120
STOPWORDS = {
    "about",
    "across",
    "after",
    "among",
    "because",
    "industry",
    "market",
    "their",
    "these",
    "this",
    "through",
    "trend",
    "trends",
    "driver",
    "drivers",
    "with",
}
TIER_1_DOMAIN_MARKERS = (".gov", ".sec", "investor", "regulator", "exchange", "official")
TIER_2_DOMAIN_MARKERS = ("reuters", "bloomberg", "spglobal", "argus", "woodmac", "mckinsey", "bnef")
TIER_3_TITLE_MARKERS = ("blog", "top 10", "list of", "overview", "market size")
LOW_VALUE_SOURCE_DOMAIN_MARKERS = ("zoominfo", "apollo", "clutch", "goodfirms", "tracxn", "6sense", "cylex", "yelp")
LOW_VALUE_SOURCE_TITLE_MARKERS = (
    "top ",
    "top-",
    "list of",
    "directory",
    "contact",
    "suppliers in",
    "vendors in",
    "company directory",
    "lead generation",
)
PREFERRED_SOURCE_TYPE_MARKERS = (
    "company",
    "investor",
    "government",
    "regulator",
    "exchange",
    "project_database",
    "industry_publication",
    "news",
    "report",
)
GENERIC_COMPANY_FACT_MARKERS = (
    "leading player",
    "strong presence",
    "recognised company",
    "recognized company",
    "major company",
    "market leader",
    "well positioned",
    "established player",
)
FACT_METRIC_MARKERS = (
    "mw",
    "gw",
    "mwh",
    "gwh",
    "kw",
    "pipeline",
    "portfolio",
    "ppa",
    "customers",
    "customer base",
    "subscribers",
    "user base",
    "users",
    "arr",
    "aum",
    "assets under management",
    "projects",
    "project",
    "plants",
    "sites",
    "assets",
    "coverage",
    "spectrum",
    "contracts",
    "installations",
    "capacity",
    "storage",
    "footprint",
    "markets",
    "states",
    "countries",
)
COMPANY_LEVEL_METRIC_MARKERS = (
    "mw",
    "gw",
    "kw",
    "pipeline",
    "portfolio",
    "aum",
    "assets under management",
    "revenue",
    "customers",
    "customer base",
    "subscribers",
    "user base",
    "users",
    "projects",
    "assets",
    "contracts",
    "capacity",
    "footprint",
    "markets",
    "countries",
    "regions",
    "operating assets",
    "contracted capacity",
)
PROJECT_LEVEL_CONSTRUCTION_MARKERS = (
    "began construction",
    "under construction",
    "expected to complete",
    "due by",
    "construction started",
    "started construction",
    "scheduled to complete",
    "planned to complete",
)
EQUIPMENT_LEVEL_MARKERS = ("panels", "panel", "modules", "module", "turbines", "turbine", "inverters", "inverter")
SINGLE_ASSET_OUTPUT_MARKERS = ("gwh per year", "annual generation", "generate per year", "generation output", "mwh per year")
OWNERSHIP_FACT_MARKERS = (
    "part of",
    "owned by",
    "subsidiary of",
    "backed by",
    "parent company",
    "strategic shareholder",
    "majority-owned",
    "joint venture",
)
GEOGRAPHIC_FOOTPRINT_MARKERS = (
    "across",
    "footprint",
    "presence in",
    "operates in",
    "active in",
    "markets",
    "countries",
    "regions",
    "regional",
    "global",
)
BUSINESS_MODEL_FACT_MARKERS = (
    "ppa",
    "ppas",
    "regulated contract",
    "regulated contracts",
    "merchant exposure",
    "merchant market",
    "epc",
    "developer",
    "development",
    "ownership",
    "o&m",
    "operation and maintenance",
    "asset mix",
    "technology mix",
    "hybrid",
    "storage",
    "offtake",
)
MARKET_POSITION_FACT_MARKERS = (
    "ranked",
    "largest",
    "top ",
    "top-",
    "market share",
    "market position",
    "leading",
    "major role",
)
CURRENT_STATE_FACT_MARKERS = (
    "operates",
    "maintains",
    "owns",
    "includes",
    "supplies",
    "serves",
    "has ",
    "is part of",
)
STRATEGIC_EVENT_MARKERS = (
    "announced",
    "launched",
    "commissioned",
    "expanded",
    "signed",
    "entered",
    "partnered",
    "acquired",
    "invested",
    "secured",
    "won",
    "awarded",
    "approved",
    "deployed",
    "started construction",
    "began construction",
    "completed",
    "unveiled",
    "closed financing",
    "raised",
    "opened",
    "introduced",
)
STATIC_DEVELOPMENT_MARKERS = (
    "headquartered",
    "founded",
    "was founded",
    "is based in",
    "operates ",
    "has capacity",
    "installed capacity",
    "portfolio includes",
    "presence across",
)
GENERIC_POSITIONING_MARKERS = (
    "leading position",
    "strong position",
    "important player",
    "major player",
    "recognized player",
    "recognised player",
    "holds a leading position",
)
GENERIC_COMPANY_OVERVIEW_MARKERS = (
    "market generated a revenue",
    "projected to reach",
    "compound annual growth rate",
    "forecast period",
    "market size",
    "report examines",
)
STALE_FORECAST_PATTERNS = (
    re.compile(r"\bproject(?:ed|ion)?\b[^.]*\bby\s+(20\d{2})\b", re.IGNORECASE),
    re.compile(r"\bexpect(?:ed|s)?\b[^.]*\bby\s+(20\d{2})\b", re.IGNORECASE),
    re.compile(r"\bforecast(?:ed)?\b[^.]*\bby\s+(20\d{2})\b", re.IGNORECASE),
)
INVALID_COMPANY_TITLE_MARKERS = (
    "market",
    "markets",
    "forecast",
    "industry",
    "executive summary",
    "generated revenue",
    "projected reach",
    "billion",
    "million",
)
EMERGING_TREND_MARKERS = (
    "emerging",
    "emerges",
    "niche",
    "pilot",
    "prototype",
    "r&d",
    "research",
    "demonstration",
    "feasibility",
    "commercialisation",
    "commercialization",
    "space-based",
    "advanced technology",
)
SBSP_SYNONYMS = (
    "space-based solar power",
    "space based solar power",
    "sbsp",
    "space solar power",
    "space-based solar",
    "solar power satellite",
    "orbital solar",
    "space-based power",
    "power beaming",
    "wireless power transmission",
    "microwave power transmission",
)


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _tokenize(value: str) -> List[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9][a-z0-9&/%-]{2,}", _normalize_text(value).lower())
        if token not in STOPWORDS
    ]


def _research_date_context() -> tuple[int, int, int]:
    current_year = datetime.now(timezone.utc).year
    return current_year, current_year - 1, current_year - 2


def _source_tier_for_source(source: Dict[str, Any]) -> str:
    domain = _normalize_text(source.get("domain") or source.get("url")).lower()
    title = _normalize_text(source.get("title")).lower()
    source_type = _normalize_text(source.get("source_type") or source.get("artifact_type")).lower()
    if any(marker in domain for marker in TIER_1_DOMAIN_MARKERS) or source_type in {"government", "report"}:
        return "Tier 1"
    if any(marker in domain for marker in TIER_2_DOMAIN_MARKERS) or source_type in {"news", "general"}:
        return "Tier 2"
    if any(marker in title for marker in TIER_3_TITLE_MARKERS) or source_type in {"blog", "low_value"}:
        return "Tier 3"
    return "Tier 2"


def _extract_year(value: Any) -> int | None:
    match = re.search(r"(20\d{2})", _normalize_text(value))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _is_recent_profile_date(value: Any) -> bool:
    year = _extract_year(value)
    if year is None:
        return False
    current_year, previous_year, two_years_ago = _research_date_context()
    return year in {current_year, previous_year, two_years_ago}


def _contains_stale_forecast_language(value: Any) -> bool:
    normalized = _normalize_text(value)
    if not normalized:
        return False
    current_year = _research_date_context()[0]
    for pattern in STALE_FORECAST_PATTERNS:
        for match in pattern.finditer(normalized):
            try:
                target_year = int(match.group(1))
            except (TypeError, ValueError, IndexError):
                continue
            if target_year <= current_year:
                return True
    return False


def _contains_any_marker(value: str, markers: Sequence[str]) -> bool:
    normalized = _normalize_text(value).lower()
    return any(marker in normalized for marker in markers)


def _count_fact_sentences(value: str) -> int:
    normalized = _normalize_text(value)
    if not normalized:
        return 0
    return len([segment for segment in re.split(r"(?<=[.!?])\s+", normalized) if segment.strip()])


def _looks_like_project_only_fact(value: str) -> bool:
    normalized = _normalize_text(value).lower()
    if not normalized:
        return False
    if _contains_any_marker(normalized, PROJECT_LEVEL_CONSTRUCTION_MARKERS):
        return True
    if _contains_any_marker(normalized, EQUIPMENT_LEVEL_MARKERS):
        return True
    if _contains_any_marker(normalized, SINGLE_ASSET_OUTPUT_MARKERS):
        return True
    return False


def _has_company_level_metric_fact(value: str) -> bool:
    normalized = _normalize_text(value).lower()
    return bool(re.search(r"\d", normalized)) and _contains_any_marker(normalized, COMPANY_LEVEL_METRIC_MARKERS)


def _has_ownership_fact(value: str) -> bool:
    return _contains_any_marker(value, OWNERSHIP_FACT_MARKERS)


def _has_geographic_footprint_fact(value: str) -> bool:
    normalized = _normalize_text(value).lower()
    if not _contains_any_marker(normalized, GEOGRAPHIC_FOOTPRINT_MARKERS):
        return False
    return bool(re.search(r"\b(?:countries|markets|regions|states)\b", normalized)) or " across " in f" {normalized} "


def _has_business_model_fact(value: str) -> bool:
    return _contains_any_marker(value, BUSINESS_MODEL_FACT_MARKERS)


def _has_market_position_fact(value: str) -> bool:
    normalized = _normalize_text(value).lower()
    if not _contains_any_marker(normalized, MARKET_POSITION_FACT_MARKERS):
        return False
    return bool(re.search(r"\b(?:no\.?\s*\d+|top\s+\d+|largest|ranked|market share)\b", normalized)) or _has_company_level_metric_fact(normalized)


def _is_isolated_investment_fact(value: str) -> bool:
    normalized = _normalize_text(value).lower()
    has_money = bool(re.search(r"(?:[$€£]\s?\d|\b\d+(?:\.\d+)?\s?(?:m|bn|million|billion)\b)", normalized))
    if not has_money:
        return False
    return not any(
        checker(normalized)
        for checker in (
            _has_company_level_metric_fact,
            _has_ownership_fact,
            _has_geographic_footprint_fact,
            _has_business_model_fact,
            _has_market_position_fact,
        )
    )


def _fact_repeats_overview(fact: str, business_overview: str) -> bool:
    normalized_fact = _normalize_text(fact).lower().strip(".")
    normalized_overview = _normalize_text(business_overview).lower()
    if not normalized_fact or not normalized_overview:
        return False
    if normalized_fact in normalized_overview:
        return True
    fact_tokens = set(_tokenize(normalized_fact))
    overview_tokens = set(_tokenize(normalized_overview))
    if not fact_tokens or not overview_tokens:
        return False
    overlap = len(fact_tokens & overview_tokens) / max(1, len(fact_tokens))
    return overlap >= 0.8


def _classify_company_profile_evidence_scope(source: Dict[str, Any]) -> str:
    combined = " ".join(
        [
            _normalize_text(source.get("title")),
            _normalize_text(source.get("snippet")),
            _normalize_text(source.get("summary")),
            _normalize_text(source.get("description")),
            _normalize_text(source.get("content"))[:1200],
        ]
    ).lower()
    if _contains_any_marker(combined, PROJECT_LEVEL_CONSTRUCTION_MARKERS) or _contains_any_marker(combined, EQUIPMENT_LEVEL_MARKERS):
        return "project_level_evidence"
    if _contains_any_marker(combined, STRATEGIC_EVENT_MARKERS):
        return "recent_developments"
    return "company_level_evidence"


def _is_company_specific_source(company_name: str, source: Dict[str, Any]) -> bool:
    company_key = _normalize_text(company_name).lower()
    combined = " ".join(
        [
            _normalize_text(source.get("title")),
            _normalize_text(source.get("snippet")),
            _normalize_text(source.get("summary")),
            _normalize_text(source.get("description")),
            _normalize_text(source.get("content"))[:1200],
        ]
    ).lower()
    if company_key and company_key in combined:
        return True
    company_tokens = [token for token in re.findall(r"[a-z0-9&.-]{3,}", company_key) if token not in STOPWORDS]
    matched_tokens = [token for token in company_tokens if token in combined]
    return len(matched_tokens) >= min(2, len(company_tokens)) if company_tokens else False


def _is_low_value_company_source(source: Dict[str, Any]) -> bool:
    domain = _normalize_text(source.get("domain") or source.get("url")).lower()
    title = _normalize_text(source.get("title")).lower()
    return any(marker in domain for marker in LOW_VALUE_SOURCE_DOMAIN_MARKERS) or any(
        marker in title for marker in LOW_VALUE_SOURCE_TITLE_MARKERS
    )


def _company_profile_source_quality_score(source: Dict[str, Any], company_name: str) -> int:
    score = 0
    source_tier = _source_tier_for_source(source)
    source_type = _normalize_text(source.get("source_type") or source.get("artifact_type")).lower()
    evidence_scope = _classify_company_profile_evidence_scope(source)
    if source_tier == "Tier 1":
        score += 8
    elif source_tier == "Tier 2":
        score += 5
    else:
        score += 1
    if source_type in PREFERRED_SOURCE_TYPE_MARKERS:
        score += 4
    if _is_company_specific_source(company_name, source):
        score += 5
    if _is_recent_profile_date(source.get("published_date") or source.get("date") or source.get("year")):
        score += 2
    if source_type == "news":
        score -= 2
    if evidence_scope == "project_level_evidence":
        score -= 4
    if _is_low_value_company_source(source):
        score -= 8
    if not _normalize_text(source.get("content")) and not _normalize_text(source.get("snippet")):
        score -= 2
    return score


def _prioritize_company_profile_sources(
    stored_sources: Sequence[Dict[str, Any]],
    *,
    company_name: str,
) -> List[Dict[str, Any]]:
    prioritized = sorted(
        [dict(source) for source in stored_sources],
        key=lambda source: (
            _company_profile_source_quality_score(source, company_name),
            len(_normalize_text(source.get("content"))),
        ),
        reverse=True,
    )
    strong_sources = [
        source for source in prioritized if _company_profile_source_quality_score(source, company_name) >= 3
    ]
    if len(strong_sources) >= 2:
        return strong_sources
    return prioritized


def _build_focus_terms(trend_heading: str, trend_body: str) -> str:
    trend_terms = _tokenize(trend_heading)[:5]
    body_terms = _tokenize(trend_body)[:8]
    return " ".join(dict.fromkeys(trend_terms + body_terms + _synonym_terms(trend_heading, trend_body)))


def _synonym_terms(*values: str) -> List[str]:
    combined = " ".join(_normalize_text(value).lower() for value in values)
    if any(term in combined for term in SBSP_SYNONYMS):
        return list(dict.fromkeys(SBSP_SYNONYMS))
    return []


def _contains_emerging_terms(heading: str, body: str) -> bool:
    combined = f"{_normalize_text(heading)} {_normalize_text(body)}".lower()
    return any(marker in combined for marker in EMERGING_TREND_MARKERS) or any(term in combined for term in SBSP_SYNONYMS)


def _dedupe_queries(queries: Sequence[str]) -> List[str]:
    deduped: List[str] = []
    seen = set()
    for query in queries:
        normalized = _normalize_text(query)
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _build_fallback_queries(
    *,
    topic: str,
    section: str,
    trend_heading: str,
    trend_body: str,
    location_context: LocationContext,
    fallback_mode: bool = False,
) -> List[str]:
    current_year, previous_year, two_years_ago = _research_date_context()
    geo = location_context.value if not location_context.is_global else ""
    focus_terms = _build_focus_terms(trend_heading, trend_body)
    year_scope = f"{current_year} OR {previous_year}"
    extended_year_scope = f"{current_year} OR {previous_year} OR {two_years_ago}"

    if section == "competitive_landscape":
        company_name = trend_heading.strip()
        templates = [
            '"{company_name}" {geo}',
            '"{company_name}" company overview products services',
            '"{company_name}" investor relations annual report',
            '"{company_name}" {geo} company overview',
            '"{company_name}" "{topic}" {geo} projects assets portfolio',
            '"{company_name}" "{topic}" {geo} customers contracts ppa',
            '"{company_name}" "{topic}" {geo} operations capacity pipeline',
            '"{company_name}" "{topic}" {geo} press release investor presentation',
        ]
        return _dedupe_queries(
            [
                template.format(
                    company_name=company_name,
                    topic=topic,
                    geo=geo,
                )
                for template in templates
            ]
        )[:MAX_EXAMPLE_RESEARCH_QUERIES]

    if fallback_mode:
        templates = [
            '{geo} {topic} {focus_terms} company announcement {current_year}',
            '{geo} {topic} {focus_terms} press release {current_year}',
            '{geo} {topic} {focus_terms} project deployment {year_scope}',
            '{geo} {topic} {focus_terms} partnership investment {year_scope}',
            '{geo} {topic} {focus_terms} case study company {year_scope}',
        ]
    else:
        templates = [
            '"{trend_heading}" "{geo}" "{topic}" announcement {current_year}',
            '"{topic}" "{geo}" "{focus_terms}" company announcement {current_year}',
            '"{topic}" "{geo}" "{focus_terms}" press release {year_scope}',
            '"{topic}" "{geo}" "{focus_terms}" partnership launch deployment {current_year}',
            '"{topic}" "{geo}" "{focus_terms}" investment expansion capacity {current_year}',
            '"{topic}" "{geo}" "{focus_terms}" project commercial operation {current_year}',
            '"{topic}" "{geo}" "{focus_terms}" acquisition funding agreement {current_year}',
            '"{topic}" "{geo}" "{focus_terms}" regulator government approval policy {extended_year_scope}',
        ]

    return _dedupe_queries(
        [
            template.format(
                trend_heading=trend_heading,
                geo=geo,
                topic=topic,
                focus_terms=focus_terms,
                current_year=current_year,
                year_scope=year_scope,
                extended_year_scope=extended_year_scope,
            )
            for template in templates
        ]
    )[:MAX_EXAMPLE_RESEARCH_QUERIES]


def _extract_parsed_query_output(response: Any) -> ExampleSearchQueryResponse:
    for output in getattr(response, "output", []):
        if getattr(output, "type", "") != "message":
            continue
        for item in getattr(output, "content", []):
            if getattr(item, "type", "") == "refusal":
                raise RuntimeError(str(getattr(item, "refusal", "Example search query generation was refused.")))
            parsed = getattr(item, "parsed", None)
            if isinstance(parsed, ExampleSearchQueryResponse):
                return parsed
    raise ValueError("Structured example search query response did not contain parsed content.")


def _extract_parsed_company_profile_output(response: Any) -> CompetitiveLandscapeProfileResponse:
    for output in getattr(response, "output", []):
        if getattr(output, "type", "") != "message":
            continue
        for item in getattr(output, "content", []):
            if getattr(item, "type", "") == "refusal":
                raise RuntimeError(str(getattr(item, "refusal", "Company profile extraction was refused.")))
            parsed = getattr(item, "parsed", None)
            if isinstance(parsed, CompetitiveLandscapeProfileResponse):
                return parsed
    raise ValueError("Structured company profile response did not contain parsed content.")


def _extract_parsed_example_output(response: Any) -> ExampleExtractionResponse:
    for output in getattr(response, "output", []):
        if getattr(output, "type", "") != "message":
            continue
        for item in getattr(output, "content", []):
            if getattr(item, "type", "") == "refusal":
                raise RuntimeError(str(getattr(item, "refusal", "Recent developments extraction was refused.")))
            parsed = getattr(item, "parsed", None)
            if isinstance(parsed, ExampleExtractionResponse):
                return parsed
    raise ValueError("Structured recent developments response did not contain parsed content.")


async def _generate_example_search_queries(
    *,
    topic: str,
    section: str,
    trend_heading: str,
    trend_body: str,
    location_context: LocationContext,
) -> List[str]:
    fallback_queries = _build_fallback_queries(
        topic=topic,
        section=section,
        trend_heading=trend_heading,
        trend_body=trend_body,
        location_context=location_context,
        fallback_mode=False,
    )
    if not settings.OPENAI_API_KEY or not can_use_openai():
        return fallback_queries

    system_prompt = build_example_search_query_system_prompt()
    user_prompt = build_example_search_query_user_prompt(
        topic=topic,
        section=section,
        trend_heading=trend_heading,
        trend_body=trend_body,
        location_context=location_context,
    )
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    try:
        response = await call_openai(
            "generate_example_search_queries",
            lambda: client.responses.parse(
                model=EXAMPLE_QUERY_MODEL_NAME,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                text_format=ExampleSearchQueryResponse,
                max_output_tokens=ensure_min_output_tokens(1000),
                temperature=0.2,
            ),
            fallback=None,
            timeout=EXAMPLE_QUERY_TIMEOUT_SECONDS,
            max_retries=EXAMPLE_QUERY_MAX_RETRIES,
            context={"model": EXAMPLE_QUERY_MODEL_NAME, "trend_heading": trend_heading},
        )
        if response is None:
            return fallback_queries
        parsed = _extract_parsed_query_output(response)
        llm_queries = _dedupe_queries([entry.query for entry in parsed.queries])
        return (llm_queries or fallback_queries)[:MAX_EXAMPLE_RESEARCH_QUERIES]
    except Exception as exc:
        logger.warning("Example query generation failed heading=%s error=%s", trend_heading, exc)
        return fallback_queries
    finally:
        await client.close()


def _looks_like_generic_company_overview(company_name: str, overview: str) -> bool:
    normalized_company = _normalize_text(company_name).lower()
    normalized_overview = _normalize_text(overview).lower()
    if not normalized_overview:
        return True
    if normalized_company and normalized_company not in normalized_overview:
        return True
    if _contains_stale_forecast_language(normalized_overview):
        return True
    return any(marker in normalized_overview for marker in GENERIC_COMPANY_OVERVIEW_MARKERS)


def _looks_like_invalid_company_heading(heading: str) -> bool:
    normalized_heading = _normalize_text(heading).lower()
    if not normalized_heading:
        return True
    if bool(re.search(r"\b20\d{2}\b", normalized_heading)):
        return True
    return any(marker in normalized_heading for marker in INVALID_COMPANY_TITLE_MARKERS)


def _extract_company_focus_sentences(company_name: str, evidence_blocks: Sequence[Dict[str, Any]]) -> List[str]:
    company_key = _normalize_text(company_name).lower()
    normalized_sentences: List[str] = []
    seen_sentences = set()
    for block in evidence_blocks:
        excerpt = _normalize_text(block.get("excerpt") or block.get("full_text_excerpt") or block.get("snippet"))
        if not excerpt:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", excerpt):
            normalized_sentence = _normalize_text(sentence)
            if not normalized_sentence:
                continue
            if company_key and company_key not in normalized_sentence.lower():
                continue
            if _contains_stale_forecast_language(normalized_sentence):
                continue
            sentence_key = normalized_sentence.lower()
            if sentence_key in seen_sentences:
                continue
            seen_sentences.add(sentence_key)
            normalized_sentences.append(normalized_sentence)
            if len(normalized_sentences) >= 4:
                return normalized_sentences
    return normalized_sentences


def _build_company_profile_fallback_overview(
    *,
    company_name: str,
    evidence_blocks: Sequence[Dict[str, Any]],
) -> str:
    focus_sentences = _extract_company_focus_sentences(company_name, evidence_blocks)
    if focus_sentences:
        selected = focus_sentences[:2]
        return " ".join(selected)
    return ""


def _build_company_profile_fallback_facts(
    *,
    company_name: str,
    evidence_blocks: Sequence[Dict[str, Any]],
    business_overview: str = "",
) -> List[str]:
    return _build_company_profile_fallback_fact_candidates(
        company_name=company_name,
        evidence_blocks=evidence_blocks,
        business_overview=business_overview,
    )[:5]


def _clean_company_profile_sentence(value: str) -> str:
    normalized = _normalize_text(value)
    return re.sub(r"^[\-\u2022]+\s*", "", normalized).strip(" ;,")


def _is_actionable_company_fact(fact: str) -> bool:
    normalized = _clean_company_profile_sentence(fact)
    normalized_lower = normalized.lower()
    if not normalized:
        return False
    if _count_fact_sentences(normalized) > 1:
        return False
    if _contains_stale_forecast_language(normalized_lower):
        return False
    if _looks_like_project_only_fact(normalized_lower):
        return False
    if any(marker in normalized_lower for marker in GENERIC_COMPANY_FACT_MARKERS) and not re.search(r"\d", normalized_lower):
        return False
    if _is_isolated_investment_fact(normalized_lower):
        return False
    return any(
        checker(normalized_lower)
        for checker in (
            _has_company_level_metric_fact,
            _has_ownership_fact,
            _has_geographic_footprint_fact,
            _has_business_model_fact,
            _has_market_position_fact,
        )
    )


def _build_company_profile_fallback_fact_candidates(
    *,
    company_name: str,
    evidence_blocks: Sequence[Dict[str, Any]],
    business_overview: str = "",
) -> List[str]:
    candidates: List[str] = []
    seen = set()
    company_key = _normalize_text(company_name).lower()
    for block in evidence_blocks:
        excerpt = _normalize_text(block.get("excerpt") or block.get("full_text_excerpt"))
        block_date = block.get("published_date") or block.get("date")
        if not excerpt:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", excerpt):
            cleaned_sentence = _clean_company_profile_sentence(sentence)
            if not cleaned_sentence:
                continue
            if company_key and company_key not in cleaned_sentence.lower():
                continue
            if not _is_recent_profile_date(block_date) and not _contains_any_marker(cleaned_sentence, CURRENT_STATE_FACT_MARKERS):
                continue
            if _contains_stale_forecast_language(cleaned_sentence):
                continue
            if not _is_actionable_company_fact(cleaned_sentence):
                continue
            if _fact_repeats_overview(cleaned_sentence, business_overview):
                continue
            sentence_key = cleaned_sentence.lower()
            if sentence_key in seen:
                continue
            seen.add(sentence_key)
            candidates.append(cleaned_sentence.rstrip(".") + ".")
            if len(candidates) >= 5:
                return candidates
    return candidates


def _filter_company_profile_facts(facts: Sequence[str], *, business_overview: str = "") -> List[str]:
    filtered: List[str] = []
    seen = set()
    for fact in facts:
        cleaned_fact = _clean_company_profile_sentence(fact)
        fact_key = cleaned_fact.lower()
        if not cleaned_fact or fact_key in seen:
            continue
        if _contains_stale_forecast_language(cleaned_fact):
            continue
        if not _is_actionable_company_fact(cleaned_fact):
            continue
        if _fact_repeats_overview(cleaned_fact, business_overview):
            continue
        seen.add(fact_key)
        filtered.append(cleaned_fact.rstrip(".") + ".")
    return filtered[:5]


def _evidence_blocks_for_source_ids(
    evidence_blocks: Sequence[Dict[str, Any]],
    source_ids: Sequence[int],
) -> List[Dict[str, Any]]:
    requested_ids = set()
    for source_id in source_ids or []:
        try:
            numeric_id = int(source_id)
        except (TypeError, ValueError):
            continue
        if numeric_id > 0:
            requested_ids.add(numeric_id)
    if not requested_ids:
        return list(evidence_blocks)
    filtered_blocks: List[Dict[str, Any]] = []
    for block in evidence_blocks:
        try:
            block_id = int(block.get("source_id"))
        except (TypeError, ValueError, AttributeError):
            continue
        if block_id in requested_ids:
            filtered_blocks.append(block)
    return filtered_blocks


def _has_evidence_support(
    text: str,
    *,
    evidence_blocks: Sequence[Dict[str, Any]],
    company_name: str,
    source_ids: Sequence[int] | None = None,
    minimum_overlap: int = 2,
) -> bool:
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return False
    relevant_blocks = _evidence_blocks_for_source_ids(evidence_blocks, list(source_ids or []))
    if not relevant_blocks:
        return False
    candidate_tokens = [
        token
        for token in _tokenize(normalized_text)
        if not re.fullmatch(r"20\d{2}", token)
    ]
    if not candidate_tokens:
        return False
    combined_evidence = " ".join(
        _normalize_text(block.get("excerpt") or block.get("full_text_excerpt") or block.get("snippet"))
        for block in relevant_blocks
    ).lower()
    if not combined_evidence:
        return False
    company_key = _normalize_text(company_name).lower()
    if company_key and company_key not in combined_evidence:
        block_hits = 0
        for block in relevant_blocks:
            block_context = {
                "title": block.get("title"),
                "snippet": block.get("snippet"),
                "content": block.get("excerpt") or block.get("full_text_excerpt"),
            }
            if _is_company_specific_source(company_name, block_context):
                block_hits += 1
        if block_hits == 0:
            return False
    overlap = len({token for token in candidate_tokens if token in combined_evidence})
    required_overlap = min(max(1, minimum_overlap), max(1, len(set(candidate_tokens))))
    return overlap >= required_overlap


def _is_strategic_development_text(text: str) -> bool:
    normalized = _normalize_text(text).lower()
    if not normalized:
        return False
    if _contains_stale_forecast_language(normalized):
        return False
    has_event = any(marker in normalized for marker in STRATEGIC_EVENT_MARKERS)
    has_static_only = any(marker in normalized for marker in STATIC_DEVELOPMENT_MARKERS)
    return has_event and not (has_static_only and not has_event)


def _filter_recent_developments(
    examples: Sequence[ExtractedExample],
    *,
    company_name: str = "",
    evidence_blocks: Sequence[Dict[str, Any]] | None = None,
) -> List[ExtractedExample]:
    filtered: List[ExtractedExample] = []
    seen = set()
    for example in examples:
        if not isinstance(example, ExtractedExample):
            continue
        text = _normalize_text(example.text or example.event)
        if not _is_strategic_development_text(text):
            continue
        if _contains_stale_forecast_language(text):
            continue
        if not _is_recent_profile_date(example.event_date or example.published_date or example.year or text):
            continue
        if evidence_blocks and not _has_evidence_support(
            text,
            evidence_blocks=evidence_blocks,
            company_name=company_name or _normalize_text(example.company),
            source_ids=list(example.source_ids or []),
            minimum_overlap=2,
        ):
            continue
        dedupe_key = (
            text.lower(),
            _normalize_text(example.event_date or example.published_date or example.year),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        filtered.append(example)
    filtered.sort(
        key=lambda example: _normalize_text(example.event_date or example.published_date or example.year),
        reverse=True,
    )
    return filtered[:4]


def _build_company_profile_fallback_developments(
    *,
    company_name: str,
    evidence_blocks: Sequence[Dict[str, Any]],
) -> List[ExtractedExample]:
    developments: List[ExtractedExample] = []
    seen = set()
    company_key = _normalize_text(company_name).lower()
    for block in evidence_blocks:
        excerpt = _normalize_text(block.get("excerpt") or block.get("full_text_excerpt"))
        if not excerpt:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", excerpt):
            cleaned_sentence = _clean_company_profile_sentence(sentence)
            if not cleaned_sentence:
                continue
            if company_key and company_key not in cleaned_sentence.lower():
                continue
            if _contains_stale_forecast_language(cleaned_sentence):
                continue
            if not _is_strategic_development_text(cleaned_sentence):
                continue
            event_date = _normalize_text(block.get("date") or block.get("published_date"))
            if not _is_recent_profile_date(event_date or cleaned_sentence):
                continue
            sentence_key = cleaned_sentence.lower()
            if sentence_key in seen:
                continue
            seen.add(sentence_key)
            developments.append(
                ExtractedExample(
                    company=company_name,
                    event="strategic development",
                    text=cleaned_sentence.rstrip(".") + ".",
                    event_date=event_date,
                    published_date=event_date,
                    example_type="other",
                    confidence="medium",
                    trend_fit_reason="Evidence shows a dated company action relevant to its competitive position.",
                    source_quality=_normalize_text(block.get("source_tier")) or "Tier 2",
                    validation_score=7,
                    year=event_date,
                    source_ids=[int(block.get("source_id"))] if str(block.get("source_id")).isdigit() else [],
                )
            )
            if len(developments) >= 4:
                return developments
    return developments


def _looks_like_generic_positioning(value: str) -> bool:
    normalized = _normalize_text(value).lower()
    return not normalized or _contains_stale_forecast_language(normalized) or any(
        marker in normalized for marker in GENERIC_POSITIONING_MARKERS
    )


def _sanitize_company_profile_overview(
    *,
    company_name: str,
    overview: str,
    evidence_blocks: Sequence[Dict[str, Any]],
    source_ids: Sequence[int],
) -> str:
    cleaned_overview = _normalize_text(overview)
    if not cleaned_overview:
        return ""
    if _looks_like_generic_company_overview(company_name, cleaned_overview):
        return ""
    if not _has_evidence_support(
        cleaned_overview,
        evidence_blocks=evidence_blocks,
        company_name=company_name,
        source_ids=source_ids,
        minimum_overlap=2,
    ):
        return ""
    return cleaned_overview


def _sanitize_company_profile_positioning(
    *,
    company_name: str,
    positioning: str,
    evidence_blocks: Sequence[Dict[str, Any]],
    source_ids: Sequence[int],
) -> str:
    cleaned_positioning = _normalize_text(positioning)
    if not cleaned_positioning or _looks_like_generic_positioning(cleaned_positioning):
        return ""
    if not _has_evidence_support(
        cleaned_positioning,
        evidence_blocks=evidence_blocks,
        company_name=company_name,
        source_ids=source_ids,
        minimum_overlap=2,
    ):
        return ""
    return cleaned_positioning


def _company_profile_has_market_relevance(
    *,
    company_name: str,
    evidence_blocks: Sequence[Dict[str, Any]],
) -> bool:
    company_specific_recent_sources = 0
    for block in evidence_blocks:
        excerpt = _normalize_text(block.get("excerpt") or block.get("full_text_excerpt"))
        if not excerpt:
            continue
        block_context = {
            "title": block.get("title"),
            "snippet": block.get("snippet"),
            "content": excerpt,
        }
        if not _is_company_specific_source(company_name, block_context):
            continue
        if not _is_recent_profile_date(block.get("date") or block.get("published_date") or excerpt):
            continue
        company_specific_recent_sources += 1
    return company_specific_recent_sources >= 1


def _has_retained_company_content(item: Dict[str, Any]) -> bool:
    body = _normalize_text(item.get("body"))
    facts = [fact for fact in list(item.get("key_company_facts", []) or []) if _normalize_text(fact)]
    sources = list(item.get("sources", []) or [])
    return bool(body or facts or sources)


def _build_enriched_evidence_blocks(
    processed_payload: Dict[str, Any],
    stored_sources: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    source_by_url = {
        _normalize_text(source.get("url")): dict(source)
        for source in stored_sources
        if _normalize_text(source.get("url"))
    }
    evidence_blocks: List[Dict[str, Any]] = []
    for block in processed_payload.get("evidence_blocks", []):
        url = _normalize_text(block.get("url"))
        source = source_by_url.get(url, {})
        evidence_blocks.append(
            {
                "source_id": block.get("source_id"),
                "title": block.get("title"),
                "url": url,
                "publisher": _normalize_text(source.get("source_type") or block.get("domain")),
                "published_date": _normalize_text(block.get("date")),
                "retrieved_date": datetime.now(timezone.utc).date().isoformat(),
                "source_tier": _source_tier_for_source({**source, **block}),
                "snippet": _normalize_text(block.get("excerpt"))[:500],
                "full_text_excerpt": _normalize_text(block.get("excerpt")),
                "excerpt": _normalize_text(block.get("excerpt")),
                "date": _normalize_text(block.get("date")),
                "domain": _normalize_text(block.get("domain")),
                "location": _normalize_text(source.get("location")),
            }
        )
    return evidence_blocks


def _build_company_profile_evidence_blocks(
    stored_sources: Sequence[Dict[str, Any]],
    *,
    company_name: str,
) -> List[Dict[str, Any]]:
    evidence_blocks: List[Dict[str, Any]] = []
    seen_signatures = set()
    prioritized_sources = _prioritize_company_profile_sources(stored_sources, company_name=company_name)
    for source_index, source in enumerate(list(prioritized_sources)[:COMPANY_PROFILE_MAX_SOURCES], start=1):
        processed_payload = prepare_processed_content([dict(source)])
        cleaned_content = _normalize_text(processed_payload.get("processed_text", ""))
        if len(cleaned_content) < COMPANY_PROFILE_MIN_LENIENT_CHARS:
            raw_content = _normalize_text(source.get("content"))
            title = _normalize_text(source.get("title"))
            metadata_summary = " ".join(
                part
                for part in [
                    title,
                    _normalize_text(source.get("snippet")),
                    _normalize_text(source.get("summary")),
                    _normalize_text(source.get("description")),
                ]
                if part
            ).strip()
            combined_content = " ".join(part for part in [metadata_summary, raw_content] if part).strip()
            cleaned_content = combined_content[:COMPANY_PROFILE_MAX_CHARS_PER_SOURCE]
        excerpt = _normalize_text(cleaned_content)[:COMPANY_PROFILE_MAX_CHARS_PER_SOURCE].strip()
        signature = excerpt.lower()
        if not excerpt or signature in seen_signatures:
            logger.info(
                'Competitive landscape company evidence skipped source_index=%s title="%s" reason="%s"',
                source_index,
                _normalize_text(source.get("title")) or f"Source {source_index}",
                "empty_or_duplicate_excerpt",
            )
            continue
        seen_signatures.add(signature)
        evidence_blocks.append(
            {
                "source_id": str(source_index),
                "title": _normalize_text(source.get("title")) or f"Source {source_index}",
                "url": _normalize_text(source.get("url")),
                "publisher": _normalize_text(source.get("source_type") or source.get("artifact_type")),
                "published_date": _normalize_text(source.get("published_date") or source.get("date") or source.get("year")),
                "retrieved_date": datetime.now(timezone.utc).date().isoformat(),
                "source_tier": _source_tier_for_source(source),
                "snippet": excerpt[:500],
                "full_text_excerpt": excerpt,
                "excerpt": excerpt,
                "date": _normalize_text(source.get("published_date") or source.get("date") or source.get("year")),
                "domain": _normalize_text(source.get("domain")),
                "location": _normalize_text(source.get("location")),
                "source_quality_score": _company_profile_source_quality_score(source, company_name),
                "company_specific": _is_company_specific_source(company_name, source),
                "evidence_scope": _classify_company_profile_evidence_scope(source),
            }
        )
    logger.info(
        'Competitive landscape company evidence built company="%s" candidate_sources=%s evidence_blocks=%s',
        company_name,
        len(list(prioritized_sources)[:COMPANY_PROFILE_MAX_SOURCES]),
        len(evidence_blocks),
    )
    return evidence_blocks


async def _extract_company_profile_from_evidence(
    *,
    topic: str,
    company_name: str,
    existing_overview: str,
    location_context: LocationContext,
    evidence_blocks: Sequence[Dict[str, Any]],
) -> CompetitiveLandscapeProfileResponse:
    if not settings.OPENAI_API_KEY or not can_use_openai():
        return CompetitiveLandscapeProfileResponse()

    payload = build_company_profile_extraction_payload(
        topic=topic,
        company_name=company_name,
        existing_overview=existing_overview,
        location_context=location_context,
        evidence_blocks=list(evidence_blocks),
    )
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    try:
        response = await call_openai(
            "extract_company_profile",
            lambda: client.responses.parse(
                model=COMPANY_PROFILE_MODEL_NAME,
                input=[
                    {"role": "system", "content": "You are an OSINT analyst building evidence-backed company profiles."},
                    {"role": "user", "content": payload},
                ],
                text_format=CompetitiveLandscapeProfileResponse,
                max_output_tokens=ensure_min_output_tokens(1800),
                temperature=0.1,
            ),
            fallback=None,
            timeout=COMPANY_PROFILE_TIMEOUT_SECONDS,
            max_retries=COMPANY_PROFILE_MAX_RETRIES,
            context={"model": COMPANY_PROFILE_MODEL_NAME, "company_name": company_name},
        )
        if response is None:
            return CompetitiveLandscapeProfileResponse()
        return _extract_parsed_company_profile_output(response)
    except Exception as exc:
        logger.warning("Company profile extraction failed company=%s error=%s", company_name, exc)
        return CompetitiveLandscapeProfileResponse()
    finally:
        await client.close()


async def _extract_recent_company_developments_from_evidence(
    *,
    topic: str,
    company_name: str,
    location_context: LocationContext,
    evidence_blocks: Sequence[Dict[str, Any]],
) -> ExampleExtractionResponse:
    if not settings.OPENAI_API_KEY or not can_use_openai():
        return ExampleExtractionResponse()

    payload = build_recent_company_developments_payload(
        topic=topic,
        company_name=company_name,
        location_context=location_context,
        evidence_blocks=list(evidence_blocks),
    )
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    try:
        response = await call_openai(
            "extract_recent_company_developments",
            lambda: client.responses.parse(
                model=COMPANY_PROFILE_MODEL_NAME,
                input=[
                    {"role": "system", "content": "You are an OSINT analyst identifying investor-grade recent company developments from evidence only."},
                    {"role": "user", "content": payload},
                ],
                text_format=ExampleExtractionResponse,
                max_output_tokens=ensure_min_output_tokens(1800),
                temperature=0.1,
            ),
            fallback=None,
            timeout=COMPANY_PROFILE_TIMEOUT_SECONDS,
            max_retries=COMPANY_PROFILE_MAX_RETRIES,
            context={"model": COMPANY_PROFILE_MODEL_NAME, "company_name": company_name},
        )
        if response is None:
            return ExampleExtractionResponse()
        return _extract_parsed_example_output(response)
    except Exception as exc:
        logger.warning("Recent company developments extraction failed company=%s error=%s", company_name, exc)
        return ExampleExtractionResponse()
    finally:
        await client.close()


async def _collect_company_research_evidence(
    *,
    topic: str,
    section: str,
    heading: str,
    body: str,
    location_context: LocationContext,
    session_id: str,
    item_index: int,
    queries: Sequence[str],
) -> Dict[str, Any]:
    logger.info('Competitive landscape company enrichment search company="%s" queries=%s', heading, list(queries))
    search_payload = await search_queries(
        f"{topic} {heading}",
        list(queries),
        freshness="high",
        location_context=location_context,
        workflow=section,
    )
    search_results = list(search_payload.get("results", []))[:MAX_EXAMPLE_RESULTS]
    if not search_results:
        logger.info('Competitive landscape company enrichment search company="%s" reason="%s"', heading, "no_search_results")
        return {"search_results": 0, "stored_sources": [], "evidence_blocks": []}

    artifact_bundle = await collect_research_artifacts(
        topic=f"{topic} {heading}",
        section="company_profile",
        session_id=f"{session_id}_trend_examples_{item_index}_profile",
        location_context=location_context,
        search_results=search_results,
    )
    stored_sources = await asyncio.to_thread(load_saved_sources, list(artifact_bundle.get("artifacts", [])))
    if not stored_sources:
        logger.info(
            'Competitive landscape company enrichment scrape company="%s" search_results=%s reason="%s"',
            heading,
            len(search_results),
            "no_stored_sources",
        )
        return {"search_results": len(search_results), "stored_sources": [], "evidence_blocks": []}

    evidence_blocks = _build_company_profile_evidence_blocks(stored_sources, company_name=heading)
    logger.info(
        'Competitive landscape company enrichment evidence company="%s" search_results=%s stored_sources=%s evidence_blocks=%s',
        heading,
        len(search_results),
        len(stored_sources),
        len(evidence_blocks),
    )
    return {
        "search_results": len(search_results),
        "stored_sources": list(stored_sources),
        "evidence_blocks": evidence_blocks,
    }


def _trend_context(
    *,
    item: Dict[str, Any],
    topic: str,
    location_context: LocationContext,
) -> Dict[str, Any]:
    return {
        "heading": _normalize_text(item.get("heading")),
        "body": _normalize_text(item.get("body")),
        "topic": topic,
        "location": location_context.value if not location_context.is_global else "",
        "synonyms": _synonym_terms(_normalize_text(item.get("heading")), _normalize_text(item.get("body"))),
    }


def _coverage_status(examples: Sequence[Dict[str, Any]]) -> str:
    if not examples:
        return "none"
    high_or_medium = [
        example
        for example in examples
        if str(example.get("confidence", "")).strip().lower() in {"high", "medium"}
        and not bool(example.get("fallback_used", False))
    ]
    if len(high_or_medium) >= 2:
        return "strong"
    return "partial"


def _item_priority(item: Dict[str, Any], index: int) -> tuple[int, int, int, int, int]:
    heading = _normalize_text(item.get("heading"))
    body = _normalize_text(item.get("body"))
    examples = item.get("examples", []) or []
    sources = item.get("sources", []) or []
    no_examples = 1 if not examples else 0
    emerging = 1 if _contains_emerging_terms(heading, body) else 0
    sparse_sources = 1 if len(sources) < 2 else 0
    has_sources_but_no_examples = 1 if sources and not examples else 0
    return (-no_examples, -emerging, -sparse_sources, -has_sources_but_no_examples, index)


def _build_skip_item(item: Dict[str, Any], *, reason: str) -> Dict[str, Any]:
    fallback_item = dict(item)
    fallback_item["examples"] = list(fallback_item.get("examples", [])) if isinstance(fallback_item.get("examples", []), list) else []
    fallback_item["example_coverage_status"] = str(fallback_item.get("example_coverage_status", "")).strip() or (
        "partial" if fallback_item["examples"] else "none"
    )
    fallback_item["fallback_used"] = bool(fallback_item.get("fallback_used", False))
    fallback_item["_example_skip_reason"] = reason
    return fallback_item


def _select_primary_items(items: Sequence[Dict[str, Any]], *, section: str) -> List[tuple[int, Dict[str, Any]]]:
    indexed_items = [(index, dict(item)) for index, item in enumerate(items, start=1)]
    if section == "competitive_landscape":
        return indexed_items
    if MAX_TRENDS_WITH_EXAMPLE_RESEARCH is None:
        return indexed_items
    sorted_items = sorted(indexed_items, key=lambda entry: _item_priority(entry[1], entry[0]))
    return sorted_items[: max(0, int(MAX_TRENDS_WITH_EXAMPLE_RESEARCH))]


async def _run_example_pass(
    *,
    topic: str,
    section: str,
    heading: str,
    body: str,
    location_context: LocationContext,
    session_id: str,
    item_index: int,
    queries: Sequence[str],
    fallback_mode: bool,
) -> Dict[str, Any]:
    search_payload = await search_queries(
        f"{topic} {heading}",
        list(queries),
        freshness="high",
        location_context=location_context,
        workflow="company_research",
    )
    search_results = list(search_payload.get("results", []))[:MAX_EXAMPLE_RESULTS]
    logger.info("Trend example search heading=%s fallback=%s results=%s", heading, fallback_mode, len(search_results))
    if not search_results:
        return {"examples": [], "rejection_reasons": [], "search_results": 0, "sources": 0, "candidate_count": 0}

    artifact_bundle = await collect_research_artifacts(
        topic=f"{topic} {heading}",
        section=section,
        session_id=f"{session_id}_trend_examples_{item_index}_{'fallback' if fallback_mode else 'primary'}",
        location_context=location_context,
        search_results=search_results,
    )
    stored_sources = await asyncio.to_thread(load_saved_sources, list(artifact_bundle.get("artifacts", [])))
    if not stored_sources:
        return {"examples": [], "rejection_reasons": [], "search_results": len(search_results), "sources": 0, "candidate_count": 0}

    processed_payload = await asyncio.to_thread(prepare_processed_content, list(stored_sources))
    evidence_blocks = _build_enriched_evidence_blocks(processed_payload, stored_sources)
    if not evidence_blocks:
        return {"examples": [], "rejection_reasons": [], "search_results": len(search_results), "sources": len(stored_sources), "candidate_count": 0}

    extraction_payload = build_trend_example_extraction_payload(
        topic=topic,
        section=section,
        trend_heading=heading,
        trend_body=body,
        location_context=location_context,
        evidence_blocks=evidence_blocks,
    )
    trend_context = {"heading": heading, "body": body, "topic": topic, "location": location_context.value}
    extraction_result = await extract_validated_examples_from_evidence(
        metadata=extraction_payload,
        section=section,
        evidence_blocks=evidence_blocks,
        log_context=f"trend_examples:{heading}",
        research_date=datetime.now(timezone.utc).date(),
        trend_context=trend_context,
        allow_low_confidence_fallback=fallback_mode,
        return_diagnostics=True,
        max_age_months=12 if section == "competitive_landscape" else None,
    )
    validated_examples, diagnostics = extraction_result
    for example in validated_examples:
        example.fallback_used = fallback_mode
    return {
        "examples": validated_examples,
        "rejection_reasons": list(diagnostics.get("rejection_reasons", [])),
        "search_results": len(search_results),
        "sources": len(stored_sources),
        "candidate_count": int(diagnostics.get("candidate_count", 0)),
    }


async def _research_examples_for_item(
    *,
    item: Dict[str, Any],
    item_index: int,
    topic: str,
    section: str,
    location_context: LocationContext,
    session_id: str,
) -> Dict[str, Any]:
    normalized_item = dict(item)
    heading = _normalize_text(normalized_item.get("heading"))
    body = _normalize_text(normalized_item.get("body"))
    if not heading or (section != "competitive_landscape" and not body):
        logger.info(
            'Trend example research skipped index=%s heading="%s" reason="%s"',
            item_index,
            heading or "<missing-heading>",
            "missing_heading_or_body",
        )
        return _build_skip_item(normalized_item, reason="missing_heading_or_body")

    queries = await _generate_example_search_queries(
        topic=topic,
        section=section,
        trend_heading=heading,
        trend_body=body,
        location_context=location_context,
    )
    logger.info("Trend example research heading=%s generated_queries=%s", heading, queries)
    if section == "competitive_landscape":
        logger.info('Competitive landscape enrichment entering company="%s" segment="%s"', heading, _normalize_text(normalized_item.get("segment")))
        evidence_bundle = await _collect_company_research_evidence(
            topic=topic,
            section=section,
            heading=heading,
            body=body,
            location_context=location_context,
            session_id=session_id,
            item_index=item_index,
            queries=queries,
        )
        evidence_blocks = list(evidence_bundle.get("evidence_blocks", []))
        stored_sources = list(evidence_bundle.get("stored_sources", []))
        if not evidence_blocks:
            logger.info('Competitive landscape enrichment skipped company="%s" reason="%s"', heading, "no_company_evidence")
            return _build_skip_item(normalized_item, reason="no_company_evidence")
        if not _company_profile_has_market_relevance(
            company_name=heading,
            evidence_blocks=evidence_blocks,
        ):
            logger.info(
                'Competitive landscape enrichment skipped company="%s" reason="%s"',
                heading,
                "insufficient_market_relevance_evidence",
            )
            return _build_skip_item(normalized_item, reason="insufficient_market_relevance_evidence")

        profile_response = await _extract_company_profile_from_evidence(
            topic=topic,
            company_name=heading,
            existing_overview=body,
            location_context=location_context,
            evidence_blocks=evidence_blocks,
        )
        profile = profile_response.profile

        attached_item = dict(normalized_item)
        fallback_overview = _build_company_profile_fallback_overview(
            company_name=heading,
            evidence_blocks=evidence_blocks,
        )
        sanitized_overview = _sanitize_company_profile_overview(
            company_name=heading,
            overview=profile.business_overview,
            evidence_blocks=evidence_blocks,
            source_ids=list(profile.source_ids or []),
        )
        if sanitized_overview:
            attached_item["body"] = sanitized_overview
        elif fallback_overview:
            attached_item["body"] = fallback_overview
        else:
            attached_item["body"] = ""
        attached_item["key_company_facts"] = _filter_company_profile_facts(
            list(profile.key_company_facts or []),
            business_overview=attached_item["body"],
        )
        if not attached_item["key_company_facts"]:
            attached_item["key_company_facts"] = _build_company_profile_fallback_facts(
                company_name=heading,
                evidence_blocks=evidence_blocks,
                business_overview=attached_item["body"],
            )
        try:
            recent_developments_response = await _extract_recent_company_developments_from_evidence(
                topic=topic,
                company_name=heading,
                location_context=location_context,
                evidence_blocks=evidence_blocks,
            )
            filtered_developments = _filter_recent_developments(
                list(recent_developments_response.examples or []),
                company_name=heading,
                evidence_blocks=evidence_blocks,
            )
        except Exception as exc:
            logger.warning(
                'Competitive landscape recent developments fallback company="%s" error=%s',
                heading,
                exc,
            )
            filtered_developments = []
        positioning_text = _sanitize_company_profile_positioning(
            company_name=heading,
            positioning=profile.competitive_positioning,
            evidence_blocks=evidence_blocks,
            source_ids=list(profile.source_ids or []),
        )
        attached_item["competitive_positioning"] = positioning_text
        attached_item["examples"] = [
            {
                "text": example.text,
                "company": example.company,
                "event": example.event,
                "event_date": example.event_date,
                "published_date": example.published_date,
                "location": example.location,
                "example_type": example.example_type,
                "why_it_matters": example.trend_fit_reason,
                "source_quality": example.source_quality,
                "confidence": example.confidence,
                "validation_score": example.validation_score,
                "fallback_used": bool(example.fallback_used),
                "year": example.year,
            }
            for example in filtered_developments[:MAX_EXAMPLES_PER_TREND]
        ]
        profile_source_ids = list(profile.source_ids or [])
        if not profile_source_ids:
            for example in filtered_developments:
                for source_id in list(example.source_ids or []):
                    if source_id not in profile_source_ids:
                        profile_source_ids.append(source_id)
        attached_item["source_ids"] = profile_source_ids[:10]
        if not _has_retained_company_content(attached_item):
            logger.info(
                'Competitive landscape enrichment skipped company="%s" reason="%s"',
                heading,
                "no_supported_company_content",
            )
            return _build_skip_item(normalized_item, reason="no_supported_company_content")
        attached_with_sources = attach_sources_to_items([attached_item], evidence_blocks, max_sources_per_item=6)
        attached_item = attached_with_sources[0] if attached_with_sources else attached_item
        attached_item["fallback_used"] = False
        attached_item["example_coverage_status"] = _coverage_status(attached_item.get("examples", []))
        logger.info(
            'Competitive landscape enrichment status index=%s company="%s" search_results=%s sources=%s facts=%s developments=%s positioning=%s',
            item_index,
            heading,
            int(evidence_bundle.get("search_results", 0)),
            len(stored_sources),
            len(attached_item.get("key_company_facts", [])),
            len(attached_item.get("examples", [])),
            bool(attached_item.get("competitive_positioning")),
        )
        return attached_item

    primary_pass = await _run_example_pass(
        topic=topic,
        section=section,
        heading=heading,
        body=body,
        location_context=location_context,
        session_id=session_id,
        item_index=item_index,
        queries=queries,
        fallback_mode=False,
    )
    validated_examples = list(primary_pass.get("examples", []))
    fallback_used = False

    if not validated_examples:
        fallback_queries = _build_fallback_queries(
            topic=topic,
            section=section,
            trend_heading=heading,
            trend_body=body,
            location_context=location_context,
            fallback_mode=True,
        )
        logger.info("Trend example fallback triggered heading=%s fallback_queries=%s", heading, fallback_queries)
        fallback_pass = await _run_example_pass(
            topic=topic,
            section=section,
            heading=heading,
            body=body,
            location_context=location_context,
            session_id=session_id,
            item_index=item_index,
            queries=fallback_queries,
            fallback_mode=True,
        )
        validated_examples = list(fallback_pass.get("examples", []))
        fallback_used = True if validated_examples else False
    else:
        fallback_pass = {"sources": 0, "candidate_count": 0, "rejection_reasons": [], "search_results": 0}

    if section == "competitive_landscape":
        attached_item = dict(normalized_item)
        attached_examples = [
            {
                "text": example.text,
                "company": example.company,
                "event": example.event,
                "event_date": example.event_date,
                "published_date": example.published_date,
                "location": example.location,
                "example_type": example.example_type,
                "why_it_matters": example.trend_fit_reason,
                "source_quality": example.source_quality,
                "confidence": example.confidence,
                "validation_score": example.validation_score,
                "fallback_used": bool(example.fallback_used),
                "year": example.year,
            }
            for example in validated_examples[:MAX_EXAMPLES_PER_TREND]
        ]
        attached_item["examples"] = attached_examples
    else:
        attached_items = attach_examples_to_insights(
            [normalized_item],
            validated_examples,
            trend_contexts={heading.lower(): _trend_context(item=normalized_item, topic=topic, location_context=location_context)},
        )
        attached_item = attached_items[0] if attached_items else normalized_item
        attached_examples = list(attached_item.get("examples", []))[:MAX_EXAMPLES_PER_TREND]
        attached_item["examples"] = attached_examples
    attached_item["fallback_used"] = fallback_used or any(bool(example.get("fallback_used", False)) for example in attached_examples)
    attached_item["example_coverage_status"] = _coverage_status(attached_examples)

    logger.info(
        'Trend example research status index=%s heading="%s" attempted=true queries=%s sources=%s candidates=%s validated=%s attached=%s fallback_triggered=%s coverage=%s rejection_reasons=%s',
        item_index,
        heading,
        len(queries),
        int(primary_pass.get("sources", 0)) + int(fallback_pass.get("sources", 0)),
        int(primary_pass.get("candidate_count", 0)) + int(fallback_pass.get("candidate_count", 0)),
        len(validated_examples),
        len(attached_examples),
        fallback_used,
        attached_item["example_coverage_status"],
        list(primary_pass.get("rejection_reasons", [])) + list(fallback_pass.get("rejection_reasons", [])),
    )
    return attached_item


async def enrich_items_with_researched_examples(
    *,
    items: Sequence[Dict[str, Any]],
    topic: str,
    section: str,
    location_context: LocationContext,
    session_id: str,
    progress_callback: Callable[[int, int, Dict[str, Any]], None] | None = None,
) -> List[Dict[str, Any]]:
    all_items = [dict(item) for item in list(items)]
    if not all_items:
        return []
    if section == "competitive_landscape":
        discovered_major_players = len(
            [item for item in all_items if _normalize_text(item.get("segment")) == "major_players"]
        )
        discovered_emerging_players = len(all_items) - discovered_major_players
        logger.info(
            "Competitive landscape diagnostics discovered_major_players=%s discovered_emerging_players=%s",
            discovered_major_players,
            discovered_emerging_players,
        )

    selected_primary = _select_primary_items(all_items, section=section)
    selected_indexes = {index for index, _ in selected_primary}

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_TREND_RESEARCH)

    async def _bounded(item: Dict[str, Any], item_index: int) -> Dict[str, Any]:
        async with semaphore:
            try:
                return await _research_examples_for_item(
                    item=item,
                    item_index=item_index,
                    topic=topic,
                    section=section,
                    location_context=location_context,
                    session_id=session_id,
                )
            except Exception as exc:
                heading = _normalize_text(item.get("heading"))
                logger.exception("Trend example research failed heading=%s error=%s", heading, exc)
                return _build_skip_item(dict(item), reason="research_error")

    async def _run_with_index(item_index: int, item: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        return item_index, await _bounded(item, item_index)

    results_by_index: Dict[int, Dict[str, Any]] = {}
    completed_primary = 0
    total_primary = len(selected_primary)

    primary_tasks = [asyncio.create_task(_run_with_index(item_index, item)) for item_index, item in selected_primary]
    for task in asyncio.as_completed(primary_tasks):
        item_index, result = await task
        results_by_index[item_index] = result
        completed_primary += 1
        if progress_callback is not None:
            progress_callback(completed_primary, total_primary, result)

    for item_index, item in enumerate(all_items, start=1):
        if item_index in selected_indexes:
            continue
        logger.info(
            'Trend example research skipped index=%s heading="%s" reason="%s"',
            item_index,
            _normalize_text(item.get("heading")),
            "cap_limit",
        )
        results_by_index[item_index] = _build_skip_item(item, reason="cap_limit")

    if settings.BACKFILL_ALL_MISSING_TREND_EXAMPLES:
        backfill_targets: List[tuple[int, Dict[str, Any]]] = []
        for item_index, item in enumerate(all_items, start=1):
            current_item = results_by_index.get(item_index, _build_skip_item(item, reason="not_processed"))
            if current_item.get("examples"):
                continue
            backfill_targets.append((item_index, dict(current_item)))

        for item_index, item in backfill_targets:
            logger.info(
                'Trend example research backfill index=%s heading="%s" reason="%s"',
                item_index,
                _normalize_text(item.get("heading")),
                "missing_examples",
            )
        total_backfill = len(backfill_targets)
        completed_backfill = 0
        backfill_tasks = [asyncio.create_task(_run_with_index(item_index, item)) for item_index, item in backfill_targets]
        for task in asyncio.as_completed(backfill_tasks):
            item_index, result = await task
            results_by_index[item_index] = result
            completed_backfill += 1
            if progress_callback is not None:
                progress_callback(total_primary + completed_backfill, total_primary + total_backfill, result)

    enriched_items: List[Dict[str, Any]] = []
    removed_items: List[tuple[str, str]] = []
    for item_index in range(1, len(all_items) + 1):
        result = results_by_index.get(item_index, _build_skip_item(all_items[item_index - 1], reason="not_processed"))
        removal_reason = str(result.get("_example_skip_reason", "")).strip()
        result["examples"] = list(result.get("examples", [])) if isinstance(result.get("examples", []), list) else []
        result["example_coverage_status"] = str(result.get("example_coverage_status", "")).strip() or (
            "partial" if result["examples"] else "none"
        )
        result["fallback_used"] = bool(result.get("fallback_used", False))
        if section == "competitive_landscape":
            if _looks_like_invalid_company_heading(result.get("heading", "")):
                removed_items.append((_normalize_text(result.get("heading")), "invalid_company_heading"))
                continue
            if not _has_retained_company_content(result):
                removed_items.append((_normalize_text(result.get("heading")), removal_reason or "no_retained_company_content"))
                continue
        result.pop("_example_skip_reason", None)
        enriched_items.append(result)

    if section == "competitive_landscape":
        final_major_players = len(
            [item for item in enriched_items if _normalize_text(item.get("segment")) == "major_players"]
        )
        final_emerging_players = len(enriched_items) - final_major_players
        logger.info(
            "Competitive landscape diagnostics enriched_major_players=%s enriched_emerging_players=%s final_major_players=%s final_emerging_players=%s removed=%s",
            len([item for item in results_by_index.values() if _normalize_text(item.get("segment")) == "major_players"]),
            len([item for item in results_by_index.values() if _normalize_text(item.get("segment")) != "major_players"]),
            final_major_players,
            final_emerging_players,
            removed_items,
        )
        for company_name, reason in removed_items:
            logger.info('Competitive landscape company removed company="%s" reason="%s"', company_name or "<unknown>", reason)

    return enriched_items
