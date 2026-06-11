# Bhutan Wildfire Hotspot Detector

This project detects and classifies active fire hotspots in Bhutan from VIIRS raw or near-real-time observations. It is not a FIRMS CSV wrapper. FIRMS-like CSV data can be used only for testing, while the detector is designed around VIIRS I4 and M13 thermal observations.

## Mathematical Model

### 1. Local Contextual Thermal Anomaly

For each VIIRS observation, the detector compares the observed thermal signal with a local background:

```text
I4_anomaly = I4_BT - mean_background_I4
M13_anomaly = M13_BT - mean_background_M13
```

A candidate hotspot passes the contextual test when:

```text
I4_anomaly  > k1 * std_background_I4
M13_anomaly > k2 * std_background_M13
```

`k1` and `k2` are configurable in `config.py`. The I4 band is treated as the sensitive fire detection band, while M13 validates that the thermal signal also appears in a coarser thermal/radiance channel.

### 2. Seasonal Adaptive Threshold

Bhutan has strong seasonal differences. The detector applies a multiplier by month:

```text
k_adjusted = k_base * season_multiplier
```

Default seasons:

```text
winter:  Dec-Feb
spring:  Mar-Apr
dry:     May, Oct-Nov
monsoon: Jun-Sep
```

Monsoon months use stricter thresholds to reduce false positives from cloud/moisture effects. Winter uses slightly lower thresholds so small fires are not missed.

### 3. Terrain-Aware Thermal Correction

From a 10 m DEM, terrain derivatives are:

```text
slope = atan(sqrt((dz/dx)^2 + (dz/dy)^2))
aspect = atan2(-dz/dx, dz/dy)
```

Solar incidence angle:

```text
cos(i) = cos(z)cos(s) + sin(z)sin(s)cos(a_sun - a_slope)
```

Where:

```text
i = solar incidence angle
z = solar zenith angle
s = terrain slope
a_sun = solar azimuth
a_slope = terrain aspect
```

Terrain correction changes sensitivity:

```text
k_terrain = k_adjusted * terrain_correction_factor
```

Steep sun-facing slopes raise the threshold. Shaded valleys lower it.

### 4. Multi-Sensor Fusion

Detections from Suomi NPP, NOAA-20, and NOAA-21 are compared within a rolling 3-hour window. If another satellite detects the same location within the configured distance, confidence increases.

Classes:

```text
Anomaly
Probable Fire
Confirmed Fire
```

### 5. Proximity-Based Threat

The detector checks distance to local layers:

```text
urban areas, roads, dzongs, schools, hospitals, forest reserves, national parks
```

Threat levels:

```text
Monitor
Warning
High Risk
Instant Alert
```

## Project Structure

```text
bhutan_fire_detector/
├── main.py
├── config.py
├── requirements.txt
├── README.md
├── data/
│   ├── dem/
│   ├── viirs/
│   ├── weather/
│   └── vectors/
├── outputs/
└── src/
    ├── data_ingestion.py
    ├── preprocessing.py
    ├── terrain_correction.py
    ├── thermal_anomaly.py
    ├── sensor_fusion.py
    ├── seasonal_threshold.py
    ├── proximity_risk.py
    ├── mapping.py
    └── utils.py
```

## Where To Put Data

Place DEM:

```text
data/dem/bhutan_dem_10m.tif
```

Place VIIRS test CSV or pre-extracted NetCDF files:

```text
data/viirs/
```

Required CSV columns:

```text
latitude, longitude, satellite, detection_time, I4_BT, M13_BT
```

Place optional vector layers:

```text
data/vectors/urban_areas.geojson
data/vectors/roads.geojson
data/vectors/dzongs.geojson
data/vectors/schools.geojson
data/vectors/hospitals.geojson
data/vectors/forest_reserves.geojson
data/vectors/national_parks.geojson
```

## Run

Install dependencies:

```powershell
pip install -r requirements.txt
```

Run with dummy VIIRS-like data:

```powershell
python main.py --dummy
```

Run with real files placed in `data/viirs`:

```powershell
python main.py
```

Run against the raw VNP02MOD/VNP03MOD NetCDF files already downloaded in the parent project:

```powershell
python main.py --viirs-dir ..\data\raw --output-dir outputs_viirs_raw_apr8_17 --k1 1.0 --k2 1.0 --brightness-threshold 999
```

Important: VNP02MOD does not contain the true VIIRS I4 image band. For this test mode, the detector uses M12 log-radiance as an I4-like 3.7 micron proxy and M13 log-radiance as the validation band. For production testing with true I4, place VNP02IMG/VJ102IMG/VJ202IMG image-band products in `data/viirs` or extend `data_ingestion.py` to pair them with their geolocation products.

## Outputs

```text
outputs/hotspots_summary.csv
outputs/hotspots.geojson
outputs/hotspots_map.html
outputs/dashboard_ready.json
```

Each detection includes:

```text
latitude
longitude
satellite
detection_time
I4_BT
M13_BT
background_I4
background_M13
terrain_correction_score
confidence_score
fire_class
nearest_infrastructure
distance_to_infrastructure_m
threat_level
```
