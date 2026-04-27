import copy
import hashlib
import logging
from threading import RLock
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_LOCK = RLock()


def _topic_key(topic: str) -> str:
    normalized_topic = topic.strip().lower().encode("utf-8")
    return hashlib.sha256(normalized_topic).hexdigest()


def get_cached_result(topic: str) -> Optional[Dict[str, Any]]:
    cache_key = _topic_key(topic)
    with _CACHE_LOCK:
        cached_value = _CACHE.get(cache_key)

    if cached_value is None:
        logger.info("Cache miss for topic: %s", topic)
        return None

    logger.info("Cache hit for topic: %s", topic)
    return copy.deepcopy(cached_value)


def set_cached_result(topic: str, data: Dict[str, Any]) -> None:
    cache_key = _topic_key(topic)
    with _CACHE_LOCK:
        _CACHE[cache_key] = copy.deepcopy(data)
    logger.info("Cache updated for topic: %s", topic)
