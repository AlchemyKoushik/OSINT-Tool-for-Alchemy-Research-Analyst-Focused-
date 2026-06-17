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
    "competitive_landscape": (
        "Identify the key players in the market, split them into major players and small / mid-sized / emerging "
        "players, and ground every company selection in recent evidence from the last 2 to 3 years."
    ),
}

SECTION_TITLES: Final[Dict[str, str]] = {
    "trends": "Industry Trends",
    "drivers": "Market Drivers",
    "competitive_landscape": "Competitive Landscape",
}


def get_prompt(section: str, max_items: int = 10) -> str:
    normalized_section = str(section or "").strip().lower()
    if normalized_section not in SECTION_TITLES:
        raise ValueError("Invalid section")

    if normalized_section == "competitive_landscape":
        return (
            "You are an analyst building the company-discovery stage for a Competitive Landscape OSINT workflow.\n\n"
            "Objective:\n"
            "- Identify and separate the market into Major Players and Small / Mid-sized / Emerging Players.\n"
            "- Focus company selection on the latest 2 to 3 years of evidence.\n"
            "- Return only real companies active in the requested industry and geography.\n"
            "- This stage is discovery only. Do not generate company profiles.\n\n"
            "Rules:\n"
            "- Use only the supplied evidence.\n"
            "- Build a broad candidate company pool before classification.\n"
            "- Exclude inactive companies, duplicate companies, and companies without meaningful industry participation.\n"
            "- Exclude companies that are not active in the requested geography.\n"
            "- Prefer companies with visible activity, expansion, launches, partnerships, funding, acquisitions, deployments, or other concrete signals from the last 2 to 3 years.\n"
            "- Look beyond market share reports and leading-company lists by considering local companies, regional companies, niche specialists, challenger companies, fast-growing companies, private companies, startups, trade-association member lists, event participants, and company-profile sources when the evidence supports them.\n"
            "- When evidence supports it, aim to surface roughly 5 to 10 major-player candidates and 5 to 15 emerging-player candidates before downstream research.\n"
            "- Keep company_name fixed to the company name only.\n"
            "- market_role must be exactly one concise label such as Market Leader, Global Leader, Regional Leader, Challenger, Emerging Player, Emerging Specialist, Niche Specialist, Technology Provider, Infrastructure Provider, or Local Champion.\n"
            "- Do not generate business_overview, key_company_facts, recent strategic developments, or competitive_positioning in this stage.\n"
            "- Every company must include source_ids tied to the evidence blocks.\n\n"
            "Output JSON:\n"
            "{\n"
            '  "major_players": [\n'
            "    {\n"
            '      "company_name": "Company name",\n'
            '      "market_role": "Market Leader",\n'
            '      "source_ids": [1, 2]\n'
            "    }\n"
            "  ],\n"
            '  "emerging_players": [\n'
            "    {\n"
            '      "company_name": "Company name",\n'
            '      "market_role": "Emerging Player",\n'
            '      "source_ids": [3, 4]\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            f"Final Rule: Return no more than {max(1, int(max_items or 1))} companies per group and return strict JSON only."
        )

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
                "evidence_scope": str(block.get("evidence_scope", "")).strip() or "company_level_evidence",
                "company_specific": bool(block.get("company_specific", False)),
                "source_quality_score": block.get("source_quality_score"),
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
    if normalized_section == "competitive_landscape":
        payload = (
            "INPUT\n"
            f"- Topic: {topic.strip()}\n"
            "- Section: Competitive Landscape\n"
            f"- Research date: {get_current_research_date()}\n"
            f"{_format_location_line(resolved_location_context)}\n\n"
            "WORKFLOW\n"
            "- Build two groups only: major_players and emerging_players.\n"
            "- Treat emerging_players as the bucket for small, mid-sized, local, regional, niche, challenger, specialist, and fast-growing companies.\n"
            "- Base company selection on evidence from the last 2 to 3 years whenever possible.\n"
            "- Prefer companies with recent commercial activity, launches, expansion, partnerships, investments, acquisitions, deployments, contracts, approvals, or visible market participation.\n"
            "- Exclude inactive companies, duplicate companies, and companies without clear geography fit.\n"
            "- Keep the output company-specific. Do not produce trend summaries.\n"
            "- This stage is company discovery only. Do not generate business overviews, key facts, recent developments, or competitive positioning yet.\n"
            "- Every company must include source_ids tied directly to the evidence blocks.\n"
            "- When the evidence supports it, try to surface roughly 5 to 10 major-player candidates and 5 to 15 emerging-player candidates before later company research.\n"
            f"- Return up to {max(1, int(max_items or 1))} companies in each group when supported by evidence.\n\n"
            "SOURCE_METADATA\n"
            f"{_format_source_metadata(source_scores, artifact_counts)}\n\n"
            "EVIDENCE\n"
            f"{_format_evidence_blocks(evidence_blocks)}"
        )
        return payload.strip()

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
    if normalized_section == "competitive_landscape":
        return (
            "INPUT\n"
            f"- Topic: {topic.strip()}\n"
            f"- Section: Competitive Landscape\n"
            f"- Research date: {current_date}\n"
            f"- Location scope: {resolved_location_context.label if not resolved_location_context.is_global else 'Global'}\n"
            f"- Company name: {trend_heading.strip()}\n"
            f"- Company overview: {trend_body.strip()}\n\n"
            "TASK\n"
            "- Extract only recent developments for this specific company from the last 2 to 3 years.\n\n"
            "Rules:\n"
            "- Use only the evidence below.\n"
            "- Extract only developments directly tied to the named company.\n"
            "- Prioritise product launches, service launches, partnerships, contracts, funding, acquisitions, expansions, deployments, approvals, and major strategic moves.\n"
            "- Prefer examples from the current year, previous year, and two years ago.\n"
            "- Every example must have a clear date signal within roughly the last 36 months from the research date.\n"
            "- If the evidence is older than 3 years, generic, or not clearly tied to the company, exclude it.\n"
            "- Return an empty examples list if no valid recent developments exist.\n\n"
            "EVIDENCE\n"
            f"{_format_example_evidence_blocks(evidence_blocks)}\n\n"
            "Return strict JSON only."
        ).strip()
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


