"""Unit and integration tests for ValLens API parsing, coordinate normalization, and SQLite persistence."""

import json
from pathlib import Path
import unittest

from vallens.analytics.projection import CoordinateProjector
from vallens.db.database import Database
from vallens.db.repository import MatchRepository
from vallens.models import MatchMetadata, VodTag
from vallens.riot.parser import MatchParser
from vallens.service import ValLensService

SAMPLE_MATCH_PATH = Path(__file__).parent.parent.parent / "data" / "sample_match.json"
MAPS_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "maps.json"


class TestValLensBackend(unittest.TestCase):
    def setUp(self):
        with open(SAMPLE_MATCH_PATH, "r", encoding="utf-8") as f:
            self.sample_match_data = json.load(f)
        self.in_memory_db = Database(":memory:")
        self.projector = CoordinateProjector(data_file=MAPS_DATA_PATH)
        self.parser = MatchParser(projector=self.projector)
        self.repo = MatchRepository(self.in_memory_db)

    def test_coordinate_projection(self):
        # Tree callout on Ascent: world=(3980.9, -5938.8)
        norm_x, norm_y = self.projector.world_to_norm("/Game/Maps/Ascent/Ascent", 3980.9, -5938.8)
        self.assertTrue(0.0 <= norm_x <= 1.0)
        self.assertTrue(0.0 <= norm_y <= 1.0)
        self.assertAlmostEqual(norm_x, 0.3982, places=2)
        self.assertAlmostEqual(norm_y, 0.2946, places=2)

        # Test pixel conversion for a 1024x1024 minimap canvas
        px, py = self.projector.world_to_pixel("/Game/Maps/Ascent/Ascent", 3980.9, -5938.8, 1024, 1024)
        self.assertTrue(400 <= px <= 415)
        self.assertTrue(295 <= py <= 308)

    def test_match_parser(self):
        metadata, events = self.parser.parse_match(self.sample_match_data)

        self.assertEqual(metadata.match_id, "f39bb79d-d81b-486d-b873-1991d3ec7a68")
        self.assertEqual(metadata.map_id, "/Game/Maps/Ascent/Ascent")
        self.assertEqual(metadata.match_duration, 2145000)

        # Ensure round starts, ends, plant, defuse, kills, deaths exist
        event_types = [e.event_type for e in events]
        self.assertIn("round_start", event_types)
        self.assertIn("round_end", event_types)
        self.assertIn("kill", event_types)
        self.assertIn("death", event_types)
        self.assertIn("plant", event_types)
        self.assertIn("defuse", event_types)

        # Kills and deaths should have normalized coordinates
        kills = [e for e in events if e.event_type == "kill"]
        self.assertEqual(len(kills), 6)  # 3 in round 0 + 3 in round 1
        for k in kills:
            self.assertIsNotNone(k.pos_x)
            self.assertTrue(0.0 <= k.pos_x <= 1.0)
            self.assertIsNotNone(k.pos_y)
            self.assertTrue(0.0 <= k.pos_y <= 1.0)
            self.assertIn("weapon", k.metadata)

    def test_repository_and_sqlite(self):
        metadata, events = self.parser.parse_match(self.sample_match_data)
        self.repo.insert_match(metadata)
        inserted_count = self.repo.insert_events(events)

        self.assertEqual(inserted_count, len(events))

        # Verify fetch match
        fetched = self.repo.get_match(metadata.match_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.match_id, metadata.match_id)

        # Update video path
        updated = self.repo.update_video_path(metadata.match_id, "/vods/ascent_match_01.mp4")
        self.assertTrue(updated)
        self.assertEqual(self.repo.get_match(metadata.match_id).video_filepath, "/vods/ascent_match_01.mp4")

        # Query filtered events
        r0_kills = self.repo.get_events(metadata.match_id, round_number=0, event_type="kill")
        self.assertEqual(len(r0_kills), 3)

        # Add review tags
        tag_id1 = self.repo.create_tag(
            VodTag(
                match_id=metadata.match_id,
                timestamp_ms=45000,
                tag_category="Mechanics",
                tag_name="crosshair_placement",
                author_type="solo",
            )
        )
        tag_id2 = self.repo.create_tag(
            VodTag(
                match_id=metadata.match_id,
                timestamp_ms=62000,
                tag_category="Positioning",
                tag_name="over_peeking",
                author_type="coach",
            )
        )

        tags = self.repo.get_tags(metadata.match_id)
        self.assertEqual(len(tags), 2)

        # Aggregate tags
        aggregations = self.repo.get_tag_aggregations(match_id=metadata.match_id)
        self.assertEqual(len(aggregations), 2)

    def test_service_end_to_end(self):
        service = ValLensService(db=self.in_memory_db, maps_file=MAPS_DATA_PATH)
        metadata = service.ingest_match_file(SAMPLE_MATCH_PATH, video_filepath="/videos/test.mp4")

        overview = service.get_match_overview(metadata.match_id)
        self.assertIsNotNone(overview)
        self.assertGreater(overview["total_events"], 0)
        self.assertEqual(overview["rounds_count"], 2)
        self.assertEqual(overview["total_kills"], 6)

        # Test heatmap extraction
        heatmap = service.get_player_heatmap(
            metadata.match_id,
            player_puuid="player-ace-001",
            event_type="kill",
        )
        self.assertEqual(len(heatmap), 3)  # Ace scored 3 kills
        for pt in heatmap:
            self.assertIn("norm_x", pt)
            self.assertIn("norm_y", pt)


if __name__ == "__main__":
    unittest.main()
