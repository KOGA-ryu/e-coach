# ValLens (e-coach)

> **High-performance Valorant VOD review, spatial analytics, and automated tagging desktop suite.**

## Overview

ValLens is a local-first desktop application designed for solo players and coaches to:
- Ingest Riot API match telemetry and local client live states.
- Automate OBS session recordings with round-accurate synchronization.
- Project spatial heatmaps (kills, deaths, weapon events) onto top-down map layouts.
- Rapidly tag performance flaws and strengths using hotkeys.
- Track long-term player habits, correlating subjective review tags with objective match statistics.

---

## Architecture

```
e-coach/
├── backend/                  # Python backend services
│   ├── vallens/
│   │   ├── db/               # SQLite database models, migrations & queries
│   │   ├── riot/             # Riot Match API (VAL-MATCH-V1) & Local Client API client
│   │   ├── obs/              # OBS WebSocket capture automation & EDL generation
│   │   └── analytics/        # Spatial heatmap coordinates & stats aggregation
│   ├── pyproject.toml        # Backend dependencies & packaging
│   └── tests/
├── frontend/                 # C++ / Qt6 / QML UI
│   ├── CMakeLists.txt
│   ├── src/                  # C++ backend bridge & media playback controllers
│   └── qml/                  # QML UI views (Video player, Minimap, Tag Grid)
├── docs/                     # Specifications, architecture notes & guides
│   └── master_specification.md
└── data/                     # Map asset bounds, test payloads & calibrations
```

---

## Tech Stack

* **Frontend:** C++20 / Qt 6 (QML, Qt Multimedia, Qt Quick)
* **Backend:** Python 3.12+ / `obs-websocket-py` / `requests` / `sqlite3`
* **Data Sources:** Riot Games API (`VAL-MATCH-V1`), Local Riot Client API
* **Recording Engine:** OBS Studio WebSocket (v5)
* **Database:** SQLite3 with WAL mode
