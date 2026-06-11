"""Output writers for fire mask arrays, CSV, GeoJSON, and Folium maps."""

from __future__ import annotations

from pathlib import Path

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from src.utils import ensure_directory


OUTPUT_COLUMNS = [
    "latitude",
    "longitude",
    "satellite_sources",
    "number_of_satellites_detected",
    "first_detection_time",
    "last_detection_time",
    "persistence_minutes",
    "BT4",
    "BT5",
    "BT4_minus_BT5",
    "M13",
    "M13_anomaly",
    "I4_saturated",
    "contextual_test_passed",
    "terrain_correction_factor",
    "terrain_false_positive_risk",
    "elevation_m",
    "slope_deg",
    "aspect_deg",
    "lulc_source_class",
    "lulc_class",
    "fire_context",
    "overlaps_building",
    "distance_to_nearest_building_m",
    "buildings_within_500m",
    "buildings_within_1km",
    "buildings_within_2km",
    "roof_false_positive_score",
    "structure_fire_probability",
    "thermal_confidence",
    "temporal_confidence",
    "final_confidence_score",
    "fire_mask_class",
    "final_context_class",
    "final_threat_level",
]


def export_fire_mask(mask: np.ndarray, out_dir: Path) -> Path:
    """Save fire mask as a NumPy array."""
    ensure_directory(out_dir)
    out_path = out_dir / "fire_mask.npy"
    np.save(out_path, mask)
    return out_path


def export_csv(detections: pd.DataFrame, out_dir: Path) -> Path:
    """Save detection summary CSV."""
    ensure_directory(out_dir)
    out_path = out_dir / "fire_detections.csv"
    columns = [col for col in OUTPUT_COLUMNS if col in detections.columns]
    detections[columns].to_csv(out_path, index=False)
    return out_path


def export_geojson(detections: pd.DataFrame, out_dir: Path) -> Path:
    """Save detection points as GeoJSON."""
    ensure_directory(out_dir)
    out_path = out_dir / "fire_detections.geojson"
    if detections.empty:
        gdf = gpd.GeoDataFrame(columns=OUTPUT_COLUMNS, geometry=[], crs="EPSG:4326")
    else:
        geometry = [Point(row.longitude, row.latitude) for row in detections.itertuples()]
        gdf = gpd.GeoDataFrame(detections.copy(), geometry=geometry, crs="EPSG:4326")
    gdf.to_file(out_path, driver="GeoJSON")
    return out_path


def export_map(detections: pd.DataFrame, out_dir: Path) -> Path:
    """Save a Folium interactive map."""
    ensure_directory(out_dir)
    out_path = out_dir / "fire_map.html"
    fmap = folium.Map(location=[27.45, 90.45], zoom_start=8, tiles="OpenStreetMap")

    color_by_threat = {
        "No Alert": "gray",
        "Monitor": "green",
        "Warning": "orange",
        "High Risk": "red",
        "Instant Alert": "darkred",
    }

    for row in detections.itertuples():
        popup = (
            f"<b>{row.final_context_class}</b><br>"
            f"Threat: {row.final_threat_level}<br>"
            f"Confidence: {row.final_confidence_score:.1f}<br>"
            f"Satellites: {row.satellite_sources}<br>"
            f"BT4: {row.BT4:.1f} K<br>"
            f"M13 anomaly: {row.M13_anomaly:.1f}"
        )
        folium.CircleMarker(
            location=[row.latitude, row.longitude],
            radius=6,
            color=color_by_threat.get(row.final_threat_level, "blue"),
            fill=True,
            fill_opacity=0.8,
            popup=popup,
        ).add_to(fmap)

    fmap.save(out_path)
    return out_path


def export_all(detections: pd.DataFrame, fire_mask: np.ndarray, out_dir: Path) -> dict[str, Path]:
    """Write all supported outputs."""
    return {
        "fire_mask": export_fire_mask(fire_mask, out_dir),
        "csv": export_csv(detections, out_dir),
        "geojson": export_geojson(detections, out_dir),
        "map": export_map(detections, out_dir),
    }
