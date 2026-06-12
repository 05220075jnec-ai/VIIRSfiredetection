const { exec } = require('child_process');
const moment = require('moment');

const NASA_FIRMS_BASE_URL = 'https://firms.modaps.eosdis.nasa.gov/api/area/csv';
const BHUTAN_BBOX = process.env.BHUTAN_BBOX || '88.5,26.5,92.5,28.5';

class NasaFirmsService {
  fetchFireData(source = 'MODIS_NRT', dayRange = 1, date = null) {
    const apiKey = process.env.NASA_API_KEY;

    let url;
    if (date) {
      url = `${NASA_FIRMS_BASE_URL}/${apiKey}/${source}/${BHUTAN_BBOX}/${dayRange}/${date}`;
    } else {
      url = `${NASA_FIRMS_BASE_URL}/${apiKey}/${source}/${BHUTAN_BBOX}/${dayRange}`;
    }

    console.log(`Fetching URL: ${url}`);

    return new Promise((resolve, reject) => {
      exec(`curl -s --max-time 30 "${url}"`, { timeout: 35000 }, (error, stdout, stderr) => {
        if (error) {
          console.error('Curl Error:', error.message);
          reject(error);
          return;
        }
        if (stderr) {
          console.error('Curl stderr:', stderr);
        }
        try {
          const parsedData = this.parseCSV(stdout);
          resolve(parsedData);
        } catch (e) {
          reject(e);
        }
      });
    });
  }

  parseCSV(csvData) {
    const lines = csvData.trim().split('\n');
    if (lines.length < 2) return [];

    const headers = lines[0].split(',');
    const fireDataList = [];

    for (let i = 1; i < lines.length; i++) {
      const values = lines[i].split(',');
      if (values.length === headers.length) {
        const fireData = {};
        headers.forEach((header, index) => {
          fireData[header.trim()] = values[index] ? values[index].trim() : null;
        });
        fireDataList.push(fireData);
      }
    }

    return fireDataList;
  }

  async fetchHistoricalData(days = 30, maxRetries = 3) {
    const allData = [];
    const source = 'MODIS_NRT';

    console.log(`Using ${source} for historical data`);

    const today = moment();
    const startDate = moment().subtract(days, 'days');

    let currentDate = moment(startDate);

    while (currentDate.isBefore(today) || currentDate.isSame(today, 'day')) {
      const dateStr = currentDate.format('YYYY-MM-DD');
      let success = false;
      let retries = 0;

      while (!success && retries < maxRetries) {
        try {
          const data = await this.fetchFireData(source, 1, dateStr);
          if (data.length > 0) {
            allData.push(...data);
            console.log(`Fetched ${data.length} records for ${dateStr}`);
          } else {
            console.log(`No records found for ${dateStr}`);
          }
          success = true;
        } catch (error) {
          retries++;
          if (retries < maxRetries) {
            console.log(`Retry ${retries}/${maxRetries} for ${dateStr} after 3s...`);
            await new Promise(resolve => setTimeout(resolve, 3000));
          } else {
            console.error(`Failed to fetch data for ${dateStr} after ${maxRetries} attempts`);
          }
        }
      }

      await new Promise(resolve => setTimeout(resolve, 1500));
      currentDate.add(1, 'days');
    }

    return allData;
  }

  async fetchLatestData(dayRange = 1) {
    return this.fetchFireData('VIIRS_SNPP_NRT', dayRange);
  }

  async fetchVIIRSData(source = 'VIIRS_SNPP_NRT', dayRange = 1) {
    return this.fetchFireData(source, dayRange);
  }
}

module.exports = new NasaFirmsService();
