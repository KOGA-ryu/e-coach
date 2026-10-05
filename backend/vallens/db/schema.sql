-- Matches table storing metadata per match
CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    map_id TEXT,
    game_mode TEXT,
    match_duration INTEGER,
    timestamp INTEGER,
    video_filepath TEXT
);

-- Objective event logs pulled from Riot API
CREATE TABLE IF NOT EXISTS match_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT NOT NULL,
    round_number INTEGER,
    event_type TEXT NOT NULL, -- 'kill', 'death', 'round_start', etc.
    event_time_ms INTEGER NOT NULL,
    player_puuid TEXT,
    pos_x REAL,
    pos_y REAL,
    metadata TEXT, -- JSON blob for weapon, killer, etc.
    FOREIGN KEY(match_id) REFERENCES matches(match_id) ON DELETE CASCADE
);

-- Custom tags applied during VOD review
CREATE TABLE IF NOT EXISTS vod_tags (
    tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT NOT NULL,
    event_id INTEGER,
    timestamp_ms INTEGER NOT NULL,
    tag_category TEXT NOT NULL,
    tag_name TEXT NOT NULL,
    author_type TEXT NOT NULL, -- 'solo' or 'coach'
    FOREIGN KEY(match_id) REFERENCES matches(match_id) ON DELETE CASCADE,
    FOREIGN KEY(event_id) REFERENCES match_events(event_id) ON DELETE SET NULL
);

-- Indexing for high-performance query lookups during review
CREATE INDEX IF NOT EXISTS idx_match_events_match_id ON match_events(match_id);
CREATE INDEX IF NOT EXISTS idx_match_events_round ON match_events(match_id, round_number);
CREATE INDEX IF NOT EXISTS idx_vod_tags_match_id ON vod_tags(match_id);
CREATE INDEX IF NOT EXISTS idx_vod_tags_category ON vod_tags(tag_category, tag_name);
