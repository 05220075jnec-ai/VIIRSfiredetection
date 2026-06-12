require('dotenv').config({ path: '../.env' });

const path = require('path');
const { FireData, sequelize } = require('../models/FireData');
const { MODIS_VERSION, parseModisHotspotCsv } = require('../services/modisDetectionService');

async function main() {
  const defaultCsv = path.resolve(__dirname, '../../../../outputs/modis_detector_test/modis_hotspot.csv');
  const csvPath = process.argv[2] ? path.resolve(process.argv[2]) : defaultCsv;

  try {
    await sequelize.authenticate();
    await sequelize.sync({ alter: true });

    const records = parseModisHotspotCsv(csvPath);
    if (records.length === 0) {
      console.log(`No MODIS hotspot rows found in: ${csvPath}`);
      process.exit(0);
    }

    const imported = await sequelize.transaction(async (transaction) => {
      await FireData.destroy({
        where: { version: MODIS_VERSION },
        transaction,
      });
      return FireData.bulkCreate(records, {
        ignoreDuplicates: true,
        transaction,
      });
    });

    console.log(`MODIS hotspot CSV: ${csvPath}`);
    console.log(`Rows read: ${records.length}`);
    console.log(`Rows inserted: ${imported.length}`);
    process.exit(0);
  } catch (error) {
    console.error('MODIS hotspot import failed:', error);
    process.exit(1);
  }
}

main();
