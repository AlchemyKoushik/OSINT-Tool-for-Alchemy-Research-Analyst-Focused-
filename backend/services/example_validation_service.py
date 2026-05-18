from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence

from models.response_models import Example, ExtractedExample

logger = logging.getLogger(__name__)

WORD_PATTERN = re.compile(r"[a-z0-9][a-z0-9&/%-]{1,}", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\b(20\d{2}|19\d{2})\b")
GENERIC_EXAMPLE_MARKERS = {
    "companies are investing",
    "firms are partnering",
    "market participants are expanding",
    "industry players are launching",
    "the market is seeing",
    "example not specified",
}
EVENT_KEYWORDS = (
    "launch",
    "launched",
    "partner",
    "partnership",
    "acquisition",
    "acquire",
    "acquired",
    "merger",
    "merged",
    "deal",
    "investment",
    "funding",
    "expand",
    "expansion",
    "deployment",
    "approval",
    "agreement",
    "manufacturing",
    "facility",
    "plant",
    "commercial",
    "infrastructure",
    "scale",
)
MAX_VALIDATED_EXAMPLES_PER_TREND = 2


@dataclass(frozen=True)
class ExampleValidationResult:
    accepted: bool
    reason: str = ""
    example: ExtractedExample | None = None


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _tokenize(value: str) -> List[str]:
    return [token.lower() for token in WORD_PATTERN.findall(_normalize_text(value))]


def _source_id_set(evidence_blocks: Sequence[Dict[str, Any]]) -> set[int]:
    ids: set[int] = set()
    for index, block in enumerate(evidence_blocks, start=1):
        for raw_value in (block.get("source_id"), index):
            try:
                numeric_id = int(raw_value)
            except (TypeError, ValueError):
                continue
            if numeric_id > 0:
                ids.add(numeric_id)
    return ids


def _build_evidence_lookup(evidence_blocks: Sequence[Dict[str, Any]]) -> Dict[int, str]:
    lookup: Dict[int, str] = {}
    for index, block in enumerate(evidence_blocks, start=1):
        excerpt = _normalize_text(block.get("excerpt"))
        title = _normalize_text(block.get("title"))
        combined = f"{title} {excerpt}".strip()
        for raw_value in (block.get("source_id"), index):
            try:
                numeric_id = int(raw_value)
            except (TypeError, ValueError):
                continue
            if numeric_id > 0 and combined:
                lookup[numeric_id] = combined
    return lookup


def _extract_year(text: str) -> str:
    match = YEAR_PATTERN.search(text)
    return match.group(1) if match else ""


def _has_specific_date_signal(example: ExtractedExample) -> bool:
    combined = " ".join(
        [
            _normalize_text(example.year),
            _normalize_text(example.text),
        ]
    )
    if YEAR_PATTERN.search(combined):
        return True
    lowered = combined.lower()
    return any(
        month in lowered
        for month in (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        )
    )


def _has_event_signal(example: ExtractedExample) -> bool:
    event_text = " ".join(
        [
            _normalize_text(example.event),
            _normalize_text(example.text),
        ]
    ).lower()
    return any(keyword in event_text for keyword in EVENT_KEYWORDS)


def _looks_generic(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in GENERIC_EXAMPLE_MARKERS)


def _is_supported_by_evidence(example: ExtractedExample, evidence_lookup: Dict[int, str]) -> bool:
    cited_evidence = [evidence_lookup[source_id] for source_id in example.source_ids if source_id in evidence_lookup]
    if not cited_evidence:
        return False

    example_tokens = set(_tokenize(example.text))
    if example.company:
        example_tokens.update(_tokenize(example.company))
    if example.event:
        example_tokens.update(_tokenize(example.event))

    if not example_tokens:
        return False

    for evidence_text in cited_evidence:
        evidence_tokens = set(_tokenize(evidence_text))
        overlap = example_tokens.intersection(evidence_tokens)
        if len(overlap) >= 3:
            return True
        if example.company and _normalize_text(example.company).lower() in evidence_text.lower():
            return True
    return False


def validate_example(
    example: ExtractedExample,
    evidence_blocks: Sequence[Dict[str, Any]],
) -> ExampleValidationResult:
    text = _normalize_text(example.text)
    company = _normalize_text(example.company)
    year = _normalize_text(example.year) or _extract_year(text)
    event = _normalize_text(example.event)

    if not text:
        return ExampleValidationResult(accepted=False, reason="empty_text")
    if len(text.split()) < 5:
        return ExampleValidationResult(accepted=False, reason="too_short")
    if _looks_generic(text):
        return ExampleValidationResult(accepted=False, reason="generic_text")
    if not company and not _has_event_signal(example):
        return ExampleValidationResult(accepted=False, reason="missing_entity_or_event")
    if not _has_specific_date_signal(example):
        return ExampleValidationResult(accepted=False, reason="missing_date_signal")

    valid_source_ids = _source_id_set(evidence_blocks)
    normalized_source_ids = [source_id for source_id in example.source_ids if source_id in valid_source_ids]
    if not normalized_source_ids:
        return ExampleValidationResult(accepted=False, reason="invalid_source_ids")

    normalized_example = ExtractedExample(
        company=company,
        event=event,
        text=text,
        year=year,
        source_ids=normalized_source_ids,
    )
    evidence_lookup = _build_evidence_lookup(evidence_blocks)
    if not _is_supported_by_evidence(normalized_example, evidence_lookup):
        return ExampleValidationResult(accepted=False, reason="unsupported_by_evidence")

    return ExampleValidationResult(accepted=True, example=normalized_example)


def validate_examples(
    examples: Iterable[ExtractedExample],
    evidence_blocks: Sequence[Dict[str, Any]],
) -> tuple[List[ExtractedExample], List[str]]:
    validated: List[ExtractedExample] = []
    discard_reasons: List[str] = []
    seen_keys = set()

    for example in examples:
        result = validate_example(example, evidence_blocks)
        if not result.accepted or result.example is None:
            discard_reasons.append(result.reason or "unknown_validation_failure")
            continue

        dedupe_key = (
            result.example.text.lower(),
            str(result.example.year or "").strip(),
            tuple(result.example.source_ids),
        )
        if dedupe_key in seen_keys:
            discard_reasons.append("duplicate_example")
            continue
        seen_keys.add(dedupe_key)
        validated.append(result.example)

    return validated, discard_reasons


def evidence_has_strong_example_signals(evidence_blocks: Sequence[Dict[str, Any]]) -> bool:
    for block in evidence_blocks:
        combined = " ".join(
            [
                _normalize_text(block.get("title")),
                _normalize_text(block.get("excerpt")),
            ]
        ).lower()
        if any(keyword in combined for keyword in EVENT_KEYWORDS):
            return True
        if len(re.findall(r"\b[A-Z][A-Za-z0-9&.-]+\b", str(block.get("excerpt", "")))) >= 2:
            return True
    return False


def attach_examples_to_insights(
    items: Sequence[Dict[str, Any]],
    validated_examples: Sequence[ExtractedExample],
) -> List[Dict[str, Any]]:
    attached_items: List[Dict[str, Any]] = []

    for item in items:
        normalized_item = dict(item)
        item_text = " ".join(
            [
                _normalize_text(normalized_item.get("heading")),
                _normalize_text(normalized_item.get("body")),
            ]
        ).lower()
        item_source_ids = {
            int(source_id)
            for source_id in normalized_item.get("source_ids", [])
            if str(source_id).strip().isdigit()
        }

        selected_examples: List[Example] = []
        seen_keys = set()
        for example in validated_examples:
            example_source_ids = set(example.source_ids)
            source_overlap = bool(item_source_ids.intersection(example_source_ids))
            token_overlap = any(token in item_text for token in _tokenize(example.text)[:6])
            company_overlap = bool(example.company and example.company.lower() in item_text)
            if not source_overlap and not token_overlap and not company_overlap:
                continue

            candidate = Example(text=example.text, year=example.year)
            dedupe_key = (candidate.text.lower(), candidate.year or "")
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            selected_examples.append(candidate)
            if len(selected_examples) >= MAX_VALIDATED_EXAMPLES_PER_TREND:
                break

        normalized_item["examples"] = [example.model_dump() for example in selected_examples]
        attached_items.append(normalized_item)

    return attached_items
