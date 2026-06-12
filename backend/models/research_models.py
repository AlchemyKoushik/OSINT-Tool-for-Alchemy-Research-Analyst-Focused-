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


class CompetitiveLandscapeProfile(BaseModel):
    business_overview: str = ""
    key_company_facts: List[str] = Field(default_factory=list)
    competitive_positioning: str = ""
    recent_developments: List[ExtractedExample] = Field(default_factory=list)
    source_ids: List[int] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("business_overview", "competitive_positioning")
    @classmethod
    def validate_optional_profile_text(cls, value: str) -> str:
        return str(value or "").strip()

    @field_validator("key_company_facts")
    @classmethod
    def validate_profile_facts(cls, value: List[str]) -> List[str]:
        normalized_facts: List[str] = []
        seen_facts = set()
        for fact in value or []:
            normalized = str(fact or "").strip()
            normalized_key = normalized.lower()
            if not normalized or normalized_key in seen_facts:
                continue
            seen_facts.add(normalized_key)
            normalized_facts.append(normalized)
        return normalized_facts[:5]

    @field_validator("recent_developments")
    @classmethod
    def validate_profile_developments(cls, value: List[ExtractedExample]) -> List[ExtractedExample]:
        normalized_examples: List[ExtractedExample] = []
        seen_keys = set()
        for example in value or []:
            if not isinstance(example, ExtractedExample):
                continue
            dedupe_key = (
                str(example.text or "").strip().lower(),
                str(example.event_date or example.published_date or example.year or "").strip(),
            )
            if not dedupe_key[0] or dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            normalized_examples.append(example)
        normalized_examples.sort(
            key=lambda example: str(example.event_date or example.published_date or example.year or "").strip(),
            reverse=True,
        )
        return normalized_examples[:5]

    @field_validator("source_ids")
    @classmethod
    def validate_profile_source_ids(cls, value: List[int]) -> List[int]:
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


class CompetitiveLandscapeProfileResponse(BaseModel):
    profile: CompetitiveLandscapeProfile = Field(default_factory=CompetitiveLandscapeProfile)

    model_config = ConfigDict(extra="forbid")


