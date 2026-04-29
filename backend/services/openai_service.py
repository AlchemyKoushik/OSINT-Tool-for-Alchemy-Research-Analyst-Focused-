import asyncio
import logging
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Sequence

from openai import AsyncOpenAI, OpenAI

from config.settings import settings
from models.response_models import Insight, Output
from services.external_client import call_openai, call_openai_sync
from services.prompt_builder import get_section_title
from services.ranking_service import rank_and_limit_insights
from services.source_attribution_service import attach_sources_to_items

logger = logging.getLogger(__name__)

MODEL_NAME = settings.OPENAI_ANALYSIS_MODEL or "gpt-5.5"
OPENAI_TEST_MODEL = settings.OPENAI_TEST_MODEL or "gpt-4o-mini"
OPENAI_TIMEOUT_SECONDS = settings.EXTERNAL_TIMEOUT_SECONDS
OPENAI_MAX_RETRIES = settings.EXTERNAL_MAX_RETRIES
MIN_OUTPUT_TOKENS = 16
DEFAULT_MAX_OUTPUT_TOKENS = 256
MAX_OUTPUT_TOKENS = 2600
GENERIC_DESCRIPTION_MARKERS = (
    "the market is growing",
    "the industry is evolving",
    "technology is improving",
    "this suggests opportunity",
    "future outlook",
    "report examines",
)
GENERIC_TITLE_MARKERS = (
    "market overview",
    "industry overview",
    "key trend",
    "key driver",
    "future outlook",
    "analysis and forecast",
    "market size",
)
GARBAGE_MARKERS = ("http", "www", "source:", "note:", "click here", "read more", "copyright")
RAW_SOURCE_TEXT_MARKERS = (
    "the report examines",
    "future outlook",
    "forecast period",
    "analysis and forecasts",
    "what is the expected",
)
SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?])\s+")
TITLE_DESCRIPTION_PREFIX_WORDS = 5

_OPENAI_RUNTIME_STATE: Dict[str, Any] = {
    "key_loaded": False,
    "connection_tested": False,
    "connection_ok": False,
    "message": "OpenAI runtime not checked yet.",
}


def ensure_min_output_tokens(user_value: Optional[Any], default_value: int = DEFAULT_MAX_OUTPUT_TOKENS) -> int:
    try:
        resolved_value = int(user_value) if user_value is not None else int(default_value)
    except (TypeError, ValueError):
        resolved_value = int(default_value)
    return max(resolved_value, MIN_OUTPUT_TOKENS)


def _set_runtime_state(
    *,
    key_loaded: Optional[bool] = None,
    connection_tested: Optional[bool] = None,
    connection_ok: Optional[bool] = None,
    message: Optional[str] = None,
) -> None:
    if key_loaded is not None:
        _OPENAI_RUNTIME_STATE["key_loaded"] = key_loaded
    if connection_tested is not None:
        _OPENAI_RUNTIME_STATE["connection_tested"] = connection_tested
    if connection_ok is not None:
        _OPENAI_RUNTIME_STATE["connection_ok"] = connection_ok
    if message is not None:
        _OPENAI_RUNTIME_STATE["message"] = message


def openai_key_loaded() -> bool:
    loaded = bool(settings.OPENAI_API_KEY.strip())
    _set_runtime_state(
        key_loaded=loaded,
        connection_tested=False if not loaded else _OPENAI_RUNTIME_STATE["connection_tested"],
        connection_ok=False if not loaded else _OPENAI_RUNTIME_STATE["connection_ok"],
        message="OPENAI_API_KEY missing" if not loaded else _OPENAI_RUNTIME_STATE["message"],
    )
    logger.info("openai_key_loaded=%s", loaded)
    return loaded


def can_use_openai() -> bool:
    if not bool(settings.OPENAI_API_KEY.strip()):
        return False
    if _OPENAI_RUNTIME_STATE["connection_tested"]:
        return bool(_OPENAI_RUNTIME_STATE["connection_ok"])
    return True


def get_openai_status_message() -> str:
    return str(_OPENAI_RUNTIME_STATE.get("message", "OpenAI runtime status unavailable."))


