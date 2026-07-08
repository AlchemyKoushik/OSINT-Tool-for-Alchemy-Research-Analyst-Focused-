import asyncio
import unittest
from datetime import date
from pathlib import Path
import sys
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models.request_models import AnalyzeRequest, PdfExportRequest
from models.response_models import (
    CompetitiveLandscapeDiscoveryAgentCompany,
    CompetitiveLandscapeDiscoveryAgentOutput,
    CompetitiveLandscapeDiscoveryCompany,
    CompetitiveLandscapeDiscoveryOutput,
    CompetitiveLandscapeProfileResponse,
    ExampleExtractionResponse,
    ExtractedExample,
)
from models.research_models import CompetitiveLandscapeProfile
from services.html_export_service import build_html_export
from services.example_validation_service import attach_examples_to_insights, validate_examples
from services.competitive_landscape_discovery_service import (
    _build_market_discovery_prompt,
    _fallback_company_queries as _fallback_discovery_company_queries,
    build_competitive_landscape_v2_discovery_bundle,
)
from services.location_service import LocationContext
from services.openai.core import CompetitiveLandscapeRelevanceDecision
from services.prompt_builder import (
    build_company_profile_extraction_payload,
    build_example_search_query_user_prompt,
    build_recent_company_developments_payload,
)
from services.trend_example_research_service import _build_fallback_queries
from services.trend_example_research_service import (
    _build_company_profile_fallback_overview,
    _company_profile_has_market_relevance,
    _coverage_status,
    _extract_company_focus_sentences,
    _filter_company_profile_facts,
    _filter_recent_developments,
    _has_retained_company_content,
    enrich_items_with_researched_examples,
)
from api.analyze import _repair_competitive_landscape_payload, run_analysis_request
from api.analyze import _resolve_competitive_landscape_mode


def _evidence_block(
    source_id: int,
    *,
    title: str,
    excerpt: str,
    published_date: str,
    source_tier: str = "Tier 1",
    url: str = "https://example.com/source",
    location: str = "",
):
    return {
        "source_id": source_id,
        "title": title,
        "excerpt": excerpt,
        "snippet": excerpt[:180],
        "published_date": published_date,
        "date": published_date,
        "source_tier": source_tier,
        "url": url,
        "publisher": "Example Publisher",
        "location": location,
    }


class TrendExamplePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.research_date = date(2026, 6, 1)
        self.trend_context = {
            "heading": "Battery Storage Partnerships Accelerate",
            "body": "Battery storage deployment is accelerating through partnerships and commercial agreements.",
            "topic": "battery storage",
            "location": "Germany",
        }

    def test_recent_example_kept(self):
        evidence = [
            _evidence_block(
                1,
                title="VoltPower and GridLink announce battery deployment",
                excerpt="VoltPower partnered with GridLink to deploy a 200 MWh battery storage project in Germany in March 2026.",
                published_date="2026-03-20",
                location="Germany",
            )
        ]
        examples, reasons = validate_examples(
            [
                ExtractedExample(
                    company="VoltPower",
                    event="partnership deployment",
                    text="VoltPower partnered with GridLink in Germany in March 2026 to deploy a 200 MWh battery storage project.",
                    event_date="March 2026",
                    source_ids=[1],
                    trend_fit_reason="Shows named commercial deployment supporting faster battery storage roll-out.",
                )
            ],
            evidence,
            research_date=self.research_date,
            trend_context=self.trend_context,
        )
        self.assertEqual(reasons, [])
        self.assertEqual(len(examples), 1)
        self.assertIn(examples[0].confidence, {"high", "medium"})

    def test_old_example_rejected_when_recent_evidence_exists(self):
        evidence = [
            _evidence_block(
                1,
                title="Legacy battery partnership",
                excerpt="VoltPower partnered with GridLink in Germany in May 2023 to deploy a battery storage project.",
                published_date="2023-05-12",
                location="Germany",
            ),
            _evidence_block(
                2,
                title="Recent storage market activity",
                excerpt="Battery storage companies in Germany announced multiple new deployments in 2026.",
                published_date="2026-02-01",
                location="Germany",
            ),
        ]
        examples, reasons = validate_examples(
            [
                ExtractedExample(
                    company="VoltPower",
                    event="partnership deployment",
                    text="VoltPower partnered with GridLink in Germany in May 2023 to deploy a battery storage project.",
                    event_date="May 2023",
                    source_ids=[1],
                    trend_fit_reason="Named battery deployment partnership.",
                )
            ],
            evidence,
            research_date=self.research_date,
            trend_context=self.trend_context,
        )
        self.assertEqual(examples, [])
        self.assertTrue(reasons)

    def test_old_fallback_allowed_when_no_recent_evidence_exists(self):
        evidence = [
            _evidence_block(
                1,
                title="Legacy hydrogen expansion",
                excerpt="HydroWorks expanded its hydrogen pilot facility in Germany in June 2024 to support industrial decarbonisation.",
                published_date="2024-06-18",
                location="Germany",
            )
        ]
        examples, reasons = validate_examples(
            [
                ExtractedExample(
                    company="HydroWorks",
                    event="facility expansion",
                    text="HydroWorks expanded its hydrogen pilot facility in Germany in June 2024 to support industrial decarbonisation.",
                    event_date="June 2024",
                    source_ids=[1],
                    trend_fit_reason="Named expansion still supports the trend where newer evidence is absent.",
                )
            ],
            evidence,
            research_date=self.research_date,
            trend_context={
                "heading": "Hydrogen Pilot Infrastructure Expands",
                "body": "Hydrogen pilot infrastructure is expanding in Germany.",
                "topic": "hydrogen infrastructure",
                "location": "Germany",
            },
            allow_low_confidence_fallback=True,
        )
        self.assertEqual(reasons, [])
        self.assertEqual(len(examples), 1)

    def test_generic_example_rejected(self):
        evidence = [
            _evidence_block(
                1,
                title="General storage commentary",
                excerpt="Companies are investing in battery storage across Europe.",
                published_date="2026-01-10",
            )
        ]
        examples, reasons = validate_examples(
            [
                ExtractedExample(
                    text="Companies are investing in battery storage.",
                    source_ids=[1],
                )
            ],
            evidence,
            research_date=self.research_date,
            trend_context=self.trend_context,
        )
        self.assertEqual(examples, [])
        self.assertIn("generic_text", reasons)

    def test_unsupported_company_rejected(self):
        evidence = [
            _evidence_block(
                1,
                title="VoltPower quarterly update",
                excerpt="VoltPower reported stable operations in Germany in March 2026.",
                published_date="2026-03-20",
                location="Germany",
            )
        ]
        examples, reasons = validate_examples(
            [
                ExtractedExample(
                    company="VoltPower",
                    event="acquisition",
                    text="VoltPower acquired GridLink in March 2026 to expand battery storage.",
                    event_date="March 2026",
                    source_ids=[1],
                    trend_fit_reason="Acquisition would support consolidation.",
                )
            ],
            evidence,
            research_date=self.research_date,
            trend_context=self.trend_context,
        )
        self.assertEqual(examples, [])
        self.assertTrue(reasons)

    def test_missing_extracted_date_but_source_date_exists_is_kept(self):
        evidence = [
            _evidence_block(
                1,
                title="VoltPower battery launch",
                excerpt="VoltPower launched a grid-scale battery storage solution in Germany to support utility customers.",
                published_date="2026-03-20",
                location="Germany",
            )
        ]
        examples, reasons = validate_examples(
            [
                ExtractedExample(
                    company="VoltPower",
                    event="launch",
                    text="VoltPower launched a grid-scale battery storage solution in Germany for utility customers.",
                    source_ids=[1],
                    trend_fit_reason="Named launch supporting battery storage adoption.",
                )
            ],
            evidence,
            research_date=self.research_date,
            trend_context=self.trend_context,
        )
        self.assertEqual(reasons, [])
        self.assertEqual(len(examples), 1)
        self.assertTrue(examples[0].year)

    def test_attachment_precision_rejects_company_overlap_only(self):
        validated_examples = [
            ExtractedExample(
                company="VoltPower",
                event="pricing action",
                text="VoltPower announced a solar inverter surcharge in Spain in April 2026.",
                event_date="April 2026",
                source_ids=[99],
                trend_fit_reason="Solar inverter pricing action.",
                confidence="high",
                source_quality="Tier 1",
                validation_score=10,
            )
        ]
        items = [
            {
                "heading": "Battery Storage Partnerships Accelerate",
                "body": "VoltPower is active in the battery storage market through commercial partnerships.",
                "source_ids": [1, 2],
                "examples": [],
            }
        ]
        attached = attach_examples_to_insights(
            items,
            validated_examples,
            trend_contexts={
                "battery storage partnerships accelerate": self.trend_context,
            },
        )
        self.assertEqual(attached[0]["examples"], [])

    def test_coverage_status_rules(self):
        strong = _coverage_status(
            [
                {"confidence": "high", "fallback_used": False},
                {"confidence": "medium", "fallback_used": False},
            ]
        )
        partial = _coverage_status(
            [
                {"confidence": "medium", "fallback_used": False},
            ]
        )
        none = _coverage_status([])
        self.assertEqual(strong, "strong")
        self.assertEqual(partial, "partial")
        self.assertEqual(none, "none")


