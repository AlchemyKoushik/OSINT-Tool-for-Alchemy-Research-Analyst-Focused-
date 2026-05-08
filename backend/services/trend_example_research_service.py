from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Sequence

from services.content_processor import prepare_processed_content
from services.location_service import LocationContext
from services.openai_service import extract_validated_examples_from_evidence
from services.prompt_builder import build_trend_example_extraction_payload
from services.scraper_service import collect_research_artifacts, load_saved_sources
from services.search_service import search_queries

logger = logging.getLogger(__name__)

MAX_EXAMPLE_RESEARCH_QUERIES = 4
MAX_EXAMPLE_RESULTS = 12
MAX_TRENDS_WITH_EXAMPLE_RESEARCH = 6
MAX_EXAMPLES_PER_TREND = 2
MAX_CONCURRENT_TREND_RESEARCH = 2
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


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _tokenize(value: str) -> List[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9][a-z0-9&/%-]{2,}", _normalize_text(value).lower())
        if token not in STOPWORDS
    ]


def _recent_year_tokens() -> str:
    current_year = datetime.utcnow().year
    recent_years = [str(current_year - offset) for offset in range(0, 3)]
    return " ".join(recent_years)


def _build_trend_example_queries(
    *,
    topic: str,
    trend_heading: str,
    trend_body: str,
    location_context: LocationContext,
) -> List[str]:
    geo = "" if location_context.is_global else location_context.value
    trend_terms = _tokenize(trend_heading)[:5]
    body_terms = _tokenize(trend_body)[:6]
    focus_terms = " ".join(dict.fromkeys(trend_terms + body_terms))
    recent_years = _recent_year_tokens()
    combined_text = f"{trend_heading} {trend_body}".lower()
    event_frames = [
        "named company announcement press release date",
        "company launch partnership investment expansion date",
        "acquisition merger deal funding approval agreement date",
        "manufacturer operator project commercial scale up date",
        "recent company example event month year press release",
    ]
    if any(keyword in combined_text for keyword in ("m&a", "merger", "acquisition", "acquire", "consolidation")):
        event_frames.insert(0, "company acquired company merger deal announced date")
    if any(keyword in combined_text for keyword in ("price", "pricing", "cost", "inflation")):
        event_frames.insert(0, "company price increase surcharge contract repricing announced date")

    queries: List[str] = []
    seen = set()
    for frame in event_frames:
        query = _normalize_text(f"{geo} {topic} {trend_heading} {focus_terms} {frame} {recent_years}")
        normalized_key = query.lower()
        if not query or normalized_key in seen:
            continue
        seen.add(normalized_key)
        queries.append(query)
        if len(queries) >= MAX_EXAMPLE_RESEARCH_QUERIES:
            break
    return queries


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
        normalized_item["examples"] = []
        return normalized_item

    queries = _build_trend_example_queries(
        topic=topic,
        trend_heading=heading,
        trend_body=body,
        location_context=location_context,
    )
    if not queries:
        normalized_item["examples"] = []
        logger.warning("Trend example research generated zero queries heading=%s", heading)
        return normalized_item

    logger.info("Trend example research queries heading=%s count=%s", heading, len(queries))
    search_payload = await search_queries(
        f"{topic} {heading}",
        queries,
        freshness="high",
        location_context=location_context,
    )
    search_results = list(search_payload.get("results", []))[:MAX_EXAMPLE_RESULTS]
    if not search_results:
        normalized_item["examples"] = []
        logger.warning("Trend example research returned zero search results heading=%s", heading)
        return normalized_item

    artifact_bundle = await collect_research_artifacts(
        topic=f"{topic} {heading}",
        section=section,
        session_id=f"{session_id}_trend_examples_{item_index}",
        location_context=location_context,
        search_results=search_results,
    )
    stored_sources = await asyncio.to_thread(load_saved_sources, list(artifact_bundle.get("artifacts", [])))
    if not stored_sources:
        normalized_item["examples"] = []
        logger.warning("Trend example research returned zero stored sources heading=%s", heading)
        return normalized_item

    processed_payload = await asyncio.to_thread(prepare_processed_content, list(stored_sources))
    evidence_blocks = list(processed_payload.get("evidence_blocks", []))
    if not evidence_blocks:
        normalized_item["examples"] = []
        logger.warning("Trend example research produced zero evidence blocks heading=%s", heading)
        return normalized_item

    extraction_payload = build_trend_example_extraction_payload(
        topic=topic,
        section=section,
        trend_heading=heading,
        trend_body=body,
        location_context=location_context,
        evidence_blocks=evidence_blocks,
    )
    validated_examples = await extract_validated_examples_from_evidence(
        metadata=extraction_payload,
        section=section,
        evidence_blocks=evidence_blocks,
        log_context=f"trend_examples:{heading}",
    )
    normalized_item["examples"] = [
        {"text": example.text, "year": str(example.year or "").strip()}
        for example in validated_examples[:MAX_EXAMPLES_PER_TREND]
    ]
    logger.info(
        "Trend example research attached heading=%s examples=%s",
        heading,
        len(normalized_item["examples"]),
    )
    return normalized_item


async def enrich_items_with_researched_examples(
    *,
    items: Sequence[Dict[str, Any]],
    topic: str,
    section: str,
    location_context: LocationContext,
    session_id: str,
) -> List[Dict[str, Any]]:
    bounded_items = [dict(item) for item in list(items)[:MAX_TRENDS_WITH_EXAMPLE_RESEARCH]]
    if not bounded_items:
        return []

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
                fallback_item = dict(item)
                fallback_item["examples"] = []
                return fallback_item

    enriched_items = await asyncio.gather(
        *[_bounded(item, item_index) for item_index, item in enumerate(bounded_items, start=1)]
    )

    if len(items) > len(bounded_items):
        enriched_items.extend([dict(item) for item in list(items)[len(bounded_items):]])
        for item in enriched_items[len(bounded_items):]:
            item["examples"] = list(item.get("examples", [])) if isinstance(item.get("examples", []), list) else []

    return enriched_items
