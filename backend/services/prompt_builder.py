import json
from typing import Any, Dict, Final, List, Optional

from services.location_service import LocationContext
from services.prompt_file_service import (
    get_current_research_date,
    get_example_extraction_prompt_template,
    get_main_output_prompt_template,
)

SECTION_DEFINITIONS: Final[Dict[str, str]] = {
    "trends": (
        "Identify WHAT is changing in the market. Focus on observable shifts such as adoption patterns, "
        "customer behavior, pricing, product mix, channel mix, competitor moves, capacity changes, and "
        "operating model evolution."
    ),
    "drivers": (
        "Explain WHY the market is changing. Focus on causal forces such as regulation, subsidies, demand "
        "signals, input costs, labor availability, supply chain changes, infrastructure, technology, "
        "investment, and strategic actions."
    ),
}

SECTION_TITLES: Final[Dict[str, str]] = {
    "trends": "Industry Trends",
    "drivers": "Market Drivers",
}


def get_prompt(section: str, max_items: int = 10) -> str:
    normalized_section = str(section or "").strip().lower()
    if normalized_section not in SECTION_TITLES:
        raise ValueError("Invalid section")

    return get_main_output_prompt_template().replace("{max_items}", str(max(1, int(max_items or 1))))


def get_example_extraction_prompt(section: str) -> str:
    normalized_section = str(section or "").strip().lower()
    if normalized_section not in SECTION_TITLES:
        raise ValueError("Invalid section")
    return get_example_extraction_prompt_template()


def get_section_title(section: str) -> str:
    title = SECTION_TITLES.get(section)
    if title is None:
        raise ValueError("Invalid section")
    return title


def _format_evidence_blocks(evidence_blocks: Optional[List[Dict[str, Any]]]) -> str:
    if not evidence_blocks:
        return "[]"

    compact_blocks: List[Dict[str, Any]] = []
    for index, block in enumerate(evidence_blocks[:20], start=1):
        excerpt = str(block.get("excerpt", "")).strip()
        if not excerpt:
            continue
        compact_blocks.append(
            {
                "source_id": index,
                "title": str(block.get("title", "")).strip(),
                "date": str(block.get("date", "")).strip(),
                "domain": str(block.get("domain", "")).strip(),
                "excerpt": excerpt,
            }
        )

    return json.dumps(compact_blocks, ensure_ascii=True, indent=2)


def _format_source_metadata(
    source_scores: Optional[List[Dict[str, Any]]],
    artifact_counts: Optional[Dict[str, Any]],
) -> str:
    compact_sources: List[Dict[str, Any]] = []
    for source in (source_scores or [])[:20]:
        compact_sources.append(
            {
                "title": str(source.get("title", "")).strip(),
                "domain": str(source.get("domain", "")).strip(),
                "score": int(source.get("score", 0)),
                "newest_year": source.get("newest_year"),
            }
        )

    metadata_payload = {
        "artifact_counts": artifact_counts or {},
        "sources": compact_sources,
    }
    return json.dumps(metadata_payload, ensure_ascii=True, indent=2)


def _format_location_line(context: LocationContext) -> str:
    if context.preference == "region_specific":
        return f"- Location: Region / {context.value}"
    if context.preference == "country_specific":
        return f"- Location: Country / {context.value}"
    return "- Location: Global / Global"


