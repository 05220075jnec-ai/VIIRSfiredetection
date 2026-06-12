"""Automate Bhutan MODIS Terra/Aqua NRT HDF detection every 15 minutes."""

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
DETECTOR_ROOT = PROJECT_ROOT / "detectors" / "modis"
FETCHER = DETECTOR_ROOT / "fetch_modis_earthdata.py"
DETECTOR = DETECTOR_ROOT / "main.py"
GRANULE_TOKEN = re.compile(r"\.A(\d{7})\.(\d{4})\.")
CYCLE_DIRECTORY_TOKEN = re.compile(r"\d{8}T\d{6}Z")

OUTPUT_COLUMNS = [
    "sensor",
    "satellite",
    "satellite_sources",
    "number_of_satellites_detected",
    "instrument",
    "granule_id",
    "acquisition_time",
    "first_detection_time",
    "last_detection_time",
    "acq_date",
    "acq_time",
    "latitude",
    "longitude",
    "day_night",
    "confidence",
    "final_confidence_score",
    "fire_mask_class",
    "fire_type",
    "final_context_class",
    "lulc_class",
    "lulc_source_class",
    "T4",
    "T11",
    "T12",
    "T4_minus_T11",
    "T4_source_band",
    "absolute_test_passed",
    "contextual_test_passed",
    "background_mean_T4",
    "background_mean_T11",
    "background_mean_delta",
    "background_MAD_T4",
    "background_MAD_delta",
    "background_window",
    "background_pixels",
    "adjacent_cloud_pixels",
    "adjacent_water_pixels",
    "glint_risk",
    "source_data",
    "source_geo",
    "cloud_mask_method",
    "algorithm_version",
]


def default_dashboard_root() -> Path:
    return PROJECT_ROOT / "apps" / "dashboard"


def configure_earthdata_netrc() -> None:
    for root in (PROJECT_ROOT, DETECTOR_ROOT):
        for name in ("netrc", ".netrc", "_netrc"):
            candidate = root / name
            if candidate.exists():
                os.environ["NETRC"] = str(candidate.resolve())
                return


def write_pipeline_status(path: Path, phase: str, message: str, **details) -> None:
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


def read_processed_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    return {str(value).lower() for value in payload.get("processed", [])}


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
                raise RuntimeError("Another MODIS NRT automation worker is already running.") from exc
        else:
            import fcntl

            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("Another MODIS NRT automation worker is already running.") from exc

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
    product_paths: dict[tuple[str, str], set[str]] = {}

    for path in data_dir.rglob("*.hdf"):
        match = GRANULE_TOKEN.search(path.name)
        if not match:
            continue
        key = ".".join(match.groups())
        if path.name.startswith("MOD021KM"):
            products = product_paths.setdefault(("terra", key), set())
            products.add("data")
        elif path.name.startswith("MOD03"):
            products = product_paths.setdefault(("terra", key), set())
            products.add("geo")
        elif path.name.startswith("MYD021KM"):
            products = product_paths.setdefault(("aqua", key), set())
            products.add("data")
        elif path.name.startswith("MYD03"):
            products = product_paths.setdefault(("aqua", key), set())
            products.add("geo")

    return {
        f"{satellite}:{key}"
        for (satellite, key), products in product_paths.items()
        if products == {"data", "geo"}
    }


def write_empty_outputs(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_dir / "modis_hotspot.csv", index=False)
    (out_dir / "modis_hotspot.geojson").write_text(
        '{"type":"FeatureCollection","features":[]}\n',
        encoding="utf-8",
    )
    for name in (
        "fire_mask.npy",
        "modis_hotspot.shp",
        "modis_hotspot.shx",
        "modis_hotspot.dbf",
        "modis_hotspot.prj",
        "modis_hotspot.cpg",
    ):
        (out_dir / name).unlink(missing_ok=True)


def import_outputs_to_dashboard(
    csv_path: Path,
    dashboard_root: Path,
    timeout_seconds: float,
    heartbeat=None,
) -> bool:
    importer = dashboard_root / "server" / "scripts" / "importModisHotspots.js"
    if not importer.exists():
        print(f"MODIS dashboard importer not found: {importer}", flush=True)
        return False

    result = run_command(
        ["node", str(importer), str(csv_path)],
        dashboard_root / "server",
        heartbeat=heartbeat,
        timeout_seconds=timeout_seconds,
    )
    if result.returncode != 0:
        print(f"MODIS dashboard import failed with exit code {result.returncode}.", flush=True)
        return False
    return True


