"""Command-line interface for ValLens backend operations and review interface."""

import argparse
import json
from pathlib import Path
import sys
import time

from vallens.db.database import Database
from vallens.obs.client import MockObsClient, ObsWebSocketClient
from vallens.obs.controller import CaptureController
from vallens.obs.local_client import GameState, LocalClient, MockLocalClient
from vallens.server import run_server
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

    # Serve command (Web Review UI)
    serve_parser = subparsers.add_parser("serve", help="Launch the local ValLens Web Review Interface")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to run server on")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host IP to bind to")

    # Report command
    report_parser = subparsers.add_parser("report", help="Generate Coaching Report Card")
    report_parser.add_argument("match_id", help="Match UUID")
    report_parser.add_argument("--format", choices=["markdown", "html"], default="markdown", help="Report format")
    report_parser.add_argument("--output", default=None, help="Save to file instead of stdout")
    report_parser.add_argument("--player", default=None, help="Player PUUID focus")

    # Sync Account command
    sync_parser = subparsers.add_parser("sync-account", help="Link account and synchronize match history")
    sync_parser.add_argument("--detect", action="store_true", help="Auto-detect account from running local Riot Client")
    sync_parser.add_argument("--puuid", default=None, help="Player PUUID")
    sync_parser.add_argument("--name", default=None, help="Riot Game Name")
    sync_parser.add_argument("--tag", default=None, help="Riot Tagline")
    sync_parser.add_argument("--region", default="na", help="Region shard (na, eu, ap, kr)")
    sync_parser.add_argument("--api-key", default=None, help="Riot Developer Portal API Key (RGAPI-...)")
    sync_parser.add_argument("--limit", type=int, default=5, help="Number of recent matches to sync")

    # Heatmap aggregate command
    agg_parser = subparsers.add_parser("heatmap-aggregate", help="Multi-match spatial heatmap aggregation across maps")
    agg_parser.add_argument("map", help="Map name or ID (e.g. Ascent, Haven, Bind)")
    agg_parser.add_argument("--type", default="death", choices=["kill", "death", "all"], help="Event type")
    agg_parser.add_argument("--side", default="all", choices=["all", "attack", "defense"], help="Round half filter")
    agg_parser.add_argument("--puuid", default=None, help="Filter by player PUUID")
    agg_parser.add_argument("--limit", type=int, default=20, help="Number of recent matches to aggregate")

    # Agent Matrix command
    agent_parser = subparsers.add_parser("agent-matrix", help="Display cross-agent performance, opening duels, and habit flaws")
    agent_parser.add_argument("--puuid", default=None, help="Player PUUID (defaults to primary player)")

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

    elif args.command == "serve":
        # If DB is empty, auto-ingest sample match for immediate out-of-the-box exploration
        matches = service.repo.list_matches(limit=1)
        if not matches:
            sample_path = Path(__file__).parent.parent.parent / "data" / "sample_match.json"
            if sample_path.exists():
                service.ingest_match_file(sample_path)
                print(f"Auto-ingested sample Ascent match into {args.db}")

        server = run_server(service=service, port=args.port, host=args.host)
        print(f"\n=======================================================")
        print(f"  ValLens Review Interface Running:")
        print(f"  http://{args.host}:{args.port}/")
        print(f"=======================================================\n")
        print("Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")
            server.server_close()

    elif args.command == "report":
        from vallens.analytics.report import CoachingReportGenerator
        match = service.repo.get_match(args.match_id)
        if not match:
            print(f"Error: match not found: {args.match_id}", file=sys.stderr)
            sys.exit(1)
        events = service.repo.get_events(args.match_id)
        tags = service.repo.get_tags(args.match_id)
        gen = CoachingReportGenerator()
        if args.format == "html":
            content = gen.generate_html(match, events, tags, player_puuid=args.player)
        else:
            content = gen.generate_markdown(match, events, tags, player_puuid=args.player)

        if args.output:
            Path(args.output).write_text(content, encoding="utf-8")
            print(f"Report written to {args.output}")
        else:
            print(content)

    elif args.command == "sync-account":
        from vallens.riot.account import AccountConnector
        connector = AccountConnector(service=service, riot_api_key=args.api_key, region=args.region)

        if args.detect:
            print("Detecting account from local Riot Client / lockfile...")
            acc = connector.detect_local_account()
            if not acc:
                print("No running Valorant / Riot Client found on this machine.")
                sys.exit(1)
            print(f"Detected Account: {acc['riot_id']} (PUUID: {acc['puuid']})")
            if args.api_key:
                matches = connector.sync_recent_matches(acc["puuid"], limit=args.limit, api_key=args.api_key, region=args.region)
                print(f"Successfully synced {len(matches)} matches.")
            else:
                print("To fetch historical matches from Riot servers, provide --api-key RGAPI-...")
        elif args.puuid and args.api_key:
            print(f"Syncing recent matches for PUUID: {args.puuid}...")
            matches = connector.sync_recent_matches(args.puuid, limit=args.limit, api_key=args.api_key, region=args.region)
            print(f"Successfully synced {len(matches)} matches.")
        elif args.name and args.tag:
            print(f"Syncing recent matches for {args.name}#{args.tag} ({args.region})...")
            matches = connector.sync_by_henrik_api(args.name, args.tag, region=args.region, limit=args.limit, api_key=args.api_key)
            print(f"Successfully synced {len(matches)} matches.")
        else:
            print("Please specify --detect, or --puuid with --api-key, or --name and --tag.")

    elif args.command == "heatmap-aggregate":
        res = service.get_map_aggregate_heatmap(
            map_id_or_name=args.map,
            player_puuid=args.puuid,
            event_type=args.type,
            side=args.side,
            limit_matches=args.limit,
        )
        print("=" * 70)
        print(f"VAL-LENS MULTI-MATCH SPATIAL HEATMAP: {res.map_name.upper()}")
        print("=" * 70)
        print(f"Matches Analyzed: {res.match_count} | Event Type: {res.event_type.upper()} | Filter: {res.side.upper()}")
        print(f"Total Telemetry Points: {res.total_events}")
        print("-" * 70)
        print("IDENTIFIED HOTSPOT CLUSTERS & HABIT FLAWS:")
        if not res.clusters:
            print("  No concentrated clusters identified for this filter.")
        for c in res.clusters:
            tags_summary = ", ".join(f"'{t['name']}' (x{t['count']})" for t in c.correlated_tags) if c.correlated_tags else "No manual review tags"
            print(f"\n  [HOTSPOT #{c.cluster_id}] {c.zone_name.upper()} ({c.super_region})")
            print(f"  Coordinates: ({c.center_x:.3f}, {c.center_y:.3f}) | Radius: {c.radius:.3f}")
            print(f"  Concentration: {c.event_count} events ({c.percentage:.1f}% of total)")
            print(f"  Correlated Tags: {tags_summary}")
            print(f"  Tactical Analysis: {c.tactical_summary}")

        print("\n" + "-" * 70)
        print("MACRO COACHING INSIGHTS:")
        for insight in res.tactical_insights:
            print(f"  • {insight}")
        print("=" * 70)

    elif args.command == "agent-matrix":
        matrix = service.get_agent_matrix(player_puuid=args.puuid)
        print("=" * 88)
        print(f"VAL-LENS AGENT PROFILING MATRIX: {matrix.player_name.upper()} ({matrix.player_puuid})")
        print("=" * 88)
        print(f"Total Matches: {matrix.total_matches} | Total Rounds: {matrix.total_rounds}")
        print("-" * 88)
        header_fmt = "{:<12} {:<12} {:<8} {:<6} {:<10} {:<8} {:<18} {:<8}"
        print(header_fmt.format("AGENT", "ROLE", "MATCHES", "K/D", "OD WIN%", "TRADE%", "TOP RECURRING FLAW", "FLAW/RND"))
        print("-" * 88)
        for a in matrix.agents:
            top_f = f"{a.top_flaws[0]['name']} ({a.top_flaws[0]['count']}x)" if a.top_flaws else "None"
            print(header_fmt.format(
                a.agent_name,
                a.role,
                str(a.matches_played),
                f"{a.kd_ratio:.2f}",
                f"{a.opening_duel_win_rate:.1f}%",
                f"{a.trade_rate:.1f}%",
                top_f,
                f"{a.flaw_rate_per_round:.2f}",
            ))

        print("\n" + "=" * 88)
        print("ROLE DIAGNOSIS & BENCHMARKING:")
        for a in matrix.agents:
            print(f"\n  [{a.agent_name.upper()}] — {a.role.upper()}")
            print(f"  • Combat Stats: {a.kills} Kills / {a.deaths} Deaths / {a.assists} Assists | K/D: {a.kd_ratio:.2f}")
            print(f"  • Opening Duels: {a.first_bloods} First Bloods / {a.first_deaths} First Deaths ({a.opening_duel_win_rate:.1f}% OD Win Rate)")
            print(f"  • Trading: {a.traded_deaths} Traded Deaths / {a.untraded_deaths} Untraded ({a.trade_rate:.1f}% Trade Rate)")
            if a.top_flaws:
                flaw_strs = [f"'{f['name']}' (x{f['count']})" for f in a.top_flaws]
                print(f"  • Logged Review Flaws: {', '.join(flaw_strs)}")
            print(f"  • Coaching Diagnosis: {a.diagnosis}")

        print("\n" + "=" * 88)
        print("MACRO AGENT POOL INSIGHTS:")
        for ins in matrix.summary_insights:
            print(f"  • {ins}")
        print("=" * 88)


if __name__ == "__main__":
    main()

