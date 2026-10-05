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
