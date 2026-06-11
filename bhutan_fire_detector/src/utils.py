from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point


WGS84 = "EPSG:4326"
BHUTAN_METRIC_CRS = "EPSG:32646"


def parse_time(value) -> pd.Timestamp:
    timestamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(timestamp):
        return pd.Timestamp(datetime.now(timezone.utc))
    return timestamp


def to_geodataframe(df: pd.DataFrame) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        df.copy(),
        geometry=gpd.points_from_xy(df["longitude"], df["latitude"]),
        crs=WGS84,
    )


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    transformer = Transformer.from_crs(WGS84, BHUTAN_METRIC_CRS, always_xy=True)
    x1, y1 = transformer.transform(lon1, lat1)
    x2, y2 = transformer.transform(lon2, lat2)
    return math.hypot(x2 - x1, y2 - y1)


def safe_read_vector(path: Path) -> gpd.GeoDataFrame | None:
    if not path.exists():
        return None
    layer = gpd.read_file(path)
    if layer.crs is None:
        return layer.set_crs(WGS84)
    return layer.to_crs(WGS84)


def bhutan_point(lat: float, lon: float) -> Point:
    return Point(float(lon), float(lat))
