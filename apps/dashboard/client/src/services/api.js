const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
const PREDICTION_API_BASE_URL = import.meta.env.VITE_PREDICTION_API_BASE_URL || '/prediction';
const BURN_SEVERITY_API_BASE_URL = import.meta.env.VITE_BURN_SEVERITY_API_BASE_URL || '/burned';

async function parseJsonResponse(response, serviceName) {
  const body = await response.text();

  if (!body) {
    throw new Error(`${serviceName} returned an empty response. Check that its service is running.`);
  }

  try {
    return JSON.parse(body);
  } catch {
    throw new Error(`${serviceName} returned an invalid response (HTTP ${response.status}).`);
  }
}

export async function fetchFireData(date = null, days = 0) {
  let url = `${API_BASE_URL}/api/fire-data`;
  const params = [];

  if (date) {
    params.push(`date=${date}`);
  }
  if (days !== null && days !== undefined && days !== '') {
    params.push(`days=${days}`);
  }

  if (params.length > 0) {
    url += `?${params.join('&')}`;
  }

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error('Failed to fetch fire data');
  }
  return response.json();
}

export async function fetchFireDataRange(start, end, source = 'viirs') {
  const params = new URLSearchParams({ start, end, source });
  const response = await fetch(`${API_BASE_URL}/api/fire-data?${params.toString()}`);
  if (!response.ok) {
    throw new Error('Failed to fetch fire data');
  }
  return response.json();
}

export async function fetchPipelineStatus() {
  const response = await fetch(`${API_BASE_URL}/api/fire-data/pipeline-status`);
  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.message || result.error || 'Failed to fetch pipeline status');
  }
  return result;
}

export async function fetchHottestMonth(source = 'viirs') {
  const params = new URLSearchParams({ source });
  const response = await fetch(`${API_BASE_URL}/api/fire-data/hottest-month?${params.toString()}`);
  if (!response.ok) {
    throw new Error('Failed to fetch hottest month');
  }
  return response.json();
}

export async function fetchPredictedRiskMap(start, end) {
  const params = new URLSearchParams({ start, end });
  const response = await fetch(`${PREDICTION_API_BASE_URL}/generate_map?${params.toString()}`);
  const result = await parseJsonResponse(response, 'Prediction service');
  if (!response.ok || result.error) {
    throw new Error(result.error || result.message || 'Failed to generate predicted risk map');
  }
  return result;
}

export async function fetchBurnSeverityMap(before, after) {
  const params = new URLSearchParams({ before, after });
  const response = await fetch(`${BURN_SEVERITY_API_BASE_URL}/generate_burn_severity?${params.toString()}`);
  const result = await parseJsonResponse(response, 'Burn severity service');
  if (!response.ok || result.error) {
    throw new Error(result.error || result.message || 'Failed to generate burn severity map');
  }
  return result;
}
