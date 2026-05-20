from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import earthaccess
import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from shapely import contains_xy
from sklearn.cluster import DBSCAN


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# VIIRS filenames contain a timestamp like:
# VNP02MOD.A2023100.0648.002....
# This regex extracts AYYYYDDD and HHMM so we can pair VNP02MOD with VNP03MOD.
GRANULE_TOKEN = re.compile(r"\.A(\d{7})\.(\d{4})\.")


def granule_key(text: str) -> str:
    # Convert a filename or URL into a comparable timestamp key.
    match = GRANULE_TOKEN.search(text)
    if not match:
        raise ValueError(f"Could not find AYYYYDDD.HHMM token in {text}")
    return ".".join(match.groups())


def granule_key_from_result(granule) -> str:
    # CMR/LAADS sometimes returns only an ID like LAADS:7504476952 in GranuleUR.
    # The real filename is usually in the data download link, so we check both
    # metadata fields and download links.
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


def load_bhutan_boundary(
    boundary_path: Path,
    district: str | None,
) -> tuple[gpd.GeoDataFrame, object, tuple[float, float, float, float]]:
    # Read the Bhutan dzongkhag boundary file. NASA search still needs a bbox,
    # but detection uses the exact dissolved country polygon.
    boundary = gpd.read_file(boundary_path)
    if boundary.crs is None:
        boundary = boundary.set_crs("EPSG:4326")
    else:
        boundary = boundary.to_crs("EPSG:4326")

    clip_boundary = boundary
    if district:
        if "Dzongkhag" not in boundary.columns:
            raise RuntimeError("Boundary file does not contain a Dzongkhag column.")

        district_aliases = {
            "mongar": "monggar",
        }
        district_key = district_aliases.get(district.casefold(), district.casefold())
        clip_boundary = boundary[boundary["Dzongkhag"].str.casefold() == district_key]
        if clip_boundary.empty:
            raise RuntimeError(f"No dzongkhag named {district!r} was found in the boundary file.")

    clip_polygon = clip_boundary.geometry.union_all()
    search_bbox = tuple(boundary.total_bounds)  # lon_min, lat_min, lon_max, lat_max
    clip_bbox = tuple(clip_boundary.total_bounds)
    return boundary, clip_polygon, search_bbox if district is None else clip_bbox


def search_viirs_pairs(
    temporal: tuple[str, str],
    bbox: tuple[float, float, float, float],
    max_granules: int,
):
    # Search NASA Earthdata for both the calibrated radiance file (VNP02MOD)
    # and the matching geolocation file (VNP03MOD).
    searches = {}
    for short_name in ("VNP02MOD", "VNP03MOD"):
        granules = earthaccess.search_data(
            short_name=short_name,
            bounding_box=bbox,
            temporal=temporal,
            count=max_granules,
        )
        searches[short_name] = {granule_key_from_result(g): g for g in granules}

    # Keep every timestamp that exists in both products. This is important for
    # an 8-16 April event because the first pass is not necessarily over Mongar.
    common_keys = sorted(set(searches["VNP02MOD"]) & set(searches["VNP03MOD"]))
    if not common_keys:
        raise RuntimeError(
            "No matching VNP02MOD/VNP03MOD pair found for this date range and boundary bbox. "
            f"Found {len(searches['VNP02MOD'])} VNP02MOD keys and "
            f"{len(searches['VNP03MOD'])} VNP03MOD keys."
        )

    return [(key, searches["VNP02MOD"][key], searches["VNP03MOD"][key]) for key in common_keys]


def download_pair(key: str, vnp02, vnp03, data_dir: Path) -> tuple[str, Path, Path]:
    # Download one matched pair into a local data folder.
    # earthaccess reuses existing files when possible.
    data_dir.mkdir(parents=True, exist_ok=True)
    paths = earthaccess.download([vnp02, vnp03], local_path=str(data_dir), threads=2)

    # Return the paths in a stable order, regardless of download order.
    by_name = {Path(path).name: Path(path) for path in paths}
    vnp02_path = next(path for name, path in by_name.items() if name.startswith("VNP02MOD"))
    vnp03_path = next(path for name, path in by_name.items() if name.startswith("VNP03MOD"))
    return key, vnp02_path, vnp03_path


