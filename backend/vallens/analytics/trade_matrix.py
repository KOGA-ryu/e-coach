"""Trade Frag Efficiency & Spacing Error Matrix for post-match tactical VOD review.

Strictly 100% post-game analysis based on downloaded match telemetry.
Evaluates 3.0s trade windows, isolated deaths, crossfire collapses, and team trading rates.
"""

from dataclasses import dataclass, field
import math
from typing import Any, Optional

from vallens.db.repository import MatchRepository
from vallens.models import MatchEvent, MatchPlayer, VodTag


@dataclass
class TradeEvent:
    """Details of a single player death and its trade outcome."""
    round_number: int
    death_time_ms: int
    victim_puuid: str
    victim_name: str
    victim_team: str
    killer_puuid: str
    killer_name: str
    killer_team: str
    victim_pos_x: Optional[float] = None
    victim_pos_y: Optional[float] = None
    killer_pos_x: Optional[float] = None
    killer_pos_y: Optional[float] = None
    weapon: str = "Unknown"
    is_traded: bool = False
    trade_time_ms: Optional[int] = None
    trade_delay_ms: Optional[int] = None
    trader_puuid: Optional[str] = None
    trader_name: Optional[str] = None
    trader_pos_x: Optional[float] = None
    trader_pos_y: Optional[float] = None
    trade_quality: str = "untraded"  # "instant", "clean", "delayed", "untraded"
    spacing_flaw: Optional[str] = None  # "isolated_death", "untraded_baiting", "crossfire_trap", None
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "death_time_ms": self.death_time_ms,
            "victim_puuid": self.victim_puuid,
            "victim_name": self.victim_name,
            "victim_team": self.victim_team,
            "killer_puuid": self.killer_puuid,
            "killer_name": self.killer_name,
            "killer_team": self.killer_team,
            "victim_pos_x": self.victim_pos_x,
            "victim_pos_y": self.victim_pos_y,
            "killer_pos_x": self.killer_pos_x,
            "killer_pos_y": self.killer_pos_y,
            "weapon": self.weapon,
            "is_traded": self.is_traded,
            "trade_time_ms": self.trade_time_ms,
            "trade_delay_ms": self.trade_delay_ms,
            "trader_puuid": self.trader_puuid,
            "trader_name": self.trader_name,
            "trader_pos_x": self.trader_pos_x,
            "trader_pos_y": self.trader_pos_y,
            "trade_quality": self.trade_quality,
            "spacing_flaw": self.spacing_flaw,
            "details": self.details,
        }


@dataclass
class RoundTradeSummary:
    """Summary of trades and spacing discipline for a specific round."""
    round_number: int
    total_deaths: int
    traded_deaths: int
    untraded_deaths: int
    trade_conversion_pct: float
    first_death_puuid: Optional[str] = None
    first_death_traded: bool = False
    spacing_errors: int = 0
    trades: list[TradeEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "total_deaths": self.total_deaths,
            "traded_deaths": self.traded_deaths,
            "untraded_deaths": self.untraded_deaths,
            "trade_conversion_pct": round(self.trade_conversion_pct, 1),
            "first_death_puuid": self.first_death_puuid,
            "first_death_traded": self.first_death_traded,
            "spacing_errors": self.spacing_errors,
            "trades": [t.to_dict() for t in self.trades],
        }


@dataclass
class PlayerTradeStats:
    """Individual player trading and spacing scorecard."""
    player_puuid: str
    player_name: str
    team_id: str
    character_id: str
    total_deaths: int = 0
    deaths_traded: int = 0          # times teammates traded this player
    untraded_deaths: int = 0
    trade_received_pct: float = 0.0 # (deaths_traded / total_deaths) * 100
    trades_given: int = 0           # kills by this player that avenged a teammate within 3s
    first_deaths: int = 0
    first_deaths_traded: int = 0
    isolated_deaths: int = 0        # spacing flaws
    avg_trade_delay_ms: float = 0.0
    trade_rating: float = 50.0      # 0 to 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_puuid": self.player_puuid,
            "player_name": self.player_name,
            "team_id": self.team_id,
            "character_id": self.character_id,
            "total_deaths": self.total_deaths,
            "deaths_traded": self.deaths_traded,
            "untraded_deaths": self.untraded_deaths,
            "trade_received_pct": round(self.trade_received_pct, 1),
            "trades_given": self.trades_given,
            "first_deaths": self.first_deaths,
            "first_deaths_traded": self.first_deaths_traded,
            "isolated_deaths": self.isolated_deaths,
            "avg_trade_delay_ms": round(self.avg_trade_delay_ms, 1),
            "trade_rating": round(self.trade_rating, 1),
        }


