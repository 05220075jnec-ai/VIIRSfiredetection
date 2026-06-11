import { useEffect, useRef, useState } from 'react';
import Map from 'ol/Map';
import View from 'ol/View';
import TileLayer from 'ol/layer/Tile';
import VectorLayer from 'ol/layer/Vector';
import OSM from 'ol/source/OSM';
import XYZ from 'ol/source/XYZ';
import VectorSource from 'ol/source/Vector';
import Feature from 'ol/Feature';
import Point from 'ol/geom/Point';
import { fromLonLat } from 'ol/proj';
import { Circle as CircleStyle, Fill, Stroke, Style } from 'ol/style';
import Overlay from 'ol/Overlay';
import GeoJSON from 'ol/format/GeoJSON';
import { fetchBurnSeverityMap, fetchPredictedRiskMap } from '../services/api';
import { BHUTAN_BOUNDS } from '../utils/constants';

const DZONGKHAG_DATA_URL = '/data/bhutan_dzong_web.geojson';
const BHUTAN_BOUNDARY_DATA_URL = '/data/bhutan-boundary.geojson';

const defaultStyle = new Style({
  stroke: new Stroke({ color: 'rgba(59, 130, 246, 0.9)', width: 1.4 }),
  fill: new Fill({ color: 'rgba(30, 64, 175, 0.03)' }),
});

const highlightedStyle = new Style({
  stroke: new Stroke({ color: '#38bdf8', width: 3 }),
  fill: new Fill({ color: 'rgba(56, 189, 248, 0.14)' }),
});

const bhutanBoundaryStyle = [
  new Style({
    stroke: new Stroke({ color: 'rgba(0, 0, 0, 0.75)', width: 6 }),
  }),
  new Style({
    stroke: new Stroke({ color: '#f8fafc', width: 3 }),
  }),
];

const bhutanCenter = [
  (BHUTAN_BOUNDS.minLon + BHUTAN_BOUNDS.maxLon) / 2,
  (BHUTAN_BOUNDS.minLat + BHUTAN_BOUNDS.maxLat) / 2,
];

const FIRE_CONTEXT_STYLES = {
  forest_fire: { color: '#ef4444', label: 'Forest fire' },
  agricultural_burning: { color: '#f97316', label: 'Agricultural burning' },
  vegetation_fire: { color: '#ef4444', label: 'Vegetation fire' },
  structure_fire_candidate: { color: '#a855f7', label: 'Structure fire candidate' },
  roof_false_positive: { color: '#94a3b8', label: 'Roof false positive' },
  possible_roof_false_positive: { color: '#64748b', label: 'Possible roof false positive' },
  unknown_thermal_anomaly: { color: '#ec4899', label: 'Unknown thermal anomaly' },
};

function formatContext(value) {
  const context = value || 'unknown_thermal_anomaly';
  return FIRE_CONTEXT_STYLES[context]?.label || context.replaceAll('_', ' ');
}

function normalizeDzongkhagName(value) {
  return String(value || '').toLowerCase().replace(/[^a-z]/g, '');
}

function getDzongkhagName(feature) {
  return feature?.get('Dzongkhag')
    || feature?.get('adm1_name')
    || feature?.get('DZONGKHA')
    || feature?.get('NAM')
    || 'Unknown dzongkhag';
}

function styleForFire(fire) {
  const context = fire.fire_type || 'unknown_thermal_anomaly';
  const color = FIRE_CONTEXT_STYLES[context]?.color || '#ec4899';
  const confidence = Number(fire.confidence) || 50;
  const radius = confidence >= 90 ? 4 : 3.25;

  return new Style({
    image: new CircleStyle({
      radius,
      fill: new Fill({ color }),
      stroke: new Stroke({ color: '#111827', width: 0.9 }),
    }),
  });
}

function findDzongkhagName(coordinate, dzongkhagSource) {
  const match = dzongkhagSource.getFeatures().find((feature) => {
    const geometry = feature.getGeometry();
    return geometry && geometry.intersectsCoordinate(coordinate);
  });

  return getDzongkhagName(match);
}

