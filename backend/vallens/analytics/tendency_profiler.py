"""Opponent Tendency & Default Timing Profiler for post-game tactical counter-stratting.

Analyzes offline match telemetry across rounds to quantify enemy habits:
1. Default Pace & Attack Execution Archetypes (Blitz Rush vs Standard Default vs Late Bleed).
2. Site Preference & Winrate Distribution (A vs B vs C vs Mid).
3. Rotation Latency & Anchor Discipline (Hyper-Rotators vs Disciplined Anchors).
4. Defense Chokehold Aggression Index (Early forward pushes per player/agent).
5. Actionable Counter-Strat Takeaways & Exploit Recommendations.

Strictly 100% post-game offline telemetry only (zero game memory hooks, 100% Vanguard compliant).
"""

from dataclasses import dataclass, field
import logging
import math
from typing import Any, Optional

from vallens.analytics.heatmap import HeatmapAggregationEngine
from vallens.db.repository import MatchRepository
from vallens.models import MatchEvent, MatchPlayer

logger = logging.getLogger(__name__)


@dataclass
class PaceBucket:
    """Statistics for a specific round pacing archetype."""
    name: str              # "Blitz Rush", "Standard Default", "Late-Round Execute"
    tag: str               # "blitz", "default", "late"
    count: int
    percentage: float      # 0.0 to 100.0
    win_rate: float        # 0.0 to 100.0
    avg_contact_sec: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tag": self.tag,
            "count": self.count,
            "percentage": round(self.percentage, 1),
            "win_rate": round(self.win_rate, 1),
            "avg_contact_sec": round(self.avg_contact_sec, 1),
        }


@dataclass
class SiteExecutionStat:
    """Statistics for execution frequency and success on a specific bomb site."""
    site: str              # "A Site", "B Site", "C Site", "Mid"
    attempts: int
    percentage: float      # 0.0 to 100.0
    round_wins: int
    win_rate: float        # 0.0 to 100.0
    avg_hit_time_sec: float
    first_blood_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "site": self.site,
            "attempts": self.attempts,
            "percentage": round(self.percentage, 1),
            "round_wins": self.round_wins,
            "win_rate": round(self.win_rate, 1),
            "avg_hit_time_sec": round(self.avg_hit_time_sec, 1),
            "first_blood_rate": round(self.first_blood_rate, 1),
        }


@dataclass
class RotationProfile:
    """Quantifies defense rotation latency and anchor discipline."""
    avg_rotation_latency_sec: float
    fast_rotation_pct: float     # % of rotations under 3.5 seconds
    classification: str          # "Hyper-Rotator", "Disciplined Anchor", "Balanced / Reactive"
    summary: str
    exploit_advice: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "avg_rotation_latency_sec": round(self.avg_rotation_latency_sec, 1),
            "fast_rotation_pct": round(self.fast_rotation_pct, 1),
            "classification": self.classification,
            "summary": self.summary,
            "exploit_advice": self.exploit_advice,
        }


@dataclass
class AggressionProfile:
    """Defense early forward push habits and chokehold aggression."""
    team_aggression_rate: float  # % of defense rounds with early push (<15s)
    early_push_rounds: int
    defense_rounds_total: int
    primary_choke_targets: list[str]
    aggressive_players: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_aggression_rate": round(self.team_aggression_rate, 1),
            "early_push_rounds": self.early_push_rounds,
            "defense_rounds_total": self.defense_rounds_total,
            "primary_choke_targets": self.primary_choke_targets,
            "aggressive_players": self.aggressive_players,
        }


@dataclass
class EntryDuelStat:
    """Opening duel profile for opponent entry players."""
    player_puuid: str
    player_name: str
    agent_name: str
    team_id: str
    first_duels_count: int
    first_kills_count: int
    first_deaths_count: int
    entry_attempt_rate: float
    entry_success_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_puuid": self.player_puuid,
            "player_name": self.player_name,
            "agent_name": self.agent_name,
            "team_id": self.team_id,
            "first_duels_count": self.first_duels_count,
            "first_kills_count": self.first_kills_count,
            "first_deaths_count": self.first_deaths_count,
            "entry_attempt_rate": round(self.entry_attempt_rate, 1),
            "entry_success_rate": round(self.entry_success_rate, 1),
        }


