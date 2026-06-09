from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence

from openai import AsyncOpenAI

from config.settings import settings
from models.response_models import (
    CompetitiveLandscapeDiscoveryAgentCompany,
    CompetitiveLandscapeDiscoveryAgentOutput,
    CompetitiveLandscapeDiscoveryCompany,
    CompetitiveLandscapeDiscoveryOutput,
    ExampleSearchQueryResponse,
)
from services.content_processor import prepare_processed_content
from services.external_client import call_openai
from services.location_service import LocationContext
from services.openai_service import can_use_openai, ensure_min_output_tokens
from services.scraper_service import collect_research_artifacts, load_saved_sources
from services.search_service import search_queries

logger = logging.getLogger(__name__)

DISCOVERY_MODEL_NAME = settings.OPENAI_ANALYSIS_MODEL or "gpt-5.5"
DISCOVERY_QUERY_MODEL_NAME = settings.OPENAI_QUERY_MODEL or settings.OPENAI_SUPPORT_MODEL or "gpt-4.1-mini"
DISCOVERY_TIMEOUT_SECONDS = settings.EXTERNAL_TIMEOUT_SECONDS
DISCOVERY_MAX_RETRIES = settings.EXTERNAL_MAX_RETRIES
DISCOVERY_QUERY_TIMEOUT_SECONDS = 30
DISCOVERY_QUERY_MAX_RETRIES = 1
DISCOVERY_MAX_CANDIDATES = 18
DISCOVERY_MAX_SEARCH_RESULTS = 12
DISCOVERY_MAX_SOURCES_PER_COMPANY = 6
DISCOVERY_MIN_SOURCE_CHARS = 120
TIER_1_DOMAIN_MARKERS = (".gov", ".sec", "investor", "regulator", "exchange", "official")
TIER_2_DOMAIN_MARKERS = ("reuters", "bloomberg", "spglobal", "argus", "woodmac", "mckinsey", "bnef")
TIER_3_TITLE_MARKERS = ("blog", "top 10", "list of", "overview", "market size")


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _location_label(context: LocationContext) -> str:
    if context.preference == "region_specific":
        return str(context.value or "Region").strip()
    if context.preference == "country_specific":
        return str(context.value or "Country").strip()
    return "Global"


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


def _extract_parsed_agent_output(response: Any) -> CompetitiveLandscapeDiscoveryAgentOutput:
    for output in getattr(response, "output", []):
        if getattr(output, "type", "") != "message":
            continue
        for item in getattr(output, "content", []):
            if getattr(item, "type", "") == "refusal":
                raise RuntimeError(str(getattr(item, "refusal", "Competitive landscape discovery was refused.")))
            parsed = getattr(item, "parsed", None)
            if isinstance(parsed, CompetitiveLandscapeDiscoveryAgentOutput):
                return parsed
    raise ValueError("Competitive landscape discovery agent response did not contain parsed content.")


def _extract_parsed_query_output(response: Any) -> ExampleSearchQueryResponse:
    for output in getattr(response, "output", []):
        if getattr(output, "type", "") != "message":
            continue
        for item in getattr(output, "content", []):
            if getattr(item, "type", "") == "refusal":
                raise RuntimeError(str(getattr(item, "refusal", "Company query generation was refused.")))
            parsed = getattr(item, "parsed", None)
            if isinstance(parsed, ExampleSearchQueryResponse):
                return parsed
    raise ValueError("Competitive landscape company query response did not contain parsed content.")


def _build_market_discovery_prompt(
    *,
    topic: str,
    location_context: LocationContext,
    max_candidates: int,
) -> str:
    return (
        "You are the Competitive Landscape Discovery Agent.\n\n"
        "Task:\n"
        "- Research the market itself using your market knowledge.\n"
        "- Do not infer the company list from supplied search results because none are provided at this stage.\n"
        "- Identify the primary competitive participants in the requested market and geography.\n\n"
        "Market selection criteria:\n"
        "- Prefer companies supported by signals such as installed capacity, project ownership, utility-scale assets, market share, developer rankings, pipeline visibility, and repeated inclusion in industry reports.\n"
        "- Focus on direct market participants, owners, developers, operators, or strategically significant players in the requested market and geography.\n"
        "- Exclude consultants, generic software vendors, financial-only actors, and adjacent ecosystem participants unless they directly own, operate, develop, or control assets in the market.\n"
        "- Use three tiers only: Major Player, Mid-Sized Player, Emerging Player.\n"
        "- Aim for a balanced company universe instead of only market leaders.\n"
        "- Confidence is an integer from 0 to 100.\n"
        "- reasons must be short evidence-style rationales such as installed capacity, asset ownership, local project portfolio, developer ranking presence, or recurring market mention.\n\n"
        f"Input:\n- Market: {topic}\n- Geography: {_location_label(location_context)}\n\n"
        "Return strict JSON only in this shape:\n"
        "{\n"
        '  "companies": [\n'
        "    {\n"
        '      "company": "Atlas Renewable Energy",\n'
        '      "tier": "Major Player",\n'
        '      "confidence": 95,\n'
        '      "reasons": ["large utility-scale solar portfolio in Chile", "recurring presence in Chile solar developer rankings"]\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"Return no more than {max_candidates} total companies."
    )


