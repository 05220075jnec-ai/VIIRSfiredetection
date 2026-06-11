"""Command-line entrypoint for the Bhutan MODIS HDF active-fire detector."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from config import PATHS
from src.context import add_lulc_context, filter_to_bhutan
from src.data_ingestion import discover_hdf_pairs, load_hdf_observation
from src.export_outputs import export_all
from src.fire_detection import detect_fires


def run_detector(
    data_dir: Path,
    boundary_path: Path,
    lulc_path: Path | None,
    max_observations: int | None,
) -> tuple[pd.DataFrame, np.ndarray]:
    pairs = discover_hdf_pairs(data_dir)
    if max_observations is not None:
        pairs = pairs[:max_observations]
    if not pairs:
        raise SystemExit(f"No matching MOD021KM/MOD03 or MYD021KM/MYD03 HDF pairs found in {data_dir}.")

    detections = []
    masks = []
    for pair in pairs:
        print(f"Processing MODIS {pair.satellite} {pair.granule_key}", flush=True)
        observation = load_hdf_observation(pair)
        fire_mask, granule_detections = detect_fires(observation)
        masks.append(fire_mask)
        if not granule_detections.empty:
            detections.append(granule_detections)

    combined = pd.concat(detections, ignore_index=True) if detections else pd.DataFrame()
    if not combined.empty:
        combined = filter_to_bhutan(combined, boundary_path)
        combined = add_lulc_context(combined, lulc_path)

    if not masks:
        representative_mask = np.zeros((0, 0), dtype=np.uint8)
    elif all(mask.shape == masks[0].shape for mask in masks):
        representative_mask = np.maximum.reduce(masks)
    else:
        representative_mask = masks[0]

    return combined, representative_mask


def main() -> None:
    parser = argparse.ArgumentParser(description="Bhutan MODIS Terra/Aqua HDF active-fire detector.")
    parser.add_argument("--data-dir", default=PATHS.data, type=Path)
    parser.add_argument("--out-dir", default=PATHS.outputs, type=Path)
    parser.add_argument("--boundary", default=PATHS.boundary, type=Path)
    parser.add_argument("--lulc", default=PATHS.lulc, type=Path)
    parser.add_argument("--max-observations", default=None, type=int)
    args = parser.parse_args()

    lulc_path = args.lulc if args.lulc.exists() else None
    detections, fire_mask = run_detector(
        args.data_dir,
        args.boundary,
        lulc_path,
        args.max_observations,
    )
    outputs = export_all(detections, fire_mask, args.out_dir)

    print(f"MODIS HDF observations processed: {len(discover_hdf_pairs(args.data_dir)[: args.max_observations])}")
    print(f"Bhutan hotspots exported: {len(detections)}")
    for name, path in outputs.items():
        print(f"{name}: {path.resolve()}")


if __name__ == "__main__":
    main()
