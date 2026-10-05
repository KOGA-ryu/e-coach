"""Spatial heatmap aggregation and multi-match clustering engine."""

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any, Optional

from vallens.analytics.projection import CoordinateProjector
from vallens.models import VodTag

MAPS_DATA_PATH = Path(__file__).parent.parent.parent.parent / "data" / "maps.json"


@dataclass
class SpatialCluster:
    """Represents a spatial hotspot cluster (e.g. death trap or fragging zone)."""
    cluster_id: int
    center_x: float  # Normalized [0..1]
    center_y: float  # Normalized [0..1]
    event_count: int
    percentage: float
    zone_name: str
    super_region: str
    radius: float
    event_type: str
    points: list[dict[str, Any]] = field(default_factory=list)
    correlated_tags: list[dict[str, Any]] = field(default_factory=list)
    tactical_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "center_x": round(self.center_x, 4),
            "center_y": round(self.center_y, 4),
            "event_count": self.event_count,
            "percentage": round(self.percentage, 1),
            "zone_name": self.zone_name,
            "super_region": self.super_region,
            "radius": round(self.radius, 4),
            "event_type": self.event_type,
            "points_count": len(self.points),
            "correlated_tags": self.correlated_tags,
            "tactical_summary": self.tactical_summary,
        }


@dataclass
class HeatmapAggregationResult:
    """Consolidated multi-match spatial aggregation payload."""
    map_id: str
    map_name: str
    match_count: int
    match_ids: list[str]
    total_events: int
    event_type: str
    side: str
    points: list[dict[str, Any]]
    clusters: list[SpatialCluster]
    density_grid: list[dict[str, Any]]
    tactical_insights: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "map_id": self.map_id,
            "map_name": self.map_name,
            "match_count": self.match_count,
            "match_ids": self.match_ids,
            "total_events": self.total_events,
            "event_type": self.event_type,
            "side": self.side,
            "points": self.points,
            "clusters": [c.to_dict() for c in self.clusters],
            "density_grid": self.density_grid,
            "tactical_insights": self.tactical_insights,
        }


