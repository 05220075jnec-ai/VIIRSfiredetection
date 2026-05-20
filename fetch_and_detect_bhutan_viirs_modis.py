from __future__ import annotations

import argparse
import os
import re
import warnings
from pathlib import Path

import earthaccess
import geopandas as gpd
import netCDF4 as nc
import numpy as np
import pandas as pd
import xarray as xr
from shapely import contains_xy
from sklearn.cluster import DBSCAN


GRANULE_TOKEN = re.compile(r"\.A(\d{7})\.(\d{4})\.")

PRODUCT_PAIRS = {
    "viirs": ("VNP02MOD", "VNP03MOD"),
    "modis_terra": ("MOD021KM", "MOD03"),
    "modis_aqua": ("MYD021KM", "MYD03"),
}

SCRIPT_DIR = Path(__file__).resolve().parent


def project_path(path: Path) -> Path:
    return path if path.is_absolute() else SCRIPT_DIR / path


def configure_earthdata_netrc() -> None:
    for name in ("netrc", ".netrc", "_netrc"):
        local_netrc = project_path(Path(name))
        if local_netrc.exists():
            os.environ["NETRC"] = str(local_netrc.resolve())
            return


def granule_key(text: str) -> str:
    match = GRANULE_TOKEN.search(text)
    if not match:
        raise ValueError(f"Could not find AYYYYDDD.HHMM token in {text}")
    return ".".join(match.groups())


def granule_key_from_result(granule) -> str:
    umm = granule.get("umm", {})
    candidates = [
        umm.get("GranuleUR"),
        umm.get("ProducerGranuleId"),
        str(granule),
    ]
    try:
        candidates.extend(granule.data_links())
    except Exception:
        pass

    for candidate in candidates:
        if not candidate:
            continue
        match = GRANULE_TOKEN.search(candidate)
        if match:
            return ".".join(match.groups())

    raise ValueError(f"Could not find AYYYYDDD.HHMM token in granule metadata: {candidates}")


def load_bhutan_boundary(boundary_path: Path) -> tuple[gpd.GeoDataFrame, object, tuple[float, float, float, float]]:
    boundary = gpd.read_file(boundary_path)
    if boundary.crs is None:
        boundary = boundary.set_crs("EPSG:4326")
    else:
        boundary = boundary.to_crs("EPSG:4326")

    bhutan_polygon = boundary.geometry.union_all()
    bbox = tuple(boundary.total_bounds)  # lon_min, lat_min, lon_max, lat_max
    return boundary, bhutan_polygon, bbox


def search_product_pairs(
    sensor: str,
    temporal: tuple[str, str],
    bbox: tuple[float, float, float, float],
    max_granules: int,
):
    data_product, geo_product = PRODUCT_PAIRS[sensor]
    searches = {}

    for short_name in (data_product, geo_product):
        granules = earthaccess.search_data(
            short_name=short_name,
            bounding_box=bbox,
            temporal=temporal,
            count=max_granules,
        )
        searches[short_name] = {granule_key_from_result(g): g for g in granules}

    common_keys = sorted(set(searches[data_product]) & set(searches[geo_product]))
    if not common_keys:
        print(
            f"No matching {data_product}/{geo_product} pairs found. "
            f"Found {len(searches[data_product])} {data_product} keys and "
            f"{len(searches[geo_product])} {geo_product} keys.",
            flush=True,
        )
        return []

    return [
        (sensor, key, searches[data_product][key], searches[geo_product][key])
        for key in common_keys
    ]


def search_all_pairs(
    temporal: tuple[str, str],
    bbox: tuple[float, float, float, float],
    max_granules: int,
    sensors: list[str],
):
    pairs = []
    for sensor in sensors:
        print(f"Searching {sensor} granules...", flush=True)
        pairs.extend(search_product_pairs(sensor, temporal, bbox, max_granules))
    return pairs


