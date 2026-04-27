import copy
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEMORY_FILE_PATH = PROJECT_ROOT / "query_memory.json"
_MEMORY_LOCK = RLock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_memory() -> Dict[str, Any]:
    return {
        "query_memory": {},
        "domain_authority": {},
        "feedback": [],
        "topic_runs": {},
    }


def _normalize_topic(topic: str) -> str:
    return topic.strip().lower()


def _extract_domain(value: str) -> str:
    parsed = urlparse(str(value).strip())
    domain = parsed.netloc.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def _ensure_memory_file() -> None:
    if MEMORY_FILE_PATH.exists():
        return

    MEMORY_FILE_PATH.write_text(json.dumps(_default_memory(), indent=2), encoding="utf-8")


def _read_memory() -> Dict[str, Any]:
    _ensure_memory_file()
    try:
        raw_content = MEMORY_FILE_PATH.read_text(encoding="utf-8").strip()
        if not raw_content:
            return _default_memory()

        parsed = json.loads(raw_content)
        if not isinstance(parsed, dict):
            return _default_memory()

        defaults = _default_memory()
        defaults.update(parsed)
        defaults["query_memory"] = parsed.get("query_memory", {}) or {}
        defaults["domain_authority"] = parsed.get("domain_authority", {}) or {}
        defaults["feedback"] = parsed.get("feedback", []) or []
        defaults["topic_runs"] = parsed.get("topic_runs", {}) or {}
        return defaults
    except Exception as exc:
        logger.warning("Failed to read memory file: %s", exc)
        return _default_memory()


def _write_memory(memory: Dict[str, Any]) -> None:
    _ensure_memory_file()
    MEMORY_FILE_PATH.write_text(json.dumps(memory, indent=2), encoding="utf-8")


def _query_limit(depth: str) -> int:
    return {"low": 4, "medium": 6, "high": 8}.get(depth, 6)


def _feedback_summary_for_topic(topic_runs: Dict[str, Any], topic: str) -> Dict[str, Any]:
    normalized_topic = _normalize_topic(topic)
    topic_record = topic_runs.get(normalized_topic, {})
    avg_rating = float(topic_record.get("avg_rating", 0.0))
    rating_count = int(topic_record.get("rating_count", 0))
    confidence_adjustment = 0

    if rating_count > 0:
        if avg_rating >= 4.0:
            confidence_adjustment = 1
        elif avg_rating <= 2.0:
            confidence_adjustment = -1

    return {
        "avg_rating": round(avg_rating, 2),
        "rating_count": rating_count,
        "confidence_adjustment": confidence_adjustment,
    }


def get_feedback_adjustment(topic: str) -> Dict[str, Any]:
    with _MEMORY_LOCK:
        memory = _read_memory()
    return _feedback_summary_for_topic(memory.get("topic_runs", {}), topic)


def optimize_queries_for_topic(topic: str, queries: List[str], depth: str = "medium") -> List[str]:
    normalized_topic = _normalize_topic(topic)
    query_limit = _query_limit(depth)

    with _MEMORY_LOCK:
        memory = _read_memory()

    topic_memory = memory.get("query_memory", {}).get(normalized_topic, {})
    query_records = topic_memory.get("queries", {})

    unique_queries: List[str] = []
    seen_queries = set()
    for query in queries:
        normalized_query = query.strip()
        if not normalized_query or normalized_query.lower() in seen_queries:
            continue
        seen_queries.add(normalized_query.lower())
        unique_queries.append(normalized_query)

    ranked_queries = sorted(
        unique_queries,
        key=lambda query: float(query_records.get(query, {}).get("avg_score", 2.5)),
        reverse=True,
    )

    retained_queries = [
        query
        for query in ranked_queries
        if query not in query_records or float(query_records.get(query, {}).get("avg_score", 0.0)) >= 1.5
    ]
    if not retained_queries:
        retained_queries = ranked_queries

    historical_boosts = [
        query
        for query, record in sorted(
            query_records.items(),
            key=lambda item: float(item[1].get("avg_score", 0.0)),
            reverse=True,
        )
        if float(record.get("avg_score", 0.0)) >= 4.0
    ]

    final_queries: List[str] = []
    seen_final = set()
    for query in retained_queries + historical_boosts + ranked_queries:
        normalized_query = query.strip()
        if not normalized_query or normalized_query.lower() in seen_final:
            continue
        seen_final.add(normalized_query.lower())
        final_queries.append(normalized_query)
        if len(final_queries) >= query_limit:
            break

    logger.info("Optimized queries for topic %s at depth %s: %s", topic, depth, final_queries)
    return final_queries


