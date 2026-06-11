from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from config import Config


REQUIRED_COLUMNS = {
    "latitude",
    "longitude",
    "satellite",
    "detection_time",
    "I4_BT",
    "M13_BT",
}

GRANULE_TOKEN = re.compile(r"\.A(\d{4})(\d{3})\.(\d{2})(\d{2})\.")


def load_viirs_observations(config: Config, use_dummy: bool = False) -> pd.DataFrame:
    """Load VIIRS-like observations from CSV/NetCDF, or generate fallback samples."""
    csv_files = sorted(config.paths.viirs.glob("*.csv"))
    nc_files = sorted(config.paths.viirs.glob("*.nc"))
    raw_pairs = local_vnp02mod_pairs(config.paths.viirs)

    if use_dummy or (not csv_files and not nc_files and not raw_pairs):
        return generate_dummy_viirs(config)

    frames: list[pd.DataFrame] = []
    for csv_path in csv_files:
        frame = pd.read_csv(csv_path)
        missing = REQUIRED_COLUMNS - set(frame.columns)
        if missing:
            raise ValueError(f"{csv_path} is missing required columns: {sorted(missing)}")
        frames.append(frame)

    generic_nc = [
        path
        for path in nc_files
        if not path.name.startswith(("VNP02MOD", "VNP03MOD"))
    ]
    for nc_path in generic_nc:
        frames.append(read_generic_viirs_netcdf(nc_path))

    for key, obs_path, geo_path in raw_pairs:
        print(f"Reading raw VIIRS NetCDF pair {key}...", flush=True)
        frames.append(read_vnp02mod_pair(key, obs_path, geo_path, config))

    if not frames:
        return generate_dummy_viirs(config)

    return pd.concat(frames, ignore_index=True)


def local_vnp02mod_pairs(data_dir: Path) -> list[tuple[str, Path, Path]]:
    vnp02 = {granule_key(path.name): path for path in data_dir.glob("VNP02MOD*.nc")}
    vnp03 = {granule_key(path.name): path for path in data_dir.glob("VNP03MOD*.nc")}
    keys = sorted(set(vnp02) & set(vnp03))
    return [(key, vnp02[key], vnp03[key]) for key in keys]


def granule_key(filename: str) -> str:
    match = GRANULE_TOKEN.search(filename)
    if not match:
        raise ValueError(f"Could not parse VIIRS granule time from {filename}")
    year, day, hour, minute = match.groups()
    return f"{year}{day}.{hour}{minute}"


def granule_datetime(filename_or_key: str) -> datetime:
    match = GRANULE_TOKEN.search(filename_or_key)
    if match:
        year, day, hour, minute = match.groups()
    else:
        key, hhmm = filename_or_key.split(".")
        year, day, hour, minute = key[:4], key[4:], hhmm[:2], hhmm[2:]
    start = datetime(int(year), 1, 1, tzinfo=timezone.utc)
    return start + timedelta(days=int(day) - 1, hours=int(hour), minutes=int(minute))


def bt_from_lut(values: np.ndarray, lut: np.ndarray) -> np.ndarray:
    bt = np.full(values.shape, np.nan, dtype="float32")
    valid = np.isfinite(values) & (values >= 0) & (values < len(lut))
    indexes = np.rint(values[valid]).astype("int64")
    bt[valid] = lut[indexes]
    return bt


