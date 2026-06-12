const { Sequelize, DataTypes } = require('sequelize');
const config = require('../config/database');

const env = process.env.NODE_ENV || 'development';
const sequelize = new Sequelize(config[env]);

const FireData = sequelize.define('FireData', {
  id: {
    type: DataTypes.INTEGER,
    primaryKey: true,
    autoIncrement: true
  },
  latitude: {
    type: DataTypes.FLOAT,
    allowNull: false
  },
  longitude: {
    type: DataTypes.FLOAT,
    allowNull: false
  },
  brightness: {
    type: DataTypes.FLOAT,
    allowNull: true
  },
  scan: {
    type: DataTypes.FLOAT,
    allowNull: true
  },
  track: {
    type: DataTypes.FLOAT,
    allowNull: true
  },
  acq_date: {
    type: DataTypes.DATEONLY,
    allowNull: false
  },
  acq_time: {
    type: DataTypes.INTEGER,
    allowNull: true
  },
  satellite: {
    type: DataTypes.STRING(80),
    allowNull: true
  },
  instrument: {
    type: DataTypes.STRING(80),
    allowNull: true
  },
  version: {
    type: DataTypes.STRING(120),
    allowNull: true
  },
  confidence: {
    type: DataTypes.INTEGER,
    allowNull: true
  },
  frp: {
    type: DataTypes.FLOAT,
    allowNull: true
  },
  fire_type: {
    type: DataTypes.STRING(120),
    allowNull: true
  },
  created_at: {
    type: DataTypes.DATE,
    defaultValue: DataTypes.NOW
  }
}, {
  tableName: 'fire_data',
  timestamps: false,
  indexes: [
    { fields: ['acq_date'] },
    { fields: ['latitude', 'longitude'] },
    { fields: ['fire_type'] },
    { unique: true, fields: ['latitude', 'longitude', 'acq_date', 'acq_time'] }
  ]
});

module.exports = { FireData, sequelize };