def build_company_profile_extraction_payload(
    *,
    topic: str,
    company_name: str,
    existing_overview: str,
    location_context: Optional[LocationContext] = None,
    evidence_blocks: Optional[List[Dict[str, Any]]] = None,
) -> str:
    resolved_location_context = location_context or LocationContext()
    current_date = get_current_research_date()
    return (
        "INPUT\n"
        f"- Topic: {topic.strip()}\n"
        f"- Section: Competitive Landscape\n"
        f"- Research date: {current_date}\n"
        f"- Location scope: {resolved_location_context.label if not resolved_location_context.is_global else 'Global'}\n"
        f"- Company name: {company_name.strip()}\n"
        f"- Existing company overview draft: {existing_overview.strip()}\n\n"
        "TASK\n"
        "- Build a concise company profile for the named company using only the evidence below.\n\n"
        "Rules:\n"
        "- Keep the company name fixed to the named company. Do not rename it.\n"
        "- Treat the existing company overview draft only as a soft disambiguation hint. Ignore it when the evidence does not support it.\n"
        "- Before writing the profile, answer these questions from the evidence: why is this company included, what makes it relevant to this market, and what evidence shows activity in this market during the last 24 to 36 months.\n"
        "- If the evidence cannot answer those questions credibly, return empty profile fields rather than guessing.\n"
        "- Write business_overview as a concise 2 to 3 sentence description of the company business, operating model, customer or end-market focus, and market role.\n"
        "- Do not write generic market size, CAGR, forecast, chapter, or report-summary text in business_overview.\n"
        "- If the evidence does not support business_overview, return an empty string.\n"
        "- Generate 3 to 5 key_company_facts for the company.\n"
        "- Focus only on company-level facts that explain the company's scale, market relevance, ownership, portfolio, geographic footprint, business model, or strategic positioning.\n"
        "- Key Company Facts should capture company-level, investor-relevant facts, not project descriptions or marketing claims.\n"
        "- Prioritise facts in this order: scale metrics such as revenue, assets, customers, stores, users, subscribers, locations, product breadth, or other company-level footprint evidence; geographic footprint and core operating markets; market position or ranking, only when supported by evidence; ownership structure / parent company / strategic shareholders; business model and revenue model; strategic differentiators such as distribution reach, technology capability, partnerships, platform scale, or long-term customer relationships.\n"
        "- Each fact must be company-level rather than single-project-level, current or recently updated, quantifiable wherever possible, verifiable from the evidence, a maximum of one sentence, and useful for understanding the company's scale, positioning, or relevance in the market.\n"
        "- Good facts include revenue scale, asset base, customer base, store or location count, subscriber or user count, distribution reach, parent company or ownership structure where relevant, country or regional footprint, market position supported by evidence, product or service mix, and commercial model.\n"
        "- Reject individual project construction updates unless the project materially changes the company's scale or market position.\n"
        "- Reject number of panels, turbines, modules, or equipment-level details.\n"
        "- Reject project investment values unless strategically material.\n"
        "- Reject expected generation output of a single asset.\n"
        "- Reject outdated phrases such as under construction, expected to complete, began construction, or due by.\n"
        "- Reject vague claims such as leading player, strong presence, or innovative company unless backed by measurable evidence.\n"
        "- Reject founding year, headquarters, or company history unless directly relevant to market positioning.\n"
        "- Reject facts that duplicate the business_overview.\n"
        "- Return only the fact text, not labels like Fact 1.\n"
        "- If the evidence does not support at least 3 strong company-level facts, return fewer facts rather than filling with weak information.\n"
        "- Do not generate recent_developments in this call. A separate extraction step will handle recent developments.\n"
        '- Always return an empty recent_developments list in this response.\n'
        "- competitive_positioning should be one concise insight-driven sentence explaining what the company's actions indicate strategically in this market.\n"
        "- Focus on implications such as scaling project pipeline, moving into storage, entering new customer segments, geographic expansion, defending position, moving up the value chain, or strengthening technology capabilities.\n"
        "- Do not write generic lines like holds a leading position in the market unless the sentence explains the strategic implication using evidence.\n"
        "- Return an empty competitive_positioning string if the evidence does not support it.\n"
        "- source_ids must reference only the numbered evidence blocks that directly support the profile.\n"
        "- Prefer official company, investor, annual report, regulator, exchange, government, project database, reputable industry publication, and reputable news sources when available.\n"
        "- Avoid relying primarily on generic news articles, old project announcements, duplicated syndicated content, pages focused only on one project, lead-generation websites, contact directories, generic Top X articles, SEO-driven blogs, or unsourced market reports.\n"
        "- Use company-level evidence first. Project-level evidence should only be used when it changes the company's overall scale, market position, or strategic relevance.\n"
        "- Each company should ideally be supported by 1 to 2 company-specific sources.\n\n"
        "EVIDENCE\n"
        f"{_format_example_evidence_blocks(evidence_blocks)}\n\n"
        "Return strict JSON only in this shape:\n"
        "{\n"
        '  "profile": {\n'
        '    "business_overview": "2 to 3 sentence company overview or empty string",\n'
        '    "key_company_facts": ["fact 1", "fact 2"],\n'
        '    "competitive_positioning": "one short concluding line or empty string",\n'
        '    "recent_developments": [\n'
        "      {\n"
        '        "company": "company name",\n'
        '        "event": "specific event",\n'
        '        "text": "full recent development sentence",\n'
        '        "event_date": "YYYY-MM-DD or empty",\n'
        '        "published_date": "YYYY-MM-DD or empty",\n'
        '        "location": "location or empty",\n'
        '        "example_type": "partnership | launch | expansion | investment | M&A | restructuring | regulatory | contract | other",\n'
        '        "confidence": "high | medium | low",\n'
        '        "trend_fit_reason": "why this matters strategically",\n'
        '        "source_quality": "Tier 1 | Tier 2 | Tier 3",\n'
        '        "validation_score": 0,\n'
        '        "year": "YYYY-MM-DD or YYYY",\n'
        '        "source_ids": [1]\n'
        "      }\n"
        "    ],\n"
        '    "source_ids": [1, 2]\n'
        "  }\n"
        "}"
    ).strip()


