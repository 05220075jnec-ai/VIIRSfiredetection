require('dotenv').config({ path: '../.env' });

const path = require('path');
const { FireData, sequelize } = require('../models/FireData');
const { parseViirsHotspotCsv } = require('../services/customViirsDetectionService');

async function main() {
  const defaultCsv = path.resolve(__dirname, '../../../outputs/viirs_nrt/viirs_nrt_hotspots.csv');
  const csvPath = process.argv[2] ? path.resolve(process.argv[2]) : defaultCsv;

  try {
    await sequelize.authenticate();
    await sequelize.sync({ alter: true });

    const records = parseViirsHotspotCsv(csvPath);
    if (records.length === 0) {
      console.log(`No custom VIIRS hotspot rows found in: ${csvPath}`);
      process.exit(0);
    }

    const imported = await FireData.bulkCreate(records, { ignoreDuplicates: true });
    console.log(`Custom VIIRS CSV: ${csvPath}`);
    console.log(`Rows read: ${records.length}`);
    console.log(`Rows inserted or accepted by database: ${imported.length}`);
    process.exit(0);
  } catch (error) {
    console.error('Custom VIIRS import failed:', error);
    process.exit(1);
  }
}

main();
