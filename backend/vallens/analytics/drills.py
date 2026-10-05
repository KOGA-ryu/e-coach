"""Actionable practice drill protocols, training routines, and Aim Lab playlist exporter."""

from dataclasses import dataclass, field
import json
from typing import Any, Optional

from vallens.analytics.correlations import FlawCorrelationEngine
from vallens.models import MatchEvent, MatchMetadata, VodTag


@dataclass
class RangeExercise:
    exercise_name: str
    weapon: str
    target_mode: str
    armor_setting: str
    duration_minutes: int
    instructions: list[str]
    coaching_cue: str


@dataclass
class AimTrainerScenario:
    scenario_name: str
    platform: str
    task_type: str
    recommended_plays: int
    target_score: str
    notes: str


@dataclass
class MapSpecificDrill:
    map_name: str
    callout: str
    objective: str
    setup: str
    drills: list[str]


@dataclass
class PrescribedFlawDrill:
    tag_name: str
    category: str
    correlated_flaw_count: int
    untraded_deaths_correlated: int
    first_deaths_correlated: int
    priority: str  # 'HIGH', 'MEDIUM', 'LOW'
    estimated_time_min: int
    range_exercise: RangeExercise
    aim_trainer_scenarios: list[AimTrainerScenario]
    map_drill: Optional[MapSpecificDrill]


@dataclass
class TrainingRoutineResult:
    match_id: str
    map_name: str
    total_routine_duration_min: int
    primary_focus: str
    summary: str
    prescriptions: list[PrescribedFlawDrill]
    aimlab_playlist: dict[str, Any]
    markdown_routine: str


