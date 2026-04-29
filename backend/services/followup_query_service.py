import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from openai import OpenAI

from config.settings import settings
from models.response_models import FollowUpResponse
from services.external_client import call_openai_sync
from services.openai_service import OPENAI_TIMEOUT_SECONDS, can_use_openai, ensure_min_output_tokens

logger = logging.getLogger(__name__)

FOLLOW_UP_MODEL = settings.OPENAI_QUERY_MODEL or "gpt-4o-mini"
FOLLOW_UP_MAX_RETRIES = 1
FOLLOW_UP_MAX_OUTPUT_TOKENS = 700
MAX_CHUNKS_FOR_DECISION = 18
MAX_CHUNK_CHARS = 900
MAX_TOTAL_CHARS = 12000
MIN_SOURCE_DIVERSITY_FOR_SUFFICIENT = 2
INSUFFICIENT_SIGNAL_THRESHOLD = 2
PARTIAL_SIGNAL_THRESHOLD = 5
M_AND_A_TERMS = (
    "m&a",
    "merger",
    "mergers",
    "acquisition",
    "acquisitions",
    "deal",
    "deals",
    "buyout",
    "buyouts",
    "takeover",
    "takeovers",
    "consolidation",
    "investment",
    "investments",
)
DIRECTIONAL_TERMS = (
    "increase",
    "increased",
    "growing",
    "growth",
    "decline",
    "declining",
    "rise",
    "rising",
    "surge",
    "higher",
    "lower",
    "accelerating",
    "slowing",
    "up",
    "down",
)
QUANT_SIGNAL_PATTERN = re.compile(r"\b\d+(?:\.\d+)?(?:%|x| million| billion| bn| m| k)?\b", re.IGNORECASE)
WORD_PATTERN = re.compile(r"[a-z0-9&]+", re.IGNORECASE)
WHITESPACE_PATTERN = re.compile(r"\s+")


def _normalize_text(value: Any) -> str:
    return WHITESPACE_PATTERN.sub(" ", str(value or "")).strip()


def _normalize_query(value: str) -> str:
    cleaned = _normalize_text(value)
    cleaned = re.sub(r"\bma\b", "M&A", cleaned, flags=re.IGNORECASE)
    return cleaned


def _tokenize(text: str) -> List[str]:
    return [token.lower() for token in WORD_PATTERN.findall(text.lower()) if token]


def _clean_metadata(existing_metadata: Optional[Dict[str, Any]]) -> Dict[str, str]:
    metadata = existing_metadata or {}
    return {
        "topic": _normalize_text(metadata.get("topic")),
        "section": _normalize_text(metadata.get("section")).lower(),
        "location": _normalize_text(metadata.get("location") or metadata.get("location_value")),
    }


def _prepare_chunks(existing_filtered_chunks: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    prepared_chunks: List[Dict[str, str]] = []
    total_chars = 0

    for chunk in existing_filtered_chunks[:MAX_CHUNKS_FOR_DECISION]:
        text = _normalize_text(chunk.get("text"))
        source_id = _normalize_text(chunk.get("source_id")) or "unknown_source"
        if not text:
            continue

        clipped_text = text[:MAX_CHUNK_CHARS].strip()
        remaining_chars = MAX_TOTAL_CHARS - total_chars
        if remaining_chars <= 0:
            break
        if len(clipped_text) > remaining_chars:
            clipped_text = clipped_text[:remaining_chars].rstrip()
        if not clipped_text:
            continue

        prepared_chunks.append({"text": clipped_text, "source_id": source_id})
        total_chars += len(clipped_text)

    return prepared_chunks


def _extract_focus_terms(refined_query: str, metadata: Dict[str, str]) -> List[str]:
    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "into",
        "give",
        "show",
        "find",
        "about",
        "related",
        "identify",
        "industry",
        "market",
        "given",
        "recent",
        "latest",
        "trends",
        "trend",
        "drivers",
        "driver",
        "specific",
    }
    metadata_terms = set(_tokenize(" ".join(value for value in metadata.values() if value)))
    focus_terms: List[str] = []

    for token in _tokenize(refined_query):
        if len(token) < 3 and token != "m&a":
            continue
        if token in stopwords or token in metadata_terms:
            continue
        if token not in focus_terms:
            focus_terms.append(token)

    return focus_terms[:4]


