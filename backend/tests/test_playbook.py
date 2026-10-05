"""Tests for Tactical Playbook & Minimap Telestrator Engine."""

import unittest
from vallens.db.database import Database
from vallens.db.repository import MatchRepository
from vallens.models import PlaybookStrat
from vallens.service import ValLensService


class TestPlaybookStrats(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.repo = MatchRepository(self.db)
        self.service = ValLensService(db=self.db)

    def test_default_strats_seeded(self):
        """Verify default professional strats are seeded if table is empty."""
        strats = self.repo.list_strats()
        self.assertGreaterEqual(len(strats), 3)
        ascent_strat = next((s for s in strats if s.map_name.lower() == "ascent"), None)
        self.assertIsNotNone(ascent_strat)
        self.assertEqual(ascent_strat.side, "retake")
        self.assertTrue(len(ascent_strat.drawing_data) > 0)

    def test_crud_strat(self):
        """Verify creating, reading, updating, and deleting a playbook strat."""
        strat = PlaybookStrat(
            strat_id="strat-split-b-push",
            title="Split B Main Rush",
            map_name="Split",
            side="attack",
            round_number=5,
            description="5-man B Main heavy push with Sage slow and Raze nade.",
            drawing_data=[
                {"type": "arrow", "x1": 0.2, "y1": 0.8, "x2": 0.3, "y2": 0.5, "color": "#00f2fe"}
            ],
            created_at=1700000000000,
        )
        self.repo.insert_strat(strat)

        fetched = self.repo.get_strat("strat-split-b-push")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.title, "Split B Main Rush")
        self.assertEqual(len(fetched.drawing_data), 1)

        # Update
        fetched.title = "Split B Main Rush [Updated]"
        self.repo.update_strat(fetched)
        updated = self.repo.get_strat("strat-split-b-push")
        self.assertEqual(updated.title, "Split B Main Rush [Updated]")

        # Delete
        success = self.repo.delete_strat("strat-split-b-push")
        self.assertTrue(success)
        self.assertIsNone(self.repo.get_strat("strat-split-b-push"))

    def test_service_playbook_methods(self):
        """Verify service layer handles playbook strategy lifecycle."""
        created = self.service.create_playbook_strat({
            "title": "Haven A Split",
            "map_name": "Haven",
            "side": "attack",
            "description": "Short and Long pinch",
            "drawing_data": [{"type": "marker", "x": 0.7, "y": 0.3, "color": "#ff4655"}],
        })
        self.assertIn("strat_id", created)
        self.assertEqual(created["title"], "Haven A Split")

        strats = self.service.list_playbook_strats(map_name="Haven")
        self.assertTrue(any(s["strat_id"] == created["strat_id"] for s in strats))

        # Delete via service
        deleted = self.service.delete_playbook_strat(created["strat_id"])
        self.assertTrue(deleted)
        self.assertIsNone(self.service.get_playbook_strat(created["strat_id"]))


if __name__ == "__main__":
    unittest.main()
