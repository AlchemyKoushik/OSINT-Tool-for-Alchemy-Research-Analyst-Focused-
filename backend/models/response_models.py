from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models.request_models import ResearchSection


class GeneratedSearchQueries(BaseModel):
    queries: List[str]

    model_config = ConfigDict(extra="forbid")

    @field_validator("queries")
    @classmethod
    def validate_queries(cls, value: List[str]) -> List[str]:
        normalized_queries = [str(query).strip() for query in value if str(query).strip()]
        if len(normalized_queries) != 10:
            raise ValueError("Search query generation must return exactly 10 queries.")
        return normalized_queries


class Example(BaseModel):
    text: str
    company: Optional[str] = ""
    event: Optional[str] = ""
    event_date: Optional[str] = ""
    published_date: Optional[str] = ""
    location: Optional[str] = ""
    example_type: Optional[str] = ""
    why_it_matters: Optional[str] = ""
    source_quality: Optional[str] = ""
    confidence: Optional[str] = ""
    validation_score: Optional[int] = None
    fallback_used: bool = False
    year: Optional[str] = ""

    model_config = ConfigDict(extra="forbid")

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("Example text must not be empty.")
        return normalized

    @field_validator(
        "company",
        "event",
        "event_date",
        "published_date",
        "location",
        "example_type",
        "why_it_matters",
        "source_quality",
        "confidence",
        "year",
    )
    @classmethod
    def validate_optional_text(cls, value: Optional[str]) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def populate_year(self) -> "Example":
        if not self.year:
            self.year = str(self.event_date or self.published_date or "").strip()
        return self


