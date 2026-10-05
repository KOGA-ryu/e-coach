"""Repository providing SQLite access for matches, telemetry events, and review tags."""

import json
from typing import Any, Optional
from vallens.db.database import Database
from vallens.models import CoachNote, MatchEvent, MatchMetadata, MatchPlayer, UtilityEvent, VodTag



class MatchRepository:
    """Manages persistence and queries for matches, telemetry events, and tags."""

    def __init__(self, db: Database):
        self.db = db

    def insert_match(self, match: MatchMetadata) -> None:
        """Insert or replace a match record."""
        sql = """
        INSERT OR REPLACE INTO matches (
            match_id, map_id, game_mode, match_duration, timestamp, video_filepath, video_offset_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?);
        """
        with self.db.connection() as conn:
            conn.execute(sql, match.to_tuple())

    def update_video_path(self, match_id: str, video_filepath: str) -> bool:
        """Associate a video recording file path with a match."""
        sql = "UPDATE matches SET video_filepath = ? WHERE match_id = ?;"
        with self.db.connection() as conn:
            cursor = conn.execute(sql, (video_filepath, match_id))
            return cursor.rowcount > 0

    def update_video_offset(self, match_id: str, offset_ms: int) -> bool:
        """Update the timeline alignment offset (in milliseconds) for a match video."""
        sql = "UPDATE matches SET video_offset_ms = ? WHERE match_id = ?;"
        with self.db.connection() as conn:
            cursor = conn.execute(sql, (offset_ms, match_id))
            return cursor.rowcount > 0

    def get_match(self, match_id: str) -> Optional[MatchMetadata]:
        """Fetch a match by its ID."""
        sql = "SELECT match_id, map_id, game_mode, match_duration, timestamp, video_filepath, COALESCE(video_offset_ms, 0) as video_offset_ms FROM matches WHERE match_id = ?;"
        with self.db.connection() as conn:
            row = conn.execute(sql, (match_id,)).fetchone()
            if not row:
                return None
            return MatchMetadata(
                match_id=row["match_id"],
                map_id=row["map_id"],
                game_mode=row["game_mode"],
                match_duration=row["match_duration"],
                timestamp=row["timestamp"],
                video_filepath=row["video_filepath"],
                video_offset_ms=row["video_offset_ms"],
            )

    def list_matches(self, limit: int = 50, offset: int = 0) -> list[MatchMetadata]:
        """List recent matches ordered by timestamp descending."""
        sql = "SELECT match_id, map_id, game_mode, match_duration, timestamp, video_filepath, COALESCE(video_offset_ms, 0) as video_offset_ms FROM matches ORDER BY timestamp DESC LIMIT ? OFFSET ?;"
        with self.db.connection() as conn:
            rows = conn.execute(sql, (limit, offset)).fetchall()
            return [
                MatchMetadata(
                    match_id=r["match_id"],
                    map_id=r["map_id"],
                    game_mode=r["game_mode"],
                    match_duration=r["match_duration"],
                    timestamp=r["timestamp"],
                    video_filepath=r["video_filepath"],
                    video_offset_ms=r["video_offset_ms"],
                )
                for r in rows
            ]

    def insert_events(self, events: list[MatchEvent]) -> int:
        """Bulk insert match events in a single transaction."""
        if not events:
            return 0

        sql = """
        INSERT INTO match_events (
            match_id, round_number, event_type, event_time_ms, player_puuid, pos_x, pos_y, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """
        payloads = [e.to_tuple() for e in events]
        with self.db.connection() as conn:
            cursor = conn.executemany(sql, payloads)
            return cursor.rowcount

    def get_events(
        self,
        match_id: str,
        round_number: Optional[int] = None,
        event_type: Optional[str] = None,
        player_puuid: Optional[str] = None,
    ) -> list[MatchEvent]:
        """Query events for a match with optional filtering."""
        query = ["SELECT event_id, match_id, round_number, event_type, event_time_ms, player_puuid, pos_x, pos_y, metadata FROM match_events WHERE match_id = ?"]
        params: list[Any] = [match_id]

        if round_number is not None:
            query.append("AND round_number = ?")
            params.append(round_number)
        if event_type is not None:
            query.append("AND event_type = ?")
            params.append(event_type)
        if player_puuid is not None:
            query.append("AND player_puuid = ?")
            params.append(player_puuid)

        query.append("ORDER BY event_time_ms ASC;")
        sql = " ".join(query)

        with self.db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            results = []
            for r in rows:
                meta = json.loads(r["metadata"]) if r["metadata"] else {}
                results.append(
                    MatchEvent(
                        event_id=r["event_id"],
                        match_id=r["match_id"],
                        round_number=r["round_number"],
                        event_type=r["event_type"],
                        event_time_ms=r["event_time_ms"],
                        player_puuid=r["player_puuid"],
                        pos_x=r["pos_x"],
                        pos_y=r["pos_y"],
                        metadata=meta,
                    )
                )
            return results

    def create_tag(self, tag: VodTag) -> int:
        """Insert a review tag and return its generated ID."""
        sql = """
        INSERT INTO vod_tags (
            match_id, event_id, timestamp_ms, tag_category, tag_name, author_type
        ) VALUES (?, ?, ?, ?, ?, ?);
        """
        with self.db.connection() as conn:
            cursor = conn.execute(sql, tag.to_tuple())
            return cursor.lastrowid

    # Alias for convenience
    insert_tag = create_tag

    def get_tags(
        self,
        match_id: str,
        event_id: Optional[int] = None,
        author_type: Optional[str] = None,
    ) -> list[VodTag]:
        """Fetch tags for a match."""
        query = ["SELECT tag_id, match_id, event_id, timestamp_ms, tag_category, tag_name, author_type FROM vod_tags WHERE match_id = ?"]
        params: list[Any] = [match_id]

        if event_id is not None:
            query.append("AND event_id = ?")
            params.append(event_id)
        if author_type is not None:
            query.append("AND author_type = ?")
            params.append(author_type)

        query.append("ORDER BY timestamp_ms ASC;")
        sql = " ".join(query)

        with self.db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [
                VodTag(
                    tag_id=r["tag_id"],
                    match_id=r["match_id"],
                    event_id=r["event_id"],
                    timestamp_ms=r["timestamp_ms"],
                    tag_category=r["tag_category"],
                    tag_name=r["tag_name"],
                    author_type=r["author_type"],
                )
                for r in rows
            ]

    # Alias for convenience
    get_tags_for_match = get_tags

    def delete_tag(self, tag_id: int) -> bool:
        """Delete a tag by ID."""
        sql = "DELETE FROM vod_tags WHERE tag_id = ?;"
        with self.db.connection() as conn:
            cursor = conn.execute(sql, (tag_id,))
            return cursor.rowcount > 0

    def get_tag_aggregations(
        self, match_id: Optional[str] = None, author_type: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Aggregate tag counts by category and tag name."""
        query = [
            "SELECT tag_category, tag_name, author_type, COUNT(*) as count FROM vod_tags WHERE 1=1"
        ]
        params: list[Any] = []
        if match_id is not None:
            query.append("AND match_id = ?")
            params.append(match_id)
        if author_type is not None:
            query.append("AND author_type = ?")
            params.append(author_type)

        query.append("GROUP BY tag_category, tag_name, author_type ORDER BY count DESC;")
        sql = " ".join(query)

        with self.db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [
                {
                    "category": r["tag_category"],
                    "name": r["tag_name"],
                    "author": r["author_type"],
                    "count": r["count"],
                }
                for r in rows
            ]

    def list_distinct_maps(self) -> list[dict[str, Any]]:
        """List distinct maps stored in matches, along with match and event counts."""
        sql = """
        SELECT 
            m.map_id,
            COUNT(DISTINCT m.match_id) as match_count,
            COUNT(e.event_id) as event_count,
            MAX(m.timestamp) as latest_timestamp
        FROM matches m
        LEFT JOIN match_events e ON m.match_id = e.match_id
        GROUP BY m.map_id
        ORDER BY latest_timestamp DESC;
        """
        with self.db.connection() as conn:
            rows = conn.execute(sql).fetchall()
            return [
                {
                    "map_id": r["map_id"],
                    "map_name": r["map_id"].strip("/").split("/")[-1] if r["map_id"] else "Unknown",
                    "match_count": r["match_count"],
                    "event_count": r["event_count"],
                    "latest_timestamp": r["latest_timestamp"],
                }
                for r in rows
            ]

    def get_multi_match_events(
        self,
        map_identifiers: list[str] | str,
        player_puuid: Optional[str] = None,
        event_type: Optional[str] = None,
        side: str = "all",
        limit_matches: int = 20,
    ) -> tuple[list[dict[str, Any]], list[VodTag], list[str]]:
        """Query spatial events and tags across multiple recent matches on a given map."""
        if isinstance(map_identifiers, str):
            map_list = [map_identifiers]
        else:
            map_list = list(map_identifiers)

        where_clauses = []
        m_params: list[Any] = []
        for m_id in map_list:
            clean = m_id.strip()
            where_clauses.append("(map_id = ? OR LOWER(map_id) LIKE ?)")
            m_params.extend([clean, f"%{clean.lower()}%"])

        or_conditions = " OR ".join(where_clauses) if where_clauses else "1=1"

        with self.db.connection() as conn:
            m_sql = f"""
            SELECT match_id, map_id, timestamp
            FROM matches
            WHERE ({or_conditions})
            ORDER BY timestamp DESC
            LIMIT ?;
            """
            m_params.append(limit_matches)
            m_rows = conn.execute(m_sql, m_params).fetchall()
            if not m_rows:
                return [], [], []


            match_ids = [r["match_id"] for r in m_rows]
            placeholders = ",".join("?" for _ in match_ids)

            e_query = [
                f"""
                SELECT event_id, match_id, round_number, event_type, event_time_ms,
                       player_puuid, pos_x, pos_y, metadata
                FROM match_events
                WHERE match_id IN ({placeholders})
                  AND pos_x IS NOT NULL AND pos_y IS NOT NULL
                """
            ]
            e_params: list[Any] = list(match_ids)

            if event_type and event_type != "all":
                e_query.append("AND event_type = ?")
                e_params.append(event_type)

            if player_puuid:
                e_query.append("AND player_puuid = ?")
                e_params.append(player_puuid)

            if side == "attack":
                e_query.append("AND round_number < 12")
            elif side == "defense":
                e_query.append("AND round_number >= 12")

            e_query.append("ORDER BY round_number ASC, event_time_ms ASC;")
            e_sql = " ".join(e_query)

            e_rows = conn.execute(e_sql, e_params).fetchall()
            events = []
            for r in e_rows:
                meta = json.loads(r["metadata"]) if r["metadata"] else {}
                events.append({
                    "event_id": r["event_id"],
                    "match_id": r["match_id"],
                    "round_number": r["round_number"],
                    "event_type": r["event_type"],
                    "event_time_ms": r["event_time_ms"],
                    "player_puuid": r["player_puuid"],
                    "norm_x": r["pos_x"],
                    "norm_y": r["pos_y"],
                    "metadata": meta,
                })

            t_sql = f"""
            SELECT tag_id, match_id, event_id, timestamp_ms, tag_category, tag_name, author_type
            FROM vod_tags
            WHERE match_id IN ({placeholders})
            ORDER BY timestamp_ms ASC;
            """
            t_rows = conn.execute(t_sql, match_ids).fetchall()
            tags = [
                VodTag(
                    tag_id=r["tag_id"],
                    match_id=r["match_id"],
                    event_id=r["event_id"],
                    timestamp_ms=r["timestamp_ms"],
                    tag_category=r["tag_category"],
                    tag_name=r["tag_name"],
                    author_type=r["author_type"],
                )
                for r in t_rows
            ]

            return events, tags, match_ids

    def insert_player(self, player: MatchPlayer) -> int:
        """Insert a single match player record."""
        return self.insert_match_players([player])

    def insert_match_players(self, players: list[MatchPlayer]) -> int:
        """Insert or replace player participant entries for matches."""
        if not players:
            return 0
        sql = """
        INSERT OR REPLACE INTO match_players (
            match_id, player_puuid, game_name, tag_line, team_id, character_id,
            score, rounds_played, kills, deaths, assists
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        payloads = [p.to_tuple() for p in players]
        with self.db.connection() as conn:
            cursor = conn.executemany(sql, payloads)
            return cursor.rowcount

    def get_match_players(self, match_id: str) -> list[MatchPlayer]:
        """Fetch all players participating in a match."""
        sql = """
        SELECT match_id, player_puuid, game_name, tag_line, team_id, character_id,
               score, rounds_played, kills, deaths, assists
        FROM match_players
        WHERE match_id = ?;
        """
        with self.db.connection() as conn:
            rows = conn.execute(sql, (match_id,)).fetchall()
            return [
                MatchPlayer(
                    match_id=r["match_id"],
                    player_puuid=r["player_puuid"],
                    game_name=r["game_name"],
                    tag_line=r["tag_line"],
                    team_id=r["team_id"],
                    character_id=r["character_id"],
                    score=r["score"],
                    rounds_played=r["rounds_played"],
                    kills=r["kills"],
                    deaths=r["deaths"],
                    assists=r["assists"],
                )
                for r in rows
            ]

    # Alias for convenience
    get_players = get_match_players

    def get_player_agent_matches(
        self, player_puuid: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Fetch player match history grouped by agent selection with match metadata."""
        sql = """
        SELECT 
            mp.match_id,
            mp.player_puuid,
            mp.game_name,
            mp.tag_line,
            mp.team_id,
            mp.character_id,
            mp.score,
            mp.rounds_played,
            mp.kills,
            mp.deaths,
            mp.assists,
            m.map_id,
            m.timestamp as match_timestamp,
            m.match_duration
        FROM match_players mp
        JOIN matches m ON mp.match_id = m.match_id
        WHERE (? IS NULL OR mp.player_puuid = ?)
        ORDER BY m.timestamp DESC;
        """
        with self.db.connection() as conn:
            rows = conn.execute(sql, (player_puuid, player_puuid)).fetchall()
            return [dict(r) for r in rows]

    def create_note(self, note: CoachNote) -> int:
        """Create a timestamped coach note or voice memo."""
        sql = """
        INSERT INTO coach_notes (
            match_id, round_number, timestamp_ms, author_type, text_note, audio_filepath, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?);
        """
        with self.db.connection() as conn:
            cursor = conn.execute(sql, note.to_tuple())
            return cursor.lastrowid

    def get_notes(
        self, match_id: str, round_number: Optional[int] = None
    ) -> list[CoachNote]:
        """Fetch notes for a match, optionally filtered by round number."""
        query = [
            "SELECT note_id, match_id, round_number, timestamp_ms, author_type, text_note, audio_filepath, created_at "
            "FROM coach_notes WHERE match_id = ?"
        ]
        params: list[Any] = [match_id]
        if round_number is not None:
            query.append("AND round_number = ?")
            params.append(round_number)
        query.append("ORDER BY timestamp_ms ASC;")
        sql = " ".join(query)
        with self.db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [
                CoachNote(
                    note_id=r["note_id"],
                    match_id=r["match_id"],
                    round_number=r["round_number"],
                    timestamp_ms=r["timestamp_ms"],
                    author_type=r["author_type"],
                    text_note=r["text_note"] or "",
                    audio_filepath=r["audio_filepath"],
                    created_at=r["created_at"] or 0,
                )
                for r in rows
            ]

    def get_note(self, note_id: int) -> Optional[CoachNote]:
        """Fetch a single note by ID."""
        sql = "SELECT note_id, match_id, round_number, timestamp_ms, author_type, text_note, audio_filepath, created_at FROM coach_notes WHERE note_id = ?;"
        with self.db.connection() as conn:
            row = conn.execute(sql, (note_id,)).fetchone()
            if not row:
                return None
            return CoachNote(
                note_id=row["note_id"],
                match_id=row["match_id"],
                round_number=row["round_number"],
                timestamp_ms=row["timestamp_ms"],
                author_type=row["author_type"],
                text_note=row["text_note"] or "",
                audio_filepath=row["audio_filepath"],
                created_at=row["created_at"] or 0,
            )

    def delete_note(self, note_id: int) -> bool:
        """Delete a note by ID."""
        sql = "DELETE FROM coach_notes WHERE note_id = ?;"
        with self.db.connection() as conn:
            cursor = conn.execute(sql, (note_id,))
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Tactical Utility Deployment & Ability Telemetry
    # ------------------------------------------------------------------
    def insert_utility_event(self, event: UtilityEvent) -> int:
        """Insert a single utility event record."""
        sql = """
        INSERT INTO utility_events (
            match_id, round_number, timestamp_ms, player_puuid, player_name,
            agent_name, ability_name, ability_slot, category, pos_x, pos_y,
            target_x, target_y, duration_ms, targets_affected, damage_dealt,
            assisted_kill, team_inflicted, wasted, roi_score, details
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        with self.db.connection() as conn:
            cursor = conn.execute(sql, event.to_tuple())
            return cursor.lastrowid

    def insert_utility_events(self, events: list[UtilityEvent]) -> None:
        """Batch insert utility events."""
        if not events:
            return
        sql = """
        INSERT INTO utility_events (
            match_id, round_number, timestamp_ms, player_puuid, player_name,
            agent_name, ability_name, ability_slot, category, pos_x, pos_y,
            target_x, target_y, duration_ms, targets_affected, damage_dealt,
            assisted_kill, team_inflicted, wasted, roi_score, details
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        with self.db.connection() as conn:
            conn.executemany(sql, [e.to_tuple() for e in events])

    def get_utility_events(
        self, match_id: str, round_number: Optional[int] = None
    ) -> list[UtilityEvent]:
        """Fetch utility deployment events for a match, optionally filtered by round."""
        query = [
            "SELECT utility_id, match_id, round_number, timestamp_ms, player_puuid,",
            "player_name, agent_name, ability_name, ability_slot, category, pos_x, pos_y,",
            "target_x, target_y, duration_ms, targets_affected, damage_dealt,",
            "assisted_kill, team_inflicted, wasted, roi_score, details",
            "FROM utility_events WHERE match_id = ?",
        ]
        params: list[Any] = [match_id]
        if round_number is not None:
            query.append("AND round_number = ?")
            params.append(round_number)
        query.append("ORDER BY timestamp_ms ASC;")
        sql = " ".join(query)

        with self.db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [
                UtilityEvent(
                    utility_id=r["utility_id"],
                    match_id=r["match_id"],
                    round_number=r["round_number"],
                    timestamp_ms=r["timestamp_ms"],
                    player_puuid=r["player_puuid"],
                    player_name=r["player_name"] or "",
                    agent_name=r["agent_name"] or "",
                    ability_name=r["ability_name"],
                    ability_slot=r["ability_slot"] or "Ability1",
                    category=r["category"],
                    pos_x=r["pos_x"],
                    pos_y=r["pos_y"],
                    target_x=r["target_x"],
                    target_y=r["target_y"],
                    duration_ms=r["duration_ms"] or 5000,
                    targets_affected=r["targets_affected"] or 0,
                    damage_dealt=r["damage_dealt"] or 0.0,
                    assisted_kill=bool(r["assisted_kill"]),
                    team_inflicted=bool(r["team_inflicted"]),
                    wasted=bool(r["wasted"]),
                    roi_score=r["roi_score"] if r["roi_score"] is not None else 50.0,
                    details=r["details"] or "",
                )
                for r in rows
            ]

    def delete_utility_events(self, match_id: str) -> None:
        """Delete all utility events for a match."""
        sql = "DELETE FROM utility_events WHERE match_id = ?;"
        with self.db.connection() as conn:
            conn.execute(sql, (match_id,))



