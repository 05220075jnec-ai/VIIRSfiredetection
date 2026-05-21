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

ee.Authenticate()   # First time only
ee.Initialize(project='ee-05220053jnec')

# ==========================================================
# FLASK APP
# ==========================================================

app = Flask(__name__)

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

    # ======================================================
    # GET DYNAMIC DATES FROM USER
    # ======================================================

    startDate = request.args.get('start', '2024-11-01')
    endDate = request.args.get('end', '2024-12-31')

    # ======================================================
    # DEM + TERRAIN
    # ======================================================

    DEM = ee.Image('USGS/SRTMGL1_003').clip(aoi)

    elevation = DEM.select('elevation')

    SLOPE = ee.Terrain.slope(elevation).rename('Slope')

    ASPECT = ee.Terrain.aspect(elevation).rename('Aspect')

    HILLSHADE = ee.Terrain.hillshade(elevation).rename('Hillshade')

    curvature = elevation.convolve(
        ee.Kernel.laplacian8()
    ).rename('Curvature')

    # ======================================================
    # CHIRPS RAINFALL
    # ======================================================

    RAINFALL = (
        ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
        .filterDate(startDate, endDate)
        .select('precipitation')
        .mean()
        .clip(aoi)
        .rename('precipitation')
    )

    # ======================================================
    # GCOM-C TEMPERATURE
    # ======================================================

    gcomLST = (
        ee.ImageCollection("JAXA/GCOM-C/L3/LAND/LST/V3")
        .filterDate(startDate, endDate)
        .filter(ee.Filter.eq('SATELLITE_DIRECTION', 'D'))
        .mean()
        .clip(aoi)
    )

    Temp = (
        gcomLST.select('LST_AVE')
        .multiply(0.02)
        .subtract(273.15)
        .rename('Surface_Temp_C')
    )

    # ======================================================
    # LANDSAT 9
    # ======================================================

    landsatCol = (
        ee.ImageCollection("LANDSAT/LC09/C02/T1_L2")
        .filterBounds(aoi)
        .filterDate(startDate, endDate)
        .filter(ee.Filter.lt('CLOUD_COVER', 30))
    )

    rawImage = landsatCol.median().clip(aoi)

    # ======================================================
    # INDICES
    # ======================================================

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

    # ======================================================
    # STACK DATASET
    # ======================================================

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
    ])

    bands = dataset.bandNames()

    # ======================================================
    # TRAIN MODEL
    # ======================================================

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

    # ======================================================
    # CLASSIFICATION
    # ======================================================

    classifiedMap = dataset.classify(classifier)

    # ======================================================
    # VISUALIZATION
    # ======================================================

    fireRiskVis = {
        'min': 0,
        'max': 1,
        'palette': ['#d73027', '#1a9850']
    }

    map_id = classifiedMap.getMapId(fireRiskVis)

    # ======================================================
    # RETURN TILE URL
    # ======================================================

    return jsonify({
        'tile_url': map_id['tile_fetcher'].url_format
    })

# ==========================================================
# RUN FLASK
# ==========================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True) 
    