def _score_existing_data(prepared_chunks: Sequence[Dict[str, str]], refined_query: str) -> Dict[str, Any]:
    if not prepared_chunks:
        return {
            "keyword_hits": 0,
            "quantitative_hits": 0,
            "directional_hits": 0,
            "focus_hits": 0,
            "source_diversity": 0,
            "score": 0,
        }

    focus_terms = _extract_focus_terms(refined_query, {})
    keyword_hits = 0
    quantitative_hits = 0
    directional_hits = 0
    focus_hits = 0
    source_ids = set()

    for chunk in prepared_chunks:
        text = str(chunk["text"])
        lowered = text.lower()
        source_ids.add(str(chunk["source_id"]))

        if any(term in lowered for term in M_AND_A_TERMS):
            keyword_hits += 1
        if QUANT_SIGNAL_PATTERN.search(text):
            quantitative_hits += 1
        if any(term in lowered for term in DIRECTIONAL_TERMS):
            directional_hits += 1
        if focus_terms and any(term in lowered for term in focus_terms):
            focus_hits += 1

    source_diversity = len(source_ids)
    score = keyword_hits * 2 + quantitative_hits + directional_hits + focus_hits + min(source_diversity, 3)
    return {
        "keyword_hits": keyword_hits,
        "quantitative_hits": quantitative_hits,
        "directional_hits": directional_hits,
        "focus_hits": focus_hits,
        "source_diversity": source_diversity,
        "score": score,
    }


def _build_refined_query(follow_up_query: str, metadata: Dict[str, str]) -> str:
    cleaned_query = _normalize_query(follow_up_query)
    lowered = cleaned_query.lower()
    section = metadata.get("section") or "trends"
    topic = metadata.get("topic")
    location = metadata.get("location")

    if "m&a" in lowered or "merger" in lowered or "acquisition" in lowered:
        section_word = "drivers" if section == "drivers" else "trends"
        base = f"Identify {section_word} related to mergers and acquisitions"
        if topic:
            base += f" in {topic}"
        if location:
            base += f" in {location}"
        return base

    if topic and topic.lower() not in lowered:
        cleaned_query = f"{cleaned_query} in {topic}"
    if location and location.lower() not in cleaned_query.lower():
        cleaned_query = f"{cleaned_query} in {location}"
    return cleaned_query


def _build_expansion_queries(refined_query: str, metadata: Dict[str, str]) -> List[str]:
    location = metadata.get("location")
    topic = metadata.get("topic")
    section = metadata.get("section") or "trends"
    focus_terms = _extract_focus_terms(refined_query, metadata)
    focus_phrase = " ".join(focus_terms[:2]).strip()
    scope = topic or "industry"
    geo = location or ""
    section_word = "drivers" if section == "drivers" else "trends"

    templates = [
        "{scope} {geo} {focus} {section_word} recent deals report",
        "{scope} {geo} mergers acquisitions activity latest data",
        "{scope} {geo} consolidation investment deal activity trends",
        "{scope} {geo} acquisition pipeline strategic deals report",
        "{scope} {geo} private equity buyout acquisition trends",
        "{scope} {geo} merger acquisition market consolidation report",
        "{scope} {geo} recent transactions investment activity data",
        "{scope} {geo} strategic partnerships acquisitions expansion trends",
    ]

    queries: List[str] = []
    seen = set()
    for template in templates:
        query = _normalize_text(
            template.format(
                scope=scope,
                geo=geo,
                focus=focus_phrase,
                section_word=section_word,
            )
        )
        normalized_key = query.lower()
        if not query or normalized_key in seen:
            continue
        seen.add(normalized_key)
        queries.append(query)

    return queries[:8]


def _fallback_response(
    follow_up_query: str,
    prepared_chunks: Sequence[Dict[str, str]],
    metadata: Dict[str, str],
    *,
    api_error: Optional[Exception] = None,
) -> Dict[str, Any]:
    refined_query = _build_refined_query(follow_up_query, metadata)
    scorecard = _score_existing_data(prepared_chunks, refined_query)
    decision = "PARTIAL"

    if scorecard["keyword_hits"] == 0 and scorecard["score"] <= INSUFFICIENT_SIGNAL_THRESHOLD:
        decision = "INSUFFICIENT"
    elif (
        scorecard["keyword_hits"] >= 2
        and scorecard["quantitative_hits"] >= 1
        and scorecard["source_diversity"] >= MIN_SOURCE_DIVERSITY_FOR_SUFFICIENT
        and scorecard["score"] >= PARTIAL_SIGNAL_THRESHOLD + 2
    ):
        decision = "SUFFICIENT"

    reason = (
        f"Fallback decision based on keyword hits={scorecard['keyword_hits']}, "
        f"directional signals={scorecard['directional_hits']}, "
        f"quantitative signals={scorecard['quantitative_hits']}, "
        f"source diversity={scorecard['source_diversity']}."
    )
    if api_error:
        reason = f"{reason} OpenAI fallback triggered after error: {api_error}"

    response = {
        "decision": decision,
        "refined_query": refined_query,
        "reason": reason,
    }
    if decision != "SUFFICIENT":
        response["new_queries"] = _build_expansion_queries(refined_query, metadata)
    return FollowUpResponse(**response).model_dump()


