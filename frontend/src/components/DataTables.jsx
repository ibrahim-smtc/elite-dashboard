/**
 * The record tables.
 *
 * One generic table drives all three tabs. That is the point: search used to be
 * wired to the order book alone, so typing a query and switching tabs filtered
 * nothing, and each tab re-implemented its own row markup. Columns are declared
 * per tab and searching, sorting and export are derived from that declaration,
 * so a new tab cannot arrive missing one of them.
 */

import React, { useMemo, useState } from 'react';
import { Search, ArrowUpDown, ArrowUp, ArrowDown, Download } from 'lucide-react';
import { n0, money, dt, pct } from '../api/client';

/* Database enums are written for the database. ALLOTED is also misspelled at
   source, which is not something a consultant should have to read. */
const STATUS = {
  RETAILED:  { label: 'Retailed',  tint: 'var(--good)' },
  ALLOTED:   { label: 'Allotted',  tint: 'var(--viz-1)' },
  BOOKED:    { label: 'Booked',    tint: 'var(--ink-muted)' },
  NO_STOCK:  { label: 'No stock',  tint: 'var(--critical)' },
  CANCELLED: { label: 'Cancelled', tint: 'var(--ink-muted)' },
};

function StatusPill({ value }) {
  const s = STATUS[value] || { label: value || '–', tint: 'var(--ink-muted)' };
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      fontSize: 'var(--fs-small)', color: 'var(--ink-2)', whiteSpace: 'nowrap',
    }}>
      <span style={{
        width: 6, height: 6, flex: 'none', borderRadius: '50%', background: s.tint,
      }} />
      {s.label}
    </span>
  );
}

const txt = v => (v == null ? '' : String(v));

/* Column shape: {key, label, num?, render?, value?} - `value` is what search,
   sort and export see; `render` is only how it looks. */
const TABS = {
  bookings: {
    label: 'Order Book',
    file: 'order-book',
    empty: 'No bookings recorded for this period.',
    columns: [
      { key: 'customer_name', label: 'Customer', strong: true },
      { key: 'consultant', label: 'Consultant' },
      { key: 'model', label: 'Model' },
      {
        key: 'variant', label: 'Variant / Colour', muted: true,
        value: r => [r.variant, r.colour].filter(Boolean).join(' · '),
      },
      { key: 'source', label: 'Source', muted: true },
      {
        key: 'fulfilment_status', label: 'Status',
        value: r => (STATUS[r.fulfilment_status] || {}).label || txt(r.fulfilment_status),
        render: r => <StatusPill value={r.fulfilment_status} />,
      },
      {
        key: 'crm_entry_done', label: 'In CRM',
        value: r => (r.crm_entry_done === false ? 'Pending' : r.crm_entry_done ? 'Yes' : ''),
        render: r => (r.crm_entry_done === false
          ? <span style={{ color: 'var(--critical)', fontSize: 'var(--fs-small)' }}>Pending</span>
          : <span style={{ color: 'var(--ink-muted)', fontSize: 'var(--fs-small)' }}>Yes</span>),
      },
      {
        key: 'booking_date', label: 'Date', muted: true,
        sortAs: r => (r.booking_date ? new Date(r.booking_date).getTime() : -Infinity),
        render: r => dt(r.booking_date),
        value: r => dt(r.booking_date),
      },
      {
        key: 'booking_amount', label: 'Deposit', num: true, strong: true,
        sortAs: r => Number(r.booking_amount) || 0,
        render: r => (r.booking_amount ? money(r.booking_amount) : '–'),
        value: r => (r.booking_amount == null ? '' : String(r.booking_amount)),
      },
    ],
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
    columns: [
      { key: 'customer_name', label: 'Customer', strong: true },
      { key: 'model_family', label: 'Model', value: r => txt(r.model_family || r.model) },
      { key: 'variant', label: 'Variant', muted: true },
      { key: 'colour', label: 'Colour', muted: true },
      { key: 'consultant', label: 'Consultant' },
      {
        key: 'is_current_period', label: 'Period',
        value: r => (r.is_current_period ? 'This month' : 'Carried over'),
        render: r => (
          <span style={{
            fontSize: 'var(--fs-small)',
            color: r.is_current_period ? 'var(--ink-2)' : 'var(--ink-muted)',
          }}>
            {r.is_current_period ? 'This month' : 'Carried over'}
          </span>
        ),
      },
      {
        key: 'days_waiting', label: 'Waiting', num: true,
        sortAs: r => Number(r.days_waiting) || 0,
        // Only a genuinely long wait is worth inking red; every row in red
        // means none of them stands out.
        render: r => (
          <span style={{
            fontWeight: 600,
            color: Number(r.days_waiting) > 60 ? 'var(--critical)' : 'var(--ink)',
          }}>
            {r.days_waiting != null ? `${n0(r.days_waiting)}d` : '–'}
          </span>
        ),
        value: r => (r.days_waiting == null ? '' : String(r.days_waiting)),
      },
    ],
  },
};

