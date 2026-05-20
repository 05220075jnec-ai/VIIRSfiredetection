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
from shapely import contains_xy
from sklearn.cluster import DBSCAN


GRANULE_TOKEN = re.compile(r"\.A(\d{7})\.(\d{4})\.")

PRODUCT_PAIRS = {
    "terra": ("MOD021KM", "MOD03"),
    "aqua": ("MYD021KM", "MYD03"),
}

SCRIPT_DIR = Path(__file__).resolve().parent


def project_path(path: Path) -> Path:
    return path if path.is_absolute() else SCRIPT_DIR / path


def boundary_path(path: Path) -> Path:
    resolved = project_path(path)
    if resolved.exists():
        return resolved

    fallback = SCRIPT_DIR / "data" / "boundaries" / path.name
    if fallback.exists():
        return fallback

    return resolved


def configure_earthdata_netrc() -> None:
    for name in ("netrc", ".netrc", "_netrc"):
        local_netrc = project_path(Path(name))
        if local_netrc.exists():
            os.environ["NETRC"] = str(local_netrc.resolve())
            return


class UnsupportedHDF4Error(RuntimeError):
    pass


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
    bbox = tuple(boundary.total_bounds)
    return boundary, bhutan_polygon, bbox


def search_modis_pairs(
    satellites: list[str],
    temporal: tuple[str, str],
    bbox: tuple[float, float, float, float],
    max_granules: int,
    product_version: str,
):
    pairs = []
    for satellite in satellites:
        data_product, geo_product = PRODUCT_PAIRS[satellite]
        searches = {}
        print(f"Searching MODIS {satellite} granules...", flush=True)

        for short_name in (data_product, geo_product):
            granules = earthaccess.search_data(
                short_name=short_name,
                version=product_version,
                bounding_box=bbox,
                temporal=temporal,
                count=max_granules,
            )
            searches[short_name] = {granule_key_from_result(g): g for g in granules}

        common_keys = sorted(set(searches[data_product]) & set(searches[geo_product]))
        if not common_keys:
            print(f"No matching {data_product}/{geo_product} pairs found.", flush=True)
            continue

        pairs.extend(
            (satellite, key, searches[data_product][key], searches[geo_product][key])
            for key in common_keys
        )

    return pairs


def download_raw_pair(satellite: str, key: str, data_granule, geo_granule, data_dir: Path) -> list[Path]:
    satellite_dir = data_dir / satellite
    satellite_dir.mkdir(parents=True, exist_ok=True)
    paths = earthaccess.download([data_granule, geo_granule], local_path=str(satellite_dir), threads=2)
    downloaded = [Path(path) for path in paths]
    for path in downloaded:
        print(f"Downloaded raw MODIS file: {path}", flush=True)
    return downloaded


def prefer_netcdf(paths: list[Path]) -> Path:
    nc_paths = [path for path in paths if path.suffix.casefold() == ".nc"]
    return sorted(nc_paths or paths)[0]


def local_file_for_key(directory: Path, prefix: str, key: str, require_netcdf: bool = True) -> Path:
    matches = [
        path
        for path in directory.glob(f"{prefix}.A*")
        if path.suffix.casefold() in {".nc", ".hdf"} and granule_key(path.name) == key
    ]
    if require_netcdf:
        matches = [path for path in matches if path.suffix.casefold() == ".nc"]
    if not matches:
        suffix = " NetCDF" if require_netcdf else ""
        raise FileNotFoundError(f"No local{suffix} {prefix} file found for granule key {key} in {directory}")
    return prefer_netcdf(matches)


def download_pair(satellite: str, key: str, data_granule, geo_granule, data_dir: Path) -> tuple[str, str, Path, Path]:
    satellite_dir = data_dir / satellite
    satellite_dir.mkdir(parents=True, exist_ok=True)
    download_raw_pair(satellite, key, data_granule, geo_granule, data_dir)

    data_prefix, geo_prefix = PRODUCT_PAIRS[satellite]
    try:
        data_path = local_file_for_key(satellite_dir, data_prefix, key)
        geo_path = local_file_for_key(satellite_dir, geo_prefix, key)
    except FileNotFoundError as exc:
        raise UnsupportedHDF4Error(
            f"Skipping MODIS {satellite} {key}: Earthdata downloaded an HDF4 file "
            "for this pair, but this Python environment reads MODIS NetCDF only."
        ) from exc
    return satellite, key, data_path, geo_path


def local_pairs_for_satellite(satellite: str, data_dir: Path) -> list[tuple[str, str, Path, Path]]:
    data_prefix, geo_prefix = PRODUCT_PAIRS[satellite]
    satellite_dirs = [data_dir / satellite, data_dir / f"modis_{satellite}", data_dir]
    pairs = []
    seen = set()

    for directory in satellite_dirs:
        if not directory.exists():
            continue

        data_files = [
            path
            for path in directory.glob(f"{data_prefix}.A*")
            if path.suffix.casefold() == ".nc"
        ]
        for data_path in data_files:
            key = granule_key(data_path.name)
            if key in seen:
                continue
            try:
                geo_path = local_file_for_key(directory, geo_prefix, key)
            except FileNotFoundError:
                continue
            pairs.append((satellite, key, prefer_netcdf([data_path]), geo_path))
            seen.add(key)

    return sorted(pairs, key=lambda row: row[1])


