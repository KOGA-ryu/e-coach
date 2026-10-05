"""Unit and integration tests for Agent Profiling Matrix, Role Benchmarking, and Analytics."""

import json
from pathlib import Path
import threading
import time
import unittest
import urllib.request

from vallens.analytics.agent_profile import AgentProfilingEngine
from vallens.db.database import Database
from vallens.models import MatchEvent, MatchMetadata, MatchPlayer, VodTag
from vallens.server import run_server
from vallens.service import ValLensService

SAMPLE_MATCH_PATH = Path(__file__).parent.parent.parent / "data" / "sample_match.json"


class TestAgentMatrixEngine(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.service = ValLensService(db=self.db)
        self.repo = self.service.repo

        # Seed Match 1 (Jett on Ascent)
        m1 = MatchMetadata(
            match_id="match-jett-001",
            map_id="/Game/Maps/Ascent/Ascent",
            game_mode="competitive",
            match_duration=1200000,
            timestamp=1690000000,
        )
        self.repo.insert_match(m1)

        # Roster for Match 1
        p1 = MatchPlayer(
            match_id="match-jett-001",
            player_puuid="player-ace-001",
            game_name="Ace",
            tag_line="VAL",
            team_id="Blue",
            character_id="add6443a-41bd-e414-f6ad-e58d267f4e95",  # Jett
            kills=20,
            deaths=10,
            assists=4,
            score=4800,
            rounds_played=15,
        )
        self.repo.insert_match_players([p1])

        # Events for Match 1:
        # Round 0: Ace gets First Blood
        ev1 = MatchEvent(
            match_id="match-jett-001",
            round_number=0,
            event_type="kill",
            event_time_ms=30000,
            player_puuid="player-ace-001",
            pos_x=0.5,
            pos_y=0.5,
            metadata={"victim": "player-enemy-001"},
        )
        # Round 1: Ace gets First Blood
        ev2 = MatchEvent(
            match_id="match-jett-001",
            round_number=1,
            event_type="kill",
            event_time_ms=32000,
            player_puuid="player-ace-001",
            pos_x=0.52,
            pos_y=0.48,
            metadata={"victim": "player-enemy-002"},
        )
        self.repo.insert_events([ev1, ev2])

        # Tags for Match 1: 2 over_peeking tags
        t1 = VodTag(
            match_id="match-jett-001",
            timestamp_ms=45000,
            tag_category="Positioning",
            tag_name="over_peeking",
            author_type="solo",
        )
        t2 = VodTag(
            match_id="match-jett-001",
            timestamp_ms=90000,
            tag_category="Positioning",
            tag_name="over_peeking",
            author_type="solo",
        )
        self.repo.create_tag(t1)
        self.repo.create_tag(t2)

        # Seed Match 2 (Omen on Bind)
        m2 = MatchMetadata(
            match_id="match-omen-002",
            map_id="/Game/Maps/Duality/Duality",
            game_mode="competitive",
            match_duration=1400000,
            timestamp=1690100000,
        )
        self.repo.insert_match(m2)

        p2 = MatchPlayer(
            match_id="match-omen-002",
            player_puuid="player-ace-001",
            game_name="Ace",
            tag_line="VAL",
            team_id="Blue",
            character_id="8e253930-4c05-31dd-1b6c-968525494517",  # Omen
            kills=12,
            deaths=8,
            assists=15,
            score=3900,
            rounds_played=20,
        )
        self.repo.insert_match_players([p2])

        # Tags for Match 2: 3 wasted_utility tags
        for ts in [30000, 60000, 90000]:
            self.repo.create_tag(
                VodTag(
                    match_id="match-omen-002",
                    timestamp_ms=ts,
                    tag_category="Utility",
                    tag_name="wasted_utility",
                    author_type="coach",
                )
            )

        self.engine = AgentProfilingEngine(repo=self.repo)

    def test_engine_generate_matrix(self):
        matrix = self.engine.generate_matrix(player_puuid="player-ace-001")
        self.assertEqual(matrix.player_puuid, "player-ace-001")
        self.assertEqual(matrix.total_matches, 2)
        self.assertEqual(matrix.total_rounds, 35)
        self.assertEqual(len(matrix.agents), 2)

        # Check Jett stats
        jett_profile = next(a for a in matrix.agents if a.agent_name == "Jett")
        self.assertEqual(jett_profile.role, "Duelist")
        self.assertEqual(jett_profile.kills, 20)
        self.assertEqual(jett_profile.deaths, 10)
        self.assertEqual(jett_profile.kd_ratio, 2.0)
        self.assertEqual(jett_profile.first_bloods, 2)
        self.assertEqual(jett_profile.first_deaths, 0)
        self.assertEqual(jett_profile.opening_duel_win_rate, 100.0)
        self.assertEqual(jett_profile.flaw_tags_count, 2)
        self.assertEqual(jett_profile.top_flaws[0]["name"], "over_peeking")
        self.assertEqual(jett_profile.top_flaws[0]["count"], 2)
        self.assertIn("entry_grade", jett_profile.role_benchmarks)
        self.assertIn("High-impact entry fragger", jett_profile.diagnosis)

        # Check Omen stats
        omen_profile = next(a for a in matrix.agents if a.agent_name == "Omen")
        self.assertEqual(omen_profile.role, "Controller")
        self.assertEqual(omen_profile.kills, 12)
        self.assertEqual(omen_profile.deaths, 8)
        self.assertEqual(omen_profile.kd_ratio, 1.5)
        self.assertEqual(omen_profile.flaw_tags_count, 3)
        self.assertEqual(omen_profile.top_flaws[0]["name"], "wasted_utility")
        self.assertIn("survival_grade", omen_profile.role_benchmarks)

        # Check role breakdown
        self.assertIn("Duelist", matrix.role_breakdown)
        self.assertIn("Controller", matrix.role_breakdown)
        self.assertEqual(matrix.role_breakdown["Duelist"]["matches"], 1)

        # Check summary insights
        self.assertGreaterEqual(len(matrix.summary_insights), 2)

    def test_service_get_agent_matrix(self):
        matrix_res = self.service.get_agent_matrix("player-ace-001")
        self.assertEqual(matrix_res.player_puuid, "player-ace-001")
        self.assertEqual(len(matrix_res.agents), 2)
        matrix_dict = matrix_res.to_dict()
        self.assertIsInstance(matrix_dict, dict)
        self.assertEqual(matrix_dict["player_puuid"], "player-ace-001")
        self.assertEqual(len(matrix_dict["agents"]), 2)
        self.assertIn("role_breakdown", matrix_dict)


class TestAgentMatrixServerEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = Database(":memory:")
        cls.service = ValLensService(db=cls.db)

        # Ingest sample match
        cls.match = cls.service.ingest_match_file(SAMPLE_MATCH_PATH)

        # Start server
        cls.port = 8998
        cls.server = run_server(service=cls.service, port=cls.port, host="127.0.0.1")
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_get_agent_matrix_api(self):
        url = f"http://127.0.0.1:{self.port}/api/analytics/agents"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("player_puuid", data)
            self.assertIn("agents", data)
            self.assertIn("role_breakdown", data)
            self.assertIn("summary_insights", data)
            self.assertIsInstance(data["agents"], list)
            if len(data["agents"]) > 0:
                agent0 = data["agents"][0]
                self.assertIn("agent_name", agent0)
                self.assertIn("role", agent0)
                self.assertIn("opening_duel_win_rate", agent0)
                self.assertIn("top_flaws", agent0)
                self.assertIn("diagnosis", agent0)


if __name__ == "__main__":
    unittest.main()