const cellValue = (col, row) =>
  col.value ? col.value(row) : txt(row[col.key]);

function toCsv(columns, rows) {
  const esc = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
  return [
    columns.map(c => esc(c.label)).join(','),
    ...rows.map(r => columns.map(c => esc(cellValue(c, r))).join(',')),
  ].join('\r\n');
}

export default function DataTables({ orderbook = [], sources = [], backorders = [] }) {
  const [tab, setTab] = useState('bookings');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState({ key: null, dir: 'asc' });

  const rowsFor = { bookings: orderbook, sources, backorders };
  const spec = TABS[tab];
  const rows = rowsFor[tab] || [];

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    // Search every declared column of whichever tab is open, rather than a
    // hand-written list that only ever covered the order book.
    const matched = q
      ? rows.filter(r => spec.columns.some(c => cellValue(c, r).toLowerCase().includes(q)))
      : rows;
    if (!sort.key) return matched;
    const col = spec.columns.find(c => c.key === sort.key);
    if (!col) return matched;
    const keyOf = r => (col.sortAs ? col.sortAs(r) : cellValue(col, r).toLowerCase());
    return [...matched].sort((a, b) => {
      const x = keyOf(a), y = keyOf(b);
      if (x === y) return 0;
      return (x > y ? 1 : -1) * (sort.dir === 'asc' ? 1 : -1);
    });
  }, [rows, spec, query, sort]);

  const toggleSort = key =>
    setSort(s => (s.key === key
      ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
      : { key, dir: 'asc' }));

  const download = () => {
    const blob = new Blob([toCsv(spec.columns, visible)], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${spec.file}-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

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
                onClick={() => { setTab(key); setSort({ key: null, dir: 'asc' }); }}
                aria-pressed={tab === key}
              >
                {t.label} ({n0((rowsFor[key] || []).length)})
              </button>
            ))}
          </div>

          <button onClick={download} disabled={!visible.length} title="Download what is shown as CSV">
            <Download size={14} />
            <span>Export</span>
          </button>
        </div>
      </div>

      <div className="table-wrap" style={{ maxHeight: '460px' }}>
        <table>
          <thead>
            <tr>
              {spec.columns.map(c => {
                const active = sort.key === c.key;
                const Icon = !active ? ArrowUpDown : sort.dir === 'asc' ? ArrowUp : ArrowDown;
                return (
                  <th
                    key={c.key}
                    className={c.num ? 'num' : ''}
                    onClick={() => toggleSort(c.key)}
                    aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                    style={{ cursor: 'pointer', userSelect: 'none' }}
                    title={`Sort by ${c.label}`}
                  >
                    <span style={{
                      display: 'inline-flex', alignItems: 'center', gap: 5,
                      flexDirection: c.num ? 'row-reverse' : 'row',
                      color: active ? 'var(--ink-2)' : undefined,
                    }}>
                      {c.label}
                      <Icon size={11} style={{ opacity: active ? 0.9 : 0.32 }} />
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visible.length ? visible.map((r, i) => (
              <tr key={r.booking_id ?? r.source ?? i}>
                {spec.columns.map(c => (
                  <td
                    key={c.key}
                    className={c.num ? 'num' : ''}
                    style={{
                      fontWeight: c.strong ? 600 : undefined,
                      color: c.muted ? 'var(--ink-muted)' : undefined,
                    }}
                  >
                    {c.render ? c.render(r) : (cellValue(c, r) || '–')}
                  </td>
                )) }
              </tr>
            )) : (
              <tr>
                <td colSpan={spec.columns.length}
                    style={{ textAlign: 'center', color: 'var(--ink-muted)', padding: '28px' }}>
                  {query ? `Nothing matches “${query}”.` : spec.empty}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
