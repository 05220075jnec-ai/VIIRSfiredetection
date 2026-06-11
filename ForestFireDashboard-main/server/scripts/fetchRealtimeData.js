require('dotenv').config({ path: '../.env' });
const { sequelize } = require('../models/FireData');
const FireData = require('../models/FireData').FireData;
const nasaFirmsService = require('../services/nasaFirmsService');

const FETCH_INTERVAL_MS = 15 * 60 * 1000;

function parseConfidence(confidence) {
  if (!confidence) return null;
  if (typeof confidence === 'number') return confidence;

  const confMap = {
    'l': 25,
    'n': 50,
    'h': 75
  };

  return confMap[confidence.toLowerCase()] || 50;
}

async function fetchAndSaveData() {
  console.log(`[${new Date().toISOString()}] Fetching latest fire data...`);

  try {
    const nasaData = await nasaFirmsService.fetchLatestData(1);

    if (nasaData.length === 0) {
      console.log(`[${new Date().toISOString()}] No new fire data available`);
      return;
    }

    const records = nasaData.map(fire => {
      const brightness = fire.brightness || fire.bright_ti4 || null;
      const confidence = parseConfidence(fire.confidence);

      return {
        latitude: parseFloat(fire.latitude),
        longitude: parseFloat(fire.longitude),
        brightness: brightness ? parseFloat(brightness) : null,
        scan: fire.scan ? parseFloat(fire.scan) : null,
        track: fire.track ? parseFloat(fire.track) : null,
        acq_date: fire.acq_date,
        acq_time: fire.acq_time ? parseInt(fire.acq_time) : null,
        satellite: fire.satellite || null,
        instrument: fire.instrument || null,
        version: fire.version || null,
        confidence: confidence,
        frp: fire.frp ? parseFloat(fire.frp) : null,
        fire_type: fire.type || fire.daynight || null,
        created_at: new Date()
      };
    });

    try {
      const result = await FireData.bulkCreate(records, {
        ignoreDuplicates: true
      });
      console.log(`[${new Date().toISOString()}] Saved ${result.length} new records`);
    } catch (error) {
      if (error.name === 'SequelizeUniqueConstraintError') {
        console.log(`[${new Date().toISOString()}] Duplicate records skipped`);
      } else {
        throw error;
      }
    }
  } catch (error) {
    console.error(`[${new Date().toISOString()}] Error fetching data:`, error.message);
  }
}

async function startRealtimeFetcher() {
  try {
    await sequelize.authenticate();
    console.log('Database connection established.');

    await sequelize.sync({ alter: true });
    console.log('Database synchronized.');

    console.log(`Starting real-time fire data fetcher...`);
    console.log(`Fetch interval: ${FETCH_INTERVAL_MS / 60000} minutes`);

    await fetchAndSaveData();

    setInterval(fetchAndSaveData, FETCH_INTERVAL_MS);
  } catch (error) {
    console.error('Failed to start real-time fetcher:', error);
    process.exit(1);
  }
}

startRealtimeFetcher();
