"""Unit tests for Pro Scouting Dossier & Offline Export Engine."""

from pathlib import Path
import unittest

from vallens.analytics.scouting_report import ScoutingReportGenerator
from vallens.db.database import Database
from vallens.service import ValLensService

SAMPLE_MATCH_PATH = Path(__file__).parent.parent.parent / "data" / "sample_match.json"


class TestScoutingReportGenerator(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.service = ValLensService(db=self.db)
        self.match = self.service.ingest_match_file(SAMPLE_MATCH_PATH)
        self.generator = ScoutingReportGenerator(
            repo=self.service.repo,
            trade_engine=self.service.trade_engine,
            win_prob_engine=self.service.win_prob_engine,
            career_radar_engine=self.service.career_radar_engine,
            utility_roi_engine=self.service.utility_roi_engine,
            economy_engine=self.service.economy_engine,
        )

    def test_generate_dossier_data(self):
        data = self.generator.generate_dossier_data(self.match.match_id)
        self.assertIsNotNone(data)
        self.assertEqual(data["match_id"], self.match.match_id)
        self.assertEqual(data["map_name"], "Ascent")
        self.assertIn("player", data)
        self.assertIn("career_radar", data)
        self.assertIn("trade_matrix", data)
        self.assertIn("win_probability", data)
        self.assertIn("utility_roi", data)
        self.assertIn("economy", data)
        self.assertIn("drills", data)

    def test_generate_standalone_html(self):
        html = self.generator.generate_standalone_html(self.match.match_id)
        self.assertIsNotNone(html)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("VAL<span>LENS</span> PRO SCOUTING DOSSIER", html)
        self.assertIn("6-Axis Tactical Skill Radar", html)
        self.assertIn("Trade Frag & Spacing Matrix", html)
        self.assertIn("Post-Match Win Expectancy Curve", html)
        self.assertIn("window.print()", html)
        self.assertIn("@media print", html)


if __name__ == "__main__":
    unittest.main()
