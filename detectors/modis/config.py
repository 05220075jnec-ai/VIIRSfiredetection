"""Configuration for the Bhutan MODIS active-fire detector."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]


@dataclass(frozen=True)
class Paths:
    data: Path = WORKSPACE_ROOT / "data" / "raw" / "modis" / "hdf"
    outputs: Path = WORKSPACE_ROOT / "outputs" / "modis_detector_test"
    boundary: Path = WORKSPACE_ROOT / "data" / "reference" / "boundaries" / "bhutan_dzong_web.geojson"
    lulc: Path = (
        WORKSPACE_ROOT
        / "data"
        / "reference"
        / "lulc"
        / "Land Use Land Cover 2020.shp"
    )


@dataclass(frozen=True)
class DetectionThresholds:
    day_candidate_t4_k: float = 310.0
    night_candidate_t4_k: float = 305.0
    candidate_delta_k: float = 10.0
    day_absolute_t4_k: float = 360.0
    night_absolute_t4_k: float = 320.0
    band22_saturation_k: float = 330.0
    contextual_delta_mad_multiplier: float = 3.5
    contextual_delta_floor_k: float = 6.0
    contextual_t4_mad_multiplier: float = 3.0
    contextual_t11_mad_multiplier: float = 1.0
    contextual_t11_offset_k: float = 4.0
    background_start_window: int = 3
    background_max_window: int = 21
    background_min_pixels: int = 8
    background_min_fraction: float = 0.25
    cold_cloud_t11_k: float = 265.0
    reflective_cloud_t11_k: float = 285.0
    reflective_cloud_sum: float = 0.90
    bright_surface_band2: float = 0.30
    day_solar_zenith_deg: float = 85.0


PATHS = Paths()
THRESHOLDS = DetectionThresholds()

MODIS_WAVELENGTHS_UM = {
    "21": 3.959,
    "22": 3.959,
    "31": 11.030,
    "32": 12.020,
}

FIRE_MASK_CLASSES = {
    0: "not processed",
    1: "water",
    2: "cloud",
    3: "clear land",
    7: "low confidence fire",
    8: "nominal confidence fire",
    9: "high confidence fire",
}

BHUTAN_BOUNDS = {
    "min_lon": 88.4,
    "max_lon": 92.6,
    "min_lat": 26.4,
    "max_lat": 28.6,
}
