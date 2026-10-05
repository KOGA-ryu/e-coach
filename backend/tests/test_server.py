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


if __name__ == "__main__":
    unittest.main()
