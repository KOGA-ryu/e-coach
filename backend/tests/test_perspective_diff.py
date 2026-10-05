"""Unit and integration tests for Perspective Diffing and Cognitive Blindspots Engine."""

import unittest

from vallens.analytics.perspective import (
    PerspectiveDiffEngine,
    PerspectiveDiffResult,
)
from vallens.db.database import Database
from vallens.db.repository import MatchRepository
from vallens.models import MatchEvent, MatchMetadata, VodTag
from vallens.service import ValLensService


class TestPerspectiveDiffEngine(unittest.TestCase):
    def setUp(self):
        self.engine = PerspectiveDiffEngine(default_tolerance_ms=5000)
        self.match_id = "test-diff-match-001"
        self.events = [
            MatchEvent(match_id=self.match_id, round_number=0, event_type="round_start", event_time_ms=0),
            MatchEvent(
                match_id=self.match_id,
                round_number=0,
                event_type="death",
                event_time_ms=40000,
                metadata={"killer": "enemy-jett", "weapon": "Vandal"},
            ),
            MatchEvent(match_id=self.match_id, round_number=1, event_type="round_start", event_time_ms=100000),
            MatchEvent(
                match_id=self.match_id,
                round_number=1,
                event_type="death",
                event_time_ms=140000,
                metadata={"killer": "enemy-sova", "weapon": "Phantom"},
            ),
        ]

    def test_full_agreement(self):
        """When Solo and Coach tag the exact same flaws within tolerance."""
        tags = [
            VodTag(match_id=self.match_id, timestamp_ms=40000, tag_category="Mechanics", tag_name="crosshair_placement", author_type="solo", tag_id=1),
            VodTag(match_id=self.match_id, timestamp_ms=41000, tag_category="Mechanics", tag_name="crosshair_placement", author_type="coach", tag_id=2),
            VodTag(match_id=self.match_id, timestamp_ms=140000, tag_category="Positioning", tag_name="over_peeking", author_type="solo", tag_id=3),
            VodTag(match_id=self.match_id, timestamp_ms=142000, tag_category="Positioning", tag_name="over_peeking", author_type="coach", tag_id=4),
        ]

        result = self.engine.analyze_perspectives(self.match_id, self.events, tags, tolerance_ms=3000)

        self.assertEqual(result.agreement_score, 1.0)
        self.assertEqual(result.alignment_status, "EXCELLENT ALIGNMENT")
        self.assertEqual(result.agreed_count, 2)
        self.assertEqual(result.blindspots_count, 0)
        self.assertEqual(result.self_criticisms_count, 0)
        self.assertEqual(len(result.blindspots), 0)
        self.assertEqual(len(result.self_criticisms), 0)
        self.assertEqual(len(result.agreed_tags), 2)

    def test_blindspots_and_self_criticisms(self):
        """Test detection of coach blindspots and player self-criticisms."""
        tags = [
            # Agreed
            VodTag(match_id=self.match_id, timestamp_ms=40000, tag_category="Mechanics", tag_name="crosshair_placement", author_type="solo", tag_id=1),
            VodTag(match_id=self.match_id, timestamp_ms=41500, tag_category="Mechanics", tag_name="crosshair_placement", author_type="coach", tag_id=2),
            # Blindspot (Coach tagged, player missed)
            VodTag(match_id=self.match_id, timestamp_ms=140000, tag_category="Positioning", tag_name="over_peeking", author_type="coach", tag_id=3),
            # Self-criticism (Solo tagged, coach ignored)
            VodTag(match_id=self.match_id, timestamp_ms=70000, tag_category="Utility", tag_name="late_flash", author_type="solo", tag_id=4),
        ]

        result = self.engine.analyze_perspectives(self.match_id, self.events, tags, tolerance_ms=4000)

        # 1 agreed out of 3 total unique => 1/3 = 0.33
        self.assertEqual(result.agreement_score, 0.33)
        self.assertEqual(result.alignment_status, "SIGNIFICANT BLINDSPOTS")
        self.assertEqual(result.agreed_count, 1)
        self.assertEqual(result.blindspots_count, 1)
        self.assertEqual(result.self_criticisms_count, 1)

        # Verify blindspot details
        bs = result.blindspots[0]
        self.assertEqual(bs.tag_name, "over_peeking")
        self.assertEqual(bs.tag_category, "Positioning")
        self.assertEqual(bs.round_number, 2)
        self.assertIn("Death vs enemy-sova", bs.related_event)
        self.assertEqual(bs.severity, "HIGH")

        # Verify self-criticism details
        sc = result.self_criticisms[0]
        self.assertEqual(sc.tag_name, "late_flash")
        self.assertEqual(sc.round_number, 1)
        self.assertIn("Coach evaluation", sc.evaluation)

        # Verify Category divergence
        pos_div = next(c for c in result.category_divergence if c.category == "Positioning")
        self.assertEqual(pos_div.blindspots_count, 1)
        self.assertEqual(pos_div.coach_count, 1)
        self.assertEqual(pos_div.solo_count, 0)
        self.assertEqual(pos_div.alignment_rate, 0.0)

    def test_service_integration(self):
        """Test integration via ValLensService with in-memory database."""
        db = Database(":memory:")
        service = ValLensService(db=db)
        repo = MatchRepository(db)

        meta = MatchMetadata(
            match_id="svc-match-001",
            map_id="/Game/Maps/Ascent/Ascent",
            game_mode="Competitive",
            match_duration=1200000,
            timestamp=1690000000000,
        )
        repo.insert_match(meta)
        repo.insert_events([
            MatchEvent(match_id="svc-match-001", round_number=0, event_type="round_start", event_time_ms=0),
            MatchEvent(match_id="svc-match-001", round_number=0, event_type="death", event_time_ms=35000),
        ])

        service.add_vod_tag("svc-match-001", timestamp_ms=35000, category="Mechanics", name="crosshair_placement", author_type="solo")
        service.add_vod_tag("svc-match-001", timestamp_ms=36000, category="Mechanics", name="crosshair_placement", author_type="coach")
        service.add_vod_tag("svc-match-001", timestamp_ms=50000, category="Positioning", name="poor_spacing", author_type="coach")

        diff = service.get_perspective_diff("svc-match-001", tolerance_ms=4000)
        self.assertIsNotNone(diff)
        self.assertEqual(diff.total_solo_tags, 1)
        self.assertEqual(diff.total_coach_tags, 2)
        self.assertEqual(diff.agreed_count, 1)
        self.assertEqual(diff.blindspots_count, 1)
        self.assertEqual(len(diff.timeline_pips), 2)


if __name__ == "__main__":
    unittest.main()
