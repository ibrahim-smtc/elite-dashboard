/**
 * What is behind a figure on the Overview.
 *
 * Each figure was a number and nothing more: asked which cars the 17 retails
 * were, the dashboard could not say. A click on a tile - or on the bookings
 * figure - opens the rows that figure counts, for the month the dashboard is
 * set to, searchable, sortable and exportable like the Records panel.
 *
 * Every list adds up to its tile. Most come with the dashboard's own data
 * (the month's bookings, backorders, free stock, scorecards and source mix)
 * and open at once; retails and enquiries are not in it, and are fetched on
 * opening from endpoints that count exactly as the headline does.
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Search, Download } from 'lucide-react';
import { api, dt, money, n0, pct } from '../api/client';
import useClosing from './useClosing';
import {
  BACKORDER_COLUMNS, BOOKING_COLUMNS, RecordTable, downloadCsv, txt, useRecordView,
} from './records';

const num = v => (v == null ? 0 : Number(v));
const share = (part, whole) => (whole > 0 ? (100 * part) / whole : null);
const plural = (n, one, many = `${one}s`) => `${n0(n)} ${n === 1 ? one : many}`;

/* A date column: sorted as a date, shown and searched as the dashboard writes one. */
const dateColumn = (key, label) => ({
  key, label, muted: true,
  sortAs: r => (r[key] ? new Date(r[key]).getTime() : -Infinity),
  render: r => dt(r[key]),
  value: r => (r[key] ? dt(r[key]) : ''),
});

const RETAIL_COLUMNS = [
  { key: 'customer_name', label: 'Customer', strong: true },
  { key: 'consultant', label: 'Consultant' },
  { key: 'model', label: 'Model' },
  {
    key: 'variant', label: 'Variant / Colour', muted: true,
    value: r => [r.variant, r.colour].filter(Boolean).join(' · '),
  },
  { key: 'chassis_number', label: 'Chassis', muted: true },
  dateColumn('nadcon_retail_date', 'Retailed'),
  { key: 'finance', label: 'Finance', value: r => [r.finance_type, r.bank].filter(Boolean).join(' · ') },
  {
    key: 'has_insurance', label: 'Insurance',
    value: r => (r.has_insurance === true ? 'Yes' : r.has_insurance === false ? 'No' : ''),
  },
];

/* No consultant or status column: the CRM export carries neither, so for a
   loaded month they were a column of dashes. The source names the referrer
   where there is one. */
const ENQUIRY_COLUMNS = [
  { key: 'lead_name', label: 'Name', strong: true },
  {
    key: 'channel', label: 'Source',
    value: r => [r.channel, r.source && r.source !== r.channel ? r.source : null].filter(Boolean).join(' · '),
  },
  { key: 'model', label: 'Model' },
  {
    key: 'qualified_stage', label: 'Qualified',
    value: r => (r.qualified_stage === 'Qualified' ? 'Yes' : ''),
  },
  dateColumn('created_at', 'Came in'),
];

const TEST_DRIVE_COLUMNS = [
  { key: 'consultant', label: 'Consultant', strong: true },
  { key: 'team', label: 'Team', muted: true },
  {
    key: 'td_achieved', label: 'Test drives', num: true, strong: true,
    sortAs: r => num(r.td_achieved), render: r => n0(num(r.td_achieved)),
  },
  {
    key: 'td_target', label: 'Target', num: true,
    sortAs: r => num(r.td_target), render: r => (r.td_target == null ? '–' : n0(num(r.td_target))),
  },
  {
    key: 'td_share', label: 'Of target', num: true,
    sortAs: r => share(num(r.td_achieved), num(r.td_target)) ?? -1,
    render: r => pct(share(num(r.td_achieved), num(r.td_target))),
    value: r => txt(pct(share(num(r.td_achieved), num(r.td_target)))),
  },
];

const CONVERSION_COLUMNS = [
  { key: 'channel', label: 'Source', strong: true },
  { key: 'enquiries', label: 'Enquiries', num: true, sortAs: r => r.enquiries, render: r => n0(r.enquiries) },
  { key: 'bookings', label: 'Bookings', num: true, sortAs: r => r.bookings, render: r => n0(r.bookings) },
  {
    key: 'conversion', label: 'Enquiry to booking', num: true, strong: true,
    sortAs: r => r.conversion ?? -1, render: r => pct(r.conversion), value: r => txt(pct(r.conversion)),
  },
];