@dataclass
class OpponentTendencyReport:
    """Consolidated post-game tendency profile and counter-strat dossier."""
    match_id: str
    map_name: str
    target_team: str
    opponent_players: list[dict[str, str]]
    rounds_analyzed: int
    attack_rounds: int
    defense_rounds: int
    pace_breakdown: list[PaceBucket]
    predominant_pace: str
    site_preferences: list[SiteExecutionStat]
    primary_site_target: str
    rotation_profile: RotationProfile
    aggression_profile: AggressionProfile
    top_entries: list[EntryDuelStat]
    counter_strats: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "map_name": self.map_name,
            "target_team": self.target_team,
            "opponent_players": self.opponent_players,
            "rounds_analyzed": self.rounds_analyzed,
            "attack_rounds": self.attack_rounds,
            "defense_rounds": self.defense_rounds,
            "pace_breakdown": [p.to_dict() for p in self.pace_breakdown],
            "predominant_pace": self.predominant_pace,
            "site_preferences": [s.to_dict() for s in self.site_preferences],
            "primary_site_target": self.primary_site_target,
            "rotation_profile": self.rotation_profile.to_dict(),
            "aggression_profile": self.aggression_profile.to_dict(),
            "top_entries": [e.to_dict() for e in self.top_entries],
            "counter_strats": self.counter_strats,
        }


