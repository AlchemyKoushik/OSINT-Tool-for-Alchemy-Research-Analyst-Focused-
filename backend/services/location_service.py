import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCATION_DATA_PATH = PROJECT_ROOT / "backend" / "data" / "locations.json"
LOCATION_PREFERENCES = (
    {"value": "global", "label": "Global"},
    {"value": "region_specific", "label": "Region Specific"},
    {"value": "country_specific", "label": "Country Specific"},
)
LOCATION_RELEVANT_DOMAIN_MARKERS = (
    ".gov",
    ".edu",
    "consult",
    "research",
    "policy",
    "ministry",
    "department",
    "agency",
    "institute",
    "analytics",
    "insight",
)
GENERIC_GLOBAL_MARKERS = (
    "global",
    "worldwide",
    "international",
    "across markets",
    "across regions",
    "multi country",
    "multicountry",
)


@dataclass(frozen=True)
class LocationContext:
    preference: str = "global"
    value: str = ""
    label: str = "Global"
    region: str = ""
    keywords: Tuple[str, ...] = ()
    primary_keywords: Tuple[str, ...] = ()
    strict: bool = False

    @property
    def is_global(self) -> bool:
        return self.preference == "global"


def _normalize_preference(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"", "global"}:
        return "global"
    if normalized in {"region", "region_specific"}:
        return "region_specific"
    if normalized in {"country", "country_specific"}:
        return "country_specific"
    raise ValueError("Location preference must be Global, Region Specific, or Country Specific.")


