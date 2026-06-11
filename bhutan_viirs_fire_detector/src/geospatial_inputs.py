"""Discovery and loading helpers for real Bhutan geospatial input layers."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd

VECTOR_SUFFIXES = (".shp", ".geojson", ".gpkg")
RASTER_SUFFIXES = (".tif", ".tiff")


def first_existing_file(folder: Path, suffixes: tuple[str, ...]) -> Path | None:
    """Return the first real data file in a folder."""
    if not folder.exists():
        return None

    for path in sorted(folder.iterdir()):
        if path.name.startswith("."):
            continue
        if path.suffix.lower() in suffixes:
            return path
    return None


def find_dem_path(folder: Path) -> Path | None:
    """Find the first DEM GeoTIFF."""
    return first_existing_file(folder, RASTER_SUFFIXES)


def find_lulc_path(folder: Path) -> Path | None:
    """Find the first LULC vector file."""
    return first_existing_file(folder, VECTOR_SUFFIXES)


def find_buildings_path(folder: Path) -> Path | None:
    """Find the first building footprint vector file."""
    return first_existing_file(folder, VECTOR_SUFFIXES)


def find_bhutan_boundary_path(folder: Path) -> Path | None:
    """Find a Bhutan boundary layer.

    The project can use either a boundary copied into data/vectors or the
    boundary file that was already used by the earlier VIIRS/dashboard work.
    The polygon boundary is stricter than the broad satellite search bbox and
    prevents nearby India/Sikkim/Arunachal swath pixels from being exported.
    """
    preferred_names = (
        "bhutan-boundary.geojson",
        "bhutan_dzong_web.geojson",
        "internationalboundary.shp",
        "dzongkhag.shp",
    )
    project_root = folder.parent.parent
    workspace_root = project_root.parent
    search_roots = [
        folder,
        project_root / "data" / "boundaries",
        workspace_root / "data" / "boundaries",
        workspace_root / "ForestFireDashboard-main" / "client" / "public" / "data",
        workspace_root / "ForestFireDashboard-main" / "server" / "Administrative Boundaries",
    ]

    for root in search_roots:
        if not root.exists():
            continue
        files = [path for path in root.iterdir() if path.suffix.lower() in VECTOR_SUFFIXES]
        for name in preferred_names:
            for path in files:
                if path.name.lower() == name:
                    return path
        for path in sorted(files):
            lower_name = path.name.lower()
            if "bhutan" in lower_name or "boundary" in lower_name:
                return path
    return None


def load_vector(path: Path) -> gpd.GeoDataFrame:
    """Load a vector layer and drop rows without geometry."""
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        raise ValueError(f"{path} has no CRS. Define its CRS before using it.")
    return gdf[gdf.geometry.notna()].copy()


def describe_inputs(
    dem_path: Path | None,
    lulc_path: Path | None,
    buildings_path: Path | None,
    boundary_path: Path | None,
) -> str:
    """Return a short human-readable summary of the context layers in use."""
    return "\n".join(
        [
            f"DEM: {dem_path if dem_path else 'not found, synthetic terrain fallback'}",
            f"LULC: {lulc_path if lulc_path else 'not found, synthetic LULC fallback'}",
            f"Buildings: {buildings_path if buildings_path else 'not found, demo building fallback'}",
            f"Bhutan boundary: {boundary_path if boundary_path else 'not found, bbox-only fallback'}",
        ]
    )
