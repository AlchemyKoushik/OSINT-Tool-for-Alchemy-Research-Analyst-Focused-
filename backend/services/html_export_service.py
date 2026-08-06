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
        ("Companies Scanned", html.escape(str(summary.get("companies_returned") or company_count or 0))),
        ("Companies Fetched", html.escape(str(summary.get("companies_enriched") or metadata.get("total_companies_successfully_enriched") or 0))),
        ("Median Rev. Growth (LQ YoY)", _escape(_format_ies_percent(summary.get("median_revenue_growth")))),
        ("Median Op. Margin (TTM)", _escape(_format_ies_percent(summary.get("median_operating_margin")))),
        ("Median EBITDA Margin (TTM)", _escape(_format_ies_percent(summary.get("median_ebitda_margin")))),
        ("Median EV / Revenue", _escape(_format_ies_ratio(summary.get("median_ev_to_revenue")))),
        ("Median EV / EBITDA", _escape(_format_ies_ratio(summary.get("median_ev_to_ebitda")))),
        ("Median Forward P/E", _escape(_format_ies_ratio(summary.get("median_forward_pe")))),
        ("EPS Beat Rate (LQ)", _escape(_format_ies_percent(summary.get("eps_beat_rate")))),
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
        f"<h4>{html.escape(_safe_text(scatter_chart.get('title'), 'Peer Positioning'))}</h4>"
        f"<p>{html.escape(_safe_text(scatter_chart.get('bubble_size_label'), 'Revenue TTM'))} bubbles</p>"
        "</div>"
        "<div class=\"ies-chart__legend\">"
        f"<span>{html.escape(_safe_text(scatter_chart.get('x_label'), 'Revenue Growth (LQ YoY)'))}</span>"
        f"<span>{html.escape(_safe_text(scatter_chart.get('y_label'), 'Operating Margin (TTM)'))}</span>"
        "</div>"
        "<div class=\"ies-chart-table\">"
        "<div class=\"ies-chart-row ies-chart-row--header\">"
        "<div>Ticker</div><div>Company</div><div>Rev. Growth (LQ YoY)</div><div>Op. Margin (TTM)</div><div>Bubble</div><div>Status</div>"
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
        f"<div class=\"summary-card\"><span>Median Rev. Growth (LQ YoY)</span><strong>{_escape(_format_ies_percent(company.get('revenue_growth_lq_yoy')))}</strong></div>"
        f"<div class=\"summary-card\"><span>Median Op. Margin (TTM)</span><strong>{_escape(_format_ies_percent(company.get('operating_margin')))}</strong></div>"
        f"<div class=\"summary-card\"><span>Median EBITDA Margin (TTM)</span><strong>{_escape(_format_ies_percent(company.get('ebitda_margin')))}</strong></div>"
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
        and (
            payload.get("section") == "industry_earnings_snapshot"
            or payload.get("report_type") == "ies_report"
            or (
                isinstance(payload.get("summary"), dict)
                and isinstance(payload.get("scatter_chart"), dict)
                and isinstance(payload.get("companies"), list)
            )
        )
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


def _format_ies_ratio_text(value: Any) -> str:
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


