"""Contextual background characterization for MODIS potential fire pixels."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from config import THRESHOLDS


@dataclass(frozen=True)
class BackgroundStats:
    mean_t4: float
    mad_t4: float
    mean_t11: float
    mad_t11: float
    mean_delta: float
    mad_delta: float
    valid_pixels: int
    window_size: int


def mean_absolute_deviation(values: np.ndarray) -> float:
    values = values[np.isfinite(values)]
    if values.size == 0:
        return float("nan")
    return float(np.mean(np.abs(values - np.mean(values))))


def _window_slice(index: int, radius: int, size: int) -> slice:
    return slice(max(0, index - radius), min(size, index + radius + 1))


def local_background_stats(
    row: int,
    col: int,
    t4: np.ndarray,
    t11: np.ndarray,
    background_mask: np.ndarray,
) -> BackgroundStats | None:
    for window in range(
        THRESHOLDS.background_start_window,
        THRESHOLDS.background_max_window + 1,
        2,
    ):
        radius = window // 2
        row_slice = _window_slice(row, radius, t4.shape[0])
        col_slice = _window_slice(col, radius, t4.shape[1])
        local_mask = background_mask[row_slice, col_slice].copy()

        center_row = row - row_slice.start
        center_col = col - col_slice.start
        local_mask[center_row, center_col] = False
        if center_col > 0:
            local_mask[center_row, center_col - 1] = False
        if center_col + 1 < local_mask.shape[1]:
            local_mask[center_row, center_col + 1] = False

        valid_pixels = int(local_mask.sum())
        available_pixels = max(1, local_mask.size - 3)
        if valid_pixels < THRESHOLDS.background_min_pixels:
            continue
        if valid_pixels / available_pixels < THRESHOLDS.background_min_fraction:
            continue

        local_t4 = t4[row_slice, col_slice][local_mask]
        local_t11 = t11[row_slice, col_slice][local_mask]
        local_delta = local_t4 - local_t11
        return BackgroundStats(
            mean_t4=float(np.mean(local_t4)),
            mad_t4=mean_absolute_deviation(local_t4),
            mean_t11=float(np.mean(local_t11)),
            mad_t11=mean_absolute_deviation(local_t11),
            mean_delta=float(np.mean(local_delta)),
            mad_delta=mean_absolute_deviation(local_delta),
            valid_pixels=valid_pixels,
            window_size=window,
        )

    return None


def contextual_fire_test(t4: float, t11: float, stats: BackgroundStats) -> bool:
    delta = t4 - t11
    delta_test = delta > (
        stats.mean_delta
        + THRESHOLDS.contextual_delta_mad_multiplier * max(stats.mad_delta, 0.5)
    )
    delta_floor = delta > stats.mean_delta + THRESHOLDS.contextual_delta_floor_k
    t4_test = t4 > (
        stats.mean_t4
        + THRESHOLDS.contextual_t4_mad_multiplier * max(stats.mad_t4, 0.5)
    )
    t11_test = t11 > (
        stats.mean_t11
        + THRESHOLDS.contextual_t11_mad_multiplier * max(stats.mad_t11, 0.5)
        - THRESHOLDS.contextual_t11_offset_k
    )
    return bool(delta_test and delta_floor and t4_test and t11_test)
