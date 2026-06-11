"""Configuration for the Bhutan VIIRS fire detector."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Paths:
    """Project input and output paths."""

    viirs: Path = PROJECT_ROOT / "data" / "viirs"
    dem: Path = PROJECT_ROOT / "data" / "dem"
    lulc: Path = PROJECT_ROOT / "data" / "lulc"
    buildings: Path = PROJECT_ROOT / "data" / "buildings"
    vectors: Path = PROJECT_ROOT / "data" / "vectors"
    outputs: Path = PROJECT_ROOT / "outputs"


@dataclass(frozen=True)
class DetectionThresholds:
    """Thermal thresholds based on VIIRS 375 m active-fire logic."""

    i4_saturation_k: float = 367.0
    i4_saturation_margin_k: float = 1.0
    day_high_bt4_k: float = 335.0
    day_high_delta_k: float = 30.0
    night_high_bt4_k: float = 300.0
    night_high_delta_k: float = 10.0
    day_candidate_bt4_k: float = 325.0
    day_candidate_delta_k: float = 25.0
    night_candidate_bt4_k: float = 295.0
    night_candidate_delta_k: float = 10.0
    bright_surface_i3: float = 0.30
    bright_surface_i2: float = 0.25
    contextual_min_background_pixels: int = 25
    contextual_start_window: int = 11
    contextual_max_window: int = 35
    contextual_mad_multiplier: float = 2.0
    contextual_day_delta_floor_k: float = 10.0
    k_m13: float = 2.0


@dataclass(frozen=True)
class FusionConfig:
    """Settings for multi-satellite temporal fusion."""

    rolling_window_hours: float = 3.0
    spatial_tolerance_m: float = 375.0


@dataclass(frozen=True)
class RiskConfig:
    """Distance thresholds for building and infrastructure alerts."""

    instant_alert_m: float = 100.0
    high_risk_m: float = 500.0
    warning_m: float = 1000.0
    building_count_radii_m: tuple[float, float, float] = (500.0, 1000.0, 2000.0)


PATHS = Paths()
THRESHOLDS = DetectionThresholds()
FUSION = FusionConfig()
RISK = RiskConfig()

SATELLITES = ("SNPP", "NOAA20", "NOAA21")

BHUTAN_BOUNDS = {
    "min_lon": 88.7,
    "max_lon": 92.2,
    "min_lat": 26.6,
    "max_lat": 28.4,
}

FIRE_MASK_CLASSES = {
    0: "not processed",
    1: "residual bowtie pixel",
    3: "water",
    4: "cloud",
    5: "land",
    7: "low confidence fire",
    8: "nominal confidence fire",
    9: "high confidence fire",
}
