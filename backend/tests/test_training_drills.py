"""Unit and integration tests for TrainingRoutineEngine and Aim Lab exporter."""

import json
import unittest

from vallens.analytics.drills import TrainingRoutineEngine
from vallens.db.database import Database
from vallens.db.repository import MatchRepository
from vallens.models import MatchEvent, MatchMetadata, VodTag
from vallens.service import ValLensService


class TestTrainingDrills(unittest.TestCase):
    def setUp(self):
        self.engine = TrainingRoutineEngine()
        self.metadata = MatchMetadata(
            match_id="drill-test-001",
            map_id="/Game/Maps/Ascent/Ascent",
            game_mode="Competitive",
            match_duration=1800000,
            timestamp=1690000000000,
        )
        self.events = [
            MatchEvent(match_id="drill-test-001", round_number=0, event_type="round_start", event_time_ms=0),
            MatchEvent(
                match_id="drill-test-001",
                round_number=0,
                event_type="death",
                event_time_ms=35000,
                player_puuid="player-01",
                metadata={"killer": "enemy-01"},
            ),
        ]

    def test_routine_generation_with_flaws(self):
        tags = [
            VodTag(match_id="drill-test-001", timestamp_ms=35000, tag_category="Mechanics", tag_name="crosshair_placement", author_type="solo"),
            VodTag(match_id="drill-test-001", timestamp_ms=36000, tag_category="Positioning", tag_name="over_peeking", author_type="coach"),
        ]

        result = self.engine.generate_routine(self.metadata, self.events, tags, player_puuid="player-01")

        self.assertEqual(result.match_id, "drill-test-001")
        self.assertEqual(result.map_name, "Ascent")
        self.assertTrue(result.total_routine_duration_min > 0)
        self.assertTrue(len(result.prescriptions) >= 2)

        # Verify prescription fields
        p = result.prescriptions[0]
        self.assertIsNotNone(p.range_exercise)
        self.assertTrue(len(p.range_exercise.instructions) > 0)
        self.assertTrue(len(p.aim_trainer_scenarios) > 0)

        # Verify Aim Lab Playlist JSON
        playlist = result.aimlab_playlist
        self.assertIn("name", playlist)
        self.assertIn("tasks", playlist)
        self.assertTrue(len(playlist["tasks"]) > 0)
        task = playlist["tasks"][0]
        self.assertIn("taskName", task)
        self.assertIn("mode", task)

        # Verify Markdown Output
        self.assertIn("# ValLens Practice Routine — Ascent", result.markdown_routine)
        self.assertIn("Executive Protocol Summary", result.markdown_routine)
        self.assertIn("The Range:", result.markdown_routine)

    def test_default_fundamentals_fallback(self):
        """When no tags exist, generate core crosshair placement fundamentals."""
        result = self.engine.generate_routine(self.metadata, self.events, [], player_puuid="player-01")
        self.assertEqual(len(result.prescriptions), 1)
        self.assertEqual(result.prescriptions[0].tag_name, "crosshair_placement")
        self.assertEqual(result.primary_focus, "Crosshair Placement")

    def test_service_integration(self):
        db = Database(":memory:")
        service = ValLensService(db=db)
        repo = MatchRepository(db)

        repo.insert_match(self.metadata)
        repo.insert_events(self.events)
        service.add_vod_tag("drill-test-001", timestamp_ms=35000, category="Mechanics", name="panic_spray", author_type="solo")

        routine = service.get_training_routine("drill-test-001")
        self.assertIsNotNone(routine)
        self.assertEqual(routine.primary_focus, "Panic Spray")
        self.assertTrue(any(p.tag_name == "panic_spray" for p in routine.prescriptions))


if __name__ == "__main__":
    unittest.main()
