"""Coaching clip extractor & automated review montage reel generator.

Strictly 100% post-game offline clipping powered by FFmpeg CLI.
Analyzes post-game telemetry, win probability swings, clutches, multi-kills,
and coach flaw tags to automatically generate precision video clips and compilations.
"""

from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import re
from typing import Any, Optional

from vallens.analytics.trade_matrix import TradeFragMatrixEngine
from vallens.analytics.win_probability import WinProbabilityEngine
from vallens.db.repository import MatchRepository
from vallens.models import MatchEvent, VodTag
from vallens.obs.trimmer import ClipTrimmer, DEFAULT_CLIPS_DIR

logger = logging.getLogger(__name__)


@dataclass
class HighlightCandidate:
    """A detected highlight moment candidate for video clipping."""
    candidate_id: str
    match_id: str
    round_number: int
    timestamp_seconds: float
    duration_seconds: float
    label: str
    category: str  # "clutch", "swing", "multikill", "flaw", "first_blood"
    description: str
    priority_score: int  # 0 to 100
    pre_roll: float = 3.0
    post_roll: float = 2.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "match_id": self.match_id,
            "round_number": self.round_number,
            "timestamp_seconds": round(self.timestamp_seconds, 2),
            "duration_seconds": round(self.duration_seconds, 2),
            "label": self.label,
            "category": self.category,
            "description": self.description,
            "priority_score": self.priority_score,
            "pre_roll": round(self.pre_roll, 1),
            "post_roll": round(self.post_roll, 1),
            "metadata": self.metadata,
        }