class ExtractedExample(BaseModel):
    company: Optional[str] = ""
    event: Optional[str] = ""
    text: str
    event_date: Optional[str] = ""
    published_date: Optional[str] = ""
    location: Optional[str] = ""
    example_type: Optional[str] = ""
    confidence: Optional[str] = ""
    trend_fit_reason: Optional[str] = ""
    source_quality: Optional[str] = ""
    validation_score: Optional[int] = None
    fallback_used: bool = False
    year: Optional[str] = ""
    source_ids: List[int] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "company",
        "event",
        "event_date",
        "published_date",
        "location",
        "example_type",
        "confidence",
        "trend_fit_reason",
        "source_quality",
        "year",
    )
    @classmethod
    def validate_optional_text_fields(cls, value: Optional[str]) -> str:
        return str(value or "").strip()

    @field_validator("text")
    @classmethod
    def validate_example_text(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("Extracted example text must not be empty.")
        return normalized

    @field_validator("source_ids")
    @classmethod
    def validate_extracted_source_ids(cls, value: List[int]) -> List[int]:
        normalized_ids: List[int] = []
        for source_id in value or []:
            try:
                numeric_id = int(source_id)
            except (TypeError, ValueError):
                continue
            if numeric_id <= 0 or numeric_id in normalized_ids:
                continue
            normalized_ids.append(numeric_id)
        return normalized_ids[:10]

    @model_validator(mode="after")
    def populate_year_alias(self) -> "ExtractedExample":
        if not self.year:
            self.year = str(self.event_date or self.published_date or "").strip()
        return self


class ExampleExtractionResponse(BaseModel):
    examples: List[ExtractedExample] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ExampleSearchQuery(BaseModel):
    query: str
    purpose: str
    priority: Literal["high", "medium", "fallback"]

    model_config = ConfigDict(extra="forbid")

    @field_validator("query", "purpose")
    @classmethod
    def validate_query_fields(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("Example search query fields must not be empty.")
        return normalized


class ExampleSearchQueryResponse(BaseModel):
    queries: List[ExampleSearchQuery]

    model_config = ConfigDict(extra="forbid")

    @field_validator("queries")
    @classmethod
    def validate_example_queries(cls, value: List[ExampleSearchQuery]) -> List[ExampleSearchQuery]:
        if not value:
            raise ValueError("Example search query generation must return at least one query.")
        return value[:8]


class Insight(BaseModel):
    title: str
    description: str
    examples: List[Example] = Field(default_factory=list)
    source_ids: List[int] = Field(default_factory=list)

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

    @field_validator("examples")
    @classmethod
    def validate_examples(cls, value: List[Example]) -> List[Example]:
        normalized_examples: List[Example] = []
        seen_keys = set()
        for example in value or []:
            normalized_example = _coerce_example(example)
            if normalized_example is None:
                continue
            text = normalized_example.text
            year = str(normalized_example.year or "").strip()
            dedupe_key = (text.lower(), year)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            normalized_examples.append(normalized_example)
        return normalized_examples[:3]


def _normalize_text_value(value) -> str:
    return str(value or "").strip()


def _pick_first_text(payload, keys: List[str]) -> str:
    for key in keys:
        normalized = _normalize_text_value(payload.get(key))
        if normalized:
            return normalized
    return ""


def _coerce_example(example) -> Example | None:
    if isinstance(example, Example):
        return example
    if isinstance(example, dict):
        text = str(example.get("text", "")).strip()
        if not text:
            return None
        event_date = str(example.get("event_date", "")).strip()
        published_date = str(example.get("published_date", "")).strip()
        year = str(example.get("year", "")).strip() or event_date or published_date
        return Example(
            text=text,
            company=str(example.get("company", "")).strip(),
            event=str(example.get("event", "")).strip(),
            event_date=event_date,
            published_date=published_date,
            location=str(example.get("location", "")).strip(),
            example_type=str(example.get("example_type", "")).strip(),
            why_it_matters=str(example.get("why_it_matters", "") or example.get("trend_fit_reason", "")).strip(),
            source_quality=str(example.get("source_quality", "")).strip(),
            confidence=str(example.get("confidence", "")).strip(),
            validation_score=(
                int(example.get("validation_score"))
                if str(example.get("validation_score", "")).strip().isdigit()
                else None
            ),
            fallback_used=bool(example.get("fallback_used", False)),
            year=year,
        )
    return None


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
            "image_url": _pick_first_text(source, ["image_url", "image", "thumbnail_url", "thumbnail"]),
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

    normalized_examples: List[dict[str, Any]] = []
    raw_examples = item.get("examples", [])
    if isinstance(raw_examples, list):
        seen_examples = set()
        for example in raw_examples:
            normalized_example = _coerce_example(example)
            if normalized_example is None:
                continue
            dedupe_key = (normalized_example.text.lower(), normalized_example.year or "")
            if dedupe_key in seen_examples:
                continue
            seen_examples.add(dedupe_key)
            normalized_examples.append(
                {
                    "text": normalized_example.text,
                    "company": normalized_example.company,
                    "event": normalized_example.event,
                    "event_date": normalized_example.event_date,
                    "published_date": normalized_example.published_date,
                    "location": normalized_example.location,
                    "example_type": normalized_example.example_type,
                    "why_it_matters": normalized_example.why_it_matters,
                    "source_quality": normalized_example.source_quality,
                    "confidence": normalized_example.confidence,
                    "validation_score": normalized_example.validation_score,
                    "fallback_used": normalized_example.fallback_used,
                    "year": str(normalized_example.year or "").strip(),
                }
            )

    return {
        "heading": heading,
        "body": body,
        "examples": normalized_examples[:3],
        "sources": _normalize_sources(item.get("sources") or item.get("references") or item.get("evidence")),
        "source_ids": normalized_source_ids[:20],
        "example_coverage_status": _normalize_text_value(item.get("example_coverage_status")),
        "fallback_used": bool(item.get("fallback_used", False)),
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
    image_url: str = ""

    model_config = ConfigDict(extra="forbid")

    @field_validator("source_id", "title", "url", "domain", "date", "image_url")
    @classmethod
    def validate_source_fields(cls, value: str) -> str:
        return str(value or "").strip()


class ResearchItem(BaseModel):
    heading: str
    body: str
    examples: List[Example] = Field(default_factory=list)
    sources: List[InsightSource] = Field(default_factory=list)
    source_ids: List[int] = Field(default_factory=list)
    example_coverage_status: str = ""
    fallback_used: bool = False

    model_config = ConfigDict(extra="forbid")

    @field_validator("heading", "body")
    @classmethod
    def validate_text_fields(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("Response item fields must not be empty.")
        return normalized

    @field_validator("example_coverage_status")
    @classmethod
    def validate_coverage_status(cls, value: str) -> str:
        return str(value or "").strip()

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

    @field_validator("examples")
    @classmethod
    def validate_research_examples(cls, value: List[Example]) -> List[Example]:
        normalized_examples: List[Example] = []
        seen_keys = set()
        for example in value or []:
            normalized_example = _coerce_example(example)
            if normalized_example is None:
                continue
            dedupe_key = (normalized_example.text.lower(), normalized_example.year or "")
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            normalized_examples.append(normalized_example)
        return normalized_examples[:3]


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

        return normalized_queries[:10]
