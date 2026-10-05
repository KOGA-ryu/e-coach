"""Lightweight HTTP and REST API server for the ValLens review interface."""

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
import os
from pathlib import Path
from typing import Optional
import urllib.parse

from vallens.analytics.correlations import FlawCorrelationEngine
from vallens.analytics.report import CoachingReportGenerator
from vallens.db.database import Database
from vallens.models import VodTag
from vallens.obs.exporter import EdlExporter
from vallens.obs.sync import TimelineSynchronizer
from vallens.service import ValLensService

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent.parent.parent / "frontend" / "web"
DATA_MAPS_DIR = Path(__file__).parent.parent.parent / "data" / "maps"


class ValLensRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request handler with REST routes and static file serving."""

    service: ValLensService
    report_gen: CoachingReportGenerator = CoachingReportGenerator()

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _send_json(self, data: object, status: int = 200) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)

    def _send_error(self, message: str, status: int = 400) -> None:
        self._send_json({"error": message}, status=status)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. Matches List
        if path == "/api/matches":
            matches = self.service.repo.list_matches()
            self._send_json([
                {
                    "match_id": m.match_id,
                    "map_id": m.map_id,
                    "game_mode": m.game_mode,
                    "match_duration": m.match_duration,
                    "timestamp": m.timestamp,
                    "video_filepath": m.video_filepath,
                }
                for m in matches
            ])
            return

        # 2. Events Stream
        if path.startswith("/api/matches/") and path.endswith("/events"):
            parts = path.split("/")
            match_id = parts[3]
            r_num = int(query["round"][0]) if "round" in query else None
            ev_type = query.get("type", [None])[0]
            puuid = query.get("player", [None])[0]

            events = self.service.repo.get_events(match_id, round_number=r_num, event_type=ev_type, player_puuid=puuid)
            self._send_json([
                {
                    "event_id": e.event_id,
                    "match_id": e.match_id,
                    "round_number": e.round_number,
                    "event_type": e.event_type,
                    "event_time_ms": e.event_time_ms,
                    "player_puuid": e.player_puuid,
                    "pos_x": e.pos_x,
                    "pos_y": e.pos_y,
                    "metadata": e.metadata,
                }
                for e in events
            ])
            return

        # 3. Heatmap Coordinates
        if path.startswith("/api/matches/") and path.endswith("/heatmap"):
            parts = path.split("/")
            match_id = parts[3]
            ev_type = query.get("type", ["death"])[0]
            r_num = int(query["round"][0]) if "round" in query else None
            puuid = query.get("player", [None])[0]

            pts = self.service.get_player_heatmap(match_id, player_puuid=puuid, event_type=ev_type, round_number=r_num)
            self._send_json(pts)
            return

        # 4. Tags
        if path.startswith("/api/matches/") and path.endswith("/tags"):
            parts = path.split("/")
            match_id = parts[3]
            tags = self.service.repo.get_tags(match_id)
            self._send_json([
                {
                    "tag_id": t.tag_id,
                    "match_id": t.match_id,
                    "event_id": t.event_id,
                    "timestamp_ms": t.timestamp_ms,
                    "category": t.tag_category,
                    "name": t.tag_name,
                    "author": t.author_type,
                }
                for t in tags
            ])
            return

        # 5. Chapters
        if path.startswith("/api/matches/") and path.endswith("/chapters"):
            parts = path.split("/")
            match_id = parts[3]
            events = self.service.repo.get_events(match_id)
            sync = TimelineSynchronizer(round_0_start_api_ms=0)
            segments = EdlExporter.build_round_segments(events, sync)
            self._send_json(segments)
            return

        # 6. Coaching Insights & Correlations API
        if path.startswith("/api/matches/") and path.endswith("/insights"):
            parts = path.split("/")
            match_id = parts[3]
            match = self.service.repo.get_match(match_id)
            if not match:
                self._send_error("Match not found", status=404)
                return

            events = self.service.repo.get_events(match_id)
            tags = self.service.repo.get_tags(match_id)
            player_puuid = query.get("player", [None])[0]

            report_data = self.report_gen.generate_data(match, events, tags, player_puuid=player_puuid)
            # Serialize
            self._send_json({
                "match_id": match.match_id,
                "grade": report_data["grade"],
                "kills": report_data["kills"],
                "deaths": report_data["deaths"],
                "kd_ratio": report_data["kd_ratio"],
                "first_bloods": report_data["first_bloods"],
                "first_deaths": report_data["first_deaths"],
                "trade_rate": report_data["trade_rate"],
                "traded_deaths": report_data["traded_deaths"],
                "untraded_deaths": report_data["untraded_deaths"],
                "tag_correlations": [
                    {
                        "category": tc.category,
                        "tag_name": tc.tag_name,
                        "total_count": tc.total_count,
                        "first_deaths": tc.first_death_count,
                        "untraded_deaths": tc.untraded_death_count,
                        "early_deaths": tc.early_death_count,
                    }
                    for tc in report_data["tag_correlations"]
                ],
                "coach_agreement_score": report_data["discrepancy"].agreement_score,
                "blindspots_count": len(report_data["discrepancy"].blindspots),
                "drills": report_data["drills"],
            })
            return

        # 7. Rendered Coaching Report Card (HTML or Markdown)
        if path.startswith("/api/matches/") and path.endswith("/report"):
            parts = path.split("/")
            match_id = parts[3]
            match = self.service.repo.get_match(match_id)
            if not match:
                self._send_error("Match not found", status=404)
                return

            events = self.service.repo.get_events(match_id)
            tags = self.service.repo.get_tags(match_id)
            fmt = query.get("format", ["html"])[0]

            if fmt == "markdown":
                md_text = self.report_gen.generate_markdown(match, events, tags)
                payload = md_text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            else:
                html_text = self.report_gen.generate_html(match, events, tags)
                payload = html_text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

        # 7.5. Perspective Diffing & Cognitive Blindspots
        if path.startswith("/api/matches/") and path.endswith("/perspective-diff"):
            parts = path.split("/")
            match_id = parts[3]
            tol_str = query.get("tolerance_ms", ["5000"])[0]
            try:
                tol_ms = int(tol_str)
            except ValueError:
                tol_ms = 5000

            result = self.service.get_perspective_diff(match_id, tolerance_ms=tol_ms)
            if not result:
                self._send_error("Match not found", status=404)
                return

            self._send_json({
                "match_id": result.match_id,
                "agreement_score": result.agreement_score,
                "alignment_status": result.alignment_status,
                "total_solo_tags": result.total_solo_tags,
                "total_coach_tags": result.total_coach_tags,
                "agreed_count": result.agreed_count,
                "blindspots_count": result.blindspots_count,
                "self_criticisms_count": result.self_criticisms_count,
                "blindspots": [
                    {
                        "tag_id": b.tag_id,
                        "round_number": b.round_number,
                        "timestamp_ms": b.timestamp_ms,
                        "formatted_time": b.formatted_time,
                        "round_rel_time": b.round_rel_time,
                        "tag_category": b.tag_category,
                        "tag_name": b.tag_name,
                        "severity": b.severity,
                        "related_event": b.related_event,
                        "coaching_directive": b.coaching_directive,
                    }
                    for b in result.blindspots
                ],
                "self_criticisms": [
                    {
                        "tag_id": sc.tag_id,
                        "round_number": sc.round_number,
                        "timestamp_ms": sc.timestamp_ms,
                        "formatted_time": sc.formatted_time,
                        "round_rel_time": sc.round_rel_time,
                        "tag_category": sc.tag_category,
                        "tag_name": sc.tag_name,
                        "related_event": sc.related_event,
                        "evaluation": sc.evaluation,
                    }
                    for sc in result.self_criticisms
                ],
                "agreed_tags": [
                    {
                        "round_number": a.round_number,
                        "timestamp_ms": a.timestamp_ms,
                        "formatted_time": a.formatted_time,
                        "round_rel_time": a.round_rel_time,
                        "solo_tag_name": a.solo_tag_name,
                        "coach_tag_name": a.coach_tag_name,
                        "tag_category": a.tag_category,
                        "time_delta_ms": a.time_delta_ms,
                        "notes": a.notes,
                    }
                    for a in result.agreed_tags
                ],
                "category_divergence": [
                    {
                        "category": cd.category,
                        "solo_count": cd.solo_count,
                        "coach_count": cd.coach_count,
                        "agreed_count": cd.agreed_count,
                        "blindspots_count": cd.blindspots_count,
                        "self_criticisms_count": cd.self_criticisms_count,
                        "alignment_rate": cd.alignment_rate,
                        "status": cd.status,
                    }
                    for cd in result.category_divergence
                ],
                "executive_takeaways": result.executive_takeaways,
                "timeline_pips": result.timeline_pips,
            })
            return

        # 7.6. Aim Lab Playlist Export
        if path.startswith("/api/matches/") and path.endswith("/drills/aimlab-playlist"):
            parts = path.split("/")
            match_id = parts[3]
            player_puuid = query.get("player", [None])[0]
            routine = self.service.get_training_routine(match_id, player_puuid=player_puuid)
            if not routine:
                self._send_error("Match not found", status=404)
                return

            payload = json.dumps(routine.aimlab_playlist, indent=2).encode("utf-8")
            filename = f"vallens_{routine.map_name.lower()}_aimlab.json"
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        # 7.7. Practice Routines & Aim Drills API
        if path.startswith("/api/matches/") and path.endswith("/drills"):
            parts = path.split("/")
            match_id = parts[3]
            player_puuid = query.get("player", [None])[0]
            fmt = query.get("format", ["json"])[0]

            routine = self.service.get_training_routine(match_id, player_puuid=player_puuid)
            if not routine:
                self._send_error("Match not found", status=404)
                return

            if fmt == "markdown":
                payload = routine.markdown_routine.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            self._send_json({
                "match_id": routine.match_id,
                "map_name": routine.map_name,
                "total_routine_duration_min": routine.total_routine_duration_min,
                "primary_focus": routine.primary_focus,
                "summary": routine.summary,
                "prescriptions": [
                    {
                        "tag_name": p.tag_name,
                        "category": p.category,
                        "correlated_flaw_count": p.correlated_flaw_count,
                        "untraded_deaths_correlated": p.untraded_deaths_correlated,
                        "first_deaths_correlated": p.first_deaths_correlated,
                        "priority": p.priority,
                        "estimated_time_min": p.estimated_time_min,
                        "range_exercise": {
                            "exercise_name": p.range_exercise.exercise_name,
                            "weapon": p.range_exercise.weapon,
                            "target_mode": p.range_exercise.target_mode,
                            "armor_setting": p.range_exercise.armor_setting,
                            "duration_minutes": p.range_exercise.duration_minutes,
                            "instructions": p.range_exercise.instructions,
                            "coaching_cue": p.range_exercise.coaching_cue,
                        },
                        "aim_trainer_scenarios": [
                            {
                                "scenario_name": sc.scenario_name,
                                "platform": sc.platform,
                                "task_type": sc.task_type,
                                "recommended_plays": sc.recommended_plays,
                                "target_score": sc.target_score,
                                "notes": sc.notes,
                            }
                            for sc in p.aim_trainer_scenarios
                        ],
                        "map_drill": (
                            {
                                "map_name": p.map_drill.map_name,
                                "callout": p.map_drill.callout,
                                "objective": p.map_drill.objective,
                                "setup": p.map_drill.setup,
                                "drills": p.map_drill.drills,
                            }
                            if p.map_drill
                            else None
                        ),
                    }
                    for p in routine.prescriptions
                ],
                "aimlab_playlist": routine.aimlab_playlist,
                "markdown_routine": routine.markdown_routine,
            })
            return

        # 8. Match Overview
        if path.startswith("/api/matches/"):
            match_id = path.split("/")[3]
            overview = self.service.get_match_overview(match_id)
            if not overview:
                self._send_error("Match not found", status=404)
                return
            m = overview["metadata"]
            self._send_json({
                "metadata": {
                    "match_id": m.match_id,
                    "map_id": m.map_id,
                    "game_mode": m.game_mode,
                    "match_duration": m.match_duration,
                    "timestamp": m.timestamp,
                    "video_filepath": m.video_filepath,
                },
                "total_events": overview["total_events"],
                "rounds_count": overview["rounds_count"],
                "total_kills": overview["total_kills"],
                "total_deaths": overview["total_deaths"],
            })
            return

        if path == "/api/tags/summary":
            match_id = query.get("match_id", [None])[0]
            summary = self.service.repo.get_tag_aggregations(match_id=match_id)
            self._send_json(summary)
            return

        # Multi-Match Heatmap Aggregation & Maps Catalog
        if path == "/api/analytics/maps":
            maps = self.service.list_available_maps()
            self._send_json(maps)
            return

        if path == "/api/analytics/heatmap":
            map_param = query.get("map", ["Ascent"])[0]
            player_param = query.get("player", [None])[0]
            type_param = query.get("type", ["death"])[0]
            side_param = query.get("side", ["all"])[0]
            limit_param = int(query.get("limit", [20])[0])

            result = self.service.get_map_aggregate_heatmap(
                map_id_or_name=map_param,
                player_puuid=player_param,
                event_type=type_param,
                side=side_param,
                limit_matches=limit_param,
            )
            self._send_json(result.to_dict())
            return

        # Agent Profiling Matrix API
        if path == "/api/analytics/agents":
            puuid = query.get("player", [None])[0]
            matrix = self.service.get_agent_matrix(player_puuid=puuid)
            self._send_json(matrix.to_dict())
            return



        # Account detection endpoint
        if path == "/api/account/detect":
            from vallens.riot.account import AccountConnector
            connector = AccountConnector(service=self.service)
            acc = connector.detect_local_account()
            if not acc:
                self._send_error("No local client detected", status=404)
                return
            self._send_json(acc)
            return

        # OBS Status API
        if path == "/api/obs/status":
            obs_status = self.service.get_obs_status()
            self._send_json(obs_status)
            return

        # 9. Static Map Icons
        if path.startswith("/maps/"):
            map_name = path[len("/maps/"):].lower()
            if not map_name.endswith(".png"):
                map_name += ".png"
            file_path = DATA_MAPS_DIR / map_name
            if file_path.exists():
                self._serve_file(file_path, "image/png")
                return

        # 10. Local Video Streaming with HTTP Byte-Range (206)
        if path == "/api/video":
            video_param = query.get("path", [None])[0]
            if video_param and Path(video_param).exists():
                self._serve_video_range(Path(video_param))
                return
            self._send_error("Video file not found", status=404)
            return

        # 11. Web Frontend Static Files
        clean_path = path.lstrip("/")
        if not clean_path:
            clean_path = "index.html"
        target_file = STATIC_DIR / clean_path
        if target_file.exists() and target_file.is_file():
            mime_type, _ = mimetypes.guess_type(target_file)
            self._serve_file(target_file, mime_type or "application/octet-stream")
            return

        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            self._serve_file(index_file, "text/html")
            return

        self._send_error("Not found", status=404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/matches/") and path.endswith("/tags"):
            match_id = path.split("/")[3]
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(body)

            tag_id = self.service.add_vod_tag(
                match_id=match_id,
                timestamp_ms=int(data.get("timestamp_ms", 0)),
                category=str(data.get("category", "General")),
                name=str(data.get("name", "tag")),
                author_type=str(data.get("author", "solo")),
                event_id=data.get("event_id"),
            )
            self._send_json({"tag_id": tag_id, "success": True}, status=201)
            return

        if path == "/api/account/sync":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(body)

            from vallens.riot.account import AccountConnector
            connector = AccountConnector(
                service=self.service,
                riot_api_key=data.get("api_key"),
                region=data.get("region", "na"),
            )

            limit = int(data.get("limit", 3))
            riot_id = data.get("riot_id", "").strip()
            puuid = data.get("puuid")

            try:
                ingested = []
                if puuid and data.get("api_key"):
                    ingested = connector.sync_recent_matches(puuid, limit=limit, api_key=data.get("api_key"))
                elif "#" in riot_id:
                    name, tag = riot_id.split("#", 1)
                    ingested = connector.sync_by_henrik_api(name, tag, region=data.get("region", "na"), limit=limit, api_key=data.get("api_key"))
                else:
                    self._send_error("Invalid Riot ID format (expected Name#Tag)", status=400)
                    return

                self._send_json({
                    "synced_count": len(ingested),
                    "matches": [m.match_id for m in ingested],
                })
            except Exception as e:
                self._send_error(f"Sync failed: {e}", status=500)
            return

        # OBS Recording Action API
        if path == "/api/obs/record":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                data = json.loads(body) if body else {}
            except Exception:
                data = {}

            action = data.get("action", "toggle")
            try:
                res = self.service.set_obs_recording(action=action)
                self._send_json(res)
            except Exception as e:
                self._send_error(str(e), status=400)
            return

        # Associate Match Video Path API
        if path.startswith("/api/matches/") and path.endswith("/video"):
            match_id = path.split("/")[3]
            match = self.service.repo.get_match(match_id)
            if not match:
                self._send_error("Match not found", status=404)
                return

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                data = json.loads(body) if body else {}
            except Exception:
                data = {}

            video_filepath = data.get("video_filepath", "").strip()
            if not video_filepath:
                self._send_error("Missing video_filepath", status=400)
                return

            success = self.service.attach_match_video(match_id, video_filepath)
            self._send_json({
                "success": success,
                "match_id": match_id,
                "video_filepath": video_filepath,
            })
            return

        self._send_error("Unknown POST endpoint", status=404)

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/tags/"):
            tag_id = int(path.split("/")[3])
            success = self.service.repo.delete_tag(tag_id)
            self._send_json({"success": success})
            return

        self._send_error("Unknown DELETE endpoint", status=404)

    def _serve_file(self, file_path: Path, content_type: str) -> None:
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _serve_video_range(self, video_path: Path) -> None:
        file_size = video_path.stat().st_size
        range_header = self.headers.get("Range")

        if not range_header:
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(file_size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with open(video_path, "rb") as f:
                self.wfile.write(f.read())
            return

        bytes_spec = range_header.strip().replace("bytes=", "").split("-")
        start = int(bytes_spec[0]) if bytes_spec[0] else 0
        end = int(bytes_spec[1]) if len(bytes_spec) > 1 and bytes_spec[1] else file_size - 1
        length = end - start + 1

        self.send_response(206)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

        with open(video_path, "rb") as f:
            f.seek(start)
            self.wfile.write(f.read(length))


def run_server(
    service: Optional[ValLensService] = None,
    port: int = 8000,
    host: str = "127.0.0.1",
) -> ThreadingHTTPServer:
    """Initialize and start the ValLens review HTTP server."""
    ValLensRequestHandler.service = service or ValLensService()
    server = ThreadingHTTPServer((host, port), ValLensRequestHandler)
    logger.info(f"ValLens Review UI running at http://{host}:{port}/")
    return server
