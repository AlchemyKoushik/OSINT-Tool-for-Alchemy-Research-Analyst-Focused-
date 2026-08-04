import os
import re
from typing import Any, Dict, List

import psycopg
from psycopg.rows import dict_row

from config.settings import settings

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ENV_FILE_PATH = os.path.join(BACKEND_DIR, ".env")
LEGACY_DATABASE_URL_ENV = "DATABASE)_URL"


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _resolve_database_url() -> str:
    candidates = (
        settings.DATABASE_URL,
        os.getenv("DATABASE_URL", ""),
        os.getenv(LEGACY_DATABASE_URL_ENV, ""),
    )
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized

    if os.path.exists(ENV_FILE_PATH):
        try:
            with open(ENV_FILE_PATH, "r", encoding="utf-8-sig") as handle:
                for raw_line in handle:
                    line = str(raw_line or "").strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue

                    key, value = line.split("=", 1)
                    normalized_key = re.sub(r"[^a-z0-9]", "", key.strip().lower())
                    if normalized_key != "databaseurl":
                        continue

                    normalized_value = value.strip().strip('"').strip("'")
                    if normalized_value:
                        return normalized_value
        except OSError:
            pass

    return ""


def _normalize_options(values: List[str]) -> List[Dict[str, str]]:
    options: List[Dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_text(value)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        options.append({"value": normalized, "label": normalized})
    return options


def get_ies_catalog() -> Dict[str, Any]:
    database_url = _resolve_database_url()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured.")

    query = """
        SELECT
            btrim(sector) AS sector,
            btrim(industry) AS industry
        FROM public.ies_company_metadata
        WHERE nullif(btrim(sector), '') IS NOT NULL
          AND nullif(btrim(industry), '') IS NOT NULL
        ORDER BY lower(btrim(sector)), lower(btrim(industry)), btrim(sector), btrim(industry)
    """

    rows: List[Dict[str, Any]]
    with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query)
            rows = list(cursor.fetchall())

    sector_order: List[str] = []
    sector_labels: Dict[str, str] = {}
    industries_by_sector: Dict[str, List[str]] = {}

    for row in rows:
        sector = _normalize_text(row.get("sector"))
        industry = _normalize_text(row.get("industry"))
        if not sector or not industry:
            continue

        sector_key = sector.casefold()
        if sector_key not in sector_labels:
            sector_order.append(sector_key)
            sector_labels[sector_key] = sector
            industries_by_sector[sector_key] = []

        industries_by_sector[sector_key].append(industry)

    sectors: List[Dict[str, Any]] = []
    industries_payload: Dict[str, List[Dict[str, str]]] = {}

    for sector_key in sector_order:
        sector_label = sector_labels[sector_key]
        sector_industries = _normalize_options(industries_by_sector.get(sector_key, []))
        sectors.append(
            {
                "value": sector_label,
                "label": sector_label,
                "industry_count": len(sector_industries),
            }
        )
        industries_payload[sector_label] = sector_industries

    return {
        "source_table": "public.ies_company_metadata",
        "sectors": sectors,
        "industries_by_sector": industries_payload,
    }
