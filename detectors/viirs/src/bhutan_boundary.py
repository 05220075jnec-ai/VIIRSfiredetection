"""Bhutan boundary filtering for detected VIIRS hotspots."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src.geospatial_inputs import load_vector


def _load_bhutan_geometry(boundary_path: Path):
    """Return one WGS84 Bhutan geometry from a vector boundary layer."""
    boundary = load_vector(boundary_path).to_crs("EPSG:4326")
    boundary["geometry"] = boundary.geometry.make_valid()
    boundary = boundary[~boundary.geometry.is_empty]
    if boundary.empty:
        raise ValueError(f"{boundary_path} contains no usable boundary geometry.")
    return boundary.geometry.union_all()


def filter_detections_to_bhutan(detections: pd.DataFrame, boundary_path: Path | None) -> pd.DataFrame:
    """Keep only hotspot points that fall inside the Bhutan boundary polygon.

    VIIRS swaths are first cropped with a rectangular bbox for speed. A bbox is
    intentionally loose, so points in nearby Indian states or Tibet can still
    appear. This polygon filter is the authoritative country clip used before
    adding terrain, LULC, building, fusion, and export fields.
    """
    if detections.empty or boundary_path is None:
        return detections

    bhutan = _load_bhutan_geometry(boundary_path)
    points = gpd.GeoSeries(
        [Point(row.longitude, row.latitude) for row in detections.itertuples()],
        crs="EPSG:4326",
    )
    inside = points.apply(lambda point: bhutan.covers(point))
    return detections.loc[inside.to_numpy()].reset_index(drop=True)