class HeatmapAggregationEngine:
    """Analyzes and clusters spatial coordinates across multiple matches."""

    def __init__(
        self,
        maps_file: Optional[Path | str] = None,
        cluster_radius: float = 0.065,
        min_cluster_size: int = 2,
    ):
        self.cluster_radius = cluster_radius
        self.min_cluster_size = min_cluster_size
        self.maps_file = Path(maps_file) if maps_file else MAPS_DATA_PATH
        self.map_callouts: dict[str, list[dict[str, Any]]] = {}
        self._load_callouts()

    def _load_callouts(self) -> None:
        """Load in-game callouts from maps.json."""
        if not self.maps_file.exists():
            return
        try:
            with open(self.maps_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for map_key, item in data.items():
                callouts = item.get("callouts") or []
                self.map_callouts[map_key.lower()] = callouts
                display_name = item.get("displayName", "").lower()
                if display_name:
                    self.map_callouts[display_name] = callouts
        except Exception:
            pass

    def find_nearest_callout(
        self, map_identifier: str, norm_x: float, norm_y: float
    ) -> tuple[str, str]:
        """Find the closest official map callout for a given normalized coordinate."""
        key = map_identifier.strip().lower()
        callouts = self.map_callouts.get(key)
        if not callouts:
            # Try segment matching, e.g. "ascent"
            seg = key.split("/")[-1]
            callouts = self.map_callouts.get(seg, [])

        if not callouts:
            # Fallback heuristic based on quad coordinates
            side_x = "A" if norm_x > 0.55 else ("B" if norm_x < 0.45 else "Mid")
            return f"{side_x} Zone", side_x

        best_callout: Optional[dict[str, Any]] = None
        min_dist = float("inf")

        for c in callouts:
            cx = c.get("norm_x", 0.5)
            cy = c.get("norm_y", 0.5)
            dist = math.hypot(norm_x - cx, norm_y - cy)
            if dist < min_dist:
                min_dist = dist
                best_callout = c

        if best_callout:
            full_name = best_callout.get("fullName") or f"{best_callout.get('superRegionName', '')} {best_callout.get('regionName', '')}".strip()
            super_region = best_callout.get("superRegionName") or "General"
            return full_name, super_region

        return "Unknown Area", "General"

    def cluster_points(
        self,
        points: list[dict[str, Any]],
        map_identifier: str,
        tags: Optional[list[VodTag]] = None,
        event_type: str = "death",
        side: str = "all",
    ) -> list[SpatialCluster]:
        """Cluster spatial coordinates into discrete tactical hotspots."""
        if not points:
            return []

        tags = tags or []
        unvisited = list(points)
        clusters: list[SpatialCluster] = []
        cluster_id = 1
        total_pts = len(points)

        # Greedy iterative density clustering
        while unvisited:
            # Find the point with highest neighborhood density
            best_seed: Optional[dict[str, Any]] = None
            best_neighbors: list[dict[str, Any]] = []

            for candidate in unvisited:
                cx, cy = candidate["norm_x"], candidate["norm_y"]
                neighbors = [
                    p for p in unvisited
                    if math.hypot(p["norm_x"] - cx, p["norm_y"] - cy) <= self.cluster_radius
                ]
                if len(neighbors) > len(best_neighbors):
                    best_neighbors = neighbors
                    best_seed = candidate

            # If the densest neighborhood is below the minimum threshold, break
            if not best_seed or len(best_neighbors) < self.min_cluster_size:
                # Group remaining points as individual minor incidents if clusters list is empty
                if not clusters and unvisited:
                    for p in unvisited:
                        zone, super_r = self.find_nearest_callout(map_identifier, p["norm_x"], p["norm_y"])
                        clusters.append(
                            SpatialCluster(
                                cluster_id=cluster_id,
                                center_x=p["norm_x"],
                                center_y=p["norm_y"],
                                event_count=1,
                                percentage=(1 / total_pts) * 100,
                                zone_name=zone,
                                super_region=super_r,
                                radius=0.03,
                                event_type=event_type,
                                points=[p],
                                tactical_summary=f"Single incident at {zone}.",
                            )
                        )
                        cluster_id += 1
                break

            # Compute weighted centroid of best neighbors
            sum_x = sum(p["norm_x"] for p in best_neighbors)
            sum_y = sum(p["norm_y"] for p in best_neighbors)
            count = len(best_neighbors)
            center_x = sum_x / count
            center_y = sum_y / count

            # Calculate actual cluster radius (max distance from centroid)
            max_r = max(math.hypot(p["norm_x"] - center_x, p["norm_y"] - center_y) for p in best_neighbors)
            radius = max(0.03, max_r)

            # Determine zone name
            zone_name, super_region = self.find_nearest_callout(map_identifier, center_x, center_y)

            # Correlate tags with this cluster
            correlated_tags = self._correlate_tags_with_cluster(best_neighbors, tags)

            # Build tactical summary
            summary = self._generate_tactical_summary(
                zone_name=zone_name,
                super_region=super_region,
                count=count,
                total_events=total_pts,
                event_type=event_type,
                side=side,
                correlated_tags=correlated_tags,
            )

            cluster = SpatialCluster(
                cluster_id=cluster_id,
                center_x=center_x,
                center_y=center_y,
                event_count=count,
                percentage=(count / total_pts) * 100,
                zone_name=zone_name,
                super_region=super_region,
                radius=radius,
                event_type=event_type,
                points=best_neighbors,
                correlated_tags=correlated_tags,
                tactical_summary=summary,
            )
            clusters.append(cluster)
            cluster_id += 1

            # Remove clustered points from unvisited pool
            neighbor_ids = {id(p) for p in best_neighbors}
            unvisited = [p for p in unvisited if id(p) not in neighbor_ids]

        # Sort clusters by event count descending
        clusters.sort(key=lambda c: c.event_count, reverse=True)
        return clusters

    def _correlate_tags_with_cluster(
        self, cluster_points: list[dict[str, Any]], tags: list[VodTag]
    ) -> list[dict[str, Any]]:
        """Find review tags that match events or timestamps within this spatial cluster."""
        if not tags or not cluster_points:
            return []

        matched_counts: dict[tuple[str, str], int] = {}
        cluster_event_ids = {p.get("event_id") for p in cluster_points if p.get("event_id") is not None}
        cluster_times = [(p.get("match_id"), p.get("event_time_ms", 0)) for p in cluster_points]

        for tag in tags:
            is_match = False
            # Direct event ID link
            if tag.event_id is not None and tag.event_id in cluster_event_ids:
                is_match = True
            else:
                # Timestamp proximity within 4 seconds of a clustered death/kill in the same match
                for mid, t_ms in cluster_times:
                    if tag.match_id == mid and abs(tag.timestamp_ms - t_ms) <= 4000:
                        is_match = True
                        break

            if is_match:
                key = (tag.tag_category, tag.tag_name)
                matched_counts[key] = matched_counts.get(key, 0) + 1

        results = [
            {"category": cat, "name": name, "count": cnt}
            for (cat, name), cnt in matched_counts.items()
        ]
        results.sort(key=lambda x: x["count"], reverse=True)
        return results

    def _generate_tactical_summary(
        self,
        zone_name: str,
        super_region: str,
        count: int,
        total_events: int,
        event_type: str,
        side: str,
        correlated_tags: list[dict[str, Any]],
    ) -> str:
        """Construct actionable coaching advice for the identified hotspot."""
        pct = (count / total_events) * 100 if total_events > 0 else 0

        tag_str = ""
        if correlated_tags:
            top_tag = correlated_tags[0]
            tag_str = f" Commonly tagged with '{top_tag['name']}' ({top_tag['count']}x)."

        if event_type == "death":
            side_label = f"on {side.upper()}" if side in ("attack", "defense") else "across rounds"
            if "Main" in zone_name or "Choke" in zone_name or "Lobby" in zone_name:
                return (
                    f"Entry Chokepoint Trap ({count} deaths, {pct:.1f}% of total {side_label})."
                    f" High vulnerability to dry-peeks or enemy defensive delay utility.{tag_str}"
                    " Recommend pairing flash/initiator utility before crossing."
                )
            elif "Site" in zone_name:
                return (
                    f"Site Engagement Hotspot ({count} deaths, {pct:.1f}%). Repeatedly caught inside {zone_name}."
                    f"{tag_str} Consider isolating post-plant angles or playing off-site crossfires."
                )
            elif "Mid" in zone_name or "Courtyard" in zone_name or "Catwalk" in zone_name:
                return (
                    f"Mid Territory Vulnerability ({count} deaths, {pct:.1f}%)."
                    f" Exposed to multi-angle Operator lines or split pinches.{tag_str}"
                    " Maintain smoke coverage before contesting."
                )
            else:
                return (
                    f"Recurring Death Cluster in {zone_name} ({count} deaths, {pct:.1f}% of total).{tag_str}"
                )
        else:
            # Fragging hotspot
            return (
                f"High-Impact Frag Zone ({count} kills, {pct:.1f}% of frags). Dominant engagement control in {zone_name}."
            )

    def generate_density_grid(
        self, points: list[dict[str, Any]], grid_size: int = 24
    ) -> list[dict[str, Any]]:
        """Discretize points into a 2D spatial grid for fast heat rasterization."""
        if not points:
            return []

        grid: dict[tuple[int, int], int] = {}
        for p in points:
            gx = min(grid_size - 1, max(0, int(p["norm_x"] * grid_size)))
            gy = min(grid_size - 1, max(0, int(p["norm_y"] * grid_size)))
            grid[(gx, gy)] = grid.get((gx, gy), 0) + 1

        max_count = max(grid.values()) if grid else 1
        cells = []
        for (gx, gy), cnt in grid.items():
            cells.append({
                "gx": gx,
                "gy": gy,
                "norm_x": round((gx + 0.5) / grid_size, 4),
                "norm_y": round((gy + 0.5) / grid_size, 4),
                "count": cnt,
                "weight": round(cnt / max_count, 3),
            })
        return cells

    def build_aggregation_result(
        self,
        map_id: str,
        map_name: str,
        match_ids: list[str],
        points: list[dict[str, Any]],
        tags: Optional[list[VodTag]] = None,
        event_type: str = "death",
        side: str = "all",
    ) -> HeatmapAggregationResult:
        """Run full clustering, grid generation, and tactical macro assessment."""
        clusters = self.cluster_points(
            points=points,
            map_identifier=map_id,
            tags=tags,
            event_type=event_type,
            side=side,
        )
        density_grid = self.generate_density_grid(points)

        # Macro tactical insights
        tactical_insights = []
        if clusters:
            top = clusters[0]
            tactical_insights.append(
                f"Primary hotspot on {map_name}: {top.zone_name} accounts for {top.percentage:.1f}% of all {event_type}s ({top.event_count} events)."
            )
            if len(clusters) > 1:
                sec = clusters[1]
                tactical_insights.append(
                    f"Secondary hotspot: {sec.zone_name} ({sec.event_count} events, {sec.percentage:.1f}%)."
                )

            # Check if majority of deaths are on Attack vs Defense
            if side == "all":
                atk_pts = [p for p in points if p.get("round_number", 0) < 12]
                def_pts = [p for p in points if p.get("round_number", 0) >= 12]
                total = len(points)
                if total > 0:
                    atk_ratio = len(atk_pts) / total
                    if atk_ratio > 0.65:
                        tactical_insights.append(
                            f"Heavy Attack-side flaw bias: {atk_ratio * 100:.0f}% of deaths occurred during attacking rounds (Rounds 1-12)."
                        )
                    elif atk_ratio < 0.35:
                        tactical_insights.append(
                            f"Heavy Defense-side flaw bias: {(1 - atk_ratio) * 100:.0f}% of deaths occurred during defensive setups (Rounds 13+)."
                        )
        else:
            tactical_insights.append(f"No concentrated {event_type} clusters identified across the {len(match_ids)} match(es).")

        return HeatmapAggregationResult(
            map_id=map_id,
            map_name=map_name,
            match_count=len(match_ids),
            match_ids=match_ids,
            total_events=len(points),
            event_type=event_type,
            side=side,
            points=points,
            clusters=clusters,
            density_grid=density_grid,
            tactical_insights=tactical_insights,
        )
