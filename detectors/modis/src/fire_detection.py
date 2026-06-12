"""MODIS-specific absolute and contextual active-fire detection."""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import THRESHOLDS
from src.contextual_tests import BackgroundStats, contextual_fire_test, local_background_stats
from src.data_ingestion import ModisObservation
from src.preprocessing import daytime_mask, initialize_fire_mask


def confidence_to_mask_class(score: float) -> int:
    if score >= 85.0:
        return 9
    if score >= 65.0:
        return 8
    return 7


def _normalize(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return float(np.clip((value - low) / (high - low), 0.0, 1.0))


def glint_risk(observation: ModisObservation, row: int, col: int) -> float:
    relative_azimuth = abs(
        float(observation.solar_azimuth[row, col])
        - float(observation.sensor_azimuth[row, col])
    )
    relative_azimuth = min(relative_azimuth, 360.0 - relative_azimuth)
    zenith_difference = abs(
        float(observation.solar_zenith[row, col])
        - float(observation.sensor_zenith[row, col])
    )
    azimuth_score = max(0.0, 1.0 - relative_azimuth / 60.0)
    zenith_score = max(0.0, 1.0 - zenith_difference / 35.0)
    return float(np.clip(azimuth_score * zenith_score, 0.0, 1.0))


def bright_surface_rejected(
    observation: ModisObservation,
    row: int,
    col: int,
    is_day: bool,
    absolute_fire: bool,
) -> bool:
    return bool(
        is_day
        and not absolute_fire
        and observation.reflectance2[row, col] > THRESHOLDS.bright_surface_band2
        and observation.t4[row, col] < 335.0
    )


def _adjacent_count(mask: np.ndarray, row: int, col: int) -> int:
    row_slice = slice(max(0, row - 1), min(mask.shape[0], row + 2))
    col_slice = slice(max(0, col - 1), min(mask.shape[1], col + 2))
    return int(mask[row_slice, col_slice].sum() - int(mask[row, col]))


def _confidence(
    t4: float,
    delta: float,
    is_day: bool,
    absolute_fire: bool,
    contextual_passed: bool,
    stats: BackgroundStats | None,
    glint: float,
    bright_rejected: bool,
    adjacent_clouds: int,
    adjacent_water: int,
) -> float:
    candidate_t4 = THRESHOLDS.day_candidate_t4_k if is_day else THRESHOLDS.night_candidate_t4_k
    absolute_t4 = THRESHOLDS.day_absolute_t4_k if is_day else THRESHOLDS.night_absolute_t4_k
    score = 25.0
    score += 28.0 * _normalize(t4, candidate_t4, absolute_t4)
    score += 22.0 * _normalize(delta, THRESHOLDS.candidate_delta_k, 35.0)
    score += 18.0 if contextual_passed else 0.0
    score += 20.0 if absolute_fire else 0.0
    if stats is not None:
        score += 7.0 * _normalize(stats.valid_pixels, 8.0, 60.0)
    score -= 15.0 if bright_rejected else 0.0
    score -= 10.0 * glint
    score -= min(8.0, adjacent_clouds * 1.5)
    score -= min(5.0, adjacent_water)
    return float(np.clip(score, 1.0, 99.0))


def detect_fires(observation: ModisObservation) -> tuple[np.ndarray, pd.DataFrame]:
    fire_mask, valid_land = initialize_fire_mask(observation)
    day = daytime_mask(observation)
    delta = observation.t4 - observation.t11

    candidate = valid_land & (delta > THRESHOLDS.candidate_delta_k)
    candidate &= np.where(
        day,
        observation.t4 > THRESHOLDS.day_candidate_t4_k,
        observation.t4 > THRESHOLDS.night_candidate_t4_k,
    )
    background_mask = valid_land & ~candidate
    cloud_pixels = fire_mask == 2
    water_pixels = fire_mask == 1

    rows = []
    for row, col in np.argwhere(candidate):
        is_day = bool(day[row, col])
        t4 = float(observation.t4[row, col])
        t11 = float(observation.t11[row, col])
        pixel_delta = float(delta[row, col])
        absolute_threshold = (
            THRESHOLDS.day_absolute_t4_k
            if is_day
            else THRESHOLDS.night_absolute_t4_k
        )
        absolute_fire = t4 > absolute_threshold
        stats = local_background_stats(
            row,
            col,
            observation.t4,
            observation.t11,
            background_mask,
        )
        contextual_passed = stats is not None and contextual_fire_test(t4, t11, stats)
        if not absolute_fire and not contextual_passed:
            continue

        glint = glint_risk(observation, row, col) if is_day else 0.0
        bright_rejected = bright_surface_rejected(
            observation,
            row,
            col,
            is_day,
            absolute_fire,
        )
        if bright_rejected or (glint >= 0.85 and not absolute_fire):
            continue

        adjacent_clouds = _adjacent_count(cloud_pixels, row, col)
        adjacent_water = _adjacent_count(water_pixels, row, col)
        confidence = _confidence(
            t4,
            pixel_delta,
            is_day,
            absolute_fire,
            contextual_passed,
            stats,
            glint,
            bright_rejected,
            adjacent_clouds,
            adjacent_water,
        )
        mask_class = confidence_to_mask_class(confidence)
        fire_mask[row, col] = mask_class

        rows.append(
            {
                "sensor": "MODIS",
                "satellite": observation.satellite,
                "satellite_sources": observation.satellite,
                "number_of_satellites_detected": 1,
                "instrument": "MODIS_1KM",
                "granule_id": f"{observation.satellite}:{observation.granule_key}",
                "acquisition_time": observation.acquisition_time.isoformat(),
                "first_detection_time": observation.acquisition_time.isoformat(),
                "last_detection_time": observation.acquisition_time.isoformat(),
                "acq_date": observation.acquisition_time.date().isoformat(),
                "acq_time": int(observation.acquisition_time.strftime("%H%M")),
                "latitude": float(observation.latitude[row, col]),
                "longitude": float(observation.longitude[row, col]),
                "day_night": "day" if is_day else "night",
                "T4": t4,
                "T11": t11,
                "T12": float(observation.t12[row, col]),
                "T4_minus_T11": pixel_delta,
                "T4_source_band": int(observation.t4_source_band[row, col]),
                "reflectance_band1": float(observation.reflectance1[row, col]),
                "reflectance_band2": float(observation.reflectance2[row, col]),
                "absolute_test_passed": absolute_fire,
                "contextual_test_passed": bool(contextual_passed),
                "background_mean_T4": stats.mean_t4 if stats else np.nan,
                "background_mean_T11": stats.mean_t11 if stats else np.nan,
                "background_mean_delta": stats.mean_delta if stats else np.nan,
                "background_MAD_T4": stats.mad_t4 if stats else np.nan,
                "background_MAD_delta": stats.mad_delta if stats else np.nan,
                "background_window": stats.window_size if stats else 0,
                "background_pixels": stats.valid_pixels if stats else 0,
                "adjacent_cloud_pixels": adjacent_clouds,
                "adjacent_water_pixels": adjacent_water,
                "glint_risk": glint,
                "confidence": confidence,
                "final_confidence_score": confidence,
                "fire_mask_class": mask_class,
                "source_data": observation.source_data,
                "source_geo": observation.source_geo,
                "cloud_mask_method": "MODIS_INTERNAL_APPROXIMATION_V1",
                "algorithm_version": "BHUTAN_MODIS_CONTEXTUAL_V1",
            }
        )

    return fire_mask, pd.DataFrame(rows)
