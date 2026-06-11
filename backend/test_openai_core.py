import sys
import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from services.openai.core import (
    CompetitiveLandscapeDiscoveryCompany,
    CompetitiveLandscapeRelevanceDecision,
    CompetitiveLandscapeRelevanceResponse,
    _classify_competitive_landscape_relevance,
)


class OpenAICoreCompetitiveLandscapeTests(unittest.IsolatedAsyncioTestCase):
    async def test_relevance_classification_batches_large_company_sets(self) -> None:
        companies = [
            CompetitiveLandscapeDiscoveryCompany(
                company_name=f"Company {index}",
                market_role="Major Player",
                source_ids=[index],
            )
            for index in range(1, 7)
        ]
        evidence_by_source_id = {
            index: {
                "source_id": str(index),
                "title": f"Source {index}",
                "excerpt": f"Evidence for Company {index}",
                "url": f"https://example.com/{index}",
                "domain": "example.com",
            }
            for index in range(1, 7)
        }

        async def fake_structured_completion(client, *, operation, input_payload, response_model, max_output_tokens):
            del client, response_model, max_output_tokens
            prompt = input_payload[0]["content"]
            decisions = []
            for company in companies:
                if f"Company: {company.company_name}" not in prompt:
                    continue
                decisions.append(
                    CompetitiveLandscapeRelevanceDecision(
                        company_name=company.company_name,
                        classification="Direct Market Participant",
                        primary_business_fit=True,
                        industry_centrality=True,
                        operator_vs_supplier=True,
                        reason=f"{company.company_name} has direct market evidence.",
                    )
                )
            self.assertIn("structured_cl_relevance_classification_batch_", operation)
            return CompetitiveLandscapeRelevanceResponse(decisions=decisions)

        with patch(
            "services.openai.core._request_structured_completion",
            new=AsyncMock(side_effect=fake_structured_completion),
        ) as mock_completion:
            decisions = await _classify_competitive_landscape_relevance(
                AsyncMock(),
                topic="Utility-Scale Solar Market",
                companies=companies,
                evidence_by_source_id=evidence_by_source_id,
            )

        self.assertEqual(len(decisions), 6)
        self.assertEqual(mock_completion.await_count, 2)
        self.assertEqual(decisions["company 1"].classification, "Direct Market Participant")
        self.assertEqual(decisions["company 6"].classification, "Direct Market Participant")


if __name__ == "__main__":
    unittest.main()
