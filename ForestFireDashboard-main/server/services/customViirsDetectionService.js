const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const moment = require('moment');

const VIIRS_ROOT = path.resolve(__dirname, '../../..');
const SCRIPT_PATH = path.join(VIIRS_ROOT, 'scripts', 'fetch_and_detect_bhutan_viirs.py');
const OUTPUT_ROOT = path.join(VIIRS_ROOT, 'outputs', 'dashboard_viirs_queries');
const NRT_OUTPUT_DIR = path.join(VIIRS_ROOT, 'outputs', 'viirs_nrt');
const TRUE_NRT_VERSION = 'BHUTAN_TRUE_I_BAND_NRT';

function satelliteLabel(value) {
  const labels = {
    suomi_npp: 'NPP',
    noaa20: 'NOAA20',
    noaa21: 'NOAA21',
  };
  return labels[value] || value || 'NPP';
}

function parseCsvLine(line) {
  const values = [];
  let current = '';
  let inQuotes = false;

  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    const next = line[i + 1];

    if (char === '"' && next === '"') {
      current += '"';
      i += 1;
    } else if (char === '"') {
      inQuotes = !inQuotes;
    } else if (char === ',' && !inQuotes) {
      values.push(current);
      current = '';
    } else {
      current += char;
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

function parseGranuleDate(key) {
  if (!key || !key.includes('.')) {
    return { acq_date: moment.utc().format('YYYY-MM-DD'), acq_time: null };
  }

  const [yearDay, hhmm] = key.split('.');
  const year = Number(yearDay.slice(0, 4));
  const dayOfYear = Number(yearDay.slice(4));
  const date = moment.utc(`${year}-01-01`).add(dayOfYear - 1, 'days');

  return {
    acq_date: date.format('YYYY-MM-DD'),
    acq_time: Number(hhmm),
  };
}

function toConfidence(row) {
  const finalConfidence = Number(row.final_confidence_score);
  if (Number.isFinite(finalConfidence)) {
    return Math.min(99, Math.max(1, Math.round(finalConfidence)));
  }

  const threshold = Number(row.threshold);
  const m13Log = Number(row.M13_log);

  if (!Number.isFinite(threshold) || threshold <= 0 || !Number.isFinite(m13Log)) {
    return 75;
  }

  return Math.min(99, Math.max(50, Math.round((m13Log / threshold) * 75)));
}

function parseIsoAcquisitionTime(value) {
  const parsed = moment.utc(value);
  if (!value || !parsed.isValid()) {
    return { acq_date: moment.utc().format('YYYY-MM-DD'), acq_time: null };
  }

  return {
    acq_date: parsed.format('YYYY-MM-DD'),
    acq_time: Number(parsed.format('HHmm')),
  };
}

function csvRowToTrueIbandFire(row, id, options = {}) {
  const parsedDate = parseIsoAcquisitionTime(row.first_detection_time || row.last_detection_time);
  const brightness = Number(row.BT4);
  const m13Anomaly = Number(row.M13_anomaly);
  const satellites = row.satellite_sources || row.satellite || 'VIIRS';
  const context = row.final_context_class || row.fire_context || 'true_i_band';

  return {
    id,
    latitude: Number(row.latitude),
    longitude: Number(row.longitude),
    brightness: Number.isFinite(brightness) ? brightness : null,
    scan: null,
    track: null,
    acq_date: parsedDate.acq_date,
    acq_time: parsedDate.acq_time,
    satellite: String(satellites),
    instrument: 'VIIRS_375M_I_BAND',
    version: options.version || 'BHUTAN_TRUE_I_BAND',
    confidence: toConfidence(row),
    frp: Number.isFinite(m13Anomaly) ? m13Anomaly : null,
    fire_type: String(context),
    created_at: new Date(),
  };
}

function csvRowToFire(row, id, options = {}) {
  if (row.first_detection_time || row.BT4 || row.final_context_class) {
    return csvRowToTrueIbandFire(row, id, options);
  }

  const parsedDate = parseGranuleDate(row.granule_key);
  const brightness = Number(row.M13_log);

  return {
    id,
    latitude: Number(row.latitude),
    longitude: Number(row.longitude),
    brightness: Number.isFinite(brightness) ? brightness : null,
    scan: null,
    track: null,
    acq_date: parsedDate.acq_date,
    acq_time: parsedDate.acq_time,
    satellite: satelliteLabel(row.satellite),
    instrument: row.satellite ? 'VIIRS_NRT_RAW' : 'VIIRS_RAW',
    version: row.satellite ? 'CUSTOM_VIIRS_NRT' : 'CUSTOM_VIIRS',
    confidence: toConfidence(row),
    frp: Number.isFinite(brightness) ? brightness : null,
    fire_type: row.Dzongkhag ? String(row.Dzongkhag) : 'CUSTOM',
    created_at: new Date(),
  };
}

function getRowCount(csvPath) {
  if (!fs.existsSync(csvPath)) {
    return 0;
  }

  const text = fs.readFileSync(csvPath, 'utf8').trim();
  if (!text) {
    return 0;
  }

  const lines = text.split(/\r?\n/).filter(Boolean);
  return Math.max(0, lines.length - 1);
}

function getGeoJsonFeatureCount(geoJsonPath) {
  if (!fs.existsSync(geoJsonPath)) {
    return 0;
  }

  try {
    const parsed = JSON.parse(fs.readFileSync(geoJsonPath, 'utf8'));
    return Array.isArray(parsed.features) ? parsed.features.length : 0;
  } catch {
    return 0;
  }
}

function getProcessedGranuleCount(statePath) {
  if (!fs.existsSync(statePath)) {
    return 0;
  }

  try {
    const parsed = JSON.parse(fs.readFileSync(statePath, 'utf8'));
    return Array.isArray(parsed.processed) ? parsed.processed.length : 0;
  } catch {
    return 0;
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

function getPipelineStatus() {
  const trueHotspotsCsv = path.join(NRT_OUTPUT_DIR, 'fire_detections.csv');
  const legacyHotspotsCsv = path.join(NRT_OUTPUT_DIR, 'viirs_nrt_hotspots.csv');
  const hotspotsCsv = fs.existsSync(trueHotspotsCsv) ? trueHotspotsCsv : legacyHotspotsCsv;
  const trueHotspotsGeoJson = path.join(NRT_OUTPUT_DIR, 'fire_detections.geojson');
  const legacyClustersGeoJson = path.join(NRT_OUTPUT_DIR, 'viirs_nrt_clusters.geojson');
  const clustersGeoJson = fs.existsSync(trueHotspotsGeoJson) ? trueHotspotsGeoJson : legacyClustersGeoJson;
  const stateFile = path.join(NRT_OUTPUT_DIR, 'processed_granules.json');
  const latestMtime = getLatestMtime([hotspotsCsv, clustersGeoJson, stateFile]);
  const now = new Date();
  const ageMinutes = latestMtime ? Math.round((now.getTime() - latestMtime.getTime()) / 60000) : null;
  const expectedIntervalMinutes = 15;

  let status = 'not_started';
  if (latestMtime) {
    status = ageMinutes <= expectedIntervalMinutes * 3 ? 'active' : 'stale';
  }

  return {
    status,
    expectedIntervalMinutes,
    latestOutputUtc: latestMtime ? latestMtime.toISOString() : null,
    ageMinutes,
    nrtHotspotRows: getRowCount(hotspotsCsv),
    nrtClusterCount: getGeoJsonFeatureCount(clustersGeoJson),
    processedGranuleCount: getProcessedGranuleCount(stateFile),
    outputFolder: NRT_OUTPUT_DIR,
  };
}

function validateDateRange(start, end) {
  const startDate = moment.utc(start, 'YYYY-MM-DD', true);
  const endDate = moment.utc(end, 'YYYY-MM-DD', true);

  if (!startDate.isValid() || !endDate.isValid()) {
    throw new Error('Use start and end dates in YYYY-MM-DD format.');
  }

  if (startDate.isAfter(endDate)) {
    throw new Error('Start date must be before or equal to end date.');
  }

  const dayCount = endDate.diff(startDate, 'days') + 1;
  if (dayCount > 45) {
    throw new Error('Please choose a range of 45 days or less.');
  }

  return {
    start: startDate.format('YYYY-MM-DD'),
    end: endDate.clone().add(1, 'day').format('YYYY-MM-DD'),
    displayEnd: endDate.format('YYYY-MM-DD'),
  };
}

function runPythonDetector(start, end, outDir) {
  return new Promise((resolve, reject) => {
    const args = [
      SCRIPT_PATH,
      '--start',
      start,
      '--end',
      end,
      '--out-dir',
      outDir,
      '--max-granules',
      '300',
    ];

    const child = spawn('python', args, {
      cwd: VIIRS_ROOT,
      shell: false,
      windowsHide: true,
    });

    let stdout = '';
    let stderr = '';

    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
    });

    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });

    child.on('error', (error) => {
      reject(error);
    });

    child.on('close', (code) => {
      if (code === 0) {
        resolve({ stdout, stderr });
      } else {
        reject(new Error(`VIIRS detector exited with code ${code}\n${stdout}\n${stderr}`));
      }
    });
  });
}

