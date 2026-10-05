"""Perspective Diffing and Cognitive Blindspots Analytics Engine.

Compares subjective review tags logged by Solo players versus Coaches to identify:
1. Cognitive Blindspots (flaws flagged by Coach that the player missed).
2. Over-Criticality (self-criticisms logged by Solo that Coach evaluated as standard).
3. Mutual Consensus (flaws recognized by both within a time tolerance).
4. Category-level divergence (e.g., Mechanics awareness vs Positioning blindspots).
"""

from dataclasses import dataclass, field
import math
from typing import Any, Optional

from vallens.models import MatchEvent, VodTag


@dataclass
class PerspectiveBlindspot:
    tag_id: Optional[int]
    round_number: int
    timestamp_ms: int
    formatted_time: str
    round_rel_time: str
    tag_category: str
    tag_name: str
    severity: str  # 'HIGH', 'MEDIUM', 'LOW'
    related_event: Optional[str]
    coaching_directive: str


@dataclass
class PerspectiveSelfCriticism:
    tag_id: Optional[int]
    round_number: int
    timestamp_ms: int
    formatted_time: str
    round_rel_time: str
    tag_category: str
    tag_name: str
    related_event: Optional[str]
    evaluation: str


@dataclass
class PerspectiveAgreedTag:
    round_number: int
    timestamp_ms: int
    formatted_time: str
    round_rel_time: str
    solo_tag_name: str
    coach_tag_name: str
    tag_category: str
    time_delta_ms: int
    notes: str


@dataclass
class CategoryDivergence:
    category: str
    solo_count: int
    coach_count: int
    agreed_count: int
    blindspots_count: int
    self_criticisms_count: int
    alignment_rate: float  # 0.0 to 1.0
    status: str  # 'High Consensus', 'Moderate Divergence', 'Critical Blindspot'


@dataclass
class PerspectiveDiffResult:
    match_id: str
    agreement_score: float  # 0.0 to 1.0
    alignment_status: str  # 'EXCELLENT ALIGNMENT', 'MODERATE DIVERGENCE', 'SIGNIFICANT BLINDSPOTS'
    total_solo_tags: int
    total_coach_tags: int
    agreed_count: int
    blindspots_count: int
    self_criticisms_count: int
    blindspots: list[PerspectiveBlindspot] = field(default_factory=list)
    self_criticisms: list[PerspectiveSelfCriticism] = field(default_factory=list)
    agreed_tags: list[PerspectiveAgreedTag] = field(default_factory=list)
    category_divergence: list[CategoryDivergence] = field(default_factory=list)
    executive_takeaways: list[str] = field(default_factory=list)
    timeline_pips: list[dict[str, Any]] = field(default_factory=list)


COACHING_DIRECTIVES: dict[str, str] = {
    "crosshair_placement": "Coach flagged suboptimal head-level angle clearing. Reset crosshair height before rounding corners.",
    "whiffed_spray": "Coach noted weapon spray committed beyond 6 rounds. Implement burst-strafe reset discipline.",
    "over_peeking": "Coach identified unnecessary angle exposure after initial info contact. Re-peek without support yielded zero EV.",
    "poor_spacing": "Coach flagged spacing failure. Position within 3m of entry duelist to guarantee instantaneous re-frag.",
    "wasted_utility": "Coach flagged unsynchronized utility. Avoid burning flashes/recon without immediate team commit.",
    "late_flash": "Coach observed delayed pop-flash. Timing failed to blind advancing opponents before site contact.",
    "forced_fight": "Coach flagged disadvantageous duel initiation. Disengage to anchor retake with full squad.",
    "late_rotate": "Coach noted delayed map rotation. Rotate on 2nd confirmation utility rather than waiting for plant audio.",
    "panic_spray": "Coach noted crouch-spray commitment under pressure. Maintain counter-strafe mobility.",
}

