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
        """Locate lockfile in standard Windows AppData directory if running on Windows."""
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            path = Path(local_app_data) / "Riot Games" / "Riot Client" / "Config" / "lockfile"
            if path.exists():
                return path
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
        """Detect current game session state (MENUS, PREGAME, INGAME)."""
        presences = self.query_presences()
        if not presences:
            return {"state": GameState.DISCONNECTED, "match_map": None}

        # Inspect local user presence
        for p in presences:
            priv_b64 = p.get("private")
            if not priv_b64:
                continue
            try:
                decoded = json.loads(base64.b64decode(priv_b64).decode("utf-8"))
                loop_state = decoded.get("sessionLoopState")
                match_map = decoded.get("matchMap")
                if loop_state:
                    return {
                        "state": loop_state,
                        "match_map": match_map,
                        "party_state": decoded.get("partyState"),
                        "raw": decoded,
                    }
            except Exception:
                continue

        return {"state": GameState.MENUS, "match_map": None}


class MockLocalClient:
    """Configurable mock client to simulate game session state transitions."""

    def __init__(self, initial_state: str = GameState.MENUS, match_map: str = "/Game/Maps/Ascent/Ascent"):
        self.current_state = initial_state
        self.match_map = match_map

    def set_state(self, state: str, match_map: Optional[str] = None) -> None:
        self.current_state = state
        if match_map:
            self.match_map = match_map

    def get_session_state(self) -> dict[str, Any]:
        return {
            "state": self.current_state,
            "match_map": self.match_map,
        }