# Rich Catalog of Professional Training Prescriptions
DRILL_REGISTRY: dict[str, dict[str, Any]] = {
    "crosshair_placement": {
        "category": "Mechanics",
        "estimated_time_min": 15,
        "range_exercise": {
            "exercise_name": "Sheriff Head-Level Micro-Clearing",
            "weapon": "Sheriff",
            "target_mode": "Eliminate 50 Bots",
            "armor_setting": "Heavy Armor",
            "duration_minutes": 10,
            "instructions": [
                "Position at the range counter 15m away from practice bots.",
                "Align crosshair horizontally with bot neck-line before strafing out of cover.",
                "Counter-strafe to zero velocity, fire exactly 1 bullet, and immediately strafe behind pillar.",
                "Zero crouching permitted; maintain rhythmic A-D movement.",
            ],
            "coaching_cue": "Never adjust vertical crosshair height while turning angles; lock elevation before clearing.",
        },
        "aim_trainer_scenarios": [
            {
                "scenario_name": "VT Angleshot Valorant",
                "platform": "Aim Lab",
                "task_type": "Micro-flick",
                "recommended_plays": 3,
                "target_score": "85,000+",
                "notes": "Trains instantaneous horizontal snapping without vertical drift.",
            },
            {
                "scenario_name": "VT Sixshot Precision",
                "platform": "Aim Lab / KovaaKs",
                "task_type": "Dynamic Clicking",
                "recommended_plays": 3,
                "target_score": "1,150+",
                "notes": "Forces target confirmation before click; eliminates early trigger panics.",
            },
        ],
        "map_drills": {
            "Ascent": {
                "callout": "A-Main & Mid Courtyard",
                "objective": "Pre-aim Ascent A-Main corner without over-clearing into Wine.",
                "setup": "Custom game with Ghost; spawn on Attack.",
                "drills": [
                    "Slice the pie from A-Lobby around the double-box corner into A-Main.",
                    "Pre-aim Generator head-glitch and A-Site dice sequentially without sprinting.",
                ],
            },
            "Haven": {
                "callout": "A-Long & Garage Doors",
                "objective": "Hold head-level crosshair against common operator off-angles.",
                "setup": "Custom game with Guardian on Defense.",
                "drills": [
                    "Hold A-Long corner at head level; jiggle to bait utility before anchoring.",
                ],
            },
        },
    },
    "panic_spray": {
        "category": "Mechanics",
        "estimated_time_min": 15,
        "range_exercise": {
            "exercise_name": "Phantom 4-Bullet Burst & Reset Discipline",
            "weapon": "Phantom / Vandal",
            "target_mode": "Practice Strafe Bots",
            "armor_setting": "Heavy Armor",
            "duration_minutes": 8,
            "instructions": [
                "Set Range bots to 'Strafe On'.",
                "Fire strictly 2-3 round bursts at moving bots.",
                "If the target does not die in 3 bullets, release mouse1, counter-strafe 2 steps, and re-burst.",
                "Under zero circumstances commit to a 5+ round spray.",
            ],
            "coaching_cue": "Re-peeking after a reset yields 3x higher duel win rates than committed crouch-spraying.",
        },
        "aim_trainer_scenarios": [
            {
                "scenario_name": "VT Microflex Speed",
                "platform": "Aim Lab",
                "task_type": "Micro-flick",
                "recommended_plays": 3,
                "target_score": "90,000+",
                "notes": "High-density micro-flicks to restore calm trigger discipline.",
            },
            {
                "scenario_name": "Floating Heads Timing",
                "platform": "Aim Lab",
                "task_type": "Target Switching",
                "recommended_plays": 2,
                "target_score": "75,000+",
                "notes": "Teaches deliberate pausing between target transfers.",
            },
        ],
        "map_drills": {
            "Ascent": {
                "callout": "B-Main Choke",
                "objective": "Practice 3-round burst and fall back to stairs.",
                "setup": "Custom match; place Sova dart or Sage slow.",
                "drills": ["Fire 3 bullets into B-Main choke and instantly dash or strafe behind lane wall."],
            },
        },
    },
    "whiffed_spray": {
        "category": "Mechanics",
        "estimated_time_min": 12,
        "range_exercise": {
            "exercise_name": "First-Bullet Accuracy Protocol",
            "weapon": "Guardian",
            "target_mode": "Eliminate 50 Bots",
            "armor_setting": "Heavy Armor",
            "duration_minutes": 8,
            "instructions": [
                "Equip Guardian only.",
                "Eliminate 50 bots with single headshots.",
                "Minimum acceptable accuracy is 85% headshot ratio.",
            ],
            "coaching_cue": "First bullet accuracy dictates 70% of high-ELO duel outcomes.",
        },
        "aim_trainer_scenarios": [
            {
                "scenario_name": "VT Angleshot Valorant",
                "platform": "Aim Lab",
                "task_type": "Micro-flick",
                "recommended_plays": 3,
                "target_score": "80,000+",
                "notes": "Emphasizes deliberate precision over reckless speed.",
            },
        ],
        "map_drills": {},
    },
    "over_peeking": {
        "category": "Positioning",
        "estimated_time_min": 15,
        "range_exercise": {
            "exercise_name": "Angle Isolation & Micro-Jiggle Protocol",
            "weapon": "Classic / Ghost",
            "target_mode": "Practice Mode behind Pillars",
            "armor_setting": "Heavy Armor",
            "duration_minutes": 8,
            "instructions": [
                "Use the support pillars in the range as hard site cover.",
                "Jiggle-peek out for no more than 150ms (shoulder peek for info only).",
                "Never re-challenge the same angle if you received damage.",
            ],
            "coaching_cue": "Info peeks are free; ego peeks cost rounds.",
        },
        "aim_trainer_scenarios": [
            {
                "scenario_name": "VT Angleshot Micro",
                "platform": "Aim Lab",
                "task_type": "Micro-flick",
                "recommended_plays": 3,
                "target_score": "80,000+",
                "notes": "Sharp target acquisition when exposing minimal hitbox.",
            },
        ],
        "map_drills": {
            "Ascent": {
                "callout": "Mid Tiles & Catwalk",
                "objective": "Practice clearing Mid Tiles with jump-peeks rather than wide swings.",
                "setup": "Custom game Defense on Catwalk.",
                "drills": [
                    "Jump-peek Mid Tiles from Catwalk corner without exposing body to Mid Courtyard.",
                    "Tag enemy position and rotate to Market rather than repeeking.",
                ],
            },
            "Haven": {
                "callout": "C-Long Anchor",
                "objective": "Hold C-Long from back plat; fall back to logs on contact.",
                "setup": "Custom match on Haven Defense.",
                "drills": ["Fire 2 rounds down C-Long and immediately reposition to site crossfire."],
            },
        },
    },
    "poor_spacing": {
        "category": "Positioning",
        "estimated_time_min": 10,
        "range_exercise": {
            "exercise_name": "2-Man Shadow Spacing Drill",
            "weapon": "Vandal",
            "target_mode": "Custom Game with Teammate or Bot",
            "armor_setting": "Heavy Armor",
            "duration_minutes": 10,
            "instructions": [
                "Position strictly 3 to 5 meters behind lead entry player.",
                "Ensure your crosshair covers the complimentary angle (e.g. entry checks close right, you check deep left).",
                "If lead player dies, your trade frag must occur within 1.5 seconds.",
            ],
            "coaching_cue": "Un-traded deaths represent unforced errors. Never let a teammate die alone.",
        },
        "aim_trainer_scenarios": [
            {
                "scenario_name": "Target Switcher 360",
                "platform": "Aim Lab",
                "task_type": "Target Switching",
                "recommended_plays": 3,
                "target_score": "70,000+",
                "notes": "Rapidly switch to trade targets after primary entry contact.",
            },
        ],
        "map_drills": {},
    },
    "late_flash": {
        "category": "Utility",
        "estimated_time_min": 10,
        "range_exercise": {
            "exercise_name": "Pop-Flash Coordination Dry-Run",
            "weapon": "Initiator Utility",
            "target_mode": "Custom Game Empty Map",
            "armor_setting": "No Armor",
            "duration_minutes": 10,
            "instructions": [
                "Stand in common execute prep zones (e.g. Ascent B-Main or Haven A-Lobby).",
                "Throw flash on a high-bounce trajectory that detonates behind your entry player.",
                "Call 'Flash popping in 3-2-1' on voice comms before the throw.",
            ],
            "coaching_cue": "Flashes thrown after contact is made blind teammates more often than enemies.",
        },
        "aim_trainer_scenarios": [],
        "map_drills": {
            "Ascent": {
                "callout": "B-Main to B-Site",
                "objective": "Practice high-window flash line-up.",
                "setup": "Custom match as KAY/O or Skye.",
                "drills": ["Pop flash through B-Main skylight into Market and swing simultaneously."],
            },
        },
    },
    "wasted_utility": {
        "category": "Utility",
        "estimated_time_min": 10,
        "range_exercise": {
            "exercise_name": "Utility Value Protocol",
            "weapon": "Controller / Initiator Utility",
            "target_mode": "Custom Game",
            "armor_setting": "No Armor",
            "duration_minutes": 8,
            "instructions": [
                "Establish a firm rule: Never deploy utility without a planned swing or hard stall.",
                "Before pressing any ability key, verify radar for teammate position.",
            ],
            "coaching_cue": "Utility deployed without map control or information gain is spent credits with zero yield.",
        },
        "aim_trainer_scenarios": [],
        "map_drills": {},
    },
    "forced_fight": {
        "category": "Decision",
        "estimated_time_min": 10,
        "range_exercise": {
            "exercise_name": "Disengage & Retake Poise",
            "weapon": "Phantom / Sheriff",
            "target_mode": "Range Retake Mode",
            "armor_setting": "Heavy Armor",
            "duration_minutes": 10,
            "instructions": [
                "Practice throwing smoke or flash to break enemy line of sight.",
                "Backpedal into site anchor spots and group with teammates for coordinated retake.",
            ],
            "coaching_cue": "Down 1 player? Disengage, regroup, and execute retake together with full utility.",
        },
        "aim_trainer_scenarios": [],
        "map_drills": {},
    },
    "late_rotate": {
        "category": "Decision",
        "estimated_time_min": 10,
        "range_exercise": {
            "exercise_name": "Radar Cue & 2nd Utility Rotation Protocol",
            "weapon": "Classic",
            "target_mode": "Custom Game",
            "armor_setting": "No Armor",
            "duration_minutes": 8,
            "instructions": [
                "Load custom game on defense.",
                "Practice rotating upon hearing the 2nd piece of confirmation utility (e.g. Sova drone + smoke).",
                "Optimize knife-out routing to arrive on site before spike plant finishes.",
            ],
            "coaching_cue": "Rotating after bomb plant leaves 20% win probability; rotating on confirmation gives 55%.",
        },
        "aim_trainer_scenarios": [],
        "map_drills": {},
    },
}