class HighlightClipper:
    """Manages auto-detection of highlight moments and extraction of MP4 clips via FFmpeg."""

    def __init__(
        self,
        repo: MatchRepository,
        trimmer: Optional[ClipTrimmer] = None,
        win_prob_engine: Optional[WinProbabilityEngine] = None,
        trade_engine: Optional[TradeFragMatrixEngine] = None,
    ):
        self.repo = repo
        self.trimmer = trimmer or ClipTrimmer()
        self.win_prob_engine = win_prob_engine or WinProbabilityEngine(repo=repo)
        self.trade_engine = trade_engine or TradeFragMatrixEngine(repo=repo)

    def detect_highlight_candidates(
        self,
        match_id: str,
        player_puuid: Optional[str] = None,
    ) -> list[HighlightCandidate]:
        """Scan match telemetry, win probability swings, and flaw tags to discover highlights."""
        match = self.repo.get_match(match_id)
        if not match:
            return []

        events = self.repo.get_events(match_id)
        players = self.repo.get_match_players(match_id)
        player_map = {p.player_puuid: p for p in players}
        tags = self.repo.get_tags(match_id)

        candidates: list[HighlightCandidate] = []
        seen_keys: set[str] = set()

        # 1. 1vX Clutch Scenarios from Win Probability Engine
        try:
            win_report = self.win_prob_engine.calculate_match_probability(
                match_id=match_id,
                events=events,
                players=players,
                target_puuid=player_puuid,
            )
            for idx, c in enumerate(win_report.clutches):
                key = f"clutch_r{c.round_number}_{int(c.start_time_ms / 1000)}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                outcome_str = "Won" if c.won else "Lost"
                priority = 95 if c.won else 75
                dur = min(25.0, max(5.0, (c.duration_ms / 1000.0) if hasattr(c, "duration_ms") and c.duration_ms else 10.0))
                candidates.append(
                    HighlightCandidate(
                        candidate_id=f"cand_clutch_{c.round_number}_{idx+1}",
                        match_id=match_id,
                        round_number=c.round_number,
                        timestamp_seconds=c.start_time_ms / 1000.0,
                        duration_seconds=dur,
                        label=f"{c.scenario_type.upper()} Clutch {outcome_str}",
                        category="clutch",
                        description=f"{c.clutcher_name} on {c.clutcher_agent} faced {c.scenario_type.upper()} ({outcome_str}, Difficulty: {getattr(c, 'difficulty_score', 50.0) / 10.0:.1f}/10)",
                        priority_score=priority,
                        pre_roll=2.0,
                        post_roll=dur,
                        metadata=c.to_dict(),
                    )
                )

            # 2. Critical Momentum Swings (>= 30% delta W)
            for idx, sw in enumerate(win_report.momentum_swings):
                key = f"swing_r{sw.round_number}_{int(sw.timestamp_ms / 1000)}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                delta_pct = int(abs(sw.swing_delta) * 100)
                sign = "+" if sw.swing_delta > 0 else "-"
                candidates.append(
                    HighlightCandidate(
                        candidate_id=f"cand_swing_{sw.round_number}_{idx+1}",
                        match_id=match_id,
                        round_number=sw.round_number,
                        timestamp_seconds=sw.timestamp_ms / 1000.0,
                        duration_seconds=6.0,
                        label=f"{sign}{delta_pct}% Win Prob Swing",
                        category="swing",
                        description=f"Round {sw.round_number}: {sw.description} shifted win probability by {sign}{delta_pct}%.",
                        priority_score=85,
                        pre_roll=3.5,
                        post_roll=2.5,
                        metadata=sw.to_dict(),
                    )
                )
        except Exception as e:
            logger.warning(f"Error extracting clutch/swing candidates for {match_id}: {e}")

        # 3. Multi-Kill Sequences (3K, 4K, Ace)
        rounds_events: dict[int, list[MatchEvent]] = {}
        for ev in events:
            if ev.round_number is not None:
                rounds_events.setdefault(ev.round_number, []).append(ev)

        for rnd_num, r_events in sorted(rounds_events.items()):
            kills_by_player: dict[str, list[MatchEvent]] = {}
            for ev in r_events:
                if ev.event_type == "kill" and ev.player_puuid:
                    kills_by_player.setdefault(ev.player_puuid, []).append(ev)

            for p_puuid, p_kills in kills_by_player.items():
                if len(p_kills) >= 3:
                    p_info = player_map.get(p_puuid)
                    p_name = p_info.game_name if p_info else "Player"
                    first_kill = min(p_kills, key=lambda k: k.event_time_ms)
                    last_kill = max(p_kills, key=lambda k: k.event_time_ms)
                    start_sec = first_kill.event_time_ms / 1000.0
                    streak_dur = max(4.0, (last_kill.event_time_ms - first_kill.event_time_ms) / 1000.0 + 3.0)

                    kill_count = len(p_kills)
                    if kill_count >= 5:
                        badge = "ACE (5K)"
                        score = 100
                    elif kill_count == 4:
                        badge = "4K Quad-Kill"
                        score = 92
                    else:
                        badge = "3K Triple-Kill"
                        score = 80

                    key = f"multikill_r{rnd_num}_{p_puuid}"
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)

                    candidates.append(
                        HighlightCandidate(
                            candidate_id=f"cand_multi_r{rnd_num}_{p_puuid[:6]}",
                            match_id=match_id,
                            round_number=rnd_num,
                            timestamp_seconds=start_sec,
                            duration_seconds=min(30.0, streak_dur),
                            label=f"{badge} - {p_name}",
                            category="multikill",
                            description=f"{p_name} secured {kill_count} kills in Round {rnd_num} across {int(streak_dur)}s.",
                            priority_score=score,
                            pre_roll=3.0,
                            post_roll=streak_dur,
                            metadata={"kills_count": kill_count, "player_puuid": p_puuid, "player_name": p_name},
                        )
                    )

        # 4. Opening Duels (First Bloods)
        for rnd_num, r_events in sorted(rounds_events.items()):
            kills = [ev for ev in r_events if ev.event_type == "kill"]
            if kills:
                fb = min(kills, key=lambda k: k.event_time_ms)
                k_info = player_map.get(fb.player_puuid or "")
                k_name = k_info.game_name if k_info else "Attacker"
                v_puuid = fb.metadata.get("victim_puuid", "")
                v_info = player_map.get(v_puuid)
                v_name = v_info.game_name if v_info else "Defender"

                key = f"fb_r{rnd_num}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    sec = fb.event_time_ms / 1000.0
                    candidates.append(
                        HighlightCandidate(
                            candidate_id=f"cand_fb_r{rnd_num}",
                            match_id=match_id,
                            round_number=rnd_num,
                            timestamp_seconds=sec,
                            duration_seconds=5.0,
                            label=f"First Blood: {k_name}",
                            category="first_blood",
                            description=f"Round {rnd_num} opening duel: {k_name} eliminated {v_name} at {sec:.1f}s.",
                            priority_score=70,
                            pre_roll=3.5,
                            post_roll=2.5,
                            metadata={"killer": k_name, "victim": v_name, "round_number": rnd_num},
                        )
                    )

        # 5. Coach Tactical Flaws
        for t in tags:
            sec = t.timestamp_ms / 1000.0
            key = f"flaw_{t.tag_name}_{int(sec)}"
            if key not in seen_keys:
                seen_keys.add(key)
                candidates.append(
                    HighlightCandidate(
                        candidate_id=f"cand_flaw_{t.tag_id or int(sec)}",
                        match_id=match_id,
                        round_number=1,  # fallback if not bound to round
                        timestamp_seconds=sec,
                        duration_seconds=6.0,
                        label=f"Tactical Flaw: {t.tag_name.replace('_', ' ').title()}",
                        category="flaw",
                        description=f"Coach flagged {t.tag_category} error '{t.tag_name}' at {sec:.1f}s.",
                        priority_score=68,
                        pre_roll=3.5,
                        post_roll=2.5,
                        metadata={"tag_id": t.tag_id, "tag_category": t.tag_category, "tag_name": t.tag_name},
                    )
                )

        # Sort candidates by priority score descending, then by timestamp
        candidates.sort(key=lambda c: (-c.priority_score, c.timestamp_seconds))
        return candidates

    def render_candidate_clip(
        self,
        match_id: str,
        candidate_id: str,
        pre_roll: Optional[float] = None,
        post_roll: Optional[float] = None,
    ) -> dict[str, Any]:
        """Render an MP4 clip for a specific candidate highlight."""
        candidates = self.detect_highlight_candidates(match_id)
        target = next((c for c in candidates if c.candidate_id == candidate_id), None)
        if not target:
            raise ValueError(f"Candidate {candidate_id} not found in match {match_id}")

        match = self.repo.get_match(match_id)
        video_filepath = match.video_filepath if match else None

        pre = pre_roll if pre_roll is not None else target.pre_roll
        post = post_roll if post_roll is not None else target.post_roll

        clip = self.trimmer.trim_moment(
            match_id=match_id,
            timestamp_seconds=target.timestamp_seconds,
            video_filepath=video_filepath,
            pre_roll=pre,
            post_roll=post,
            label=f"{target.category}_{target.label}",
            round_number=target.round_number,
        )
        clip["candidate_id"] = candidate_id
        clip["priority_score"] = target.priority_score
        clip["category"] = target.category
        clip["description"] = target.description
        return clip

    def render_custom_clip(
        self,
        match_id: str,
        start_seconds: float,
        duration_seconds: float,
        label: str = "custom_clip",
        round_number: Optional[int] = None,
    ) -> dict[str, Any]:
        """Trim an arbitrary custom clip window."""
        match = self.repo.get_match(match_id)
        video_filepath = match.video_filepath if match else None

        return self.trimmer.trim_moment(
            match_id=match_id,
            timestamp_seconds=start_seconds + (duration_seconds / 2.0),
            video_filepath=video_filepath,
            pre_roll=duration_seconds / 2.0,
            post_roll=duration_seconds / 2.0,
            label=label,
            round_number=round_number,
        )

    def compile_highlight_reel(
        self,
        match_id: str,
        candidate_ids: Optional[list[str]] = None,
        title: Optional[str] = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        """Compile selected or top highlight candidates into a continuous review reel MP4."""
        candidates = self.detect_highlight_candidates(match_id)
        if candidate_ids:
            selected = [c for c in candidates if c.candidate_id in candidate_ids]
        else:
            selected = candidates[:limit]

        if not selected:
            raise ValueError(f"No highlight candidates available for match {match_id}")

        match = self.repo.get_match(match_id)
        video_filepath = match.video_filepath if match else None

        moments = [
            {
                "timestamp_seconds": c.timestamp_seconds,
                "label": f"{c.category}_{c.label}",
                "round_number": c.round_number,
            }
            for c in selected
        ]

        reel_title = title or "Match Highlights Reel"
        montage = self.trimmer.create_montage(
            match_id=match_id,
            moments=moments,
            video_filepath=video_filepath,
            title=reel_title,
            pre_roll=3.0,
            post_roll=2.5,
        )
        montage["candidates"] = [c.to_dict() for c in selected]
        return montage

    def list_saved_clips(self, match_id: Optional[str] = None) -> list[dict[str, Any]]:
        """List previously exported MP4 clips from the data/clips directory."""
        clips_dir = self.trimmer.clips_dir
        if not clips_dir.exists():
            return []

        results = []
        short_id = match_id.replace("-", "")[:8] if match_id else ""

        for file_path in sorted(clips_dir.glob("*.mp4"), key=os.path.getmtime, reverse=True):
            if short_id and short_id not in file_path.name:
                continue

            stat = file_path.stat()
            results.append({
                "filename": file_path.name,
                "output_path": str(file_path),
                "download_url": f"/api/clips/{file_path.name}",
                "file_size_bytes": stat.st_size,
                "file_size_mb": round(stat.st_size / (1024 * 1024), 2),
                "modified_at": int(stat.st_mtime * 1000),
                "is_montage": "montage" in file_path.name.lower(),
            })

        return results
