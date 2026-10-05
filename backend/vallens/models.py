"""Data models for ValLens match data, telemetry, and tagging."""

from dataclasses import dataclass, field
from typing import Any, Optional
import json


@dataclass
class MatchMetadata:
    """Metadata representing a single Valorant match."""
    match_id: str
    map_id: str
    game_mode: str
    match_duration: int  # in milliseconds
    timestamp: int       # epoch millisecond timestamp
    video_filepath: Optional[str] = None

    def to_tuple(self) -> tuple:
        return (
            self.match_id,
            self.map_id,
            self.game_mode,
            self.match_duration,
            self.timestamp,
            self.video_filepath,
        )


@dataclass
class MatchEvent:
    """An event occurring during a match (kill, death, round start/end, plant, defuse)."""
    match_id: str
    round_number: int
    event_type: str  # 'kill', 'death', 'round_start', 'round_end', 'plant', 'defuse'
    event_time_ms: int
    event_id: Optional[int] = None
    player_puuid: Optional[str] = None
    pos_x: Optional[float] = None  # Normalized map coordinate (0.0 to 1.0)
    pos_y: Optional[float] = None  # Normalized map coordinate (0.0 to 1.0)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def metadata_json(self) -> str:
        return json.dumps(self.metadata)

    def to_tuple(self) -> tuple:
        return (
            self.match_id,
            self.round_number,
            self.event_type,
            self.event_time_ms,
            self.player_puuid,
            self.pos_x,
            self.pos_y,
            self.metadata_json,
        )


@dataclass
class VodTag:
    """Custom tagging record logged during solo or coach review."""
    match_id: str
    timestamp_ms: int
    tag_category: str  # e.g., 'Mechanics', 'Positioning', 'Utility', 'Decision'
    tag_name: str      # e.g., 'crosshair_placement', 'over_peeking'
    author_type: str   # 'solo' or 'coach'
    tag_id: Optional[int] = None
    event_id: Optional[int] = None

    def to_tuple(self) -> tuple:
        return (
            self.match_id,
            self.event_id,
            self.timestamp_ms,
            self.tag_category,
            self.tag_name,
            self.author_type,
        )


@dataclass
class CoachNote:
    """Timestamped coach note or voice memo logged during VOD review."""
    match_id: str
    round_number: int
    timestamp_ms: int
    author_type: str  # 'coach' or 'solo'
    text_note: str = ""
    audio_filepath: Optional[str] = None
    created_at: int = 0
    note_id: Optional[int] = None

    def to_tuple(self) -> tuple:
        return (
            self.match_id,
            self.round_number,
            self.timestamp_ms,
            self.author_type,
            self.text_note,
            self.audio_filepath,
            self.created_at,
        )


@dataclass
class MatchPlayer:
    """Player roster and agent selection data for a match."""
    match_id: str
    player_puuid: str
    game_name: str
    tag_line: str
    team_id: str
    character_id: str  # Agent UUID
    score: int = 0
    rounds_played: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0

    def to_tuple(self) -> tuple:
        return (
            self.match_id,
            self.player_puuid,
            self.game_name,
            self.tag_line,
            self.team_id,
            self.character_id,
            self.score,
            self.rounds_played,
            self.kills,
            self.deaths,
            self.assists,
        )

