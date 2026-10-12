/**
 * Record tables, shared.
 *
 * The Records panel and the Overview's drill-downs show the same kind of
 * table, so they share one: columns are declared once, and searching, sorting
 * and export are derived from that declaration. A booking in a drill-down is
 * therefore the same row, read the same way, as it is in the Records panel.
 */

import React, { useMemo, useState } from 'react';
import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';
import { n0, money, dt } from '../api/client';

/* Database enums are written for the database. ALLOTED is also misspelled at
   source, which is not something a consultant should have to read. */
export const STATUS = {
  RETAILED:  { label: 'Retailed',  tint: 'var(--good)' },
  ALLOTED:   { label: 'Allotted',  tint: 'var(--viz-1)' },
  BOOKED:    { label: 'Booked',    tint: 'var(--ink-muted)' },
  NO_STOCK:  { label: 'No stock',  tint: 'var(--critical)' },
  CANCELLED: { label: 'Cancelled', tint: 'var(--ink-muted)' },
};

export function StatusPill({ value }) {
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

export const txt = v => (v == null ? '' : String(v));

/* Column shape: {key, label, num?, render?, value?} - `value` is what search,
   sort and export see; `render` is only how it looks. */
export const BOOKING_COLUMNS = [
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
];

export const BACKORDER_COLUMNS = [
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
];

export const cellValue = (col, row) =>
  col.value ? col.value(row) : txt(row[col.key]);

export function toCsv(columns, rows) {
  const esc = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
  return [
    columns.map(c => esc(c.label)).join(','),
    ...rows.map(r => columns.map(c => esc(cellValue(c, r))).join(',')),
  ].join('\r\n');
}

export function downloadCsv(columns, rows, file) {
  const blob = new Blob([toCsv(columns, rows)], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${file}-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/* Search across every declared column, and sort by one. */
export function useRecordView(rows, columns) {
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState({ key: null, dir: 'asc' });

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    // Search every declared column, rather than a hand-written list that
    // only ever covered the order book.
    const matched = q
      ? rows.filter(r => columns.some(c => cellValue(c, r).toLowerCase().includes(q)))
      : rows;
    if (!sort.key) return matched;
    const col = columns.find(c => c.key === sort.key);
    if (!col) return matched;
    const keyOf = r => (col.sortAs ? col.sortAs(r) : cellValue(col, r).toLowerCase());
    return [...matched].sort((a, b) => {
      const x = keyOf(a), y = keyOf(b);
      if (x === y) return 0;
      return (x > y ? 1 : -1) * (sort.dir === 'asc' ? 1 : -1);
    });
  }, [rows, columns, query, sort]);

  const toggleSort = key =>
    setSort(s => (s.key === key
      ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
      : { key, dir: 'asc' }));
  const resetSort = () => setSort({ key: null, dir: 'asc' });

  return { query, setQuery, sort, toggleSort, resetSort, visible };
}

export function RecordTable({
  columns, rows, sort, onSort, empty, query, rowKey, maxHeight = '460px',
}) {
  return (
    <div className="table-wrap" style={{ maxHeight }}>
      <table>
        <thead>
          <tr>
            {columns.map(c => {
              const active = sort.key === c.key;
              const Icon = !active ? ArrowUpDown : sort.dir === 'asc' ? ArrowUp : ArrowDown;
              return (
                <th
                  key={c.key}
                  className={c.num ? 'num' : ''}
                  onClick={() => onSort(c.key)}
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
          {rows.length ? rows.map((r, i) => (
            <tr key={rowKey ? rowKey(r, i) : (r.booking_id ?? r.source ?? i)}>
              {columns.map(c => (
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
              <td colSpan={columns.length}
                  style={{ textAlign: 'center', color: 'var(--ink-muted)', padding: '28px' }}>
                {query ? `Nothing matches “${query}”.` : empty}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
