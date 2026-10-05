CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    map_id TEXT,
    game_mode TEXT,
    match_duration INTEGER,
    timestamp INTEGER,
    video_filepath TEXT,
    video_offset_ms INTEGER DEFAULT 0
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

-- Player agent and roster assignments per match
CREATE TABLE IF NOT EXISTS match_players (
    match_id TEXT NOT NULL,
    player_puuid TEXT NOT NULL,
    game_name TEXT,
    tag_line TEXT,
    team_id TEXT,
    character_id TEXT NOT NULL, -- Agent UUID
    score INTEGER DEFAULT 0,
    rounds_played INTEGER DEFAULT 0,
    kills INTEGER DEFAULT 0,
    deaths INTEGER DEFAULT 0,
    assists INTEGER DEFAULT 0,
    PRIMARY KEY(match_id, player_puuid),
    FOREIGN KEY(match_id) REFERENCES matches(match_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_match_players_puuid ON match_players(player_puuid);
CREATE INDEX IF NOT EXISTS idx_match_players_character ON match_players(character_id);

-- Timestamped coach notes and audio dictations
CREATE TABLE IF NOT EXISTS coach_notes (
    note_id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT NOT NULL,
    round_number INTEGER,
    timestamp_ms INTEGER NOT NULL,
    author_type TEXT NOT NULL, -- 'coach' or 'solo'
    text_note TEXT,
    audio_filepath TEXT,
    created_at INTEGER,
    FOREIGN KEY(match_id) REFERENCES matches(match_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_coach_notes_match_id ON coach_notes(match_id);
CREATE INDEX IF NOT EXISTS idx_coach_notes_round ON coach_notes(match_id, round_number);

-- Tactical utility deployments and ability telemetry
CREATE TABLE IF NOT EXISTS utility_events (
    utility_id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    player_puuid TEXT,
    player_name TEXT,
    agent_name TEXT,
    ability_name TEXT NOT NULL,
    ability_slot TEXT,
    category TEXT NOT NULL, -- 'flash', 'smoke', 'recon', 'molly', 'stun', 'wall', 'mobility', 'ultimate'
    pos_x REAL,
    pos_y REAL,
    target_x REAL,
    target_y REAL,
    duration_ms INTEGER DEFAULT 5000,
    targets_affected INTEGER DEFAULT 0,
    damage_dealt REAL DEFAULT 0.0,
    assisted_kill INTEGER DEFAULT 0,
    team_inflicted INTEGER DEFAULT 0,
    wasted INTEGER DEFAULT 0,
    roi_score REAL DEFAULT 50.0,
    details TEXT,
    FOREIGN KEY(match_id) REFERENCES matches(match_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_utility_events_match ON utility_events(match_id, round_number);

-- Tactical Playbook strats and whiteboard diagrams
CREATE TABLE IF NOT EXISTS playbook_strats (
    strat_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    map_name TEXT NOT NULL,
    side TEXT NOT NULL DEFAULT 'attack', -- 'attack', 'defense', 'retake', 'default'
    round_number INTEGER,
    match_id TEXT,
    description TEXT,
    drawing_data TEXT NOT NULL, -- JSON array of shapes/lines/markers
    created_at INTEGER NOT NULL,
    FOREIGN KEY(match_id) REFERENCES matches(match_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_playbook_strats_map ON playbook_strats(map_name, side);



