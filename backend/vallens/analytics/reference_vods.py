"""Pro Reference VOD catalog and tactical comparison engine for ValLens."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class ProReferenceVod:
    """A pro player tactical reference VOD record for side-by-side comparison."""
    id: str
    title: str
    player: str
    team: str
    agent: str
    map_name: str
    flaw_category: str
    flaw_tag: str
    tactical_concept: str
    clip_url: str
    key_points: list[str] = field(default_factory=list)
    default_offset_sec: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "player": self.player,
            "team": self.team,
            "agent": self.agent,
            "map": self.map_name,
            "flaw_category": self.flaw_category,
            "flaw_tag": self.flaw_tag,
            "tactical_concept": self.tactical_concept,
            "clip_url": self.clip_url,
            "key_points": self.key_points,
            "default_offset_sec": self.default_offset_sec,
        }


CURATED_PRO_REFERENCES: list[ProReferenceVod] = [
    ProReferenceVod(
        id="aspas_ascent_a_op",
        title="Aspas (Leviatán) - Ascent A Main OP & Angle Isolation",
        player="Aspas",
        team="Leviatán",
        agent="Jett",
        map_name="Ascent",
        flaw_category="Mechanics",
        flaw_tag="crosshair_placement",
        tactical_concept="Micro-adjusted crosshair buffer & instant retreat",
        clip_url="/api/clips/vallens_f39bb79d_coaching_reel_montage.mp4",
        key_points=[
            "Holds 1 head-width off door frame for reaction buffer rather than pixel edge",
            "Pre-aims head height at Ascent A main arch crease",
            "Zero dry repeeking: retreats immediately to site on contact",
        ],
        default_offset_sec=0.0,
    ),
    ProReferenceVod(
        id="tenz_ascent_mid_market",
        title="TenZ (Sentinels) - Mid Market Repositioning & Counter-Strafe",
        player="TenZ",
        team="Sentinels",
        agent="Omen",
        map_name="Ascent",
        flaw_category="Positioning",
        flaw_tag="over_peeking",
        tactical_concept="Angle slicing & discipline against repeeking",
        clip_url="/api/clips/vallens_f39bb79d_whiffed_spray_43s.mp4",
        key_points=[
            "Jiggle peeks for information before committing body",
            "Waits for flash contact audio cue before swinging mid tiles",
            "Disciplined 3-shot burst then resets into pizza cover",
        ],
        default_offset_sec=0.5,
    ),
    ProReferenceVod(
        id="boaster_ascent_b_retake",
        title="Boaster (Fnatic) - B Site Retake Spacing & Buddy Trading",
        player="Boaster",
        team="Fnatic",
        agent="Astra",
        map_name="Ascent",
        flaw_category="Positioning",
        flaw_tag="poor_spacing",
        tactical_concept="2-meter spacing & delayed utility coordination",
        clip_url="/api/clips/vallens_f39bb79d_1_whiffed_spray_44s.mp4",
        key_points=[
            "Maintains 2-3m spacing behind duel entry to guarantee immediate trade",
            "Avoids lining up in B main choke to prevent collateral spray",
            "Gravity well timed exactly with defuser tap bait",
        ],
        default_offset_sec=-0.2,
    ),
    ProReferenceVod(
        id="chronicle_ascent_tree_hold",
        title="Chronicle (Fnatic) - Tree Room First-Bullet Tap Discipline",
        player="Chronicle",
        team="Fnatic",
        agent="Sova",
        map_name="Ascent",
        flaw_category="Mechanics",
        flaw_tag="whiffed_spray",
        tactical_concept="First-bullet accuracy & spray reset rhythm",
        clip_url="/api/clips/vallens_f39bb79d_r1_whiffed_spray_43s.mp4",
        key_points=[
            "Refuses to crouch-spray through smoke at long range",
            "Crosshair aligned precisely to A Garden wall elevation line",
            "Clean 2-bullet burst cadence with complete recoil resets",
        ],
        default_offset_sec=0.0,
    ),
]


class ProReferenceCatalog:
    """Catalog of Pro VCT player reference VODs for side-by-side comparison."""

    def __init__(self, references: Optional[list[ProReferenceVod]] = None):
        self._references: list[ProReferenceVod] = list(references or CURATED_PRO_REFERENCES)

    def list_references(
        self,
        map_name: Optional[str] = None,
        flaw_tag: Optional[str] = None,
        agent: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return reference VODs filtered by map, flaw, or agent."""
        results = []
        for ref in self._references:
            if map_name and ref.map_name.lower() != map_name.lower():
                continue
            if flaw_tag and ref.flaw_tag.lower() != flaw_tag.lower():
                continue
            if agent and ref.agent.lower() != agent.lower():
                continue
            results.append(ref.to_dict())
        return results

    def get_reference_by_id(self, ref_id: str) -> Optional[dict[str, Any]]:
        """Find a reference VOD by unique ID."""
        for ref in self._references:
            if ref.id == ref_id:
                return ref.to_dict()
        return None

    def recommend_for_flaw(self, flaw_tag: str, map_name: Optional[str] = None) -> list[dict[str, Any]]:
        """Recommend reference VODs that teach solutions to a specific flaw."""
        matched = []
        for ref in self._references:
            score = 0
            if ref.flaw_tag.lower() == flaw_tag.lower():
                score += 10
            if map_name and ref.map_name.lower() == map_name.lower():
                score += 5
            if score > 0:
                d = ref.to_dict()
                d["relevance_score"] = score
                matched.append(d)
        matched.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        return matched if matched else [r.to_dict() for r in self._references[:2]]

    def add_custom_reference(self, reference: ProReferenceVod) -> None:
        """Add a custom reference VOD to the catalog."""
        self._references.append(reference)
