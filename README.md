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
..\gee_env\Scripts\Activate.ps1
pip install -r requirements.txt
```

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
