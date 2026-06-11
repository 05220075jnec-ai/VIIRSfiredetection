"""Land-cover context and false-positive filtering."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src.geospatial_inputs import load_vector


def classify_lulc(latitude: float, longitude: float) -> str:
    """Return a deterministic demo LULC class for a coordinate."""
    if latitude < 26.72:
        return "water"
    if longitude < 89.6:
        return "built-up"
    if longitude < 90.4:
        return "agriculture"
    if longitude < 91.4:
        return "forest"
    if latitude > 27.7:
        return "barren/rocky"
    return "shrub/grassland"


def fire_context_from_lulc(lulc_class: str) -> str:
    """Map LULC to a Bhutan-specific fire context class."""
    mapping = {
        "water": "water_false_positive",
        "agriculture": "agricultural_burning",
        "forest": "forest_fire",
        "built-up": "possible_roof_false_positive",
        "barren/rocky": "unknown_thermal_anomaly",
        "shrub/grassland": "vegetation_fire",
    }
    return mapping.get(lulc_class, "unknown_thermal_anomaly")


def normalize_lulc_class(value: object) -> str:
    """Map real Bhutan LULC labels into detector categories."""
    text = str(value or "").strip().casefold()
    if "water" in text:
        return "water"
    if "agriculture" in text or "crop" in text or "paddy" in text:
        return "agriculture"
    if "forest" in text:
        return "forest"
    if "built" in text and "non" not in text:
        return "built-up"
    if "shrub" in text or "meadow" in text or "grass" in text or "alpine" in text:
        return "shrub/grassland"
    if "rock" in text or "moraine" in text or "landslide" in text or "sandy" in text or "snow" in text or "glacier" in text:
        return "barren/rocky"
    return "unknown"


def _detect_lulc_column(lulc: gpd.GeoDataFrame) -> str | None:
    preferred = ["class_name", "Class_Name", "CLASS_NAME", "lulc_class", "LULC", "class", "Name", "name"]
    for column in preferred:
        if column in lulc.columns:
            return column
    candidates = [column for column in lulc.columns if column != "geometry" and lulc[column].dtype == object]
    return candidates[0] if candidates else None


def add_lulc_context(detections: pd.DataFrame, lulc_path=None) -> pd.DataFrame:
    """Attach LULC class and first-pass fire context to detections.

    If a LULC path is supplied, this uses a real spatial join. Otherwise it
    falls back to the deterministic demo classifier.
    """
    if detections.empty:
        return detections
    result = detections.copy()

    if lulc_path:
        lulc = load_vector(lulc_path)
        lulc_column = _detect_lulc_column(lulc)
        points = gpd.GeoDataFrame(
            result,
            geometry=[Point(row.longitude, row.latitude) for row in result.itertuples()],
            crs="EPSG:4326",
        )
        points_projected = points.to_crs(lulc.crs)
        joined = gpd.sjoin(
            points_projected,
            lulc[[lulc_column, "geometry"]] if lulc_column else lulc[["geometry"]],
            how="left",
            predicate="within",
        ).drop(columns=["index_right"], errors="ignore")
        joined = joined.groupby(joined.index).first().reindex(result.index)

        if lulc_column:
            result["lulc_source_class"] = joined[lulc_column].fillna("unknown").astype(str).to_list()
            result["lulc_class"] = [normalize_lulc_class(value) for value in result["lulc_source_class"]]
        else:
            result["lulc_source_class"] = "unknown"
            result["lulc_class"] = "unknown"
    else:
        result["lulc_source_class"] = ""
        result["lulc_class"] = [classify_lulc(row.latitude, row.longitude) for row in result.itertuples()]

    result["fire_context"] = result["lulc_class"].map(fire_context_from_lulc)
    return result
