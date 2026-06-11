const shapefile = require('shapefile');
const proj4 = require('proj4');
const fs = require('fs');
const path = require('path');

const BHUTAN_TM_TO_WGS84 = '+proj=tmerc +lat_0=0 +lon_0=90 +k=1 +x_0=250000 +y_0=0 +ellps=GRS80 +units=m +no_defs';

function transformCoordinates(coords, fromProj, toProj) {
  if (typeof coords[0] === 'number' && typeof coords[1] === 'number') {
    return proj4(fromProj, toProj, [coords[0], coords[1]]);
  }
  return coords.map(c => transformCoordinates(c, fromProj, toProj));
}

function transformGeometry(geometry, fromProj, toProj) {
  if (!geometry || !geometry.coordinates) {
    return geometry;
  }

  return {
    ...geometry,
    coordinates: transformCoordinates(geometry.coordinates, fromProj, toProj),
  };
}

async function convertBhutanBoundaryToGeoJSON() {
  const shpPath = path.join(__dirname, '../Administrative Boundaries/Internationalboundary.shp');
  const dbfPath = path.join(__dirname, '../Administrative Boundaries/Internationalboundary.dbf');

  console.log('Converting Bhutan international boundary shapefile to GeoJSON...');

  const source = await shapefile.open(shpPath, dbfPath);
  const features = [];

  while (true) {
    const result = await source.read();
    if (result.done) break;

    const { geometry, properties } = result.value;
    const transformedGeometry = transformGeometry(geometry, BHUTAN_TM_TO_WGS84, 'WGS84');

    features.push({
      type: 'Feature',
      geometry: transformedGeometry,
      properties: {
        NAME: properties.NAM || properties.NAME || 'Bhutan',
      },
    });
  }

  const geoJSON = {
    type: 'FeatureCollection',
    features,
  };

  const outputPath = path.join(__dirname, '../../client/public/data/bhutan-boundary.geojson');
  fs.writeFileSync(outputPath, JSON.stringify(geoJSON, null, 2));

  console.log(`Converted ${features.length} boundary feature(s)`);
  console.log(`Output: ${outputPath}`);
}

convertBhutanBoundaryToGeoJSON().catch(console.error);
