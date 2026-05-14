import html
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Set
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

LOW_QUALITY_MARKERS = ("login", "subscribe")
REPORT_MARKERS = ("report", "analysis", "market", "outlook", "research", "forecast", "survey", "data")
WEAK_OPINION_MARKERS = ("opinion", "editorial", "blog", "commentary", "hot take", "newsletter")
RECENT_KEYWORDS = ("recent", "latest", "new", "current", "emerging", "updated")
GARBAGE_MARKERS = (
    "click here",
    "read more",
    "copyright",
    "all rights reserved",
    "privacy policy",
    "terms of use",
    "cookie policy",
    "follow us",
    "share this",
    "contact us",
    "skip to",
    "site map",
    "newsletter",
    "breadcrumbs",
    "navigation",
    "note:",
    "source:",
)
STRIP_PREFIX_PATTERN = re.compile(r"^(?:source|note|references?)\s*:\s*", re.IGNORECASE)
URL_PATTERN = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
MAX_SELECTED_SOURCES = 30
MAX_SENTENCES_PER_SOURCE = 4
MAX_CHARS_PER_SOURCE = 2200
MAX_TOTAL_CONTEXT_TOKENS = 14000
MAX_TOTAL_CONTEXT_CHARS = MAX_TOTAL_CONTEXT_TOKENS * 4
MIN_CONTENT_LENGTH = 160
MIN_SENTENCE_LENGTH = 50
MAX_SENTENCE_LENGTH = 360
MIN_WORDS_PER_SENTENCE = 8
HEADING_WORD_THRESHOLD = 14
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
NUMERIC_PATTERN = re.compile(r"\b\d+(?:\.\d+)?(?:%|x| million| billion| bn| m| k)?\b", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
NON_ALPHA_PATTERN = re.compile(r"[^A-Za-z]+")
METADATA_PATTERN = re.compile(r"\b(?:type|weight|score|rank|source_id|artifact_type)\s*=\s*\S+", re.IGNORECASE)


def _extract_domain(url: str) -> str:
    parsed = urlparse(str(url).strip())
    domain = parsed.netloc.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def _clean_html_artifacts(text: str) -> str:
    cleaned = html.unescape(text or "")
    cleaned = cleaned.replace("\r", "\n").replace("\xa0", " ")
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)

    normalized_lines: List[str] = []
    for raw_line in cleaned.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            if normalized_lines and normalized_lines[-1] != "":
                normalized_lines.append("")
            continue
        normalized_lines.append(line)

    return "\n".join(normalized_lines).strip()


def _word_count(text: str) -> int:
    return len([part for part in re.split(r"\s+", text.strip()) if part])


def _estimate_tokens(text: str) -> int:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return 0
    return max(1, len(normalized) // 4)


def _contains_url(text: str) -> bool:
    return bool(URL_PATTERN.search(text))


def _contains_garbage_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in GARBAGE_MARKERS)


def _looks_like_heading_or_nav(line: str) -> bool:
    if any(punctuation in line for punctuation in ".!?;:"):
        return False
    word_count = _word_count(line)
    if word_count < MIN_WORDS_PER_SENTENCE:
        return True
    return word_count <= HEADING_WORD_THRESHOLD and line == line.title()


def _clean_line(line: str) -> str:
    cleaned = URL_PATTERN.sub(" ", line)
    cleaned = METADATA_PATTERN.sub(" ", cleaned)
    cleaned = STRIP_PREFIX_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -|")
    return cleaned


def _clean_source_text(text: str) -> str:
    cleaned = _clean_html_artifacts(text)
    kept_lines: List[str] = []

    for raw_line in cleaned.splitlines():
        line = _clean_line(raw_line)
        if not line:
            continue
        if _contains_url(line):
            continue
        if _contains_garbage_marker(line):
            continue
        if _word_count(line) < MIN_WORDS_PER_SENTENCE:
            continue
        if _looks_like_heading_or_nav(line):
            continue
        kept_lines.append(line)

    return "\n".join(kept_lines).strip()


def clean_evidence_text(text: str) -> str:
    return _clean_source_text(text)


