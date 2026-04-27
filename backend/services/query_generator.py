import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from config.settings import settings
from models.response_models import GeneratedSearchQueries
from services.location_service import LocationContext
from services.openai_service import can_use_openai, ensure_min_output_tokens
from services.prompt_file_service import get_search_query_prompt_template

logger = logging.getLogger(__name__)

DEBUG = True
QUERY_MODEL_NAME = settings.OPENAI_QUERY_MODEL or "gpt-4o-mini"
QUERY_TIMEOUT_SECONDS = 25
QUERY_MAX_RETRIES = 1
MIN_QUERY_COUNT = 15
MAX_QUERY_COUNT = 15
DATA_TERMS = ("statistics", "report", "forecast", "data")
BANNED_QUERY_PHRASES = (
    "analysis of",
    "overview of",
    "cagr",
    "future outlook",
    "forecast period",
)
SECTION_QUERY_FOCUSES = {
    "drivers": (
        "demand",
        "cost",
        "policy",
        "regulation",
        "investment",
        "infrastructure",
        "labor",
        "supply chain",
        "technology",
        "capacity",
        "pricing",
        "subsidy",
        "imports",
        "exports",
        "energy",
    ),
    "trends": (
        "adoption",
        "pricing",
        "customer behavior",
        "product mix",
        "channel",
        "capacity",
        "competition",
        "innovation",
        "usage",
        "demand",
        "margin",
        "digital",
        "premiumization",
        "localization",
        "expansion",
    ),
}
SECTION_QUERY_SUFFIXES = (
    "statistics",
    "report",
    "data",
    "forecast",
)


def _log(message: str) -> None:
    logger.info(message)
    if DEBUG:
        print(message)


def _extract_parsed_output(response: Any) -> GeneratedSearchQueries:
    for output in getattr(response, "output", []):
        if getattr(output, "type", "") != "message":
            continue

        for item in getattr(output, "content", []):
            if getattr(item, "type", "") == "refusal":
                raise RuntimeError(str(getattr(item, "refusal", "Query generation was refused.")))

            parsed = getattr(item, "parsed", None)
            if isinstance(parsed, GeneratedSearchQueries):
                return parsed

    raise ValueError("Structured query response did not contain parsed content.")


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", str(query or "").strip())


def _word_count(query: str) -> int:
    return len([part for part in re.split(r"\s+", query.strip()) if part])


def _topic_terms(topic: str) -> List[str]:
    return [part.lower() for part in re.findall(r"[a-z0-9]+", topic.lower()) if len(part) >= 3]


def _deduplicate_queries(queries: List[str]) -> List[str]:
    unique_queries: List[str] = []
    seen_queries = set()

    for query in queries:
        normalized = _normalize_query(query)
        normalized_key = normalized.lower()
        if not normalized or normalized_key in seen_queries:
            continue
        seen_queries.add(normalized_key)
        unique_queries.append(normalized)

    return unique_queries


def _contains_location(query: str, context: LocationContext) -> bool:
    if context.is_global:
        return True

    lowered = query.lower()
    location_terms = [context.value.lower()]
    location_terms.extend(keyword.lower() for keyword in context.primary_keywords[:4])
    return any(term and term in lowered for term in location_terms)


def _contains_topic_signal(query: str, topic: str) -> bool:
    lowered_query = query.lower()
    terms = _topic_terms(topic)
    if not terms:
        return True
    required_matches = 2 if len(terms) >= 3 else 1
    matches = sum(1 for term in terms if term in lowered_query)
    return matches >= required_matches


