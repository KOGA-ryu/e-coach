"""Generates executive Coaching Report Cards and actionable practice drills."""

from pathlib import Path
from typing import Any, Optional

from vallens.analytics.correlations import FlawCorrelationEngine
from vallens.models import MatchEvent, MatchMetadata, VodTag
from vallens.obs.sync import TimelineSynchronizer

DRILL_CATALOG: dict[str, str] = {
    "crosshair_placement": "15 min Range Drill: 50 Elimination with Sheriff at head-level + 1 Deathmatch with Guardian only.",
    "whiffed_spray": "Recoil Control: 10 min 4-bullet Phantom burst discipline against strafe bots; avoid committing to 10+ bullet sprays.",
    "over_peeking": "Angle Isolation: Never re-peek an angle where you took damage; fall back to site crossfire or anchor retake.",
    "poor_spacing": "Trade Spacing Protocol: Maintain 3-5m distance behind entry duelist to guarantee a sub-2s trade frag.",
    "wasted_utility": "Utility Economy: Never deploy flash/recon without an immediate team swing within 4 seconds.",
    "late_flash": "Pop-Flash Coordination: Call flash 2 seconds prior to round timer push; throw high-bounce trajectory.",
    "forced_fight": "Disengage Protocol: If down 1 player in the round, preserve weapons or group for 5-man site retake.",
    "late_rotate": "Radar Awareness: Rotate on 2nd piece of confirmation utility (e.g. Sova drone / Omen smoke), not after bomb plant.",
}


