"""Unit tests for UtilityRoiEngine."""

import unittest

from vallens.analytics.utility_roi import UtilityRoiEngine
from vallens.db.database import Database
from vallens.db.repository import MatchRepository
from vallens.models import MatchEvent, MatchMetadata, MatchPlayer, UtilityEvent


class TestUtilityRoiEngine(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.repo = MatchRepository(self.db)
        self.engine = UtilityRoiEngine(self.repo)

        # Create sample match
        self.match = MatchMetadata(
            match_id="test_util_match_001",
            map_id="/Game/Maps/Ascent/Ascent",
            game_mode="competitive",
            match_duration=120000,
            timestamp=1700000000000,
        )
        self.repo.insert_match(self.match)

        # Create players: Jett and Omen
        self.p_jett = MatchPlayer(
            match_id=self.match.match_id,
            player_puuid="puuid-jett",
            game_name="Ace",
            tag_line="NA1",
            team_id="Blue",
            character_id="add6443a-41bd-e414-f6ad-e58d267f4e95", # Jett
            kills=10,
        )
        self.p_omen = MatchPlayer(
            match_id=self.match.match_id,
            player_puuid="puuid-omen",
            game_name="Smoker",
            tag_line="VAL",
            team_id="Blue",
            character_id="8e253930-4c05-31dd-1b6c-968525494517", # Omen
            assists=8,
        )
        self.repo.insert_player(self.p_jett)
        self.repo.insert_player(self.p_omen)

        # Events
        self.events = [
            MatchEvent(match_id=self.match.match_id, round_number=0, event_type="round_start", event_time_ms=0),
            MatchEvent(
                match_id=self.match.match_id,
                round_number=0,
                event_type="kill",
                event_time_ms=25000,
                player_puuid=self.p_jett.player_puuid,
                pos_x=0.45,
                pos_y=0.55,
                metadata={
                    "victim_name": "Enemy Reyna",
                    "assistants": [{"assistant_puuid": self.p_omen.player_puuid}],
                },
            ),
            MatchEvent(
                match_id=self.match.match_id,
                round_number=0,
                event_type="plant",
                event_time_ms=45000,
                pos_x=0.48,
                pos_y=0.52,
            ),
            MatchEvent(match_id=self.match.match_id, round_number=0, event_type="round_end", event_time_ms=65000),
        ]
        self.repo.insert_events(self.events)

    def test_extract_and_analyze_utility(self):
        report = self.engine.analyze_match_utility(self.match.match_id)
        self.assertEqual(report.match_id, self.match.match_id)
        self.assertGreater(report.total_casts, 0)
        self.assertGreater(report.overall_utility_rating, 0.0)

        # Verify flash/smoke stats populated
        self.assertIn("conversion_rate", report.flash_stats)
        self.assertIn("efficiency_rate", report.smoke_stats)

        # Verify stored utility events in database
        saved_events = self.repo.get_utility_events(self.match.match_id)
        self.assertEqual(len(saved_events), report.total_casts)

    def test_pre_existing_utility_events(self):
        custom_ev = UtilityEvent(
            match_id=self.match.match_id,
            round_number=0,
            timestamp_ms=15000,
            player_puuid=self.p_omen.player_puuid,
            player_name=self.p_omen.game_name,
            agent_name="Omen",
            ability_name="Dark Cover",
            ability_slot="Ability2",
            category="smoke",
            pos_x=0.4,
            pos_y=0.5,
            duration_ms=15000,
            targets_affected=3,
            assisted_kill=True,
            roi_score=92.0,
        )
        self.repo.delete_utility_events(self.match.match_id)
        self.repo.insert_utility_event(custom_ev)

        report = self.engine.analyze_match_utility(self.match.match_id, force_recompute=False)
        self.assertEqual(report.total_casts, 1)
        self.assertEqual(report.smoke_stats["total_casts"], 1)
        self.assertEqual(report.smoke_stats["efficiency_rate"], 100.0)


if __name__ == "__main__":
    unittest.main()