def _is_low_quality_content(text: str) -> bool:
    lower_text = text.lower()
    return len(text) < MIN_CONTENT_LENGTH or any(marker in lower_text for marker in LOW_QUALITY_MARKERS)


def _normalize_sentence(sentence: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()


def _extract_years(text: str) -> List[int]:
    current_year = datetime.utcnow().year + 1
    years = {int(match) for match in YEAR_PATTERN.findall(text)}
    return sorted(year for year in years if 2000 <= year <= current_year)


def _temporal_analysis(text: str) -> Dict[str, Any]:
    lower_text = text.lower()
    years = _extract_years(text)
    recent_terms = [keyword for keyword in RECENT_KEYWORDS if keyword in lower_text]
    temporal_weight = 0

    if years:
        newest_year = max(years)
        current_year = datetime.utcnow().year
        if newest_year >= current_year - 1:
            temporal_weight += 2
        elif newest_year >= current_year - 3:
            temporal_weight += 1
    else:
        newest_year = None

    if recent_terms:
        temporal_weight += 1

    return {
        "years": years,
        "newest_year": newest_year,
        "recent_terms": recent_terms,
        "temporal_weight": temporal_weight,
    }


def _build_weight_components(url: str, text: str, artifact_type: str = "") -> Dict[str, Any]:
    lower_text = text.lower()
    lower_url = url.lower()
    normalized_artifact_type = artifact_type.lower().strip()
    temporal = _temporal_analysis(text)

    statistics_weight = 3 if NUMERIC_PATTERN.search(text) else 0
    report_gov_weight = 2 if (
        any(marker in lower_text for marker in REPORT_MARKERS)
        or ".gov" in lower_url
        or lower_url.endswith(".pdf")
        or normalized_artifact_type == "pdf"
    ) else 0
    general_weight = 1
    weak_opinion_weight = -2 if any(marker in lower_text or marker in lower_url for marker in WEAK_OPINION_MARKERS) else 0

    total_weight = (
        statistics_weight
        + report_gov_weight
        + general_weight
        + weak_opinion_weight
        + int(temporal["temporal_weight"])
    )

    return {
        "total_weight": total_weight,
        "components": {
            "statistics": statistics_weight,
            "report_gov": report_gov_weight,
            "general": general_weight,
            "weak_opinion": weak_opinion_weight,
            "temporal": int(temporal["temporal_weight"]),
        },
        "years": temporal["years"],
        "newest_year": temporal["newest_year"],
        "recent_terms": temporal["recent_terms"],
    }


def _is_meaningful_sentence(sentence: str) -> bool:
    clean_sentence = re.sub(r"\s+", " ", sentence).strip()
    if not clean_sentence:
        return False
    if _contains_url(clean_sentence):
        return False
    if _contains_garbage_marker(clean_sentence):
        return False
    if _word_count(clean_sentence) < MIN_WORDS_PER_SENTENCE:
        return False
    if len(clean_sentence) < MIN_SENTENCE_LENGTH or len(clean_sentence) > MAX_SENTENCE_LENGTH:
        return False

    alphabetic_chars = len(NON_ALPHA_PATTERN.sub("", clean_sentence))
    if alphabetic_chars < 20:
        return False

    return True


def is_garbage_text(text: str) -> bool:
    normalized = _clean_line(text)
    lowered = normalized.lower()
    if not normalized:
        return True
    if _word_count(normalized) < MIN_WORDS_PER_SENTENCE:
        return True
    if any(marker in lowered for marker in GARBAGE_MARKERS):
        return True
    if "http" in lowered or "www" in lowered:
        return True
    return not _is_meaningful_sentence(normalized)


def _extract_candidate_sentences(text: str) -> List[str]:
    candidates: List[str] = []

    for sentence in SENTENCE_SPLIT_PATTERN.split(text):
        clean_sentence = _clean_line(sentence)
        if is_garbage_text(clean_sentence):
            continue
        candidates.append(clean_sentence)

    return candidates


def _score_sentence(sentence: str) -> int:
    lower_sentence = sentence.lower()
    score = 1

    if NUMERIC_PATTERN.search(sentence):
        score += 3
    if YEAR_PATTERN.search(sentence):
        score += 2
    if any(marker in lower_sentence for marker in REPORT_MARKERS):
        score += 1
    if any(marker in lower_sentence for marker in RECENT_KEYWORDS):
        score += 1

    return score


def _truncate_text(text: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _pick_sentences(
    sentence_candidates: List[Dict[str, Any]],
    seen_sentences: Set[str],
) -> List[str]:
    selected: List[str] = []

    for candidate in sentence_candidates:
        sentence = str(candidate.get("text", "")).strip()
        normalized = _normalize_sentence(sentence)
        if not normalized or normalized in seen_sentences:
            continue

        seen_sentences.add(normalized)
        selected.append(sentence)
        if len(selected) >= MAX_SENTENCES_PER_SOURCE:
            break

    return selected


def filter_evidence_sentences(sentences: List[str], *, limit: int = MAX_SENTENCES_PER_SOURCE) -> List[str]:
    selected: List[str] = []
    seen: Set[str] = set()
    for sentence in sentences:
        normalized = _normalize_sentence(sentence)
        if not normalized or normalized in seen:
            continue
        if is_garbage_text(sentence):
            continue
        seen.add(normalized)
        selected.append(sentence)
        if len(selected) >= limit:
            break
    return selected


def _format_detected_date(years: List[int]) -> str:
    if not years:
        return ""
    if len(years) == 1:
        return str(years[0])
    return str(max(years))


def prepare_processed_content(
    scraped_data: List[Dict[str, Any]],
) -> Dict[str, Any]:
    logger.info("Content processing started for %s scraped sources.", len(scraped_data))

    candidate_sources: List[Dict[str, Any]] = []
    for data in scraped_data:
        url = str(data.get("url", "unknown"))
        title = str(data.get("title", "")).strip() or _extract_domain(url) or "Untitled source"
        content = str(data.get("content", ""))
        artifact_type = str(data.get("artifact_type", "")).strip().lower()
        artifact_path = str(data.get("artifact_path", "")).strip()
        image_url = str(data.get("image_url", "")).strip()
        location_score = int(data.get("location_score", 0))
        location_matches = [str(match).strip() for match in data.get("location_matches", []) if str(match).strip()]
        cleaned_content = clean_evidence_text(content)

        if _is_low_quality_content(cleaned_content):
            logger.info("Skipping low-quality source: %s", url)
            continue

        weight_data = _build_weight_components(url, cleaned_content, artifact_type)
        sentence_candidates: List[Dict[str, Any]] = []
        for sentence in _extract_candidate_sentences(cleaned_content):
            sentence_weight = _build_weight_components(url, sentence, artifact_type)
            sentence_candidates.append(
                {
                    "text": sentence,
                    "score": _score_sentence(sentence) + int(sentence_weight["total_weight"]),
                    "years": sentence_weight["years"],
                    "newest_year": sentence_weight["newest_year"] or 0,
                }
            )

        sentence_candidates.sort(
            key=lambda item: (
                int(item["score"]),
                int(item["newest_year"]),
                len(str(item["text"])),
            ),
            reverse=True,
        )

        if not sentence_candidates:
            logger.info("Skipping source with no usable evidence sentences: %s", url)
            continue

        candidate_sources.append(
            {
                "url": url,
                "title": title,
                "domain": _extract_domain(url),
                "content": cleaned_content,
                "artifact_type": artifact_type or "web",
                "artifact_path": artifact_path,
                "image_url": image_url,
                "sentence_candidates": sentence_candidates,
                "weight_data": weight_data,
                "location_score": location_score,
                "location_matches": location_matches,
                "score": int(weight_data["total_weight"]) + location_score,
            }
        )

    candidate_sources.sort(
        key=lambda item: (
            int(item["score"]),
            int(item["weight_data"].get("newest_year") or 0),
            len(str(item["content"])),
        ),
        reverse=True,
    )
    selected_candidates = candidate_sources[:MAX_SELECTED_SOURCES]

    evidence_blocks: List[Dict[str, Any]] = []
    processed_sources: List[str] = []
    selected_urls: List[str] = []
    source_scores: List[Dict[str, Any]] = []
    signal_weights: List[Dict[str, Any]] = []
    seen_sentences: Set[str] = set()
    seen_source_excerpts: Set[str] = set()
    total_output_chars = 0

    for source_index, candidate in enumerate(selected_candidates, start=1):
        selected_sentences = _pick_sentences(candidate["sentence_candidates"], seen_sentences)
        selected_sentences = filter_evidence_sentences(selected_sentences, limit=MAX_SENTENCES_PER_SOURCE)
        if not selected_sentences:
            logger.info("Skipping source with no usable sentences after dedupe: %s", candidate["url"])
            continue

        combined_years = sorted(
            {
                int(year)
                for sentence_candidate in candidate["sentence_candidates"][:MAX_SENTENCES_PER_SOURCE * 2]
                for year in sentence_candidate.get("years", [])
            }
        )
        weight_data = candidate["weight_data"]
        excerpt = _truncate_text(" ".join(selected_sentences), MAX_CHARS_PER_SOURCE)
        source_text = excerpt.strip()
        normalized_excerpt = _normalize_sentence(source_text)
        if not normalized_excerpt or normalized_excerpt in seen_source_excerpts:
            logger.info("Skipping duplicate source excerpt: %s", candidate["url"])
            continue
        seen_source_excerpts.add(normalized_excerpt)
        remaining_chars = MAX_TOTAL_CONTEXT_CHARS - total_output_chars
        if remaining_chars <= 0:
            break
        if len(source_text) > remaining_chars:
            if remaining_chars < 250:
                break
            source_text = _truncate_text(source_text, remaining_chars)

        processed_sources.append(source_text)
        evidence_blocks.append(
            {
                "source_id": str(source_index),
                "title": candidate["title"],
                "date": _format_detected_date(combined_years or weight_data["years"]),
                "excerpt": source_text,
                "url": candidate["url"],
                "domain": candidate["domain"],
                "image_url": candidate["image_url"],
            }
        )
        selected_urls.append(candidate["url"])
        total_output_chars += len(source_text) + 2

        source_scores.append(
            {
                "title": candidate["title"],
                "url": candidate["url"],
                "domain": candidate["domain"],
                "artifact_type": candidate["artifact_type"],
                "artifact_path": candidate["artifact_path"],
                "image_url": candidate["image_url"],
                "score": candidate["score"],
                "location_score": candidate["location_score"],
                "location_matches": candidate["location_matches"],
                "newest_year": weight_data["newest_year"],
                "years": weight_data["years"],
            }
        )
        signal_weights.append(
            {
                "title": candidate["title"],
                "url": candidate["url"],
                "domain": candidate["domain"],
                "artifact_type": candidate["artifact_type"],
                "artifact_path": candidate["artifact_path"],
                "image_url": candidate["image_url"],
                "total_weight": weight_data["total_weight"],
                "location_score": candidate["location_score"],
                "location_matches": candidate["location_matches"],
                "components": weight_data["components"],
                "years": weight_data["years"],
                "recent_terms": weight_data["recent_terms"],
            }
        )

        if _estimate_tokens("\n\n".join(processed_sources)) >= MAX_TOTAL_CONTEXT_TOKENS:
            break

    processed_text = "\n\n".join(processed_sources)
    logger.info(
        "Content processing completed with %s selected sources and %s characters.",
        len(selected_urls),
        len(processed_text),
    )
    return {
        "processed_text": processed_text,
        "evidence_blocks": evidence_blocks,
        "selected_urls": selected_urls,
        "num_sources": len(selected_urls),
        "processing_chars": len(processed_text),
        "source_scores": source_scores,
        "signal_weights": signal_weights,
    }


def process_scraped_content(scraped_data: List[Dict[str, Any]]) -> str:
    processed_payload = prepare_processed_content(scraped_data)
    return str(processed_payload["processed_text"])