const STOCK_COLUMNS = [
  { key: 'model', label: 'Model', strong: true },
  { key: 'variant', label: 'Variant', muted: true },
  { key: 'colour', label: 'Colour', muted: true },
  { key: 'chassis_number', label: 'Chassis', muted: true },
  {
    key: 'stock_aging_days', label: 'In stock', num: true,
    sortAs: r => num(r.stock_aging_days),
    // Ninety days is where a car starts to carry interest - the ageing the
    // Overview's own tile used to count - so only those are inked red.
    render: r => (
      <span style={{
        fontWeight: 600,
        color: num(r.stock_aging_days) > 90 ? 'var(--critical)' : 'var(--ink)',
      }}>
        {r.stock_aging_days != null ? `${n0(r.stock_aging_days)}d` : '–'}
      </span>
    ),
    value: r => txt(r.stock_aging_days),
  },
];

/* The month's enquiries from the source mix and its bookings from the order
   book, by channel - so the rows add up to the tile's own two totals. */
function byChannel(sources, orderbook) {
  const rows = {};
  const row = c => (rows[c] = rows[c] || { channel: c, enquiries: 0, bookings: 0 });
  sources.forEach(s => { row(s.channel || 'Not recorded').enquiries += num(s.leads); });
  orderbook.forEach(b => { row(b.source_channel || 'Not recorded').bookings += 1; });
  return Object.values(rows)
    .map(r => ({ ...r, conversion: share(r.bookings, r.enquiries) }))
    .sort((a, b) => b.enquiries - a.enquiries || b.bookings - a.bookings);
}

const sum = (rows, key) => rows.reduce((t, r) => t + num(r[key]), 0);

const DETAILS = {
  retails: {
    title: 'Retails delivered',
    fetch: '/api/retails',
    columns: RETAIL_COLUMNS,
    file: 'retails',
    rowKey: r => r.registration_id,
    empty: 'No retails recorded for this month.',
    line: (rows, month) => `${plural(rows.length, 'car')} retailed in ${month}`,
  },
  enquiries: {
    title: 'Enquiries',
    fetch: '/api/enquiries',
    columns: ENQUIRY_COLUMNS,
    file: 'enquiries',
    rowKey: r => r.lead_id,
    empty: 'No enquiries recorded for this month.',
    line: (rows, month) => `${plural(rows.length, 'enquiry', 'enquiries')} in ${month}, `
      + `${n0(rows.filter(r => r.qualified_stage === 'Qualified').length)} qualified`,
  },
  test_drives: {
    title: 'Test drives by consultant',
    rows: d => (d.scorecards || [])
      .filter(s => s.row_kind === 'CONSULTANT' && (num(s.td_achieved) || num(s.td_target)))
      .sort((a, b) => num(b.td_achieved) - num(a.td_achieved)),
    columns: TEST_DRIVE_COLUMNS,
    file: 'test-drives-by-consultant',
    rowKey: (r, i) => `${r.consultant}-${i}`,
    empty: 'No scorecard has been loaded for this month.',
    line: (rows, month) => `${plural(sum(rows, 'td_achieved'), 'test drive')} in ${month}, `
      + 'from the DSR scorecard',
  },
  bookings: {
    title: 'Bookings',
    rows: d => d.orderbook || [],
    columns: BOOKING_COLUMNS,
    file: 'bookings',
    rowKey: r => r.booking_id,
    empty: 'No bookings recorded for this month.',
    line: (rows, month) => `${plural(rows.length, 'booking')} in ${month} · `
      + `${money(sum(rows, 'booking_amount'))} collected in advances`,
  },
  conversion: {
    title: 'Enquiry to booking, by source',
    rows: d => byChannel(d.sources || [], d.orderbook || []),
    columns: CONVERSION_COLUMNS,
    file: 'enquiry-to-booking',
    rowKey: r => r.channel,
    empty: 'No enquiries or bookings recorded for this month.',
    line: (rows, month) => {
      const e = sum(rows, 'enquiries'), b = sum(rows, 'bookings');
      return `${plural(b, 'booking')} from ${plural(e, 'enquiry', 'enquiries')} in ${month} `
        + `(${pct(share(b, e))})`;
    },
  },
  free_stock: {
    title: 'Free stock',
    rows: d => d.options?.free_chassis || [],
    columns: STOCK_COLUMNS,
    file: 'free-stock',
    rowKey: r => r.chassis_number,
    empty: 'No cars in free stock.',
    line: rows => `${plural(rows.length, 'car')} in free stock now, oldest first · `
      + `${n0(rows.filter(r => num(r.stock_aging_days) > 90).length)} over 90 days`,
  },
  backorders: {
    title: 'Backorders',
    rows: d => (d.backorders || []).filter(b => b.is_current_period),
    columns: BACKORDER_COLUMNS.filter(c => c.key !== 'is_current_period'),
    file: 'backorders',
    rowKey: r => r.booking_id,
    empty: 'None of this month’s bookings is waiting for a car.',
    line: (rows, month) => `${plural(rows.length, 'booking')} from ${month} waiting for a car`,
  },
  crm_pending: {
    title: 'Pending CRM punch',
    rows: d => (d.orderbook || []).filter(b => b.crm_entry_done === false),
    columns: BOOKING_COLUMNS,
    file: 'pending-crm-punch',
    rowKey: r => r.booking_id,
    empty: 'Every booking this month is in the CRM.',
    line: (rows, month) => `${plural(rows.length, 'booking')} from ${month} not yet entered in the CRM`,
  },
};

