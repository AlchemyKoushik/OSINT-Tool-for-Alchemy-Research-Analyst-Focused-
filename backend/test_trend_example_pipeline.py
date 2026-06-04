import unittest
from datetime import date
from pathlib import Path
import sys
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models.response_models import ExtractedExample
from services.html_export_service import build_html_export
from services.example_validation_service import attach_examples_to_insights, validate_examples
from services.location_service import LocationContext
from services.trend_example_research_service import _coverage_status, enrich_items_with_researched_examples


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

        async def fake_generate_queries(*, topic, section, trend_heading, trend_body, location_context):
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


if __name__ == "__main__":
    unittest.main()
