# Bhutan MODIS Active-Fire Detection — Report Context

## Purpose

This document describes the MODIS active-fire detection component developed for
the Bhutan forest-fire detection project. It can be uploaded to ChatGPT and used
as source material for writing a project report, methodology chapter, system
design, presentation, or algorithm explanation.

The implementation is a transparent **MODIS-inspired contextual active-fire
detector**. It follows the general structure documented for NASA's MOD14/MYD14
active-fire products, but it is not a bit-for-bit reproduction of NASA's
operational algorithm.

## Input Data

The detector processes MODIS Level-1B HDF4 files from Terra and Aqua.

| Satellite | Science data | Geolocation data |
|---|---|---|
| Terra | `MOD021KM` | `MOD03` |
| Aqua | `MYD021KM` | `MYD03` |

The science and geolocation files are matched using the acquisition token in
their filenames, such as `A2023098.1545`.

The acquisition token contains:

- Year: `2023`
- Julian day: `098`
- UTC acquisition time: `15:45`

## MODIS Bands Used

| Band | Approximate wavelength | Purpose |
|---|---:|---|
| 1 | 0.65 µm | Reflective cloud and bright-surface screening |
| 2 | 0.86 µm | Reflective cloud, bright-surface and false-alarm screening |
| 21 | 3.96 µm | High-temperature fire channel |
| 22 | 3.96 µm | Preferred fire channel when unsaturated |
| 31 | 11.03 µm | Background surface temperature and contextual testing |
| 32 | 12.02 µm | Cloud screening |

Band 22 is preferred for the 4 µm brightness temperature because it has lower
noise. Band 21 replaces it when band 22 is invalid or reaches approximately
`330 K`.

## Radiance Calibration

Raw digital numbers are converted into calibrated radiance using the scale and
offset attributes stored in the HDF dataset:

```text
Radiance = (Raw value − Radiance offset) × Radiance scale
```

Fill values and values outside the dataset's valid range are converted to
missing values before calibration.

## Brightness Temperature

Thermal radiance is converted into brightness temperature using Planck's law:

```text
T = c2 / [λ × ln(c1 / (L × λ^5) + 1)]
```

Where:

- `T` is brightness temperature in Kelvin.
- `L` is spectral radiance.
- `λ` is the central wavelength in micrometres.
- `c1 = 1.191042 × 10^8`
- `c2 = 1.4387752 × 10^4`

The resulting temperatures are:

- `T4`: combined band 21/22 brightness temperature.
- `T11`: band 31 brightness temperature.
- `T12`: band 32 brightness temperature.
- `ΔT = T4 − T11`: thermal contrast used to identify active fires.

## Preprocessing and Masking

### Invalid-Data Mask

A pixel is excluded when its thermal data, latitude, longitude, or solar angle
is missing or invalid.

### Bhutan Bounding-Box Mask

Only pixels within the approximate Bhutan region are processed:

```text
Longitude: 88.4°E to 92.6°E
Latitude:  26.4°N to 28.6°N
```

This early mask reduces processing time. Accepted hotspot points are later
checked against Bhutan's exact national boundary polygon.

### Water Mask

The `Land/SeaMask` dataset from `MOD03` or `MYD03` is used. Only pixels marked
as land are considered for fire detection.

### Cloud Mask

The project currently uses an internal approximation:

```text
Cold cloud:
T11 < 265 K
```

For daytime pixels, an additional reflective-cloud condition is used:

```text
Band 1 reflectance + Band 2 reflectance > 0.90
and
T11 < 285 K
```

This is not a complete reproduction of NASA's operational MOD14 cloud mask.

## Day and Night Identification

Day or night is determined separately for every pixel using solar zenith:

```text
Solar zenith < 85°  → Daytime
Solar zenith ≥ 85°  → Nighttime
```

Pixel-level classification is used because a MODIS swath can contain different
illumination conditions.

## Potential-Fire Candidate Selection

Only clear-land pixels are tested.

### Daytime Candidate

```text
T4 > 310 K
and
T4 − T11 > 10 K
```

### Nighttime Candidate

```text
T4 > 305 K
and
T4 − T11 > 10 K
```

These tests remove clearly non-fire pixels before the more expensive contextual
analysis.

## Absolute Fire Test

Exceptionally hot pixels can pass an absolute fire test:

```text
Daytime:   T4 > 360 K
Nighttime: T4 > 320 K
```

An absolute-fire pixel does not have to depend entirely on successful local
background characterization.

## Contextual Background Test

Potential fire pixels that do not pass the absolute test are compared with
nearby clear-land pixels.

The local window:

1. Starts at `3 × 3` pixels.
2. Expands by two pixels at each step.
3. Stops at a maximum of `21 × 21`.
4. Requires at least eight valid background pixels.
5. Requires valid background pixels to occupy at least 25% of the available
   window.
6. Excludes the candidate and its two immediate along-scan neighbours from the
   background calculation.

For the valid background, the algorithm calculates:

- Mean `T4`
- Mean `T11`
- Mean `T4 − T11`
- Mean absolute deviation of `T4`
- Mean absolute deviation of `T11`
- Mean absolute deviation of `T4 − T11`

The contextual pixel must pass the following general conditions:

```text
Pixel ΔT >
Background mean ΔT + 3.5 × Background MAD ΔT
```

```text
Pixel ΔT > Background mean ΔT + 6 K
```

```text
Pixel T4 >
Background mean T4 + 3 × Background MAD T4
```

The `T11` condition prevents an implausibly cold or contaminated candidate from
being accepted.

The use of local statistics allows detection to adapt to environmental
temperature differences instead of assuming that the hottest percentage of
every granule contains fire.

## False-Positive Screening

### Bright Surface

A daytime candidate may be rejected when:

