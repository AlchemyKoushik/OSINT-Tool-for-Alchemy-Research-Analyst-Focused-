from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Literal, Tuple


SearchTimeline = Literal[
    "any_time",
    "past_month",
    "past_year",
    "past_2_years",
    "past_5_years",
]
EvidenceHorizon = Literal["open", "short_term", "medium_term", "long_term"]
EvidenceHorizonInput = Literal["Short-Term", "Medium-Term", "Long-Term", "short_term", "medium_term", "long_term"]


@dataclass(frozen=True)
class SearchTimelineContext:
    preset: SearchTimeline
    label: str
    evidence_horizon: EvidenceHorizon
    evidence_horizon_label: str
    ddg_timelimit: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    query_hint: str = ""
    time_anchors: Tuple[str, ...] = ()

    @property
    def is_limited(self) -> bool:
        return bool(self.ddg_timelimit)

    @property
    def backend(self) -> str:
        return "duckduckgo" if self.is_limited else "auto"


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _subtract_years(anchor: date, years: int) -> date:
    try:
        return anchor.replace(year=anchor.year - years)
    except ValueError:
        return anchor.replace(month=2, day=28, year=anchor.year - years)


def _build_range_ddg_timelimit(start_date: date, end_date: date) -> str:
    return f"{start_date.isoformat()}..{end_date.isoformat()}"


def _short_term_anchors(anchor: date) -> Tuple[str, ...]:
    return (str(anchor.year - 1), str(anchor.year - 2), "latest")


def resolve_search_timeline(value: str | None, *, as_of: date | None = None) -> SearchTimelineContext:
    anchor = as_of or _today_utc()
    normalized = str(value or "any_time").strip() or "any_time"

    presets: Dict[str, SearchTimelineContext] = {
        "any_time": SearchTimelineContext(
            preset="any_time",
            label="Any Time",
            evidence_horizon="open",
            evidence_horizon_label="Any Time",
            query_hint="Keep the search window open across all available publication dates.",
            time_anchors=("latest", "current", "report"),
        ),
        "past_month": SearchTimelineContext(
            preset="past_month",
            label="Last 30 Days",
            evidence_horizon="short_term",
            evidence_horizon_label="Short-Term",
            ddg_timelimit=_build_range_ddg_timelimit(anchor - timedelta(days=30), anchor),
            start_date=anchor - timedelta(days=30),
            end_date=anchor,
            query_hint="Prioritize sources published within the last 30 days only.",
            time_anchors=_short_term_anchors(anchor),
        ),
        "past_year": SearchTimelineContext(
            preset="past_year",
            label="Last 12 Months",
            evidence_horizon="short_term",
            evidence_horizon_label="Short-Term",
            ddg_timelimit=_build_range_ddg_timelimit(_subtract_years(anchor, 1), anchor),
            start_date=_subtract_years(anchor, 1),
            end_date=anchor,
            query_hint="Prioritize sources published within the last 12 months only.",
            time_anchors=_short_term_anchors(anchor),
        ),
        "past_2_years": SearchTimelineContext(
            preset="past_2_years",
            label="Last 2 Years",
            evidence_horizon="medium_term",
            evidence_horizon_label="Medium-Term",
            ddg_timelimit=_build_range_ddg_timelimit(_subtract_years(anchor, 2), anchor),
            start_date=_subtract_years(anchor, 2),
            end_date=anchor,
            query_hint="Prioritize sources published within the last 2 years only.",
            time_anchors=("last 5 years", "trend analysis"),
        ),
        "past_5_years": SearchTimelineContext(
            preset="past_5_years",
            label="Last 5 Years",
            evidence_horizon="long_term",
            evidence_horizon_label="Long-Term",
            ddg_timelimit=_build_range_ddg_timelimit(_subtract_years(anchor, 5), anchor),
            start_date=_subtract_years(anchor, 5),
            end_date=anchor,
            query_hint="Prioritize sources published within the last 5 years only.",
            time_anchors=("2030", "long-term outlook"),
        ),
    }

    return presets.get(normalized, presets["any_time"])


def resolve_timeline_from_evidence_horizon(
    value: str | None,
    *,
    as_of: date | None = None,
) -> SearchTimelineContext:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "short_term": "past_year",
        "medium_term": "past_2_years",
        "long_term": "past_5_years",
    }
    return resolve_search_timeline(mapping.get(normalized, "any_time"), as_of=as_of)


def get_search_timeline_signature(context: SearchTimelineContext) -> str:
    return context.preset


def describe_search_timeline(context: SearchTimelineContext) -> Dict[str, Any]:
    return {
        "preset": context.preset,
        "label": context.label,
        "evidence_horizon": context.evidence_horizon,
        "evidence_horizon_label": context.evidence_horizon_label,
        "time_anchors": list(context.time_anchors),
        "start_date": context.start_date.isoformat() if context.start_date else None,
        "end_date": context.end_date.isoformat() if context.end_date else None,
    }


def build_search_timeline_hint(context: SearchTimelineContext) -> str:
    return context.query_hint or "Keep the search window open across all available publication dates."


def build_evidence_horizon_summary(context: SearchTimelineContext) -> str:
    if context.evidence_horizon == "open":
        return "Any Time"
    return f"{context.evidence_horizon_label} ({context.label})"


def timeline_matches_years(
    years: Iterable[int] | None,
    context: SearchTimelineContext,
    *,
    allow_unknown: bool = True,
) -> bool:
    if not context.is_limited:
        return True

    normalized_years = [int(year) for year in (years or []) if isinstance(year, int) or str(year).isdigit()]
    if not normalized_years:
        return allow_unknown

    if context.start_date is None or context.end_date is None:
        return True

    start_year = context.start_date.year
    end_year = context.end_date.year
    return any(start_year <= year <= end_year for year in normalized_years)
