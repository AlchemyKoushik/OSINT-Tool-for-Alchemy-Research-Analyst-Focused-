import json
import logging
import time
from typing import Any, Dict

import redis

from config.settings import settings

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = settings.SESSION_TTL_SECONDS
SESSION_KEY_PREFIX = "osint:session:"
RATE_LIMIT_KEY_PREFIX = "osint:rate_limit:"

redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def _session_key(session_id: str) -> str:
    return f"{SESSION_KEY_PREFIX}{session_id}"


def get_json_value(key: str, default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    data = redis_client.get(key)
    if not data:
        return dict(default or {})

    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return dict(default or {})
    return parsed if isinstance(parsed, dict) else dict(default or {})


def set_json_value(key: str, data: Dict[str, Any], ttl: int | None = None) -> None:
    payload = json.dumps(data)
    if ttl is None:
        redis_client.set(key, payload)
    else:
        redis_client.set(key, payload, ex=ttl)


def set_session(session_id: str, data: Dict[str, Any], ttl: int = SESSION_TTL_SECONDS) -> None:
    set_json_value(_session_key(session_id), data, ttl=ttl)


def get_session(session_id: str) -> Dict[str, Any]:
    return get_json_value(_session_key(session_id), default={})


def update_session(session_id: str, updates: Dict[str, Any], ttl: int = SESSION_TTL_SECONDS) -> Dict[str, Any]:
    data = get_session(session_id)
    data.update(updates)

    remaining_ttl = redis_client.ttl(_session_key(session_id))
    resolved_ttl = ttl if remaining_ttl in (-2, -1) or int(remaining_ttl) <= 0 else int(remaining_ttl)
    set_session(session_id, data, ttl=resolved_ttl)
    return data


def delete_session(session_id: str) -> None:
    session_key = _session_key(session_id)
    last_error: Exception | None = None

    for retry_index in range(settings.CLEANUP_MAX_RETRIES + 1):
        try:
            redis_client.delete(session_key)
            logger.info("Session deleted session_id=%s store=redis", session_id)
            return
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Cleanup failed session_id=%s store=redis attempt=%s error=%s",
                session_id,
                retry_index + 1,
                exc,
            )
            if retry_index < settings.CLEANUP_MAX_RETRIES:
                time.sleep(min(2**retry_index, 4))

    logger.exception("Cleanup failed session_id=%s store=redis", session_id, exc_info=last_error)
    raise RuntimeError(f"Redis session delete failed for {session_id}") from last_error


def check_rate_limit(identifier: str, route_name: str, limit: int | None = None, window_seconds: int = 60) -> tuple[bool, int]:
    normalized_identifier = str(identifier).strip() or "anonymous"
    normalized_route = str(route_name).strip() or "default"
    applied_limit = max(1, int(limit or settings.RATE_LIMIT_REQUESTS_PER_MINUTE))
    key = f"{RATE_LIMIT_KEY_PREFIX}{normalized_route}:{normalized_identifier}"

    pipeline = redis_client.pipeline()
    pipeline.incr(key)
    pipeline.ttl(key)
    current_count, ttl = pipeline.execute()
    if int(current_count) == 1:
        redis_client.expire(key, window_seconds)
        ttl = window_seconds
    retry_after = max(int(ttl or window_seconds), 1)

    allowed = int(current_count) <= applied_limit
    if not allowed:
        logger.warning(
            "rate_limit_exceeded route=%s identifier=%s limit=%s retry_after=%s",
            normalized_route,
            normalized_identifier,
            applied_limit,
            retry_after,
        )
    return allowed, retry_after
