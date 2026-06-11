from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from config import Config
from src.utils import BHUTAN_METRIC_CRS, safe_read_vector, to_geodataframe


VECTOR_LAYERS = {
    "urban": "urban_areas.geojson",
    "roads": "roads.geojson",
    "dzongs": "dzongs.geojson",
    "schools": "schools.geojson",
    "hospitals": "hospitals.geojson",
    "forest_reserves": "forest_reserves.geojson",
    "national_parks": "national_parks.geojson",
}


def load_infrastructure_layers(vector_dir: Path) -> list[tuple[str, gpd.GeoDataFrame]]:
    layers = []
    for label, filename in VECTOR_LAYERS.items():
        layer = safe_read_vector(vector_dir / filename)
        if layer is not None and not layer.empty:
            layers.append((label, layer.to_crs(BHUTAN_METRIC_CRS)))
    return layers


def apply_proximity_risk(detections: pd.DataFrame, config: Config) -> pd.DataFrame:
    if detections.empty:
        return detections

    gdf = to_geodataframe(detections).to_crs(BHUTAN_METRIC_CRS)
    layers = load_infrastructure_layers(config.paths.vectors)
    nearest_names: list[str] = []
    nearest_distances: list[float] = []

    for geom in gdf.geometry:
        best_name = "none"
        best_distance = float("inf")
        for label, layer in layers:
            distances = layer.geometry.distance(geom)
            if not distances.empty and distances.min() < best_distance:
                best_distance = float(distances.min())
                best_name = label
        nearest_names.append(best_name)
        nearest_distances.append(best_distance if best_distance != float("inf") else -1)

    output = detections.copy()
    output["nearest_infrastructure"] = nearest_names
    output["distance_to_infrastructure_m"] = nearest_distances
    output["threat_level"] = output.apply(classify_threat, axis=1)
    return output


def classify_threat(row) -> str:
    distance = row["distance_to_infrastructure_m"]
    confidence = row["confidence_score"]
    fire_class = row["fire_class"]

    if distance >= 0 and distance <= 500 and fire_class == "Confirmed Fire":
        return "Instant Alert"
    if distance >= 0 and distance <= 1000 and confidence >= 0.75:
        return "High Risk"
    if fire_class in {"Confirmed Fire", "Probable Fire"}:
        return "Warning"
    return "Monitor"
