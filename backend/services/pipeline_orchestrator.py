import logging
import time
import json
import asyncio
from typing import Any, Dict, List

from services.content_processor import prepare_processed_content
from services.location_service import LocationContext
from services.redis_service import update_session
from services.query_generator import generate_search_queries
from services.scraper_service import collect_research_artifacts, load_saved_sources
from services.search_service import search_queries
from services.storage_service import upload_to_r2

logger = logging.getLogger(__name__)

DEBUG = True


def _log(message: str) -> None:
    logger.info("%s", message)


def _elapsed_ms(start_time: float) -> int:
    return int((time.perf_counter() - start_time) * 1000)


async def execute_pipeline(
    topic: str,
    section: str,
    session_id: str,
    freshness: str = "high",
    location_context: LocationContext | None = None,
    provided_queries: List[str] | None = None,
) -> Dict[str, Any]:
    # Keep orchestration in one place so the API route gets a single bounded, observable pipeline call.
    resolved_location_context = location_context or LocationContext()
    _log(f"[PIPELINE] Start | topic={topic} | section={section}")
    execution_time: Dict[str, int] = {}

    queries: List[str] = []
    search_results: List[Dict[str, Any]] = []
    query_performance: Dict[str, Any] = {}
    artifact_bundle: Dict[str, Any] = {
        "artifact_dir": "",
        "manifest_path": "",
        "artifacts": [],
        "counts": {},
        "pages": [],
    }
    processed_payload: Dict[str, Any] = {
        "processed_text": "",
        "evidence_blocks": [],
        "selected_urls": [],
        "num_sources": 0,
        "processing_chars": 0,
        "source_scores": [],
        "signal_weights": [],
    }

    query_start = time.perf_counter()
    try:
        if provided_queries:
            queries = [str(query).strip() for query in provided_queries if str(query).strip()]
            _log(f"[PIPELINE] Using provided queries | count={len(queries)}")
        else:
            queries = await generate_search_queries(
                topic,
                section,
                location_context=resolved_location_context,
            )
    except Exception as exc:
        logger.exception("Pipeline query generation failed for topic %s section %s", topic, section)
        _log(f"[PIPELINE] Query generation failed | error={exc}")
        queries = []
    execution_time["query_ms"] = _elapsed_ms(query_start)

    search_start = time.perf_counter()
    try:
        search_payload = await search_queries(
            topic,
            queries,
            freshness=freshness,
            location_context=resolved_location_context,
        )
        queries = list(search_payload.get("queries", queries))
        search_results = list(search_payload.get("results", []))
        query_performance = dict(search_payload.get("query_performance", {}))
    except Exception as exc:
        logger.exception("Pipeline search failed for topic %s section %s", topic, section)
        _log(f"[PIPELINE] Search failed | error={exc}")
    execution_time["search_ms"] = _elapsed_ms(search_start)

    scrape_start = time.perf_counter()
    try:
        artifact_bundle = await collect_research_artifacts(
            topic=topic,
            section=section,
            session_id=session_id,
            location_context=resolved_location_context,
            search_results=search_results,
        )
    except Exception as exc:
        logger.exception("Pipeline scraping failed for topic %s section %s", topic, section)
        _log(f"[PIPELINE] Scraping failed | error={exc}")
    execution_time["scrape_ms"] = _elapsed_ms(scrape_start)

    process_start = time.perf_counter()
    try:
        stored_sources = await asyncio.to_thread(load_saved_sources, list(artifact_bundle.get("artifacts", [])))
        scraped_results = list(stored_sources) if stored_sources else list(artifact_bundle.get("pages", []))
        if stored_sources:
            processed_payload = prepare_processed_content(
                stored_sources,
            )
        else:
            _log("[PIPELINE] No stored sources passed content processing.")

        cleaned_dump_payload = {
            "existing_chunks": [
                {
                    "text": str(block.get("excerpt", "")).strip(),
                    "source_id": str(block.get("source_id", "")).strip(),
                    "source_title": str(block.get("title", "")).strip(),
                    "source_url": str(block.get("url", "")).strip(),
                    "source_domain": str(block.get("domain", "")).strip(),
                    "source_date": str(block.get("date", "")).strip(),
                }
                for block in processed_payload.get("evidence_blocks", [])
                if str(block.get("excerpt", "")).strip()
            ],
            "evidence_blocks": list(processed_payload.get("evidence_blocks", [])),
            "selected_urls": list(processed_payload.get("selected_urls", [])),
            "num_sources": int(processed_payload.get("num_sources", 0)),
        }
        cleaned_data = json.dumps(cleaned_dump_payload, indent=2) if cleaned_dump_payload["existing_chunks"] else ""

        logger.info("cleaned_dump_prepared chars=%s session_id=%s", len(cleaned_data) if cleaned_data else 0, session_id)

        if not cleaned_data:
            logger.warning("cleaned_data empty; using fallback session_id=%s", session_id)
            try:
                combined_text = ""
                for item in scraped_results:
                    if isinstance(item, dict):
                        combined_text += str(item.get("content", "") or "") + "\n"

                cleaned_data = combined_text[:50000]
            except Exception as exc:
                logger.warning("Fallback cleaning failed for session %s: %s", session_id, exc)
                cleaned_data = "Fallback empty content"

        if not cleaned_data:
            logger.warning("Empty cleaned_data after fallback for session %s", session_id)
            cleaned_data = "No structured cleaned data available"

        cleaned_key = await asyncio.to_thread(
            upload_to_r2,
            session_id,
            "cleaned_dump.json",
            cleaned_data,
        )

        if cleaned_key:
            logger.info("cleaned_dump_uploaded session_id=%s key=%s", session_id, cleaned_key)
            update_session(session_id, {"cleaned_dump_key": cleaned_key})
        else:
            logger.warning("cleaned_dump_upload_failed session_id=%s", session_id)

        update_session(
            session_id,
            {
                "query": topic,
                "queries_generated": queries,
                "sources": list(processed_payload.get("selected_urls", [])),
                "cleaned_dump_key": cleaned_key,
                "artifacts": [
                    str(artifact.get("text_key") or artifact.get("binary_key") or artifact.get("text_path") or "").strip()
                    for artifact in artifact_bundle.get("artifacts", [])
                    if str(artifact.get("text_key") or artifact.get("binary_key") or artifact.get("text_path") or "").strip()
                ],
            },
        )
        logger.info("session_updated_with_cleaned_dump session_id=%s", session_id)
        processed_payload["cleaned_dump_key"] = cleaned_key
    except Exception as exc:
        logger.exception("Pipeline processing failed for topic %s section %s", topic, section)
        _log(f"[PIPELINE] Processing failed | error={exc}")
    execution_time["processing_ms"] = _elapsed_ms(process_start)

    _log("[PIPELINE] Completed")
    return {
        "queries": queries,
        "search_results": search_results,
        "query_performance": query_performance,
        "artifact_bundle": artifact_bundle,
        "processed_payload": processed_payload,
        "execution_time": execution_time,
    }