def validated_cycle_path(cycle_data_dir: Path, data_root: Path) -> tuple[Path, Path]:
    resolved_cycle = cycle_data_dir.resolve()
    resolved_root = data_root.resolve()
    if resolved_cycle == resolved_root:
        raise RuntimeError("Refusing to remove the MODIS NRT data root.")
    try:
        resolved_cycle.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f"Refusing to remove raw data outside {resolved_root}.") from exc
    return resolved_cycle, resolved_root


def satellite_files(cycle_data_dir: Path) -> list[Path]:
    return [
        path
        for path in cycle_data_dir.rglob("*")
        if path.is_file() and path.suffix.lower() == ".hdf"
    ]


def retain_cycle_directory(
    cycle_data_dir: Path,
    data_root: Path,
    keep_raw: bool,
    retention_hours: float,
) -> None:
    if not cycle_data_dir.exists():
        return
    resolved_cycle, _ = validated_cycle_path(cycle_data_dir, data_root)
    if not satellite_files(resolved_cycle):
        shutil.rmtree(resolved_cycle)
        print(f"Removed empty MODIS cycle folder: {resolved_cycle}", flush=True)
        return
    if keep_raw:
        print(f"Keeping raw MODIS files indefinitely: {resolved_cycle}", flush=True)
        return

    delete_after = datetime.now(timezone.utc) + timedelta(hours=retention_hours)
    marker_path = resolved_cycle / ".retention.json"
    marker_path.write_text(
        json.dumps({"delete_after_utc": delete_after.isoformat()}, indent=2),
        encoding="utf-8",
    )
    print(
        f"Keeping raw MODIS files until {delete_after.isoformat()}: {resolved_cycle}",
        flush=True,
    )