def _build_messages(
    follow_up_query: str,
    prepared_chunks: Sequence[Dict[str, str]],
    metadata: Dict[str, str],
    scorecard: Dict[str, Any],
) -> List[Dict[str, str]]:
    system_prompt = """
You are a follow-up query controller for an AI OSINT research platform.

Your job is to decide whether the existing filtered evidence is enough to answer a follow-up query.
Do not generate final insights.
Do not summarize the chunks.
Only decide whether reuse is enough and whether targeted search expansion is needed.

Return strict JSON only with this exact schema:
{
  "decision": "SUFFICIENT" | "PARTIAL" | "INSUFFICIENT",
  "refined_query": "cleaned query",
  "reason": "brief justification",
  "new_queries": ["focused search query"]
}

Rules:
- Be conservative and prefer reuse when evidence is clearly adequate.
- Use SUFFICIENT only when existing chunks contain direct signals for the follow-up topic across multiple sources.
- Use PARTIAL when some relevant signals exist but coverage, strength, or source diversity is limited.
- Use INSUFFICIENT when relevant evidence is minimal or absent.
- If decision is SUFFICIENT, return an empty array for new_queries.
- If decision is PARTIAL or INSUFFICIENT, return 5 to 8 tightly focused search queries.
- Preserve geography if metadata contains it.
- Keep refined_query simple, specific, and useful.
""".strip()

    payload = {
        "follow_up_query": _normalize_query(follow_up_query),
        "existing_metadata": metadata,
        "heuristic_scorecard": scorecard,
        "existing_filtered_chunks": list(prepared_chunks),
    }
    user_prompt = (
        "Decide whether the existing filtered evidence is enough for the follow-up request.\n\n"
        f"{json.dumps(payload, ensure_ascii=True)}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _parse_response(response: Any) -> Dict[str, Any]:
    parsed = getattr(response, "output_parsed", None)
    if isinstance(parsed, FollowUpResponse):
        return parsed.model_dump()

    for output in getattr(response, "output", []):
        if getattr(output, "type", "") != "message":
            continue
        for item in getattr(output, "content", []):
            if getattr(item, "type", "") == "refusal":
                raise RuntimeError(str(getattr(item, "refusal", "Follow-up query decision was refused.")))
            candidate = getattr(item, "parsed", None)
            if isinstance(candidate, FollowUpResponse):
                return candidate.model_dump()

    raise ValueError("Structured follow-up response did not contain parsed content.")


def handle_followup_query(
    follow_up_query: str,
    existing_filtered_chunks: List[dict],
    existing_metadata: Optional[Dict[str, Any]] = None,
) -> dict:
    normalized_query = _normalize_query(follow_up_query)
    if not normalized_query:
        return FollowUpResponse(
            decision="PARTIAL",
            refined_query="Clarify the follow-up research request",
            reason="Follow-up query was empty after normalization.",
            new_queries=[],
        ).model_dump()

    prepared_chunks = _prepare_chunks(existing_filtered_chunks or [])
    metadata = _clean_metadata(existing_metadata)

    if not prepared_chunks:
        return _fallback_response(normalized_query, prepared_chunks, metadata)

    scorecard = _score_existing_data(prepared_chunks, _build_refined_query(normalized_query, metadata))
    if not settings.OPENAI_API_KEY or not can_use_openai():
        logger.warning("OpenAI unavailable for follow-up decision. Using heuristic fallback.")
        return _fallback_response(normalized_query, prepared_chunks, metadata)

    messages = _build_messages(normalized_query, prepared_chunks, metadata, scorecard)
    client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=OPENAI_TIMEOUT_SECONDS)
    last_error: Optional[Exception] = None

    try:
        for attempt in range(1, FOLLOW_UP_MAX_RETRIES + 2):
            try:
                response = call_openai_sync(
                    "followup_decision",
                    lambda: client.responses.parse(
                        model=FOLLOW_UP_MODEL,
                        input=messages,
                        text_format=FollowUpResponse,
                        max_output_tokens=ensure_min_output_tokens(FOLLOW_UP_MAX_OUTPUT_TOKENS),
                    ),
                    fallback=None,
                    timeout=OPENAI_TIMEOUT_SECONDS,
                    max_retries=FOLLOW_UP_MAX_RETRIES,
                    context={"model": FOLLOW_UP_MODEL, "query": normalized_query},
                )
                if response is None:
                    raise RuntimeError("Follow-up query decision returned no response.")
                return _parse_response(response)
            except (ValueError, RuntimeError) as exc:
                last_error = exc
                logger.warning("Follow-up query attempt %s failed: %s", attempt, exc)
                if attempt <= FOLLOW_UP_MAX_RETRIES:
                    continue
    finally:
        client.close()

    logger.exception("Follow-up query decision failed after retries.", exc_info=last_error)
    return _fallback_response(normalized_query, prepared_chunks, metadata, api_error=last_error)

