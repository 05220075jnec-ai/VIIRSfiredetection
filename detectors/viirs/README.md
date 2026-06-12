# Bhutan VIIRS Fire Detector

This project is a Bhutan-specific VIIRS active fire detection scaffold. It is designed to work from VIIRS I-band and M-band arrays from three satellites:

- Suomi NPP
- NOAA-20
- NOAA-21

It does not use FIRMS CSV as the detector input. FIRMS can be used later for validation or comparison.

## Quick Start

From this folder:

```powershell
python main.py --demo
```

Demo mode creates synthetic VIIRS arrays so the project runs immediately in VS Code.
If real DEM, LULC, and building files are present in `data/`, demo mode uses
those real context layers automatically.

To write outputs to a separate folder:

```powershell
python main.py --demo --out-dir outputs_real_context
```

Outputs are written to:

```text
outputs/viirs_detector/fire_mask.npy
outputs/viirs_detector/fire_detections.csv
outputs/viirs_detector/fire_detections.geojson
outputs/viirs_detector/fire_map.html
```

## Data Folders

Place real files here later:

```text
data/raw/viirs/historical_detector/snpp/      Suomi NPP VIIRS arrays
data/raw/viirs/historical_detector/noaa20/    NOAA-20 VIIRS arrays
data/raw/viirs/historical_detector/noaa21/    NOAA-21 VIIRS arrays
data/reference/dem/                           Bhutan DEM
data/reference/lulc/                          Bhutan land-use/land-cover raster or vector
data/reference/buildings/                     NSDI Bhutan building footprints
data/reference/vectors/                       roads, settlements, dzongs, schools, hospitals, protected areas
```

## Where To Put Each Dataset

Use this layout exactly so the code and future real-data adapters can find the inputs.

### 1. VIIRS Raw Satellite Data

Put raw VIIRS files under the satellite folder:

```text
data/raw/viirs/historical_detector/snpp/
data/raw/viirs/historical_detector/noaa20/
data/raw/viirs/historical_detector/noaa21/
```

For this project, each overpass should ideally contain both image-resolution and moderate-resolution files:

```text
02IMG file  image-band observations, including I1, I2, I3, I4, I5
03IMG file  image-band geolocation
02MOD file  moderate-band observations, including M13
03MOD file  moderate-band geolocation
```

Typical NASA Earthdata short names:

```text
Suomi NPP archive: VNP02IMG, VNP03IMG, VNP02MOD, VNP03MOD
NOAA-20 archive:   VJ102IMG, VJ103IMG, VJ102MOD, VJ103MOD
NOAA-21 archive:   VJ202IMG, VJ203IMG, VJ202MOD, VJ203MOD

Suomi NPP NRT:      VNP02IMG_NRT, VNP03IMG_NRT, VNP02MOD_NRT, VNP03MOD_NRT
NOAA-20 NRT:        VJ102IMG_NRT, VJ103IMG_NRT, VJ102MOD_NRT, VJ103MOD_NRT
NOAA-21 NRT:        VJ202IMG_NRT, VJ203IMG_NRT, VJ202MOD_NRT, VJ203MOD_NRT
```

Expected file format:

```text
.nc NetCDF from NASA Earthdata/LAADS is preferred.
.hdf can be stored here too, but Python on Windows may need extra HDF4 tooling.
```

### 2. DEM

Put Bhutan DEM files in:

```text
data/reference/dem/
```

Recommended format:

```text
GeoTIFF, .tif
CRS: EPSG:4326 or a projected CRS with proper metadata
Resolution: 10 m if available
```

Example:

```text
data/reference/dem/bhutan_dem_10m.tif
```

### 3. LULC

Put Bhutan land-use/land-cover data in:

```text
data/reference/lulc/
```

Accepted formats:

```text
GeoTIFF raster: .tif
GeoPackage vector: .gpkg
Shapefile vector: .shp with .dbf, .shx, .prj
GeoJSON vector: .geojson
```

Example classes expected by the logic:

```text
water
forest
agriculture
built-up
barren/rocky
shrub/grassland
```