def build_recent_company_developments_payload(
    *,
    topic: str,
    company_name: str,
    location_context: Optional[LocationContext] = None,
    evidence_blocks: Optional[List[Dict[str, Any]]] = None,
) -> str:
    resolved_location_context = location_context or LocationContext()
    current_date = get_current_research_date()
    return (
        "# COMPETITIVE LANDSCAPE | RECENT COMPANY DEVELOPMENTS\n\n"
        "## Objective\n"
        "Identify the most important recent developments for a given company operating within a specified industry.\n\n"
        "The output should focus only on developments that are strategically significant and relevant to:\n"
        "- Investors\n"
        "- Competitors\n"
        "- Customers\n"
        "- Industry participants\n\n"
        "---\n\n"
        "## Input Variables\n\n"
        f"- Company Name: {company_name.strip()}\n"
        f"- Industry Name: {topic.strip()}\n"
        f"- Research date: {current_date}\n"
        f"- Geography: {resolved_location_context.label if not resolved_location_context.is_global else 'Global'}\n\n"
        "---\n\n"
        "## Time Period\n\n"
        "Analyze only developments announced within:\n"
        "- Current calendar year\n"
        "- Previous calendar year\n"
        "- Two calendar years prior\n\n"
        "Total Coverage:\n"
        "- Last 3 calendar years only\n\n"
        "Ignore anything older.\n\n"
        "---\n\n"
        "## Selection Criteria\n\n"
        "Include developments that satisfy one or more of the following:\n"
        "- Acquisitions\n"
        "- Mergers\n"
        "- Divestments\n"
        "- Strategic investments\n"
        "- Major project awards\n"
        "- Contract wins\n"
        "- Commercial agreements\n"
        "- Funding rounds\n"
        "- Debt raises\n"
        "- Capital investments\n"
        "- Entry into new countries or regions\n"
        "- Expansion into new customer segments\n"
        "- Major product launches\n"
        "- Major technology launches\n"
        "- Platform launches\n"
        "- Large-scale project announcements\n"
        "- Project commissioning\n"
        "- Operational milestones\n"
        "- Strategic partnerships\n"
        "- Joint ventures\n"
        "- Alliances\n"
        "- Regulatory approvals\n"
        "- Licences\n"
        "- Permits materially impacting growth\n"
        "- Manufacturing, infrastructure, or operational expansion\n"
        "- Major restructurings\n"
        "- Significant leadership changes\n"
        "- Business transformations\n\n"
        "---\n\n"
        "## Exclusion Criteria\n\n"
        "Do NOT include:\n"
        "- General company descriptions\n"
        "- Marketing announcements\n"
        "- Event participation\n"
        "- Conference attendance\n"
        "- Awards\n"
        "- Rankings\n"
        "- Certifications\n"
        "- Industry recognitions\n"
        "- Minor product updates\n"
        "- Routine business activities\n"
        "- Media speculation\n"
        "- Opinion articles\n"
        "- Duplicate announcements\n"
        "- Developments older than 3 years\n"
        "- Developments lacking verifiable sources\n\n"
        "---\n\n"
        "## Source Requirements\n\n"
        "Use only:\n"
        "- Company press releases\n"
        "- Regulatory filings\n"
        "- Investor presentations\n"
        "- Stock exchange announcements\n"
        "- Government announcements\n"
        "- Reputable industry publications\n"
        "- Tier-1 business media\n\n"
        "Do NOT use:\n"
        "- Blogs\n"
        "- Aggregator websites\n"
        "- AI-generated content\n"
        "- User-generated content\n"
        "- Forums\n"
        "- Social media posts\n\n"
        "Exception:\n"
        "- Social media posts may be used only if they directly link to an official announcement.\n\n"
        "---\n\n"
        "## Verification Requirements\n\n"
        "Each development must:\n"
        "- Be supported by at least one verifiable source\n"
        "- Include the exact announcement date or month/year\n"
        "- Be factually stated\n"
        "- Contain no assumptions or interpretations\n"
        "- Be independently corroborated when possible\n"
        "- Clearly explain why the development is strategically significant\n\n"
        "---\n\n"
        "## Output Requirements\n\n"
        "### Maximum Results\n"
        "- Return a maximum of 5 developments\n\n"
        "### Prioritization Logic\n"
        "- Rank by strategic importance\n"
        "- Do NOT rank by recency alone\n\n"
        "### If Fewer Than 5 Exist\n"
        "- Return only available developments\n\n"
        "### If None Exist\n"
        '- Return exactly an empty "examples" list.\n\n'
        "---\n\n"
        "## Quality Control Checklist\n\n"
        "Verify:\n"
        "- All developments occurred within the last 3 years\n"
        "- No duplicate developments are included\n"
        "- No vague language is used\n"
        "- No assumptions\n"
        "- No forecasts\n"
        "- No analyst opinions\n"
        "- Every development has a valid source\n"
        "- Every development is material to competitive positioning\n"
        "- Only company-specific developments are included\n"
        "- No general industry trends are included\n\n"
        "Avoid phrases such as:\n"
        '- "continued expansion"\n'
        '- "strengthened position"\n'
        '- "focused on growth"\n\n'
        "Before finalizing:\n"
        "1. Search separately for acquisitions, partnerships, funding activities, project awards, major contracts, market expansions, technology launches, and operational milestones.\n"
        "2. Do NOT stop after finding five developments.\n"
        "3. First identify all material developments from the last three years.\n"
        "4. Rank all identified developments by strategic importance.\n"
        "5. Return only the top 5 most material developments.\n\n"
        "## Evidence\n"
        f"{_format_example_evidence_blocks(evidence_blocks)}\n\n"
        "Return strict JSON only in this shape:\n"
        "{\n"
        '  "examples": [\n'
        "    {\n"
        f'      "company": "{company_name.strip()}",\n'
        '      "event": "specific development title",\n'
        '      "text": "factual development description",\n'
        '      "event_date": "YYYY-MM-DD or YYYY-MM or empty",\n'
        '      "published_date": "YYYY-MM-DD or YYYY-MM or empty",\n'
        '      "location": "location or empty",\n'
        '      "example_type": "acquisition | merger | divestment | investment | project_award | contract | partnership | expansion | launch | regulatory | capacity_expansion | restructuring | leadership | other",\n'
        '      "confidence": "high | medium | low",\n'
        '      "trend_fit_reason": "why this development is strategically significant",\n'
        '      "source_quality": "Tier 1 | Tier 2 | Tier 3",\n'
        '      "validation_score": 0,\n'
        '      "year": "YYYY-MM-DD or YYYY",\n'
        '      "source_ids": [1]\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Return no commentary outside JSON."
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
    if section.strip().lower() == "competitive_landscape":
        return (
            "INPUT\n"
            f"- Topic: {topic.strip()}\n"
            f"- Section: Competitive Landscape\n"
            f"- Research date: {current_date}\n"
            f"- Location: {geo}\n"
            f"- Company: {trend_heading.strip()}\n"
            f"- Company overview: {trend_body.strip()}\n\n"
            "TASK\n"
            "Generate search queries to gather high-quality company evidence for this company in the specified market and geography.\n\n"
            "Rules:\n"
            "- Generate 5 to 8 queries.\n"
            "- Every query must be centered on the named company.\n"
            "- Prioritise company overview, portfolio, operating assets, project pipeline, customer exposure, contracts, PPAs, official company publications, investor materials, and company-specific market activity.\n"
            "- Prefer broader company-evidence queries before narrower event-specific queries.\n"
            "- Do not generate queries whose main purpose is recent developments, competitor positioning, or generic market trend summaries.\n"
            "- Avoid brittle year-scope strings such as OR OR combinations.\n"
            "- Avoid unsupported competitor names.\n\n"
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
