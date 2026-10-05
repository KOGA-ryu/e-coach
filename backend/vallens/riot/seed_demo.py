"""Demo fixture generator to seed realistic multi-match telemetry for Ascent and Haven."""

import json
import time
from typing import Optional

from vallens.db.database import Database
from vallens.models import MatchEvent, MatchMetadata, VodTag
from vallens.service import ValLensService


def seed_demo_data(service: Optional[ValLensService] = None) -> list[str]:
    """Seed multi-match data into database for multi-match heatmap aggregation demo."""
    s = service or ValLensService()

    match_ids = []

    # Match 2: Ascent Competitive Match #2 (18 rounds)
    match2_id = "match-ascent-comp-002"
    m2 = MatchMetadata(
        match_id=match2_id,
        map_id="/Game/Maps/Ascent/Ascent",
        game_mode="/Game/GameModes/Bomb/BombGameMode.BombGameMode_C",
        match_duration=2250000,
        timestamp=int(time.time() * 1000) - 86400000,  # 1 day ago
        video_filepath=None,
    )
    s.repo.insert_match(m2)
    match_ids.append(match2_id)

    # Telemetry events for Match 2:
    # A-Main cluster: norm_x ~ 0.484, norm_y ~ 0.201 (Ace deaths on Attack rounds 1-5)
    # Mid Courtyard: norm_x ~ 0.440, norm_y ~ 0.460 (Ace deaths on Attack rounds 6-9)
    # B-Site Market: norm_x ~ 0.355, norm_y ~ 0.580 (Ace deaths on Defense rounds 13-16)
    m2_events = []
    m2_tags = []

    # Round 0-11: Attack
    # Deaths in A-Main
    a_main_coords = [
        (0.483, 0.203), (0.486, 0.198), (0.482, 0.205),
        (0.487, 0.202), (0.485, 0.199), (0.484, 0.204)
    ]
    for i, (nx, ny) in enumerate(a_main_coords):
        t_ms = 40000 + i * 150000
        ev = MatchEvent(
            match_id=match2_id,
            round_number=i,
            event_type="death",
            event_time_ms=t_ms,
            player_puuid="player-ace-001",
            pos_x=nx,
            pos_y=ny,
            metadata={"killer": "enemy-jett", "weapon": "Vandal", "damage_type": "Weapon"},
        )
        m2_events.append(ev)

    # Mid Courtyard deaths
    mid_coords = [(0.441, 0.458), (0.439, 0.462), (0.443, 0.459)]
    for i, (nx, ny) in enumerate(mid_coords):
        rnd = 6 + i
        t_ms = 45000 + rnd * 150000
        ev = MatchEvent(
            match_id=match2_id,
            round_number=rnd,
            event_type="death",
            event_time_ms=t_ms,
            player_puuid="player-ace-001",
            pos_x=nx,
            pos_y=ny,
            metadata={"killer": "enemy-sova", "weapon": "Operator", "damage_type": "Weapon"},
        )
        m2_events.append(ev)

    # Ace kills on Defense (B-Site & A-Site)
    kill_coords = [
        (0.350, 0.145), (0.352, 0.148), (0.348, 0.142),
        (0.245, 0.650), (0.248, 0.652)
    ]
    for i, (nx, ny) in enumerate(kill_coords):
        rnd = 12 + i
        t_ms = 50000 + rnd * 150000
        ev = MatchEvent(
            match_id=match2_id,
            round_number=rnd,
            event_type="kill",
            event_time_ms=t_ms,
            player_puuid="player-ace-001",
            pos_x=nx,
            pos_y=ny,
            metadata={"victim": "enemy-entry", "weapon": "Phantom", "damage_type": "Weapon"},
        )
        m2_events.append(ev)

    s.repo.insert_events(m2_events)

    # Insert review tags on Match 2
    s.add_vod_tag(match2_id, timestamp_ms=40000, category="Positioning", name="over_peeking", author_type="solo")
    s.add_vod_tag(match2_id, timestamp_ms=190000, category="Positioning", name="over_peeking", author_type="coach")
    s.add_vod_tag(match2_id, timestamp_ms=340000, category="Mechanics", name="crosshair_placement", author_type="solo")
    s.add_vod_tag(match2_id, timestamp_ms=945000, category="Decision", name="forced_fight", author_type="solo")

    # Match 3: Haven Competitive Match (20 rounds)
    match3_id = "match-haven-comp-003"
    m3 = MatchMetadata(
        match_id=match3_id,
        map_id="/Game/Maps/Triad/Triad",
        game_mode="/Game/GameModes/Bomb/BombGameMode.BombGameMode_C",
        match_duration=2400000,
        timestamp=int(time.time() * 1000) - 172800000,  # 2 days ago
        video_filepath=None,
    )
    s.repo.insert_match(m3)
    match_ids.append(match3_id)

    # Haven events:
    # A-Long: norm_x ~ 0.65, norm_y ~ 0.35
    # C-Long: norm_x ~ 0.35, norm_y ~ 0.65
    m3_events = []
    haven_a_deaths = [(0.652, 0.351), (0.648, 0.353), (0.650, 0.349), (0.654, 0.352)]
    for i, (nx, ny) in enumerate(haven_a_deaths):
        m3_events.append(
            MatchEvent(
                match_id=match3_id,
                round_number=i,
                event_type="death",
                event_time_ms=35000 + i * 140000,
                player_puuid="player-ace-001",
                pos_x=nx,
                pos_y=ny,
                metadata={"killer": "enemy-reyna", "weapon": "Vandal", "damage_type": "Weapon"},
            )
        )
    haven_c_deaths = [(0.351, 0.648), (0.349, 0.652), (0.353, 0.650)]
    for i, (nx, ny) in enumerate(haven_c_deaths):
        m3_events.append(
            MatchEvent(
                match_id=match3_id,
                round_number=5 + i,
                event_type="death",
                event_time_ms=40000 + (5 + i) * 140000,
                player_puuid="player-ace-001",
                pos_x=nx,
                pos_y=ny,
                metadata={"killer": "enemy-chamber", "weapon": "Operator", "damage_type": "Weapon"},
            )
        )
    s.repo.insert_events(m3_events)

    s.add_vod_tag(match3_id, timestamp_ms=35000, category="Positioning", name="poor_spacing", author_type="solo")
    s.add_vod_tag(match3_id, timestamp_ms=175000, category="Utility", name="late_flash", author_type="coach")

    return match_ids


if __name__ == "__main__":
    ids = seed_demo_data()
    print(f"Successfully seeded demo matches: {ids}")
