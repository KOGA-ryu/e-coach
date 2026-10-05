"""Exporters for generating Edit Decision Lists (EDL) and chapter markers."""

from pathlib import Path
from typing import Any
from vallens.models import MatchEvent
from vallens.obs.sync import TimelineSynchronizer


class EdlExporter:
    """Generates standard CMX 3600 EDL, YouTube/VLC chapter marks, and FFmpeg metadata."""

    @staticmethod
    def build_round_segments(
        events: list[MatchEvent], synchronizer: TimelineSynchronizer
    ) -> list[dict[str, Any]]:
        """Group events into discrete round intervals with start, end, and summary comments."""
        rounds: dict[int, dict[str, Any]] = {}

        for e in events:
            r_num = e.round_number
            if r_num not in rounds:
                rounds[r_num] = {
                    "round_num": r_num,
                    "start_api_ms": e.event_time_ms,
                    "end_api_ms": e.event_time_ms + 100_000,
                    "result": None,
                    "winner": None,
                    "kills": 0,
                }

            if e.event_type == "round_start":
                rounds[r_num]["start_api_ms"] = e.event_time_ms
            elif e.event_type == "round_end":
                rounds[r_num]["end_api_ms"] = e.event_time_ms
                rounds[r_num]["winner"] = e.metadata.get("winning_team")
                rounds[r_num]["result"] = e.metadata.get("round_result")
            elif e.event_type == "kill":
                rounds[r_num]["kills"] += 1

        segments = []
        for r_num in sorted(rounds.keys()):
            r = rounds[r_num]
            start_vid_ms = synchronizer.api_to_video_ms(r["start_api_ms"])
            end_vid_ms = synchronizer.api_to_video_ms(r["end_api_ms"])
            if end_vid_ms <= start_vid_ms:
                end_vid_ms = start_vid_ms + 100_000

            comment = f"Round {r_num + 1}"
            if r_num == 0 or r_num == 12:
                comment += " (Pistol)"
            if r["winner"]:
                comment += f" - {r['winner']} Win ({r['result'] or 'Won'})"

            segments.append({
                "round_num": r_num,
                "start_ms": start_vid_ms,
                "end_ms": end_vid_ms,
                "comment": comment,
            })

        return segments

    @classmethod
    def export_cmx3600_edl(
        cls,
        events: list[MatchEvent],
        synchronizer: TimelineSynchronizer,
        video_filename: str,
        output_path: str | Path,
        title: str = "VALORANT_REVIEW",
        fps: int = 60,
    ) -> Path:
        """Export round segments to a standard CMX 3600 Edit Decision List (.edl) file."""
        segments = cls.build_round_segments(events, synchronizer)
        lines = [
            f"TITLE: {title.upper()}",
            "FCM: NON-DROP FRAME",
            "",
        ]

        clip_name = Path(video_filename).name

        for idx, seg in enumerate(segments, start=1):
            src_in = TimelineSynchronizer.ms_to_smpte(seg["start_ms"], fps=fps)
            src_out = TimelineSynchronizer.ms_to_smpte(seg["end_ms"], fps=fps)
            rec_in = src_in
            rec_out = src_out

            lines.append(f"{idx:03d}  AX       V     C        {src_in} {src_out} {rec_in} {rec_out}")
            lines.append(f"* FROM CLIP NAME: {clip_name}")
            lines.append(f"* COMMENT: {seg['comment']}")
            lines.append("")

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return out

    @classmethod
    def export_chapters_txt(
        cls,
        events: list[MatchEvent],
        synchronizer: TimelineSynchronizer,
        output_path: str | Path,
        include_kills: bool = True,
    ) -> Path:
        """Export timestamped chapters compatible with YouTube, VLC, and player bookmarks."""
        segments = cls.build_round_segments(events, synchronizer)
        entries: list[tuple[int, str]] = []

        for seg in segments:
            entries.append((seg["start_ms"], seg["comment"]))

        if include_kills:
            for e in events:
                if e.event_type == "kill":
                    vid_ms = synchronizer.api_to_video_ms(e.event_time_ms)
                    weapon = e.metadata.get("weapon", "Weapon")
                    victim = e.metadata.get("victim", "Enemy")
                    killer = e.player_puuid or "Player"
                    # shorten PUUID if long
                    if len(killer) > 16:
                        killer = killer[:8]
                    if len(victim) > 16:
                        victim = victim[:8]
                    entries.append((vid_ms, f"Kill: {killer} [{weapon}] -> {victim}"))

        entries.sort(key=lambda x: x[0])

        lines = []
        for ms, text in entries:
            time_str = TimelineSynchronizer.ms_to_display_time(ms)
            lines.append(f"{time_str} {text}")

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        return out

    @classmethod
    def export_ffmetadata(
        cls,
        events: list[MatchEvent],
        synchronizer: TimelineSynchronizer,
        output_path: str | Path,
        title: str = "ValLens Review",
    ) -> Path:
        """Export FFmpeg metadata file (FFMETADATA1) for embedding chapters into MP4/MKV."""
        segments = cls.build_round_segments(events, synchronizer)
        lines = [
            ";FFMETADATA1",
            f"title={title}",
            "",
        ]

        for seg in segments:
            lines.extend([
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={seg['start_ms']}",
                f"END={seg['end_ms']}",
                f"title={seg['comment']}",
                "",
            ])

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return out