@dataclass
class MatchTradeReport:
    """Full match trading efficiency and spacing error report."""
    match_id: str
    total_deaths: int
    total_traded_deaths: int
    match_trade_conversion_pct: float
    first_death_trade_pct: float
    total_spacing_flaws: int
    team_trade_rates: dict[str, float]
    player_stats: list[PlayerTradeStats]
    round_summaries: list[RoundTradeSummary]
    all_trade_events: list[TradeEvent]

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "total_deaths": self.total_deaths,
            "total_traded_deaths": self.total_traded_deaths,
            "match_trade_conversion_pct": round(self.match_trade_conversion_pct, 1),
            "first_death_trade_pct": round(self.first_death_trade_pct, 1),
            "total_spacing_flaws": self.total_spacing_flaws,
            "team_trade_rates": {k: round(v, 1) for k, v in self.team_trade_rates.items()},
            "player_stats": [p.to_dict() for p in self.player_stats],
            "round_summaries": [r.to_dict() for r in self.round_summaries],
            "all_trade_events": [t.to_dict() for t in self.all_trade_events],
        }

    @property
    def trades(self) -> list[TradeEvent]:
        return self.all_trade_events



class TradeMatrixEngine:
    """Evaluates combat trade windows, spacing errors, and revenge frags."""

    def __init__(self, repo: Optional[MatchRepository] = None, trade_window_ms: int = 3000):
        self.repo = repo
        self.trade_window_ms = trade_window_ms

    def analyze_match_trades(
        self,
        match_id: str,
        events: Optional[list[MatchEvent]] = None,
        players: Optional[list[MatchPlayer]] = None,
        tags: Optional[list[VodTag]] = None,
    ) -> MatchTradeReport:
        """Process all kill/death events for a match to produce trade and spacing telemetry."""
        if events is None and self.repo:
            events = self.repo.get_events(match_id)
        events = events or []


        if players is None and self.repo:
            players = self.repo.get_match_players(match_id)
        players = players or []

        if tags is None and self.repo:
            tags = self.repo.get_tags(match_id)
        tags = tags or []

        player_map = {p.player_puuid: p for p in players}

        # Filter and sort kill events
        kills = [e for e in events if e.event_type == "kill"]
        kills.sort(key=lambda e: (e.round_number, e.event_time_ms))

        # Group kills by round
        rounds_set = sorted(list(set(e.round_number for e in events)))
        all_trade_events: list[TradeEvent] = []
        round_summaries: list[RoundTradeSummary] = []

        total_first_deaths = 0
        total_first_deaths_traded = 0

        # Track per-player trading accumulators
        player_acc: dict[str, dict[str, Any]] = {}
        for puuid, p in player_map.items():
            player_acc[puuid] = {
                "total_deaths": 0,
                "deaths_traded": 0,
                "untraded_deaths": 0,
                "trades_given": 0,
                "first_deaths": 0,
                "first_deaths_traded": 0,
                "isolated_deaths": 0,
                "trade_delays": [],
            }

        for r_num in rounds_set:
            r_kills = [k for k in kills if k.round_number == r_num]
            r_trades: list[TradeEvent] = []
            r_spacing_errors = 0

            first_death_id: Optional[str] = None
            first_death_traded = False

            if r_kills:
                first_victim = r_kills[0].metadata.get("victim") or r_kills[0].metadata.get("victim_puuid")
                first_death_id = first_victim
                total_first_deaths += 1
                if first_victim and first_victim in player_acc:
                    player_acc[first_victim]["first_deaths"] += 1

            for i, k in enumerate(r_kills):
                killer_id = k.player_puuid or "unknown"
                victim_id = k.metadata.get("victim") or k.metadata.get("victim_puuid") or "unknown"
                death_time = k.event_time_ms

                killer_player = player_map.get(killer_id)
                victim_player = player_map.get(victim_id)

                killer_name = killer_player.game_name if killer_player else "Enemy"
                victim_name = victim_player.game_name if victim_player else "Player"
                killer_team = killer_player.team_id if killer_player else "Red"
                victim_team = victim_player.team_id if victim_player else "Blue"

                # Extract positions
                k_pos_x = k.pos_x
                k_pos_y = k.pos_y
                v_pos_info = k.metadata.get("victim_pos") or {}
                v_pos_x = v_pos_info.get("norm_x")
                v_pos_y = v_pos_info.get("norm_y")

                weapon = k.metadata.get("weapon") or "Weapon"

                # Check for trade frag
                is_traded = False
                trade_time: Optional[int] = None
                trade_delay: Optional[int] = None
                trader_id: Optional[str] = None
                trader_name: Optional[str] = None
                trader_pos_x: Optional[float] = None
                trader_pos_y: Optional[float] = None
                trade_quality = "untraded"

                for next_k in r_kills[i + 1 :]:
                    delta = next_k.event_time_ms - death_time
                    if delta > self.trade_window_ms:
                        break

                    # Did a teammate of victim kill the original killer?
                    next_killer_id = next_k.player_puuid
                    next_victim_id = next_k.metadata.get("victim") or next_k.metadata.get("victim_puuid")
                    next_killer_player = player_map.get(next_killer_id)


                    # Same team as victim, killed the killer
                    is_teammate = (
                        next_killer_player and next_killer_player.team_id == victim_team
                    ) or (next_killer_id != killer_id and next_victim_id == killer_id)

                    if next_victim_id == killer_id and is_teammate:
                        is_traded = True
                        trade_time = next_k.event_time_ms
                        trade_delay = delta
                        trader_id = next_killer_id
                        trader_name = (
                            next_killer_player.game_name
                            if next_killer_player
                            else "Teammate"
                        )
                        trader_pos_x = next_k.pos_x
                        trader_pos_y = next_k.pos_y

                        if delta < 1200:
                            trade_quality = "instant"
                        elif delta < 2200:
                            trade_quality = "clean"
                        else:
                            trade_quality = "delayed"

                        # Register trade given for the trader
                        if trader_id and trader_id in player_acc:
                            player_acc[trader_id]["trades_given"] += 1
                            player_acc[trader_id]["trade_delays"].append(delta)
                        break

                # Spacing flaw evaluation if untraded
                spacing_flaw = None
                details = ""
                if not is_traded:
                    # Check if there was a multi-kill collapse (same killer killed someone else quickly)
                    multi_kill_collapse = False
                    for next_k in r_kills[i + 1 :]:
                        if (
                            next_k.player_puuid == killer_id
                            and (next_k.event_time_ms - death_time) <= 4000
                        ):
                            multi_kill_collapse = True
                            break

                    # Check proximity tags
                    has_spacing_tag = any(
                        t.tag_name in ("poor_spacing", "over_peeking", "forced_fight")
                        and abs(t.timestamp_ms - death_time) <= 6000
                        for t in tags
                    )

                    if multi_kill_collapse:
                        spacing_flaw = "crossfire_trap"
                        details = "Collapsed on by enemy crossfire / multi-duel"
                    elif i == 0 or has_spacing_tag:
                        spacing_flaw = "isolated_death"
                        details = "Overextended opening duel without teammate trade line"
                        r_spacing_errors += 1
                        if victim_id in player_acc:
                            player_acc[victim_id]["isolated_deaths"] += 1
                    else:
                        spacing_flaw = "untraded_baiting"
                        details = "Death went untraded beyond 3.0s window"
                else:
                    details = f"Successfully traded in {trade_delay}ms by {trader_name}"

                # Update victim stats
                if victim_id in player_acc:
                    player_acc[victim_id]["total_deaths"] += 1
                    if is_traded:
                        player_acc[victim_id]["deaths_traded"] += 1
                    else:
                        player_acc[victim_id]["untraded_deaths"] += 1

                if i == 0 and is_traded:
                    first_death_traded = True
                    total_first_deaths_traded += 1
                    if victim_id in player_acc:
                        player_acc[victim_id]["first_deaths_traded"] += 1

                t_event = TradeEvent(
                    round_number=r_num,
                    death_time_ms=death_time,
                    victim_puuid=victim_id,
                    victim_name=victim_name,
                    victim_team=victim_team,
                    killer_puuid=killer_id,
                    killer_name=killer_name,
                    killer_team=killer_team,
                    victim_pos_x=v_pos_x,
                    victim_pos_y=v_pos_y,
                    killer_pos_x=k_pos_x,
                    killer_pos_y=k_pos_y,
                    weapon=weapon,
                    is_traded=is_traded,
                    trade_time_ms=trade_time,
                    trade_delay_ms=trade_delay,
                    trader_puuid=trader_id,
                    trader_name=trader_name,
                    trader_pos_x=trader_pos_x,
                    trader_pos_y=trader_pos_y,
                    trade_quality=trade_quality,
                    spacing_flaw=spacing_flaw,
                    details=details,
                )
                r_trades.append(t_event)
                all_trade_events.append(t_event)

            # Round level summary
            r_total = len(r_trades)
            r_traded = sum(1 for t in r_trades if t.is_traded)
            r_untraded = r_total - r_traded
            r_conv = (r_traded / max(1, r_total)) * 100.0

            round_summaries.append(
                RoundTradeSummary(
                    round_number=r_num,
                    total_deaths=r_total,
                    traded_deaths=r_traded,
                    untraded_deaths=r_untraded,
                    trade_conversion_pct=r_conv,
                    first_death_puuid=first_death_id,
                    first_death_traded=first_death_traded,
                    spacing_errors=r_spacing_errors,
                    trades=r_trades,
                )
            )

        # Team level calculations
        team_deaths: dict[str, int] = {}
        team_traded: dict[str, int] = {}
        for t in all_trade_events:
            v_team = t.victim_team
            team_deaths[v_team] = team_deaths.get(v_team, 0) + 1
            if t.is_traded:
                team_traded[v_team] = team_traded.get(v_team, 0) + 1

        team_rates = {}
        for team, d_count in team_deaths.items():
            t_count = team_traded.get(team, 0)
            team_rates[team] = (t_count / max(1, d_count)) * 100.0

        # Player stats collation
        player_stats_list: list[PlayerTradeStats] = []
        for puuid, p in player_map.items():
            acc = player_acc.get(puuid, {})
            t_deaths = acc.get("total_deaths", 0)
            d_traded = acc.get("deaths_traded", 0)
            u_deaths = acc.get("untraded_deaths", 0)
            delays = acc.get("trade_delays", [])
            avg_delay = sum(delays) / max(1, len(delays)) if delays else 0.0

            recv_pct = (d_traded / max(1, t_deaths)) * 100.0 if t_deaths > 0 else 0.0
            trades_given = acc.get("trades_given", 0)
            isolated = acc.get("isolated_deaths", 0)

            # Rating algorithm (0 - 100):
            # Base 65 + bonus for received trade %, bonus for trades given, penalty for isolated deaths
            rating = 65.0
            rating += (recv_pct - 40.0) * 0.35
            rating += min(20.0, trades_given * 6.0)
            rating -= isolated * 5.0
            rating = max(15.0, min(99.0, rating))

            player_stats_list.append(
                PlayerTradeStats(
                    player_puuid=puuid,
                    player_name=p.game_name,
                    team_id=p.team_id,
                    character_id=p.character_id,
                    total_deaths=t_deaths,
                    deaths_traded=d_traded,
                    untraded_deaths=u_deaths,
                    trade_received_pct=recv_pct,
                    trades_given=trades_given,
                    first_deaths=acc.get("first_deaths", 0),
                    first_deaths_traded=acc.get("first_deaths_traded", 0),
                    isolated_deaths=isolated,
                    avg_trade_delay_ms=avg_delay,
                    trade_rating=rating,
                )
            )

        # Sort player stats: Blue / Ace team first, then by trade rating
        player_stats_list.sort(key=lambda p: (0 if p.team_id == "Blue" else 1, -p.trade_rating))

        total_match_deaths = len(all_trade_events)
        total_match_traded = sum(1 for t in all_trade_events if t.is_traded)
        match_conv_pct = (total_match_traded / max(1, total_match_deaths)) * 100.0
        first_death_pct = (
            (total_first_deaths_traded / max(1, total_first_deaths)) * 100.0
            if total_first_deaths > 0
            else 0.0
        )
        total_spacing = sum(r.spacing_errors for r in round_summaries)

        return MatchTradeReport(
            match_id=match_id,
            total_deaths=total_match_deaths,
            total_traded_deaths=total_match_traded,
            match_trade_conversion_pct=match_conv_pct,
            first_death_trade_pct=first_death_pct,
            total_spacing_flaws=total_spacing,
            team_trade_rates=team_rates,
            player_stats=player_stats_list,
            round_summaries=round_summaries,
            all_trade_events=all_trade_events,
        )

    # Class method alias
    analyze = analyze_match_trades



# Convenient alias
TradeFragMatrixEngine = TradeMatrixEngine