```text
Band 2 reflectance > 0.30
and
T4 < 335 K
```

Absolute high-temperature fires are not rejected by this condition.

### Sun-Glint Risk

Solar and sensor zenith/azimuth angles are used to estimate glint risk. A
high-risk daytime candidate is rejected unless it passes the absolute fire
test.

### Cloud and Water Adjacency

The number of cloud and water pixels surrounding a candidate is recorded.
Nearby cloud and water pixels reduce confidence because coastlines and cloud
edges can generate false thermal anomalies.

## Confidence Calculation

Confidence is calculated from several pieces of evidence:

- Strength of `T4`
- Strength of `T4 − T11`
- Absolute-test result
- Contextual-test result
- Number of valid background pixels
- Bright-surface rejection
- Sun-glint risk
- Adjacent clouds
- Adjacent water

The score is limited to `1–99`.

| Fire mask | Confidence meaning |
|---:|---|
| 7 | Low-confidence fire |
| 8 | Nominal-confidence fire, score ≥ 65 |
| 9 | High-confidence fire, score ≥ 85 |

## Exact Bhutan Boundary Filter

After detection, every candidate point is tested against the exact Bhutan
boundary polygon. Points within the rectangular processing area but outside
Bhutan are removed.

## Fire-Type Context

The accepted point is spatially joined with Bhutan's Land Use/Land Cover map.

| Land-cover class | Assigned context |
|---|---|
| Forest | `forest_fire` |
| Agriculture | `agricultural_fire` |
| Shrub or grassland | `forest_fire` |
| Built-up | `possible_structure_or_roof_anomaly` |
| Water | `water_false_positive` |
| Barren or rocky | `unknown_thermal_anomaly` |

This value describes the land-cover context of the thermal anomaly. It should
not be presented as definitive proof of the cause of the fire.

For this project, `forest_fire` is the broad wildland-fire category. It includes
hotspots on forest, shrubland, and grassland. Agricultural land is retained as
the separate `agricultural_fire` category.

## Output Attributes

Each detected hotspot contains:

- Sensor and satellite
- Granule ID
- Acquisition date and UTC time
- Latitude and longitude
- Day/night status
- Confidence and fire-mask class
- Land-cover and fire-context class
- `T4`, `T11`, `T12`, and `T4 − T11`
- Band 21/22 source used for `T4`
- Absolute and contextual test results
- Background statistics and window size
- Adjacent cloud and water counts
- Sun-glint risk
- Source HDF filenames
- Algorithm version

## Output Formats

The detector writes:

```text
fire_detections.csv
fire_detections.geojson
fire_mask.npy
```

The CSV is suitable for database import. GeoJSON is suitable for web mapping
and GIS software. The NumPy mask preserves the pixel-level classification.

## Current Validation

The implementation was tested with:

- Controlled synthetic daytime fire
- Controlled synthetic nighttime fire
- Contextual-only fire
- Water-mask rejection
- Four actual Terra/Aqua MODIS HDF observations

The four real observations produced three Bhutan hotspot candidates:

- Two nominal-confidence detections
- One high-confidence detection
- Two vegetation-fire contexts
- One forest-fire context

Further validation against official MOD14/MYD14 products, FIRMS observations,
field records, or higher-resolution imagery is recommended before operational
deployment.

## Limitations

1. The internal cloud mask is an approximation.
2. The thresholds require validation for Bhutan's terrain and seasons.
3. The algorithm is inspired by MOD14/MYD14 but is not identical to NASA's
   proprietary operational implementation.
4. MODIS has approximately 1 km resolution, so a detected pixel can contain a
   mixture of land-cover types.
5. LULC-based fire type indicates context, not confirmed cause.
6. The detector is not yet connected to the automatic downloader or PostgreSQL
   import pipeline.
7. Comparison with official MOD14/MYD14 fire products should be performed to
   estimate omission and commission errors.

## Implementation Files

- `bhutan_modis_fire_detector/config.py`
- `bhutan_modis_fire_detector/main.py`
- `bhutan_modis_fire_detector/src/data_ingestion.py`
- `bhutan_modis_fire_detector/src/preprocessing.py`
- `bhutan_modis_fire_detector/src/contextual_tests.py`
- `bhutan_modis_fire_detector/src/fire_detection.py`
- `bhutan_modis_fire_detector/src/context.py`
- `bhutan_modis_fire_detector/src/export_outputs.py`

## Authoritative References

1. LP DAAC MODIS/Terra Thermal Anomalies and Fire product:
   https://lpdaac.usgs.gov/products/mod14v061/

2. MOD14/MYD14 Collection 6.1 User Guide:
   https://lpdaac.usgs.gov/documents/1005/MOD14_User_Guide_V61.pdf

3. MODIS Fire Products Algorithm Theoretical Basis Document:
   https://lpdaac.usgs.gov/documents/87/MOD14_ATBD.pdf

4. Giglio, L., Descloitres, J., Justice, C. O., and Kaufman, Y. J. (2003).
   An enhanced contextual fire detection algorithm for MODIS. Remote Sensing
   of Environment, 87, 273–282.

## Prompt to Use in ChatGPT

Upload this file to ChatGPT and send:

```text
Using the uploaded MODIS detection context, write a detailed academic report
section for my Bhutan forest-fire detection project. Include an introduction,
input datasets, preprocessing and masking, radiance calibration, brightness
temperature calculation, day/night thresholding, absolute and contextual fire
tests, confidence classification, LULC-based fire context, outputs, validation,
limitations, and recommendations. Clearly state that this is a MODIS-inspired
contextual detector and not a bit-for-bit reproduction of NASA MOD14/MYD14.
Use formal academic language, equations, tables, and the listed authoritative
references. Do not invent validation accuracy values.
```
