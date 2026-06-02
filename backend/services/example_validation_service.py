from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Sequence

from models.response_models import Example, ExtractedExample

logger = logging.getLogger(__name__)

WORD_PATTERN = re.compile(r"[a-z0-9][a-z0-9&/%-]{1,}", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\b(20\d{2}|19\d{2})\b")
MONTH_YEAR_PATTERNS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d %B %Y",
    "%d %b %Y",
    "%B %Y",
    "%b %Y",
    "%Y",
)
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
    "roll out",
    "rolled out",
    "introduced",
    "unveiled",
    "partner",
    "partnered",
    "partnership",
    "collaboration",
    "joint venture",
    "acquisition",
    "acquire",
    "acquired",
    "buyout",
    "stake",
    "minority stake",
    "majority stake",
    "merger",
    "merged",
    "deal",
    "transaction",
    "divest",
    "divested",
    "sale",
    "investment",
    "invested",
    "funding",
    "financing",
    "raised",
    "committed",
    "expand",
    "expanded",
    "expansion",
    "capacity",
    "facility",
    "plant",
    "factory",
    "deployment",
    "deployed",
    "installation",
    "installed",
    "commissioned",
    "commercial operation",
    "operational",
    "construction",
    "broke ground",
    "approval",
    "approved",
    "permit",
    "licensed",
    "authorised",
    "authorized",
    "regulatory approval",
    "agreement",
    "contract",
    "offtake",
    "ppa",
    "supply agreement",
    "manufacturing",
    "infrastructure",
    "scale-up",
    "pilot",
    "prototype",
    "demonstration",
    "demonstration mission",
    "feasibility",
    "research contract",
    "research programme",
    "research program",
    "grant",
    "funded",
    "programme",
    "program",
    "consortium",
    "proof-of-concept",
    "proof of concept",
    "mission",
    "price increase",
    "surcharge",
    "repricing",
    "tariff",
    "subsidy",
    "auction",
    "market entry",
    "entered",
    "opened office",
    "geographic expansion",
)
SBSP_SYNONYMS = (
    "space-based solar power",
    "space based solar power",
    "sbsp",
    "space solar power",
    "space-based solar",
    "solar power satellite",
    "orbital solar",
    "space-based power",
    "power beaming",
    "wireless power transmission",
    "microwave power transmission",
)
LOW_VALUE_SOURCE_TIERS = {"Tier 3"}
MAX_VALIDATED_EXAMPLES_PER_TREND = 5


@dataclass(frozen=True)
class ExampleValidationResult:
    accepted: bool
    reason: str = ""
    example: ExtractedExample | None = None
    score: int = 0


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _tokenize(value: str) -> List[str]:
    return [token.lower() for token in WORD_PATTERN.findall(_normalize_text(value))]


def _topic_terms_from_trend_context(trend_context: Dict[str, Any] | None) -> List[str]:
    if not trend_context:
        return []
    values = [
        _normalize_text(trend_context.get("heading")),
        _normalize_text(trend_context.get("body")),
        _normalize_text(trend_context.get("topic")),
    ]
    tokens: List[str] = []
    for value in values:
        for token in _tokenize(value):
            if len(token) >= 4 and token not in tokens:
                tokens.append(token)
    synonyms = trend_context.get("synonyms") if trend_context else []
    if isinstance(synonyms, list):
        for synonym in synonyms:
            for token in _tokenize(str(synonym)):
                if len(token) >= 3 and token not in tokens:
                    tokens.append(token)
    return tokens[:12]


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