class TendencyProfilerEngine:
    """Post-match offline engine analyzing opponent habits, timings, and rotation patterns."""

    def __init__(
        self,
        repo: MatchRepository,
        heatmap_engine: Optional[HeatmapAggregationEngine] = None,
    ):
        self.repo = repo
        self.heatmap_engine = heatmap_engine or HeatmapAggregationEngine()

    def analyze_opponent_tendencies(
        self,
        match_id: str,
        target_team: Optional[str] = None,
        user_puuid: Optional[str] = None,
    ) -> OpponentTendencyReport:
        """Generates a complete post-match tendency profile for the opponent team."""
        match = self.repo.get_match(match_id)
        map_name = match.map_id if match else "Ascent"

        players = self.repo.get_match_players(match_id)
        player_map = {p.player_puuid: p for p in players}

        # Resolve target team (opposing team)
        resolved_target_team = self._resolve_target_team(players, target_team, user_puuid)

        # Get opponent players
        opp_players = [p for p in players if p.team_id == resolved_target_team]
        opp_puuids = {p.player_puuid for p in opp_players}

        # Retrieve all events for this match
        all_events = self.repo.get_events(match_id)
        
        # Group events by round
        rounds_dict: dict[int, list[MatchEvent]] = {}
        for ev in all_events:
            rounds_dict.setdefault(ev.round_number, []).append(ev)

        rounds_analyzed = len(rounds_dict)
        if rounds_analyzed == 0:
            return self._empty_report(match_id, map_name, resolved_target_team, opp_players)

        # Determine side (attack / defense) per round for target team
        attack_rounds: list[int] = []
        defense_rounds: list[int] = []
        for r_num, evs in sorted(rounds_dict.items()):
            side = self._determine_team_side(r_num, evs, resolved_target_team, opp_puuids)
            if side == "Attack":
                attack_rounds.append(r_num)
            else:
                defense_rounds.append(r_num)

        # 1. Pace Analysis (Attack rounds of opponent)
        pace_buckets, predominant_pace = self._analyze_pace(
            rounds_dict, attack_rounds, resolved_target_team, opp_puuids
        )

        # 2. Site Preferences (Attack rounds of opponent)
        site_stats, primary_site = self._analyze_site_preferences(
            map_name, rounds_dict, attack_rounds, resolved_target_team, opp_puuids
        )

        # 3. Rotation Latency & Anchor Discipline (Defense rounds of opponent)
        rotation_profile = self._analyze_rotation_latency(
            map_name, rounds_dict, defense_rounds, resolved_target_team, opp_puuids
        )

        # 4. Chokehold Early Aggression Index (Defense rounds of opponent)
        aggression_profile = self._analyze_early_aggression(
            map_name, rounds_dict, defense_rounds, opp_players, opp_puuids
        )

        # 5. Opening Duel / Entry Profiles
        top_entries = self._analyze_entries(rounds_dict, opp_players, opp_puuids)

        # 6. Synthesize Actionable Counter-Strats
        counter_strats = self._generate_counter_strats(
            predominant_pace=predominant_pace,
            pace_buckets=pace_buckets,
            site_stats=site_stats,
            primary_site=primary_site,
            rotation_profile=rotation_profile,
            aggression_profile=aggression_profile,
            top_entries=top_entries,
            map_name=map_name,
        )

        return OpponentTendencyReport(
            match_id=match_id,
            map_name=map_name,
            target_team=resolved_target_team,
            opponent_players=[
                {"puuid": p.player_puuid, "name": p.game_name, "agent": p.character_id}
                for p in opp_players
            ],
            rounds_analyzed=rounds_analyzed,
            attack_rounds=len(attack_rounds),
            defense_rounds=len(defense_rounds),
            pace_breakdown=pace_buckets,
            predominant_pace=predominant_pace,
            site_preferences=site_stats,
            primary_site_target=primary_site,
            rotation_profile=rotation_profile,
            aggression_profile=aggression_profile,
            top_entries=top_entries,
            counter_strats=counter_strats,
        )

    def _resolve_target_team(
        self,
        players: list[MatchPlayer],
        target_team: Optional[str],
        user_puuid: Optional[str],
    ) -> str:
        """Determines which team is considered the opponent."""
        if target_team:
            return target_team

        # If user_puuid provided, target is the opposite team
        if user_puuid:
            for p in players:
                if p.player_puuid == user_puuid:
                    return "Red" if p.team_id == "Blue" else "Blue"

        # Default fallback: If Team Red exists, target Red; else Blue
        teams = {p.team_id for p in players if p.team_id}
        if "Red" in teams and "Blue" in teams:
            return "Red"
        if len(teams) > 1:
            return list(teams)[1]
        return "Red"

    def _determine_team_side(
        self,
        round_number: int,
        events: list[MatchEvent],
        target_team: str,
        opp_puuids: set[str],
    ) -> str:
        """Identifies if target team was on Attack or Defense in this round."""
        # 1. Check spike plant: whoever plants is on Attack
        for ev in events:
            if ev.event_type == "plant":
                planter = ev.player_puuid or ev.metadata.get("planted_by")
                if planter in opp_puuids:
                    return "Attack"
                elif planter is not None:
                    return "Defense"

        # 2. Check standard half assignment:
        # Standard: Blue defends first 12 rounds, Red attacks (or vice versa).
        # We assume target_team "Red" attacks rounds 1-12, defends 13-24.
        # If target_team is "Blue", attacks rounds 13-24, defends 1-12.
        if target_team.lower() in ("red", "team_red"):
            return "Attack" if round_number <= 12 else "Defense"
        else:
            return "Defense" if round_number <= 12 else "Attack"

    def _analyze_pace(
        self,
        rounds_dict: dict[int, list[MatchEvent]],
        attack_rounds: list[int],
        target_team: str,
        opp_puuids: set[str],
    ) -> tuple[list[PaceBucket], str]:
        """Categorizes attack rounds into Blitz Rush, Standard Default, and Late Bleed."""
        if not attack_rounds:
            return [
                PaceBucket("Blitz Rush (<18s)", "blitz", 0, 0.0, 0.0, 0.0),
                PaceBucket("Standard Default (18-45s)", "default", 0, 0.0, 0.0, 0.0),
                PaceBucket("Late-Round Execute (>45s)", "late", 0, 0.0, 0.0, 0.0),
            ], "Unknown"

        blitz_times: list[float] = []
        default_times: list[float] = []
        late_times: list[float] = []

        blitz_wins = 0
        default_wins = 0
        late_wins = 0

        for r_num in attack_rounds:
            evs = sorted(rounds_dict.get(r_num, []), key=lambda x: x.event_time_ms)
            if not evs:
                continue

            r_start_ms = evs[0].event_time_ms
            for e in evs:
                if e.event_type == "round_start":
                    r_start_ms = e.event_time_ms
                    break

            # Find first decisive action by opponent (first kill, death, or plant)
            contact_sec = 25.0  # fallback default
            for e in evs:
                if e.event_type in ("kill", "death", "plant") and e.event_time_ms > r_start_ms:
                    contact_sec = max(1.0, (e.event_time_ms - r_start_ms) / 1000.0)
                    break

            # Check if target team won the round
            won = self._did_target_team_win(evs, target_team, opp_puuids)

            if contact_sec < 18.0:
                blitz_times.append(contact_sec)
                if won:
                    blitz_wins += 1
            elif contact_sec <= 45.0:
                default_times.append(contact_sec)
                if won:
                    default_wins += 1
            else:
                late_times.append(contact_sec)
                if won:
                    late_wins += 1

        total = len(attack_rounds)
        b_count = len(blitz_times)
        d_count = len(default_times)
        l_count = len(late_times)

        buckets = [
            PaceBucket(
                name="Blitz Rush (<18s)",
                tag="blitz",
                count=b_count,
                percentage=(b_count / total * 100.0) if total else 0.0,
                win_rate=(blitz_wins / b_count * 100.0) if b_count else 0.0,
                avg_contact_sec=(sum(blitz_times) / b_count) if b_count else 0.0,
            ),
            PaceBucket(
                name="Standard Default (18-45s)",
                tag="default",
                count=d_count,
                percentage=(d_count / total * 100.0) if total else 0.0,
                win_rate=(default_wins / d_count * 100.0) if d_count else 0.0,
                avg_contact_sec=(sum(default_times) / d_count) if d_count else 0.0,
            ),
            PaceBucket(
                name="Late-Round Execute (>45s)",
                tag="late",
                count=l_count,
                percentage=(l_count / total * 100.0) if total else 0.0,
                win_rate=(late_wins / l_count * 100.0) if l_count else 0.0,
                avg_contact_sec=(sum(late_times) / l_count) if l_count else 0.0,
            ),
        ]

        # Determine predominant pace
        max_b = max(buckets, key=lambda b: b.count)
        predominant = max_b.name if max_b.count > 0 else "Balanced Attack"

        return buckets, predominant

    def _analyze_site_preferences(
        self,
        map_name: str,
        rounds_dict: dict[int, list[MatchEvent]],
        attack_rounds: list[int],
        target_team: str,
        opp_puuids: set[str],
    ) -> tuple[list[SiteExecutionStat], str]:
        """Calculates hit frequency, plant location preference, and win rates per bomb site."""
        site_data: dict[str, dict[str, Any]] = {
            "A Site": {"attempts": 0, "wins": 0, "hit_times": [], "fb_count": 0},
            "B Site": {"attempts": 0, "wins": 0, "hit_times": [], "fb_count": 0},
            "Mid / Split": {"attempts": 0, "wins": 0, "hit_times": [], "fb_count": 0},
        }
        # For Haven or Lotus, support C Site
        if any(m in map_name.lower() for m in ("haven", "lotus")):
            site_data["C Site"] = {"attempts": 0, "wins": 0, "hit_times": [], "fb_count": 0}

        for r_num in attack_rounds:
            evs = sorted(rounds_dict.get(r_num, []), key=lambda x: x.event_time_ms)
            if not evs:
                continue

            r_start_ms = evs[0].event_time_ms
            for e in evs:
                if e.event_type == "round_start":
                    r_start_ms = e.event_time_ms
                    break

            # Identify target site from plant or first kill
            chosen_site = "Mid / Split"
            hit_time_sec = 30.0
            had_fb = False

            # Check plant event first
            plant_ev = next((e for e in evs if e.event_type == "plant"), None)
            if plant_ev and plant_ev.pos_x is not None and plant_ev.pos_y is not None:
                callout, super_r = self.heatmap_engine.find_nearest_callout(
                    map_name, plant_ev.pos_x, plant_ev.pos_y
                )
                chosen_site = self._normalize_site_label(super_r, callout, plant_ev.pos_x)
                hit_time_sec = max(1.0, (plant_ev.event_time_ms - r_start_ms) / 1000.0)
            else:
                # Infer from first kill/death event
                first_combat = next(
                    (e for e in evs if e.event_type in ("kill", "death") and e.pos_x is not None),
                    None,
                )
                if first_combat and first_combat.pos_x is not None and first_combat.pos_y is not None:
                    callout, super_r = self.heatmap_engine.find_nearest_callout(
                        map_name, first_combat.pos_x, first_combat.pos_y
                    )
                    chosen_site = self._normalize_site_label(super_r, callout, first_combat.pos_x)
                    hit_time_sec = max(1.0, (first_combat.event_time_ms - r_start_ms) / 1000.0)
                    if (first_combat.player_puuid in opp_puuids) or (
                        first_combat.metadata.get("killer_puuid") in opp_puuids
                    ):
                        had_fb = True

            if chosen_site not in site_data:
                chosen_site = "A Site" if "A" in chosen_site else ("B Site" if "B" in chosen_site else "Mid / Split")

            won = self._did_target_team_win(evs, target_team, opp_puuids)
            site_data[chosen_site]["attempts"] += 1
            if won:
                site_data[chosen_site]["wins"] += 1
            site_data[chosen_site]["hit_times"].append(hit_time_sec)
            if had_fb:
                site_data[chosen_site]["fb_count"] += 1

        total_attempts = len(attack_rounds)
        stats: list[SiteExecutionStat] = []
        for site_name, d in site_data.items():
            att = d["attempts"]
            pct = (att / total_attempts * 100.0) if total_attempts else 0.0
            wr = (d["wins"] / att * 100.0) if att else 0.0
            avg_time = (sum(d["hit_times"]) / att) if att else 0.0
            fb_rate = (d["fb_count"] / att * 100.0) if att else 0.0
            stats.append(
                SiteExecutionStat(
                    site=site_name,
                    attempts=att,
                    percentage=pct,
                    round_wins=d["wins"],
                    win_rate=wr,
                    avg_hit_time_sec=avg_time,
                    first_blood_rate=fb_rate,
                )
            )

        # Sort by most attempted
        stats.sort(key=lambda s: s.attempts, reverse=True)
        primary = stats[0].site if (stats and stats[0].attempts > 0) else "Flexible"

        return stats, primary

    def _normalize_site_label(self, super_region: str, callout: str, norm_x: float) -> str:
        """Normalizes region text into standard site bucket."""
        sr = super_region.strip().upper()
        if sr == "A":
            return "A Site"
        if sr == "B":
            return "B Site"
        if sr == "C":
            return "C Site"
        if sr in ("MID", "MIDDLE"):
            return "Mid / Split"

        text = f"{super_region} {callout}".lower()
        if "c site" in text or "site c" in text or " c " in f" {text} ":
            return "C Site"
        if "a site" in text or "site a" in text or " a " in f" {text} ":
            return "A Site"
        if "b site" in text or "site b" in text or " b " in f" {text} ":
            return "B Site"
        return "Mid / Split"

    def _analyze_rotation_latency(
        self,
        map_name: str,
        rounds_dict: dict[int, list[MatchEvent]],
        defense_rounds: list[int],
        target_team: str,
        opp_puuids: set[str],
    ) -> RotationProfile:
        """Measures defense rotation latency on spike tap or opposite site contact."""
        if not defense_rounds:
            return RotationProfile(
                avg_rotation_latency_sec=4.5,
                fast_rotation_pct=0.0,
                classification="Balanced / Reactive",
                summary="Insufficient defense telemetry rounds recorded.",
                exploit_advice="Run standard defaults to test defender reaction speed.",
            )

        latencies: list[float] = []

        for r_num in defense_rounds:
            evs = sorted(rounds_dict.get(r_num, []), key=lambda x: x.event_time_ms)
            if not evs:
                continue

            # Check if there is an opening site contact or spike plant by attacking team
            plant_or_first_combat = next(
                (e for e in evs if e.event_type in ("plant", "kill", "death")),
                None,
            )
            if not plant_or_first_combat:
                continue

            t_trigger = plant_or_first_combat.event_time_ms

            # Find subsequent action by opponent defenders on the other site
            reaction_ev = next(
                (
                    e
                    for e in evs
                    if e.event_time_ms > t_trigger
                    and (
                        e.player_puuid in opp_puuids
                        or e.metadata.get("killer_puuid") in opp_puuids
                    )
                ),
                None,
            )

            if reaction_ev:
                dt_sec = (reaction_ev.event_time_ms - t_trigger) / 1000.0
                if 0.5 <= dt_sec <= 20.0:
                    latencies.append(dt_sec)
            else:
                # Default baseline approximation
                latencies.append(4.2)

        avg_latency = (sum(latencies) / len(latencies)) if latencies else 4.0
        fast_count = sum(1 for dt in latencies if dt < 3.5)
        fast_pct = (fast_count / len(latencies) * 100.0) if latencies else 0.0

        if avg_latency < 3.2 or fast_pct >= 50.0:
            classification = "Hyper-Rotator"
            summary = (
                f"Opponent defense over-rotates rapidly (Avg latency {avg_latency:.1f}s, "
                f"{fast_pct:.0f}% fast rotations). Anchors abandon opposite sites on first audio contact."
            )
            exploit_advice = (
                "Execute loud decoy utility on one site (e.g. 1-man flash & smoke), wait 4 seconds "
                "for anchors to abandon post, then slip into the deserted opposite site uncontested."
            )
        elif avg_latency >= 5.5:
            classification = "Disciplined Anchor"
            summary = (
                f"Opponent plays patient, disciplined site anchors (Avg latency {avg_latency:.1f}s). "
                "Defenders hold site crossfires until visual confirmation or spike plant."
            )
            exploit_advice = (
                "Do not waste utility on sound fakes. Execute full 5-man site hits with overwhelming "
                "utility isolation to overwhelm lone anchors before late rotations can arrive."
            )
        else:
            classification = "Balanced / Reactive"
            summary = (
                f"Opponent displays measured rotation latency ({avg_latency:.1f}s average). "
                "Rotations are timed reasonably to utility confirmation."
            )
            exploit_advice = (
                "Work mid-map control to cut off rotation corridors (e.g. Ascent Market / Tree) "
                "to catch rotating defenders during transit."
            )

        return RotationProfile(
            avg_rotation_latency_sec=avg_latency,
            fast_rotation_pct=fast_pct,
            classification=classification,
            summary=summary,
            exploit_advice=exploit_advice,
        )

    def _analyze_early_aggression(
        self,
        map_name: str,
        rounds_dict: dict[int, list[MatchEvent]],
        defense_rounds: list[int],
        opp_players: list[MatchPlayer],
        opp_puuids: set[str],
    ) -> AggressionProfile:
        """Detects early forward pushes and chokehold aggression in defense rounds."""
        if not defense_rounds:
            return AggressionProfile(
                team_aggression_rate=0.0,
                early_push_rounds=0,
                defense_rounds_total=0,
                primary_choke_targets=[],
                aggressive_players=[],
            )

        player_push_counts: dict[str, int] = {p.player_puuid: 0 for p in opp_players}
        player_push_zones: dict[str, list[str]] = {p.player_puuid: [] for p in opp_players}
        early_push_rounds = 0
        all_choke_targets: list[str] = []

        for r_num in defense_rounds:
            evs = sorted(rounds_dict.get(r_num, []), key=lambda x: x.event_time_ms)
            if not evs:
                continue

            r_start_ms = evs[0].event_time_ms
            for e in evs:
                if e.event_type == "round_start":
                    r_start_ms = e.event_time_ms
                    break

            round_had_push = False
            # Check early events (< 14 seconds into round)
            for e in evs:
                delta_sec = (e.event_time_ms - r_start_ms) / 1000.0
                if 0.5 <= delta_sec <= 14.0:
                    killer = e.metadata.get("killer_puuid")
                    actor = e.player_puuid or killer

                    if actor in opp_puuids:
                        round_had_push = True
                        player_push_counts[actor] = player_push_counts.get(actor, 0) + 1

                        zone = "Chokehold"
                        if e.pos_x is not None and e.pos_y is not None:
                            callout, _ = self.heatmap_engine.find_nearest_callout(
                                map_name, e.pos_x, e.pos_y
                            )
                            zone = callout
                        player_push_zones.setdefault(actor, []).append(zone)
                        all_choke_targets.append(zone)
                        break

            if round_had_push:
                early_push_rounds += 1

        total_def = len(defense_rounds)
        aggression_rate = (early_push_rounds / total_def * 100.0) if total_def else 0.0

        # Construct player profiles
        p_list = []
        for p in opp_players:
            cnt = player_push_counts.get(p.player_puuid, 0)
            if cnt > 0:
                zones = player_push_zones.get(p.player_puuid, [])
                top_zone = max(set(zones), key=zones.count) if zones else "Main Choke"
                p_list.append(
                    {
                        "puuid": p.player_puuid,
                        "name": p.game_name,
                        "agent": p.character_id,
                        "push_count": cnt,
                        "push_rate": round(cnt / total_def * 100.0, 1) if total_def else 0.0,
                        "primary_choke": top_zone,
                    }
                )

        p_list.sort(key=lambda x: x["push_count"], reverse=True)

        # Most targeted choke points
        top_chokes = []
        if all_choke_targets:
            from collections import Counter
            top_chokes = [item for item, _ in Counter(all_choke_targets).most_common(3)]

        return AggressionProfile(
            team_aggression_rate=aggression_rate,
            early_push_rounds=early_push_rounds,
            defense_rounds_total=total_def,
            primary_choke_targets=top_chokes,
            aggressive_players=p_list,
        )

    def _analyze_entries(
        self,
        rounds_dict: dict[int, list[MatchEvent]],
        opp_players: list[MatchPlayer],
        opp_puuids: set[str],
    ) -> list[EntryDuelStat]:
        """Identifies opponent first contact entry players and duel rates."""
        first_duels: dict[str, int] = {p.player_puuid: 0 for p in opp_players}
        first_kills: dict[str, int] = {p.player_puuid: 0 for p in opp_players}
        first_deaths: dict[str, int] = {p.player_puuid: 0 for p in opp_players}

        total_rounds = len(rounds_dict)

        for r_num, evs in rounds_dict.items():
            sorted_evs = sorted(evs, key=lambda x: x.event_time_ms)
            # Find first kill / death
            fb = next((e for e in sorted_evs if e.event_type in ("kill", "death")), None)
            if not fb:
                continue

            killer = fb.metadata.get("killer_puuid") or (fb.player_puuid if fb.event_type == "kill" else None)
            victim = fb.metadata.get("victim_puuid") or (fb.player_puuid if fb.event_type == "death" else None)

            if killer in opp_puuids:
                first_duels[killer] = first_duels.get(killer, 0) + 1
                first_kills[killer] = first_kills.get(killer, 0) + 1
            if victim in opp_puuids:
                first_duels[victim] = first_duels.get(victim, 0) + 1
                first_deaths[victim] = first_deaths.get(victim, 0) + 1

        entries: list[EntryDuelStat] = []
        for p in opp_players:
            d_cnt = first_duels.get(p.player_puuid, 0)
            k_cnt = first_kills.get(p.player_puuid, 0)
            deaths_cnt = first_deaths.get(p.player_puuid, 0)

            att_rate = (d_cnt / total_rounds * 100.0) if total_rounds else 0.0
            succ_rate = (k_cnt / d_cnt * 100.0) if d_cnt else 0.0

            entries.append(
                EntryDuelStat(
                    player_puuid=p.player_puuid,
                    player_name=p.game_name,
                    agent_name=p.character_id,
                    team_id=p.team_id,
                    first_duels_count=d_cnt,
                    first_kills_count=k_cnt,
                    first_deaths_count=deaths_cnt,
                    entry_attempt_rate=att_rate,
                    entry_success_rate=succ_rate,
                )
            )

        entries.sort(key=lambda e: (e.first_duels_count, e.first_kills_count), reverse=True)
        return entries

    def _generate_counter_strats(
        self,
        predominant_pace: str,
        pace_buckets: list[PaceBucket],
        site_stats: list[SiteExecutionStat],
        primary_site: str,
        rotation_profile: RotationProfile,
        aggression_profile: AggressionProfile,
        top_entries: list[EntryDuelStat],
        map_name: str,
    ) -> list[str]:
        """Synthesizes high-priority tactical counter-strat recommendations."""
        strats: list[str] = []

        # 1. Pacing Counter
        blitz_b = next((b for b in pace_buckets if b.tag == "blitz"), None)
        late_b = next((b for b in pace_buckets if b.tag == "late"), None)

        if blitz_b and blitz_b.percentage >= 45.0:
            strats.append(
                f"🚨 Fast Execute Defense: Opponent rushes within 18s in {blitz_b.percentage:.0f}% of attack rounds. "
                "Deploy heavy delay utility (mollies, cypher cages, slows) at barrier drop rather than saving for retake."
            )
        elif late_b and late_b.percentage >= 40.0:
            strats.append(
                f"⏳ Slow Default Counter: Opponent bleeds the clock in {late_b.percentage:.0f}% of attack rounds. "
                "Do not over-peek or burn smokes early; hold discipline and reserve recon/smoke utility for the final 30 seconds."
            )
        else:
            strats.append(
                "⚖️ Standard Default Adaptation: Opponent attacks with measured pacing. "
                "Contest mid-corridors early for informational denial, then hold site anchors."
            )

        # 2. Site Bias Counter
        if site_stats and site_stats[0].attempts >= 2 and site_stats[0].percentage >= 50.0:
            primary = site_stats[0]
            strats.append(
                f"📍 Site Heavy Bias: Opponent attacks {primary.site} in {primary.percentage:.0f}% of attack rounds "
                f"({primary.win_rate:.0f}% winrate). Pre-allocate a 3-man defense stack or set up aggressive forward info traps."
            )

        # 3. Rotation Exploit
        if rotation_profile.classification == "Hyper-Rotator":
            strats.append(
                f"🎭 Exploit Over-Rotations: Opponent rotates off-site in {rotation_profile.avg_rotation_latency_sec:.1f}s. "
                "Run a 1-man audio decoy on the off-site, wait 4 seconds for anchors to vacate, then walk into the target site."
            )
        elif rotation_profile.classification == "Disciplined Anchor":
            strats.append(
                f"🛡️ Hard Anchor Lockdown: Opponent anchors hold position for {rotation_profile.avg_rotation_latency_sec:.1f}s. "
                "Sound fakes will fail. Commit to full 5-man utility floods to overwhelm lone site defenders before rotations arrive."
            )

        # 4. Aggressive Push Counter
        if aggression_profile.team_aggression_rate >= 40.0 and aggression_profile.aggressive_players:
            top_pusher = aggression_profile.aggressive_players[0]
            strats.append(
                f"⚠️ Punish Defense Over-Extension: Opponent defense pushes forward in {aggression_profile.team_aggression_rate:.0f}% of rounds. "
                f"{top_pusher['name']} ({top_pusher['agent']}) frequently pushes {top_pusher['primary_choke']}. "
                "Hold passive pre-aim crossfires from spawn for the first 12 seconds to collect free opening numbers."
            )

        # 5. Entry Neutralization
        if top_entries and top_entries[0].first_duels_count >= 2:
            star_entry = top_entries[0]
            strats.append(
                f"🎯 Neutralize Primary Entry: {star_entry.player_name} ({star_entry.agent_name}) accounts for "
                f"{star_entry.entry_attempt_rate:.0f}% of opening duels ({star_entry.entry_success_rate:.0f}% winrate). "
                "Use early flashes or shock darts at barrier drop to deny their initial peek angle."
            )

        return strats

    def _did_target_team_win(
        self,
        events: list[MatchEvent],
        target_team: str,
        opp_puuids: set[str],
    ) -> bool:
        """Determines if target team won the specified round."""
        # Check round_end or death counts
        all_deaths = [e for e in events if e.event_type == "death"]
        opp_deaths = [d for d in all_deaths if d.player_puuid in opp_puuids]
        other_deaths = [d for d in all_deaths if d.player_puuid not in opp_puuids]

        if other_deaths and len(other_deaths) >= len(opp_deaths):
            return True
        return False

    def _empty_report(
        self, match_id: str, map_name: str, target_team: str, opp_players: list[MatchPlayer]
    ) -> OpponentTendencyReport:
        """Returns a blank tendency report when no round data exists."""
        return OpponentTendencyReport(
            match_id=match_id,
            map_name=map_name,
            target_team=target_team,
            opponent_players=[
                {"puuid": p.player_puuid, "name": p.game_name, "agent": p.character_id}
                for p in opp_players
            ],
            rounds_analyzed=0,
            attack_rounds=0,
            defense_rounds=0,
            pace_breakdown=[],
            predominant_pace="Unknown",
            site_preferences=[],
            primary_site_target="Unknown",
            rotation_profile=RotationProfile(0.0, 0.0, "Unknown", "No data", "No data"),
            aggression_profile=AggressionProfile(0.0, 0, 0, [], []),
            top_entries=[],
            counter_strats=["No match events recorded to evaluate tendencies."],
        )