def _validate_query(
    query: str,
    context: LocationContext,
    *,
    topic: str,
) -> str:
    normalized = _normalize_query(query)
    if not normalized:
        raise ValueError("Encountered an empty query.")
    if _word_count(normalized) > 15:
        raise ValueError(f"Query exceeds 15 words: {normalized}")
    if any(phrase in normalized.lower() for phrase in BANNED_QUERY_PHRASES):
        raise ValueError(f"Query contains a banned phrase: {normalized}")
    if not any(term in normalized.lower() for term in DATA_TERMS):
        raise ValueError(f"Query missing a required data term: {normalized}")
    if not _contains_topic_signal(normalized, topic):
        raise ValueError(f"Query is missing topic signal: {normalized}")
    if not _contains_location(normalized, context):
        raise ValueError(f"Query is missing the required geography: {normalized}")
    return normalized


def _build_query_focus_terms(section: str) -> List[str]:
    normalized_section = str(section or "").strip().lower() or "trends"
    return list(SECTION_QUERY_FOCUSES.get(normalized_section, SECTION_QUERY_FOCUSES["trends"]))


def _trim_query_to_limit(parts: List[str], limit: int = 15) -> str:
    return " ".join([part for part in parts if part][:limit]).strip()


def _compact_topic_for_query(topic: str, remaining_words: int) -> str:
    words = [part for part in topic.split() if part]
    if not words:
        return topic
    if remaining_words <= 0:
        return " ".join(words[:2])
    minimum_topic_words = 2 if len(words) >= 3 else 1
    target_words = max(minimum_topic_words, min(len(words), remaining_words))
    return " ".join(words[:target_words])


def build_fallback_queries(
    topic: str,
    section: str,
    location_context: LocationContext | None = None,
) -> List[str]:
    resolved_location_context = location_context or LocationContext()
    normalized_topic = _normalize_query(topic)
    normalized_section = str(section or "").strip().lower() or "trends"
    geo = resolved_location_context.value if not resolved_location_context.is_global else ""
    focus_terms = _build_query_focus_terms(normalized_section)

    fallback_queries: List[str] = []
    for index, focus_term in enumerate(focus_terms):
        suffix = SECTION_QUERY_SUFFIXES[index % len(SECTION_QUERY_SUFFIXES)]
        fixed_parts = [part for part in [geo, focus_term, suffix] if part]
        fixed_word_count = sum(_word_count(part) for part in fixed_parts)
        compact_topic = _compact_topic_for_query(normalized_topic, 15 - fixed_word_count)
        query_parts = [compact_topic, *fixed_parts]
        normalized_query = _normalize_query(_trim_query_to_limit(query_parts))
        try:
            fallback_queries.append(
                _validate_query(
                    normalized_query,
                    resolved_location_context,
                    topic=normalized_topic,
                )
            )
        except ValueError:
            continue

    return _deduplicate_queries(fallback_queries)[:MAX_QUERY_COUNT]


def _build_query_system_prompt(section: str) -> str:
    normalized_section = str(section or "").strip().lower()
    return get_search_query_prompt_template(normalized_section)


def _build_query_user_prompt(
    topic: str,
    section: str,
    location_context: LocationContext,
) -> str:
    section_focus = {
        "trends": "what is changing in the market",
        "drivers": "why the market is changing",
    }.get(section, "what is changing in the market")
    focus_terms = ", ".join(_build_query_focus_terms(section)[:8])
    location_mode = "Global"
    location_value = "Global"
    if location_context.preference == "region_specific":
        location_mode = "Region"
        location_value = location_context.value
    elif location_context.preference == "country_specific":
        location_mode = "Country"
        location_value = location_context.value

    return (
        "Input:\n"
        f"- Topic: {topic}\n"
        f"- Section: {section.title()}\n"
        f"- Location: {location_mode} / {location_value}\n"
        "\n"
        "Task:\n"
        f"- Generate exactly 15 search queries that reveal {section_focus}.\n"
        f"- Cover a diverse set of angles such as {focus_terms}.\n\n"
        "Runtime rules:\n"
        "- If Country is selected, every query must explicitly include the country name.\n"
        "- If Region is selected, every query must explicitly include the region keyword.\n"
        '- Every query must include at least one of: "statistics", "report", "forecast", or "data".\n'
        '- Every query must explicitly contain the topic or its obvious key terms.\n'
        '- Prefer geography-aware and data-focused wording.\n'
        '- Avoid vague phrases like "analysis of" and "overview of".\n'
        '- Avoid generic forecast headlines and vague academic wording.\n'
        '- Use varied phrasing across the 15 queries; do not repeat the same frame.\n'
        "- Keep each query to 15 words or fewer."
    ).strip()


