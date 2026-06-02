from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from config.settings import settings
from services.location_service import resolve_location_context


ResearchSection = Literal["trends", "drivers", "competitive_landscape"]
LocationPreference = Literal["global", "region_specific", "country_specific"]


def _validate_non_empty_string(value: str, *, field_name: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} exceeds the maximum length of {max_length} characters.")
    return normalized


def _validate_existing_chunks(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(chunks) > settings.MAX_EXISTING_CHUNKS:
        raise ValueError(f"existing_chunks exceeds the maximum count of {settings.MAX_EXISTING_CHUNKS}.")

    normalized_chunks: List[Dict[str, Any]] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        normalized_chunk = dict(chunk)
        text = str(normalized_chunk.get("text", "")).strip()
        if text and len(text) > settings.MAX_CHUNK_TEXT_LENGTH:
            raise ValueError(
                f"existing chunk text exceeds the maximum length of {settings.MAX_CHUNK_TEXT_LENGTH} characters."
            )
        normalized_chunks.append(normalized_chunk)
    return normalized_chunks


class AnalyzeRequest(BaseModel):
    topic: str
    section: ResearchSection
    location_preference: LocationPreference = "global"
    location_value: str | None = None
    session_id: str | None = None
    debug: bool = False
    queries: List[str] = []
    follow_up_mode: bool = False
    existing_chunks: List[Dict[str, Any]] = []

    model_config = ConfigDict(extra="forbid")

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, value: str) -> str:
        return _validate_non_empty_string(value, field_name="Topic", max_length=settings.MAX_QUERY_LENGTH)

    @field_validator("location_value")
    @classmethod
    def validate_location_value(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @field_validator("queries")
    @classmethod
    def validate_queries(cls, value: List[str]) -> List[str]:
        normalized_queries: List[str] = []
        seen_queries = set()
        for query in value:
            normalized = str(query).strip()
            if len(normalized) > settings.MAX_QUERY_LENGTH:
                raise ValueError(f"Query exceeds the maximum length of {settings.MAX_QUERY_LENGTH} characters.")
            normalized_key = normalized.lower()
            if not normalized or normalized_key in seen_queries:
                continue
            seen_queries.add(normalized_key)
            normalized_queries.append(normalized)
        return normalized_queries

    @field_validator("existing_chunks")
    @classmethod
    def validate_existing_chunks(cls, value: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return _validate_existing_chunks(value)

    @model_validator(mode="after")
    def validate_location_selection(self) -> "AnalyzeRequest":
        context = resolve_location_context(self.location_preference, self.location_value)
        self.location_preference = context.preference  # type: ignore[assignment]
        self.location_value = context.value or None
        return self


class FollowUpRequest(BaseModel):
    follow_up_query: str
    session_id: str | None = None
    existing_chunks: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {}

    model_config = ConfigDict(extra="forbid")

    @field_validator("follow_up_query")
    @classmethod
    def validate_follow_up_query(cls, value: str) -> str:
        return _validate_non_empty_string(
            value,
            field_name="follow_up_query",
            max_length=settings.MAX_FOLLOW_UP_QUERY_LENGTH,
        )

    @field_validator("session_id")
    @classmethod
    def validate_follow_up_session_id(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @field_validator("existing_chunks")
    @classmethod
    def validate_follow_up_existing_chunks(cls, value: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return _validate_existing_chunks(value)


class AnalyzeExistingRequest(BaseModel):
    refined_query: str
    session_id: str | None = None
    existing_chunks: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {}

    model_config = ConfigDict(extra="forbid")

    @field_validator("refined_query")
    @classmethod
    def validate_refined_query(cls, value: str) -> str:
        return _validate_non_empty_string(
            value,
            field_name="refined_query",
            max_length=settings.MAX_FOLLOW_UP_QUERY_LENGTH,
        )

    @field_validator("session_id")
    @classmethod
    def validate_existing_session_id(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @field_validator("existing_chunks")
    @classmethod
    def validate_analyze_existing_chunks(cls, value: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return _validate_existing_chunks(value)


class PdfExportRequest(BaseModel):
    result: Dict[str, Any]
    meta: Dict[str, Any] = {}
    follow_ups: List[Dict[str, Any]] = []

    model_config = ConfigDict(extra="forbid")

    @field_validator("result")
    @classmethod
    def validate_result(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError("result is required.")
        return value

    @field_validator("meta")
    @classmethod
    def validate_meta(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @field_validator("follow_ups")
    @classmethod
    def validate_follow_ups(cls, value: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [entry for entry in value if isinstance(entry, dict)]

