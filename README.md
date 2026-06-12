# Bhutan Forest Fire Detection

Integrated Bhutan fire-monitoring workspace for VIIRS and MODIS hotspot
detection, PostgreSQL storage, dashboard visualization, fire-risk prediction,
and dNBR burn-severity mapping.

## Project Structure

```text
apps/
  dashboard/                 React client, Node API, Docker Compose
detectors/
  viirs/                     VIIRS 375 m active-fire algorithm
  modis/                     MODIS 1 km contextual active-fire algorithm
services/
  prediction/                Google Earth Engine fire-risk service
  burn_severity/             Sentinel-2 dNBR service
pipelines/                   Historical and automatic NRT orchestration
notebooks/
  reference/                 Original exploratory reference notebooks
  backups/                   Local notebook backups, ignored by Git
data/                        Raw/reference/processed data, ignored by Git
outputs/                     Hotspots, logs, state, and backups, ignored by Git
docs/                        Current and legacy workflow documentation
```

## Python Environment

Create the shared environment once:

```powershell
& "C:\Users\Public\miniforge3\Scripts\conda.exe" env create -f environment.yml
```

Activate it for manual detector or notebook work:

```powershell
(& "C:\Users\Public\miniforge3\Scripts\conda.exe" "shell.powershell" "hook") |
    Out-String |
    Invoke-Expression
conda activate bhutan-fire-detection
```

`start_dashboard.ps1` locates this environment automatically.

## Start the Complete System

From the project root:

```powershell
.\start_dashboard.ps1
```

Services:

- Dashboard: `http://127.0.0.1:5173`
- Dashboard API: `http://127.0.0.1:3000`
- Prediction: `http://127.0.0.1:5000`
- Burn severity: `http://127.0.0.1:5001`
- PostgreSQL: `localhost:5433`

The Compose file uses the existing persistent Docker volume
`forestfiredashboard-main_postgres_data`.

## Run VIIRS Detection

Legacy reference workflow:

```powershell
python notebooks\reference\fetch_and_detect_bhutan_viirs.py `
  --start 2023-04-08 `
  --end 2023-04-17 `
  --local-only
```

Direct detector:

```powershell
python detectors\viirs\main.py --real
```

Automatic NRT run:

```powershell
python pipelines\auto_viirs_nrt_fire_detection.py --once
```

Continuous 15-minute monitoring with database import:

```powershell
python pipelines\auto_viirs_nrt_fire_detection.py `
  --interval-minutes 15 `
  --lookback-hours 24 `
  --max-granules 200 `
  --dashboard-import
```

## Logs

Current logs are separated by component:

- VIIRS automation: `outputs/logs/viirs/`
- MODIS automation: `outputs/logs/modis/`
- Dashboard and supporting services: `outputs/logs/services/`

On restart, the previous current log is moved into that component's
`archive/` folder. Archived logs older than 30 days are removed when
`start_dashboard.ps1` runs. Set `BHUTAN_FIRE_LOG_RETENTION_DAYS` before
starting the dashboard to use a different retention period.

Watch the current MODIS log:

```powershell
Get-Content .\outputs\logs\modis\modis_realtime.log -Wait -Tail 30
```

Watch the current VIIRS log:

```powershell
Get-Content .\outputs\logs\viirs\viirs_realtime.log -Wait -Tail 30
```

## Raw Data Retention

Downloaded NRT files remain available for 24 hours after a processing cycle:

- VIIRS: `data/raw/viirs/nrt/<cycle timestamp>/`
- MODIS: `data/raw/modis/nrt/<cycle timestamp>/`

The automation removes expired cycle folders before each new cycle. Empty
cycle folders are removed immediately. Use `--raw-retention-hours` to change
the retention period, or `--keep-raw` to disable automatic raw-data deletion.

## Run MODIS Detection

```powershell
python detectors\modis\main.py
```

MODIS reads Terra/Aqua HDF pairs from `data/raw/modis/hdf` and writes the
dashboard-compatible output under `outputs/modis_detector_test`.

## Data Layout

```text
data/
  raw/
    viirs/
      historical_detector/
      historical_workspace/
      nrt/
      nrt_cycle_archive/
    modis/
      hdf/
      standard_archive/
    archive/
      combined_viirs_modis/
  reference/
    boundaries/
    buildings/
    dem/
    lulc/
    vectors/
  processed/
    burn_severity/
```

Raw satellite files remain outside Git. Generated hotspot CSV, GeoJSON, and
Shapefile outputs remain under `outputs/`.

## Documentation

- Current workflow: `docs/PROJECT_WORKFLOW.md`
- Pre-restructure detailed reference: `docs/PROJECT_WORKFLOW_LEGACY.md`
- MODIS algorithm report context: `docs/MODIS_DETECTION_REPORT_CONTEXT.md`
