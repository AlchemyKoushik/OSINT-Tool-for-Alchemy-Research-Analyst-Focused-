import copy
import hashlib
import logging
from typing import Any, Dict, Optional

from config.settings import settings
from services.redis_service import get_json_value, set_json_value

logger = logging.getLogger(__name__)
CACHE_KEY_PREFIX = "osint:cache:"


def _topic_key(topic: str) -> str:
    normalized_topic = topic.strip().lower().encode("utf-8")
    return f"{CACHE_KEY_PREFIX}{hashlib.sha256(normalized_topic).hexdigest()}"


def get_cached_result(topic: str) -> Optional[Dict[str, Any]]:
    cache_key = _topic_key(topic)
    cached_value = get_json_value(cache_key, default={})

    if not cached_value:
        logger.info("Cache miss for topic: %s", topic)
        return None

    logger.info("Cache hit for topic: %s", topic)
    return copy.deepcopy(cached_value)


def set_cached_result(topic: str, data: Dict[str, Any]) -> None:
    cache_key = _topic_key(topic)
    set_json_value(cache_key, copy.deepcopy(data), ttl=settings.CACHE_TTL_SECONDS)
    logger.info("Cache updated for topic: %s", topic)
