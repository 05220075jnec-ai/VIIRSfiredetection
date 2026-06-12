"""Automated Bhutan VIIRS NRT fire detection using the true 375 m I-band detector.

This script replaces the older NRT percentile detector. Each cycle:

1. Fetches VIIRS IMG/MOD NRT granule sets from Suomi NPP, NOAA-20, and NOAA-21.
2. Runs detectors/viirs/main.py on those downloaded files.
3. Writes dashboard-ready CSV/GeoJSON outputs to outputs/viirs_nrt.
4. Optionally imports the detections into the ForestFireDashboard database.

The thermal detection logic is therefore the same as "VIIRS Detection
(3 satellites)": I04/I05 contextual testing, M13 validation, Bhutan boundary
filtering, terrain/LULC/building context, and 3-satellite fusion.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DETECTOR_ROOT = PROJECT_ROOT / "detectors" / "viirs"
FETCHER = DETECTOR_ROOT / "fetch_viirs_earthdata.py"
DETECTOR = DETECTOR_ROOT / "main.py"
GRANULE_TOKEN = re.compile(r"\.A(\d{7})\.(\d{4})\.")
CYCLE_DIRECTORY_TOKEN = re.compile(r"\d{8}T\d{6}Z")

SENSOR_NAMES = {
    "suomi_npp": "snpp",
    "snpp": "snpp",
    "noaa20": "noaa20",
    "noaa21": "noaa21",
}


def default_dashboard_root() -> Path:
    return PROJECT_ROOT / "apps" / "dashboard"


def configure_earthdata_netrc() -> None:
    """Let earthaccess find credentials in local netrc files."""
    for root in (PROJECT_ROOT, DETECTOR_ROOT):
        for name in ("netrc", ".netrc", "_netrc"):
            candidate = root / name
            if candidate.exists():
                os.environ["NETRC"] = str(candidate.resolve())
                return


def write_pipeline_status(path: Path, phase: str, message: str, **details) -> None:
    """Write an atomic heartbeat consumed by the dashboard status endpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "active" if phase != "error" else "error",
        "phase": phase,
        "message": message,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "worker_pid": os.getpid(),
        **details,
    }
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary_path.replace(path)


def run_command(
    command: list[str],
    cwd: Path,
    heartbeat=None,
    timeout_seconds: float | None = None,
) -> subprocess.CompletedProcess:
    """Run a subprocess and keep the dashboard heartbeat fresh while it works."""
    print(" ".join(str(part) for part in command), flush=True)
    stop_heartbeat = threading.Event()
    heartbeat_thread = None
    if heartbeat:
        heartbeat()

        def pulse() -> None:
            while not stop_heartbeat.wait(30):
                heartbeat()

        heartbeat_thread = threading.Thread(target=pulse, daemon=True)
        heartbeat_thread.start()

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            process.kill()
        stdout, stderr = process.communicate()
        timeout_message = f"Command timed out after {timeout_seconds:g} seconds."
        stderr = f"{stderr.rstrip()}\n{timeout_message}".strip()
        result = subprocess.CompletedProcess(command, 124, stdout, stderr)
    finally:
        stop_heartbeat.set()
        if heartbeat_thread:
            heartbeat_thread.join(timeout=2)

    if result.stdout:
        print(result.stdout.strip(), flush=True)
    if result.stderr:
        print(result.stderr.strip(), flush=True)
    return result


def normalized_sensors(value: str) -> str:
    names = []
    for raw_name in value.split(","):
        name = raw_name.strip()
        if not name:
            continue
        if name not in SENSOR_NAMES:
            raise ValueError(f"Unknown sensor {name!r}. Use suomi_npp,noaa20,noaa21.")
        names.append(SENSOR_NAMES[name])
    return ",".join(dict.fromkeys(names))


def read_processed_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        keys = set(json.loads(path.read_text(encoding="utf-8")).get("processed", []))
        return {
            "snpp:" + key.split(":", 1)[1] if key.startswith("suomi_npp:") else key
            for key in keys
        }
    except json.JSONDecodeError:
        return set()


