"""Load VIIRS observations or generate dummy observations for immediate testing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

import numpy as np
import xarray as xr

from config import BHUTAN_BOUNDS, SATELLITES


GRANULE_TOKEN = re.compile(r"\.A(\d{7})\.(\d{4})\.")
TAI93_EPOCH = datetime(1993, 1, 1, tzinfo=timezone.utc)


@dataclass
class VIIRSObservation:
    """Aligned VIIRS arrays for one satellite overpass."""

    latitude: np.ndarray
    longitude: np.ndarray
    bt4: np.ndarray
    bt5: np.ndarray
    m13: np.ndarray
    i1: np.ndarray
    i2: np.ndarray
    i3: np.ndarray
    land_water_mask: np.ndarray
    cloud_mask: np.ndarray
    bowtie_mask: np.ndarray
    satellite: str
    acquisition_time: datetime
    solar_zenith: np.ndarray
    view_zenith: np.ndarray
    relative_azimuth: np.ndarray


def _base_grid(shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    lat = np.linspace(BHUTAN_BOUNDS["min_lat"], BHUTAN_BOUNDS["max_lat"], shape[0])
    lon = np.linspace(BHUTAN_BOUNDS["min_lon"], BHUTAN_BOUNDS["max_lon"], shape[1])
    return np.meshgrid(lat, lon, indexing="ij")


def _insert_hotspot(arrays: dict[str, np.ndarray], lat_grid: np.ndarray, lon_grid: np.ndarray, lat: float, lon: float, strength: float) -> None:
    distance = (lat_grid - lat) ** 2 + (lon_grid - lon) ** 2
    row, col = np.unravel_index(np.argmin(distance), distance.shape)
    row_slice = slice(max(0, row - 1), min(arrays["bt4"].shape[0], row + 2))
    col_slice = slice(max(0, col - 1), min(arrays["bt4"].shape[1], col + 2))
    arrays["bt4"][row_slice, col_slice] += strength
    arrays["bt5"][row_slice, col_slice] += strength * 0.15
    arrays["m13"][row_slice, col_slice] += strength * 0.8


def generate_dummy_observation(satellite: str, acquisition_time: datetime, seed: int) -> VIIRSObservation:
    """Create one synthetic VIIRS overpass with a few repeatable hotspot pixels."""
    rng = np.random.default_rng(seed)
    shape = (80, 100)
    latitude, longitude = _base_grid(shape)

    bt5 = 286.0 + rng.normal(0, 2.0, shape)
    bt4 = bt5 + 4.0 + rng.normal(0, 1.8, shape)
    m13 = 285.0 + rng.normal(0, 2.5, shape)
    i1 = rng.uniform(0.04, 0.18, shape)
    i2 = rng.uniform(0.05, 0.22, shape)
    i3 = rng.uniform(0.04, 0.20, shape)

    arrays = {"bt4": bt4, "bt5": bt5, "m13": m13}

    # Same approximate locations are seen by multiple satellites, allowing the
    # fusion module to promote persistent detections.
    common_hotspots = [
        (27.26, 91.41, 48.0),
        (27.49, 89.90, 44.0),
    ]
    for lat, lon, strength in common_hotspots:
        _insert_hotspot(arrays, latitude, longitude, lat, lon, strength)

    if satellite == "NOAA21":
        _insert_hotspot(arrays, latitude, longitude, 26.91, 90.48, 34.0)

    # Simulate a bright roof/rock pixel that should be reduced by filters.
    roof_row, roof_col = 36, 31
    bt4[roof_row, roof_col] = 329.0
    bt5[roof_row, roof_col] = 300.0
    m13[roof_row, roof_col] = 292.0
    i2[roof_row, roof_col] = 0.33
    i3[roof_row, roof_col] = 0.42

    land_water_mask = np.ones(shape, dtype=bool)
    land_water_mask[:5, :12] = False
    cloud_mask = np.zeros(shape, dtype=bool)
    cloud_mask[10:16, 40:50] = True
    bowtie_mask = np.zeros(shape, dtype=bool)
    bowtie_mask[:, ::25] = True

    return VIIRSObservation(
        latitude=latitude,
        longitude=longitude,
        bt4=bt4,
        bt5=bt5,
        m13=m13,
        i1=i1,
        i2=i2,
        i3=i3,
        land_water_mask=land_water_mask,
        cloud_mask=cloud_mask,
        bowtie_mask=bowtie_mask,
        satellite=satellite,
        acquisition_time=acquisition_time,
        solar_zenith=np.full(shape, 38.0),
        view_zenith=np.full(shape, 12.0),
        relative_azimuth=np.full(shape, 25.0),
    )


def load_demo_observations() -> list[VIIRSObservation]:
    """Return three dummy overpasses from SNPP, NOAA-20, and NOAA-21."""
    start = datetime(2026, 1, 23, 5, 0, tzinfo=timezone.utc)
    return [
        generate_dummy_observation(satellite, start + timedelta(minutes=index * 55), seed=42 + index)
        for index, satellite in enumerate(SATELLITES)
    ]


def granule_key(path: Path) -> str:
    """Extract AYYYYDDD.HHMM as YYYYDDD.HHMM from a VIIRS filename."""
    match = GRANULE_TOKEN.search(path.name)
    if not match:
        raise ValueError(f"Could not extract VIIRS granule key from {path.name}")
    return ".".join(match.groups())


def acquisition_time_from_key(key: str) -> datetime:
    """Convert VIIRS YYYYDDD.HHMM key into a UTC datetime."""
    year_day, hhmm = key.split(".")
    year = int(year_day[:4])
    day_of_year = int(year_day[4:])
    hour = int(hhmm[:2])
    minute = int(hhmm[2:])
    return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_of_year - 1, hours=hour, minutes=minute)


def brightness_temperature_from_radiance(radiance: np.ndarray, wavelength_um: float) -> np.ndarray:
    """Convert spectral radiance to brightness temperature using Planck's law.

    Radiance is expected in W m-2 sr-1 um-1, matching NASA VIIRS L1B units.
    """
    c1 = 1.191042e8  # W um^4 m-2 sr-1
    c2 = 1.4387752e4  # um K
    radiance = np.asarray(radiance, dtype="float64")
    bt = np.full(radiance.shape, np.nan, dtype="float64")
    valid = np.isfinite(radiance) & (radiance > 0)
    bt[valid] = c2 / (wavelength_um * np.log((c1 / (radiance[valid] * wavelength_um**5)) + 1.0))
    return bt


def _normalize_reflectance_like(values: np.ndarray) -> np.ndarray:
    """Create a 0-1 reflectance-like array from an M-band when true I-bands are absent."""
    values = np.asarray(values, dtype="float64")
    output = np.zeros(values.shape, dtype="float64")
    valid = np.isfinite(values)
    if not valid.any():
        return output
    low, high = np.nanpercentile(values[valid], [2, 98])
    if high <= low:
        return output
    output[valid] = np.clip((values[valid] - low) / (high - low), 0.0, 1.0)
    return output


def _optional_observation(ds: xr.Dataset, name: str, row_slice: slice, col_slice: slice, shape: tuple[int, int]) -> np.ndarray:
    """Read an optional observation band or return zeros if it is absent."""
    if name not in ds:
        return np.zeros(shape, dtype="float64")
    return ds[name].values[row_slice, col_slice].astype("float64")


def _crop_to_bhutan_bbox(lat: np.ndarray, lon: np.ndarray) -> tuple[slice, slice]:
    """Return a row/column slice around Bhutan to keep real swaths manageable."""
    valid = (
        np.isfinite(lat)
        & np.isfinite(lon)
        & (lon >= BHUTAN_BOUNDS["min_lon"])
        & (lon <= BHUTAN_BOUNDS["max_lon"])
        & (lat >= BHUTAN_BOUNDS["min_lat"])
        & (lat <= BHUTAN_BOUNDS["max_lat"])
    )
    if not valid.any():
        return slice(0, 0), slice(0, 0)

    rows, cols = np.where(valid)
    pad = 5
    row_slice = slice(max(0, rows.min() - pad), min(lat.shape[0], rows.max() + pad + 1))
    col_slice = slice(max(0, cols.min() - pad), min(lat.shape[1], cols.max() + pad + 1))
    return row_slice, col_slice


def _read_scan_time(path: Path, fallback_key: str) -> datetime:
    """Read scan midpoint time if present; otherwise use filename time."""
    try:
        with xr.open_dataset(path, group="/scan_line_attributes") as scan:
            if "ev_mid_time" in scan:
                seconds = float(np.nanmedian(scan["ev_mid_time"].values))
                if np.isfinite(seconds) and seconds > 0:
                    return TAI93_EPOCH + timedelta(seconds=seconds)
    except Exception:
        pass
    return acquisition_time_from_key(fallback_key)


def load_mod_observation(mod_path: Path, geo_path: Path, satellite: str, key: str) -> VIIRSObservation:
    """Load a real VIIRS MOD pair.

    This is a working fallback for the files already present in this workspace.
    It uses:

    - M13 radiance converted to a 4 micrometer brightness temperature proxy
    - M15 radiance converted to an 11 micrometer brightness temperature proxy
    - M05/M07/M10 normalized as reflectance-like I1/I2/I3 proxies

    True I-band ingestion should be preferred when 02IMG/03IMG files are added.
    """
    with xr.open_dataset(geo_path, group="/geolocation_data") as geo:
        lat_full = geo["latitude"].values.astype("float64")
        lon_full = geo["longitude"].values.astype("float64")
        row_slice, col_slice = _crop_to_bhutan_bbox(lat_full, lon_full)
        lat = lat_full[row_slice, col_slice]
        lon = lon_full[row_slice, col_slice]
        land_water_raw = geo.get("land_water_mask")
        if land_water_raw is not None:
            land_water = land_water_raw.values[row_slice, col_slice]
            land_water_mask = np.isin(land_water, [1, 2, 3, 4, 5])
        else:
            land_water_mask = np.ones(lat.shape, dtype=bool)
        solar_zenith = geo.get("solar_zenith", xr.DataArray(np.full(lat_full.shape, 40.0))).values[row_slice, col_slice]
        sensor_zenith = geo.get("sensor_zenith", xr.DataArray(np.full(lat_full.shape, 10.0))).values[row_slice, col_slice]
        solar_azimuth = geo.get("solar_azimuth", xr.DataArray(np.zeros(lat_full.shape))).values[row_slice, col_slice]
        sensor_azimuth = geo.get("sensor_azimuth", xr.DataArray(np.zeros(lat_full.shape))).values[row_slice, col_slice]

    if lat.size == 0:
        raise ValueError(f"{geo_path.name} does not overlap Bhutan bounding box.")

    with xr.open_dataset(mod_path, group="/observation_data") as obs:
        m13_radiance = obs["M13"].values[row_slice, col_slice].astype("float64")
        m15_radiance = obs["M15"].values[row_slice, col_slice].astype("float64")
        m05 = obs.get("M05", xr.DataArray(np.zeros(obs["M13"].shape))).values[row_slice, col_slice]
        m07 = obs.get("M07", xr.DataArray(np.zeros(obs["M13"].shape))).values[row_slice, col_slice]
        m10 = obs.get("M10", xr.DataArray(np.zeros(obs["M13"].shape))).values[row_slice, col_slice]
        quality = obs.get("M13_quality_flags")
        if quality is not None:
            q = quality.values[row_slice, col_slice].astype("uint16")
            bowtie_mask = (q & 256) > 0
        else:
            bowtie_mask = np.zeros(lat.shape, dtype=bool)

    bt4_proxy = brightness_temperature_from_radiance(m13_radiance, 4.05)
    bt5_proxy = brightness_temperature_from_radiance(m15_radiance, 10.76)
    valid_radiance = np.isfinite(m13_radiance) & np.isfinite(m15_radiance) & (m13_radiance > 0) & (m15_radiance > 0)

    return VIIRSObservation(
        latitude=lat,
        longitude=lon,
        bt4=bt4_proxy,
        bt5=bt5_proxy,
        m13=bt4_proxy,
        i1=_normalize_reflectance_like(m05),
        i2=_normalize_reflectance_like(m07),
        i3=_normalize_reflectance_like(m10),
        land_water_mask=land_water_mask & valid_radiance,
        cloud_mask=np.zeros(lat.shape, dtype=bool),
        bowtie_mask=bowtie_mask,
        satellite=satellite,
        acquisition_time=_read_scan_time(mod_path, key),
        solar_zenith=solar_zenith.astype("float64"),
        view_zenith=sensor_zenith.astype("float64"),
        relative_azimuth=np.abs((solar_azimuth - sensor_azimuth + 180.0) % 360.0 - 180.0).astype("float64"),
    )


def load_img_mod_observation(
    img_path: Path,
    img_geo_path: Path,
    mod_path: Path,
    satellite: str,
    key: str,
) -> VIIRSObservation:
    """Load a true VIIRS 375 m I-band observation with MOD M13 validation.

    I04 is used as the main 3.74 micrometer fire band.
    I05 is used as the 11.45 micrometer background comparison band.
    M13 from the matching MOD product is converted to brightness temperature
    and repeated 2x to align with IMG resolution for energy validation.
    """
    with xr.open_dataset(img_geo_path, group="/geolocation_data") as geo:
        lat_full = geo["latitude"].values.astype("float64")
        lon_full = geo["longitude"].values.astype("float64")
        row_slice, col_slice = _crop_to_bhutan_bbox(lat_full, lon_full)
        lat = lat_full[row_slice, col_slice]
        lon = lon_full[row_slice, col_slice]

        land_water_raw = geo.get("land_water_mask")
        if land_water_raw is not None:
            land_water = land_water_raw.values[row_slice, col_slice]
            land_water_mask = np.isin(land_water, [1, 2, 3, 4, 5])
        else:
            land_water_mask = np.ones(lat.shape, dtype=bool)

        solar_zenith = geo.get("solar_zenith", xr.DataArray(np.full(lat_full.shape, 40.0))).values[row_slice, col_slice]
        sensor_zenith = geo.get("sensor_zenith", xr.DataArray(np.full(lat_full.shape, 10.0))).values[row_slice, col_slice]
        solar_azimuth = geo.get("solar_azimuth", xr.DataArray(np.zeros(lat_full.shape))).values[row_slice, col_slice]
        sensor_azimuth = geo.get("sensor_azimuth", xr.DataArray(np.zeros(lat_full.shape))).values[row_slice, col_slice]

    if lat.size == 0:
        raise ValueError(f"{img_geo_path.name} does not overlap Bhutan bounding box.")

    with xr.open_dataset(img_path, group="/observation_data") as obs:
        i1_radiance = _optional_observation(obs, "I01", row_slice, col_slice, lat.shape)
        i2_radiance = _optional_observation(obs, "I02", row_slice, col_slice, lat.shape)
        i3_radiance = _optional_observation(obs, "I03", row_slice, col_slice, lat.shape)
        i4_radiance = obs["I04"].values[row_slice, col_slice].astype("float64")
        i5_radiance = obs["I05"].values[row_slice, col_slice].astype("float64")
        q = obs.get("I04_quality_flags")
        if q is not None:
            quality = q.values[row_slice, col_slice].astype("uint16")
            bowtie_mask = (quality & 256) > 0
        else:
            bowtie_mask = np.zeros(lat.shape, dtype=bool)

    bt4 = brightness_temperature_from_radiance(i4_radiance, 3.74)
    bt5 = brightness_temperature_from_radiance(i5_radiance, 11.45)

    with xr.open_dataset(mod_path, group="/observation_data") as mod_obs:
        m13_full = mod_obs["M13"].values.astype("float64")
        m13_bt_full = brightness_temperature_from_radiance(m13_full, 4.05)
        m13_img = np.repeat(np.repeat(m13_bt_full, 2, axis=0), 2, axis=1)
        m13 = m13_img[row_slice, col_slice]

    valid = np.isfinite(bt4) & np.isfinite(bt5) & np.isfinite(m13) & (bt4 > 0) & (bt5 > 0) & (m13 > 0)

    return VIIRSObservation(
        latitude=lat,
        longitude=lon,
        bt4=bt4,
        bt5=bt5,
        m13=m13,
        i1=_normalize_reflectance_like(i1_radiance),
        i2=_normalize_reflectance_like(i2_radiance),
        i3=_normalize_reflectance_like(i3_radiance),
        land_water_mask=land_water_mask & valid,
        cloud_mask=np.zeros(lat.shape, dtype=bool),
        bowtie_mask=bowtie_mask,
        satellite=satellite,
        acquisition_time=_read_scan_time(img_path, key),
        solar_zenith=solar_zenith.astype("float64"),
        view_zenith=sensor_zenith.astype("float64"),
        relative_azimuth=np.abs((solar_azimuth - sensor_azimuth + 180.0) % 360.0 - 180.0).astype("float64"),
    )


def _satellite_from_product(name: str) -> str:
    if name.startswith("VNP"):
        return "SNPP"
    if name.startswith("VJ1"):
        return "NOAA20"
    if name.startswith("VJ2"):
        return "NOAA21"
    return "UNKNOWN"


def discover_img_mod_sets(roots: list[Path]) -> list[tuple[str, Path, Path, Path, Path, str]]:
    """Discover complete 02IMG/03IMG/02MOD/03MOD granule sets."""
    img_data_by_key: dict[str, Path] = {}
    img_geo_by_key: dict[str, Path] = {}
    mod_data_by_key: dict[str, Path] = {}
    mod_geo_by_key: dict[str, Path] = {}
    satellites: dict[str, str] = {}

    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.nc"):
            name = path.name
            if "02IMG" in name:
                key = granule_key(path)
                img_data_by_key[key] = path
                satellites[key] = _satellite_from_product(name)
            elif "03IMG" in name:
                img_geo_by_key[granule_key(path)] = path
            elif "02MOD" in name:
                mod_data_by_key[granule_key(path)] = path
            elif "03MOD" in name:
                mod_geo_by_key[granule_key(path)] = path

    keys = sorted(set(img_data_by_key) & set(img_geo_by_key) & set(mod_data_by_key) & set(mod_geo_by_key))
    return [
        (
            key,
            img_data_by_key[key],
            img_geo_by_key[key],
            mod_data_by_key[key],
            mod_geo_by_key[key],
            satellites.get(key, "UNKNOWN"),
        )
        for key in keys
    ]


def discover_mod_pairs(roots: list[Path]) -> list[tuple[str, Path, Path, str]]:
    """Discover real 02MOD/03MOD pairs in one or more folders."""
    data_by_key: dict[str, Path] = {}
    geo_by_key: dict[str, Path] = {}
    satellites: dict[str, str] = {}

    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.nc"):
            name = path.name
            if "02MOD" in name:
                key = granule_key(path)
                data_by_key[key] = path
                satellites[key] = _satellite_from_product(name)
            elif "03MOD" in name:
                geo_by_key[granule_key(path)] = path

    keys = sorted(set(data_by_key) & set(geo_by_key))
    return [(key, data_by_key[key], geo_by_key[key], satellites.get(key, "UNKNOWN")) for key in keys]


def load_real_observations(viirs_root: Path, fallback_raw_root: Path | None = None, max_observations: int | None = None) -> list[VIIRSObservation]:
    """Load real VIIRS observations from downloaded IMG/MOD or MOD pairs.

    True 375 m IMG observations are preferred. If no IMG files are available,
    the loader falls back to the MOD-only proxy reader.
    """
    roots = [viirs_root]
    if fallback_raw_root is not None:
        roots.append(fallback_raw_root)

    img_sets = discover_img_mod_sets(roots)
    if img_sets:
        if max_observations is not None:
            img_sets = img_sets[:max_observations]
        observations = []
        for key, img_path, img_geo_path, mod_path, _mod_geo_path, satellite in img_sets:
            observations.append(load_img_mod_observation(img_path, img_geo_path, mod_path, satellite, key))
        return observations

    pairs = discover_mod_pairs(roots)
    if max_observations is not None:
        pairs = pairs[:max_observations]
    observations = []
    for key, mod_path, geo_path, satellite in pairs:
        observations.append(load_mod_observation(mod_path, geo_path, satellite, key))
    return observations


def load_real_observation(path: Path, satellite: str, acquisition_time: datetime) -> VIIRSObservation:
    """Load a real VIIRS-like NetCDF file with expected variable names.

    The file should contain latitude, longitude, BT4, BT5, M13, I1, I2, I3,
    land_water_mask, cloud_mask, and bowtie_mask. Product-specific NASA file
    adapters can be added here without changing the downstream detector.
    """
    with xr.open_dataset(path) as ds:
        required = ["latitude", "longitude", "BT4", "BT5", "M13", "I1", "I2", "I3"]
        missing = [name for name in required if name not in ds]
        if missing:
            raise ValueError(f"{path} is missing required variables: {missing}")

        shape = ds["BT4"].shape
        return VIIRSObservation(
            latitude=ds["latitude"].values,
            longitude=ds["longitude"].values,
            bt4=ds["BT4"].values,
            bt5=ds["BT5"].values,
            m13=ds["M13"].values,
            i1=ds["I1"].values,
            i2=ds["I2"].values,
            i3=ds["I3"].values,
            land_water_mask=ds.get("land_water_mask", xr.DataArray(np.ones(shape, dtype=bool))).values.astype(bool),
            cloud_mask=ds.get("cloud_mask", xr.DataArray(np.zeros(shape, dtype=bool))).values.astype(bool),
            bowtie_mask=ds.get("bowtie_mask", xr.DataArray(np.zeros(shape, dtype=bool))).values.astype(bool),
            satellite=satellite,
            acquisition_time=acquisition_time,
            solar_zenith=ds.get("solar_zenith", xr.DataArray(np.full(shape, 40.0))).values,
            view_zenith=ds.get("view_zenith", xr.DataArray(np.full(shape, 10.0))).values,
            relative_azimuth=ds.get("relative_azimuth", xr.DataArray(np.full(shape, 20.0))).values,
        )
