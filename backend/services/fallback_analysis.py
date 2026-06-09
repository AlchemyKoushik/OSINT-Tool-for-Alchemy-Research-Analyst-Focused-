import re
from typing import Any, Dict, List

JUNK_PHRASES = (
    "thanks very much",
    "future outlook",
    "analysis and forecast",
    "analysis and forecasts",
    "market size",
    "what is the expected",
    "the report examines",
    "forecast period",
    "overview",
)
SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")
WORD_PATTERN = re.compile(r"\b[a-zA-Z][a-zA-Z\-]{2,}\b")
COMPANY_CANDIDATE_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z&.\-]+(?:\s+[A-Z][A-Za-z&.\-]+){0,4}\s+"
    r"(?:Inc\.?|Ltd\.?|Limited|LLC|PLC|Corp\.?|Corporation|Group|Holdings|Technologies|Systems|Media|Networks))\b"
)
COMPANY_REJECT_TERMS = {
    "market",
    "markets",
    "forecast",
    "forecasts",
    "industry",
    "industries",
    "executive",
    "summary",
    "chapter",
    "global",
    "billion",
    "million",
    "report",
    "reports",
    "analysis",
    "insight",
    "insights",
}
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "have",
    "has",
    "been",
    "are",
    "was",
    "were",
    "will",
    "about",
    "their",
    "them",
    "they",
    "than",
    "then",
    "when",
    "where",
    "which",
    "while",
    "over",
    "under",
    "your",
    "topic",
    "market",
    "analysis",
    "report",
    "trends",
    "drivers",
}


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _candidate_sentences(processed_text: str) -> List[str]:
    candidates: List[str] = []
    for sentence in SENTENCE_PATTERN.split(_clean_text(processed_text)):
        cleaned = _clean_text(sentence)
        if len(cleaned.split()) < 8:
            continue
        if any(phrase in cleaned.lower() for phrase in JUNK_PHRASES):
            continue
        candidates.append(cleaned)
    return candidates


def _topic_terms(topic: str) -> List[str]:
    return [token.lower() for token in WORD_PATTERN.findall(topic) if token.lower() not in STOPWORDS]


def _build_heading(text: str, topic: str, index: int) -> str:
    topic_terms = set(_topic_terms(topic))
    words: List[str] = []
    for token in WORD_PATTERN.findall(text):
        lowered = token.lower()
        if lowered in STOPWORDS or lowered in topic_terms:
            continue
        words.append(token.capitalize())
        if len(words) >= 6:
            break
    if words:
        phrase = " ".join(words[:6])
        if index % 4 == 1:
            return f"Shift Towards {phrase}"
        if index % 4 == 2:
            return f"Rise of {phrase}"
        if index % 4 == 3:
            return f"Expansion of {phrase}"
        return f"Growing Adoption of {phrase}"
    return f"{topic.title()} Insight {index}"


def _build_description(text: str, section: str) -> str:
    if section == "competitive_landscape":
        return (
            f"{text} Available evidence suggests this player has visible market activity, but the fallback path "
            "could not reliably position it with the same depth as the primary analysis flow."
        )
    if section == "trends":
        return (
            f"{text} The pattern is becoming more visible across the market as competitive priorities, investment focus, and operating choices adjust around the same shift."
        )
    return (
        f"{text} The underlying force is increasingly shaping commercial decisions, capital allocation, and market positioning across the sector."
    )


def _looks_like_company_name(value: str) -> bool:
    normalized = _clean_text(value)
    if not normalized:
        return False
    lowered = normalized.lower()
    if any(term in lowered for term in JUNK_PHRASES):
        return False
    return not any(term in lowered.split() for term in COMPANY_REJECT_TERMS)


def _extract_company_candidates(processed_text: str) -> List[str]:
    candidates: List[str] = []
    seen = set()
    for match in COMPANY_CANDIDATE_PATTERN.finditer(processed_text or ""):
        candidate = _clean_text(match.group(1).strip(" .,-:;"))
        key = candidate.lower()
        if key in seen or not _looks_like_company_name(candidate):
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates[:8]


def build_fallback_section_analysis(
    *,
    topic: str,
    processed_text: str,
    section: str,
) -> Dict[str, Any]:
    if section == "competitive_landscape":
        company_candidates = _extract_company_candidates(processed_text)
        grouped_candidates = [
            {
                "heading": company_name,
                "body": (
                    f"{company_name} appears in the available evidence as an active participant in {topic}, "
                    "but the fallback path could not validate enough information to build a full company profile."
                ),
                "segment": "emerging_players",
                "market_role": "Emerging Player",
                "key_company_facts": [],
                "competitive_positioning": "",
                "source_ids": [],
            }
            for company_name in company_candidates
        ]
        return {
            "section": section,
            "title": "Competitive Landscape",
            "major_players": [],
            "emerging_players": grouped_candidates,
        }

    sentences = _candidate_sentences(processed_text)
    if not sentences:
        sentences = [f"Evidence around {topic} remains limited, but the topic is receiving relevant external attention."]

    items: List[Dict[str, str]] = []
    seen_headings = set()
    for index, sentence in enumerate(sentences[:8], start=1):
        heading = _build_heading(sentence, topic, index)
        if heading.lower() in seen_headings:
            continue
        seen_headings.add(heading.lower())
        items.append(
            {
                "heading": heading,
                "body": _build_description(sentence, section),
                "segment": "",
                "key_company_facts": [],
                "competitive_positioning": "",
                "source_ids": [],
            }
        )

    return {
        "section": section,
        "title": (
            "Industry Trends" if section == "trends" else "Market Drivers"
        ),
        "items": items,
    }
