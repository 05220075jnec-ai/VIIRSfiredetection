from __future__ import annotations

from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd

from src.utils import to_geodataframe


DISPLAY_COLUMNS = [
    "latitude",
    "longitude",
    "satellite",
    "detection_time",
    "I4_BT",
    "M13_BT",
    "background_I4",
    "background_M13",
    "terrain_correction_score",
    "confidence_score",
    "fire_class",
    "nearest_infrastructure",
    "distance_to_infrastructure_m",
    "threat_level",
]


def write_outputs(detections: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    output = detections.copy()
    if output.empty:
        output = pd.DataFrame(columns=DISPLAY_COLUMNS)

    output.to_csv(output_dir / "hotspots_summary.csv", index=False)

    if not output.empty:
        gdf = to_geodataframe(output)
    else:
        gdf = gpd.GeoDataFrame(output, geometry=[], crs="EPSG:4326")

    gdf.to_file(output_dir / "hotspots.geojson", driver="GeoJSON")
    write_dashboard_json(output, output_dir / "dashboard_ready.json")
    write_folium_map(output, output_dir / "hotspots_map.html")


def write_dashboard_json(detections: pd.DataFrame, path: Path) -> None:
    dashboard = detections.copy()
    if "detection_time" in dashboard:
        dashboard["detection_time"] = dashboard["detection_time"].astype(str)
    dashboard.to_json(path, orient="records", indent=2)


def write_folium_map(detections: pd.DataFrame, path: Path) -> None:
    fmap = folium.Map(location=[27.45, 90.45], zoom_start=8, tiles="CartoDB positron")
    colors = {
        "Anomaly": "orange",
        "Probable Fire": "red",
        "Confirmed Fire": "darkred",
    }

    for row in detections.itertuples():
        popup = (
            f"<b>{row.fire_class}</b><br>"
            f"Satellite: {row.satellite}<br>"
            f"Time: {row.detection_time}<br>"
            f"I4 BT: {row.I4_BT:.2f} K<br>"
            f"M13 BT: {row.M13_BT:.2f} K<br>"
            f"Confidence: {row.confidence_score:.2f}<br>"
            f"Threat: {row.threat_level}"
        )
        folium.CircleMarker(
            location=[row.latitude, row.longitude],
            radius=6,
            color=colors.get(row.fire_class, "blue"),
            fill=True,
            fill_opacity=0.8,
            popup=popup,
        ).add_to(fmap)

    fmap.save(path)
