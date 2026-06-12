const fs = require('fs');
const moment = require('moment');
const path = require('path');

const MODIS_VERSION = 'BHUTAN_MODIS_CONTEXTUAL_V1';
const MODIS_NRT_OUTPUT_DIR = path.resolve(__dirname, '../../../../outputs/modis_nrt');

function parseCsvLine(line) {
  const values = [];
  let current = '';
  let inQuotes = false;

  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    const nextCharacter = line[index + 1];

    if (character === '"' && nextCharacter === '"') {
      current += '"';
      index += 1;
    } else if (character === '"') {
      inQuotes = !inQuotes;
    } else if (character === ',' && !inQuotes) {
      values.push(current);
      current = '';
    } else {
      current += character;
    }
  }

  values.push(current);
  return values;
}

function readCsvRows(csvPath) {
  if (!fs.existsSync(csvPath)) {
    return [];
  }

  const text = fs.readFileSync(csvPath, 'utf8').trim();
  if (!text) {
    return [];
  }

  const lines = text.split(/\r?\n/);
  const headers = parseCsvLine(lines[0]);

  return lines.slice(1).filter(Boolean).map((line) => {
    const values = parseCsvLine(line);
    return Object.fromEntries(headers.map((header, index) => [header, values[index] ?? '']));
  });
}

function finiteNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseAcquisition(row) {
  const timestamp = moment.utc(row.acquisition_time || row.first_detection_time);
  if (timestamp.isValid()) {
    return {
      acq_date: timestamp.format('YYYY-MM-DD'),
      acq_time: Number(timestamp.format('HHmm')),
    };
  }

  const time = String(row.acq_time || '').padStart(4, '0');
  return {
    acq_date: row.acq_date,
    acq_time: /^\d{4}$/.test(time) ? Number(time) : null,
  };
}

function modisRowToFireData(row) {
  const acquisition = parseAcquisition(row);
  const confidence = finiteNumber(row.final_confidence_score ?? row.confidence);
  const brightness = finiteNumber(row.T4);
  const anomaly = finiteNumber(row.T4_minus_T11);

  return {
    latitude: finiteNumber(row.latitude),
    longitude: finiteNumber(row.longitude),
    brightness,
    scan: null,
    track: null,
    acq_date: acquisition.acq_date,
    acq_time: acquisition.acq_time,
    satellite: row.satellite || row.satellite_sources || 'MODIS',
    instrument: row.instrument || 'MODIS_1KM',
    version: MODIS_VERSION,
    confidence: confidence === null ? 75 : Math.min(99, Math.max(1, Math.round(confidence))),
    frp: anomaly,
    fire_type: row.final_context_class || row.fire_type || 'unknown_thermal_anomaly',
    created_at: new Date(),
  };
}

function parseModisHotspotCsv(csvPath) {
  return readCsvRows(csvPath)
    .map(modisRowToFireData)
    .filter((row) => (
      Number.isFinite(row.latitude)
      && Number.isFinite(row.longitude)
      && row.acq_date
    ));
}

function readJsonFile(filePath) {
  if (!fs.existsSync(filePath)) {
    return null;
  }
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (error) {
    return null;
  }
}

function getLatestMtime(paths) {
  const times = paths
    .filter((filePath) => fs.existsSync(filePath))
    .map((filePath) => fs.statSync(filePath).mtime);
  if (times.length === 0) {
    return null;
  }
  return new Date(Math.max(...times.map((time) => time.getTime())));
}

function getProcessedGranuleCount(stateFile) {
  const state = readJsonFile(stateFile);
  return Array.isArray(state?.processed) ? state.processed.length : 0;
}

function getModisPipelineStatus() {
  const hotspotsCsv = path.join(MODIS_NRT_OUTPUT_DIR, 'modis_hotspot.csv');
  const hotspotsGeoJson = path.join(MODIS_NRT_OUTPUT_DIR, 'modis_hotspot.geojson');
  const stateFile = path.join(MODIS_NRT_OUTPUT_DIR, 'processed_granules.json');
  const heartbeat = readJsonFile(path.join(MODIS_NRT_OUTPUT_DIR, 'pipeline_status.json'));
  const latestMtime = getLatestMtime([hotspotsCsv, hotspotsGeoJson, stateFile]);
  const now = new Date();
  const ageMinutes = latestMtime ? Math.round((now.getTime() - latestMtime.getTime()) / 60000) : null;
  const heartbeatTime = heartbeat?.updated_utc ? new Date(heartbeat.updated_utc) : null;
  const heartbeatAgeMinutes = heartbeatTime && !Number.isNaN(heartbeatTime.getTime())
    ? Math.round((now.getTime() - heartbeatTime.getTime()) / 60000)
    : null;
  const expectedIntervalMinutes = 15;

  let status = 'not_started';
  if (heartbeatAgeMinutes !== null && heartbeatAgeMinutes <= 2) {
    status = heartbeat?.status === 'error' ? 'error' : 'active';
  } else if (latestMtime) {
    status = ageMinutes <= expectedIntervalMinutes * 3 ? 'active' : 'stale';
  }

  return {
    status,
    phase: heartbeat?.phase || null,
    statusMessage: heartbeat?.message || null,
    heartbeatUtc: heartbeatTime ? heartbeatTime.toISOString() : null,
    workerPid: heartbeat?.worker_pid || null,
    currentCycle: heartbeat?.cycle_id || null,
    expectedIntervalMinutes,
    latestOutputUtc: latestMtime ? latestMtime.toISOString() : null,
    ageMinutes,
    nrtHotspotRows: readCsvRows(hotspotsCsv).length,
    processedGranuleCount: getProcessedGranuleCount(stateFile),
    outputFolder: MODIS_NRT_OUTPUT_DIR,
  };
}

module.exports = {
  MODIS_VERSION,
  getModisPipelineStatus,
  parseModisHotspotCsv,
};
