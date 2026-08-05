from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Sequence, Tuple

from models.response_models import normalize_analyze_response_payload


def _slugify_filename_part(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized or fallback


def _safe_text(value: Any, fallback: str = "") -> str:
    normalized = str(value or "").strip()
    return normalized or fallback


def _escape(value: Any, fallback: str = "") -> str:
    return html.escape(_safe_text(value, fallback))


def _format_multiline_html(value: Any, fallback: str = "") -> str:
    normalized = _safe_text(value, fallback)
    if not normalized:
        return ""
    return "<br>".join(html.escape(line) for line in normalized.splitlines())


def _build_filename(result: Dict[str, Any], meta: Dict[str, Any]) -> str:
    scope = _slugify_filename_part(meta.get("location", {}).get("label", "global"), "global")
    topic = _slugify_filename_part(meta.get("topic", "") or result.get("title", ""), "industry-brief")
    section = _slugify_filename_part(result.get("section", "trends"), "trends")
    prepared = _slugify_filename_part(meta.get("prepared", "brief"), "brief")
    return f"{topic}-{section}-{scope}-{prepared}.html"


def _resolve_ies_scope(request: Dict[str, Any], summary: Dict[str, Any]) -> Tuple[str, str]:
    filter_type = _safe_text(request.get("filter_type") or summary.get("filter_type"), "").lower()
    filter_value = _safe_text(
        request.get("filter_value")
        or summary.get("filter_value")
        or request.get("country")
        or summary.get("country"),
        "",
    )

    if filter_type == "global":
        return "Scope", "Global"
    if filter_type == "region":
        return "Region", filter_value or "N/A"
    if filter_type == "country":
        return "Country", filter_value or "N/A"
    if filter_value:
        return "Country", filter_value
    return "Scope", "Global"


def _count_sources(items: Sequence[Dict[str, Any]]) -> int:
    total = 0
    for item in items:
        total += len(item.get("sources", []) or [])
    return total


def _count_competitive_landscape_sources(result: Dict[str, Any]) -> int:
    return _count_sources([*list(result.get("major_players", []) or []), *list(result.get("emerging_players", []) or [])])


def _render_ies_metric_cards(summary: Dict[str, Any], metadata: Dict[str, Any], request: Dict[str, Any], company_count: int) -> str:
    scope_label, scope_value = _resolve_ies_scope(request, summary)
    cards = [
        ("Industry", _escape(request.get("industry") or summary.get("industry") or "N/A")),
        (scope_label, _escape(scope_value)),
        ("Top N", _escape(request.get("top_n") or summary.get("requested_top_n") or "N/A")),
        ("Companies", html.escape(str(summary.get("companies_returned") or company_count or 0))),
        ("Enriched", html.escape(str(summary.get("companies_enriched") or metadata.get("total_companies_successfully_enriched") or 0))),
        ("Median Revenue Growth", _escape(_format_ies_percent(summary.get("median_revenue_growth")))),
        ("Median Operating Margin", _escape(_format_ies_percent(summary.get("median_operating_margin")))),
        ("Median EBITDA Margin", _escape(_format_ies_percent(summary.get("median_ebitda_margin")))),
        ("Median EV / Revenue", _escape(_format_ies_ratio(summary.get("median_ev_to_revenue")))),
        ("Median EV / EBITDA", _escape(_format_ies_ratio(summary.get("median_ev_to_ebitda")))),
        ("Median Forward P/E", _escape(_format_ies_ratio(summary.get("median_forward_pe")))),
        ("EPS Beat Rate", _escape(_format_ies_percent(summary.get("eps_beat_rate")))),
        ("5-Day Reaction", _escape(_format_ies_percent(summary.get("median_five_day_price_reaction")))),
    ]
    return "".join(
        f"<div class=\"summary-card\"><span>{label}</span><strong>{value}</strong></div>"
        for label, value in cards
    )


def _render_ies_scatter_chart(scatter_chart: Dict[str, Any]) -> str:
    points = list(scatter_chart.get("data", []) or [])
    if not points:
        return (
            "<div class=\"memo-empty-state\">"
            "No scatter chart data was returned for this report."
            "</div>"
        )

    rows = []
    for index, point in enumerate(points, start=1):
        ticker = _escape(point.get("ticker"), f"Point {index}")
        company_name = _escape(point.get("company_name"), ticker)
        revenue_growth = _escape(_format_ies_percent(point.get("revenue_growth_lq_yoy")))
        operating_margin = _escape(_format_ies_percent(point.get("operating_margin")))
        bubble_size = _escape(_format_ies_compact_number(point.get("bubble_size")))
        outlier = "Outlier" if bool(point.get("is_outlier")) else "In range"
        rows.append(
            "<div class=\"ies-chart-row\">"
            f"<div class=\"ies-chart-row__ticker\">{ticker}</div>"
            f"<div class=\"ies-chart-row__company\">{company_name}</div>"
            f"<div class=\"ies-chart-row__metric\">{revenue_growth}</div>"
            f"<div class=\"ies-chart-row__metric\">{operating_margin}</div>"
            f"<div class=\"ies-chart-row__metric\">{bubble_size}</div>"
            f"<div class=\"ies-chart-row__metric\">{outlier}</div>"
            "</div>"
        )

    return (
        "<div class=\"ies-chart\">"
        "<div class=\"ies-chart__header\">"
        f"<h4>{html.escape(_safe_text(scatter_chart.get('title'), 'Revenue Growth vs Operating Margin'))}</h4>"
        f"<p>{html.escape(_safe_text(scatter_chart.get('bubble_size_label'), 'Revenue TTM'))} bubbles</p>"
        "</div>"
        "<div class=\"ies-chart__legend\">"
        f"<span>{html.escape(_safe_text(scatter_chart.get('x_label'), 'Revenue Growth (LQ YoY)'))}</span>"
        f"<span>{html.escape(_safe_text(scatter_chart.get('y_label'), 'Operating Margin'))}</span>"
        "</div>"
        "<div class=\"ies-chart-table\">"
        "<div class=\"ies-chart-row ies-chart-row--header\">"
        "<div>Ticker</div><div>Company</div><div>Growth</div><div>Margin</div><div>Bubble</div><div>Status</div>"
        "</div>"
        f"{''.join(rows)}"
        "</div>"
        "</div>"
    )


def _render_ies_company_card(company: Dict[str, Any], index: int) -> str:
    ticker = _escape(company.get("ticker"), "N/A")
    company_name = _escape(company.get("company_name"), "Company")
    exchange = _escape(company.get("exchange"))
    country = _escape(company.get("country"))
    status = _escape(company.get("enrichment_status"), "unknown")
    outlier = bool(company.get("is_outlier"))
    warnings = list(company.get("validation_warnings", []) or [])
    outlier_metrics = list(company.get("outlier_metrics", []) or [])
    metric_sources = company.get("metric_sources", {}) if isinstance(company.get("metric_sources", {}), dict) else {}
    source_count = len(metric_sources)
    card_classes = "memo-item"
    if outlier:
        card_classes += " memo-item--outlier"

    badges = []
    if status:
        badges.append(f"<span class=\"memo-badge memo-badge--status\">{status}</span>")
    if outlier:
        badges.append("<span class=\"memo-badge memo-badge--outlier\">Outlier</span>")

    extra_badges = []
    if source_count:
        extra_badges.append(f"<span class=\"memo-pill\">Sources {source_count}</span>")
    if outlier_metrics:
        extra_badges.append(f"<span class=\"memo-pill memo-pill--warn\">{html.escape(', '.join(outlier_metrics))}</span>")
    if warnings:
        extra_badges.append(f"<span class=\"memo-pill memo-pill--error\">{html.escape(warnings[0])}</span>")

    error_block = ""
    enrichment_error = _safe_text(company.get("enrichment_error"))
    if enrichment_error:
        error_block = f"<p class=\"memo-error\">{html.escape(enrichment_error)}</p>"

    return (
        f"<article class=\"{card_classes}\">"
        "<div class=\"memo-item__header\">"
        f"<span class=\"memo-item__index\">{index}</span>"
        "<div>"
        f"<div class=\"memo-item__badge\">Company {index}</div>"
        f"<h3>{company_name}</h3>"
        f"<p class=\"memo-item__meta\">{ticker}{f' | {exchange}' if exchange else ''}{f' | {country}' if country else ''}</p>"
        "</div>"
        f"<div class=\"memo-item__badges\">{''.join(badges)}</div>"
        "</div>"
        "<div class=\"ies-company-grid\">"
        f"<div class=\"summary-card\"><span>Revenue TTM</span><strong>{_escape(_format_ies_compact_number(company.get('revenue_ttm')))}</strong></div>"
        f"<div class=\"summary-card\"><span>Market Cap</span><strong>{_escape(_format_ies_compact_number(company.get('market_cap')))}</strong></div>"
        f"<div class=\"summary-card\"><span>EV / Revenue</span><strong>{_escape(_format_ies_ratio(company.get('ev_to_revenue_ttm')))}</strong></div>"
        f"<div class=\"summary-card\"><span>EV / EBITDA</span><strong>{_escape(_format_ies_ratio(company.get('ev_to_ebitda_ttm')))}</strong></div>"
        f"<div class=\"summary-card\"><span>Operating Margin</span><strong>{_escape(_format_ies_percent(company.get('operating_margin')))}</strong></div>"
        f"<div class=\"summary-card\"><span>EBITDA Margin</span><strong>{_escape(_format_ies_percent(company.get('ebitda_margin')))}</strong></div>"
        f"<div class=\"summary-card\"><span>Forward P/E</span><strong>{_escape(_format_ies_ratio(company.get('forward_pe')))}</strong></div>"
        f"<div class=\"summary-card\"><span>EPS Surprise</span><strong>{_escape(_format_ies_percent(company.get('eps_surprise')))}</strong></div>"
        "</div>"
        f"<div class=\"memo-pill-row\">{''.join(extra_badges)}</div>"
        f"{error_block}"
        "</article>"
    )


def _render_ies_section(result: Dict[str, Any], meta: Dict[str, Any], *, title_override: str | None = None) -> str:
    request = dict(result.get("request", {}) or {})
    summary = dict(result.get("summary", {}) or {})
    metadata = dict(result.get("metadata", {}) or {})
    chart = dict(result.get("scatter_chart", {}) or {})
    companies = list(result.get("companies", []) or [])
    title = _escape(title_override or result.get("title"), "Industry Earnings Snapshot")
    scope = _escape(meta.get("location", {}).get("label"), "Country")
    top_n = _escape(request.get("top_n") or summary.get("requested_top_n") or len(companies) or "N/A")
    scope_label, scope_value = _resolve_ies_scope(request, summary)
    company_cards = "".join(_render_ies_company_card(company, index) for index, company in enumerate(companies, start=1))
    company_cards_html = company_cards or '<div class="memo-empty-state">No companies were returned for this report.</div>'
    note = _safe_text(metadata.get("note"))
    note_html = f"<div class=\"memo-note\">{html.escape(note)}</div>" if note else ""

    return (
        "<section class=\"memo-section memo-section--ies\">"
        "<div class=\"memo-section__hero\">"
        "<div>"
        "<div class=\"memo-eyebrow\">Final Brief</div>"
        f"<h1>{title}</h1>"
        f"<p class=\"memo-topic\">{html.escape(_safe_text(request.get('industry') or summary.get('industry'), 'Industry'))} | {html.escape(scope_label)}: {html.escape(scope_value)} | Top {top_n}</p>"
        "<p class=\"memo-description\">"
        "A geography-scoped earnings snapshot with summary metrics, a revenue-growth vs operating-margin chart, and memo-ready company rows."
        "</p>"
        "</div>"
        f"<div class=\"memo-scope\">{scope} | {title}</div>"
        "</div>"
        "<div class=\"memo-meta-panel\">"
        f"<div class=\"memo-summary-grid\">{_render_ies_metric_cards(summary, metadata, request, len(companies))}</div>"
        "</div>"
        f"{note_html}"
        "<div class=\"editorial-rule\"></div>"
        "<div class=\"ies-chart-shell\">"
        f"{_render_ies_scatter_chart(chart)}"
        "</div>"
        "<div class=\"editorial-rule\"></div>"
        "<div class=\"memo-items\">"
        "<div class=\"competitive-group__header\"><h2>Company Memo</h2><span>"
        f"{len(companies)}"
        "</span></div>"
        f"{company_cards_html}"
        "</div>"
        "</section>"
    )


def _normalize_export_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    fallback_section = _safe_text(payload.get("section"), "trends").lower() or "trends"
    return normalize_analyze_response_payload(payload, fallback_section=fallback_section)


def _is_ies_report_payload(payload: Dict[str, Any]) -> bool:
    return bool(
        isinstance(payload, dict)
        and isinstance(payload.get("summary"), dict)
        and isinstance(payload.get("scatter_chart"), dict)
        and isinstance(payload.get("companies"), list)
    )


def _format_ies_percent(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "N/A"
    return f"{numeric:.1f}%"


def _format_ies_ratio(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "N/A"
    return f"{numeric:.1f}x"


def _format_ies_compact_number(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "N/A"
    absolute = abs(numeric)
    if absolute >= 1_000_000_000_000:
        return f"{numeric / 1_000_000_000_000:.1f}T"
    if absolute >= 1_000_000_000:
        return f"{numeric / 1_000_000_000:.1f}B"
    if absolute >= 1_000_000:
        return f"{numeric / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"{numeric / 1_000:.1f}K"
    return f"{numeric:.1f}"


def _render_source_link(source: Dict[str, Any], index: int) -> str:
    title = _escape(source.get("title"), f"Source {index}")
    domain = _escape(source.get("domain"))
    date = _escape(source.get("date"))
    url = _safe_text(source.get("url"))

    meta_parts = [part for part in (domain, date) if part]
    meta_html = f"<div class=\"source-meta\">{' | '.join(meta_parts)}</div>" if meta_parts else ""

    if url:
        return (
            "<li class=\"source-item\">"
            f"<a href=\"{html.escape(url, quote=True)}\" target=\"_blank\" rel=\"noopener noreferrer\">{title}</a>"
            f"{meta_html}"
            "</li>"
        )

    return f"<li class=\"source-item\"><span>{title}</span>{meta_html}</li>"


def _render_examples(examples: Sequence[Dict[str, Any]]) -> str:
    if not examples:
        return ""

    items = []
    for example in examples[:5]:
        text = _escape(example.get("text"))
        if not text:
            continue
        year = _escape(example.get("year") or example.get("event_date") or example.get("published_date"))
        why_it_matters = _escape(example.get("why_it_matters"))
        suffix = f" <span class=\"example-year\">({year})</span>" if year else ""
        why_html = f"<div class=\"source-meta\">{why_it_matters}</div>" if why_it_matters else ""
        items.append(f"<li>{text}{suffix}{why_html}</li>")

    if not items:
        return ""

    return (
        "<section class=\"item-subsection\">"
        "<h4>Examples</h4>"
        f"<ul class=\"example-list\">{''.join(items)}</ul>"
        "</section>"
    )


def _render_source_list(sources: Sequence[Dict[str, Any]]) -> str:
    if not sources:
        return ""

    items = [_render_source_link(source, index) for index, source in enumerate(sources[:5], start=1)]
    return f"<ul class=\"source-list\">{''.join(items)}</ul>"


def _render_sources_disclosure(sources: Sequence[Dict[str, Any]]) -> str:
    if not sources:
        return ""
    return (
        "<details class=\"disclosure disclosure--sources\">"
        f"<summary>Sources ({len(list(sources[:5]))})</summary>"
        f"<div class=\"disclosure__body\">{_render_source_list(sources)}</div>"
        "</details>"
    )


def _render_examples_sources_disclosure(examples: Sequence[Dict[str, Any]], sources: Sequence[Dict[str, Any]]) -> str:
    example_count = len([example for example in examples[:5] if _safe_text(example.get('text'))])
    source_count = len(list(sources[:5]))
    if not example_count and not source_count:
        return ""

    examples_html = _render_examples(examples)
    if examples_html:
        examples_html = examples_html.replace("<section class=\"item-subsection\">", "<section class=\"disclosure-block\">", 1)
        examples_html = examples_html.replace("</section>", "</section>", 1)

    sources_html = ""
    if source_count:
        sources_html = (
            "<section class=\"disclosure-block\">"
            "<h4>Sources</h4>"
            f"{_render_source_list(sources)}"
            "</section>"
        )

    summary_suffix = ""
    if example_count or source_count:
        summary_suffix = f' <span class="summary-separator">|</span> Examples ({example_count})'

    return (
        "<details class=\"disclosure\">"
        f"<summary>Sources ({source_count})"
        f"{summary_suffix}"
        "</summary>"
        f"<div class=\"disclosure__body\">{examples_html}{sources_html}</div>"
        "</details>"
    )


def _render_fact_list(facts: Sequence[str]) -> str:
    normalized_facts = [_escape(fact) for fact in list(facts or []) if _safe_text(fact)]
    if not normalized_facts:
        return ""
    return f"<ul class=\"example-list\">{''.join(f'<li>{fact}</li>' for fact in normalized_facts[:5])}</ul>"


def _render_competitive_landscape_item(item: Dict[str, Any], index: int) -> str:
    heading = _escape(item.get("heading"), "Insight")
    body = _format_multiline_html(item.get("body"))
    market_role = _escape(item.get("market_role"))
    examples = item.get("recent_strategic_developments") or item.get("examples", []) or []
    sources = item.get("sources", []) or []
    positioning_text = _format_multiline_html(item.get("competitive_positioning"))
    facts_html = _render_fact_list(item.get("key_company_facts", []) or [])
    developments_html = _render_examples(examples).replace("<h4>Examples</h4>", "<h4>Recent Strategic Developments</h4>")
    market_role_html = f'<div class="memo-item__badge">{market_role}</div>' if market_role else ""
    facts_section_html = f'<section class="item-subsection"><h4>Key Company Facts</h4>{facts_html}</section>' if facts_html else ""
    positioning_section_html = (
        f'<section class="item-subsection"><h4>Competitive Positioning / Implication</h4><p class="memo-item__body">{positioning_text}</p></section>'
        if positioning_text
        else ""
    )
    return (
        "<article class=\"memo-item memo-item--competitive\">"
        "<div class=\"memo-item__header\">"
        f"<span class=\"memo-item__index\">{index}</span>"
        "<div>"
        f"{market_role_html}"
        f"<h3>{heading}</h3>"
        "</div>"
        "</div>"
        "<section class=\"item-subsection item-subsection--first\">"
        "<h4>Business Overview</h4>"
        f"<p class=\"memo-item__body\">{body}</p>"
        "</section>"
        f"{facts_section_html}"
        f"{developments_html}"
        f"{positioning_section_html}"
        f"{_render_sources_disclosure(sources)}"
        "</article>"
    )


def _render_competitive_landscape_group(title: str, items: Sequence[Dict[str, Any]]) -> str:
    normalized_items = list(items or [])
    items_html = "".join(
        _render_competitive_landscape_item(item, index) for index, item in enumerate(normalized_items, start=1)
    )
    group_body_html = items_html or '<div class="memo-empty-state">No strong company profiles found.</div>'
    return (
        "<section class=\"competitive-group\">"
        f"<div class=\"competitive-group__header\"><h2>{html.escape(title)}</h2><span>{len(normalized_items)}</span></div>"
        f"<div class=\"memo-items\">{group_body_html}</div>"
        "</section>"
    )


def _render_trend_or_driver_item(item: Dict[str, Any], index: int, section: str) -> str:
    heading = _escape(item.get("heading"), "Insight")
    body = _format_multiline_html(item.get("body"))
    badge = "Driver" if section == "drivers" else "Trend"
    examples = item.get("examples", []) or []
    sources = item.get("sources", []) or []
    return (
        "<article class=\"memo-item\">"
        "<div class=\"memo-item__header\">"
        f"<span class=\"memo-item__index\">{index}</span>"
        "<div>"
        f"<div class=\"memo-item__badge\">{html.escape(badge)}</div>"
        f"<h3>{heading}</h3>"
        "</div>"
        "</div>"
        f"<p class=\"memo-item__body\">{body}</p>"
        f"{_render_examples_sources_disclosure(examples, sources)}"
        "</article>"
    )


def _render_item(item: Dict[str, Any], index: int, section: str) -> str:
    if section == "competitive_landscape":
        return _render_competitive_landscape_item(item, index)
    return _render_trend_or_driver_item(item, index, section)


def _render_summary_cards(meta: Dict[str, Any], result: Dict[str, Any]) -> str:
    location_label = _escape(meta.get("location", {}).get("label"), "Global")
    prepared = _escape(meta.get("prepared"), "Prepared now")
    section_title = _escape(result.get("title"), "Industry Trends")
    source_count = html.escape(
        str(
            _count_competitive_landscape_sources(result)
            if _safe_text(result.get("section"), "trends") == "competitive_landscape"
            else _count_sources(result.get("items", []) or [])
        )
    )

    cards = [
        ("Section", section_title),
        ("Scope", location_label),
        ("Sources", source_count),
        ("Prepared", prepared),
    ]
    cards_html = "".join(
        f"<div class=\"summary-card\"><span>{label}</span><strong>{value}</strong></div>"
        for label, value in cards
    )
    return f"<div class=\"memo-summary-grid\">{cards_html}</div>"


def _render_section(result: Dict[str, Any], meta: Dict[str, Any], *, title_override: str | None = None) -> str:
    title = _escape(title_override or result.get("title"), "Industry Trends")
    location_label = _escape(meta.get("location", {}).get("label"), "Global")
    topic = _escape(meta.get("topic"), "Research topic")
    section = _safe_text(result.get("section"), "trends")
    description = (
        "Underlying forces accelerating or shaping the market."
        if section == "drivers"
        else "Key players and other players separated into memo-ready company cards, with recent developments from the last 2 to 3 years."
        if section == "competitive_landscape"
        else "Observable patterns, shifts, and momentum lines across the landscape."
    )
    if section == "competitive_landscape":
        items_html = (
            _render_competitive_landscape_group("Key Players", result.get("major_players", []) or [])
            + _render_competitive_landscape_group("Other Players", result.get("emerging_players", []) or [])
        )
        empty_state_html = ""
    else:
        items_html = "".join(
            _render_item(item, index, section) for index, item in enumerate(result.get("items", []) or [], start=1)
        )
        empty_state_html = (
            "<div class=\"memo-empty-state\">No strong insights found.</div>"
            if not (result.get("items", []) or [])
            else ""
        )

    return (
        "<section class=\"memo-section\">"
        "<div class=\"memo-section__hero\">"
        "<div>"
        "<div class=\"memo-eyebrow\">Final Brief</div>"
        f"<h1>{title}</h1>"
        f"<p class=\"memo-topic\">{topic}</p>"
        f"<p class=\"memo-description\">{html.escape(description)}</p>"
        "</div>"
        f"<div class=\"memo-scope\">{location_label} | {html.escape(title)}</div>"
        "</div>"
        f"<div class=\"memo-meta-panel\">{_render_summary_cards(meta, result)}</div>"
        "<div class=\"editorial-rule\"></div>"
        f"<div class=\"memo-items\">{items_html or empty_state_html}</div>"
        "</section>"
    )


def build_html_export(
    *,
    result_payload: Dict[str, Any],
    meta_payload: Dict[str, Any],
    follow_up_payloads: Sequence[Dict[str, Any]],
) -> Tuple[bytes, str]:
    is_ies_report = _is_ies_report_payload(result_payload)
    if is_ies_report:
        result = dict(result_payload)
        request = dict(result.get("request", {}) or {})
        summary = dict(result.get("summary", {}) or {})
        title = _safe_text(result.get("title"), "")
        if not title:
            title = " | ".join(
                part
                for part in [request.get("industry") or summary.get("industry"), request.get("country") or summary.get("country")]
                if _safe_text(part)
            ) or "Industry Earnings Snapshot"
        result["section"] = "industry_earnings_snapshot"
        result["title"] = title
        result["request"] = request
        result["summary"] = summary
        result["scatter_chart"] = dict(result.get("scatter_chart", {}) or {})
        result["companies"] = list(result.get("companies", []) or [])
        result["metadata"] = dict(result.get("metadata", {}) or {})
    else:
        result = _normalize_export_result(result_payload)
    meta = dict(meta_payload or {})
    location_meta = meta.get("location") if isinstance(meta.get("location"), dict) else {}
    meta["location"] = {
        "label": _safe_text(location_meta.get("label"), "Global"),
    }
    meta["prepared"] = _safe_text(meta.get("prepared"), "")

    follow_up_sections: List[str] = []
    if not is_ies_report:
        for follow_up in [payload for payload in (follow_up_payloads or []) if isinstance(payload, dict)]:
            follow_title = _safe_text(follow_up.get("title"), "Follow-up Brief")
            follow_meta = follow_up.get("meta") if isinstance(follow_up.get("meta"), dict) else meta
            normalized_follow_up = _normalize_export_result(follow_up)
            follow_up_sections.append(
                _render_section(normalized_follow_up, follow_meta, title_override=follow_title)
            )

    document_title = _escape(result.get("title"), "Industry Trends")
    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{document_title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5efe4;
      --panel: #fffdf8;
      --panel-strong: #f7f0e6;
      --ink: #182321;
      --muted: #596763;
      --accent: #27433c;
      --accent-soft: #dce8e1;
      --line: #d7ccbd;
      --gold: #9f6f2f;
      --shadow: 0 18px 40px rgba(31, 42, 41, 0.08);
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background:
        radial-gradient(circle at top left, rgba(184, 140, 82, 0.18), transparent 26%),
        linear-gradient(180deg, #f8f3ea 0%, var(--bg) 100%);
      color: var(--ink);
    }}

    a {{
      color: var(--accent);
    }}

    .memo-shell {{
      width: min(1120px, calc(100% - 32px));
      margin: 32px auto 48px;
      display: grid;
      gap: 28px;
    }}

    .memo-section {{
      background: rgba(255, 253, 248, 0.94);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: var(--shadow);
      padding: 28px;
    }}

    .memo-section__hero {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: flex-start;
      margin-bottom: 24px;
    }}

    .memo-eyebrow {{
      font: 700 11px/1.3 Arial, sans-serif;
      letter-spacing: 0.22em;
      text-transform: uppercase;
      color: rgba(89, 103, 99, 0.85);
      margin-bottom: 10px;
    }}

    h1 {{
      margin: 0;
      font-size: clamp(30px, 4vw, 46px);
      line-height: 1.06;
    }}

    .memo-topic,
    .memo-description {{
      margin: 10px 0 0;
      max-width: 760px;
      font-size: 15px;
      line-height: 1.7;
      color: var(--muted);
    }}

    .memo-scope {{
      flex: 0 0 auto;
      font: 600 14px/1.4 Arial, sans-serif;
      color: var(--ink);
      text-align: center;
    }}

    .memo-meta-panel {{
      margin-top: 20px;
      border: 1px solid var(--line);
      border-radius: 24px;
      background: rgba(255, 255, 255, 0.72);
      padding: 18px 20px;
    }}

    .memo-summary-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(150px, 210px));
      gap: 12px;
      align-items: stretch;
      justify-content: start;
    }}

    .summary-card {{
      background: rgba(255,255,255,0.84);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 12px 14px;
      min-width: 0;
    }}

    .summary-card span {{
      display: block;
      margin-bottom: 8px;
      font: 700 11px/1.4 Arial, sans-serif;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--muted);
    }}

    .summary-card strong {{
      display: block;
      font-size: 14px;
      line-height: 1.4;
      color: var(--ink);
    }}

    .editorial-rule {{
      height: 1px;
      margin: 24px 0 0;
      background: linear-gradient(90deg, transparent, var(--line), transparent);
    }}

    .memo-items {{
      display: grid;
      gap: 18px;
      margin-top: 24px;
    }}

    .competitive-group {{
      display: grid;
      gap: 18px;
    }}

    .competitive-group__header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 0 4px;
    }}

    .competitive-group__header h2 {{
      margin: 0;
      font-size: 24px;
      line-height: 1.1;
      color: var(--accent);
    }}

    .competitive-group__header span {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 40px;
      height: 40px;
      padding: 0 12px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: var(--panel-strong);
      color: var(--muted);
      font: 700 11px/1 Arial, sans-serif;
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }}

    .memo-item {{
      background: rgba(255, 255, 255, 0.78);
      border: 1px solid var(--line);
      border-radius: 26px;
      padding: 20px;
    }}

    .memo-item__header {{
      display: flex;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 14px;
    }}

    .memo-item__index {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 44px;
      height: 44px;
      border-radius: 999px;
      background: var(--accent);
      color: #fff;
      font: 700 14px/1 Arial, sans-serif;
    }}

    .memo-item__badge {{
      font: 700 11px/1.4 Arial, sans-serif;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--gold);
      margin-bottom: 8px;
    }}

    .memo-item__label {{
      font: 700 11px/1.4 Arial, sans-serif;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 10px;
    }}

    .memo-item h3 {{
      margin: 0;
      font-size: 32px;
      line-height: 1.02;
    }}

    .memo-item__body {{
      margin: 0;
      font-size: 15px;
      line-height: 1.9;
      color: var(--muted);
    }}

    .item-subsection {{
      margin-top: 24px;
    }}

    .item-subsection--first {{
      margin-top: 0;
      padding-top: 0;
      border-top: 0;
    }}

    .item-subsection h4 {{
      margin: 0 0 10px;
      font: 700 13px/1.4 Arial, sans-serif;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--muted);
    }}

    .example-list,
    .source-list {{
      margin: 0;
      padding-left: 22px;
      color: var(--muted);
      font-size: 15px;
      line-height: 1.7;
    }}

    .source-list {{
      list-style: none;
      padding-left: 0;
    }}

    .source-item {{
      background: rgba(255,255,255,0.84);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 12px 14px;
    }}

    .example-year {{
      color: var(--gold);
      font-weight: 700;
    }}

    .source-item + .source-item {{
      margin-top: 8px;
    }}

    .source-meta {{
      font-size: 13px;
      color: var(--muted);
      margin-top: 4px;
    }}

    .disclosure {{
      margin-top: 28px;
      border: 1px solid var(--line);
      border-radius: 22px;
      background: rgba(255,255,255,0.72);
      overflow: hidden;
    }}

    .disclosure > summary {{
      cursor: pointer;
      list-style: none;
      padding: 14px 16px;
      font: 700 11px/1.4 Arial, sans-serif;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      color: var(--muted);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}

    .disclosure > summary::-webkit-details-marker {{
      display: none;
    }}

    .disclosure > summary::after {{
      content: "Show";
      color: var(--accent);
    }}

    .disclosure[open] > summary::after {{
      content: "Hide";
    }}

    .disclosure__body {{
      border-top: 1px solid var(--line);
      padding: 16px;
      display: grid;
      gap: 16px;
    }}

    .disclosure-block h4 {{
      margin: 0 0 10px;
      font: 700 11px/1.4 Arial, sans-serif;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: rgba(89, 103, 99, 0.82);
    }}

    .summary-separator {{
      margin: 0 6px;
      color: rgba(89, 103, 99, 0.55);
    }}

    .memo-empty-state {{
      border: 1px dashed var(--line);
      border-radius: 26px;
      background: rgba(255,255,255,0.76);
      padding: 24px 20px;
      font-size: 15px;
      line-height: 1.8;
      color: var(--muted);
    }}

    .memo-section--ies .memo-topic {{
      font-weight: 700;
      color: var(--accent);
    }}

    .memo-item--outlier {{
      border-color: rgba(159, 111, 47, 0.36);
      background: rgba(255, 248, 237, 0.9);
    }}

    .memo-item__meta {{
      margin: 10px 0 0;
      font: 600 12px/1.5 Arial, sans-serif;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: var(--muted);
    }}

    .memo-item__badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
    }}

    .memo-badge,
    .memo-pill {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      border: 1px solid var(--line);
      padding: 6px 10px;
      font: 700 10px/1 Arial, sans-serif;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      background: rgba(255, 255, 255, 0.9);
      color: var(--muted);
    }}

    .memo-badge--outlier,
    .memo-pill--warn {{
      border-color: rgba(159, 111, 47, 0.28);
      color: var(--gold);
      background: rgba(255, 248, 237, 0.95);
    }}

    .memo-badge--status {{
      border-color: rgba(39, 67, 60, 0.18);
      color: var(--accent);
      background: rgba(220, 232, 225, 0.65);
    }}

    .memo-pill-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 14px;
    }}

    .memo-pill--error {{
      border-color: rgba(185, 28, 28, 0.2);
      color: #b91c1c;
      background: rgba(254, 242, 242, 0.95);
    }}

    .memo-error {{
      margin: 14px 0 0;
      border-radius: 18px;
      border: 1px solid rgba(185, 28, 28, 0.18);
      background: rgba(254, 242, 242, 0.95);
      padding: 12px 14px;
      font-size: 14px;
      line-height: 1.7;
      color: #b91c1c;
    }}

    .ies-chart-shell {{
      overflow: hidden;
    }}

    .ies-chart {{
      border: 1px solid var(--line);
      border-radius: 26px;
      background: rgba(255, 255, 255, 0.8);
      padding: 18px;
    }}

    .ies-chart__header {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 14px;
    }}

    .ies-chart__header h4 {{
      margin: 0;
      font-size: 24px;
      line-height: 1.06;
      color: var(--ink);
    }}

    .ies-chart__header p {{
      margin: 0;
      font: 700 11px/1.4 Arial, sans-serif;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--muted);
    }}

    .ies-chart-table {{
      display: grid;
      gap: 8px;
      margin-top: 16px;
    }}

    .ies-chart-row {{
      display: grid;
      grid-template-columns: minmax(72px, 0.7fr) minmax(170px, 1.6fr) repeat(4, minmax(70px, 0.75fr));
      gap: 10px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 10px 12px;
      background: rgba(255, 255, 255, 0.8);
    }}

    .ies-chart-row--header {{
      font: 700 10px/1.4 Arial, sans-serif;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--muted);
      background: rgba(247, 240, 230, 0.88);
    }}

    .ies-chart-row__company {{
      color: var(--ink);
      font-weight: 700;
    }}

    .ies-chart-row__metric,
    .ies-chart-row__ticker {{
      font-size: 14px;
      line-height: 1.5;
      color: var(--muted);
    }}

    .ies-company-grid {{
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      margin-top: 18px;
    }}

    @media (max-width: 960px) {{
      .ies-chart-row {{
        grid-template-columns: minmax(64px, 0.6fr) minmax(120px, 1.2fr) repeat(2, minmax(0, 1fr));
      }}

      .ies-chart-row--header {{
        display: none;
      }}

      .ies-company-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
    }}

    @media (max-width: 640px) {{
      .ies-chart-row {{
        grid-template-columns: 1fr 1fr;
      }}

      .ies-company-grid {{
        grid-template-columns: minmax(0, 1fr);
      }}
    }}

    @media (max-width: 860px) {{
      .memo-section {{
        padding: 22px 18px;
      }}

      .memo-section__hero {{
        flex-direction: column;
      }}

      .memo-scope {{
        min-width: 0;
      }}

      .memo-summary-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
      }}

      .memo-item h3 {{
        font-size: 24px;
      }}
    }}

    @media (max-width: 560px) {{
      .memo-shell {{
        width: min(100% - 20px, 1000px);
        margin: 18px auto 28px;
      }}

      .memo-summary-grid {{
        grid-template-columns: minmax(0, 1fr);
      }}

      .memo-item__header {{
        flex-direction: column;
      }}

      .memo-item__index {{
        min-width: 48px;
        height: 48px;
        border-radius: 14px;
      }}
    }}
  </style>
</head>
<body>
  <main class="memo-shell">
    {_render_ies_section(result, meta) if is_ies_report else _render_section(result, meta)}
    {''.join(follow_up_sections)}
  </main>
</body>
</html>
"""

    return full_html.encode("utf-8"), _build_filename(result, meta)
