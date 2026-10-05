"""Unit tests for CareerRadarEngine."""

import unittest

from vallens.analytics.career_radar import CareerRadarEngine
from vallens.db.database import Database
from vallens.db.repository import MatchRepository
from vallens.models import MatchEvent, MatchMetadata, MatchPlayer, VodTag


class TestCareerRadarEngine(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.repo = MatchRepository(self.db)
        self.engine = CareerRadarEngine(self.repo)

        # Seed 3 sequential matches
        for i in range(1, 4):
            m_id = f"test_match_00{i}"
            match = MatchMetadata(
                match_id=m_id,
                map_id="/Game/Maps/Ascent/Ascent" if i < 3 else "/Game/Maps/Triad/Triad",
                game_mode="competitive",
                match_duration=1800000,
                timestamp=1700000000000 + (i * 86400000),
            )
            self.repo.insert_match(match)

            # Player
            p = MatchPlayer(
                match_id=m_id,
                player_puuid="puuid-ace",
                game_name="Ace",
                tag_line="NA1",
                team_id="Blue",
                character_id="add6443a-41bd-e414-f6ad-e58d267f4e95", # Jett
                kills=18 + (i * 2),
                deaths=12,
                assists=5,
                score=3500,
            )
            self.repo.insert_player(p)

            # Events
            events = [
                MatchEvent(match_id=m_id, round_number=0, event_type="round_start", event_time_ms=0),
                MatchEvent(match_id=m_id, round_number=0, event_type="kill", event_time_ms=25000, player_puuid="puuid-ace", pos_x=0.5, pos_y=0.5),
                MatchEvent(match_id=m_id, round_number=0, event_type="round_end", event_time_ms=60000),
            ]
            self.repo.insert_events(events)

            # Tags (flaws: over_peeking decreasing over time: 4 in m1, 2 in m2, 1 in m3)
            flaw_count = 4 if i == 1 else (2 if i == 2 else 1)
            for k in range(flaw_count):
                tag = VodTag(
                    match_id=m_id,
                    timestamp_ms=10000 + (k * 2000),
                    tag_category="Positioning",
                    tag_name="over_peeking",
                    author_type="coach",
                )
                self.repo.insert_tag(tag)

    def test_generate_career_profile(self):
        profile = self.engine.generate_career_profile(limit=10)
        self.assertEqual(profile.matches_reviewed, 3)
        self.assertGreaterEqual(profile.career_kd, 1.0)
        self.assertGreater(profile.rank_readiness_score, 0)
        self.assertIn("Immortal", profile.projected_rank)

        # Check 6 axes exist and are bounded [0, 100]
        axes = profile.radar_axes.to_dict()
        self.assertEqual(len(axes), 6)
        for val in axes.values():
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 100.0)

        # Check flaw trends (over_peeking should show a negative delta = improvement!)
        over_peek_trend = next((t for t in profile.flaw_trends if t.tag_name == "over_peeking"), None)
        self.assertIsNotNone(over_peek_trend)
        self.assertEqual(over_peek_trend.total_occurrences, 7)
        self.assertLess(over_peek_trend.delta_percentage, 0.0) # Confirms improvement

    def test_empty_profile_fallback(self):
        empty_db = Database(":memory:")
        empty_repo = MatchRepository(empty_db)
        empty_engine = CareerRadarEngine(empty_repo)

        profile = empty_engine.generate_career_profile()
        self.assertEqual(profile.matches_reviewed, 0)
        self.assertEqual(profile.rank_readiness_score, 50)
        self.assertEqual(profile.match_history, [])


if __name__ == "__main__":
    unittest.main()
