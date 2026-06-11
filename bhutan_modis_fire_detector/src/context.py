"""Bhutan boundary and land-cover context for MODIS detections."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point


def filter_to_bhutan(detections: pd.DataFrame, boundary_path: Path) -> pd.DataFrame:
    if detections.empty:
        return detections

    boundary = gpd.read_file(boundary_path).to_crs("EPSG:4326")
    boundary["geometry"] = boundary.geometry.make_valid()
    bhutan = boundary.geometry.union_all()
    points = gpd.GeoSeries(
        [Point(row.longitude, row.latitude) for row in detections.itertuples()],
        crs="EPSG:4326",
    )
    inside = points.apply(bhutan.covers)
    return detections.loc[inside.to_numpy()].reset_index(drop=True)


def _detect_lulc_column(lulc: gpd.GeoDataFrame) -> str | None:
    preferred = ["class_name", "Class_Name", "CLASS_NAME", "lulc_class", "LULC", "class", "Name", "name"]
    for column in preferred:
        if column in lulc.columns:
            return column
    candidates = [
        column
        for column in lulc.columns
        if column != "geometry" and lulc[column].dtype == object
    ]
    return candidates[0] if candidates else None


def _normalize_lulc(value: object) -> str:
    text = str(value or "").strip().casefold()
    if "water" in text:
        return "water"
    if "agriculture" in text or "crop" in text or "paddy" in text:
        return "agriculture"
    if "forest" in text:
        return "forest"
    if "built" in text and "non" not in text:
        return "built-up"
    if "shrub" in text or "grass" in text or "meadow" in text:
        return "shrub/grassland"
    if "rock" in text or "snow" in text or "glacier" in text or "barren" in text:
        return "barren/rocky"
    return "unknown"


def _fire_context(lulc_class: str) -> str:
    return {
        "forest": "forest_fire",
        "agriculture": "agricultural_fire",
        "shrub/grassland": "forest_fire",
        "built-up": "possible_structure_or_roof_anomaly",
        "water": "water_false_positive",
        "barren/rocky": "unknown_thermal_anomaly",
    }.get(lulc_class, "unknown_thermal_anomaly")


def add_lulc_context(detections: pd.DataFrame, lulc_path: Path | None) -> pd.DataFrame:
    result = detections.copy()
    if result.empty:
        return result
    if lulc_path is None:
        result["lulc_source_class"] = "unknown"
        result["lulc_class"] = "unknown"
        result["fire_type"] = "unknown_thermal_anomaly"
        result["final_context_class"] = result["fire_type"]
        return result

    lulc = gpd.read_file(lulc_path)
    lulc_column = _detect_lulc_column(lulc)
    points = gpd.GeoDataFrame(
        result,
        geometry=[Point(row.longitude, row.latitude) for row in result.itertuples()],
        crs="EPSG:4326",
    ).to_crs(lulc.crs)
    joined = gpd.sjoin(
        points,
        lulc[[lulc_column, "geometry"]] if lulc_column else lulc[["geometry"]],
        how="left",
        predicate="within",
    ).drop(columns=["index_right"], errors="ignore")
    joined = joined.groupby(joined.index).first().reindex(result.index)

    if lulc_column:
        result["lulc_source_class"] = joined[lulc_column].fillna("unknown").astype(str).to_list()
        result["lulc_class"] = result["lulc_source_class"].map(_normalize_lulc)
    else:
        result["lulc_source_class"] = "unknown"
        result["lulc_class"] = "unknown"
    result["fire_type"] = result["lulc_class"].map(_fire_context)
    result["final_context_class"] = result["fire_type"]
    return result
