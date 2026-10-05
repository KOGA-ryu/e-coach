"""Economy vs. Flaw Correlation Engine for ValLens.

Analyzes player economy tiers (Pistol, Eco/Save, Force Buy, Full Buy) and cross-references
them with subjective flaw tags to identify poor tactical spending or over-aggression on save rounds.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from vallens.models import MatchEvent, VodTag

WEAPON_TIER_MAP = {
    # Pistols / Sidearms
    "classic": "Pistol",
    "shorty": "Pistol",
    "frenzy": "Pistol",
    "ghost": "Pistol",
    "sheriff": "Pistol",
    # Eco / Save (Knife / Unarmed)
    "knife": "Eco",
    "melee": "Eco",
    # Force Buy / Semi-Buy (SMGs, Shotguns, Light Rifles)
    "stinger": "Force Buy",
    "spectre": "Force Buy",
    "bucky": "Force Buy",
    "judge": "Force Buy",
    "marshal": "Force Buy",
    "ares": "Force Buy",
    "outlaw": "Force Buy",
    "bulldog": "Force Buy",
    # Full Buy (Rifles, Heavy Snipers, Heavy MGs)
    "guardian": "Full Buy",
    "phantom": "Full Buy",
    "vandal": "Full Buy",
    "operator": "Full Buy",
    "odin": "Full Buy",
}


@dataclass
class RoundEconomyInfo:
    round_number: int
    tier: str  # 'Pistol', 'Eco', 'Force Buy', 'Full Buy'
    won: bool = False
    flaws_count: int = 0
    flaws: list[str] = field(default_factory=list)


@dataclass
class EconomyFlawRow:
    tag_name: str
    category: str
    pistol_count: int = 0
    eco_count: int = 0
    force_count: int = 0
    full_count: int = 0
    total_count: int = 0
    dominant_tier: str = "Full Buy"
    eco_share_pct: float = 0.0


@dataclass
class EconomyAnalysisResult:
    match_id: str
    rounds: list[RoundEconomyInfo]
    flaw_rows: list[EconomyFlawRow]
    kpis: dict[str, Any]
    coaching_insights: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "rounds": [
                {
                    "round_number": r.round_number,
                    "tier": r.tier,
                    "won": r.won,
                    "flaws_count": r.flaws_count,
                    "flaws": r.flaws,
                }
                for r in self.rounds
            ],
            "flaw_rows": [
                {
                    "tag_name": f.tag_name,
                    "category": f.category,
                    "pistol_count": f.pistol_count,
                    "eco_count": f.eco_count,
                    "force_count": f.force_count,
                    "full_count": f.full_count,
                    "total_count": f.total_count,
                    "dominant_tier": f.dominant_tier,
                    "eco_share_pct": f.eco_share_pct,
                }
                for f in self.flaw_rows
            ],
            "kpis": self.kpis,
            "coaching_insights": self.coaching_insights,
        }


class EconomyCorrelationEngine:
    """Classifies rounds by economy status and correlates with tactical flaws."""

    def classify_rounds(
        self,
        events: list[MatchEvent],
        player_puuid: Optional[str] = None,
    ) -> dict[int, RoundEconomyInfo]:
        """Classify each round into an economy tier and record outcome."""
        round_nums = sorted(list(set(e.round_number for e in events)))
        rounds_info: dict[int, RoundEconomyInfo] = {}

        for r in round_nums:
            round_events = [e for e in events if e.round_number == r]
            
            # 1. Determine if round was won
            won = False
            end_ev = next((e for e in round_events if e.event_type == "round_end"), None)
            if end_ev and end_ev.metadata:
                res = str(end_ev.metadata.get("round_result", "")).lower()
                win_team = str(end_ev.metadata.get("winning_team", "")).lower()
                if "won" in res or win_team == "blue":
                    won = True

            # 2. Determine economy tier
            if r in (0, 12):
                tier = "Pistol"
            else:
                # Find weapons used by player (or team in round)
                weapons = []
                for e in round_events:
                    if e.event_type in ("kill", "death"):
                        w = e.metadata.get("weapon")
                        if w:
                            weapons.append(str(w).lower())

                # Classify based on highest weapon tier observed
                tier_priority = {"Full Buy": 4, "Force Buy": 3, "Eco": 2, "Pistol": 1}
                highest_tier = "Force Buy"  # fallback default
                max_rank = 0

                for w in weapons:
                    matched_tier = WEAPON_TIER_MAP.get(w)
                    if matched_tier:
                        # Non-round-0 pistols outside pistol rounds are Eco
                        if matched_tier == "Pistol" and r not in (0, 12):
                            matched_tier = "Eco"
                        rank = tier_priority.get(matched_tier, 2)
                        if rank > max_rank:
                            max_rank = rank
                            highest_tier = matched_tier

                tier = highest_tier if max_rank > 0 else "Full Buy"

            rounds_info[r] = RoundEconomyInfo(
                round_number=r,
                tier=tier,
                won=won,
            )

        return rounds_info

    def analyze(
        self,
        match_id: str,
        events: list[MatchEvent],
        tags: list[VodTag],
        player_puuid: Optional[str] = None,
    ) -> EconomyAnalysisResult:
        """Run full correlation between economy tiers and review flaw tags."""
        rounds_info = self.classify_rounds(events, player_puuid=player_puuid)

        # Map round start intervals
        round_starts = {}
        for e in events:
            if e.event_type == "round_start":
                round_starts[e.round_number] = e.event_time_ms

        sorted_starts = sorted(round_starts.items(), key=lambda x: x[1])

        def get_tag_round(tag_ms: int) -> int:
            if not sorted_starts:
                return 0
            curr_rnd = sorted_starts[0][0]
            for rnd, start_ms in sorted_starts:
                if tag_ms >= start_ms:
                    curr_rnd = rnd
                else:
                    break
            return curr_rnd

        # Group tags by flaw name
        flaw_counts: dict[str, dict[str, Any]] = {}

        for tag in tags:
            tag_name = tag.tag_name
            cat = tag.tag_category
            tag_round = get_tag_round(tag.timestamp_ms)

            # Record flaw on round
            if tag_round in rounds_info:
                rounds_info[tag_round].flaws_count += 1
                rounds_info[tag_round].flaws.append(tag_name)
                tier = rounds_info[tag_round].tier
            else:
                tier = "Full Buy"

            if tag_name not in flaw_counts:
                flaw_counts[tag_name] = {
                    "category": cat,
                    "Pistol": 0,
                    "Eco": 0,
                    "Force Buy": 0,
                    "Full Buy": 0,
                    "total": 0,
                }

            flaw_counts[tag_name][tier] = flaw_counts[tag_name].get(tier, 0) + 1
            flaw_counts[tag_name]["total"] += 1

        # Build flaw rows
        flaw_rows: list[EconomyFlawRow] = []
        for tag_name, counts in flaw_counts.items():
            total = counts["total"]
            p_cnt = counts.get("Pistol", 0)
            e_cnt = counts.get("Eco", 0)
            f_cnt = counts.get("Force Buy", 0)
            full_cnt = counts.get("Full Buy", 0)

            # Determine dominant tier
            tiers_data = [
                ("Pistol", p_cnt),
                ("Eco", e_cnt),
                ("Force Buy", f_cnt),
                ("Full Buy", full_cnt),
            ]
            dominant = max(tiers_data, key=lambda x: x[1])[0]
            eco_share = round(((e_cnt + p_cnt) / total * 100), 1) if total > 0 else 0.0

            flaw_rows.append(
                EconomyFlawRow(
                    tag_name=tag_name,
                    category=counts["category"],
                    pistol_count=p_cnt,
                    eco_count=e_cnt,
                    force_count=f_cnt,
                    full_count=full_cnt,
                    total_count=total,
                    dominant_tier=dominant,
                    eco_share_pct=eco_share,
                )
            )

        # Sort flaw rows by total count descending
        flaw_rows.sort(key=lambda r: r.total_count, reverse=True)

        # Calculate KPIs
        total_flaws = sum(r.total_count for r in flaw_rows)
        eco_flaws = sum(r.eco_count for r in flaw_rows)
        eco_flaw_rate = round((eco_flaws / total_flaws * 100), 1) if total_flaws > 0 else 0.0

        tier_rounds: dict[str, list[RoundEconomyInfo]] = {}
        for r_info in rounds_info.values():
            tier_rounds.setdefault(r_info.tier, []).append(r_info)

        def win_rate(t_name: str) -> float:
            r_list = tier_rounds.get(t_name, [])
            if not r_list:
                return 0.0
            wins = sum(1 for r in r_list if r.won)
            return round((wins / len(r_list)) * 100, 1)

        kpis = {
            "total_flaws": total_flaws,
            "eco_flaws": eco_flaws,
            "eco_flaw_rate": eco_flaw_rate,
            "full_buy_win_rate": win_rate("Full Buy"),
            "force_buy_win_rate": win_rate("Force Buy"),
            "eco_win_rate": win_rate("Eco"),
            "pistol_win_rate": win_rate("Pistol"),
            "most_frequent_eco_flaw": next((r.tag_name for r in flaw_rows if r.eco_count > 0), "None"),
        }

        # Generate tactical coaching insights
        insights = []
        if eco_flaw_rate >= 40.0:
            insights.append(
                f"Severe Eco Over-Aggression: {eco_flaw_rate}% of your mistakes occur on Eco/Save rounds. Play for exit frags and avoid taking dry 50/50 duels against rifle armor."
            )

        for row in flaw_rows[:3]:
            if row.tag_name == "forced_fight" and row.eco_count >= 2:
                insights.append(
                    f"Forced Fights on Eco: Logged {row.eco_count}x on save rounds. Do not ego-peek when out-gunned; bait opponent utility or stack crossfires."
                )
            elif row.tag_name == "wasted_utility" and (row.eco_count + row.force_count) >= 2:
                insights.append(
                    f"Sub-optimal Economy Utility: Logged {row.eco_count + row.force_count}x on Eco/Force rounds. Preserve high-value utility for coordinated full-buy rounds."
                )
            elif row.tag_name == "over_peeking" and row.full_count >= 3:
                insights.append(
                    f"Full Buy Over-Peeking: Committed {row.full_count}x with rifles. Fall back to site after securing first contact rather than re-peeking un-tradeable angles."
                )

        if not insights:
            insights.append("Balanced economy discipline. Tactical flaws are distributed evenly without disproportionate save-round reckless peeks.")

        return EconomyAnalysisResult(
            match_id=match_id,
            rounds=list(rounds_info.values()),
            flaw_rows=flaw_rows,
            kpis=kpis,
            coaching_insights=insights,
        )
