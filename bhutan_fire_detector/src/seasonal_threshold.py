from __future__ import annotations

import pandas as pd

from config import Config


SEASON_MULTIPLIER = {
    "winter": 0.90,
    "spring": 1.00,
    "dry": 1.15,
    "monsoon": 1.30,
}


def season_for_month(month: int) -> str:
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4):
        return "spring"
    if month in (5,):
        return "dry"
    if month in (6, 7, 8, 9):
        return "monsoon"
    return "dry"


def weather_adjustment(weather_temp_c: float | None) -> float:
    if weather_temp_c is None or pd.isna(weather_temp_c):
        return 1.0
    if weather_temp_c >= 30:
        return 1.10
    if weather_temp_c <= 5:
        return 0.92
    return 1.0


def apply_seasonal_thresholds(df: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Attach rolling local background and seasonal k1/k2 values."""
    result = df.copy()
    result["season"] = result["detection_time"].dt.month.map(season_for_month)
    result["season_multiplier"] = result["season"].map(SEASON_MULTIPLIER).fillna(1.0)

    rolling = (
        result.sort_values("detection_time")
        .groupby("grid_cell", group_keys=False)[["I4_BT", "M13_BT"]]
        .rolling(window=40, min_periods=8)
    )
    stats = rolling.agg(["mean", "std"]).reset_index(level=0, drop=True)
    result["background_I4"] = stats[("I4_BT", "mean")].fillna(result["I4_BT"].median())
    result["std_background_I4"] = stats[("I4_BT", "std")].fillna(result["I4_BT"].std())
    result["background_M13"] = stats[("M13_BT", "mean")].fillna(result["M13_BT"].median())
    result["std_background_M13"] = stats[("M13_BT", "std")].fillna(result["M13_BT"].std())

    result["std_background_I4"] = result["std_background_I4"].clip(lower=1.0)
    result["std_background_M13"] = result["std_background_M13"].clip(lower=1.0)
    result["k1_adjusted"] = config.thresholds.k1_i4 * result["season_multiplier"]
    result["k2_adjusted"] = config.thresholds.k2_m13 * result["season_multiplier"]
    return result
