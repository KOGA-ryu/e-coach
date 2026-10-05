"""Unit and integration tests for OBS automation, timeline synchronization, and EDL export."""

import json
from pathlib import Path
import tempfile
import unittest

from vallens.db.database import Database
from vallens.models import MatchEvent
from vallens.obs.client import MockObsClient
from vallens.obs.controller import CaptureController
from vallens.obs.exporter import EdlExporter
from vallens.obs.local_client import GameState, LocalClient, MockLocalClient
from vallens.obs.sync import TimelineSynchronizer
from vallens.service import ValLensService

SAMPLE_MATCH_PATH = Path(__file__).parent.parent.parent / "data" / "sample_match.json"


class TestObsPipeline(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.service = ValLensService(db=self.db)
        self.match = self.service.ingest_match_file(SAMPLE_MATCH_PATH)

    def test_timeline_synchronizer(self):
        # Round 0 starts at API ms = 20,000. Anchor video to 00:00:00 (offset = 0)
        sync = TimelineSynchronizer(round_0_start_api_ms=20_000, video_anchor_offset_ms=0)

        # An event at API 25,000 should map to video 5,000 ms
        vid_ms = sync.api_to_video_ms(25_000)
        self.assertEqual(vid_ms, 5_000)
        self.assertEqual(sync.video_to_api_ms(5_000), 25_000)

        # Video timecode formatting
        self.assertEqual(TimelineSynchronizer.ms_to_display_time(5_000), "00:05")
        self.assertEqual(TimelineSynchronizer.ms_to_display_time(65_000), "01:05")
        self.assertEqual(TimelineSynchronizer.ms_to_display_time(3665_000), "01:01:05")

        # SMPTE timecode (60 fps)
        # 1 second + 500 ms = 1s + 30 frames
        self.assertEqual(TimelineSynchronizer.ms_to_smpte(1500, fps=60), "00:00:01:30")

    def test_edl_and_chapter_export(self):
        events = self.service.repo.get_events(self.match.match_id)
        sync = TimelineSynchronizer(round_0_start_api_ms=0, video_anchor_offset_ms=0)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            edl_file = tmp / "match.edl"
            chapters_file = tmp / "match.chapters.txt"
            ffmeta_file = tmp / "match.ffmeta"

            # 1. CMX 3600 EDL
            EdlExporter.export_cmx3600_edl(events, sync, "match.mp4", edl_file)
            self.assertTrue(edl_file.exists())
            edl_text = edl_file.read_text(encoding="utf-8")
            self.assertIn("TITLE:", edl_text)
            self.assertIn("FCM: NON-DROP FRAME", edl_text)
            self.assertIn("Round 1 (Pistol)", edl_text)
            self.assertIn("FROM CLIP NAME: match.mp4", edl_text)

            # 2. Chapters text
            EdlExporter.export_chapters_txt(events, sync, chapters_file, include_kills=True)
            self.assertTrue(chapters_file.exists())
            ch_text = chapters_file.read_text(encoding="utf-8")
            self.assertIn("Round 1 (Pistol)", ch_text)
            self.assertIn("Kill:", ch_text)

            # 3. FFmpeg metadata
            EdlExporter.export_ffmetadata(events, sync, ffmeta_file)
            self.assertTrue(ffmeta_file.exists())
            ff_text = ffmeta_file.read_text(encoding="utf-8")
            self.assertIn(";FFMETADATA1", ff_text)
            self.assertIn("[CHAPTER]", ff_text)

    def test_lockfile_parser(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            lockfile_path = Path(tmp_dir) / "lockfile"
            lockfile_path.write_text("Valorant:1234:55555:secretPass123:https\n", encoding="utf-8")

            client = LocalClient(lockfile_path=lockfile_path)
            self.assertTrue(client.read_lockfile())
            self.assertEqual(client.port, 55555)
            self.assertEqual(client.password, "secretPass123")
            self.assertEqual(client.protocol, "https")

    def test_capture_controller_automation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_out = str(Path(tmp_dir) / "capture_test.mp4")
            local_client = MockLocalClient(initial_state=GameState.MENUS)
            obs_client = MockObsClient(default_output_path=video_out)

            controller = CaptureController(
                local_client=local_client,
                obs_client=obs_client,
                service=self.service,
            )
            controller.current_match_id = self.match.match_id

            # Step 1: In Menus (not recording)
            res1 = controller.poll_once()
            self.assertEqual(res1["state"], GameState.MENUS)
            self.assertFalse(obs_client.is_recording)

            # Step 2: Transition to PREGAME (Agent Select)
            local_client.set_state(GameState.PREGAME)
            controller.poll_once()
            self.assertFalse(obs_client.is_recording)

            # Step 3: Transition to INGAME -> Triggers OBS StartRecord
            local_client.set_state(GameState.INGAME)
            controller.poll_once()
            self.assertTrue(obs_client.is_recording)

            # Step 4: Transition to POSTGAME -> Triggers OBS StopRecord & EDL export
            local_client.set_state(GameState.POSTGAME)
            controller.poll_once()
            self.assertFalse(obs_client.is_recording)

            # Verify video path was persisted to SQLite
            updated_match = self.service.repo.get_match(self.match.match_id)
            self.assertEqual(updated_match.video_filepath, video_out)

            # Verify exported files exist alongside video
            self.assertTrue((Path(tmp_dir) / "capture_test.edl").exists())
            self.assertTrue((Path(tmp_dir) / "capture_test.chapters.txt").exists())
            self.assertTrue((Path(tmp_dir) / "capture_test.ffmeta").exists())


if __name__ == "__main__":
    unittest.main()
