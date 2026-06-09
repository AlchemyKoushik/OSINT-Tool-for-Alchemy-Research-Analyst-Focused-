import logging
import json
import asyncio
from typing import Any, Dict, List, Optional

from models.response_models import AnalyzeResponse, normalize_analyze_response_payload
from services.fallback_analysis import build_fallback_section_analysis
from services.location_service import LocationContext, resolve_location_context
from services.openai_service import generate_section_analysis
from services.prompt_builder import build_metadata_payload, get_prompt
from services.redis_service import get_session
from services.ranking_service import rank_and_limit_insights
from services.source_attribution_service import attach_sources_to_items
from services.storage_service import read_from_r2
from services.trend_example_research_service import enrich_items_with_researched_examples

logger = logging.getLogger(__name__)
FOLLOW_UP_INSIGHT_LIMIT = 5


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _build_evidence_blocks(existing_chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    evidence_blocks: List[Dict[str, Any]] = []
    for index, chunk in enumerate(existing_chunks, start=1):
        text = _normalize_text(chunk.get("text"))
        source_id = _normalize_text(chunk.get("source_id")) or str(index)
        source_title = _normalize_text(chunk.get("source_title")) or source_id
        source_url = _normalize_text(chunk.get("source_url") or chunk.get("url"))
        source_domain = _normalize_text(chunk.get("source_domain") or chunk.get("domain"))
        source_date = _normalize_text(chunk.get("source_date") or chunk.get("date"))
        if not text:
            continue
        evidence_blocks.append(
            {
                "source_id": source_id,
                "title": source_title,
                "date": source_date,
                "excerpt": text,
                "url": source_url,
                "domain": source_domain or "existing-research",
            }
        )
    return evidence_blocks


def _build_source_scores(existing_chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    source_scores: List[Dict[str, Any]] = []
    for index, chunk in enumerate(existing_chunks, start=1):
        source_id = _normalize_text(chunk.get("source_id")) or str(index)
        source_title = _normalize_text(chunk.get("source_title")) or source_id
        source_url = _normalize_text(chunk.get("source_url") or chunk.get("url"))
        source_domain = _normalize_text(chunk.get("source_domain") or chunk.get("domain"))
        source_scores.append(
            {
                "title": source_title,
                "url": source_url,
                "domain": source_domain or "existing-research",
                "artifact_type": "existing_chunk",
                "artifact_path": "",
                "score": 1,
                "location_score": 0,
                "location_matches": [],
                "newest_year": None,
                "years": [],
            }
        )
    return source_scores


def _validate_research_items(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []

    valid_items: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        heading = _normalize_text(item.get("heading") or item.get("title"))
        body = _normalize_text(item.get("body") or item.get("description"))
        if not heading or not body:
            continue

        valid_items.append(
            {
                "heading": heading,
                "body": body,
                "segment": _normalize_text(item.get("segment")),
                "market_role": _normalize_text(item.get("market_role")),
                "key_company_facts": list(item.get("key_company_facts", [])) if isinstance(item.get("key_company_facts", []), list) else [],
                "competitive_positioning": _normalize_text(item.get("competitive_positioning")),
                "examples": list(item.get("examples", [])) if isinstance(item.get("examples", []), list) else [],
                "sources": list(item.get("sources", [])) if isinstance(item.get("sources", []), list) else [],
                "source_ids": list(item.get("source_ids", [])) if isinstance(item.get("source_ids", []), list) else [],
            }
        )

    return valid_items


def _group_competitive_landscape_items(items: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    major_players: List[Dict[str, Any]] = []
    emerging_players: List[Dict[str, Any]] = []
    for item in items:
        normalized_item = dict(item)
        if str(normalized_item.get("segment", "")).strip().lower() == "major_players":
            major_players.append(normalized_item)
        else:
            if not str(normalized_item.get("segment", "")).strip():
                normalized_item["segment"] = "emerging_players"
            emerging_players.append(normalized_item)
    return major_players, emerging_players


async def analyze_existing_chunks(
    refined_query: str,
    chunks: List[Dict[str, Any]],
    metadata: Optional[Dict[str, Any]] = None,
    session_id: str | None = None,
) -> Dict[str, Any]:
    normalized_query = _normalize_text(refined_query)
    if not normalized_query:
        raise ValueError("refined_query is required.")

    resolved_chunks = list(chunks)
    if not resolved_chunks and session_id:
        session = get_session(session_id)
        cleaned_dump_key = _normalize_text(session.get("cleaned_dump_key"))
        if cleaned_dump_key:
            try:
                cleaned_blob = await asyncio.to_thread(read_from_r2, cleaned_dump_key)
                cleaned_data = json.loads(cleaned_blob.decode("utf-8", errors="ignore"))
                if isinstance(cleaned_data, dict):
                    resolved_chunks = list(cleaned_data.get("existing_chunks", []))
            except Exception as exc:
                logger.warning("Failed to load follow-up cleaned dump for session %s: %s", session_id, exc)

    usable_chunks = [chunk for chunk in resolved_chunks if _normalize_text(chunk.get("text"))]
    if not usable_chunks:
        empty_section = str((metadata or {}).get("section", "trends")).strip().lower() or "trends"
        empty_payload = {
            "section": empty_section,
            "title": "No strong insights found",
            "items": [
                {
                    "heading": "Market Activity Observed",
                    "body": "Aggregated sources indicate ongoing activity, but structured insights could not be generated reliably.",
                    "sources": [],
                    "source_ids": [],
                }
            ],
            "error": None,
            "session_id": session_id,
        }
        if empty_section == "competitive_landscape":
            empty_payload["major_players"] = []
            empty_payload["emerging_players"] = list(empty_payload["items"])
            empty_payload["items"][0]["segment"] = "emerging_players"
        return {
            **empty_payload,
        }

    resolved_metadata = metadata or {}
    section = str(resolved_metadata.get("section", "trends")).strip().lower() or "trends"
    location_context = resolve_location_context(
        str(resolved_metadata.get("location_preference", "global")).strip() or "global",
        _normalize_text(resolved_metadata.get("location_value")),
    )
    evidence_blocks = _build_evidence_blocks(usable_chunks)
    source_scores = _build_source_scores(usable_chunks)
    artifact_counts = {
        "usable_text_count": len(evidence_blocks),
        "existing_chunk_count": len(evidence_blocks),
    }
    processed_text = "\n\n".join(block["excerpt"] for block in evidence_blocks if block.get("excerpt"))

    try:
        system_prompt = get_prompt(section, max_items=FOLLOW_UP_INSIGHT_LIMIT)
        metadata_payload = build_metadata_payload(
            topic=normalized_query,
            section=section,
            processed_sources=processed_text,
            location_context=location_context,
            evidence_blocks=evidence_blocks,
            source_scores=source_scores,
            artifact_counts=artifact_counts,
            max_items=FOLLOW_UP_INSIGHT_LIMIT,
        )
        analysis_json = await generate_section_analysis(
            system_prompt,
            metadata_payload,
            section,
            max_items=FOLLOW_UP_INSIGHT_LIMIT,
            evidence_blocks=evidence_blocks,
        )
    except Exception as exc:
        logger.exception("Analyze existing chunks failed for query %s", normalized_query)
        analysis_json = build_fallback_section_analysis(
            topic=normalized_query,
            processed_text=processed_text,
            section=section,
        )

    analysis_json = normalize_analyze_response_payload(analysis_json, fallback_section=section)
    if section == "competitive_landscape":
        analysis_json["major_players"] = attach_sources_to_items(
            rank_and_limit_insights(list(analysis_json.get("major_players", [])), limit=FOLLOW_UP_INSIGHT_LIMIT),
            evidence_blocks,
            max_sources_per_item=6,
        )
        analysis_json["emerging_players"] = attach_sources_to_items(
            rank_and_limit_insights(list(analysis_json.get("emerging_players", [])), limit=FOLLOW_UP_INSIGHT_LIMIT),
            evidence_blocks,
            max_sources_per_item=6,
        )
        sourced_items = [*analysis_json["major_players"], *analysis_json["emerging_players"]]
    else:
        ranked_items = rank_and_limit_insights(
            list(analysis_json.get("items", [])),
            limit=FOLLOW_UP_INSIGHT_LIMIT,
        )
        sourced_items = attach_sources_to_items(
            list(ranked_items),
            evidence_blocks,
        )
    sourced_items = await enrich_items_with_researched_examples(
        items=list(sourced_items),
        topic=normalized_query,
        section=section,
        location_context=location_context,
        session_id=session_id or "followup_examples",
    )
    validated_items = _validate_research_items(sourced_items)
    if not validated_items:
        logger.warning("Invalid or empty LLM output for analyze_existing_chunks; applying fallback.")
        validated_items = [
            {
                "heading": "Market Activity Observed",
                "body": "Aggregated sources indicate ongoing activity, but structured insights could not be generated reliably.",
                "sources": [],
                "source_ids": [],
            }
        ]
    analysis_json["items"] = validated_items
    if section == "competitive_landscape":
        major_players, emerging_players = _group_competitive_landscape_items(validated_items)
        analysis_json["major_players"] = major_players
        analysis_json["emerging_players"] = emerging_players
    if not _normalize_text(analysis_json.get("title")):
        analysis_json["title"] = "No strong insights found"

    validated = AnalyzeResponse(**analysis_json)
    response_payload = validated.model_dump()
    response_payload["error"] = None
    response_payload["session_id"] = session_id
    response_payload["meta"] = {
        "topic": normalized_query,
        "location": {"label": location_context.label, "value": location_context.value, "preference": location_context.preference},
    }
    response_payload["debug"] = {
        "existing_chunks": [
            {
                "text": block["excerpt"],
                "source_id": block["source_id"],
                "source_title": block["title"],
                "source_url": block["url"],
                "source_domain": block["domain"],
                "source_date": block["date"],
            }
            for block in evidence_blocks
        ],
        "num_sources": len(evidence_blocks),
        "source_scores": source_scores,
        "artifact_counts": artifact_counts,
    }
    return response_payload