def write_processed_keys(path: Path, keys: set[str], latest_cycle: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps({"processed": sorted(keys), "latest_cycle": latest_cycle}, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(path)


@contextlib.contextmanager
def worker_lock(lock_path: Path, pid_path: Path):
    """Prevent two automation workers from running at the same time."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = lock_path.open("a+b")
    acquired = False
    try:
        lock_handle.seek(0, os.SEEK_END)
        if lock_handle.tell() == 0:
            lock_handle.write(b"0")
            lock_handle.flush()
        lock_handle.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("Another VIIRS NRT automation worker is already running.") from exc
        else:
            import fcntl

            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("Another VIIRS NRT automation worker is already running.") from exc

        acquired = True
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
        yield
    finally:
        if acquired:
            pid_path.unlink(missing_ok=True)
            if os.name == "nt":
                import msvcrt

                lock_handle.seek(0)
                try:
                    msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        lock_handle.close()


def discover_complete_granule_sets(data_dir: Path) -> set[str]:
    """Return satellite:key names with complete IMG/MOD files in a cycle folder."""
    products_by_key: dict[str, set[str]] = {}
    satellite_by_key: dict[str, str] = {}

    for path in data_dir.rglob("*.nc"):
        match = GRANULE_TOKEN.search(path.name)
        if not match:
            continue
        key = ".".join(match.groups())
        products = products_by_key.setdefault(key, set())
        name = path.name
        if "02IMG" in name:
            products.add("02IMG")
        elif "03IMG" in name:
            products.add("03IMG")
        elif "02MOD" in name:
            products.add("02MOD")
        elif "03MOD" in name:
            products.add("03MOD")

        if name.startswith("VNP"):
            satellite_by_key[key] = "snpp"
        elif name.startswith("VJ1"):
            satellite_by_key[key] = "noaa20"
        elif name.startswith("VJ2"):
            satellite_by_key[key] = "noaa21"

    complete = set()
    required = {"02IMG", "03IMG", "02MOD", "03MOD"}
    for key, products in products_by_key.items():
        if required.issubset(products):
            complete.add(f"{satellite_by_key.get(key, 'unknown')}:{key}")
    return complete


def write_empty_outputs(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    columns = [
        "latitude",
        "longitude",
        "satellite_sources",
        "number_of_satellites_detected",
        "first_detection_time",
        "last_detection_time",
        "BT4",
        "BT5",
        "M13",
        "M13_anomaly",
        "final_confidence_score",
        "final_context_class",
        "final_threat_level",
    ]
    pd.DataFrame(columns=columns).to_csv(out_dir / "fire_detections.csv", index=False)
    (out_dir / "fire_detections.geojson").write_text(
        '{"type":"FeatureCollection","features":[]}\n',
        encoding="utf-8",
    )
    shutil.copyfile(out_dir / "fire_detections.csv", out_dir / "viirs_nrt_hotspots.csv")
    shutil.copyfile(out_dir / "fire_detections.geojson", out_dir / "viirs_nrt_hotspots.geojson")
    (out_dir / "viirs_nrt_clusters.geojson").write_text(
        '{"type":"FeatureCollection","features":[]}\n',
        encoding="utf-8",
    )


def sync_dashboard_compat_outputs(out_dir: Path) -> None:
    """Keep legacy dashboard status filenames in sync with true detector outputs."""
    fire_csv = out_dir / "fire_detections.csv"
    fire_geojson = out_dir / "fire_detections.geojson"
    if fire_csv.exists():
        shutil.copyfile(fire_csv, out_dir / "viirs_nrt_hotspots.csv")
    if fire_geojson.exists():
        shutil.copyfile(fire_geojson, out_dir / "viirs_nrt_hotspots.geojson")
    clusters = out_dir / "viirs_nrt_clusters.geojson"
    if not clusters.exists():
        clusters.write_text('{"type":"FeatureCollection","features":[]}\n', encoding="utf-8")


def import_outputs_to_dashboard(
    csv_path: Path,
    dashboard_root: Path,
    timeout_seconds: float,
    heartbeat=None,
) -> bool:
    importer = dashboard_root / "server" / "scripts" / "importCustomViirsOutput.js"
    if not importer.exists():
        print(f"Dashboard importer not found: {importer}", flush=True)
        return False

    print(f"Importing true I-band NRT detections into dashboard database: {csv_path}", flush=True)
    result = run_command(
        ["node", str(importer), str(csv_path)],
        dashboard_root / "server",
        heartbeat=heartbeat,
        timeout_seconds=timeout_seconds,
    )
    if result.returncode != 0:
        print(f"Dashboard import failed with exit code {result.returncode}.", flush=True)
        return False
    return True


def cleanup_cycle_directory(cycle_data_dir: Path, data_root: Path, keep_raw: bool) -> None:
    if keep_raw or not cycle_data_dir.exists():
        return
    resolved_cycle = cycle_data_dir.resolve()
    resolved_root = data_root.resolve()
    if resolved_cycle == resolved_root:
        raise RuntimeError("Refusing to remove the NRT data root.")
    try:
        resolved_cycle.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f"Refusing to remove raw data outside {resolved_root}.") from exc
    shutil.rmtree(resolved_cycle)
    print(f"Removed transient raw VIIRS files: {resolved_cycle}", flush=True)


def cleanup_orphaned_cycle_directories(data_root: Path, keep_raw: bool) -> None:
    """Remove timestamped NRT work folders left by a killed worker."""
    if keep_raw or not data_root.exists():
        return
    for path in data_root.iterdir():
        if path.is_dir() and CYCLE_DIRECTORY_TOKEN.fullmatch(path.name):
            cleanup_cycle_directory(path, data_root, keep_raw=False)


def cycle_window(args: argparse.Namespace) -> tuple[datetime, datetime]:
    if args.start and args.end:
        start = pd.to_datetime(args.start, utc=True).to_pydatetime()
        end = pd.to_datetime(args.end, utc=True).to_pydatetime()
    else:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=args.lookback_hours)
    if start >= end:
        raise ValueError("--start must be earlier than --end.")
    return start, end


def run_cycle(args: argparse.Namespace, processed_keys: set[str]) -> set[str]:
    start, end = cycle_window(args)
    temporal_start = start.isoformat()
    temporal_end = end.isoformat()
    cycle_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if args.start and args.end:
        cycle_data_dir = args.data_dir / f"{start:%Y%m%d}_to_{end:%Y%m%d}"
    else:
        cycle_data_dir = args.data_dir / cycle_id

    args.out_dir.mkdir(parents=True, exist_ok=True)
    cycle_data_dir.mkdir(parents=True, exist_ok=True)
    status_details = {
        "cycle_id": cycle_id,
        "window_start_utc": temporal_start,
        "window_end_utc": temporal_end,
        "data_dir": str(cycle_data_dir.resolve()),
        "output_dir": str(args.out_dir.resolve()),
    }

    def heartbeat(phase: str, message: str, **details) -> None:
        write_pipeline_status(
            args.status_file,
            phase,
            message,
            **status_details,
            **details,
        )

    print(
        f"\nNRT true I-band cycle {datetime.now().isoformat(timespec='seconds')} | "
        f"window {temporal_start} to {temporal_end}",
        flush=True,
    )

    mode = "archive" if args.archive else "nrt"
    heartbeat("fetching", "Downloading available VIIRS NRT granules from NASA Earthdata.")
    fetch_result = run_command(
        [
            sys.executable,
            str(FETCHER),
            "--mode",
            mode,
            "--start",
            temporal_start,
            "--end",
            temporal_end,
            "--sensors",
            normalized_sensors(args.sensors),
            "--max-granules",
            str(args.max_granules),
            "--out-dir",
            str(cycle_data_dir),
        ]
        + ([] if args.reprocess else ["--skip-keys-file", str(args.state_file)]),
        DETECTOR_ROOT,
        heartbeat=lambda: heartbeat(
            "fetching",
            "Downloading available VIIRS NRT granules from NASA Earthdata.",
        ),
        timeout_seconds=args.fetch_timeout_minutes * 60,
    )

    heartbeat("checking", "Checking downloaded files for complete IMG/MOD granule sets.")
    complete_sets = discover_complete_granule_sets(cycle_data_dir)
    new_sets = complete_sets - processed_keys if not args.reprocess else complete_sets

    latest_cycle = {
        "cycle_id": cycle_id,
        "start": temporal_start,
        "end": temporal_end,
        "mode": mode,
        "data_dir": str(cycle_data_dir.resolve()),
        "complete_granule_sets": len(complete_sets),
        "new_granule_sets": len(new_sets),
        "fetch_return_code": fetch_result.returncode,
    }

    if fetch_result.returncode != 0:
        print("Fetch step failed; writing empty true-I-band NRT output so old detector rows are not reused.", flush=True)
        write_empty_outputs(args.out_dir)
        write_processed_keys(args.state_file, processed_keys, latest_cycle)
        cleanup_cycle_directory(cycle_data_dir, args.data_dir, args.keep_raw)
        heartbeat("error", "VIIRS download failed or timed out.", fetch_return_code=fetch_result.returncode)
        return processed_keys

    if not new_sets:
        print("No complete new IMG/MOD granule sets found this cycle.", flush=True)
        write_empty_outputs(args.out_dir)
        write_processed_keys(args.state_file, processed_keys, latest_cycle)
        cleanup_cycle_directory(cycle_data_dir, args.data_dir, args.keep_raw)
        heartbeat("completed", "No complete new VIIRS granule sets were available.", complete_granule_sets=0)
        return processed_keys

    heartbeat(
        "detecting",
        "Running the VIIRS 375 m active-fire detector.",
        complete_granule_sets=len(complete_sets),
        new_granule_sets=len(new_sets),
    )
    detector_result = run_command(
        [
            sys.executable,
            str(DETECTOR),
            "--real",
            "--viirs-dir",
            str(cycle_data_dir),
            "--no-fallback-raw",
            "--max-observations",
            str(args.max_observations or max(args.max_granules * 3, len(new_sets))),
            "--out-dir",
            str(args.out_dir),
        ],
        DETECTOR_ROOT,
        heartbeat=lambda: heartbeat(
            "detecting",
            "Running the VIIRS 375 m active-fire detector.",
            complete_granule_sets=len(complete_sets),
            new_granule_sets=len(new_sets),
        ),
        timeout_seconds=args.detect_timeout_minutes * 60,
    )

    if detector_result.returncode != 0:
        print("Detector step failed; writing empty NRT output for dashboard status.", flush=True)
        write_empty_outputs(args.out_dir)
        cleanup_cycle_directory(cycle_data_dir, args.data_dir, args.keep_raw)
        latest_cycle["detector_return_code"] = detector_result.returncode
        write_processed_keys(args.state_file, processed_keys, latest_cycle)
        heartbeat("error", "VIIRS detection failed or timed out.", detector_return_code=detector_result.returncode)
        return processed_keys

    sync_dashboard_compat_outputs(args.out_dir)

    csv_path = args.out_dir / "fire_detections.csv"
    if not csv_path.exists():
        cleanup_cycle_directory(cycle_data_dir, args.data_dir, args.keep_raw)
        latest_cycle["detector_output_missing"] = True
        write_processed_keys(args.state_file, processed_keys, latest_cycle)
        heartbeat("error", "VIIRS detector completed without producing its CSV output.")
        return processed_keys

    row_count = 0
    try:
        row_count = max(0, len(pd.read_csv(csv_path)))
    except pd.errors.EmptyDataError:
        row_count = 0
    latest_cycle["hotspot_rows"] = row_count

    import_succeeded = True
    if args.dashboard_import:
        heartbeat("importing", "Importing detected VIIRS hotspots into PostgreSQL.", hotspot_rows=row_count)
        import_succeeded = import_outputs_to_dashboard(
            csv_path,
            args.dashboard_root,
            args.import_timeout_minutes * 60,
            heartbeat=lambda: heartbeat(
                "importing",
                "Importing detected VIIRS hotspots into PostgreSQL.",
                hotspot_rows=row_count,
            ),
        )

    if not import_succeeded:
        cleanup_cycle_directory(cycle_data_dir, args.data_dir, args.keep_raw)
        latest_cycle["database_import_succeeded"] = False
        write_processed_keys(args.state_file, processed_keys, latest_cycle)
        heartbeat("error", "Hotspot database import failed or timed out.", hotspot_rows=row_count)
        return processed_keys

    processed_keys |= new_sets
    latest_cycle["database_import_succeeded"] = import_succeeded
    write_processed_keys(args.state_file, processed_keys, latest_cycle)
    cleanup_cycle_directory(cycle_data_dir, args.data_dir, args.keep_raw)

    heartbeat(
        "completed",
        "The latest VIIRS NRT cycle completed.",
        complete_granule_sets=len(complete_sets),
        new_granule_sets=len(new_sets),
        hotspot_rows=row_count,
    )
    print(f"Complete granule sets found: {len(complete_sets)}")
    print(f"New granule sets processed: {len(new_sets)}")
    print(f"True I-band hotspots exported this cycle: {row_count}")
    print(f"Output folder: {args.out_dir.resolve()}", flush=True)
    return processed_keys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run true VIIRS 375 m I-band Bhutan fire detection every 15 minutes using NRT IMG/MOD data."
    )
    parser.add_argument("--data-dir", default=PROJECT_ROOT / "data" / "raw" / "viirs" / "nrt", type=Path)
    parser.add_argument("--out-dir", default=PROJECT_ROOT / "outputs" / "viirs_nrt", type=Path)
    parser.add_argument("--state-file", default=PROJECT_ROOT / "outputs" / "viirs_nrt" / "processed_granules.json", type=Path)
    parser.add_argument("--status-file", default=PROJECT_ROOT / "outputs" / "viirs_nrt" / "pipeline_status.json", type=Path)
    parser.add_argument("--lock-file", default=PROJECT_ROOT / "outputs" / "viirs_nrt" / "automation.lock", type=Path)
    parser.add_argument("--pid-file", default=PROJECT_ROOT / "outputs" / "viirs_nrt" / "realtime_worker.pid", type=Path)
    parser.add_argument("--dashboard-root", default=default_dashboard_root(), type=Path)
    parser.add_argument("--dashboard-import", action="store_true")
    parser.add_argument("--sensors", default="suomi_npp,noaa20,noaa21", help="Comma list: suomi_npp,noaa20,noaa21")
    parser.add_argument("--lookback-hours", default=6.0, type=float)
    parser.add_argument("--start", default=None, help="Fixed UTC start date/time, e.g. 2025-01-23 or 2025-01-23T00:00:00Z")
    parser.add_argument("--end", default=None, help="Fixed UTC end date/time, e.g. 2025-01-24 or 2025-01-24T23:59:59Z")
    parser.add_argument("--interval-minutes", default=15.0, type=float)
    parser.add_argument("--max-granules", default=80, type=int)
    parser.add_argument("--max-observations", default=None, type=int)
    parser.add_argument("--fetch-timeout-minutes", default=30.0, type=float)
    parser.add_argument("--detect-timeout-minutes", default=30.0, type=float)
    parser.add_argument("--import-timeout-minutes", default=5.0, type=float)
    parser.add_argument("--keep-raw", action="store_true", help="Keep per-cycle raw files for troubleshooting.")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--reprocess", action="store_true")
    parser.add_argument("--archive", action="store_true", help="Use archive products for fixed historical dates.")
    parser.add_argument("--percentile", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--cluster-eps", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--min-samples", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    normalized_sensors(args.sensors)
    if bool(args.start) != bool(args.end):
        raise ValueError("Use both --start and --end, or neither.")
    if not FETCHER.exists() or not DETECTOR.exists():
        raise FileNotFoundError("detectors/viirs fetcher/main.py was not found.")
    return args


def main() -> None:
    args = parse_args()
    configure_earthdata_netrc()
    with worker_lock(args.lock_file, args.pid_file):
        cleanup_orphaned_cycle_directories(args.data_dir, args.keep_raw)
        processed_keys = read_processed_keys(args.state_file)

        while True:
            try:
                processed_keys = run_cycle(args, processed_keys)
            except Exception as exc:
                write_pipeline_status(
                    args.status_file,
                    "error",
                    f"NRT cycle failed: {exc}",
                )
                print(f"NRT cycle failed: {exc}", flush=True)
                if args.once or (args.start and args.end):
                    raise
            if args.once or (args.start and args.end):
                break
            print(f"Sleeping {args.interval_minutes} minutes...", flush=True)
            sleep_deadline = time.monotonic() + args.interval_minutes * 60
            while True:
                remaining_seconds = sleep_deadline - time.monotonic()
                if remaining_seconds <= 0:
                    break
                write_pipeline_status(
                    args.status_file,
                    "sleeping",
                    f"Waiting for the next cycle in {max(1, round(remaining_seconds / 60))} minute(s).",
                )
                time.sleep(min(30, remaining_seconds))


if __name__ == "__main__":
    main()