def _dedupe_queries(queries: Sequence[str]) -> List[str]:
    deduped: List[str] = []
    seen_queries = set()
    for query in queries:
        normalized = _normalize_text(query)
        normalized_key = normalized.lower()
        if not normalized or normalized_key in seen_queries:
            continue
        seen_queries.add(normalized_key)
        deduped.append(normalized)
    return deduped


def _build_company_query_user_prompt(
    *,
    topic: str,
    candidate: CompetitiveLandscapeDiscoveryAgentCompany,
    location_context: LocationContext,
) -> str:
    geography = _location_label(location_context)
    reasons = "; ".join(candidate.reasons[:4]) or "market participation"
    return (
        "You are generating company-specific OSINT search queries for Competitive Landscape validation.\n\n"
        "Task:\n"
        "- Create search queries that verify whether the company is a real participant in the target market and geography.\n"
        "- Search for projects, portfolios, assets, installed capacity, ownership, developer activity, contracts, utility-scale presence, and market participation.\n"
        "- Start broad, then narrow into assets, projects, and portfolio evidence.\n"
        "- Avoid generic company overview queries unless needed as one fallback.\n\n"
        f"Input:\n- Market: {topic}\n- Geography: {geography}\n- Company: {candidate.company}\n- Discovery tier: {candidate.tier}\n- Discovery reasons: {reasons}\n\n"
        "Return JSON in this shape:\n"
        "{\n"
        '  "queries": [\n'
        "    {\n"
        '      "query": "Atlas Renewable Energy Chile projects",\n'
        '      "purpose": "verify local project footprint",\n'
        '      "priority": "high"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )


def _fallback_company_queries(
    *,
    topic: str,
    candidate: CompetitiveLandscapeDiscoveryAgentCompany,
    location_context: LocationContext,
) -> List[str]:
    geography = _location_label(location_context)
    company_name = candidate.company
    templates = [
        '"{company}" {geo} projects',
        '"{company}" {geo} solar portfolio',
        '"{company}" {geo} utility-scale assets',
        '"{company}" {geo} installed capacity',
        '"{company}" {geo} project ownership',
        '"{company}" "{topic}" {geo} developer',
        '"{company}" "{topic}" {geo} power plant',
        '"{company}" "{topic}" {geo} market share',
    ]
    return _dedupe_queries(
        [template.format(company=company_name, geo=geography, topic=topic) for template in templates]
    )[:8]


async def _generate_company_validation_queries(
    *,
    topic: str,
    candidate: CompetitiveLandscapeDiscoveryAgentCompany,
    location_context: LocationContext,
) -> List[str]:
    fallback_queries = _fallback_company_queries(
        topic=topic,
        candidate=candidate,
        location_context=location_context,
    )
    if not settings.OPENAI_API_KEY or not can_use_openai():
        return fallback_queries

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY.strip())
    try:
        response = await call_openai(
            "generate_cl_discovery_company_queries",
            lambda: client.responses.parse(
                model=DISCOVERY_QUERY_MODEL_NAME,
                input=[{"role": "user", "content": _build_company_query_user_prompt(
                    topic=topic,
                    candidate=candidate,
                    location_context=location_context,
                )}],
                text_format=ExampleSearchQueryResponse,
                max_output_tokens=ensure_min_output_tokens(900),
                temperature=0.2,
            ),
            fallback=None,
            timeout=DISCOVERY_QUERY_TIMEOUT_SECONDS,
            max_retries=DISCOVERY_QUERY_MAX_RETRIES,
            context={"model": DISCOVERY_QUERY_MODEL_NAME, "company": candidate.company},
        )
        if response is None:
            return fallback_queries
        parsed = _extract_parsed_query_output(response)
        llm_queries = _dedupe_queries([entry.query for entry in parsed.queries])
        return (llm_queries or fallback_queries)[:8]
    except Exception as exc:
        logger.warning("Competitive landscape discovery query generation failed company=%s error=%s", candidate.company, exc)
        return fallback_queries
    finally:
        await client.close()


def _build_company_evidence_blocks(stored_sources: Sequence[Dict[str, Any]], *, source_id_start: int) -> tuple[List[Dict[str, Any]], List[int]]:
    evidence_blocks: List[Dict[str, Any]] = []
    source_ids: List[int] = []
    next_source_id = source_id_start
    seen_signatures = set()
    for source in list(stored_sources)[:DISCOVERY_MAX_SOURCES_PER_COMPANY]:
        processed_payload = prepare_processed_content([dict(source)])
        cleaned_content = _normalize_text(processed_payload.get("processed_text", ""))
        if len(cleaned_content) < DISCOVERY_MIN_SOURCE_CHARS:
            cleaned_content = _normalize_text(source.get("content"))
        excerpt = cleaned_content[:2800].strip()
        signature = excerpt.lower()
        if not excerpt or signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        evidence_blocks.append(
            {
                "source_id": str(next_source_id),
                "title": _normalize_text(source.get("title")) or f"Source {next_source_id}",
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
                "content": excerpt,
            }
        )
        source_ids.append(next_source_id)
        next_source_id += 1
    return evidence_blocks, source_ids


