import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from config.settings import settings
from models.response_models import GeneratedSearchQueries
from services.external_client import call_openai
from services.location_service import LocationContext
from services.openai_service import can_use_openai, ensure_min_output_tokens
from services.prompt_file_service import get_search_query_prompt_template

logger = logging.getLogger(__name__)

DEBUG = True
QUERY_MODEL_NAME = settings.OPENAI_QUERY_MODEL or settings.OPENAI_SUPPORT_MODEL or "gpt-4.1-mini"
QUERY_TIMEOUT_SECONDS = 25
QUERY_MAX_RETRIES = 1
MIN_QUERY_COUNT = 10
MAX_QUERY_COUNT = 10
BASE_DATA_TERMS = ("statistics", "report", "forecast", "data")
COMPETITIVE_LANDSCAPE_TERMS = (
    "market share",
    "key players",
    "leading companies",
    "competitors",
    "company profiles",
    "ranking",
    "major players",
    "emerging players",
    "local companies",
    "regional companies",
    "independent developers",
    "niche specialists",
    "challenger companies",
    "fast-growing companies",
    "solar developers",
    "renewable project developers",
    "epc companies",
)
CURRENT_QUERY_YEAR = datetime.utcnow().year
RECENT_QUERY_YEARS = tuple(str(CURRENT_QUERY_YEAR - offset) for offset in range(0, 2))
QUERY_ANGLE_QUALIFIERS = (
    "latest",
    *RECENT_QUERY_YEARS,
    "recent",
    "market size",
    "investment",
    "pricing",
    "capacity",
    "demand",
    "policy",
    "regulation",
    "adoption",
    "supply chain",
    "competitive landscape",
    "technology",
    "consumer behavior",
)
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
    "competitive_landscape": (
        "key players",
        "market share",
        "leading companies",
        "competitors",
        "company profiles",
        "ranking",
        "regional players",
        "challenger brands",
        "ecosystem",
        "niche companies",
        "major players",
        "top companies",
        "emerging players",
        "local companies",
        "regional companies",
        "independent developers",
        "niche specialists",
        "challenger companies",
        "fast-growing companies",
        "solar developers",
        "renewable project developers",
        "epc companies",
    ),
}
SECTION_QUERY_SUFFIXES = (
    "statistics",
    "report",
    "data",
    "forecast",
)


def _log(message: str) -> None:
    logger.info("%s", message)


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


def _required_query_terms(section: str) -> tuple[str, ...]:
    return COMPETITIVE_LANDSCAPE_TERMS if section == "competitive_landscape" else BASE_DATA_TERMS


def _validate_query(
    query: str,
    context: LocationContext,
    *,
    topic: str,
    section: str,
) -> str:
    normalized = _normalize_query(query)
    if not normalized:
        raise ValueError("Encountered an empty query.")
    max_words = 16 if section == "competitive_landscape" else 15
    if _word_count(normalized) > max_words:
        raise ValueError(f"Query exceeds {max_words} words: {normalized}")
    if any(phrase in normalized.lower() for phrase in BANNED_QUERY_PHRASES):
        raise ValueError(f"Query contains a banned phrase: {normalized}")
    if not any(term in normalized.lower() for term in _required_query_terms(section)):
        raise ValueError(f"Query missing a required section term: {normalized}")
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


