# ==========================================================
# DYNAMIC FOREST FIRE SUSCEPTIBILITY WEB APP
# Flask + Google Earth Engine
# ==========================================================

# INSTALL:
# pip install flask earthengine-api geemap

# ==========================================================
# IMPORTS
# ==========================================================

from flask import Flask, render_template, jsonify, request
import ee

# ==========================================================
# INITIALIZE GEE
# ==========================================================

EE_INITIALIZED = False
EE_INIT_ERROR = None


def initialize_earth_engine():
    """Initialize Earth Engine without forcing browser auth from the web server."""
    global EE_INITIALIZED, EE_INIT_ERROR
    try:
        ee.Initialize(project='ee-05220053jnec')
        EE_INITIALIZED = True
        EE_INIT_ERROR = None
    except Exception:
        # Run `earthengine authenticate` once from a normal terminal if this happens.
        EE_INITIALIZED = False
        EE_INIT_ERROR = 'Google Earth Engine is not authenticated. Run: earthengine authenticate'


initialize_earth_engine()

# ==========================================================
# FLASK APP
# ==========================================================

app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    """Allow the React dashboard to request the prediction tile URL."""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# ==========================================================
# LOAD STATIC ASSETS
# ==========================================================

aoi = ee.FeatureCollection(
    'projects/ee-05220053jnec/assets/BHUTAN_WGS84'
)

trainingpoints = ee.FeatureCollection(
    'projects/ee-05220053jnec/assets/TS_Balanced_5k'
)

# ==========================================================
# PREPARE TRAIN / TEST ONCE
# ==========================================================

finalPoints = trainingpoints.randomColumn('split_random')

trainPointsPart = finalPoints.filter(
    ee.Filter.lt('split_random', 0.7)
)

testPointsPart = finalPoints.filter(
    ee.Filter.gte('split_random', 0.7)
)

# ==========================================================
# ROUTE : HOME PAGE
# ==========================================================

@app.route('/')
def index():
    return render_template('index.html')

# ==========================================================
# ROUTE : GENERATE DYNAMIC FIRE MAP
# ==========================================================

