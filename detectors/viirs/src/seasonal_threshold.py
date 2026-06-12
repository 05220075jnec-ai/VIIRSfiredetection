"""Bhutan-specific seasonal sensitivity adjustments."""

from __future__ import annotations


def get_seasonal_adjustment(month: int) -> float:
    """Return a multiplier for contextual thresholds by Bhutan fire season.

    Values below 1.0 increase sensitivity; values above 1.0 lower sensitivity.
    """
    if month in (12, 1, 2):
        return 0.90  # winter and dry season
    if month in (3, 4, 5):
        return 0.85  # spring forest-fire season
    if month in (6, 7, 8, 9):
        return 1.15  # monsoon, more cloud/wet-surface false positives
    return 1.00  # post-monsoon