def local_pairs(data_dir: Path, satellites: list[str]) -> list[tuple[str, str, Path, Path]]:
    pairs = []
    for satellite in satellites:
        pairs.extend(local_pairs_for_satellite(satellite, data_dir))
    return pairs


def find_variable(group, variable_name: str):
    if variable_name in group.variables:
        return group.variables[variable_name]

    for subgroup in group.groups.values():
        variable = find_variable(subgroup, variable_name)
        if variable is not None:
            return variable

    return None


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


def modis_band_radiance(emissive) -> tuple[np.ndarray, str]:
    attrs = {name: getattr(emissive, name) for name in emissive.ncattrs()}
    band_names = [band.strip() for band in attrs["band_names"].split(",")]
    band_name = "21" if "21" in band_names else "22"
    band_index = band_names.index(band_name)

    radiance = np.asarray(emissive[band_index], dtype="float64")
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
        emissive = find_variable(data_ds, "EV_1KM_Emissive")
        lat_var = find_variable(geo_ds, "Latitude")
        lon_var = find_variable(geo_ds, "Longitude")

        if emissive is None:
            raise RuntimeError(f"EV_1KM_Emissive was not found in {data_path.name}")
        if lat_var is None or lon_var is None:
            raise RuntimeError(f"Latitude/Longitude were not found in {geo_path.name}")

        radiance, band_name = modis_band_radiance(emissive)
        lat = np.asarray(lat_var[:], dtype="float64")
        lon = np.asarray(lon_var[:], dtype="float64")

    return radiance, lat, lon, band_name


