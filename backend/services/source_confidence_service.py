from typing import Any, Dict
from urllib.parse import urlparse

HIGH_CONFIDENCE_KEYWORDS = (".gov", ".edu", "investor", "ir.", "sec.gov", "official")
MEDIUM_CONFIDENCE_KEYWORDS = ("journal", "industry", "association", "research", "report")
LOW_CONFIDENCE_KEYWORDS = ("blog", "forum", "reddit", "medium.com", "substack")


def _extract_domain(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    domain = str(parsed.netloc or "").strip().lower()
    return domain[4:] if domain.startswith("www.") else domain


def score_source_confidence(*, url: str, source_type: str = "", title: str = "") -> Dict[str, Any]:
    domain = _extract_domain(url)
    combined = f"{domain} {source_type} {title}".lower()

    if any(keyword in combined for keyword in HIGH_CONFIDENCE_KEYWORDS):
        return {"confidence": "high", "reason": "Government, regulator, or official investor relations source."}
    if any(keyword in combined for keyword in LOW_CONFIDENCE_KEYWORDS):
        return {"confidence": "low", "reason": "Blog, forum, or user-generated source."}
    if any(keyword in combined for keyword in MEDIUM_CONFIDENCE_KEYWORDS):
        return {"confidence": "medium", "reason": "Industry publication or research source."}
    if domain.endswith(".com"):
        return {"confidence": "medium", "reason": "Commercial domain with no explicit downgrade markers."}
    return {"confidence": "low", "reason": "Unclassified source requires manual review."}
