"""Unit and integration tests for ValLens review interface HTTP and REST server."""

import json
from pathlib import Path
import threading
import time
import unittest
import urllib.request

from vallens.db.database import Database
from vallens.server import run_server
from vallens.service import ValLensService

SAMPLE_MATCH_PATH = Path(__file__).parent.parent.parent / "data" / "sample_match.json"


class TestValLensServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = Database(":memory:")
        cls.service = ValLensService(db=cls.db)
        cls.match = cls.service.ingest_match_file(SAMPLE_MATCH_PATH)

        # Run on local port 8999
        cls.port = 8999
        cls.server = run_server(service=cls.service, port=cls.port, host="127.0.0.1")
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path: str) -> tuple[int, bytes, dict]:
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return resp.status, resp.read(), dict(resp.headers)

    def _post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _delete(self, path: str) -> tuple[int, dict]:
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url, method="DELETE")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_static_files(self):
        # Index HTML
        status, body, headers = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"ValLens", body)
        self.assertIn("text/html", headers.get("Content-Type", ""))

        # Ascent map icon
        status, body, headers = self._get("/maps/ascent.png")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "image/png")
        self.assertGreater(len(body), 1000)

    def test_rest_api_match_and_events(self):
        # 1. Matches list
        status, body, _ = self._get("/api/matches")
        self.assertEqual(status, 200)
        matches = json.loads(body.decode("utf-8"))
        self.assertGreaterEqual(len(matches), 1)
        self.assertEqual(matches[0]["match_id"], self.match.match_id)

        # 2. Match overview
        status, body, _ = self._get(f"/api/matches/{self.match.match_id}")
        self.assertEqual(status, 200)
        overview = json.loads(body.decode("utf-8"))
        self.assertEqual(overview["rounds_count"], 2)
        self.assertEqual(overview["total_kills"], 6)

        # 3. Events filtered
        status, body, _ = self._get(f"/api/matches/{self.match.match_id}/events?round=0&type=kill")
        self.assertEqual(status, 200)
        events = json.loads(body.decode("utf-8"))
        self.assertEqual(len(events), 3)

        # 4. Heatmap points
        status, body, _ = self._get(f"/api/matches/{self.match.match_id}/heatmap?type=death")
        self.assertEqual(status, 200)
        heatmap = json.loads(body.decode("utf-8"))
        self.assertEqual(len(heatmap), 6)
        for pt in heatmap:
            self.assertIn("norm_x", pt)
            self.assertIn("norm_y", pt)

    def test_tag_lifecycle(self):
        # Create tag
        payload = {
            "timestamp_ms": 45000,
            "category": "Mechanics",
            "name": "crosshair_placement",
            "author": "solo",
        }
        status, res = self._post_json(f"/api/matches/{self.match.match_id}/tags", payload)
        self.assertEqual(status, 201)
        self.assertTrue(res.get("success"))
        tag_id = res["tag_id"]

        # Verify tag listed
        status, body, _ = self._get(f"/api/matches/{self.match.match_id}/tags")
        tags = json.loads(body.decode("utf-8"))
        self.assertTrue(any(t["tag_id"] == tag_id for t in tags))

        # Delete tag
        status, del_res = self._delete(f"/api/tags/{tag_id}")
        self.assertEqual(status, 200)
        self.assertTrue(del_res.get("success"))

    def test_perspective_diff_endpoint(self):
        # Seed solo and coach tags
        self.service.add_vod_tag(self.match.match_id, 40000, "Mechanics", "crosshair_placement", "solo")
        self.service.add_vod_tag(self.match.match_id, 41000, "Mechanics", "crosshair_placement", "coach")
        self.service.add_vod_tag(self.match.match_id, 90000, "Positioning", "over_peeking", "coach")

        status, body, _ = self._get(f"/api/matches/{self.match.match_id}/perspective-diff?tolerance_ms=3000")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("agreement_score", data)
        self.assertIn("alignment_status", data)
        self.assertEqual(data["agreed_count"], 1)
        self.assertEqual(data["blindspots_count"], 1)
        self.assertTrue(len(data["blindspots"]) >= 1)
        self.assertTrue(len(data["category_divergence"]) >= 4)
        self.assertTrue(len(data["executive_takeaways"]) >= 1)

    def test_drills_endpoints(self):
        # 1. JSON endpoint
        status, body, _ = self._get(f"/api/matches/{self.match.match_id}/drills")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("prescriptions", data)
        self.assertIn("aimlab_playlist", data)
        self.assertTrue(len(data["prescriptions"]) >= 1)

        # 2. Markdown endpoint
        status, md_body, headers = self._get(f"/api/matches/{self.match.match_id}/drills?format=markdown")
        self.assertEqual(status, 200)
        self.assertIn("text/markdown", headers.get("Content-Type", ""))
        self.assertIn(b"ValLens Practice Routine", md_body)

        # 3. Aim Lab Playlist attachment endpoint
        status, playlist_body, headers = self._get(f"/api/matches/{self.match.match_id}/drills/aimlab-playlist")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers.get("Content-Disposition", ""))
        pl_data = json.loads(playlist_body.decode("utf-8"))
        self.assertIn("tasks", pl_data)

    def test_obs_endpoints_and_match_video(self):
        # 1. Check initial OBS status
        status, body, _ = self._get("/api/obs/status")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("connected", data)
        self.assertIn("recording", data)
        self.assertIn("game_state", data)
        self.assertFalse(data["recording"])

        # 2. Trigger start recording
        status, res = self._post_json("/api/obs/record", {"action": "start"})
        self.assertEqual(status, 200)
        self.assertEqual(res["action"], "started")
        self.assertTrue(res["recording"])

        # Verify status is recording
        status, body, _ = self._get("/api/obs/status")
        data = json.loads(body.decode("utf-8"))
        self.assertTrue(data["recording"])

        # 3. Toggle/Stop recording
        status, res = self._post_json("/api/obs/record", {"action": "stop"})
        self.assertEqual(status, 200)
        self.assertEqual(res["action"], "stopped")
        self.assertFalse(res["recording"])
        self.assertTrue(len(res["output_path"]) > 0)

        # 4. Associate video with match
        vid_path = "/recordings/custom_match_review.mp4"
        status, vid_res = self._post_json(
            f"/api/matches/{self.match.match_id}/video",
            {"video_filepath": vid_path},
        )
        self.assertEqual(status, 200)
        self.assertTrue(vid_res["success"])
        self.assertEqual(vid_res["video_filepath"], vid_path)

        # Verify overview reflects video_filepath
        status, body, _ = self._get(f"/api/matches/{self.match.match_id}")
        overview = json.loads(body.decode("utf-8"))
        self.assertEqual(overview["metadata"]["video_filepath"], vid_path)

        # 5. Check OBS Config API
        status, body, _ = self._get("/api/obs/config")
        self.assertEqual(status, 200)
        cfg = json.loads(body.decode("utf-8"))
        self.assertIn("host", cfg)
        self.assertIn("port", cfg)
        self.assertIn("use_mock", cfg)

        # 6. Configure Mock mode
        status, res = self._post_json("/api/obs/config", {"use_mock": True, "host": "127.0.0.1", "port": 4455})
        self.assertEqual(status, 200)
        self.assertTrue(res["success"])
        self.assertEqual(res["mode"], "mock")

        # 7. Toggle auto-capture polling
        status, res = self._post_json("/api/obs/auto-capture", {})
        self.assertEqual(status, 200)
        self.assertTrue(res["auto_capture_active"])
        # Toggle off
        status, res = self._post_json("/api/obs/auto-capture", {})
        self.assertEqual(status, 200)
        self.assertFalse(res["auto_capture_active"])

    def test_clip_trimmer_endpoints(self):
        # 1. Trim single moment
        payload = {
            "timestamp_seconds": 45.0,
            "pre_roll": 2.0,
            "post_roll": 1.0,
            "label": "whiffed_spray",
            "round_number": 1,
        }
        status, res = self._post_json(f"/api/matches/{self.match.match_id}/trim", payload)
        self.assertEqual(status, 200)
        self.assertTrue(res["success"])
        clip = res["clip"]
        self.assertIn("whiffed_spray", clip["filename"])
        self.assertEqual(clip["round_number"], 1)
        self.assertGreater(clip["duration_seconds"], 0)

        # 2. Fetch/stream the trimmed clip file
        status, body, headers = self._get(clip["download_url"])
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "video/mp4")
        self.assertGreater(len(body), 1000)

        # 3. Batch trim all flaw tags
        self.service.add_vod_tag(self.match.match_id, 45000, "Mechanics", "whiffed_spray", "solo")
        status, batch_res = self._post_json(
            f"/api/matches/{self.match.match_id}/trim-all-flaws",
            {"pre_roll": 1.5, "post_roll": 1.0},
        )
        self.assertEqual(status, 200)
        self.assertTrue(batch_res["success"])
        self.assertGreaterEqual(batch_res["count"], 1)
        self.assertTrue(len(batch_res["clips"]) >= 1)

    def test_montage_endpoint(self):
        # 1. Generate review montage
        payload = {"filter_type": "flaws", "pre_roll": 1.0, "post_roll": 1.0, "title": "coaching_reel"}
        status, res = self._post_json(f"/api/matches/{self.match.match_id}/montage", payload)
        self.assertEqual(status, 200)
        self.assertTrue(res["success"])
        montage = res["montage"]
        self.assertIn("coaching_reel_montage.mp4", montage["filename"])
        self.assertGreaterEqual(montage["segments_count"], 1)

        # 2. Download/stream the merged montage
        status, body, headers = self._get(montage["download_url"])
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "video/mp4")
        self.assertGreater(len(body), 1000)

    def test_coach_notes_endpoints(self):
        # 1. Create a text-only coach note
        payload = {
            "round_number": 2,
            "timestamp_ms": 35000,
            "author_type": "coach",
            "text_note": "Keep crosshair head-level at A Main corner",
        }
        status, note_res = self._post_json(f"/api/matches/{self.match.match_id}/notes", payload)
        self.assertEqual(status, 201)
        self.assertIn("note_id", note_res)
        note_id = note_res["note_id"]
        self.assertEqual(note_res["text_note"], "Keep crosshair head-level at A Main corner")

        # 2. Create a note with simulated base64 voice memo
        import base64
        fake_audio = base64.b64encode(b"RIFFmockaudiobytes").decode("utf-8")
        audio_payload = {
            "round_number": 2,
            "timestamp_ms": 38000,
            "author_type": "coach",
            "text_note": "Voice memo explanation",
            "audio_data": f"data:audio/webm;base64,{fake_audio}",
        }
        status, voice_res = self._post_json(f"/api/matches/{self.match.match_id}/notes", audio_payload)
        self.assertEqual(status, 201)
        self.assertIsNotNone(voice_res["audio_url"])

        # 3. Stream the audio file
        status, body, headers = self._get(voice_res["audio_url"])
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "audio/webm")
        self.assertEqual(body, b"RIFFmockaudiobytes")

        # 4. Fetch list of notes
        status, body, _ = self._get(f"/api/matches/{self.match.match_id}/notes")
        self.assertEqual(status, 200)
        notes = json.loads(body.decode("utf-8"))
        self.assertGreaterEqual(len(notes), 2)

        # 5. Delete note
        status, del_res = self._delete(f"/api/notes/{note_id}")
        self.assertEqual(status, 200)
        self.assertTrue(del_res["success"])

        # Delete voice note and ensure file cleanup
        status, del_voice = self._delete(f"/api/notes/{voice_res['note_id']}")
        self.assertEqual(status, 200)
        self.assertTrue(del_voice["success"])


if __name__ == "__main__":
    unittest.main()