def local_pairs(data_dir: Path) -> list[tuple[str, Path, Path]]:
    # Reuse already downloaded files. This is useful after a long download run
    # times out before the processing/export step completes.
    vnp02 = {granule_key(path.name): path for path in data_dir.glob("VNP02MOD*.nc")}
    vnp03 = {granule_key(path.name): path for path in data_dir.glob("VNP03MOD*.nc")}
    common_keys = sorted(set(vnp02) & set(vnp03))
    return [(key, vnp02[key], vnp03[key]) for key in common_keys]


def detect_hotspots_for_pair(
    key: str,
    vnp02_path: Path,
    vnp03_path: Path,
    bbox: tuple[float, float, float, float],
    bhutan_polygon,
    percentile: float,
) -> gpd.GeoDataFrame:
    # Open the two VIIRS NetCDF groups used by the notebook:
    # VNP02MOD has M13 radiance, and VNP03MOD has latitude/longitude.
    obs = xr.open_dataset(vnp02_path, group="/observation_data")
    geo = xr.open_dataset(vnp03_path, group="/geolocation_data")

    # Pull the arrays into NumPy for simple thresholding.
    m13 = obs.M13.values.astype("float64")
    lat = geo.latitude.values.astype("float64")
    lon = geo.longitude.values.astype("float64")

    # First apply a cheap rectangular boundary filter, then the exact Bhutan
    # polygon from bhutan_dzong_web.geojson. This removes points falling in India.
    lon_min, lat_min, lon_max, lat_max = bbox
    valid = (
        np.isfinite(m13)
        & np.isfinite(lat)
        & np.isfinite(lon)
        & (m13 > 0)
        & (m13 < 100)
        & (lon >= lon_min)
        & (lon <= lon_max)
        & (lat >= lat_min)
        & (lat <= lat_max)
    )

    if not valid.any():
        return gpd.GeoDataFrame(geometry=gpd.GeoSeries([], crs="EPSG:4326"), crs="EPSG:4326")

    inside_bhutan = np.zeros(m13.shape, dtype=bool)
    inside_bhutan[valid] = contains_xy(bhutan_polygon, lon[valid], lat[valid])
    valid &= inside_bhutan

    if not valid.any():
        return gpd.GeoDataFrame(geometry=gpd.GeoSeries([], crs="EPSG:4326"), crs="EPSG:4326")

    # Match the notebook's core idea:
    # transform M13 to log scale and detect the bright/hot tail with a threshold.
    log_m13 = np.full(m13.shape, np.nan, dtype="float64")
    log_m13[valid] = np.log(m13[valid])
    threshold = np.nanpercentile(log_m13[valid], percentile)
    hot = valid & (log_m13 >= threshold)

    if not hot.any():
        return gpd.GeoDataFrame(geometry=gpd.GeoSeries([], crs="EPSG:4326"), crs="EPSG:4326")

    # Convert hotspot pixels into a QGIS-ready point dataset.
    df = pd.DataFrame(
        {
            "longitude": lon[hot],
            "latitude": lat[hot],
            "M13_log": log_m13[hot],
            "threshold": threshold,
            "granule_key": key,
            "source_vnp02": vnp02_path.name,
            "source_vnp03": vnp03_path.name,
        }
    )

    return gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df.longitude, df.latitude),
        crs="EPSG:4326",
    )