def read_vnp02mod_pair(key: str, obs_path: Path, geo_path: Path, config: Config) -> pd.DataFrame:
    """Read NASA VNP02MOD/VNP03MOD files for Bhutan.

    VNP02MOD does not contain the true VIIRS I4 image band. For this test
    pipeline, M12 brightness temperature is used as a 3.7 micron I4 proxy,
    while M13 brightness temperature remains the validator.
    """
    bounds = config.bounds
    with xr.open_dataset(obs_path, group="/observation_data") as obs, xr.open_dataset(
        geo_path,
        group="/geolocation_data",
    ) as geo:
        lat = geo["latitude"].values.astype("float32")
        lon = geo["longitude"].values.astype("float32")
        bbox = (
            np.isfinite(lat)
            & np.isfinite(lon)
            & (lat >= bounds.min_lat)
            & (lat <= bounds.max_lat)
            & (lon >= bounds.min_lon)
            & (lon <= bounds.max_lon)
        )
        if not bbox.any():
            return pd.DataFrame(columns=sorted(REQUIRED_COLUMNS))

        # VNP02MOD stores moderate-resolution radiance for M12 and M13.
        # The project detector expects I4_BT/M13_BT columns, so for this raw
        # VNP02MOD test we feed log-radiance signals with explicit provenance.
        # True I4 testing needs VNP02IMG/VJ102IMG/VJ202IMG image-band products.
        m12_raw = obs["M12"].values.astype("float64")
        m13_raw = obs["M13"].values.astype("float64")
        m12_signal = np.log1p(m12_raw)
        m13_signal = np.log1p(m13_raw)

    valid = bbox & np.isfinite(m12_raw) & np.isfinite(m13_raw)
    valid &= np.isfinite(m12_signal) & np.isfinite(m13_signal)
    valid &= (m12_raw > 0) & (m13_raw > 0) & (m12_raw < 100) & (m13_raw < 100)
    valid_indexes = np.flatnonzero(valid.ravel())
    if len(valid_indexes) == 0:
        return pd.DataFrame(columns=sorted(REQUIRED_COLUMNS))

    score = np.maximum(m12_signal, m13_signal).ravel()
    top_n = min(300, len(valid_indexes))
    ranked_valid = valid_indexes[np.argsort(score[valid_indexes])]
    hot_indexes = ranked_valid[-top_n:]

    rng_seed = abs(hash(key)) % (2**32)
    rng = np.random.default_rng(rng_seed)
    sample_size = min(2000, len(valid_indexes))
    background_pool = np.setdiff1d(valid_indexes, hot_indexes, assume_unique=False)
    if len(background_pool) == 0:
        background_pool = valid_indexes
    sample_size = min(2000, len(background_pool))
    background_indexes = rng.choice(background_pool, size=sample_size, replace=False)
    keep_indexes = np.unique(np.concatenate([hot_indexes, background_indexes]))

    lat_flat = lat.ravel()[keep_indexes]
    lon_flat = lon.ravel()[keep_indexes]
    m12_flat = m12_signal.ravel()[keep_indexes]
    m13_flat = m13_signal.ravel()[keep_indexes]
    timestamp = granule_datetime(key).isoformat()
    return pd.DataFrame(
        {
            "latitude": lat_flat,
            "longitude": lon_flat,
            "satellite": "suomi_npp",
            "detection_time": timestamp,
            "I4_BT": m12_flat,
            "M13_BT": m13_flat,
            "I4_source": "M12_log_radiance_proxy_from_VNP02MOD",
            "M13_source": "M13_log_radiance_from_VNP02MOD",
            "thermal_units": "log1p_radiance",
            "raw_prefilter_top_n": top_n,
            "source_observation": obs_path.name,
            "source_geolocation": geo_path.name,
        }
    )


def read_generic_viirs_netcdf(path: Path) -> pd.DataFrame:
    """Read a simplified VIIRS NetCDF product with lat/lon/I4/M13 variables.

    Real VIIRS raw files vary by product. This reader supports a practical
    project convention: place pre-extracted NetCDF files with variables named
    latitude, longitude, I4_BT, and M13_BT in data/viirs.
    """
    with xr.open_dataset(path) as dataset:
        required = ["latitude", "longitude", "I4_BT", "M13_BT"]
        missing = [name for name in required if name not in dataset]
        if missing:
            raise ValueError(f"{path} is missing variables: {missing}")

        frame = pd.DataFrame(
            {
                "latitude": dataset["latitude"].values.ravel(),
                "longitude": dataset["longitude"].values.ravel(),
                "I4_BT": dataset["I4_BT"].values.ravel(),
                "M13_BT": dataset["M13_BT"].values.ravel(),
            }
        )

    frame["satellite"] = path.stem.split("_")[0]
    frame["detection_time"] = datetime.now(timezone.utc).isoformat()
    return frame


def generate_dummy_viirs(config: Config, count: int = 900) -> pd.DataFrame:
    """Generate deterministic VIIRS-like observations over Bhutan."""
    rng = np.random.default_rng(42)
    bounds = config.bounds
    satellites = np.array(["suomi_npp", "noaa20", "noaa21"])
    start = datetime(2023, 4, 8, 4, 0, tzinfo=timezone.utc)

    lat = rng.uniform(bounds.min_lat, bounds.max_lat, count)
    lon = rng.uniform(bounds.min_lon, bounds.max_lon, count)
    satellite = rng.choice(satellites, count)
    times = [start + timedelta(minutes=int(v)) for v in rng.uniform(0, 9 * 24 * 60, count)]

    i4 = rng.normal(298, 4.5, count)
    m13 = rng.normal(294, 3.5, count)

    fire_centers = [
        (27.25, 91.23, datetime(2023, 4, 11, 6, 0, tzinfo=timezone.utc)),
        (26.86, 89.42, datetime(2023, 4, 13, 8, 0, tzinfo=timezone.utc)),
        (27.51, 90.12, datetime(2023, 4, 14, 7, 0, tzinfo=timezone.utc)),
    ]
    for center_lat, center_lon, center_time in fire_centers:
        for sat in satellites:
            rows = rng.choice(count, 12, replace=False)
            lat[rows] = center_lat + rng.normal(0, 0.015, len(rows))
            lon[rows] = center_lon + rng.normal(0, 0.015, len(rows))
            satellite[rows] = sat
            times_for_sat = [
                center_time + timedelta(minutes=int(delta))
                for delta in rng.uniform(-75, 75, len(rows))
            ]
            for row, dt_value in zip(rows, times_for_sat):
                times[row] = dt_value
            i4[rows] += rng.uniform(18, 42, len(rows))
            m13[rows] += rng.uniform(8, 22, len(rows))

    return pd.DataFrame(
        {
            "latitude": lat,
            "longitude": lon,
            "satellite": satellite,
            "detection_time": [value.isoformat() for value in times],
            "I4_BT": i4,
            "M13_BT": m13,
        }
    )
