"""Building footprint checks for roof false-positive logic."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, box

from config import RISK
from src.geospatial_inputs import load_vector


def demo_building_footprints() -> gpd.GeoDataFrame:
    """Create small demo building polygons near settlement-like locations."""
    centers = [
        (89.64, 27.47),
        (89.90, 27.49),
        (90.08, 27.25),
        (91.42, 27.26),
        (91.55, 27.33),
    ]
    footprints = []
    for lon, lat in centers:
        footprints.append(box(lon - 0.002, lat - 0.002, lon + 0.002, lat + 0.002))
    return gpd.GeoDataFrame({"building_id": range(len(footprints))}, geometry=footprints, crs="EPSG:4326")


def _count_within(point_m, buildings_m: gpd.GeoDataFrame, radius_m: float) -> int:
    return int(buildings_m.distance(point_m).le(radius_m).sum())


def add_building_context(detections: pd.DataFrame, buildings: gpd.GeoDataFrame | str | Path | None = None) -> pd.DataFrame:
    """Attach building overlap, distance, density, and roof false-positive scores."""
    if detections.empty:
        return detections
    if buildings is None:
        buildings = demo_building_footprints()
    elif isinstance(buildings, (str, bytes, Path)):
        buildings = load_vector(buildings)

    result = detections.copy()
    buildings = buildings[buildings.geometry.notna()].copy()
    if buildings.empty:
        return add_building_context(detections, None)

    buildings_m = buildings.to_crs("EPSG:3857")

    rows = []
    for det in result.itertuples():
        point = gpd.GeoSeries([Point(det.longitude, det.latitude)], crs="EPSG:4326").to_crs("EPSG:3857").iloc[0]
        distances = buildings_m.distance(point)
        nearest = float(distances.min()) if len(distances) else float("inf")
        overlaps = bool(buildings_m.contains(point).any())
        overlap_area = 375.0 * 375.0 if overlaps else 0.0
        buildings_500 = _count_within(point, buildings_m, RISK.building_count_radii_m[0])
        buildings_1000 = _count_within(point, buildings_m, RISK.building_count_radii_m[1])
        buildings_2000 = _count_within(point, buildings_m, RISK.building_count_radii_m[2])

        weak_m13 = not bool(getattr(det, "m13_confirmed", False))
        weak_thermal = float(det.thermal_confidence) < 65.0
        roof_score = 0.0
        if overlaps:
            roof_score += 0.45
        if weak_m13:
            roof_score += 0.30
        if weak_thermal:
            roof_score += 0.25
        if buildings_500 > 8:
            roof_score += 0.10
        roof_score = min(1.0, roof_score)

        structure_probability = 0.0
        if overlaps and bool(getattr(det, "m13_confirmed", False)):
            structure_probability += 0.45
        if float(det.thermal_confidence) > 80.0:
            structure_probability += 0.30
        if nearest <= 100.0:
            structure_probability += 0.20
        structure_probability = min(1.0, structure_probability)

        rows.append(
            {
                "overlaps_building": overlaps,
                "building_overlap_area_m2": overlap_area,
                "distance_to_nearest_building_m": nearest,
                "buildings_within_500m": buildings_500,
                "buildings_within_1km": buildings_1000,
                "buildings_within_2km": buildings_2000,
                "roof_false_positive_score": roof_score,
                "structure_fire_probability": structure_probability,
            }
        )

    return pd.concat([result.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def refine_context_with_buildings(detections: pd.DataFrame) -> pd.DataFrame:
    """Update fire context using building and M13 evidence."""
    if detections.empty:
        return detections

    result = detections.copy()
    contexts = []
    for row in result.itertuples():
        context = row.fire_context
        if row.overlaps_building and row.roof_false_positive_score >= 0.75:
            context = "roof_false_positive"
        elif row.overlaps_building and not row.m13_confirmed:
            context = "possible_roof_false_positive"
        elif row.overlaps_building and (row.m13_confirmed or row.structure_fire_probability >= 0.55):
            context = "structure_fire_candidate"
        contexts.append(context)

    result["fire_context"] = contexts
    return result