def _normalize_phrase(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _extract_domain(url: str) -> str:
    parsed = urlparse(str(url).strip())
    domain = parsed.netloc.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


@lru_cache(maxsize=1)
def _load_location_payload() -> Dict[str, Any]:
    raw_content = LOCATION_DATA_PATH.read_text(encoding="utf-8")
    parsed = json.loads(raw_content)
    if not isinstance(parsed, dict):
        raise ValueError("Location dataset is invalid.")
    return parsed


@lru_cache(maxsize=1)
def _country_records() -> Tuple[Dict[str, Any], ...]:
    payload = _load_location_payload()
    countries = payload.get("countries", [])
    if not isinstance(countries, list):
        raise ValueError("Country dataset is invalid.")
    return tuple(record for record in countries if isinstance(record, dict))


@lru_cache(maxsize=1)
def _region_records() -> Tuple[Dict[str, Any], ...]:
    payload = _load_location_payload()
    regions = payload.get("regions", [])
    if not isinstance(regions, list):
        raise ValueError("Region dataset is invalid.")
    return tuple(record for record in regions if isinstance(record, dict))


@lru_cache(maxsize=1)
def _country_lookup() -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for record in _country_records():
        aliases = [str(record.get("name", "")).strip()]
        aliases.extend(str(alias).strip() for alias in record.get("aliases", []) or [])
        for alias in aliases:
            normalized_alias = _normalize_phrase(alias)
            if normalized_alias:
                lookup[normalized_alias] = record
    return lookup


@lru_cache(maxsize=1)
def _region_lookup() -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for record in _region_records():
        names = [str(record.get("name", "")).strip()]
        names.extend(str(alias).strip() for alias in record.get("aliases", []) or [])
        for name in names:
            normalized_name = _normalize_phrase(name)
            if normalized_name:
                lookup[normalized_name] = record
    return lookup


@lru_cache(maxsize=1)
def _countries_by_region() -> Dict[str, Tuple[Dict[str, Any], ...]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for record in _country_records():
        region = str(record.get("region", "")).strip()
        if not region:
            continue
        grouped.setdefault(region, []).append(record)
    return {region: tuple(records) for region, records in grouped.items()}


def get_region_options() -> List[str]:
    return [str(record.get("name", "")).strip() for record in _region_records() if str(record.get("name", "")).strip()]


def get_country_options() -> List[Dict[str, str]]:
    countries = []
    for record in _country_records():
        name = str(record.get("name", "")).strip()
        region = str(record.get("region", "")).strip()
        if not name:
            continue
        countries.append({"name": name, "region": region})
    return countries


def get_location_catalog() -> Dict[str, Any]:
    return {
        "preferences": list(LOCATION_PREFERENCES),
        "regions": get_region_options(),
        "countries": get_country_options(),
    }


def _deduplicate_keywords(values: List[str]) -> Tuple[str, ...]:
    deduplicated: List[str] = []
    seen = set()
    for value in values:
        cleaned_value = str(value or "").strip()
        normalized = _normalize_phrase(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduplicated.append(cleaned_value)
    return tuple(deduplicated)


def _matchable_aliases(values: List[str]) -> List[str]:
    matchable_values: List[str] = []
    for value in values:
        cleaned_value = str(value or "").strip()
        normalized_value = _normalize_phrase(cleaned_value)
        compact_alpha = re.sub(r"[^a-z]", "", cleaned_value.lower())
        if not normalized_value:
            continue
        if len(compact_alpha) <= 3 and cleaned_value.upper() == cleaned_value:
            continue
        matchable_values.append(cleaned_value)
    return matchable_values


def resolve_location_context(preference: str | None, value: str | None = None) -> LocationContext:
    normalized_preference = _normalize_preference(preference)
    normalized_value = str(value or "").strip()

    if normalized_preference == "global":
        return LocationContext()

    if not normalized_value:
        raise ValueError("A region or country must be selected for the chosen location preference.")

    normalized_lookup_value = _normalize_phrase(normalized_value)
    if normalized_preference == "region_specific":
        region_record = _region_lookup().get(normalized_lookup_value)
        if region_record is None:
            raise ValueError("Selected region is not supported.")

        region_name = str(region_record.get("name", "")).strip()
        region_keywords = [region_name]
        region_keywords.extend(_matchable_aliases([str(alias).strip() for alias in region_record.get("aliases", []) or []]))
        for country_record in _countries_by_region().get(region_name, ()):
            region_keywords.append(str(country_record.get("name", "")).strip())
            region_keywords.extend(
                _matchable_aliases([str(alias).strip() for alias in country_record.get("aliases", []) or []])
            )

        primary_keywords = [region_name]
        primary_keywords.extend(_matchable_aliases([str(alias).strip() for alias in region_record.get("aliases", []) or []]))
        return LocationContext(
            preference="region_specific",
            value=region_name,
            label=region_name,
            region=region_name,
            keywords=_deduplicate_keywords(region_keywords),
            primary_keywords=_deduplicate_keywords(primary_keywords),
            strict=False,
        )

    country_record = _country_lookup().get(normalized_lookup_value)
    if country_record is None:
        raise ValueError("Selected country is not supported.")

    country_name = str(country_record.get("name", "")).strip()
    country_region = str(country_record.get("region", "")).strip()
    country_keywords = [country_name]
    country_keywords.extend(_matchable_aliases([str(alias).strip() for alias in country_record.get("aliases", []) or []]))
    primary_keywords = [country_name]
    return LocationContext(
        preference="country_specific",
        value=country_name,
        label=country_name,
        region=country_region,
        keywords=_deduplicate_keywords(country_keywords),
        primary_keywords=_deduplicate_keywords(primary_keywords),
        strict=True,
    )


def build_location_topic_key(topic: str, context: LocationContext) -> str:
    normalized_topic = str(topic or "").strip()
    if context.is_global:
        return normalized_topic
    scope_label = "region" if context.preference == "region_specific" else "country"
    return f"{normalized_topic} [{scope_label}: {context.value}]"


def get_location_signature(context: LocationContext) -> str:
    if context.is_global:
        return "global"
    return f"{context.preference}:{context.value.lower()}"


def build_query_location_hint(context: LocationContext) -> str:
    if context.preference == "region_specific":
        return f"Focus every search on the {context.value} market, geography, or policy context."
    if context.preference == "country_specific":
        return f"Focus every search on {context.value} and avoid generic global-only queries."
    return "Do not add geographic restrictions."


def build_prompt_location_summary(context: LocationContext) -> str:
    if context.preference == "region_specific":
        return (
            f"- location_preference=Region Specific\n"
            f"- selected_region={context.value}\n"
            f"- location_instruction=Keep the analysis centered on {context.value}."
        )
    if context.preference == "country_specific":
        return (
            f"- location_preference=Country Specific\n"
            f"- selected_country={context.value}\n"
            f"- location_instruction=Keep the analysis centered on {context.value}."
        )
    return (
        "- location_preference=Global\n"
        "- location_instruction=No geographic restriction was applied."
    )


def describe_location_context(context: LocationContext) -> Dict[str, Any]:
    scope = "global"
    if context.preference == "region_specific":
        scope = "region"
    elif context.preference == "country_specific":
        scope = "country"

    return {
        "preference": context.preference,
        "scope": scope,
        "label": context.label,
        "value": context.value,
        "region": context.region,
        "strict": context.strict,
    }


def _normalized_matchable_text(text: str) -> str:
    normalized = _normalize_phrase(text)
    if not normalized:
        return " "
    return f" {normalized} "


def _find_keyword_matches(text: str, keywords: Tuple[str, ...]) -> List[str]:
    if not keywords:
        return []

    normalized_text = _normalized_matchable_text(text)
    matches: List[str] = []
    seen = set()
    for keyword in keywords:
        phrase = _normalize_phrase(keyword)
        if not phrase or phrase in seen:
            continue
        if f" {phrase} " in normalized_text:
            seen.add(phrase)
            matches.append(keyword)
    return matches


def assess_location_relevance(
    *,
    url: str,
    title: str,
    text: str,
    context: LocationContext,
) -> Dict[str, Any]:
    if context.is_global:
        return {
            "location_score": 0,
            "location_matches": [],
            "primary_location_matches": [],
            "has_location_match": True,
            "domain_relevance": False,
            "generic_unrelated": False,
        }

    domain = _extract_domain(url)
    combined_text = " ".join(part for part in (title, text, url) if part).strip()
    normalized_text = _normalized_matchable_text(combined_text)
    primary_matches = _find_keyword_matches(combined_text, context.primary_keywords)
    all_matches = _find_keyword_matches(combined_text, context.keywords)
    has_location_match = bool(all_matches)
    domain_relevance = any(marker in domain or marker in normalized_text for marker in LOCATION_RELEVANT_DOMAIN_MARKERS)
    generic_marker_hit = any(f" {_normalize_phrase(marker)} " in normalized_text for marker in GENERIC_GLOBAL_MARKERS)
    generic_unrelated = (context.strict and not has_location_match) or (generic_marker_hit and not has_location_match)

    score = 0
    if has_location_match:
        score += 2
    if domain_relevance:
        score += 1
    if generic_unrelated:
        score -= 2

    return {
        "location_score": score,
        "location_matches": all_matches[:8],
        "primary_location_matches": primary_matches[:4],
        "has_location_match": has_location_match,
        "domain_relevance": domain_relevance,
        "generic_unrelated": generic_unrelated,
    }


def should_keep_search_result(result: Dict[str, Any], context: LocationContext) -> bool:
    if context.is_global:
        return True

    has_location_match = bool(result.get("has_location_match"))
    location_score = int(result.get("location_score", 0))
    generic_unrelated = bool(result.get("generic_unrelated"))

    if context.preference == "country_specific":
        return has_location_match and location_score >= 2 and not generic_unrelated

    return not generic_unrelated and (has_location_match or location_score >= 0)


def should_keep_scraped_content(score_payload: Dict[str, Any], context: LocationContext) -> bool:
    if context.is_global:
        return True

    has_location_match = bool(score_payload.get("has_location_match"))
    location_score = int(score_payload.get("location_score", 0))
    generic_unrelated = bool(score_payload.get("generic_unrelated"))

    if context.preference == "country_specific":
        return has_location_match and location_score >= 2 and not generic_unrelated

    return has_location_match and location_score >= 1 and not generic_unrelated
