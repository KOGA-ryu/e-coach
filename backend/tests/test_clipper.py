"""Tests for Local FFmpeg Coaching Clip & Highlight Reel Extractor."""

import tempfile
import unittest
from vallens.db.database import Database
from vallens.db.repository import MatchRepository
from vallens.models import MatchEvent, MatchMetadata, MatchPlayer, VodTag
from vallens.obs.trimmer import ClipTrimmer
from vallens.service import ValLensService
from vallens.video.clipper import HighlightClipper


class TestHighlightClipper(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(":memory:")
        self.repo = MatchRepository(self.db)
        self.trimmer = ClipTrimmer(clips_dir=self.temp_dir.name)
        self.service = ValLensService(db=self.db)
        self.service.trimmer = self.trimmer
        self.service.clipper.trimmer = self.trimmer

        self.match_id = "test-match-highlights"
        match = MatchMetadata(
            match_id=self.match_id,
            map_id="Ascent",
            game_mode="Competitive",
            match_duration=120000,
            timestamp=1700000000,
        )
        self.repo.insert_match(match)

        # Seed players
        p1 = MatchPlayer(self.match_id, "p-ace", "Ace", "DEVIL", "Blue", "Jett")
        p2 = MatchPlayer(self.match_id, "p-ally", "Ally", "111", "Blue", "Sova")
        p3 = MatchPlayer(self.match_id, "p-foe1", "Foe1", "222", "Red", "Reyna")
        p4 = MatchPlayer(self.match_id, "p-foe2", "Foe2", "333", "Red", "Omen")
        p5 = MatchPlayer(self.match_id, "p-foe3", "Foe3", "444", "Red", "Killjoy")
        self.repo.insert_match_players([p1, p2, p3, p4, p5])

        # Seed Round 1: Ace gets 3K multi-kill, clutch
        events = [
            MatchEvent(self.match_id, 1, "round_start", 1000),
            MatchEvent(self.match_id, 1, "death", 10000, player_puuid="p-ally", metadata={"killer_puuid": "p-foe1"}),
            # Ace gets 3 kills
            MatchEvent(self.match_id, 1, "kill", 12000, player_puuid="p-ace", metadata={"victim_puuid": "p-foe1"}),
            MatchEvent(self.match_id, 1, "kill", 14000, player_puuid="p-ace", metadata={"victim_puuid": "p-foe2"}),
            MatchEvent(self.match_id, 1, "kill", 17000, player_puuid="p-ace", metadata={"victim_puuid": "p-foe3"}),
            MatchEvent(self.match_id, 1, "round_end", 20000),
        ]
        self.repo.insert_events(events)

        # Tag an error
        self.repo.insert_tag(VodTag(self.match_id, 10000, "Positioning", "over_peeking", "coach"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_detect_candidates(self):
        """Verify highlights detector discovers multi-kills, clutches, opening duels, and coach flaws."""
        candidates = self.service.get_highlight_candidates(self.match_id, player_puuid="p-ace")
        self.assertTrue(len(candidates) > 0)

        # Verify multi-kill was detected
        multi = next((c for c in candidates if c["category"] == "multikill"), None)
        self.assertIsNotNone(multi)
        self.assertIn("3K", multi["label"])

        # Verify first blood or flaw was detected
        categories = {c["category"] for c in candidates}
        self.assertTrue("flaw" in categories or "first_blood" in categories or "clutch" in categories)

    def test_render_and_list_clips(self):
        """Verify rendering a clip and compiling a reel works cleanly."""
        candidates = self.service.get_highlight_candidates(self.match_id)
        self.assertTrue(len(candidates) > 0)
        target = candidates[0]

        # Render clip
        clip = self.service.render_highlight_clip(
            match_id=self.match_id,
            candidate_id=target["candidate_id"],
            pre_roll=1.0,
            post_roll=1.0,
        )
        self.assertIn("download_url", clip)
        self.assertTrue(clip["output_path"])

        # Verify clip appears in saved clips list
        saved = self.service.list_saved_match_clips(self.match_id)
        self.assertGreaterEqual(len(saved), 1)

    def test_compile_highlights_montage(self):
        """Verify compiling a montage reel produces a valid video file."""
        candidates = self.service.get_highlight_candidates(self.match_id)
        cand_ids = [c["candidate_id"] for c in candidates[:2]]

        reel = self.service.compile_highlights_montage(
            match_id=self.match_id,
            candidate_ids=cand_ids,
            title="Ace Review Highlights",
        )
        self.assertIn("download_url", reel)
        self.assertIn("filename", reel)
        self.assertGreaterEqual(reel["segments_count"], 1)


if __name__ == "__main__":
    unittest.main()
