import unittest

from backend.services.content_processor import clean_evidence_text, prepare_processed_content


class ContentProcessorRegressionTests(unittest.TestCase):
    def test_clean_evidence_text_recovers_broken_line_paragraphs(self) -> None:
        raw_text = """
        Cookie Policy
        Streaming platforms continue
        to invest in live sports rights
        to reduce churn and support
        ad-tier growth in 2025.

        Creator-led monetization expanded
        across global entertainment markets
        as short-form video and direct fan
        subscriptions gained momentum in 2024.
        """

        cleaned = clean_evidence_text(raw_text)

        self.assertIn("live sports rights", cleaned)
        self.assertIn("Creator-led monetization expanded", cleaned)

    def test_prepare_processed_content_keeps_fallback_rendered_source(self) -> None:
        source = {
            "url": "https://example.com/insights/media-outlook",
            "title": "Media Outlook 2025",
            "content": """
            Privacy Policy
            Streaming platforms continue
            to invest in live sports rights
            to reduce churn and support
            ad-tier growth in 2025.

            Creator-led monetization expanded
            across global entertainment markets
            as short-form video and direct fan
            subscriptions gained momentum in 2024.
            """,
            "artifact_type": "web",
        }

        processed = prepare_processed_content([source])

        self.assertEqual(processed["num_sources"], 1)
        self.assertEqual(len(processed["evidence_blocks"]), 1)
        self.assertIn("live sports rights", processed["processed_text"])


if __name__ == "__main__":
    unittest.main()
