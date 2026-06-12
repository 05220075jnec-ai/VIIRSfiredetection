"""Small utility helpers used across the detector."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def ensure_directory(path: Path) -> Path:
    """Create a directory if it does not already exist."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def haversine_distance_m(lon1, lat1, lon2, lat2) -> np.ndarray:
    """Return approximate great-circle distance in meters."""
    radius_m = 6_371_000.0
    lon1 = np.radians(lon1)
    lat1 = np.radians(lat1)
    lon2 = np.radians(lon2)
    lat2 = np.radians(lat2)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return radius_m * 2.0 * np.arcsin(np.sqrt(a))


def confidence_to_mask_class(score: float) -> int:
    """Convert a 0-100 confidence score to VIIRS-style fire mask class."""
    if score >= 85:
        return 9
    if score >= 65:
        return 8
    return 7


def normalize_score(value: float, low: float, high: float) -> float:
    """Normalize a value to 0-1 with clipping."""
    if high <= low:
        return 0.0
    return float(np.clip((value - low) / (high - low), 0.0, 1.0))
