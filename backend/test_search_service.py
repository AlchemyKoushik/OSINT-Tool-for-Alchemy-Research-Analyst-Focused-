import unittest
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.location_service import LocationContext
from services.query_generator import build_fallback_queries
from services.search_service import (
    _is_quality_result,
    _result_sort_key,
    _search_concurrency_for_workflow,
    _should_keep_result_for_workflow,
)


class CompetitiveLandscapeSearchModeTests(unittest.TestCase):
    def test_competitive_landscape_keeps_directory_style_result_without_exact_overlap(self):
        result = {
            "url": "https://solarassociation.org/members-directory",
            "title": "Solar Association Members Directory",
            "snippet": "Browse member companies, exhibitors, regional participants, and private firms active in the market.",
            "domain": "solarassociation.org",
            "source_type": "general",
            "query_overlap_count": 0,
            "anchor_overlap_count": 0,
            "exact_query_phrase_match": False,
            "query_relevance_score": -4,
            "domain_quality_score": 1,
            "competitor_discovery_signal_score": 4,
        }

        self.assertTrue(_is_quality_result(result, workflow="competitive_landscape"))

    def test_trends_still_rejects_zero_overlap_general_result(self):
        result = {
            "url": "https://example.com/random-page",
            "title": "Generic Industry Commentary",
            "snippet": "This page discusses several unrelated business ideas without topic-specific signals or data.",
            "domain": "example.com",
            "source_type": "general",
            "query_overlap_count": 0,
            "anchor_overlap_count": 0,
            "exact_query_phrase_match": False,
            "query_relevance_score": -9,
            "domain_quality_score": 0,
            "competitor_discovery_signal_score": 0,
        }

        self.assertFalse(_is_quality_result(result, workflow="trends"))

    def test_competitive_landscape_relaxes_country_location_gate_for_market_directories(self):
        result = {
            "has_location_match": False,
            "location_score": 0,
            "generic_unrelated": False,
            "domain_relevance": False,
            "competitor_discovery_signal_score": 3,
            "query_overlap_count": 0,
            "domain_quality_score": 0,
        }
        context = LocationContext(preference="country_specific", value="Chile", label="Chile")

        self.assertTrue(_should_keep_result_for_workflow(result, context, "competitive_landscape"))
        self.assertFalse(_should_keep_result_for_workflow(result, context, "trends"))

    def test_competitive_landscape_rejects_low_value_login_page(self):
        result = {
            "url": "https://example.org/member-login",
            "title": "Member Login",
            "snippet": "Sign in to access the member directory and subscription portal.",
            "domain": "example.org",
            "source_type": "general",
            "query_overlap_count": 2,
            "anchor_overlap_count": 1,
            "exact_query_phrase_match": False,
            "query_relevance_score": 3,
            "domain_quality_score": 2,
            "competitor_discovery_signal_score": 2,
        }

        self.assertFalse(_is_quality_result(result, workflow="competitive_landscape"))

    def test_competitive_landscape_sort_prioritizes_discovery_signals(self):
        high_discovery = {
            "competitor_discovery_signal_score": 4,
            "location_score": 0,
            "temporal_boost": 1,
            "query_overlap_count": 0,
            "anchor_overlap_count": 0,
            "rank_score": 2,
            "score": 1,
        }
        high_authority = {
            "competitor_discovery_signal_score": 0,
            "location_score": 0,
            "temporal_boost": 1,
            "query_overlap_count": 2,
            "anchor_overlap_count": 0,
            "rank_score": 10,
            "score": 8,
        }

        self.assertGreater(
            _result_sort_key(high_discovery, workflow="competitive_landscape"),
            _result_sort_key(high_authority, workflow="competitive_landscape"),
        )

    def test_competitive_landscape_fallback_queries_cover_broader_dimensions(self):
        queries = build_fallback_queries(
            "utility solar",
            "competitive_landscape",
            location_context=LocationContext(preference="country_specific", value="Chile", label="Chile"),
        )

        self.assertEqual(len(queries), 10)
        query_blob = " ".join(queries).lower()
        self.assertIn("association members", query_blob)
        self.assertIn("conference participants", query_blob)
        self.assertIn("market directory", query_blob)
        self.assertIn("private companies", query_blob)
        self.assertNotIn("solar developers", query_blob)
        self.assertNotIn("renewable project developers", query_blob)
        self.assertNotIn("epc companies", query_blob)
        self.assertTrue(all("chile" in query.lower() for query in queries))

    def test_competitive_landscape_discovery_uses_safe_concurrency(self):
        self.assertEqual(_search_concurrency_for_workflow("competitive_landscape_discovery"), 1)


if __name__ == "__main__":
    unittest.main()
