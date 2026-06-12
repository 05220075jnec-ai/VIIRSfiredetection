"""Download paired MODIS Terra/Aqua Level-1B HDF4 granules over Bhutan."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import earthaccess

from config import BHUTAN_BOUNDS


DETECTOR_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = DETECTOR_ROOT.parents[1]
GRANULE_TOKEN = re.compile(r"\.A(\d{7})\.(\d{4})\.")


@dataclass(frozen=True)
class ProductPair:
    folder: str
    label: str
    data_product: str
    geo_product: str


PRODUCTS = {
    "terra": ProductPair("terra", "MODIS Terra", "MOD021KM", "MOD03"),
    "aqua": ProductPair("aqua", "MODIS Aqua", "MYD021KM", "MYD03"),
}

COLLECTION_VERSIONS = {
    "archive": "6.1",
    "nrt": "6.1NRT",
}


def configure_earthdata_netrc() -> None:
    for root in (DETECTOR_ROOT, WORKSPACE_ROOT):
        for name in ("netrc", ".netrc", "_netrc"):
            candidate = root / name
            if candidate.exists():
                os.environ["NETRC"] = str(candidate.resolve())
                return


def granule_key_from_result(granule) -> str:
    umm = granule.get("umm", {})
    candidates = [umm.get("GranuleUR"), umm.get("ProducerGranuleId"), str(granule)]
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

    raise ValueError(f"Could not extract a MODIS granule timestamp from metadata: {candidates}")


def read_skip_keys(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    return {str(value).lower() for value in payload.get("processed", [])}


def search_product(
    short_name: str,
    version: str,
    temporal: tuple[str, str],
    max_granules: int,
):
    bbox = (
        BHUTAN_BOUNDS["min_lon"],
        BHUTAN_BOUNDS["min_lat"],
        BHUTAN_BOUNDS["max_lon"],
        BHUTAN_BOUNDS["max_lat"],
    )
    return earthaccess.search_data(
        short_name=short_name,
        version=version,
        bounding_box=bbox,
        temporal=temporal,
        count=max_granules,
    )


def download_product_pair(
    product_pair: ProductPair,
    version: str,
    temporal: tuple[str, str],
    max_granules: int,
    out_root: Path,
    skip_keys: set[str],
) -> int:
    results_by_product = {}
    for product_name in (product_pair.data_product, product_pair.geo_product):
        print(f"Searching {product_pair.label}: {product_name} {version}", flush=True)
        granules = search_product(product_name, version, temporal, max_granules)
        results_by_product[product_name] = {
            granule_key_from_result(granule): granule
            for granule in granules
        }

    common_keys = sorted(
        set(results_by_product[product_pair.data_product])
        & set(results_by_product[product_pair.geo_product])
    )
    if not common_keys:
        print(f"No complete HDF pairs found for {product_pair.label}.", flush=True)
        return 0

    output_dir = out_root / product_pair.folder
    output_dir.mkdir(parents=True, exist_ok=True)

    downloaded_count = 0
    for key in common_keys:
        processed_key = f"{product_pair.folder}:{key}"
        if processed_key in skip_keys:
            print(f"Skipping already processed {product_pair.label} granule {key}.", flush=True)
            continue

        print(f"Downloading {product_pair.label} granule pair {key}...", flush=True)
        paths = earthaccess.download(
            [
                results_by_product[product_pair.data_product][key],
                results_by_product[product_pair.geo_product][key],
            ],
            local_path=str(output_dir),
            threads=2,
        )
        downloaded_count += len(paths)

    return downloaded_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch paired MODIS Terra/Aqua Level-1B HDF4 granules over Bhutan."
    )
    parser.add_argument("--start", required=True, help="UTC start date/time.")
    parser.add_argument("--end", required=True, help="UTC end date/time.")
    parser.add_argument("--mode", choices=["archive", "nrt"], default="nrt")
    parser.add_argument("--sensors", default="terra,aqua", help="Comma list: terra,aqua")
    parser.add_argument("--max-granules", default=80, type=int)
    parser.add_argument(
        "--out-dir",
        default=WORKSPACE_ROOT / "data" / "raw" / "modis" / "nrt",
        type=Path,
    )
    parser.add_argument("--skip-keys-file", default=None, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_earthdata_netrc()
    earthaccess.login(strategy="netrc")

    selected = [name.strip().lower() for name in args.sensors.split(",") if name.strip()]
    unknown = [name for name in selected if name not in PRODUCTS]
    if unknown:
        raise SystemExit(f"Unknown MODIS sensor(s): {', '.join(unknown)}. Use terra,aqua.")

    skip_keys = read_skip_keys(args.skip_keys_file)
    temporal = (args.start, args.end)
    version = COLLECTION_VERSIONS[args.mode]

    total = 0
    for sensor in selected:
        total += download_product_pair(
            PRODUCTS[sensor],
            version,
            temporal,
            args.max_granules,
            args.out_dir,
            skip_keys,
        )

    print(f"MODIS download complete. Files downloaded/reused: {total}")
    print(f"Output folder: {args.out_dir.resolve()}")


if __name__ == "__main__":
    main()
