import logging
import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from openai import OpenAI

from config.settings import settings
from models.response_models import ContentFilterResponse
from services.external_client import call_openai_sync
from services.openai_service import (
    OPENAI_TIMEOUT_SECONDS,
    can_use_openai,
    ensure_min_output_tokens,
)
from services.prompt_file_service import get_content_filter_prompt_template

logger = logging.getLogger(__name__)

CONTENT_FILTER_MODEL = settings.OPENAI_SUPPORT_MODEL or settings.OPENAI_QUERY_MODEL or "gpt-4.1-mini"
CONTENT_FILTER_MAX_RETRIES = 1
CONTENT_FILTER_MAX_OUTPUT_TOKENS = 900
MIN_CHUNK_WORDS = 8
MAX_CHUNK_WORDS = 80
MAX_DOCS = 20
MAX_CHUNKS_PER_DOC = 12
MAX_DOC_CHARS = 5000
MAX_TOTAL_INPUT_CHARS = 30000
CHUNK_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")
URL_PATTERN = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
WHITESPACE_PATTERN = re.compile(r"\s+")
NUMERIC_PATTERN = re.compile(r"\b\d+(?:\.\d+)?(?:%|x| million| billion| bn| m| k)?\b", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
GARBAGE_MARKERS = (
    "thank you for reading",
    "subscribe",
    "contact us",
    "all rights reserved",
    "privacy policy",
    "terms of use",
    "cookie policy",
    "follow us",
    "share this",
    "read more",
    "click here",
    "sign up",
    "newsletter",
    "advertisement",
    "advertorial",
    "sponsored",
    "menu",
    "navigation",
    "footer",
    "header",
    "breadcrumbs",
)
LOW_SIGNAL_MARKERS = (
    "industry is growing",
    "market is growing",
    "is expected to grow",
    "plays an important role",
    "is a key market",
    "continues to evolve",
    "various factors",
    "in today's world",
)
TREND_MARKERS = (
    "increase",
    "decrease",
    "rise",
    "decline",
    "shift",
    "adoption",
    "growth",
    "expansion",
    "acceleration",
    "uptake",
    "transition",
    "emerging",
    "surge",
    "higher",
    "lower",
)
DRIVER_MARKERS = (
    "because",
    "driven by",
    "due to",
    "led by",
    "resulting from",
    "supported by",
    "regulation",
    "policy",
    "subsidy",
    "investment",
    "cost",
    "demand",
    "supply",
    "labor",
    "capacity",
    "infrastructure",
)


def _normalize_whitespace(text: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", str(text or "")).strip()


def _word_count(text: str) -> int:
    return len([part for part in text.split(" ") if part])


def _clean_text(text: str) -> str:
    cleaned = URL_PATTERN.sub(" ", str(text or ""))
    cleaned = cleaned.replace("\r", "\n").replace("\xa0", " ")
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    lines: List[str] = []
    for raw_line in cleaned.splitlines():
        line = _normalize_whitespace(raw_line)
        if not line:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _looks_like_garbage(text: str) -> bool:
    normalized = _normalize_whitespace(text).lower()
    if not normalized:
        return True
    if any(marker in normalized for marker in GARBAGE_MARKERS):
        return True
    if _word_count(normalized) < MIN_CHUNK_WORDS:
        return True
    return False


def _is_high_signal(text: str) -> bool:
    lowered = text.lower()
    if any(marker in lowered for marker in LOW_SIGNAL_MARKERS):
        return False

    signal_score = 0
    if NUMERIC_PATTERN.search(text):
        signal_score += 2
    if YEAR_PATTERN.search(text):
        signal_score += 1
    if any(marker in lowered for marker in TREND_MARKERS):
        signal_score += 1
    if any(marker in lowered for marker in DRIVER_MARKERS):
        signal_score += 1

    return signal_score >= 2


def _chunk_document(text: str) -> List[str]:
    cleaned = _clean_text(text)
    if not cleaned:
        return []

    chunks: List[str] = []
    current_parts: List[str] = []
    current_word_count = 0

    for part in CHUNK_SPLIT_PATTERN.split(cleaned):
        sentence = _normalize_whitespace(part)
        if not sentence or _looks_like_garbage(sentence):
            continue

        sentence_word_count = _word_count(sentence)
        if sentence_word_count > MAX_CHUNK_WORDS:
            sentence = " ".join(sentence.split()[:MAX_CHUNK_WORDS]).strip()
            sentence_word_count = _word_count(sentence)

        projected_count = current_word_count + sentence_word_count
        if current_parts and projected_count > MAX_CHUNK_WORDS:
            chunk = _normalize_whitespace(" ".join(current_parts))
            if chunk:
                chunks.append(chunk)
            current_parts = [sentence]
            current_word_count = sentence_word_count
        else:
            current_parts.append(sentence)
            current_word_count = projected_count

    if current_parts:
        chunk = _normalize_whitespace(" ".join(current_parts))
        if chunk:
            chunks.append(chunk)

    return chunks[:MAX_CHUNKS_PER_DOC]


def _build_source_id(index: int) -> str:
    return f"doc_{index + 1}"


def _prepare_documents(scraped_data: Sequence[str]) -> List[Dict[str, Any]]:
    prepared_docs: List[Dict[str, Any]] = []
    total_chars = 0

    for index, raw_text in enumerate(list(scraped_data)[:MAX_DOCS]):
        cleaned = _clean_text(raw_text)[:MAX_DOC_CHARS].strip()
        if not cleaned:
            continue
        remaining_chars = MAX_TOTAL_INPUT_CHARS - total_chars
        if remaining_chars <= 0:
            break
        if len(cleaned) > remaining_chars:
            cleaned = cleaned[:remaining_chars].rstrip()
        if not cleaned:
            continue
        prepared_docs.append(
            {
                "source_id": _build_source_id(index),
                "text": cleaned,
                "chunks": _chunk_document(cleaned),
            }
        )
        total_chars += len(cleaned)

    return prepared_docs


def _fallback_reason(text: str) -> str:
    lowered = text.lower()
    if NUMERIC_PATTERN.search(text):
        return "Quantitative signal indicating a trend or driver"
    if any(marker in lowered for marker in DRIVER_MARKERS):
        return "Cause-effect relationship indicating a market driver"
    return "Directional industry signal relevant to trends or drivers"


def _fallback_filter(prepared_docs: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, str]]]:
    seen = set()
    cleaned_chunks: List[Dict[str, str]] = []

    for doc in prepared_docs:
        source_id = str(doc.get("source_id", "")).strip()
        for chunk in doc.get("chunks", []):
            normalized = _normalize_whitespace(str(chunk)).lower()
            if not normalized or normalized in seen:
                continue
            if _looks_like_garbage(normalized):
                continue
            if not _is_high_signal(normalized):
                continue
            seen.add(normalized)
            cleaned_chunks.append(
                {
                    "text": _normalize_whitespace(str(chunk)),
                    "reason": _fallback_reason(str(chunk)),
                    "source_id": source_id,
                }
            )

    return {"cleaned_chunks": cleaned_chunks}


