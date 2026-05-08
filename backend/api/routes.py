import logging
import time
import json
import asyncio
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request

from config.settings import settings
from models.request_models import AnalyzeExistingRequest, AnalyzeRequest, FollowUpRequest
from models.response_models import AnalyzeResponse, normalize_analyze_response_payload
from services.cache_service import get_cached_result, set_cached_result
from services.fallback_analysis import build_fallback_section_analysis
from services.followup_analysis_service import analyze_existing_chunks
from services.followup_query_service import handle_followup_query
from services.location_service import (
    LocationContext,
    build_location_topic_key,
    describe_location_context,
    get_location_catalog,
    get_location_signature,
    resolve_location_context,
)
from services.memory_service import (
    get_best_sources_for_topic,
    get_feedback_adjustment,
    store_feedback,
    update_best_sources_for_topic,
    update_domain_authority,
)
from services.openai_service import generate_section_analysis
from services.pipeline_orchestrator import execute_pipeline
from services.prompt_builder import build_metadata_payload, get_prompt
from services.redis_service import check_rate_limit, delete_session, get_session, update_session
from services.ranking_service import rank_and_limit_insights
from services.session_service import create_session_id
from services.source_attribution_service import attach_sources_to_items
from services.storage_service import delete_session_prefix, read_from_r2
from services.trend_example_research_service import enrich_items_with_researched_examples

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

PIPELINE_VERSION = "artifact_sot_v8_company_event_examples"
INTERNAL_DEPTH = "high"
INTERNAL_FRESHNESS = "high"
MAX_WEB_SCRAPE_URLS = 100
INITIAL_INSIGHT_LIMIT = 10
FOLLOW_UP_INSIGHT_LIMIT = 5


def _sanitize_for_log(value: str, limit: int = 120) -> str:
    normalized = " ".join(str(value or "").split())
    return normalized[:limit] + ("..." if len(normalized) > limit else "")


async def _read_json_payload(request: Request) -> Dict[str, Any]:
    raw_body = await request.body()
    if not raw_body:
        raise ValueError("Empty request body.")
    if len(raw_body) > settings.MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="Request payload too large.")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON payload: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("JSON payload must be an object.")
    return payload


def _build_rate_limit_identity(request: Request, session_id: str | None) -> str:
    normalized_session_id = str(session_id or "").strip()
    if normalized_session_id:
        return normalized_session_id

    if request.client and request.client.host:
        return str(request.client.host).strip()
    return "unknown"


def _enforce_rate_limit(request: Request, route_name: str, session_id: str | None) -> None:
    allowed, retry_after = check_rate_limit(
        _build_rate_limit_identity(request, session_id),
        route_name=route_name,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Retry after {retry_after} seconds.",
        )


def _elapsed_ms(start_time: float) -> int:
    return int((time.perf_counter() - start_time) * 1000)


def _normalize_depth(depth: str) -> str:
    return depth if depth in {"low", "medium", "high"} else "medium"


def _normalize_freshness(freshness: str) -> str:
    return freshness if freshness in {"low", "high"} else "high"


def _build_cache_key(
    topic: str,
    section: str,
    depth: str,
    freshness: str,
    feedback_summary: Dict[str, Any],
    location_signature: str,
) -> str:
    return (
        f"{topic.strip()}::pipeline={PIPELINE_VERSION}::section={section}::depth={depth}::freshness={freshness}"
        f"::location={location_signature}"
        f"::rating={float(feedback_summary.get('avg_rating', 0.0)):.2f}"
        f"::rating_count={int(feedback_summary.get('rating_count', 0))}"
    )


def _dedupe_urls(urls: List[str]) -> List[str]:
    unique_urls: List[str] = []
    seen_urls = set()
    for url in urls:
        normalized_url = str(url).strip()
        if not normalized_url or normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        unique_urls.append(normalized_url)
    return unique_urls


def _extract_domain(url: str) -> str:
    parsed = urlparse(str(url).strip())
    domain = parsed.netloc.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def _is_probable_pdf_url(url: str) -> bool:
    lower_url = str(url).strip().lower()
    return lower_url.endswith(".pdf") or ".pdf?" in lower_url or "filetype:pdf" in lower_url