def _log_openai_error(error: Exception, prefix: str = "OpenAI ERROR") -> None:
    error_message = str(error)
    logger.error("%s: %s", prefix, error_message)

    lowered_message = error_message.lower()
    if "insufficient_quota" in lowered_message:
        _set_runtime_state(connection_tested=True, connection_ok=False, message=error_message)
    elif "api key" in lowered_message or "authentication" in lowered_message:
        _set_runtime_state(connection_tested=True, connection_ok=False, message=error_message)


def test_openai_connection() -> bool:
    api_key = settings.OPENAI_API_KEY.strip()
    if not api_key:
        message = "OPENAI_API_KEY missing"
        logger.error("OpenAI Connection FAILED: %s", message)
        _set_runtime_state(
            key_loaded=False,
            connection_tested=True,
            connection_ok=False,
            message=message,
        )
        return False

    client = OpenAI(api_key=api_key)
    try:
        response = call_openai_sync(
            "openai_connection_test",
            lambda: client.responses.create(
                model=OPENAI_TEST_MODEL,
                input="Reply with OK.",
                max_output_tokens=ensure_min_output_tokens(8),
            ),
            fallback=None,
            timeout=OPENAI_TIMEOUT_SECONDS,
            max_retries=OPENAI_MAX_RETRIES,
            context={"model": OPENAI_TEST_MODEL},
        )
        if response is None:
            raise RuntimeError("OpenAI connection test returned no response.")
        logger.info("OpenAI Connection: SUCCESS")
        _set_runtime_state(
            key_loaded=True,
            connection_tested=True,
            connection_ok=True,
            message="OpenAI connection healthy.",
        )
        return True
    except Exception as exc:
        logger.error("OpenAI Connection FAILED: %s", exc)
        _log_openai_error(exc, prefix="OpenAI ERROR")
        _set_runtime_state(
            key_loaded=True,
            connection_tested=True,
            connection_ok=False,
            message=str(exc),
        )
        return False
    finally:
        client.close()


def _extract_parsed_output(response: Any) -> Output:
    for output in getattr(response, "output", []):
        if getattr(output, "type", "") != "message":
            continue

        for item in getattr(output, "content", []):
            if getattr(item, "type", "") == "refusal":
                raise RuntimeError(str(getattr(item, "refusal", "OpenAI refused the request.")))

            parsed = getattr(item, "parsed", None)
            if isinstance(parsed, Output):
                return parsed

    raise ValueError("Structured response did not contain parsed content.")


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _count_sentences(text: str) -> int:
    return len([part for part in SENTENCE_BOUNDARY_PATTERN.split(text.strip()) if part.strip()])


def _titles_are_similar(title_a: str, title_b: str) -> bool:
    normalized_a = _normalize_title(title_a)
    normalized_b = _normalize_title(title_b)
    if not normalized_a or not normalized_b:
        return False
    if normalized_a == normalized_b:
        return True
    return SequenceMatcher(None, normalized_a, normalized_b).ratio() >= 0.84


def _descriptions_are_similar(description_a: str, description_b: str) -> bool:
    normalized_a = _normalize_text(description_a).lower()
    normalized_b = _normalize_text(description_b).lower()
    if not normalized_a or not normalized_b:
        return False
    return SequenceMatcher(None, normalized_a, normalized_b).ratio() >= 0.82


def _normalize_phrase_words(text: str, limit: int) -> str:
    normalized = re.sub(r"[^a-z0-9\s]+", " ", text.lower())
    words = [word for word in normalized.split() if word]
    return " ".join(words[:limit])


def _title_repeats_description(title: str, description: str) -> bool:
    title_prefix = _normalize_phrase_words(title, TITLE_DESCRIPTION_PREFIX_WORDS)
    description_prefix = _normalize_phrase_words(description, TITLE_DESCRIPTION_PREFIX_WORDS)
    return bool(title_prefix and description_prefix and title_prefix == description_prefix)


