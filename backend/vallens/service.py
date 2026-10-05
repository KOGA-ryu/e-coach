"""ValLens core ingestion and review service."""

import json
from pathlib import Path
from typing import Any, Optional

from vallens.analytics.agent_profile import AgentMatrixResult, AgentProfilingEngine
from vallens.analytics.career_radar import CareerProfileReport, CareerRadarEngine
from vallens.analytics.drills import TrainingRoutineEngine, TrainingRoutineResult
from vallens.analytics.economy import EconomyAnalysisResult, EconomyCorrelationEngine
from vallens.analytics.frame_sync import FrameSyncEngine, FrameSyncResult
from vallens.analytics.heatmap import HeatmapAggregationEngine, HeatmapAggregationResult
from vallens.analytics.perspective import PerspectiveDiffEngine, PerspectiveDiffResult
from vallens.analytics.projection import CoordinateProjector
from vallens.analytics.reference_vods import ProReferenceCatalog
from vallens.analytics.round_comparison import RoundComparisonEngine, RoundComparisonResult
from vallens.analytics.scouting_report import ScoutingReportGenerator
from vallens.analytics.trade_matrix import MatchTradeReport, TradeMatrixEngine
from vallens.analytics.transcription import CoachVoiceTranscriber
from vallens.analytics.utility_roi import UtilityRoiEngine, UtilityRoiReport
from vallens.analytics.win_probability import MatchWinProbabilityReport, WinProbabilityEngine
from vallens.db.database import Database
from vallens.db.repository import MatchRepository
from vallens.models import CoachNote, MatchEvent, MatchMetadata, MatchPlayer, PlaybookStrat, VodTag
from vallens.obs.controller import CaptureController
from vallens.obs.trimmer import ClipTrimmer
from vallens.riot.client import RiotApiClient
from vallens.riot.parser import MatchParser
from vallens.video.clipper import HighlightCandidate, HighlightClipper



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
        self.economy_engine = EconomyCorrelationEngine()
        self.transcriber = CoachVoiceTranscriber()
        self.reference_catalog = ProReferenceCatalog()
        self.sync_engine = FrameSyncEngine()
        self.utility_roi_engine = UtilityRoiEngine(self.repo)
        self.career_radar_engine = CareerRadarEngine(
            self.repo,
            economy_engine=self.economy_engine,
            utility_roi_engine=self.utility_roi_engine,
        )
        self.trade_engine = TradeMatrixEngine(self.repo)
        self.win_prob_engine = WinProbabilityEngine(self.repo)
        self.scouting_generator = ScoutingReportGenerator(
            repo=self.repo,
            trade_engine=self.trade_engine,
            win_prob_engine=self.win_prob_engine,
            career_radar_engine=self.career_radar_engine,
            utility_roi_engine=self.utility_roi_engine,
            economy_engine=self.economy_engine,
            drills_engine=TrainingRoutineEngine(),
        )
        self.trimmer = ClipTrimmer()
        self.clipper = HighlightClipper(
            repo=self.repo,
            trimmer=self.trimmer,
            win_prob_engine=self.win_prob_engine,
            trade_engine=self.trade_engine,
        )
        self.round_comparator = RoundComparisonEngine(
            repo=self.repo,
            win_prob_engine=self.win_prob_engine,
            trade_engine=self.trade_engine,
        )
        try:
            self.repo.seed_default_strats()
        except Exception:
            pass
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

    def get_obs_config(self) -> dict[str, Any]:
        """Return current OBS WebSocket connection and auto-capture settings."""
        return self.capture_controller.get_obs_config()

    def configure_obs(
        self,
        host: str = "127.0.0.1",
        port: int = 4455,
        password: Optional[str] = None,
        use_mock: bool = False,
    ) -> dict[str, Any]:
        """Configure and connect to OBS WebSocket v5 or switch to Mock mode."""
        return self.capture_controller.configure_obs(
            host=host,
            port=port,
            password=password,
            use_mock=use_mock,
        )

    def toggle_auto_capture(self) -> bool:
        """Toggle background game state detection loop."""
        return self.capture_controller.toggle_auto_capture()

    def get_riot_status(self) -> dict[str, Any]:
        """Return current Riot Client connection and game-state telemetry."""
        return self.capture_controller.get_riot_status()

    def configure_riot_client(
        self, use_mock: bool = False, lockfile_path: Optional[str] = None
    ) -> dict[str, Any]:
        """Configure local Riot Client lockfile reader or mock simulation mode."""
        return self.capture_controller.configure_local_client(
            use_mock=use_mock, lockfile_path=lockfile_path
        )

    def simulate_riot_game_state(
        self,
        state: str,
        map_name: Optional[str] = None,
        agent: Optional[str] = None,
        player_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """Simulate a game state change for zero-touch auto-capture testing."""
        return self.capture_controller.simulate_game_state(
            state=state, match_map=map_name, agent=agent, player_name=player_name
        )

    def attach_match_video(self, match_id: str, video_filepath: str) -> bool:
        """Associate a video recording file path with a match."""
        return self.repo.update_video_path(match_id, video_filepath)

    def trim_match_clip(
        self,
        match_id: str,
        timestamp_seconds: float,
        pre_roll: float = 3.0,
        post_roll: float = 2.0,
        label: Optional[str] = None,
        round_number: Optional[int] = None,
    ) -> dict[str, Any]:
        """Cut and export an MP4 clip for a specific match event or flaw."""
        match = self.repo.get_match(match_id)
        if not match:
            raise ValueError(f"Match not found: {match_id}")

        trimmer = ClipTrimmer()
        return trimmer.trim_moment(
            match_id=match_id,
            timestamp_seconds=timestamp_seconds,
            video_filepath=match.video_filepath,
            pre_roll=pre_roll,
            post_roll=post_roll,
            label=label,
            round_number=round_number,
        )

    def batch_trim_flaws(
        self,
        match_id: str,
        pre_roll: float = 3.0,
        post_roll: float = 2.0,
    ) -> list[dict[str, Any]]:
        """Batch-export video clips for all logged flaw tags in a match."""
        match = self.repo.get_match(match_id)
        if not match:
            raise ValueError(f"Match not found: {match_id}")

        tags = self.repo.get_tags(match_id)
        trimmer = ClipTrimmer()
        return trimmer.batch_trim_tags(
            match_id=match_id,
            tags=tags,
            video_filepath=match.video_filepath,
            pre_roll=pre_roll,
            post_roll=post_roll,
        )

    def generate_match_montage(
        self,
        match_id: str,
        filter_type: str = "flaws",
        pre_roll: float = 3.0,
        post_roll: float = 2.0,
        title: Optional[str] = None,
    ) -> dict[str, Any]:
        """Compile a single continuous review montage video from match moments."""
        match = self.repo.get_match(match_id)
        if not match:
            raise ValueError(f"Match not found: {match_id}")

        moments: list[dict[str, Any]] = []

        if filter_type == "blindspots":
            diff = self.get_perspective_diff(match_id)
            if diff:
                for b in diff.blindspots:
                    moments.append({
                        "label": f"blindspot_{b.tag_name}",
                        "timestamp_seconds": b.timestamp_ms / 1000.0,
                        "round_number": b.round_number,
                        "category": b.tag_category,
                    })
        elif filter_type == "deaths":
            events = self.repo.get_events(match_id, event_type="death")
            for e in events:
                moments.append({
                    "label": "death",
                    "timestamp_seconds": e.event_time_ms / 1000.0,
                    "round_number": e.round_number,
                    "category": "Combat",
                })
        else:
            tags = self.repo.get_tags(match_id)
            for t in tags:
                moments.append({
                    "label": t.tag_name,
                    "timestamp_seconds": t.timestamp_ms / 1000.0,
                    "round_number": None,
                    "category": t.tag_category,
                })

        # Fallback if no tags/blindspots: use death events
        if not moments:
            events = self.repo.get_events(match_id, event_type="death")
            for e in events[:10]:
                moments.append({
                    "label": "death",
                    "timestamp_seconds": e.event_time_ms / 1000.0,
                    "round_number": e.round_number,
                    "category": "Combat",
                })

        if not moments:
            raise ValueError(f"No flaws or events found in match {match_id} to generate montage.")

        # Sort chronologically
        moments.sort(key=lambda m: m["timestamp_seconds"])

        trimmer = ClipTrimmer()
        return trimmer.create_montage(
            match_id=match_id,
            moments=moments,
            video_filepath=match.video_filepath,
            pre_roll=pre_roll,
            post_roll=post_roll,
            title=title or f"{filter_type}_review",
        )

    def add_coach_note(
        self,
        match_id: str,
        round_number: int,
        timestamp_ms: int,
        author_type: str = "coach",
        text_note: str = "",
        audio_data: Optional[str] = None,
    ) -> dict[str, Any]:
        """Add a timestamped coach note with optional voice memo dictation."""
        audio_filepath = None
        if audio_data and isinstance(audio_data, str) and len(audio_data) > 0:
            import base64
            import uuid
            import time

            if "," in audio_data:
                header, b64_payload = audio_data.split(",", 1)
            else:
                b64_payload = audio_data

            try:
                audio_bytes = base64.b64decode(b64_payload)
                notes_dir = Path(__file__).resolve().parent.parent.parent / "data" / "notes"
                notes_dir.mkdir(parents=True, exist_ok=True)
                audio_filename = f"{match_id}_R{round_number}_{int(time.time())}_{uuid.uuid4().hex[:6]}.webm"
                audio_path = notes_dir / audio_filename
                with open(audio_path, "wb") as f:
                    f.write(audio_bytes)
                audio_filepath = audio_filename
            except Exception as e:
                import logging
                logging.getLogger("vallens.service").error(f"Failed to decode voice memo: {e}")

        import time
        created_at = int(time.time() * 1000)
        note = CoachNote(
            match_id=match_id,
            round_number=round_number,
            timestamp_ms=timestamp_ms,
            author_type=author_type,
            text_note=text_note,
            audio_filepath=audio_filepath,
            created_at=created_at,
        )
        note_id = self.repo.create_note(note)
        suggested_tags = self.transcriber.extract_tactical_tags(text_note)
        return {
            "note_id": note_id,
            "match_id": match_id,
            "round_number": round_number,
            "timestamp_ms": timestamp_ms,
            "author_type": author_type,
            "text_note": text_note,
            "audio_filepath": audio_filepath,
            "audio_url": f"/api/notes/{audio_filepath}" if audio_filepath else None,
            "created_at": created_at,
            "suggested_tags": suggested_tags,
        }

    def transcribe_voice_memo(
        self,
        audio_data: Optional[str] = None,
        text_hint: Optional[str] = None,
    ) -> dict[str, Any]:
        """Transcribe voice dictation and identify tactical flaw tags."""
        return self.transcriber.transcribe_audio_data(audio_data=audio_data, text_hint=text_hint)

    def suggest_tactical_tags(self, text: str) -> list[dict[str, Any]]:
        """Extract tactical tags and confidence scores from a coaching text observation."""
        return self.transcriber.extract_tactical_tags(text)

    def get_coach_notes(
        self, match_id: str, round_number: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """Fetch coach notes and voice memos for a match."""
        notes = self.repo.get_notes(match_id, round_number=round_number)
        return [
            {
                "note_id": n.note_id,
                "match_id": n.match_id,
                "round_number": n.round_number,
                "timestamp_ms": n.timestamp_ms,
                "author_type": n.author_type,
                "text_note": n.text_note,
                "audio_filepath": n.audio_filepath,
                "audio_url": f"/api/notes/{n.audio_filepath}" if n.audio_filepath else None,
                "created_at": n.created_at,
            }
            for n in notes
        ]

    def delete_coach_note(self, note_id: int) -> bool:
        """Delete a coach note and remove any associated audio memo."""
        note = self.repo.get_note(note_id)
        if note and note.audio_filepath:
            notes_dir = Path(__file__).resolve().parent.parent.parent / "data" / "notes"
            target_file = notes_dir / note.audio_filepath
            if target_file.exists():
                try:
                    target_file.unlink()
                except Exception:
                    pass
        return self.repo.delete_note(note_id)

    def get_economy_analysis(
        self, match_id: str, player_puuid: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        """Run economy vs flaw correlation analysis for a match."""
        match = self.repo.get_match(match_id)
        if not match:
            return None

        events = self.repo.get_events(match_id)
        tags = self.repo.get_tags(match_id)

        analysis = self.economy_engine.analyze(
            match_id=match_id,
            events=events,
            tags=tags,
            player_puuid=player_puuid,
        )
        return analysis.to_dict()

    def list_pro_references(
        self,
        map_name: Optional[str] = None,
        flaw_tag: Optional[str] = None,
        agent: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """List curated pro reference VODs with optional filters."""
        return self.reference_catalog.list_references(
            map_name=map_name, flaw_tag=flaw_tag, agent=agent
        )

    def get_pro_reference(self, ref_id: str) -> Optional[dict[str, Any]]:
        """Fetch a pro reference VOD by ID."""
        return self.reference_catalog.get_reference_by_id(ref_id)

    def recommend_pro_references(
        self, flaw_tag: str, map_name: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Recommend pro reference clips targeted to a specific tactical flaw."""
        return self.reference_catalog.recommend_for_flaw(flaw_tag=flaw_tag, map_name=map_name)

    def auto_align_match_video(
        self, match_id: str, video_filepath: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        """Run automated visual and acoustic cross-correlation to synchronize video timeline."""
        match = self.repo.get_match(match_id)
        if not match:
            return None

        events = self.repo.get_events(match_id)
        result = self.sync_engine.analyze_and_align(
            metadata=match, events=events, video_filepath=video_filepath
        )

        # Automatically update match record with suggested offset
        self.repo.update_video_offset(match_id, result.suggested_offset_ms)
        if video_filepath:
            self.repo.update_video_path(match_id, str(video_filepath))

        return result.to_dict()

    def calibrate_match_video_offset(
        self,
        match_id: str,
        video_time_ms: int,
        target_event_id: Optional[int] = None,
        align_to: Optional[str] = None,
        target_event_time_ms: Optional[int] = None,
    ) -> Optional[dict[str, Any]]:
        """Calibrate offset directly by locking a specific video frame to an event landmark."""
        match = self.repo.get_match(match_id)
        if not match:
            return None

        events = self.repo.get_events(match_id)
        target_event = None
        event_name = align_to or "Round 1 Start"
        chosen_time_ms = target_event_time_ms

        if target_event_id:
            for e in events:
                if e.event_id == target_event_id:
                    target_event = e
                    event_name = f"{e.event_type.replace('_', ' ').title()} (Round {e.round_number + 1})"
                    chosen_time_ms = e.event_time_ms
                    break

        if chosen_time_ms is None:
            # Default to Round 1 Start
            for e in events:
                if e.event_type == "round_start" and e.round_number == 0:
                    chosen_time_ms = e.event_time_ms
                    event_name = "Round 1 Start"
                    break
            if chosen_time_ms is None:
                chosen_time_ms = 0

        result = self.sync_engine.calibrate_from_point(
            match_id=match_id,
            video_time_ms=video_time_ms,
            target_event_time_ms=chosen_time_ms,
            event_name=event_name,
        )

        self.repo.update_video_offset(match_id, result.suggested_offset_ms)
        return result.to_dict()

    def set_match_video_offset(self, match_id: str, offset_ms: int) -> bool:
        """Set video offset directly in milliseconds."""
        return self.repo.update_video_offset(match_id, offset_ms)

    def get_match_sync_status(self, match_id: str) -> Optional[dict[str, Any]]:
        """Fetch current video alignment offset and telemetry sync state."""
        match = self.repo.get_match(match_id)
        if not match:
            return None

        events = self.repo.get_events(match_id)
        return {
            "match_id": match.match_id,
            "video_filepath": match.video_filepath,
            "video_offset_ms": getattr(match, "video_offset_ms", 0) or 0,
            "video_offset_sec": round((getattr(match, "video_offset_ms", 0) or 0) / 1000.0, 3),
            "events_count": len(events),
            "calibrated": (getattr(match, "video_offset_ms", 0) or 0) != 0,
        }

    # ------------------------------------------------------------------
    # Post-Match Ability ROI & Tactical Utility Telemetry
    # ------------------------------------------------------------------
    def get_match_utility_roi(
        self, match_id: str, force_recompute: bool = False
    ) -> Optional[dict[str, Any]]:
        """Calculate post-game utility ROI, flash conversion, and smoke efficiency."""
        match = self.repo.get_match(match_id)
        if not match:
            return None

        report = self.utility_roi_engine.analyze_match_utility(
            match_id, force_recompute=force_recompute
        )
        report_data = report.to_dict()
        events = self.repo.get_utility_events(match_id)
        report_data["events"] = [e.to_dict() for e in events]
        return report_data

    # ------------------------------------------------------------------
    # Longitudinal Career Profile & 6-Axis Tactical Radar
    # ------------------------------------------------------------------
    def get_career_profile(
        self,
        player_puuid: Optional[str] = None,
        limit: int = 20,
        map_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Generate longitudinal career skill radar and flaw reduction trajectories."""
        profile = self.career_radar_engine.generate_career_profile(
            player_puuid=player_puuid,
            limit=limit,
            map_id=map_id,
        )
        return profile.to_dict()

    # ------------------------------------------------------------------
    # Post-Match Trade Frag Efficiency & Spacing Matrix
    # ------------------------------------------------------------------
    def get_match_trades(self, match_id: str) -> Optional[dict[str, Any]]:
        """Calculate trade frag conversion, 3.0s trade windows, and spacing errors."""
        match = self.repo.get_match(match_id)
        if not match:
            return None

        report = self.trade_engine.analyze_match_trades(match_id=match_id)
        return report.to_dict()

    # ------------------------------------------------------------------
    # Post-Match Win Probability Timeline & Clutch Evaluator
    # ------------------------------------------------------------------
    def get_match_win_probability(self, match_id: str) -> Optional[dict[str, Any]]:
        """Calculate round-by-round win expectancy timeline W(t) and 1vX clutch ratings."""
        match = self.repo.get_match(match_id)
        if not match:
            return None

        report = self.win_prob_engine.calculate_match_probability(match_id=match_id)
        return report.to_dict()

    # ------------------------------------------------------------------
    # Pro Scouting Dossier & Offline Report Export
    # ------------------------------------------------------------------
    def get_match_scouting_report(
        self,
        match_id: str,
        player_puuid: Optional[str] = None,
        format: str = "json",
    ) -> Optional[dict[str, Any] | str]:
        """Generate structured JSON or standalone printable HTML scouting dossier."""
        match = self.repo.get_match(match_id)
        if not match:
            return None

        if format.lower() == "html":
            return self.scouting_generator.generate_standalone_html(
                match_id=match_id, player_puuid=player_puuid
            )
        return self.scouting_generator.generate_dossier_data(
            match_id=match_id, player_puuid=player_puuid
        )

    # ------------------------------------------------------------------
    # Tactical Playbook Strategies & Minimap Telestrator Drawings
    # ------------------------------------------------------------------
    def create_playbook_strat(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new playbook tactical strategy."""
        import time
        import uuid

        strat_id = data.get("strat_id") or f"strat_{uuid.uuid4().hex[:8]}"
        title = data.get("title") or "Tactical Strategy"
        map_name = data.get("map_name") or "Ascent"
        side = data.get("side") or "attack"
        round_number = data.get("round_number")
        match_id = data.get("match_id")
        description = data.get("description") or ""
        drawing_data = data.get("drawing_data") or []
        created_at = int(time.time() * 1000)

        strat = PlaybookStrat(
            strat_id=strat_id,
            title=title,
            map_name=map_name,
            side=side,
            round_number=int(round_number) if round_number is not None else None,
            match_id=match_id,
            description=description,
            drawing_data=drawing_data,
            created_at=created_at,
        )
        self.repo.insert_strat(strat)
        return strat.to_dict()

    def get_playbook_strat(self, strat_id: str) -> Optional[dict[str, Any]]:
        """Retrieve a playbook strategy by its strat_id."""
        strat = self.repo.get_strat(strat_id)
        return strat.to_dict() if strat else None

    def list_playbook_strats(
        self,
        map_name: Optional[str] = None,
        side: Optional[str] = None,
        match_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """List saved playbook strategies."""
        strats = self.repo.list_strats(map_name=map_name, side=side, match_id=match_id)
        return [s.to_dict() for s in strats]

    def update_playbook_strat(self, strat_id: str, data: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Update an existing playbook strategy."""
        existing = self.repo.get_strat(strat_id)
        if not existing:
            return None

        if "title" in data:
            existing.title = data["title"]
        if "map_name" in data:
            existing.map_name = data["map_name"]
        if "side" in data:
            existing.side = data["side"]
        if "round_number" in data:
            existing.round_number = int(data["round_number"]) if data["round_number"] is not None else None
        if "match_id" in data:
            existing.match_id = data["match_id"]
        if "description" in data:
            existing.description = data["description"]
        if "drawing_data" in data:
            existing.drawing_data = data["drawing_data"]

        self.repo.update_strat(existing)
        return existing.to_dict()

    def delete_playbook_strat(self, strat_id: str) -> bool:
        """Delete a playbook strategy."""
        return self.repo.delete_strat(strat_id)

    # ------------------------------------------------------------------
    # Automated Video Clipping & Highlight Reel Generation
    # ------------------------------------------------------------------
    def get_highlight_candidates(
        self, match_id: str, player_puuid: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Discover auto-detected highlight moments (clutches, swings, multi-kills, flaws)."""
        candidates = self.clipper.detect_highlight_candidates(match_id, player_puuid=player_puuid)
        return [c.to_dict() for c in candidates]

    def render_highlight_clip(
        self,
        match_id: str,
        candidate_id: str,
        pre_roll: Optional[float] = None,
        post_roll: Optional[float] = None,
    ) -> dict[str, Any]:
        """Render an MP4 clip for a specific candidate moment."""
        return self.clipper.render_candidate_clip(
            match_id=match_id,
            candidate_id=candidate_id,
            pre_roll=pre_roll,
            post_roll=post_roll,
        )

    def compile_highlights_montage(
        self,
        match_id: str,
        candidate_ids: Optional[list[str]] = None,
        title: Optional[str] = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        """Compile selected or top highlight clips into a single continuous review reel."""
        return self.clipper.compile_highlight_reel(
            match_id=match_id,
            candidate_ids=candidate_ids,
            title=title,
            limit=limit,
        )

    def list_saved_match_clips(self, match_id: Optional[str] = None) -> list[dict[str, Any]]:
        """List previously exported MP4 clips from the data/clips directory."""
        return self.clipper.list_saved_clips(match_id=match_id)

    # ------------------------------------------------------------------
    # Multi-POV / Round-over-Round Side-by-Side Comparison
    # ------------------------------------------------------------------
    def compare_rounds(
        self,
        match_id: str,
        round_a: int,
        round_b: int,
        target_puuid: Optional[str] = None,
    ) -> dict[str, Any]:
        """Perform side-by-side round comparison and generate tactical delta takeaways."""
        result = self.round_comparator.compare(
            match_id=match_id,
            round_a_num=round_a,
            round_b_num=round_b,
            target_puuid=target_puuid,
        )
        return result.to_dict()






