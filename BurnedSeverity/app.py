"""Burn severity tile service for the Bhutan fire dashboard.

This Flask app converts the Google Earth Engine JavaScript dNBR workflow into
Python. The dashboard calls /generate_burn_severity with a before and after
date, and the app returns an Earth Engine tile URL that OpenLayers can display.
"""

from flask import Flask, jsonify, request
import ee


EE_PROJECT = "ee-05220053jnec"
BHUTAN_AOI_ASSET = "projects/ee-05220053jnec/assets/BHUTAN_WGS84"

EE_INITIALIZED = False
EE_INIT_ERROR = None


def initialize_earth_engine():
    """Initialize Earth Engine without forcing browser auth from the server."""
    global EE_INITIALIZED, EE_INIT_ERROR
    try:
        ee.Initialize(project=EE_PROJECT)
        EE_INITIALIZED = True
        EE_INIT_ERROR = None
    except Exception:
        EE_INITIALIZED = False
        EE_INIT_ERROR = "Google Earth Engine is not authenticated. Run: earthengine authenticate"


initialize_earth_engine()

app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    """Allow the React dashboard to request this tile service."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


def mask_sentinel2_clouds(image):
    """Mask Sentinel-2 QA60 cloud and cirrus bits, then scale reflectance."""
    qa = image.select("QA60")
    cloud_bit_mask = 1 << 10
    cirrus_bit_mask = 1 << 11
    mask = qa.bitwiseAnd(cloud_bit_mask).eq(0).And(
        qa.bitwiseAnd(cirrus_bit_mask).eq(0)
    )
    return image.updateMask(mask).divide(10000)


def sentinel2_composite(roi, start_date, end_date):
    """Build a cloud-masked Sentinel-2 median composite for the date window."""
    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(roi)
        .filterDate(start_date, end_date)
        .map(mask_sentinel2_clouds)
    )

    empty = ee.Image.constant([0, 0, 0, 0]).rename(["B2", "B4", "B8", "B12"]).clip(roi)
    return ee.Image(
        ee.Algorithms.If(collection.size().gt(0), collection.median().clip(roi), empty)
    )


def add_nbr(image):
    """Add Normalized Burn Ratio: NBR = (NIR - SWIR2) / (NIR + SWIR2)."""
    nbr = image.normalizedDifference(["B8", "B12"]).rename("NBR")
    return image.addBands(nbr)


@app.route("/")
def index():
    return jsonify({
        "service": "Bhutan Burn Severity dNBR",
        "endpoint": "/generate_burn_severity?before=2023-01-20&after=2023-04-18",
    })


@app.route("/generate_burn_severity", methods=["GET"])
def generate_burn_severity():
    """Return a GEE tile URL for dNBR burn severity over Bhutan."""
    if not EE_INITIALIZED:
        return jsonify({"error": EE_INIT_ERROR or "Google Earth Engine is not initialized."}), 503

    before_fire = request.args.get("before") or request.args.get("start") or "2023-01-20"
    after_fire = request.args.get("after") or request.args.get("end") or "2023-04-18"

    try:
        roi = ee.FeatureCollection(BHUTAN_AOI_ASSET)
        before_date = ee.Date(before_fire)
        after_date = ee.Date(after_fire)

        # Match the GEE script: pre-fire composite from two months before the
        # before date, and post-fire composite from the after date to two months
        # after the fire.
        before_image = sentinel2_composite(
            roi,
            before_date.advance(-2, "month"),
            before_date,
        )
        after_image = sentinel2_composite(
            roi,
            after_date,
            after_date.advance(2, "month"),
        )

        before_nbr = add_nbr(before_image)
        after_nbr = add_nbr(after_image)

        d_nbr = (
            before_nbr.select("NBR")
            .subtract(after_nbr.select("NBR"))
            .rename("dNBR")
            .clip(roi)
        )

        severity_vis = {
            "min": -1,
            "max": 1,
            "palette": ["blue", "green", "yellow", "orange", "red"],
        }
        map_id = d_nbr.getMapId(severity_vis)

        return jsonify({
            "tile_url": map_id["tile_fetcher"].url_format,
            "source": "Google Earth Engine Sentinel-2 dNBR",
            "layer_name": "Burn Severity (dNBR)",
            "before": before_fire,
            "after": after_fire,
        })
    except Exception as exc:
        return jsonify({"error": f"Burn severity generation failed: {exc}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
