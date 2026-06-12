const express = require('express');
const router = express.Router();
const fireDataController = require('../controllers/fireDataController');

router.get('/', fireDataController.getFireData);

router.get('/pipeline-status', fireDataController.getPipelineStatus);

router.post('/run-viirs', fireDataController.runCustomViirsDetection);

router.get('/fetch-latest', fireDataController.fetchAndSaveLatest);

router.get('/latest', fireDataController.getLatestFromAPI);

router.get('/statistics', fireDataController.getStatistics);

router.get('/hottest-month', fireDataController.getHottestMonth);

module.exports = router;
