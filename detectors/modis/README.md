# Bhutan MODIS HDF Active-Fire Detector

This detector is separate from the VIIRS 375 m detector. It reads MODIS Terra
and Aqua Level-1B HDF4 pairs:

- `MOD021KM` + `MOD03`
- `MYD021KM` + `MYD03`

The design follows the structure described for NASA's MOD14/MYD14 contextual
active-fire algorithm:

1. Calibrate bands 21, 22, 31, and 32.
2. Use band 22 for the 4 µm temperature where possible and band 21 when band
   22 is saturated or invalid.
3. Screen invalid, water, cloud, bright-surface, and sun-glint-risk pixels.
4. Apply separate daytime and nighttime potential-fire thresholds.
5. Characterize the clear-land background with an expanding 3×3 to 21×21
   window.
6. Apply absolute and contextual 4 µm / 11 µm tests.
7. Calculate confidence and assign fire-mask classes 7, 8, or 9.
8. Clip detections to Bhutan and attach LULC-based fire context.
9. Export a NumPy fire mask, CSV, and GeoJSON.

The reporting categories group natural vegetation together:

- Forest and shrub/grassland → `forest_fire`
- Agriculture and cropland → `agricultural_fire`
- Other land cover → an appropriate anomaly or unknown category

This is a transparent MODIS-inspired detector for this project, not a
bit-for-bit reproduction or replacement for NASA's operational MOD14/MYD14
product.

Algorithm references:

- [MODIS/Terra Thermal Anomalies and Fire product](https://lpdaac.usgs.gov/products/mod14v061/)
- [MOD14/MYD14 Collection 6.1 User Guide](https://lpdaac.usgs.gov/documents/1005/MOD14_User_Guide_V61.pdf)
- [MODIS Fire Products Algorithm Theoretical Basis Document](https://lpdaac.usgs.gov/documents/87/MOD14_ATBD.pdf)

Run it with the installed Conda environment:

```powershell
C:\Users\Public\miniforge3\Scripts\conda.exe run -n bhutan-fire-detection python detectors\modis\main.py --max-observations 2
```

Outputs are written to `outputs/modis_detector_test` by default.

## Near-real-time automation

The production worker uses NASA Earthdata Collection `6.1NRT` HDF4 pairs:

- Terra: `MOD021KM` + `MOD03`
- Aqua: `MYD021KM` + `MYD03`

Run one cycle:

```powershell
C:\Users\Public\miniforge3\envs\bhutan-fire-detection\python.exe pipelines\auto_modis_nrt_fire_detection.py --once --dashboard-import
```

The normal dashboard launcher starts the worker every 15 minutes:

```powershell
.\start_dashboard.ps1
```

Each cycle searches the latest 24-hour window, skips granules listed in
`outputs/modis_nrt/processed_granules.json`, detects new pairs, incrementally
inserts hotspots into PostgreSQL, and deletes the temporary raw HDF files only
after the cycle finishes. Status is written to
`outputs/modis_nrt/pipeline_status.json`.
