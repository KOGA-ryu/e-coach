"""Tests for Multi-POV & Round-over-Round Side-by-Side Synchronizer."""

import unittest
from vallens.db.database import Database
from vallens.db.repository import MatchRepository
from vallens.models import MatchEvent, MatchMetadata, MatchPlayer, UtilityEvent, VodTag
from vallens.service import ValLensService


class TestRoundComparison(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.repo = MatchRepository(self.db)
        self.service = ValLensService(db=self.db)

        self.match_id = "test-match-round-compare"
        match = MatchMetadata(
            match_id=self.match_id,
            map_id="Ascent",
            game_mode="Competitive",
            match_duration=180000,
            timestamp=1700000000,
        )
        self.repo.insert_match(match)

        # Seed players
        p_ace = MatchPlayer(self.match_id, "p-ace", "Ace", "DEVIL", "Blue", "Jett")
        p_ally = MatchPlayer(self.match_id, "p-ally", "Ally", "111", "Blue", "Sova")
        p_foe1 = MatchPlayer(self.match_id, "p-foe1", "Foe1", "222", "Red", "Reyna")
        p_foe2 = MatchPlayer(self.match_id, "p-foe2", "Foe2", "333", "Red", "Omen")
        self.repo.insert_match_players([p_ace, p_ally, p_foe1, p_foe2])

        # Round 1 (Eco Loss): Ace dies untraded at 8.0s, Ally dies at 14.0s
        r1_events = [
            MatchEvent(self.match_id, 1, "round_start", 1000),
            MatchEvent(self.match_id, 1, "death", 9000, player_puuid="p-ace", pos_x=0.45, pos_y=0.70, metadata={"killer_puuid": "p-foe1"}),
            MatchEvent(self.match_id, 1, "death", 15000, player_puuid="p-ally", pos_x=0.30, pos_y=0.60, metadata={"killer_puuid": "p-foe2"}),
            MatchEvent(self.match_id, 1, "round_end", 20000),
        ]
        self.repo.insert_events(r1_events)

        # Round 2 (Full Buy Win): Foe1 kills Ally at 10.0s, Ace trades Foe1 at 11.2s (clean 1.2s trade!), then kills Foe2 at 18.0s
        r2_events = [
            MatchEvent(self.match_id, 2, "round_start", 25000),
            MatchEvent(self.match_id, 2, "kill", 35000, player_puuid="p-foe1", pos_x=0.50, pos_y=0.50, metadata={"victim_puuid": "p-ally"}),
            MatchEvent(self.match_id, 2, "kill", 36200, player_puuid="p-ace", pos_x=0.52, pos_y=0.51, metadata={"victim_puuid": "p-foe1"}),
            MatchEvent(self.match_id, 2, "plant", 40000, pos_x=0.60, pos_y=0.45),
            MatchEvent(self.match_id, 2, "kill", 43000, player_puuid="p-ace", pos_x=0.62, pos_y=0.44, metadata={"victim_puuid": "p-foe2"}),
            MatchEvent(self.match_id, 2, "round_end", 48000),
        ]
        self.repo.insert_events(r2_events)

        # Utility in Round 2
        util = UtilityEvent(
            match_id=self.match_id,
            round_number=2,
            timestamp_ms=35500,
            player_puuid="p-ace",
            player_name="Ace",
            agent_name="Jett",
            ability_name="Cloudburst",
            ability_slot="Ability1",
            category="smoke",
            targets_affected=1,
            assisted_kill=True,
            roi_score=85.0,
        )
        self.repo.insert_utility_events([util])

    def test_compare_rounds(self):
        """Verify comparison correctly computes round deltas and tactical takeaways."""
        result = self.service.compare_rounds(self.match_id, round_a=1, round_b=2, target_puuid="p-ace")

        self.assertIn("round_a", result)
        self.assertIn("round_b", result)
        self.assertIn("deltas", result)
        self.assertIn("key_takeaways", result)

        ra = result["round_a"]
        rb = result["round_b"]

        self.assertEqual(ra["round_number"], 1)
        self.assertFalse(ra["won"])
        self.assertEqual(rb["round_number"], 2)
        self.assertTrue(rb["won"])

        # Check plant
        self.assertFalse(ra["spike_planted"])
        self.assertTrue(rb["spike_planted"])

        # Check trades
        self.assertEqual(rb["trades_landed"], 1)

        # Check deltas
        deltas = result["deltas"]
        self.assertIn("duration_delta_sec", deltas)
        self.assertIn("first_blood_delta_sec", deltas)

        # Check takeaways
        takeaways = result["key_takeaways"]
        self.assertGreaterEqual(len(takeaways), 2)
        self.assertTrue(any("Round 1" in t and "Round 2" in t for t in takeaways))


if __name__ == "__main__":
    unittest.main()
