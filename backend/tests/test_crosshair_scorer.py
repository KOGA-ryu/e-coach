"""Tests for Offline Crosshair Placement & Corner Peeking Precision Scorer."""

import unittest
from vallens.db.database import Database
from vallens.db.repository import MatchRepository
from vallens.models import MatchEvent, MatchMetadata, MatchPlayer
from vallens.service import ValLensService


class TestCrosshairScorer(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.repo = MatchRepository(self.db)
        self.service = ValLensService(db=self.db)

        self.match_id = "test-match-crosshair"
        match = MatchMetadata(
            match_id=self.match_id,
            map_id="Ascent",
            game_mode="Competitive",
            match_duration=120000,
            timestamp=1700000000,
        )
        self.repo.insert_match(match)

        p_ace = MatchPlayer(self.match_id, "p-ace", "Ace", "DEVIL", "Blue", "Jett")
        p_foe = MatchPlayer(self.match_id, "p-foe", "Foe", "123", "Red", "Reyna")
        self.repo.insert_match_players([p_ace, p_foe])

        # Round 1: Ace (0.35, 0.15) kills Foe (0.45, 0.15) with pixel pre-aim (offset 3.5 deg)
        # Target bearing is 0.0 deg (along x axis). View yaw is 3.5 deg.
        r1_events = [
            MatchEvent(self.match_id, 1, "round_start", 1000),
            MatchEvent(
                self.match_id, 1, "kill", 9000,
                player_puuid="p-ace",
                pos_x=0.35, pos_y=0.15,
                metadata={
                    "victim": "p-foe",
                    "weapon": "Vandal",
                    "damage_type": "headshot",
                    "victim_pos": {"norm_x": 0.45, "norm_y": 0.15},
                    "view_yaw_deg": 3.5,
                },
            ),
            MatchEvent(self.match_id, 1, "round_end", 20000),
        ]
        self.repo.insert_events(r1_events)

        # Round 2: Ace (0.30, 0.20) kills Foe (0.30, 0.30) with clean micro-adjust (offset 10.0 deg)
        # Target bearing is 90.0 deg (along y axis). View yaw is 100.0 deg.
        r2_events = [
            MatchEvent(self.match_id, 2, "round_start", 25000),
            MatchEvent(
                self.match_id, 2, "kill", 32000,
                player_puuid="p-ace",
                pos_x=0.30, pos_y=0.20,
                metadata={
                    "victim": "p-foe",
                    "weapon": "Phantom",
                    "victim_pos": {"norm_x": 0.30, "norm_y": 0.30},
                    "view_yaw_deg": 100.0,
                },
            ),
            MatchEvent(self.match_id, 2, "round_end", 40000),
        ]
        self.repo.insert_events(r2_events)

        # Round 3: Foe kills Ace (Ace died with lazy crosshair / wide swing, offset 35.0 deg)
        # Ace was at (0.28, 0.74), Foe was at (0.38, 0.74). Bearing to Foe is 0.0 deg. View yaw 35.0 deg.
        r3_events = [
            MatchEvent(self.match_id, 3, "round_start", 50000),
            MatchEvent(
                self.match_id, 3, "death", 60000,
                player_puuid="p-ace",
                pos_x=0.28, pos_y=0.74,
                metadata={
                    "killer": "p-foe",
                    "weapon": "Vandal",
                    "killer_pos": {"norm_x": 0.38, "norm_y": 0.74},
                    "view_yaw_deg": 35.0,
                },
            ),
            MatchEvent(self.match_id, 3, "round_end", 70000),
        ]
        self.repo.insert_events(r3_events)

    def test_crosshair_evaluation(self):
        """Verify crosshair scorer extracts duels, computes angular errors and grades."""
        report = self.service.get_crosshair_scores(self.match_id, target_puuid="p-ace")

        self.assertEqual(report["match_id"], self.match_id)
        self.assertEqual(report["target_puuid"], "p-ace")
        self.assertEqual(report["player_name"], "Ace")
        self.assertEqual(report["duels_analyzed"], 3)

        engs = report["engagements"]
        self.assertEqual(len(engs), 3)

        # Duel 1: ~3.5 deg -> Grade S
        self.assertAlmostEqual(engs[0]["angular_offset_deg"], 3.5, delta=0.5)
        self.assertEqual(engs[0]["pre_aim_grade"], "S")
        self.assertEqual(engs[0]["grade_label"], "Pixel Pre-Aim")
        self.assertTrue(engs[0]["won"])

        # Duel 2: ~10.0 deg -> Grade A
        self.assertAlmostEqual(engs[1]["angular_offset_deg"], 10.0, delta=0.5)
        self.assertEqual(engs[1]["pre_aim_grade"], "A")
        self.assertEqual(engs[1]["grade_label"], "Clean Micro-Adjust")
        self.assertTrue(engs[1]["won"])

        # Duel 3: ~35.0 deg -> Grade F
        self.assertAlmostEqual(engs[2]["angular_offset_deg"], 35.0, delta=0.5)
        self.assertEqual(engs[2]["pre_aim_grade"], "F")
        self.assertEqual(engs[2]["grade_label"], "Lazy Crosshair")
        self.assertFalse(engs[2]["won"])

        # Aggregate rates
        self.assertAlmostEqual(report["pixel_pre_aim_rate"], 33.3, delta=0.5)
        self.assertAlmostEqual(report["clean_micro_adjust_rate"], 33.3, delta=0.5)
        self.assertAlmostEqual(report["wide_flick_rate"], 33.3, delta=0.5)

        # Pre-aim winrate (duels <= 16°: 2/2 = 100%) vs wide winrate (0/1 = 0%)
        self.assertEqual(report["pre_aim_win_rate"], 100.0)
        self.assertEqual(report["wide_flick_win_rate"], 0.0)

        # Coaching insights
        self.assertGreaterEqual(len(report["coaching_insights"]), 2)
        has_winrate_proof = any("Mechanical Impact Proof" in s for s in report["coaching_insights"])
        self.assertTrue(has_winrate_proof)

    def test_empty_match_graceful_handling(self):
        """Verify empty match returns clean zero-score report."""
        empty_id = "empty-match-crosshair"
        match = MatchMetadata(
            match_id=empty_id,
            map_id="Ascent",
            game_mode="Competitive",
            match_duration=60000,
            timestamp=1700000000,
        )
        self.repo.insert_match(match)

        report = self.service.get_crosshair_scores(empty_id, target_puuid="p-ace")
        self.assertEqual(report["duels_analyzed"], 0)
        self.assertEqual(report["overall_score"], 0.0)
        self.assertEqual(len(report["coaching_insights"]), 1)
