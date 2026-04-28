import json
from typing import Any, Dict

import redis

from config.settings import settings

SESSION_TTL_SECONDS = 3600
SESSION_KEY_PREFIX = "osint:session:"

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
    resolved_ttl = ttl if remaining_ttl in (-2, -1) else int(remaining_ttl)
    set_session(session_id, data, ttl=resolved_ttl)
    return data


def delete_session(session_id: str) -> None:
    try:
        redis_client.delete(_session_key(session_id))
        print("[CLEANUP] Redis session deleted:", session_id)
    except Exception as exc:
        print("[CLEANUP ERROR] Redis delete failed:", str(exc))
