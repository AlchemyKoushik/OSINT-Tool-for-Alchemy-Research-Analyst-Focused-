from typing import List, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from models.request_models import ResearchSection


class GeneratedSearchQueries(BaseModel):
    queries: List[str]

    model_config = ConfigDict(extra="forbid")

    @field_validator("queries")
    @classmethod
    def validate_queries(cls, value: List[str]) -> List[str]:
        normalized_queries = [str(query).strip() for query in value if str(query).strip()]
        if len(normalized_queries) != 8:
            raise ValueError("Search query generation must return exactly 8 queries.")
        return normalized_queries


class Insight(BaseModel):
    title: str
    description: str
    source_ids: List[int] = []

    model_config = ConfigDict(extra="forbid")

    @field_validator("title", "description")
    @classmethod
    def validate_text_fields(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("Insight fields must not be empty.")
        return normalized

    @field_validator("source_ids")
    @classmethod
    def validate_source_ids(cls, value: List[int]) -> List[int]:
        normalized_ids: List[int] = []
        for source_id in value:
            try:
                numeric_id = int(source_id)
            except (TypeError, ValueError):
                continue
            if numeric_id <= 0 or numeric_id in normalized_ids:
                continue
            normalized_ids.append(numeric_id)
        return normalized_ids[:20]


def _normalize_text_value(value) -> str:
    return str(value or "").strip()


def _pick_first_text(payload, keys: List[str]) -> str:
    for key in keys:
        normalized = _normalize_text_value(payload.get(key))
        if normalized:
            return normalized
    return ""


def _normalize_sources(raw_sources) -> list[dict[str, str]]:
    if not isinstance(raw_sources, list):
        return []

    normalized_sources: list[dict[str, str]] = []
    seen_keys = set()

    for index, source in enumerate(raw_sources, start=1):
        if not isinstance(source, dict):
            continue

        normalized_source = {
            "source_id": _pick_first_text(source, ["source_id", "id"]) or str(index),
            "title": _pick_first_text(source, ["title", "name", "label"]) or f"Source {index}",
            "url": _pick_first_text(source, ["url", "link", "href"]),
            "domain": _pick_first_text(source, ["domain", "publisher", "site"]),
            "date": _pick_first_text(source, ["date", "published_at", "publishedDate"]),
        }
        dedupe_key = (
            normalized_source["source_id"],
            normalized_source["title"],
            normalized_source["url"],
        )
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        normalized_sources.append(normalized_source)

    return normalized_sources[:20]


def normalize_research_item_payload(item) -> dict[str, object] | None:
    if not isinstance(item, dict):
        return None

    heading = _pick_first_text(item, ["heading", "title", "name", "label", "main_trend", "main_driver"])
    body = _pick_first_text(item, ["body", "description", "details", "summary", "explanation"])
    if not heading or not body:
        return None

    normalized_source_ids: List[int] = []
    raw_source_ids = item.get("source_ids", [])
    if isinstance(raw_source_ids, list):
        for source_id in raw_source_ids:
            try:
                numeric_id = int(source_id)
            except (TypeError, ValueError):
                continue
            if numeric_id > 0 and numeric_id not in normalized_source_ids:
                normalized_source_ids.append(numeric_id)

    return {
        "heading": heading,
        "body": body,
        "sources": _normalize_sources(item.get("sources") or item.get("references") or item.get("evidence")),
        "source_ids": normalized_source_ids[:20],
    }


class Output(BaseModel):
    items: List[Insight]

    model_config = ConfigDict(extra="forbid")

    @field_validator("items")
    @classmethod
    def validate_items(cls, value: List[Insight]) -> List[Insight]:
        if not value:
            raise ValueError("Structured output must contain at least one insight.")
        return value


class CleanedChunk(BaseModel):
    text: str
    reason: str
    source_id: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("text", "reason", "source_id")
    @classmethod
    def validate_text_fields(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("Cleaned chunk fields must not be empty.")
        return normalized


class ContentFilterResponse(BaseModel):
    cleaned_chunks: List[CleanedChunk]

    model_config = ConfigDict(extra="forbid")


class InsightSource(BaseModel):
    source_id: str
    title: str
    url: str
    domain: str = ""
    date: str = ""

    model_config = ConfigDict(extra="forbid")

    @field_validator("source_id", "title", "url", "domain", "date")
    @classmethod
    def validate_source_fields(cls, value: str) -> str:
        return str(value or "").strip()


class ResearchItem(BaseModel):
    heading: str
    body: str
    sources: List[InsightSource] = []
    source_ids: List[int] = []

    model_config = ConfigDict(extra="forbid")

    @field_validator("heading", "body")
    @classmethod
    def validate_text_fields(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("Response item fields must not be empty.")
        return normalized

    @field_validator("source_ids")
    @classmethod
    def validate_source_ids(cls, value: List[int]) -> List[int]:
        normalized_ids: List[int] = []
        for source_id in value:
            try:
                numeric_id = int(source_id)
            except (TypeError, ValueError):
                continue
            if numeric_id <= 0 or numeric_id in normalized_ids:
                continue
            normalized_ids.append(numeric_id)
        return normalized_ids[:10]

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, value: List[InsightSource]) -> List[InsightSource]:
        deduped_sources: List[InsightSource] = []
        seen_keys = set()
        for source in value:
            key = (str(source.url).strip(), str(source.title).strip(), str(source.source_id).strip())
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped_sources.append(source)
        return deduped_sources[:20]


class AnalyzeResponse(BaseModel):
    section: ResearchSection
    title: str
    items: List[ResearchItem]

    model_config = ConfigDict(extra="forbid")

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("Response title is required.")
        return normalized

    @field_validator("items")
    @classmethod
    def validate_items(cls, value: List[ResearchItem]) -> List[ResearchItem]:
        return value


def normalize_analyze_response_payload(payload, fallback_section: str = "trends") -> dict[str, object]:
    normalized_payload = dict(payload) if isinstance(payload, dict) else {}
    normalized_section = _normalize_text_value(normalized_payload.get("section")).lower()
    if normalized_section not in {"trends", "drivers"}:
        normalized_section = _normalize_text_value(fallback_section).lower() or "trends"

    raw_items = normalized_payload.get("items")
    if not isinstance(raw_items, list):
        raw_items = normalized_payload.get(normalized_section)
    if not isinstance(raw_items, list):
        raw_items = []

    normalized_items = [
        normalized_item
        for normalized_item in (normalize_research_item_payload(item) for item in raw_items)
        if normalized_item
    ]

    normalized_title = _pick_first_text(normalized_payload, ["title", "heading"])
    if not normalized_title:
        normalized_title = "Market Drivers" if normalized_section == "drivers" else "Industry Trends"

    normalized_payload["section"] = normalized_section
    normalized_payload["title"] = normalized_title
    normalized_payload["items"] = normalized_items
    return normalized_payload


FollowUpDecision = Literal["SUFFICIENT", "PARTIAL", "INSUFFICIENT"]


class FollowUpResponse(BaseModel):
    decision: FollowUpDecision
    refined_query: str
    reason: str
    new_queries: List[str] = []

    model_config = ConfigDict(extra="forbid")

    @field_validator("refined_query", "reason")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("Follow-up response text fields must not be empty.")
        return normalized

    @field_validator("new_queries")
    @classmethod
    def validate_new_queries(cls, value: List[str]) -> List[str]:
        normalized_queries = []
        seen_queries = set()

        for query in value:
            normalized = str(query).strip()
            normalized_key = normalized.lower()
            if not normalized or normalized_key in seen_queries:
                continue
            seen_queries.add(normalized_key)
            normalized_queries.append(normalized)

        return normalized_queries[:8]

