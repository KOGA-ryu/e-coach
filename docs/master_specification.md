# Project Master Specification: Valorant VOD & Analytics Suite (Codename: `ValLens`)

## 1. Project Vision & Scope

Build a high-performance, local-first desktop application designed for solo players and coaches to ingest Valorant match data, automate VOD recording and timestamp synchronization, render interactive spatial heatmaps, and log custom performance tags to uncover deep behavioral and mechanical habits over time.

## 2. Core Technical Stack

* **Architecture:** Desktop Application (C++ / Qt/QML frontend for high-performance UI rendering and media playback).
* **Backend / Processing:** Python (handling API ingestion, data transformation, SQLite database operations, and OBS automation).
* **Data Sources:** Riot Official Developer API (`VAL-MATCH-V1`, RSO authentication) and Local Client API (for match state polling).
* **Recording & Automation:** OBS WebSocket API for automated session capture and bookmark/EDL generation.
* **Storage:** Local SQLite database for matches, telemetry events, tags, and profile aggregations.

---

## 3. Core Feature Modules

### Module A: Automated Session Capture & Sync Pipeline

* **Match State Detection:** Polls local client endpoints to detect match start/end triggers.
* **OBS Integration:** Programmatically fires `StartRecording` on agent-select completion and `StopRecording` on match conclusion via OBS WebSocket.
* **Timestamp Alignment:** Synchronizes the recording timeline with API match events by anchoring `Round 0 Start` to video time `00:00:00`.
* **Export Options:** Generates an Edit Decision List (EDL) / Chapter text file alongside the MP4 for quick video navigation.

### Module B: Telemetry & Spatial Heatmap Engine

* **API Ingestion:** Pulls round histories, economy data, and precise $X, Y$ coordinate vectors for kills and deaths.
* **Map Projection:** Converts raw in-game world coordinates into pixel coordinates matching top-down map asset bounds.
* **Interactive Heatmaps:** Renders clustering points for deaths and kills, with dynamic filtering by round type, weapon, or user-applied tags.

### Module C: Hotkey-Driven VOD Tagging System

* **Unified Review UI:** Synchronizes a media player pane, a minimap telemetry pane, and a fast-action tag grid.
* **Taxonomy Structure:** Categorized failure and strength tags (e.g., `Mechanics:crosshair_placement`, `Positioning:over_peeking`).
* **Instant Logging:** Hotkey bindings (e.g., numeric keys) map real-time review clicks directly to database events with sub-second precision offsets.

### Module D: Long-Term Profile Aggregation & Coaching Insights

* **Habit Tracking:** Aggregates tag frequencies across maps, agents, and time spans to surface recurring performance flaws.
* **Metric Correlation:** Cross-references manual review tags with objective API stats (e.g., correlating `over_peeking` tags with First Death percentages).
* **Coach vs. Solo Sync:** Supports multi-user viewpoints to highlight discrepancies between self-assessment and coach critique.

---

## 4. Initial Database Schema (SQLite)

```sql
-- Matches table storing metadata per match
CREATE TABLE matches (
    match_id TEXT PRIMARY KEY,
    map_id TEXT,
    game_mode TEXT,
    match_duration INTEGER,
    timestamp INTEGER,
    video_filepath TEXT
);

-- Objective event logs pulled from Riot API
CREATE TABLE match_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT,
    round_number INTEGER,
    event_type TEXT, -- 'kill', 'death', 'round_start', etc.
    event_time_ms INTEGER,
    player_puuid TEXT,
    pos_x REAL,
    pos_y REAL,
    metadata TEXT, -- JSON blob for weapon, killer, etc.
    FOREIGN KEY(match_id) REFERENCES matches(match_id)
);

-- Custom tags applied during VOD review
CREATE TABLE vod_tags (
    tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT,
    event_id INTEGER,
    timestamp_ms INTEGER,
    tag_category TEXT,
    tag_name TEXT,
    author_type TEXT, -- 'solo' or 'coach'
    FOREIGN KEY(match_id) REFERENCES matches(match_id),
    FOREIGN KEY(event_id) REFERENCES match_events(event_id)
);
```
