"""MODIS pixel-quality, water, and internal cloud masks."""

from __future__ import annotations

import numpy as np

from config import BHUTAN_BOUNDS, THRESHOLDS
from src.data_ingestion import ModisObservation


def daytime_mask(observation: ModisObservation) -> np.ndarray:
    return observation.solar_zenith < THRESHOLDS.day_solar_zenith_deg


def cloud_mask(observation: ModisObservation) -> np.ndarray:
    day = daytime_mask(observation)
    cold_cloud = observation.t11 < THRESHOLDS.cold_cloud_t11_k
    reflective_cloud = (
        day
        & ((observation.reflectance1 + observation.reflectance2) > THRESHOLDS.reflective_cloud_sum)
        & (observation.t11 < THRESHOLDS.reflective_cloud_t11_k)
    )
    return cold_cloud | reflective_cloud


def initialize_fire_mask(observation: ModisObservation) -> tuple[np.ndarray, np.ndarray]:
    fire_mask = np.zeros(observation.t4.shape, dtype=np.uint8)
    invalid = (
        ~np.isfinite(observation.t4)
        | ~np.isfinite(observation.t11)
        | ~np.isfinite(observation.latitude)
        | ~np.isfinite(observation.longitude)
        | ~np.isfinite(observation.solar_zenith)
    )
    clouds = cloud_mask(observation)
    water = ~observation.land_mask
    inside_bhutan_bbox = (
        (observation.longitude >= BHUTAN_BOUNDS["min_lon"])
        & (observation.longitude <= BHUTAN_BOUNDS["max_lon"])
        & (observation.latitude >= BHUTAN_BOUNDS["min_lat"])
        & (observation.latitude <= BHUTAN_BOUNDS["max_lat"])
    )
    valid_land = ~(invalid | clouds | water) & inside_bhutan_bbox

    fire_mask[water] = 1
    fire_mask[clouds] = 2
    fire_mask[valid_land] = 3
    return fire_mask, valid_land
