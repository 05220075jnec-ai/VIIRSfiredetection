"""M13 energy validation for VIIRS I4 thermal candidates."""

from __future__ import annotations

from config import THRESHOLDS
from src.contextual_tests import ContextStats


def m13_anomaly(pixel_m13: float, stats: ContextStats | None) -> tuple[float, bool]:
    """Return M13 anomaly and whether it confirms the candidate."""
    if stats is None or stats.mad_m13 <= 0:
        return 0.0, False

    anomaly = float(pixel_m13 - stats.mean_m13)
    return anomaly, bool(anomaly > THRESHOLDS.k_m13 * stats.mad_m13)
