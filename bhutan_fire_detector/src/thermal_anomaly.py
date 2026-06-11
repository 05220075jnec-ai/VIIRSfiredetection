from __future__ import annotations

import numpy as np
import pandas as pd

from config import Thresholds


def detect_thermal_anomalies(df: pd.DataFrame, thresholds: Thresholds) -> pd.DataFrame:
    """Apply I4 and M13 contextual anomaly tests."""
    result = df.copy()
    result["I4_anomaly"] = result["I4_BT"] - result["background_I4"]
    result["M13_anomaly"] = result["M13_BT"] - result["background_M13"]

    result["i4_pass"] = result["I4_anomaly"] > result["k1_adjusted"] * result["std_background_I4"]
    result["m13_pass"] = result["M13_anomaly"] > result["k2_adjusted"] * result["std_background_M13"]
    result["absolute_pass"] = result["I4_BT"] >= thresholds.brightness_temp

    candidates = result[result["i4_pass"] | result["absolute_pass"]].copy()
    candidates["base_confidence"] = np.where(candidates["m13_pass"], 0.70, 0.42)
    candidates.loc[candidates["i4_pass"] & candidates["m13_pass"], "base_confidence"] = 0.82
    candidates["confidence_score"] = candidates["base_confidence"]
    candidates["fire_class"] = np.where(candidates["m13_pass"], "Probable Fire", "Anomaly")
    return candidates.reset_index(drop=True)
