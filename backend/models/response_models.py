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
        if len(normalized_queries) != 15:
            raise ValueError("Search query generation must return exactly 15 queries.")
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