def _select_pdf_results(search_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pdf_results: List[Dict[str, Any]] = []
    seen_urls: Set[str] = set()

    for result in search_results:
        url = str(result.get("url", "")).strip()
        if not url or url in seen_urls:
            continue
        if not bool(result.get("is_pdf")) and not _is_probable_pdf_url(url):
            continue
        seen_urls.add(url)
        pdf_results.append(dict(result))

    return pdf_results


def _prioritize_web_results(
    ranked_results: List[Dict[str, Any]],
    search_results: List[Dict[str, Any]],
    remembered_urls: List[str],
) -> List[Dict[str, Any]]:
    result_lookup: Dict[str, Dict[str, Any]] = {}
    for result in search_results + ranked_results:
        url = str(result.get("url", "")).strip()
        if not url or url in result_lookup:
            continue
        result_lookup[url] = dict(result)

    ranked_urls = [str(result.get("url", "")).strip() for result in ranked_results if str(result.get("url", "")).strip()]
    search_urls = [str(result.get("url", "")).strip() for result in search_results if str(result.get("url", "")).strip()]
    prioritized_urls = _dedupe_urls(remembered_urls + ranked_urls + search_urls)
    prioritized_results: List[Dict[str, Any]] = []

    for url in prioritized_urls:
        if not url:
            continue

        result = dict(
            result_lookup.get(
                url,
                {
                    "url": url,
                    "title": "",
                    "snippet": "",
                    "domain": _extract_domain(url),
                    "is_pdf": _is_probable_pdf_url(url),
                },
            )
        )
        if bool(result.get("is_pdf")) or _is_probable_pdf_url(url):
            continue

        result["domain"] = str(result.get("domain", "")).strip() or _extract_domain(url)
        prioritized_results.append(result)
        if len(prioritized_results) >= MAX_WEB_SCRAPE_URLS:
            break

    return prioritized_results


def _build_debug_payload(
    queries: List[str],
    selected_urls: List[str],
    num_sources: int,
    processing_chars: int,
    prompt_chars: int,
    execution_time: Dict[str, int],
    cache_hit: bool,
    source_scores: List[Dict[str, Any]],
    detected_conflicts: List[Any],
    signal_weights: List[Dict[str, Any]],
    trend_metadata: List[Dict[str, Any]],
    query_performance: Dict[str, Any],
    stability_actions: List[Dict[str, Any]],
    historical_sources: List[str],
    feedback_summary: Dict[str, Any],
    section: str,
    depth: str,
    freshness: str,
    location: Dict[str, Any],
    artifact_dir: str = "",
    artifact_manifest: str = "",
    artifact_counts: Optional[Dict[str, Any]] = None,
    existing_chunks: Optional[List[Dict[str, Any]]] = None,
    stage_errors: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "queries": queries,
        "selected_urls": selected_urls,
        "num_sources": num_sources,
        "processing_chars": processing_chars,
        "prompt_chars": prompt_chars,
        "execution_time": execution_time,
        "cache_hit": cache_hit,
        "source_scores": source_scores,
        "detected_conflicts": detected_conflicts,
        "signal_weights": signal_weights,
        "trend_metadata": trend_metadata,
        "query_performance": query_performance,
        "stability_actions": stability_actions,
        "historical_sources": historical_sources,
        "feedback_summary": feedback_summary,
        "section": section,
        "depth": depth,
        "freshness": freshness,
        "location": location,
    }
    if artifact_dir:
        payload["artifact_dir"] = artifact_dir
    if artifact_manifest:
        payload["artifact_manifest"] = artifact_manifest
    if artifact_counts:
        payload["artifact_counts"] = artifact_counts
    if existing_chunks:
        payload["existing_chunks"] = existing_chunks
    if stage_errors:
        payload["stage_errors"] = stage_errors
    return payload
def _empty_insight_analysis() -> Dict[str, List[Any]]:
    return {"conflicts": [], "consensus_signals": []}


def _build_existing_chunks(evidence_blocks: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    chunks: List[Dict[str, str]] = []
    for index, block in enumerate(evidence_blocks, start=1):
        excerpt = str(block.get("excerpt", "")).strip()
        if not excerpt:
            continue
        source_id = str(block.get("source_id", "")).strip() or str(index)
        source_title = str(block.get("title", "")).strip() or f"Source {index}"
        chunks.append(
            {
                "text": excerpt,
                "source_id": source_id,
                "source_title": source_title,
                "source_url": str(block.get("url", "")).strip(),
                "source_domain": str(block.get("domain", "")).strip(),
                "source_date": str(block.get("date", "")).strip(),
            }
        )
    return chunks


def _load_session_cleaned_dump(session_id: str) -> Dict[str, Any]:
    session = get_session(session_id)
    cleaned_dump_key = str(session.get("cleaned_dump_key", "")).strip()
    if not cleaned_dump_key:
        raise HTTPException(status_code=404, detail="No cleaned session dump found for the provided session_id.")

    try:
        payload = read_from_r2(cleaned_dump_key).decode("utf-8", errors="ignore")
        parsed = json.loads(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load session cleaned dump: {exc}") from exc

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=500, detail="Session cleaned dump is malformed.")
    return parsed


def _resolve_session_existing_chunks(session_id: str | None, provided_chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if provided_chunks:
        return list(provided_chunks)
    if not session_id:
        return []
    cleaned_dump = _load_session_cleaned_dump(session_id)
    existing_chunks = cleaned_dump.get("existing_chunks", [])
    return list(existing_chunks) if isinstance(existing_chunks, list) else []


def _build_fail_safe_response(
    error_message: str,
    section: str = "",
    debug_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "section": section,
        "title": "",
        "items": [],
        "error": error_message,
    }
    if debug_payload is not None:
        payload["debug"] = debug_payload
    return payload


def _attach_session_id(payload: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    if session_id:
        payload["session_id"] = session_id
    return payload


def _resolve_insight_limit(follow_up_mode: bool) -> int:
    return FOLLOW_UP_INSIGHT_LIMIT if follow_up_mode else INITIAL_INSIGHT_LIMIT


@router.get("/locations")
async def get_locations() -> Dict[str, Any]:
    return get_location_catalog()


@router.post("/follow-up")
async def follow_up(request: Request) -> Dict[str, Any]:
    try:
        payload = await _read_json_payload(request)
        request_model = FollowUpRequest(**payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid follow-up payload: {exc}") from exc

    _enforce_rate_limit(request, "follow-up", request_model.session_id)
    return await asyncio.to_thread(
        handle_followup_query,
        follow_up_query=request_model.follow_up_query,
        existing_filtered_chunks=_resolve_session_existing_chunks(request_model.session_id, request_model.existing_chunks),
        existing_metadata=request_model.metadata,
    )


@router.post("/analyze-existing")
async def analyze_existing(request: Request) -> Dict[str, Any]:
    try:
        payload = await _read_json_payload(request)
        request_model = AnalyzeExistingRequest(**payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid analyze-existing payload: {exc}") from exc

    return await analyze_existing_chunks(
        refined_query=request_model.refined_query,
        chunks=_resolve_session_existing_chunks(request_model.session_id, request_model.existing_chunks),
        metadata=request_model.metadata,
        session_id=request_model.session_id,
    )


@router.post("/research")
async def research_topic(request: Request) -> Dict[str, Any]:
    return await analyze_topic(request)


@router.post("/analyze")
async def analyze_topic(request: Request) -> Dict[str, Any]:
    total_start = time.perf_counter()
    execution_time: Dict[str, int] = {}

    topic = ""
    topic_key = ""
    section = "trends"
    depth = INTERNAL_DEPTH
    freshness = INTERNAL_FRESHNESS
    debug_mode = False
    location_context = LocationContext()
    location_summary = describe_location_context(location_context)
    feedback_summary: Dict[str, Any] = {"avg_rating": 0.0, "rating_count": 0, "confidence_adjustment": 0}
    historical_sources: List[str] = []
    queries: List[str] = []
    selected_urls: List[str] = []
    evidence_blocks: List[Dict[str, Any]] = []
    num_sources = 0
    processing_chars = 0
    prompt_chars = 0
    source_scores: List[Dict[str, Any]] = []
    detected_conflicts: List[Any] = []
    signal_weights: List[Dict[str, Any]] = []
    trend_metadata: List[Dict[str, Any]] = []
    query_performance: Dict[str, Any] = {}
    stage_errors: Dict[str, Any] = {}
    stability_actions: List[Dict[str, Any]] = []
    artifact_dir = ""
    artifact_manifest = ""
    artifact_counts: Dict[str, Any] = {}
    existing_chunks: List[Dict[str, Any]] = []
    provided_queries: List[str] = []
    session_id = ""
    follow_up_mode = False
    provided_existing_chunks: List[Dict[str, Any]] = []

    try:
        try:
            payload = await _read_json_payload(request)
        except Exception as exc:
            logger.warning("Analyze payload read failed: %s", exc)
            return _build_fail_safe_response("Invalid JSON payload.", section=section)

        try:
            request_model = AnalyzeRequest(**payload)
        except Exception as exc:
            logger.warning("Analyze payload validation failed: %s", exc)
            return _build_fail_safe_response(f"Invalid request payload: {exc}", section=section)

        topic = request_model.topic.strip()
        section = request_model.section
        debug_mode = bool(request_model.debug)
        provided_queries = list(request_model.queries)
        session_id = request_model.session_id or create_session_id()
        follow_up_mode = bool(request_model.follow_up_mode)
        _enforce_rate_limit(request, "analyze", session_id)
        provided_existing_chunks = (
            _resolve_session_existing_chunks(session_id, list(request_model.existing_chunks))
            if follow_up_mode or bool(request_model.existing_chunks)
            else []
        )
        location_context = resolve_location_context(
            request_model.location_preference,
            request_model.location_value,
        )
        update_session(
            session_id,
            {
                "query": topic,
                "queries_generated": provided_queries,
            },
        )
        location_summary = describe_location_context(location_context)
        topic_key = build_location_topic_key(topic, location_context)
        depth = INTERNAL_DEPTH
        freshness = INTERNAL_FRESHNESS

        logger.info(
            "Analyze request received for topic=%s section=%s location=%s",
            _sanitize_for_log(topic),
            section,
            location_summary["label"],
        )

        try:
            feedback_summary = get_feedback_adjustment(topic_key)
        except Exception as exc:
            logger.warning("Feedback adjustment lookup failed for topic %s: %s", topic, exc)

        cache_key = _build_cache_key(
            topic,
            section,
            depth,
            freshness,
            feedback_summary,
            get_location_signature(location_context),
        )
        if follow_up_mode and provided_queries:
            cache_key = f"{cache_key}::followup=1::queries={'|'.join(provided_queries)}"

        try:
            historical_sources = get_best_sources_for_topic(topic_key, limit=3)
        except Exception as exc:
            logger.warning("Historical source lookup failed for topic %s: %s", topic, exc)
            historical_sources = []

        try:
            cache_start = time.perf_counter()
            cached_result = get_cached_result(cache_key)
            execution_time["cache_lookup_ms"] = _elapsed_ms(cache_start)
        except Exception as exc:
            logger.warning("Cache lookup failed for topic %s: %s", topic, exc)
            cached_result = None

        if cached_result is not None and not follow_up_mode:
            cached_items_raw = cached_result.get("response", {}).get("items", [])
            cache_has_examples_shape = (
                isinstance(cached_items_raw, list)
                and bool(cached_items_raw)
                and all(isinstance(item, dict) and "examples" in item for item in cached_items_raw)
            )
            if not cache_has_examples_shape:
                logger.info("Bypassing stale cached response without examples for topic %s", topic)
                cached_result = None

        if cached_result is not None and not follow_up_mode:
            cached_response = normalize_analyze_response_payload(
                cached_result.get("response", {}),
                fallback_section=section,
            )
            cached_response["items"] = rank_and_limit_insights(
                list(cached_response.get("items", [])),
                limit=INITIAL_INSIGHT_LIMIT,
            )
            cached_response["items"] = attach_sources_to_items(
                list(cached_response.get("items", [])),
                list(cached_result.get("evidence_blocks", [])),
            )
            if not cached_response["items"]:
                cached_response["title"] = "No strong insights found"
            cached_meta = dict(cached_response.get("meta", {}))
            cached_meta.setdefault("topic", topic)
            cached_meta.setdefault("location", dict(cached_result.get("location", location_summary)))
            cached_response["meta"] = cached_meta
            cached_response["session_id"] = session_id
            if debug_mode:
                execution_time["total_ms"] = _elapsed_ms(total_start)
                cached_response["debug"] = _build_debug_payload(
                    queries=[str(query) for query in cached_result.get("queries", [])],
                    selected_urls=[str(url) for url in cached_result.get("selected_urls", [])],
                    num_sources=int(cached_result.get("num_sources", 0)),
                    processing_chars=len(str(cached_result.get("processed_text", ""))),
                    prompt_chars=int(cached_result.get("prompt_chars", 0)),
                    execution_time=execution_time,
                    cache_hit=True,
                    source_scores=list(cached_result.get("source_scores", [])),
                    detected_conflicts=list(cached_result.get("detected_conflicts", [])),
                    signal_weights=list(cached_result.get("signal_weights", [])),
                    trend_metadata=list(cached_result.get("trend_metadata", [])),
                    query_performance=dict(cached_result.get("query_performance", {})),
                    stability_actions=list(cached_result.get("stability_actions", [])),
                    historical_sources=[str(url) for url in cached_result.get("historical_sources", historical_sources)],
                    feedback_summary=dict(cached_result.get("feedback_summary", feedback_summary)),
                    section=str(cached_result.get("section", section)),
                    depth=str(cached_result.get("depth", depth)),
                    freshness=str(cached_result.get("freshness", freshness)),
                    location=dict(cached_result.get("location", location_summary)),
                    artifact_dir=str(cached_result.get("artifact_dir", "")),
                    artifact_manifest=str(cached_result.get("artifact_manifest", "")),
                    artifact_counts=dict(cached_result.get("artifact_counts", {})),
                    existing_chunks=list(cached_result.get("existing_chunks", [])),
                )
            return _attach_session_id(cached_response, session_id)

        pipeline_start = time.perf_counter()
        try:
            pipeline_payload = await execute_pipeline(
                topic=topic,
                section=section,
                session_id=session_id,
                freshness=freshness,
                location_context=location_context,
                provided_queries=provided_queries or None,
            )
        except Exception as exc:
            logger.exception("Pipeline orchestrator failed for topic %s", _sanitize_for_log(topic))
            pipeline_payload = {
                "queries": [],
                "search_results": [],
                "query_performance": {},
                "stage_errors": {"pipeline": str(exc)},
                "artifact_bundle": {
                    "artifact_dir": "",
                    "manifest_path": "",
                    "artifacts": [],
                    "counts": {},
                    "pages": [],
                },
                "processed_payload": {
                    "processed_text": "",
                    "evidence_blocks": [],
                    "selected_urls": [],
                    "num_sources": 0,
                    "processing_chars": 0,
                    "source_scores": [],
                    "signal_weights": [],
                },
                "execution_time": {},
            }
        pipeline_elapsed_ms = _elapsed_ms(pipeline_start)
        execution_time.update({key: int(value) for key, value in dict(pipeline_payload.get("execution_time", {})).items()})
        execution_time["pipeline_ms"] = pipeline_elapsed_ms
        execution_time["search_ms"] = int(execution_time.get("search_ms", 0))
        execution_time["scraping_ms"] = int(execution_time.get("scrape_ms", execution_time.get("scraping_ms", 0)))
        execution_time["source_acquisition_ms"] = int(execution_time.get("scraping_ms", 0))
        execution_time["processing_ms"] = int(execution_time.get("processing_ms", 0))
        execution_time["ranking_ms"] = 0

        search_results = list(pipeline_payload.get("search_results", []))
        queries = [str(query) for query in pipeline_payload.get("queries", [])]
        query_performance = dict(pipeline_payload.get("query_performance", {}))
        stage_errors = dict(pipeline_payload.get("stage_errors", {}))
        artifact_bundle = dict(pipeline_payload.get("artifact_bundle", {}))
        processed_payload = dict(pipeline_payload.get("processed_payload", {}))

        logger.info("Pipeline output query_count=%s search_result_count=%s", len(queries), len(search_results))

        if not search_results:
            execution_time["total_ms"] = _elapsed_ms(total_start)
            debug_payload = None
            if debug_mode:
                debug_payload = _build_debug_payload(
                    queries=queries,
                    selected_urls=selected_urls,
                    num_sources=num_sources,
                    processing_chars=processing_chars,
                    prompt_chars=prompt_chars,
                    execution_time=execution_time,
                    cache_hit=False,
                    source_scores=source_scores,
                    detected_conflicts=detected_conflicts,
                    signal_weights=signal_weights,
                    trend_metadata=trend_metadata,
                    query_performance=query_performance,
                    stability_actions=stability_actions,
                    historical_sources=historical_sources,
                    feedback_summary=feedback_summary,
                    section=section,
                    depth=depth,
                    freshness=freshness,
                    location=location_summary,
                    stage_errors=stage_errors,
                )
            return _attach_session_id(
                _build_fail_safe_response(
                    stage_errors.get("search")
                    or stage_errors.get("query_generation")
                    or "No search results found.",
                    section=section,
                    debug_payload=debug_payload,
                ),
                session_id,
            )

        artifact_dir = str(artifact_bundle.get("artifact_dir", ""))
        artifact_manifest = str(artifact_bundle.get("manifest_path", ""))
        artifact_counts = dict(artifact_bundle.get("counts", {}))

        processed_text = str(processed_payload.get("processed_text", ""))
        evidence_blocks = list(processed_payload.get("evidence_blocks", []))
        existing_chunks = _build_existing_chunks(evidence_blocks)
        if follow_up_mode and provided_existing_chunks:
            merged_chunks = list(provided_existing_chunks) + existing_chunks
            deduped_chunks: List[Dict[str, str]] = []
            seen_chunk_text = set()
            for chunk in merged_chunks:
                text = str(chunk.get("text", "")).strip()
                source_id = str(chunk.get("source_id", "")).strip() or "followup_source"
                source_title = str(chunk.get("source_title", "")).strip() or source_id
                source_url = str(chunk.get("source_url") or chunk.get("url") or "").strip()
                source_domain = str(chunk.get("source_domain") or chunk.get("domain") or "").strip()
                source_date = str(chunk.get("source_date") or chunk.get("date") or "").strip()
                normalized_text = text.lower()
                if not text or normalized_text in seen_chunk_text:
                    continue
                seen_chunk_text.add(normalized_text)
                deduped_chunks.append(
                    {
                        "text": text,
                        "source_id": source_id,
                        "source_title": source_title,
                        "source_url": source_url,
                        "source_domain": source_domain,
                        "source_date": source_date,
                    }
                )
            existing_chunks = deduped_chunks
            evidence_blocks = [
                {
                    "source_id": chunk["source_id"],
                    "title": chunk["source_title"],
                    "date": chunk["source_date"],
                    "excerpt": chunk["text"],
                    "url": chunk["source_url"],
                    "domain": chunk["source_domain"] or "followup-merged",
                }
                for chunk in existing_chunks
            ]
            processed_text = "\n\n".join(chunk["text"] for chunk in existing_chunks)
            selected_urls = [chunk["source_id"] for chunk in existing_chunks]
            num_sources = len(existing_chunks)
            processing_chars = len(processed_text)
            source_scores = [
                {
                    "title": chunk["source_title"],
                    "url": chunk["source_url"],
                    "domain": chunk["source_domain"] or "followup-merged",
                    "artifact_type": "followup_chunk",
                    "artifact_path": "",
                    "score": 1,
                    "location_score": 0,
                    "location_matches": [],
                    "newest_year": None,
                    "years": [],
                }
                for chunk in existing_chunks
            ]
        else:
            selected_urls = [str(url) for url in processed_payload.get("selected_urls", [])]
            num_sources = int(processed_payload.get("num_sources", 0))
            processing_chars = int(processed_payload.get("processing_chars", 0))
            source_scores = list(processed_payload.get("source_scores", []))
        signal_weights = list(processed_payload.get("signal_weights", []))

        logger.info("Processed text prepared chars=%s", len(processed_text))

        if not processed_text:
            execution_time["total_ms"] = _elapsed_ms(total_start)
            debug_payload = None
            if debug_mode:
                debug_payload = _build_debug_payload(
                    queries=queries,
                    selected_urls=selected_urls,
                    num_sources=num_sources,
                    processing_chars=processing_chars,
                    prompt_chars=prompt_chars,
                    execution_time=execution_time,
                    cache_hit=False,
                    source_scores=source_scores,
                    detected_conflicts=detected_conflicts,
                    signal_weights=signal_weights,
                    trend_metadata=trend_metadata,
                    query_performance=query_performance,
                    stability_actions=stability_actions,
                    historical_sources=historical_sources,
                    feedback_summary=feedback_summary,
                    section=section,
                    depth=depth,
                    freshness=freshness,
                    location=location_summary,
                    artifact_dir=artifact_dir,
                    artifact_manifest=artifact_manifest,
                    artifact_counts=artifact_counts,
                    existing_chunks=existing_chunks,
                    stage_errors=stage_errors,
                )
            return _attach_session_id(
                _build_fail_safe_response(
                    stage_errors.get("processing")
                    or stage_errors.get("scraping")
                    or "No usable content extracted from stored research artifacts.",
                    section=section,
                    debug_payload=debug_payload,
                ),
                session_id,
            )

        try:
            update_best_sources_for_topic(topic_key, source_scores)
        except Exception as exc:
            logger.warning("Best source memory update failed for topic %s: %s", topic, exc)

        try:
            update_domain_authority(signal_weights)
        except Exception as exc:
            logger.warning("Domain authority memory update failed for topic %s: %s", topic, exc)

        try:
            historical_sources = get_best_sources_for_topic(topic_key, limit=3)
        except Exception as exc:
            logger.warning("Historical source refresh failed for topic %s: %s", topic, exc)

        insight_analysis = _empty_insight_analysis()
        execution_time["insight_analysis_ms"] = 0
        detected_conflicts = []

        prompt_start = time.perf_counter()
        try:
            insight_limit = _resolve_insight_limit(follow_up_mode)
            system_prompt = get_prompt(section, max_items=insight_limit)
            metadata_payload = build_metadata_payload(
                topic=topic,
                section=section,
                processed_sources=processed_text,
                insight_analysis=insight_analysis,
                signal_weights=signal_weights,
                historical_sources=historical_sources,
                depth=depth,
                freshness=freshness,
                location_context=location_context,
                evidence_blocks=evidence_blocks,
                source_scores=source_scores,
                artifact_counts=artifact_counts,
                max_items=insight_limit,
            )
        except Exception as exc:
            logger.warning("Prompt builder failed: %s", exc)
            execution_time["prompt_ms"] = _elapsed_ms(prompt_start)
            execution_time["total_ms"] = _elapsed_ms(total_start)
            debug_payload = None
            if debug_mode:
                debug_payload = _build_debug_payload(
                    queries=queries,
                    selected_urls=selected_urls,
                    num_sources=num_sources,
                    processing_chars=processing_chars,
                    prompt_chars=prompt_chars,
                    execution_time=execution_time,
                    cache_hit=False,
                    source_scores=source_scores,
                    detected_conflicts=detected_conflicts,
                    signal_weights=signal_weights,
                    trend_metadata=trend_metadata,
                    query_performance=query_performance,
                    stability_actions=stability_actions,
                    historical_sources=historical_sources,
                    feedback_summary=feedback_summary,
                    section=section,
                    depth=depth,
                    freshness=freshness,
                    location=location_summary,
                    artifact_dir=artifact_dir,
                    artifact_manifest=artifact_manifest,
                    artifact_counts=artifact_counts,
                    existing_chunks=existing_chunks,
                )
            return _attach_session_id(
                _build_fail_safe_response(f"Prompt building failed: {exc}", section=section, debug_payload=debug_payload),
                session_id,
            )
        execution_time["prompt_ms"] = _elapsed_ms(prompt_start)
        prompt_chars = len(system_prompt) + len(metadata_payload)

        openai_start = time.perf_counter()
        try:
            analysis_json = await generate_section_analysis(
                system_prompt,
                metadata_payload,
                section,
                max_items=insight_limit,
                evidence_blocks=evidence_blocks,
            )
        except Exception as exc:
            logger.exception("OpenAI analysis failed for topic %s and section %s", _sanitize_for_log(topic), section)
            analysis_json = build_fallback_section_analysis(
                topic=topic,
                processed_text=processed_text,
                section=section,
            )
        execution_time["openai_ms"] = _elapsed_ms(openai_start)
        analysis_json = normalize_analyze_response_payload(analysis_json, fallback_section=section)
        analysis_json["items"] = rank_and_limit_insights(
            list(analysis_json.get("items", [])),
            limit=insight_limit,
        )
        analysis_json["items"] = attach_sources_to_items(
            list(analysis_json.get("items", [])),
            evidence_blocks,
        )
        analysis_json["items"] = await enrich_items_with_researched_examples(
            items=list(analysis_json.get("items", [])),
            topic=topic,
            section=section,
            location_context=location_context,
            session_id=session_id,
        )
        if not analysis_json["items"]:
            analysis_json["title"] = "No strong insights found"

        validation_start = time.perf_counter()
        try:
            validated_response = AnalyzeResponse(**analysis_json)
        except Exception as exc:
            logger.warning("Analyze response validation failed: %s", exc)
            execution_time["validation_ms"] = _elapsed_ms(validation_start)
            execution_time["total_ms"] = _elapsed_ms(total_start)
            debug_payload = None
            if debug_mode:
                debug_payload = _build_debug_payload(
                    queries=queries,
                    selected_urls=selected_urls,
                    num_sources=num_sources,
                    processing_chars=processing_chars,
                    prompt_chars=prompt_chars,
                    execution_time=execution_time,
                    cache_hit=False,
                    source_scores=source_scores,
                    detected_conflicts=detected_conflicts,
                    signal_weights=signal_weights,
                    trend_metadata=trend_metadata,
                    query_performance=query_performance,
                    stability_actions=stability_actions,
                    historical_sources=historical_sources,
                    feedback_summary=feedback_summary,
                    section=section,
                    depth=depth,
                    freshness=freshness,
                    location=location_summary,
                    artifact_dir=artifact_dir,
                    artifact_manifest=artifact_manifest,
                    artifact_counts=artifact_counts,
                    existing_chunks=existing_chunks,
                )
            return _attach_session_id(
                _build_fail_safe_response(
                    f"Response validation failed: {exc}",
                    section=section,
                    debug_payload=debug_payload,
                ),
                session_id,
            )
        execution_time["validation_ms"] = _elapsed_ms(validation_start)
        execution_time["total_ms"] = _elapsed_ms(total_start)

        response_payload: Dict[str, Any] = validated_response.model_dump()
        response_payload["meta"] = {
            "topic": topic,
            "location": location_summary,
        }
        response_payload["session_id"] = session_id
        trend_metadata = [
            {
                "heading": str(item.get("heading", "")),
                "body_preview": str(item.get("body", ""))[:160],
            }
            for item in response_payload.get("items", [])
        ]

        try:
            set_cached_result(
                cache_key,
                {
                    "processed_text": processed_text,
                    "evidence_blocks": evidence_blocks,
                    "response": response_payload,
                    "num_sources": num_sources,
                    "prompt_chars": prompt_chars,
                    "queries": queries,
                    "selected_urls": selected_urls,
                    "source_scores": source_scores,
                    "detected_conflicts": detected_conflicts,
                    "signal_weights": signal_weights,
                    "trend_metadata": trend_metadata,
                    "query_performance": query_performance,
                    "stability_actions": stability_actions,
                    "historical_sources": historical_sources,
                    "feedback_summary": feedback_summary,
                    "location": location_summary,
                    "section": section,
                    "depth": depth,
                    "freshness": freshness,
                    "artifact_dir": artifact_dir,
                    "artifact_manifest": artifact_manifest,
                    "artifact_counts": artifact_counts,
                    "existing_chunks": existing_chunks,
                },
            )
        except Exception as exc:
            logger.warning("Cache write failed for topic %s: %s", topic, exc)

        try:
            update_session(
                session_id,
                {
                    "query": topic,
                    "queries_generated": queries,
                    "sources": selected_urls,
                    "artifacts": [
                        str(artifact.get("text_key") or artifact.get("binary_key") or artifact.get("text_path") or "").strip()
                        for artifact in artifact_bundle.get("artifacts", [])
                        if str(artifact.get("text_key") or artifact.get("binary_key") or artifact.get("text_path") or "").strip()
                    ],
                    "cleaned_dump_key": str(processed_payload.get("cleaned_dump_key", "")).strip(),
                    "final_output": response_payload,
                },
            )
        except Exception as exc:
            logger.warning("Session update failed for session %s: %s", session_id, exc)

        if debug_mode:
            response_payload["debug"] = _build_debug_payload(
                queries=queries,
                selected_urls=selected_urls,
                num_sources=num_sources,
                processing_chars=processing_chars,
                prompt_chars=prompt_chars,
                execution_time=execution_time,
                cache_hit=False,
                source_scores=source_scores,
                detected_conflicts=detected_conflicts,
                signal_weights=signal_weights,
                trend_metadata=trend_metadata,
                query_performance=query_performance,
                stability_actions=stability_actions,
                historical_sources=historical_sources,
                feedback_summary=feedback_summary,
                section=section,
                depth=depth,
                freshness=freshness,
                location=location_summary,
                artifact_dir=artifact_dir,
                artifact_manifest=artifact_manifest,
                artifact_counts=artifact_counts,
                existing_chunks=existing_chunks,
            )

        return _attach_session_id(response_payload, session_id)
    except HTTPException:
        raise
    except Exception as exc:
        execution_time["total_ms"] = _elapsed_ms(total_start)
        logger.exception("Analyze pipeline failed for topic=%s", _sanitize_for_log(topic))
        debug_payload = None
        if debug_mode:
            debug_payload = _build_debug_payload(
                queries=queries,
                selected_urls=selected_urls,
                num_sources=num_sources,
                processing_chars=processing_chars,
                prompt_chars=prompt_chars,
                execution_time=execution_time,
                cache_hit=False,
                source_scores=source_scores,
                detected_conflicts=detected_conflicts,
                signal_weights=signal_weights,
                trend_metadata=trend_metadata,
                query_performance=query_performance,
                stability_actions=stability_actions,
                historical_sources=historical_sources,
                feedback_summary=feedback_summary,
                section=section,
                depth=depth,
                freshness=freshness,
                location=location_summary,
                artifact_dir=artifact_dir,
                artifact_manifest=artifact_manifest,
                artifact_counts=artifact_counts,
            )
        return _attach_session_id(
            _build_fail_safe_response(f"Pipeline failed: {exc}", section=section, debug_payload=debug_payload),
            session_id,
        )


@router.post("/feedback")
async def submit_feedback(request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        logger.warning("Invalid feedback payload received: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc

    topic = str(payload.get("topic", "")).strip()
    rating = payload.get("rating")
    comment = str(payload.get("comment", "")).strip()
    location_preference = str(payload.get("location_preference", "global")).strip()
    location_value = str(payload.get("location_value", "")).strip() or None

    if not topic:
        raise HTTPException(status_code=422, detail="Topic is required.")

    try:
        rating_value = int(rating)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Rating must be an integer.") from exc

    if rating_value < 1 or rating_value > 5:
        raise HTTPException(status_code=422, detail="Rating must be between 1 and 5.")

    try:
        location_context = resolve_location_context(location_preference, location_value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    store_feedback(
        topic=build_location_topic_key(topic, location_context),
        rating=rating_value,
        comment=comment,
    )
    logger.info(
        "Feedback stored for topic %s with rating %s and location %s.",
        topic,
        rating_value,
        location_context.label,
    )
    return {"status": "success"}


@router.delete("/sessions/{session_id}")
async def cleanup_session(session_id: str) -> Dict[str, str]:
    normalized_session_id = session_id.strip()
    if not normalized_session_id:
        raise HTTPException(status_code=422, detail="session_id is required.")

    try:
        await asyncio.to_thread(delete_session_prefix, normalized_session_id)
        await asyncio.to_thread(delete_session, normalized_session_id)
    except Exception as exc:
        logger.exception("Cleanup failed session_id=%s", normalized_session_id)
        raise HTTPException(status_code=500, detail=f"Session cleanup failed: {exc}") from exc

    logger.info("Session deleted session_id=%s", normalized_session_id)
    return {"status": "deleted"}
