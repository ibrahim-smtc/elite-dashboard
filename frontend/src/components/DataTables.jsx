/**
 * The record tables.
 *
 * One generic table drives all three tabs. That is the point: search used to be
 * wired to the order book alone, so typing a query and switching tabs filtered
 * nothing, and each tab re-implemented its own row markup. Columns are declared
 * per tab and searching, sorting and export are derived from that declaration,
 * so a new tab cannot arrive missing one of them. The table itself is shared
 * with the Overview's drill-downs (records.jsx).
 */

import React from 'react';
import { Search, Download } from 'lucide-react';
import { n0, pct } from '../api/client';
import {
  BACKORDER_COLUMNS, BOOKING_COLUMNS, RecordTable, downloadCsv, txt, useRecordView,
} from './records';

const TABS = {
  bookings: {
    label: 'Order Book',
    file: 'order-book',
    empty: 'No bookings recorded for this period.',
    columns: BOOKING_COLUMNS,
  },
  sources: {
    label: 'Lead Sources',
    file: 'lead-sources',
    empty: 'No lead sources for this period.',
    columns: [
      { key: 'source', label: 'Source', strong: true },
      { key: 'channel', label: 'Channel', muted: true, value: r => txt(r.channel || 'Direct') },
      { key: 'leads', label: 'Enquiries', num: true, sortAs: r => Number(r.leads) || 0,
        render: r => n0(r.leads) },
      { key: 'qualified', label: 'Qualified', num: true, sortAs: r => Number(r.qualified) || 0,
        render: r => n0(r.qualified) },
      { key: 'qualified_pct', label: 'Qualified %', num: true,
        sortAs: r => Number(r.qualified_pct) || 0, render: r => pct(r.qualified_pct) },
    ],
  },
  backorders: {
    label: 'Backorders',
    file: 'backorders',
    empty: 'Nothing is waiting on stock.',
    columns: BACKORDER_COLUMNS,
  },
};

export default function DataTables({ orderbook = [], sources = [], backorders = [] }) {
  const [tab, setTab] = React.useState('bookings');

  const rowsFor = { bookings: orderbook, sources, backorders };
  const spec = TABS[tab];
  const rows = rowsFor[tab] || [];
  const { query, setQuery, sort, toggleSort, resetSort, visible } = useRecordView(rows, spec.columns);

  return (
    <div className="panel" style={{ marginTop: '26px' }}>
      <div className="panel-head" style={{ flexWrap: 'wrap', gap: '12px', alignItems: 'center' }}>
        <div>
          <h2>Records</h2>
          <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)', marginTop: 3 }}>
            {query
              ? `${n0(visible.length)} of ${n0(rows.length)} rows match “${query}”`
              : `${n0(rows.length)} rows`}
          </div>
        </div>

        <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: '6px',
            background: 'var(--surface-sub)', borderRadius: 'var(--radius-sm)',
            padding: '5px 10px', border: '1px solid var(--grid)',
          }}>
            <Search size={14} style={{ color: 'var(--ink-muted)' }} />
            <input
              type="text"
              placeholder={`Search ${spec.label.toLowerCase()}…`}
              value={query}
              onChange={e => setQuery(e.target.value)}
              aria-label={`Search ${spec.label}`}
              style={{ border: 'none', background: 'transparent', padding: '2px', outline: 'none' }}
            />
          </div>

          <div style={{ display: 'flex', gap: '4px' }}>
            {Object.entries(TABS).map(([key, t]) => (
              <button
                key={key}
                className={tab === key ? 'primary' : ''}
                onClick={() => { setTab(key); resetSort(); }}
                aria-pressed={tab === key}
              >
                {t.label} ({n0((rowsFor[key] || []).length)})
              </button>
            ))}
          </div>

          <button onClick={() => downloadCsv(spec.columns, visible, spec.file)}
                  disabled={!visible.length} title="Download what is shown as CSV">
            <Download size={14} />
            <span>Export</span>
          </button>
        </div>
      </div>

      <RecordTable columns={spec.columns} rows={visible} sort={sort} onSort={toggleSort}
                   empty={spec.empty} query={query} />
    </div>
  );
}
