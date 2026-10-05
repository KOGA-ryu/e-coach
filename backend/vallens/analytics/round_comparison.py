"""Round-over-round side-by-side comparison & multi-perspective synchronizer.

Strictly 100% post-game offline telemetry comparison.
Compares two rounds (e.g. Round 3 Eco vs Round 15 Full Buy) with lockstepped timeline,
simultaneous 2D path replay, trade differences, and automated coaching divergence takeaways.
"""

from dataclasses import dataclass, field
import logging
from typing import Any, Optional

from vallens.analytics.trade_matrix import TradeFragMatrixEngine
from vallens.analytics.win_probability import WinProbabilityEngine
from vallens.db.repository import MatchRepository
from vallens.models import MatchEvent, MatchPlayer

logger = logging.getLogger(__name__)


@dataclass
class RoundSummary:
    """Consolidated telemetry and tactical summary for a single round."""
    round_number: int
    won: bool
    winning_team: str
    user_team: str
    side: str  # "Attack" or "Defense"
    duration_seconds: float
    start_time_ms: int
    end_time_ms: int
    first_blood: Optional[dict[str, Any]]
    kills_count: int
    deaths_count: int
    economy_tier: str  # "eco", "force", "full_buy"
    credits_spent: int
    utility_used: int
    wasted_utility: int
    utility_roi: float
    untraded_deaths: int
    trades_landed: int
    spike_planted: bool
    plant_time_sec: Optional[float]
    defused: bool
    win_probability_curve: list[dict[str, Any]] = field(default_factory=list)
    player_paths: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    key_events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "won": self.won,
            "winning_team": self.winning_team,
            "user_team": self.user_team,
            "side": self.side,
            "duration_seconds": round(self.duration_seconds, 1),
            "start_time_ms": self.start_time_ms,
            "end_time_ms": self.end_time_ms,
            "first_blood": self.first_blood,
            "kills_count": self.kills_count,
            "deaths_count": self.deaths_count,
            "economy_tier": self.economy_tier,
            "credits_spent": self.credits_spent,
            "utility_used": self.utility_used,
            "wasted_utility": self.wasted_utility,
            "utility_roi": round(self.utility_roi, 1),
            "untraded_deaths": self.untraded_deaths,
            "trades_landed": self.trades_landed,
            "spike_planted": self.spike_planted,
            "plant_time_sec": round(self.plant_time_sec, 1) if self.plant_time_sec is not None else None,
            "defused": self.defused,
            "win_probability_curve": self.win_probability_curve,
            "player_paths": self.player_paths,
            "key_events": self.key_events,
        }


@dataclass
class RoundComparisonResult:
    """Side-by-side comparative analysis of two rounds."""
    match_id: str
    map_name: str
    round_a: RoundSummary
    round_b: RoundSummary
    deltas: dict[str, Any]
    key_takeaways: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "map_name": self.map_name,
            "round_a": self.round_a.to_dict(),
            "round_b": self.round_b.to_dict(),
            "deltas": self.deltas,
            "key_takeaways": self.key_takeaways,
        }


