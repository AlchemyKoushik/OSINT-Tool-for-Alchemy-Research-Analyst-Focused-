import logging
import time
import json
import asyncio
from typing import Any, Dict, List

from config.settings import settings
from core.diagnostics import ProgressCallback, ResearchDiagnostics
from services.content_processor import prepare_processed_content
from services.location_service import LocationContext
from services.redis_service import update_session
from services.query_generator import generate_search_queries
from services.scraper_service import collect_research_artifacts, load_saved_sources
from services.search_service import search_queries
from services.storage_service import upload_to_r2

logger = logging.getLogger(__name__)

DEBUG = True
MAX_PIPELINE_SCRAPE_RESULTS = max(20, min(int(settings.MAX_PIPELINE_SCRAPE_RESULTS), 200))
SCRAPE_BATCH_SIZE = max(4, min(int(settings.SCRAPE_BATCH_SIZE), 25))
TARGET_USABLE_TEXT_COUNT = max(10, min(int(settings.TARGET_USABLE_TEXT_COUNT), MAX_PIPELINE_SCRAPE_RESULTS))
SCRAPE_TIME_BUDGET_SECONDS = max(60, int(settings.SCRAPE_TIME_BUDGET_SECONDS))


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
    progress_callback: ProgressCallback | None = None,
    diagnostics: ResearchDiagnostics | None = None,
) -> Dict[str, Any]:
    # Keep orchestration in one place so the API route gets a single bounded, observable pipeline call.
    resolved_location_context = location_context or LocationContext()
    _log(f"[PIPELINE] Start | topic={topic} | section={section}")
    execution_time: Dict[str, int] = {}

    queries: List[str] = []
    search_results: List[Dict[str, Any]] = []
    query_performance: Dict[str, Any] = {}
    search_diagnostics: Dict[str, Any] = {}
    stage_errors: Dict[str, str] = {}
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
    if diagnostics is not None and progress_callback is not None:
        progress_callback(
            diagnostics.mark_stage(
                "Query Generation",
                activity="Generating search queries",
                progress=22,
            )
        )
    _log(f"[PIPELINE] Query generation started | session_id={session_id}")
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
        stage_errors["query_generation"] = str(exc)
        queries = []
    if not queries:
        stage_errors.setdefault("query_generation", "Query generation returned no usable queries.")
    execution_time["query_ms"] = _elapsed_ms(query_start)
    _log(f"[PIPELINE] Query generation completed | count={len(queries)} | ms={execution_time['query_ms']} | session_id={session_id}")

    search_start = time.perf_counter()
    if diagnostics is not None and progress_callback is not None:
        progress_callback(
            diagnostics.mark_stage(
                "Search",
                activity="Searching source candidates",
                progress=32,
            )
        )
    _log(f"[PIPELINE] Search started | query_count={len(queries)} | session_id={session_id}")
    try:
        search_payload = await search_queries(
            topic,
            queries,
            freshness=freshness,
            location_context=resolved_location_context,
            workflow=section,
        )
        queries = list(search_payload.get("queries", queries))
        search_results = list(search_payload.get("results", []))
        query_performance = dict(search_payload.get("query_performance", {}))
        search_diagnostics = dict(search_payload.get("diagnostics", {}))
    except Exception as exc:
        logger.exception("Pipeline search failed for topic %s section %s", topic, section)
        _log(f"[PIPELINE] Search failed | error={exc}")
        stage_errors["search"] = str(exc)
    if queries and not search_results:
        stage_errors.setdefault(
            "search",
            f"Search returned no usable results after filtering across {len(queries)} queries.",
        )
    execution_time["search_ms"] = _elapsed_ms(search_start)
    _log(f"[PIPELINE] Search completed | results={len(search_results)} | ms={execution_time['search_ms']} | session_id={session_id}")

    scrape_start = time.perf_counter()
    if diagnostics is not None and progress_callback is not None:
        progress_callback(
            diagnostics.mark_stage(
                "Scraping",
                activity="Scraping URLs and collecting artifacts",
                progress=44,
                urls_processed=len(search_results),
            )
        )
    _log(f"[PIPELINE] Scraping started | candidate_results={len(search_results)} | session_id={session_id}")
    try:
        prioritized_search_results = list(search_results[:MAX_PIPELINE_SCRAPE_RESULTS])
        artifact_bundle = await collect_research_artifacts(
            topic=topic,
            section=section,
            session_id=session_id,
            location_context=resolved_location_context,
            search_results=prioritized_search_results,
            batch_size=SCRAPE_BATCH_SIZE,
            target_usable_text_count=TARGET_USABLE_TEXT_COUNT,
            max_duration_seconds=SCRAPE_TIME_BUDGET_SECONDS,
        )
    except Exception as exc:
        logger.exception("Pipeline scraping failed for topic %s section %s", topic, section)
        _log(f"[PIPELINE] Scraping failed | error={exc}")
        stage_errors["scraping"] = str(exc)
    if search_results:
        successful_artifacts = sum(
            1 for artifact in artifact_bundle.get("artifacts", []) if str(artifact.get("status", "")).strip() == "success"
        )
        if successful_artifacts == 0:
            stage_errors.setdefault(
                "scraping",
                f"Scraping completed without any successful artifacts from {len(search_results)} candidate results.",
            )
    execution_time["scrape_ms"] = _elapsed_ms(scrape_start)
    _log(
        f"[PIPELINE] Scraping completed | usable_artifacts={artifact_bundle.get('counts', {}).get('usable_text_count', 0)} "
        f"| success={artifact_bundle.get('counts', {}).get('success_count', 0)} | ms={execution_time['scrape_ms']} | session_id={session_id}"
    )

    process_start = time.perf_counter()
    if diagnostics is not None and progress_callback is not None:
        progress_callback(
            diagnostics.mark_stage(
                "Validation",
                activity="Processing scraped content into evidence",
                progress=56,
                urls_processed=int(artifact_bundle.get("counts", {}).get("success_count", 0)),
                documents_processed=int(artifact_bundle.get("counts", {}).get("usable_text_count", 0)),
            )
        )
    _log(f"[PIPELINE] Content processing started | session_id={session_id}")
    try:
        stored_sources = await asyncio.to_thread(load_saved_sources, list(artifact_bundle.get("artifacts", [])))
        scraped_results = list(stored_sources) if stored_sources else list(artifact_bundle.get("pages", []))
        if stored_sources:
            processed_payload = prepare_processed_content(
                stored_sources,
            )
        else:
            _log("[PIPELINE] No stored sources passed content processing.")
            if scraped_results:
                stage_errors.setdefault(
                    "processing",
                    "Stored artifacts were created, but none produced usable processed content.",
                )

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

        if not cleaned_dump_payload["existing_chunks"] and scraped_results:
            cleaned_dump_payload["existing_chunks"] = [
                {
                    "text": str(item.get("content", "")).strip()[: settings.MAX_CHUNK_TEXT_LENGTH],
                    "source_id": f"fallback_{index}",
                    "source_title": str(item.get("title", "")).strip() or f"Fallback Source {index}",
                    "source_url": str(item.get("url", "")).strip(),
                    "source_domain": str(item.get("domain", "")).strip(),
                    "source_date": "",
                }
                for index, item in enumerate(scraped_results, start=1)
                if str(item.get("content", "")).strip()
            ][: settings.MAX_EXISTING_CHUNKS]

        if not cleaned_dump_payload["evidence_blocks"] and cleaned_dump_payload["existing_chunks"]:
            cleaned_dump_payload["evidence_blocks"] = [
                {
                    "source_id": chunk["source_id"],
                    "title": chunk["source_title"],
                    "date": chunk["source_date"],
                    "excerpt": chunk["text"],
                    "url": chunk["source_url"],
                    "domain": chunk["source_domain"],
                }
                for chunk in cleaned_dump_payload["existing_chunks"]
            ]
            cleaned_dump_payload["selected_urls"] = [
                chunk["source_url"] or chunk["source_id"] for chunk in cleaned_dump_payload["existing_chunks"]
            ]
            cleaned_dump_payload["num_sources"] = len(cleaned_dump_payload["existing_chunks"])

        cleaned_dump_payload["raw_fallback_text"] = ""
        if not cleaned_dump_payload["existing_chunks"]:
            logger.warning("cleaned_data empty; using fallback session_id=%s", session_id)
            try:
                combined_text = ""
                for item in scraped_results:
                    if isinstance(item, dict):
                        combined_text += str(item.get("content", "") or "") + "\n"
                cleaned_dump_payload["raw_fallback_text"] = combined_text[:50000]
            except Exception as exc:
                logger.warning("Fallback cleaning failed for session %s: %s", session_id, exc)
                cleaned_dump_payload["raw_fallback_text"] = "Fallback empty content"

        cleaned_data = json.dumps(cleaned_dump_payload, indent=2)

        logger.info("cleaned_dump_prepared chars=%s session_id=%s", len(cleaned_data) if cleaned_data else 0, session_id)

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
        stage_errors["processing"] = str(exc)
    if not str(processed_payload.get("processed_text", "")).strip():
        stage_errors.setdefault(
            "processing",
            "Processing finished without any usable text in the final evidence bundle.",
        )
    execution_time["processing_ms"] = _elapsed_ms(process_start)
    _log(
        f"[PIPELINE] Content processing completed | sources={processed_payload.get('num_sources', 0)} "
        f"| chars={processed_payload.get('processing_chars', 0)} | ms={execution_time['processing_ms']} | session_id={session_id}"
    )

    _log("[PIPELINE] Completed")
    return {
        "queries": queries,
        "search_results": search_results,
        "query_performance": query_performance,
        "search_diagnostics": search_diagnostics,
        "artifact_bundle": artifact_bundle,
        "processed_payload": processed_payload,
        "stage_errors": stage_errors,
        "execution_time": execution_time,
    }

