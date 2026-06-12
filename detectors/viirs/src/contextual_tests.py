"""Local contextual tests for VIIRS candidate fire pixels."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from config import THRESHOLDS


@dataclass
class ContextStats:
    """Background statistics around one candidate pixel."""

    mean_bt4: float
    mad_bt4: float
    mean_bt5: float
    mad_bt5: float
    mean_delta: float
    mad_delta: float
    mean_m13: float
    mad_m13: float
    background_pixels: int
    window_size: int


def mean_absolute_deviation(values: np.ndarray) -> float:
    """Compute mean absolute deviation while ignoring NaN values."""
    values = values[np.isfinite(values)]
    if values.size == 0:
        return float("nan")
    return float(np.mean(np.abs(values - np.mean(values))))


def _window_slice(index: int, radius: int, max_size: int) -> slice:
    return slice(max(0, index - radius), min(max_size, index + radius + 1))


def local_background_stats(
    row: int,
    col: int,
    bt4: np.ndarray,
    bt5: np.ndarray,
    m13: np.ndarray,
    background_mask: np.ndarray,
) -> ContextStats | None:
    """Find local background stats, expanding from 11x11 to 35x35 if needed."""
    for window in range(THRESHOLDS.contextual_start_window, THRESHOLDS.contextual_max_window + 1, 2):
        radius = window // 2
        rs = _window_slice(row, radius, bt4.shape[0])
        cs = _window_slice(col, radius, bt4.shape[1])
        local_mask = background_mask[rs, cs].copy()

        center_r = row - rs.start
        center_c = col - cs.start
        local_mask[center_r, center_c] = False

        if int(local_mask.sum()) < THRESHOLDS.contextual_min_background_pixels:
            continue

        local_bt4 = bt4[rs, cs][local_mask]
        local_bt5 = bt5[rs, cs][local_mask]
        local_m13 = m13[rs, cs][local_mask]
        local_delta = local_bt4 - local_bt5

        return ContextStats(
            mean_bt4=float(np.mean(local_bt4)),
            mad_bt4=mean_absolute_deviation(local_bt4),
            mean_bt5=float(np.mean(local_bt5)),
            mad_bt5=mean_absolute_deviation(local_bt5),
            mean_delta=float(np.mean(local_delta)),
            mad_delta=mean_absolute_deviation(local_delta),
            mean_m13=float(np.mean(local_m13)),
            mad_m13=mean_absolute_deviation(local_m13),
            background_pixels=int(local_mask.sum()),
            window_size=window,
        )

    return None


def contextual_fire_test(delta: float, stats: ContextStats, is_day: bool, seasonal_factor: float) -> bool:
    """Apply day/night contextual delta-temperature tests."""
    adaptive = stats.mean_delta + THRESHOLDS.contextual_mad_multiplier * stats.mad_delta * seasonal_factor
    if is_day:
        absolute = stats.mean_delta + THRESHOLDS.contextual_day_delta_floor_k * seasonal_factor
        return bool(delta > adaptive and delta > absolute)
    return bool(delta > adaptive)
