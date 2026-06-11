"""Preprocessing masks for VIIRS fire detection."""

from __future__ import annotations

import numpy as np

from config import FIRE_MASK_CLASSES
from src.data_ingestion import VIIRSObservation


def initialize_fire_mask(obs: VIIRSObservation) -> np.ndarray:
    """Initialize VIIRS-style fire mask classes before thermal testing."""
    mask = np.zeros(obs.bt4.shape, dtype=np.uint8)
    invalid = ~np.isfinite(obs.bt4) | ~np.isfinite(obs.bt5) | ~np.isfinite(obs.m13)

    mask[obs.bowtie_mask] = 1
    mask[~obs.land_water_mask] = 3
    mask[obs.cloud_mask] = 4

    valid_land = ~(invalid | obs.bowtie_mask | ~obs.land_water_mask | obs.cloud_mask)
    mask[valid_land] = 5
    return mask


def valid_land_mask(fire_mask: np.ndarray) -> np.ndarray:
    """Return pixels available for fire testing."""
    return fire_mask == 5


def mask_name(mask_value: int) -> str:
    """Human-readable fire mask name."""
    return FIRE_MASK_CLASSES.get(int(mask_value), "unknown")
