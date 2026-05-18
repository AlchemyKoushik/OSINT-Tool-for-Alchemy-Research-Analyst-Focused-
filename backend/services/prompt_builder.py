import json
from typing import Any, Dict, Final, List, Optional

from services.location_service import LocationContext
from services.prompt_file_service import (
    get_current_research_date,
    get_example_extraction_prompt_template,
    get_example_search_query_system_prompt_template,
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


def build_example_search_query_system_prompt() -> str:
    return get_example_search_query_system_prompt_template()


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


def _format_example_evidence_blocks(evidence_blocks: Optional[List[Dict[str, Any]]]) -> str:
    if not evidence_blocks:
        return "[]"

    compact_blocks: List[Dict[str, Any]] = []
    for index, block in enumerate(evidence_blocks[:24], start=1):
        excerpt = str(block.get("excerpt", "") or block.get("full_text_excerpt", "")).strip()
        snippet = str(block.get("snippet", "")).strip() or excerpt[:500]
        compact_blocks.append(
            {
                "source_id": int(block.get("source_id", index)) if str(block.get("source_id", "")).strip().isdigit() else index,
                "title": str(block.get("title", "")).strip(),
                "url": str(block.get("url", "")).strip(),
                "publisher": str(block.get("publisher", "") or block.get("domain", "")).strip(),
                "published_date": str(block.get("published_date", "") or block.get("date", "")).strip(),
                "retrieved_date": str(block.get("retrieved_date", "")).strip() or get_current_research_date(),
                "source_tier": str(block.get("source_tier", "")).strip() or "Tier 3",
                "snippet": snippet,
                "full_text_excerpt": excerpt,
            }
        )

    return json.dumps(compact_blocks, ensure_ascii=True, indent=2)


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
    current_date = get_current_research_date()
    current_year = current_date[:4]
    previous_year = str(int(current_year) - 1)
    two_years_ago = str(int(current_year) - 2)
    synonym_line = ""
    combined_trend_text = f"{trend_heading.strip()} {trend_body.strip()}".lower()
    if any(term in combined_trend_text for term in ("space-based solar power", "space based solar power", "sbsp", "space solar power", "space-based solar", "solar power satellite", "orbital solar", "space-based power", "power beaming", "wireless power transmission", "microwave power transmission")):
        synonym_line = (
            "- Relevant synonyms: space-based solar power, space based solar power, SBSP, space solar power, "
            "space-based solar, solar power satellite, orbital solar, space-based power, power beaming, "
            "wireless power transmission, microwave power transmission.\n"
        )
    return (
        "INPUT\n"
        f"- Topic: {topic.strip()}\n"
        f"- Section: {normalized_section.title()}\n"
        f"- Research date: {current_date}\n"
        f"- Location scope: {resolved_location_context.label if not resolved_location_context.is_global else 'Global'}\n"
        f"- Written trend title: {trend_heading.strip()}\n"
        f"- Written trend description: {trend_body.strip()}\n\n"
        "TASK\n"
        "- Extract recent factual examples that directly support the written trend or driver.\n\n"
        "Rules:\n"
        "- Use only the evidence below.\n"
        "- Extract only concrete named examples.\n"
        "- Each example must include a named entity, specific action, and date signal.\n"
        f"- Prefer examples from {current_year} and {previous_year}.\n"
        f"- Use {two_years_ago} or older examples only if no newer evidence is available and the example is clearly relevant.\n"
        "- Prioritise examples from official company, government, regulator, exchange, investor or recognised trade sources.\n"
        "- Do not use generic market statements as examples.\n"
        "- Do not use examples that are only loosely related to the trend.\n"
        "- Do not repeat the same company event across multiple examples.\n"
        "- If a source contains both a publication date and event date, prefer the event date.\n"
        "- If only the publication date is available, use that as the date signal and make this clear through the published_date field.\n"
        "- If no good recent example exists, return an empty examples list.\n\n"
        f"{synonym_line}"
        "QUALITY BAR\n"
        "Only extract an example if it answers all five questions:\n"
        "1. Who did something?\n"
        "2. What exactly happened?\n"
        "3. When did it happen?\n"
        "4. Where did it happen, if relevant?\n"
        "5. How does it evidence the trend?\n\n"
        "EVIDENCE\n"
        f"{_format_example_evidence_blocks(evidence_blocks)}\n\n"
        "Return strict JSON only."
    ).strip()


def build_example_search_query_user_prompt(
    *,
    topic: str,
    section: str,
    trend_heading: str,
    trend_body: str,
    location_context: Optional[LocationContext] = None,
) -> str:
    resolved_location_context = location_context or LocationContext()
    current_date = get_current_research_date()
    geo = resolved_location_context.value if not resolved_location_context.is_global else "Global"
    synonym_line = ""
    combined_trend_text = f"{trend_heading.strip()} {trend_body.strip()}".lower()
    if any(term in combined_trend_text for term in ("space-based solar power", "space based solar power", "sbsp", "space solar power", "space-based solar", "solar power satellite", "orbital solar", "space-based power", "power beaming", "wireless power transmission", "microwave power transmission")):
        synonym_line = (
            "- Treat these as equivalent if useful: space-based solar power, space based solar power, SBSP, space solar power, "
            "space-based solar, solar power satellite, orbital solar, space-based power, power beaming, wireless power transmission, microwave power transmission.\n"
        )
    return (
        "INPUT\n"
        f"- Topic: {topic.strip()}\n"
        f"- Section: {section.strip().title()}\n"
        f"- Research date: {current_date}\n"
        f"- Location: {geo}\n"
        f"- Trend title: {trend_heading.strip()}\n"
        f"- Trend description: {trend_body.strip()}\n\n"
        "TASK\n"
        "Generate search queries to find recent examples or facts that directly evidence this trend.\n\n"
        "Rules:\n"
        "- Generate 6 to 8 queries.\n"
        "- Each query must include the topic, location, trend-specific terms, and a recent-year signal.\n"
        "- Prioritise the current year and previous year.\n"
        "- Use source-seeking terms such as:\n"
        "  press release, announcement, partnership, launch, expansion, investment, acquisition, project, contract, deployment, funding, financing, approval, capacity, commercial operation, regulator, government.\n"
        "- Include at least:\n"
        "  1. one company announcement query,\n"
        "  2. one trade publication query,\n"
        "  3. one project or deployment query,\n"
        "  4. one investment / partnership / acquisition query,\n"
        "  5. one policy or regulatory query if the trend has a policy/regulatory angle.\n"
        "- Avoid generic queries like \"market trends\" or \"industry growth\".\n"
        "- Do not include unsupported company names unless present in the trend text.\n"
        "- Use exact phrases from the trend where useful, but simplify technical wording where needed.\n\n"
        f"{synonym_line}"
        "Return JSON in this shape:\n"
        "{\n"
        "  \"queries\": [\n"
        "    {\n"
        "      \"query\": \"search query text\",\n"
        "      \"purpose\": \"what type of evidence this query is trying to find\",\n"
        "      \"priority\": \"high | medium | fallback\"\n"
        "    }\n"
        "  ]\n"
        "}"
    ).strip()