def add_dzongkhag_names(hotspots: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    # Attach dzongkhag names to each point so Mongar detections are easy to find.
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
    # Reproduce the notebook's vector cluster step:
    # group DBSCAN-labeled hotspot points and create one convex hull per cluster.
    cluster_rows = []
    for cluster_id in sorted(hotspots["cluster"].unique()):
        if cluster_id == -1:
            continue

        cluster_points = hotspots[hotspots["cluster"] == cluster_id]
        hull = cluster_points.geometry.union_all().convex_hull

        # Shapefiles are happier with one geometry type. Clusters with too few
        # or non-spread points can become Point or LineString, so keep polygons.
        if hull.geom_type != "Polygon":
            continue

        dzongkhags = ""
        if "Dzongkhag" in cluster_points:
            dzongkhags = ",".join(sorted(cluster_points["Dzongkhag"].dropna().unique()))

        cluster_rows.append(
            {
                "cluster": int(cluster_id),
                "points": int(len(cluster_points)),
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
            {"cluster": [], "points": [], "dzongkhag": []},
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
    # Create the output folder before writing CSV, GeoJSON, or shapefiles.
    out_dir.mkdir(parents=True, exist_ok=True)

    if hotspots.empty:
        raise RuntimeError("No hotspot pixels were found inside the Bhutan boundary.")

    # Add dzongkhag names, then cluster all hotspot points from all granules.
    hotspots = add_dzongkhag_names(hotspots, boundary)
    coords = hotspots[["longitude", "latitude"]].to_numpy()
    hotspots["cluster"] = DBSCAN(eps=cluster_eps, min_samples=min_samples).fit_predict(coords)

    # Write point outputs for inspection in QGIS or Excel.
    hotspots.to_csv(out_dir / "bhutan_fire_hotspots.csv", index=False)
    hotspots.to_file(out_dir / "bhutan_fire_hotspots.geojson", driver="GeoJSON")
    hotspots.to_file(out_dir / "bhutan_fire_hotspots.shp", driver="ESRI Shapefile")

    # Write one polygon hull per DBSCAN cluster, similar to the notebook.
    clusters = build_cluster_polygons(hotspots, out_dir)
    return hotspots, clusters


def main() -> None:
    # Command-line settings let you run this workflow from VS Code/PowerShell
    # without opening the notebook.
    parser = argparse.ArgumentParser(
        description="Download VIIRS VNP02MOD/VNP03MOD over Bhutan and export demo hotspots."
    )
    parser.add_argument("--start", required=True, help="Start date/time, e.g. 2023-04-08")
    parser.add_argument("--end", required=True, help="End date/time, e.g. 2023-04-17")
    parser.add_argument(
        "--boundary",
        default=PROJECT_ROOT / "data" / "boundaries" / "bhutan_dzong_web.geojson",
        type=Path,
    )
    parser.add_argument("--district", default=None)
    parser.add_argument("--data-dir", default=PROJECT_ROOT / "data" / "raw", type=Path)
    parser.add_argument("--out-dir", default=PROJECT_ROOT / "outputs" / "bhutan", type=Path)
    parser.add_argument("--percentile", default=99.9, type=float)
    parser.add_argument("--cluster-eps", default=0.5, type=float)
    parser.add_argument("--min-samples", default=4, type=int)
    parser.add_argument("--max-granules", default=200, type=int)
    parser.add_argument("--local-only", action="store_true")
    args = parser.parse_args()

    # Use the project-local .netrc if present.
    # This lets Earthdata authentication work from this folder in VS Code.
    local_netrc = PROJECT_ROOT / ".netrc"
    if local_netrc.exists():
        os.environ.setdefault("NETRC", str(local_netrc.resolve()))

    # Read the exact Bhutan boundary. If --district is supplied, clipping uses
    # that dzongkhag polygon while NASA search still uses the boundary bbox.
    boundary, clip_polygon, bbox = load_bhutan_boundary(args.boundary, args.district)

    # Find all matching VIIRS passes for the event window, or reuse local files.
    if args.local_only:
        pairs = local_pairs(args.data_dir)
    else:
        # Authenticate against NASA Earthdata Login using .netrc credentials.
        earthaccess.login(strategy="netrc")
        search_boundary, _, search_bbox = load_bhutan_boundary(args.boundary, None)
        pairs = search_viirs_pairs((args.start, args.end), search_bbox, args.max_granules)

    hotspot_layers = []
    for pair in pairs:
        print(f"Processing granule pair {pair[0]}...", flush=True)
        if args.local_only:
            key, vnp02_path, vnp03_path = pair
        else:
            key, vnp02, vnp03 = pair
            key, vnp02_path, vnp03_path = download_pair(key, vnp02, vnp03, args.data_dir)
        gdf = detect_hotspots_for_pair(
            key,
            vnp02_path,
            vnp03_path,
            bbox,
            clip_polygon,
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
        all_hotspots = gpd.GeoDataFrame(geometry=gpd.GeoSeries([], crs="EPSG:4326"), crs="EPSG:4326")

    hotspots, clusters = export_outputs(
        all_hotspots,
        boundary,
        args.out_dir,
        args.cluster_eps,
        args.min_samples,
    )

    # Print a short run summary for the terminal.
    mongar_count = 0
    if "Dzongkhag" in hotspots:
        mongar_count = int(hotspots["Dzongkhag"].isin(["Mongar", "Monggar"]).sum())
    print(f"Granule pairs processed: {len(pairs)}")
    print(f"Hotspots exported: {len(hotspots)}")
    print(f"Mongar hotspot points: {mongar_count}")
    print(f"DBSCAN clusters exported: {len(clusters)}")
    print(f"Output folder: {args.out_dir.resolve()}")


if __name__ == "__main__":
    main()
