import logging
import time
from typing import Any, Dict, List

from services.content_processor import prepare_processed_content
from services.location_service import LocationContext
from services.query_generator import generate_search_queries
from services.scraper_service import collect_research_artifacts, load_saved_sources
from services.search_service import search_queries

logger = logging.getLogger(__name__)

DEBUG = True


def _log(message: str) -> None:
    logger.info(message)
    if DEBUG:
        print(message)


def _elapsed_ms(start_time: float) -> int:
    return int((time.perf_counter() - start_time) * 1000)


async def execute_pipeline(
    topic: str,
    section: str,
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
            location_context=resolved_location_context,
            search_results=search_results,
        )
    except Exception as exc:
        logger.exception("Pipeline scraping failed for topic %s section %s", topic, section)
        _log(f"[PIPELINE] Scraping failed | error={exc}")
    execution_time["scrape_ms"] = _elapsed_ms(scrape_start)

    process_start = time.perf_counter()
    try:
        stored_sources = load_saved_sources(list(artifact_bundle.get("artifacts", [])))
        if stored_sources:
            processed_payload = prepare_processed_content(
                stored_sources,
            )
        else:
            _log("[PIPELINE] No stored sources passed content processing.")
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