class TrendExampleBackfillTests(unittest.IsolatedAsyncioTestCase):
    async def test_tenth_trend_processed_and_rendered(self):
        query_calls = []

        async def fake_generate_queries(*, topic, section, trend_heading, trend_body, location_context, perf_state=None):
            del topic, section, trend_body, location_context, perf_state
            query_calls.append(trend_heading)
            return [f"{trend_heading} announcement 2026"]

        async def fake_search_queries(topic, queries, freshness="high", location_context=None, workflow=None):
            return {
                "results": [
                    {
                        "url": "https://spaceagency.example/sbsp-demo",
                        "title": "Space agency SBSP demonstration mission",
                        "snippet": "A 2026 demonstration mission advanced space-based solar power.",
                        "domain": "spaceagency.example",
                    }
                ]
            }

        async def fake_collect_research_artifacts(**kwargs):
            return {
                "artifacts": [{"status": "success", "text_available": True, "text_key": "fake", "url": "https://spaceagency.example/sbsp-demo"}]
            }

        def fake_load_saved_sources(artifacts):
            return [
                {
                    "url": "https://spaceagency.example/sbsp-demo",
                    "title": "SBSP demonstration mission announced",
                    "content": "In April 2026, Orbital Nexus and ESA launched an SBSP demonstration mission for wireless power transmission.",
                    "artifact_type": "web",
                    "source_type": "government",
                    "domain": "spaceagency.example",
                    "location": "Europe",
                }
            ]

        def fake_prepare_processed_content(sources):
            return {
                "evidence_blocks": [
                    {
                        "source_id": "1",
                        "title": "SBSP demonstration mission announced",
                        "excerpt": "In April 2026, Orbital Nexus and ESA launched an SBSP demonstration mission for wireless power transmission.",
                        "url": "https://spaceagency.example/sbsp-demo",
                        "domain": "spaceagency.example",
                        "date": "2026-04-18",
                    }
                ]
            }

        async def fake_extract_examples(**kwargs):
            metadata = kwargs.get("metadata", "")
            if "Space-Based Solar Power Emerges as a Niche Growth Segment" not in metadata:
                return [], {"candidate_count": 0, "validated_count": 0, "rejection_reasons": []}
            return [
                ExtractedExample(
                    company="Orbital Nexus",
                    event="demonstration mission",
                    text="Orbital Nexus and ESA launched an SBSP demonstration mission in April 2026 to advance wireless power transmission.",
                    event_date="April 2026",
                    published_date="2026-04-18",
                    location="Europe",
                    example_type="project",
                    source_ids=[1],
                    confidence="high",
                    trend_fit_reason="Demonstrates concrete progress toward space-based solar power deployment.",
                    source_quality="Tier 1",
                    validation_score=11,
                )
            ], {"candidate_count": 1, "validated_count": 1, "rejection_reasons": []}

        items = [
            {
                "heading": f"Trend {index}",
                "body": f"Body {index}",
                "examples": [],
                "sources": [{"source_id": str(index), "title": f"Source {index}", "url": f"https://example.com/{index}", "domain": "example.com", "date": "2026-01-01"}],
                "source_ids": [index],
            }
            for index in range(1, 10)
        ]
        items.append(
            {
                "heading": "Space-Based Solar Power Emerges as a Niche Growth Segment",
                "body": "Space-based solar power is moving from research and feasibility into demonstration missions and consortium-backed programmes.",
                "examples": [],
                "sources": [{"source_id": "10", "title": "Source 10", "url": "https://example.com/10", "domain": "example.com", "date": "2026-01-01"}],
                "source_ids": [10],
            }
        )

        with patch("services.trend_example_research_service._generate_example_search_queries", side_effect=fake_generate_queries), \
            patch("services.trend_example_research_service.search_queries", side_effect=fake_search_queries), \
            patch("services.trend_example_research_service.collect_research_artifacts", side_effect=fake_collect_research_artifacts), \
            patch("services.trend_example_research_service.load_saved_sources", side_effect=fake_load_saved_sources), \
            patch("services.trend_example_research_service.prepare_processed_content", side_effect=fake_prepare_processed_content), \
            patch("services.trend_example_research_service.extract_validated_examples_from_evidence", side_effect=fake_extract_examples):
            enriched = await enrich_items_with_researched_examples(
                items=items,
                topic="space-based solar power",
                section="trends",
                location_context=LocationContext(),
                session_id="test-session",
            )

        tenth = enriched[9]
        self.assertIn("Space-Based Solar Power Emerges as a Niche Growth Segment", query_calls)
        self.assertTrue(tenth["examples"])
        self.assertEqual(tenth["example_coverage_status"], "partial")

        html_bytes, _ = build_html_export(
            result_payload={
                "section": "trends",
                "title": "Industry Trends",
                "items": enriched,
            },
            meta_payload={"topic": "space-based solar power", "location": {"label": "Global"}, "prepared": "Now"},
            follow_up_payloads=[],
        )
        html_output = html_bytes.decode("utf-8")
        self.assertIn("Examples", html_output)
        self.assertIn("Orbital Nexus and ESA launched an SBSP demonstration mission", html_output)

    async def test_competitive_landscape_backfill_reuses_cached_artifacts(self):
        search_calls = 0
        scrape_calls = 0
        profile_calls = 0
        developments_calls = 0

        async def fake_generate_queries(*, topic, section, trend_heading, trend_body, location_context, perf_state=None):
            del topic, section, trend_body, location_context, perf_state
            return [f'"{trend_heading}" Mexico solar projects']

        async def fake_search_queries(topic, queries, freshness="high", location_context=None, workflow=None):
            del topic, queries, freshness, location_context, workflow
            nonlocal search_calls
            search_calls += 1
            return {
                "results": [
                    {
                        "url": "https://example.com/enel",
                        "title": "Enel operates utility-scale solar plants in Mexico",
                        "snippet": "Enel added new utility-scale solar capacity in Mexico in 2025.",
                        "domain": "example.com",
                    }
                ]
            }

        async def fake_collect_research_artifacts(**kwargs):
            del kwargs
            nonlocal scrape_calls
            scrape_calls += 1
            return {
                "artifacts": [
                    {"status": "success", "text_available": True, "text_key": "fake", "url": "https://example.com/enel"}
                ]
            }

        def fake_load_saved_sources(artifacts):
            del artifacts
            return [
                {
                    "url": "https://example.com/enel",
                    "title": "Enel Green Power Mexico utility-scale solar portfolio in Mexico",
                    "content": "Enel Green Power Mexico operates utility-scale solar plants in Mexico. In 2025 Enel Green Power Mexico commissioned a new solar expansion in Mexico.",
                    "artifact_type": "web",
                    "source_type": "news",
                    "domain": "example.com",
                    "published_date": "2025-09-12",
                    "location": "Mexico",
                }
            ]

        async def fake_profile(**kwargs):
            del kwargs
            nonlocal profile_calls
            profile_calls += 1
            return CompetitiveLandscapeProfileResponse(
                profile=CompetitiveLandscapeProfile(
                    business_overview="Enel Green Power Mexico operates utility-scale solar plants in Mexico.",
                    key_company_facts=["Enel Green Power Mexico operates utility-scale solar plants in Mexico."],
                    competitive_positioning="Enel remains a direct operator with an active solar portfolio in Mexico.",
                    source_ids=[1],
                )
            )

        async def fake_recent_developments(**kwargs):
            del kwargs
            nonlocal developments_calls
            developments_calls += 1
            if developments_calls == 1:
                return ExampleExtractionResponse(examples=[])
            raise AssertionError("Backfill should reuse cached recent developments artifacts instead of calling OpenAI again.")

        items = [
            {
                "heading": "Enel Green Power Mexico",
                "body": "Initial overview",
                "segment": "major_players",
                "examples": [],
                "source_ids": [],
            }
        ]

        with patch("services.trend_example_research_service._generate_example_search_queries", side_effect=fake_generate_queries), \
            patch("services.trend_example_research_service.search_queries", side_effect=fake_search_queries), \
            patch("services.trend_example_research_service.collect_research_artifacts", side_effect=fake_collect_research_artifacts), \
            patch("services.trend_example_research_service.load_saved_sources", side_effect=fake_load_saved_sources), \
            patch("services.trend_example_research_service._extract_company_profile_from_evidence", side_effect=fake_profile), \
            patch("services.trend_example_research_service._extract_recent_company_developments_from_evidence", side_effect=fake_recent_developments), \
            patch("services.trend_example_research_service.resolve_cl_enrichment_concurrency", return_value=2):
            enriched = await enrich_items_with_researched_examples(
                items=items,
                topic="Distributed Solar Power Generation Market",
                section="competitive_landscape",
                location_context=LocationContext(preference="country_specific", value="Mexico"),
                session_id="test-session",
            )

        self.assertEqual(search_calls, 1)
        self.assertEqual(scrape_calls, 1)
        self.assertEqual(profile_calls, 1)
        self.assertEqual(developments_calls, 1)
        self.assertTrue(enriched[0]["examples"])
        self.assertEqual(enriched[0]["example_coverage_status"], "partial")