SELF_CRITICISM_EVALUATIONS: dict[str, str] = {
    "crosshair_placement": "Coach evaluation: Placement was acceptable for that off-angle; duel loss was due to opponent pre-fire speed.",
    "whiffed_spray": "Coach evaluation: Spray commitment was mathematically justified against two close-quarter targets.",
    "over_peeking": "Coach evaluation: Angle challenge was necessary to contest spike defuse timer; do not over-penalize.",
    "poor_spacing": "Coach evaluation: Spacing was dictated by teammate sudden stop; player reaction was standard.",
    "wasted_utility": "Coach evaluation: Utility forced enemy retreat and stalled push; value was positive despite no kill.",
    "late_flash": "Coach evaluation: Flash timing accounted for teammate reload; delay was optimal under circumstances.",
    "forced_fight": "Coach evaluation: Fight was unavoidable due to teammate flank collapse; necessary aggressive gamble.",
    "late_rotate": "Coach evaluation: Anchor delay prevented enemy fake-execute; correct defensive poise.",
    "panic_spray": "Coach evaluation: Target movement was erratic; burst decision was sound.",
}


class PerspectiveDiffEngine:
    """Computes cognitive divergence and blindspots between Solo review and Coach annotations."""

    def __init__(self, default_tolerance_ms: int = 5000):
        self.default_tolerance_ms = default_tolerance_ms

    def analyze_perspectives(
        self,
        match_id: str,
        events: list[MatchEvent],
        tags: list[VodTag],
        tolerance_ms: Optional[int] = None,
    ) -> PerspectiveDiffResult:
        tol = tolerance_ms if tolerance_ms is not None else self.default_tolerance_ms

        # Map round starts to calculate round numbers and relative timestamps
        round_starts: dict[int, int] = {}
        for e in events:
            if e.event_type == "round_start":
                round_starts[e.round_number] = e.event_time_ms

        # Fallback if no round_start events
        if not round_starts and events:
            rounds = sorted(list(set(e.round_number for e in events)))
            for r in rounds:
                revs = [e.event_time_ms for e in events if e.round_number == r]
                if revs:
                    round_starts[r] = min(revs)

        # Helper to find round number for a timestamp
        def get_round_info(t_ms: int) -> tuple[int, str]:
            if not round_starts:
                return 1, "+00:00"
            sorted_rounds = sorted(round_starts.items(), key=lambda x: x[1])
            curr_rnd = sorted_rounds[0][0]
            curr_start = sorted_rounds[0][1]
            for r, s_ms in sorted_rounds:
                if t_ms >= s_ms:
                    curr_rnd = r
                    curr_start = s_ms
                else:
                    break
            rel_sec = max(0, int((t_ms - curr_start) / 1000))
            mins = rel_sec // 60
            secs = rel_sec % 60
            return curr_rnd + 1, f"+{mins:02d}:{secs:02d}"

        def fmt_time(ms: int) -> str:
            sec = int(ms / 1000)
            return f"{sec // 60:02d}:{sec % 60:02d}"

        # Helper to find nearby events (kill/death)
        def find_related_event(t_ms: int) -> tuple[Optional[str], str]:
            nearby = [
                e for e in events
                if e.event_type in ("kill", "death") and abs(e.event_time_ms - t_ms) <= 6000
            ]
            if not nearby:
                return None, "LOW"
            first = nearby[0]
            if first.event_type == "death":
                killer = first.metadata.get("killer", "Enemy")
                weapon = first.metadata.get("weapon", "Weapon")
                return f"Death vs {killer} ({weapon})", "HIGH"
            elif first.event_type == "kill":
                weapon = first.metadata.get("weapon", "Weapon")
                return f"Frag secured ({weapon})", "MEDIUM"
            return f"{first.event_type.capitalize()} nearby", "LOW"

        solo_tags = [t for t in tags if t.author_type == "solo"]
        coach_tags = [t for t in tags if t.author_type == "coach"]

        blindspots: list[PerspectiveBlindspot] = []
        self_criticisms: list[PerspectiveSelfCriticism] = []
        agreed_tags: list[PerspectiveAgreedTag] = []

        matched_coach_ids: set[int] = set()
        matched_solo_ids: set[int] = set()

        # Pair coach and solo tags within tolerance
        for c in coach_tags:
            c_id = c.tag_id or id(c)
            found_match = False
            for s in solo_tags:
                s_id = s.tag_id or id(s)
                if s_id in matched_solo_ids:
                    continue
                delta = abs(c.timestamp_ms - s.timestamp_ms)
                if delta <= tol:
                    r_num, rel_time = get_round_info(c.timestamp_ms)
                    agreed_tags.append(
                        PerspectiveAgreedTag(
                            round_number=r_num,
                            timestamp_ms=c.timestamp_ms,
                            formatted_time=fmt_time(c.timestamp_ms),
                            round_rel_time=rel_time,
                            solo_tag_name=s.tag_name,
                            coach_tag_name=c.tag_name,
                            tag_category=c.tag_category,
                            time_delta_ms=delta,
                            notes="Aligned diagnosis between Coach and Solo reviewer.",
                        )
                    )
                    matched_coach_ids.add(c_id)
                    matched_solo_ids.add(s_id)
                    found_match = True
                    break

            if not found_match:
                r_num, rel_time = get_round_info(c.timestamp_ms)
                rel_evt, severity = find_related_event(c.timestamp_ms)
                directive = COACHING_DIRECTIVES.get(
                    c.tag_name,
                    f"Coach flagged {c.tag_name.replace('_', ' ')}. Player missed this error during review."
                )
                blindspots.append(
                    PerspectiveBlindspot(
                        tag_id=c.tag_id,
                        round_number=r_num,
                        timestamp_ms=c.timestamp_ms,
                        formatted_time=fmt_time(c.timestamp_ms),
                        round_rel_time=rel_time,
                        tag_category=c.tag_category,
                        tag_name=c.tag_name,
                        severity=severity,
                        related_event=rel_evt,
                        coaching_directive=directive,
                    )
                )

        for s in solo_tags:
            s_id = s.tag_id or id(s)
            if s_id not in matched_solo_ids:
                r_num, rel_time = get_round_info(s.timestamp_ms)
                rel_evt, _ = find_related_event(s.timestamp_ms)
                evaluation = SELF_CRITICISM_EVALUATIONS.get(
                    s.tag_name,
                    "Coach deemed this play acceptable or lower priority; player self-criticism may be overzealous."
                )
                self_criticisms.append(
                    PerspectiveSelfCriticism(
                        tag_id=s.tag_id,
                        round_number=r_num,
                        timestamp_ms=s.timestamp_ms,
                        formatted_time=fmt_time(s.timestamp_ms),
                        round_rel_time=rel_time,
                        tag_category=s.tag_category,
                        tag_name=s.tag_name,
                        related_event=rel_evt,
                        evaluation=evaluation,
                    )
                )

        # Calculate overall agreement score
        total_unique = len(solo_tags) + len(coach_tags) - len(agreed_tags)
        if total_unique > 0:
            score = round(len(agreed_tags) / total_unique, 2)
        elif not solo_tags and not coach_tags:
            score = 1.0
        else:
            score = 0.0

        if score >= 0.70:
            status = "EXCELLENT ALIGNMENT"
        elif score >= 0.40:
            status = "MODERATE DIVERGENCE"
        else:
            status = "SIGNIFICANT BLINDSPOTS"

        # Category divergence aggregation
        all_categories = ["Mechanics", "Positioning", "Utility", "Decision"]
        cat_map: dict[str, dict[str, int]] = {
            c: {"solo": 0, "coach": 0, "agreed": 0, "blindspots": 0, "self_crit": 0}
            for c in all_categories
        }

        for s in solo_tags:
            cat = s.tag_category if s.tag_category in cat_map else "Mechanics"
            cat_map[cat]["solo"] += 1

        for c in coach_tags:
            cat = c.tag_category if c.tag_category in cat_map else "Mechanics"
            cat_map[cat]["coach"] += 1

        for a in agreed_tags:
            cat = a.tag_category if a.tag_category in cat_map else "Mechanics"
            cat_map[cat]["agreed"] += 1

        for b in blindspots:
            cat = b.tag_category if b.tag_category in cat_map else "Mechanics"
            cat_map[cat]["blindspots"] += 1

        for sc in self_criticisms:
            cat = sc.tag_category if sc.tag_category in cat_map else "Mechanics"
            cat_map[cat]["self_crit"] += 1

        cat_divergences = []
        for cat, counts in cat_map.items():
            tot = counts["solo"] + counts["coach"] - counts["agreed"]
            cat_score = round(counts["agreed"] / tot, 2) if tot > 0 else 1.0
            if counts["blindspots"] >= 2 or (counts["coach"] > 0 and cat_score < 0.4):
                c_status = "Critical Blindspot"
            elif cat_score >= 0.7:
                c_status = "High Consensus"
            else:
                c_status = "Moderate Divergence"

            cat_divergences.append(
                CategoryDivergence(
                    category=cat,
                    solo_count=counts["solo"],
                    coach_count=counts["coach"],
                    agreed_count=counts["agreed"],
                    blindspots_count=counts["blindspots"],
                    self_criticisms_count=counts["self_crit"],
                    alignment_rate=cat_score,
                    status=c_status,
                )
            )

        # Executive takeaways synthesis
        takeaways = []
        # 1. Overall Alignment Takeaway
        takeaways.append(
            f"Overall consensus between Solo and Coach sits at {int(score * 100)}% ({status}). "
            f"{len(agreed_tags)} mutual flaw recognitions identified across {len(tags)} total tags."
        )

        # 2. Critical Blindspot Category
        worst_cat = min(cat_divergences, key=lambda c: (c.alignment_rate, -c.blindspots_count))
        if worst_cat.blindspots_count > 0:
            takeaways.append(
                f"Primary blindspot concentration is in {worst_cat.category.upper()}: Coach flagged "
                f"{worst_cat.coach_count} items where Player missed {worst_cat.blindspots_count} errors "
                f"({int(worst_cat.alignment_rate * 100)}% category alignment)."
            )

        # 3. Over-Criticality Observation
        if len(self_criticisms) >= 2:
            takeaways.append(
                f"Player logged {len(self_criticisms)} unconfirmed self-criticisms. "
                "Coach reviewed these engagements as standard or forced duels; player exhibits excessive self-reproach."
            )
        elif len(blindspots) >= 3:
            takeaways.append(
                f"Player logged fewer tags than Coach ({len(solo_tags)} vs {len(coach_tags)}). "
                "Recommend expanding review criteria beyond missed shots to include pre-engagement angle discipline."
            )
        else:
            takeaways.append(
                "Review discipline is tightly synchronized with coaching expectations. Flaw recognition is actively translating to tactical self-awareness."
            )

        # Chronological timeline pips for interactive scrubbing
        pips = []
        for a in agreed_tags:
            pips.append({
                "type": "agreed",
                "timestamp_ms": a.timestamp_ms,
                "round_number": a.round_number,
                "label": f"Consensus: {a.coach_tag_name.replace('_', ' ')}",
                "category": a.tag_category,
                "badge": "MUTUAL",
                "author": "both",
            })
        for b in blindspots:
            pips.append({
                "type": "blindspot",
                "timestamp_ms": b.timestamp_ms,
                "round_number": b.round_number,
                "label": f"Blindspot: {b.tag_name.replace('_', ' ')}",
                "category": b.tag_category,
                "badge": "COACH ONLY",
                "author": "coach",
                "severity": b.severity,
            })
        for sc in self_criticisms:
            pips.append({
                "type": "self_criticism",
                "timestamp_ms": sc.timestamp_ms,
                "round_number": sc.round_number,
                "label": f"Self-Criticism: {sc.tag_name.replace('_', ' ')}",
                "category": sc.tag_category,
                "badge": "SOLO ONLY",
                "author": "solo",
            })

        pips.sort(key=lambda p: p["timestamp_ms"])

        return PerspectiveDiffResult(
            match_id=match_id,
            agreement_score=score,
            alignment_status=status,
            total_solo_tags=len(solo_tags),
            total_coach_tags=len(coach_tags),
            agreed_count=len(agreed_tags),
            blindspots_count=len(blindspots),
            self_criticisms_count=len(self_criticisms),
            blindspots=blindspots,
            self_criticisms=self_criticisms,
            agreed_tags=agreed_tags,
            category_divergence=cat_divergences,
            executive_takeaways=takeaways,
            timeline_pips=pips,
        )
