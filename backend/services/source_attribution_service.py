import re
from typing import Any, Dict, List, Sequence

WORD_PATTERN = re.compile(r"[a-z0-9][a-z0-9&/%-]{1,}", re.IGNORECASE)
STOPWORDS = {
    "about",
    "after",
    "also",
    "among",
    "been",
    "being",
    "between",
    "from",
    "have",
    "into",
    "market",
    "that",
    "their",
    "them",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "trend",
    "trends",
    "driver",
    "drivers",
    "under",
    "using",
    "while",
    "with",
}


def _tokenize(value: str) -> List[str]:
    return [
        token.lower()
        for token in WORD_PATTERN.findall(str(value or "").lower())
        if token.lower() not in STOPWORDS and len(token) > 2
    ]


def _normalize_source_id(value: Any) -> str:
    return str(value or "").strip()


def _build_source_ref(block: Dict[str, Any], source_id: int) -> Dict[str, str]:
    return {
        "source_id": str(source_id),
        "title": str(block.get("title", "")).strip() or f"Source {source_id}",
        "url": str(block.get("url", "")).strip(),
        "domain": str(block.get("domain", "")).strip(),
        "date": str(block.get("date", "")).strip(),
        "image_url": str(block.get("image_url", "")).strip(),
    }


def _build_catalog(evidence_blocks: Sequence[Dict[str, Any]]) -> tuple[Dict[str, Dict[str, str]], List[Dict[str, Any]]]:
    catalog: Dict[str, Dict[str, str]] = {}
    scored_blocks: List[Dict[str, Any]] = []

    for index, block in enumerate(evidence_blocks, start=1):
        source_id = _normalize_source_id(block.get("source_id")) or str(index)
        source_ref = _build_source_ref(block, index)
        catalog[source_id] = source_ref
        catalog[str(index)] = source_ref
        scored_blocks.append(
            {
                "source_id": source_id,
                "source_ref": source_ref,
                "tokens": set(
                    _tokenize(
                        f"{source_ref['title']} {source_ref['domain']} {str(block.get('excerpt', '')).strip()}"
                    )
                ),
                "excerpt": str(block.get("excerpt", "")).strip(),
            }
        )

    return catalog, scored_blocks


def _normalize_source_ids(raw_source_ids: Any) -> List[str]:
    if not isinstance(raw_source_ids, list):
        return []
    normalized: List[str] = []
    for value in raw_source_ids:
        source_id = _normalize_source_id(value)
        if source_id and source_id not in normalized:
            normalized.append(source_id)
    return normalized


def _score_block_for_item(item_tokens: set[str], block: Dict[str, Any]) -> float:
    block_tokens = set(block.get("tokens", set()))
    overlap = item_tokens.intersection(block_tokens)
    if not overlap:
        return 0.0

    excerpt = str(block.get("excerpt", "")).lower()
    numeric_matches = len(re.findall(r"\b\d+(?:\.\d+)?%?\b", excerpt))
    return float(len(overlap) * 3 + min(numeric_matches, 4))


def attach_sources_to_items(
    items: Sequence[Dict[str, Any]],
    evidence_blocks: Sequence[Dict[str, Any]],
    *,
    max_sources_per_item: int = 3,
) -> List[Dict[str, Any]]:
    if not items:
        return []

    catalog, scored_blocks = _build_catalog(evidence_blocks)
    enriched_items: List[Dict[str, Any]] = []

    for item in items:
        normalized_item = dict(item)
        existing_sources = normalized_item.get("sources")
        if isinstance(existing_sources, list) and existing_sources:
            normalized_item["sources"] = [
                dict(source)
                for source in existing_sources
                if isinstance(source, dict) and (str(source.get("title", "")).strip() or str(source.get("url", "")).strip())
            ][:max_sources_per_item]
            normalized_item.pop("source_ids", None)
            enriched_items.append(normalized_item)
            continue

        heading = str(normalized_item.get("heading", "")).strip()
        body = str(normalized_item.get("body", "")).strip()
        item_tokens = set(_tokenize(f"{heading} {body}"))

        selected_sources: List[Dict[str, str]] = []
        seen_urls = set()

        for source_id in _normalize_source_ids(normalized_item.get("source_ids")):
            source_ref = catalog.get(source_id)
            if not source_ref:
                continue
            source_key = source_ref.get("url") or source_ref.get("source_id")
            if source_key in seen_urls:
                continue
            seen_urls.add(source_key)
            selected_sources.append(dict(source_ref))
            if len(selected_sources) >= max_sources_per_item:
                break

        if not selected_sources and item_tokens:
            ranked_blocks = sorted(
                scored_blocks,
                key=lambda block: _score_block_for_item(item_tokens, block),
                reverse=True,
            )
            for block in ranked_blocks:
                if _score_block_for_item(item_tokens, block) <= 0:
                    continue
                source_ref = dict(block["source_ref"])
                source_key = source_ref.get("url") or source_ref.get("source_id")
                if source_key in seen_urls:
                    continue
                seen_urls.add(source_key)
                selected_sources.append(source_ref)
                if len(selected_sources) >= max_sources_per_item:
                    break

        normalized_item["sources"] = selected_sources
        normalized_item.pop("source_ids", None)
        enriched_items.append(normalized_item)

    return enriched_items
