import json
import logging
import re
from collections import Counter
from datetime import date
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Sequence

from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel, ConfigDict, Field, field_validator

from config.settings import settings
from models.response_models import (
    CompetitiveLandscapeCompanyDraft,
    CompetitiveLandscapeDiscoveryCompany,
    CompetitiveLandscapeDiscoveryOutput,
    CompetitiveLandscapeOutput,
    ExampleExtractionResponse,
    ExtractedExample,
    Insight,
    Output,
)
from services.example_validation_service import evidence_has_strong_example_signals, validate_examples
from services.competitive_landscape_runtime import run_with_cl_provider_limit
from services.external_client import call_openai, call_openai_sync, get_last_external_call_failure
from services.prompt_builder import get_example_extraction_prompt, get_section_title
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
EXTRACTION_MAX_OUTPUT_TOKENS = 1800
STRUCTURED_TEMPERATURE = 0.1
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
COMPANY_TITLE_REJECT_MARKERS = (
    "market",
    "markets",
    "executive summary",
    "forecast",
    "forecasts",
    "analysis",
    "industry",
    "chapter",
    "usd",
    "billion",
    "million",
)
CL_SUPPLIER_REJECT_TERMS = (
    "consultant",
    "consulting",
    "agency",
    "service provider",
    "services provider",
    "supplier",
    "vendor",
    "software",
    "saas",
    "cloud",
    "infrastructure",
    "adtech",
    "martech",
    "investor",
    "investment firm",
    "venture capital",
    "private equity",
)
CL_ADJACENT_REJECT_TERMS = (
    "advertising",
    "advertiser",
    "technology platform",
    "tech platform",
    "platform company",
    "social media",
    "search engine",
    "marketplace",
    "e-commerce",
    "retail",
    "retailer",
    "payments",
    "consultancy",
)
CL_GENERIC_OPERATOR_TERMS = (
    "operator",
    "producer",
    "production company",
    "developer",
    "manufacturer",
    "publisher",
    "provider",
)
CL_ENTERTAINMENT_OPERATOR_TERMS = (
    "broadcaster",
    "broadcasting",
    "ott",
    "streaming service",
    "streaming platform",
    "production studio",
    "film company",
    "movie studio",
    "television network",
    "tv network",
    "music company",
    "music label",
    "record label",
    "entertainment company",
    "content provider",
    "content studio",
    "media network",
    "media company",
    "film studio",
)
CL_RELEVANCE_MAX_OUTPUT_TOKENS = 2200
SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?])\s+")
TITLE_DESCRIPTION_PREFIX_WORDS = 5
CURRENT_YEAR = datetime.now().year
PRESCRIPTIVE_TREND_MARKERS = (
    "should invest",
    "should respond",
    "should adapt",
    "should focus",
    "should prioritize",
    "should accelerate",
    "must adapt",
    "must respond",
    "must invest",
    "need to respond",
    "need to adapt",
    "need to invest",
    "operators must",
    "operators should",
    "companies should",
    "companies must",
    "players should",
    "players must",
)
STALE_FORECAST_PATTERNS = (
    re.compile(r"\bproject(?:ed|ion)?\b[^.]*\bby\s+(20\d{2})\b", re.IGNORECASE),
    re.compile(r"\bexpect(?:ed|s)?\b[^.]*\bby\s+(20\d{2})\b", re.IGNORECASE),
    re.compile(r"\bforecast(?:ed)?\b[^.]*\bby\s+(20\d{2})\b", re.IGNORECASE),
)

_OPENAI_RUNTIME_STATE: Dict[str, Any] = {
    "key_loaded": False,
    "connection_tested": False,
    "connection_ok": False,
    "message": "OpenAI runtime not checked yet.",
}
_LAST_STRUCTURED_COMPLETION_DIAGNOSTICS: Dict[str, Dict[str, Any]] = {}


def ensure_min_output_tokens(user_value: Optional[Any], default_value: int = DEFAULT_MAX_OUTPUT_TOKENS) -> int:
    try:
        resolved_value = int(user_value) if user_value is not None else int(default_value)
    except (TypeError, ValueError):
        resolved_value = int(default_value)
    return max(resolved_value, MIN_OUTPUT_TOKENS)


