import json
import time
import uuid
from threading import RLock
from typing import Any, Dict, List, Optional

from config.settings import settings
from core.logging import get_logger
from services.redis_service import run_redis_operation

logger = get_logger(__name__)

JOB_KEY_PREFIX = "osint:research:job:"
JOB_STATS_KEY = "osint:research:job-stats"
JOB_QUEUE_KEY = settings.JOB_QUEUE_NAME

_FALLBACK_JOBS: Dict[str, Dict[str, Any]] = {}
_FALLBACK_QUEUE: List[str] = []
_FALLBACK_LOCK = RLock()


def _job_key(job_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{job_id}"


def _utc_timestamp() -> float:
    return round(time.time(), 3)


def _build_job_record(payload: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    now = _utc_timestamp()
    job_id = str(uuid.uuid4())
    return {
        "job_id": job_id,
        "session_id": session_id,
        "status": "queued",
        "stage": "Queued",
        "current_activity": "Waiting for worker",
        "progress_percentage": 0,
        "payload": payload,
        "result": None,
        "error": "",
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
        "attempts": 0,
        "worker_id": "",
        "diagnostics": {},
    }


def _fallback_stats() -> Dict[str, int]:
    stats = {
        "queued": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
    }
    for job in _FALLBACK_JOBS.values():
        status = str(job.get("status", "")).strip()
        if status in stats:
            stats[status] += 1
    return stats


def _write_job_record(record: Dict[str, Any]) -> Dict[str, Any]:
    payload = json.dumps(record)
    run_redis_operation(
        "job_set",
        lambda client: client.set(_job_key(record["job_id"]), payload, ex=settings.JOB_TTL_SECONDS),
        fallback=lambda: _fallback_set_job(record),
    )
    return record


def _fallback_set_job(record: Dict[str, Any]) -> bool:
    with _FALLBACK_LOCK:
        _FALLBACK_JOBS[str(record["job_id"])] = dict(record)
    return True


def _get_job_record(job_id: str) -> Dict[str, Any]:
    raw = run_redis_operation(
        "job_get",
        lambda client: client.get(_job_key(job_id)),
        fallback=lambda: _fallback_get_job(job_id),
    )
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _fallback_get_job(job_id: str) -> Dict[str, Any]:
    with _FALLBACK_LOCK:
        return dict(_FALLBACK_JOBS.get(job_id, {}))


def _update_stats(previous_status: str, next_status: str) -> None:
    previous = str(previous_status or "").strip()
    current = str(next_status or "").strip()
    if previous == current:
        return

    def _update(client) -> bool:
        pipeline = client.pipeline()
        if previous:
            pipeline.hincrby(JOB_STATS_KEY, previous, -1)
        if current:
            pipeline.hincrby(JOB_STATS_KEY, current, 1)
        pipeline.expire(JOB_STATS_KEY, settings.JOB_TTL_SECONDS)
        pipeline.execute()
        return True

    run_redis_operation("job_stats_update", _update, fallback=lambda: True)


def create_research_job(payload: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    record = _build_job_record(payload, session_id=session_id)
    _write_job_record(record)
    _update_stats("", "queued")
    run_redis_operation(
        "job_enqueue",
        lambda client: client.rpush(JOB_QUEUE_KEY, record["job_id"]),
        fallback=lambda: _fallback_enqueue(record["job_id"]),
    )
    logger.info("Research job created job_id=%s session_id=%s", record["job_id"], session_id)
    return record


def _fallback_enqueue(job_id: str) -> int:
    with _FALLBACK_LOCK:
        _FALLBACK_QUEUE.append(job_id)
        return len(_FALLBACK_QUEUE)


def update_research_job(job_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    record = _get_job_record(job_id)
    if not record:
        return {}

    previous_status = str(record.get("status", "")).strip()
    record.update(updates)
    record["updated_at"] = _utc_timestamp()
    _write_job_record(record)
    _update_stats(previous_status, str(record.get("status", "")).strip())
    return record


def get_research_job(job_id: str) -> Dict[str, Any]:
    return _get_job_record(job_id)


def mark_job_running(job_id: str, worker_id: str) -> Dict[str, Any]:
    record = _get_job_record(job_id)
    if not record:
        return {}
    next_attempts = int(record.get("attempts", 0)) + 1
    updates = {
        "status": "running",
        "worker_id": worker_id,
        "started_at": record.get("started_at") or _utc_timestamp(),
        "current_activity": "Worker accepted job",
        "stage": "Initializing",
        "attempts": next_attempts,
    }
    return update_research_job(job_id, updates)


def mark_job_completed(job_id: str, result: Dict[str, Any], diagnostics: Dict[str, Any]) -> Dict[str, Any]:
    return update_research_job(
        job_id,
        {
            "status": "completed",
            "progress_percentage": 100,
            "stage": "Completed",
            "current_activity": "Research complete",
            "result": result,
            "error": "",
            "completed_at": _utc_timestamp(),
            "diagnostics": diagnostics,
        },
    )


def mark_job_failed(job_id: str, error_message: str, diagnostics: Dict[str, Any]) -> Dict[str, Any]:
    return update_research_job(
        job_id,
        {
            "status": "failed",
            "stage": "Failed",
            "current_activity": "Research failed",
            "error": str(error_message).strip(),
            "completed_at": _utc_timestamp(),
            "diagnostics": diagnostics,
        },
    )


def requeue_research_job(job_id: str, current_error: str, diagnostics: Dict[str, Any]) -> Dict[str, Any]:
    record = update_research_job(
        job_id,
        {
            "status": "queued",
            "stage": "Retry Queued",
            "current_activity": str(current_error).strip() or "Retry queued",
            "error": str(current_error).strip(),
            "diagnostics": diagnostics,
        },
    )
    run_redis_operation(
        "job_requeue",
        lambda client: client.rpush(JOB_QUEUE_KEY, job_id),
        fallback=lambda: _fallback_enqueue(job_id),
    )
    logger.warning("Research job requeued job_id=%s attempts=%s", job_id, record.get("attempts", 0))
    return record


def reserve_next_job(timeout_seconds: int | None = None) -> Dict[str, Any]:
    timeout_value = max(int(timeout_seconds or settings.JOB_POLL_TIMEOUT_SECONDS), 1)
    raw = run_redis_operation(
        "job_dequeue",
        lambda client: client.blpop(JOB_QUEUE_KEY, timeout=timeout_value),
        fallback=lambda: _fallback_dequeue(),
    )
    if not raw:
        return {}

    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        job_id = str(raw[1])
    else:
        job_id = str(raw)
    return _get_job_record(job_id)


def _fallback_dequeue() -> Optional[str]:
    with _FALLBACK_LOCK:
        if not _FALLBACK_QUEUE:
            return None
        return _FALLBACK_QUEUE.pop(0)


def get_job_metrics() -> Dict[str, Any]:
    def _fetch(client) -> Dict[str, Any]:
        stats = client.hgetall(JOB_STATS_KEY)
        queue_length = client.llen(JOB_QUEUE_KEY)
        return {
            "stats": stats,
            "queue_length": int(queue_length or 0),
        }

    payload = run_redis_operation(
        "job_metrics",
        _fetch,
        fallback=lambda: {
            "stats": _fallback_stats(),
            "queue_length": len(_FALLBACK_QUEUE),
        },
    )
    stats = payload.get("stats", {}) if isinstance(payload, dict) else {}
    return {
        "queue_length": int(payload.get("queue_length", 0)) if isinstance(payload, dict) else 0,
        "active_jobs": int(stats.get("running", 0)),
        "completed_jobs": int(stats.get("completed", 0)),
        "failed_jobs": int(stats.get("failed", 0)),
        "queued_jobs": int(stats.get("queued", 0)),
    }
