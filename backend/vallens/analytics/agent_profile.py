"""Agent profiling matrix and role performance analytics."""

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Optional

from vallens.analytics.correlations import FlawCorrelationEngine
from vallens.db.database import Database
from vallens.db.repository import MatchRepository
from vallens.models import VodTag

AGENTS_DATA_PATH = Path(__file__).parent.parent.parent.parent / "data" / "agents.json"


@dataclass
class AgentProfile:
    """Consolidated performance profile for a specific agent in player's pool."""
    character_id: str
    agent_name: str
    role: str  # Duelist, Initiator, Controller, Sentinel
    display_icon: Optional[str]
    role_icon: Optional[str]
    matches_played: int
    rounds_played: int
    kills: int
    deaths: int
    assists: int
    kd_ratio: float
    first_bloods: int
    first_deaths: int
    opening_duel_win_rate: float
    first_death_rate: float
    trade_rate: float
    traded_deaths: int
    untraded_deaths: int
    flaw_tags_count: int
    top_flaws: list[dict[str, Any]]
    flaw_rate_per_round: float
    role_benchmarks: dict[str, Any]
    diagnosis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "character_id": self.character_id,
            "agent_name": self.agent_name,
            "role": self.role,
            "display_icon": self.display_icon,
            "role_icon": self.role_icon,
            "matches_played": self.matches_played,
            "rounds_played": self.rounds_played,
            "kills": self.kills,
            "deaths": self.deaths,
            "assists": self.assists,
            "kd_ratio": round(self.kd_ratio, 2),
            "first_bloods": self.first_bloods,
            "first_deaths": self.first_deaths,
            "opening_duel_win_rate": round(self.opening_duel_win_rate, 1),
            "first_death_rate": round(self.first_death_rate, 1),
            "trade_rate": round(self.trade_rate, 1),
            "traded_deaths": self.traded_deaths,
            "untraded_deaths": self.untraded_deaths,
            "flaw_tags_count": self.flaw_tags_count,
            "top_flaws": self.top_flaws,
            "flaw_rate_per_round": round(self.flaw_rate_per_round, 2),
            "role_benchmarks": self.role_benchmarks,
            "diagnosis": self.diagnosis,
        }


@dataclass
class AgentMatrixResult:
    """Consolidated player agent matrix across all competitive matches."""
    player_puuid: str
    player_name: str
    total_matches: int
    total_rounds: int
    agents: list[AgentProfile]
    role_breakdown: dict[str, dict[str, Any]]
    summary_insights: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_puuid": self.player_puuid,
            "player_name": self.player_name,
            "total_matches": self.total_matches,
            "total_rounds": self.total_rounds,
            "agents": [a.to_dict() for a in self.agents],
            "role_breakdown": self.role_breakdown,
            "summary_insights": self.summary_insights,
        }


