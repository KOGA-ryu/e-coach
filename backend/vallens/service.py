"""ValLens core ingestion and review service."""

import json
from pathlib import Path
from typing import Any, Optional

from vallens.analytics.projection import CoordinateProjector
from vallens.db.database import Database
from vallens.db.repository import MatchRepository
from vallens.models import MatchEvent, MatchMetadata, VodTag
from vallens.riot.client import RiotApiClient
from vallens.riot.parser import MatchParser


class ValLensService:
    """Central service orchestrating ingestion, persistence, and review queries."""

    def __init__(
        self,
        db: Optional[Database] = None,
        maps_file: Optional[Path | str] = None,
        riot_api_key: Optional[str] = None,
    ):
        self.db = db or Database()
        self.repo = MatchRepository(self.db)
        self.projector = CoordinateProjector(data_file=maps_file)
        self.parser = MatchParser(projector=self.projector)
        self.client = RiotApiClient(api_key=riot_api_key)

    def ingest_match_payload(
        self, raw_data: dict[str, Any], video_filepath: Optional[str] = None
    ) -> MatchMetadata:
        """Parse and persist a raw match JSON payload into SQLite."""
        metadata, events = self.parser.parse_match(raw_data)
        if video_filepath:
            metadata.video_filepath = video_filepath

        self.repo.insert_match(metadata)
        self.repo.insert_events(events)
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
