"""Read and calibrate MODIS Terra/Aqua Level-1B HDF4 observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

import numpy as np
from pyhdf.SD import SD, SDC

from config import MODIS_WAVELENGTHS_UM, THRESHOLDS


GRANULE_TOKEN = re.compile(r"\.A(\d{7})\.(\d{4})\.")


@dataclass(frozen=True)
class ModisPair:
    satellite: str
    granule_key: str
    data_path: Path
    geo_path: Path


@dataclass
class ModisObservation:
    latitude: np.ndarray
    longitude: np.ndarray
    t4: np.ndarray
    t11: np.ndarray
    t12: np.ndarray
    reflectance1: np.ndarray
    reflectance2: np.ndarray
    solar_zenith: np.ndarray
    sensor_zenith: np.ndarray
    solar_azimuth: np.ndarray
    sensor_azimuth: np.ndarray
    land_mask: np.ndarray
    satellite: str
    acquisition_time: datetime
    granule_key: str
    source_data: str
    source_geo: str
    t4_source_band: np.ndarray


def granule_key(path: Path) -> str:
    match = GRANULE_TOKEN.search(path.name)
    if not match:
        raise ValueError(f"Could not extract MODIS granule key from {path.name}")
    return ".".join(match.groups())


def acquisition_time_from_key(key: str) -> datetime:
    year_day, hhmm = key.split(".")
    year = int(year_day[:4])
    day_of_year = int(year_day[4:])
    hour = int(hhmm[:2])
    minute = int(hhmm[2:])
    return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(
        days=day_of_year - 1,
        hours=hour,
        minutes=minute,
    )


def discover_hdf_pairs(data_dir: Path) -> list[ModisPair]:
    pairs = []
    product_sets = (
        ("Terra", "MOD021KM", "MOD03"),
        ("Aqua", "MYD021KM", "MYD03"),
    )

    for satellite, data_prefix, geo_prefix in product_sets:
        data_files = {}
        geo_files = {}
        for path in data_dir.rglob("*.hdf"):
            if path.name.startswith(data_prefix):
                data_files[granule_key(path)] = path
            elif path.name.startswith(geo_prefix):
                geo_files[granule_key(path)] = path

        for key in sorted(set(data_files) & set(geo_files)):
            pairs.append(ModisPair(satellite, key, data_files[key], geo_files[key]))

    return sorted(pairs, key=lambda pair: (pair.granule_key, pair.satellite))


def _scaled_array(dataset, scale_name: str, offset_name: str) -> tuple[np.ndarray, dict]:
    raw = dataset[:].astype("float64")
    attrs = dataset.attributes()
    fill_value = attrs.get("_FillValue")
    valid_range = attrs.get("valid_range")

    if fill_value is not None:
        raw[raw == fill_value] = np.nan
    if valid_range is not None:
        low, high = valid_range
        raw[(raw < low) | (raw > high)] = np.nan

    scales = np.asarray(attrs[scale_name], dtype="float64")
    offsets = np.asarray(attrs[offset_name], dtype="float64")
    reshape = (len(scales),) + (1,) * (raw.ndim - 1)
    values = (raw - offsets.reshape(reshape)) * scales.reshape(reshape)
    return values, attrs


def _select_band(values: np.ndarray, attrs: dict, band_name: str) -> np.ndarray:
    band_names = [name.strip() for name in attrs["band_names"].split(",")]
    return values[band_names.index(band_name)]


def brightness_temperature(radiance: np.ndarray, wavelength_um: float) -> np.ndarray:
    c1 = 1.191042e8
    c2 = 1.4387752e4
    output = np.full(radiance.shape, np.nan, dtype="float64")
    valid = np.isfinite(radiance) & (radiance > 0)
    output[valid] = c2 / (
        wavelength_um
        * np.log((c1 / (radiance[valid] * wavelength_um**5)) + 1.0)
    )
    return output


def _scaled_geo(geo_hdf, name: str) -> np.ndarray:
    dataset = geo_hdf.select(name)
    values = dataset[:].astype("float64")
    attrs = dataset.attributes()
    fill_value = attrs.get("_FillValue")
    valid_range = attrs.get("valid_range")
    if fill_value is not None:
        values[values == fill_value] = np.nan
    if valid_range is not None:
        low, high = valid_range
        values[(values < low) | (values > high)] = np.nan
    return values * float(attrs.get("scale_factor", 1.0))


def load_hdf_observation(pair: ModisPair) -> ModisObservation:
    data_hdf = SD(str(pair.data_path), SDC.READ)
    geo_hdf = SD(str(pair.geo_path), SDC.READ)
    try:
        emissive, emissive_attrs = _scaled_array(
            data_hdf.select("EV_1KM_Emissive"),
            "radiance_scales",
            "radiance_offsets",
        )
        reflectance, reflectance_attrs = _scaled_array(
            data_hdf.select("EV_250_Aggr1km_RefSB"),
            "reflectance_scales",
            "reflectance_offsets",
        )

        radiance21 = _select_band(emissive, emissive_attrs, "21")
        radiance22 = _select_band(emissive, emissive_attrs, "22")
        radiance31 = _select_band(emissive, emissive_attrs, "31")
        radiance32 = _select_band(emissive, emissive_attrs, "32")
        t21 = brightness_temperature(radiance21, MODIS_WAVELENGTHS_UM["21"])
        t22 = brightness_temperature(radiance22, MODIS_WAVELENGTHS_UM["22"])
        t11 = brightness_temperature(radiance31, MODIS_WAVELENGTHS_UM["31"])
        t12 = brightness_temperature(radiance32, MODIS_WAVELENGTHS_UM["32"])

        use_band21 = ~np.isfinite(t22) | (t22 >= THRESHOLDS.band22_saturation_k)
        t4 = np.where(use_band21, t21, t22)
        source_band = np.where(use_band21, 21, 22).astype("uint8")

        latitude = geo_hdf.select("Latitude")[:].astype("float64")
        longitude = geo_hdf.select("Longitude")[:].astype("float64")
        land_sea = geo_hdf.select("Land/SeaMask")[:]
        land_mask = land_sea == 1

        return ModisObservation(
            latitude=latitude,
            longitude=longitude,
            t4=t4,
            t11=t11,
            t12=t12,
            reflectance1=_select_band(reflectance, reflectance_attrs, "1"),
            reflectance2=_select_band(reflectance, reflectance_attrs, "2"),
            solar_zenith=_scaled_geo(geo_hdf, "SolarZenith"),
            sensor_zenith=_scaled_geo(geo_hdf, "SensorZenith"),
            solar_azimuth=_scaled_geo(geo_hdf, "SolarAzimuth"),
            sensor_azimuth=_scaled_geo(geo_hdf, "SensorAzimuth"),
            land_mask=land_mask,
            satellite=pair.satellite,
            acquisition_time=acquisition_time_from_key(pair.granule_key),
            granule_key=pair.granule_key,
            source_data=pair.data_path.name,
            source_geo=pair.geo_path.name,
            t4_source_band=source_band,
        )
    finally:
        data_hdf.end()
        geo_hdf.end()
