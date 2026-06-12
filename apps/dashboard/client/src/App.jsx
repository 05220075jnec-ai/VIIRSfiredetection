import { useState, useEffect } from 'react';
import { format, parse } from 'date-fns';
import FireMap from './components/FireMap';
import { fetchFireDataRange, fetchHottestMonth, fetchPipelineStatus } from './services/api';
import { isWithinBhutanRegion } from './utils/constants';
import { DatePicker } from './components/ui/date-picker';
import { DzongkhagSelector } from './components/ui/dzongkhag-selector';
import './App.css';

const DZONGKHAGS = [
  'Bumthang', 'Chhukha', 'Dagana', 'Gasa', 'Haa', 'Lhuentse', 'Monggar',
  'Paro', 'Pemagatshel', 'Punakha', 'Samdrupjongkhar', 'Samtse', 'Sarpang',
  'Thimphu', 'Trashigang', 'Trongsa', 'Tsirang', 'Wangduephodrang', 'Yangtse', 'Zhemgang'
];

const REFRESH_SECONDS = 60;

const DATA_SOURCES = [
  { value: 'viirs', label: 'VIIRS' },
  { value: 'modis', label: 'MODIS' },
  { value: 'live_nrt', label: 'Live NRT automation (recent)' },
];

function formatHottestMonth(monthStr, count) {
  if (!monthStr) return null;
  const date = parse(monthStr, 'yyyy-MM', new Date());
  const monthName = format(date, 'MMMM yyyy');
  return `${monthName} (${count} fires)`;
}

function formatPipelineTime(value) {
  if (!value) return 'No output yet';
  return new Date(value).toLocaleString();
}

function pipelineStatusLabel(status, phase) {
  const labels = {
    active: 'Active',
    error: 'Error',
    stale: 'Stale',
    not_started: 'Not started',
  };
  const phases = {
    fetching: 'downloading satellite data',
    checking: 'checking granules',
    detecting: 'detecting hotspots',
    importing: 'saving hotspots',
    completed: 'cycle completed',
    sleeping: 'waiting for next cycle',
    error: 'cycle error',
  };
  const label = labels[status] || 'Unknown';
  return status === 'active' && phases[phase] ? `${label} — ${phases[phase]}` : label;
}