def _validate_query_batch(
    queries: List[str],
    *,
    topic: str,
    location_context: LocationContext,
) -> List[str]:
    validated_queries = [
        _validate_query(
            query,
            location_context,
            topic=topic,
        )
        for query in _deduplicate_queries(queries)
    ]

    if len(validated_queries) != MAX_QUERY_COUNT:
        raise ValueError(f"Expected exactly {MAX_QUERY_COUNT} queries, got {len(validated_queries)}.")

    return validated_queries


async def generate_search_queries(
    topic: str,
    section: str,
    location_context: LocationContext | None = None,
) -> List[str]:
    resolved_location_context = location_context or LocationContext()
    normalized_topic = _normalize_query(topic)
    normalized_section = str(section or "").strip().lower()
    if not normalized_topic or not normalized_section:
        return []

    if not settings.OPENAI_API_KEY or not can_use_openai():
        _log("[QUERY] OpenAI unavailable. Using fallback queries.")
        return build_fallback_queries(
            normalized_topic,
            normalized_section,
            location_context=resolved_location_context,
        )

    system_prompt = _build_query_system_prompt(normalized_section)
    user_prompt = _build_query_user_prompt(
        normalized_topic,
        normalized_section,
        resolved_location_context,
    )
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    last_error: Optional[Exception] = None
    validation_error: Optional[str] = None

    try:
        for attempt in range(1, QUERY_MAX_RETRIES + 2):
            try:
                _log(f"[QUERY] Start | topic={normalized_topic} | section={normalized_section} | attempt={attempt}")
                input_payload: List[Dict[str, str]] = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
                if validation_error:
                    input_payload.append(
                        {
                            "role": "user",
                            "content": (
                                "The previous response failed validation. Fix these issues and regenerate only valid JSON.\n"
                                f"Validation errors: {validation_error}"
                            ),
                        }
                    )

                response = await asyncio.wait_for(
                    client.responses.parse(
                        model=QUERY_MODEL_NAME,
                        input=input_payload,
                        text_format=GeneratedSearchQueries,
                        temperature=0.2,
                        max_output_tokens=ensure_min_output_tokens(500),
                    ),
                    timeout=QUERY_TIMEOUT_SECONDS,
                )
                parsed = _extract_parsed_output(response)
                final_queries = _validate_query_batch(
                    list(parsed.queries),
                    topic=normalized_topic,
                    location_context=resolved_location_context,
                )

                _log(f"[QUERY] Generated queries | count={len(final_queries)}")
                for query in final_queries:
                    _log(f"[QUERY] {query}")
                return final_queries
            except Exception as exc:
                last_error = exc
                validation_error = str(exc)
                logger.warning(
                    "Query generation attempt %s failed for topic %s and section %s: %s",
                    attempt,
                    normalized_topic,
                    normalized_section,
                    exc,
                )
                if DEBUG:
                    print(f"[QUERY] Failed | attempt={attempt} | error={exc}")
                if attempt <= QUERY_MAX_RETRIES:
                    await asyncio.sleep(min(2 ** (attempt - 1), 4))
    finally:
        await client.close()

    if last_error is not None:
        logger.warning(
            "Query generation exhausted retries for topic %s and section %s: %s",
            normalized_topic,
            normalized_section,
            last_error,
        )
        if DEBUG:
            print(f"[QUERY] Exhausted retries | error={last_error}")

    return build_fallback_queries(
        normalized_topic,
        normalized_section,
        location_context=resolved_location_context,
    )

