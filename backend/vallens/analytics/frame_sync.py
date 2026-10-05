"""Automated VOD-to-API Frame Alignment Engine for ValLens.

Synchronizes local video recording timelines with Riot API match telemetry events
using multi-modal acoustic, visual landmark, and event-sequence cross-correlation.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from vallens.models import MatchEvent, MatchMetadata

logger = logging.getLogger("vallens.analytics.frame_sync")


@dataclass
class DetectedLandmark:
    """A visual or acoustic transition detected in the video stream."""
    time_sec: float
    landmark_type: str  # 'scene_cut', 'audio_spike', 'black_frame_exit', 'metadata_start'
    confidence: float
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "time_sec": round(self.time_sec, 3),
            "landmark_type": self.landmark_type,
            "confidence": round(self.confidence, 2),
            "description": self.description,
        }


@dataclass
class FrameSyncResult:
    """The result of video-to-telemetry frame alignment."""
    match_id: str
    suggested_offset_ms: int
    confidence: float
    strategy_used: str
    detected_landmarks: list[dict[str, Any]] = field(default_factory=list)
    candidate_offsets: list[dict[str, Any]] = field(default_factory=list)
    aligned_events_count: int = 0
    diagnostic_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "suggested_offset_ms": self.suggested_offset_ms,
            "suggested_offset_sec": round(self.suggested_offset_ms / 1000.0, 2),
            "confidence": round(self.confidence, 2),
            "strategy_used": self.strategy_used,
            "detected_landmarks": self.detected_landmarks,
            "candidate_offsets": self.candidate_offsets,
            "aligned_events_count": self.aligned_events_count,
            "diagnostic_notes": self.diagnostic_notes,
        }


class FrameSyncEngine:
    """Zero-drift millisecond alignment engine correlating video frames with Riot API telemetry."""

    def __init__(self, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe"):
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin

    def detect_video_metadata_start(self, video_path: Path | str) -> Optional[float]:
        """Extract creation_time tag from video container metadata using ffprobe."""
        path = Path(video_path)
        if not path.exists():
            return None

        cmd = [
            self.ffprobe_bin,
            "-v", "quiet",
            "-print_format", "json",
            "-show_entries", "format_tags=creation_time:format=duration,start_time",
            str(path),
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
            if res.returncode == 0 and res.stdout:
                data = json.loads(res.stdout)
                tags = data.get("format", {}).get("tags", {})
                c_time = tags.get("creation_time")
                if c_time:
                    # ISO 8601 parsing
                    dt = datetime.fromisoformat(c_time.replace("Z", "+00:00"))
                    return dt.timestamp() * 1000.0
        except Exception as e:
            logger.debug(f"Could not read video metadata tags: {e}")
        return None

    def detect_visual_landmarks(
        self, video_path: Path | str, scan_duration_sec: float = 120.0
    ) -> list[DetectedLandmark]:
        """Detect scene transitions, barrier drops, and visual cuts using ffmpeg scene filter."""
        path = Path(video_path)
        if not path.exists():
            return []

        landmarks: list[DetectedLandmark] = []
        cmd = [
            self.ffmpeg_bin,
            "-i", str(path),
            "-t", str(scan_duration_sec),
            "-filter:v", "select='gt(scene,0.22)',showinfo",
            "-f", "null",
            "-",
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
            stderr = res.stderr or ""

            # Regex parse showinfo pts_time
            # e.g., [Parsed_showinfo_1 @ ...] n: 42 pts_time:14.240000
            for match in re.finditer(r"pts_time:([0-9\.]+)", stderr):
                t_sec = float(match.group(1))
                # Filter out closely spaced duplicate cuts (< 1.5s)
                if not landmarks or (t_sec - landmarks[-1].time_sec) >= 1.5:
                    landmarks.append(
                        DetectedLandmark(
                            time_sec=t_sec,
                            landmark_type="scene_cut",
                            confidence=0.85,
                            description=f"Visual HUD / camera transition at {t_sec:.1f}s",
                        )
                    )
        except Exception as e:
            logger.warning(f"FFmpeg visual landmark detection failed: {e}")

        return landmarks

    def detect_acoustic_spikes(
        self, video_path: Path | str, scan_duration_sec: float = 120.0
    ) -> list[DetectedLandmark]:
        """Detect acoustic transients and volume spikes (round horns, initial gunshots)."""
        path = Path(video_path)
        if not path.exists():
            return []

        landmarks: list[DetectedLandmark] = []
        # Extract audio volume peaks using ebur128 or silencedetect
        cmd = [
            self.ffmpeg_bin,
            "-i", str(path),
            "-t", str(scan_duration_sec),
            "-af", "silencedetect=noise=-28dB:d=0.8",
            "-f", "null",
            "-",
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            stderr = res.stderr or ""

            # Parse silence_end timestamps (marking sound start after buy phase silence)
            for match in re.finditer(r"silence_end:\s*([0-9\.]+)", stderr):
                t_sec = float(match.group(1))
                if not landmarks or (t_sec - landmarks[-1].time_sec) >= 2.0:
                    landmarks.append(
                        DetectedLandmark(
                            time_sec=t_sec,
                            landmark_type="audio_spike",
                            confidence=0.80,
                            description=f"Acoustic transient / barrier drop sound at {t_sec:.1f}s",
                        )
                    )
        except Exception as e:
            logger.warning(f"FFmpeg acoustic spike detection failed: {e}")

        return landmarks

    def correlate_event_sequence(
        self,
        video_landmarks: list[DetectedLandmark],
        events: list[MatchEvent],
        search_window_sec: tuple[float, float] = (-30.0, 90.0),
        step_sec: float = 0.2,
        sigma_sec: float = 1.8,
    ) -> tuple[int, float, list[dict[str, Any]]]:
        """Correlate candidate landmark timestamps against Riot API event timings.

        Evaluates candidate offsets O in search_window_sec.
        Score(O) = sum_e max_l exp( - (e_time - (l_time - O))^2 / (2 * sigma^2) )
        Returns (best_offset_ms, confidence, top_candidates).
        """
        if not video_landmarks or not events:
            return (0, 0.0, [])

        # Anchor events: round_start, kills, plant, defuse
        target_event_times: list[float] = []
        for e in events:
            if e.event_type in ("round_start", "kill", "plant", "defuse") and e.event_time_ms < 180000:
                target_event_times.append(e.event_time_ms / 1000.0)

        if not target_event_times:
            return (0, 0.0, [])

        landmark_times = [l.time_sec for l in video_landmarks]

        min_off, max_off = search_window_sec
        steps = int((max_off - min_off) / step_sec) + 1

        best_offset = 0.0
        best_score = -1.0
        scores: list[tuple[float, float]] = []

        two_sigma_sq = 2.0 * (sigma_sec ** 2)

        for i in range(steps):
            cand_offset = min_off + (i * step_sec)
            score = 0.0

            for et in target_event_times:
                # Video expected time for this event
                expected_vt = et + cand_offset
                # Find closest landmark
                min_dist_sq = min((vt - expected_vt) ** 2 for vt in landmark_times)
                score += math.exp(-min_dist_sq / two_sigma_sq)

            scores.append((cand_offset, score))
            if score > best_score:
                best_score = score
                best_offset = cand_offset

        # Calculate confidence metric from peak-to-average ratio
        avg_score = sum(s[1] for s in scores) / max(1, len(scores))
        peak_ratio = best_score / max(1e-4, avg_score)
        confidence = min(0.98, max(0.45, 0.40 + (peak_ratio - 1.0) * 0.15))

        # Top 3 candidate offsets
        scores.sort(key=lambda x: x[1], reverse=True)
        top_candidates = [
            {"offset_sec": round(s[0], 2), "offset_ms": int(s[0] * 1000), "score": round(s[1], 2)}
            for s in scores[:4]
        ]

        best_offset_ms = int(round(best_offset * 1000))
        return (best_offset_ms, confidence, top_candidates)

    def analyze_and_align(
        self,
        metadata: MatchMetadata,
        events: list[MatchEvent],
        video_filepath: Optional[str | Path] = None,
    ) -> FrameSyncResult:
        """Run full alignment analysis pipeline to determine millisecond synchronization offset."""
        target_path = Path(video_filepath or metadata.video_filepath or "")
        notes: list[str] = []

        # If file does not exist on disk, fallback to relative round_start sequence or default 0
        if not target_path.exists():
            notes.append(f"Video file '{target_path}' not found on local disk. Using metadata timing.")
            r1_start = 0
            for e in events:
                if e.event_type == "round_start" and e.round_number == 0:
                    r1_start = e.event_time_ms
                    break

            return FrameSyncResult(
                match_id=metadata.match_id,
                suggested_offset_ms=r1_start,
                confidence=0.60,
                strategy_used="event_round_start_fallback",
                detected_landmarks=[],
                candidate_offsets=[{"offset_sec": r1_start / 1000.0, "offset_ms": r1_start, "score": 1.0}],
                aligned_events_count=len(events),
                diagnostic_notes=notes,
            )

        # 1. Detect visual and acoustic landmarks
        visual_landmarks = self.detect_visual_landmarks(target_path, scan_duration_sec=120.0)
        acoustic_landmarks = self.detect_acoustic_spikes(target_path, scan_duration_sec=120.0)
        all_landmarks = visual_landmarks + acoustic_landmarks
        all_landmarks.sort(key=lambda l: l.time_sec)

        notes.append(f"Detected {len(visual_landmarks)} visual scene transitions and {len(acoustic_landmarks)} acoustic spikes in video.")

        # 2. Correlate with Riot API event sequence
        if all_landmarks:
            offset_ms, confidence, candidates = self.correlate_event_sequence(
                all_landmarks, events, search_window_sec=(-20.0, 75.0), step_sec=0.2
            )
            strategy = "acoustic_visual_cross_correlation"
            notes.append(f"Cross-correlation matched peak alignment at {offset_ms / 1000.0:.2f}s with {confidence * 100:.0f}% confidence.")
        else:
            # Fallback 1: Container creation_time vs match epoch
            container_start_ms = self.detect_video_metadata_start(target_path)
            if container_start_ms and metadata.timestamp:
                delta_ms = int(container_start_ms - metadata.timestamp)
                offset_ms = delta_ms
                confidence = 0.82
                strategy = "video_metadata_delta"
                candidates = [{"offset_sec": round(delta_ms / 1000.0, 2), "offset_ms": delta_ms, "score": 0.85}]
                notes.append(f"Aligned via container creation_time delta: {delta_ms / 1000.0:.2f}s.")
            else:
                offset_ms = 0
                confidence = 0.50
                strategy = "default_zero_offset"
                candidates = [{"offset_sec": 0.0, "offset_ms": 0, "score": 0.5}]
                notes.append("No distinct landmarks detected; defaulted to 0.0s offset.")

        return FrameSyncResult(
            match_id=metadata.match_id,
            suggested_offset_ms=offset_ms,
            confidence=confidence,
            strategy_used=strategy,
            detected_landmarks=[l.to_dict() for l in all_landmarks[:10]],
            candidate_offsets=candidates,
            aligned_events_count=len(events),
            diagnostic_notes=notes,
        )

    def calibrate_from_point(
        self,
        match_id: str,
        video_time_ms: int,
        target_event_time_ms: int,
        event_name: str = "Round 1 Start",
    ) -> FrameSyncResult:
        """Calibrate offset directly from a user-identified or frame-locked landmark point.

        Formula: video_time_ms = event_time_ms + video_offset_ms
        => video_offset_ms = video_time_ms - event_time_ms
        """
        offset_ms = int(video_time_ms - target_event_time_ms)
        notes = [
            f"Manually calibrated frame lock: aligned {event_name} (API {target_event_time_ms / 1000.0:.2f}s) to video frame {video_time_ms / 1000.0:.2f}s.",
            f"Calculated offset: {offset_ms / 1000.0:+.2f}s ({offset_ms}ms).",
        ]
        return FrameSyncResult(
            match_id=match_id,
            suggested_offset_ms=offset_ms,
            confidence=1.0,
            strategy_used="manual_landmark_calibration",
            detected_landmarks=[
                {
                    "time_sec": round(video_time_ms / 1000.0, 3),
                    "landmark_type": "user_frame_anchor",
                    "confidence": 1.0,
                    "description": f"Frame lock: {event_name}",
                }
            ],
            candidate_offsets=[{"offset_sec": round(offset_ms / 1000.0, 2), "offset_ms": offset_ms, "score": 1.0}],
            aligned_events_count=1,
            diagnostic_notes=notes,
        )
