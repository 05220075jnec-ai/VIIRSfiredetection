# VIIRS Fire Detection

Command-line workflow for detecting active fire hotspot candidates over Bhutan from VIIRS VNP02MOD radiance granules and matching VNP03MOD geolocation granules.

## Project Layout

```text
scripts/                 Python command-line workflow
notebooks/               Original exploratory notebooks
data/raw/                Downloaded VIIRS NetCDF granules
data/boundaries/         Bhutan and district boundary files
data/reference/          Reference or comparison CSV data
outputs/bhutan/          Generated all-Bhutan hotspot outputs
outputs/bhutan_boundary/ Generated Bhutan-boundary run outputs
outputs/mongar/          Generated Mongar district outputs
```

## Environment

From the project root:

```powershell
& "C:\Users\Public\miniforge3\Scripts\conda.exe" env create -f environment.yml
(& "C:\Users\Public\miniforge3\Scripts\conda.exe" "shell.powershell" "hook") |
    Out-String |
    Invoke-Expression
conda activate bhutan-fire-detection
```

The shared `bhutan-fire-detection` environment includes the VIIRS, MODIS HDF,
Google Earth Engine, Flask, geospatial, machine-learning, and notebook
dependencies used across the project.

To update an existing environment after changing `environment.yml`:

```powershell
conda env update -n bhutan-fire-detection -f environment.yml --prune
```

`start_dashboard.ps1` automatically uses this environment for the prediction
and burn-severity Python services.

## Run With Local Data

```powershell
python scripts\fetch_and_detect_bhutan_viirs.py --start 2023-04-08 --end 2023-04-17 --local-only
```

For Mongar:

```powershell
python scripts\fetch_and_detect_bhutan_viirs.py --start 2023-04-08 --end 2023-04-17 --district Mongar --out-dir outputs\mongar --local-only
```

## Run With NASA Earthdata Search

Keep Earthdata credentials in a local `.netrc` file at the project root. The file is ignored by Git.

```powershell
python scripts\fetch_and_detect_bhutan_viirs.py --start 2023-04-08 --end 2023-04-17
```

## Run Automatic VIIRS NRT Monitoring

This fetches raw VIIRS NRT moderate-resolution radiance and geolocation swaths for:

- Suomi NPP: `VNP02MOD_NRT` + `VNP03MOD_NRT`
- NOAA-20: `VJ102MOD_NRT` + `VJ103MOD_NRT`
- NOAA-21: `VJ202MOD_NRT` + `VJ203MOD_NRT`

It applies the same Bhutan boundary and M13 log-tail detection logic used by `scripts\fetch_and_detect_bhutan_viirs.py`, including the `0 < M13 < 100` raw-radiance sanity filter.

Run once:

```powershell
python scripts\auto_viirs_nrt_fire_detection.py --once
```

Run continuously every 15 minutes:

```powershell
python scripts\auto_viirs_nrt_fire_detection.py --interval-minutes 15
```

Run continuously and import each cycle into the ForestFireDashboard PostgreSQL database:

```powershell
python scripts\auto_viirs_nrt_fire_detection.py --interval-minutes 15 --lookback-hours 24 --max-granules 200 --dashboard-import
```

This requires the dashboard database to be running from `ForestFireDashboard-main`:

```powershell
docker compose up -d
```

The Python script calls:

```text
ForestFireDashboard-main/server/scripts/importCustomViirsOutput.js
```

That importer converts `outputs/viirs_nrt/viirs_nrt_hotspots.csv` into the dashboard's existing `fire_data` table, so the current React map can display the custom VIIRS detections through `/api/fire-data`.

Default outputs:

```text
outputs/viirs_nrt/viirs_nrt_hotspots.csv
outputs/viirs_nrt/viirs_nrt_hotspots.geojson
outputs/viirs_nrt/viirs_nrt_hotspots.shp
outputs/viirs_nrt/viirs_nrt_clusters.geojson
outputs/viirs_nrt/processed_granules.json
```

Downloaded NRT granules are saved under:

```text
data/viirs_nrt/
```

Useful options:

```powershell
python scripts\auto_viirs_nrt_fire_detection.py --once --lookback-hours 12 --max-granules 120
python scripts\auto_viirs_nrt_fire_detection.py --sensors suomi_npp,noaa20
python scripts\auto_viirs_nrt_fire_detection.py --reprocess --once
```
