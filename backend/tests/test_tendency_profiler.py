"""Tests for Opponent Tendency & Default Timing Profiler engine."""

import unittest
from vallens.db.database import Database
from vallens.db.repository import MatchRepository
from vallens.models import MatchEvent, MatchMetadata, MatchPlayer
from vallens.service import ValLensService


class TestTendencyProfiler(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.repo = MatchRepository(self.db)
        self.service = ValLensService(db=self.db)

        self.match_id = "test-match-tendencies"
        match = MatchMetadata(
            match_id=self.match_id,
            map_id="Ascent",
            game_mode="Competitive",
            match_duration=180000,
            timestamp=1700000000,
        )
        self.repo.insert_match(match)

        # Blue team (our team) & Red team (opponent team)
        p_ace = MatchPlayer(self.match_id, "p-ace", "Ace", "DEVIL", "Blue", "Jett")
        p_ally = MatchPlayer(self.match_id, "p-ally", "Ally", "111", "Blue", "Sova")
        p_foe1 = MatchPlayer(self.match_id, "p-foe1", "FoeReyna", "222", "Red", "Reyna")
        p_foe2 = MatchPlayer(self.match_id, "p-foe2", "FoeOmen", "333", "Red", "Omen")
        self.repo.insert_match_players([p_ace, p_ally, p_foe1, p_foe2])

        # Round 1: Red Attack Blitz Rush on A Site (First contact 8.0s, Plant 12.0s, Win)
        r1_events = [
            MatchEvent(self.match_id, 1, "round_start", 1000),
            MatchEvent(self.match_id, 1, "kill", 9000, player_puuid="p-foe1", pos_x=0.35, pos_y=0.15, metadata={"victim_puuid": "p-ally"}),
            MatchEvent(self.match_id, 1, "plant", 13000, player_puuid="p-foe2", pos_x=0.35, pos_y=0.14),
            MatchEvent(self.match_id, 1, "death", 20000, player_puuid="p-ace", pos_x=0.35, pos_y=0.15, metadata={"killer_puuid": "p-foe1"}),
            MatchEvent(self.match_id, 1, "round_end", 22000),
        ]
        self.repo.insert_events(r1_events)

        # Round 2: Red Attack Blitz Rush on A Site (First contact 10.0s, Plant 15.0s, Win)
        r2_events = [
            MatchEvent(self.match_id, 2, "round_start", 25000),
            MatchEvent(self.match_id, 2, "kill", 35000, player_puuid="p-foe1", pos_x=0.36, pos_y=0.15, metadata={"victim_puuid": "p-ally"}),
            MatchEvent(self.match_id, 2, "plant", 40000, player_puuid="p-foe2", pos_x=0.35, pos_y=0.14),
            MatchEvent(self.match_id, 2, "death", 45000, player_puuid="p-ace", metadata={"killer_puuid": "p-foe2"}),
            MatchEvent(self.match_id, 2, "round_end", 48000),
        ]
        self.repo.insert_events(r2_events)

        # Round 3: Red Attack Standard Default on B Site (Contact 30.0s, Plant 35.0s, Loss)
        r3_events = [
            MatchEvent(self.match_id, 3, "round_start", 50000),
            MatchEvent(self.match_id, 3, "plant", 85000, player_puuid="p-foe2", pos_x=0.28, pos_y=0.74),
            MatchEvent(self.match_id, 3, "death", 90000, player_puuid="p-foe1", metadata={"killer_puuid": "p-ace"}),
            MatchEvent(self.match_id, 3, "death", 92000, player_puuid="p-foe2", metadata={"killer_puuid": "p-ally"}),
            MatchEvent(self.match_id, 3, "round_end", 95000),
        ]
        self.repo.insert_events(r3_events)

        # Round 13: Red Defense Early Push (FoeReyna pushes at 6.0s into round on A-Main)
        r13_events = [
            MatchEvent(self.match_id, 13, "round_start", 100000),
            MatchEvent(self.match_id, 13, "kill", 106000, player_puuid="p-foe1", pos_x=0.70, pos_y=0.45, metadata={"victim_puuid": "p-ally"}),
            MatchEvent(self.match_id, 13, "death", 115000, player_puuid="p-foe1", metadata={"killer_puuid": "p-ace"}),
            MatchEvent(self.match_id, 13, "round_end", 120000),
        ]
        self.repo.insert_events(r13_events)

        # Round 14: Red Defense Fast Rotation (Blue plants B at 20.0s, FoeOmen rotates and kills at 22.5s -> 2.5s rotation)
        r14_events = [
            MatchEvent(self.match_id, 14, "round_start", 130000),
            MatchEvent(self.match_id, 14, "plant", 150000, player_puuid="p-ace", pos_x=0.28, pos_y=0.74),
            MatchEvent(self.match_id, 14, "kill", 152500, player_puuid="p-foe2", pos_x=0.28, pos_y=0.73, metadata={"victim_puuid": "p-ace"}),
            MatchEvent(self.match_id, 14, "round_end", 160000),
        ]
        self.repo.insert_events(r14_events)

    def test_tendency_report_structure(self):
        """Verify full tendency report contains all required metrics."""
        report = self.service.get_opponent_tendencies(self.match_id, target_team="Red")

        self.assertEqual(report["match_id"], self.match_id)
        self.assertEqual(report["target_team"], "Red")
        self.assertEqual(report["rounds_analyzed"], 5)
        self.assertEqual(report["attack_rounds"], 3)
        self.assertEqual(report["defense_rounds"], 2)

        # 1. Pace Analysis
        pace = report["pace_breakdown"]
        self.assertEqual(len(pace), 3)
        blitz = next(p for p in pace if p["tag"] == "blitz")
        self.assertEqual(blitz["count"], 2)
        self.assertAlmostEqual(blitz["percentage"], 66.7, delta=0.5)
        self.assertEqual(report["predominant_pace"], "Blitz Rush (<18s)")

        # 2. Site Preferences
        sites = report["site_preferences"]
        a_site = next((s for s in sites if "A" in s["site"]), None)
        self.assertIsNotNone(a_site)
        self.assertEqual(a_site["attempts"], 2)
        self.assertEqual(report["primary_site_target"], "A Site")

        # 3. Rotation Latency Profile
        rot = report["rotation_profile"]
        self.assertIn("avg_rotation_latency_sec", rot)
        self.assertIn("classification", rot)
        self.assertIn(rot["classification"], ["Hyper-Rotator", "Balanced / Reactive", "Disciplined Anchor"])

        # 4. Aggression Profile
        agg = report["aggression_profile"]
        self.assertGreaterEqual(agg["team_aggression_rate"], 40.0)
        self.assertGreaterEqual(len(agg["aggressive_players"]), 1)
        pusher = agg["aggressive_players"][0]
        self.assertEqual(pusher["name"], "FoeReyna")
        self.assertEqual(pusher["agent"], "Reyna")

        # 5. Counter-Strat Recommendations
        strats = report["counter_strats"]
        self.assertGreaterEqual(len(strats), 2)
        # Should detect fast execute and over-extension
        has_fast_rush_advice = any("Fast Execute" in s or "Delay" in s or "rush" in s.lower() for s in strats)
        self.assertTrue(has_fast_rush_advice)

    def test_empty_match_graceful_handling(self):
        """Verify empty match returns clean fallback report without errors."""
        empty_id = "empty-match-tendencies"
        match = MatchMetadata(
            match_id=empty_id,
            map_id="Ascent",
            game_mode="Competitive",
            match_duration=60000,
            timestamp=1700000000,
        )
        self.repo.insert_match(match)

        report = self.service.get_opponent_tendencies(empty_id, target_team="Red")
        self.assertEqual(report["rounds_analyzed"], 0)
        self.assertEqual(len(report["counter_strats"]), 1)
