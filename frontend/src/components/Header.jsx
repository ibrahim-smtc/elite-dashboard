import React from 'react';
import { Sun, Moon, Table, RefreshCw, Database } from 'lucide-react';

export default function Header({
  periods = [],
  activePeriod = '',
  onPeriodChange,
  liveStatus = { state: 'off', text: 'connecting' },
  showTables,
  onToggleTables,
  theme,
  onToggleTheme,
}) {
  const activeObj = periods.find(p => p.label === activePeriod) || {};

  // "1 - 31 August 2026" rather than "2026-08-01 to 2026-08-31": the same fact,
  // written the way a person would say it. The month name carries the period,
  // so the AUG2026 code is left to the selector instead of being printed twice.
  const span = (() => {
    const { period_start: a, period_end: b } = activeObj;
    if (!a || !b) return null;
    const from = new Date(a), to = new Date(b);
    if (Number.isNaN(+from) || Number.isNaN(+to)) return null;
    const month = to.toLocaleDateString('en-IN', { month: 'long', year: 'numeric', timeZone: 'UTC' });
    return `${from.getUTCDate()}–${to.getUTCDate()} ${month}`;
  })();

  return (
    <header style={{
      display: 'flex',
      flexWrap: 'wrap',
      gap: '16px',
      alignItems: 'flex-end',
      justifyContent: 'space-between',
      marginBottom: '38px',
      paddingBottom: '22px',
      borderBottom: '1px solid var(--grid)',
    }}>
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
          <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '40px',
            height: '40px',
            border: '1.5px solid var(--shu)',
            color: 'var(--shu-ink)',
            fontWeight: '600',
            fontSize: 'var(--fs-body)',
            letterSpacing: '0.04em',
            borderRadius: '2px',
            transform: 'rotate(-2.5deg)',
            flex: 'none',
          }}>VW</span>
          <h1 style={{ margin: 0 }}>
            Volkswagen Elite Motors
          </h1>
        </div>
        <div style={{ color: 'var(--ink-muted)', fontSize: 'var(--fs-small)', letterSpacing: '0.04em' }}>
          {span ? (
            <span>
              {span} &nbsp;·&nbsp; Hosur Road, Bengaluru
            </span>
          ) : 'Preparing the sheet…'}
        </div>
      </div>

      <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
        <select
          value={activePeriod}
          onChange={e => onPeriodChange(e.target.value)}
          title="Switch reporting month"
          className="period-select"
        >
          {periods.map(p => (
            <option key={p.label} value={p.label}>
              {p.label} {p.is_active ? '· Active' : ''}
            </option>
          ))}
        </select>

        <span
          className="live-badge"
          title="Direct connection to Supabase PostgreSQL database"
        >
          <span className={`live-dot ${liveStatus.state === 'down' ? 'down' : ''}`} />
          <Database size={13} style={{ color: 'var(--ink-muted)' }} />
          <span>{liveStatus.text}</span>
        </span>

        <button
          onClick={onToggleTables}
          aria-pressed={showTables}
          aria-label={showTables ? 'Hide data tables' : 'Show data tables'}
          title="Toggle comprehensive data tables"
          style={{
            background: showTables ? 'var(--surface-sub)' : 'transparent',
            borderColor: showTables ? 'var(--axis)' : 'var(--border)',
          }}
        >
          <Table size={14} />
          <span>{showTables ? 'Hide data tables' : 'Show data tables'}</span>
        </button>

        <button
          onClick={onToggleTheme}
          title={theme === 'dark' ? 'Switch to the paper sheet' : 'Switch to the night sheet'}
          aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          style={{ padding: '7px 10px' }}
        >
          {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
        </button>
      </div>
    </header>
  );
}
