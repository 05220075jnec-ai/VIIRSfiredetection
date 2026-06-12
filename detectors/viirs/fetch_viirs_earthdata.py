"""Download raw VIIRS files for Bhutan using NASA Earthdata/LAADS.

This downloader places files into:

data/raw/viirs/historical_detector/snpp/
data/raw/viirs/historical_detector/noaa20/
data/raw/viirs/historical_detector/noaa21/

It fetches both image-resolution and moderate-resolution L1B products because
the detector needs I-band thermal inputs plus M13 validation:

- 02IMG/03IMG: I-band radiance/brightness temperature and image geolocation
- 02MOD/03MOD: M-band radiance/brightness temperature and moderate geolocation
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import earthaccess

from config import BHUTAN_BOUNDS, PATHS


PROJECT_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
GRANULE_TOKEN = re.compile(r"\.A(\d{7})\.(\d{4})\.")


@dataclass(frozen=True)
class ProductSet:
    """Earthdata short names for one satellite."""

    folder: str
    label: str
    img_data: str
    img_geo: str
    mod_data: str
    mod_geo: str
    version: str | None


ARCHIVE_PRODUCTS = {
    "snpp": ProductSet("snpp", "Suomi NPP", "VNP02IMG", "VNP03IMG", "VNP02MOD", "VNP03MOD", "2"),
    "noaa20": ProductSet("noaa20", "NOAA-20", "VJ102IMG", "VJ103IMG", "VJ102MOD", "VJ103MOD", "2.1"),
    "noaa21": ProductSet("noaa21", "NOAA-21", "VJ202IMG", "VJ203IMG", "VJ202MOD", "VJ203MOD", "2.1"),
}

NRT_PRODUCTS = {
    "snpp": ProductSet("snpp", "Suomi NPP NRT", "VNP02IMG_NRT", "VNP03IMG_NRT", "VNP02MOD_NRT", "VNP03MOD_NRT", "2"),
    "noaa20": ProductSet("noaa20", "NOAA-20 NRT", "VJ102IMG_NRT", "VJ103IMG_NRT", "VJ102MOD_NRT", "VJ103MOD_NRT", "2.1"),
    "noaa21": ProductSet("noaa21", "NOAA-21 NRT", "VJ202IMG_NRT", "VJ203IMG_NRT", "VJ202MOD_NRT", "VJ203MOD_NRT", "2"),
}


def configure_earthdata_netrc() -> None:
    """Let earthaccess find credentials in local netrc files."""
    for root in (PROJECT_ROOT, WORKSPACE_ROOT):
        for name in ("netrc", ".netrc", "_netrc"):
            candidate = root / name
            if candidate.exists():
                os.environ["NETRC"] = str(candidate.resolve())
                return


def granule_key_from_result(granule) -> str:
    """Extract AYYYYDDD.HHMM from CMR metadata or data links."""
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

    raise ValueError(f"Could not extract granule timestamp from metadata: {candidates}")


def search_product(short_name: str, temporal: tuple[str, str], max_granules: int, version: str | None):
    """Search one VIIRS product over the Bhutan bounding box."""
    bbox = (
        BHUTAN_BOUNDS["min_lon"],
        BHUTAN_BOUNDS["min_lat"],
        BHUTAN_BOUNDS["max_lon"],
        BHUTAN_BOUNDS["max_lat"],
    )
    kwargs = {
        "short_name": short_name,
        "bounding_box": bbox,
        "temporal": temporal,
        "count": max_granules,
    }
    if version:
        kwargs["version"] = version
    return earthaccess.search_data(**kwargs)


def read_skip_keys(path: Path | None) -> set[str]:
    """Read satellite:granule keys that were already processed."""
    if not path or not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()

    normalized = set()
    for value in payload.get("processed", []):
        key = str(value)
        if key.startswith("suomi_npp:"):
            key = "snpp:" + key.split(":", 1)[1]
        normalized.add(key)
    return normalized


def download_product_set(
    product_set: ProductSet,
    temporal: tuple[str, str],
    max_granules: int,
    out_root: Path,
    skip_keys: set[str],
) -> int:
    """Download IMG and MOD product pairs for one satellite."""
    product_names = [product_set.img_data, product_set.img_geo, product_set.mod_data, product_set.mod_geo]
    results_by_product = {}

    for product_name in product_names:
        print(f"Searching {product_set.label}: {product_name}", flush=True)
        granules = search_product(product_name, temporal, max_granules, product_set.version)
        results_by_product[product_name] = {granule_key_from_result(granule): granule for granule in granules}

    common_keys = sorted(set.intersection(*(set(items) for items in results_by_product.values())))
    if not common_keys:
        print(f"No complete IMG/MOD pairs found for {product_set.label}.", flush=True)
        return 0

    output_dir = out_root / product_set.folder
    output_dir.mkdir(parents=True, exist_ok=True)

    downloaded_count = 0
    for key in common_keys:
        processed_key = f"{product_set.folder}:{key}"
        if processed_key in skip_keys:
            print(f"Skipping already processed {product_set.label} granule set {key}.", flush=True)
            continue
        granules = [results_by_product[product_name][key] for product_name in product_names]
        print(f"Downloading {product_set.label} granule set {key}...", flush=True)
        paths = earthaccess.download(granules, local_path=str(output_dir), threads=4)
        downloaded_count += len(paths)

    return downloaded_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Bhutan VIIRS IMG/MOD files using NASA Earthdata.")
    parser.add_argument("--start", required=True, help="UTC start date/time, e.g. 2023-04-08 or 2023-04-08T00:00:00Z")
    parser.add_argument("--end", required=True, help="UTC end date/time, e.g. 2023-04-17 or 2023-04-17T23:59:59Z")
    parser.add_argument("--mode", choices=["archive", "nrt"], default="archive")
    parser.add_argument("--sensors", default="snpp,noaa20,noaa21", help="Comma list: snpp,noaa20,noaa21")
    parser.add_argument("--max-granules", default=80, type=int)
    parser.add_argument("--out-dir", default=PATHS.viirs, type=Path)
    parser.add_argument("--skip-keys-file", default=None, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_earthdata_netrc()
    earthaccess.login(strategy="netrc")

    catalog = ARCHIVE_PRODUCTS if args.mode == "archive" else NRT_PRODUCTS
    selected = [name.strip() for name in args.sensors.split(",") if name.strip()]
    temporal = (args.start, args.end)
    skip_keys = read_skip_keys(args.skip_keys_file)

    total = 0
    for sensor in selected:
        if sensor not in catalog:
            raise SystemExit(f"Unknown sensor {sensor!r}. Use snpp,noaa20,noaa21.")
        total += download_product_set(catalog[sensor], temporal, args.max_granules, args.out_dir, skip_keys)

    print(f"Download complete. Files downloaded/reused: {total}")
    print(f"Output folder: {args.out_dir.resolve()}")


if __name__ == "__main__":
    main()