def _build_evidence_lookup(evidence_blocks: Sequence[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    lookup: Dict[int, Dict[str, Any]] = {}
    for index, block in enumerate(evidence_blocks, start=1):
        for raw_value in (block.get("source_id"), index):
            try:
                numeric_id = int(raw_value)
            except (TypeError, ValueError):
                continue
            if numeric_id <= 0:
                continue
            lookup[numeric_id] = {
                "title": _normalize_text(block.get("title")),
                "excerpt": _normalize_text(block.get("excerpt") or block.get("full_text_excerpt")),
                "snippet": _normalize_text(block.get("snippet")),
                "date": _normalize_text(block.get("published_date") or block.get("date")),
                "url": _normalize_text(block.get("url")),
                "publisher": _normalize_text(block.get("publisher") or block.get("domain")),
                "source_tier": _normalize_text(block.get("source_tier")) or "Tier 3",
                "location": _normalize_text(block.get("location")),
            }
    return lookup


def _extract_year(text: str) -> str:
    match = YEAR_PATTERN.search(text)
    return match.group(1) if match else ""


def _parse_date_signal(value: str) -> date | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    for fmt in MONTH_YEAR_PATTERNS:
        try:
            parsed = datetime.strptime(normalized, fmt)
            if fmt == "%Y":
                return date(parsed.year, 1, 1)
            if fmt in {"%B %Y", "%b %Y"}:
                return date(parsed.year, parsed.month, 1)
            return parsed.date()
        except ValueError:
            continue
    year_match = YEAR_PATTERN.search(normalized)
    if year_match:
        try:
            return date(int(year_match.group(1)), 1, 1)
        except ValueError:
            return None
    return None


def _research_date(research_date: date | None) -> date:
    return research_date or datetime.utcnow().date()


def _months_old(candidate: date | None, *, research_date: date) -> int | None:
    if candidate is None:
        return None
    return (research_date.year - candidate.year) * 12 + (research_date.month - candidate.month)


def _has_specific_date_signal(example: ExtractedExample, evidence_lookup: Dict[int, Dict[str, Any]]) -> bool:
    for candidate in (
        _normalize_text(example.event_date),
        _normalize_text(example.published_date),
        _normalize_text(example.year),
        _normalize_text(example.text),
    ):
        if YEAR_PATTERN.search(candidate):
            return True
        lowered = candidate.lower()
        if any(
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
        ):
            return True

    for source_id in example.source_ids:
        evidence = evidence_lookup.get(source_id, {})
        if _parse_date_signal(str(evidence.get("date", ""))):
            return True
    return False


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


def _cited_evidence_bundle(example: ExtractedExample, evidence_lookup: Dict[int, Dict[str, Any]]) -> str:
    parts: List[str] = []
    for source_id in example.source_ids:
        evidence = evidence_lookup.get(source_id, {})
        parts.extend(
            [
                str(evidence.get("title", "")),
                str(evidence.get("snippet", "")),
                str(evidence.get("excerpt", "")),
            ]
        )
    return " ".join(part for part in parts if part).strip()


def _company_name_in_evidence(company: str, evidence_text: str) -> bool:
    normalized_company = _normalize_text(company).lower()
    return bool(normalized_company and normalized_company in evidence_text.lower())


def _event_terms_overlap(text: str, evidence_text: str) -> bool:
    lowered_text = _normalize_text(text).lower()
    lowered_evidence = _normalize_text(evidence_text).lower()
    matched_keywords = [keyword for keyword in EVENT_KEYWORDS if keyword in lowered_text and keyword in lowered_evidence]
    return len(matched_keywords) >= 1


def _key_object_terms_overlap(text: str, evidence_text: str) -> bool:
    tokens = [token for token in _tokenize(text) if len(token) >= 5]
    evidence_tokens = set(_tokenize(evidence_text))
    overlap = [token for token in tokens if token in evidence_tokens]
    return len(overlap) >= 2


def _date_or_publication_date_present(example: ExtractedExample, evidence_lookup: Dict[int, Dict[str, Any]]) -> bool:
    if _parse_date_signal(_normalize_text(example.event_date)):
        return True
    if _parse_date_signal(_normalize_text(example.published_date)):
        return True
    for source_id in example.source_ids:
        evidence = evidence_lookup.get(source_id, {})
        if _parse_date_signal(str(evidence.get("date", ""))):
            return True
    return False


def _is_supported_by_evidence(example: ExtractedExample, evidence_lookup: Dict[int, Dict[str, Any]]) -> bool:
    cited_text = _cited_evidence_bundle(example, evidence_lookup)
    if not cited_text:
        return False

    company_match = _company_name_in_evidence(example.company, cited_text)
    event_match = _event_terms_overlap(f"{example.event} {example.text}", cited_text)
    date_match = _date_or_publication_date_present(example, evidence_lookup)
    object_match = _key_object_terms_overlap(example.text, cited_text)

    return bool(company_match and event_match and (date_match or object_match))


def _best_source_tier(example: ExtractedExample, evidence_lookup: Dict[int, Dict[str, Any]]) -> str:
    ranking = {"Tier 1": 3, "Tier 2": 2, "Tier 3": 1}
    best_tier = "Tier 3"
    best_score = 0
    for source_id in example.source_ids:
        tier = str(evidence_lookup.get(source_id, {}).get("source_tier", "Tier 3")).strip() or "Tier 3"
        tier_score = ranking.get(tier, 0)
        if tier_score > best_score:
            best_score = tier_score
            best_tier = tier
    return best_tier


def _best_date_signal(example: ExtractedExample, evidence_lookup: Dict[int, Dict[str, Any]]) -> str:
    for candidate in (
        _normalize_text(example.event_date),
        _normalize_text(example.published_date),
        _normalize_text(example.year),
    ):
        if candidate:
            return candidate
    for source_id in example.source_ids:
        evidence_date = _normalize_text(evidence_lookup.get(source_id, {}).get("date"))
        if evidence_date:
            return evidence_date
    return _extract_year(_normalize_text(example.text))


def _is_market_level_only(example: ExtractedExample) -> bool:
    combined = f"{_normalize_text(example.event)} {_normalize_text(example.text)}".lower()
    return not _has_event_signal(example) or combined.startswith("the market ")


def _location_matches(example: ExtractedExample, trend_context: Dict[str, Any] | None) -> bool:
    if not trend_context:
        return True
    location_value = _normalize_text(trend_context.get("location"))
    if not location_value:
        return True
    if not _normalize_text(example.location):
        return True
    return location_value.lower() in _normalize_text(example.location).lower()


def _score_example(
    example: ExtractedExample,
    evidence_lookup: Dict[int, Dict[str, Any]],
    *,
    research_date: date,
    trend_context: Dict[str, Any] | None,
) -> int:
    score = 0
    cited_text = _cited_evidence_bundle(example, evidence_lookup)
    best_date = _parse_date_signal(_best_date_signal(example, evidence_lookup))
    months_old = _months_old(best_date, research_date=research_date)
    source_tier = _best_source_tier(example, evidence_lookup)
    trend_terms = _topic_terms_from_trend_context(trend_context)
    example_text = f"{_normalize_text(example.event)} {_normalize_text(example.text)}".lower()

    if _normalize_text(example.company):
        score += 2
    if _has_event_signal(example):
        score += 2
    if _has_specific_date_signal(example, evidence_lookup):
        score += 2
    if months_old is not None and months_old <= 24:
        score += 2
    if source_tier in {"Tier 1", "Tier 2"}:
        score += 2
    if trend_terms and any(term in example_text for term in trend_terms[:8]):
        score += 1
    if _company_name_in_evidence(example.company, cited_text):
        score += 2
    if _event_terms_overlap(f"{example.event} {example.text}", cited_text):
        score += 2
    if _location_matches(example, trend_context):
        score += 1
    if _normalize_text(example.trend_fit_reason):
        score += 1

    if months_old is not None and months_old > 36:
        score -= 2
    if _looks_generic(_normalize_text(example.text)):
        score -= 3
    if trend_terms and not any(term in example_text for term in trend_terms[:6]):
        score -= 3
    if _normalize_text(example.company) and not _event_terms_overlap(f"{example.event} {example.text}", cited_text):
        score -= 3
    if _is_market_level_only(example):
        score -= 2
    if not _has_specific_date_signal(example, evidence_lookup):
        score -= 2

    return score


def validate_example(
    example: ExtractedExample,
    evidence_blocks: Sequence[Dict[str, Any]],
    *,
    research_date: date | None = None,
    trend_context: Dict[str, Any] | None = None,
    allow_low_confidence_fallback: bool = False,
    recent_evidence_exists: bool = False,
    max_age_months: int | None = None,
) -> ExampleValidationResult:
    text = _normalize_text(example.text)
    company = _normalize_text(example.company)
    event = _normalize_text(example.event)
    evidence_lookup = _build_evidence_lookup(evidence_blocks)
    resolved_research_date = _research_date(research_date)

    if not text:
        return ExampleValidationResult(accepted=False, reason="empty_text")
    if len(text.split()) < 5:
        return ExampleValidationResult(accepted=False, reason="too_short")
    if _looks_generic(text):
        return ExampleValidationResult(accepted=False, reason="generic_text")

    valid_source_ids = _source_id_set(evidence_blocks)
    normalized_source_ids = [source_id for source_id in example.source_ids if source_id in valid_source_ids]
    if not normalized_source_ids:
        return ExampleValidationResult(accepted=False, reason="invalid_source_ids")

    normalized_example = ExtractedExample(
        company=company,
        event=event,
        text=text,
        event_date=_normalize_text(example.event_date),
        published_date=_normalize_text(example.published_date),
        location=_normalize_text(example.location),
        example_type=_normalize_text(example.example_type),
        confidence=_normalize_text(example.confidence),
        trend_fit_reason=_normalize_text(example.trend_fit_reason),
        source_ids=normalized_source_ids,
        source_quality=_best_source_tier(example, evidence_lookup),
        fallback_used=bool(example.fallback_used),
    )
    normalized_example.year = _best_date_signal(normalized_example, evidence_lookup)

    if not _is_supported_by_evidence(normalized_example, evidence_lookup):
        return ExampleValidationResult(accepted=False, reason="unsupported_by_evidence")

    score = _score_example(
        normalized_example,
        evidence_lookup,
        research_date=resolved_research_date,
        trend_context=trend_context,
    )
    normalized_example.validation_score = score

    if not company and not _has_event_signal(normalized_example):
        return ExampleValidationResult(accepted=False, reason="unsupported_by_evidence", score=score)

    best_date = _parse_date_signal(_best_date_signal(normalized_example, evidence_lookup))
    months_old = _months_old(best_date, research_date=resolved_research_date)
    if max_age_months is not None and months_old is not None and months_old > max_age_months:
        return ExampleValidationResult(accepted=False, reason="too_old", score=score)
    if months_old is not None and months_old > 24 and recent_evidence_exists and not allow_low_confidence_fallback:
        return ExampleValidationResult(accepted=False, reason="unsupported_by_evidence", score=score)

    if score >= 9:
        normalized_example.confidence = "high"
        return ExampleValidationResult(accepted=True, example=normalized_example, score=score)
    if score >= 7:
        normalized_example.confidence = "medium"
        return ExampleValidationResult(accepted=True, example=normalized_example, score=score)
    if allow_low_confidence_fallback and score >= 6:
        normalized_example.confidence = "low"
        normalized_example.fallback_used = True
        return ExampleValidationResult(accepted=True, example=normalized_example, score=score)
    return ExampleValidationResult(accepted=False, reason="unsupported_by_evidence", score=score)


def validate_examples(
    examples: Iterable[ExtractedExample],
    evidence_blocks: Sequence[Dict[str, Any]],
    *,
    research_date: date | None = None,
    trend_context: Dict[str, Any] | None = None,
    allow_low_confidence_fallback: bool = False,
    max_age_months: int | None = None,
) -> tuple[List[ExtractedExample], List[str]]:
    validated: List[ExtractedExample] = []
    discard_reasons: List[str] = []
    seen_keys = set()
    resolved_research_date = _research_date(research_date)
    evidence_lookup = _build_evidence_lookup(evidence_blocks)
    recent_evidence_exists = any(
        (_months_old(_parse_date_signal(str(block.get("published_date") or block.get("date") or "")), research_date=resolved_research_date) or 999) <= 24
        for block in evidence_lookup.values()
    )

    for example in examples:
        result = validate_example(
            example,
            evidence_blocks,
            research_date=resolved_research_date,
            trend_context=trend_context,
            allow_low_confidence_fallback=allow_low_confidence_fallback,
            recent_evidence_exists=recent_evidence_exists,
            max_age_months=max_age_months,
        )
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

    confidence_rank = {"high": 3, "medium": 2, "low": 1}
    tier_rank = {"Tier 1": 3, "Tier 2": 2, "Tier 3": 1}
    validated.sort(
        key=lambda example: (
            confidence_rank.get(str(example.confidence or "").strip(), 0),
            -(_months_old(_parse_date_signal(_best_date_signal(example, evidence_lookup)), research_date=resolved_research_date) or 999),
            tier_rank.get(str(example.source_quality or "").strip(), 0),
            int(example.validation_score or 0),
        ),
        reverse=True,
    )
    return validated, discard_reasons


def evidence_has_strong_example_signals(evidence_blocks: Sequence[Dict[str, Any]]) -> bool:
    for block in evidence_blocks:
        combined = " ".join(
            [
                _normalize_text(block.get("title")),
                _normalize_text(block.get("snippet")),
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
    *,
    trend_contexts: Dict[str, Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    attached_items: List[Dict[str, Any]] = []
    confidence_rank = {"high": 3, "medium": 2, "low": 1}
    tier_rank = {"Tier 1": 3, "Tier 2": 2, "Tier 3": 1}

    for item in items:
        normalized_item = dict(item)
        heading = _normalize_text(normalized_item.get("heading"))
        body = _normalize_text(normalized_item.get("body"))
        item_text = f"{heading} {body}".lower()
        item_source_ids = {
            int(source_id)
            for source_id in normalized_item.get("source_ids", [])
            if str(source_id).strip().isdigit()
        }
        trend_context = (trend_contexts or {}).get(heading.lower(), {})
        location_value = _normalize_text(trend_context.get("location"))
        trend_terms = _topic_terms_from_trend_context(
            {"heading": heading, "body": body, "topic": trend_context.get("topic", "")}
        )

        scored_examples: List[tuple[int, Example, ExtractedExample]] = []
        seen_keys = set()
        for example in validated_examples:
            company_tokens = set(_tokenize(_normalize_text(example.company)))
            source_overlap = len(item_source_ids.intersection(set(example.source_ids)))
            focus_overlap = sum(
                1
                for term in trend_terms[:10]
                if term
                and term not in company_tokens
                and term in f"{_normalize_text(example.event)} {_normalize_text(example.text)}".lower()
            )
            trend_fit_overlap = sum(
                1 for term in _tokenize(_normalize_text(example.trend_fit_reason))[:6] if term and term in item_text
            )
            company_overlap = bool(_normalize_text(example.company) and _normalize_text(example.company).lower() in item_text)
            location_conflict = bool(
                location_value
                and _normalize_text(example.location)
                and location_value.lower() not in _normalize_text(example.location).lower()
            )

            attachment_score = 0
            if source_overlap:
                attachment_score += 3
            if focus_overlap:
                attachment_score += 3
            if trend_fit_overlap:
                attachment_score += 2
            if company_overlap:
                attachment_score += 1
            if company_overlap and not source_overlap and not focus_overlap:
                attachment_score -= 3
            if location_conflict:
                attachment_score -= 2

            if attachment_score < 4:
                continue

            candidate = Example(
                text=example.text,
                company=example.company,
                event=example.event,
                event_date=example.event_date,
                published_date=example.published_date,
                location=example.location,
                example_type=example.example_type,
                why_it_matters=example.trend_fit_reason,
                source_quality=example.source_quality,
                confidence=example.confidence,
                validation_score=example.validation_score,
                fallback_used=bool(example.fallback_used),
                year=example.year,
            )
            dedupe_key = (candidate.text.lower(), candidate.year or "")
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            scored_examples.append((attachment_score, candidate, example))

        scored_examples.sort(
            key=lambda entry: (
                confidence_rank.get(str(entry[1].confidence or "").strip(), 0),
                int(entry[1].validation_score or 0),
                tier_rank.get(str(entry[1].source_quality or "").strip(), 0),
                entry[0],
            ),
            reverse=True,
        )

        normalized_item["examples"] = [candidate.model_dump() for _, candidate, _ in scored_examples[:MAX_VALIDATED_EXAMPLES_PER_TREND]]
        attached_items.append(normalized_item)

    return attached_items
