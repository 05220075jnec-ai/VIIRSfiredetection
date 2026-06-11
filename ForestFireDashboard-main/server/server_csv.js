require('dotenv').config({ path: '../.env' });

const express = require('express');
const cors = require('cors');
const fs = require('fs');
const path = require('path');
const moment = require('moment');
const { getPipelineStatus, runViirsDetection } = require('./services/customViirsDetectionService');

const app = express();
const PORT = process.env.PORT || 3000;
const DEFAULT_CSV = path.resolve(__dirname, '../../outputs/viirs_nrt/viirs_nrt_hotspots.csv');
const CSV_PATH = process.env.CUSTOM_VIIRS_CSV || DEFAULT_CSV;

app.use(cors());
app.use(express.json());

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
    const today = moment.utc();
    return { acq_date: today.format('YYYY-MM-DD'), acq_time: null };
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

function satelliteLabel(value) {
  const labels = {
    suomi_npp: 'NPP',
    noaa20: 'NOAA20',
    noaa21: 'NOAA21',
  };
  return labels[value] || value || 'VIIRS';
}

function csvRowToFire(row, id) {
  const parsedDate = parseGranuleDate(row.granule_key);
  const threshold = Number(row.threshold);
  const m13Log = Number(row.M13_log);
  const confidence = Number.isFinite(threshold) && threshold > 0 && Number.isFinite(m13Log)
    ? Math.min(99, Math.max(50, Math.round((m13Log / threshold) * 75)))
    : 75;

  return {
    id,
    latitude: Number(row.latitude),
    longitude: Number(row.longitude),
    brightness: Number.isFinite(m13Log) ? m13Log : null,
    scan: null,
    track: null,
    acq_date: parsedDate.acq_date,
    acq_time: parsedDate.acq_time,
    satellite: satelliteLabel(row.satellite),
    instrument: 'VIIRS_NRT_RAW',
    version: row.source_data || 'custom-viirs-nrt',
    confidence,
    frp: Number.isFinite(m13Log) ? m13Log : null,
    fire_type: row.Dzongkhag || 'custom_viirs',
    created_at: row.processed_utc || new Date().toISOString(),
  };
}

function loadFireData() {
  return readCsvRows(CSV_PATH)
    .map(csvRowToFire)
    .filter((row) => Number.isFinite(row.latitude) && Number.isFinite(row.longitude));
}

function filterByQuery(data, query) {
  const { date, days, start, end } = query;

  if (start && end) {
    return data.filter((row) => row.acq_date >= start && row.acq_date <= end);
  }

  if (date && days !== undefined && days !== null && days !== '') {
    const daysInt = Number(days);
    if (daysInt === 0) {
      return data;
    }
    const endDate = moment(date, 'YYYY-MM-DD');
    const startDate = endDate.clone().subtract(daysInt - 1, 'days');
    return data.filter((row) => {
      const current = moment(row.acq_date, 'YYYY-MM-DD');
      return current.isSameOrAfter(startDate, 'day') && current.isSameOrBefore(endDate, 'day');
    });
  }

  if (days) {
    const daysInt = Number(days);
    if (daysInt > 0) {
      const startDate = moment().subtract(daysInt, 'days');
      return data.filter((row) => moment(row.acq_date, 'YYYY-MM-DD').isSameOrAfter(startDate, 'day'));
    }
  }

  return data;
}

app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    mode: 'csv',
    csvPath: CSV_PATH,
    timestamp: new Date().toISOString(),
  });
});

app.get('/api/fire-data', (req, res) => {
  try {
    const data = filterByQuery(loadFireData(), req.query);
    res.json({ success: true, count: data.length, data });
  } catch (error) {
    res.status(500).json({
      success: false,
      error: 'Failed to read custom VIIRS CSV',
      message: error.message,
      csvPath: CSV_PATH,
    });
  }
});

app.get('/api/fire-data/pipeline-status', (req, res) => {
  try {
    res.json({
      success: true,
      pipeline: getPipelineStatus(),
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      error: 'Failed to read pipeline status',
      message: error.message,
    });
  }
});

app.post('/api/fire-data/run-viirs', async (req, res) => {
  try {
    const { start, end } = req.body;
    const result = await runViirsDetection(start, end);
    res.json({
      success: true,
      count: result.count,
      data: result.data,
      outputFolder: result.outDir,
      csvPath: result.csvPath,
    });
  } catch (error) {
    console.error('Custom VIIRS detection failed:', error);
    res.status(500).json({
      success: false,
      error: 'Custom VIIRS detection failed',
      message: error.message,
    });
  }
});

app.get('/api/fire-data/hottest-month', (req, res) => {
  const counts = new Map();
  for (const row of loadFireData()) {
    const month = row.acq_date.slice(0, 7);
    counts.set(month, (counts.get(month) || 0) + 1);
  }

  let hottest = null;
  for (const [month, count] of counts.entries()) {
    if (!hottest || count > hottest.count) {
      hottest = { month, count };
    }
  }

  res.json({
    success: true,
    month: hottest ? hottest.month : null,
    count: hottest ? hottest.count : 0,
  });
});

app.listen(PORT, () => {
  console.log(`CSV dashboard server running on http://localhost:${PORT}`);
  console.log(`Reading custom VIIRS detections from: ${CSV_PATH}`);
});
