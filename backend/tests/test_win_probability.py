"""Unit tests for Win Probability Curve & 1vX Clutch Evaluator."""

from pathlib import Path
import unittest

from vallens.analytics.win_probability import WinProbabilityEngine
from vallens.db.database import Database
from vallens.models import MatchEvent, MatchPlayer
from vallens.service import ValLensService

SAMPLE_MATCH_PATH = Path(__file__).parent.parent.parent / "data" / "sample_match.json"


class TestWinProbabilityEngine(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.service = ValLensService(db=self.db)
        self.match = self.service.ingest_match_file(SAMPLE_MATCH_PATH)
        self.engine = WinProbabilityEngine(self.service.repo, swing_threshold=0.30)

    def test_sample_match_probability(self):
        report = self.engine.calculate_match_probability(self.match.match_id)

        self.assertEqual(report.match_id, self.match.match_id)
        self.assertGreater(report.total_rounds, 0)
        self.assertIn(0, report.round_curves)

        # Timeline check
        self.assertGreater(len(report.match_timeline), 0)
        for pt in report.match_timeline:
            self.assertGreaterEqual(pt.team_a_prob, 0.0)
            self.assertLessEqual(pt.team_a_prob, 1.0)
            self.assertAlmostEqual(pt.team_a_prob + pt.team_b_prob, 1.0, places=2)

    def test_clutch_detection_and_momentum_swing(self):
        mid = "custom-winprob-test"
        players = [
            MatchPlayer(mid, "player-ace", "Ace", "DEV", "Blue", "jett-char"),
            MatchPlayer(mid, "enemy-1", "Viper", "VIP", "Red", "viper-char"),
            MatchPlayer(mid, "enemy-2", "Reyna", "REY", "Red", "reyna-char"),
        ]

        # Round 0:
        # Round starts (1v2 for Ace: Blue=1, Red=2)
        # At t=15000: Ace kills enemy-1 -> 1v1!
        # At t=20000: Ace kills enemy-2 -> Won round!
        events = [
            MatchEvent(mid, 0, "round_start", 0),
            MatchEvent(mid, 0, "kill", 15000, player_puuid="player-ace", metadata={"victim": "enemy-1", "weapon": "Vandal"}),
            MatchEvent(mid, 0, "kill", 20000, player_puuid="player-ace", metadata={"victim": "enemy-2", "weapon": "Vandal"}),
        ]

        report = self.engine.calculate_match_probability(mid, events=events, players=players)

        # Check clutch scenario
        self.assertGreaterEqual(report.clutches_attempted, 1)
        ace_clutch = next((c for c in report.clutch_scenarios if c.clutcher_puuid == "player-ace"), None)
        self.assertIsNotNone(ace_clutch)
        self.assertEqual(ace_clutch.scenario_type, "1v2")
        self.assertTrue(ace_clutch.won)
        self.assertEqual(ace_clutch.difficulty_score, 70.0)
        self.assertGreaterEqual(ace_clutch.clutch_rating, 75.0)

        # Swings check
        self.assertGreaterEqual(report.critical_swings_count, 1)


if __name__ == "__main__":
    unittest.main()
