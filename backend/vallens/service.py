"""ValLens core ingestion and review service."""

import json
from pathlib import Path
from typing import Any, Optional

from vallens.analytics.agent_profile import AgentMatrixResult, AgentProfilingEngine
from vallens.analytics.drills import TrainingRoutineEngine, TrainingRoutineResult
from vallens.analytics.heatmap import HeatmapAggregationEngine, HeatmapAggregationResult
from vallens.analytics.perspective import PerspectiveDiffEngine, PerspectiveDiffResult
from vallens.analytics.projection import CoordinateProjector
from vallens.db.database import Database
from vallens.db.repository import MatchRepository
from vallens.models import MatchEvent, MatchMetadata, MatchPlayer, VodTag
from vallens.obs.controller import CaptureController
from vallens.riot.client import RiotApiClient
from vallens.riot.parser import MatchParser



class ValLensService:
    """Central service orchestrating ingestion, persistence, and review queries."""

    def __init__(
        self,
        db: Optional[Database] = None,
        maps_file: Optional[Path | str] = None,
        riot_api_key: Optional[str] = None,
        capture_controller: Optional[CaptureController] = None,
    ):
        self.db = db or Database()
        self.repo = MatchRepository(self.db)
        self.projector = CoordinateProjector(data_file=maps_file)
        self.parser = MatchParser(projector=self.projector)
        self.client = RiotApiClient(api_key=riot_api_key)
        self.heatmap_engine = HeatmapAggregationEngine(maps_file=maps_file)
        self.capture_controller = capture_controller or CaptureController(service=self)

    def ingest_match_payload(
        self, raw_data: dict[str, Any], video_filepath: Optional[str] = None
    ) -> MatchMetadata:
        """Parse and persist a raw match JSON payload into SQLite."""
        metadata, events = self.parser.parse_match(raw_data)
        players = self.parser.parse_players(raw_data, metadata.match_id)
        if video_filepath:
            metadata.video_filepath = video_filepath

        self.repo.insert_match(metadata)
        self.repo.insert_events(events)
        self.repo.insert_match_players(players)
        return metadata


    def ingest_match_file(
        self, file_path: Path | str, video_filepath: Optional[str] = None
    ) -> MatchMetadata:
        """Load and ingest a match JSON file from disk."""
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return self.ingest_match_payload(data, video_filepath=video_filepath)

    def ingest_match_by_id(
        self, match_id: str, video_filepath: Optional[str] = None
    ) -> MatchMetadata:
        """Fetch match from Riot API and ingest into database."""
        raw_data = self.client.fetch_match(match_id)
        return self.ingest_match_payload(raw_data, video_filepath=video_filepath)

    def get_match_overview(self, match_id: str) -> Optional[dict[str, Any]]:
        """Return match metadata along with total event count and round count."""
        match = self.repo.get_match(match_id)
        if not match:
            return None

        events = self.repo.get_events(match_id)
        rounds = sorted(list(set(e.round_number for e in events)))
        kills = [e for e in events if e.event_type == "kill"]
        deaths = [e for e in events if e.event_type == "death"]

        return {
            "metadata": match,
            "total_events": len(events),
            "rounds_count": len(rounds),
            "total_kills": len(kills),
            "total_deaths": len(deaths),
        }

    def get_player_heatmap(
        self,
        match_id: str,
        player_puuid: Optional[str] = None,
        event_type: str = "death",
        round_number: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Return projected points for rendering spatial heatmaps."""
        events = self.repo.get_events(
            match_id=match_id,
            round_number=round_number,
            event_type=event_type,
            player_puuid=player_puuid,
        )

        points = []
        for e in events:
            if e.pos_x is not None and e.pos_y is not None:
                points.append(
                    {
                        "event_id": e.event_id,
                        "round_number": e.round_number,
                        "event_time_ms": e.event_time_ms,
                        "norm_x": e.pos_x,
                        "norm_y": e.pos_y,
                        "metadata": e.metadata,
                    }
                )
        return points

    def add_vod_tag(
        self,
        match_id: str,
        timestamp_ms: int,
        category: str,
        name: str,
        author_type: str = "solo",
        event_id: Optional[int] = None,
    ) -> int:
        """Add a review tag anchored to a timestamp or event."""
        tag = VodTag(
            match_id=match_id,
            event_id=event_id,
            timestamp_ms=timestamp_ms,
            tag_category=category,
            tag_name=name,
            author_type=author_type,
        )
        return self.repo.create_tag(tag)

    def list_available_maps(self) -> list[dict[str, Any]]:
        """List all maps with matches stored in the local database, with calibrated display names."""
        raw_maps = self.repo.list_distinct_maps()
        results = []
        for m in raw_maps:
            cal = self.projector.get_calibration(m["map_id"])
            display_name = cal.display_name if cal else m["map_name"]
            results.append({
                "map_id": m["map_id"],
                "map_name": display_name,
                "match_count": m["match_count"],
                "event_count": m["event_count"],
                "latest_timestamp": m["latest_timestamp"],
            })
        return results

    def get_map_aggregate_heatmap(
        self,
        map_id_or_name: str,
        player_puuid: Optional[str] = None,
        event_type: str = "death",
        side: str = "all",
        limit_matches: int = 20,
    ) -> HeatmapAggregationResult:
        """Query and aggregate telemetry coordinates across matches for a map."""
        cal = self.projector.get_calibration(map_id_or_name)
        display_name = cal.display_name if cal else map_id_or_name.strip("/").split("/")[-1].capitalize()
        map_url = cal.map_url if cal else map_id_or_name

        identifiers = [map_id_or_name]
        if cal:
            identifiers.extend([cal.map_url, cal.display_name])

        events, tags, match_ids = self.repo.get_multi_match_events(
            map_identifiers=identifiers,
            player_puuid=player_puuid,
            event_type=event_type,
            side=side,
            limit_matches=limit_matches,
        )

        return self.heatmap_engine.build_aggregation_result(
            map_id=map_url,
            map_name=display_name,
            match_ids=match_ids,
            points=events,
            tags=tags,
            event_type=event_type,
            side=side,
        )

    def get_agent_matrix(
        self, player_puuid: Optional[str] = None
    ) -> AgentMatrixResult:
        """Compute Agent Profiling Matrix comparing opening duels, trades, and habit flaws."""
        engine = AgentProfilingEngine(repo=self.repo)
        return engine.generate_matrix(player_puuid=player_puuid)

    def get_perspective_diff(
        self, match_id: str, tolerance_ms: int = 5000
    ) -> Optional[PerspectiveDiffResult]:
        """Compute cognitive discrepancy and blindspots between Solo and Coach tags."""
        match = self.repo.get_match(match_id)
        if not match:
            return None
        events = self.repo.get_events(match_id)
        tags = self.repo.get_tags(match_id)
        engine = PerspectiveDiffEngine(default_tolerance_ms=tolerance_ms)
        return engine.analyze_perspectives(
            match_id=match_id, events=events, tags=tags, tolerance_ms=tolerance_ms
        )

    def get_training_routine(
        self, match_id: str, player_puuid: Optional[str] = None
    ) -> Optional[TrainingRoutineResult]:
        """Generate structured practice routine and Aim Lab playlist tailored to match flaws."""
        match = self.repo.get_match(match_id)
        if not match:
            return None
        events = self.repo.get_events(match_id)
        tags = self.repo.get_tags(match_id)
        engine = TrainingRoutineEngine()
        return engine.generate_routine(
            metadata=match, events=events, tags=tags, player_puuid=player_puuid
        )

    def get_obs_status(self) -> dict[str, Any]:
        """Return current OBS connection, recording state, and local client game state."""
        client = self.capture_controller.obs_client
        connected = False
        if hasattr(client, "connected"):
            connected = bool(client.connected)
        elif hasattr(client, "ws"):
            connected = client.ws is not None
        else:
            connected = True

        rec_status = False
        duration_sec = 0.0
        output_path = ""
        try:
            status = client.get_record_status()
            rec_status = status.get("outputActive", False)
            duration_sec = status.get("outputDuration", 0.0) / 1000.0 if "outputDuration" in status else 0.0
            output_path = status.get("outputPath", "")
        except Exception:
            pass

        session = self.capture_controller.local_client.get_session_state()
        game_state = session.get("state", "DISCONNECTED")

        return {
            "connected": connected,
            "recording": rec_status,
            "duration_seconds": round(duration_sec, 1),
            "output_path": output_path or self.capture_controller.last_recorded_file or "",
            "game_state": game_state,
        }

    def set_obs_recording(self, action: str = "toggle") -> dict[str, Any]:
        """Start, stop, or toggle OBS recording."""
        client = self.capture_controller.obs_client
        status = client.get_record_status()
        active = status.get("outputActive", False)

        if action == "start":
            if not active:
                client.start_recording()
            return {"action": "started", "recording": True}
        elif action == "stop":
            out_file = ""
            if active:
                out_file = client.stop_recording()
                self.capture_controller.last_recorded_file = out_file
            return {"action": "stopped", "recording": False, "output_path": out_file}
        elif action == "toggle":
            if not active:
                client.start_recording()
                return {"action": "started", "recording": True}
            else:
                out_file = client.stop_recording()
                self.capture_controller.last_recorded_file = out_file
                return {"action": "stopped", "recording": False, "output_path": out_file}
        else:
            raise ValueError(f"Unknown OBS action: {action}")

    def attach_match_video(self, match_id: str, video_filepath: str) -> bool:
        """Associate a video recording file path with a match."""
        return self.repo.update_video_path(match_id, video_filepath)



