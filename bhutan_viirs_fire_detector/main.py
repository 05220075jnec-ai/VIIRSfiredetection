"""Command-line entrypoint for the Bhutan VIIRS fire detector."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from config import PATHS, PROJECT_ROOT
from src.bhutan_boundary import filter_detections_to_bhutan
from src.building_filter import add_building_context, refine_context_with_buildings
from src.data_ingestion import VIIRSObservation, load_demo_observations, load_real_observations
from src.export_outputs import export_all
from src.fire_detection import detect_fires
from src.geospatial_inputs import (
    describe_inputs,
    find_bhutan_boundary_path,
    find_buildings_path,
    find_dem_path,
    find_lulc_path,
)
from src.lulc_filter import add_lulc_context
from src.proximity_risk import add_threat_levels
from src.sensor_fusion import fuse_detections
from src.terrain_correction import add_terrain_context
from src.utils import ensure_directory


def _context_paths(use_real_context: bool):
    dem_path = find_dem_path(PATHS.dem) if use_real_context else None
    lulc_path = find_lulc_path(PATHS.lulc) if use_real_context else None
    buildings_path = find_buildings_path(PATHS.buildings) if use_real_context else None
    boundary_path = find_bhutan_boundary_path(PATHS.vectors) if use_real_context else None
    print(describe_inputs(dem_path, lulc_path, buildings_path, boundary_path))
    return dem_path, lulc_path, buildings_path, boundary_path


def run_observations(observations: list[VIIRSObservation], use_real_context: bool = True) -> tuple[pd.DataFrame, np.ndarray]:
    """Run any list of VIIRS observations through detection and context logic."""
    dem_path, lulc_path, buildings_path, boundary_path = _context_paths(use_real_context)
    all_detections = []
    masks = []

    for obs in observations:
        fire_mask, detections = detect_fires(obs)
        masks.append(fire_mask)
        if not detections.empty:
            detections = filter_detections_to_bhutan(detections, boundary_path)
        if not detections.empty:
            detections = add_terrain_context(detections, dem_path=dem_path)
            detections = add_lulc_context(detections, lulc_path=lulc_path)
            detections = add_building_context(detections, buildings=buildings_path)
            detections = refine_context_with_buildings(detections)
            all_detections.append(detections)

    if all_detections:
        combined = pd.concat(all_detections, ignore_index=True)
        fused = fuse_detections(combined)
        fused = add_threat_levels(fused)
    else:
        fused = pd.DataFrame()

    # Demo masks have the same shape, but real swath crops can differ by
    # overpass. In that case we export the first swath mask as a representative
    # fire-mask array and keep all detections in CSV/GeoJSON.
    if not masks:
        stacked_mask = np.zeros((0, 0), dtype=np.uint8)
    elif all(mask.shape == masks[0].shape for mask in masks):
        stacked_mask = np.maximum.reduce(masks)
    else:
        stacked_mask = masks[0]
    return fused, stacked_mask


def run_demo(use_real_context: bool = True) -> tuple[pd.DataFrame, np.ndarray]:
    """Run dummy VIIRS observations through real Bhutan context layers."""
    return run_observations(load_demo_observations(), use_real_context)


def run_real(
    max_observations: int | None,
    use_real_context: bool = True,
    viirs_dir=None,
    use_fallback_raw: bool = True,
) -> tuple[pd.DataFrame, np.ndarray]:
    """Run real VIIRS observations from downloaded NetCDF files."""
    input_dir = viirs_dir or PATHS.viirs
    fallback_raw = PROJECT_ROOT.parent / "data" / "raw" if use_fallback_raw else None
    observations = load_real_observations(input_dir, fallback_raw_root=fallback_raw, max_observations=max_observations)
    if not observations:
        raise SystemExit(
            "No real VIIRS MOD pairs found. Put files in data/viirs/* or keep the earlier workspace data/raw folder."
        )
    print(f"Real VIIRS observations loaded: {len(observations)}")
    return run_observations(observations, use_real_context)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bhutan-specific VIIRS active fire detector.")
    parser.add_argument("--demo", action="store_true", help="Run with dummy VIIRS arrays.")
    parser.add_argument("--real", action="store_true", help="Run with real downloaded VIIRS NetCDF MOD pairs.")
    parser.add_argument("--max-observations", default=12, type=int, help="Limit real VIIRS granules for faster testing.")
    parser.add_argument("--viirs-dir", default=PATHS.viirs, type=str, help="Folder containing downloaded VIIRS IMG/MOD files.")
    parser.add_argument(
        "--no-fallback-raw",
        action="store_true",
        help="Only read --viirs-dir and do not scan the older workspace data/raw folder.",
    )
    parser.add_argument(
        "--synthetic-context",
        action="store_true",
        help="Ignore real DEM/LULC/building files and use synthetic context fallbacks.",
    )
    parser.add_argument("--out-dir", default=PATHS.outputs, type=str, help="Output folder.")
    args = parser.parse_args()

    if not args.demo and not args.real:
        raise SystemExit("Choose --demo or --real.")

    out_dir = ensure_directory(PATHS.outputs if args.out_dir == str(PATHS.outputs) else PATHS.outputs.parent / args.out_dir)
    if args.real:
        detections, fire_mask = run_real(
            args.max_observations,
            use_real_context=not args.synthetic_context,
            viirs_dir=PROJECT_ROOT / args.viirs_dir if not Path(args.viirs_dir).is_absolute() else Path(args.viirs_dir),
            use_fallback_raw=not args.no_fallback_raw,
        )
        run_label = "real VIIRS"
    else:
        detections, fire_mask = run_demo(use_real_context=not args.synthetic_context)
        run_label = "demo"
    outputs = export_all(detections, fire_mask, out_dir)

    print(f"Bhutan VIIRS fire detector {run_label} run complete.")
    print(f"Detections exported: {len(detections)}")
    for name, path in outputs.items():
        print(f"{name}: {path.resolve()}")


if __name__ == "__main__":
    main()
