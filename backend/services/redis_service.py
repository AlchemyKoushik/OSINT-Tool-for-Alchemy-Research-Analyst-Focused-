import json
import logging
import time
from threading import RLock
from typing import Any, Dict

import redis

from config.settings import settings

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = settings.SESSION_TTL_SECONDS
SESSION_KEY_PREFIX = "osint:session:"
RATE_LIMIT_KEY_PREFIX = "osint:rate_limit:"

_REDIS_CLIENT_LOCK = RLock()
_FALLBACK_STORE_LOCK = RLock()
_FALLBACK_STORE: Dict[str, Dict[str, Any]] = {}


def _build_redis_client() -> redis.Redis:
    return redis.Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        health_check_interval=30,
        socket_connect_timeout=5,
        socket_timeout=20,
        socket_keepalive=True,
        retry_on_timeout=True,
    )


redis_client = _build_redis_client()


def _reset_redis_client() -> redis.Redis:
    global redis_client
    with _REDIS_CLIENT_LOCK:
        redis_client = _build_redis_client()
        return redis_client


def _fallback_purge_expired_key(key: str) -> None:
    record = _FALLBACK_STORE.get(key)
    if not record:
        return
    expires_at = record.get("expires_at")
    if expires_at is not None and float(expires_at) <= time.time():
        _FALLBACK_STORE.pop(key, None)


def _fallback_get(key: str) -> Any:
    with _FALLBACK_STORE_LOCK:
        _fallback_purge_expired_key(key)
        record = _FALLBACK_STORE.get(key)
        return None if record is None else record.get("value")


def _fallback_set(key: str, value: Any, ttl: int | None = None) -> None:
    expires_at = None if ttl is None else time.time() + max(int(ttl), 1)
    with _FALLBACK_STORE_LOCK:
        _FALLBACK_STORE[key] = {
            "value": value,
            "expires_at": expires_at,
        }


def _fallback_delete(key: str) -> None:
    with _FALLBACK_STORE_LOCK:
        _FALLBACK_STORE.pop(key, None)


def _fallback_ttl(key: str) -> int:
    with _FALLBACK_STORE_LOCK:
        _fallback_purge_expired_key(key)
        record = _FALLBACK_STORE.get(key)
        if record is None:
            return -2
        expires_at = record.get("expires_at")
        if expires_at is None:
            return -1
        return max(int(expires_at - time.time()), 0)


def _fallback_incr(key: str) -> int:
    with _FALLBACK_STORE_LOCK:
        _fallback_purge_expired_key(key)
        record = _FALLBACK_STORE.get(key)
        current_value = 0 if record is None else int(record.get("value", 0))
        next_value = current_value + 1
        expires_at = None if record is None else record.get("expires_at")
        _FALLBACK_STORE[key] = {
            "value": next_value,
            "expires_at": expires_at,
        }
        return next_value


def _fallback_expire(key: str, ttl: int) -> None:
    expires_at = time.time() + max(int(ttl), 1)
    with _FALLBACK_STORE_LOCK:
        record = _FALLBACK_STORE.get(key)
        if record is None:
            return
        record["expires_at"] = expires_at


def _run_redis_command(command_name: str, operation, fallback=None):
    last_error: Exception | None = None

    for attempt in range(2):
        client = redis_client if attempt == 0 else _reset_redis_client()
        try:
            return operation(client)
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Redis command failed command=%s attempt=%s error=%s",
                command_name,
                attempt + 1,
                exc,
            )

    if fallback is not None:
        logger.warning(
            "Redis fallback activated command=%s error=%s",
            command_name,
            last_error,
        )
        return fallback()

    assert last_error is not None
    raise last_error


def run_redis_operation(command_name: str, operation, fallback=None):
    return _run_redis_command(command_name, operation, fallback=fallback)


def ping_redis() -> bool:
    return bool(_run_redis_command("ping", lambda client: client.ping(), fallback=lambda: False))


def get_redis_status() -> Dict[str, Any]:
    healthy = ping_redis()
    return {
        "available": healthy,
        "url": settings.REDIS_URL,
    }


def _session_key(session_id: str) -> str:
    return f"{SESSION_KEY_PREFIX}{session_id}"


def get_json_value(key: str, default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    data = _run_redis_command(
        "get",
        lambda client: client.get(key),
        fallback=lambda: _fallback_get(key),
    )
    if not data:
        return dict(default or {})

    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return dict(default or {})
    return parsed if isinstance(parsed, dict) else dict(default or {})


def set_json_value(key: str, data: Dict[str, Any], ttl: int | None = None) -> None:
    payload = json.dumps(data)
    _fallback_set(key, payload, ttl=ttl)
    _run_redis_command(
        "set",
        lambda client: client.set(key, payload) if ttl is None else client.set(key, payload, ex=ttl),
        fallback=lambda: True,
    )


def set_session(session_id: str, data: Dict[str, Any], ttl: int = SESSION_TTL_SECONDS) -> None:
    set_json_value(_session_key(session_id), data, ttl=ttl)


def get_session(session_id: str) -> Dict[str, Any]:
    return get_json_value(_session_key(session_id), default={})


def update_session(session_id: str, updates: Dict[str, Any], ttl: int = SESSION_TTL_SECONDS) -> Dict[str, Any]:
    data = get_session(session_id)
    data.update(updates)

    remaining_ttl = _run_redis_command(
        "ttl",
        lambda client: client.ttl(_session_key(session_id)),
        fallback=lambda: _fallback_ttl(_session_key(session_id)),
    )
    resolved_ttl = ttl if remaining_ttl in (-2, -1) or int(remaining_ttl) <= 0 else int(remaining_ttl)
    set_session(session_id, data, ttl=resolved_ttl)
    return data


def delete_session(session_id: str) -> None:
    session_key = _session_key(session_id)
    last_error: Exception | None = None
    _fallback_delete(session_key)

    for retry_index in range(settings.CLEANUP_MAX_RETRIES + 1):
        try:
            _run_redis_command("delete", lambda client: client.delete(session_key), fallback=lambda: 1)
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

    def _redis_rate_limit(client: redis.Redis) -> tuple[int, int]:
        pipeline = client.pipeline()
        pipeline.incr(key)
        pipeline.ttl(key)
        current_count, ttl = pipeline.execute()
        if int(current_count) == 1:
            client.expire(key, window_seconds)
            ttl = window_seconds
        return int(current_count), int(ttl or window_seconds)

    def _fallback_rate_limit() -> tuple[int, int]:
        current_count = _fallback_incr(key)
        ttl = _fallback_ttl(key)
        if current_count == 1 or ttl in (-2, -1, 0):
            _fallback_expire(key, window_seconds)
            ttl = window_seconds
        return int(current_count), int(ttl or window_seconds)

    current_count, ttl = _run_redis_command(
        "rate_limit",
        _redis_rate_limit,
        fallback=_fallback_rate_limit,
    )
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
