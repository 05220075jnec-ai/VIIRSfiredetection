# Bhutan Forest Fire Detection

Real-time fire monitoring system for Bhutan using NASA FIRMS VIIRS satellite data. This project fetches, stores, and displays fire detection data on an interactive map.

## Features

- **Real-time Monitoring**: Automatic fire detection updates every 15 minutes via NASA FIRMS VIIRS S-NPP satellite
- **Historical Data**: Import historical fire data from downloaded NASA FIRMS shapefiles
- **Interactive Map**: Web-based map visualization using Leaflet and OpenStreetMap
- **Bhutan Focus**: Filters fire data to Bhutan borders with 10km buffer zone
- **Data Export**: REST API for accessing fire data programmatically

## Technology Stack

| Layer | Technology |
|-------|------------|
| Backend | Node.js, Express.js |
| Database | PostgreSQL (via Docker) |
| ORM | Sequelize |
| Frontend | React, Vite |
| Maps | Leaflet, React-Leaflet |
| Satellite Data | NASA FIRMS VIIRS S-NPP |

---

## Quick Start (5 Minutes)

If you have all prerequisites installed:

```bash
# 1. Clone and install
git clone <repo-url> && cd ForestFireDetection
cd server && npm install && cd ../client && npm install

# 2. Start database
docker compose up -d

# 3. Import data and start server (in server folder)
cd server && npm run import-shp && npm start

# 4. Start frontend (in new terminal)
cd client && npm run dev
```

Open http://localhost:5173

---

## Prerequisites

Before setting up, ensure you have:

