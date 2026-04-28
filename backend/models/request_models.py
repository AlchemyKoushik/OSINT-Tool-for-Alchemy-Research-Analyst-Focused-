from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from services.location_service import resolve_location_context


ResearchSection = Literal["trends", "drivers"]
LocationPreference = Literal["global", "region_specific", "country_specific"]


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
        normalized = value.strip()
        if not normalized:
            raise ValueError("Topic is required.")
        return normalized

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
            normalized_key = normalized.lower()
            if not normalized or normalized_key in seen_queries:
                continue
            seen_queries.add(normalized_key)
            normalized_queries.append(normalized)
        return normalized_queries

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
        normalized = value.strip()
        if not normalized:
            raise ValueError("follow_up_query is required.")
        return normalized

    @field_validator("session_id")
    @classmethod
    def validate_follow_up_session_id(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None


class AnalyzeExistingRequest(BaseModel):
    refined_query: str
    session_id: str | None = None
    existing_chunks: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {}

    model_config = ConfigDict(extra="forbid")

    @field_validator("refined_query")
    @classmethod
    def validate_refined_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("refined_query is required.")
        return normalized

    @field_validator("session_id")
    @classmethod
    def validate_existing_session_id(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

