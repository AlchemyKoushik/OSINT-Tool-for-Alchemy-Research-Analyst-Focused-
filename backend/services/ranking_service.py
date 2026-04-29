import asyncio
import json
import logging
import re
from collections import Counter
from typing import Any, Dict, List

from openai import AsyncOpenAI

from config.settings import settings
from services.external_client import call_openai

logger = logging.getLogger(__name__)

RANKING_MODEL_NAME = "gpt-4o-mini"
RANKING_TIMEOUT_SECONDS = 30
MAX_SELECTED_RESULTS = 8
SIGNAL_TERMS = {
    "accelerating",
    "adoption",
    "capacity",
    "consolidation",
    "demand",
    "expansion",
    "growth",
    "increase",
    "investment",
    "launch",
    "margin",
    "momentum",
    "partnership",
    "price",
    "pricing",
    "procurement",
    "regulation",
    "scale",
    "shift",
    "supply",
    "tariff",
}
STOPWORDS = {
    "about",
    "after",
    "also",
    "among",
    "and",
    "because",
    "been",
    "being",
    "between",
    "from",
    "have",
    "into",
    "more",
    "over",
    "than",
    "that",
    "their",
    "them",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "under",
    "using",
    "while",
    "with",
}


def _default_selected_ids(total_results: int) -> List[int]:
    return list(range(min(MAX_SELECTED_RESULTS, total_results)))


def _normalize_selected_ids(candidate_ids: Any, total_results: int) -> List[int]:
    if not isinstance(candidate_ids, list):
        return []

    normalized_ids: List[int] = []
    for candidate in candidate_ids:
        try:
            index = int(candidate)
        except (TypeError, ValueError):
            continue

        if 0 <= index < total_results and index not in normalized_ids:
            normalized_ids.append(index)

        if len(normalized_ids) >= MAX_SELECTED_RESULTS:
            break

    return normalized_ids


def _parse_selected_ids(content: str, total_results: int) -> List[int]:
    cleaned_content = content.strip()
    if not cleaned_content:
        return []

    if cleaned_content.startswith("```"):
        cleaned_content = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            cleaned_content,
            flags=re.IGNORECASE | re.DOTALL,
        ).strip()

    candidate_payloads = [cleaned_content]
    json_match = re.search(r"\{.*\}", cleaned_content, flags=re.DOTALL)
    if json_match and json_match.group(0) not in candidate_payloads:
        candidate_payloads.append(json_match.group(0))

    for candidate_payload in candidate_payloads:
        try:
            parsed = json.loads(candidate_payload)
        except json.JSONDecodeError:
            continue

        if isinstance(parsed, dict):
            selected_ids = _normalize_selected_ids(parsed.get("selected_ids"), total_results)
            if selected_ids:
                return selected_ids

            for value in parsed.values():
                selected_ids = _normalize_selected_ids(value, total_results)
                if selected_ids:
                    return selected_ids

        if isinstance(parsed, list):
            selected_ids = _normalize_selected_ids(parsed, total_results)
            if selected_ids:
                return selected_ids

    numeric_fallback = [int(match) for match in re.findall(r"\d+", cleaned_content)]
    return _normalize_selected_ids(numeric_fallback, total_results)


async def rank_and_filter_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not results:
        logger.info("Ranking skipped because there are no search results.")
        return []

    default_ids = _default_selected_ids(len(results))
    items_to_score = [
        {
            "id": index,
            "url": result.get("url"),
            "title": result.get("title", ""),
            "snippet": result.get("snippet", ""),
        }
        for index, result in enumerate(results)
    ]

    from services.openai_service import can_use_openai

    if not settings.OPENAI_API_KEY or not can_use_openai():
        logger.warning("OpenAI unavailable for ranking. Using ranking fallback.")
        return [results[index] for index in default_ids]

    prompt = (
        "Evaluate the following search results for relevance, credibility, and freshness.\n"
        "Select the best 5 to 8 links when possible.\n"
        "Return ONLY a JSON object in this format: "
        '{"selected_ids": [0, 1, 2]}\n\n'
        f"Search Results:\n{json.dumps(items_to_score, indent=2)}"
    )

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    try:
        logger.info("Ranking started for %s search results.", len(results))
        response = await call_openai(
            "rank_search_results",
            lambda: client.chat.completions.create(
                model=RANKING_MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            ),
            fallback=None,
            timeout=RANKING_TIMEOUT_SECONDS,
            context={"model": RANKING_MODEL_NAME, "result_count": len(results)},
        )
        if response is None:
            raise RuntimeError("Ranking returned no response.")

        content = response.choices[0].message.content or ""
        selected_ids = _parse_selected_ids(content, len(results))
        if not selected_ids:
            logger.warning("Ranking response could not be parsed. Using default ranking fallback.")
            selected_ids = default_ids

        logger.info("Ranking completed with %s selected results.", len(selected_ids))
        return [results[index] for index in selected_ids]
    except Exception as exc:
        logger.exception("Ranking failed. Using default ranking fallback. Error: %s", exc)
        return [results[index] for index in default_ids]
    finally:
        await client.close()


def _tokenize_insight_text(value: str) -> List[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9][a-z0-9&/%-]{1,}", str(value or "").lower())
        if token not in STOPWORDS and len(token) > 2
    ]


def _insight_text(insight: Dict[str, Any]) -> str:
    return f"{str(insight.get('heading', '')).strip()} {str(insight.get('body', '')).strip()}".strip()


def _score_insight(insight: Dict[str, Any], token_frequency: Counter[str], index: int) -> float:
    heading = str(insight.get("heading", "")).strip()
    body = str(insight.get("body", "")).strip()
    combined = f"{heading} {body}".strip()
    tokens = _tokenize_insight_text(combined)
    unique_tokens = set(tokens)

    frequency_score = sum(token_frequency.get(token, 0) for token in unique_tokens)
    signal_score = sum(2 for token in unique_tokens if token in SIGNAL_TERMS)
    numeric_score = len(re.findall(r"\b\d+(?:\.\d+)?%?\b", combined))
    heading_score = min(len(heading.split()), 8)
    body_score = min(len(body.split()) / 18, 8)
    punctuation_score = body.count(";") + body.count(":")
    recency_bias = max(0, 6 - index)

    return (
        frequency_score
        + signal_score
        + numeric_score * 1.5
        + heading_score * 0.8
        + body_score
        + punctuation_score * 0.5
        + recency_bias
    )


def rank_and_limit_insights(insights: List[dict], limit: int) -> List[dict]:
    normalized_limit = max(0, int(limit or 0))
    if normalized_limit <= 0 or not insights:
        return []

    sanitized_insights: List[Dict[str, Any]] = []
    seen_pairs = set()
    for insight in insights:
        if not isinstance(insight, dict):
            continue
        heading = str(insight.get("heading", "")).strip()
        body = str(insight.get("body", "")).strip()
        if not heading or not body:
            continue
        dedupe_key = (heading.lower(), body.lower())
        if dedupe_key in seen_pairs:
            continue
        seen_pairs.add(dedupe_key)
        normalized_item = dict(insight)
        normalized_item["heading"] = heading
        normalized_item["body"] = body
        sanitized_insights.append(normalized_item)

    if not sanitized_insights:
        return []

    token_frequency: Counter[str] = Counter()
    for insight in sanitized_insights:
        token_frequency.update(set(_tokenize_insight_text(_insight_text(insight))))

    ranked = sorted(
        enumerate(sanitized_insights),
        key=lambda item: _score_insight(item[1], token_frequency, item[0]),
        reverse=True,
    )

    return [dict(insight) for _, insight in ranked[:normalized_limit]]

