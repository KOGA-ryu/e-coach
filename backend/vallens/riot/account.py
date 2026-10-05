"""Account linking and match history synchronization."""

import base64
import json
import logging
from pathlib import Path
import ssl
from typing import TYPE_CHECKING, Any, Optional
import urllib.error
import urllib.parse
import urllib.request

from vallens.models import MatchMetadata
from vallens.obs.local_client import LocalClient
from vallens.riot.client import RiotApiClient

if TYPE_CHECKING:
    from vallens.service import ValLensService

logger = logging.getLogger(__name__)


class AccountConnector:
    """Manages linking Riot Accounts via Local Client lockfile or Remote API credentials."""

    def __init__(
        self,
        service: Optional[Any] = None,
        riot_api_key: Optional[str] = None,
        region: str = "na",
    ):
        if service is None:
            from vallens.service import ValLensService
            self.service = ValLensService()
        else:
            self.service = service
        self.riot_api_key = riot_api_key
        self.region = region.lower()
        self.local_client = LocalClient()

    def detect_local_account(self) -> Optional[dict[str, Any]]:
        """Detect logged-in player from running local Valorant / Riot Client."""
        if not self.local_client.read_lockfile():
            return None

        port = self.local_client.port
        password = self.local_client.password
        protocol = self.local_client.protocol

        auth = base64.b64encode(f"riot:{password}".encode("utf-8")).decode("ascii")
        headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        # Query chat session / user info
        url = f"{protocol}://127.0.0.1:{port}/chat/v1/session"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                puuid = data.get("puuid")
                name = data.get("game_name")
                tag = data.get("game_tag")
                if puuid:
                    return {
                        "puuid": puuid,
                        "riot_id": f"{name}#{tag}" if name and tag else "Player",
                        "game_name": name,
                        "game_tag": tag,
                        "source": "local_client",
                    }
        except Exception as e:
            logger.debug(f"Local session query failed: {e}")

        # Fallback to presences
        presences = self.local_client.query_presences()
        for p in presences:
            puuid = p.get("puuid")
            name = p.get("game_name")
            tag = p.get("game_tag")
            if puuid and name and tag:
                return {
                    "puuid": puuid,
                    "riot_id": f"{name}#{tag}",
                    "game_name": name,
                    "game_tag": tag,
                    "source": "local_presence",
                }

        return None

    def sync_recent_matches(
        self,
        puuid: str,
        limit: int = 5,
        api_key: Optional[str] = None,
        region: Optional[str] = None,
    ) -> list[MatchMetadata]:
        """Fetch and ingest recent matches for a player PUUID via Riot API."""
        key = api_key or self.riot_api_key
        reg = region or self.region
        if not key:
            raise ValueError(
                "Riot API Key is required to fetch match history from remote servers. "
                "Get one at https://developer.riotgames.com/"
            )

        client = RiotApiClient(api_key=key, region=reg)
        logger.info(f"Querying match history for PUUID: {puuid} ({reg.upper()})...")

        matchlist = client.fetch_matchlist_by_puuid(puuid)
        history = matchlist.get("history", [])[:limit]

        ingested: list[MatchMetadata] = []
        for item in history:
            match_id = item.get("matchId")
            if not match_id:
                continue

            # Check if match already ingested
            existing = self.service.repo.get_match(match_id)
            if existing:
                ingested.append(existing)
                continue

            try:
                raw_match = client.fetch_match(match_id)
                meta = self.service.ingest_match_payload(raw_match)
                ingested.append(meta)
                logger.info(f"Successfully ingested match: {match_id} (Map: {meta.map_id})")
            except Exception as e:
                logger.error(f"Failed to ingest match {match_id}: {e}")

        return ingested

    def sync_by_henrik_api(
        self,
        name: str,
        tag: str,
        region: str = "na",
        api_key: Optional[str] = None,
        limit: int = 3,
    ) -> list[MatchMetadata]:
        """Fetch and ingest matches via community HenrikDev API using in-game Riot ID (Name#Tag)."""
        clean_name = urllib.parse.quote(name)
        clean_tag = urllib.parse.quote(tag)
        url = f"https://api.henrikdev.xyz/valorant/v3/matches/{region}/{clean_name}/{clean_tag}"

        headers = {"User-Agent": "ValLens/0.1.0"}
        if api_key:
            headers["Authorization"] = api_key

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        raw_matches = data.get("data", [])[:limit]
        ingested: list[MatchMetadata] = []

        for m in raw_matches:
            match_id = m.get("metadata", {}).get("matchid")
            if not match_id:
                continue

            existing = self.service.repo.get_match(match_id)
            if existing:
                ingested.append(existing)
                continue

            # Adapt third-party format to match parser structure if needed
            try:
                adapted = self._adapt_henrik_match(m)
                meta = self.service.ingest_match_payload(adapted)
                ingested.append(meta)
            except Exception as e:
                logger.error(f"Failed to ingest match {match_id}: {e}")

        return ingested

    def _adapt_henrik_match(self, h: dict[str, Any]) -> dict[str, Any]:
        """Convert third-party match structure into standard VAL-MATCH-V1 format."""
        meta = h.get("metadata", {})
        return {
            "matchInfo": {
                "matchId": meta.get("matchid"),
                "mapId": f"/Game/Maps/{meta.get('map')}/{meta.get('map')}",
                "gameMode": meta.get("mode", "Standard"),
                "gameLengthMillis": meta.get("game_length", 0) * 1000,
                "gameStartMillis": meta.get("game_start", 0) * 1000,
            },
            "players": [
                {
                    "puuid": p.get("puuid"),
                    "gameName": p.get("name"),
                    "tagLine": p.get("tag"),
                    "teamId": p.get("team"),
                    "characterId": p.get("character"),
                }
                for p in h.get("players", {}).get("all_players", [])
            ],
            "roundResults": [
                {
                    "roundNum": idx,
                    "roundResult": r.get("end_type", "Eliminated"),
                    "roundCeremony": r.get("round_ceremony", "CeremonyDefault"),
                    "winningTeam": r.get("winning_team"),
                    "bombPlanter": r.get("plant_events", {}).get("planted_by", {}).get("puuid"),
                    "plantRoundTime": r.get("plant_events", {}).get("plant_time_in_round"),
                    "bombDefuser": r.get("defuse_events", {}).get("defused_by", {}).get("puuid"),
                    "defuseRoundTime": r.get("defuse_events", {}).get("defuse_time_in_round"),
                    "kills": [
                        {
                            "timeSinceRoundStartMillis": k.get("kill_time_in_round"),
                            "timeSinceGameStartMillis": k.get("kill_time_in_match"),
                            "killer": k.get("killer_puuid"),
                            "victim": k.get("victim_puuid"),
                            "victimLocation": {
                                "x": k.get("victim_death_report", {}).get("location", {}).get("x", 0),
                                "y": k.get("victim_death_report", {}).get("location", {}).get("y", 0),
                            },
                            "finishingDamage": {
                                "damageItem": k.get("damage_weapon_name", "Weapon"),
                                "damageType": "Weapon",
                            },
                        }
                        for k in r.get("player_stats", [])
                        for k in k.get("kill_events", [])
                    ],
                }
                for idx, r in enumerate(h.get("rounds", []))
            ],
        }
