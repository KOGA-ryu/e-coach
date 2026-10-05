"""Spatial projection utilities for converting Valorant in-game world coordinates to map pixels."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Optional


@dataclass
class MapCalibration:
    display_name: str
    map_url: str
    x_multiplier: float
    y_multiplier: float
    x_scalar_to_add: float
    y_scalar_to_add: float
    display_icon: Optional[str] = None


# Default built-in map calibrations (fallback if maps.json is not present)
DEFAULT_CALIBRATIONS: dict[str, MapCalibration] = {
    "/Game/Maps/Ascent/Ascent": MapCalibration("Ascent", "/Game/Maps/Ascent/Ascent", 7e-05, -7e-05, 0.813895, 0.573242),
    "/Game/Maps/Bonsai/Bonsai": MapCalibration("Split", "/Game/Maps/Bonsai/Bonsai", 7.8e-05, -7.8e-05, 0.842188, 0.697578),
    "/Game/Maps/Canyon/Canyon": MapCalibration("Fracture", "/Game/Maps/Canyon/Canyon", 7.8e-05, -7.8e-05, 0.556952, 1.155886),
    "/Game/Maps/Duality/Duality": MapCalibration("Bind", "/Game/Maps/Duality/Duality", 5.9e-05, -5.9e-05, 0.576941, 0.967566),
    "/Game/Maps/Foxtrot/Foxtrot": MapCalibration("Breeze", "/Game/Maps/Foxtrot/Foxtrot", 7e-05, -7e-05, 0.465123, 0.833078),
    "/Game/Maps/Infinity/Infinity": MapCalibration("Abyss", "/Game/Maps/Infinity/Infinity", 8.1e-05, -8.1e-05, 0.5, 0.5),
    "/Game/Maps/Jam/Jam": MapCalibration("Lotus", "/Game/Maps/Jam/Jam", 7.2e-05, -7.2e-05, 0.454789, 0.917752),
    "/Game/Maps/Juliett/Juliett": MapCalibration("Sunset", "/Game/Maps/Juliett/Juliett", 7.8e-05, -7.8e-05, 0.5, 0.515625),
    "/Game/Maps/Pitt/Pitt": MapCalibration("Pearl", "/Game/Maps/Pitt/Pitt", 7.8e-05, -7.8e-05, 0.480469, 0.916016),
    "/Game/Maps/Port/Port": MapCalibration("Icebox", "/Game/Maps/Port/Port", 7.2e-05, -7.2e-05, 0.460214, 0.304687),
    "/Game/Maps/Triad/Triad": MapCalibration("Haven", "/Game/Maps/Triad/Triad", 7.5e-05, -7.5e-05, 1.09345, 0.642728),
    "/Game/Maps/Rook/Rook": MapCalibration("Corrode", "/Game/Maps/Rook/Rook", 7e-05, -7e-05, 0.526158, 0.5),
}


class CoordinateProjector:
    """Projects Unreal Engine world coordinates into normalized (0..1) and pixel-space coordinates."""

    def __init__(self, data_file: Optional[Path | str] = None):
        self.calibrations: dict[str, MapCalibration] = dict(DEFAULT_CALIBRATIONS)
        self._name_index: dict[str, MapCalibration] = {}

        if data_file and Path(data_file).exists():
            self._load_from_file(Path(data_file))

        self._build_name_index()

    def _load_from_file(self, path: Path) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for map_url, item in raw.items():
                self.calibrations[map_url] = MapCalibration(
                    display_name=item["displayName"],
                    map_url=map_url,
                    x_multiplier=float(item["xMultiplier"]),
                    y_multiplier=float(item["yMultiplier"]),
                    x_scalar_to_add=float(item["xScalarToAdd"]),
                    y_scalar_to_add=float(item["yScalarToAdd"]),
                    display_icon=item.get("displayIcon"),
                )
        except Exception:
            # Fall back to built-ins on error
            pass

    def _build_name_index(self) -> None:
        for cal in self.calibrations.values():
            self._name_index[cal.display_name.lower()] = cal
            self._name_index[cal.map_url.lower()] = cal
            # Also index last segment, e.g. "ascent"
            segment = cal.map_url.strip("/").split("/")[-1].lower()
            self._name_index[segment] = cal

    def get_calibration(self, map_identifier: str) -> Optional[MapCalibration]:
        clean = map_identifier.strip().lower()
        return self._name_index.get(clean)

    def world_to_norm(
        self, map_identifier: str, world_x: float, world_y: float
    ) -> tuple[float, float]:
        """Convert Unreal Engine world coordinates (X, Y) to normalized (0.0 to 1.0) 2D map coordinates."""
        cal = self.get_calibration(map_identifier)
        if not cal:
            return 0.5, 0.5

        # Standard Valorant mapping:
        # 2D X corresponds to world Y scaled by xMultiplier + xScalarToAdd
        # 2D Y corresponds to world X scaled by yMultiplier + yScalarToAdd
        norm_x = (world_y * cal.x_multiplier) + cal.x_scalar_to_add
        norm_y = (world_x * cal.y_multiplier) + cal.y_scalar_to_add

        return norm_x, norm_y

    def norm_to_pixel(
        self, norm_x: float, norm_y: float, width: int, height: int
    ) -> tuple[int, int]:
        """Convert normalized (0..1) coordinates to integer pixel coordinates."""
        px = int(round(norm_x * width))
        py = int(round(norm_y * height))
        return px, py

    def world_to_pixel(
        self, map_identifier: str, world_x: float, world_y: float, width: int, height: int
    ) -> tuple[int, int]:
        """Convert world coordinates directly to pixel coordinates for a given canvas size."""
        norm_x, norm_y = self.world_to_norm(map_identifier, world_x, world_y)
        return self.norm_to_pixel(norm_x, norm_y, width, height)