class CoachingReportGenerator:
    """Generates structured Markdown and HTML Coaching Report Cards from match telemetry and tags."""

    def __init__(self, engine: Optional[FlawCorrelationEngine] = None):
        self.engine = engine or FlawCorrelationEngine()

    def generate_data(
        self,
        metadata: MatchMetadata,
        events: list[MatchEvent],
        tags: list[VodTag],
        player_puuid: Optional[str] = None,
    ) -> dict[str, Any]:
        """Aggregate all metrics into a structured report dictionary."""
        # Find player PUUID if not provided (default to player with most kills/events)
        if not player_puuid:
            player_kills: dict[str, int] = {}
            for e in events:
                if e.event_type == "kill" and e.player_puuid:
                    player_kills[e.player_puuid] = player_kills.get(e.player_puuid, 0) + 1
            player_puuid = max(player_kills, key=player_kills.get) if player_kills else "player"

        rounds = sorted(list(set(e.round_number for e in events)))
        total_rounds = len(rounds)
        openings = self.engine.analyze_openings(events)
        trades = self.engine.analyze_trades(events)
        player_trades = [t for t in trades if t.victim_puuid == player_puuid]

        # First Bloods & Deaths
        fb_count = sum(1 for op in openings.values() if op.first_blood_puuid == player_puuid)
        fd_count = sum(1 for op in openings.values() if op.first_death_puuid == player_puuid)

        # Trade Efficiency
        total_player_deaths = len(player_trades)
        traded_deaths = sum(1 for t in player_trades if t.is_traded)
        untraded_deaths = total_player_deaths - traded_deaths
        trade_rate = (traded_deaths / max(1, total_player_deaths)) * 100

        # Kills and Deaths
        kills = [e for e in events if e.event_type == "kill" and e.player_puuid == player_puuid]
        kd_ratio = len(kills) / max(1, total_player_deaths)

        # Correlate tags
        tag_correlations = self.engine.correlate_tags_with_metrics(player_puuid, events, tags)

        # Coach vs Solo comparison
        discrepancy = self.engine.compare_coach_vs_solo(tags)

        # Letter Grade Calculation
        grade = self._calculate_grade(kd_ratio, trade_rate, fd_count, len(tags))

        # Recommended Drills
        drills = []
        for tc in tag_correlations:
            drill = DRILL_CATALOG.get(tc.tag_name)
            if drill and drill not in drills:
                drills.append({"tag": tc.tag_name, "drill": drill})

        return {
            "metadata": metadata,
            "player_puuid": player_puuid,
            "total_rounds": total_rounds,
            "kills": len(kills),
            "deaths": total_player_deaths,
            "kd_ratio": round(kd_ratio, 2),
            "first_bloods": fb_count,
            "first_deaths": fd_count,
            "traded_deaths": traded_deaths,
            "untraded_deaths": untraded_deaths,
            "trade_rate": round(trade_rate, 1),
            "grade": grade,
            "tag_correlations": tag_correlations,
            "discrepancy": discrepancy,
            "drills": drills,
        }

    def _calculate_grade(self, kd: float, trade_rate: float, fd_count: int, tag_count: int) -> str:
        score = 80.0
        score += (kd - 1.0) * 15.0
        score += (trade_rate - 40.0) * 0.3
        score -= fd_count * 3.0
        score -= tag_count * 1.5

        if score >= 90:
            return "A"
        elif score >= 85:
            return "A-"
        elif score >= 80:
            return "B+"
        elif score >= 75:
            return "B"
        elif score >= 70:
            return "B-"
        elif score >= 65:
            return "C+"
        elif score >= 60:
            return "C"
        return "D"

    def generate_markdown(
        self,
        metadata: MatchMetadata,
        events: list[MatchEvent],
        tags: list[VodTag],
        player_puuid: Optional[str] = None,
    ) -> str:
        """Generate a GitHub-flavored Markdown coaching report."""
        data = self.generate_data(metadata, events, tags, player_puuid)
        m = data["metadata"]
        map_name = m.map_id.split("/")[-1]

        lines = [
            f"# ValLens Coaching Report Card — {map_name.upper()}",
            f"**Match ID:** `{m.match_id}`  ",
            f"**Map:** {map_name} | **Rounds:** {data['total_rounds']} | **Performance Grade:** **{data['grade']}**",
            "",
            "## 1. Executive Telemetry Overview",
            f"* **K/D Performance:** {data['kills']} Kills / {data['deaths']} Deaths ({data['kd_ratio']} Ratio)",
            f"* **Opening Duels:** {data['first_bloods']} First Bloods / {data['first_deaths']} First Deaths",
            f"* **Trade Efficiency:** **{data['trade_rate']}%** ({data['traded_deaths']} traded / {data['untraded_deaths']} isolated deaths)",
            "",
            "## 2. Review Tag Correlations & Root Causes",
        ]

        if not data["tag_correlations"]:
            lines.append("No review tags logged for this match.")
        else:
            lines.append("| Tag Category | Flaw Name | Frequency | First Deaths | Un-traded Deaths |")
            lines.append("| :--- | :--- | :--- | :--- | :--- |")
            for tc in data["tag_correlations"]:
                lines.append(
                    f"| **{tc.category}** | `{tc.tag_name}` | {tc.total_count} | {tc.first_death_count} | {tc.untraded_death_count} |"
                )

        lines.extend([
            "",
            "## 3. Coach vs. Solo Alignment",
            f"* **Agreement Score:** **{int(data['discrepancy'].agreement_score * 100)}%**",
            f"* **Coach Blindspots (Missed by Player):** {len(data['discrepancy'].blindspots)}",
        ])

        for b in data["discrepancy"].blindspots:
            tc_str = TimelineSynchronizer.ms_to_display_time(b.timestamp_ms)
            lines.append(f"  * [{tc_str}] **{b.tag_category}**: `{b.tag_name}`")

        lines.extend([
            "",
            "## 4. Prescribed Practice Drills",
        ])

        if not data["drills"]:
            lines.append("No specific drills required based on current review tags.")
        else:
            for d in data["drills"]:
                lines.append(f"* **{d['tag'].replace('_', ' ').title()}:** {d['drill']}")

        return "\n".join(lines)

    def generate_html(
        self,
        metadata: MatchMetadata,
        events: list[MatchEvent],
        tags: list[VodTag],
        player_puuid: Optional[str] = None,
    ) -> str:
        """Generate a self-contained, printable dark-mode HTML report card."""
        data = self.generate_data(metadata, events, tags, player_puuid)
        m = data["metadata"]
        map_name = m.map_id.split("/")[-1].upper()

        tags_html = ""
        for tc in data["tag_correlations"]:
            tags_html += f"""
            <tr>
              <td><span class="badge {tc.category.lower()}">{tc.category}</span></td>
              <td><strong>{tc.tag_name}</strong></td>
              <td>{tc.total_count}</td>
              <td>{tc.first_death_count}</td>
              <td>{tc.untraded_death_count}</td>
            </tr>
            """

        drills_html = ""
        for d in data["drills"]:
            drills_html += f"""
            <div class="drill-card">
              <div class="drill-title">{d['tag'].replace('_', ' ').upper()}</div>
              <div class="drill-text">{d['drill']}</div>
            </div>
            """

        blindspots_html = ""
        for b in data["discrepancy"].blindspots:
            tc_str = TimelineSynchronizer.ms_to_display_time(b.timestamp_ms)
            blindspots_html += f"<li><span class='time'>{tc_str}</span> <strong>{b.tag_category}</strong>: {b.tag_name}</li>"

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>ValLens Coaching Report — {map_name}</title>
  <style>
    body {{ background: #0b1118; color: #ece8e1; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 40px; margin: 0; }}
    .report-card {{ max-width: 900px; margin: 0 auto; background: #121b24; border: 1px solid #2b3947; border-radius: 8px; padding: 32px; box-shadow: 0 8px 30px rgba(0,0,0,0.5); }}
    .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #ff4655; padding-bottom: 16px; margin-bottom: 24px; }}
    .title {{ font-size: 28px; font-weight: 800; letter-spacing: 1px; color: #fff; }}
    .grade-badge {{ font-size: 36px; font-weight: 900; color: #00f5d4; background: rgba(0,245,212,0.1); border: 2px solid #00f5d4; border-radius: 8px; padding: 4px 20px; }}
    .grid-stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 28px; }}
    .stat-box {{ background: #19232d; padding: 16px; border-radius: 6px; border: 1px solid #2b3947; text-align: center; }}
    .stat-label {{ font-size: 11px; color: #8b97a5; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }}
    .stat-val {{ font-size: 22px; font-weight: 700; color: #fff; }}
    .stat-val.highlight {{ color: #ff4655; }}
    .stat-val.cyan {{ color: #00f5d4; }}
    h2 {{ font-size: 18px; color: #fff; border-left: 3px solid #ff4655; padding-left: 10px; margin: 28px 0 16px; }}
    table {{ width: 100%; border-collapse: collapse; background: #19232d; border-radius: 6px; overflow: hidden; }}
    th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #2b3947; font-size: 13px; }}
    th {{ background: #1f2b37; color: #8b97a5; text-transform: uppercase; font-size: 11px; }}
    .badge {{ font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 3px; text-transform: uppercase; }}
    .badge.mechanics {{ background: #ff70a6; color: #0b1118; }}
    .badge.positioning {{ background: #70d6ff; color: #0b1118; }}
    .badge.utility {{ background: #ffd670; color: #0b1118; }}
    .badge.decision {{ background: #e9ff70; color: #0b1118; }}
    .drill-card {{ background: #19232d; border-left: 4px solid #00f5d4; padding: 12px 16px; border-radius: 4px; margin-bottom: 10px; }}
    .drill-title {{ font-size: 13px; font-weight: 700; color: #00f5d4; margin-bottom: 4px; }}
    .drill-text {{ font-size: 13px; color: #ece8e1; }}
    .time {{ font-family: monospace; color: #00f5d4; margin-right: 8px; }}
    ul {{ padding-left: 20px; }}
    li {{ margin-bottom: 6px; font-size: 13px; }}
  </style>
</head>
<body>
  <div class="report-card">
    <div class="header">
      <div>
        <div class="title">COACHING REPORT CARD — {map_name}</div>
        <div style="color: #8b97a5; font-size: 13px; margin-top: 4px;">Match: {m.match_id}</div>
      </div>
      <div class="grade-badge">{data['grade']}</div>
    </div>

    <div class="grid-stats">
      <div class="stat-box">
        <div class="stat-label">K/D PERFORMANCE</div>
        <div class="stat-val">{data['kills']} / {data['deaths']} <span style="font-size: 14px; color: #8b97a5;">({data['kd_ratio']})</span></div>
      </div>
      <div class="stat-box">
        <div class="stat-label">OPENING DUELS</div>
        <div class="stat-val cyan">{data['first_bloods']} FB / <span class="highlight">{data['first_deaths']} FD</span></div>
      </div>
      <div class="stat-box">
        <div class="stat-label">TRADE EFFICIENCY</div>
        <div class="stat-val cyan">{data['trade_rate']}%</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">COACH ALIGNMENT</div>
        <div class="stat-val">{int(data['discrepancy'].agreement_score * 100)}%</div>
      </div>
    </div>

    <h2>TAG CORRELATIONS & RECURRING FLAWS</h2>
    <table>
      <thead>
        <tr>
          <th>Category</th>
          <th>Flaw Name</th>
          <th>Frequency</th>
          <th>First Deaths</th>
          <th>Un-traded Deaths</th>
        </tr>
      </thead>
      <tbody>
        {tags_html or "<tr><td colspan='5' style='text-align:center;'>No review tags logged.</td></tr>"}
      </tbody>
    </table>

    <h2>COACH BLINDSPOTS (MISSED IN SELF-REVIEW)</h2>
    <ul>
      {blindspots_html or "<li>No blindspots detected; full alignment with coach!</li>"}
    </ul>

    <h2>ACTIONABLE DRILLS & PRESCRIPTIONS</h2>
    {drills_html or "<div style='color: #8b97a5; font-size: 13px;'>No specific training routine required.</div>"}
  </div>
</body>
</html>
"""
