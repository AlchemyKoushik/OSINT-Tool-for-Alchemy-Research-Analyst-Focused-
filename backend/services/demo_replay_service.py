from __future__ import annotations

import asyncio
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Tuple

from bs4 import BeautifulSoup

from config.settings import settings
from models.response_models import AnalyzeResponse

DEMO_PAYLOAD_PATH = Path(__file__).resolve().parents[1] / "data" / "demo_replay_payload.json"
DEFAULT_DEMO_HTML_PATH = Path(__file__).resolve().parents[1] / "data" / "demo_replay_memo.html"


def _build_demo_queries(topic: str, section: str, location_label: str) -> List[str]:
    normalized_topic = topic or "Industry"
    normalized_scope = location_label or "Global"
    focus = "drivers" if section == "drivers" else "trends"
    return [
        f"{normalized_topic} {focus} {normalized_scope} 2026",
        f"{normalized_topic} market {focus} {normalized_scope}",
        f"{normalized_topic} growth shifts {normalized_scope}",
        f"{normalized_topic} commercial adoption {normalized_scope}",
        f"{normalized_topic} policy changes {normalized_scope}",
        f"{normalized_topic} competition outlook {normalized_scope}",
        f"{normalized_topic} regional divergence {normalized_scope}",
        f"{normalized_topic} technology shifts {normalized_scope}",
        f"{normalized_topic} enterprise demand {normalized_scope}",
        f"{normalized_topic} market outlook {normalized_scope}",
    ]