def build_metadata_payload(
    topic: str,
    section: str,
    processed_sources: str = "",
    insight_analysis: Optional[Dict[str, Any]] = None,
    signal_weights: Optional[List[Dict[str, Any]]] = None,
    historical_sources: Optional[List[str]] = None,
    depth: str = "high",
    freshness: str = "high",
    location_context: Optional[LocationContext] = None,
    evidence_blocks: Optional[List[Dict[str, Any]]] = None,
    source_scores: Optional[List[Dict[str, Any]]] = None,
    artifact_counts: Optional[Dict[str, Any]] = None,
    max_items: int = 10,
) -> str:
    del insight_analysis, signal_weights, historical_sources, depth, freshness, processed_sources

    normalized_section = str(section or "").strip().lower()
    if normalized_section not in SECTION_TITLES:
        raise ValueError("Invalid section")

    resolved_location_context = location_context or LocationContext()

    payload = (
        "INPUT\n"
        f"- Topic: {topic.strip()}\n"
        f"- Section: {normalized_section.title()}\n"
        f"- Research date: {get_current_research_date()}\n"
        f"{_format_location_line(resolved_location_context)}\n"
        "\n"
        "ANALYSIS RULES\n"
        "- Evidence has already been cleaned and filtered.\n"
        "- Use only the supplied evidence.\n"
        "- Ignore any residual noise if present.\n"
        "- Generate insights after understanding the full evidence set, not source by source.\n"
        "- Prioritize concrete signals, changes, and implications over descriptive filler.\n"
        f"- Section focus: {SECTION_DEFINITIONS[normalized_section]}\n"
        "- Every returned item must include supporting source_ids from the numbered evidence blocks.\n"
        f"- Final output cap: Return only the top {max(1, int(max_items or 1))} ranked insights.\n\n"
        "SOURCE_METADATA\n"
        f"{_format_source_metadata(source_scores, artifact_counts)}\n\n"
        "EVIDENCE\n"
        f"{_format_evidence_blocks(evidence_blocks)}"
    )
    return payload.strip()


def build_example_extraction_payload(
    *,
    topic: str,
    section: str,
    location_context: Optional[LocationContext] = None,
    evidence_blocks: Optional[List[Dict[str, Any]]] = None,
) -> str:
    normalized_section = str(section or "").strip().lower()
    if normalized_section not in SECTION_TITLES:
        raise ValueError("Invalid section")

    resolved_location_context = location_context or LocationContext()
    return (
        "INPUT\n"
        f"- Topic: {topic.strip()}\n"
        f"- Section: {normalized_section.title()}\n"
        f"- Research date: {get_current_research_date()}\n"
        f"{_format_location_line(resolved_location_context)}\n"
        f"- Section focus: {SECTION_DEFINITIONS[normalized_section]}\n\n"
        "TASK\n"
        "- Review the evidence bundle and extract only explicit, factual examples that could support later synthesis.\n"
        "- Return no examples if the evidence does not support any concrete examples safely.\n\n"
        "EVIDENCE\n"
        f"{_format_evidence_blocks(evidence_blocks)}"
    ).strip()


def build_trend_example_extraction_payload(
    *,
    topic: str,
    section: str,
    trend_heading: str,
    trend_body: str,
    location_context: Optional[LocationContext] = None,
    evidence_blocks: Optional[List[Dict[str, Any]]] = None,
) -> str:
    normalized_section = str(section or "").strip().lower()
    if normalized_section not in SECTION_TITLES:
        raise ValueError("Invalid section")

    resolved_location_context = location_context or LocationContext()
    return (
        "INPUT\n"
        f"- Topic: {topic.strip()}\n"
        f"- Section: {normalized_section.title()}\n"
        f"- Research date: {get_current_research_date()}\n"
        f"{_format_location_line(resolved_location_context)}\n"
        f"- Written trend title: {trend_heading.strip()}\n"
        f"- Written trend description: {trend_body.strip()}\n\n"
        "TASK\n"
        "- Use only the newly researched evidence below.\n"
        "- Extract only factual examples that directly support the written trend or driver above.\n"
        "- An example must be a concrete company-level or organization-level event, not a generic market statement.\n"
        "- Prefer examples shaped like: Company A acquired Company B, Company C launched X, Company D raised funding, Company E expanded capacity.\n"
        "- Prefer examples supported by the latest available evidence, ideally from the last two years relative to the research date.\n"
        "- Include the most specific event date available in the `year` field, such as `March 2026` or `2026-03-14`; use just the year only if the source does not provide a better date.\n"
        "- The `text` field should read like a short factual event line and should name the company and action explicitly.\n"
        "- If recent examples are not clearly supported, return no examples rather than forcing weak or loosely related ones.\n"
        "- If the evidence is not clearly tied to the written trend or driver, return no examples.\n\n"
        "EVIDENCE\n"
        f"{_format_evidence_blocks(evidence_blocks)}"
    ).strip()
