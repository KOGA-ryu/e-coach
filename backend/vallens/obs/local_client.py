"""Local Riot Client API and lockfile reader for real-time game-state detection."""

import base64
import json
import logging
import os
from pathlib import Path
import ssl
from typing import Any, Optional
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


class GameState:
    DISCONNECTED = "DISCONNECTED"
    MENUS = "MENUS"
    PREGAME = "PREGAME"    # Agent Select
    INGAME = "INGAME"      # Match active
    POSTGAME = "POSTGAME"  # Match summary


class LocalClient:
    """Interfaces with the local Riot Client / Valorant REST endpoints."""

    def __init__(self, lockfile_path: Optional[str | Path] = None):
        self.lockfile_path = Path(lockfile_path) if lockfile_path else self._find_default_lockfile()
        self.port: Optional[int] = None
        self.password: Optional[str] = None
        self.protocol: str = "https"

    @staticmethod
    def _find_default_lockfile() -> Optional[Path]:
        """Locate lockfile in environment variable or standard OS directories."""
        # 1. Explicit env override
        custom_env = os.environ.get("RIOT_LOCKFILE_PATH")
        if custom_env:
            p = Path(custom_env)
            if p.exists():
                return p

        # 2. Windows LocalAppData
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            path = Path(local_app_data) / "Riot Games" / "Riot Client" / "Config" / "lockfile"
            if path.exists():
                return path

        # 3. macOS Application Support
        home = Path.home()
        mac_path = home / "Library" / "Application Support" / "Riot Games" / "Riot Client" / "Config" / "lockfile"
        if mac_path.exists():
            return mac_path

        return None

    def read_lockfile(self) -> bool:
        """Parse lockfile (name:pid:port:password:protocol)."""
        if not self.lockfile_path or not self.lockfile_path.exists():
            return False

        try:
            with open(self.lockfile_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            parts = content.split(":")
            if len(parts) >= 5:
                self.port = int(parts[2])
                self.password = parts[3]
                self.protocol = parts[4]
                return True
        except Exception as e:
            logger.warning(f"Failed to read lockfile {self.lockfile_path}: {e}")
        return False

    def _get_auth_header(self) -> str:
        token = base64.b64encode(f"riot:{self.password}".encode("utf-8")).decode("ascii")
        return f"Basic {token}"

    def query_presences(self) -> list[dict[str, Any]]:
        """Fetch local player presences from Riot Client chat endpoint."""
        if not self.port or not self.password:
            if not self.read_lockfile():
                return []

        url = f"{self.protocol}://127.0.0.1:{self.port}/chat/v4/presences"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": self._get_auth_header(),
                "Accept": "application/json",
            },
        )

        # Riot client uses self-signed SSL certificates locally
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        try:
            with urllib.request.urlopen(req, context=ctx, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("presences", [])
        except Exception as e:
            logger.debug(f"Local client presence query failed: {e}")
            return []

    def get_session_state(self) -> dict[str, Any]:
        """Detect current game session state (MENUS, PREGAME, INGAME, POSTGAME)."""
        if not self.read_lockfile():
            return {
                "state": GameState.DISCONNECTED,
                "match_map": None,
                "map_name": None,
                "agent": None,
                "player_name": None,
                "queue_id": None,
                "connected": False,
                "port": None,
                "protocol": self.protocol,
                "is_mock": False,
            }

        presences = self.query_presences()
        if not presences:
            return {
                "state": GameState.MENUS,
                "match_map": None,
                "map_name": None,
                "agent": None,
                "player_name": None,
                "queue_id": None,
                "connected": True,
                "port": self.port,
                "protocol": self.protocol,
                "is_mock": False,
            }

        # Inspect local user presence
        for p in presences:
            priv_b64 = p.get("private")
            if not priv_b64:
                continue
            try:
                decoded = json.loads(base64.b64decode(priv_b64).decode("utf-8"))
                loop_state = decoded.get("sessionLoopState", GameState.MENUS)
                match_map = decoded.get("matchMap")
                map_name = match_map.split("/")[-1] if match_map else None

                p_name = p.get("game_name")
                p_tag = p.get("game_tag")
                player_str = f"{p_name}#{p_tag}" if p_name and p_tag else None

                return {
                    "state": loop_state,
                    "match_map": match_map,
                    "map_name": map_name,
                    "agent": decoded.get("characterSelectionState") or decoded.get("agent"),
                    "player_name": player_str,
                    "queue_id": decoded.get("queueId"),
                    "party_state": decoded.get("partyState"),
                    "connected": True,
                    "port": self.port,
                    "protocol": self.protocol,
                    "is_mock": False,
                    "raw": decoded,
                }
            except Exception:
                continue

        return {
            "state": GameState.MENUS,
            "match_map": None,
            "map_name": None,
            "agent": None,
            "player_name": None,
            "queue_id": None,
            "connected": True,
            "port": self.port,
            "protocol": self.protocol,
            "is_mock": False,
        }


class MockLocalClient:
    """Configurable mock client to simulate game session state transitions."""

    def __init__(
        self,
        initial_state: str = GameState.MENUS,
        match_map: str = "/Game/Maps/Ascent/Ascent",
        agent: str = "Sova",
        player_name: str = "Ace#NA1",
    ):
        self.current_state = initial_state
        self.match_map = match_map
        self.agent = agent
        self.player_name = player_name
        self.port = 55555
        self.protocol = "https"
        self.connected = True
        self.queue_id = "competitive"

    def set_state(
        self,
        state: str,
        match_map: Optional[str] = None,
        agent: Optional[str] = None,
        player_name: Optional[str] = None,
        queue_id: Optional[str] = None,
    ) -> None:
        self.current_state = state
        if match_map:
            self.match_map = match_map
        if agent:
            self.agent = agent
        if player_name:
            self.player_name = player_name
        if queue_id:
            self.queue_id = queue_id

    def read_lockfile(self) -> bool:
        return True

    def get_session_state(self) -> dict[str, Any]:
        map_name = self.match_map.split("/")[-1] if self.match_map else "Ascent"
        return {
            "state": self.current_state,
            "match_map": self.match_map,
            "map_name": map_name,
            "agent": self.agent,
            "player_name": self.player_name,
            "queue_id": self.queue_id,
            "connected": True,
            "port": self.port,
            "protocol": self.protocol,
            "is_mock": True,
        }