@app.route('/generate_map', methods=['GET'])
def generate_map():
    if not EE_INITIALIZED:
        return jsonify({
            'error': EE_INIT_ERROR or 'Google Earth Engine is not initialized.'
        }), 503

    # ======================================================
    # GET DYNAMIC DATES FROM USER
    # ======================================================

    startDate = request.args.get('start', '2024-11-01')
    endDate = request.args.get('end', '2024-12-31')

    try:
        selected_start = ee.Date(startDate)
        selected_end = ee.Date(endDate)
        optical_start = selected_start.advance(-30, 'day')
        optical_end = selected_end.advance(30, 'day')

        # ==================================================
        # DEM + TERRAIN
        # ==================================================

        DEM = ee.Image('USGS/SRTMGL1_003').clip(aoi)
        elevation = DEM.select('elevation')
        SLOPE = ee.Terrain.slope(elevation).rename('Slope')
        ASPECT = ee.Terrain.aspect(elevation).rename('Aspect')
        HILLSHADE = ee.Terrain.hillshade(elevation).rename('Hillshade')
        curvature = elevation.convolve(
            ee.Kernel.laplacian8()
        ).rename('Curvature')

        # ==================================================
        # CHIRPS RAINFALL
        # ==================================================

        rainfall_col = (
            ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
            .filterDate(startDate, endDate)
            .select('precipitation')
        )
        rainfall_fallback = ee.Image.constant(0).rename('precipitation').clip(aoi)
        RAINFALL = ee.Image(
            ee.Algorithms.If(
                rainfall_col.size().gt(0),
                rainfall_col.mean().clip(aoi).rename('precipitation'),
                rainfall_fallback,
            )
        )

        # ==================================================
        # GCOM-C TEMPERATURE
        # ==================================================

        gcom_col = (
            ee.ImageCollection("JAXA/GCOM-C/L3/LAND/LST/V3")
            .filterDate(startDate, endDate)
            .filter(ee.Filter.eq('SATELLITE_DIRECTION', 'D'))
        )
        temp_fallback = ee.Image.constant(20).rename('Surface_Temp_C').clip(aoi)
        Temp = ee.Image(
            ee.Algorithms.If(
                gcom_col.size().gt(0),
                gcom_col.mean().clip(aoi).select('LST_AVE')
                .multiply(0.02).subtract(273.15).rename('Surface_Temp_C'),
                temp_fallback,
            )
        )

        # ==================================================
        # LANDSAT OPTICAL INDICES
        # Use a wider +/- 30 day window because a 1-day user
        # range may have no cloud-free Landsat scene.
        # ==================================================

        landsat_col = (
            ee.ImageCollection("LANDSAT/LC09/C02/T1_L2")
            .merge(ee.ImageCollection("LANDSAT/LC08/C02/T1_L2"))
            .filterBounds(aoi)
            .filterDate(optical_start, optical_end)
            .filter(ee.Filter.lt('CLOUD_COVER', 70))
        )

        empty_landsat = ee.Image.constant([0, 0, 0, 0, 0, 0]).rename([
            'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'
        ]).clip(aoi)

        rawImage = ee.Image(
            ee.Algorithms.If(
                landsat_col.size().gt(0),
                landsat_col.median().clip(aoi),
                empty_landsat,
            )
        )

        # ==================================================
        # INDICES
        # ==================================================

        ndvi = rawImage.normalizedDifference(
            ['SR_B5', 'SR_B4']
        ).rename('NDVI')

        ndmi = rawImage.normalizedDifference(
            ['SR_B5', 'SR_B6']
        ).rename('NDMI')

        nbr = rawImage.normalizedDifference(
            ['SR_B5', 'SR_B7']
        ).rename('NBR')

        bsi = rawImage.expression(
            '((B6 + B4) - (B5 + B2)) / ((B6 + B4) + (B5 + B2) + 14545.45)',
            {
                'B2': rawImage.select('SR_B2'),
                'B4': rawImage.select('SR_B4'),
                'B5': rawImage.select('SR_B5'),
                'B6': rawImage.select('SR_B6')
            }
        ).rename('BSI')

        # ==================================================
        # STACK DATASET
        # ==================================================

        dataset = ee.Image.cat([
            elevation,
            SLOPE,
            ASPECT,
            HILLSHADE,
            curvature,
            RAINFALL,
            Temp,
            ndvi,
            ndmi,
            nbr,
            bsi
        ]).unmask(0)

        bands = dataset.bandNames()

        # ==================================================
        # TRAIN MODEL
        # ==================================================

        trainingPartition = dataset.sampleRegions(
            collection=trainPointsPart,
            properties=['value'],
            scale=30,
            tileScale=16
        )

        classifier = ee.Classifier.smileRandomForest(100).train(
            features=trainingPartition,
            classProperty='value',
            inputProperties=bands
        )

        # ==================================================
        # CLASSIFICATION
        # ==================================================

        classifiedMap = dataset.classify(classifier).clip(aoi)

        # ==================================================
        # VISUALIZATION
        # ==================================================

        fireRiskVis = {
            'min': 0,
            'max': 1,
            'palette': ['#1a9850', '#d73027']
        }

        map_id = classifiedMap.getMapId(fireRiskVis)

        # ==================================================
        # RETURN TILE URL
        # ==================================================

        return jsonify({
            'tile_url': map_id['tile_fetcher'].url_format,
            'source': 'Google Earth Engine',
            'layer_name': 'Predicted Risk Map',
            'start': startDate,
            'end': endDate,
        })
    except Exception as exc:
        return jsonify({
            'error': f'Prediction map generation failed: {exc}'
        }), 500

# ==========================================================
# RUN FLASK
# ==========================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