async def discover_competitive_landscape_candidates(
    *,
    topic: str,
    location_context: LocationContext,
    max_candidates: int = DISCOVERY_MAX_CANDIDATES,
) -> CompetitiveLandscapeDiscoveryAgentOutput:
    api_key = settings.OPENAI_API_KEY.strip()
    if not api_key or not can_use_openai():
        raise RuntimeError("OpenAI is unavailable for competitive landscape market discovery.")

    client = AsyncOpenAI(api_key=api_key)
    try:
        response = await call_openai(
            "competitive_landscape_market_discovery",
            lambda: client.responses.parse(
                model=DISCOVERY_MODEL_NAME,
                input=[{"role": "user", "content": _build_market_discovery_prompt(
                    topic=topic,
                    location_context=location_context,
                    max_candidates=max_candidates,
                )}],
                text_format=CompetitiveLandscapeDiscoveryAgentOutput,
                max_output_tokens=ensure_min_output_tokens(2200),
                temperature=0.1,
            ),
            fallback=None,
            timeout=DISCOVERY_TIMEOUT_SECONDS,
            max_retries=DISCOVERY_MAX_RETRIES,
            context={"model": DISCOVERY_MODEL_NAME, "topic": topic, "location": _location_label(location_context)},
        )
        if response is None:
            raise RuntimeError("Competitive landscape discovery agent returned no response.")
        parsed = _extract_parsed_agent_output(response)
        return CompetitiveLandscapeDiscoveryAgentOutput(
            companies=list(parsed.companies or [])[:max_candidates],
        )
    finally:
        await client.close()


async def build_competitive_landscape_v2_discovery_bundle(
    *,
    topic: str,
    location_context: LocationContext,
    session_id: str,
    max_candidates: int = DISCOVERY_MAX_CANDIDATES,
) -> Dict[str, Any]:
    discovery_output = await discover_competitive_landscape_candidates(
        topic=topic,
        location_context=location_context,
        max_candidates=max_candidates,
    )

    major_players: List[CompetitiveLandscapeDiscoveryCompany] = []
    emerging_players: List[CompetitiveLandscapeDiscoveryCompany] = []
    all_evidence_blocks: List[Dict[str, Any]] = []
    query_diagnostics: List[Dict[str, Any]] = []
    global_source_id = 1

    for candidate_index, candidate in enumerate(discovery_output.companies, start=1):
        queries = await _generate_company_validation_queries(
            topic=topic,
            candidate=candidate,
            location_context=location_context,
        )
        search_payload = await search_queries(
            f"{topic} {candidate.company}",
            list(queries),
            freshness="high",
            location_context=location_context,
            workflow="company_research",
        )
        search_results = list(search_payload.get("results", []))[:DISCOVERY_MAX_SEARCH_RESULTS]
        stored_sources: List[Dict[str, Any]] = []
        evidence_blocks: List[Dict[str, Any]] = []
        source_ids: List[int] = []
        if search_results:
            artifact_bundle = await collect_research_artifacts(
                topic=f"{topic} {candidate.company}",
                section="company_profile",
                session_id=f"{session_id}_cl_discovery_{candidate_index}",
                location_context=location_context,
                search_results=search_results,
            )
            stored_sources = await asyncio.to_thread(load_saved_sources, list(artifact_bundle.get("artifacts", [])))
            evidence_blocks, source_ids = _build_company_evidence_blocks(
                stored_sources,
                source_id_start=global_source_id,
            )
            global_source_id += len(source_ids)
            all_evidence_blocks.extend(evidence_blocks)

        query_diagnostics.append(
            {
                "company": candidate.company,
                "tier": candidate.tier,
                "confidence": int(candidate.confidence),
                "reasons": list(candidate.reasons),
                "queries": list(queries),
                "search_results": len(search_results),
                "stored_sources": len(stored_sources),
                "evidence_blocks": len(evidence_blocks),
            }
        )

        discovered_company = CompetitiveLandscapeDiscoveryCompany(
            company_name=candidate.company,
            market_role=candidate.tier,
            source_ids=source_ids,
        )
        if candidate.tier == "Major Player":
            major_players.append(discovered_company)
        else:
            emerging_players.append(discovered_company)

    return {
        "discovery_output": CompetitiveLandscapeDiscoveryOutput(
            major_players=major_players,
            emerging_players=emerging_players,
        ),
        "evidence_blocks": all_evidence_blocks,
        "agent_output": discovery_output,
        "query_diagnostics": query_diagnostics,
    }
