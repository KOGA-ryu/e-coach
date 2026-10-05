"""Orchestrates automated OBS session recording, timeline synchronization, and EDL export."""

import logging
from pathlib import Path
import threading
import time
from typing import Any, Callable, Optional

from vallens.obs.client import MockObsClient, ObsWebSocketClient
from vallens.obs.exporter import EdlExporter
from vallens.obs.local_client import GameState, LocalClient, MockLocalClient
from vallens.obs.sync import TimelineSynchronizer
from vallens.service import ValLensService

logger = logging.getLogger(__name__)


class CaptureController:
    """Manages the full automated capture loop: game state detection -> OBS recording -> timeline alignment -> EDL export."""

    def __init__(
        self,
        local_client: Optional[LocalClient | MockLocalClient] = None,
        obs_client: Optional[ObsWebSocketClient | MockObsClient] = None,
        service: Optional[ValLensService] = None,
        poll_interval: float = 1.0,
    ):
        self.local_client = local_client or LocalClient()
        self.obs_client = obs_client or MockObsClient()
        self.service = service or ValLensService()
        self.poll_interval = poll_interval

        self.last_state = GameState.DISCONNECTED
        self.current_match_id: Optional[str] = None
        self.recording_start_time: Optional[float] = None
        self.last_recorded_file: Optional[str] = None

        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Callbacks for UI updates or external listeners
        self.on_state_change: Optional[Callable[[str, str], None]] = None
        self.on_recording_started: Optional[Callable[[], None]] = None
        self.on_recording_finished: Optional[Callable[[str, list[Path]], None]] = None

    def poll_once(self) -> dict[str, Any]:
        """Perform a single iteration of game-state polling and trigger recording state actions."""
        session = self.local_client.get_session_state()
        new_state = session.get("state", GameState.DISCONNECTED)
        match_map = session.get("match_map")

        if new_state != self.last_state:
            logger.info(f"State transition: {self.last_state} -> {new_state} (Map: {match_map})")
            if self.on_state_change:
                self.on_state_change(self.last_state, new_state)

            # Trigger 1: Agent Select finished, entering INGAME -> Start Recording
            if self.last_state in (GameState.PREGAME, GameState.MENUS) and new_state == GameState.INGAME:
                self._handle_match_start(match_map)

            # Trigger 2: INGAME finished, returning to POSTGAME or MENUS -> Stop Recording & Export
            elif self.last_state == GameState.INGAME and new_state in (GameState.POSTGAME, GameState.MENUS):
                self._handle_match_end()

            self.last_state = new_state

        return {"state": new_state, "map": match_map}

    def _handle_match_start(self, match_map: Optional[str]) -> None:
        """Trigger OBS recording start."""
        try:
            self.obs_client.start_recording()
            self.recording_start_time = time.time()
            logger.info("OBS recording started for match.")
            if self.on_recording_started:
                self.on_recording_started()
        except Exception as e:
            logger.error(f"Failed to start OBS recording: {e}")

    def _handle_match_end(self) -> None:
        """Trigger OBS recording stop and generate synchronized EDL / chapter markers."""
        try:
            output_file = self.obs_client.stop_recording()
            self.last_recorded_file = output_file
            logger.info(f"OBS recording stopped: {output_file}")

            exported_files: list[Path] = []
            if output_file and self.current_match_id:
                exported_files = self.process_match_sync_and_edl(self.current_match_id, output_file)

            if self.on_recording_finished:
                self.on_recording_finished(output_file, exported_files)

        except Exception as e:
            logger.error(f"Failed to stop OBS recording or export EDL: {e}")

    def process_match_sync_and_edl(
        self, match_id: str, video_filepath: str, video_anchor_offset_ms: int = 0
    ) -> list[Path]:
        """Align match timeline, associate video with match in SQLite, and export EDL/chapters."""
        # 1. Update DB with video file path
        self.service.repo.update_video_path(match_id, video_filepath)

        # 2. Fetch match events from repository
        events = self.service.repo.get_events(match_id)
        if not events:
            logger.warning(f"No events found for match {match_id} to generate EDL.")
            return []

        # Find Round 0 Start timestamp in events
        round_0_start_ms = 0
        for e in events:
            if e.event_type == "round_start" and e.round_number == 0:
                round_0_start_ms = e.event_time_ms
                break

        synchronizer = TimelineSynchronizer(
            round_0_start_api_ms=round_0_start_ms,
            video_anchor_offset_ms=video_anchor_offset_ms,
        )

        vid_path = Path(video_filepath)
        base_name = vid_path.stem
        out_dir = vid_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        # 3. Generate CMX 3600 EDL, YouTube/VLC Chapters, and FFmpeg metadata
        edl_path = out_dir / f"{base_name}.edl"
        chapters_path = out_dir / f"{base_name}.chapters.txt"
        ffmeta_path = out_dir / f"{base_name}.ffmeta"

        EdlExporter.export_cmx3600_edl(events, synchronizer, vid_path.name, edl_path, title=base_name)
        EdlExporter.export_chapters_txt(events, synchronizer, chapters_path, include_kills=True)
        EdlExporter.export_ffmetadata(events, synchronizer, ffmeta_path, title=f"ValLens Review - {base_name}")

        logger.info(f"Generated EDL files: {edl_path}, {chapters_path}, {ffmeta_path}")
        return [edl_path, chapters_path, ffmeta_path]

    def start_polling(self) -> None:
        """Start polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("CaptureController polling loop started.")

    def stop_polling(self) -> None:
        """Stop polling thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("CaptureController polling loop stopped.")

    def _run_loop(self) -> None:
        while self._running:
            try:
                self.poll_once()
            except Exception as e:
                logger.error(f"Error during poll iteration: {e}")
            time.sleep(self.poll_interval)