class CompetitiveLandscapeCompanyDraft(BaseModel):
    company_name: str
    market_role: str
    business_overview: str
    key_company_facts: List[str] = Field(default_factory=list)
    competitive_positioning: str = ""
    source_ids: List[int] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("company_name", "market_role", "business_overview")
    @classmethod
    def validate_required_company_text(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("Competitive landscape company fields must not be empty.")
        return normalized

    @field_validator("competitive_positioning")
    @classmethod
    def validate_optional_company_text(cls, value: str) -> str:
        return str(value or "").strip()

    @field_validator("key_company_facts")
    @classmethod
    def validate_company_facts(cls, value: List[str]) -> List[str]:
        normalized_facts: List[str] = []
        seen_facts = set()
        for fact in value or []:
            normalized = str(fact or "").strip()
            normalized_key = normalized.lower()
            if not normalized or normalized_key in seen_facts:
                continue
            seen_facts.add(normalized_key)
            normalized_facts.append(normalized)
        return normalized_facts[:7]

    @field_validator("source_ids")
    @classmethod
    def validate_company_source_ids(cls, value: List[int]) -> List[int]:
        normalized_ids: List[int] = []
        for source_id in value or []:
            try:
                numeric_id = int(source_id)
            except (TypeError, ValueError):
                continue
            if numeric_id <= 0 or numeric_id in normalized_ids:
                continue
            normalized_ids.append(numeric_id)
        return normalized_ids[:20]


class CompetitiveLandscapeOutput(BaseModel):
    major_players: List[CompetitiveLandscapeCompanyDraft] = Field(default_factory=list)
    emerging_players: List[CompetitiveLandscapeCompanyDraft] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("major_players", "emerging_players")
    @classmethod
    def validate_company_groups(cls, value: List[CompetitiveLandscapeCompanyDraft]) -> List[CompetitiveLandscapeCompanyDraft]:
        deduped: List[CompetitiveLandscapeCompanyDraft] = []
        seen_names = set()
        for company in value or []:
            name_key = str(company.company_name or "").strip().lower()
            if not name_key or name_key in seen_names:
                continue
            seen_names.add(name_key)
            deduped.append(company)
        return deduped

    @model_validator(mode="after")
    def validate_non_empty_groups(self) -> "CompetitiveLandscapeOutput":
        if not self.major_players and not self.emerging_players:
            raise ValueError("Competitive landscape output must contain at least one company.")
        return self


class CompetitiveLandscapeDiscoveryCompany(BaseModel):
    company_name: str
    market_role: str
    source_ids: List[int] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("company_name", "market_role")
    @classmethod
    def validate_discovery_text(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("Competitive landscape discovery fields must not be empty.")
        return normalized

    @field_validator("source_ids")
    @classmethod
    def validate_discovery_source_ids(cls, value: List[int]) -> List[int]:
        normalized_ids: List[int] = []
        for source_id in value or []:
            try:
                numeric_id = int(source_id)
            except (TypeError, ValueError):
                continue
            if numeric_id <= 0 or numeric_id in normalized_ids:
                continue
            normalized_ids.append(numeric_id)
        return normalized_ids[:20]


class CompetitiveLandscapeDiscoveryOutput(BaseModel):
    major_players: List[CompetitiveLandscapeDiscoveryCompany] = Field(default_factory=list)
    emerging_players: List[CompetitiveLandscapeDiscoveryCompany] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_discovery_groups(self) -> "CompetitiveLandscapeDiscoveryOutput":
        if not self.major_players and not self.emerging_players:
            raise ValueError("Competitive landscape discovery must contain at least one company.")
        return self


class CompetitiveLandscapeDiscoveryAgentCompany(BaseModel):
    company: str
    tier: Literal["Major Player", "Mid-Sized Player", "Emerging Player"]
    confidence: int
    reasons: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("company")
    @classmethod
    def validate_agent_company(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("Discovery agent company must not be empty.")
        return normalized

    @field_validator("confidence")
    @classmethod
    def validate_agent_confidence(cls, value: int) -> int:
        numeric_value = int(value)
        if numeric_value < 0:
            return 0
        if numeric_value > 100:
            return 100
        return numeric_value

    @field_validator("reasons")
    @classmethod
    def validate_agent_reasons(cls, value: List[str]) -> List[str]:
        normalized_reasons: List[str] = []
        seen_reasons = set()
        for reason in value or []:
            normalized = str(reason or "").strip()
            normalized_key = normalized.lower()
            if not normalized or normalized_key in seen_reasons:
                continue
            seen_reasons.add(normalized_key)
            normalized_reasons.append(normalized)
        return normalized_reasons[:5]


class CompetitiveLandscapeDiscoveryAgentOutput(BaseModel):
    companies: List[CompetitiveLandscapeDiscoveryAgentCompany] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("companies")
    @classmethod
    def validate_agent_companies(
        cls,
        value: List[CompetitiveLandscapeDiscoveryAgentCompany],
    ) -> List[CompetitiveLandscapeDiscoveryAgentCompany]:
        deduped: List[CompetitiveLandscapeDiscoveryAgentCompany] = []
        seen_names = set()
        for company in value or []:
            company_key = str(company.company or "").strip().lower()
            if not company_key or company_key in seen_names:
                continue
            seen_names.add(company_key)
            deduped.append(company)
        return deduped[:24]

    @model_validator(mode="after")
    def validate_agent_output(self) -> "CompetitiveLandscapeDiscoveryAgentOutput":
        if not self.companies:
            raise ValueError("Competitive landscape discovery agent must contain at least one company.")
        return self


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
    segment: str = ""
    key_company_facts: List[str] = Field(default_factory=list)
    competitive_positioning: str = ""
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

    @field_validator("segment")
    @classmethod
    def validate_segment(cls, value: str) -> str:
        return str(value or "").strip().lower()

    @field_validator("key_company_facts")
    @classmethod
    def validate_key_company_facts(cls, value: List[str]) -> List[str]:
        normalized_facts: List[str] = []
        seen_facts = set()
        for fact in value or []:
            normalized = str(fact or "").strip()
            normalized_key = normalized.lower()
            if not normalized or normalized_key in seen_facts:
                continue
            seen_facts.add(normalized_key)
            normalized_facts.append(normalized)
        return normalized_facts[:5]

    @field_validator("competitive_positioning")
    @classmethod
    def validate_competitive_positioning(cls, value: str) -> str:
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
        return normalized_examples[:5]


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
        "segment": _pick_first_text(item, ["segment", "player_segment", "tier", "bucket"]).lower(),
        "market_role": _pick_first_text(item, ["market_role", "role", "company_role"]),
        "key_company_facts": [
            normalized_fact
            for normalized_fact in [
                _normalize_text_value(fact)
                for fact in (
                    item.get("key_company_facts")
                    or item.get("key_facts")
                    or item.get("company_facts")
                    or []
                )
            ]
            if normalized_fact
        ][:5],
        "competitive_positioning": _pick_first_text(
            item,
            ["competitive_positioning", "competitive_implication", "positioning_implication"],
        ),
        "examples": normalized_examples[:5],
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
    segment: str = ""
    market_role: str = ""
    key_company_facts: List[str] = Field(default_factory=list)
    competitive_positioning: str = ""
    examples: List[Example] = Field(default_factory=list)
    sources: List[InsightSource] = Field(default_factory=list)
    source_ids: List[int] = Field(default_factory=list)
    example_coverage_status: str = ""
    fallback_used: bool = False

    model_config = ConfigDict(extra="forbid")

    @field_validator("heading")
    @classmethod
    def validate_heading(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("Response item fields must not be empty.")
        return normalized

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        return str(value or "").strip()

    @field_validator("segment")
    @classmethod
    def validate_segment(cls, value: str) -> str:
        return str(value or "").strip().lower()

    @field_validator("market_role")
    @classmethod
    def validate_market_role(cls, value: str) -> str:
        return str(value or "").strip()

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
        return normalized_examples[:5]

    @field_validator("key_company_facts")
    @classmethod
    def validate_research_key_company_facts(cls, value: List[str]) -> List[str]:
        normalized_facts: List[str] = []
        seen_facts = set()
        for fact in value or []:
            normalized = str(fact or "").strip()
            normalized_key = normalized.lower()
            if not normalized or normalized_key in seen_facts:
                continue
            seen_facts.add(normalized_key)
            normalized_facts.append(normalized)
        return normalized_facts[:5]

    @field_validator("competitive_positioning")
    @classmethod
    def validate_research_competitive_positioning(cls, value: str) -> str:
        return str(value or "").strip()


class AnalyzeResponse(BaseModel):
    section: ResearchSection
    title: str
    items: List[ResearchItem] = Field(default_factory=list)
    major_players: List[ResearchItem] = Field(default_factory=list)
    emerging_players: List[ResearchItem] = Field(default_factory=list)

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

    @field_validator("major_players", "emerging_players")
    @classmethod
    def validate_company_groups(cls, value: List[ResearchItem]) -> List[ResearchItem]:
        return value

    @model_validator(mode="after")
    def validate_section_payload(self) -> "AnalyzeResponse":
        if self.section == "competitive_landscape":
            if not self.major_players and not self.emerging_players:
                raise ValueError("Competitive Landscape responses must include major_players or emerging_players.")
        elif not self.items:
            raise ValueError("Trends and Drivers responses must include items.")
        elif any(not str(item.body or "").strip() for item in self.items):
            raise ValueError("Trends and Drivers response item body fields must not be empty.")
        return self


def _normalize_competitive_landscape_company_payload(item) -> dict[str, object] | None:
    normalized_item = normalize_research_item_payload(item)
    if normalized_item is None:
        return None

    market_role = _pick_first_text(item, ["market_role", "role", "company_role"]).strip()
    normalized_item["market_role"] = market_role
    return normalized_item


def normalize_analyze_response_payload(payload, fallback_section: str = "trends") -> dict[str, object]:
    normalized_payload = dict(payload) if isinstance(payload, dict) else {}
    normalized_section = _normalize_text_value(normalized_payload.get("section")).lower()
    if normalized_section not in {"trends", "drivers", "competitive_landscape"}:
        normalized_section = _normalize_text_value(fallback_section).lower() or "trends"

    if normalized_section == "competitive_landscape":
        raw_major_players = normalized_payload.get("major_players")
        raw_emerging_players = normalized_payload.get("emerging_players")

        if not isinstance(raw_major_players, list) and not isinstance(raw_emerging_players, list):
            fallback_items = normalized_payload.get("items")
            if isinstance(fallback_items, list):
                raw_major_players = [
                    item
                    for item in fallback_items
                    if _pick_first_text(item, ["segment", "player_segment", "tier", "bucket"]).lower()
                    in {"major_players", "top_players"}
                ]
                raw_emerging_players = [
                    item
                    for item in fallback_items
                    if _pick_first_text(item, ["segment", "player_segment", "tier", "bucket"]).lower()
                    not in {"major_players", "top_players"}
                ]

        normalized_major_players = [
            normalized_item
            for normalized_item in (
                _normalize_competitive_landscape_company_payload(item) for item in (raw_major_players or [])
            )
            if normalized_item
        ]
        normalized_emerging_players = [
            normalized_item
            for normalized_item in (
                _normalize_competitive_landscape_company_payload(item) for item in (raw_emerging_players or [])
            )
            if normalized_item
        ]
        normalized_items = [*normalized_major_players, *normalized_emerging_players]

        normalized_title = _pick_first_text(normalized_payload, ["title", "heading"]) or "Competitive Landscape"
        normalized_payload["section"] = normalized_section
        normalized_payload["title"] = normalized_title
        normalized_payload["major_players"] = normalized_major_players
        normalized_payload["emerging_players"] = normalized_emerging_players
        normalized_payload["items"] = normalized_items
        return normalized_payload

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
        normalized_title = {
            "drivers": "Market Drivers",
            "competitive_landscape": "Competitive Landscape",
        }.get(normalized_section, "Industry Trends")

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
