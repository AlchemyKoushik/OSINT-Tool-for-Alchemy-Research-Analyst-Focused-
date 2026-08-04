import unittest
from pathlib import Path
import sys
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.ies_catalog_service import get_ies_catalog


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed_query = None

    def execute(self, query):
        self.executed_query = query

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, rows):
        self._cursor = _FakeCursor(rows)

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    @property
    def cursor_obj(self):
        return self._cursor


class IesCatalogServiceTests(unittest.TestCase):
    def test_get_ies_catalog_groups_and_deduplicates_sector_industry_pairs(self):
        rows = [
            {"sector": "Technology", "industry": "Software"},
            {"sector": "technology", "industry": "Software"},
            {"sector": "Technology", "industry": "Semiconductors"},
            {"sector": "Healthcare", "industry": "Biotechnology"},
            {"sector": "Healthcare", "industry": "Medical Devices"},
            {"sector": "Healthcare", "industry": "Medical Devices"},
        ]

        fake_connection = _FakeConnection(rows)

        with patch("services.ies_catalog_service._resolve_database_url", return_value="postgresql://example"), patch(
            "services.ies_catalog_service.psycopg.connect",
            return_value=fake_connection,
        ) as mock_connect:
            catalog = get_ies_catalog()

        mock_connect.assert_called_once()
        self.assertEqual(catalog["source_table"], "public.ies_company_metadata")
        self.assertEqual([item["value"] for item in catalog["sectors"]], ["Technology", "Healthcare"])
        self.assertEqual(catalog["sectors"][0]["industry_count"], 2)
        self.assertEqual(catalog["sectors"][1]["industry_count"], 2)
        self.assertEqual(
            [item["value"] for item in catalog["industries_by_sector"]["Technology"]],
            ["Software", "Semiconductors"],
        )
        self.assertEqual(
            [item["value"] for item in catalog["industries_by_sector"]["Healthcare"]],
            ["Biotechnology", "Medical Devices"],
        )


if __name__ == "__main__":
    unittest.main()
