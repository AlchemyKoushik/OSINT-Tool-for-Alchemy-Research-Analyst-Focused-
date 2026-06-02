from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence

from openai import AsyncOpenAI

from config.settings import settings
from models.response_models import CompetitiveLandscapeProfileResponse, ExampleSearchQueryResponse
from services.content_processor import prepare_processed_content
from services.example_validation_service import attach_examples_to_insights
from services.external_client import call_openai
from services.location_service import LocationContext
from services.openai_service import can_use_openai, ensure_min_output_tokens, extract_validated_examples_from_evidence
from services.prompt_builder import (
    build_company_profile_extraction_payload,
    build_example_search_query_system_prompt,
    build_example_search_query_user_prompt,
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
GENERIC_COMPANY_OVERVIEW_MARKERS = (
    "market generated a revenue",
    "projected to reach",
    "compound annual growth rate",
    "forecast period",
    "market size",
    "report examines",
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
            '"{company_name}" company profile headquarters products services {year_scope}',
            '"{company_name}" investor relations annual report revenue operations {year_scope}',
            '"{company_name}" headquarters founded revenue ownership market position',
            '"{company_name}" annual report geographic presence products services',
            '"{company_name}" about us business overview brands markets {year_scope}',
            '"{company_name}" {geo} launch partnership acquisition {year_scope}',
            '"{company_name}" {geo} expansion investment contract {year_scope}',
            '"{company_name}" {geo} leadership change restructuring regulatory challenge {year_scope}',
            '"{company_name}" {geo} recent developments {year_scope}',
            '"{company_name}" {geo} market position footprint distribution {year_scope}',
        ]
        return _dedupe_queries(
            [
                template.format(
                    company_name=company_name,
                    geo=geo,
                    year_scope=year_scope,
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
    if section == "competitive_landscape":
        return fallback_queries
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
    return any(marker in normalized_overview for marker in GENERIC_COMPANY_OVERVIEW_MARKERS)


def _looks_like_invalid_company_heading(heading: str) -> bool:
    normalized_heading = _normalize_text(heading).lower()
    if not normalized_heading:
        return True
    if bool(re.search(r"\b20\d{2}\b", normalized_heading)):
        return True
    return any(marker in normalized_heading for marker in INVALID_COMPANY_TITLE_MARKERS)


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
) -> List[Dict[str, Any]]:
    evidence_blocks: List[Dict[str, Any]] = []
    seen_signatures = set()
    for source_index, source in enumerate(list(stored_sources)[:COMPANY_PROFILE_MAX_SOURCES], start=1):
        cleaned_content = prepare_processed_content([dict(source)]).get("processed_text", "")
        if not cleaned_content:
            raw_content = _normalize_text(source.get("content"))
            cleaned_content = raw_content[:COMPANY_PROFILE_MAX_CHARS_PER_SOURCE]
        excerpt = _normalize_text(cleaned_content)[:COMPANY_PROFILE_MAX_CHARS_PER_SOURCE].strip()
        signature = excerpt.lower()
        if not excerpt or signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        evidence_blocks.append(
            {
                "source_id": str(source_index),
                "title": _normalize_text(source.get("title")) or f"Source {source_index}",
                "url": _normalize_text(source.get("url")),
                "publisher": _normalize_text(source.get("source_type") or source.get("artifact_type")),
                "published_date": "",
                "retrieved_date": datetime.now(timezone.utc).date().isoformat(),
                "source_tier": _source_tier_for_source(source),
                "snippet": excerpt[:500],
                "full_text_excerpt": excerpt,
                "excerpt": excerpt,
                "date": "",
                "domain": _normalize_text(source.get("domain")),
                "location": _normalize_text(source.get("location")),
            }
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
    search_payload = await search_queries(
        f"{topic} {heading}",
        list(queries),
        freshness="high",
        location_context=location_context,
    )
    search_results = list(search_payload.get("results", []))[:MAX_EXAMPLE_RESULTS]
    if not search_results:
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
        return {"search_results": len(search_results), "stored_sources": [], "evidence_blocks": []}

    evidence_blocks = _build_company_profile_evidence_blocks(stored_sources)
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


def _select_primary_items(items: Sequence[Dict[str, Any]]) -> List[tuple[int, Dict[str, Any]]]:
    indexed_items = [(index, dict(item)) for index, item in enumerate(items, start=1)]
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
    if not heading or not body:
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

        profile_response = await _extract_company_profile_from_evidence(
            topic=topic,
            company_name=heading,
            existing_overview=body,
            location_context=location_context,
            evidence_blocks=evidence_blocks,
        )
        profile = profile_response.profile

        attached_item = dict(normalized_item)
        if profile.business_overview and not _looks_like_generic_company_overview(heading, profile.business_overview):
            attached_item["body"] = profile.business_overview
        attached_item["key_company_facts"] = list(profile.key_company_facts or [])
        attached_item["competitive_positioning"] = _normalize_text(profile.competitive_positioning)
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
            for example in list(profile.recent_developments or [])[:MAX_EXAMPLES_PER_TREND]
        ]
        profile_source_ids = list(profile.source_ids or [])
        if not profile_source_ids:
            for example in profile.recent_developments or []:
                for source_id in list(example.source_ids or []):
                    if source_id not in profile_source_ids:
                        profile_source_ids.append(source_id)
        attached_item["source_ids"] = profile_source_ids[:10]
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
) -> List[Dict[str, Any]]:
    all_items = [dict(item) for item in list(items)]
    if not all_items:
        return []

    selected_primary = _select_primary_items(all_items)
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

    results_by_index: Dict[int, Dict[str, Any]] = {}

    primary_results = await asyncio.gather(*[_bounded(item, item_index) for item_index, item in selected_primary])
    for (item_index, _), result in zip(selected_primary, primary_results):
        results_by_index[item_index] = result

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
        backfill_results = await asyncio.gather(*[_bounded(item, item_index) for item_index, item in backfill_targets])
        for (item_index, _), result in zip(backfill_targets, backfill_results):
            results_by_index[item_index] = result

    enriched_items: List[Dict[str, Any]] = []
    for item_index in range(1, len(all_items) + 1):
        result = results_by_index.get(item_index, _build_skip_item(all_items[item_index - 1], reason="not_processed"))
        result["examples"] = list(result.get("examples", [])) if isinstance(result.get("examples", []), list) else []
        result["example_coverage_status"] = str(result.get("example_coverage_status", "")).strip() or (
            "partial" if result["examples"] else "none"
        )
        result["fallback_used"] = bool(result.get("fallback_used", False))
        if section == "competitive_landscape":
            if _looks_like_invalid_company_heading(result.get("heading", "")):
                continue
            if _looks_like_generic_company_overview(result.get("heading", ""), result.get("body", "")):
                continue
        enriched_items.append(result)

    return enriched_items
