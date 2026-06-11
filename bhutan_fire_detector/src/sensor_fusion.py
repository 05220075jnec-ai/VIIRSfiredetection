from __future__ import annotations

import pandas as pd

from config import Thresholds
from src.utils import distance_m


def apply_sensor_fusion(detections: pd.DataFrame, thresholds: Thresholds) -> pd.DataFrame:
    if detections.empty:
        return detections

    fused = detections.copy().sort_values("detection_time").reset_index(drop=True)
    fused["supporting_satellites"] = 1
    fused["fusion_support"] = ""

    if fused["satellite"].nunique() <= 1:
        fused["fusion_support"] = fused["satellite"]
        fused["fire_class"] = fused.apply(classify_fire, axis=1)
        return fused

    window = pd.Timedelta(hours=thresholds.fusion_window_hours)
    for idx, row in fused.iterrows():
        time_mask = (fused["detection_time"] - row["detection_time"]).abs() <= window
        nearby = []
        for other_idx, other in fused[time_mask].iterrows():
            if other_idx == idx:
                continue
            if distance_m(row["latitude"], row["longitude"], other["latitude"], other["longitude"]) <= thresholds.fusion_distance_m:
                nearby.append(other["satellite"])

        satellites = sorted(set([row["satellite"], *nearby]))
        fused.at[idx, "supporting_satellites"] = len(satellites)
        fused.at[idx, "fusion_support"] = ",".join(satellites)
        if len(satellites) > 1:
            fused.at[idx, "confidence_score"] = min(
                1.0,
                row["confidence_score"] + thresholds.high_confidence_bonus,
            )

    fused["fire_class"] = fused.apply(classify_fire, axis=1)
    return fused


def classify_fire(row) -> str:
    if row["supporting_satellites"] >= 2 and row["m13_pass"] and row["confidence_score"] >= 0.85:
        return "Confirmed Fire"
    if row["m13_pass"] or row["confidence_score"] >= 0.65:
        return "Probable Fire"
    return "Anomaly"
