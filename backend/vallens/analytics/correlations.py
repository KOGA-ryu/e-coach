"""Correlates subjective VOD review tags with objective Riot API telemetry."""

from dataclasses import dataclass, field
from typing import Any, Optional

from vallens.models import MatchEvent, VodTag


@dataclass
class RoundOpeningStats:
    round_number: int
    first_blood_puuid: Optional[str] = None
    first_death_puuid: Optional[str] = None
    first_kill_weapon: Optional[str] = None
    first_kill_time_ms: Optional[int] = None


@dataclass
class DeathTradeInfo:
    victim_puuid: str
    killer_puuid: str
    death_time_ms: int
    round_number: int
    is_traded: bool = False
    trade_time_ms: Optional[int] = None
    trader_puuid: Optional[str] = None
    trade_window_ms: Optional[int] = None


@dataclass
class TagCorrelationSummary:
    tag_name: str
    category: str
    total_count: int
    first_death_count: int = 0
    untraded_death_count: int = 0
    early_death_count: int = 0  # within 25s of round start


@dataclass
class DiscrepancyComparison:
    blindspots: list[VodTag] = field(default_factory=list)  # tagged by coach, missed by solo
    self_criticisms: list[VodTag] = field(default_factory=list)  # tagged by solo, not flagged by coach
    agreed_tags: list[tuple[VodTag, VodTag]] = field(default_factory=list)  # tagged by both within 5s
    agreement_score: float = 0.0  # 0.0 to 1.0


class FlawCorrelationEngine:
    """Analyzes round telemetry to correlate tags with opening duels, trades, and coach alignment."""

    def __init__(self, trade_window_ms: int = 3000, early_death_threshold_ms: int = 25000):
        self.trade_window_ms = trade_window_ms
        self.early_death_threshold_ms = early_death_threshold_ms

    def analyze_openings(self, events: list[MatchEvent]) -> dict[int, RoundOpeningStats]:
        """Determine First Blood and First Death for every round."""
        openings: dict[int, RoundOpeningStats] = {}
        rounds = sorted(list(set(e.round_number for e in events)))

        for r in rounds:
            round_events = [e for e in events if e.round_number == r and e.event_type == "kill"]
            round_events.sort(key=lambda e: e.event_time_ms)

            if round_events:
                first_kill = round_events[0]
                openings[r] = RoundOpeningStats(
                    round_number=r,
                    first_blood_puuid=first_kill.player_puuid,
                    first_death_puuid=first_kill.metadata.get("victim"),
                    first_kill_weapon=first_kill.metadata.get("weapon"),
                    first_kill_time_ms=first_kill.event_time_ms,
                )
            else:
                openings[r] = RoundOpeningStats(round_number=r)

        return openings

    def analyze_trades(self, events: list[MatchEvent]) -> list[DeathTradeInfo]:
        """Analyze whether each death was traded by a teammate within the trade window."""
        death_trades: list[DeathTradeInfo] = []
        kills = [e for e in events if e.event_type == "kill"]
        kills.sort(key=lambda e: e.event_time_ms)

        for i, k in enumerate(kills):
            killer = k.player_puuid
            victim = k.metadata.get("victim")
            death_time = k.event_time_ms
            round_num = k.round_number

            info = DeathTradeInfo(
                victim_puuid=victim or "unknown",
                killer_puuid=killer or "unknown",
                death_time_ms=death_time,
                round_number=round_num,
            )

            # Check subsequent kills in the same round within trade window
            for next_k in kills[i + 1 :]:
                if next_k.round_number != round_num:
                    break
                delta = next_k.event_time_ms - death_time
                if delta > self.trade_window_ms:
                    break

                # If the subsequent kill killed the original killer -> Traded!
                if next_k.metadata.get("victim") == killer:
                    info.is_traded = True
                    info.trade_time_ms = next_k.event_time_ms
                    info.trader_puuid = next_k.player_puuid
                    info.trade_window_ms = delta
                    break

            death_trades.append(info)

        return death_trades

    def correlate_tags_with_metrics(
        self,
        player_puuid: str,
        events: list[MatchEvent],
        tags: list[VodTag],
    ) -> list[TagCorrelationSummary]:
        """Cross-reference player review tags with First Deaths and un-traded deaths."""
        openings = self.analyze_openings(events)
        trades = self.analyze_trades(events)
        player_trades = [t for t in trades if t.victim_puuid == player_puuid]

        # Map round numbers to round start times
        round_starts = {
            e.round_number: e.event_time_ms
            for e in events
            if e.event_type == "round_start"
        }

        # Group tags by name
        summary_map: dict[str, TagCorrelationSummary] = {}

        for tag in tags:
            key = f"{tag.tag_category}:{tag.tag_name}"
            if key not in summary_map:
                summary_map[key] = TagCorrelationSummary(
                    tag_name=tag.tag_name,
                    category=tag.tag_category,
                    total_count=0,
                )
            summary = summary_map[key]
            summary.total_count += 1

            # Check if tag is close in time (within 6 seconds) to a player death
            tag_time = tag.timestamp_ms
            matching_deaths = [
                d for d in player_trades if abs(d.death_time_ms - tag_time) <= 6000
            ]

            for d in matching_deaths:
                # 1. Did player die first in this round?
                op = openings.get(d.round_number)
                if op and op.first_death_puuid == player_puuid:
                    summary.first_death_count += 1

                # 2. Was this death un-traded?
                if not d.is_traded:
                    summary.untraded_death_count += 1

                # 3. Was this an early round death?
                r_start = round_starts.get(d.round_number, d.death_time_ms)
                if (d.death_time_ms - r_start) <= self.early_death_threshold_ms:
                    summary.early_death_count += 1

        return sorted(summary_map.values(), key=lambda s: s.total_count, reverse=True)

    def compare_coach_vs_solo(self, tags: list[VodTag], tolerance_ms: int = 5000) -> DiscrepancyComparison:
        """Compare tags logged by Coach vs Solo player to highlight cognitive blindspots."""
        solo_tags = [t for t in tags if t.author_type == "solo"]
        coach_tags = [t for t in tags if t.author_type == "coach"]

        blindspots: list[VodTag] = []
        agreed: list[tuple[VodTag, VodTag]] = []
        matched_coach_ids: set[int] = set()
        matched_solo_ids: set[int] = set()

        for c in coach_tags:
            # Look for a solo tag within tolerance window
            found_match = False
            for s in solo_tags:
                if s.tag_id in matched_solo_ids:
                    continue
                if abs(c.timestamp_ms - s.timestamp_ms) <= tolerance_ms:
                    agreed.append((s, c))
                    matched_coach_ids.add(c.tag_id or 0)
                    matched_solo_ids.add(s.tag_id or 0)
                    found_match = True
                    break
            if not found_match:
                blindspots.append(c)

        self_criticisms = [s for s in solo_tags if (s.tag_id or 0) not in matched_solo_ids]

        total = max(1, len(solo_tags) + len(coach_tags) - len(agreed))
        score = len(agreed) / total

        return DiscrepancyComparison(
            blindspots=blindspots,
            self_criticisms=self_criticisms,
            agreed_tags=agreed,
            agreement_score=round(score, 2),
        )
