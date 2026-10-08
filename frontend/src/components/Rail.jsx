/**
 * The left rail.
 *
 * Everything that was competing for the top of the page - identity, the period
 * control, live state, the entry actions, the view toggles - now lives down the
 * side, where it stays put while the sheet scrolls past it. The page was 4,500
 * pixels tall with no way to get anywhere; the rail is also the map.
 */

import React, { useEffect, useRef, useState } from 'react';
import { NavLink } from 'react-router-dom';
import {
  PlusCircle, UserPlus, Compass, KeyRound, UploadCloud, Download,
  RefreshCw, Table, Sun, Moon, Headset, CalendarCog, ChevronDown
} from 'lucide-react';
import { connection, justUpdated, CONNECTION } from './connection';

const ENTRIES = [
  { tab: 'booking', label: 'New booking', Icon: PlusCircle },
  { tab: 'lead', label: 'New lead', Icon: UserPlus },
  { tab: 'testdrive', label: 'Test drive', Icon: Compass },
  { tab: 'allotment', label: 'Allotment', Icon: KeyRound },
];

const RECORD_OPEN_KEY = 'dsr.rail.record.open';

/** Whether the Record group was left open, remembered per browser. */
function rememberedOpen() {
  try {
    return window.localStorage.getItem(RECORD_OPEN_KEY) === '1';
  } catch {
    // Private windows and blocked site data both throw here. Closed is the
    // safe default: it is the state that saves the space.
    return false;
  }
}