def _build_messages(prepared_docs: Sequence[Dict[str, Any]]) -> Tuple[str, str]:
    system_prompt = get_content_filter_prompt_template()

    input_payload = {
        "documents": [
            {
                "source_id": str(doc["source_id"]),
                "chunks": [str(chunk) for chunk in doc.get("chunks", []) if str(chunk).strip()],
            }
            for doc in prepared_docs
            if doc.get("chunks")
        ]
    }
    user_prompt = (
        "Filter the following extracted document chunks and return only the high-signal content.\n\n"
        f"{json.dumps(input_payload, ensure_ascii=True)}"
    )
    return system_prompt, user_prompt


def _parse_llm_response(response: Any) -> Dict[str, List[Dict[str, str]]]:
    parsed = getattr(response, "output_parsed", None)
    if isinstance(parsed, ContentFilterResponse):
        return parsed.model_dump()

    for output in getattr(response, "output", []):
        if getattr(output, "type", "") != "message":
            continue
        for item in getattr(output, "content", []):
            if getattr(item, "type", "") == "refusal":
                raise RuntimeError(str(getattr(item, "refusal", "Content filtering was refused.")))
            candidate = getattr(item, "parsed", None)
            if isinstance(candidate, ContentFilterResponse):
                return candidate.model_dump()

    raise ValueError("Structured content filter response did not contain parsed content.")


def filter_content(scraped_data: List[str]) -> dict:
    if not isinstance(scraped_data, list):
        raise ValueError("scraped_data must be a list of strings.")

    prepared_docs = _prepare_documents(scraped_data)
    if not prepared_docs:
        return {"cleaned_chunks": []}

    if not settings.OPENAI_API_KEY or not can_use_openai():
        logger.warning("OpenAI unavailable for content filtering. Using heuristic fallback.")
        return _fallback_filter(prepared_docs)

    system_prompt, user_prompt = _build_messages(prepared_docs)
    client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=OPENAI_TIMEOUT_SECONDS)
    last_error: Optional[Exception] = None

    try:
        for attempt in range(1, CONTENT_FILTER_MAX_RETRIES + 2):
            try:
                response = call_openai_sync(
                    "content_filter",
                    lambda: client.responses.parse(
                        model=CONTENT_FILTER_MODEL,
                        input=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        text_format=ContentFilterResponse,
                        max_output_tokens=ensure_min_output_tokens(CONTENT_FILTER_MAX_OUTPUT_TOKENS),
                    ),
                    fallback=None,
                    timeout=OPENAI_TIMEOUT_SECONDS,
                    max_retries=CONTENT_FILTER_MAX_RETRIES,
                    context={"model": CONTENT_FILTER_MODEL},
                )
                if response is None:
                    raise RuntimeError("Content filtering returned no response.")
                return _parse_llm_response(response)
            except (ValueError, RuntimeError) as exc:
                last_error = exc
                logger.warning("Content filtering attempt %s failed: %s", attempt, exc)
                if attempt <= CONTENT_FILTER_MAX_RETRIES:
                    continue
    finally:
        client.close()

    logger.exception("Content filtering failed after retries.", exc_info=last_error)
    return _fallback_filter(prepared_docs)

