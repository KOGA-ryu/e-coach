"""Unit tests for ProReferenceCatalog."""

import unittest
from vallens.analytics.reference_vods import ProReferenceCatalog, ProReferenceVod


class TestReferenceVods(unittest.TestCase):
    def setUp(self):
        self.catalog = ProReferenceCatalog()

    def test_list_all_references(self):
        refs = self.catalog.list_references()
        self.assertGreaterEqual(len(refs), 4)
        ids = [r["id"] for r in refs]
        self.assertIn("aspas_ascent_a_op", ids)
        self.assertIn("tenz_ascent_mid_market", ids)

    def test_filter_by_map(self):
        ascent_refs = self.catalog.list_references(map_name="Ascent")
        self.assertTrue(all(r["map"] == "Ascent" for r in ascent_refs))

        empty_refs = self.catalog.list_references(map_name="NonExistentMap")
        self.assertEqual(empty_refs, [])

    def test_filter_by_flaw_tag(self):
        refs = self.catalog.list_references(flaw_tag="crosshair_placement")
        self.assertTrue(len(refs) >= 1)
        self.assertEqual(refs[0]["player"], "Aspas")

    def test_recommend_for_flaw(self):
        recommended = self.catalog.recommend_for_flaw("over_peeking", map_name="Ascent")
        self.assertTrue(len(recommended) >= 1)
        self.assertEqual(recommended[0]["player"], "TenZ")

    def test_add_custom_reference(self):
        custom = ProReferenceVod(
            id="custom_1",
            title="Custom Clip",
            player="CustomPlayer",
            team="CustomTeam",
            agent="Jett",
            map_name="Haven",
            flaw_category="Mechanics",
            flaw_tag="crosshair_placement",
            tactical_concept="Haven A Long peek",
            clip_url="/api/clips/custom.mp4",
        )
        self.catalog.add_custom_reference(custom)
        found = self.catalog.get_reference_by_id("custom_1")
        self.assertIsNotNone(found)
        self.assertEqual(found["player"], "CustomPlayer")


if __name__ == "__main__":
    unittest.main()