### 4. Building Footprints

Put NSDI Bhutan building footprints in:

```text
data/reference/buildings/
```

Recommended formats:

```text
GeoPackage: .gpkg
Shapefile: .shp with .dbf, .shx, .prj
GeoJSON: .geojson
```

Each feature should be a building polygon. The building filter uses overlap, nearest distance, and building density.

### 5. Other Vector Layers

Put optional infrastructure layers in:

```text
data/reference/vectors/
```

Useful layers:

```text
roads
settlements
dzongs
schools
hospitals
protected areas
forest reserves
national parks
Bhutan boundary
dzongkhag boundary
```

Recommended formats:

```text
.gpkg, .shp, or .geojson
```

## Fetch VIIRS Data Using Your Earthdata Account

This project includes:

```text
fetch_viirs_earthdata.py
```

It uses `earthaccess`, the same style as the earlier NASA LAADS workflow.

### Step 1: Make Sure Your Earthdata Credentials Exist

The script looks for one of these files in this project or the parent workspace:

```text
netrc
.netrc
_netrc
```

On Windows, Earthdata often expects:

```text
C:\Users\<your user>\_netrc
```

But this project also supports local files like:

```text
VIIRSfiredetection\.netrc
VIIRSfiredetection\netrc
VIIRSfiredetection\_netrc
```

The file content should look like:

```text
machine urs.earthdata.nasa.gov
login YOUR_EARTHDATA_USERNAME
password YOUR_EARTHDATA_PASSWORD
```

Do not commit this file to GitHub.

### Step 2: Install Requirements

From inside this project:

```powershell
pip install -r requirements.txt
```

### Step 3: Fetch Archive VIIRS Data

Example for April 8-17, 2023:

```powershell
python fetch_viirs_earthdata.py --mode archive --start 2023-04-08 --end 2023-04-17 --max-granules 200
```

This downloads/reuses files into:

```text
data/raw/viirs/historical_detector/snpp/
data/raw/viirs/historical_detector/noaa20/
data/raw/viirs/historical_detector/noaa21/
```

### Step 4: Fetch NRT VIIRS Data

Example for recent near-real-time data:

```powershell
python fetch_viirs_earthdata.py --mode nrt --start 2026-05-21T00:00:00Z --end 2026-05-22T00:00:00Z --max-granules 200
```

### Step 5: Fetch Only One Satellite

```powershell
python fetch_viirs_earthdata.py --mode archive --sensors snpp --start 2023-04-08 --end 2023-04-17
```

Or:

```powershell
python fetch_viirs_earthdata.py --mode archive --sensors noaa20,noaa21 --start 2023-04-08 --end 2023-04-17
```

### Important Note About Real Detection

The demo detector currently runs with dummy arrays:

```powershell
python main.py --demo
```

The downloader prepares the raw NASA files. The next implementation step is to add product-specific readers that convert downloaded `02IMG/03IMG/02MOD/03MOD` files into the internal observation format:

```text
latitude
longitude
BT4
BT5
M13
I1
I2
I3
land_water_mask
cloud_mask
bowtie_mask
solar_zenith
view_zenith
relative_azimuth
```

## Algorithm Summary

The detector follows a VIIRS 375 m active-fire style workflow:

1. Load VIIRS observations containing `I1`, `I2`, `I3`, `BT4`, `BT5`, `M13`, latitude, longitude, masks, satellite name, and acquisition time.
2. Mask invalid, water, cloud, and residual bowtie pixels.
3. Initialize valid land pixels as fire mask class `5`.
4. Use I4/BT4 as the main thermal anomaly band.
5. Use I5/BT5 as background thermal comparison.
6. Use M13 as an energy validation band because I4 can saturate near 367 K.
7. Apply absolute daytime/nighttime fire thresholds.
8. Apply local contextual background tests using expanding windows.
9. Reject bright surfaces and reduce confidence for sun-glint risk.
10. Add terrain correction from slope, aspect, and solar incidence.
11. Add Bhutan LULC context: forest, agriculture, built-up, water, barren, shrub/grassland.
12. Use building footprints to detect roof false positives or structure fire candidates.
13. Fuse detections from SNPP, NOAA-20, and NOAA-21 within a rolling 3-hour window.
14. Calculate final confidence and threat level.
15. Export CSV, GeoJSON, fire mask array, and Folium map.