function App() {
  const [fireData, setFireData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [startDate, setStartDate] = useState(new Date(2023, 3, 8));
  const [endDate, setEndDate] = useState(new Date(2023, 3, 9));
  const [selectedDzongkhag, setSelectedDzongkhag] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [stats, setStats] = useState({ total: 0 });
  const [hottestMonth, setHottestMonth] = useState(null);
  const [pipeline, setPipeline] = useState(null);
  const [refreshIn, setRefreshIn] = useState(REFRESH_SECONDS);
  const [dataSource, setDataSource] = useState('viirs');
  const viirsPipeline = pipeline?.viirs || pipeline;
  const modisPipeline = pipeline?.modis;

  useEffect(() => {
    loadFireData();
  }, [startDate, endDate, dataSource]);

  useEffect(() => {
    loadHottestMonth();
    loadPipelineStatus();
  }, [dataSource]);

  useEffect(() => {
    const tick = setInterval(() => {
      setRefreshIn((current) => {
        if (current <= 1) {
          loadFireData({ silent: true });
          loadPipelineStatus();
          return REFRESH_SECONDS;
        }
        return current - 1;
      });
    }, 1000);

    return () => clearInterval(tick);
  }, [startDate, endDate, dataSource]);

  const loadHottestMonth = async () => {
    try {
      const result = await fetchHottestMonth(dataSource);
      if (result.success && result.month) {
        setHottestMonth(formatHottestMonth(result.month, result.count));
      } else {
        setHottestMonth(null);
      }
    } catch (err) {
      console.error('Failed to load hottest month:', err);
    }
  };

  const loadPipelineStatus = async () => {
    try {
      const result = await fetchPipelineStatus();
      if (result.success) {
        setPipeline(result.pipeline);
      }
    } catch (err) {
      console.error('Failed to load pipeline status:', err);
    }
  };

  const loadFireData = async ({ silent = false } = {}) => {
    if (!silent) {
      setLoading(true);
    }
    setError(null);
    try {
      const start = format(startDate, 'yyyy-MM-dd');
      const end = format(endDate, 'yyyy-MM-dd');
      const result = await fetchFireDataRange(start, end, dataSource);
      if (result.success) {
        const bhutanFires = (result.data || []).filter(f =>
          isWithinBhutanRegion(f.latitude, f.longitude)
        );
        setFireData(bhutanFires);
        setLastUpdated(new Date());
        setStats({ total: bhutanFires.length });
        setRefreshIn(REFRESH_SECONDS);
      } else if (result.error) {
        setError(result.error);
      }
    } catch (err) {
      setError('Failed to load fire data. Make sure the server is running.');
      console.error(err);
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  };

  const useLiveWindow = () => {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - 1);
    setDataSource('live_nrt');
    setSelectedDzongkhag(null);
    setStartDate(start);
    setEndDate(end);
  };

  const useHistoricalDate = (setter) => (date) => {
    if (!date) return;
    setSelectedDzongkhag(null);
    setter(date);
  };

  return (
    <div className="app">
      <header className="header">
        <div className="brand-block">
          <div className="logo-stack" aria-label="Project logos">
            <img
              className="logo logo-flag"
              src="/logo/bhutanflag.jpg"
              alt="Bhutan flag"
            />
            <img
              className="logo logo-jnec"
              src="/logo/jneclogo.png"
              alt="Jigme Namgyel Engineering College logo"
            />
          </div>
          <div className="header-content">
            <h1>Bhutan Fire Detection</h1>
          </div>
        </div>
      </header>

      <div className="controls">
        <div className="control-group">
          <label htmlFor="start-date">Start Date:</label>
          <DatePicker
            selected={startDate}
            onSelect={useHistoricalDate(setStartDate)}
            maxDate={endDate}
            minYear={2020}
          />
        </div>
        <div className="control-group">
          <label htmlFor="end-date">End Date:</label>
          <DatePicker
            selected={endDate}
            onSelect={useHistoricalDate(setEndDate)}
            maxDate={new Date()}
            minYear={2020}
          />
        </div>
        <div className="control-group">
          <label htmlFor="data-source">Source:</label>
          <select
            id="data-source"
            value={dataSource}
            onChange={(event) => setDataSource(event.target.value)}
            disabled={loading}
          >
            {DATA_SOURCES.map((source) => (
              <option key={source.value} value={source.value}>
                {source.label}
              </option>
            ))}
          </select>
        </div>
        <div className="control-group">
          <label htmlFor="dzongkhag">Dzongkhag:</label>
          <DzongkhagSelector
            dzongkhags={DZONGKHAGS}
            selected={selectedDzongkhag}
            onSelect={setSelectedDzongkhag}
          />
        </div>
        <button
          type="button"
          className="secondary-btn"
          onClick={useLiveWindow}
          disabled={loading}
        >
          Live 24 Hours
        </button>
        <button
          type="button"
          className="refresh-btn"
          onClick={loadFireData}
          disabled={loading}
        >
          Load Hotspots
        </button>
        {lastUpdated && (
          <span className="last-updated">
            Last updated: {lastUpdated.toLocaleTimeString()}
          </span>
        )}
      </div>

      <section className="pipeline-status" aria-label="Automation pipeline status">
        <div className="pipeline-item pipeline-main">
          <span className={`pipeline-dot ${viirsPipeline?.status || 'not_started'}`} />
          <span>VIIRS automation: <strong>{pipelineStatusLabel(viirsPipeline?.status, viirsPipeline?.phase)}</strong></span>
        </div>
        <div className="pipeline-item">
          VIIRS output: <strong>{formatPipelineTime(viirsPipeline?.latestOutputUtc)}</strong>
        </div>
        <div className="pipeline-item">
          VIIRS hotspots: <strong>{viirsPipeline?.nrtHotspotRows ?? 0}</strong>
        </div>
        <div className="pipeline-item">
          VIIRS granules: <strong>{viirsPipeline?.processedGranuleCount ?? 0}</strong>
        </div>
        <div className="pipeline-item pipeline-main">
          <span className={`pipeline-dot ${modisPipeline?.status || 'not_started'}`} />
          <span>MODIS automation: <strong>{pipelineStatusLabel(modisPipeline?.status, modisPipeline?.phase)}</strong></span>
        </div>
        <div className="pipeline-item">
          MODIS output: <strong>{formatPipelineTime(modisPipeline?.latestOutputUtc)}</strong>
        </div>
        <div className="pipeline-item">
          MODIS hotspots: <strong>{modisPipeline?.nrtHotspotRows ?? 0}</strong>
        </div>
        <div className="pipeline-item">
          MODIS granules: <strong>{modisPipeline?.processedGranuleCount ?? 0}</strong>
        </div>
        <div className="pipeline-item">
          Dashboard refresh: <strong>{refreshIn}s</strong>
        </div>
      </section>

      {error && <div className="error-message">{error}</div>}

      <main className="main-content">
        {loading && fireData.length === 0 ? (
          <div className="loading">Loading fire data...</div>
        ) : (
          <FireMap
            fireData={fireData}
            riskStart={format(startDate, 'yyyy-MM-dd')}
            riskEnd={format(endDate, 'yyyy-MM-dd')}
            selectedDzongkhag={selectedDzongkhag}
            onDzongkhagClick={setSelectedDzongkhag}
          />
        )}
      </main>

      <footer className="footer">
        <p>Data sources: VIIRS and MODIS detections stored in PostgreSQL</p>
        <p>Choose a start and end date to fetch saved detections</p>
      </footer>
    </div>
  );
}

export default App;
