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


def _count_sources(items: Sequence[Dict[str, Any]]) -> int:
    total = 0
    for item in items:
        total += len(item.get("sources", []) or [])
    return total


def _normalize_export_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    fallback_section = _safe_text(payload.get("section"), "trends").lower() or "trends"
    return normalize_analyze_response_payload(payload, fallback_section=fallback_section)


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
    for example in examples[:2]:
        text = _escape(example.get("text"))
        if not text:
            continue
        year = _escape(example.get("year"))
        suffix = f" <span class=\"example-year\">({year})</span>" if year else ""
        items.append(f"<li>{text}{suffix}</li>")

    if not items:
        return ""

    return (
        "<section class=\"item-subsection\">"
        "<h4>Examples</h4>"
        f"<ul class=\"example-list\">{''.join(items)}</ul>"
        "</section>"
    )


def _render_sources(sources: Sequence[Dict[str, Any]]) -> str:
    if not sources:
        return ""

    items = [_render_source_link(source, index) for index, source in enumerate(sources[:5], start=1)]
    return (
        "<section class=\"item-subsection\">"
        "<h4>Sources</h4>"
        f"<ul class=\"source-list\">{''.join(items)}</ul>"
        "</section>"
    )


def _render_item(item: Dict[str, Any], index: int) -> str:
    heading = _escape(item.get("heading"), "Insight")
    body = _format_multiline_html(item.get("body"))
    badge = "Trend" if "trend" in _safe_text(item.get("heading")).lower() else "Insight"
    examples = item.get("examples", []) or []
    sources = item.get("sources", []) or []

    return (
        "<article class=\"memo-item\">"
        "<div class=\"memo-item__header\">"
        f"<span class=\"memo-item__index\">{index:02d}</span>"
        "<div>"
        f"<div class=\"memo-item__badge\">{html.escape(badge)}</div>"
        f"<h3>{heading}</h3>"
        "</div>"
        "</div>"
        f"<p class=\"memo-item__body\">{body}</p>"
        f"{_render_examples(examples)}"
        f"{_render_sources(sources)}"
        "</article>"
    )


def _render_summary_cards(meta: Dict[str, Any], result: Dict[str, Any]) -> str:
    location_label = _escape(meta.get("location", {}).get("label"), "Global")
    prepared = _escape(meta.get("prepared"), "Prepared now")
    section_title = _escape(result.get("title"), "Industry Trends")
    source_count = html.escape(str(_count_sources(result.get("items", []) or [])))

    cards = [
        ("Section", section_title),
        ("Scope", location_label),
        ("Sources", source_count),
        ("Prepared", prepared),
    ]
    return "".join(
        f"<div class=\"summary-card\"><span>{label}</span><strong>{value}</strong></div>"
        for label, value in cards
    )


def _render_section(result: Dict[str, Any], meta: Dict[str, Any], *, title_override: str | None = None) -> str:
    title = _escape(title_override or result.get("title"), "Industry Trends")
    location_label = _escape(meta.get("location", {}).get("label"), "Global")
    topic = _escape(meta.get("topic"), "Research topic")
    description = (
        "Underlying forces accelerating or shaping the market."
        if result.get("section") == "drivers"
        else "Observable patterns, shifts, and momentum lines across the landscape."
    )
    items_html = "".join(
        _render_item(item, index) for index, item in enumerate(result.get("items", []) or [], start=1)
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
        f"<div class=\"memo-scope\">{location_label}</div>"
        "</div>"
        f"<div class=\"memo-summary-grid\">{_render_summary_cards(meta, result)}</div>"
        f"<div class=\"memo-items\">{items_html}</div>"
        "</section>"
    )


def build_html_export(
    *,
    result_payload: Dict[str, Any],
    meta_payload: Dict[str, Any],
    follow_up_payloads: Sequence[Dict[str, Any]],
) -> Tuple[bytes, str]:
    result = _normalize_export_result(result_payload)
    meta = dict(meta_payload or {})
    location_meta = meta.get("location") if isinstance(meta.get("location"), dict) else {}
    meta["location"] = {
        "label": _safe_text(location_meta.get("label"), "Global"),
    }
    meta["prepared"] = _safe_text(meta.get("prepared"), "")

    follow_up_sections: List[str] = []
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
      color: var(--gold);
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
      font-size: 17px;
      line-height: 1.7;
      color: var(--muted);
    }}

    .memo-scope {{
      flex: 0 0 auto;
      min-width: 180px;
      padding: 12px 16px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font: 700 12px/1.4 Arial, sans-serif;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      text-align: center;
    }}

    .memo-summary-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }}

    .summary-card {{
      background: var(--panel-strong);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px 16px;
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
      font-size: 16px;
      line-height: 1.5;
    }}

    .memo-items {{
      display: grid;
      gap: 18px;
    }}

    .memo-item {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 22px;
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
      min-width: 56px;
      height: 56px;
      border-radius: 16px;
      background: var(--accent);
      color: #fff;
      font: 700 20px/1 Arial, sans-serif;
    }}

    .memo-item__badge {{
      font: 700 11px/1.4 Arial, sans-serif;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--gold);
      margin-bottom: 8px;
    }}

    .memo-item h3 {{
      margin: 0;
      font-size: 28px;
      line-height: 1.15;
    }}

    .memo-item__body {{
      margin: 0;
      font-size: 17px;
      line-height: 1.78;
      color: var(--ink);
    }}

    .item-subsection {{
      margin-top: 16px;
      padding-top: 14px;
      border-top: 1px solid var(--line);
    }}

    .item-subsection h4 {{
      margin: 0 0 10px;
      font: 700 13px/1.4 Arial, sans-serif;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--accent);
    }}

    .example-list,
    .source-list {{
      margin: 0;
      padding-left: 22px;
      color: var(--muted);
      font-size: 15px;
      line-height: 1.7;
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
    {_render_section(result, meta)}
    {''.join(follow_up_sections)}
  </main>
</body>
</html>
"""

    return full_html.encode("utf-8"), _build_filename(result, meta)