def download_pair(sensor: str, key: str, data_granule, geo_granule, data_dir: Path) -> tuple[str, str, Path, Path]:
    sensor_dir = data_dir / sensor
    sensor_dir.mkdir(parents=True, exist_ok=True)
    paths = earthaccess.download([data_granule, geo_granule], local_path=str(sensor_dir), threads=2)

    data_prefix, geo_prefix = PRODUCT_PAIRS[sensor]
    by_name = {Path(path).name: Path(path) for path in paths}
    data_path = next(path for name, path in by_name.items() if name.startswith(data_prefix))
    geo_path = next(path for name, path in by_name.items() if name.startswith(geo_prefix))
    return sensor, key, data_path, geo_path


def local_pairs_for_sensor(sensor: str, data_dir: Path) -> list[tuple[str, str, Path, Path]]:
    data_prefix, geo_prefix = PRODUCT_PAIRS[sensor]
    sensor_dirs = [data_dir / sensor, data_dir]
    data_files = {}
    geo_files = {}

    for directory in sensor_dirs:
        if not directory.exists():
            continue
        for suffix in ("*.nc", "*.hdf"):
            data_files.update({granule_key(path.name): path for path in directory.glob(f"{data_prefix}{suffix}")})
            geo_files.update({granule_key(path.name): path for path in directory.glob(f"{geo_prefix}{suffix}")})

    common_keys = sorted(set(data_files) & set(geo_files))
    return [(sensor, key, data_files[key], geo_files[key]) for key in common_keys]


def local_pairs(data_dir: Path, sensors: list[str]) -> list[tuple[str, str, Path, Path]]:
    pairs = []
    for sensor in sensors:
        pairs.extend(local_pairs_for_sensor(sensor, data_dir))
    return pairs


def empty_hotspots() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=gpd.GeoSeries([], crs="EPSG:4326"), crs="EPSG:4326")


def boundary_mask(
    value: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    bbox: tuple[float, float, float, float],
    bhutan_polygon,
) -> np.ndarray:
    lon_min, lat_min, lon_max, lat_max = bbox
    valid = (
        np.isfinite(value)
        & np.isfinite(lat)
        & np.isfinite(lon)
        & (value > 0)
        & (lon >= lon_min)
        & (lon <= lon_max)
        & (lat >= lat_min)
        & (lat <= lat_max)
    )

    if not valid.any():
        return valid

    inside_bhutan = np.zeros(value.shape, dtype=bool)
    inside_bhutan[valid] = contains_xy(bhutan_polygon, lon[valid], lat[valid])
    return valid & inside_bhutan


def detect_viirs_hotspots(
    key: str,
    data_path: Path,
    geo_path: Path,
    bbox: tuple[float, float, float, float],
    bhutan_polygon,
    percentile: float,
) -> gpd.GeoDataFrame:
    with xr.open_dataset(data_path, group="/observation_data") as obs:
        m13 = obs.M13.values.astype("float64")
    with xr.open_dataset(geo_path, group="/geolocation_data") as geo:
        lat = geo.latitude.values.astype("float64")
        lon = geo.longitude.values.astype("float64")

    valid = boundary_mask(m13, lat, lon, bbox, bhutan_polygon) & (m13 < 100)
    if not valid.any():
        return empty_hotspots()

    log_m13 = np.full(m13.shape, np.nan, dtype="float64")
    log_m13[valid] = np.log(m13[valid])
    threshold = np.nanpercentile(log_m13[valid], percentile)
    hot = valid & (log_m13 >= threshold)
    if not hot.any():
        return empty_hotspots()

    df = pd.DataFrame(
        {
            "sensor": "viirs",
            "satellite": "Suomi NPP",
            "longitude": lon[hot],
            "latitude": lat[hot],
            "thermal_value": m13[hot],
            "thermal_log": log_m13[hot],
            "threshold": threshold,
            "thermal_band": "M13",
            "granule_key": key,
            "source_data": data_path.name,
            "source_geo": geo_path.name,
        }
    )
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.longitude, df.latitude), crs="EPSG:4326")