def update_query_memory(topic: str, query_performance: Dict[str, Dict[str, float]]) -> None:
    normalized_topic = _normalize_topic(topic)

    with _MEMORY_LOCK:
        memory = _read_memory()
        topic_memory = memory.setdefault("query_memory", {}).setdefault(
            normalized_topic,
            {"topic": topic.strip(), "queries": {}, "last_updated": _utc_now()},
        )
        query_records = topic_memory.setdefault("queries", {})

        for query, performance in query_performance.items():
            previous = query_records.get(query, {})
            previous_count = int(previous.get("count", 0))
            previous_avg = float(previous.get("avg_score", 0.0))
            new_avg = float(performance.get("avg_score", 0.0))
            new_count = previous_count + 1
            blended_avg = (
                ((previous_avg * previous_count) + new_avg) / new_count
                if new_count > 0
                else new_avg
            )

            query_records[query] = {
                "avg_score": round(blended_avg, 2),
                "count": new_count,
                "last_used": _utc_now(),
            }

        topic_memory["last_updated"] = _utc_now()
        _write_memory(memory)


def get_best_sources_for_topic(topic: str, limit: int = 3) -> List[str]:
    normalized_topic = _normalize_topic(topic)
    with _MEMORY_LOCK:
        memory = _read_memory()

    topic_record = memory.get("topic_runs", {}).get(normalized_topic, {})
    best_sources = topic_record.get("best_sources", []) or []
    urls = [str(source.get("url", "")).strip() for source in best_sources if str(source.get("url", "")).strip()]
    return urls[:limit]


def update_best_sources_for_topic(topic: str, source_scores: List[Dict[str, Any]], limit: int = 3) -> None:
    normalized_topic = _normalize_topic(topic)

    with _MEMORY_LOCK:
        memory = _read_memory()
        topic_runs = memory.setdefault("topic_runs", {})
        topic_record = topic_runs.setdefault(
            normalized_topic,
            {
                "topic": topic.strip(),
                "avg_rating": 0.0,
                "rating_count": 0,
                "best_sources": [],
                "last_updated": _utc_now(),
            },
        )

        source_map: Dict[str, Dict[str, Any]] = {}
        for existing_source in topic_record.get("best_sources", []) or []:
            url = str(existing_source.get("url", "")).strip()
            if not url:
                continue
            source_map[url] = {
                "url": url,
                "domain": str(existing_source.get("domain", "")).strip() or _extract_domain(url),
                "score": float(existing_source.get("score", 0.0)),
                "updated_at": str(existing_source.get("updated_at", "")) or _utc_now(),
            }

        for source in source_scores:
            url = str(source.get("url", "")).strip()
            if not url:
                continue
            score = float(source.get("score", 0.0))
            domain = str(source.get("domain", "")).strip() or _extract_domain(url)
            existing = source_map.get(url)
            if existing is None or score >= float(existing.get("score", 0.0)):
                source_map[url] = {
                    "url": url,
                    "domain": domain,
                    "score": score,
                    "updated_at": _utc_now(),
                }

        ranked_sources = sorted(
            source_map.values(),
            key=lambda item: (float(item.get("score", 0.0)), str(item.get("updated_at", ""))),
            reverse=True,
        )
        topic_record["best_sources"] = ranked_sources[:limit]
        topic_record["last_updated"] = _utc_now()
        _write_memory(memory)


def get_domain_authority_boosts() -> Dict[str, int]:
    with _MEMORY_LOCK:
        memory = _read_memory()

    boosts: Dict[str, int] = {}
    for domain, record in memory.get("domain_authority", {}).items():
        avg_weight = float(record.get("avg_weight", 0.0))
        avg_feedback_rating = float(record.get("avg_feedback_rating", 0.0))
        high_rating_count = int(record.get("high_rating_count", 0))

        base_boost = 0
        if avg_weight >= 6:
            base_boost = 3
        elif avg_weight >= 4:
            base_boost = 2
        elif avg_weight >= 2:
            base_boost = 1

        feedback_boost = 0
        if high_rating_count >= 1:
            feedback_boost += 1
        if avg_feedback_rating >= 4.0 and int(record.get("feedback_count", 0)) >= 1:
            feedback_boost += 1

        boosts[domain] = max(0, min(5, base_boost + feedback_boost))
    return boosts


