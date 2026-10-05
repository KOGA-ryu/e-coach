"""Parser for Riot VAL-MATCH-V1 and local client match payloads."""

import logging
from typing import Any, Optional

from vallens.analytics.projection import CoordinateProjector
from vallens.models import MatchEvent, MatchMetadata

logger = logging.getLogger(__name__)


class MatchParser:
    """Parses raw Valorant match JSON payloads into MatchMetadata and MatchEvent domain objects."""

    def __init__(self, projector: Optional[CoordinateProjector] = None):
        self.projector = projector or CoordinateProjector()

    def parse_match(self, raw_data: dict[str, Any]) -> tuple[MatchMetadata, list[MatchEvent]]:
        """Extract MatchMetadata and a sequence of normalized MatchEvents from match JSON."""
        match_info = raw_data.get("matchInfo", {})

        match_id = match_info.get("matchId") or raw_data.get("matchId", "unknown_match")
        map_id = match_info.get("mapId") or raw_data.get("mapId", "unknown_map")
        game_mode = match_info.get("gameMode") or raw_data.get("gameMode", "Standard")
        match_duration = match_info.get("gameLengthMillis") or raw_data.get("gameLengthMillis", 0)
        timestamp = match_info.get("gameStartMillis") or raw_data.get("gameStartMillis", 0)

        metadata = MatchMetadata(
            match_id=match_id,
            map_id=map_id,
            game_mode=game_mode,
            match_duration=int(match_duration),
            timestamp=int(timestamp),
        )

        events: list[MatchEvent] = []
        round_results = raw_data.get("roundResults", [])

        # Track running estimated game time in case round results don't have absolute timestamps
        estimated_game_time_ms = 0

        for r_idx, round_data in enumerate(round_results):
            round_num = round_data.get("roundNum", r_idx)
            round_events = self._parse_round(match_id, map_id, round_num, round_data, estimated_game_time_ms)
            events.extend(round_events)

            # Advance estimated game time by standard round length (~100s) if not specified
            round_duration = round_data.get("roundDurationMillis", 100_000)
            estimated_game_time_ms += round_duration

        # Sort all match events chronologically
        events.sort(key=lambda e: e.event_time_ms)

        return metadata, events

    def _parse_round(
        self,
        match_id: str,
        map_id: str,
        round_num: int,
        round_data: dict[str, Any],
        round_start_fallback_ms: int,
    ) -> list[MatchEvent]:
        """Parse events for a single round."""
        events: list[MatchEvent] = []

        # Find anchor for round start time
        round_start_ms = round_start_fallback_ms
        first_kill_anchor = None

        # Check kills inside playerStats or top-level kills list
        round_kills: list[dict[str, Any]] = []
        if "kills" in round_data:
            round_kills.extend(round_data["kills"])

        player_stats = round_data.get("playerStats", [])
        for ps in player_stats:
            for k in ps.get("kills", []):
                round_kills.append(k)

        # Detect round start timestamp if gameTime and roundTime exist
        for k in round_kills:
            game_time = k.get("timeSinceGameStartMillis") or k.get("gameTime")
            round_time = k.get("timeSinceRoundStartMillis") or k.get("roundTime")
            if game_time is not None and round_time is not None:
                first_kill_anchor = max(0, int(game_time) - int(round_time))
                round_start_ms = first_kill_anchor
                break

        # Round Start Event
        events.append(
            MatchEvent(
                match_id=match_id,
                round_number=round_num,
                event_type="round_start",
                event_time_ms=round_start_ms,
                metadata={"round_num": round_num},
            )
        )

        # Bomb Plant Event
        plant_time_offset = round_data.get("plantRoundTime")
        if plant_time_offset is not None and plant_time_offset > 0:
            plant_time_ms = round_start_ms + int(plant_time_offset)
            planter_puuid = round_data.get("bombPlanter")
            plant_loc = round_data.get("plantLocation") or {}
            raw_px = plant_loc.get("x")
            raw_py = plant_loc.get("y")

            norm_px, norm_py = (None, None)
            if raw_px is not None and raw_py is not None:
                norm_px, norm_py = self.projector.world_to_norm(map_id, raw_px, raw_py)

            events.append(
                MatchEvent(
                    match_id=match_id,
                    round_number=round_num,
                    event_type="plant",
                    event_time_ms=plant_time_ms,
                    player_puuid=planter_puuid,
                    pos_x=norm_px,
                    pos_y=norm_py,
                    metadata={
                        "site": round_data.get("plantSite"),
                        "raw_x": raw_px,
                        "raw_y": raw_py,
                    },
                )
            )

        # Bomb Defuse Event
        defuse_time_offset = round_data.get("defuseRoundTime")
        if defuse_time_offset is not None and defuse_time_offset > 0:
            defuse_time_ms = round_start_ms + int(defuse_time_offset)
            defuser_puuid = round_data.get("bombDefuser")
            defuse_loc = round_data.get("defuseLocation") or {}
            raw_dx = defuse_loc.get("x")
            raw_dy = defuse_loc.get("y")

            norm_dx, norm_dy = (None, None)
            if raw_dx is not None and raw_dy is not None:
                norm_dx, norm_dy = self.projector.world_to_norm(map_id, raw_dx, raw_dy)

            events.append(
                MatchEvent(
                    match_id=match_id,
                    round_number=round_num,
                    event_type="defuse",
                    event_time_ms=defuse_time_ms,
                    player_puuid=defuser_puuid,
                    pos_x=norm_dx,
                    pos_y=norm_dy,
                    metadata={
                        "raw_x": raw_dx,
                        "raw_y": raw_dy,
                    },
                )
            )

        # Kill and Death Events
        seen_kills: set[str] = set()
        for k in round_kills:
            killer_puuid = k.get("killer")
            victim_puuid = k.get("victim")
            game_time = k.get("timeSinceGameStartMillis") or k.get("gameTime")
            round_time = k.get("timeSinceRoundStartMillis") or k.get("roundTime")

            if game_time is not None:
                event_time_ms = int(game_time)
            elif round_time is not None:
                event_time_ms = round_start_ms + int(round_time)
            else:
                event_time_ms = round_start_ms

            # Deduplicate if kills are present in both round_data and playerStats
            kill_key = f"{killer_puuid}:{victim_puuid}:{event_time_ms}"
            if kill_key in seen_kills:
                continue
            seen_kills.add(kill_key)

            finishing_damage = k.get("finishingDamage", {})
            weapon = finishing_damage.get("damageItem")
            damage_type = finishingDamage = finishing_damage.get("damageType")

            # Extract victim position
            victim_loc = k.get("victimLocation") or {}
            vx = victim_loc.get("x")
            vy = victim_loc.get("y")
            v_norm_x, v_norm_y = (None, None)
            if vx is not None and vy is not None:
                v_norm_x, v_norm_y = self.projector.world_to_norm(map_id, vx, vy)

            # Extract killer position from playerLocations
            kx, ky = (None, None)
            k_norm_x, k_norm_y = (None, None)
            for ploc in k.get("playerLocations", []):
                puuid = ploc.get("puuid") or ploc.get("subject")
                if puuid == killer_puuid:
                    loc = ploc.get("location", {})
                    kx = loc.get("x")
                    ky = loc.get("y")
                    if kx is not None and ky is not None:
                        k_norm_x, k_norm_y = self.projector.world_to_norm(map_id, kx, ky)
                    break

            # 1. Killer event
            if killer_puuid:
                events.append(
                    MatchEvent(
                        match_id=match_id,
                        round_number=round_num,
                        event_type="kill",
                        event_time_ms=event_time_ms,
                        player_puuid=killer_puuid,
                        pos_x=k_norm_x,
                        pos_y=k_norm_y,
                        metadata={
                            "victim": victim_puuid,
                            "weapon": weapon,
                            "damage_type": damage_type,
                            "victim_pos": {"norm_x": v_norm_x, "norm_y": v_norm_y, "raw_x": vx, "raw_y": vy},
                            "raw_x": kx,
                            "raw_y": ky,
                        },
                    )
                )

            # 2. Death event for victim
            if victim_puuid:
                events.append(
                    MatchEvent(
                        match_id=match_id,
                        round_number=round_num,
                        event_type="death",
                        event_time_ms=event_time_ms,
                        player_puuid=victim_puuid,
                        pos_x=v_norm_x,
                        pos_y=v_norm_y,
                        metadata={
                            "killer": killer_puuid,
                            "weapon": weapon,
                            "damage_type": damage_type,
                            "killer_pos": {"norm_x": k_norm_x, "norm_y": k_norm_y, "raw_x": kx, "raw_y": ky},
                            "raw_x": vx,
                            "raw_y": vy,
                        },
                    )
                )

        # Round End Event
        max_round_event_time = max([e.event_time_ms for e in events] + [round_start_ms + 10_000])
        events.append(
            MatchEvent(
                match_id=match_id,
                round_number=round_num,
                event_type="round_end",
                event_time_ms=max_round_event_time,
                metadata={
                    "winning_team": round_data.get("winningTeam"),
                    "round_result": round_data.get("roundResult"),
                    "ceremony": round_data.get("roundCeremony"),
                },
            )
        )

        return events
