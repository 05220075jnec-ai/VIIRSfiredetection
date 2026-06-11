from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd

try:
    import rasterio
except ImportError:  # DEM terrain sampling is optional until rasterio is installed.
    rasterio = None

from config import Config


def calculate_slope(dem: np.ndarray, pixel_size: float) -> np.ndarray:
    dz_dy, dz_dx = np.gradient(dem, pixel_size)
    return np.degrees(np.arctan(np.sqrt(dz_dx**2 + dz_dy**2)))


def calculate_aspect(dem: np.ndarray, pixel_size: float) -> np.ndarray:
    dz_dy, dz_dx = np.gradient(dem, pixel_size)
    aspect = np.degrees(np.arctan2(-dz_dx, dz_dy))
    return (aspect + 360) % 360


def solar_position(timestamp: datetime, latitude: float, longitude: float) -> tuple[float, float]:
    """Approximate solar azimuth and elevation in degrees."""
    day = timestamp.timetuple().tm_yday
    hour = timestamp.hour + timestamp.minute / 60 + timestamp.second / 3600
    gamma = 2 * math.pi / 365 * (day - 1 + (hour - 12) / 24)
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )
    equation_time = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    time_offset = equation_time + 4 * longitude
    true_solar_time = (hour * 60 + time_offset) % 1440
    hour_angle = math.radians(true_solar_time / 4 - 180)
    lat_rad = math.radians(latitude)

    elevation = math.asin(
        math.sin(lat_rad) * math.sin(decl)
        + math.cos(lat_rad) * math.cos(decl) * math.cos(hour_angle)
    )
    azimuth = math.atan2(
        -math.sin(hour_angle),
        math.tan(decl) * math.cos(lat_rad) - math.sin(lat_rad) * math.cos(hour_angle),
    )
    return (math.degrees(azimuth) + 360) % 360, math.degrees(elevation)


def solar_incidence_angle(
    slope_deg: float,
    aspect_deg: float,
    solar_azimuth_deg: float,
    solar_elevation_deg: float,
) -> float:
    slope = math.radians(slope_deg)
    aspect = math.radians(aspect_deg)
    solar_azimuth = math.radians(solar_azimuth_deg)
    solar_zenith = math.radians(90 - solar_elevation_deg)
    cos_i = (
        math.cos(solar_zenith) * math.cos(slope)
        + math.sin(solar_zenith) * math.sin(slope) * math.cos(solar_azimuth - aspect)
    )
    return math.degrees(math.acos(float(np.clip(cos_i, -1, 1))))


def terrain_correction_factor(slope_deg: float, incidence_deg: float) -> float:
    if slope_deg > 25 and incidence_deg < 45:
        return 1.20
    if incidence_deg > 90:
        return 0.88
    if slope_deg > 35:
        return 1.10
    return 1.0


def apply_terrain_correction(df: pd.DataFrame, config: Config) -> pd.DataFrame:
    result = df.copy()
    result["slope_deg"] = 0.0
    result["aspect_deg"] = 0.0

    if config.paths.dem_file.exists() and rasterio is None:
        raise RuntimeError(
            f"DEM file found at {config.paths.dem_file}, but rasterio is not installed. "
            "Install dependencies with: pip install -r requirements.txt"
        )

    if config.paths.dem_file.exists() and rasterio is not None:
        with rasterio.open(config.paths.dem_file) as src:
            dem = src.read(1, masked=True).filled(np.nan)
            pixel_size = abs(src.transform.a)
            slope = calculate_slope(dem, pixel_size)
            aspect = calculate_aspect(dem, pixel_size)
            coords = list(zip(result["longitude"], result["latitude"]))
            for idx, (row, col) in zip(result.index, (src.index(x, y) for x, y in coords)):
                if 0 <= row < slope.shape[0] and 0 <= col < slope.shape[1]:
                    result.at[idx, "slope_deg"] = float(slope[row, col])
                    result.at[idx, "aspect_deg"] = float(aspect[row, col])

    scores = []
    factors = []
    for row in result.itertuples():
        azimuth, elevation = solar_position(row.detection_time.to_pydatetime(), row.latitude, row.longitude)
        incidence = solar_incidence_angle(row.slope_deg, row.aspect_deg, azimuth, elevation)
        factor = terrain_correction_factor(row.slope_deg, incidence)
        scores.append(incidence)
        factors.append(factor)

    result["solar_incidence_angle"] = scores
    result["terrain_correction_score"] = factors
    result["k1_adjusted"] = result["k1_adjusted"] * result["terrain_correction_score"]
    result["k2_adjusted"] = result["k2_adjusted"] * result["terrain_correction_score"]
    return result
