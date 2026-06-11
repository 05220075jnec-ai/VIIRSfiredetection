"""Core VIIRS active fire detection logic."""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import THRESHOLDS
from src.contextual_tests import contextual_fire_test, local_background_stats
from src.data_ingestion import VIIRSObservation
from src.m13_validation import m13_anomaly
from src.preprocessing import initialize_fire_mask, valid_land_mask
from src.seasonal_threshold import get_seasonal_adjustment
from src.utils import confidence_to_mask_class, normalize_score


def is_daytime(obs: VIIRSObservation) -> bool:
    """Use solar zenith to decide whether daytime thresholds apply."""
    return bool(np.nanmedian(obs.solar_zenith) < 85.0)


def glint_risk(solar_zenith: float, view_zenith: float, relative_azimuth: float) -> float:
    """Estimate sun-glint risk from solar/view geometry.

    This is a compact approximation. Risk is highest when view and solar angles
    are similar and relative azimuth is small.
    """
    angle_difference = abs(solar_zenith - view_zenith)
    azimuth_term = max(0.0, 1.0 - abs(relative_azimuth) / 60.0)
    zenith_term = max(0.0, 1.0 - angle_difference / 35.0)
    return float(np.clip(azimuth_term * zenith_term, 0.0, 1.0))


def bright_surface_rejection(obs: VIIRSObservation, row: int, col: int, is_day: bool) -> bool:
    """Reject daytime bright surfaces unless thermal evidence is strong."""
    if not is_day:
        return False
    return bool(
        obs.i3[row, col] > THRESHOLDS.bright_surface_i3
        and obs.i3[row, col] > obs.i2[row, col]
        and obs.i2[row, col] > THRESHOLDS.bright_surface_i2
        and obs.bt4[row, col] <= THRESHOLDS.day_high_bt4_k
    )


def absolute_fire_class(obs: VIIRSObservation, row: int, col: int, is_day: bool, m13_confirmed: bool) -> str | None:
    """Apply absolute VIIRS I4/I5 fire thresholds."""
    bt4 = float(obs.bt4[row, col])
    delta = float(obs.bt4[row, col] - obs.bt5[row, col])
    saturated = bt4 >= THRESHOLDS.i4_saturation_k - THRESHOLDS.i4_saturation_margin_k

    if saturated and m13_confirmed:
        return "high"

    if is_day:
        if bt4 > THRESHOLDS.day_high_bt4_k and delta > THRESHOLDS.day_high_delta_k:
            return "high"
        if bt4 > THRESHOLDS.day_candidate_bt4_k and delta > THRESHOLDS.day_candidate_delta_k:
            return "candidate"
    else:
        if bt4 > THRESHOLDS.night_high_bt4_k and delta > THRESHOLDS.night_high_delta_k:
            return "high"
        if bt4 > THRESHOLDS.night_candidate_bt4_k and delta > THRESHOLDS.night_candidate_delta_k:
            return "candidate"

    return None


def _confidence_score(
    bt4: float,
    delta: float,
    m13_confirmed: bool,
    contextual_passed: bool,
    saturated: bool,
    bright_rejected: bool,
    glint: float,
) -> float:
    score = 35.0
    score += 25.0 * normalize_score(bt4, 295.0, 367.0)
    score += 20.0 * normalize_score(delta, 8.0, 35.0)
    score += 15.0 if m13_confirmed else -8.0
    score += 12.0 if contextual_passed else -5.0
    score += 8.0 if saturated else 0.0
    score -= 18.0 if bright_rejected else 0.0
    score -= 8.0 * glint
    return float(np.clip(score, 1.0, 99.0))


def detect_fires(obs: VIIRSObservation) -> tuple[np.ndarray, pd.DataFrame]:
    """Detect active fire candidates for one VIIRS observation."""
    fire_mask = initialize_fire_mask(obs)
    land = valid_land_mask(fire_mask)
    background_mask = land.copy()
    is_day = is_daytime(obs)
    seasonal_factor = get_seasonal_adjustment(obs.acquisition_time.month)

    # Broad candidate screen. Contextual and M13 tests are applied afterwards.
    delta = obs.bt4 - obs.bt5
    if is_day:
        candidate_mask = land & (obs.bt4 > THRESHOLDS.day_candidate_bt4_k) & (delta > THRESHOLDS.day_candidate_delta_k)
    else:
        candidate_mask = land & (obs.bt4 > THRESHOLDS.night_candidate_bt4_k) & (delta > THRESHOLDS.night_candidate_delta_k)

    rows = []
    for row, col in np.argwhere(candidate_mask):
        stats = local_background_stats(row, col, obs.bt4, obs.bt5, obs.m13, background_mask)
        if stats is None:
            continue

        pixel_delta = float(delta[row, col])
        m13_delta, m13_confirmed = m13_anomaly(float(obs.m13[row, col]), stats)
        contextual_passed = contextual_fire_test(pixel_delta, stats, is_day, seasonal_factor)
        absolute_class = absolute_fire_class(obs, row, col, is_day, m13_confirmed)
        saturated = bool(obs.bt4[row, col] >= THRESHOLDS.i4_saturation_k - THRESHOLDS.i4_saturation_margin_k)
        bright_rejected = bright_surface_rejection(obs, row, col, is_day)
        glint = glint_risk(float(obs.solar_zenith[row, col]), float(obs.view_zenith[row, col]), float(obs.relative_azimuth[row, col]))

        if absolute_class is None and not contextual_passed:
            continue

        confidence = _confidence_score(
            float(obs.bt4[row, col]),
            pixel_delta,
            m13_confirmed,
            contextual_passed,
            saturated,
            bright_rejected,
            glint,
        )
        if absolute_class == "high":
            confidence = max(confidence, 85.0)
        elif absolute_class == "candidate":
            confidence = max(confidence, 55.0)

        fire_class = confidence_to_mask_class(confidence)
        fire_mask[row, col] = fire_class
        background_mask[row, col] = False

        rows.append(
            {
                "latitude": float(obs.latitude[row, col]),
                "longitude": float(obs.longitude[row, col]),
                "satellite": obs.satellite,
                "acquisition_time": obs.acquisition_time.isoformat(),
                "BT4": float(obs.bt4[row, col]),
                "BT5": float(obs.bt5[row, col]),
                "BT4_minus_BT5": pixel_delta,
                "M13": float(obs.m13[row, col]),
                "M13_anomaly": m13_delta,
                "I1": float(obs.i1[row, col]),
                "I2": float(obs.i2[row, col]),
                "I3": float(obs.i3[row, col]),
                "I4_saturated": saturated,
                "contextual_test_passed": bool(contextual_passed),
                "m13_confirmed": bool(m13_confirmed),
                "bright_surface_rejected": bool(bright_rejected),
                "glint_risk": glint,
                "thermal_confidence": confidence,
                "contextual_confidence": 90.0 if contextual_passed else 40.0,
                "fire_mask_class": int(fire_class),
            }
        )

    return fire_mask, pd.DataFrame(rows)
