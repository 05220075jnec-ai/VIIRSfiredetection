from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from config import Config
from src.data_ingestion import load_viirs_observations
from src.mapping import write_outputs
from src.preprocessing import prepare_observations
from src.proximity_risk import apply_proximity_risk
from src.seasonal_threshold import apply_seasonal_thresholds
from src.sensor_fusion import apply_sensor_fusion
from src.terrain_correction import apply_terrain_correction
from src.thermal_anomaly import detect_thermal_anomalies


def run_pipeline(config: Config, use_dummy: bool = False) -> Path:
    config.ensure_directories()

    observations = load_viirs_observations(config, use_dummy=use_dummy)
    observations = prepare_observations(observations, config.bounds)
    observations = apply_seasonal_thresholds(observations, config)
    observations = apply_terrain_correction(observations, config)
    detections = detect_thermal_anomalies(observations, config.thresholds)
    detections = apply_sensor_fusion(detections, config.thresholds)
    detections = apply_proximity_risk(detections, config)
    write_outputs(detections, config.paths.outputs)

    return config.paths.outputs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bhutan-specific VIIRS wildfire hotspot detector."
    )
    parser.add_argument(
        "--dummy",
        action="store_true",
        help="Run with generated sample VIIRS-like observations.",
    )
    parser.add_argument(
        "--viirs-dir",
        type=Path,
        default=None,
        help="Directory containing VIIRS CSV/NetCDF files. Supports VNP02MOD/VNP03MOD raw pairs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for CSV, GeoJSON, dashboard JSON, and map.",
    )
    parser.add_argument("--k1", type=float, default=None, help="Override I4 contextual sigma.")
    parser.add_argument("--k2", type=float, default=None, help="Override M13 contextual sigma.")
    parser.add_argument(
        "--brightness-threshold",
        type=float,
        default=None,
        help="Override absolute thermal threshold.",
    )
    args = parser.parse_args()

    config = Config()
    if args.k1 is not None or args.k2 is not None or args.brightness_threshold is not None:
        config = replace(
            config,
            thresholds=replace(
                config.thresholds,
                k1_i4=args.k1 if args.k1 is not None else config.thresholds.k1_i4,
                k2_m13=args.k2 if args.k2 is not None else config.thresholds.k2_m13,
                brightness_temp=(
                    args.brightness_threshold
                    if args.brightness_threshold is not None
                    else config.thresholds.brightness_temp
                ),
            ),
        )
    if args.viirs_dir is not None or args.output_dir is not None:
        paths = replace(
            config.paths,
            viirs=(args.viirs_dir.resolve() if args.viirs_dir else config.paths.viirs),
            outputs=(args.output_dir.resolve() if args.output_dir else config.paths.outputs),
        )
        config = replace(config, paths=paths)

    output_dir = run_pipeline(config, use_dummy=args.dummy)
    print(f"Finished. Outputs written to: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
