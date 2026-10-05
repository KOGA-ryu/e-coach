"""Unit and integration tests for Multi-Match Heatmap Aggregation (Phase 4)."""

import json
from pathlib import Path
import unittest

from vallens.analytics.heatmap import HeatmapAggregationEngine, SpatialCluster
from vallens.db.database import Database
from vallens.models import MatchEvent, MatchMetadata, VodTag
from vallens.riot.seed_demo import seed_demo_data
from vallens.server import run_server
from vallens.service import ValLensService

SAMPLE_MATCH_PATH = Path(__file__).parent.parent.parent / "data" / "sample_match.json"


class TestHeatmapAggregation(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.service = ValLensService(db=self.db)
        # Ingest base sample match
        self.service.ingest_match_file(SAMPLE_MATCH_PATH)
        # Seed demo matches
        seed_demo_data(self.service)
        self.engine = HeatmapAggregationEngine()

    def test_list_available_maps(self):
        maps = self.service.list_available_maps()
        self.assertGreaterEqual(len(maps), 2)
        map_names = [m["map_name"] for m in maps]
        self.assertIn("Ascent", map_names)
        self.assertIn("Haven", map_names)

        ascent_meta = next(m for m in maps if m["map_name"] == "Ascent")
        self.assertEqual(ascent_meta["match_count"], 2)

    def test_callout_resolution(self):
        # A Main on Ascent: (0.484, 0.201)
        name, super_r = self.engine.find_nearest_callout("/Game/Maps/Ascent/Ascent", 0.484, 0.201)
        self.assertIn("Main", name)
        self.assertEqual(super_r, "A")

        # Tree on Ascent: (0.398, 0.295)
        name2, _ = self.engine.find_nearest_callout("Ascent", 0.400, 0.290)
        self.assertIn("Tree", name2)

    def test_multi_match_ascent_aggregation(self):
        res = self.service.get_map_aggregate_heatmap("Ascent", event_type="death")
        self.assertEqual(res.map_name, "Ascent")
        self.assertEqual(res.match_count, 2)
        self.assertGreaterEqual(res.total_events, 10)

        # Check clusters
        self.assertGreaterEqual(len(res.clusters), 2)
        top_cluster = res.clusters[0]
        self.assertIn("Main", top_cluster.zone_name)
        self.assertGreater(top_cluster.event_count, 3)

        # Check correlated tags
        tag_names = [t["name"] for t in top_cluster.correlated_tags]
        self.assertIn("over_peeking", tag_names)

        # Check tactical insights
        self.assertTrue(any("A Main" in s for s in res.tactical_insights))

    def test_side_filtering(self):
        # Attack side (Rounds 0-11)
        res_attack = self.service.get_map_aggregate_heatmap("Ascent", event_type="death", side="attack")
        for p in res_attack.points:
            self.assertLess(p["round_number"], 12)

        # Defense side (Rounds 12+)
        res_defense = self.service.get_map_aggregate_heatmap("Ascent", event_type="kill", side="defense")
        for p in res_defense.points:
            self.assertGreaterEqual(p["round_number"], 12)

    def test_density_grid_generation(self):
        res = self.service.get_map_aggregate_heatmap("Ascent", event_type="death")
        self.assertIsInstance(res.density_grid, list)
        self.assertGreater(len(res.density_grid), 0)
        first_cell = res.density_grid[0]
        self.assertIn("gx", first_cell)
        self.assertIn("gy", first_cell)
        self.assertIn("weight", first_cell)
        self.assertGreaterEqual(first_cell["weight"], 0.0)

    def test_server_heatmap_api_endpoints(self):
        import threading
        import urllib.request
        server = run_server(self.service, port=8877)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            # 1. /api/analytics/maps
            req1 = urllib.request.urlopen("http://127.0.0.1:8877/api/analytics/maps")
            maps_data = json.loads(req1.read().decode("utf-8"))
            self.assertGreaterEqual(len(maps_data), 2)

            # 2. /api/analytics/heatmap
            req2 = urllib.request.urlopen("http://127.0.0.1:8877/api/analytics/heatmap?map=Ascent&type=death&side=all")
            heat_data = json.loads(req2.read().decode("utf-8"))
            self.assertEqual(heat_data["map_name"], "Ascent")
            self.assertGreaterEqual(len(heat_data["clusters"]), 2)
            self.assertIn("points", heat_data)
        finally:
            server.shutdown()
            server.server_close()



if __name__ == "__main__":
    unittest.main()

