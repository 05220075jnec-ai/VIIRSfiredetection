"""Export MODIS hotspot detections using the shared project schema."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point


OUTPUT_COLUMNS = [
    "sensor",
    "satellite",
    "satellite_sources",
    "number_of_satellites_detected",
    "instrument",
    "granule_id",
    "acquisition_time",
    "first_detection_time",
    "last_detection_time",
    "acq_date",
    "acq_time",
    "latitude",
    "longitude",
    "day_night",
    "confidence",
    "final_confidence_score",
    "fire_mask_class",
    "fire_type",
    "final_context_class",
    "lulc_class",
    "lulc_source_class",
    "T4",
    "T11",
    "T12",
    "T4_minus_T11",
    "T4_source_band",
    "absolute_test_passed",
    "contextual_test_passed",
    "background_mean_T4",
    "background_mean_T11",
    "background_mean_delta",
    "background_MAD_T4",
    "background_MAD_delta",
    "background_window",
    "background_pixels",
    "adjacent_cloud_pixels",
    "adjacent_water_pixels",
    "glint_risk",
    "source_data",
    "source_geo",
    "cloud_mask_method",
    "algorithm_version",
]

SHAPEFILE_COLUMNS = {
    "sensor": "sensor",
    "satellite": "satellite",
    "instrument": "instrmnt",
    "granule_id": "granule_id",
    "acq_date": "acq_date",
    "acq_time": "acq_time",
    "latitude": "latitude",
    "longitude": "longitude",
    "day_night": "day_night",
    "confidence": "confidence",
    "fire_mask_class": "mask_class",
    "fire_type": "fire_type",
    "lulc_class": "lulc_class",
    "T4": "T4",
    "T11": "T11",
    "T12": "T12",
    "T4_minus_T11": "T4_T11",
    "T4_source_band": "T4_band",
    "absolute_test_passed": "abs_test",
    "contextual_test_passed": "ctx_test",
    "background_window": "bg_window",
    "background_pixels": "bg_pixels",
    "adjacent_cloud_pixels": "adj_cloud",
    "adjacent_water_pixels": "adj_water",
    "glint_risk": "glint_risk",
    "algorithm_version": "algorithm",
}


def _serializable(value):
    if pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def export_all(
    detections: pd.DataFrame,
    fire_mask: np.ndarray,
    out_dir: Path,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    mask_path = out_dir / "fire_mask.npy"
    csv_path = out_dir / "modis_hotspot.csv"
    geojson_path = out_dir / "modis_hotspot.geojson"
    shapefile_path = out_dir / "modis_hotspot.shp"

    np.save(mask_path, fire_mask)
    detections.reindex(columns=OUTPUT_COLUMNS).to_csv(csv_path, index=False)

    features = []
    for row in detections.to_dict(orient="records"):
        longitude = float(row["longitude"])
        latitude = float(row["latitude"])
        properties = {
            key: _serializable(value)
            for key, value in row.items()
            if key not in {"longitude", "latitude"}
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [longitude, latitude],
                },
                "properties": properties,
            }
        )

    geojson_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2),
        encoding="utf-8",
    )

    shapefile_data = detections.reindex(columns=SHAPEFILE_COLUMNS).rename(
        columns=SHAPEFILE_COLUMNS
    )
    geometry = [
        Point(row.longitude, row.latitude)
        for row in detections.itertuples()
    ]
    shapefile = gpd.GeoDataFrame(
        shapefile_data,
        geometry=geometry,
        crs="EPSG:4326",
    )
    shapefile.to_file(shapefile_path, driver="ESRI Shapefile", index=False)

    return {
        "fire_mask": mask_path,
        "csv": csv_path,
        "geojson": geojson_path,
        "shapefile": shapefile_path,
    }