async function runViirsDetection(startInput, endInput) {
  const range = validateDateRange(startInput, endInput);
  const outDir = path.join(OUTPUT_ROOT, `${range.start}_to_${range.displayEnd}`);
  fs.mkdirSync(outDir, { recursive: true });

  const run = await runPythonDetector(range.start, range.end, outDir);
  const csvPath = path.join(outDir, 'bhutan_fire_hotspots.csv');
  const rows = readCsvRows(csvPath);
  const data = rows
    .map((row, index) => csvRowToFire(row, index))
    .filter((row) => Number.isFinite(row.latitude) && Number.isFinite(row.longitude));

  return {
    count: data.length,
    data,
    csvPath,
    outDir,
    stdout: run.stdout,
    stderr: run.stderr,
  };
}

function parseViirsHotspotCsv(csvPath) {
  const normalizedPath = String(csvPath).toLowerCase();
  const options = normalizedPath.includes('viirs_nrt')
    ? { version: TRUE_NRT_VERSION }
    : {};
  const rows = readCsvRows(csvPath);
  return rows
    .map((row, index) => csvRowToFire(row, index, options))
    .map(({ id, ...record }) => record)
    .filter((row) => Number.isFinite(row.latitude) && Number.isFinite(row.longitude));
}

module.exports = {
  getPipelineStatus,
  parseViirsHotspotCsv,
  runViirsDetection,
};
