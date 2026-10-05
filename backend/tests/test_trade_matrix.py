"""Unit tests for Trade Frag Efficiency & Spacing Matrix."""

from pathlib import Path
import unittest

from vallens.analytics.trade_matrix import TradeMatrixEngine
from vallens.db.database import Database
from vallens.models import MatchEvent, MatchPlayer, VodTag
from vallens.service import ValLensService

SAMPLE_MATCH_PATH = Path(__file__).parent.parent.parent / "data" / "sample_match.json"


class TestTradeMatrixEngine(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.service = ValLensService(db=self.db)
        self.match = self.service.ingest_match_file(SAMPLE_MATCH_PATH)
        self.engine = TradeMatrixEngine(self.service.repo, trade_window_ms=3000)

    def test_sample_match_trade_analysis(self):
        report = self.engine.analyze_match_trades(self.match.match_id)

        self.assertEqual(report.match_id, self.match.match_id)
        self.assertGreater(report.total_deaths, 0)
        self.assertGreaterEqual(report.match_trade_conversion_pct, 0.0)
        self.assertLessEqual(report.match_trade_conversion_pct, 100.0)

        # Check round summaries
        self.assertGreater(len(report.round_summaries), 0)
        r0 = report.round_summaries[0]
        self.assertEqual(r0.round_number, 0)

        # Check player stats
        self.assertGreater(len(report.player_stats), 0)
        ace_stats = next((p for p in report.player_stats if p.player_puuid == "player-ace-001"), None)
        self.assertIsNotNone(ace_stats)
        self.assertGreaterEqual(ace_stats.trade_rating, 15.0)
        self.assertLessEqual(ace_stats.trade_rating, 99.0)

    def test_instant_trade_and_untraded_isolation(self):
        mid = "custom-trade-test"
        players = [
            MatchPlayer(mid, "player-ace", "Ace", "DEV", "Blue", "jett-char"),
            MatchPlayer(mid, "player-ally", "Ally", "VAL", "Blue", "sova-char"),
            MatchPlayer(mid, "enemy-1", "Viper", "VIP", "Red", "viper-char"),
            MatchPlayer(mid, "enemy-2", "Chamber", "CHM", "Red", "chamber-char"),
        ]

        # Round 0:
        # 1. At t=10000ms: enemy-1 kills player-ace (pos_x=0.4, pos_y=0.2)
        # 2. At t=11100ms: player-ally kills enemy-1 (delta=1100ms -> Instant Trade!)
        # 3. At t=25000ms: enemy-2 kills player-ally (untraded opening isolation death)
        events = [
            MatchEvent(mid, 0, "round_start", 0),
            MatchEvent(mid, 0, "kill", 10000, player_puuid="enemy-1", metadata={"victim": "player-ace", "weapon": "Vandal"}),
            MatchEvent(mid, 0, "kill", 11100, player_puuid="player-ally", metadata={"victim": "enemy-1", "weapon": "Phantom"}),
            MatchEvent(mid, 0, "kill", 25000, player_puuid="enemy-2", metadata={"victim": "player-ally", "weapon": "Operator"}),
        ]

        tags = [
            VodTag(mid, 25000, "Positioning", "poor_spacing", "coach")
        ]

        report = self.engine.analyze_match_trades(mid, events=events, players=players, tags=tags)
        self.assertEqual(report.total_deaths, 3)
        self.assertEqual(report.total_traded_deaths, 1)

        # Death of player-ace was traded instantly
        ace_death = next(t for t in report.all_trade_events if t.victim_puuid == "player-ace")
        self.assertTrue(ace_death.is_traded)
        self.assertEqual(ace_death.trade_delay_ms, 1100)
        self.assertEqual(ace_death.trade_quality, "instant")
        self.assertEqual(ace_death.trader_puuid, "player-ally")

        # Death of player-ally at 25000 was untraded and flagged as isolated_death
        ally_death = next(t for t in report.all_trade_events if t.victim_puuid == "player-ally")
        self.assertFalse(ally_death.is_traded)
        self.assertEqual(ally_death.spacing_flaw, "isolated_death")

        # Player ally should have 1 trade given
        ally_stats = next(p for p in report.player_stats if p.player_puuid == "player-ally")
        self.assertEqual(ally_stats.trades_given, 1)


if __name__ == "__main__":
    unittest.main()
