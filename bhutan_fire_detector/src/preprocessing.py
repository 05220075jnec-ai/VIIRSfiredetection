from __future__ import annotations

import pandas as pd

from config import BhutanBounds


def prepare_observations(df: pd.DataFrame, bounds: BhutanBounds) -> pd.DataFrame:
    """Normalize columns and keep only observations inside Bhutan's bounding box."""
    prepared = df.copy()
    prepared["detection_time"] = pd.to_datetime(prepared["detection_time"], utc=True)
    prepared["satellite"] = prepared["satellite"].astype(str).str.lower()

    numeric_columns = ["latitude", "longitude", "I4_BT", "M13_BT"]
    for column in numeric_columns:
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")

    prepared = prepared.dropna(subset=numeric_columns + ["detection_time"])
    prepared = prepared[
        prepared["latitude"].between(bounds.min_lat, bounds.max_lat)
        & prepared["longitude"].between(bounds.min_lon, bounds.max_lon)
    ]
    prepared["grid_cell"] = (
        prepared["latitude"].round(2).astype(str)
        + "_"
        + prepared["longitude"].round(2).astype(str)
    )
    return prepared.sort_values("detection_time").reset_index(drop=True)
