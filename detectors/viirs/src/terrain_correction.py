"""Terrain correction and terrain false-positive risk logic."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.windows import Window


def calculate_slope_aspect(dem: np.ndarray, pixel_size_m: float = 30.0) -> tuple[np.ndarray, np.ndarray]:
    """Calculate slope and aspect from a DEM array."""
    dz_dy, dz_dx = np.gradient(dem, pixel_size_m, pixel_size_m)
    slope = np.degrees(np.arctan(np.sqrt(dz_dx**2 + dz_dy**2)))
    aspect = (np.degrees(np.arctan2(-dz_dx, dz_dy)) + 360.0) % 360.0
    return slope, aspect


def solar_position(dt: datetime, latitude: float, longitude: float) -> tuple[float, float]:
    """Approximate solar azimuth and elevation in degrees."""
    day = dt.timetuple().tm_yday
    declination = 23.45 * np.sin(np.radians(360.0 * (284 + day) / 365.0))
    hour = dt.hour + dt.minute / 60.0
    solar_time = hour + longitude / 15.0
    hour_angle = 15.0 * (solar_time - 12.0)
    lat_rad = np.radians(latitude)
    dec_rad = np.radians(declination)
    ha_rad = np.radians(hour_angle)
    elevation = np.degrees(np.arcsin(np.sin(lat_rad) * np.sin(dec_rad) + np.cos(lat_rad) * np.cos(dec_rad) * np.cos(ha_rad)))
    azimuth = (180.0 + np.degrees(np.arctan2(np.sin(ha_rad), np.cos(ha_rad) * np.sin(lat_rad) - np.tan(dec_rad) * np.cos(lat_rad)))) % 360.0
    return float(azimuth), float(elevation)


def solar_incidence_angle(slope_deg: float, aspect_deg: float, solar_azimuth_deg: float, solar_elevation_deg: float) -> float:
    """Calculate incidence angle between terrain normal and sun vector."""
    slope = np.radians(slope_deg)
    aspect = np.radians(aspect_deg)
    zenith = np.radians(90.0 - solar_elevation_deg)
    azimuth = np.radians(solar_azimuth_deg)
    cos_i = np.cos(zenith) * np.cos(slope) + np.sin(zenith) * np.sin(slope) * np.cos(azimuth - aspect)
    return float(np.degrees(np.arccos(np.clip(cos_i, -1.0, 1.0))))


def terrain_factor(slope_deg: float, incidence_deg: float, is_day: bool) -> tuple[float, str]:
    """Return terrain correction factor and false-positive risk label."""
    if not is_day:
        return 1.0, "low"
    if slope_deg > 28.0 and incidence_deg < 45.0:
        return 1.12, "high"
    if incidence_deg > 100.0:
        return 0.94, "low"
    return 1.0, "moderate"


class DEMSampler:
    """Sample elevation, slope, and aspect from a real DEM GeoTIFF."""

    def __init__(self, dem_path: Path):
        self.dem_path = dem_path
        self.dataset = rasterio.open(dem_path)
        self.transformer = Transformer.from_crs("EPSG:4326", self.dataset.crs, always_xy=True)
        self.pixel_size_m = float(abs(self.dataset.transform.a))

    def close(self) -> None:
        """Close the raster dataset."""
        self.dataset.close()

    def sample(self, longitude: float, latitude: float) -> tuple[float, float, float]:
        """Sample elevation, local slope, and aspect for a WGS84 coordinate."""
        x, y = self.transformer.transform(longitude, latitude)
        row, col = self.dataset.index(x, y)

        if row < 0 or col < 0 or row >= self.dataset.height or col >= self.dataset.width:
            return float("nan"), float("nan"), float("nan")

        elevation = next(self.dataset.sample([(x, y)]))[0]
        if self.dataset.nodata is not None and elevation == self.dataset.nodata:
            return float("nan"), float("nan"), float("nan")

        window_size = 5
        half = window_size // 2
        window = Window(
            max(0, col - half),
            max(0, row - half),
            min(window_size, self.dataset.width - max(0, col - half)),
            min(window_size, self.dataset.height - max(0, row - half)),
        )
        local = self.dataset.read(1, window=window, masked=True).astype("float64")
        if local.count() < 9:
            return float(elevation), 0.0, 0.0

        local_filled = local.filled(float(local.mean()))
        slope_grid, aspect_grid = calculate_slope_aspect(local_filled, self.pixel_size_m)
        center_r = min(half, slope_grid.shape[0] - 1)
        center_c = min(half, slope_grid.shape[1] - 1)
        return float(elevation), float(slope_grid[center_r, center_c]), float(aspect_grid[center_r, center_c])


def _synthetic_terrain(longitude: float, latitude: float) -> tuple[float, float, float]:
    """Fallback terrain values when no DEM is available."""
    elevation = 500.0 + (latitude - 26.6) * 1200.0 + np.sin(longitude * 5.0) * 200.0
    slope = float(np.clip(abs(np.sin(latitude * longitude)) * 40.0, 0.0, 45.0))
    aspect = float((longitude * 100.0) % 360.0)
    return float(elevation), slope, aspect


def add_terrain_context(detections: pd.DataFrame, dem_path: Path | None = None) -> pd.DataFrame:
    """Attach terrain context from a real DEM, with synthetic fallback."""
    if detections.empty:
        return detections

    result = detections.copy()
    sampler = DEMSampler(dem_path) if dem_path else None
    factors = []
    risks = []
    elevations = []
    slopes = []
    aspects = []

    try:
        for row in result.itertuples():
            if sampler:
                elevation, slope, aspect = sampler.sample(row.longitude, row.latitude)
                if not np.isfinite(elevation):
                    elevation, slope, aspect = _synthetic_terrain(row.longitude, row.latitude)
            else:
                elevation, slope, aspect = _synthetic_terrain(row.longitude, row.latitude)

            dt = datetime.fromisoformat(row.acquisition_time)
            solar_azimuth, solar_elevation = solar_position(dt, row.latitude, row.longitude)
            incidence = solar_incidence_angle(slope, aspect, solar_azimuth, solar_elevation)
            factor, risk = terrain_factor(slope, incidence, solar_elevation > 0)
            factors.append(factor)
            risks.append(risk)
            elevations.append(elevation)
            slopes.append(slope)
            aspects.append(aspect)
    finally:
        if sampler:
            sampler.close()

    result["elevation_m"] = elevations
    result["slope_deg"] = slopes
    result["aspect_deg"] = aspects
    result["terrain_correction_factor"] = factors
    result["terrain_false_positive_risk"] = risks
    return result
