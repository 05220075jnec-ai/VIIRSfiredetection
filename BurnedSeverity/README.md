# Bhutan Burn Severity dNBR Service

This service converts the Google Earth Engine Sentinel-2 dNBR burn severity script into a Python Flask API for the dashboard.

Run it with:

```powershell
cd BurnedSeverity
python app.py
```

Endpoint:

```text
http://localhost:5001/generate_burn_severity?before=2023-01-20&after=2023-04-18
```

The dashboard uses its selected start date as the before-fire date and selected end date as the after-fire date.

Earth Engine must be authenticated once on the machine:

```powershell
earthengine authenticate
```
