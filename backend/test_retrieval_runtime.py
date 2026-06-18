import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.crawlers.base import CrawlResultPayload
from services.external_client import _retry_delay_seconds
from services.location_service import LocationContext
from services.scrapers.core import _scrape_with_existing_stack_payload, collect_research_artifacts


class ExternalClientRetryTests(unittest.TestCase):
    @patch("services.external_client.random.uniform", return_value=0.25)
    def test_rate_limit_retry_delay_uses_backoff_and_jitter(self, _mock_uniform: MagicMock) -> None:
        delay = _retry_delay_seconds(0, RuntimeError("429 Too Many Requests"))
        self.assertAlmostEqual(delay, 2.25, places=2)

    @patch("services.external_client.random.uniform", return_value=0.1)
    def test_retry_after_hint_is_honored_with_jitter(self, _mock_uniform: MagicMock) -> None:
        delay = _retry_delay_seconds(1, RuntimeError("retry after 3s"))
        self.assertAlmostEqual(delay, 3.6, places=2)


class ScraperFallbackOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_stack_prefers_direct_http_before_other_fallbacks(self) -> None:
        with patch(
            "services.scrapers.core._scrape_with_httpx_payload",
            new=AsyncMock(return_value=("direct content", "", "")),
        ) as mock_direct, patch(
            "services.scrapers.core._scrape_with_scrapling_payload",
            new=AsyncMock(return_value=("", "", "should not run")),
        ) as mock_scrapling, patch(
            "services.scrapers.core.get_shared_playwright_fallback_crawler",
            new=AsyncMock(),
        ) as mock_playwright_getter, patch(
            "services.scrapers.core._scrape_with_scrapedo_payload",
            new=AsyncMock(return_value=("", "", "should not run")),
        ) as mock_scrapedo:
            payload = await _scrape_with_existing_stack_payload("https://example.com", AsyncMock())

        self.assertEqual(payload.crawler_used, "httpx_direct")
        self.assertTrue(payload.is_success)
        mock_direct.assert_awaited_once()
        mock_scrapling.assert_not_called()
        mock_playwright_getter.assert_not_called()
        mock_scrapedo.assert_not_called()

    async def test_existing_stack_uses_scrapedo_only_after_other_fallbacks_fail(self) -> None:
        playwright_crawler = AsyncMock()
        playwright_crawler.crawl.return_value = CrawlResultPayload(
            url="https://example.com",
            crawler_used="playwright",
            error="playwright failed",
        ).ensure_metrics()

        with patch(
            "services.scrapers.core._scrape_with_httpx_payload",
            new=AsyncMock(return_value=("", "", "direct failed")),
        ) as mock_direct, patch(
            "services.scrapers.core._scrape_with_scrapling_payload",
            new=AsyncMock(return_value=("", "", "scrapling failed")),
        ) as mock_scrapling, patch(
            "services.scrapers.core.get_shared_playwright_fallback_crawler",
            new=AsyncMock(return_value=playwright_crawler),
        ) as mock_playwright_getter, patch(
            "services.scrapers.core._scrape_with_scrapedo_payload",
            new=AsyncMock(return_value=("scrapedo content", "", "")),
        ) as mock_scrapedo:
            payload = await _scrape_with_existing_stack_payload("https://example.com", AsyncMock())

        self.assertEqual(payload.crawler_used, "scrapedo")
        self.assertTrue(payload.fallback_triggered)
        mock_direct.assert_awaited_once()
        mock_scrapling.assert_awaited_once()
        mock_playwright_getter.assert_awaited_once()
        playwright_crawler.crawl.assert_awaited_once()
        mock_scrapedo.assert_awaited_once()


class ScrapePrioritizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_collect_research_artifacts_prioritizes_stronger_candidates(self) -> None:
        observed_urls = []

        async def fake_scrape_batch(
            results,
            topic,
            section,
            session_id,
            location_context=None,
            start_index=1,
            timeout_seconds=None,
        ):
            del topic, section, session_id, location_context, start_index, timeout_seconds
            observed_urls.extend(str(result.get("url", "")) for result in results)
            return {"artifacts": [], "pages": [], "timed_out": False}

        with patch("services.scrapers.core._scrape_batch", new=AsyncMock(side_effect=fake_scrape_batch)), patch(
            "services.scrapers.core.upload_to_r2",
            return_value="manifest.json",
        ):
            await collect_research_artifacts(
                topic="Utility-Scale Solar Market",
                section="competitive_landscape",
                session_id="session-1",
                location_context=LocationContext(preference="country_specific", value="Chile", label="Chile"),
                search_results=[
                    {
                        "url": "https://weak-example.com/listing",
                        "source_type": "general",
                        "domain_quality_score": 0,
                        "query_relevance_score": 0,
                        "rank_score": 1,
                        "location_score": 0,
                        "competitor_discovery_signal_score": 0,
                    },
                    {
                        "url": "https://strong-example.org/company-profile",
                        "source_type": "report",
                        "domain_quality_score": 3,
                        "query_relevance_score": 4,
                        "rank_score": 7,
                        "location_score": 2,
                        "competitor_discovery_signal_score": 5,
                    },
                ],
                batch_size=2,
                target_usable_text_count=5,
                max_duration_seconds=30,
            )

        self.assertEqual(
            observed_urls[:2],
            [
                "https://strong-example.org/company-profile",
                "https://weak-example.com/listing",
            ],
        )


if __name__ == "__main__":
    unittest.main()
