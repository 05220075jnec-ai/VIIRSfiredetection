"""Proximity-based threat classification."""

from __future__ import annotations

import pandas as pd

from config import RISK


def classify_threat(row) -> str:
    """Classify final alert threat using context, confidence, and building distance."""
    if row.fire_context in ("roof_false_positive", "possible_roof_false_positive", "water_false_positive"):
        return "No Alert"

    distance = float(row.distance_to_nearest_building_m)
    confidence = float(row.final_confidence_score)
    confirmed = confidence >= 85.0 or int(row.number_of_satellites_detected) >= 2

    if confirmed and distance <= RISK.instant_alert_m:
        return "Instant Alert"
    if confirmed and distance <= RISK.high_risk_m:
        return "High Risk"
    if confirmed and distance <= RISK.warning_m:
        return "Warning"
    if row.fire_context == "forest_fire" and distance <= RISK.high_risk_m:
        return "High Risk"
    if row.fire_context == "agricultural_burning" and distance > RISK.warning_m:
        return "Monitor"
    return "Monitor"


def add_threat_levels(detections: pd.DataFrame) -> pd.DataFrame:
    """Add final threat level labels."""
    if detections.empty:
        return detections
    result = detections.copy()
    result["final_threat_level"] = [classify_threat(row) for row in result.itertuples()]
    return result