class CompetitiveLandscapeDiscoveryOptimizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_bundle_processes_candidates_with_bounded_parallelism(self):
        candidates = CompetitiveLandscapeDiscoveryAgentOutput(
            companies=[
                CompetitiveLandscapeDiscoveryAgentCompany(
                    company="Company A",
                    tier="Major Player",
                    confidence=95,
                    reasons=["large installed base"],
                ),
                CompetitiveLandscapeDiscoveryAgentCompany(
                    company="Company B",
                    tier="Mid-Sized Player",
                    confidence=88,
                    reasons=["active project pipeline"],
                ),
                CompetitiveLandscapeDiscoveryAgentCompany(
                    company="Company C",
                    tier="Emerging Player",
                    confidence=80,
                    reasons=["recent market entry"],
                ),
            ]
        )

        async def fake_discover(*, topic, location_context, max_candidates, perf_state=None):
            del topic, location_context, max_candidates, perf_state
            return candidates

        async def fake_generate_queries(*, topic, candidate, location_context, perf_state=None):
            del topic, location_context, perf_state
            await asyncio.sleep(0.05)
            return [f'"{candidate.company}" Mexico projects']

        async def fake_search_queries(topic, queries, freshness="high", location_context=None, workflow=None):
            del topic, queries, freshness, location_context, workflow
            await asyncio.sleep(0.05)
            return {
                "results": [
                    {
                        "url": "https://example.com/company",
                        "title": "Company validation source",
                        "snippet": "Company operates solar projects in Mexico.",
                        "domain": "example.com",
                    }
                ]
            }

        async def fake_collect_research_artifacts(**kwargs):
            del kwargs
            await asyncio.sleep(0.05)
            return {
                "artifacts": [
                    {"status": "success", "text_available": True, "text_key": "fake", "url": "https://example.com/company"}
                ]
            }

        def fake_load_saved_sources(artifacts):
            del artifacts
            return [
                {
                    "url": "https://example.com/company",
                    "title": "Company validation source",
                    "content": "Company operates solar projects in Mexico.",
                    "artifact_type": "web",
                    "source_type": "news",
                    "domain": "example.com",
                }
            ]

        async def passthrough_provider_limit(provider, operation, call, *, perf_state=None):
            del provider, operation, perf_state
            return await call()

        start = asyncio.get_running_loop().time()
        with patch("services.competitive_landscape_discovery_service.discover_competitive_landscape_candidates", side_effect=fake_discover), \
            patch("services.competitive_landscape_discovery_service._generate_company_validation_queries", side_effect=fake_generate_queries), \
            patch("services.competitive_landscape_discovery_service.search_queries", side_effect=fake_search_queries), \
            patch("services.competitive_landscape_discovery_service.collect_research_artifacts", side_effect=fake_collect_research_artifacts), \
            patch("services.competitive_landscape_discovery_service.load_saved_sources", side_effect=fake_load_saved_sources), \
            patch("services.competitive_landscape_discovery_service.run_with_cl_provider_limit", side_effect=passthrough_provider_limit), \
            patch("services.competitive_landscape_discovery_service.resolve_cl_discovery_concurrency", return_value=3):
            bundle = await build_competitive_landscape_v2_discovery_bundle(
                topic="Distributed Solar Power Generation Market",
                location_context=LocationContext(preference="country_specific", value="Mexico"),
                session_id="test-session",
            )
        elapsed = asyncio.get_running_loop().time() - start

        self.assertLess(elapsed, 0.35)
        self.assertEqual(len(bundle["query_diagnostics"]), 3)
        self.assertEqual(len(bundle["evidence_blocks"]), 3)