def scaled_modis_radiance(emissive, raw: np.ndarray) -> tuple[np.ndarray, str]:
    attrs = {name: getattr(emissive, name) for name in emissive.ncattrs()}
    band_names = [band.strip() for band in attrs["band_names"].split(",")]

    # MODIS fire detection uses the 4 micron channel. Band 21 is preferred;
    # band 22 is the backup high-temperature 4 micron channel.
    band_name = "21" if "21" in band_names else "22"
    band_index = band_names.index(band_name)
    radiance = raw[band_index].astype("float64")

    fill_value = attrs.get("_FillValue")
    valid_range = attrs.get("valid_range")
    if fill_value is not None:
        radiance[radiance == fill_value] = np.nan
    if valid_range is not None:
        low, high = valid_range
        radiance[(radiance < low) | (radiance > high)] = np.nan

    scales = np.asarray(attrs["radiance_scales"], dtype="float64")
    offsets = np.asarray(attrs["radiance_offsets"], dtype="float64")
    radiance = (radiance - offsets[band_index]) * scales[band_index]
    return radiance, f"MODIS_{band_name}"


def read_modis_netcdf(data_path: Path, geo_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    with nc.Dataset(data_path) as data_ds, nc.Dataset(geo_path) as geo_ds:
        data_fields = data_ds["/HDFEOS/SWATHS/MODIS_SWATH_Type_L1B/Data Fields"]
        geo_fields = geo_ds["/HDFEOS/SWATHS/MODIS_Swath_Type_GEO/Geolocation Fields"]

        emissive = data_fields.variables["EV_1KM_Emissive"]
        raw = np.asarray(emissive[:])
        radiance, band_name = scaled_modis_radiance(emissive, raw)
        lat = np.asarray(geo_fields.variables["Latitude"][:], dtype="float64")
        lon = np.asarray(geo_fields.variables["Longitude"][:], dtype="float64")

    return radiance, lat, lon, band_name


def read_modis_hdf4(data_path: Path, geo_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    try:
        from pyhdf.SD import SD, SDC
    except ImportError as exc:
        raise RuntimeError(
            "This MODIS file is HDF4 and needs pyhdf. On Windows, pyhdf does not "
            "currently install cleanly on Python 3.14. Use the Earthdata .nc "
            "downloads, or run this script in Python 3.11/3.12 with pyhdf installed."
        ) from exc

    data_hdf = SD(str(data_path), SDC.READ)
    geo_hdf = SD(str(geo_path), SDC.READ)

    emissive = data_hdf.select("EV_1KM_Emissive")
    raw = emissive[:].astype("float64")
    attrs = emissive.attributes()
    band_names = [band.strip() for band in attrs["band_names"].split(",")]

    # MODIS fire detection uses the 4 micron channel. Band 21 is preferred;
    # band 22 is the backup high-temperature 4 micron channel.
    band_name = "21" if "21" in band_names else "22"
    band_index = band_names.index(band_name)
    radiance = raw[band_index]

    scales = np.asarray(attrs.get("radiance_scales"), dtype="float64")
    offsets = np.asarray(attrs.get("radiance_offsets"), dtype="float64")
    fill_value = attrs.get("_FillValue")
    valid_range = attrs.get("valid_range")

    if fill_value is not None:
        radiance[radiance == fill_value] = np.nan
    if valid_range is not None:
        low, high = valid_range
        radiance[(radiance < low) | (radiance > high)] = np.nan

    radiance = (radiance - offsets[band_index]) * scales[band_index]
    lat = geo_hdf.select("Latitude")[:].astype("float64")
    lon = geo_hdf.select("Longitude")[:].astype("float64")
    return radiance, lat, lon, f"MODIS_{band_name}"


def read_modis_file(data_path: Path, geo_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    if data_path.suffix.casefold() == ".nc":
        return read_modis_netcdf(data_path, geo_path)
    return read_modis_hdf4(data_path, geo_path)


def detect_modis_hotspots(
    sensor: str,
    key: str,
    data_path: Path,
    geo_path: Path,
    bbox: tuple[float, float, float, float],
    bhutan_polygon,
    percentile: float,
) -> gpd.GeoDataFrame:
    radiance, lat, lon, band_name = read_modis_file(data_path, geo_path)
    valid = boundary_mask(radiance, lat, lon, bbox, bhutan_polygon)
    if not valid.any():
        return empty_hotspots()

    log_radiance = np.full(radiance.shape, np.nan, dtype="float64")
    log_radiance[valid] = np.log(radiance[valid])
    threshold = np.nanpercentile(log_radiance[valid], percentile)
    hot = valid & (log_radiance >= threshold)
    if not hot.any():
        return empty_hotspots()

    satellite = "Terra" if sensor == "modis_terra" else "Aqua"
    df = pd.DataFrame(
        {
            "sensor": "modis",
            "satellite": satellite,
            "longitude": lon[hot],
            "latitude": lat[hot],
            "thermal_value": radiance[hot],
            "thermal_log": log_radiance[hot],
            "threshold": threshold,
            "thermal_band": band_name,
            "granule_key": key,
            "source_data": data_path.name,
            "source_geo": geo_path.name,
        }
    )
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.longitude, df.latitude), crs="EPSG:4326")


def detect_hotspots_for_pair(
    sensor: str,
    key: str,
    data_path: Path,
    geo_path: Path,
    bbox: tuple[float, float, float, float],
    bhutan_polygon,
    percentile: float,
) -> gpd.GeoDataFrame:
    if sensor == "viirs":
        return detect_viirs_hotspots(key, data_path, geo_path, bbox, bhutan_polygon, percentile)
    return detect_modis_hotspots(sensor, key, data_path, geo_path, bbox, bhutan_polygon, percentile)


def add_dzongkhag_names(hotspots: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if hotspots.empty or "Dzongkhag" not in boundary.columns:
        return hotspots

    joined = gpd.sjoin(
        hotspots,
        boundary[["Dzongkhag", "geometry"]],
        how="left",
        predicate="within",
    )
    return joined.drop(columns=["index_right"], errors="ignore")


def build_cluster_polygons(hotspots: gpd.GeoDataFrame, out_dir: Path) -> gpd.GeoDataFrame:
    cluster_rows = []
    for cluster_id in sorted(hotspots["cluster"].unique()):
        if cluster_id == -1:
            continue

        cluster_points = hotspots[hotspots["cluster"] == cluster_id]
        hull = cluster_points.geometry.union_all().convex_hull
        if hull.geom_type != "Polygon":
            continue

        dzongkhags = ""
        if "Dzongkhag" in cluster_points:
            dzongkhags = ",".join(sorted(cluster_points["Dzongkhag"].dropna().unique()))

        sensors = ",".join(sorted(cluster_points["sensor"].dropna().unique()))
        satellites = ",".join(sorted(cluster_points["satellite"].dropna().unique()))
        cluster_rows.append(
            {
                "cluster": int(cluster_id),
                "points": int(len(cluster_points)),
                "sensors": sensors,
                "satellites": satellites,
                "dzongkhag": dzongkhags,
                "geometry": hull,
            }
        )

    if cluster_rows:
        cluster_gdf = gpd.GeoDataFrame(cluster_rows, geometry="geometry", crs="EPSG:4326")
        cluster_gdf.to_file(out_dir / "bhutan_fire_clusters.geojson", driver="GeoJSON")
        cluster_gdf.to_file(out_dir / "bhutan_fire_clusters.shp", driver="ESRI Shapefile")
    else:
        cluster_gdf = gpd.GeoDataFrame(
            {"cluster": [], "points": [], "sensors": [], "satellites": [], "dzongkhag": []},
            geometry=gpd.GeoSeries([], crs="EPSG:4326"),
            crs="EPSG:4326",
        )

    return cluster_gdf


def export_outputs(
    hotspots: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    out_dir: Path,
    cluster_eps: float,
    min_samples: int,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    out_dir.mkdir(parents=True, exist_ok=True)

    if hotspots.empty:
        raise RuntimeError("No hotspot pixels were found inside the Bhutan boundary.")

    hotspots = add_dzongkhag_names(hotspots, boundary)
    coords = hotspots[["longitude", "latitude"]].to_numpy()
    hotspots["cluster"] = DBSCAN(eps=cluster_eps, min_samples=min_samples).fit_predict(coords)

    hotspots.to_csv(out_dir / "bhutan_fire_hotspots.csv", index=False)
    hotspots.to_file(out_dir / "bhutan_fire_hotspots.geojson", driver="GeoJSON")
    hotspots.to_file(out_dir / "bhutan_fire_hotspots.shp", driver="ESRI Shapefile")

    clusters = build_cluster_polygons(hotspots, out_dir)
    return hotspots, clusters


def parse_sensors(sensor_arg: str) -> list[str]:
    if sensor_arg == "all":
        return list(PRODUCT_PAIRS)

    sensors = [sensor.strip() for sensor in sensor_arg.split(",") if sensor.strip()]
    unknown = sorted(set(sensors) - set(PRODUCT_PAIRS))
    if unknown:
        raise ValueError(f"Unknown sensor(s): {', '.join(unknown)}")
    return sensors


def main() -> None:
    warnings.filterwarnings(
        "ignore",
        message="As of version 1.0, `DataGranule.size`",
        category=FutureWarning,
        module="earthaccess.store",
    )

    parser = argparse.ArgumentParser(
        description=(
            "Download VIIRS and MODIS Level-1 data over all Bhutan, detect hot thermal "
            "pixels inside bhutan_dzong_web.geojson, and export QGIS-ready outputs."
        )
    )
    parser.add_argument("--start", required=True, help="Start date/time, e.g. 2023-04-08")
    parser.add_argument("--end", required=True, help="End date/time, e.g. 2023-04-17")
    parser.add_argument("--boundary", default="bhutan_dzong_web.geojson", type=Path)
    parser.add_argument("--data-dir", default="data_bhutan_viirs_modis", type=Path)
    parser.add_argument("--out-dir", default="outputs_bhutan_viirs_modis", type=Path)
    parser.add_argument("--percentile", default=99.9, type=float)
    parser.add_argument("--cluster-eps", default=0.5, type=float)
    parser.add_argument("--min-samples", default=4, type=int)
    parser.add_argument("--max-granules", default=200, type=int)
    parser.add_argument(
        "--sensors",
        default="all",
        help="Use all, or a comma list: viirs,modis_terra,modis_aqua",
    )
    parser.add_argument("--local-only", action="store_true")
    args = parser.parse_args()

    configure_earthdata_netrc()

    sensors = parse_sensors(args.sensors)
    boundary, bhutan_polygon, bbox = load_bhutan_boundary(args.boundary)

    if args.local_only:
        pairs = local_pairs(args.data_dir, sensors)
    else:
        earthaccess.login(strategy="netrc")
        pairs = search_all_pairs((args.start, args.end), bbox, args.max_granules, sensors)

    if not pairs:
        raise RuntimeError("No matching data/geolocation pairs were found for the selected sensors.")

    hotspot_layers = []
    for pair in pairs:
        sensor, key = pair[0], pair[1]
        print(f"Processing {sensor} granule pair {key}...", flush=True)
        if args.local_only:
            _, _, data_path, geo_path = pair
        else:
            _, _, data_granule, geo_granule = pair
            _, _, data_path, geo_path = download_pair(sensor, key, data_granule, geo_granule, args.data_dir)

        gdf = detect_hotspots_for_pair(
            sensor,
            key,
            data_path,
            geo_path,
            bbox,
            bhutan_polygon,
            args.percentile,
        )
        if not gdf.empty:
            hotspot_layers.append(gdf)

    if hotspot_layers:
        all_hotspots = gpd.GeoDataFrame(
            pd.concat(hotspot_layers, ignore_index=True),
            geometry="geometry",
            crs="EPSG:4326",
        )
    else:
        all_hotspots = empty_hotspots()

    hotspots, clusters = export_outputs(
        all_hotspots,
        boundary,
        args.out_dir,
        args.cluster_eps,
        args.min_samples,
    )

    print(f"Granule pairs processed: {len(pairs)}")
    print(f"Hotspots exported: {len(hotspots)}")
    print("Hotspots by sensor:")
    for sensor, count in hotspots["sensor"].value_counts().items():
        print(f"  {sensor}: {count}")
    print(f"DBSCAN clusters exported: {len(clusters)}")
    print(f"Output folder: {args.out_dir.resolve()}")


if __name__ == "__main__":
    main()