class AgentProfilingEngine:
    """Computes cross-agent matrices, opening duel win rates, and utility flaw ratios."""

    def __init__(
        self,
        repo: MatchRepository,
        agents_file: Optional[Path | str] = None,
        correlation_engine: Optional[FlawCorrelationEngine] = None,
    ):
        self.repo = repo
        self.agents_file = Path(agents_file) if agents_file else AGENTS_DATA_PATH
        self.correlation_engine = correlation_engine or FlawCorrelationEngine()
        self.agent_catalog: dict[str, dict[str, Any]] = {}
        self._load_agent_catalog()

    def _load_agent_catalog(self) -> None:
        """Load agent UUID mappings from data/agents.json."""
        if not self.agents_file.exists():
            return
        try:
            with open(self.agents_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                self.agent_catalog[k.lower()] = v
                self.agent_catalog[v.get("displayName", "").lower()] = v
        except Exception:
            pass

    def resolve_agent(self, character_id_or_name: str) -> dict[str, Any]:
        """Resolve agent metadata by UUID or display name."""
        key = character_id_or_name.strip().lower()
        if key in self.agent_catalog:
            return self.agent_catalog[key]

        return {
            "uuid": character_id_or_name,
            "displayName": character_id_or_name[:8].capitalize() if character_id_or_name else "Unknown",
            "role": "Specialist",
            "displayIcon": None,
            "roleIcon": None,
        }

    def generate_matrix(self, player_puuid: Optional[str] = None) -> AgentMatrixResult:
        """Calculate complete agent matrix and role breakdown for player."""
        # 1. Fetch player records
        player_matches = self.repo.get_player_agent_matches(player_puuid)

        # If no player PUUID specified, pick the most frequent player PUUID
        target_puuid = player_puuid
        player_name = "Player"
        if not target_puuid and player_matches:
            # Count occurrences of PUUIDs
            puuid_counts: dict[str, int] = {}
            for pm in player_matches:
                p = pm["player_puuid"]
                puuid_counts[p] = puuid_counts.get(p, 0) + 1
            target_puuid = max(puuid_counts.keys(), key=lambda k: puuid_counts[k])
            player_matches = [pm for pm in player_matches if pm["player_puuid"] == target_puuid]

        if player_matches:
            player_name = player_matches[0].get("game_name") or "Player"

        # Group matches by character_id
        grouped: dict[str, list[dict[str, Any]]] = {}
        for pm in player_matches:
            cid = (pm.get("character_id") or "unknown").lower()
            if cid not in grouped:
                grouped[cid] = []
            grouped[cid].append(pm)

        agent_profiles: list[AgentProfile] = []
        total_matches = len(player_matches)
        total_rounds = sum(pm.get("rounds_played", 0) for pm in player_matches)

        for cid, matches in grouped.items():
            meta = self.resolve_agent(cid)
            agent_name = meta.get("displayName", "Unknown")
            role = meta.get("role", "Specialist")

            m_count = len(matches)
            r_count = sum(m.get("rounds_played", 0) for m in matches)
            kills = sum(m.get("kills", 0) for m in matches)
            deaths = sum(m.get("deaths", 0) for m in matches)
            assists = sum(m.get("assists", 0) for m in matches)
            kd = kills / max(1, deaths)

            # Analyze Openings & Trades across these matches
            first_bloods = 0
            first_deaths = 0
            traded_deaths = 0
            untraded_deaths = 0

            match_ids = [m["match_id"] for m in matches]
            all_tags: list[VodTag] = []

            for mid in match_ids:
                events = self.repo.get_events(mid)
                tags = self.repo.get_tags(mid)
                all_tags.extend(tags)

                openings = self.correlation_engine.analyze_openings(events)
                for op in openings.values():
                    if op.first_blood_puuid == target_puuid:
                        first_bloods += 1
                    if op.first_death_puuid == target_puuid:
                        first_deaths += 1

                trades = self.correlation_engine.analyze_trades(events)
                for tr in trades:
                    if tr.victim_puuid == target_puuid:
                        if tr.is_traded:
                            traded_deaths += 1
                        else:
                            untraded_deaths += 1

            total_openings = first_bloods + first_deaths
            od_win_rate = (first_bloods / max(1, total_openings)) * 100 if total_openings > 0 else 0.0
            fd_rate = (first_deaths / max(1, r_count)) * 100 if r_count > 0 else 0.0
            trade_rate = (traded_deaths / max(1, deaths)) * 100 if deaths > 0 else 0.0

            # Tag Flaw Distribution for this agent
            tag_counts: dict[str, int] = {}
            for t in all_tags:
                tag_counts[t.tag_name] = tag_counts.get(t.tag_name, 0) + 1

            top_flaws = [
                {"name": name, "count": cnt, "percentage": round((cnt / max(1, len(all_tags))) * 100, 1)}
                for name, cnt in sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
            ]

            flaw_rate_per_round = len(all_tags) / max(1, r_count)

            # Role benchmarks & diagnosis
            benchmarks, diagnosis = self._evaluate_role(
                role=role,
                agent_name=agent_name,
                od_win_rate=od_win_rate,
                fd_rate=fd_rate,
                trade_rate=trade_rate,
                top_flaws=top_flaws,
                r_count=r_count,
            )

            agent_profiles.append(
                AgentProfile(
                    character_id=cid,
                    agent_name=agent_name,
                    role=role,
                    display_icon=meta.get("displayIcon"),
                    role_icon=meta.get("roleIcon"),
                    matches_played=m_count,
                    rounds_played=r_count,
                    kills=kills,
                    deaths=deaths,
                    assists=assists,
                    kd_ratio=kd,
                    first_bloods=first_bloods,
                    first_deaths=first_deaths,
                    opening_duel_win_rate=od_win_rate,
                    first_death_rate=fd_rate,
                    trade_rate=trade_rate,
                    traded_deaths=traded_deaths,
                    untraded_deaths=untraded_deaths,
                    flaw_tags_count=len(all_tags),
                    top_flaws=top_flaws[:4],
                    flaw_rate_per_round=flaw_rate_per_round,
                    role_benchmarks=benchmarks,
                    diagnosis=diagnosis,
                )
            )

        # Sort agents by matches played descending
        agent_profiles.sort(key=lambda a: a.matches_played, reverse=True)

        # Macro Role Breakdown
        role_breakdown: dict[str, dict[str, Any]] = {}
        for ap in agent_profiles:
            r = ap.role
            if r not in role_breakdown:
                role_breakdown[r] = {
                    "role": r,
                    "matches": 0,
                    "kills": 0,
                    "deaths": 0,
                    "kd": 0.0,
                    "opening_win_rate": 0.0,
                    "agents_count": 0,
                }
            rb = role_breakdown[r]
            rb["matches"] += ap.matches_played
            rb["kills"] += ap.kills
            rb["deaths"] += ap.deaths
            rb["agents_count"] += 1
            rb["kd"] = round(rb["kills"] / max(1, rb["deaths"]), 2)

        # Overall Summary Insights
        summary_insights = self._build_macro_insights(agent_profiles)

        return AgentMatrixResult(
            player_puuid=target_puuid or "unknown",
            player_name=player_name,
            total_matches=total_matches,
            total_rounds=total_rounds,
            agents=agent_profiles,
            role_breakdown=role_breakdown,
            summary_insights=summary_insights,
        )

    def _evaluate_role(
        self,
        role: str,
        agent_name: str,
        od_win_rate: float,
        fd_rate: float,
        trade_rate: float,
        top_flaws: list[dict[str, Any]],
        r_count: int,
    ) -> tuple[dict[str, Any], str]:
        """Benchmark agent stats against competitive esports expectations."""
        benchmarks: dict[str, Any] = {}
        diagnosis_parts = []

        primary_flaw = top_flaws[0]["name"] if top_flaws else "none"

        if role == "Duelist":
            # Duelist: High opening duel win rate required (benchmark >= 50%)
            entry_grade = "S" if od_win_rate >= 60 else ("A" if od_win_rate >= 50 else ("B" if od_win_rate >= 40 else "C"))
            benchmarks = {
                "entry_grade": entry_grade,
                "target_od_win_rate": 50.0,
                "target_trade_rate": 45.0,
            }
            if od_win_rate >= 55:
                diagnosis_parts.append(f"High-impact entry fragger ({od_win_rate:.1f}% opening win rate).")
            else:
                diagnosis_parts.append(f"Sub-50% opening duel conversion ({od_win_rate:.1f}%).")

            if primary_flaw in ("over_peeking", "forced_fight"):
                diagnosis_parts.append(f"Recurring '{primary_flaw}' tags suggest dry-peeking without Initiator utility.")
            elif primary_flaw == "whiffed_spray":
                diagnosis_parts.append("Mechanical spray resets needed on medium-range engagements.")

        elif role == "Controller":
            # Controller: Must stay alive to refresh smokes; First Death rate must be low (benchmark <= 10%)
            survival_grade = "S" if fd_rate <= 6 else ("A" if fd_rate <= 10 else ("B" if fd_rate <= 15 else "C"))
            benchmarks = {
                "survival_grade": survival_grade,
                "target_max_fd_rate": 10.0,
                "target_trade_rate": 50.0,
            }
            if fd_rate <= 10:
                diagnosis_parts.append(f"Disciplined positioning: low first death rate ({fd_rate:.1f}%).")
            else:
                diagnosis_parts.append(f"Over-extended for a Controller: high first death rate ({fd_rate:.1f}%).")

            if primary_flaw in ("wasted_utility", "late_rotate"):
                diagnosis_parts.append(f"Frequent '{primary_flaw}' tags: optimize smoke deployment timing.")

        elif role == "Initiator":
            # Initiator: Trade enablement and info timing
            benchmarks = {
                "info_grade": "A" if trade_rate >= 40 else "B",
                "target_trade_rate": 45.0,
            }
            if trade_rate >= 40:
                diagnosis_parts.append(f"Effective trade spacing ({trade_rate:.1f}% trade rate).")
            else:
                diagnosis_parts.append(f"Low trade conversion ({trade_rate:.1f}%). Coordinate follow-up timing.")

            if primary_flaw == "late_flash":
                diagnosis_parts.append("Recon/flash utility deployed after entry duel initiated.")
        else:
            # Sentinel
            benchmarks = {
                "anchor_grade": "A" if fd_rate <= 12 else "B",
                "target_max_fd_rate": 12.0,
            }
            diagnosis_parts.append(f"Anchor hold stability with {trade_rate:.1f}% trade efficiency.")

        return benchmarks, " ".join(diagnosis_parts)

    def _build_macro_insights(self, profiles: list[AgentProfile]) -> list[str]:
        """Surface macro comparative insights across the player's agent pool."""
        insights = []
        if not profiles:
            return ["No agent telemetry recorded yet."]

        # Best K/D agent
        best_kd = max(profiles, key=lambda a: a.kd_ratio)
        insights.append(f"Peak fragging performance: {best_kd.agent_name} with {best_kd.kd_ratio:.2f} K/D across {best_kd.matches_played} match(es).")

        # Duelist vs Controller/Initiator opening duel difference
        duelists = [p for p in profiles if p.role == "Duelist"]
        support = [p for p in profiles if p.role in ("Controller", "Initiator", "Sentinel")]

        if duelists and support:
            d_od = duelists[0].opening_duel_win_rate
            s_fd = support[0].first_death_rate
            insights.append(
                f"Role discipline: {duelists[0].agent_name} entries at {d_od:.1f}% win rate, while {support[0].agent_name} sustains a {s_fd:.1f}% First Death rate."
            )

        # Flaw concentration
        most_flawed = max(profiles, key=lambda a: a.flaw_rate_per_round)
        if most_flawed.top_flaws:
            tf = most_flawed.top_flaws[0]
            insights.append(
                f"Highest habit flaw concentration: {most_flawed.agent_name} ({most_flawed.flaw_rate_per_round:.2f} tags/round), heavily skewed toward '{tf['name']}'."
            )

        return insights
