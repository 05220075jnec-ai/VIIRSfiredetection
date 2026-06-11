from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class BhutanBounds:
    min_lat: float = 26.7
    max_lat: float = 28.3
    min_lon: float = 88.7
    max_lon: float = 92.1


@dataclass(frozen=True)
class Thresholds:
    brightness_temp: float = 310.0
    frp_threshold: float = 5.0
    contextual_sigma: float = 3.0
    k1_i4: float = 3.0
    k2_m13: float = 2.5
    fusion_distance_m: float = 750.0
    fusion_window_hours: int = 3
    high_confidence_bonus: float = 0.2


@dataclass(frozen=True)
class Paths:
    data: Path = PROJECT_ROOT / "data"
    dem: Path = PROJECT_ROOT / "data" / "dem"
    viirs: Path = PROJECT_ROOT / "data" / "viirs"
    weather: Path = PROJECT_ROOT / "data" / "weather"
    vectors: Path = PROJECT_ROOT / "data" / "vectors"
    outputs: Path = PROJECT_ROOT / "outputs"

    @property
    def dem_file(self) -> Path:
        return self.dem / "bhutan_dem_10m.tif"


@dataclass(frozen=True)
class Config:
    earthdata_username: str = os.getenv("EARTHDATA_USERNAME", "")
    earthdata_password: str = os.getenv("EARTHDATA_PASSWORD", "")
    laads_token: str = os.getenv("LAADS_TOKEN", "")

    viirs_sources: dict[str, str] = field(
        default_factory=lambda: {
            "suomi_npp": "https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/5110/VNP14A1NRT",
            "noaa20": "https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/5110/VJ114A1NRT",
            "noaa21": "https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/5110/VJ214A1NRT",
        }
    )

    bounds: BhutanBounds = field(default_factory=BhutanBounds)
    thresholds: Thresholds = field(default_factory=Thresholds)
    paths: Paths = field(default_factory=Paths)

    update_interval_minutes: int = 15
    data_retention_days: int = 30
    database_url: str = "sqlite:///fire_detection.db"

    def ensure_directories(self) -> None:
        for path in (
            self.paths.dem,
            self.paths.viirs,
            self.paths.weather,
            self.paths.vectors,
            self.paths.outputs,
        ):
            path.mkdir(parents=True, exist_ok=True)