def _safe_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _safe_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_jsonable(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _safe_jsonable(model_dump(mode="json"))
        except TypeError:
            try:
                return _safe_jsonable(model_dump())
            except Exception:
                pass
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return _safe_jsonable(dict(vars(value)))
        except Exception:
            pass
    return str(value)


def _response_usage_payload(response: Any) -> Dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    return _safe_jsonable(usage) or {}


def _response_output_text(response: Any) -> str:
    text_value = getattr(response, "output_text", None)
    if isinstance(text_value, str) and text_value.strip():
        return text_value
    output_chunks: List[str] = []
    for output in getattr(response, "output", []):
        for item in getattr(output, "content", []):
            text_piece = getattr(item, "text", None)
            if isinstance(text_piece, str) and text_piece.strip():
                output_chunks.append(text_piece)
                continue
            refusal_piece = getattr(item, "refusal", None)
            if isinstance(refusal_piece, str) and refusal_piece.strip():
                output_chunks.append(refusal_piece)
    return "\n".join(output_chunks).strip()


def _response_debug_payload(response: Any) -> Dict[str, Any]:
    return {
        "response_id": getattr(response, "id", ""),
        "status": getattr(response, "status", ""),
        "usage": _response_usage_payload(response),
        "output_text": _response_output_text(response),
        "raw_response": _safe_jsonable(response),
    }


def _record_structured_completion_diagnostics(operation: str, diagnostics: Dict[str, Any]) -> None:
    _LAST_STRUCTURED_COMPLETION_DIAGNOSTICS[operation] = dict(diagnostics)


def get_last_structured_completion_diagnostics(operation: str | None = None) -> Dict[str, Any]:
    if operation is None:
        return {
            key: dict(value)
            for key, value in _LAST_STRUCTURED_COMPLETION_DIAGNOSTICS.items()
        }
    return dict(_LAST_STRUCTURED_COMPLETION_DIAGNOSTICS.get(operation, {}))


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


def mark_openai_unavailable(message: str) -> None:
    normalized_message = str(message or "").strip() or "OpenAI runtime unavailable."
    _set_runtime_state(connection_tested=True, connection_ok=False, message=normalized_message)


def _log_openai_error(error: Exception, prefix: str = "OpenAI ERROR") -> None:
    error_message = str(error)
    logger.error("%s: %s", prefix, error_message)

    lowered_message = error_message.lower()
    if "insufficient_quota" in lowered_message:
        mark_openai_unavailable(error_message)
    elif "api key" in lowered_message or "authentication" in lowered_message:
        mark_openai_unavailable(error_message)


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
                temperature=STRUCTURED_TEMPERATURE,
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


def _extract_parsed_output(response: Any, expected_type: type[Any]) -> Any:
    for output in getattr(response, "output", []):
        if getattr(output, "type", "") != "message":
            continue
        for item in getattr(output, "content", []):
            if getattr(item, "type", "") == "refusal":
                raise RuntimeError(str(getattr(item, "refusal", "OpenAI refused the request.")))
            parsed = getattr(item, "parsed", None)
            if isinstance(parsed, expected_type):
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


def _contains_prescriptive_trend_language(description: str) -> bool:
    lowered_description = description.lower()
    return any(marker in lowered_description for marker in PRESCRIPTIVE_TREND_MARKERS)


def _contains_stale_forecast_language(description: str) -> bool:
    for pattern in STALE_FORECAST_PATTERNS:
        for match in pattern.finditer(description):
            try:
                target_year = int(match.group(1))
            except (TypeError, ValueError, IndexError):
                continue
            if target_year <= CURRENT_YEAR:
                return True
    return False


def _looks_like_invalid_company_title(title: str) -> bool:
    lowered_title = title.lower().strip()
    if any(marker in lowered_title for marker in COMPANY_TITLE_REJECT_MARKERS):
        return True
    return bool(re.search(r"\b20\d{2}\b", lowered_title))


def _normalize_market_role(value: str) -> str:
    return _normalize_text(value)


def _collect_competitive_landscape_source_text(
    company: CompetitiveLandscapeDiscoveryCompany,
    evidence_by_source_id: Dict[int, Dict[str, Any]],
) -> str:
    parts: List[str] = []
    for source_id in list(company.source_ids or []):
        try:
            numeric_source_id = int(source_id)
        except (TypeError, ValueError):
            continue
        evidence = evidence_by_source_id.get(numeric_source_id) or {}
        parts.extend(
            [
                str(evidence.get("title", "")).strip(),
                str(evidence.get("content", "")).strip(),
                str(evidence.get("source", "")).strip(),
                str(evidence.get("url", "")).strip(),
            ]
        )
    return " ".join(part for part in parts if part).lower()


def _topic_operator_terms(topic: str) -> tuple[str, ...]:
    normalized_topic = _normalize_text(topic).lower()
    if any(term in normalized_topic for term in ("entertainment", "media", "film", "music", "broadcast", "television", "ott")):
        return CL_ENTERTAINMENT_OPERATOR_TERMS
    return CL_GENERIC_OPERATOR_TERMS


def _extract_topic_from_metadata(metadata: str) -> str:
    match = re.search(r"^- Topic:\s*(.+)$", str(metadata or ""), flags=re.MULTILINE)
    if match:
        return _normalize_text(match.group(1))
    return _normalize_text(metadata)


class CompetitiveLandscapeRelevanceDecision(BaseModel):
    company_name: str
    classification: str
    primary_business_fit: bool
    industry_centrality: bool
    operator_vs_supplier: bool
    reason: str = ""

    model_config = ConfigDict(extra="forbid")

    @field_validator("company_name", "classification", "reason")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _normalize_text(value)


class CompetitiveLandscapeRelevanceResponse(BaseModel):
    decisions: List[CompetitiveLandscapeRelevanceDecision] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


def _company_name_signals(company_name: str) -> Counter[str]:
    lowered_name = _normalize_text(company_name).lower()
    signals: Counter[str] = Counter()
    if any(term in lowered_name for term in CL_SUPPLIER_REJECT_TERMS):
        signals["supplier"] += 1
    if any(term in lowered_name for term in CL_ADJACENT_REJECT_TERMS):
        signals["adjacent"] += 1
    return signals


def _build_competitive_landscape_relevance_prompt(
    *,
    topic: str,
    companies: Sequence[CompetitiveLandscapeDiscoveryCompany],
    evidence_by_source_id: Dict[int, Dict[str, Any]],
) -> str:
    company_blocks: List[str] = []
    for company in companies:
        evidence_lines: List[str] = []
        for source_id in list(company.source_ids or []):
            try:
                numeric_source_id = int(source_id)
            except (TypeError, ValueError):
                continue
            evidence = evidence_by_source_id.get(numeric_source_id) or {}
            title = _normalize_text(str(evidence.get("title", "")))
            excerpt = _normalize_text(str(evidence.get("content", "") or evidence.get("excerpt", "")))
            domain = _normalize_text(str(evidence.get("domain", "") or evidence.get("source", "")))
            date_value = _normalize_text(str(evidence.get("date", "")))
            url = _normalize_text(str(evidence.get("url", "")))
            trimmed_excerpt = excerpt[:700]
            evidence_lines.append(
                f"- Source {numeric_source_id} | title={title} | domain={domain} | date={date_value} | "
                f"url={url} | excerpt={trimmed_excerpt}"
            )
        company_blocks.append(
            "\n".join(
                [
                    f"Company: {company.company_name}",
                    f"Discovery market_role: {company.market_role}",
                    f"Cited source_ids: {list(company.source_ids or [])}",
                    "Evidence:",
                    *(evidence_lines or ["- No cited evidence supplied."]),
                ]
            )
        )

    return (
        "You are validating company relevance for a Competitive Landscape workflow.\n\n"
        "Task:\n"
        "- Use only the cited evidence for each company.\n"
        "- Classify each company as exactly one of:\n"
        "  Direct Market Participant\n"
        "  Strategically Significant Participant\n"
        "  Adjacent Participant\n"
        "  Unrelated\n\n"
        "Definitions:\n"
        "- Direct Market Participant: the company directly operates, develops, owns, produces, installs, finances, distributes, or sells core offerings in the target market.\n"
        "- Strategically Significant Participant: the company is not the clearest pure-play operator but the evidence shows it materially shapes the target market through major ownership, project development, long-term deployment, financing tied directly to the market, or meaningful commercial scale in the geography.\n"
        "- Adjacent Participant: the company supports the market as a supplier, consultant, platform, equipment vendor, software provider, advertiser, general service provider, or similar ecosystem participant without being a core market participant.\n"
        "- Unrelated: the evidence does not support meaningful participation in the target market and geography.\n\n"
        "Scoring rules:\n"
        "- primary_business_fit=true only when the evidence supports that the company's business is directly in the target market or materially centered on it in the geography.\n"
        "- industry_centrality=true only when the evidence shows the company matters to the target market itself, not merely to adjacent infrastructure.\n"
        "- operator_vs_supplier=true only when the company is acting as a core participant rather than mainly as a supplier or adjacent service provider.\n"
        "- Keep Direct Market Participant and Strategically Significant Participant.\n"
        "- Reject Adjacent Participant and Unrelated.\n"
        "- Do not rely on keyword matching alone. Infer from the meaning of the evidence.\n"
        "- If evidence is mixed, prefer the best-supported classification and explain briefly in reason.\n\n"
        f"Topic: {topic}\n\n"
        "Return strict JSON in this shape:\n"
        "{\n"
        '  "decisions": [\n'
        "    {\n"
        '      "company_name": "Company name",\n'
        '      "classification": "Direct Market Participant",\n'
        '      "primary_business_fit": true,\n'
        '      "industry_centrality": true,\n'
        '      "operator_vs_supplier": true,\n'
        '      "reason": "short evidence-based explanation"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Companies to classify:\n\n"
        + "\n\n".join(company_blocks)
    )


async def _classify_competitive_landscape_relevance(
    client: AsyncOpenAI,
    *,
    topic: str,
    companies: Sequence[CompetitiveLandscapeDiscoveryCompany],
    evidence_by_source_id: Dict[int, Dict[str, Any]],
) -> Dict[str, CompetitiveLandscapeRelevanceDecision]:
    if not companies:
        return {}

    prompt = _build_competitive_landscape_relevance_prompt(
        topic=topic,
        companies=companies,
        evidence_by_source_id=evidence_by_source_id,
    )
    parsed = await run_with_cl_provider_limit(
        "openai",
        "structured_cl_relevance_classification",
        lambda: _request_structured_completion(
            client,
            operation="structured_cl_relevance_classification",
            input_payload=[{"role": "user", "content": prompt}],
            response_model=CompetitiveLandscapeRelevanceResponse,
            max_output_tokens=CL_RELEVANCE_MAX_OUTPUT_TOKENS,
        ),
    )

    decisions_by_name: Dict[str, CompetitiveLandscapeRelevanceDecision] = {}
    for decision in list(parsed.decisions or []):
        company_name = _normalize_text(decision.company_name)
        if not company_name:
            continue
        normalized_decision = CompetitiveLandscapeRelevanceDecision(
            company_name=company_name,
            classification=_normalize_text(decision.classification),
            primary_business_fit=bool(decision.primary_business_fit),
            industry_centrality=bool(decision.industry_centrality),
            operator_vs_supplier=bool(decision.operator_vs_supplier),
            reason=_normalize_text(decision.reason),
        )
        decisions_by_name[company_name.lower()] = normalized_decision
    return decisions_by_name


def _positive_term_match_count(text: str, terms: Sequence[str]) -> int:
    match_count = 0
    lowered_text = str(text or "").lower()
    for term in terms:
        escaped_term = re.escape(term)
        for match in re.finditer(escaped_term, lowered_text):
            prefix = lowered_text[max(0, match.start() - 120):match.start()]
            if any(
                marker in prefix
                for marker in (
                    "no ",
                    "not ",
                    "without ",
                    "without evidence",
                    "lack of ",
                    "lacks ",
                    "lacking ",
                    "unable to ",
                    "no evidence",
                )
            ):
                continue
            match_count += 1
    return match_count


def _evaluate_competitive_landscape_relevance_v2(
    *,
    company: CompetitiveLandscapeDiscoveryCompany,
    relevance_decision: CompetitiveLandscapeRelevanceDecision | None,
) -> Dict[str, Any]:
    if relevance_decision is None:
        return {
            "classification": "Unrelated",
            "primary_business_fit": False,
            "industry_centrality": False,
            "operator_vs_supplier": False,
            "rejection_reason": "rejected_primary_business_mismatch",
            "reason": "No relevance classification was produced for this company.",
        }

    classification = _normalize_text(relevance_decision.classification)
    primary_business_fit = bool(relevance_decision.primary_business_fit)
    industry_centrality = bool(relevance_decision.industry_centrality)
    operator_vs_supplier = bool(relevance_decision.operator_vs_supplier)
    reason = _normalize_text(relevance_decision.reason)
    rejection_reason = ""
    keep_classifications = {"Direct Market Participant", "Strategically Significant Participant"}
    if classification in keep_classifications:
        rejection_reason = ""
    elif classification == "Adjacent Participant":
        if not operator_vs_supplier:
            rejection_reason = "rejected_supplier"
        else:
            rejection_reason = "rejected_adjacent_participant"
    elif classification == "Unrelated":
        rejection_reason = "rejected_primary_business_mismatch"
    elif classification:
        rejection_reason = "rejected_supplier"
    elif not primary_business_fit or not industry_centrality:
        rejection_reason = "rejected_primary_business_mismatch"

    return {
        "classification": classification,
        "primary_business_fit": primary_business_fit,
        "industry_centrality": industry_centrality,
        "operator_vs_supplier": operator_vs_supplier,
        "rejection_reason": rejection_reason,
        "reason": reason,
    }


def _evaluate_competitive_landscape_relevance_legacy(
    *,
    company: CompetitiveLandscapeDiscoveryCompany,
    topic: str,
    evidence_by_source_id: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    evidence_text = _collect_competitive_landscape_source_text(company, evidence_by_source_id)
    operator_terms = _topic_operator_terms(topic)
    supplier_hits = _positive_term_match_count(evidence_text, CL_SUPPLIER_REJECT_TERMS)
    adjacent_hits = _positive_term_match_count(evidence_text, CL_ADJACENT_REJECT_TERMS)
    operator_hits = _positive_term_match_count(evidence_text, operator_terms)
    generic_operator_hits = _positive_term_match_count(evidence_text, CL_GENERIC_OPERATOR_TERMS)
    name_signals = _company_name_signals(company.company_name)
    supplier_hits += name_signals["supplier"]
    adjacent_hits += name_signals["adjacent"]
    operator_strength = operator_hits + generic_operator_hits
    primary_business_fit = operator_strength > 0 and operator_strength >= max(supplier_hits, adjacent_hits)
    industry_centrality = operator_hits > 0 or (
        operator_strength > 0
        and any(term in _normalize_text(topic).lower() for term in ("entertainment", "media", "film", "music", "broadcast", "television", "ott"))
    )
    operator_vs_supplier = supplier_hits == 0 and adjacent_hits == 0

    rejection_reason = ""
    if supplier_hits > 0 and operator_strength == 0:
        rejection_reason = "rejected_supplier"
    elif adjacent_hits > 0 and operator_strength == 0:
        rejection_reason = "rejected_adjacent_participant"
    elif not primary_business_fit or not industry_centrality or not operator_vs_supplier:
        rejection_reason = "rejected_primary_business_mismatch"

    return {
        "classification": "Legacy Keyword Validation",
        "primary_business_fit": primary_business_fit,
        "industry_centrality": industry_centrality,
        "operator_vs_supplier": operator_vs_supplier,
        "rejection_reason": rejection_reason,
        "reason": (
            f"legacy operator_hits={operator_hits} generic_operator_hits={generic_operator_hits} "
            f"supplier_hits={supplier_hits} adjacent_hits={adjacent_hits}"
        ),
    }


def _validate_structured_output(parsed: Output, section: str) -> Output:
    filtered_items: List[Insight] = []
    normalized_section = str(section or "").strip().lower()

    for item in parsed.items:
        title = _normalize_text(item.title)
        description = _normalize_text(item.description)
        competitive_positioning = _normalize_text(getattr(item, "competitive_positioning", ""))
        key_company_facts = [
            _normalize_text(fact)
            for fact in list(getattr(item, "key_company_facts", []) or [])
            if _normalize_text(fact)
        ]
        if not title or not description:
            continue
        if _looks_like_raw_source_text(title, description):
            continue
        if _title_repeats_description(title, description):
            continue
        if _is_generic_insight(title, description):
            continue
        title_word_count = len(title.split())
        if normalized_section == "competitive_landscape":
            if title_word_count < 1 or title_word_count > 8:
                continue
            if _looks_like_invalid_company_title(title):
                continue
        elif title_word_count < 3 or title_word_count > 14:
            continue
        if len(description) < 90:
            continue
        sentence_count = _count_sentences(description)
        if normalized_section == "competitive_landscape":
            if sentence_count < 2 or sentence_count > 4:
                continue
        elif sentence_count < 3 or sentence_count > 6:
            continue
        if normalized_section == "trends" and _contains_prescriptive_trend_language(description):
            continue
        if _contains_stale_forecast_language(description):
            continue
        if normalized_section == "competitive_landscape" and not str(item.segment or "").strip():
            continue
        if normalized_section == "competitive_landscape":
            if len(key_company_facts) < 3:
                continue
            if not competitive_positioning:
                continue

        if any(
            _titles_are_similar(title, existing.title) or _descriptions_are_similar(description, existing.description)
            for existing in filtered_items
        ):
            continue

        filtered_items.append(
            Insight(
                title=title,
                description=description,
                segment=str(item.segment or "").strip().lower(),
                key_company_facts=key_company_facts[:5],
                competitive_positioning=competitive_positioning,
                examples=[],
                source_ids=list(item.source_ids),
            )
        )

    if not filtered_items:
        raise ValueError("Structured output did not contain any usable insights.")

    return Output(items=filtered_items)


def _validate_competitive_landscape_discovery_output_legacy(
    parsed: CompetitiveLandscapeDiscoveryOutput,
    *,
    topic: str = "",
    evidence_blocks: Optional[Sequence[Dict[str, Any]]] = None,
) -> tuple[CompetitiveLandscapeDiscoveryOutput, Dict[str, Any]]:
    validated_groups: Dict[str, List[CompetitiveLandscapeCompanyDraft]] = {
        "major_players": [],
        "emerging_players": [],
    }
    seen_companies = set()
    removed_companies: List[tuple[str, str]] = []
    removal_reason_counts: Counter[str] = Counter()
    evidence_by_source_id: Dict[int, Dict[str, Any]] = {}
    for block in list(evidence_blocks or []):
        try:
            source_id = int(block.get("source_id"))
        except (TypeError, ValueError, AttributeError):
            continue
        evidence_by_source_id[source_id] = dict(block)

    for group_name in ("major_players", "emerging_players"):
        companies = getattr(parsed, group_name, []) or []
        for company in companies:
            company_name = _normalize_text(company.company_name)
            market_role = _normalize_market_role(company.market_role)
            if not company_name:
                removed_companies.append(("<missing-company>", "missing_company_name"))
                removal_reason_counts["missing_company_name"] += 1
                continue
            if _looks_like_invalid_company_title(company_name):
                removed_companies.append((company_name, "invalid_company_title"))
                removal_reason_counts["invalid_company_title"] += 1
                continue
            if len(company_name.split()) > 8:
                removed_companies.append((company_name, "title_too_long"))
                removal_reason_counts["title_too_long"] += 1
                continue
            if not market_role:
                removed_companies.append((company_name, "missing_market_role"))
                removal_reason_counts["missing_market_role"] += 1
                continue
            company_key = company_name.lower()
            if company_key in seen_companies:
                removed_companies.append((company_name, "duplicate_company"))
                removal_reason_counts["duplicate_company"] += 1
                continue
            relevance = _evaluate_competitive_landscape_relevance_legacy(
                company=CompetitiveLandscapeDiscoveryCompany(
                    company_name=company_name,
                    market_role=market_role,
                    source_ids=list(company.source_ids or []),
                ),
                topic=topic,
                evidence_by_source_id=evidence_by_source_id,
            )
            rejection_reason = str(relevance.get("rejection_reason", "")).strip()
            if rejection_reason:
                removed_companies.append((company_name, rejection_reason))
                removal_reason_counts[rejection_reason] += 1
                logger.info(
                    "Competitive landscape v1 company removed company=%s group=%s reason=%s primary_business_fit=%s industry_centrality=%s operator_vs_supplier=%s explanation=%s source_ids=%s",
                    company_name,
                    group_name,
                    rejection_reason,
                    relevance["primary_business_fit"],
                    relevance["industry_centrality"],
                    relevance["operator_vs_supplier"],
                    relevance.get("reason", ""),
                    list(company.source_ids or []),
                )
                continue
            seen_companies.add(company_key)
            validated_groups[group_name].append(
                CompetitiveLandscapeCompanyDraft(
                    company_name=company_name,
                    market_role=market_role,
                    business_overview=f"Profile pending evidence-driven research for {company_name}.",
                    key_company_facts=[],
                    competitive_positioning="",
                    source_ids=list(company.source_ids or []),
                )
            )

    if not validated_groups["major_players"] and not validated_groups["emerging_players"]:
        raise ValueError("Structured competitive landscape discovery did not contain any usable companies.")

    logger.info(
        "Competitive landscape v1 validation major_players=%s emerging_players=%s removed=%s reason_counts=%s",
        len(validated_groups["major_players"]),
        len(validated_groups["emerging_players"]),
        removed_companies,
        dict(removal_reason_counts),
    )

    return (
        CompetitiveLandscapeDiscoveryOutput(
            major_players=[
                CompetitiveLandscapeDiscoveryCompany(
                    company_name=company.company_name,
                    market_role=company.market_role,
                    source_ids=list(company.source_ids or []),
                )
                for company in validated_groups["major_players"]
            ],
            emerging_players=[
                CompetitiveLandscapeDiscoveryCompany(
                    company_name=company.company_name,
                    market_role=company.market_role,
                    source_ids=list(company.source_ids or []),
                )
                for company in validated_groups["emerging_players"]
            ],
        ),
        {
            "validation_mode": "v1",
            "discovery_count": sum(len(getattr(parsed, group_name, []) or []) for group_name in ("major_players", "emerging_players")),
            "validated_count": len(validated_groups["major_players"]) + len(validated_groups["emerging_players"]),
            "rejected_count": sum(int(count) for count in removal_reason_counts.values()),
            "rejected_primary_business_mismatch": int(removal_reason_counts.get("rejected_primary_business_mismatch", 0)),
            "rejected_supplier": int(removal_reason_counts.get("rejected_supplier", 0)),
            "rejected_adjacent_participant": int(removal_reason_counts.get("rejected_adjacent_participant", 0)),
            "removed_companies": [
                {"company_name": company_name, "reason": reason}
                for company_name, reason in removed_companies
            ],
        },
    )


async def _validate_competitive_landscape_discovery_output_v2(
    client: AsyncOpenAI,
    parsed: CompetitiveLandscapeDiscoveryOutput,
    *,
    topic: str = "",
    evidence_blocks: Optional[Sequence[Dict[str, Any]]] = None,
) -> tuple[CompetitiveLandscapeDiscoveryOutput, Dict[str, Any]]:
    validated_groups: Dict[str, List[CompetitiveLandscapeCompanyDraft]] = {
        "major_players": [],
        "emerging_players": [],
    }
    seen_companies = set()
    removed_companies: List[tuple[str, str]] = []
    removal_reason_counts: Counter[str] = Counter()
    evidence_by_source_id: Dict[int, Dict[str, Any]] = {}
    for block in list(evidence_blocks or []):
        try:
            source_id = int(block.get("source_id"))
        except (TypeError, ValueError, AttributeError):
            continue
        evidence_by_source_id[source_id] = dict(block)

    discovered_companies: List[CompetitiveLandscapeDiscoveryCompany] = []
    for group_name in ("major_players", "emerging_players"):
        discovered_companies.extend(list(getattr(parsed, group_name, []) or []))

    relevance_decisions = await _classify_competitive_landscape_relevance(
        client,
        topic=topic,
        companies=discovered_companies,
        evidence_by_source_id=evidence_by_source_id,
    )

    for group_name in ("major_players", "emerging_players"):
        companies = getattr(parsed, group_name, []) or []
        for company in companies:
            company_name = _normalize_text(company.company_name)
            market_role = _normalize_market_role(company.market_role)
            if not company_name:
                removed_companies.append(("<missing-company>", "missing_company_name"))
                removal_reason_counts["missing_company_name"] += 1
                continue
            if _looks_like_invalid_company_title(company_name):
                removed_companies.append((company_name, "invalid_company_title"))
                removal_reason_counts["invalid_company_title"] += 1
                continue
            if len(company_name.split()) > 8:
                removed_companies.append((company_name, "title_too_long"))
                removal_reason_counts["title_too_long"] += 1
                continue
            if not market_role:
                removed_companies.append((company_name, "missing_market_role"))
                removal_reason_counts["missing_market_role"] += 1
                continue
            company_key = company_name.lower()
            if company_key in seen_companies:
                removed_companies.append((company_name, "duplicate_company"))
                removal_reason_counts["duplicate_company"] += 1
                continue
            relevance = _evaluate_competitive_landscape_relevance_v2(
                company=CompetitiveLandscapeDiscoveryCompany(
                    company_name=company_name,
                    market_role=market_role,
                    source_ids=list(company.source_ids or []),
                ),
                relevance_decision=relevance_decisions.get(company_name.lower()),
            )
            rejection_reason = str(relevance.get("rejection_reason", "")).strip()
            if rejection_reason:
                removed_companies.append((company_name, rejection_reason))
                removal_reason_counts[rejection_reason] += 1
                logger.info(
                    "Competitive landscape company removed company=%s group=%s reason=%s classification=%s primary_business_fit=%s industry_centrality=%s operator_vs_supplier=%s explanation=%s source_ids=%s",
                    company_name,
                    group_name,
                    rejection_reason,
                    relevance.get("classification", ""),
                    relevance["primary_business_fit"],
                    relevance["industry_centrality"],
                    relevance["operator_vs_supplier"],
                    relevance.get("reason", ""),
                    list(company.source_ids or []),
                )
                continue
            seen_companies.add(company_key)
            validated_groups[group_name].append(
                CompetitiveLandscapeCompanyDraft(
                    company_name=company_name,
                    market_role=market_role,
                    business_overview=f"Profile pending evidence-driven research for {company_name}.",
                    key_company_facts=[],
                    competitive_positioning="",
                    source_ids=list(company.source_ids or []),
                )
            )

    if not validated_groups["major_players"] and not validated_groups["emerging_players"]:
        raise ValueError("Structured competitive landscape discovery did not contain any usable companies.")

    logger.info(
        "Competitive landscape discovery validation major_players=%s emerging_players=%s removed=%s reason_counts=%s",
        len(validated_groups["major_players"]),
        len(validated_groups["emerging_players"]),
        removed_companies,
        dict(removal_reason_counts),
    )

    return (
        CompetitiveLandscapeDiscoveryOutput(
            major_players=[
                CompetitiveLandscapeDiscoveryCompany(
                    company_name=company.company_name,
                    market_role=company.market_role,
                    source_ids=list(company.source_ids or []),
                )
                for company in validated_groups["major_players"]
            ],
            emerging_players=[
                CompetitiveLandscapeDiscoveryCompany(
                    company_name=company.company_name,
                    market_role=company.market_role,
                    source_ids=list(company.source_ids or []),
                )
                for company in validated_groups["emerging_players"]
            ],
        ),
        {
            "validation_mode": "v2",
            "discovery_count": len(discovered_companies),
            "validated_count": len(validated_groups["major_players"]) + len(validated_groups["emerging_players"]),
            "rejected_count": sum(int(count) for count in removal_reason_counts.values()),
            "rejected_primary_business_mismatch": int(removal_reason_counts.get("rejected_primary_business_mismatch", 0)),
            "rejected_supplier": int(removal_reason_counts.get("rejected_supplier", 0)),
            "rejected_adjacent_participant": int(removal_reason_counts.get("rejected_adjacent_participant", 0)),
            "classification_decisions": [
                {
                    "company_name": decision.company_name,
                    "classification": decision.classification,
                    "primary_business_fit": bool(decision.primary_business_fit),
                    "industry_centrality": bool(decision.industry_centrality),
                    "operator_vs_supplier": bool(decision.operator_vs_supplier),
                    "reason": _normalize_text(decision.reason),
                }
                for decision in relevance_decisions.values()
            ],
            "removed_companies": [
                {"company_name": company_name, "reason": reason}
                for company_name, reason in removed_companies
            ],
        },
    )


async def _validate_competitive_landscape_discovery_output(
    client: AsyncOpenAI,
    parsed: CompetitiveLandscapeDiscoveryOutput,
    *,
    topic: str = "",
    evidence_blocks: Optional[Sequence[Dict[str, Any]]] = None,
    mode: str = "v1",
) -> tuple[CompetitiveLandscapeDiscoveryOutput, Dict[str, Any]]:
    if mode == "v2":
        return await _validate_competitive_landscape_discovery_output_v2(
            client,
            parsed,
            topic=topic,
            evidence_blocks=evidence_blocks,
        )
    return _validate_competitive_landscape_discovery_output_legacy(
        parsed,
        topic=topic,
        evidence_blocks=evidence_blocks,
    )


async def _request_structured_completion(
    client: AsyncOpenAI,
    *,
    operation: str,
    input_payload: List[Dict[str, str]],
    response_model: type[Any],
    max_output_tokens: int,
) -> Any:
    response_schema = response_model.model_json_schema()
    resolved_max_output_tokens = ensure_min_output_tokens(max_output_tokens)
    diagnostics: Dict[str, Any] = {
        "operation": operation,
        "model_name": MODEL_NAME,
        "response_model": response_model.__name__,
        "response_schema": response_schema,
        "schema_size_chars": len(json.dumps(response_schema, ensure_ascii=False)),
        "max_output_tokens": resolved_max_output_tokens,
        "temperature": STRUCTURED_TEMPERATURE,
        "request_payload": {
            "model": MODEL_NAME,
            "input": input_payload,
            "max_output_tokens": resolved_max_output_tokens,
            "temperature": STRUCTURED_TEMPERATURE,
            "response_model": response_model.__name__,
            "response_schema": response_schema,
        },
        "system_prompt": "\n\n".join(
            str(message.get("content", "")).strip()
            for message in input_payload
            if str(message.get("role", "")).strip() == "system"
        ),
        "user_prompt": "\n\n".join(
            str(message.get("content", "")).strip()
            for message in input_payload
            if str(message.get("role", "")).strip() == "user"
        ),
        "input_chars": sum(len(str(message.get("content", ""))) for message in input_payload),
        "prompt_token_count": None,
        "completion_token_count": None,
        "total_token_count": None,
        "raw_model_response": None,
        "raw_model_output_text": "",
        "error_type": "",
        "error_message": "",
        "error_details": {},
        "status": "pending",
    }
    response = await call_openai(
        operation,
        lambda: client.responses.parse(
            model=MODEL_NAME,
            input=input_payload,
            text_format=response_model,
            max_output_tokens=resolved_max_output_tokens,
            temperature=STRUCTURED_TEMPERATURE,
        ),
        fallback=None,
        timeout=OPENAI_TIMEOUT_SECONDS,
        max_retries=OPENAI_MAX_RETRIES,
        context={"model": MODEL_NAME, "response_model": response_model.__name__},
    )
    if response is None:
        failure = get_last_external_call_failure("openai", operation)
        diagnostics["status"] = "request_failed"
        diagnostics["error_details"] = failure
        diagnostics["error_type"] = str(failure.get("error_type", "RuntimeError"))
        diagnostics["error_message"] = str(
            failure.get("error_message", "Structured completion returned no response.")
        )
        _record_structured_completion_diagnostics(operation, diagnostics)
        raise RuntimeError(
            "Structured completion failed "
            f"operation={operation} model={MODEL_NAME} response_model={response_model.__name__} "
            f"error_type={diagnostics['error_type']} error={diagnostics['error_message']}"
        )
    response_debug = _response_debug_payload(response)
    usage = dict(response_debug.get("usage", {}) or {})
    diagnostics["prompt_token_count"] = usage.get("input_tokens")
    diagnostics["completion_token_count"] = usage.get("output_tokens")
    diagnostics["total_token_count"] = usage.get("total_tokens")
    diagnostics["raw_model_response"] = response_debug.get("raw_response")
    diagnostics["raw_model_output_text"] = response_debug.get("output_text", "")
    diagnostics["status"] = str(response_debug.get("status") or "completed")
    _set_runtime_state(
        key_loaded=True,
        connection_tested=True,
        connection_ok=True,
        message="OpenAI connection healthy.",
    )
    try:
        parsed = _extract_parsed_output(response, response_model)
    except Exception as exc:
        diagnostics["status"] = "parse_failed"
        diagnostics["error_type"] = exc.__class__.__name__
        diagnostics["error_message"] = str(exc)
        _record_structured_completion_diagnostics(operation, diagnostics)
        raise RuntimeError(
            "Structured completion parse failed "
            f"operation={operation} model={MODEL_NAME} response_model={response_model.__name__} "
            f"error_type={exc.__class__.__name__} error={exc}"
        ) from exc
    _record_structured_completion_diagnostics(operation, diagnostics)
    return parsed


async def _extract_candidate_examples(
    client: AsyncOpenAI,
    *,
    metadata: str,
    section: str,
) -> List[ExtractedExample]:
    extraction_prompt = get_example_extraction_prompt(section)
    parsed = await _request_structured_completion(
        client,
        operation="structured_example_extraction",
        input_payload=[
            {"role": "system", "content": extraction_prompt},
            {"role": "user", "content": metadata},
        ],
        response_model=ExampleExtractionResponse,
        max_output_tokens=EXTRACTION_MAX_OUTPUT_TOKENS,
    )
    return list(parsed.examples or [])


async def extract_validated_examples_from_evidence(
    *,
    metadata: str,
    section: str,
    evidence_blocks: Sequence[Dict[str, Any]],
    log_context: str = "",
    research_date: date | None = None,
    trend_context: Dict[str, Any] | None = None,
    allow_low_confidence_fallback: bool = False,
    return_diagnostics: bool = False,
    max_age_months: int | None = None,
) -> List[ExtractedExample] | tuple[List[ExtractedExample], Dict[str, Any]]:
    api_key = settings.OPENAI_API_KEY.strip()
    if not api_key:
        logger.warning("Example extraction skipped because OPENAI_API_KEY is not configured.")
        return []
    if not can_use_openai():
        logger.warning("Example extraction skipped because OpenAI is not available: %s", get_openai_status_message())
        return []

    resolved_evidence_blocks = list(evidence_blocks or [])
    if not resolved_evidence_blocks:
        return []

    client = AsyncOpenAI(api_key=api_key)
    try:
        candidate_examples = await _extract_candidate_examples(
            client,
            metadata=metadata,
            section=section,
        )
        logger.info(
            "Extracted %s candidate examples context=%s section=%s",
            len(candidate_examples),
            log_context,
            section,
        )

        validated_examples, discard_reasons = validate_examples(
            candidate_examples,
            resolved_evidence_blocks,
            research_date=research_date,
            trend_context=trend_context,
            allow_low_confidence_fallback=allow_low_confidence_fallback,
            max_age_months=max_age_months,
        )
        if discard_reasons:
            logger.info(
                "Discarded %s extracted examples context=%s section=%s reasons=%s",
                len(discard_reasons),
                log_context,
                section,
                discard_reasons,
            )
        logger.info(
            "Validated %s extracted examples context=%s section=%s",
            len(validated_examples),
            log_context,
            section,
        )
        if not validated_examples and evidence_has_strong_example_signals(resolved_evidence_blocks):
            logger.warning(
                "Example extraction returned zero validated examples despite strong evidence signals context=%s section=%s",
                log_context,
                section,
            )
        diagnostics = {
            "candidate_count": len(candidate_examples),
            "validated_count": len(validated_examples),
            "rejection_reasons": discard_reasons,
        }
        if return_diagnostics:
            return validated_examples, diagnostics
        return validated_examples
    finally:
        await client.close()


async def generate_section_analysis(
    system_prompt: str,
    metadata: str,
    section: str,
    max_items: int = 10,
    evidence_blocks: Optional[Sequence[Dict[str, Any]]] = None,
    example_metadata: Optional[str] = None,
    competitive_landscape_mode: str = "v1",
    competitive_landscape_discovery_override: CompetitiveLandscapeDiscoveryOutput | None = None,
) -> Dict[str, Any]:
    del example_metadata

    api_key = settings.OPENAI_API_KEY.strip()
    if not api_key:
        error = ValueError("OPENAI_API_KEY is not configured")
        _log_openai_error(error)
        raise error

    if not can_use_openai():
        raise RuntimeError(get_openai_status_message())

    resolved_evidence_blocks = list(evidence_blocks or [])
    client = AsyncOpenAI(api_key=api_key)
    validation_error: Optional[str] = None

    try:
        if section == "competitive_landscape" and competitive_landscape_discovery_override is not None:
            validated, validation_diagnostics = await _validate_competitive_landscape_discovery_output(
                client,
                competitive_landscape_discovery_override,
                topic=_extract_topic_from_metadata(metadata),
                evidence_blocks=resolved_evidence_blocks,
                mode=competitive_landscape_mode,
            )

            def _rank_group(
                companies: Sequence[CompetitiveLandscapeDiscoveryCompany],
                *,
                segment_name: str,
            ) -> List[Dict[str, Any]]:
                ranked_companies = rank_and_limit_insights(
                    [
                        {
                            "heading": company.company_name,
                            "body": f"Evidence-driven profile pending research for {company.company_name}.",
                            "market_role": company.market_role,
                            "key_company_facts": [],
                            "competitive_positioning": "",
                            "examples": [],
                            "source_ids": list(company.source_ids or []),
                            "segment": segment_name,
                        }
                        for company in companies
                    ],
                    limit=max_items,
                )
                return attach_sources_to_items(ranked_companies, resolved_evidence_blocks, max_sources_per_item=6)

            return {
                "section": section,
                "title": get_section_title(section),
                "major_players": _rank_group(validated.major_players, segment_name="major_players"),
                "emerging_players": _rank_group(validated.emerging_players, segment_name="emerging_players"),
                "_competitive_landscape_validation": validation_diagnostics,
            }

        for attempt in range(1, OPENAI_MAX_RETRIES + 2):
            input_payload: List[Dict[str, str]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": metadata},
            ]
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

            response_model: type[Any] = CompetitiveLandscapeDiscoveryOutput if section == "competitive_landscape" else Output
            parsed = await _request_structured_completion(
                client,
                operation="structured_section_analysis",
                input_payload=input_payload,
                response_model=response_model,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            )

            try:
                if section == "competitive_landscape":
                    validated, validation_diagnostics = await _validate_competitive_landscape_discovery_output(
                        client,
                        parsed,
                        topic=_extract_topic_from_metadata(metadata),
                        evidence_blocks=resolved_evidence_blocks,
                        mode=competitive_landscape_mode,
                    )

                    def _rank_group(
                        companies: Sequence[CompetitiveLandscapeDiscoveryCompany],
                        *,
                        segment_name: str,
                    ) -> List[Dict[str, Any]]:
                        ranked_companies = rank_and_limit_insights(
                            [
                                {
                                    "heading": company.company_name,
                                    "body": f"Evidence-driven profile pending research for {company.company_name}.",
                                    "market_role": company.market_role,
                                    "key_company_facts": [],
                                    "competitive_positioning": "",
                                    "examples": [],
                                    "source_ids": list(company.source_ids or []),
                                    "segment": segment_name,
                                }
                                for company in companies
                            ],
                            limit=max_items,
                        )
                        return attach_sources_to_items(ranked_companies, resolved_evidence_blocks, max_sources_per_item=6)

                    return {
                        "section": section,
                        "title": get_section_title(section),
                        "major_players": _rank_group(validated.major_players, segment_name="major_players"),
                        "emerging_players": _rank_group(validated.emerging_players, segment_name="emerging_players"),
                        "_competitive_landscape_validation": validation_diagnostics,
                    }

                validated = _validate_structured_output(parsed, section)
                ranked_items = rank_and_limit_insights(
                    [
                        {
                            "heading": item.title,
                            "body": item.description,
                            "examples": [],
                            "source_ids": list(item.source_ids),
                        }
                        for item in validated.items
                    ],
                    limit=max_items,
                )
                return {
                    "section": section,
                    "title": get_section_title(section),
                    "items": attach_sources_to_items(ranked_items, resolved_evidence_blocks),
                }
            except ValueError as exc:
                validation_error = str(exc)
                if attempt > OPENAI_MAX_RETRIES:
                    raise

        raise RuntimeError("Structured analysis failed after the allowed retry.")
    finally:
        await client.close()
