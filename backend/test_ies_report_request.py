import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
import sys

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from api.analyze import ies_report
from models.request_models import IESReportRequest


class IESReportRequestTests(unittest.TestCase):
    def test_legacy_country_payload_normalizes_to_country_scope(self):
        request = IESReportRequest(industry="Software - Infrastructure", country="United States", top_n=10)

        self.assertEqual(request.filter_type, "country")
        self.assertEqual(request.filter_value, "United States")
        self.assertEqual(request.country, "United States")

    def test_region_scope_requires_filter_value_and_normalizes_case(self):
        request = IESReportRequest(
            industry="Software - Infrastructure",
            filter_type="Region",
            filter_value="North America",
            top_n=15,
        )

        self.assertEqual(request.filter_type, "region")
        self.assertEqual(request.filter_value, "North America")
        self.assertIsNone(request.country)

    def test_global_scope_clears_filter_value(self):
        request = IESReportRequest(
            industry="Software - Infrastructure",
            filter_type="global",
            filter_value="should be ignored",
            top_n=5,
        )

        self.assertEqual(request.filter_type, "global")
        self.assertIsNone(request.filter_value)
        self.assertIsNone(request.country)


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.response


class IESReportRouteTests(unittest.IsolatedAsyncioTestCase):
    async def _run_route(self, payload, response_payload=None):
        fake_response = _FakeResponse(200, response_payload or {"ok": True})
        fake_client = _FakeAsyncClient(fake_response)

        with patch("api.analyze._read_json_payload", new=AsyncMock(return_value=payload)), patch(
            "api.analyze.httpx.AsyncClient",
            return_value=fake_client,
        ):
            response = await ies_report(object())

        return response, fake_client

    async def test_route_forwards_new_region_scope_payload(self):
        response, fake_client = await self._run_route(
            {
                "industry": "Software - Infrastructure",
                "filter_type": "region",
                "filter_value": "North America",
                "top_n": 12,
            },
            response_payload={"request": {"filter_type": "region"}},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_client.calls[0]["url"], "https://ies-api.alchemy-research.com/v1/reports/ies")
        self.assertEqual(
            fake_client.calls[0]["json"],
            {
                "industry": "Software - Infrastructure",
                "filter_type": "region",
                "filter_value": "North America",
                "top_n": 12,
            },
        )

    async def test_route_converts_legacy_country_payload(self):
        response, fake_client = await self._run_route(
            {
                "industry": "Software - Infrastructure",
                "country": "United States",
                "top_n": 10,
            },
            response_payload={"request": {"filter_type": "country"}},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            fake_client.calls[0]["json"],
            {
                "industry": "Software - Infrastructure",
                "filter_type": "country",
                "filter_value": "United States",
                "top_n": 10,
            },
        )

    async def test_route_omits_filter_value_for_global_scope(self):
        response, fake_client = await self._run_route(
            {
                "industry": "Software - Infrastructure",
                "filter_type": "global",
                "top_n": 8,
            },
            response_payload={"request": {"filter_type": "global"}},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            fake_client.calls[0]["json"],
            {
                "industry": "Software - Infrastructure",
                "filter_type": "global",
                "top_n": 8,
            },
        )


if __name__ == "__main__":
    unittest.main()