## Fire Mask Classes

```text
0 = not processed
1 = residual bowtie pixel
3 = water
4 = cloud
5 = land
7 = low confidence fire
8 = nominal confidence fire
9 = high confidence fire
```

## Main Modules

- `src/data_ingestion.py`: dummy and real-data loading adapters
- `src/preprocessing.py`: invalid/water/cloud/bowtie masking
- `src/fire_detection.py`: absolute fire tests, bright-surface rejection, contextual decision setup
- `src/contextual_tests.py`: local background mean and mean absolute deviation
- `src/m13_validation.py`: M13 energy anomaly validation
- `src/sensor_fusion.py`: 3-hour, 375 m multi-satellite fusion
- `src/terrain_correction.py`: slope, aspect, solar incidence, terrain risk
- `src/lulc_filter.py`: Bhutan LULC fire context
- `src/building_filter.py`: roof false-positive and structure-fire logic
- `src/proximity_risk.py`: threat level classification
- `src/export_outputs.py`: CSV, GeoJSON, NumPy mask, Folium map

## Real Data Mode

The first version implements demo mode fully. Real-data support is scaffolded in `src/data_ingestion.py` with `load_real_observation()`.

Expected real-data variables:

```text
latitude
longitude
BT4
BT5
M13
I1
I2
I3
land_water_mask
cloud_mask
bowtie_mask
solar_zenith
view_zenith
relative_azimuth
```

Product-specific NASA NetCDF/HDF readers can be added inside `src/data_ingestion.py` while keeping the rest of the detector unchanged.

## Current Real-Context Status

The project now automatically discovers and uses:

```text
data/reference/dem/*.tif
data/reference/lulc/*.shp, *.geojson, or *.gpkg
data/reference/buildings/*.shp, *.geojson, or *.gpkg
```

With your current files, the run uses:

```text
DEM: data/reference/dem/BHutan_SRTM.tif
LULC: data/reference/lulc/Land Use Land Cover 2020.shp
Buildings: data/reference/buildings/NCRP Building Footprints.shp
```

The output CSV now includes real context fields such as:

```text
elevation_m
slope_deg
aspect_deg
lulc_source_class
lulc_class
distance_to_nearest_building_m
buildings_within_500m
buildings_within_1km
buildings_within_2km
roof_false_positive_score
structure_fire_probability
final_threat_level
```

## Run With Real VIIRS Files

The project can now ingest the real VIIRS NetCDF files already downloaded in
the parent workspace folder:

```text
data/raw/viirs/historical_workspace/
```

Those existing files are Suomi NPP `VNP02MOD/VNP03MOD` pairs. The reader crops
each swath to Bhutan, converts M13/M15 radiance to brightness-temperature-style
thermal arrays, and then applies the fire detection, terrain, LULC, building,
fusion, and risk logic.

Run a small test:

```powershell
python main.py --real --max-observations 2 --out-dir outputs_real_viirs_test
```

Run a larger real-data pass:

```powershell
python main.py --real --max-observations 12 --out-dir outputs_real_viirs
```

Current real-ingest note:

```text
The available local files are MOD products, not IMG products.
So the current real mode uses a MOD fallback:
- M13 radiance -> 4 micrometer brightness-temperature proxy
- M15 radiance -> 11 micrometer brightness-temperature proxy
- M05/M07/M10 -> reflectance-like bright-surface proxy bands

For full VIIRS 375 m I-band fire detection, add/fetch 02IMG/03IMG files.
```

The real run writes:

```text
outputs_real_viirs/fire_mask.npy
outputs_real_viirs/fire_detections.csv
outputs_real_viirs/fire_detections.geojson
outputs_real_viirs/fire_map.html
```