| Requirement | Version | Download |
|------------|---------|----------|
| Git | Any recent | [git-scm.com](https://git-scm.com/) |
| Docker | Latest | [docker.com/get-docker](https://docs.docker.com/get-docker/) |
| Node.js | v18+ | [nodejs.org](https://nodejs.org/) |
| NASA FIRMS API Key | Free | [firms.modaps.eosdis.nasa.gov](https://firms.modaps.eosdis.nasa.gov/api/data_availability) |
| NASA FIRMS Shapefile Data | VIIRS S-NPP | [firms.modaps.eosdis.nasa.gov/download/](https://firms.modaps.eosdis.nasa.gov/download/) |

### Getting NASA FIRMS API Key

1. Visit https://firms.modaps.eosdis.nasa.gov/api/data_availability
2. Enter your email address
3. Copy the API key sent to your email
4. Use this key in your `.env` file

### Downloading Shapefile Data

1. Visit https://firms.modaps.eosdis.nasa.gov/download/
2. Select:
   - **Source**: VIIRS S-NPP
   - **Data Type**: Archive
3. Draw bounding box or search for Bhutan region
4. Download the shapefile (.shp, .dbf, .shx, .prj, .cpg)

---

## Complete Setup Guide

### Step 1: Clone the Repository

```bash
git clone <repository-url>
cd ForestFireDetection
```

### Step 2: Install Dependencies

```bash
# Install server dependencies
cd server
npm install

# Install client dependencies
cd ../client
npm install
```

### Step 3: Configure Environment Variables

Create a `.env` file in the project root (`ForestFireDetection/.env`):

```bash
# NASA FIRMS API Key (required)
NASA_API_KEY=your_nasa_api_key_here

# PostgreSQL Configuration
DB_USER=fireuser
DB_PASSWORD=firepass123
DB_NAME=forestfire
DB_HOST=localhost
DB_PORT=5432

# Server Port
PORT=3000

# Bhutan Bounding Box (Bhutan + 10km buffer)
BHUTAN_BBOX=88.4,26.4,92.6,28.6
```

### Step 4: Start PostgreSQL Database

```bash
# Start PostgreSQL container
docker compose up -d

# Verify container is running
docker ps

# Expected output:
# CONTAINER ID   IMAGE          STATUS    PORTS
# xxxxxxxx       postgres:15    Up        0.0.0.0:5433->5432/tcp
```

### Step 5: Prepare Historical Data

Create folders in `server/Data/` with date range names. Place shapefile files inside each folder:

```
server/Data/
├── 2024-03-29_2025-03-29/
│   ├── fire_archive_SV-C2_739418.shp
│   ├── fire_archive_SV-C2_739418.dbf
│   ├── fire_archive_SV-C2_739418.shx
│   ├── fire_archive_SV-C2_739418.prj
│   └── fire_archive_SV-C2_739418.cpg
└── 2025-03-30_2025-12-30/
    ├── fire_archive_SV-C2_739417.shp
    └── ...
```

**Folder naming convention:** `YYYY-MM-DD_YYYY-MM-DD` (start date_end date)

### Step 6: Import Historical Data

```bash
cd server

# Import all shapefiles from all date folders
npm run import-shp
```

Expected output:
```
Starting dynamic VIIRS SHP data import...
Found 2 data folder(s):
  - 2024-03-29_2025-03-29
  - 2025-03-30_2025-12-30
[2024-03-29_2025-03-29] Importing fire_archive_SV-C2_739418.shp...
  Total records: 1393
  Imported: 1393 records
[2025-03-30_2025-12-30] Importing fire_archive_SV-C2_739417.shp...
  Total records: 368
  Imported: 368 records
=== Import Complete ===
Total imported: 1761 records
```

### Step 7: Start the Backend Server

```bash
cd server
npm run dev && npm run start
```

Expected output:
```
Database connection established successfully.
Database synchronized.
[2026-04-14T04:00:00.000Z] Fetching latest fire data...
Server is running on port 3000
Health check: http://localhost:3000/health
API endpoint: http://localhost:3000/api/fire-data
Real-time fetcher: Running every 15 minutes
```

### Step 8: Start the Frontend

Open a new terminal:

```bash
cd client
npm run dev
```

Expected output:
```
  VITE v8.0.0  ready in 500ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: http://192.168.x.x:5173/
```

### Step 9: Access the Application

Open your browser: **http://localhost:5173**

You should see:
- Interactive map centered on Bhutan
- Fire markers displayed on the map
- Time period filter dropdown
- Refresh button
- Fire detection count

---

## Project Structure

```
ForestFireDetection/
├── server/                      # Node.js Backend
│   ├── config/
│   │   └── database.js         # PostgreSQL configuration
│   ├── controllers/
│   │   └── fireDataController.js
│   ├── models/
│   │   └── FireData.js        # Fire detection model
│   ├── routes/
│   │   └── fireDataRoutes.js
│   ├── services/
│   │   └── nasaFirmsService.js
│   ├── scripts/
│   │   └── importShapefile.js  # Historical data importer
│   ├── Data/                   # Shapefile data storage
│   ├── app.js
│   ├── server.js               # Entry point
│   └── package.json
├── client/                      # React Frontend
│   ├── src/
│   │   ├── components/
│   │   │   ├── FireMap.jsx
│   │   │   └── FireMarkers.jsx
│   │   ├── services/
│   │   │   └── api.js
│   │   ├── utils/
│   │   │   └── constants.js
│   │   ├── App.jsx
│   │   ├── App.css
│   │   └── main.jsx
│   └── package.json
├── docker-compose.yml
├── .env
└── README.md
```

---

## How to Add New Historical Data

### Step 1: Create a Date Folder

```bash
mkdir -p server/Data/2026-01-01_2026-06-30
```

### Step 2: Place Shapefile Files

Copy NASA FIRMS shapefile files into the folder:
- `fire_archive_SV-C2_XXXXXX.shp`
- `fire_archive_SV-C2_XXXXXX.dbf`
- `fire_archive_SV-C2_XXXXXX.shx`
- `fire_archive_SV-C2_XXXXXX.prj`
- `fire_archive_SV-C2_XXXXXX.cpg`

### Step 3: Run Import

```bash
cd server
npm run import-shp
```

The script automatically:
- Scans `server/Data/` for all subfolders
- Finds all `fire_archive*.shp` files
- Imports records from each file
- Skips duplicates

---

## Bhutan Region Configuration

### Bhutan Bounds (Strict)
| Direction | Coordinate |
|-----------|------------|
| West | 88.5° |
| South | 26.5° |
| East | 92.5° |
| North | 28.5° |

### Monitoring Region (Bhutan + 10km Buffer)
| Direction | Coordinate |
|-----------|------------|
| West | 88.4° |
| South | 26.4° |
| East | 92.6° |
| North | 28.6° |

To change the bounding box, update `BHUTAN_BBOX` in `.env`:
```bash
BHUTAN_BBOX=88.4,26.4,92.6,28.6
```

---

## API Documentation

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/api/fire-data` | Get all fire data |
| GET | `/api/fire-data?days=N` | Get last N days |
| GET | `/api/fire-data?start=YYYY-MM-DD&end=YYYY-MM-DD` | Custom date range |
| GET | `/api/fire-data/fetch-latest?days=N` | Fetch from NASA and save |
| GET | `/api/fire-data/statistics` | Daily statistics |

### Example Requests

```bash
# Get all fire data
curl http://localhost:3000/api/fire-data

# Get last 7 days
curl "http://localhost:3000/api/fire-data?days=7"

# Get date range
curl "http://localhost:3000/api/fire-data?start=2025-03-01&end=2025-03-31"

# Fetch latest from NASA
curl "http://localhost:3000/api/fire-data/fetch-latest?days=1"

# Check API health
curl http://localhost:3000/health
```

---

## Frontend Features

- **Interactive Map**: Pan, zoom, click markers
- **Time Filter**: All Time, 7, 14, 30, 90 days
- **Refresh Button**: Manually fetch latest data
- **Fire Details Popup**: Date, time, location, brightness, FRP, confidence
- **Bhutan Border**: Blue outline showing monitoring region

---

## Troubleshooting

### Docker Issues

```bash
# Check if Docker is running
docker ps

# Start PostgreSQL
docker compose up -d

# View logs
docker logs forest_fire_db

# Restart PostgreSQL
docker restart forest_fire_db

# Stop PostgreSQL
docker compose down
```

### Port Already in Use

```bash
# Find process on port 3000
lsof -i:3000

# Kill process
kill -9 <PID>

# Or force kill
lsof -ti:3000 | xargs kill -9
```

### Database Connection Failed

```bash
# Check PostgreSQL is running
docker ps | grep postgres

# Check port mapping
docker port forest_fire_db

# Recreate container
docker compose down
docker compose up -d
```

### API Key Invalid

1. Visit https://firms.modaps.eosdis.nasa.gov/api/key
2. Verify your key in `.env` file
3. Restart server

### No Fire Data Showing

```bash
# Check database has records
curl http://localhost:3000/api/fire-data | jq '.count'

# Check Bhutan bounds in .env
cat .env | grep BHUTAN_BBOX

# Check data date range
curl http://localhost:3000/api/fire-data | jq '.data[0].acq_date'
```

### Rebuild Frontend

```bash
cd client
npm run build
```

---

## Development Commands

```bash
# Backend
cd server
npm start          # Start server
npm run start:csv  # Start server without Docker/PostgreSQL, reading custom VIIRS CSV
npm run dev        # Start with hot reload
npm run import-shp # Import historical data

# Frontend
cd client
npm run dev        # Start dev server
npm run build      # Production build
npm run preview    # Preview production build
```

## No-Docker Custom VIIRS Mode

If Docker is not installed, you can still display detections generated by:

```text
VIIRSfiredetection/scripts/auto_viirs_nrt_fire_detection.py
```

Start the CSV-backed API server:

```powershell
cd "C:\Users\Dell PC\Desktop\Yeshiproject2026\VIIRSfiredetection\ForestFireDashboard-main\server"
npm run start:csv
```

By default it reads:

```text
C:\Users\Dell PC\Desktop\Yeshiproject2026\VIIRSfiredetection\outputs\viirs_nrt\viirs_nrt_hotspots.csv
```

To test with the earlier VIIRS output:

```powershell
$env:CUSTOM_VIIRS_CSV="C:\Users\Dell PC\Desktop\Yeshiproject2026\VIIRSfiredetection\outputs_bhutan_viirs\bhutan_fire_hotspots.csv"
npm run start:csv
```

Then start the frontend:

```powershell
cd "C:\Users\Dell PC\Desktop\Yeshiproject2026\VIIRSfiredetection\ForestFireDashboard-main\client"
npm run dev
```

Open:

```text
http://localhost:5173
```

---

## License

This project is for educational and research purposes. Fire data courtesy of NASA FIRMS.
