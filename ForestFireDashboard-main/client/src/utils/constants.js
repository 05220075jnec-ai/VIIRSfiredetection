export const BHUTAN_BOUNDS = {
  minLat: 26.5,
  maxLat: 28.5,
  minLon: 88.5,
  maxLon: 92.5,
};

export const BUFFER_KM = 10;

const KM_TO_DEG_LAT = 1 / 111;
const KM_TO_DEG_LON_FACTOR = 1 / 111;

export function getBufferedBounds() {
  const latBuffer = BUFFER_KM * KM_TO_DEG_LAT;
  const lonBuffer = BUFFER_KM * KM_TO_DEG_LON_FACTOR;

  return {
    minLat: BHUTAN_BOUNDS.minLat - latBuffer,
    maxLat: BHUTAN_BOUNDS.maxLat + latBuffer,
    minLon: BHUTAN_BOUNDS.minLon - lonBuffer,
    maxLon: BHUTAN_BOUNDS.maxLon + lonBuffer,
  };
}

export function isWithinBhutanRegion(lat, lon) {
  const bounds = getBufferedBounds();
  return (
    lat >= bounds.minLat &&
    lat <= bounds.maxLat &&
    lon >= bounds.minLon &&
    lon <= bounds.maxLon
  );
}

export function getIntensityLabel(frp) {
  if (frp >= 60) return 'Extreme';
  if (frp >= 30) return 'High';
  if (frp >= 10) return 'Moderate';
  return 'Low';
}
