"""Automated video clipping and trimming engine powered by FFmpeg."""

import logging
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Optional

from vallens.models import VodTag

logger = logging.getLogger(__name__)

DEFAULT_CLIPS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "clips"


class ClipTrimmer:
    """Manages cutting, exporting, and synthesizing precision MP4 video clips."""

    def __init__(self, clips_dir: Optional[Path | str] = None, ffmpeg_bin: Optional[str] = None):
        self.clips_dir = Path(clips_dir) if clips_dir else DEFAULT_CLIPS_DIR
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_bin = ffmpeg_bin or shutil.which("ffmpeg") or "ffmpeg"

    def has_ffmpeg(self) -> bool:
        """Check if ffmpeg executable is available on the system."""
        try:
            res = subprocess.run(
                [self.ffmpeg_bin, "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=3.0,
            )
            return res.returncode == 0
        except Exception:
            return False

    def trim_clip(
        self,
        source_video: Path | str,
        start_seconds: float,
        duration_seconds: float,
        output_path: Optional[Path | str] = None,
        reencode: bool = False,
    ) -> Path:
        """Trim a video file to the specified time window.

        Args:
            source_video: Path to the input video file.
            start_seconds: Timestamp to begin clipping.
            duration_seconds: Duration of the extracted clip.
            output_path: Target destination path for the clip.
            reencode: If True, re-encodes with libx264; if False, attempts fast stream copy first.

        Returns:
            Path to the successfully created clip file.
        """
        source_path = Path(source_video)
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"Source video file not found: {source_path}")

        if not output_path:
            clean_stem = source_path.stem
            out_name = f"{clean_stem}_{int(start_seconds)}s_{int(duration_seconds)}s.mp4"
            output_path = self.clips_dir / out_name
        else:
            output_path = Path(output_path)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        start_str = f"{max(0.0, start_seconds):.3f}"
        dur_str = f"{max(0.5, duration_seconds):.3f}"

        # 1. Attempt fast stream copy if reencode=False
        if not reencode:
            cmd = [
                self.ffmpeg_bin,
                "-y",
                "-ss",
                start_str,
                "-i",
                str(source_path),
                "-t",
                dur_str,
                "-c",
                "copy",
                "-avoid_negative_ts",
                "make_zero",
                str(output_path),
            ]
            try:
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30.0)
                if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    logger.info(f"Stream copy clip created: {output_path}")
                    return output_path
                logger.warning("Stream copy failed; falling back to ultrafast re-encoding.")
            except Exception as e:
                logger.warning(f"Stream copy encountered error ({e}); falling back to re-encoding.")

        # 2. Re-encode clip with ultrafast x264 preset
        cmd_reencode = [
            self.ffmpeg_bin,
            "-y",
            "-ss",
            start_str,
            "-i",
            str(source_path),
            "-t",
            dur_str,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(output_path),
        ]
        proc = subprocess.run(cmd_reencode, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60.0)
        if proc.returncode != 0:
            err_msg = proc.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"FFmpeg trimming failed (code {proc.returncode}): {err_msg}")

        logger.info(f"Re-encoded clip created: {output_path}")
        return output_path

    def generate_synthetic_clip(
        self,
        duration_seconds: float,
        output_path: Path | str,
        label: str = "ValLens Flaw Review",
    ) -> Path:
        """Generate a synthetic test clip when no raw VOD file is present."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        dur = max(1.0, duration_seconds)

        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={dur:.2f}:size=1280x720:rate=30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20.0)
        if proc.returncode != 0:
            err_msg = proc.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"FFmpeg synthetic clip generation failed: {err_msg}")

        logger.info(f"Generated synthetic clip: {output_path}")
        return output_path

    def trim_moment(
        self,
        match_id: str,
        timestamp_seconds: float,
        video_filepath: Optional[str] = None,
        pre_roll: float = 3.0,
        post_roll: float = 2.0,
        label: Optional[str] = None,
        round_number: Optional[int] = None,
    ) -> dict[str, Any]:
        """Convenience method to extract or synthesize a clip for a specific match moment.

        Args:
            match_id: Target match identifier.
            timestamp_seconds: Target moment timestamp (relative to video or match).
            video_filepath: Path to local VOD video file (if available).
            pre_roll: Seconds to include prior to the event (default 3.0).
            post_roll: Seconds to include after the event (default 2.0).
            label: Descriptive flaw or event tag name.
            round_number: Round in which event took place.

        Returns:
            Dictionary with clip metadata and download/playback URI.
        """
        start_sec = max(0.0, timestamp_seconds - pre_roll)
        duration_sec = pre_roll + post_roll

        clean_label = (label or "moment").replace(" ", "_").replace("/", "_").lower()
        round_part = f"_r{round_number}" if round_number is not None else ""
        short_id = match_id.replace("-", "")[:8]
        filename = f"vallens_{short_id}{round_part}_{clean_label}_{int(start_sec)}s.mp4"
        dest_path = self.clips_dir / filename

        is_synthetic = False
        if video_filepath and Path(video_filepath).exists() and Path(video_filepath).is_file():
            self.trim_clip(
                source_video=video_filepath,
                start_seconds=start_sec,
                duration_seconds=duration_sec,
                output_path=dest_path,
            )
        else:
            # Fall back to synthetic clip for demo/testing when no physical VOD on disk
            self.generate_synthetic_clip(
                duration_seconds=duration_sec,
                output_path=dest_path,
                label=f"{label or 'Moment'} (Round {round_number if round_number is not None else '?'})",
            )
            is_synthetic = True

        file_size = dest_path.stat().st_size if dest_path.exists() else 0

        return {
            "match_id": match_id,
            "round_number": round_number,
            "label": label or "moment",
            "start_seconds": round(start_sec, 2),
            "duration_seconds": round(duration_sec, 2),
            "filename": filename,
            "output_path": str(dest_path),
            "download_url": f"/api/clips/{filename}",
            "file_size_bytes": file_size,
            "is_synthetic": is_synthetic,
        }

    def batch_trim_tags(
        self,
        match_id: str,
        tags: list[VodTag],
        video_filepath: Optional[str] = None,
        pre_roll: float = 3.0,
        post_roll: float = 2.0,
    ) -> list[dict[str, Any]]:
        """Batch-export clips for every tagged flaw in a match."""
        results = []
        for tag in tags:
            sec = tag.timestamp_ms / 1000.0
            clip = self.trim_moment(
                match_id=match_id,
                timestamp_seconds=sec,
                video_filepath=video_filepath,
                pre_roll=pre_roll,
                post_roll=post_roll,
                label=tag.tag_name,
            )
            clip["tag_id"] = tag.tag_id
            clip["category"] = tag.tag_category
            clip["author"] = tag.author_type
            results.append(clip)
        return results

    def create_montage(
        self,
        match_id: str,
        moments: list[dict[str, Any]],
        video_filepath: Optional[str] = None,
        output_path: Optional[Path | str] = None,
        pre_roll: float = 3.0,
        post_roll: float = 2.0,
        title: Optional[str] = None,
    ) -> dict[str, Any]:
        """Combine multiple match moments/flaws into a single concatenated review montage MP4.

        Args:
            match_id: Target match identifier.
            moments: List of dicts, each with 'timestamp_seconds', 'label', and optional 'round_number'.
            video_filepath: Path to local VOD video file (if available).
            output_path: Target path for the combined montage MP4.
            pre_roll: Seconds to include prior to each event.
            post_roll: Seconds to include after each event.
            title: Optional montage title.

        Returns:
            Dictionary with montage metadata, duration, segment count, and download URI.
        """
        if not moments:
            raise ValueError("No moments provided to generate montage.")

        short_id = match_id.replace("-", "")[:8]
        clean_title = (title or "review_reel").lower().replace(" ", "_")
        filename = f"vallens_{short_id}_{clean_title}_montage.mp4"
        dest_path = Path(output_path) if output_path else self.clips_dir / filename
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        temp_seg_dir = self.clips_dir / f"temp_montage_{short_id}"
        temp_seg_dir.mkdir(parents=True, exist_ok=True)

        segment_paths: list[Path] = []
        try:
            # 1. Generate or trim individual segment clips
            for idx, moment in enumerate(moments):
                ts = float(moment.get("timestamp_seconds", 0.0))
                lbl = moment.get("label", f"moment_{idx+1}")
                rnd = moment.get("round_number")

                clip_info = self.trim_moment(
                    match_id=match_id,
                    timestamp_seconds=ts,
                    video_filepath=video_filepath,
                    pre_roll=pre_roll,
                    post_roll=post_roll,
                    label=f"{idx+1}_{lbl}",
                    round_number=rnd,
                )
                src_clip = Path(clip_info["output_path"])
                if src_clip.exists():
                    segment_paths.append(src_clip)

            if not segment_paths:
                raise RuntimeError("Failed to extract any segments for the montage.")

            # 2. Write filelist.txt for FFmpeg concat demuxer
            concat_list_file = temp_seg_dir / "concat_list.txt"
            with open(concat_list_file, "w", encoding="utf-8") as f:
                for seg in segment_paths:
                    safe_path = str(seg.resolve()).replace("'", "'\\''")
                    f.write(f"file '{safe_path}'\n")

            # 3. Concatenate using FFmpeg concat demuxer (-c copy)
            cmd_concat = [
                self.ffmpeg_bin,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list_file),
                "-c",
                "copy",
                str(dest_path),
            ]
            proc = subprocess.run(cmd_concat, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45.0)

            # 4. Fallback to re-encoding concat if stream copy fails
            if proc.returncode != 0 or not dest_path.exists() or dest_path.stat().st_size == 0:
                logger.warning("Concat stream copy failed; falling back to re-encoding concat filter.")
                cmd_reencode = [
                    self.ffmpeg_bin,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_list_file),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-pix_fmt",
                    "yuv420p",
                    "-crf",
                    "22",
                    str(dest_path),
                ]
                proc_re = subprocess.run(cmd_reencode, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90.0)
                if proc_re.returncode != 0:
                    err_msg = proc_re.stderr.decode("utf-8", errors="replace")
                    raise RuntimeError(f"FFmpeg montage concatenation failed: {err_msg}")

            total_dur = len(segment_paths) * (pre_roll + post_roll)
            file_size = dest_path.stat().st_size if dest_path.exists() else 0

            return {
                "match_id": match_id,
                "title": title or "Review Reel",
                "filename": dest_path.name,
                "output_path": str(dest_path),
                "download_url": f"/api/clips/{dest_path.name}",
                "file_size_bytes": file_size,
                "segments_count": len(segment_paths),
                "total_duration_seconds": round(total_dur, 2),
                "moments": moments,
            }

        finally:
            shutil.rmtree(temp_seg_dir, ignore_errors=True)
