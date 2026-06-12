"""Multi-satellite temporal fusion for SNPP, NOAA-20, and NOAA-21."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from config import FUSION
from src.utils import confidence_to_mask_class, haversine_distance_m


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def fuse_detections(detections: pd.DataFrame) -> pd.DataFrame:
    """Fuse detections within 375 m and a rolling 3-hour window."""
    if detections.empty:
        return detections

    records = detections.copy().sort_values("acquisition_time").reset_index(drop=True)
    used = np.zeros(len(records), dtype=bool)
    fused_rows = []

    for idx, row in records.iterrows():
        if used[idx]:
            continue

        row_time = _parse_time(row["acquisition_time"])
        distances = haversine_distance_m(row["longitude"], row["latitude"], records["longitude"].to_numpy(), records["latitude"].to_numpy())
        time_deltas = records["acquisition_time"].map(lambda value: abs((_parse_time(value) - row_time).total_seconds()) / 3600.0)
        group_mask = (distances <= FUSION.spatial_tolerance_m) & (time_deltas <= FUSION.rolling_window_hours) & ~used
        group = records[group_mask]
        used[group_mask] = True

        satellites = sorted(group["satellite"].dropna().unique())
        first_time = min(_parse_time(value) for value in group["acquisition_time"])
        last_time = max(_parse_time(value) for value in group["acquisition_time"])
        persistence = int((last_time - first_time).total_seconds() / 60.0)
        temporal_confidence = min(100.0, 35.0 + 25.0 * len(satellites) + min(20.0, persistence / 3.0))

        best = group.sort_values("thermal_confidence", ascending=False).iloc[0].to_dict()
        best["satellite_sources"] = ",".join(satellites)
        best["number_of_satellites_detected"] = len(satellites)
        best["first_detection_time"] = first_time.isoformat()
        best["last_detection_time"] = last_time.isoformat()
        best["persistence_minutes"] = persistence
        best["temporal_confidence"] = temporal_confidence
        fused_rows.append(best)

    result = pd.DataFrame(fused_rows)
    result["final_context_class"] = result["fire_context"]
    result["final_confidence_score"] = [
        final_confidence(row) for row in result.itertuples()
    ]
    result["fire_mask_class"] = result["final_confidence_score"].map(confidence_to_mask_class)
    return result


def final_confidence(row) -> float:
    """Combine thermal, contextual, M13, terrain, LULC, building, and temporal evidence."""
    score = 0.42 * float(row.thermal_confidence)
    score += 0.18 * float(row.contextual_confidence)
    score += 0.22 * float(row.temporal_confidence)
    score += 10.0 if bool(row.m13_confirmed) else -8.0
    score -= 8.0 if row.terrain_false_positive_risk == "high" else 0.0
    score -= 25.0 * float(row.roof_false_positive_score)
    score += 20.0 * float(row.structure_fire_probability)

    if row.fire_context == "forest_fire":
        score += 5.0
    elif row.fire_context in ("roof_false_positive", "water_false_positive"):
        score -= 35.0
    elif row.fire_context == "agricultural_burning":
        score -= 4.0

    return float(np.clip(score, 1.0, 99.0))