def update_domain_authority(signal_weights: List[Dict[str, Any]]) -> None:
    with _MEMORY_LOCK:
        memory = _read_memory()
        domain_memory = memory.setdefault("domain_authority", {})

        for signal in signal_weights:
            domain = str(signal.get("domain", "")).strip()
            if not domain:
                domain = _extract_domain(str(signal.get("url", "")))
            if not domain:
                continue

            total_weight = float(signal.get("total_weight", 0.0))
            previous = domain_memory.get(domain, {})
            previous_count = int(previous.get("count", 0))
            previous_avg = float(previous.get("avg_weight", 0.0))
            new_count = previous_count + 1
            blended_avg = (
                ((previous_avg * previous_count) + total_weight) / new_count
                if new_count > 0
                else total_weight
            )

            domain_memory[domain] = {
                "avg_weight": round(blended_avg, 2),
                "count": new_count,
                "last_seen": _utc_now(),
                "high_rating_count": int(previous.get("high_rating_count", 0)),
                "avg_feedback_rating": float(previous.get("avg_feedback_rating", 0.0)),
                "feedback_count": int(previous.get("feedback_count", 0)),
            }

        _write_memory(memory)


def store_feedback(topic: str, rating: int, comment: str) -> None:
    normalized_topic = _normalize_topic(topic)

    with _MEMORY_LOCK:
        memory = _read_memory()
        feedback = memory.setdefault("feedback", [])
        feedback_entry = {
            "topic": topic.strip(),
            "rating": int(rating),
            "comment": comment.strip(),
            "timestamp": _utc_now(),
        }
        feedback.append(feedback_entry)

        topic_runs = memory.setdefault("topic_runs", {})
        topic_record = topic_runs.setdefault(
            normalized_topic,
            {
                "topic": topic.strip(),
                "avg_rating": 0.0,
                "rating_count": 0,
                "best_sources": [],
                "last_updated": _utc_now(),
            },
        )

        rating_count = int(topic_record.get("rating_count", 0))
        current_avg = float(topic_record.get("avg_rating", 0.0))
        new_count = rating_count + 1
        new_avg = ((current_avg * rating_count) + float(rating)) / new_count if new_count > 0 else float(rating)
        topic_record["rating_count"] = new_count
        topic_record["avg_rating"] = round(new_avg, 2)
        topic_record["last_feedback"] = feedback_entry["timestamp"]
        topic_record["last_updated"] = feedback_entry["timestamp"]

        domain_memory = memory.setdefault("domain_authority", {})
        best_sources = topic_record.get("best_sources", []) or []
        for best_source in best_sources:
            domain = str(best_source.get("domain", "")).strip() or _extract_domain(best_source.get("url", ""))
            if not domain:
                continue

            domain_record = domain_memory.setdefault(
                domain,
                {
                    "avg_weight": 0.0,
                    "count": 0,
                    "last_seen": "",
                    "high_rating_count": 0,
                    "avg_feedback_rating": 0.0,
                    "feedback_count": 0,
                },
            )

            feedback_count = int(domain_record.get("feedback_count", 0))
            current_feedback_avg = float(domain_record.get("avg_feedback_rating", 0.0))
            new_feedback_count = feedback_count + 1
            new_feedback_avg = (
                ((current_feedback_avg * feedback_count) + float(rating)) / new_feedback_count
                if new_feedback_count > 0
                else float(rating)
            )

            if rating >= 4:
                domain_record["high_rating_count"] = int(domain_record.get("high_rating_count", 0)) + 1

            domain_record["avg_feedback_rating"] = round(new_feedback_avg, 2)
            domain_record["feedback_count"] = new_feedback_count
            domain_record["last_seen"] = feedback_entry["timestamp"]

        _write_memory(memory)


def get_memory_snapshot() -> Dict[str, Any]:
    with _MEMORY_LOCK:
        return copy.deepcopy(_read_memory())