export default function Rail({
  periods = [],
  activePeriod = '',
  onPeriodChange,
  liveStatus = { state: 'off', text: 'connecting' },
  sections = [],
  activeSection,
  onOpenDrawer,
  onOpenUpload,
  onOpenExport,
  onRefresh,
  isRefreshing,
  showTables,
  onToggleTables,
  onManagePeriods,
  theme,
  onToggleTheme,
}) {
  const [recordOpen, setRecordOpen] = useState(rememberedOpen);
  const recordRef = useRef(null);
  const triggerRef = useRef(null);

  useEffect(() => {
    try {
      window.localStorage.setItem(RECORD_OPEN_KEY, recordOpen ? '1' : '0');
    } catch {
      // Nothing to do - the group still works, it just will not be remembered.
    }
  }, [recordOpen]);

  const activeObj = periods.find(p => p.label === activePeriod) || {};
  const span = (() => {
    const { period_start: a, period_end: b } = activeObj;
    if (!a || !b) return null;
    const from = new Date(a), to = new Date(b);
    if (Number.isNaN(+from) || Number.isNaN(+to)) return null;
    return `${from.getUTCDate()}–${to.getUTCDate()} ${
      to.toLocaleDateString('en-IN', { month: 'long', year: 'numeric', timeZone: 'UTC' })}`;
  })();

  return (
    <aside className="rail">
      <div className="rail-identity">
        {/* Volkswagen roundel, public domain (below the threshold of
            originality for copyright) per
            https://commons.wikimedia.org/wiki/File:Volkswagen_logo_2019.svg */}
        <span className="rail-seal rail-seal-logo">
          <svg viewBox="0 0 1024 1024" width="26" height="26" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Volkswagen">
            <g transform="matrix(10.188387870788574, 0, 0, 10.188387870788574, -251.519936680809, -252.79260253906244)">
              <path fill="currentColor" d="M75,120.4c-24.9,0-45.3-20.5-45.3-45.4c0-5.6,1-10.9,2.9-15.9l26.5,53.3c0.3,0.7,0.8,1.3,1.6,1.3c0.8,0,1.3-0.6,1.6-1.3l12.2-27.3c0.1-0.3,0.3-0.6,0.6-0.6s0.4,0.3,0.6,0.6l12.2,27.3c0.3,0.7,0.8,1.3,1.6,1.3c0.8,0,1.3-0.6,1.6-1.3l26.5-53.3c1.9,5,2.9,10.3,2.9,15.9C120.3,99.9,99.9,120.4,75,120.4z M75,64.7c-0.3,0-0.4-0.3-0.6-0.6l-14.2-32c4.6-1.7,9.6-2.6,14.8-2.6c5.2,0,10.2,0.9,14.8,2.6l-14.2,32C75.4,64.5,75.3,64.7,75,64.7z M60.5,97.6c-0.3,0-0.4-0.3-0.6-0.6l-23-46.4c4.1-6.3,9.6-11.6,16.3-15.3l16.6,36.9C70,72.8,70.5,73,71,73h8c0.6,0,1-0.1,1.3-0.8l16.6-36.9c6.6,3.7,12.2,9,16.3,15.3L90,97c-0.1,0.3-0.3,0.6-0.6,0.6c-0.3,0-0.4-0.3-0.6-0.6l-8.7-19.8c-0.3-0.7-0.7-0.8-1.3-0.8h-8c-0.6,0-1,0.1-1.3,0.8L61.1,97C61,97.3,60.8,97.6,60.5,97.6z M75,125c27.7,0,50-22.3,50-50c0-27.7-22.3-50-50-50c-27.7,0-50,22.3-50,50C25,102.7,47.3,125,75,125z" />
            </g>
          </svg>
        </span>
        <div>
          <div className="rail-name">Volkswagen<br />Elite Motors</div>
          <div className="rail-place">Hosur Road, Bengaluru</div>
        </div>
      </div>
      


      <div className="rail-block">
        <select
          value={activePeriod}
          onChange={e => onPeriodChange(e.target.value)}
          className="period-select rail-period"
          title="Switch reporting month"
        >
          {periods.map(p => (
            <option key={p.label} value={p.label}>
              {p.label}{p.is_active ? ' · Active' : ''}
            </option>
          ))}
        </select>
        {span && <div className="rail-span">{span}</div>}
        <button className="rail-btn rail-quiet" onClick={onManagePeriods}
                style={{ padding: '4px 0', marginTop: 2 }}>
          <CalendarCog size={13} />
          <span>Manage months</span>
        </button>
        {/* The state comes from the same reader the footer uses, so the two
            can no longer disagree. The word stays ink; only the dot carries
            colour, and only a dot that means what it says. It moves once, when
            a change actually lands, instead of breathing forever - a pulse on
            every frame of every hour is indistinguishable from a pulse that
            means something. */}
        {(() => {
          const state = connection(liveStatus);
          const { label, tone } = CONNECTION[state];
          const fresh = justUpdated(liveStatus);
          return (
            <span className="live-badge rail-live" data-tone={tone}
                  role="status" aria-live="polite">
              <span className={`live-dot ${fresh ? 'is-fresh' : ''}`} aria-hidden="true" />
              {fresh ? 'Updated just now' : label}
            </span>
          );
        })()}
      </div>

      {/* The site's navigation. NavLink renders a real anchor with a real
          href, so the status bar shows where a link goes, middle-click and
          cmd-click still open a new tab, and the router only intercepts the
          plain left-click it can handle without breaking any of that. */}
      <nav className="rail-nav">
        {sections.map(s => (
          <NavLink
            key={s.id}
            to={s.path || `/${s.id}`}
            end={s.path === '/'}
            className={({ isActive }) => (isActive ? 'is-here' : '')}
          >
            {s.label}
          </NavLink>
        ))}
      </nav>

      {/* Six buttons is the longest thing in the rail, and most of the time the
          sheet is being read rather than written to. Folded away by default:
          the group states what it is, and opens when there is something to
          record. The rail scrolls, so this is a disclosure rather than a
          floating menu - a popover would be clipped by the rail's own
          overflow. */}
      <div
        className="rail-block"
        // Scoped to this group rather than bound to the window: the entry
        // drawer and the upload dialog both close on Escape, and a global
        // listener here would collapse the rail behind them.
        onKeyDown={e => {
          if (e.key === 'Escape' && recordOpen) {
            setRecordOpen(false);
            triggerRef.current?.focus();
          }
        }}
      >
        <button
          type="button"
          ref={triggerRef}
          className="rail-disclosure"
          aria-expanded={recordOpen}
          aria-controls="rail-record"
          onClick={() => setRecordOpen(o => !o)}
        >
          <span className="rail-legend">Record</span>
          <ChevronDown size={13} className={`rail-chevron${recordOpen ? ' is-open' : ''}`} />
        </button>

        <div id="rail-record" ref={recordRef}
             className={`rail-drawer${recordOpen ? ' is-open' : ''}`}>
          {/* The inner wrapper is what gets clipped while the row collapses;
              the group itself has to keep its natural height for the
              animation to have something to travel to. */}
          <div className="rail-drawer-inner" aria-hidden={!recordOpen}>
            {ENTRIES.map(({ tab, label, Icon }) => (
              <button key={tab} className="rail-btn" tabIndex={recordOpen ? 0 : -1}
                      onClick={() => onOpenDrawer(tab)}>
                <Icon size={14} />
                <span>{label}</span>
              </button>
            ))}
            <button className="rail-btn rail-btn-accent" tabIndex={recordOpen ? 0 : -1}
                    onClick={onOpenUpload}>
              <UploadCloud size={14} />
              <span>Upload report</span>
            </button>
            {/* The same door, the other way round: a workbook comes in above, and
                goes back out here. */}
            <button className="rail-btn rail-btn-accent" tabIndex={recordOpen ? 0 : -1}
                    onClick={onOpenExport}>
              <Download size={14} />
              <span>Export data</span>
            </button>
          </div>
        </div>
      </div>

      <div className="rail-foot">
        <button className="rail-btn rail-quiet" onClick={onRefresh} disabled={isRefreshing}>
          <RefreshCw size={13}
                     style={isRefreshing ? { animation: 'spin 0.9s linear infinite' } : undefined} />
          <span>{isRefreshing ? 'Refreshing' : 'Refresh'}</span>
        </button>
        <button className="rail-btn rail-quiet" onClick={onToggleTables} aria-pressed={showTables}>
          <Table size={13} />
          <span>{showTables ? 'Hide records' : 'Show records'}</span>
        </button>
        <button
          className="rail-btn rail-quiet"
          onClick={onToggleTheme}
          aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
        >
          {theme === 'dark' ? <Sun size={13} /> : <Moon size={13} />}
          <span>{theme === 'dark' ? 'Light sheet' : 'Night sheet'}</span>
        </button>
      </div>
    </aside>
  );
}
