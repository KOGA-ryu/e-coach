"""Generates comprehensive, interactive review dossiers and coaching report cards."""

import html
import json
from pathlib import Path
from typing import Any, Optional

from vallens.analytics.correlations import FlawCorrelationEngine
from vallens.analytics.economy import EconomyCorrelationEngine
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
        notes: Optional[list[Any]] = None,
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

        # Economy Analysis
        eco_engine = EconomyCorrelationEngine()
        eco_result = eco_engine.analyze(metadata.match_id, events, tags, player_puuid=player_puuid)

        # Letter Grade Calculation
        grade = self._calculate_grade(kd_ratio, trade_rate, fd_count, len(tags))

        # Recommended Drills
        drills = []
        for tc in tag_correlations:
            drill = DRILL_CATALOG.get(tc.tag_name)
            if drill and drill not in [d["drill"] for d in drills]:
                drills.append({"tag": tc.tag_name, "drill": drill})

        # Format Coach Notes
        formatted_notes = []
        if notes:
            for n in notes:
                if isinstance(n, dict):
                    formatted_notes.append(n)
                else:
                    fp = getattr(n, "audio_filepath", None)
                    fname = Path(fp).name if fp else None
                    audio_url = f"/api/notes/{fname}" if fname else None
                    formatted_notes.append({
                        "note_id": getattr(n, "note_id", None),
                        "round_number": getattr(n, "round_number", 0),
                        "timestamp_ms": getattr(n, "timestamp_ms", 0),
                        "formatted_time": TimelineSynchronizer.ms_to_display_time(getattr(n, "timestamp_ms", 0)),
                        "author_type": getattr(n, "author_type", "coach"),
                        "text_note": getattr(n, "text_note", ""),
                        "has_audio": bool(fp),
                        "audio_url": audio_url,
                        "created_at": getattr(n, "created_at", 0),
                    })

        # Sort notes by timestamp
        formatted_notes.sort(key=lambda x: x["timestamp_ms"])

        # Build Round-by-Round Timeline Recap
        round_tier_map = {r.round_number: r.tier for r in eco_result.rounds}
        round_won_map = {r.round_number: r.won for r in eco_result.rounds}

        # Tag round mapping
        round_starts = {e.round_number: e.event_time_ms for e in events if e.event_type == "round_start"}
        sorted_starts = sorted(round_starts.items(), key=lambda x: x[1])

        def get_tag_round(t_ms: int) -> int:
            if not sorted_starts:
                return 0
            curr = sorted_starts[0][0]
            for rnd, s_ms in sorted_starts:
                if t_ms >= s_ms:
                    curr = rnd
                else:
                    break
            return curr

        round_tags_map: dict[int, list[str]] = {}
        for t in tags:
            r_num = get_tag_round(t.timestamp_ms)
            round_tags_map.setdefault(r_num, []).append(t.tag_name)

        recap_rounds = []
        for r_num in rounds:
            r_kills = sum(1 for e in events if e.round_number == r_num and e.event_type == "kill" and e.player_puuid == player_puuid)
            r_deaths = sum(1 for e in events if e.round_number == r_num and e.event_type == "death" and e.player_puuid == player_puuid)
            recap_rounds.append({
                "round_number": r_num,
                "tier": round_tier_map.get(r_num, "Full Buy"),
                "won": round_won_map.get(r_num, False),
                "kills": r_kills,
                "deaths": r_deaths,
                "flaws": round_tags_map.get(r_num, []),
            })

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
            "economy": eco_result.to_dict(),
            "notes": formatted_notes,
            "recap_rounds": recap_rounds,
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
        notes: Optional[list[Any]] = None,
    ) -> str:
        """Generate a comprehensive GitHub-flavored Markdown coaching report."""
        data = self.generate_data(metadata, events, tags, player_puuid=player_puuid, notes=notes)
        m = data["metadata"]
        map_name = m.map_id.split("/")[-1].title()
        total_flaws = len(tags)

        lines = [
            f"# ValLens Coaching Report Card — {map_name.upper()}",
            f"**Match ID:** `{m.match_id}`  ",
            f"**Map:** {map_name} | **Rounds:** {data['total_rounds']} | **Performance Grade:** **{data['grade']}**",
            "",
            "## 1. Executive Telemetry Overview",
            f"* **K/D Performance:** {data['kills']} Kills / {data['deaths']} Deaths ({data['kd_ratio']} Ratio)",
            f"* **Opening Duels:** {data['first_bloods']} First Bloods / {data['first_deaths']} First Deaths",
            f"* **Trade Efficiency:** **{data['trade_rate']}%** ({data['traded_deaths']} traded / {data['untraded_deaths']} isolated deaths)",
            f"* **Coach Alignment Score:** **{int(data['discrepancy'].agreement_score * 100)}%**",
            f"* **Eco Flaw Rate:** **{data['economy']['kpis'].get('eco_flaw_rate', 0)}%**",
            "",
            "## 2. Review Tag Correlations & Habit Breakdown",
        ]

        if not data["tag_correlations"]:
            lines.append("No review tags logged for this match.")
        else:
            lines.append("| Tag Category | Flaw Name | Frequency | % Share | First Deaths | Un-traded Deaths |")
            lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
            for tc in data["tag_correlations"]:
                pct = round((tc.total_count / max(1, total_flaws)) * 100, 1)
                lines.append(
                    f"| **{tc.category}** | `{tc.tag_name}` | {tc.total_count} | {pct}% | {tc.first_death_count} | {tc.untraded_death_count} |"
                )

        lines.extend([
            "",
            "## 3. Economy vs. Flaw Correlation Matrix",
            f"* **Full Buy Win Rate:** {data['economy']['kpis'].get('full_buy_win_rate', 0)}%",
            f"* **Force Buy Win Rate:** {data['economy']['kpis'].get('force_buy_win_rate', 0)}%",
            f"* **Eco / Save Win Rate:** {data['economy']['kpis'].get('eco_win_rate', 0)}%",
            f"* **Top Save-Round Flaw:** `{data['economy']['kpis'].get('most_frequent_eco_flaw', 'None')}`",
            "",
            "### Economy Coaching Diagnosis",
        ])

        for insight in data["economy"].get("coaching_insights", []):
            lines.append(f"> 💡 **Tactical Diagnosis:** {insight}")

        lines.extend([
            "",
            "## 4. Coach vs. Solo Alignment",
            f"* **Agreement Score:** **{int(data['discrepancy'].agreement_score * 100)}%**",
            f"* **Coach Blindspots (Missed by Player):** {len(data['discrepancy'].blindspots)}",
        ])

        for b in data["discrepancy"].blindspots:
            tc_str = TimelineSynchronizer.ms_to_display_time(b.timestamp_ms)
            lines.append(f"  * [{tc_str}] **{b.tag_category}**: `{b.tag_name}`")

        lines.extend([
            "",
            "## 5. Prescribed Practice Drills",
        ])

        if not data["drills"]:
            lines.append("No specific drills required based on current review tags.")
        else:
            for d in data["drills"]:
                lines.append(f"* **{d['tag'].replace('_', ' ').title()}:** {d['drill']}")

        if data["notes"]:
            lines.extend([
                "",
                "## 6. Timestamped Coach Notes & Audio Memos",
            ])
            for n in data["notes"]:
                audio_str = "🎙️ [Voice Memo Attached]" if n.get("has_audio") else ""
                lines.append(
                    f"* **Round {n['round_number'] + 1}** [{n['formatted_time']}] ({n['author_type'].upper()}): {n['text_note']} {audio_str}"
                )

        return "\n".join(lines)

    def generate_html(
        self,
        metadata: MatchMetadata,
        events: list[MatchEvent],
        tags: list[VodTag],
        player_puuid: Optional[str] = None,
        notes: Optional[list[Any]] = None,
    ) -> str:
        """Generate a self-contained, printable dark-mode HTML review dossier."""
        data = self.generate_data(metadata, events, tags, player_puuid=player_puuid, notes=notes)
        m = data["metadata"]
        map_name = m.map_id.split("/")[-1].upper()
        total_flaws = len(tags)
        eco_kpis = data["economy"]["kpis"]

        # Tag frequency rows with visual meters
        tags_rows_html = ""
        for tc in data["tag_correlations"]:
            pct = round((tc.total_count / max(1, total_flaws)) * 100, 1)
            cat_lower = tc.category.lower()
            tags_rows_html += f"""
            <tr>
              <td><span class="badge {cat_lower}">{tc.category}</span></td>
              <td><strong>{tc.tag_name.replace('_', ' ')}</strong></td>
              <td>
                <div class="meter-bar-wrapper">
                  <div class="meter-bar-fill {cat_lower}" style="width: {pct}%;"></div>
                  <span class="meter-bar-val">{tc.total_count} ({pct}%)</span>
                </div>
              </td>
              <td class="text-center">{tc.first_death_count}</td>
              <td class="text-center">{tc.untraded_death_count}</td>
            </tr>
            """

        # Economy correlation table rows
        eco_rows_html = ""
        for er in data["economy"].get("flaw_rows", []):
            tier_class = er["dominant_tier"].lower().replace(" ", "-")
            eco_rows_html += f"""
            <tr>
              <td><strong>{er['tag_name'].replace('_', ' ')}</strong></td>
              <td><span class="badge {er['category'].lower()}">{er['category']}</span></td>
              <td class="text-center">{er['pistol_count']}</td>
              <td class="text-center">{er['eco_count']}</td>
              <td class="text-center">{er['force_count']}</td>
              <td class="text-center">{er['full_count']}</td>
              <td class="text-center"><strong>{er['total_count']}</strong></td>
              <td><span class="tier-badge {tier_class}">{er['dominant_tier'].upper()}</span></td>
              <td class="text-center"><strong>{er['eco_share_pct']}%</strong></td>
            </tr>
            """

        # Economy insights callouts
        eco_insights_html = ""
        for ins in data["economy"].get("coaching_insights", []):
            eco_insights_html += f"""
            <div class="insight-box">
              <span class="insight-icon">💡</span>
              <div class="insight-text">{html.escape(ins)}</div>
            </div>
            """

        # Coach vs Solo blindspots
        blindspots_html = ""
        for b in data["discrepancy"].blindspots:
            tc_str = TimelineSynchronizer.ms_to_display_time(b.timestamp_ms)
            blindspots_html += f"""
            <li class="blindspot-item">
              <span class="time-badge">{tc_str}</span>
              <span class="badge {b.tag_category.lower()}">{b.tag_category}</span>
              <strong>{b.tag_name.replace('_', ' ')}</strong>
              <span class="blindspot-note">— Identified by coach; missed in self-review</span>
            </li>
            """

        # Prescribed practice drills
        drills_html = ""
        for d in data["drills"]:
            drills_html += f"""
            <div class="drill-card">
              <div class="drill-title">{d['tag'].replace('_', ' ').upper()}</div>
              <div class="drill-text">{d['drill']}</div>
            </div>
            """

        # Timestamped Coach Notes & Audio Memos
        notes_html = ""
        for n in data["notes"]:
            audio_markup = ""
            if n.get("has_audio") and n.get("audio_url"):
                audio_markup = f"""
                <div class="note-audio-container">
                  <audio controls class="dossier-audio" src="{n['audio_url']}"></audio>
                </div>
                """
            notes_html += f"""
            <div class="note-card {n['author_type']}">
              <div class="note-card-header">
                <div class="note-badges">
                  <span class="time-badge">ROUND {n['round_number'] + 1} · {n['formatted_time']}</span>
                  <span class="author-badge {n['author_type']}">{n['author_type'].upper()} PERSPECTIVE</span>
                </div>
                {f'<span class="voice-indicator">🎙️ VOICE MEMO</span>' if n.get("has_audio") else ''}
              </div>
              <div class="note-card-body">{html.escape(n.get('text_note', ''))}</div>
              {audio_markup}
            </div>
            """

        # Round Recap Timeline
        recap_html = ""
        for r in data["recap_rounds"]:
            res_class = "won" if r["won"] else "lost"
            res_text = "VICTORY" if r["won"] else "DEFEAT"
            flaws_str = ", ".join(f.replace("_", " ") for f in r["flaws"]) if r["flaws"] else "Clean Round"
            recap_html += f"""
            <div class="round-card {res_class}">
              <div class="round-card-top">
                <span class="round-number">ROUND {r['round_number'] + 1}</span>
                <span class="round-outcome {res_class}">{res_text}</span>
              </div>
              <div class="round-card-meta">
                <span class="tier-pill">{r['tier']}</span>
                <span class="round-kd">{r['kills']}K / {r['deaths']}D</span>
              </div>
              <div class="round-flaws-text" title="{flaws_str}">{flaws_str}</div>
            </div>
            """

        # Generate serialized markdown for copy-to-clipboard
        md_content = self.generate_markdown(metadata, events, tags, player_puuid=player_puuid, notes=notes)
        md_json = json.dumps(md_content)
        download_filename = f"vallens-dossier-{map_name.lower()}-{m.match_id[:8]}.html"

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ValLens Coaching Dossier — {map_name} ({m.match_id[:8]})</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Teko:wght@500;700&family=Rajdhani:wght@500;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg-base: #0b1118;
      --bg-card: #121b24;
      --bg-sub: #19232d;
      --border: #2b3947;
      --text-main: #ece8e1;
      --text-muted: #8b97a5;
      --accent-red: #ff4655;
      --accent-cyan: #00f5d4;
      --accent-yellow: #ffd166;
      --accent-green: #10b981;
      --font-header: 'Teko', sans-serif;
      --font-tactical: 'Rajdhani', sans-serif;
      --font-body: 'Inter', sans-serif;
    }}

    * {{ box-sizing: border-box; }}
    body {{
      background: var(--bg-base);
      color: var(--text-main);
      font-family: var(--font-body);
      margin: 0;
      padding: 0;
      line-height: 1.5;
    }}

    /* Sticky Actions Toolbar */
    .dossier-toolbar {{
      position: sticky;
      top: 0;
      z-index: 100;
      background: rgba(18, 27, 36, 0.95);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--border);
      padding: 10px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .toolbar-brand {{
      display: flex;
      align-items: center;
      gap: 10px;
      font-family: var(--font-tactical);
      font-weight: 700;
      font-size: 15px;
      letter-spacing: 1px;
    }}
    .toolbar-logo {{
      background: var(--accent-red);
      color: #fff;
      font-family: var(--font-header);
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 16px;
    }}
    .toolbar-actions {{
      display: flex;
      gap: 10px;
    }}
    .tool-btn {{
      background: var(--bg-sub);
      border: 1px solid var(--border);
      color: var(--text-main);
      font-family: var(--font-tactical);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.5px;
      padding: 6px 14px;
      border-radius: 4px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s ease;
    }}
    .tool-btn:hover {{
      border-color: var(--accent-cyan);
      color: #fff;
    }}
    .tool-btn.primary {{
      background: rgba(0, 245, 212, 0.12);
      border-color: var(--accent-cyan);
      color: var(--accent-cyan);
    }}
    .tool-btn.primary:hover {{
      background: var(--accent-cyan);
      color: #0b1118;
    }}

    /* Main Container */
    .dossier-container {{
      max-width: 1040px;
      margin: 30px auto 60px;
      padding: 0 20px;
    }}

    /* Header Card */
    .header-card {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 28px 32px;
      margin-bottom: 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-left: 6px solid var(--accent-red);
      box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    }}
    .header-info-title {{
      font-family: var(--font-header);
      font-size: 38px;
      line-height: 1;
      letter-spacing: 1.5px;
      color: #fff;
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .map-badge {{
      background: rgba(255, 70, 85, 0.15);
      border: 1px solid var(--accent-red);
      color: var(--accent-red);
      font-size: 20px;
      padding: 2px 10px;
      border-radius: 4px;
    }}
    .header-meta {{
      font-family: var(--font-tactical);
      font-size: 14px;
      color: var(--text-muted);
      margin-top: 6px;
      display: flex;
      gap: 18px;
    }}
    .grade-box {{
      text-align: center;
    }}
    .grade-badge {{
      font-family: var(--font-header);
      font-size: 52px;
      font-weight: 700;
      color: var(--accent-cyan);
      background: rgba(0,245,212,0.1);
      border: 2px solid var(--accent-cyan);
      border-radius: 8px;
      padding: 2px 24px;
      line-height: 1;
      display: inline-block;
      box-shadow: 0 0 20px rgba(0,245,212,0.25);
    }}
    .grade-caption {{
      font-family: var(--font-tactical);
      font-size: 11px;
      font-weight: 700;
      color: var(--text-muted);
      letter-spacing: 1px;
      margin-top: 4px;
    }}

    /* KPI Grid */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(6, 1fr);
      gap: 12px;
      margin-bottom: 28px;
    }}
    .kpi-card {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 14px;
      text-align: center;
    }}
    .kpi-label {{
      font-family: var(--font-tactical);
      font-size: 11px;
      font-weight: 700;
      color: var(--text-muted);
      letter-spacing: 1px;
      margin-bottom: 4px;
      text-transform: uppercase;
    }}
    .kpi-val {{
      font-family: var(--font-header);
      font-size: 28px;
      font-weight: 700;
      color: #fff;
      line-height: 1.1;
    }}
    .kpi-val.cyan {{ color: var(--accent-cyan); }}
    .kpi-val.red {{ color: var(--accent-red); }}
    .kpi-val.green {{ color: var(--accent-green); }}
    .kpi-sub {{
      font-size: 11px;
      color: var(--text-muted);
      margin-top: 2px;
    }}

    /* Sections */
    .section-card {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 24px;
      margin-bottom: 24px;
    }}
    .section-title {{
      font-family: var(--font-tactical);
      font-size: 17px;
      font-weight: 700;
      letter-spacing: 1px;
      color: #fff;
      border-left: 3px solid var(--accent-red);
      padding-left: 10px;
      margin-bottom: 16px;
      text-transform: uppercase;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}

    /* Table Styles */
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th {{
      font-family: var(--font-tactical);
      font-size: 11px;
      font-weight: 700;
      color: var(--text-muted);
      letter-spacing: 0.8px;
      text-transform: uppercase;
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
      text-align: left;
      background: rgba(255,255,255,0.02);
    }}
    td {{
      padding: 10px 12px;
      border-bottom: 1px solid rgba(255,255,255,0.04);
      color: var(--text-main);
    }}
    tr:hover td {{
      background: rgba(255,255,255,0.02);
    }}
    .text-center {{ text-align: center; }}

    /* Badges */
    .badge {{
      display: inline-block;
      font-family: var(--font-tactical);
      font-size: 10px;
      font-weight: 700;
      padding: 2px 7px;
      border-radius: 3px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .badge.mechanics {{ background: rgba(255, 112, 166, 0.15); color: #ff70a6; border: 1px solid rgba(255, 112, 166, 0.3); }}
    .badge.positioning {{ background: rgba(112, 214, 255, 0.15); color: #70d6ff; border: 1px solid rgba(112, 214, 255, 0.3); }}
    .badge.utility {{ background: rgba(255, 214, 112, 0.15); color: #ffd670; border: 1px solid rgba(255, 214, 112, 0.3); }}
    .badge.decision {{ background: rgba(233, 255, 112, 0.15); color: #e9ff70; border: 1px solid rgba(233, 255, 112, 0.3); }}
    .badge.strength {{ background: rgba(0, 245, 212, 0.15); color: var(--accent-cyan); border: 1px solid rgba(0, 245, 212, 0.3); }}

    .tier-badge {{
      font-family: var(--font-tactical);
      font-size: 10px;
      font-weight: 700;
      padding: 2px 6px;
      border-radius: 3px;
      letter-spacing: 0.5px;
    }}
    .tier-badge.full-buy {{ background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); }}
    .tier-badge.force-buy {{ background: rgba(255, 209, 102, 0.15); color: #ffd166; border: 1px solid rgba(255, 209, 102, 0.3); }}
    .tier-badge.eco {{ background: rgba(255, 70, 85, 0.15); color: #ff4655; border: 1px solid rgba(255, 70, 85, 0.3); }}
    .tier-badge.pistol {{ background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid rgba(148, 163, 184, 0.3); }}

    /* Meter Bars */
    .meter-bar-wrapper {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .meter-bar-fill {{
      height: 8px;
      border-radius: 4px;
      background: var(--accent-red);
      transition: width 0.3s ease;
      min-width: 4px;
    }}
    .meter-bar-fill.mechanics {{ background: #ff70a6; }}
    .meter-bar-fill.positioning {{ background: #70d6ff; }}
    .meter-bar-fill.utility {{ background: #ffd670; }}
    .meter-bar-fill.decision {{ background: #e9ff70; }}
    .meter-bar-val {{
      font-size: 12px;
      font-family: var(--font-tactical);
      font-weight: 700;
      color: var(--text-muted);
      white-space: nowrap;
    }}

    /* Insights Callout */
    .insight-box {{
      background: rgba(16, 185, 129, 0.06);
      border-left: 3px solid var(--accent-green);
      padding: 10px 14px;
      border-radius: 4px;
      margin-top: 10px;
      display: flex;
      align-items: flex-start;
      gap: 10px;
    }}
    .insight-icon {{ font-size: 16px; line-height: 1.2; }}
    .insight-text {{ font-size: 13px; color: #e2e8f0; }}

    /* Round Cards Grid */
    .round-recap-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
      gap: 10px;
    }}
    .round-card {{
      background: var(--bg-sub);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .round-card.won {{ border-top: 3px solid var(--accent-green); }}
    .round-card.lost {{ border-top: 3px solid var(--accent-red); }}
    .round-card-top {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-family: var(--font-tactical);
      font-size: 12px;
      font-weight: 700;
    }}
    .round-outcome.won {{ color: var(--accent-green); font-size: 11px; }}
    .round-outcome.lost {{ color: var(--accent-red); font-size: 11px; }}
    .round-card-meta {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 11px;
      color: var(--text-muted);
    }}
    .round-flaws-text {{
      font-size: 11px;
      color: var(--text-muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    /* Prescribed Drills */
    .drill-card {{
      background: var(--bg-sub);
      border-left: 4px solid var(--accent-cyan);
      padding: 14px 18px;
      border-radius: 4px;
      margin-bottom: 12px;
    }}
    .drill-title {{
      font-family: var(--font-tactical);
      font-size: 14px;
      font-weight: 700;
      color: var(--accent-cyan);
      letter-spacing: 0.5px;
      margin-bottom: 4px;
    }}
    .drill-text {{
      font-size: 13px;
      color: #e2e8f0;
    }}

    /* Coach Notes */
    .note-card {{
      background: var(--bg-sub);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 14px 16px;
      margin-bottom: 12px;
      border-left: 4px solid var(--accent-yellow);
    }}
    .note-card-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }}
    .note-badges {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .time-badge {{
      font-family: monospace;
      font-size: 11px;
      color: var(--accent-cyan);
      background: rgba(0, 245, 212, 0.1);
      padding: 2px 6px;
      border-radius: 3px;
    }}
    .author-badge {{
      font-family: var(--font-tactical);
      font-size: 11px;
      font-weight: 700;
      color: var(--text-muted);
    }}
    .voice-indicator {{
      font-family: var(--font-tactical);
      font-size: 11px;
      font-weight: 700;
      color: var(--accent-yellow);
    }}
    .note-card-body {{
      font-size: 13px;
      color: #ece8e1;
    }}
    .dossier-audio {{
      margin-top: 8px;
      width: 100%;
      height: 32px;
    }}

    /* Blindspots List */
    .blindspots-list {{
      list-style: none;
      padding: 0;
      margin: 0;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .blindspot-item {{
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 13px;
    }}
    .blindspot-note {{
      color: var(--text-muted);
      font-size: 12px;
    }}

    /* Print Styles */
    @media print {{
      body {{
        background: #fff !important;
        color: #111 !important;
      }}
      .dossier-toolbar {{ display: none !important; }}
      .dossier-container {{
        max-width: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
      }}
      .header-card, .section-card, .kpi-card, .round-card, .drill-card, .note-card {{
        background: #fff !important;
        border: 1px solid #ccc !important;
        box-shadow: none !important;
        color: #111 !important;
        page-break-inside: avoid;
      }}
      .header-info-title, .section-title, .kpi-val, .drill-title {{
        color: #000 !important;
      }}
      th {{ background: #f0f0f0 !important; color: #333 !important; }}
      td {{ color: #111 !important; border-bottom: 1px solid #eee !important; }}
      .meter-bar-fill {{ print-color-adjust: exact; -webkit-print-color-adjust: exact; }}
      .badge, .tier-badge {{ print-color-adjust: exact; -webkit-print-color-adjust: exact; }}
    }}

    @media (max-width: 768px) {{
      .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }}
      .header-card {{ flex-direction: column; gap: 16px; text-align: center; }}
      .header-info-title {{ justify-content: center; }}
    }}
  </style>
</head>
<body>

  <!-- Sticky Actions Toolbar -->
  <div class="dossier-toolbar">
    <div class="toolbar-brand">
      <span class="toolbar-logo">VL</span>
      <span>VALLENS COACHING REVIEW DOSSIER</span>
    </div>
    <div class="toolbar-actions">
      <button class="tool-btn" onclick="copyMarkdownSummary()">📋 COPY SUMMARY [MD]</button>
      <button class="tool-btn" onclick="downloadDossierHtml()">💾 DOWNLOAD DOSSIER</button>
      <button class="tool-btn primary" onclick="window.print()">🖨️ PRINT / PDF</button>
    </div>
  </div>

  <div class="dossier-container">
    <!-- Header Card -->
    <div class="header-card">
      <div>
        <div class="header-info-title">
          <span>COACHING REPORT CARD</span>
          <span class="map-badge">{map_name}</span>
        </div>
        <div class="header-meta">
          <span><strong>MATCH ID:</strong> {m.match_id}</span>
          <span><strong>ROUNDS:</strong> {data['total_rounds']}</span>
          <span><strong>DATE:</strong> {TimelineSynchronizer.ms_to_display_time(m.match_duration)} DURATION</span>
        </div>
      </div>
      <div class="grade-box">
        <div class="grade-badge">{data['grade']}</div>
        <div class="grade-caption">PERFORMANCE GRADE</div>
      </div>
    </div>

    <!-- Executive KPI Grid -->
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">K/D RATIO</div>
        <div class="kpi-val">{data['kd_ratio']}</div>
        <div class="kpi-sub">{data['kills']} Kills / {data['deaths']} Deaths</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">OPENING DUELS</div>
        <div class="kpi-val cyan">{data['first_bloods']} FB</div>
        <div class="kpi-sub">{data['first_deaths']} First Deaths</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">TRADE EFFICIENCY</div>
        <div class="kpi-val green">{data['trade_rate']}%</div>
        <div class="kpi-sub">{data['traded_deaths']} of {data['deaths']} traded</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">COACH AGREEMENT</div>
        <div class="kpi-val">{int(data['discrepancy'].agreement_score * 100)}%</div>
        <div class="kpi-sub">{len(data['discrepancy'].blindspots)} blindspots noted</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">ECO FLAW RATE</div>
        <div class="kpi-val red">{eco_kpis.get('eco_flaw_rate', 0)}%</div>
        <div class="kpi-sub">{eco_kpis.get('eco_flaws', 0)} flaws on save rounds</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">TOP ECO MISTAKE</div>
        <div class="kpi-val cyan" style="font-size: 20px;">{eco_kpis.get('most_frequent_eco_flaw', 'None').replace('_', ' ').upper()}</div>
        <div class="kpi-sub">Highest save-round count</div>
      </div>
    </div>

    <!-- Section 1: Flaw Habit Distribution -->
    <div class="section-card">
      <div class="section-title">
        <span>1. REVIEW TAG CORRELATIONS & RECURRING FLAWS</span>
        <span style="font-size: 13px; color: var(--text-muted);">{total_flaws} TOTAL TAGS LOGGED</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>CATEGORY</th>
            <th>FLAW TAG</th>
            <th>OCCURRENCE & SHARE</th>
            <th class="text-center">FIRST DEATHS</th>
            <th class="text-center">UN-TRADED DEATHS</th>
          </tr>
        </thead>
        <tbody>
          {tags_rows_html or "<tr><td colspan='5' style='text-align:center;'>No review tags logged for this match.</td></tr>"}
        </tbody>
      </table>
    </div>

    <!-- Section 2: Economy vs Flaw Cross-Tabulation -->
    <div class="section-card">
      <div class="section-title">
        <span>2. ECONOMY VS. FLAW CORRELATION MATRIX</span>
        <span style="font-size: 13px; color: var(--accent-green);">FULL BUY WIN RATE: {eco_kpis.get('full_buy_win_rate', 0)}%</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>FLAW TAG</th>
            <th>CATEGORY</th>
            <th class="text-center">PISTOL</th>
            <th class="text-center">ECO</th>
            <th class="text-center">FORCE</th>
            <th class="text-center">FULL BUY</th>
            <th class="text-center">TOTAL</th>
            <th>DOMINANT TIER</th>
            <th class="text-center">ECO SHARE</th>
          </tr>
        </thead>
        <tbody>
          {eco_rows_html or "<tr><td colspan='9' style='text-align:center;'>No economy cross-tabulation data.</td></tr>"}
        </tbody>
      </table>
      <div style="margin-top: 14px;">
        {eco_insights_html}
      </div>
    </div>

    <!-- Section 3: Coach Alignment & Cognitive Blindspots -->
    <div class="section-card">
      <div class="section-title">
        <span>3. COACH VS. SOLO ALIGNMENT & BLINDSPOTS</span>
        <span style="font-size: 13px; color: var(--accent-cyan);">{int(data['discrepancy'].agreement_score * 100)}% CONSENSUS</span>
      </div>
      <ul class="blindspots-list">
        {blindspots_html or "<li>No blindspots detected; complete strategic alignment with coaching staff!</li>"}
      </ul>
    </div>

    <!-- Section 4: Round-by-Round Timeline Recap -->
    <div class="section-card">
      <div class="section-title">4. ROUND-BY-ROUND TIMELINE RECAP</div>
      <div class="round-recap-grid">
        {recap_html or "<div>No rounds logged.</div>"}
      </div>
    </div>

    <!-- Section 5: Prescribed Practice Regimen -->
    <div class="section-card">
      <div class="section-title">5. ACTIONABLE PRACTICE DRILLS & AIM PROTOCOLS</div>
      {drills_html or "<div style='color: var(--text-muted); font-size: 13px;'>No specific training routine required. Fundamental mechanical discipline is sound.</div>"}
    </div>

    <!-- Section 6: Coach Notes & Audio Memos -->
    <div class="section-card">
      <div class="section-title">
        <span>6. TIMESTAMPED COACH OBSERVATIONS & VOICE MEMOS</span>
        <span style="font-size: 13px; color: var(--text-muted);">{len(data['notes'])} NOTES LOGGED</span>
      </div>
      {notes_html or "<div style='color: var(--text-muted); font-size: 13px;'>No timestamped coach notes recorded for this match.</div>"}
    </div>

  </div>

  <script>
    const MARKDOWN_CONTENT = {md_json};

    function copyMarkdownSummary() {{
      navigator.clipboard.writeText(MARKDOWN_CONTENT).then(() => {{
        alert("Coaching Report Markdown copied to clipboard!");
      }}).catch(() => {{
        alert("Failed to copy markdown.");
      }});
    }}

    function downloadDossierHtml() {{
      const blob = new Blob([document.documentElement.outerHTML], {{ type: 'text/html;charset=utf-8' }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = '{download_filename}';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }}
  </script>
</body>
</html>
"""