function buildPopupContent(fire, coordinate, dzongkhagSource) {
  const frp = Number(fire.frp) || 0;
  let intensity = 'Low';
  if (frp >= 60) intensity = 'Extreme';
  else if (frp >= 30) intensity = 'High';
  else if (frp >= 10) intensity = 'Moderate';

  return {
    dzongkhag: findDzongkhagName(coordinate, dzongkhagSource),
    context: formatContext(fire.fire_type),
    rawContext: fire.fire_type || 'unknown_thermal_anomaly',
    date: fire.acq_date,
    time: fire.acq_time,
    brightness: fire.brightness,
    frp,
    confidence: fire.confidence || 50,
    intensity,
    satellite: fire.satellite,
    instrument: fire.instrument,
  };
}

function FireMap({ fireData, riskStart, riskEnd, selectedDzongkhag, onDzongkhagClick }) {
  const mapRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const popupRef = useRef(null);
  const [popupContent, setPopupContent] = useState(null);
  const [baseMap, setBaseMap] = useState('satellite_hybrid');
  const [showRiskMap, setShowRiskMap] = useState(false);
  const [riskMapStatus, setRiskMapStatus] = useState('idle');
  const [riskMapMessage, setRiskMapMessage] = useState('');
  const [showBurnSeverity, setShowBurnSeverity] = useState(false);
  const [burnSeverityStatus, setBurnSeverityStatus] = useState('idle');
  const [burnSeverityMessage, setBurnSeverityMessage] = useState('');
  const [showDzongkhags, setShowDzongkhags] = useState(true);
  const [showBoundary, setShowBoundary] = useState(true);

  useEffect(() => {
    if (mapInstanceRef.current) return;

    const vectorSource = new VectorSource();
    const dzongkhagSource = new VectorSource();
    const bhutanBoundarySource = new VectorSource();

    const satelliteLayer = new TileLayer({
      source: new XYZ({
        url: 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        maxZoom: 19,
        crossOrigin: 'anonymous',
      }),
      visible: true,
    });
    const satelliteLabelsLayer = new TileLayer({
      source: new XYZ({
        url: 'https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
        maxZoom: 19,
        crossOrigin: 'anonymous',
      }),
      visible: true,
    });
    const osmLayer = new TileLayer({
      source: new OSM(),
      visible: true,
    });
    const riskLayer = new TileLayer({
      source: null,
      opacity: 0.55,
      visible: false,
    });
    const burnSeverityLayer = new TileLayer({
      source: null,
      opacity: 0.62,
      visible: false,
    });
    const vectorLayer = new VectorLayer({ source: vectorSource });
    const dzongkhagLayer = new VectorLayer({
      source: dzongkhagSource,
      style: defaultStyle,
    });
    const bhutanBoundaryLayer = new VectorLayer({
      source: bhutanBoundarySource,
      style: bhutanBoundaryStyle,
    });

    const map = new Map({
      target: mapRef.current,
      layers: [
        satelliteLayer,
        osmLayer,
        riskLayer,
        burnSeverityLayer,
        satelliteLabelsLayer,
        dzongkhagLayer,
        bhutanBoundaryLayer,
        vectorLayer,
      ],
      view: new View({
        center: fromLonLat(bhutanCenter),
        zoom: 8,
        minZoom: 6,
        maxZoom: 18,
      }),
    });

    const popup = new Overlay({
      element: popupRef.current,
      positioning: 'bottom-left',
      stopEvent: true,
      offset: [10, -10],
    });
    map.addOverlay(popup);

    map.on('pointermove', (evt) => {
      const feature = map.forEachFeatureAtPixel(evt.pixel, (f) => f);
      map.getTargetElement().style.cursor = feature ? 'pointer' : '';
    });

    map.on('click', (evt) => {
      const fireFeature = map.forEachFeatureAtPixel(
        evt.pixel,
        (feature) => (feature.get('fireData') ? feature : null),
        { hitTolerance: 6 },
      );

      if (fireFeature) {
        const fire = fireFeature.get('fireData');
        setPopupContent(buildPopupContent(fire, evt.coordinate, dzongkhagSource));
        popup.setPosition(evt.coordinate);
        popupRef.current.style.display = 'block';
        return;
      }

      popupRef.current.style.display = 'none';
      const dzongkhagFeature = map.forEachFeatureAtPixel(evt.pixel, (feature, layer) => {
        if (layer === dzongkhagLayer) return feature;
        return null;
      }, { hitTolerance: 4 });

      if (dzongkhagFeature) {
        const dzongkhagName = getDzongkhagName(dzongkhagFeature);
        if (onDzongkhagClick) {
          onDzongkhagClick(dzongkhagName);
        }
      }
    });

    map.on('moveend', () => {
      map.getView().getZoom();
    });

    mapInstanceRef.current = {
      map,
      vectorSource,
      vectorLayer,
      dzongkhagLayer,
      dzongkhagSource,
      bhutanBoundaryLayer,
      bhutanBoundarySource,
      satelliteLayer,
      satelliteLabelsLayer,
      osmLayer,
      riskLayer,
      burnSeverityLayer,
    };

    const parser = new GeoJSON();
    Promise.all([
      fetch(DZONGKHAG_DATA_URL).then(res => res.json()),
      fetch(BHUTAN_BOUNDARY_DATA_URL).then(res => res.json()),
    ])
      .then(([dzongkhagData, bhutanBoundaryData]) => {
        const dzongkhagFeatures = parser.readFeatures(dzongkhagData, {
          dataProjection: 'EPSG:4326',
          featureProjection: 'EPSG:3857',
        });
        dzongkhagSource.addFeatures(dzongkhagFeatures);

        const boundaryFeatures = parser.readFeatures(bhutanBoundaryData, {
          dataProjection: 'EPSG:4326',
          featureProjection: 'EPSG:3857',
        });
        bhutanBoundarySource.addFeatures(boundaryFeatures);
      })
      .catch(err => console.error('Failed to load dzongkhag data:', err));

    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.map.setTarget(null);
        mapInstanceRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!mapInstanceRef.current) return;
    const { satelliteLayer, satelliteLabelsLayer, osmLayer } = mapInstanceRef.current;
    satelliteLayer.setVisible(baseMap === 'satellite_hybrid');
    satelliteLabelsLayer.setVisible(baseMap === 'satellite_hybrid');
    osmLayer.setVisible(baseMap === 'osm');
  }, [baseMap]);

  useEffect(() => {
    if (!mapInstanceRef.current) return;
    const { riskLayer } = mapInstanceRef.current;

    if (!showRiskMap) {
      riskLayer.setVisible(false);
      setRiskMapStatus('idle');
      setRiskMapMessage('');
      return;
    }

    let cancelled = false;
    setRiskMapStatus('loading');
    setRiskMapMessage('');

    fetchPredictedRiskMap(riskStart, riskEnd)
      .then((result) => {
        if (cancelled) return;
        riskLayer.setSource(new XYZ({
          url: result.tile_url,
          crossOrigin: 'anonymous',
        }));
        riskLayer.setVisible(true);
        setRiskMapStatus('ready');
        setRiskMapMessage('Risk map loaded');
      })
      .catch((error) => {
        console.error('Failed to load predicted risk map:', error);
        if (cancelled) return;
        riskLayer.setVisible(false);
        setRiskMapStatus('error');
        setRiskMapMessage(error.message || 'Prediction server unavailable');
      });

    return () => {
      cancelled = true;
    };
  }, [showRiskMap, riskStart, riskEnd]);

  useEffect(() => {
    if (!mapInstanceRef.current) return;
    const { burnSeverityLayer } = mapInstanceRef.current;

    if (!showBurnSeverity) {
      burnSeverityLayer.setVisible(false);
      setBurnSeverityStatus('idle');
      setBurnSeverityMessage('');
      return;
    }

    let cancelled = false;
    setBurnSeverityStatus('loading');
    setBurnSeverityMessage('');

    fetchBurnSeverityMap(riskStart, riskEnd)
      .then((result) => {
        if (cancelled) return;
        burnSeverityLayer.setSource(new XYZ({
          url: result.tile_url,
          crossOrigin: 'anonymous',
        }));
        burnSeverityLayer.setVisible(true);
        setBurnSeverityStatus('ready');
        setBurnSeverityMessage('Burn severity loaded');
      })
      .catch((error) => {
        console.error('Failed to load burn severity map:', error);
        if (cancelled) return;
        burnSeverityLayer.setVisible(false);
        setBurnSeverityStatus('error');
        setBurnSeverityMessage(error.message || 'Burn severity server unavailable');
      });

    return () => {
      cancelled = true;
    };
  }, [showBurnSeverity, riskStart, riskEnd]);

  useEffect(() => {
    if (!mapInstanceRef.current) return;
    mapInstanceRef.current.dzongkhagLayer.setVisible(showDzongkhags);
  }, [showDzongkhags]);

  useEffect(() => {
    if (!mapInstanceRef.current) return;
    mapInstanceRef.current.bhutanBoundaryLayer.setVisible(showBoundary);
  }, [showBoundary]);

  useEffect(() => {
    if (!mapInstanceRef.current) return;

    const { dzongkhagSource, map } = mapInstanceRef.current;
    const features = dzongkhagSource.getFeatures();

    features.forEach((feature) => {
      const name = getDzongkhagName(feature);
      if (
        selectedDzongkhag
        && normalizeDzongkhagName(name) === normalizeDzongkhagName(selectedDzongkhag)
      ) {
        feature.setStyle(highlightedStyle);
      } else {
        feature.setStyle(defaultStyle);
      }
    });

    if (selectedDzongkhag) {
      const selectedFeature = features.find(
        f => normalizeDzongkhagName(getDzongkhagName(f)) === normalizeDzongkhagName(selectedDzongkhag),
      );
      if (selectedFeature) {
        const extent = selectedFeature.getGeometry().getExtent();
        map.getView().fit(extent, {
          padding: [50, 50, 50, 50],
          maxZoom: 12,
          duration: 500,
        });
      }
    } else {
      map.getView().animate({
        center: fromLonLat(bhutanCenter),
        zoom: 8,
        duration: 500,
      });
    }
  }, [selectedDzongkhag]);

  useEffect(() => {
    if (!mapInstanceRef.current) return;

    const { vectorSource } = mapInstanceRef.current;
    const features = vectorSource.getFeatures().filter(f => !f.get('fireData'));

    const fireFeatures = fireData.map((fire) => {
      const feature = new Feature({
        geometry: new Point(fromLonLat([fire.longitude, fire.latitude])),
        fireData: fire,
      });

      feature.setStyle(styleForFire(fire));

      return feature;
    });

    vectorSource.clear();
    vectorSource.addFeatures([...features, ...fireFeatures]);
  }, [fireData]);

  return (
    <div className="map-container">
      <div ref={mapRef} style={{ height: '100%', width: '100%' }} />
      <div className="map-tools" aria-label="Map controls">
        <div className="tool-row">
          <button
            type="button"
            className={baseMap === 'satellite_hybrid' ? 'active' : ''}
            onClick={() => setBaseMap('satellite_hybrid')}
          >
            Satellite Hybrid
          </button>
          <button
            type="button"
            className={baseMap === 'osm' ? 'active' : ''}
            onClick={() => setBaseMap('osm')}
          >
            Streets
          </button>
        </div>
        <label>
          <input
            type="checkbox"
            checked={showBoundary}
            onChange={(event) => setShowBoundary(event.target.checked)}
          />
          Boundary
        </label>
        <label>
          <input
            type="checkbox"
            checked={showRiskMap}
            onChange={(event) => setShowRiskMap(event.target.checked)}
          />
          Predicted Risk Map
        </label>
        <label>
          <input
            type="checkbox"
            checked={showBurnSeverity}
            onChange={(event) => setShowBurnSeverity(event.target.checked)}
          />
          Burn Severity
        </label>
        <label>
          <input
            type="checkbox"
            checked={showDzongkhags}
            onChange={(event) => setShowDzongkhags(event.target.checked)}
          />
          Dzongkhags
        </label>
        {riskMapStatus === 'loading' && <span className="risk-status">Generating risk map...</span>}
        {riskMapStatus === 'ready' && <span className="risk-status">{riskMapMessage}</span>}
        {riskMapStatus === 'error' && <span className="risk-status error">{riskMapMessage}</span>}
        {burnSeverityStatus === 'loading' && <span className="risk-status">Generating burn severity...</span>}
        {burnSeverityStatus === 'ready' && <span className="risk-status">{burnSeverityMessage}</span>}
        {burnSeverityStatus === 'error' && <span className="risk-status error">{burnSeverityMessage}</span>}
      </div>
      <div className="legend" aria-label="Map legend">
        <h4>Legend</h4>
        {!showRiskMap && !showBurnSeverity && (
          <>
            <div className="legend-section-title">Fire detections</div>
            <div className="legend-item">
              <span className="legend-color round" style={{ backgroundColor: '#ef4444' }} />
              <span>Forest / vegetation fire</span>
            </div>
            <div className="legend-item">
              <span className="legend-color round" style={{ backgroundColor: '#f97316' }} />
              <span>Agricultural burning</span>
            </div>
          </>
        )}
        {showRiskMap && (
          <div className="legend-section">
            <div className="legend-section-title">Predicted risk map</div>
            <div className="legend-item">
              <span className="legend-color round" style={{ backgroundColor: '#1a9850' }} />
              <span>Low risk</span>
            </div>
            <div className="legend-item">
              <span className="legend-color round" style={{ backgroundColor: '#fee08b' }} />
              <span>Medium risk</span>
            </div>
            <div className="legend-item">
              <span className="legend-color round" style={{ backgroundColor: '#d73027' }} />
              <span>High risk</span>
            </div>
          </div>
        )}
        {showBurnSeverity && (
          <div className="legend-section">
            <div className="legend-section-title">Burn severity (dNBR)</div>
            <div className="legend-item">
              <span className="legend-color round" style={{ backgroundColor: 'blue' }} />
              <span>Enhanced regrowth</span>
            </div>
            <div className="legend-item">
              <span className="legend-color round" style={{ backgroundColor: 'green' }} />
              <span>Unburned / low change</span>
            </div>
            <div className="legend-item">
              <span className="legend-color round" style={{ backgroundColor: 'yellow' }} />
              <span>Low severity</span>
            </div>
            <div className="legend-item">
              <span className="legend-color round" style={{ backgroundColor: 'orange' }} />
              <span>Moderate severity</span>
            </div>
            <div className="legend-item">
              <span className="legend-color round" style={{ backgroundColor: 'red' }} />
              <span>High severity</span>
            </div>
          </div>
        )}
      </div>
      <div ref={popupRef} className="ol-popup" style={{ display: 'none' }}>
        {popupContent && (
          <div className="fire-popup">
            <div className="popup-header">
              <h4>{popupContent.context}</h4>
              <button
                type="button"
                aria-label="Close popup"
                onClick={() => {
                  popupRef.current.style.display = 'none';
                  setPopupContent(null);
                }}
              >
                x
              </button>
            </div>
            <p><strong>Dzongkhag:</strong> {popupContent.dzongkhag}</p>
            <p><strong>Date:</strong> {popupContent.date}</p>
            <p><strong>Time:</strong> {popupContent.time}</p>
            <p><strong>Brightness:</strong> {Number(popupContent.brightness).toFixed(1)} K</p>
            <p><strong>M13 anomaly:</strong> {Number(popupContent.frp).toFixed(2)}</p>
            <p><strong>Confidence:</strong> {popupContent.confidence}%</p>
            <p><strong>Intensity:</strong> {popupContent.intensity}</p>
            <p><strong>Satellite:</strong> {popupContent.satellite} ({popupContent.instrument})</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default FireMap;
