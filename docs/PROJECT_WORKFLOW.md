# Current Project Workflow

## 1. Data Acquisition

The automation pipeline in `pipelines/auto_viirs_nrt_fire_detection.py`
queries NASA Earthdata for Suomi NPP, NOAA-20, and NOAA-21 VIIRS granules.
Downloaded NRT data is written to `data/raw/viirs/nrt`. Bhutan boundaries and
other context layers are stored under `data/reference`. Processed granule keys
are stored in `outputs/viirs_nrt/processed_granules.json`, preventing the same
granule from being processed repeatedly.

Historical VIIRS processing is orchestrated by
`pipelines/fetch_and_detect_bhutan_viirs.py`. MODIS Terra/Aqua HDF pairs are
read from `data/raw/modis/hdf`.

## 2. Detection Algorithms

The VIIRS implementation is under `detectors/viirs`. It applies I-band thermal
candidate thresholds, day/night logic, contextual background tests, M13
validation, Bhutan-boundary filtering, terrain and land-cover context,
building proximity, and multi-satellite fusion.

The MODIS implementation is under `detectors/modis`. It applies Terra/Aqua
HDF ingestion, cloud and invalid-pixel masking, day/night candidate
thresholding, absolute-fire tests, contextual neighborhood tests, confidence
scoring, Bhutan-boundary filtering, and land-cover classification.

## 3. Outputs

VIIRS NRT outputs are written to `outputs/viirs_nrt`. Historical VIIRS outputs
are stored under `outputs/bhutan` or a user-selected output directory. MODIS
dashboard outputs are stored under `outputs/modis_detector_test`.

Raw satellite files are intentionally excluded from Git. CSV, GeoJSON,
Shapefile, masks, logs, and processing state are also generated artifacts and
remain under `outputs`.

## 4. Database Import

The Node API under `apps/dashboard/server` imports normalized hotspot rows into
the PostgreSQL `fire_data` table. VIIRS and MODIS records are distinguished by
their `version`, `instrument`, and satellite attributes.

PostgreSQL runs through `apps/dashboard/docker-compose.yml` and uses the
persistent external volume `forestfiredashboard-main_postgres_data`.

## 5. Dashboard

The React client under `apps/dashboard/client` requests hotspot records from
`/api/fire-data`. Users can select VIIRS or MODIS, filter dates and
dzongkhags, and display stored historical detections without rerunning the
satellite algorithms.

## 6. Prediction and Burn Severity

`services/prediction/app.py` exposes the Google Earth Engine predicted-risk
map on port 5000. `services/burn_severity/app.py` exposes Sentinel-2 dNBR burn
severity on port 5001.

## 7. Startup

`start_dashboard.ps1` starts PostgreSQL, the Node API, both Python services,
and the Vite frontend. It automatically selects the
`bhutan-fire-detection` Conda environment.

The pre-restructure detailed technical narrative is retained in
`docs/PROJECT_WORKFLOW_LEGACY.md`.