def _ensure_required_terms_for_section(query: str, *, topic: str, context: LocationContext, section: str) -> str:
    normalized = _normalize_query(query)
    lowered = normalized.lower()
    rebuilt_parts: List[str] = []

    if not _contains_topic_signal(normalized, topic):
        rebuilt_parts.append(topic)

    if not _contains_location(normalized, context) and not context.is_global:
        rebuilt_parts.append(context.value)

    rebuilt_parts.append(normalized)
    candidate = _normalize_query(" ".join(part for part in rebuilt_parts if part))

    if not any(term in lowered for term in _required_query_terms(section)):
        fallback_term = "market share" if section == "competitive_landscape" else "statistics"
        candidate = _normalize_query(f"{candidate} {fallback_term}")

    max_words = 16 if section == "competitive_landscape" else 15
    return _trim_query_to_limit(candidate.split(), limit=max_words)


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
    max_words = 16 if normalized_section == "competitive_landscape" else 15

    if normalized_section == "competitive_landscape":
        geography = geo or "global"
        candidate_queries = [
            f"{normalized_topic} {geography} key players leading companies",
            f"{normalized_topic} {geography} emerging players local companies",
            f"{normalized_topic} {geography} regional companies challenger companies",
            f"{normalized_topic} {geography} independent developers niche specialists",
            f"{normalized_topic} {geography} fast-growing companies solar developers",
            f"{normalized_topic} {geography} renewable project developers epc companies",
            f"{normalized_topic} {geography} utility solar developers pipeline",
            f"{normalized_topic} {geography} epc companies solar developers",
            f"{normalized_topic} {geography} renewable project developers local companies",
            f"{normalized_topic} {geography} utility scale solar competitors ecosystem",
        ]
        validated_queries: List[str] = []
        for query in candidate_queries:
            try:
                validated_queries.append(
                    _validate_query(
                        _trim_query_to_limit(query.split(), limit=max_words),
                        resolved_location_context,
                        topic=normalized_topic,
                        section=normalized_section,
                    )
                )
            except ValueError:
                continue
        return _deduplicate_queries(validated_queries)[:MAX_QUERY_COUNT]

    fallback_queries: List[str] = []
    seen_queries = set()
    for focus_term in focus_terms:
        for qualifier in QUERY_ANGLE_QUALIFIERS:
            for suffix in SECTION_QUERY_SUFFIXES:
                fixed_parts = [part for part in [geo, focus_term, qualifier, suffix] if part]
                fixed_word_count = sum(_word_count(part) for part in fixed_parts)
                compact_topic = _compact_topic_for_query(normalized_topic, max_words - fixed_word_count)
                query_parts = [compact_topic, *fixed_parts]
                normalized_query = _normalize_query(_trim_query_to_limit(query_parts, limit=max_words))
                normalized_key = normalized_query.lower()
                if not normalized_query or normalized_key in seen_queries:
                    continue
                try:
                    validated_query = _validate_query(
                        normalized_query,
                        resolved_location_context,
                        topic=normalized_topic,
                        section=normalized_section,
                    )
                except ValueError:
                    continue
                seen_queries.add(normalized_key)
                fallback_queries.append(validated_query)
                if len(fallback_queries) >= MAX_QUERY_COUNT:
                    return fallback_queries[:MAX_QUERY_COUNT]

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
        "competitive_landscape": "who the key players are and how they compare",
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
        f"- Generate exactly {MAX_QUERY_COUNT} search queries that reveal {section_focus}.\n"
        f"- Cover a diverse set of angles such as {focus_terms}.\n\n"
        "Runtime rules:\n"
        "- If Country is selected, every query must explicitly include the country name.\n"
        "- If Region is selected, every query must explicitly include the region keyword.\n"
        f'- Every query must include at least one section signal such as: {", ".join(_required_query_terms(section)[:6])}.\n'
        '- Every query must explicitly contain the topic or its obvious key terms.\n'
        f'- Prefer the latest available evidence and bias the query set toward {RECENT_QUERY_YEARS[0]} and {RECENT_QUERY_YEARS[-1]} when useful.\n'
        '- Prefer geography-aware and data-focused wording.\n'
        '- Avoid vague phrases like "analysis of" and "overview of".\n'
        '- Avoid generic forecast headlines and vague academic wording.\n'
        '- For Competitive Landscape, broaden candidate discovery before classification: include emerging players, local companies, regional companies, independent developers, niche specialists, challenger companies, fast-growing companies, solar developers, renewable project developers, and EPC companies.\n'
        '- For Competitive Landscape, do not rely only on market share reports, top company rankings, or leading company lists.\n'
        '- For Competitive Landscape, include several company-universe queries that surface broader candidate pools before leader-focused queries.\n'
        f'- Use varied phrasing across the {MAX_QUERY_COUNT} queries; do not repeat the same frame.\n'
        f'- Keep each query to {16 if section == "competitive_landscape" else 15} words or fewer.'
    ).strip()


def _validate_query_batch(
    queries: List[str],
    *,
    topic: str,
    location_context: LocationContext,
    section: str,
) -> List[str]:
    repaired_queries = [
        _ensure_required_terms_for_section(
            query,
            topic=topic,
            context=location_context,
            section=section,
        )
        for query in _deduplicate_queries(queries)
    ]
    validated_queries = [
        _validate_query(
            query,
            location_context,
            topic=topic,
            section=section,
        )
        for query in repaired_queries
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

                response = await call_openai(
                    "generate_search_queries",
                    lambda: client.responses.parse(
                        model=QUERY_MODEL_NAME,
                        input=input_payload,
                        text_format=GeneratedSearchQueries,
                        temperature=0.2,
                        max_output_tokens=ensure_min_output_tokens(500),
                    ),
                    fallback=None,
                    timeout=QUERY_TIMEOUT_SECONDS,
                    max_retries=QUERY_MAX_RETRIES,
                    context={"model": QUERY_MODEL_NAME, "topic": normalized_topic, "section": normalized_section},
                )
                if response is None:
                    raise RuntimeError("Query generation returned no response.")
                parsed = _extract_parsed_output(response)
                final_queries = _validate_query_batch(
                    list(parsed.queries),
                    topic=normalized_topic,
                    location_context=resolved_location_context,
                    section=normalized_section,
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
    return build_fallback_queries(
        normalized_topic,
        normalized_section,
        location_context=resolved_location_context,
    )

