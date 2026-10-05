"""Unit tests for ValLens Economy vs Flaw Correlation Engine."""

import unittest
from vallens.analytics.economy import EconomyCorrelationEngine
from vallens.models import MatchEvent, VodTag


class TestEconomyCorrelationEngine(unittest.TestCase):
    def setUp(self):
        self.engine = EconomyCorrelationEngine()

        # Mock events across 3 rounds
        self.events = [
            # Round 0: Pistol
            MatchEvent("m1", 0, "round_start", 0),
            MatchEvent("m1", 0, "kill", 25000, player_puuid="p1", metadata={"weapon": "ghost"}),
            MatchEvent("m1", 0, "round_end", 45000, metadata={"winning_team": "Blue", "round_result": "Eliminated"}),
            # Round 1: Eco / Save (Opponent full bought, player used classic/sheriff)
            MatchEvent("m1", 1, "round_start", 50000),
            MatchEvent("m1", 1, "death", 65000, player_puuid="p1", metadata={"weapon": "classic"}),
            MatchEvent("m1", 1, "round_end", 90000, metadata={"winning_team": "Red", "round_result": "Eliminated"}),
            # Round 2: Full Buy (Vandal)
            MatchEvent("m1", 2, "round_start", 100000),
            MatchEvent("m1", 2, "kill", 120000, player_puuid="p1", metadata={"weapon": "vandal"}),
            MatchEvent("m1", 2, "round_end", 145000, metadata={"winning_team": "Blue", "round_result": "Eliminated"}),
        ]

        # Mock subjective tags
        self.tags = [
            # 2 forced fights on Eco round 1
            VodTag("m1", 60000, "Decision", "forced_fight", "solo"),
            VodTag("m1", 64000, "Decision", "forced_fight", "coach"),
            # 1 over_peeking on Full Buy round 2
            VodTag("m1", 115000, "Positioning", "over_peeking", "solo"),
        ]

    def test_classify_rounds(self):
        rounds = self.engine.classify_rounds(self.events, player_puuid="p1")
        self.assertEqual(rounds[0].tier, "Pistol")
        self.assertTrue(rounds[0].won)

        self.assertEqual(rounds[1].tier, "Eco")
        self.assertFalse(rounds[1].won)

        self.assertEqual(rounds[2].tier, "Full Buy")
        self.assertTrue(rounds[2].won)

    def test_analyze_correlation(self):
        res = self.engine.analyze("m1", self.events, self.tags, player_puuid="p1")

        self.assertEqual(res.match_id, "m1")
        self.assertEqual(len(res.flaw_rows), 2)

        # Check forced_fight row
        ff = next(r for r in res.flaw_rows if r.tag_name == "forced_fight")
        self.assertEqual(ff.total_count, 2)
        self.assertEqual(ff.eco_count, 2)
        self.assertEqual(ff.dominant_tier, "Eco")
        self.assertEqual(ff.eco_share_pct, 100.0)

        # Check over_peeking row
        op = next(r for r in res.flaw_rows if r.tag_name == "over_peeking")
        self.assertEqual(op.total_count, 1)
        self.assertEqual(op.full_count, 1)
        self.assertEqual(op.dominant_tier, "Full Buy")

        # Check KPIs
        self.assertEqual(res.kpis["total_flaws"], 3)
        self.assertEqual(res.kpis["eco_flaws"], 2)
        self.assertAlmostEqual(res.kpis["eco_flaw_rate"], 66.7, places=1)
        self.assertEqual(res.kpis["full_buy_win_rate"], 100.0)
        self.assertEqual(res.kpis["eco_win_rate"], 0.0)

        # Check coaching insights generated
        self.assertTrue(any("Eco Over-Aggression" in ins for ins in res.coaching_insights))


if __name__ == "__main__":
    unittest.main()
