"""Unit tests for FrameSyncEngine and automated VOD-to-API frame alignment."""

import unittest
from pathlib import Path

from vallens.analytics.frame_sync import DetectedLandmark, FrameSyncEngine, FrameSyncResult
from vallens.models import MatchEvent, MatchMetadata


class TestFrameSyncEngine(unittest.TestCase):
    def setUp(self):
        self.engine = FrameSyncEngine()
        self.metadata = MatchMetadata(
            match_id="test_match_sync",
            map_id="/Game/Maps/Ascent/Ascent",
            game_mode="standard",
            match_duration=120000,
            timestamp=1690000000000,
            video_filepath="data/clips/vallens_f39bb79d_whiffed_spray_43s.mp4",
        )
        self.events = [
            MatchEvent(match_id="test_match_sync", round_number=0, event_type="round_start", event_time_ms=0),
            MatchEvent(match_id="test_match_sync", round_number=0, event_type="kill", event_time_ms=25000),
            MatchEvent(match_id="test_match_sync", round_number=0, event_type="kill", event_time_ms=32000),
            MatchEvent(match_id="test_match_sync", round_number=0, event_type="plant", event_time_ms=50000),
            MatchEvent(match_id="test_match_sync", round_number=1, event_type="round_start", event_time_ms=65000),
        ]

    def test_correlate_event_sequence_exact_offset(self):
        # Ground truth offset: +12.0s
        known_offset = 12.0
        synthetic_landmarks = [
            DetectedLandmark(time_sec=0.0 + known_offset, landmark_type="scene_cut", confidence=0.9),
            DetectedLandmark(time_sec=25.0 + known_offset, landmark_type="audio_spike", confidence=0.85),
            DetectedLandmark(time_sec=32.0 + known_offset, landmark_type="audio_spike", confidence=0.85),
            DetectedLandmark(time_sec=50.0 + known_offset, landmark_type="scene_cut", confidence=0.8),
            DetectedLandmark(time_sec=65.0 + known_offset, landmark_type="scene_cut", confidence=0.9),
        ]

        best_offset_ms, confidence, candidates = self.engine.correlate_event_sequence(
            synthetic_landmarks, self.events, search_window_sec=(0.0, 25.0), step_sec=0.2
        )

        self.assertAlmostEqual(best_offset_ms / 1000.0, 12.0, delta=0.3)
        self.assertGreaterEqual(confidence, 0.75)
        self.assertGreaterEqual(len(candidates), 1)

    def test_calibrate_from_point(self):
        # User aligns Round 1 kill (API time 25.0s) to video at 37.5s => offset = +12.5s (12500ms)
        result = self.engine.calibrate_from_point(
            match_id="test_match_sync",
            video_time_ms=37500,
            target_event_time_ms=25000,
            event_name="Ace Kill 1",
        )

        self.assertEqual(result.suggested_offset_ms, 12500)
        self.assertEqual(result.confidence, 1.0)
        self.assertEqual(result.strategy_used, "manual_landmark_calibration")
        self.assertIn("37.50s", result.diagnostic_notes[0])

    def test_analyze_and_align_file_not_found_fallback(self):
        meta = MatchMetadata(
            match_id="missing_video_match",
            map_id="Ascent",
            game_mode="standard",
            match_duration=100000,
            timestamp=1690000000000,
            video_filepath="non_existent_file.mp4",
        )
        result = self.engine.analyze_and_align(meta, self.events)
        self.assertIsInstance(result, FrameSyncResult)
        self.assertEqual(result.strategy_used, "event_round_start_fallback")
        self.assertIn("not found", result.diagnostic_notes[0])

    def test_analyze_and_align_real_clip(self):
        clip_path = Path("data/clips/vallens_f39bb79d_whiffed_spray_43s.mp4")
        if clip_path.exists():
            result = self.engine.analyze_and_align(self.metadata, self.events, video_filepath=clip_path)
            self.assertIsInstance(result, FrameSyncResult)
            self.assertIsNotNone(result.suggested_offset_ms)
            self.assertGreater(result.confidence, 0.0)
            self.assertTrue(len(result.diagnostic_notes) >= 1)


if __name__ == "__main__":
    unittest.main()
