import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from config.settings import settings
from services.external_client import call_openai
from services.openai_service import can_use_openai

logger = logging.getLogger(__name__)

INSIGHT_MODEL_NAME = "gpt-4o-mini"
INSIGHT_TIMEOUT_SECONDS = 30
INSIGHT_MAX_RETRIES = 2

INSIGHT_RESPONSE_FORMAT: Dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "insight_analysis",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "conflicts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "issue": {"type": "string"},
                            "statement_a": {"type": "string"},
                            "statement_b": {"type": "string"},
                            "source_refs": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["issue", "statement_a", "statement_b", "source_refs"],
                        "additionalProperties": False,
                    },
                },
                "consensus_signals": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["conflicts", "consensus_signals"],
            "additionalProperties": False,
        },
    },
}


def _empty_analysis() -> Dict[str, List[Any]]:
    return {"conflicts": [], "consensus_signals": []}


async def analyze_insights(sources_text: str) -> Dict[str, List[Any]]:
    normalized_sources = sources_text.strip()
    if not normalized_sources:
        return _empty_analysis()

    api_key = settings.OPENAI_API_KEY
    if not api_key or not can_use_openai():
        logger.warning("OpenAI unavailable. Skipping insight analysis.")
        return _empty_analysis()

    prompt = (
        "Review the source extracts below and identify where the sources conflict or converge.\n"
        "Return only JSON.\n"
        "- conflicts: material contradictions or disagreements across sources.\n"
        "- consensus_signals: themes or facts that multiple sources reinforce.\n"
        "Use only the supplied source text.\n\n"
        f"Sources:\n{normalized_sources}"
    )

    client = AsyncOpenAI(api_key=api_key)
    last_error: Optional[Exception] = None

    try:
        for attempt in range(1, INSIGHT_MAX_RETRIES + 2):
            try:
                logger.info("Insight analysis attempt %s started.", attempt)
                response = await call_openai(
                    "insight_analysis",
                    lambda: client.chat.completions.create(
                        model=INSIGHT_MODEL_NAME,
                        messages=[
                            {
                                "role": "system",
                                "content": "You are an OSINT reasoning engine that detects contradictions and consensus from source extracts.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        response_format=INSIGHT_RESPONSE_FORMAT,
                    ),
                    fallback=None,
                    timeout=INSIGHT_TIMEOUT_SECONDS,
                    max_retries=INSIGHT_MAX_RETRIES,
                    context={"model": INSIGHT_MODEL_NAME},
                )
                if response is None:
                    raise RuntimeError("Insight analysis returned no response.")

                content = response.choices[0].message.content
                if not content:
                    raise ValueError("Insight analyzer returned empty content.")

                parsed = json.loads(content)
                conflicts = parsed.get("conflicts", [])
                consensus_signals = parsed.get("consensus_signals", [])

                if not isinstance(conflicts, list) or not isinstance(consensus_signals, list):
                    raise ValueError("Insight analyzer returned an invalid payload.")

                logger.info(
                    "Insight analysis attempt %s succeeded with %s conflicts and %s consensus signals.",
                    attempt,
                    len(conflicts),
                    len(consensus_signals),
                )
                return {
                    "conflicts": conflicts,
                    "consensus_signals": [str(signal) for signal in consensus_signals],
                }
            except (json.JSONDecodeError, ValueError, RuntimeError) as exc:
                last_error = exc
                logger.warning("Insight analysis attempt %s returned invalid JSON: %s", attempt, exc)
            except Exception as exc:
                last_error = exc
                logger.exception("Insight analysis attempt %s failed unexpectedly.", attempt)

            if attempt <= INSIGHT_MAX_RETRIES:
                await asyncio.sleep(min(attempt, 2))

        logger.warning("Insight analysis failed after %s attempts: %s", INSIGHT_MAX_RETRIES + 1, last_error)
        return _empty_analysis()
    finally:
        await client.close()

