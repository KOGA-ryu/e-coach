"""Unit and integration tests for Coaching Insights, Metric Correlation, and Report Generation."""

import json
from pathlib import Path
import unittest

from vallens.analytics.correlations import FlawCorrelationEngine
from vallens.analytics.report import CoachingReportGenerator
from vallens.db.database import Database
from vallens.models import VodTag
from vallens.service import ValLensService

SAMPLE_MATCH_PATH = Path(__file__).parent.parent.parent / "data" / "sample_match.json"


class TestCoachingInsights(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.service = ValLensService(db=self.db)
        self.match = self.service.ingest_match_file(SAMPLE_MATCH_PATH)
        self.events = self.service.repo.get_events(self.match.match_id)
        self.engine = FlawCorrelationEngine(trade_window_ms=3000)
        self.report_gen = CoachingReportGenerator(engine=self.engine)

    def test_openings_analysis(self):
        openings = self.engine.analyze_openings(self.events)
        self.assertIn(0, openings)
        self.assertIn(1, openings)

        # In Round 0: player-ace-001 got FB on player-enemy-001
        self.assertEqual(openings[0].first_blood_puuid, "player-ace-001")
        self.assertEqual(openings[0].first_death_puuid, "player-enemy-001")
        self.assertEqual(openings[0].first_kill_weapon, "Ghost")

        # In Round 1: player-enemy-001 got FB on player-002
        self.assertEqual(openings[1].first_blood_puuid, "player-enemy-001")
        self.assertEqual(openings[1].first_death_puuid, "player-002")

    def test_trade_analysis(self):
        trades = self.engine.analyze_trades(self.events)
        self.assertEqual(len(trades), 6)

        # In Round 1: player-enemy-001 killed player-002 at 142000 ms,
        # then player-ace-001 killed player-enemy-001 at 150000 ms (delta = 8000 ms > 3000 ms window) -> untraded
        r1_death1 = [t for t in trades if t.victim_puuid == "player-002" and t.round_number == 1][0]
        self.assertFalse(r1_death1.is_traded)

    def test_tag_correlation_and_discrepancy(self):
        tags = [
            VodTag(
                match_id=self.match.match_id,
                timestamp_ms=45000,
                tag_category="Mechanics",
                tag_name="crosshair_placement",
                author_type="solo",
            ),
            VodTag(
                match_id=self.match.match_id,
                timestamp_ms=46000,
                tag_category="Mechanics",
                tag_name="crosshair_placement",
                author_type="coach",
            ),
            VodTag(
                match_id=self.match.match_id,
                timestamp_ms=172000,
                tag_category="Positioning",
                tag_name="over_peeking",
                author_type="coach",
            ),
        ]

        # Correlate tags with Ace's telemetry
        correlations = self.engine.correlate_tags_with_metrics("player-ace-001", self.events, tags)
        self.assertGreaterEqual(len(correlations), 2)

        # Coach vs Solo comparison
        comparison = self.engine.compare_coach_vs_solo(tags, tolerance_ms=3000)
        self.assertEqual(len(comparison.agreed_tags), 1)  # 45000 vs 46000 agreed
        self.assertEqual(len(comparison.blindspots), 1)   # 172000 missed by solo
        self.assertGreater(comparison.agreement_score, 0.0)

    def test_report_generation(self):
        tags = [
            VodTag(
                match_id=self.match.match_id,
                timestamp_ms=45000,
                tag_category="Mechanics",
                tag_name="crosshair_placement",
                author_type="solo",
            ),
            VodTag(
                match_id=self.match.match_id,
                timestamp_ms=172000,
                tag_category="Positioning",
                tag_name="over_peeking",
                author_type="coach",
            ),
        ]

        # Test report with coach notes
        notes = [
            {
                "round_number": 0,
                "timestamp_ms": 45000,
                "formatted_time": "00:45",
                "author_type": "coach",
                "text_note": "Great trigger discipline on Ascent B main",
                "has_audio": False,
                "audio_url": None,
            },
            {
                "round_number": 1,
                "timestamp_ms": 172000,
                "formatted_time": "02:52",
                "author_type": "coach",
                "text_note": "Audio memo recorded regarding repeek",
                "has_audio": True,
                "audio_url": "/api/notes/memo_test.webm",
            },
        ]

        # Markdown Report
        md = self.report_gen.generate_markdown(self.match, self.events, tags, player_puuid="player-ace-001", notes=notes)
        self.assertIn("# ValLens Coaching Report Card", md)
        self.assertIn("ASCENT", md)
        self.assertIn("Opening Duels:", md)
        self.assertIn("crosshair_placement", md)
        self.assertIn("Angle Isolation:", md)
        self.assertIn("Great trigger discipline", md)
        self.assertIn("Economy vs. Flaw Correlation Matrix", md)

        # HTML Report
        html = self.report_gen.generate_html(self.match, self.events, tags, player_puuid="player-ace-001", notes=notes)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("COACHING REPORT CARD", html)
        self.assertIn("trade efficiency", html.lower())
        self.assertIn("VALLENS COACHING REVIEW DOSSIER", html)
        self.assertIn("Great trigger discipline", html)
        self.assertIn("memo_test.webm", html)
        self.assertIn("window.print()", html)


if __name__ == "__main__":
    unittest.main()
