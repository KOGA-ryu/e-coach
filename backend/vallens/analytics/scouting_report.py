"""Pro Scouting Dossier & Offline Export Engine.

Strictly 100% post-game analysis and compilation.
Generates comprehensive offline dossiers combining:
- 6-Axis Tactical Skill Radar & Radiant Benchmarks
- Trade Frag Efficiency & Spacing Matrix
- Win Probability Curves & Pivotal Momentum Swings
- Utility ROI & Ability Burn Scorecard
- Economy Discipline & Flaw Trajectory
- Printable / Save-as-PDF optimized standalone HTML report
"""

from dataclasses import dataclass
import json
import math
from typing import Any, Optional

from vallens.analytics.career_radar import CareerRadarEngine
from vallens.analytics.drills import TrainingRoutineEngine
from vallens.analytics.economy import EconomyCorrelationEngine
from vallens.analytics.trade_matrix import TradeMatrixEngine
from vallens.analytics.utility_roi import UtilityRoiEngine
from vallens.analytics.win_probability import WinProbabilityEngine
from vallens.db.repository import MatchRepository
from vallens.models import MatchMetadata, MatchPlayer


class ScoutingReportGenerator:
    """Compiles multi-engine analytics into an executive pro scouting report."""

    def __init__(
        self,
        repo: MatchRepository,
        trade_engine: Optional[TradeMatrixEngine] = None,
        win_prob_engine: Optional[WinProbabilityEngine] = None,
        career_radar_engine: Optional[CareerRadarEngine] = None,
        utility_roi_engine: Optional[UtilityRoiEngine] = None,
        economy_engine: Optional[EconomyCorrelationEngine] = None,
        drills_engine: Optional[TrainingRoutineEngine] = None,
    ):
        self.repo = repo
        self.trade_engine = trade_engine or TradeMatrixEngine(repo)
        self.win_prob_engine = win_prob_engine or WinProbabilityEngine(repo)
        self.utility_roi_engine = utility_roi_engine or UtilityRoiEngine(repo)
        self.economy_engine = economy_engine or EconomyCorrelationEngine()
        self.career_radar_engine = career_radar_engine or CareerRadarEngine(
            repo,
            economy_engine=self.economy_engine,
            utility_roi_engine=self.utility_roi_engine,
        )
        self.drills_engine = drills_engine or TrainingRoutineEngine()

    def generate_dossier_data(
        self, match_id: str, player_puuid: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        """Generate structured data object containing all dossier sections."""
        match = self.repo.get_match(match_id)
        if not match:
            return None

        events = self.repo.get_events(match_id)
        players = self.repo.get_match_players(match_id)
        tags = self.repo.get_tags(match_id)
        notes = self.repo.get_notes(match_id)

        # Determine target player (Ace by default)
        target_player: Optional[MatchPlayer] = None
        if player_puuid:
            target_player = next((p for p in players if p.player_puuid == player_puuid), None)
        if not target_player:
            target_player = next(
                (p for p in players if "ace" in p.player_puuid.lower() or "ace" in p.game_name.lower()),
                players[0] if players else None,
            )

        target_puuid = target_player.player_puuid if target_player else "player-ace-001"
        target_name = target_player.game_name if target_player else "Ace"

        # 1. Trade Matrix
        trade_report = self.trade_engine.analyze_match_trades(
            match_id=match_id, events=events, players=players, tags=tags
        )

        # 2. Win Probability & Clutch
        win_prob_report = self.win_prob_engine.calculate_match_probability(
            match_id=match_id, events=events, players=players
        )

        # 3. Career Profile & 6-Axis Radar
        career_profile = self.career_radar_engine.generate_career_profile(
            player_puuid=target_puuid, limit=10
        )

        # 4. Utility ROI
        utility_report = self.utility_roi_engine.analyze_match_utility(match_id)

        # 5. Economy Analysis
        eco_report = self.economy_engine.analyze(
            match_id=match_id, events=events, tags=tags, player_puuid=target_puuid
        )
        eco_kpis = eco_report.kpis

        # 6. Practice Drills
        routine = self.drills_engine.generate_routine(
            metadata=match, events=events, tags=tags, player_puuid=target_puuid
        )
        drill_items = [
            {
                "name": pr.range_exercise.exercise_name,
                "category": pr.category,
                "target_flaw": pr.tag_name,
                "difficulty": pr.priority,
                "duration_min": pr.estimated_time_min,
                "description": pr.range_exercise.coaching_cue,
                "instructions": pr.range_exercise.instructions,
            }
            for pr in routine.prescriptions
        ]

        # Map display name
        map_name = match.map_id.split("/")[-1] if "/" in match.map_id else match.map_id

        # Player stats
        k = target_player.kills if target_player else sum(1 for e in events if e.event_type == "kill" and e.player_puuid == target_puuid)
        d = target_player.deaths if target_player else sum(1 for e in events if e.event_type == "death" and e.player_puuid == target_puuid)
        a = target_player.assists if target_player else 0
        kd = round(k / max(1, d), 2)

        return {
            "match_id": match_id,
            "map_name": map_name,
            "game_mode": match.game_mode.split("/")[-1].replace("GameMode_C", "").replace("GameMode", ""),
            "duration_ms": match.match_duration,
            "player": {
                "puuid": target_puuid,
                "name": target_name,
                "team_id": target_player.team_id if target_player else "Blue",
                "character_id": target_player.character_id if target_player else "Unknown",
                "kills": k,
                "deaths": d,
                "assists": a,
                "kd_ratio": kd,
                "score": target_player.score if target_player else 0,
            },
            "career_radar": career_profile.to_dict(),
            "trade_matrix": trade_report.to_dict(),
            "win_probability": win_prob_report.to_dict(),
            "utility_roi": utility_report.to_dict(),
            "economy": {
                "full_buy_win_rate": round(eco_kpis.get("full_buy_win_rate", 0.0), 1),
                "eco_win_rate": round(eco_kpis.get("eco_win_rate", 0.0), 1),
                "force_buy_win_rate": round(eco_kpis.get("force_buy_win_rate", 0.0), 1),
                "wasteful_buys_count": eco_kpis.get("eco_flaws", 0),
                "total_rounds": len(eco_report.rounds),
            },
            "coach_notes": [
                {
                    "note_id": n.note_id,
                    "round_number": n.round_number,
                    "timestamp_ms": n.timestamp_ms,
                    "author": n.author_type,
                    "text": n.text_note,
                }
                for n in notes
            ],
            "tags_count": len(tags),
            "drills": drill_items,
        }

    def generate_standalone_html(
        self, match_id: str, player_puuid: Optional[str] = None
    ) -> str:
        """Compile a complete, self-contained printable HTML scouting report."""
        data = self.generate_dossier_data(match_id, player_puuid)
        if not data:
            return "<html><body><h1>Match Not Found</h1></body></html>"

        p = data["player"]
        radar = data["career_radar"].get("radar_axes", {})
        bench = data["career_radar"].get("pro_benchmarks", {})
        trades = data["trade_matrix"]
        win_prob = data["win_probability"]
        util = data["utility_roi"]
        eco = data["economy"]
        drills = data["drills"]
        notes = data["coach_notes"]

        # SVG Radar calculation
        axes = [
            ("AIM", radar.get("aim", 50), bench.get("aim", 85)),
            ("ECONOMY", radar.get("economy", 50), bench.get("economy", 80)),
            ("UTILITY", radar.get("utility", 50), bench.get("utility", 82)),
            ("CLUTCH", radar.get("clutch", 50), bench.get("clutch", 78)),
            ("SURVIVAL", radar.get("survivability", 50), bench.get("survivability", 80)),
            ("VERSATILITY", radar.get("versatility", 50), bench.get("versatility", 75)),
        ]

        center_x, center_y, max_r = 160, 160, 110
        player_pts = []
        bench_pts = []
        labels_svg = []

        for i, (label, val, b_val) in enumerate(axes):
            angle = (math.pi * 2 / 6) * i - (math.pi / 2)
            # Player point
            r_p = (val / 100.0) * max_r
            px = center_x + r_p * math.cos(angle)
            py = center_y + r_p * math.sin(angle)
            player_pts.append(f"{px:.1f},{py:.1f}")

            # Benchmark point
            r_b = (b_val / 100.0) * max_r
            bx = center_x + r_b * math.cos(angle)
            by = center_y + r_b * math.sin(angle)
            bench_pts.append(f"{bx:.1f},{by:.1f}")

            # Label pos
            lx = center_x + (max_r + 26) * math.cos(angle)
            ly = center_y + (max_r + 26) * math.sin(angle) + 4
            labels_svg.append(
                f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" font-size="10" fill="#a0aab8" font-weight="700">{label} ({int(val)})</text>'
            )

        player_poly = " ".join(player_pts)
        bench_poly = " ".join(bench_pts)

        # Concentric guide webs
        rings = [0.25, 0.5, 0.75, 1.0]
        guide_polys = []
        for factor in rings:
            r = max_r * factor
            ring_pts = [
                f"{center_x + r * math.cos((math.pi * 2 / 6) * j - math.pi / 2):.1f},{center_y + r * math.sin((math.pi * 2 / 6) * j - math.pi / 2):.1f}"
                for j in range(6)
            ]
            guide_polys.append(
                f'<polygon points="{" ".join(ring_pts)}" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>'
            )

        # Win Prob SVG Sparkline calculation
        timeline = win_prob.get("match_timeline", [])
        sparkline_svg = ""
        if timeline:
            sw_w, sw_h = 600, 100
            step = sw_w / max(1, len(timeline) - 1)
            path_pts = []
            circles = []
            for idx, pt in enumerate(timeline):
                x = idx * step
                y = sw_h - (pt["team_a_prob"] * sw_h)
                path_pts.append(f"{x:.1f},{y:.1f}")
                if pt["is_swing"]:
                    circles.append(
                        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="#ff4655" stroke="#fff" stroke-width="1.5"><title>Swing: {pt["description"]}</title></circle>'
                    )
            path_d = "M " + " L ".join(path_pts)
            sparkline_svg = f"""
            <svg viewBox="0 0 {sw_w} {sw_h}" class="sparkline-svg">
              <defs>
                <linearGradient id="prob-grad" x1="0%" y1="0%" x2="0%" y2="100%">
                  <stop offset="0%" stop-color="#00f5d4" stop-opacity="0.3"/>
                  <stop offset="100%" stop-color="#ff4655" stop-opacity="0.05"/>
                </linearGradient>
              </defs>
              <line x1="0" y1="50" x2="{sw_w}" y2="50" stroke="rgba(255,255,255,0.15)" stroke-dasharray="4,4"/>
              <path d="{path_d}" fill="none" stroke="#00f5d4" stroke-width="2.5"/>
              {' '.join(circles)}
            </svg>
            """

        # Generate HTML string
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>ValLens Pro Scouting Dossier - {data['map_name']} ({p['name']})</title>
  <style>
    :root {{
      --bg-dark: #0f1923;
      --card-bg: #1a222d;
      --card-border: #2c3644;
      --accent-red: #ff4655;
      --accent-cyan: #00f5d4;
      --accent-gold: #ffd166;
      --accent-green: #00e676;
      --text-main: #ece8e1;
      --text-muted: #8b97a5;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background: var(--bg-dark);
      color: var(--text-main);
      padding: 32px 24px;
      line-height: 1.5;
    }}
    .dossier-wrapper {{
      max-width: 1080px;
      margin: 0 auto;
    }}
    .header-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 20px;
      border-bottom: 2px solid var(--accent-red);
      margin-bottom: 28px;
    }}
    .brand-title {{
      font-size: 26px;
      font-weight: 900;
      letter-spacing: 1.5px;
      color: #fff;
    }}
    .brand-title span {{ color: var(--accent-red); }}
    .badge-bar {{
      display: flex;
      gap: 12px;
      align-items: center;
    }}
    .pill {{
      padding: 6px 14px;
      border-radius: 4px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.5px;
      text-transform: uppercase;
      background: #232d3b;
      border: 1px solid var(--card-border);
    }}
    .pill.red {{ background: rgba(255,70,85,0.15); border-color: var(--accent-red); color: var(--accent-red); }}
    .pill.cyan {{ background: rgba(0,245,212,0.15); border-color: var(--accent-cyan); color: var(--accent-cyan); }}
    .pill.gold {{ background: rgba(255,209,102,0.15); border-color: var(--accent-gold); color: var(--accent-gold); }}

    .kpi-row {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 16px;
      margin-bottom: 28px;
    }}
    .kpi-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 16px;
      text-align: center;
    }}
    .kpi-label {{
      font-size: 11px;
      color: var(--text-muted);
      font-weight: 700;
      letter-spacing: 0.8px;
      margin-bottom: 6px;
    }}
    .kpi-value {{
      font-size: 24px;
      font-weight: 900;
      color: #fff;
    }}
    .kpi-value.cyan {{ color: var(--accent-cyan); }}
    .kpi-value.green {{ color: var(--accent-green); }}
    .kpi-value.gold {{ color: var(--accent-gold); }}

    .grid-2col {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 24px;
      margin-bottom: 28px;
    }}
    .panel {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 20px;
    }}
    .panel-title {{
      font-size: 14px;
      font-weight: 800;
      letter-spacing: 1px;
      text-transform: uppercase;
      color: #fff;
      margin-bottom: 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      padding-bottom: 8px;
    }}

    .radar-svg {{
      width: 100%;
      max-width: 320px;
      height: auto;
      margin: 0 auto;
      display: block;
    }}
    .radar-legend {{
      display: flex;
      justify-content: center;
      gap: 20px;
      margin-top: 12px;
      font-size: 11px;
      color: var(--text-muted);
      font-weight: 600;
    }}
    .legend-box {{
      display: inline-block;
      width: 12px;
      height: 12px;
      margin-right: 6px;
      vertical-align: middle;
      border-radius: 2px;
    }}

    .data-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
      margin-top: 10px;
    }}
    .data-table th, .data-table td {{
      padding: 8px 12px;
      text-align: left;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }}
    .data-table th {{
      color: var(--text-muted);
      font-weight: 700;
      letter-spacing: 0.5px;
    }}

    .sparkline-container {{
      background: #141b24;
      border-radius: 6px;
      padding: 12px;
      border: 1px solid var(--card-border);
      margin-top: 8px;
    }}
    .sparkline-svg {{
      width: 100%;
      height: 100px;
      display: block;
    }}

    .drill-card {{
      background: #131a24;
      border-left: 3px solid var(--accent-cyan);
      padding: 12px 16px;
      border-radius: 4px;
      margin-bottom: 12px;
    }}
    .drill-name {{
      font-weight: 800;
      font-size: 13px;
      color: #fff;
    }}
    .drill-desc {{
      font-size: 12px;
      color: var(--text-muted);
      margin: 4px 0;
    }}

    .action-toolbar {{
      margin-bottom: 24px;
      display: flex;
      gap: 12px;
    }}
    .btn {{
      padding: 8px 18px;
      font-size: 12px;
      font-weight: 800;
      border-radius: 4px;
      cursor: pointer;
      border: none;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .btn-red {{ background: var(--accent-red); color: #fff; }}
    .btn-outline {{ background: transparent; border: 1px solid var(--card-border); color: #fff; }}

    @media print {{
      body {{ background: #fff !important; color: #111 !important; padding: 0; }}
      .action-toolbar {{ display: none !important; }}
      .panel, .kpi-card {{ background: #fff !important; border: 1px solid #ddd !important; break-inside: avoid; page-break-inside: avoid; }}
      .brand-title, .kpi-value, .panel-title {{ color: #111 !important; }}
      .kpi-label, .drill-desc, .data-table th {{ color: #555 !important; }}
      .sparkline-container {{ background: #fafafa !important; border: 1px solid #ccc !important; }}
      svg text {{ fill: #333 !important; }}
      .dossier-wrapper {{ max-width: 100%; }}
    }}
  </style>
</head>
<body>
  <div class="dossier-wrapper">
    <div class="action-toolbar">
      <button class="btn btn-red" onclick="window.print()">🖨️ Save as PDF / Print</button>
      <button class="btn btn-outline" onclick="window.close()">✕ Close Dossier</button>
    </div>

    <div class="header-bar">
      <div>
        <div class="brand-title">VAL<span>LENS</span> PRO SCOUTING DOSSIER</div>
        <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
          Match {data['match_id'][:18]}... • Verified Post-Match Telemetry
        </div>
      </div>
      <div class="badge-bar">
        <span class="pill red">{data['map_name']}</span>
        <span class="pill cyan">{p['name']} ({p['team_id']})</span>
        <span class="pill gold">{data['game_mode']}</span>
      </div>
    </div>

    <!-- Match KPIs -->
    <div class="kpi-row">
      <div class="kpi-card">
        <div class="kpi-label">K / D (RATIO)</div>
        <div class="kpi-value cyan">{p['kills']} / {p['deaths']} ({p['kd_ratio']})</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">COMBAT SCORE</div>
        <div class="kpi-value gold">{p['score']}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">TRADE CONVERSION</div>
        <div class="kpi-value green">{trades.get('match_trade_conversion_pct', 0)}%</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">UTILITY ROI</div>
        <div class="kpi-value cyan">{util.get('match_roi_score', 0)}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">RANK READINESS</div>
        <div class="kpi-value gold">{data['career_radar'].get('rank_readiness_score', 0)} / 100</div>
      </div>
    </div>

    <!-- 6-Axis Radar & Tactical Flaws -->
    <div class="grid-2col">
      <div class="panel">
        <div class="panel-title">
          <span>🕸️ 6-Axis Tactical Skill Radar</span>
          <span style="font-size: 11px; color: var(--accent-gold);">Pro Calibrated</span>
        </div>
        <svg viewBox="0 0 320 320" class="radar-svg">
          {' '.join(guide_polys)}
          <polygon points="{bench_poly}" fill="none" stroke="#ffd166" stroke-width="1.8" stroke-dasharray="4,4"/>
          <polygon points="{player_poly}" fill="rgba(0,245,212,0.25)" stroke="#00f5d4" stroke-width="2.5"/>
          {' '.join(labels_svg)}
        </svg>
        <div class="radar-legend">
          <span><span class="legend-box" style="background: #00f5d4;"></span> {p['name']} Performance</span>
          <span><span class="legend-box" style="background: #ffd166;"></span> Radiant Benchmark</span>
        </div>
      </div>

      <div class="panel">
        <div class="panel-title">
          <span>🤝 Trade Frag & Spacing Matrix</span>
          <span style="font-size: 11px; color: var(--accent-green);">3.0s Window</span>
        </div>
        <table class="data-table">
          <tr><th>Team Trade Conversion</th><td><strong>{trades.get('match_trade_conversion_pct', 0)}%</strong></td></tr>
          <tr><th>Opening Death Traded %</th><td><strong>{trades.get('first_death_trade_pct', 0)}%</strong></td></tr>
          <tr><th>Isolated Spacing Deaths</th><td><strong style="color: var(--accent-red);">{trades.get('total_spacing_flaws', 0)}</strong></td></tr>
          <tr><th>Total Match Deaths</th><td>{trades.get('total_deaths', 0)} ({trades.get('total_traded_deaths', 0)} Traded)</td></tr>
        </table>

        <div class="panel-title" style="margin-top: 20px;">
          <span>🔮 Utility Efficiency Scorecard</span>
        </div>
        <table class="data-table">
          <tr><th>Total Abilities Deployed</th><td>{util.get('total_abilities_cast', 0)}</td></tr>
          <tr><th>Flash Frag Conversion</th><td>{util.get('flash_conversion_rate', 0)}%</td></tr>
          <tr><th>Smoke Zone Isolation</th><td>{util.get('smoke_effectiveness_score', 0)} / 100</td></tr>
          <tr><th>Ability Economy Wasted</th><td>${util.get('total_credits_wasted', 0)}</td></tr>
        </table>
      </div>
    </div>

    <!-- Win Probability Timeline -->
    <div class="panel" style="margin-bottom: 28px;">
      <div class="panel-title">
        <span>📈 Post-Match Win Expectancy Curve & Momentum Swings</span>
        <span style="font-size: 11px; color: var(--accent-red);">{win_prob.get('critical_swings_count', 0)} Critical Swings (≥30%)</span>
      </div>
      <div class="sparkline-container">
        {sparkline_svg}
      </div>
      <div style="display: flex; justify-content: space-between; margin-top: 8px; font-size: 11px; color: var(--text-muted);">
        <span>Round 1 Start (50%)</span>
        <span>Clutch Conversion: {win_prob.get('clutch_conversion_pct', 0)}% ({win_prob.get('clutches_won', 0)}/{win_prob.get('clutches_attempted', 0)})</span>
        <span>Match Conclusion</span>
      </div>
    </div>

    <!-- Targeted Practice Regimen -->
    <div class="panel">
      <div class="panel-title">
        <span>🎯 Prescribed Post-Match Training Regimen</span>
        <span style="font-size: 11px; color: var(--accent-cyan);">Actionable Drills</span>
      </div>
      <div>
        {''.join(f'''
        <div class="drill-card">
          <div class="drill-name">{dr['name']} • <span style="color: var(--accent-gold);">{dr['difficulty']}</span> ({dr['duration_min']} mins)</div>
          <div class="drill-desc">{dr['description']}</div>
        </div>
        ''' for dr in drills[:3])}
      </div>
    </div>

  </div>
</body>
</html>
"""
        return html
