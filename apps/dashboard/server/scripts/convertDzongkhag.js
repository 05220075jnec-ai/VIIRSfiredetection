const shapefile = require('shapefile');
const proj4 = require('proj4');
const fs = require('fs');
const path = require('path');

// Bhutan administrative boundary shapefiles use DrukRef03 TM (not UTM).
const BHUTAN_TM_TO_WGS84 = '+proj=tmerc +lat_0=0 +lon_0=90 +k=1 +x_0=250000 +y_0=0 +ellps=GRS80 +units=m +no_defs';

function transformRing(ringCoords, fromProj, toProj) {
  return ringCoords.map(coord => {
    if (typeof coord[0] === 'number' && typeof coord[1] === 'number') {
      return proj4(fromProj, toProj, [coord[0], coord[1]]);
    }
    return transformRing(coord, fromProj, toProj);
  });
}

function transformGeometry(geometry, fromProj, toProj) {
  if (geometry.type === 'Polygon') {
    return {
      type: 'Polygon',
      coordinates: geometry.coordinates.map(ring => transformRing(ring, fromProj, toProj))
    };
  } else if (geometry.type === 'MultiPolygon') {
    return {
      type: 'MultiPolygon',
      coordinates: geometry.coordinates.map(polygon =>
        polygon.map(ring => transformRing(ring, fromProj, toProj))
      )
    };
  }
  return geometry;
}

async function convertDzongkhagToGeoJSON() {
  const shpPath = path.join(__dirname, '../Administrative Boundaries/Dzongkhag.shp');
  const dbfPath = path.join(__dirname, '../Administrative Boundaries/Dzongkhag.dbf');

  console.log('Converting Dzongkhag shapefile to GeoJSON (with Bhutan TM to WGS84 transformation)...');

  const source = await shapefile.open(shpPath, dbfPath);

  const features = [];
  let count = 0;

  while (true) {
    const result = await source.read();
    if (result.done) break;

    const { geometry, properties } = result.value;

    const transformedGeometry = transformGeometry(geometry, BHUTAN_TM_TO_WGS84, 'WGS84');

    const feature = {
      type: 'Feature',
      geometry: transformedGeometry,
      properties: {
        DZONGKHA: properties.NAM || properties.DZONGKHA || properties.dzongkhag || properties.NAME || properties.NAME_,
      }
    };

    features.push(feature);
    count++;
  }

  const geoJSON = {
    type: 'FeatureCollection',
    features: features
  };

  const outputPath = path.join(__dirname, '../../client/public/data/dzongkhags.geojson');
  fs.writeFileSync(outputPath, JSON.stringify(geoJSON, null, 2));

  console.log(`Converted ${count} dzongkhags to GeoJSON`);
  console.log(`Output: ${outputPath}`);

  const dzongkhagNames = features.map(f => f.properties.DZONGKHA).sort();
  console.log('\nDzongkhag names:');
  dzongkhagNames.forEach(name => console.log(`  - ${name}`));

  if (features.length > 0) {
    const sample = features[0].geometry.coordinates[0][0];
    console.log('\nSample coordinate (first ring, first point):');
    console.log(`  Before: [318600, 3107394] (UTM)`);
    console.log(`  After: [${sample[0].toFixed(6)}, ${sample[1].toFixed(6)}] (WGS84)`);
  }
}

convertDzongkhagToGeoJSON().catch(console.error);