/* "September 2026", from the month the dashboard is set to. */
function monthName(period) {
  if (!period?.period_start) return 'this month';
  const d = new Date(`${String(period.period_start).slice(0, 10)}T00:00:00`);
  return d.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' });
}

function DetailBody({ spec, rows, loading, error, month, onClose }) {
  const { query, setQuery, sort, toggleSort, visible } = useRecordView(rows, spec.columns);
  return (
    <>
      <div className="kpi-detail-head">
        <div>
          <h2>{spec.title}</h2>
          <div className="kpi-detail-line">
            {loading ? 'Reading the records…' : error ? ' ' : spec.line(rows, month)}
            {!loading && !error && query && ` · ${n0(visible.length)} match “${query}”`}
          </div>
        </div>
        <button type="button" className="rail-quiet" onClick={onClose} aria-label="Close">Close</button>
      </div>

      {error ? (
        <div className="kpi-detail-error">{error}</div>
      ) : (
        <>
          <div className="kpi-detail-tools">
            <label className="kpi-detail-search">
              <Search size={14} style={{ color: 'var(--ink-muted)' }} />
              <input
                type="text"
                placeholder={`Search ${spec.title.toLowerCase()}…`}
                value={query}
                onChange={e => setQuery(e.target.value)}
                aria-label={`Search ${spec.title}`}
              />
            </label>
            <button onClick={() => downloadCsv(spec.columns, visible, spec.file)}
                    disabled={!visible.length} title="Download what is shown as CSV">
              <Download size={14} />
              <span>Export</span>
            </button>
          </div>
          <RecordTable columns={spec.columns} rows={visible} sort={sort} onSort={toggleSort}
                       empty={loading ? 'Reading the records…' : spec.empty} query={query}
                       rowKey={spec.rowKey} maxHeight="none" />
        </>
      )}
    </>
  );
}

export default function OverviewDetail({ which, data, period, onClose }) {
  const open = !!DETAILS[which];
  const { render, leaving } = useClosing(open);
  // Keep showing what was open while it animates away.
  const shown = useRef(which);
  if (open) shown.current = which;
  const key = shown.current;
  const spec = DETAILS[key];

  const [fetched, setFetched] = useState({ key: null, rows: [], error: null, loading: false });
  useEffect(() => {
    if (!open || !spec?.fetch) return undefined;
    let cancelled = false;
    setFetched({ key, rows: [], error: null, loading: true });
    api(spec.fetch)
      .then(res => { if (!cancelled) setFetched({ key, rows: res.rows || [], error: res.error || null, loading: false }); })
      .catch(err => { if (!cancelled) setFetched({ key, rows: [], error: err.message || 'The records could not be read.', loading: false }); });
    return () => { cancelled = true; };
  }, [open, key, spec, period?.label]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = e => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  // Focus moves into the dialog once it is on the page, and back to the
  // figure that opened it when it closes, so a keyboard user stays put.
  const panel = useRef(null);
  const opener = useRef(null);
  useEffect(() => {
    if (open && render) {
      if (!opener.current) opener.current = document.activeElement;
      panel.current?.focus();
    } else if (!open && opener.current) {
      opener.current.focus?.();
      opener.current = null;
    }
  }, [open, render, key]);

  const rows = useMemo(() => {
    if (!spec) return [];
    if (spec.fetch) return fetched.key === key ? fetched.rows : [];
    return spec.rows(data || {});
  }, [spec, key, data, fetched]);

  if (!render || !spec) return null;
  const loading = !!spec.fetch && (fetched.key !== key || fetched.loading);
  return (
    <div className={`drawer-scrim ${leaving ? 'is-leaving' : ''}`}
         style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
         onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={panel} tabIndex={-1} className="xp-panel kpi-detail"
           role="dialog" aria-modal="true" aria-label={spec.title}>
        <DetailBody key={key} spec={spec} rows={rows} loading={loading}
                    error={spec.fetch && fetched.key === key ? fetched.error : null}
                    month={monthName(period)} onClose={onClose} />
      </div>
    </div>
  );
}