def _format_ies_signed_percent(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "N/A"
    sign = "+" if numeric > 0 else ""
    return f"{sign}{numeric:.1f}%"


def _format_ies_signed_percent_html(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return '<span class="ies-metric-value ies-metric-value--empty">N/A</span>'

    if numeric > 0:
        tone = "positive"
    elif numeric < 0:
        tone = "negative"
    else:
        tone = "neutral"
    return f'<span class="ies-metric-value ies-metric-value--{tone}">{html.escape(_format_ies_signed_percent(numeric))}</span>'


def _format_ies_ratio_html(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return '<span class="ies-metric-value ies-metric-value--empty">N/A</span>'
    return f'<span class="ies-metric-value ies-metric-value--neutral">{html.escape(f"{numeric:.1f}x")}</span>'


def _format_ies_compact_number_html(value: Any) -> str:
    formatted = _format_ies_compact_number(value)
    if formatted == "N/A":
        return '<span class="ies-metric-value ies-metric-value--empty">N/A</span>'
    return f'<span class="ies-metric-value ies-metric-value--neutral">{html.escape(formatted)}</span>'


def _compute_ies_scatter_geometry(points: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    normalized_points = []
    for index, point in enumerate(points):
        try:
            x = float(point.get("revenue_growth_lq_yoy"))
            y = float(point.get("operating_margin"))
        except (TypeError, ValueError):
            continue
        bubble = point.get("bubble_size")
        try:
            bubble_value = float(bubble)
        except (TypeError, ValueError):
            bubble_value = None
        normalized_points.append(
            {
                "index": index,
                "x": x,
                "y": y,
                "bubble": bubble_value,
                "ticker": _safe_text(point.get("ticker"), ""),
                "company_name": _safe_text(point.get("company_name"), ""),
                "country": _safe_text(point.get("country") or point.get("exchange"), ""),
                "is_outlier": bool(point.get("is_outlier")),
            }
        )

    if not normalized_points:
        return {
            "points": [],
            "has_data": False,
            "width": 1000,
            "height": 560,
            "margin": {"top": 42, "right": 48, "bottom": 76, "left": 104},
            "plot_width": 848,
            "plot_height": 442,
            "x_min": 0.0,
            "x_max": 1.0,
            "y_min": 0.0,
            "y_max": 1.0,
            "bubble_min": 1.0,
            "bubble_max": 1.0,
            "x_median": 0.0,
            "y_median": 0.0,
        }

    x_values = [point["x"] for point in normalized_points]
    y_values = [point["y"] for point in normalized_points]
    bubble_values = [point["bubble"] for point in normalized_points if point["bubble"] is not None]
    x_min = min(x_values)
    x_max = max(x_values)
    y_min = min(y_values)
    y_max = max(y_values)
    bubble_min = min(bubble_values) if bubble_values else 1.0
    bubble_max = max(bubble_values) if bubble_values else 1.0

    def median(values: Sequence[float]) -> float:
        ordered = sorted(values)
        if not ordered:
            return 0.0
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2

    return {
        "points": normalized_points,
        "has_data": True,
        "width": 1000,
        "height": 560,
        "margin": {"top": 42, "right": 48, "bottom": 76, "left": 104},
        "plot_width": 848,
        "plot_height": 442,
        "x_min": x_min,
        "x_max": x_max,
        "y_min": y_min,
        "y_max": y_max,
        "bubble_min": bubble_min,
        "bubble_max": bubble_max,
        "x_median": median(x_values),
        "y_median": median(y_values),
    }


def _render_ies_scatter_svg(chart: Dict[str, Any]) -> str:
    points = list(chart.get("data", []) or [])
    geometry = _compute_ies_scatter_geometry(points)
    if not geometry["has_data"]:
        return (
            '<div class="ies-empty-state">No scatter chart data was returned for this report.</div>'
        )

    width = geometry["width"]
    height = geometry["height"]
    margin = geometry["margin"]
    plot_width = geometry["plot_width"]
    plot_height = geometry["plot_height"]
    x_min = geometry["x_min"]
    x_max = geometry["x_max"]
    y_min = geometry["y_min"]
    y_max = geometry["y_max"]
    bubble_min = geometry["bubble_min"]
    bubble_max = geometry["bubble_max"]
    x_median = geometry["x_median"]
    y_median = geometry["y_median"]
    x_pad = (x_max - x_min or 1.0) * 0.18
    y_pad = (y_max - y_min or 1.0) * 0.18
    axis_x_min = x_min - x_pad
    axis_x_max = x_max + x_pad
    axis_y_min = y_min - y_pad
    axis_y_max = y_max + y_pad

    def x_scale(value: float) -> float:
        return margin["left"] + ((value - axis_x_min) / max(1e-9, axis_x_max - axis_x_min)) * plot_width

    def y_scale(value: float) -> float:
        return margin["top"] + plot_height - ((value - axis_y_min) / max(1e-9, axis_y_max - axis_y_min)) * plot_height

    def radius_for(point: Dict[str, Any]) -> float:
        bubble_value = point["bubble"] if point["bubble"] is not None else bubble_min
        bubble_range = max(1.0, bubble_max - bubble_min)
        scaled = 9 + ((bubble_value - bubble_min) / bubble_range) * 20
        return max(9.0, min(29.0, scaled))

    def color_for(point: Dict[str, Any]) -> str:
        diff = point["y"] - y_median
        spread = max(4.0, abs(y_max - y_min) * 0.4)
        if diff > spread * 0.08:
            return "url(#ies-grad-pos)"
        if diff < -spread * 0.08:
            return "url(#ies-grad-neg)"
        return "url(#ies-grad-neu)"

    def format_axis_percent(value: float) -> str:
        sign = "+" if value > 0 else ""
        return f"{sign}{value:.1f}%"

    grid_line_count = 4
    x_ticks = [axis_x_min + ((axis_x_max - axis_x_min) * index) / grid_line_count for index in range(grid_line_count + 1)]
    y_ticks = [axis_y_min + ((axis_y_max - axis_y_min) * index) / grid_line_count for index in range(grid_line_count + 1)]
    left_axis_x = margin["left"]
    right_axis_x = margin["left"] + plot_width
    top_axis_y = margin["top"]
    bottom_axis_y = margin["top"] + plot_height
    median_x = x_scale(x_median)
    median_y = y_scale(y_median)

    sorted_points = sorted(
        geometry["points"],
        key=lambda point: point["bubble"] if point["bubble"] is not None else bubble_min,
        reverse=True,
    )

    watermark_positions = [
        (left_axis_x + plot_width * 0.75, top_axis_y + plot_height * 0.22, "HIGH GROWTH • HIGH MARGIN"),
        (left_axis_x + plot_width * 0.25, top_axis_y + plot_height * 0.22, "LOW GROWTH • HIGH MARGIN"),
        (left_axis_x + plot_width * 0.75, top_axis_y + plot_height * 0.78, "HIGH GROWTH • LOW MARGIN"),
        (left_axis_x + plot_width * 0.25, top_axis_y + plot_height * 0.78, "LOW GROWTH • LOW MARGIN"),
    ]

    bubbles = []
    for point in sorted_points:
        x = x_scale(point["x"])
        y = y_scale(point["y"])
        radius = radius_for(point)
        ticker = html.escape(point.get("ticker") or "")
        company_name = html.escape(point.get("company_name") or ticker)
        rev_growth = _format_ies_signed_percent(point.get("x"))
        op_margin = _format_ies_signed_percent(point.get("y"))
        bubble_val = _format_ies_compact_number(point.get("bubble"))
        title_text = f"{company_name} ({ticker})\nRevenue Growth: {rev_growth}\nOp. Margin: {op_margin}\nRevenue TTM: {bubble_val}"
        bubbles.append(
            f'<g class="ies-scatter-bubble-group group outline-none" data-key="{ticker}" transform="translate({x:.2f}, {y:.2f})">'
            f'<circle class="ies-bubble-circle transition-all duration-200" r="{radius:.2f}" fill="{color_for(point)}" fill-opacity="0.9" stroke="#FFFFFF" stroke-width="2" filter="url(#ies-bubble-shadow)">'
            f'<title>{title_text}</title>'
            '</circle>'
            '</g>'
        )

    y_grid_lines = []
    for tick in y_ticks:
        y = top_axis_y + plot_height - ((tick - axis_y_min) / max(1e-9, axis_y_max - axis_y_min)) * plot_height
        y_grid_lines.append(
            "<g>"
            f'<line x1="{left_axis_x:.2f}" y1="{y:.2f}" x2="{right_axis_x:.2f}" y2="{y:.2f}" stroke="rgba(104,117,113,0.12)" stroke-width="0.8" />'
            f'<text x="{left_axis_x - 14:.2f}" y="{y + 4:.2f}" text-anchor="end" font-size="11" font-family="Manrope, sans-serif" font-weight="600" fill="#65706A">{html.escape(format_axis_percent(tick))}</text>'
            "</g>"
        )

    x_grid_lines = []
    for tick in x_ticks:
        x = left_axis_x + ((tick - axis_x_min) / max(1e-9, axis_x_max - axis_x_min)) * plot_width
        x_grid_lines.append(
            "<g>"
            f'<line x1="{x:.2f}" y1="{top_axis_y:.2f}" x2="{x:.2f}" y2="{bottom_axis_y:.2f}" stroke="rgba(104,117,113,0.12)" stroke-width="0.8" />'
            f'<text x="{x:.2f}" y="{bottom_axis_y + 20:.2f}" text-anchor="middle" font-size="11" font-family="Manrope, sans-serif" font-weight="600" fill="#65706A">{html.escape(format_axis_percent(tick))}</text>'
            "</g>"
        )

    watermark_html = "".join(
        f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="middle" font-size="11" font-weight="700" letter-spacing="0.22em" fill="rgba(65,80,74,0.07)">{html.escape(label)}</text>'
        for x, y, label in watermark_positions
    )

    chart_title = "Peer Positioning"
    x_label = html.escape(_safe_text(chart.get("x_label"), "Revenue Growth (LQ YoY)"))
    y_label = html.escape(_safe_text(chart.get("y_label"), "Operating Margin (TTM)"))
    bubble_label = html.escape(_safe_text(chart.get("bubble_size_label"), "Revenue TTM"))

    return f"""
<div class="rounded-[28px] border border-atelier-line/80 bg-white/80 p-5 md:p-7 shadow-[0_20px_50px_rgba(31,42,41,0.05)]">
  <div class="flex flex-wrap items-center justify-between gap-4 border-b border-atelier-line/60 pb-4">
    <div>
      <h4 class="m-0 font-display text-2xl md:text-3xl font-semibold leading-tight text-atelier-ink">{chart_title}</h4>
    </div>
    <div class="flex flex-wrap items-center gap-2.5">
      <div class="inline-flex items-center gap-2 rounded-full border border-atelier-line/80 bg-white/90 px-3.5 py-1.5 text-[10px] font-bold uppercase tracking-wider text-atelier-ink shadow-2xs">
        <span class="h-2 w-2 rounded-full bg-amber-600"></span>
        <span>Bubble Size: <strong class="text-atelier-forest">{bubble_label}</strong></span>
      </div>
      <div class="inline-flex items-center gap-2 rounded-full border border-atelier-line/80 bg-white/90 px-3.5 py-1.5 text-[10px] font-bold uppercase tracking-wider text-atelier-ink shadow-2xs">
        <div class="flex h-2.5 w-6 rounded-full bg-gradient-to-r from-[#D96B60] via-[#C5BEB5] to-[#4E8764]"></div>
        <span>Color: <strong class="text-atelier-forest">{y_label}</strong></span>
      </div>
    </div>
  </div>
  <div class="ies-chart-stage mt-6 rounded-[24px] border border-atelier-line/60 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-[#FFFDF8] via-white to-[#F9F5EC] p-4 md:p-6 shadow-[inset_0_1px_2px_rgba(255,255,255,0.9),0_20px_50px_rgba(31,42,41,0.04)]" style="position: relative; overflow: visible; min-height: 35rem;">
    <svg viewBox="0 0 {width} {height}" class="ies-scatter block h-auto w-full overflow-visible" role="img" aria-label="{chart_title}">
      <defs>
        <radialGradient id="ies-grad-pos" cx="35%" cy="35%" r="65%">
          <stop offset="0%" stop-color="#6EA383" stop-opacity="0.95" />
          <stop offset="70%" stop-color="#4E8764" stop-opacity="0.88" />
          <stop offset="100%" stop-color="#3A6A4E" stop-opacity="0.9" />
        </radialGradient>
        <radialGradient id="ies-grad-neu" cx="35%" cy="35%" r="65%">
          <stop offset="0%" stop-color="#DCD5CC" stop-opacity="0.95" />
          <stop offset="70%" stop-color="#C5BEB5" stop-opacity="0.88" />
          <stop offset="100%" stop-color="#A8A096" stop-opacity="0.9" />
        </radialGradient>
        <radialGradient id="ies-grad-neg" cx="35%" cy="35%" r="65%">
          <stop offset="0%" stop-color="#E88B81" stop-opacity="0.95" />
          <stop offset="70%" stop-color="#D96B60" stop-opacity="0.88" />
          <stop offset="100%" stop-color="#B84F45" stop-opacity="0.9" />
        </radialGradient>
        <filter id="ies-bubble-shadow" x="-40%" y="-40%" width="180%" height="180%">
          <feDropShadow dx="0" dy="4" stdDeviation="3" flood-color="#1F2A29" flood-opacity="0.16" />
        </filter>
      </defs>
      <g class="quadrant-watermarks pointer-events-none select-none">
        {watermark_html}
      </g>
      {"".join(y_grid_lines)}
      {"".join(x_grid_lines)}
      <line x1="{left_axis_x:.2f}" y1="{median_y:.2f}" x2="{right_axis_x:.2f}" y2="{median_y:.2f}" stroke="rgba(88,104,101,0.25)" stroke-width="1.2" stroke-dasharray="5 5" />
      <line x1="{median_x:.2f}" y1="{top_axis_y:.2f}" x2="{median_x:.2f}" y2="{bottom_axis_y:.2f}" stroke="rgba(88,104,101,0.25)" stroke-width="1.2" stroke-dasharray="5 5" />
      <g class="median-labels pointer-events-none select-none">
        <text x="{right_axis_x - 10:.2f}" y="{median_y - 6:.2f}" text-anchor="end" font-size="9" font-weight="700" letter-spacing="0.16em" fill="rgba(88,104,101,0.45)">ABOVE MEDIAN MARGIN</text>
        <text x="{right_axis_x - 10:.2f}" y="{median_y + 14:.2f}" text-anchor="end" font-size="9" font-weight="700" letter-spacing="0.16em" fill="rgba(88,104,101,0.45)">BELOW MEDIAN MARGIN</text>
        <text x="{median_x + 8:.2f}" y="{top_axis_y + 14:.2f}" text-anchor="start" font-size="9" font-weight="700" letter-spacing="0.16em" fill="rgba(88,104,101,0.45)">ABOVE MEDIAN GROWTH</text>
        <text x="{median_x - 8:.2f}" y="{top_axis_y + 14:.2f}" text-anchor="end" font-size="9" font-weight="700" letter-spacing="0.16em" fill="rgba(88,104,101,0.45)">BELOW MEDIAN GROWTH</text>
      </g>
      <line x1="{left_axis_x:.2f}" y1="{bottom_axis_y:.2f}" x2="{right_axis_x:.2f}" y2="{bottom_axis_y:.2f}" stroke="rgba(31,42,41,0.22)" stroke-width="1.2" />
      <line x1="{left_axis_x:.2f}" y1="{top_axis_y:.2f}" x2="{left_axis_x:.2f}" y2="{bottom_axis_y:.2f}" stroke="rgba(31,42,41,0.22)" stroke-width="1.2" />
      {"".join(bubbles)}
      <text x="{(left_axis_x + right_axis_x) / 2:.2f}" y="{height - 4:.2f}" text-anchor="middle" font-size="12" font-weight="700" fill="#41504A">{x_label}</text>
      <text x="18" y="{(top_axis_y + bottom_axis_y) / 2:.2f}" text-anchor="middle" font-size="12" font-weight="700" fill="#41504A" transform="rotate(-90 18 {(top_axis_y + bottom_axis_y) / 2:.2f})">{y_label}</text>
    </svg>
  </div>
</div>
"""


def _render_ies_insight_cards(result: Dict[str, Any]) -> str:
    companies = list(result.get("companies", []) or [])
    summary = dict(result.get("summary", {}) or {})

    highest_growth = None
    for company in companies:
        try:
            float(company.get("revenue_growth_lq_yoy"))
        except (TypeError, ValueError):
            continue
        if highest_growth is None or float(company.get("revenue_growth_lq_yoy")) > float(highest_growth.get("revenue_growth_lq_yoy")):
            highest_growth = company

    highest_margin = None
    for company in companies:
        try:
            float(company.get("operating_margin"))
        except (TypeError, ValueError):
            continue
        if highest_margin is None or float(company.get("operating_margin")) > float(highest_margin.get("operating_margin")):
            highest_margin = company

    revenue_candidates = []
    ebitda_candidates = []
    for company in companies:
        try:
            revenue_candidates.append(float(company.get("ev_to_revenue_ttm")))
        except (TypeError, ValueError):
            pass
        try:
            ebitda_candidates.append(float(company.get("ev_to_ebitda_ttm")))
        except (TypeError, ValueError):
            pass

    highest_growth_label = (
        f"{_safe_text(highest_growth.get('company_name') or highest_growth.get('ticker'), 'Company')} leads revenue growth at {_format_ies_signed_percent(highest_growth.get('revenue_growth_lq_yoy'))}."
        if highest_growth
        else "Revenue growth leadership is not available in the current universe."
    )
    highest_margin_label = (
        f"{_safe_text(highest_margin.get('company_name') or highest_margin.get('ticker'), 'Company')} shows the highest operating margin at {_format_ies_signed_percent(highest_margin.get('operating_margin'))}."
        if highest_margin
        else "Operating margin leadership is not available in the current universe."
    )

    if revenue_candidates:
        valuation_revenue_text = f"EV / Revenue spans {_format_ies_ratio_text(min(revenue_candidates))} to {_format_ies_ratio_text(max(revenue_candidates))} across the universe."
    else:
        valuation_revenue_text = "EV / Revenue could not be derived from the available companies."

    if ebitda_candidates:
        valuation_ebitda_text = f"EV / EBITDA spans {_format_ies_ratio_text(min(ebitda_candidates))} to {_format_ies_ratio_text(max(ebitda_candidates))} across the universe."
    else:
        valuation_ebitda_text = "EV / EBITDA could not be derived from the available companies."

    summary_text = html.escape(
        _safe_text(
            summary.get("memo_summary")
            or summary.get("summary")
            or "This memo presents peer data for the selected companies to support industry analysis and comparison.",
            "This memo presents peer data for the selected companies to support industry analysis and comparison.",
        )
    )

    return f"""
<section class="ies-insights-shell rounded-[28px] border border-atelier-line/80 bg-white/80 p-6 md:p-8 shadow-[0_20px_50px_rgba(31,42,41,0.04)]">
  <div class="flex flex-col gap-1.5">
    <h4 class="m-0 font-display text-2xl md:text-3xl font-semibold leading-tight text-atelier-ink">Editorial Readout &amp; Market Structure</h4>
    <p class="mt-1 font-display text-xs md:text-sm font-medium leading-relaxed text-atelier-moss">{summary_text}</p>
  </div>
  <div class="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
    <div class="ies-insight-card h-full rounded-2xl border border-atelier-line/70 border-l-4 p-5 shadow-2xs border-l-emerald-600 bg-gradient-to-br from-emerald-50/40 to-white/90">
      <div class="flex items-center gap-2">
        <div class="flex h-7 w-7 items-center justify-center rounded-lg bg-white/80 shadow-2xs shrink-0">
          <svg class="w-4 h-4 text-emerald-600 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="width: 16px; height: 16px; min-width: 16px; min-height: 16px;"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18" /><polyline points="17 6 23 6 23 12" /></svg>
        </div>
        <p class="m-0 font-display text-[12px] font-semibold text-atelier-ink">Highest Growth</p>
      </div>
      <p class="mt-2.5 font-display text-xs md:text-sm leading-relaxed text-atelier-moss font-medium whitespace-pre-line">{html.escape(highest_growth_label)}</p>
    </div>
    <div class="ies-insight-card h-full rounded-2xl border border-atelier-line/70 border-l-4 p-5 shadow-2xs border-l-amber-500 bg-gradient-to-br from-amber-50/30 to-white/90">
      <div class="flex items-center gap-2">
        <div class="flex h-7 w-7 items-center justify-center rounded-lg bg-white/80 shadow-2xs shrink-0">
          <svg class="w-4 h-4 text-amber-600 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="width: 16px; height: 16px; min-width: 16px; min-height: 16px;"><circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="6" /><circle cx="12" cy="12" r="2" /></svg>
        </div>
        <p class="m-0 font-display text-[12px] font-semibold text-atelier-ink">Highest Margin</p>
      </div>
      <p class="mt-2.5 font-display text-xs md:text-sm leading-relaxed text-atelier-moss font-medium whitespace-pre-line">{html.escape(highest_margin_label)}</p>
    </div>
    <div class="ies-insight-card h-full rounded-2xl border border-atelier-line/70 border-l-4 p-5 shadow-2xs border-l-slate-500 bg-gradient-to-br from-slate-50/25 to-white/90">
      <div class="flex items-center gap-2">
        <div class="flex h-7 w-7 items-center justify-center rounded-lg bg-white/80 shadow-2xs shrink-0">
          <svg class="w-4 h-4 text-slate-500 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="width: 16px; height: 16px; min-width: 16px; min-height: 16px;"><line x1="18" y1="20" x2="18" y2="10" /><line x1="6" y1="20" x2="6" y2="14" /></svg>
        </div>
        <p class="m-0 font-display text-[12px] font-semibold text-atelier-ink">Valuation Range</p>
      </div>
      <p class="mt-2.5 font-display text-xs md:text-sm leading-relaxed text-atelier-moss font-medium whitespace-pre-line">{html.escape(valuation_revenue_text)}<br>{html.escape(valuation_ebitda_text)}</p>
    </div>
  </div>
</section>
"""


def _render_ies_company_table(companies: Sequence[Dict[str, Any]]) -> str:
    normalized_companies = list(companies or [])
    if not normalized_companies:
        return '<div class="ies-empty-state">No companies were returned for this report.</div>'

    rows = []
    for index, company in enumerate(normalized_companies, start=1):
        company_name = _safe_text(company.get("company_name") or company.get("ticker"), "Company")
        ticker = _safe_text(company.get("ticker"), "N/A")
        exchange = _safe_text(company.get("exchange"), "")
        country = _safe_text(company.get("country"), "")

        is_outlier = company.get("is_outlier")
        row_bg = "bg-amber-50/40" if is_outlier else ("bg-[#FAF7F2]/30" if index % 2 == 0 else "bg-white/40")

        location_bits = [part for part in [ticker, exchange, country] if part]
        location_html = " ".join(
            f"<span>• {html.escape(part)}</span>" if idx > 0 else f'<span class="font-semibold text-atelier-ink">{html.escape(part)}</span>'
            for idx, part in enumerate(location_bits)
        )

        rows.append(
            f"""
            <tr class="ies-universe-row group transition-colors duration-75 {row_bg}" data-key="{html.escape(ticker)}">
              <td class="py-3 pl-3 pr-1 font-display text-xs font-semibold text-atelier-moss/60 align-middle text-center w-8">{index:02d}</td>
              <td class="py-3 px-2.5 align-middle">
                <div class="flex flex-col min-w-0">
                  <span class="font-display font-bold text-atelier-ink break-words whitespace-normal leading-tight text-xs sm:text-sm">{html.escape(company_name)}</span>
                  <div class="flex flex-wrap items-center gap-1 mt-0.5 text-atelier-moss/80 font-display text-[10px]">{location_html}</div>
                </div>
              </td>
              <td class="py-3 px-2 text-center font-display tabular-nums font-semibold text-atelier-ink align-middle text-xs sm:text-sm">{_format_ies_compact_number(company.get("revenue_ttm"))}</td>
              <td class="py-3 px-2 text-center font-display tabular-nums font-semibold text-atelier-ink align-middle text-xs sm:text-sm">{_format_ies_signed_percent(company.get("revenue_growth_lq_yoy"))}</td>
              <td class="py-3 px-2 text-center font-display tabular-nums font-semibold text-atelier-ink align-middle text-xs sm:text-sm">{_format_ies_signed_percent(company.get("operating_margin"))}</td>
              <td class="py-3 px-2 text-center font-display tabular-nums font-medium text-atelier-ink align-middle text-xs sm:text-sm">{_format_ies_ratio(company.get("ev_to_revenue_ttm"))}</td>
              <td class="py-3 px-2 text-center font-display tabular-nums font-medium text-atelier-ink align-middle text-xs sm:text-sm">{_format_ies_ratio(company.get("ev_to_ebitda_ttm"))}</td>
            </tr>
            """
        )

    return f"""
<section>
  <div class="flex flex-wrap items-center justify-between gap-4 mb-4">
    <div>
      <h4 class="m-0 font-display text-2xl font-semibold leading-tight text-atelier-ink">Company Ranking Table</h4>
    </div>
  </div>
  <div class="overflow-hidden rounded-2xl border border-atelier-line/80 bg-white/80 shadow-[0_18px_48px_rgba(31,42,41,0.04)]">
    <div class="max-h-[38rem] overflow-y-auto panel-scroll">
      <table class="w-full text-left border-collapse">
        <thead class="sticky top-0 z-20 isolate bg-[#FAF6F0] border-b border-atelier-line/80">
          <tr>
            <th class="sticky top-0 z-20 bg-[#FAF6F0] py-3 pl-3 pr-1 text-center text-[10px] font-bold uppercase tracking-[0.18em] text-atelier-moss/70 w-8">#</th>
            <th class="sticky top-0 z-20 bg-[#FAF6F0] py-3 px-2.5 text-[10px] font-bold uppercase tracking-[0.18em] text-atelier-moss/70">Company &amp; Ticker</th>
            <th class="sticky top-0 z-20 bg-[#FAF6F0] py-3 px-2 text-center text-[10px] font-bold uppercase tracking-[0.18em] text-atelier-moss/70">Revenue (TTM)</th>
            <th class="sticky top-0 z-20 bg-[#FAF6F0] py-3 px-2 text-center text-[10px] font-bold uppercase tracking-[0.18em] text-atelier-moss/70">Rev. Growth (LQ YoY)</th>
            <th class="sticky top-0 z-20 bg-[#FAF6F0] py-3 px-2 text-center text-[10px] font-bold uppercase tracking-[0.18em] text-atelier-moss/70">Op. Margin (TTM)</th>
            <th class="sticky top-0 z-20 bg-[#FAF6F0] py-3 px-2 text-center text-[10px] font-bold uppercase tracking-[0.18em] text-atelier-moss/70">EV / Revenue</th>
            <th class="sticky top-0 z-20 bg-[#FAF6F0] py-3 px-2 text-center text-[10px] font-bold uppercase tracking-[0.18em] text-atelier-moss/70">EV / EBITDA</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-atelier-line/40">
          {"".join(rows)}
        </tbody>
      </table>
    </div>
  </div>
</section>
"""


def _render_ies_export_document(result: Dict[str, Any], meta: Dict[str, Any]) -> str:
    request = dict(result.get("request", {}) or {})
    summary = dict(result.get("summary", {}) or {})
    metadata = dict(result.get("metadata", {}) or {})
    chart = dict(result.get("scatter_chart", {}) or {})
    companies = list(result.get("companies", []) or [])

    title = _escape(result.get("title"), "Industry Earnings Snapshot")
    scatter_html = _render_ies_scatter_svg(chart)
    table_html = _render_ies_company_table(companies)
    insights_html = _render_ies_insight_cards(result)

    companies_scanned = summary.get("companies_returned") or len(companies) or 0
    companies_fetched = summary.get("companies_enriched") or metadata.get("total_companies_successfully_enriched") or len(companies) or 0
    median_rev_growth = summary.get("median_revenue_growth")
    median_op_margin = summary.get("median_operating_margin")
    median_ev_revenue = summary.get("median_ev_to_revenue")
    median_ev_ebitda = summary.get("median_ev_to_ebitda")

    def _trend_arrow(value: Any) -> str:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return ""
        if numeric > 0:
            return '<span class="trend-up">↑</span>'
        if numeric < 0:
            return '<span class="trend-down">↓</span>'
        return ""

    kpi_cards_html = (
        '<div class="ies-kpi-card"><span class="ies-kpi-label">Companies Scanned</span><div class="ies-kpi-val-row"><span class="ies-kpi-value">'
        f'{html.escape(str(companies_scanned))}</span></div></div>'
        '<div class="ies-kpi-card"><span class="ies-kpi-label">Companies Fetched</span><div class="ies-kpi-val-row"><span class="ies-kpi-value">'
        f'{html.escape(str(companies_fetched))}</span></div></div>'
        '<div class="ies-kpi-card"><span class="ies-kpi-label">Median Rev. Growth (LQ YoY)</span><div class="ies-kpi-val-row"><span class="ies-kpi-value">'
        f'{html.escape(_format_ies_percent(median_rev_growth))}</span>{_trend_arrow(median_rev_growth)}</div></div>'
        '<div class="ies-kpi-card"><span class="ies-kpi-label">Median Op. Margin (TTM)</span><div class="ies-kpi-val-row"><span class="ies-kpi-value">'
        f'{html.escape(_format_ies_percent(median_op_margin))}</span>{_trend_arrow(median_op_margin)}</div></div>'
        '<div class="ies-kpi-card"><span class="ies-kpi-label">Median EV / Revenue</span><div class="ies-kpi-val-row"><span class="ies-kpi-value">'
        f'{html.escape(_format_ies_ratio(median_ev_revenue))}</span></div></div>'
        '<div class="ies-kpi-card"><span class="ies-kpi-label">Median EV / EBITDA</span><div class="ies-kpi-val-row"><span class="ies-kpi-value">'
        f'{html.escape(_format_ies_ratio(median_ev_ebitda))}</span></div></div>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {{
      color-scheme: light;
      --bg: #F8F5EE;
      --panel: #FFFDF9;
      --panel-strong: #FFFDF8;
      --ink: #1F2A29;
      --muted: #65706A;
      --accent: #27433c;
      --accent-soft: #dce8e1;
      --line: rgba(62, 69, 63, 0.12);
      --gold: #B88C52;
      --shadow: 0 18px 40px rgba(31, 42, 41, 0.08);
      --font-display: 'Fraunces', Georgia, serif;
      --font-body: 'Manrope', -apple-system, sans-serif;
    }}

    * {{
      box-sizing: border-box;
    }}

    html, body {{
      min-height: 100%;
    }}

    html {{
      font-size: 15px;
      background:
        radial-gradient(circle at 100% 0%, rgba(231, 211, 181, 0.38), transparent 22%),
        radial-gradient(circle at 84% 84%, rgba(203, 228, 217, 0.28), transparent 24%),
        linear-gradient(135deg, #fbf7f1 0%, #f4eee4 56%, #eee4d5 100%);
      overflow-x: hidden;
      overflow-y: auto;
      scrollbar-width: none;
      -ms-overflow-style: none;
    }}

    body {{
      margin: 0;
      font-family: var(--font-body);
      color: var(--ink);
      overflow-x: hidden;
      overflow-y: auto;
      min-height: 100vh;
      background:
        radial-gradient(circle at 100% 0%, rgba(231, 211, 181, 0.38), transparent 22%),
        radial-gradient(circle at 84% 84%, rgba(203, 228, 217, 0.28), transparent 24%),
        linear-gradient(135deg, #fbf7f1 0%, #f4eee4 56%, #eee4d5 100%);
      scrollbar-width: none;
      -ms-overflow-style: none;
    }}

    body::before {{
      content: "";
      position: fixed;
      inset: -2px;
      z-index: -1;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(39, 67, 60, 0.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(39, 67, 60, 0.03) 1px, transparent 1px);
      background-size: 26px 26px;
      mask-image: radial-gradient(circle at center, rgba(0, 0, 0, 0.7), transparent 95%);
      opacity: 0.35;
    }}

    body::after {{
      content: "";
      position: fixed;
      inset: -2px;
      z-index: -1;
      pointer-events: none;
      background:
        radial-gradient(circle at 84% 8%, rgba(255, 248, 239, 0.72), transparent 18%);
      opacity: 0.95;
    }}

    .memo-shell {{
      width: min(1120px, calc(100% - 32px));
      margin: 32px auto 48px;
      display: grid;
      gap: 28px;
    }}

    .paper-sheet {{
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(252, 248, 242, 0.96));
      border: 1px solid rgba(62, 69, 63, 0.12);
      border-radius: 32px;
      box-shadow: 0 20px 50px rgba(31, 42, 41, 0.05);
      padding: 36px;
      position: relative;
    }}

    .paper-sheet::before {{
      content: "";
      position: absolute;
      inset: 0;
      z-index: 0;
      border-radius: inherit;
      pointer-events: none;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.68), transparent 18%);
    }}

    .ies-hero {{
      margin-bottom: 32px;
      position: relative;
      z-index: 1;
    }}

    .ies-hero h3 {{
      font-family: var(--font-display);
      font-size: 38px;
      font-weight: 700;
      line-height: 1.05;
      color: #0F172A;
      margin: 0;
      opacity: 1 !important;
    }}

    .ies-kpi-ribbon {{
      display: grid;
      grid-template-columns: repeat(6, 1fr);
      gap: 12px;
      background: rgba(255, 255, 255, 0.95);
      border: 1px solid rgba(62, 69, 63, 0.14);
      border-radius: 18px;
      padding: 16px 20px;
      margin-bottom: 32px;
      position: relative;
      z-index: 1;
    }}

    .ies-kpi-card {{
      display: flex;
      flex-direction: column;
      justify-content: center;
      padding: 4px 8px;
    }}

    .ies-kpi-card + .ies-kpi-card {{
      border-left: 1px solid rgba(62, 69, 63, 0.12);
      padding-left: 16px;
    }}

    .ies-kpi-label {{
      font-family: var(--font-display);
      font-size: 9px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: #1F2937;
      opacity: 1 !important;
    }}

    .ies-kpi-val-row {{
      display: flex;
      align-items: baseline;
      gap: 6px;
      margin-top: 6px;
    }}

    .ies-kpi-value {{
      font-family: var(--font-display);
      font-size: 26px;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: #000000;
      opacity: 1 !important;
    }}

    .trend-up {{ color: #047857; font-weight: 700; font-size: 14px; }}
    .trend-down {{ color: #be123c; font-weight: 700; font-size: 14px; }}

    .panel-scroll {{
      scrollbar-width: none;
      -ms-overflow-style: none;
    }}
    .panel-scroll::-webkit-scrollbar {{
      display: none;
      width: 0;
      height: 0;
    }}

    @media (max-width: 960px) {{
      .ies-kpi-ribbon {{ grid-template-columns: repeat(3, 1fr); }}
    }}
  </style>
</head>
<body>
  <main class="memo-shell">
    <div class="paper-sheet ies-result-sheet flex w-full flex-col rounded-[32px] px-6 py-6 md:px-10 md:py-10 space-y-9 my-auto justify-center">
      <section class="ies-hero">
        <div class="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div class="w-full space-y-2">
            <h3 class="font-display text-4xl sm:text-5xl font-semibold leading-[0.95] tracking-tight text-atelier-ink">{title}</h3>
          </div>
        </div>
      </section>

      <div class="ies-kpi-ribbon">
        {kpi_cards_html}
      </div>

      <section>
        {scatter_html}
      </section>

      {insights_html}

      {table_html}
    </div>
  </main>
</body>
</html>
"""


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
        meta = dict(meta_payload or {})
        location_meta = meta.get("location") if isinstance(meta.get("location"), dict) else {}
        meta["location"] = {
            "label": _safe_text(location_meta.get("label"), "Global"),
        }
        meta["prepared"] = _safe_text(meta.get("prepared"), "")
        html_output = _render_ies_export_document(result, meta)
        return html_output.encode("utf-8"), _build_filename(result, meta)
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
      font: 700 9px/1.4 Arial, sans-serif;
      letter-spacing: 0.14em;
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