def _looks_like_raw_source_text(title: str, description: str) -> bool:
    lowered_title = title.lower().strip()
    lowered_description = description.lower().strip()
    if "?" in title or lowered_title.startswith(("what ", "how ", "why ", "when ")):
        return True
    return any(marker in lowered_title or marker in lowered_description for marker in RAW_SOURCE_TEXT_MARKERS)


def _is_generic_insight(title: str, description: str) -> bool:
    lowered_title = title.lower()
    lowered_description = description.lower()
    if any(marker in lowered_title for marker in GENERIC_TITLE_MARKERS):
        return True
    if any(marker in lowered_description for marker in GENERIC_DESCRIPTION_MARKERS):
        return True
    if any(marker in lowered_title or marker in lowered_description for marker in GARBAGE_MARKERS):
        return True
    return False


def _validate_structured_output(parsed: Output) -> Output:
    filtered_items: List[Insight] = []

    for item in parsed.items:
        title = _normalize_text(item.title)
        description = _normalize_text(item.description)
        if not title or not description:
            continue
        if _looks_like_raw_source_text(title, description):
            continue
        if _title_repeats_description(title, description):
            continue
        if _is_generic_insight(title, description):
            continue
        if len(title.split()) < 3 or len(title.split()) > 14:
            continue
        if len(description) < 90:
            continue
        sentence_count = _count_sentences(description)
        if sentence_count < 2 or sentence_count > 4:
            continue

        if any(
            _titles_are_similar(title, existing.title) or _descriptions_are_similar(description, existing.description)
            for existing in filtered_items
        ):
            continue

        filtered_items.append(Insight(title=title, description=description, source_ids=list(item.source_ids)))

    if not filtered_items:
        raise ValueError("Structured output did not contain any usable insights.")

    return Output(items=filtered_items)


async def _request_structured_completion(client: AsyncOpenAI, input_payload: List[Dict[str, str]]) -> Output:
    response = await call_openai(
        "structured_section_analysis",
        lambda: client.responses.parse(
            model=MODEL_NAME,
            input=input_payload,
            text_format=Output,
            max_output_tokens=ensure_min_output_tokens(MAX_OUTPUT_TOKENS),
        ),
        fallback=None,
        timeout=OPENAI_TIMEOUT_SECONDS,
        max_retries=OPENAI_MAX_RETRIES,
        context={"model": MODEL_NAME},
    )
    if response is None:
        raise RuntimeError("Failed to generate structured analysis output.")
    _set_runtime_state(
        key_loaded=True,
        connection_tested=True,
        connection_ok=True,
        message="OpenAI connection healthy.",
    )
    return _extract_parsed_output(response)


async def generate_section_analysis(
    system_prompt: str,
    metadata: str,
    section: str,
    max_items: int = 10,
    evidence_blocks: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    api_key = settings.OPENAI_API_KEY.strip()
    if not api_key:
        error = ValueError("OPENAI_API_KEY is not configured")
        _log_openai_error(error)
        raise error

    if not can_use_openai():
        raise RuntimeError(get_openai_status_message())

    client = AsyncOpenAI(api_key=api_key)
    base_input = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": metadata},
    ]
    validation_error: Optional[str] = None

    try:
        for attempt in range(1, OPENAI_MAX_RETRIES + 2):
            input_payload = list(base_input)
            if validation_error:
                input_payload.append(
                    {
                        "role": "user",
                        "content": (
                            "The previous response was low quality. Regenerate the full JSON and fix these issues:\n"
                            f"{validation_error}"
                        ),
                    }
                )

            parsed = await _request_structured_completion(client, input_payload)
            try:
                validated = _validate_structured_output(parsed)
                ranked_items = rank_and_limit_insights(
                    [
                        {
                            "heading": item.title,
                            "body": item.description,
                            "source_ids": list(item.source_ids),
                        }
                        for item in validated.items
                    ],
                    limit=max_items,
                )
                return {
                    "section": section,
                    "title": get_section_title(section),
                    "items": attach_sources_to_items(ranked_items, evidence_blocks or []),
                }
            except ValueError as exc:
                validation_error = str(exc)
                if attempt > OPENAI_MAX_RETRIES:
                    raise

        raise RuntimeError("Structured analysis failed after the allowed retry.")
    finally:
        await client.close()