def cleanup_expired_cycle_directories(
    data_root: Path,
    keep_raw: bool,
    retention_hours: float,
) -> None:
    if keep_raw or not data_root.exists():
        return
    now = datetime.now(timezone.utc)
    for path in data_root.iterdir():
        marker_path = path / ".retention.json"
        is_timestamped_cycle = bool(CYCLE_DIRECTORY_TOKEN.fullmatch(path.name))
        if not path.is_dir() or (not is_timestamped_cycle and not marker_path.exists()):
            continue
        resolved_cycle, _ = validated_cycle_path(path, data_root)
        if not satellite_files(resolved_cycle):
            shutil.rmtree(resolved_cycle)
            print(f"Removed empty MODIS cycle folder: {resolved_cycle}", flush=True)
            continue

        delete_after = None
        if marker_path.exists():
            try:
                payload = json.loads(marker_path.read_text(encoding="utf-8"))
                delete_after = pd.to_datetime(
                    payload.get("delete_after_utc"),
                    utc=True,
                ).to_pydatetime()
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                delete_after = None
        if delete_after is None:
            if not is_timestamped_cycle:
                continue
            cycle_time = datetime.strptime(path.name, "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc
            )
            delete_after = cycle_time + timedelta(hours=retention_hours)

        if now >= delete_after:
            shutil.rmtree(resolved_cycle)
            print(f"Removed expired raw MODIS files: {resolved_cycle}", flush=True)


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
        f"\nMODIS NRT cycle {datetime.now().isoformat(timespec='seconds')} | "
        f"window {temporal_start} to {temporal_end}",
        flush=True,
    )

    mode = "archive" if args.archive else "nrt"
    fetch_command = [
        sys.executable,
        str(FETCHER),
        "--mode",
        mode,
        "--start",
        temporal_start,
        "--end",
        temporal_end,
        "--sensors",
        args.sensors,
        "--max-granules",
        str(args.max_granules),
        "--out-dir",
        str(cycle_data_dir),
    ]
    if not args.reprocess:
        fetch_command.extend(["--skip-keys-file", str(args.state_file)])

    heartbeat("fetching", "Downloading available MODIS Terra/Aqua NRT HDF granules.")
    fetch_result = run_command(
        fetch_command,
        DETECTOR_ROOT,
        heartbeat=lambda: heartbeat(
            "fetching",
            "Downloading available MODIS Terra/Aqua NRT HDF granules.",
        ),
        timeout_seconds=args.fetch_timeout_minutes * 60,
    )

    heartbeat("checking", "Checking downloaded MODIS files for complete data/geolocation pairs.")
    complete_sets = discover_complete_granule_sets(cycle_data_dir)
    new_sets = complete_sets if args.reprocess else complete_sets - processed_keys
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
        write_empty_outputs(args.out_dir)
        write_processed_keys(args.state_file, processed_keys, latest_cycle)
        retain_cycle_directory(
            cycle_data_dir,
            args.data_dir,
            args.keep_raw,
            args.raw_retention_hours,
        )
        heartbeat("error", "MODIS download failed or timed out.", fetch_return_code=fetch_result.returncode)
        return processed_keys

    if not new_sets:
        print("No complete new MODIS HDF pairs were available.", flush=True)
        write_empty_outputs(args.out_dir)
        write_processed_keys(args.state_file, processed_keys, latest_cycle)
        retain_cycle_directory(
            cycle_data_dir,
            args.data_dir,
            args.keep_raw,
            args.raw_retention_hours,
        )
        heartbeat("completed", "No complete new MODIS granules were available.", hotspot_rows=0)
        return processed_keys

    heartbeat(
        "detecting",
        "Running the MODIS contextual active-fire detector.",
        complete_granule_sets=len(complete_sets),
        new_granule_sets=len(new_sets),
    )
    detector_result = run_command(
        [
            sys.executable,
            str(DETECTOR),
            "--data-dir",
            str(cycle_data_dir),
            "--out-dir",
            str(args.out_dir),
            "--max-observations",
            str(len(new_sets)),
        ],
        DETECTOR_ROOT,
        heartbeat=lambda: heartbeat(
            "detecting",
            "Running the MODIS contextual active-fire detector.",
            new_granule_sets=len(new_sets),
        ),
        timeout_seconds=args.detect_timeout_minutes * 60,
    )

    if detector_result.returncode != 0:
        write_empty_outputs(args.out_dir)
        latest_cycle["detector_return_code"] = detector_result.returncode
        write_processed_keys(args.state_file, processed_keys, latest_cycle)
        retain_cycle_directory(
            cycle_data_dir,
            args.data_dir,
            args.keep_raw,
            args.raw_retention_hours,
        )
        heartbeat("error", "MODIS detection failed or timed out.", detector_return_code=detector_result.returncode)
        return processed_keys

    csv_path = args.out_dir / "modis_hotspot.csv"
    if not csv_path.exists():
        latest_cycle["detector_output_missing"] = True
        write_processed_keys(args.state_file, processed_keys, latest_cycle)
        retain_cycle_directory(
            cycle_data_dir,
            args.data_dir,
            args.keep_raw,
            args.raw_retention_hours,
        )
        heartbeat("error", "MODIS detector completed without producing its CSV output.")
        return processed_keys

    try:
        row_count = len(pd.read_csv(csv_path))
    except pd.errors.EmptyDataError:
        row_count = 0
    latest_cycle["hotspot_rows"] = row_count

    import_succeeded = True
    if args.dashboard_import:
        heartbeat("importing", "Importing detected MODIS hotspots into PostgreSQL.", hotspot_rows=row_count)
        import_succeeded = import_outputs_to_dashboard(
            csv_path,
            args.dashboard_root,
            args.import_timeout_minutes * 60,
            heartbeat=lambda: heartbeat(
                "importing",
                "Importing detected MODIS hotspots into PostgreSQL.",
                hotspot_rows=row_count,
            ),
        )

    if not import_succeeded:
        latest_cycle["database_import_succeeded"] = False
        write_processed_keys(args.state_file, processed_keys, latest_cycle)
        retain_cycle_directory(
            cycle_data_dir,
            args.data_dir,
            args.keep_raw,
            args.raw_retention_hours,
        )
        heartbeat("error", "MODIS hotspot database import failed or timed out.", hotspot_rows=row_count)
        return processed_keys

    processed_keys |= new_sets
    latest_cycle["database_import_succeeded"] = import_succeeded
    write_processed_keys(args.state_file, processed_keys, latest_cycle)
    retain_cycle_directory(
        cycle_data_dir,
        args.data_dir,
        args.keep_raw,
        args.raw_retention_hours,
    )
    heartbeat(
        "completed",
        "The latest MODIS NRT cycle completed.",
        complete_granule_sets=len(complete_sets),
        new_granule_sets=len(new_sets),
        hotspot_rows=row_count,
    )
    print(f"Complete MODIS granule pairs found: {len(complete_sets)}")
    print(f"New MODIS granule pairs processed: {len(new_sets)}")
    print(f"MODIS hotspots exported this cycle: {row_count}")
    print(f"Output folder: {args.out_dir.resolve()}", flush=True)
    return processed_keys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Bhutan MODIS Terra/Aqua contextual detection every 15 minutes."
    )
    parser.add_argument(
        "--data-dir",
        default=PROJECT_ROOT / "data" / "raw" / "modis" / "nrt",
        type=Path,
    )
    parser.add_argument(
        "--out-dir",
        default=PROJECT_ROOT / "outputs" / "modis_nrt",
        type=Path,
    )
    parser.add_argument(
        "--state-file",
        default=PROJECT_ROOT / "outputs" / "modis_nrt" / "processed_granules.json",
        type=Path,
    )
    parser.add_argument(
        "--status-file",
        default=PROJECT_ROOT / "outputs" / "modis_nrt" / "pipeline_status.json",
        type=Path,
    )
    parser.add_argument(
        "--lock-file",
        default=PROJECT_ROOT / "outputs" / "modis_nrt" / "automation.lock",
        type=Path,
    )
    parser.add_argument(
        "--pid-file",
        default=PROJECT_ROOT / "outputs" / "modis_nrt" / "realtime_worker.pid",
        type=Path,
    )
    parser.add_argument("--dashboard-root", default=default_dashboard_root(), type=Path)
    parser.add_argument("--dashboard-import", action="store_true")
    parser.add_argument("--sensors", default="terra,aqua", help="Comma list: terra,aqua")
    parser.add_argument("--lookback-hours", default=24.0, type=float)
    parser.add_argument("--start", default=None, help="Fixed UTC start date/time.")
    parser.add_argument("--end", default=None, help="Fixed UTC end date/time.")
    parser.add_argument("--interval-minutes", default=15.0, type=float)
    parser.add_argument("--max-granules", default=80, type=int)
    parser.add_argument("--fetch-timeout-minutes", default=30.0, type=float)
    parser.add_argument("--detect-timeout-minutes", default=30.0, type=float)
    parser.add_argument("--import-timeout-minutes", default=5.0, type=float)
    parser.add_argument(
        "--raw-retention-hours",
        default=24.0,
        type=float,
        help="Keep downloaded raw cycle files for this many hours.",
    )
    parser.add_argument("--keep-raw", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--reprocess", action="store_true")
    parser.add_argument("--archive", action="store_true")
    args = parser.parse_args()

    selected = [name.strip().lower() for name in args.sensors.split(",") if name.strip()]
    if not selected or any(name not in {"terra", "aqua"} for name in selected):
        raise ValueError("--sensors must contain terra and/or aqua.")
    if bool(args.start) != bool(args.end):
        raise ValueError("Use both --start and --end, or neither.")
    if args.raw_retention_hours < 0:
        raise ValueError("--raw-retention-hours cannot be negative.")
    if not FETCHER.exists() or not DETECTOR.exists():
        raise FileNotFoundError("MODIS fetcher or detector was not found.")
    return args


def main() -> None:
    args = parse_args()
    configure_earthdata_netrc()
    with worker_lock(args.lock_file, args.pid_file):
        processed_keys = read_processed_keys(args.state_file)

        while True:
            cleanup_expired_cycle_directories(
                args.data_dir,
                args.keep_raw,
                args.raw_retention_hours,
            )
            try:
                processed_keys = run_cycle(args, processed_keys)
            except Exception as exc:
                write_pipeline_status(
                    args.status_file,
                    "error",
                    f"MODIS NRT cycle failed: {exc}",
                )
                print(f"MODIS NRT cycle failed: {exc}", flush=True)
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
                    f"Waiting for the next MODIS cycle in {max(1, round(remaining_seconds / 60))} minute(s).",
                )
                time.sleep(min(30, remaining_seconds))


if __name__ == "__main__":
    main()