class RoundComparisonEngine:
    """Extracts and compares tactical differences between two rounds."""

    def __init__(
        self,
        repo: MatchRepository,
        win_prob_engine: Optional[WinProbabilityEngine] = None,
        trade_engine: Optional[TradeFragMatrixEngine] = None,
    ):
        self.repo = repo
        self.win_prob_engine = win_prob_engine or WinProbabilityEngine(repo=repo)
        self.trade_engine = trade_engine or TradeFragMatrixEngine(repo=repo)

    def compare(
        self,
        match_id: str,
        round_a_num: int,
        round_b_num: int,
        target_puuid: Optional[str] = None,
    ) -> RoundComparisonResult:
        """Execute complete round-over-round comparison."""
        match = self.repo.get_match(match_id)
        if not match:
            raise ValueError(f"Match not found: {match_id}")

        players = self.repo.get_match_players(match_id)
        player_map = {p.player_puuid: p for p in players}

        # Determine user PUUID and user team
        user_p = player_map.get(target_puuid or "") if target_puuid else (players[0] if players else None)
        user_team = user_p.team_id if user_p else "Blue"

        # Extract round summaries
        summary_a = self._build_round_summary(match_id, round_a_num, players, user_team)
        summary_b = self._build_round_summary(match_id, round_b_num, players, user_team)

        # Compute metric deltas
        fb_a_time = summary_a.first_blood.get("round_time_sec", 0.0) if summary_a.first_blood else 0.0
        fb_b_time = summary_b.first_blood.get("round_time_sec", 0.0) if summary_b.first_blood else 0.0
        fb_delta = round(fb_b_time - fb_a_time, 1)

        dur_delta = round(summary_b.duration_seconds - summary_a.duration_seconds, 1)
        roi_delta = round(summary_b.utility_roi - summary_a.utility_roi, 1)
        untraded_delta = summary_b.untraded_deaths - summary_a.untraded_deaths

        deltas = {
            "duration_delta_sec": dur_delta,
            "first_blood_delta_sec": fb_delta,
            "utility_roi_delta": roi_delta,
            "untraded_deaths_delta": untraded_delta,
            "trades_delta": summary_b.trades_landed - summary_a.trades_landed,
            "credits_spent_delta": summary_b.credits_spent - summary_a.credits_spent,
        }

        # Generate intelligent coaching takeaways
        takeaways = self._generate_takeaways(summary_a, summary_b, deltas)

        return RoundComparisonResult(
            match_id=match_id,
            map_name=match.map_id or "Ascent",
            round_a=summary_a,
            round_b=summary_b,
            deltas=deltas,
            key_takeaways=takeaways,
        )

    def _build_round_summary(
        self,
        match_id: str,
        round_num: int,
        players: list[MatchPlayer],
        user_team: str,
    ) -> RoundSummary:
        """Synthesize metrics for a specific round."""
        player_map = {p.player_puuid: p for p in players}
        events = self.repo.get_events(match_id, round_number=round_num)
        tags = [t for t in self.repo.get_tags(match_id) if getattr(t, "round_number", None) == round_num]

        # Timing and duration
        round_start = next((e for e in events if e.event_type == "round_start"), None)
        round_end = next((e for e in events if e.event_type == "round_end"), None)

        start_time_ms = round_start.event_time_ms if round_start else (min((e.event_time_ms for e in events), default=0))
        end_time_ms = round_end.event_time_ms if round_end else (max((e.event_time_ms for e in events), default=start_time_ms + 45000))
        duration_sec = max(10.0, (end_time_ms - start_time_ms) / 1000.0)

        # Side calculation (Valorant switches at round 12)
        is_attack = (user_team == "Red" and round_num <= 12) or (user_team == "Blue" and round_num > 12)
        side = "Attack" if is_attack else "Defense"

        # Kills and Deaths
        kills = [e for e in events if e.event_type == "kill"]
        first_blood: Optional[dict[str, Any]] = None
        if kills:
            fb = min(kills, key=lambda k: k.event_time_ms)
            k_info = player_map.get(fb.player_puuid or "")
            v_puuid = fb.metadata.get("victim_puuid", "")
            v_info = player_map.get(v_puuid)
            fb_time = max(0.0, (fb.event_time_ms - start_time_ms) / 1000.0)
            first_blood = {
                "killer_name": k_info.game_name if k_info else "Attacker",
                "killer_agent": k_info.character_id if k_info else "Jett",
                "killer_team": k_info.team_id if k_info else "Blue",
                "victim_name": v_info.game_name if v_info else "Defender",
                "victim_agent": v_info.character_id if v_info else "Omen",
                "victim_team": v_info.team_id if v_info else "Red",
                "round_time_sec": round(fb_time, 1),
                "timestamp_ms": fb.event_time_ms,
                "pos_x": fb.pos_x,
                "pos_y": fb.pos_y,
            }

        deaths = [e for e in events if e.event_type == "death"]
        if not first_blood and deaths:
            fb_d = min(deaths, key=lambda k: k.event_time_ms)
            v_info = player_map.get(fb_d.player_puuid or "")
            k_puuid = fb_d.metadata.get("killer_puuid") or fb_d.metadata.get("killer", "")
            k_info = player_map.get(k_puuid)
            fb_time = max(0.0, (fb_d.event_time_ms - start_time_ms) / 1000.0)
            first_blood = {
                "killer_name": k_info.game_name if k_info else "Attacker",
                "killer_agent": k_info.character_id if k_info else "Jett",
                "killer_team": k_info.team_id if k_info else ("Red" if v_info and v_info.team_id == "Blue" else "Blue"),
                "victim_name": v_info.game_name if v_info else "Defender",
                "victim_agent": v_info.character_id if v_info else "Omen",
                "victim_team": v_info.team_id if v_info else "Blue",
                "round_time_sec": round(fb_time, 1),
                "timestamp_ms": fb_d.event_time_ms,
                "pos_x": fb_d.pos_x,
                "pos_y": fb_d.pos_y,
            }

        # Spike Plant & Defuse
        plant_event = next((e for e in events if e.event_type == "plant"), None)
        spike_planted = plant_event is not None
        plant_time_sec = ((plant_event.event_time_ms - start_time_ms) / 1000.0) if plant_event else None
        defuse_event = next((e for e in events if e.event_type == "defuse"), None)
        defused = defuse_event is not None

        # Round Winner Determination
        team_kills: dict[str, int] = {}
        for k in kills:
            k_team = player_map.get(k.player_puuid or "", MatchPlayer("", "", "", "", "Blue", "")).team_id
            team_kills[k_team] = team_kills.get(k_team, 0) + 1

        for d in deaths:
            killer_id = d.metadata.get("killer_puuid") or d.metadata.get("killer")
            if killer_id and killer_id in player_map:
                k_team = player_map[killer_id].team_id
                team_kills[k_team] = team_kills.get(k_team, 0) + 1
            elif d.player_puuid and d.player_puuid in player_map:
                v_team = player_map[d.player_puuid].team_id
                opp_team = "Red" if v_team == "Blue" else "Blue"
                team_kills[opp_team] = team_kills.get(opp_team, 0) + 1

        if defused:
            winning_team = "Blue" if side == "Attack" else "Red"
        elif spike_planted and not defused:
            winning_team = "Red" if side == "Attack" else "Blue"
        else:
            blue_kills = team_kills.get("Blue", 0)
            red_kills = team_kills.get("Red", 0)
            if blue_kills != red_kills:
                winning_team = "Blue" if blue_kills > red_kills else "Red"
            else:
                dead_puuids = {e.metadata.get("victim_puuid") for e in kills if e.metadata.get("victim_puuid")}
                dead_puuids.update({e.player_puuid for e in deaths if e.player_puuid})
                blue_alive = sum(1 for p in players if p.team_id == "Blue" and p.player_puuid not in dead_puuids)
                red_alive = sum(1 for p in players if p.team_id == "Red" and p.player_puuid not in dead_puuids)
                winning_team = "Blue" if blue_alive >= red_alive else "Red"

        round_won = (winning_team == user_team)


        # Trade metrics for this round
        trade_report = self.trade_engine.analyze(match_id, events=events, players=players)
        round_trades = [t for t in trade_report.trades if t.round_number == round_num]
        trades_landed = len([t for t in round_trades if t.trade_quality in ("instant", "clean", "delayed")])
        untraded_deaths = len([t for t in round_trades if t.trade_quality == "untraded"])

        # Utility metrics
        utility_events = self.repo.get_utility_events(match_id, round_number=round_num)
        util_used = len(utility_events)
        wasted_util = len([u for u in utility_events if u.wasted])
        avg_roi = (sum(u.roi_score for u in utility_events) / util_used) if util_used > 0 else 50.0

        # Economy heuristic
        credits_spent = 0
        if round_num in (1, 13):
            economy_tier = "eco"
            credits_spent = 800 * 5
        elif round_won and round_num in (2, 14):
            economy_tier = "force"
            credits_spent = 2100 * 5
        else:
            economy_tier = "full_buy" if util_used >= 3 or len(kills) >= 4 else "semi"
            credits_spent = 3900 * 5 if economy_tier == "full_buy" else 1900 * 5

        # Key events list formatted for timeline scrub
        key_events = []
        for e in events:
            rel_sec = max(0.0, (e.event_time_ms - start_time_ms) / 1000.0)
            if e.event_type == "kill":
                k_p = player_map.get(e.player_puuid or "")
                v_puuid = e.metadata.get("victim_puuid", "")
                v_p = player_map.get(v_puuid)
                key_events.append({
                    "round_time_sec": round(rel_sec, 1),
                    "event_type": "kill",
                    "killer": k_p.game_name if k_p else "Unknown",
                    "victim": v_p.game_name if v_p else "Unknown",
                    "team": k_p.team_id if k_p else "Blue",
                    "description": f"{k_p.game_name if k_p else 'Killer'} killed {v_p.game_name if v_p else 'Victim'}",
                })
            elif e.event_type == "plant":
                key_events.append({
                    "round_time_sec": round(rel_sec, 1),
                    "event_type": "plant",
                    "description": "Spike Planted",
                })
            elif e.event_type == "defuse":
                key_events.append({
                    "round_time_sec": round(rel_sec, 1),
                    "event_type": "defuse",
                    "description": "Spike Defused",
                })

        for u in utility_events:
            rel_sec = max(0.0, (u.timestamp_ms - start_time_ms) / 1000.0)
            key_events.append({
                "round_time_sec": round(rel_sec, 1),
                "event_type": "utility",
                "ability": u.ability_name,
                "agent": u.agent_name,
                "description": f"{u.agent_name} used {u.ability_name}",
            })

        key_events.sort(key=lambda k: k["round_time_sec"])

        # Win probability curve points relative to round start
        prob_points = []
        try:
            win_report = self.win_prob_engine.calculate_match_probability(match_id, events, players)
            r_points = [p for p in win_report.points if p.round_number == round_num]
            for p in r_points:
                rel_sec = max(0.0, (p.timestamp_ms - start_time_ms) / 1000.0)
                prob_points.append({
                    "time_sec": round(rel_sec, 1),
                    "user_win_prob": round(p.team_a_prob if user_team == "Blue" else p.team_b_prob, 3),
                    "description": p.description,
                })
        except Exception:
            prob_points = [
                {"time_sec": 0.0, "user_win_prob": 0.50, "description": "Round Start"},
                {"time_sec": round(duration_sec, 1), "user_win_prob": 1.0 if round_won else 0.0, "description": "Round End"},
            ]

        # Player spatial paths $(x, y, t)$
        player_paths: dict[str, list[dict[str, Any]]] = {}
        for ev in events:
            if ev.player_puuid and ev.pos_x is not None and ev.pos_y is not None:
                rel_sec = max(0.0, (ev.event_time_ms - start_time_ms) / 1000.0)
                player_paths.setdefault(ev.player_puuid, []).append({
                    "t": round(rel_sec, 1),
                    "x": round(ev.pos_x, 3),
                    "y": round(ev.pos_y, 3),
                    "type": ev.event_type,
                })

        return RoundSummary(
            round_number=round_num,
            won=round_won,
            winning_team=winning_team,
            user_team=user_team,
            side=side,
            duration_seconds=duration_sec,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            first_blood=first_blood,
            kills_count=len(kills),
            deaths_count=sum(1 for k in kills if player_map.get(k.metadata.get("victim_puuid", ""), MatchPlayer("", "", "", "", "", "")).team_id == user_team),
            economy_tier=economy_tier,
            credits_spent=credits_spent,
            utility_used=util_used,
            wasted_utility=wasted_util,
            utility_roi=avg_roi,
            untraded_deaths=untraded_deaths,
            trades_landed=trades_landed,
            spike_planted=spike_planted,
            plant_time_sec=plant_time_sec,
            defused=defused,
            win_probability_curve=prob_points,
            player_paths=player_paths,
            key_events=key_events,
        )

    def _generate_takeaways(
        self,
        ra: RoundSummary,
        rb: RoundSummary,
        deltas: dict[str, Any],
    ) -> list[str]:
        """Synthesize actionable tactical takeaways between Round A and Round B."""
        takeaways = []

        # 1. Round Outcome & Conversion
        outcome_a = "WON" if ra.won else "LOST"
        outcome_b = "WON" if rb.won else "LOST"
        takeaways.append(
            f"Round {ra.round_number} ({outcome_a}, {ra.economy_tier.upper()}) vs Round {rb.round_number} ({outcome_b}, {rb.economy_tier.upper()})."
        )

        # 2. First Blood opening duel impact
        if ra.first_blood and rb.first_blood:
            fb_a_sec = ra.first_blood["round_time_sec"]
            fb_b_sec = rb.first_blood["round_time_sec"]
            killer_a = ra.first_blood["killer_name"]
            killer_b = rb.first_blood["killer_name"]

            if fb_b_sec < fb_a_sec:
                takeaways.append(
                    f"Opening contact in Round {rb.round_number} occurred {fb_a_sec - fb_b_sec:.1f}s earlier ({killer_b} @ {fb_b_sec}s vs {killer_a} @ {fb_a_sec}s in R{ra.round_number})."
                )
            else:
                takeaways.append(
                    f"Round {rb.round_number} played a slower default; opening duel initiated at {fb_b_sec}s (+{fb_b_sec - fb_a_sec:.1f}s delay vs R{ra.round_number})."
                )

        # 3. Spacing & Trade Efficiency
        if ra.untraded_deaths > 0 and rb.untraded_deaths == 0:
            takeaways.append(
                f"Spacing discipline dramatically improved in Round {rb.round_number}: 0 untraded deaths compared to {ra.untraded_deaths} isolated losses in Round {ra.round_number}."
            )
        elif rb.trades_landed > ra.trades_landed:
            takeaways.append(
                f"Team trade conversion was higher in Round {rb.round_number} ({rb.trades_landed} trades secured vs {ra.trades_landed} in R{ra.round_number})."
            )

        # 4. Utility Efficiency
        if rb.utility_roi > ra.utility_roi + 5.0:
            takeaways.append(
                f"Utility deployment ROI was superior in Round {rb.round_number} ({rb.utility_roi:.1f} vs {ra.utility_roi:.1f}), with only {rb.wasted_utility} wasted abilities."
            )
        elif ra.wasted_utility > rb.wasted_utility:
            takeaways.append(
                f"Reduced ability waste in Round {rb.round_number}: {rb.wasted_utility} wasted casts vs {ra.wasted_utility} in Round {ra.round_number}."
            )

        # 5. Site Execution & Objective
        if rb.spike_planted and not ra.spike_planted:
            takeaways.append(
                f"Round {rb.round_number} achieved a successful site plant at {rb.plant_time_sec or 0:.1f}s, whereas Round {ra.round_number} stalled before planting."
            )
        elif ra.spike_planted and rb.spike_planted and ra.plant_time_sec and rb.plant_time_sec:
            takeaways.append(
                f"Spike plant was executed at {rb.plant_time_sec:.1f}s in Round {rb.round_number} vs {ra.plant_time_sec:.1f}s in Round {ra.round_number}."
            )

        return takeaways