def read_modis_hdf4(data_path: Path, geo_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    try:
        from pyhdf.SD import SD, SDC
    except ImportError as exc:
        raise UnsupportedHDF4Error(
            "This local MODIS pair uses HDF4. Python 3.14 on Windows often cannot "
            "install pyhdf from pip. Delete the .hdf copy or re-download Earthdata "
            ".nc files, then rerun this script."
        ) from exc

    data_hdf = SD(str(data_path), SDC.READ)
    geo_hdf = SD(str(geo_path), SDC.READ)
    emissive = data_hdf.select("EV_1KM_Emissive")
    raw = emissive[:].astype("float64")
    attrs = emissive.attributes()
    band_names = [band.strip() for band in attrs["band_names"].split(",")]
    band_name = "21" if "21" in band_names else "22"
    band_index = band_names.index(band_name)
    radiance = raw[band_index]

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
    lat = geo_hdf.select("Latitude")[:].astype("float64")
    lon = geo_hdf.select("Longitude")[:].astype("float64")
    return radiance, lat, lon, f"MODIS_{band_name}"


def read_modis_pair(data_path: Path, geo_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    if data_path.suffix.casefold() == ".nc" and geo_path.suffix.casefold() == ".nc":
        return read_modis_netcdf(data_path, geo_path)
    raise UnsupportedHDF4Error(
        f"Skipping HDF4 MODIS pair: {data_path.name} / {geo_path.name}. "
        "Use NetCDF .nc MODIS files with this Python environment."
    )


def detect_hotspots_for_pair(
    satellite: str,
    key: str,
    data_path: Path,
    geo_path: Path,
    bbox: tuple[float, float, float, float],
    bhutan_polygon,
    percentile: float,
) -> gpd.GeoDataFrame:
    radiance, lat, lon, band_name = read_modis_pair(data_path, geo_path)
    valid = boundary_mask(radiance, lat, lon, bbox, bhutan_polygon)
    if not valid.any():
        return empty_hotspots()

    log_radiance = np.full(radiance.shape, np.nan, dtype="float64")
    log_radiance[valid] = np.log(radiance[valid])
    threshold = np.nanpercentile(log_radiance[valid], percentile)
    hot = valid & (log_radiance >= threshold)
    if not hot.any():
        return empty_hotspots()

    df = pd.DataFrame(
        {
            "sensor": "modis",
            "satellite": satellite.title(),
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

        satellites = ",".join(sorted(cluster_points["satellite"].dropna().unique()))
        cluster_rows.append(
            {
                "cluster": int(cluster_id),
                "points": int(len(cluster_points)),
                "satellites": satellites,
                "dzongkhag": dzongkhags,
                "geometry": hull,
            }
        )

    if not cluster_rows:
        return gpd.GeoDataFrame(
            {"cluster": [], "points": [], "satellites": [], "dzongkhag": []},
            geometry=gpd.GeoSeries([], crs="EPSG:4326"),
            crs="EPSG:4326",
        )

    cluster_gdf = gpd.GeoDataFrame(cluster_rows, geometry="geometry", crs="EPSG:4326")
    cluster_gdf.to_file(out_dir / "bhutan_modis_fire_clusters.geojson", driver="GeoJSON")
    cluster_gdf.to_file(out_dir / "bhutan_modis_fire_clusters.shp", driver="ESRI Shapefile")
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
        raise RuntimeError("No MODIS hotspot pixels were found inside the Bhutan boundary.")

    hotspots = add_dzongkhag_names(hotspots, boundary)
    coords = hotspots[["longitude", "latitude"]].to_numpy()
    hotspots["cluster"] = DBSCAN(eps=cluster_eps, min_samples=min_samples).fit_predict(coords)

    hotspots.to_csv(out_dir / "bhutan_modis_fire_hotspots.csv", index=False)
    hotspots.to_file(out_dir / "bhutan_modis_fire_hotspots.geojson", driver="GeoJSON")
    hotspots.to_file(out_dir / "bhutan_modis_fire_hotspots.shp", driver="ESRI Shapefile")

    clusters = build_cluster_polygons(hotspots, out_dir)
    return hotspots, clusters


def parse_satellites(satellites_arg: str) -> list[str]:
    if satellites_arg == "all":
        return list(PRODUCT_PAIRS)

    satellites = [item.strip().casefold() for item in satellites_arg.split(",") if item.strip()]
    unknown = sorted(set(satellites) - set(PRODUCT_PAIRS))
    if unknown:
        raise ValueError(f"Unknown MODIS satellite(s): {', '.join(unknown)}")
    return satellites


def main() -> None:
    warnings.filterwarnings(
        "ignore",
        message="As of version 1.0, `DataGranule.size`",
        category=FutureWarning,
        module="earthaccess.store",
    )

    parser = argparse.ArgumentParser(
        description="Download MODIS Terra/Aqua over all Bhutan and export MODIS fire hotspot outputs."
    )
    parser.add_argument("--start", required=True, help="Start date/time, e.g. 2023-04-08")
    parser.add_argument("--end", required=True, help="End date/time, e.g. 2023-04-17")
    parser.add_argument("--boundary", default="data/boundaries/bhutan_dzong_web.geojson", type=Path)
    parser.add_argument("--data-dir", default="data_bhutan_modis", type=Path)
    parser.add_argument("--out-dir", default="outputs_bhutan_modis", type=Path)
    parser.add_argument("--percentile", default=99.9, type=float)
    parser.add_argument("--cluster-eps", default=0.5, type=float)
    parser.add_argument("--min-samples", default=4, type=int)
    parser.add_argument("--max-granules", default=200, type=int)
    parser.add_argument(
        "--product-version",
        default="6.1",
        help="MODIS collection version. Use 6.1 for raw HDF4 .hdf files; use 7 for NetCDF .nc.",
    )
    parser.add_argument("--satellites", default="all", help="Use all, terra, aqua, or terra,aqua")
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Only fetch raw MODIS files; do not run hotspot detection.",
    )
    args = parser.parse_args()

    args.boundary = boundary_path(args.boundary)
    args.data_dir = project_path(args.data_dir)
    args.out_dir = project_path(args.out_dir)

    configure_earthdata_netrc()

    satellites = parse_satellites(args.satellites)
    boundary, bhutan_polygon, bbox = load_bhutan_boundary(args.boundary)

    if args.local_only:
        pairs = local_pairs(args.data_dir, satellites)
    else:
        earthaccess.login(strategy="netrc")
        pairs = search_modis_pairs(
            satellites,
            (args.start, args.end),
            bbox,
            args.max_granules,
            args.product_version,
        )

    if not pairs:
        raise RuntimeError("No matching MODIS data/geolocation pairs were found.")

    if args.download_only:
        if args.local_only:
            print(f"Local MODIS pairs available: {len(pairs)}")
        else:
            downloaded_count = 0
            for satellite, key, data_granule, geo_granule in pairs:
                print(f"Fetching raw MODIS {satellite} granule pair {key}...", flush=True)
                downloaded_count += len(download_raw_pair(satellite, key, data_granule, geo_granule, args.data_dir))
            print(f"Raw MODIS granule pairs fetched: {len(pairs)}")
            print(f"Raw MODIS files downloaded or reused: {downloaded_count}")
            print(f"Raw data folder: {args.data_dir.resolve()}")
        return

    hotspot_layers = []
    for pair in pairs:
        satellite, key = pair[0], pair[1]
        print(f"Processing MODIS {satellite} granule pair {key}...", flush=True)
        try:
            if args.local_only:
                _, _, data_path, geo_path = pair
            else:
                _, _, data_granule, geo_granule = pair
                _, _, data_path, geo_path = download_pair(satellite, key, data_granule, geo_granule, args.data_dir)

            gdf = detect_hotspots_for_pair(
                satellite,
                key,
                data_path,
                geo_path,
                bbox,
                bhutan_polygon,
                args.percentile,
            )
        except UnsupportedHDF4Error as exc:
            print(str(exc), flush=True)
            continue

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

    print(f"MODIS granule pairs processed: {len(pairs)}")
    print(f"MODIS hotspots exported: {len(hotspots)}")
    print("Hotspots by satellite:")
    for satellite, count in hotspots["satellite"].value_counts().items():
        print(f"  {satellite}: {count}")
    print(f"DBSCAN clusters exported: {len(clusters)}")
    print(f"Output folder: {args.out_dir.resolve()}")


if __name__ == "__main__":
    main()