def _decode_text(raw_bytes: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _read_text_file(path: Path) -> str:
    return _decode_text(path.read_bytes())


def _resolve_demo_html_path() -> Path | None:
    configured = str(settings.DEMO_REPLAY_HTML_PATH or "").strip()
    candidate = (Path(configured) if configured else DEFAULT_DEMO_HTML_PATH)
    if not candidate.is_absolute():
        candidate = Path(__file__).resolve().parents[1] / candidate
    return candidate if candidate.exists() else None


def _extract_summary_cards(soup: BeautifulSoup) -> Dict[str, str]:
    cards: Dict[str, str] = {}
    for card in soup.select(".summary-card"):
        label = _normalize_whitespace(card.select_one("span").get_text(" ", strip=True) if card.select_one("span") else "")
        value = _normalize_whitespace(card.select_one("strong").get_text(" ", strip=True) if card.select_one("strong") else "")
        if label and value:
            cards[label.lower()] = value
    return cards


def _parse_example_item(node: Any) -> Dict[str, str] | None:
    if node is None:
        return None

    year_node = node.select_one(".example-year")
    year = _normalize_whitespace(year_node.get_text(" ", strip=True) if year_node else "")
    if year.startswith("(") and year.endswith(")"):
        year = year[1:-1].strip()

    text_parts: List[str] = []
    for child in node.contents:
        child_classes = getattr(child, "get", lambda *_args, **_kwargs: [])("class", [])
        if "example-year" in child_classes:
            continue
        text_parts.append(str(child))

    text = _normalize_whitespace(BeautifulSoup("".join(text_parts), "html.parser").get_text(" ", strip=True))
    if not text:
        return None
    return {"text": text, "year": year}


def _infer_section(title: str) -> str:
    lowered = str(title or "").strip().lower()
    return "drivers" if "driver" in lowered else "trends"


def _parse_demo_html_document(path: Path) -> Dict[str, Any]:
    html_text = _read_text_file(path)
    soup = BeautifulSoup(html_text, "html.parser")

    title = _normalize_whitespace(soup.select_one(".memo-section h1").get_text(" ", strip=True) if soup.select_one(".memo-section h1") else "")
    topic = _normalize_whitespace(soup.select_one(".memo-topic").get_text(" ", strip=True) if soup.select_one(".memo-topic") else "")
    location_label = _normalize_whitespace(soup.select_one(".memo-scope").get_text(" ", strip=True) if soup.select_one(".memo-scope") else "")
    summary_cards = _extract_summary_cards(soup)
    prepared = summary_cards.get("prepared", "")

    items: List[Dict[str, Any]] = []
    source_id_map: Dict[Tuple[str, str], int] = {}
    selected_urls: List[str] = []
    source_scores: List[Dict[str, Any]] = []

    for item_node in soup.select(".memo-item"):
        heading = _normalize_whitespace(item_node.select_one("h3").get_text(" ", strip=True) if item_node.select_one("h3") else "")
        body = _normalize_whitespace(
            item_node.select_one(".memo-item__body").get_text(" ", strip=True) if item_node.select_one(".memo-item__body") else ""
        )
        if not heading or not body:
            continue

        examples = [
            parsed
            for parsed in (_parse_example_item(example_node) for example_node in item_node.select(".example-list li"))
            if parsed
        ]

        sources: List[Dict[str, str]] = []
        source_ids: List[int] = []
        for source_node in item_node.select(".source-list .source-item"):
            link = source_node.select_one("a")
            meta_node = source_node.select_one(".source-meta")

            source_title = _normalize_whitespace(link.get_text(" ", strip=True) if link else source_node.get_text(" ", strip=True))
            source_url = _normalize_whitespace(link.get("href", "") if link else "")
            meta_text = _normalize_whitespace(meta_node.get_text(" ", strip=True) if meta_node else "")
            meta_parts = [part.strip() for part in meta_text.split("|")] if meta_text else []
            domain = meta_parts[0] if meta_parts else ""
            date = meta_parts[1] if len(meta_parts) > 1 else ""

            if not source_title:
                continue

            source_key = (source_url, source_title)
            if source_key not in source_id_map:
                source_id_map[source_key] = len(source_id_map) + 1
            source_id = source_id_map[source_key]

            sources.append(
                {
                    "source_id": str(source_id),
                    "title": source_title,
                    "url": source_url,
                    "domain": domain,
                    "date": date,
                }
            )
            if source_id not in source_ids:
                source_ids.append(source_id)

            if source_url and source_url not in selected_urls:
                selected_urls.append(source_url)

            if source_url:
                source_scores.append(
                    {
                        "source_id": str(source_id),
                        "title": source_title,
                        "url": source_url,
                        "domain": domain,
                        "published_at": date,
                        "score": 1.0,
                    }
                )

        items.append(
            {
                "heading": heading,
                "body": body,
                "examples": examples[:2],
                "sources": sources[:5],
                "source_ids": source_ids[:10],
            }
        )

    payload = {
        "section": _infer_section(title),
        "title": title or "Industry Trends",
        "topic": topic or "Research topic",
        "prepared": prepared,
        "location_label": location_label or "Global",
        "items": items,
        "selected_urls": selected_urls,
        "source_scores": source_scores,
        "source_html_filename": path.name,
    }
    AnalyzeResponse(section=payload["section"], title=payload["title"], items=payload["items"])
    return payload


@lru_cache(maxsize=1)
def _load_demo_document() -> Dict[str, Any]:
    configured_html_path = _resolve_demo_html_path()
    if configured_html_path is not None:
        return _parse_demo_html_document(configured_html_path)

    if not DEMO_PAYLOAD_PATH.exists():
        raise FileNotFoundError(
            f"Demo replay source not found. Checked HTML path '{configured_html_path}' and JSON payload '{DEMO_PAYLOAD_PATH}'."
        )

    payload = json.loads(DEMO_PAYLOAD_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Demo replay payload must be a JSON object: {DEMO_PAYLOAD_PATH}")

    section = str(payload.get("section", "trends")).strip() or "trends"
    title = str(payload.get("title", "Industry Trends")).strip() or "Industry Trends"
    items = payload.get("items", [])
    AnalyzeResponse(section=section, title=title, items=items)
    return payload


def load_demo_replay_source_html(meta_payload: Dict[str, Any] | None = None) -> tuple[bytes, str] | None:
    source_path = _resolve_demo_html_path()
    if source_path is None:
        return None
    return source_path.read_bytes(), source_path.name


async def maybe_build_demo_replay_response(*, session_id: str, debug_mode: bool) -> Dict[str, Any] | None:
    if not settings.DEMO_REPLAY_ENABLED:
        return None

    demo_document = _load_demo_document()
    delay_seconds = max(int(settings.DEMO_REPLAY_DELAY_SECONDS), 0)
    if delay_seconds:
        await asyncio.sleep(delay_seconds)

    location_label = str(demo_document.get("location_label", "Global")).strip() or "Global"
    items = list(demo_document.get("items", []))
    selected_urls = list(demo_document.get("selected_urls", []))
    topic = str(demo_document.get("topic", "Industry")).strip() or "Industry"
    section = str(demo_document.get("section", "trends")).strip() or "trends"
    source_html_filename = str(demo_document.get("source_html_filename", "")).strip()
    debug_payload = None

    if debug_mode:
        cleaned_chunks = []
        for item_index, item in enumerate(items, start=1):
            for source_index, source in enumerate(item.get("sources", []), start=1):
                cleaned_chunks.append(
                    {
                        "text": f"{item.get('heading', '')}. {item.get('body', '')}".strip(),
                        "reason": "demo_replay",
                        "source_id": str(source.get("source_id", f"demo_{item_index}_{source_index}")).strip(),
                        "source_title": str(source.get("title", "")).strip(),
                        "source_url": str(source.get("url", "")).strip(),
                        "source_domain": str(source.get("domain", "")).strip(),
                        "source_date": str(source.get("date", "")).strip(),
                    }
                )

        delay_ms = delay_seconds * 1000
        debug_payload = {
            "queries": _build_demo_queries(topic, section, location_label),
            "selected_urls": selected_urls,
            "num_sources": len(selected_urls),
            "processing_chars": sum(len(str(item.get("body", ""))) for item in items),
            "prompt_chars": 0,
            "execution_time": {
                "total_ms": delay_ms,
                "pipeline_ms": delay_ms,
                "demo_delay_ms": delay_ms,
            },
            "cache_hit": False,
            "source_scores": list(demo_document.get("source_scores", [])),
            "detected_conflicts": [],
            "signal_weights": [],
            "trend_metadata": [],
            "query_performance": {},
            "stability_actions": [
                {
                    "stage": "demo_replay",
                    "action": "served_html_backed_demo_replay",
                    "delay_seconds": delay_seconds,
                    "source_html_filename": source_html_filename,
                }
            ],
            "historical_sources": [],
            "feedback_summary": {"avg_rating": 0.0, "rating_count": 0, "confidence_adjustment": 0},
            "section": section,
            "depth": "high",
            "freshness": "high",
            "location": {
                "preference": "global",
                "scope": "global",
                "label": location_label,
                "value": "",
                "region": "",
                "strict": False,
            },
            "artifact_dir": "",
            "artifact_manifest": source_html_filename or "demo_replay_memo.html",
            "artifact_counts": {"usable_text_count": len(items)},
            "existing_chunks": cleaned_chunks,
            "cleaned_chunks": cleaned_chunks,
            "stage_errors": {},
        }

    return {
        "section": section,
        "title": str(demo_document.get("title", "Industry Trends")).strip() or "Industry Trends",
        "items": items,
        "meta": {
            "topic": topic,
            "location": {
                "preference": "global",
                "scope": "global",
                "label": location_label,
                "value": "",
                "region": "",
                "strict": False,
            },
            "prepared": str(demo_document.get("prepared", "")).strip(),
            "source_html_filename": source_html_filename,
        },
        "debug": debug_payload,
        "session_id": session_id,
    }
