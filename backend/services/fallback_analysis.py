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
        return " ".join(words)
    return f"{topic.title()} Insight {index}"


def _build_description(text: str, section: str) -> str:
    if section == "trends":
        return (
            f"{text} Taken together, the evidence points to a concrete market shift rather than an isolated source detail."
        )
    return (
        f"{text} Taken together, the evidence points to an underlying force that is actively shaping market change."
    )


def build_fallback_section_analysis(
    *,
    topic: str,
    processed_text: str,
    section: str,
) -> Dict[str, Any]:
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
                "source_ids": [],
            }
        )

    return {
        "section": section,
        "title": "Industry Trends" if section == "trends" else "Market Drivers",
        "items": items,
    }
