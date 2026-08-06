import unittest
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.html_export_service import build_html_export


class IESHtmlExportServiceTests(unittest.TestCase):
    def test_ies_export_renders_static_presentation_html(self):
        html_bytes, filename = build_html_export(
            result_payload={
                "section": "industry_earnings_snapshot",
                "title": "Industry Earnings Snapshot",
                "request": {
                    "industry": "Solar Power Equipment",
                    "filter_type": "country",
                    "filter_value": "Mexico",
                    "top_n": 2,
                },
                "summary": {
                    "industry": "Solar Power Equipment",
                    "country": "Mexico",
                    "filter_type": "country",
                    "filter_value": "Mexico",
                    "requested_top_n": 2,
                    "companies_returned": 2,
                    "companies_enriched": 2,
                    "median_revenue_growth": 12.3,
                    "median_operating_margin": 8.4,
                    "median_ebitda_margin": 11.1,
                    "median_ev_to_revenue": 4.2,
                    "median_ev_to_ebitda": 13.7,
                    "median_forward_pe": 18.9,
                    "eps_beat_rate": 66.7,
                    "median_five_day_price_reaction": 3.1,
                },
                "scatter_chart": {
                    "title": "Peer Positioning",
                    "x_label": "Revenue Growth (LQ YoY)",
                    "y_label": "Operating Margin (TTM)",
                    "bubble_size_label": "Revenue TTM",
                    "data": [
                        {
                            "ticker": "ABC",
                            "company_name": "Acme Solar",
                            "country": "Mexico",
                            "revenue_growth_lq_yoy": 15.0,
                            "operating_margin": 9.0,
                            "bubble_size": 120000000.0,
                            "is_outlier": False,
                        },
                        {
                            "ticker": "XYZ",
                            "company_name": "Zeta Energy",
                            "country": "Mexico",
                            "revenue_growth_lq_yoy": 8.5,
                            "operating_margin": 5.2,
                            "bubble_size": 86000000.0,
                            "is_outlier": True,
                        },
                    ],
                },
                "companies": [
                    {
                        "ticker": "ABC",
                        "company_name": "Acme Solar",
                        "exchange": "BMV",
                        "country": "Mexico",
                        "revenue_ttm": 120000000.0,
                        "revenue_growth_lq_yoy": 15.0,
                        "operating_margin": 9.0,
                        "ebitda_margin": 11.5,
                        "ev_to_revenue_ttm": 4.2,
                        "ev_to_ebitda_ttm": 13.7,
                    },
                    {
                        "ticker": "XYZ",
                        "company_name": "Zeta Energy",
                        "exchange": "BMV",
                        "country": "Mexico",
                        "revenue_ttm": 86000000.0,
                        "revenue_growth_lq_yoy": 8.5,
                        "operating_margin": 5.2,
                        "ebitda_margin": 7.1,
                        "ev_to_revenue_ttm": 5.1,
                        "ev_to_ebitda_ttm": 15.3,
                        "is_outlier": True,
                    },
                ],
                "metadata": {
                    "note": "Prepared for client sharing only.",
                },
            },
            meta_payload={
                "location": {"label": "Mexico"},
                "prepared": "August 6, 2026",
            },
            follow_up_payloads=[],
        )

        html_output = html_bytes.decode("utf-8")

        self.assertTrue(filename.endswith(".html"))
        self.assertIn('<svg viewBox="0 0 1000 560"', html_output)
        self.assertIn("Company Ranking Table", html_output)
        self.assertIn("Industry Earnings Snapshot", html_output)
        self.assertIn("Acme Solar", html_output)
        self.assertIn("Zeta Energy", html_output)
        self.assertNotIn("onClick=", html_output)
        self.assertNotIn("cursor:pointer", html_output)
        self.assertNotIn("cursor-pointer", html_output)
        self.assertNotIn("circle at 20% 16%", html_output)
        self.assertNotIn("circle at 20% 10%", html_output)
        self.assertNotIn('<text x="12" y="-10"', html_output)



if __name__ == "__main__":
    unittest.main()