class TrainingRoutineEngine:
    """Generates tailored training routines and Aim Lab playlists from match review flaws."""

    def __init__(self, registry: Optional[dict[str, dict[str, Any]]] = None):
        self.registry = registry or DRILL_REGISTRY

    def generate_routine(
        self,
        metadata: MatchMetadata,
        events: list[MatchEvent],
        tags: list[VodTag],
        player_puuid: Optional[str] = None,
    ) -> TrainingRoutineResult:
        map_name = metadata.map_id.strip("/").split("/")[-1].capitalize()

        # Determine player PUUID if not provided
        if not player_puuid:
            kills = [e for e in events if e.event_type == "kill" and e.player_puuid]
            if kills:
                player_puuid = max(set(e.player_puuid for e in kills), key=lambda p: len([k for k in kills if k.player_puuid == p]))
            else:
                player_puuid = "player"

        engine = FlawCorrelationEngine()
        tag_correlations = engine.correlate_tags_with_metrics(player_puuid, events, tags)

        prescriptions: list[PrescribedFlawDrill] = []
        total_time = 0
        seen_tags: set[str] = set()

        # Process correlated tags first
        for tc in tag_correlations:
            t_name = tc.tag_name
            if t_name in seen_tags:
                continue
            seen_tags.add(t_name)

            drill_data = self.registry.get(t_name)
            if not drill_data:
                continue

            # Determine priority based on un-traded deaths and first deaths
            if tc.untraded_death_count >= 2 or tc.first_death_count >= 2:
                priority = "HIGH"
            elif tc.total_count >= 2:
                priority = "MEDIUM"
            else:
                priority = "LOW"

            re_data = drill_data["range_exercise"]
            range_ex = RangeExercise(
                exercise_name=re_data["exercise_name"],
                weapon=re_data["weapon"],
                target_mode=re_data["target_mode"],
                armor_setting=re_data["armor_setting"],
                duration_minutes=re_data["duration_minutes"],
                instructions=re_data["instructions"],
                coaching_cue=re_data["coaching_cue"],
            )

            aim_scenarios = [
                AimTrainerScenario(
                    scenario_name=sc["scenario_name"],
                    platform=sc["platform"],
                    task_type=sc["task_type"],
                    recommended_plays=sc["recommended_plays"],
                    target_score=sc["target_score"],
                    notes=sc["notes"],
                )
                for sc in drill_data.get("aim_trainer_scenarios", [])
            ]

            # Map-specific drill if available
            map_drill_obj = None
            map_drills_dict = drill_data.get("map_drills", {})
            map_d = map_drills_dict.get(map_name) or (next(iter(map_drills_dict.values())) if map_drills_dict else None)
            if map_d:
                map_drill_obj = MapSpecificDrill(
                    map_name=map_name,
                    callout=map_d["callout"],
                    objective=map_d["objective"],
                    setup=map_d["setup"],
                    drills=map_d["drills"],
                )

            t_min = drill_data.get("estimated_time_min", 10)
            total_time += t_min

            prescriptions.append(
                PrescribedFlawDrill(
                    tag_name=t_name,
                    category=drill_data.get("category", "General"),
                    correlated_flaw_count=tc.total_count,
                    untraded_deaths_correlated=tc.untraded_death_count,
                    first_deaths_correlated=tc.first_death_count,
                    priority=priority,
                    estimated_time_min=t_min,
                    range_exercise=range_ex,
                    aim_trainer_scenarios=aim_scenarios,
                    map_drill=map_drill_obj,
                )
            )

        # Fallback if no tags were logged: provide core fundamentals
        if not prescriptions:
            default_data = self.registry["crosshair_placement"]
            re_data = default_data["range_exercise"]
            prescriptions.append(
                PrescribedFlawDrill(
                    tag_name="crosshair_placement",
                    category="Mechanics",
                    correlated_flaw_count=0,
                    untraded_deaths_correlated=0,
                    first_deaths_correlated=0,
                    priority="HIGH",
                    estimated_time_min=15,
                    range_exercise=RangeExercise(
                        exercise_name=re_data["exercise_name"],
                        weapon=re_data["weapon"],
                        target_mode=re_data["target_mode"],
                        armor_setting=re_data["armor_setting"],
                        duration_minutes=re_data["duration_minutes"],
                        instructions=re_data["instructions"],
                        coaching_cue=re_data["coaching_cue"],
                    ),
                    aim_trainer_scenarios=[
                        AimTrainerScenario(
                            scenario_name="VT Angleshot Valorant",
                            platform="Aim Lab",
                            task_type="Micro-flick",
                            recommended_plays=3,
                            target_score="85,000+",
                            notes="Standard fundamental benchmark.",
                        )
                    ],
                    map_drill=None,
                )
            )
            total_time = 15

        primary_focus = prescriptions[0].tag_name.replace("_", " ").title() if prescriptions else "Fundamentals"
        summary = (
            f"Tailored {total_time}-minute training routine targeting {len(prescriptions)} recurring flaw(s). "
            f"Primary focus is {primary_focus.upper()} with correlated un-traded death mitigation."
        )

        # Build Aim Lab Playlist JSON
        aimlab_tasks = []
        for p in prescriptions:
            for sc in p.aim_trainer_scenarios:
                aimlab_tasks.append({
                    "taskName": sc.scenario_name,
                    "mode": sc.task_type,
                    "weapon": p.range_exercise.weapon,
                    "playCount": sc.recommended_plays,
                    "targetScore": sc.target_score,
                })

        aimlab_playlist = {
            "name": f"ValLens Custom - {map_name} Focus ({primary_focus})",
            "author": "ValLens AI Coaching",
            "version": 1,
            "description": f"Targeted aim routine addressing match flaws on {map_name}.",
            "totalEstimatedMinutes": total_time,
            "tasks": aimlab_tasks,
        }

        # Build Markdown Workout Routine
        md_lines = [
            f"# ValLens Practice Routine — {map_name} ({primary_focus})",
            f"**Total Duration:** ~{total_time} Minutes | **Focus:** {primary_focus}",
            "",
            "---",
            "",
            "## 1. Executive Protocol Summary",
            summary,
            "",
            "---",
            "",
            "## 2. Structured Workout Exercises",
            "",
        ]

        for i, p in enumerate(prescriptions, start=1):
            md_lines.append(f"### Exercise #{i}: {p.tag_name.replace('_', ' ').title()} Protocol [{p.priority} PRIORITY]")
            md_lines.append(f"* **Category:** {p.category} | **Est. Time:** {p.estimated_time_min} min")
            md_lines.append(f"* **The Range:** {p.range_exercise.exercise_name} ({p.range_exercise.weapon})")
            md_lines.append(f"  * Mode: `{p.range_exercise.target_mode}` · Armor: `{p.range_exercise.armor_setting}`")
            for inst in p.range_exercise.instructions:
                md_lines.append(f"  * {inst}")
            md_lines.append(f"  * *Coaching Cue:* \"{p.range_exercise.coaching_cue}\"")
            md_lines.append("")

            if p.aim_trainer_scenarios:
                md_lines.append("* **Aim Trainer Scenarios (Aim Lab / KovaaKs):**")
                for sc in p.aim_trainer_scenarios:
                    md_lines.append(f"  * **{sc.scenario_name}** ({sc.platform}) — {sc.recommended_plays} plays · Target: `{sc.target_score}`")
                md_lines.append("")

            if p.map_drill:
                md_lines.append(f"* **Map Specific Dry-Run ({p.map_drill.map_name} — {p.map_drill.callout}):**")
                md_lines.append(f"  * Setup: {p.map_drill.setup}")
                for d in p.map_drill.drills:
                    md_lines.append(f"  * {d}")
                md_lines.append("")

            md_lines.append("---")
            md_lines.append("")

        markdown_routine = "\n".join(md_lines)

        return TrainingRoutineResult(
            match_id=metadata.match_id,
            map_name=map_name,
            total_routine_duration_min=total_time,
            primary_focus=primary_focus,
            summary=summary,
            prescriptions=prescriptions,
            aimlab_playlist=aimlab_playlist,
            markdown_routine=markdown_routine,
        )
