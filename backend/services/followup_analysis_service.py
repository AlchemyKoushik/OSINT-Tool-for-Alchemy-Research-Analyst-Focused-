import logging
from typing import Any, Dict, List, Optional

from models.response_models import AnalyzeResponse
from services.fallback_analysis import build_fallback_section_analysis
from services.location_service import LocationContext, resolve_location_context
from services.openai_service import generate_section_analysis
from services.prompt_builder import build_metadata_payload, get_prompt
from services.ranking_service import rank_and_limit_insights
from services.source_attribution_service import attach_sources_to_items

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


async def analyze_existing_chunks(
    refined_query: str,
    chunks: List[Dict[str, Any]],
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized_query = _normalize_text(refined_query)
    if not normalized_query:
        raise ValueError("refined_query is required.")

    usable_chunks = [chunk for chunk in chunks if _normalize_text(chunk.get("text"))]
    if not usable_chunks:
        return {
            "section": str((metadata or {}).get("section", "trends")).strip().lower() or "trends",
            "title": "No strong insights found",
            "items": [],
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

    analysis_json["items"] = rank_and_limit_insights(
        list(analysis_json.get("items", [])),
        limit=FOLLOW_UP_INSIGHT_LIMIT,
    )
    analysis_json["items"] = attach_sources_to_items(
        list(analysis_json.get("items", [])),
        evidence_blocks,
    )
    if not analysis_json["items"]:
        analysis_json["title"] = "No strong insights found"

    validated = AnalyzeResponse(**analysis_json)
    response_payload = validated.model_dump()
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