class CompetitiveLandscapeV2RegressionTests(unittest.IsolatedAsyncioTestCase):
    def test_competitive_landscape_defaults_to_v2(self):
        request = AnalyzeRequest(
            topic="Distributed Solar Power Generation Market",
            section="competitive_landscape",
        )
        self.assertEqual(_resolve_competitive_landscape_mode(request), "v2")

        explicit_v1_request = AnalyzeRequest(
            topic="Distributed Solar Power Generation Market",
            section="competitive_landscape",
            feature_flags={"competitive_landscape_v2": False},
        )
        self.assertEqual(_resolve_competitive_landscape_mode(explicit_v1_request), "v1")

    def test_pdf_export_request_accepts_session_only_payload(self):
        request_model = PdfExportRequest(session_id="session-123", meta={"topic": "Distributed Solar"})
        self.assertEqual(request_model.session_id, "session-123")
        self.assertEqual(request_model.result, {})

    def test_company_profile_fact_filter_rejects_generic_claims(self):
        filtered = _filter_company_profile_facts(
            [
                "Leading player in the market.",
                "Operates 2.9 GW of renewable capacity across 14 projects.",
                "Strong presence in Latin America.",
                "Signed PPAs covering 420 MW of solar capacity.",
            ]
        )
        self.assertEqual(
            filtered,
            [
                "Operates 2.9 GW of renewable capacity across 14 projects.",
                "Signed PPAs covering 420 MW of solar capacity.",
            ],
        )

    def test_company_profile_fact_filter_rejects_stale_forecast_language(self):
        filtered = _filter_company_profile_facts(
            [
                "A 2024 market report projected the company would reach 5 GW by 2025.",
                "Operates 2.9 GW of renewable capacity across 14 projects.",
            ]
        )
        self.assertEqual(
            filtered,
            ["Operates 2.9 GW of renewable capacity across 14 projects."],
        )

    def test_company_profile_fact_filter_rejects_project_construction_and_equipment_details(self):
        filtered = _filter_company_profile_facts(
            [
                "Began construction of a 200 MW solar project in 2025.",
                "The project uses 154,710 bifacial panels.",
                "Operates 2.9 GW of renewable capacity across Chile and Peru.",
            ]
        )
        self.assertEqual(
            filtered,
            ["Operates 2.9 GW of renewable capacity across Chile and Peru."],
        )

    def test_company_profile_fact_filter_rejects_fact_repeated_in_business_overview(self):
        filtered = _filter_company_profile_facts(
            [
                "Operates a renewable energy portfolio exceeding 2.0 GW across Chile.",
                "Part of Enel Group, one of the world's largest integrated power utilities.",
            ],
            business_overview="The company operates a renewable energy portfolio exceeding 2.0 GW across Chile.",
        )
        self.assertEqual(
            filtered,
            ["Part of Enel Group, one of the world's largest integrated power utilities."],
        )

    def test_company_profile_fact_filter_rejects_unsupported_claims_when_evidence_is_supplied(self):
        evidence = [
            _evidence_block(
                1,
                title="The Chefs' Warehouse Q1 2026 results",
                excerpt=(
                    "The Chefs' Warehouse reported trailing 12-month revenue of $4.26 billion as of March 31, 2026. "
                    "The specialty food distributor serves restaurants, hotels, caterers, and gourmet stores."
                ),
                published_date="2026-05-01",
                url="https://investors.chefswarehouse.com/q1-2026",
            )
        ]
        filtered = _filter_company_profile_facts(
            [
                "The Chefs' Warehouse reported trailing 12-month revenue of $4.26 billion as of March 31, 2026.",
                "The company holds the number-one share in the bottled water market segment, which contributed about 40% of revenue and EBIT in 2024.",
            ],
            evidence_blocks=evidence,
            company_name="The Chefs' Warehouse",
            source_ids=[1],
        )
        self.assertEqual(
            filtered,
            ["The Chefs' Warehouse reported trailing 12-month revenue of $4.26 billion as of March 31, 2026."],
        )

    def test_company_profile_market_relevance_requires_topic_overlap(self):
        evidence = [
            _evidence_block(
                1,
                title="The Chefs' Warehouse Q1 2026 results",
                excerpt=(
                    "The Chefs' Warehouse reported trailing 12-month revenue of $4.26 billion as of March 31, 2026. "
                    "The specialty food distributor serves restaurants, hotels, caterers, and gourmet stores across North America."
                ),
                published_date="2026-05-01",
                url="https://investors.chefswarehouse.com/q1-2026",
            )
        ]
        self.assertFalse(
            _company_profile_has_market_relevance(
                topic="Satellite launch market",
                company_name="The Chefs' Warehouse",
                evidence_blocks=evidence,
            )
        )
        self.assertTrue(
            _company_profile_has_market_relevance(
                topic="Food distribution market",
                company_name="The Chefs' Warehouse",
                evidence_blocks=evidence,
            )
        )

    def test_competitive_landscape_discovery_queries_are_market_aware_for_distribution_topics(self):
        candidate = CompetitiveLandscapeDiscoveryAgentCompany(
            company="US Foods",
            tier="Major Player",
            confidence=96,
            reasons=["large national foodservice distribution footprint"],
        )
        queries = _fallback_discovery_company_queries(
            topic="Food distribution market",
            candidate=candidate,
            location_context=LocationContext(preference="country_specific", value="United States"),
        )
        joined_queries = " ".join(queries).lower()
        self.assertIn("distribution", joined_queries)
        self.assertNotIn("solar", joined_queries)
        self.assertNotIn("utility-scale", joined_queries)

    def test_competitive_landscape_discovery_prompt_avoids_sector_specific_asset_bias(self):
        prompt = _build_market_discovery_prompt(
            topic="Food distribution market",
            location_context=LocationContext(preference="country_specific", value="United States"),
            max_candidates=12,
        )
        lowered = prompt.lower()
        self.assertIn("distribution footprint", lowered)
        self.assertIn("exclude product brands", lowered)
        self.assertNotIn("utility-scale assets", lowered)
        self.assertNotIn("installed capacity", lowered)

    def test_recent_development_filter_rejects_static_capacity_fact(self):
        filtered = _filter_recent_developments(
            [
                ExtractedExample(
                    company="Example Energy",
                    text="As of March 2023, Example Energy operated 2.9 GW of solar capacity.",
                    event_date="2023-03-01",
                    published_date="2023-03-01",
                    source_ids=[1],
                ),
                ExtractedExample(
                    company="Example Energy",
                    text="Example Energy announced a 200 MW solar project in Mexico in February 2026.",
                    event_date="2026-02-10",
                    published_date="2026-02-10",
                    source_ids=[2],
                ),
            ]
        )
        self.assertEqual(len(filtered), 1)
        self.assertIn("announced a 200 MW solar project", filtered[0].text)

    def test_recent_development_filter_rejects_stale_forecast_language(self):
        filtered = _filter_recent_developments(
            [
                ExtractedExample(
                    company="Example Energy",
                    text="A 2024 report projected Example Energy would reach 5 GW by 2025.",
                    event_date="2024-06-01",
                    published_date="2024-06-01",
                    source_ids=[1],
                ),
                ExtractedExample(
                    company="Example Energy",
                    text="Example Energy signed a 300 MW PPA in January 2026.",
                    event_date="2026-01-15",
                    published_date="2026-01-15",
                    source_ids=[2],
                ),
            ]
        )
        self.assertEqual(len(filtered), 1)
        self.assertIn("signed a 300 MW PPA", filtered[0].text)

    def test_recent_development_filter_rejects_mixed_company_roundup_source(self):
        mixed_text = (
            "In 2025 a separate deal framework for Cox to acquire Iberdrola's remaining Mexico assets was reported. "
            "In April 2025 First Solar lowered its 2025 sales and profit outlook. "
            "Neoen also reported record 2023 results and an accelerated path toward 10 GW by 2025. "
            "Conermex is listed as a Mexico based distributor and wholesaler."
        )
        filtered = _filter_recent_developments(
            [
                ExtractedExample(
                    company="Cox Energy",
                    text=mixed_text,
                    event_date="2025-01-01",
                    published_date="2025-01-01",
                    source_ids=[1],
                ),
            ],
            company_name="Cox Energy",
            evidence_blocks=[
                _evidence_block(
                    1,
                    title="Top Mexico Solar Energy Companies - Key Players & More",
                    excerpt=mixed_text,
                    published_date="2025-01-01",
                    url="https://www.mordorintelligence.com/industry-reports/mexico-solar-energy-market/companies",
                )
            ],
        )
        self.assertEqual(filtered, [])

    def test_company_profile_fallback_overview_does_not_invent_summary(self):
        overview = _build_company_profile_fallback_overview(
            company_name="Bright",
            evidence_blocks=[
                _evidence_block(
                    1,
                    title="Distributed Solar Market Outlook",
                    excerpt="A 2024 report projected the market would reach $8 billion by 2025.",
                    published_date="2024-05-01",
                )
            ],
        )
        self.assertEqual(overview, "")

    def test_company_focus_sentences_ignore_low_quality_topic_feed_text(self):
        sentences = _extract_company_focus_sentences(
            "Mukta Arts",
            [
                _evidence_block(
                    1,
                    title="mukta: Latest News & Videos, Photos about mukta",
                    excerpt=(
                        "18 Oct, 2015, 11:41 AM IST Mukta Arts rallies on reports of stake sale to Foxconn Technology. "
                        "6th June, 2025 Amaira - Review. "
                        "25th May, 2025 Amaira premiere show inaugurated by Culture Minister Ashish Shelar."
                    ),
                    published_date="2025-06-06",
                    url="https://economictimes.indiatimes.com/topic/mukta",
                )
            ],
        )
        self.assertEqual(sentences, [])

    def test_company_profile_prompt_defers_recent_developments_to_separate_call(self):
        prompt = build_company_profile_extraction_payload(
            topic="Distributed Solar Power Generation Market",
            company_name="Bright",
            existing_overview="",
            location_context=LocationContext(preference="country_specific", value="Mexico", label="Country / Mexico"),
            evidence_blocks=[],
        )
        self.assertIn("Do not generate recent_developments in this call.", prompt)
        self.assertIn("Always return an empty recent_developments list", prompt)
        self.assertIn("Reject number of panels, turbines, modules, or equipment-level details.", prompt)
        self.assertIn("Use company-level evidence first.", prompt)

    def test_recent_company_developments_prompt_uses_last_three_calendar_years_logic(self):
        prompt = build_recent_company_developments_payload(
            topic="Distributed Solar Power Generation Market",
            company_name="Bright",
            location_context=LocationContext(preference="country_specific", value="Mexico", label="Country / Mexico"),
            evidence_blocks=[],
        )
        self.assertIn("Current calendar year", prompt)
        self.assertIn("Previous calendar year", prompt)
        self.assertIn("Two calendar years prior", prompt)
        self.assertIn("Rank by strategic importance", prompt)
        self.assertIn("generic market roundup or competitor list", prompt)
        self.assertIn("never merge updates from multiple companies", prompt)

    def test_competitive_landscape_payload_repairs_empty_body_from_facts_and_positioning(self):
        payload = {
            "items": [
                {
                    "heading": "Zee Entertainment Enterprises Ltd",
                    "body": "",
                    "segment": "emerging_players",
                    "key_company_facts": [
                        "Zee Entertainment Enterprises Ltd holds broadcast and content distribution assets across India."
                    ],
                    "competitive_positioning": "",
                },
                {
                    "heading": "January. The FICCI-EY Media",
                    "body": "",
                    "segment": "emerging_players",
                    "key_company_facts": [],
                    "competitive_positioning": "",
                    "examples": [],
                },
            ]
        }

        repaired = _repair_competitive_landscape_payload(payload)

        self.assertEqual(len(repaired["items"]), 1)
        self.assertEqual(repaired["items"][0]["heading"], "Zee Entertainment Enterprises Ltd")
        self.assertTrue(repaired["items"][0]["body"])
        self.assertEqual(len(repaired["emerging_players"]), 1)

    def test_placeholder_company_body_does_not_count_as_retained_content(self):
        self.assertFalse(
            _has_retained_company_content(
                {
                    "heading": "Tips Industries",
                    "body": "Evidence-driven profile pending research for Tips Industries.",
                    "sources": [{"source_id": "1", "title": "Source", "url": "https://example.com"}],
                    "key_company_facts": [],
                    "competitive_positioning": "",
                    "examples": [],
                }
            )
        )

    def test_competitive_landscape_query_prompt_avoids_recent_developments_focus(self):
        prompt = build_example_search_query_user_prompt(
            topic="Utility-Scale Solar Market",
            section="competitive_landscape",
            trend_heading="Sonnedix",
            trend_body="Solar developer in Chile",
            location_context=LocationContext(preference="country_specific", value="Chile", label="Country / Chile"),
        )
        self.assertIn("high-quality company evidence", prompt)
        self.assertIn("Do not generate queries whose main purpose is recent developments", prompt)

    def test_competitive_landscape_fallback_queries_do_not_include_recent_developments_or_or(self):
        queries = _build_fallback_queries(
            topic="Utility-Scale Solar Market",
            section="competitive_landscape",
            trend_heading="Cox Energy",
            trend_body="Solar company",
            location_context=LocationContext(preference="country_specific", value="Chile", label="Country / Chile"),
        )
        self.assertTrue(queries)
        self.assertFalse(any("recent developments" in query.lower() for query in queries))
        self.assertFalse(any("or or" in query.lower() for query in queries))

    async def test_v2_discovery_validation_path_does_not_fallback(self):
        async def fake_execute_pipeline(**kwargs):
            return {
                "queries": ["distributed solar mexico"],
                "search_results": [
                    {
                        "url": "https://example.com/market",
                        "title": "Distributed Solar Mexico Market",
                        "snippet": "Market overview",
                        "domain": "example.com",
                    }
                ],
                "query_performance": {},
                "stage_errors": {},
                "artifact_bundle": {
                    "artifact_dir": "",
                    "manifest_path": "",
                    "artifacts": [],
                    "counts": {},
                    "pages": [],
                },
                "processed_payload": {
                    "processed_text": "Distributed solar market evidence in Mexico.",
                    "evidence_blocks": [
                        {
                            "source_id": 1,
                            "title": "Market source 1",
                            "excerpt": "Enel Green Power Mexico operates distributed solar assets in Mexico.",
                            "url": "https://example.com/enel",
                            "domain": "example.com",
                            "date": "2026-01-10",
                        },
                        {
                            "source_id": 2,
                            "title": "Market source 2",
                            "excerpt": "Bright installs and finances rooftop solar systems in Mexico.",
                            "url": "https://example.com/bright",
                            "domain": "example.com",
                            "date": "2026-02-15",
                        },
                    ],
                    "selected_urls": ["https://example.com/enel", "https://example.com/bright"],
                    "num_sources": 2,
                    "processing_chars": 128,
                    "source_scores": [],
                    "signal_weights": [],
                },
                "execution_time": {},
            }

        async def fake_discovery_bundle(**kwargs):
            return {
                "discovery_output": CompetitiveLandscapeDiscoveryOutput(
                    major_players=[
                        CompetitiveLandscapeDiscoveryCompany(
                            company_name="Enel Green Power Mexico",
                            market_role="Major Player",
                            source_ids=[1],
                        )
                    ],
                    emerging_players=[
                        CompetitiveLandscapeDiscoveryCompany(
                            company_name="Bright",
                            market_role="Emerging Player",
                            source_ids=[2],
                        )
                    ],
                ),
                "evidence_blocks": [
                    {
                        "source_id": 1,
                        "title": "Market source 1",
                        "excerpt": "Enel Green Power Mexico operates distributed solar assets in Mexico.",
                        "url": "https://example.com/enel",
                        "domain": "example.com",
                        "date": "2026-01-10",
                    },
                    {
                        "source_id": 2,
                        "title": "Market source 2",
                        "excerpt": "Bright installs and finances rooftop solar systems in Mexico.",
                        "url": "https://example.com/bright",
                        "domain": "example.com",
                        "date": "2026-02-15",
                    },
                ],
                "agent_output": CompetitiveLandscapeDiscoveryAgentOutput(
                    companies=[
                        CompetitiveLandscapeDiscoveryAgentCompany(
                            company="Enel Green Power Mexico",
                            tier="Major Player",
                            confidence=94,
                            reasons=["large distributed solar portfolio in Mexico"],
                        ),
                        CompetitiveLandscapeDiscoveryAgentCompany(
                            company="Bright",
                            tier="Emerging Player",
                            confidence=82,
                            reasons=["growing rooftop solar customer base in Mexico"],
                        ),
                    ]
                ),
                "query_diagnostics": [
                    {
                        "company": "Enel Green Power Mexico",
                        "tier": "Major Player",
                        "confidence": 94,
                        "reasons": ["large distributed solar portfolio in Mexico"],
                        "queries": ["Enel Green Power Mexico distributed solar assets Mexico"],
                        "search_results": 1,
                        "stored_sources": 1,
                        "evidence_blocks": 1,
                    },
                    {
                        "company": "Bright",
                        "tier": "Emerging Player",
                        "confidence": 82,
                        "reasons": ["growing rooftop solar customer base in Mexico"],
                        "queries": ["Bright rooftop solar Mexico"],
                        "search_results": 1,
                        "stored_sources": 1,
                        "evidence_blocks": 1,
                    },
                ],
            }

        async def fake_enrichment(**kwargs):
            return list(kwargs["items"])

        async def fake_classification(client, *, topic, companies, evidence_by_source_id):
            del client, topic, evidence_by_source_id
            return {
                company.company_name.lower(): CompetitiveLandscapeRelevanceDecision(
                    company_name=company.company_name,
                    classification="Direct Market Participant",
                    primary_business_fit=True,
                    industry_centrality=True,
                    operator_vs_supplier=True,
                    reason=f"{company.company_name} is a direct participant in the Mexico distributed solar market.",
                )
                for company in companies
            }

        request = AnalyzeRequest(
            topic="Distributed Solar Power Generation Market",
            section="competitive_landscape",
            location_preference="country_specific",
            location_value="Mexico",
            debug=True,
            feature_flags={"competitive_landscape_v2": True},
        )

        with patch("api.analyze.get_cached_result", return_value=None), \
            patch("api.analyze.set_cached_result"), \
            patch("api.analyze.update_session"), \
            patch("api.analyze.update_best_sources_for_topic"), \
            patch("api.analyze.update_domain_authority"), \
            patch("api.analyze.get_best_sources_for_topic", return_value=[]), \
            patch("api.analyze.get_feedback_adjustment", return_value={"avg_rating": 0.0, "rating_count": 0, "confidence_adjustment": 0}), \
            patch("api.analyze.execute_pipeline", side_effect=fake_execute_pipeline), \
            patch("api.analyze.build_competitive_landscape_v2_discovery_bundle", side_effect=fake_discovery_bundle), \
            patch("api.analyze.enrich_items_with_researched_examples", side_effect=fake_enrichment), \
            patch("services.openai.core.can_use_openai", return_value=True), \
            patch("services.openai.core.settings.OPENAI_API_KEY", "test-key"), \
            patch("services.openai.core._classify_competitive_landscape_relevance", side_effect=fake_classification):
            result = await run_analysis_request(request_model=request, progress_callback=None, diagnostics=None)

        diagnostics = result.get("debug", {}).get("competitive_landscape_diagnostics", {})
        self.assertFalse(diagnostics.get("fallback_used_due_to_exception"))
        self.assertEqual(diagnostics.get("validator_exception"), "")
        self.assertEqual(diagnostics.get("discovery_count"), 2)
        self.assertEqual(diagnostics.get("validated_count"), 2)
        self.assertEqual(diagnostics.get("rejected_count"), 0)
        self.assertEqual(diagnostics.get("final_major_count"), 1)
        self.assertEqual(diagnostics.get("final_emerging_count"), 1)
        self.assertEqual([item["heading"] for item in result["major_players"]], ["Enel Green Power Mexico"])
        self.assertEqual([item["heading"] for item in result["emerging_players"]], ["Bright"])
        self.assertNotIn("Join Solar Media", [item["heading"] for item in result["items"]])

    async def test_competitive_landscape_enrichment_removes_placeholder_and_low_quality_companies(self):
        items = [
            {"heading": "Tips Industries", "body": "Evidence-driven profile pending research for Tips Industries.", "segment": "emerging_players"},
            {
                "heading": "Mukta Arts",
                "body": (
                    "18 Oct, 2015, 11:41 AM IST Mukta Arts rallies on reports of stake sale to Foxconn Technology. "
                    "25th May, 2025 Amaira premiere show inaugurated by Culture Minister Ashish Shelar."
                ),
                "segment": "emerging_players",
            },
            {
                "heading": "Reliance Entertainment",
                "body": "Reliance Entertainment operates film, television, and digital entertainment assets in India.",
                "segment": "major_players",
                "key_company_facts": ["Operates media and entertainment assets across India."],
            },
        ]

        async def fake_research_examples_for_item(**kwargs):
            heading = kwargs["item"]["heading"]
            if heading == "Tips Industries":
                return {
                    "heading": heading,
                    "body": "Evidence-driven profile pending research for Tips Industries.",
                    "segment": "emerging_players",
                    "sources": [{"source_id": "1", "title": "Source", "url": "https://example.com/tips"}],
                    "_example_skip_reason": "insufficient_market_relevance_evidence",
                    "examples": [],
                    "key_company_facts": [],
                    "competitive_positioning": "",
                }
            if heading == "Mukta Arts":
                return {
                    "heading": heading,
                    "body": kwargs["item"]["body"],
                    "segment": "emerging_players",
                    "examples": [{"text": "Mukta Arts reported FY25 financial results.", "fallback_used": False}],
                    "key_company_facts": [],
                    "competitive_positioning": "",
                }
            return {
                "heading": heading,
                "body": kwargs["item"]["body"],
                "segment": "major_players",
                "examples": [],
                "key_company_facts": ["Operates media and entertainment assets across India."],
                "competitive_positioning": "Scaled incumbent with broad media footprint.",
            }

        with patch("services.trend_example_research_service._research_examples_for_item", side_effect=fake_research_examples_for_item):
            enriched = await enrich_items_with_researched_examples(
                items=items,
                topic="Entertainment Industry",
                section="competitive_landscape",
                location_context=LocationContext(preference="country_specific", value="India", label="Country / India"),
                session_id="session-123",
            )

        self.assertEqual([item["heading"] for item in enriched], ["Reliance Entertainment"])


if __name__ == "__main__":
    unittest.main()
