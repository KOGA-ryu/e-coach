"""Unit tests for ClipTrimmer engine."""

from pathlib import Path
import tempfile
import unittest

from vallens.models import VodTag
from vallens.obs.trimmer import ClipTrimmer


class TestClipTrimmer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.trimmer = ClipTrimmer(clips_dir=self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_has_ffmpeg(self):
        self.assertTrue(self.trimmer.has_ffmpeg())

    def test_generate_synthetic_clip(self):
        out_path = Path(self.temp_dir.name) / "test_synth.mp4"
        res = self.trimmer.generate_synthetic_clip(2.0, out_path, label="Test Clip")
        self.assertTrue(res.exists())
        self.assertGreater(res.stat().st_size, 1000)

    def test_trim_clip_stream_and_reencode(self):
        # 1. Create a source clip
        src_path = Path(self.temp_dir.name) / "source_vod.mp4"
        self.trimmer.generate_synthetic_clip(4.0, src_path)

        # 2. Trim a 1.5s slice
        out_path = Path(self.temp_dir.name) / "trimmed_slice.mp4"
        res = self.trimmer.trim_clip(src_path, start_seconds=1.0, duration_seconds=1.5, output_path=out_path)
        self.assertTrue(res.exists())
        self.assertGreater(res.stat().st_size, 1000)

    def test_trim_moment_synthetic_fallback(self):
        # Moment for match without physical video file on disk
        res = self.trimmer.trim_moment(
            match_id="test-match-1234",
            timestamp_seconds=30.0,
            video_filepath=None,
            pre_roll=2.0,
            post_roll=1.0,
            label="crosshair_placement",
            round_number=2,
        )
        self.assertTrue(res["is_synthetic"])
        self.assertIn("crosshair_placement", res["filename"])
        self.assertEqual(res["start_seconds"], 28.0)
        self.assertEqual(res["duration_seconds"], 3.0)
        self.assertTrue(Path(res["output_path"]).exists())

    def test_batch_trim_tags(self):
        tags = [
            VodTag(tag_id=1, match_id="m1", timestamp_ms=15000, tag_category="Mechanics", tag_name="whiffed_spray", author_type="solo"),
            VodTag(tag_id=2, match_id="m1", timestamp_ms=45000, tag_category="Positioning", tag_name="over_peeking", author_type="coach"),
        ]
        clips = self.trimmer.batch_trim_tags("m1", tags, pre_roll=1.0, post_roll=1.0)
        self.assertEqual(len(clips), 2)
        for c in clips:
            self.assertTrue(Path(c["output_path"]).exists())
            self.assertIn("download_url", c)

    def test_missing_source_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.trimmer.trim_clip("/non/existent/video.mp4", 0.0, 5.0)

    def test_create_montage(self):
        moments = [
            {"timestamp_seconds": 15.0, "label": "whiffed_spray", "round_number": 1},
            {"timestamp_seconds": 45.0, "label": "over_peeking", "round_number": 2},
        ]
        montage = self.trimmer.create_montage(
            match_id="test-match-1234",
            moments=moments,
            pre_roll=1.0,
            post_roll=1.0,
            title="quick_flaws",
        )
        self.assertEqual(montage["segments_count"], 2)
        self.assertEqual(montage["total_duration_seconds"], 4.0)
        self.assertTrue(Path(montage["output_path"]).exists())
        self.assertGreater(montage["file_size_bytes"], 1000)
        self.assertIn("quick_flaws_montage.mp4", montage["filename"])

    def test_empty_moments_raises(self):
        with self.assertRaises(ValueError):
            self.trimmer.create_montage(match_id="test-match", moments=[])


if __name__ == "__main__":
    unittest.main()
