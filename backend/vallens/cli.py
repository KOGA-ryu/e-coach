"""Command-line interface for ValLens backend operations and OBS automation."""

import argparse
import json
from pathlib import Path
import sys
import time

from vallens.db.database import Database
from vallens.obs.client import MockObsClient, ObsWebSocketClient
from vallens.obs.controller import CaptureController
from vallens.obs.local_client import GameState, LocalClient, MockLocalClient
from vallens.service import ValLensService


def main() -> None:
    parser = argparse.ArgumentParser(description="ValLens CLI - Valorant Telemetry & Analytics")
    parser.add_argument("--db", default="vallens.db", help="Path to SQLite database file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Ingest command
    ingest_parser = subparsers.add_parser("ingest", help="Ingest a match JSON file into the database")
    ingest_parser.add_argument("file", help="Path to match JSON file")
    ingest_parser.add_argument("--video", default=None, help="Optional path to associated video file")

    # Show command
    show_parser = subparsers.add_parser("show", help="Display match summary and event counts")
    show_parser.add_argument("match_id", help="Match UUID")

    # Heatmap command
    heat_parser = subparsers.add_parser("heatmap", help="Get projected coordinates for heatmaps")
    heat_parser.add_argument("match_id", help="Match UUID")
    heat_parser.add_argument("--type", default="death", choices=["kill", "death"], help="Event type")
    heat_parser.add_argument("--puuid", default=None, help="Filter by player PUUID")
    heat_parser.add_argument("--round", type=int, default=None, help="Filter by round number")

    # Tag command
    tag_parser = subparsers.add_parser("tag", help="Add a review tag to a match")
    tag_parser.add_argument("match_id", help="Match UUID")
    tag_parser.add_argument("--category", required=True, help="Tag category (e.g., Mechanics, Positioning)")
    tag_parser.add_argument("--name", required=True, help="Tag name (e.g., crosshair_placement)")
    tag_parser.add_argument("--time-ms", type=int, required=True, help="Timestamp offset in ms")
    tag_parser.add_argument("--author", default="solo", choices=["solo", "coach"], help="Tag author type")

    # Tags summary command
    tags_sum_parser = subparsers.add_parser("tags-summary", help="Aggregate tag counts")
    tags_sum_parser.add_argument("--match-id", default=None, help="Optional match UUID filter")

    # Export EDL command
    edl_parser = subparsers.add_parser("export-edl", help="Export CMX 3600 EDL, YouTube chapters, and FFmpeg metadata")
    edl_parser.add_argument("match_id", help="Match UUID")
    edl_parser.add_argument("--video", required=True, help="Video recording filepath")
    edl_parser.add_argument("--offset-ms", type=int, default=0, help="Offset between video start and Round 0 in ms")

    # OBS Poll / Automate command
    poll_parser = subparsers.add_parser("obs-poll", help="Run local client poller and OBS capture automation")
    poll_parser.add_argument("--obs-host", default="127.0.0.1", help="OBS WebSocket host")
    poll_parser.add_argument("--obs-port", type=int, default=4455, help="OBS WebSocket port")
    poll_parser.add_argument("--obs-password", default=None, help="OBS WebSocket password")
    poll_parser.add_argument("--mock", action="store_true", help="Run with simulated clients for testing")

    args = parser.parse_args()

    db = Database(args.db)
    service = ValLensService(db=db)

    if args.command == "ingest":
        path = Path(args.file)
        if not path.exists():
            print(f"Error: file not found: {path}", file=sys.stderr)
            sys.exit(1)
        match = service.ingest_match_file(path, video_filepath=args.video)
        print(f"Successfully ingested match: {match.match_id} (Map: {match.map_id})")

    elif args.command == "show":
        overview = service.get_match_overview(args.match_id)
        if not overview:
            print(f"Match not found: {args.match_id}", file=sys.stderr)
            sys.exit(1)
        meta = overview["metadata"]
        print(f"Match ID:       {meta.match_id}")
        print(f"Map:            {meta.map_id}")
        print(f"Game Mode:      {meta.game_mode}")
        print(f"Duration:       {meta.match_duration / 1000:.1f}s")
        print(f"Rounds:         {overview['rounds_count']}")
        print(f"Total Events:   {overview['total_events']}")
        print(f"Total Kills:    {overview['total_kills']}")
        print(f"Total Deaths:   {overview['total_deaths']}")
        if meta.video_filepath:
            print(f"Video File:     {meta.video_filepath}")

    elif args.command == "heatmap":
        points = service.get_player_heatmap(
            args.match_id,
            player_puuid=args.puuid,
            event_type=args.type,
            round_number=args.round,
        )
        print(json.dumps(points, indent=2))

    elif args.command == "tag":
        tag_id = service.add_vod_tag(
            match_id=args.match_id,
            timestamp_ms=args.time_ms,
            category=args.category,
            name=args.name,
            author_type=args.author,
        )
        print(f"Created tag with ID {tag_id} for match {args.match_id}")

    elif args.command == "tags-summary":
        summary = service.repo.get_tag_aggregations(match_id=args.match_id)
        print(json.dumps(summary, indent=2))

    elif args.command == "export-edl":
        controller = CaptureController(service=service)
        exported = controller.process_match_sync_and_edl(
            args.match_id, args.video, video_anchor_offset_ms=args.offset_ms
        )
        print(f"Exported {len(exported)} timeline files:")
        for p in exported:
            print(f" - {p}")

    elif args.command == "obs-poll":
        if args.mock:
            print("Starting capture automation in MOCK simulation mode...")
            local_client = MockLocalClient(initial_state=GameState.MENUS)
            obs_client = MockObsClient()
            controller = CaptureController(
                local_client=local_client,
                obs_client=obs_client,
                service=service,
            )
            print("Simulating PREGAME (Agent Select)...")
            local_client.set_state(GameState.PREGAME)
            controller.poll_once()

            print("Simulating INGAME (Match Start) -> OBS StartRecording...")
            local_client.set_state(GameState.INGAME)
            controller.poll_once()
            print(f"OBS is recording: {obs_client.is_recording}")

            time.sleep(1.0)
            print("Simulating POSTGAME (Match End) -> OBS StopRecording...")
            local_client.set_state(GameState.POSTGAME)
            controller.poll_once()
            print(f"OBS stopped recording: file saved to {controller.last_recorded_file}")
            print("Simulation complete.")
        else:
            print(f"Connecting to OBS WebSocket at {args.obs_host}:{args.obs_port}...")
            obs_client = ObsWebSocketClient(
                host=args.obs_host, port=args.obs_port, password=args.obs_password
            )
            obs_client.connect()
            local_client = LocalClient()
            controller = CaptureController(
                local_client=local_client, obs_client=obs_client, service=service
            )
            print("Listening for Valorant match events... Press Ctrl+C to stop.")
            try:
                controller.start_polling()
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                controller.stop_polling()
                obs_client.close()
                print("\nStopped.")


if __name__ == "__main__":
    main()
