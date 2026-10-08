import React, { useState, useEffect, useCallback, useRef } from 'react';
import { BrowserRouter, useLocation } from 'react-router-dom';
import Rail from './components/Rail';
import HeroMetric from './components/HeroMetric';
import KpiTiles from './components/KpiTiles';
import SalesFunnel from './components/SalesFunnel';
import Leaderboard from './components/Leaderboard';
import StockAndModels from './components/StockAndModels';
import DataTables from './components/DataTables';
import EntryDrawer from './components/EntryDrawer';
import ExcelUploadModal from './components/ExcelUploadModal';
import ExportDataModal from './components/ExportDataModal';
import ToastContainer from './components/ToastContainer';
import ChatWidget from './components/ChatWidget';
import SheetFooter from './components/SheetFooter';
import Loading from './components/Loading';
import PeriodManager from './components/PeriodManager';
import SalesTimeline from './components/SalesTimeline';
import Trends from './components/Trends';
import Composition from './components/Composition';
import AgentCalls from './components/AgentCalls';
import TestDriveBoard from './components/TestDriveBoard';
import Visualizations from './components/Visualizations';
import {
  BookingPace, Commitments, StockAgeing, Backorders,
  ConsultantConversion, Attachments,
} from './components/Analytics';
import FolderTat from './components/FolderTat';
import { fetchDashboardData, activatePeriod, DASHBOARD_CALLS } from './api/client';
import { setupLiveEvents } from './api/liveEvents';

/**
 * A seam. Fourteen panels in one column read as an undifferentiated scroll, so
 * the page is divided into acts - the label sits on a rule the way a seam runs
 * across cloth, rather than being another heavy heading competing with the
 * panel titles beneath it.
 */
/**
 * The dashboard is a set of pages, one per department.
 *
 * It used to be one scroll of fourteen panels, then one page of hash tabs.
 * Both were a single document pretending to be several. These are real routes:
 * /sales and /accounts are addresses you can type, bookmark, send to someone,
 * and land on directly - which is what anybody means by a website.
 *
 * Only the page you are on renders, which is also what makes it quick: the old
 * sheet mounted every chart on load and Recharts is not cheap.
 *
 * The server serves index.html for any path it does not recognise, so a refresh
 * on /people is a page rather than a 404 - see spa_fallback in app/main.py.
 * Without that half of this would only work for someone who clicked their way
 * here.
 */
const PAGES = [
  { id: 'overview',  path: '/',          label: 'Overview',  note: 'Where the month stands' },
  { id: 'sales',     path: '/sales',     label: 'Sales',     note: 'Enquiries, demand and how the month is running' },
  { id: 'accounts',  path: '/accounts',  label: 'Accounts',  note: 'Attachments and how fast paperwork clears' },
  { id: 'people',    path: '/people',    label: 'People',    note: 'Consultants against their targets' },
  { id: 'inventory', path: '/inventory', label: 'Inventory', note: 'Stock by model, ageing, and orders awaiting a car' },
  { id: 'calls',     path: '/calls',     label: 'Calls',     note: 'What the agent handled on the phone' },
  // Prototype: see app/test_drives.py.
  { id: 'testdrives', path: '/test-drives', label: 'Test Drives', note: 'Test drives booked by the AI agent, the sales desk and walk-ins, and test-drive enquiries' },
];

function Dashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [liveStatus, setLiveStatus] = useState({ state: 'off', text: 'connecting' });
  // When the figures on screen were last drawn. A screenshot of this sheet
  // travels - into Teams, into a deck - and the first question anyone asks of
  // it is 'as of when?'. The footer answers with this.
  const [loadedAt, setLoadedAt] = useState(null);
  const [loaded, setLoaded] = useState(0);
  // Counts the database's change signals (and Refresh clicks). The test drive
  // board refetches on it directly, so a change reaches the calendar as soon
  // as the signal does - not after the sixteen requests of a dashboard reload,
  // and not at all only if that reload succeeds.
  const [changeTick, setChangeTick] = useState(0);

  // UI States
  // The report sheet is the primary state: light reads as a printed document
  // rather than a tech demo, and it survives a projector in a meeting room.
  // The night sheet stays, one click away, for anyone working a late shift.
  const [theme, setTheme] = useState(() => localStorage.getItem('dsr.theme') || 'light');
  const [showTables, setShowTables] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerTab, setDrawerTab] = useState('booking');
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const [periodsOpen, setPeriodsOpen] = useState(false);
  const [toasts, setToasts] = useState([]);

  // Toast Helper
  const addToast = useCallback((message, { bad = false } = {}) => {
    const id = Date.now() + Math.random();
    setToasts(prev => [...prev, { id, message, bad }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 4500);
  }, []);

  // Theme synchronization
  useEffect(() => {
    // :root carries the dark palette, so it is LIGHT that is stamped on the
    // element - the reverse of the previous arrangement.
    if (theme === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    localStorage.setItem('dsr.theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => (prev === 'dark' ? 'light' : 'dark'));
  };

  // Whether a load has ever succeeded, and the load currently in flight. Both
  // are refs rather than state on purpose: loadData must keep a stable
  // identity, or the effect below re-runs on every fetch.
  const hasLoadedRef = useRef(false);
  const inFlightRef = useRef(null);

  // Data fetching
  const loadData = useCallback(async (quiet = false) => {
    if (!quiet) setIsRefreshing(true);
    try {
      // A change event, the heartbeat and a Refresh click can all land
      // together, and one pass is sixteen requests against a database a round
      // trip away - left alone they queue behind the browser's per-host
      // connection limit until fetches time out. So concurrent callers JOIN the
      // run already in flight rather than starting another.
      //
      // Joining, not dropping: an earlier version returned early here, which
      // meant a Refresh clicked while the background heartbeat happened to be
      // running did nothing at all - no spinner, no result, no message.
      if (!inFlightRef.current) {
        inFlightRef.current = (async () => {
          try {
            setLoaded(0);
            return await fetchDashboardData(n => setLoaded(n));
          } finally {
            inFlightRef.current = null;
          }
        })();
      }
      const res = await inFlightRef.current;
      setData(res);
      setLoadedAt(new Date());
      hasLoadedRef.current = true;
      setError(null);
    } catch (err) {
      console.error('Failed to load dashboard data:', err);
      if (!hasLoadedRef.current) setError(err.message || 'Failed to connect to CRM API');
      addToast(`Refresh failed: ${err.message}`, { bad: true });
    } finally {
      setLoading(false);
      if (!quiet) setIsRefreshing(false);
    }
  }, [addToast]);

  // Initial fetch and SSE event wiring. loadData is stable, so this runs once -
  // when it also depended on `data` the effect re-ran after every fetch, which
  // reloaded the dashboard in a loop and tore the event stream down with it.
  useEffect(() => {
    loadData();

    const cleanup = setupLiveEvents(
      () => { setChangeTick(t => t + 1); loadData(true); },
      (state, text) => setLiveStatus({ state, text })
    );

    return cleanup;
  }, [loadData]);

  // Which page is open. Taken from the router rather than tracked here, so
  // the address bar is the single source of truth and back/forward need no
  // help from us.
  const location = useLocation();
  const page = PAGES.find(p => p.path === location.pathname) || PAGES[0];
  const activeTab = page.id;

  // Handle active period change
  const handlePeriodChange = async (newPeriod) => {
    try {
      await activatePeriod(newPeriod);
      addToast(`Activated month: ${newPeriod}`);
      await loadData();
    } catch (err) {
      addToast(`Could not switch month: ${err.message}`, { bad: true });
    }
  };

  const handleOpenDrawer = (tab = 'booking') => {
    setDrawerTab(tab);
    setDrawerOpen(true);
  };

  if (loading && !data) {
    return <Loading done={loaded} total={DASHBOARD_CALLS} />;
  }

  if (error && !data) {
    return (
      <div className="wrap">
        <div className="panel" style={{ textAlign: 'center', padding: '40px 20px' }}>
          <h2>Could not connect to CRM API</h2>
          <p style={{ color: 'var(--ink-muted)', margin: '8px 0 20px' }}>{error}</p>
          <button className="primary" onClick={() => loadData()}>Retry Connection</button>
        </div>
      </div>
    );
  }

  const activePeriodObj = data?.periods?.find(p => p.is_active) || data?.periods?.[0] || {};


  return (
    <div className="shell">
      <Rail
        periods={data?.periods || []}
        activePeriod={activePeriodObj.label || ''}
        onPeriodChange={handlePeriodChange}
        liveStatus={liveStatus}
        sections={PAGES}
        activeSection={activeTab}
        onOpenDrawer={handleOpenDrawer}
        onOpenUpload={() => setUploadModalOpen(true)}
        onOpenExport={() => setExportModalOpen(true)}
        onRefresh={() => {
          addToast('Pulling the latest figures…');
          setChangeTick(t => t + 1);
          loadData();
        }}
        isRefreshing={isRefreshing}
        showTables={showTables}
        onToggleTables={() => setShowTables(prev => !prev)}
        onManagePeriods={() => setPeriodsOpen(true)}
        theme={theme}
        onToggleTheme={toggleTheme}
      />

      <main className="sheet">
        {/* The tab's own title, so the sheet says which department it is
            showing. The rail marks it too, but the rail is 232px away and the
            eye is here. */}
        <div style={{ marginBottom: 22 }}>
          <h1 style={{ fontSize: 22, letterSpacing: '-0.02em' }}>{page.label}</h1>
          {page.note && (
            <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)', marginTop: 5 }}>
              {page.note}
            </div>
          )}
        </div>

        {activeTab === 'overview' && (
          <>
            <HeroMetric kpi={data?.kpi || {}} period={activePeriodObj}
                        trends={data?.trends || {}} />
            <KpiTiles kpi={data?.kpi || {}} trends={data?.trends || {}} />
            <div style={{ marginTop: 26 }}>
              <SalesFunnel funnel={data?.funnel || {}} />
            </div>
          </>
        )}

        {activeTab === 'sales' && (
          <>
            <Visualizations sources={data?.sources || []} models={data?.models || []} />
            <div style={{ marginBottom: 26 }}>
              <SalesTimeline refreshKey={data?.kpi?.bookings} />
            </div>
            <Trends refreshKey={data?.kpi?.bookings} />
            <Composition refreshKey={data?.kpi?.bookings} />
            {/* The funnel lives on Overview. Repeating it here would make the
                longest tab longer to say something already said. */}
            <BookingPace orderbook={data?.orderbook || []}
                         target={Number(data?.kpi?.booking_target) || 0} />
          </>
        )}

        {activeTab === 'accounts' && (
          <>
            <div className="grid-2" style={{ marginBottom: 26 }}>
              <Attachments attachments={data?.attachments || null} />
              <FolderTat />
            </div>
          </>
        )}

        {activeTab === 'people' && (
          <>
            <div style={{ marginBottom: 26 }}>
              <Leaderboard board={data?.board || []} />
            </div>
            <div className="grid-2">
              <ConsultantConversion scorecards={data?.scorecards || []} />
              <Commitments commitments={data?.commitments || []} />
            </div>
          </>
        )}

        {activeTab === 'inventory' && (
          <>
            <StockAndModels
              models={data?.models || []}
              ageing={data?.ageing || []}
              activity={data?.activity || []}
            />
            <div className="grid-2">
              <StockAgeing ageing={data?.ageing || []} />
              <Backorders backorders={data?.backorders || []} />
            </div>
          </>
        )}

        {activeTab === 'calls' && <AgentCalls />}
        {/* changeTick moves on every change the database announces - an
            agent's enquiry, a Record-drawer save, a workbook upload - and on
            the 25-second heartbeat, so the board refetches its month and the
            calendar keeps up with the database on its own. */}
        {activeTab === 'testdrives' && <TestDriveBoard refreshKey={changeTick} />}

        {/* The record tables are a drill-down on whatever is on screen, so they
            follow the tab rather than living on one of them. */}
        {showTables && (
          <DataTables
            orderbook={data?.orderbook || []}
            sources={data?.sources || []}
            backorders={data?.backorders || []}
          />
        )}

      <SheetFooter
        period={activePeriodObj}
        liveStatus={liveStatus}
        loadedAt={loadedAt}
      />
      </main>

      {/* Overlays sit outside the sheet so the rail cannot clip them. */}
      <PeriodManager
        isOpen={periodsOpen}
        periods={data?.periods || []}
        onClose={() => setPeriodsOpen(false)}
        onChanged={(msg) => {
          addToast(msg);
          loadData(true);
        }}
      />

      <EntryDrawer
        isOpen={drawerOpen}
        activeTab={drawerTab}
        onClose={() => setDrawerOpen(false)}
        options={data?.options || {}}
        activePeriod={activePeriodObj}
        onSaved={(msg) => {
          addToast(msg);
          loadData(true);
        }}
      />

      {/* Drag & Drop Excel Upload Modal */}
      <ExcelUploadModal
        isOpen={uploadModalOpen}
        onClose={() => setUploadModalOpen(false)}
        onUploadComplete={(msg) => {
          addToast(msg);
          loadData(true);
        }}
      />

      {/* The way back out: the live tables as a workbook or a CSV set. An
          export only reads, so there is nothing to reload afterwards. */}
      <ExportDataModal
        isOpen={exportModalOpen}
        onClose={() => setExportModalOpen(false)}
        onExported={(msg) => addToast(msg)}
      />

      {/* Toasts */}
      <ToastContainer toasts={toasts} />

      {/* Perfox "Dashboard Insights" agent - internal staff copilot over
          live dashboard data. Renders nothing until VITE_PERFOX_SITE_ID is set. */}
      <ChatWidget />
    </div>
  );
}


/**
 * useLocation only works inside a Router, and the dashboard is the thing that
 * needs it - so the router wraps it here rather than in main.jsx, which keeps
 * everything about routing in one file.
 */
export default function App() {
  return (
    // The dev server mounts the app under Vite's base, /static/, so a path
    // there is /static/sales while in production it is /sales - the app is
    // served from the root and only its assets come from /static. Without a
    // basename no route ever matched in dev and the rail looked broken while
    // production was fine, which is the worst way round to have a bug.
    // import.meta.env.BASE_URL is '/static/' in both, so it cannot be used
    // directly; DEV is the thing that actually differs.
    <BrowserRouter basename={import.meta.env.DEV ? '/static' : '/'}>
      <Dashboard />
    </BrowserRouter>
  );
}
