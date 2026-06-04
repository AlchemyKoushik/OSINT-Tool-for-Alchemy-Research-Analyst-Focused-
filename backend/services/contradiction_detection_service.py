import re
from typing import Any, Dict, List, Sequence

NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?(?:%| million| billion|m|bn)?\b", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\b20\d{2}\b")


def detect_contradictions(claims: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    statistics: Dict[str, List[Dict[str, Any]]] = {}
    dates: Dict[str, List[Dict[str, Any]]] = {}
    conflicts: List[Dict[str, Any]] = []

    for claim in claims:
        text = str(claim.get("text", "")).strip()
        source = str(claim.get("source", "")).strip()
        for number in NUMBER_PATTERN.findall(text):
            statistics.setdefault(number.lower(), []).append({"text": text, "source": source})
        for year in YEAR_PATTERN.findall(text):
            dates.setdefault(year, []).append({"text": text, "source": source})

    if len(statistics) > 1:
        conflicts.append({"type": "statistics", "details": statistics})
    if len(dates) > 1:
        conflicts.append({"type": "dates", "details": dates})

    return {
        "conflicts": conflicts,
        "statistics_index": [{"value": key, "claims": value} for key, value in statistics.items()],
        "date_index": [{"value": key, "claims": value} for key, value in dates.items()],
    }
