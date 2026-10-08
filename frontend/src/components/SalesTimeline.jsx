/**
 * Sales over time, at day / week / month.
 *
 * The rest of the sheet answers "where does the month stand". This answers
 * "how did it get there" - which day the bookings landed on, which week ran
 * hot, how the months compare.
 *
 * Bookings and enquiries only. Retails belong here too, but every date on the
 * Reg Report tab - delivery, registration, invoice - is blank, and the test
 * drive tab carries 2024 dates, so neither can be placed on a day. Drawing them
 * would mean inventing dates, so the panel says so instead.
 */

import React, { useEffect, useMemo, useState } from 'react';
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, ResponsiveContainer,
  Tooltip as RechartsTooltip, Legend,
} from 'recharts';
import { AlertTriangle } from 'lucide-react';
import { api, n0, money, dt } from '../api/client';

const GRAINS = [
  { key: 'day', label: 'Day' },
  { key: 'week', label: 'Week' },
  { key: 'month', label: 'Month' },
];

const AXIS = { fill: 'var(--ink-muted)', fontSize: 'var(--fs-small)' };

/** "2026-08-03" reads as a date, not a label. Shape it for the grain. */
function tick(key, grain) {
  if (grain === 'month') return key;
  const d = new Date(`${key}T00:00:00Z`);
  if (Number.isNaN(+d)) return key;
  const day = d.getUTCDate();
  const mon = d.toLocaleDateString('en-IN', { month: 'short', timeZone: 'UTC' });
  return grain === 'week' ? `${day} ${mon}` : String(day);
}

function Tip({ active, payload, label, grain }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload || {};
  const heading = grain === 'week' ? `Week of ${tick(p.key, 'week')}`
    : grain === 'month' ? p.key
    : new Date(`${p.key}T00:00:00Z`).toLocaleDateString('en-IN',
        { day: 'numeric', month: 'long', timeZone: 'UTC' });
  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--grid)',
      padding: '10px 14px', borderRadius: 'var(--radius-sm)',
      boxShadow: 'var(--shadow-md)', color: 'var(--ink)', fontSize: 'var(--fs-small)',
    }}>
      <div style={{ fontWeight: 700, marginBottom: 6 }}>{heading}</div>
      {payload.map((s, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, lineHeight: 1.7 }}>
          <span style={{
            width: 8, height: 8, borderRadius: '50%',
            background: s.color || s.fill, flexShrink: 0,
          }} />
          <span style={{ color: 'var(--ink-2)' }}>{s.name}</span>
          <b style={{ marginLeft: 'auto' }}>{n0(s.value)}</b>
        </div>
      ))}
      {p.revenue > 0 && (
        <div style={{ marginTop: 6, color: 'var(--ink-muted)' }}>
          {money(p.revenue)} taken
        </div>
      )}
    </div>
  );
}

export default function SalesTimeline({ refreshKey }) {
  const [grain, setGrain] = useState('day');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let dead = false;
    setError(null);
    // Drop the previous grain's response before fetching the next. Without
    // this the panel keeps rendering the old buckets for the second or so the
    // request is in flight, so switching to Day briefly reported "busiest day:
    // AUG2026" - a month bucket described as a day.
    setData(null);
    api(`/api/sales/timeline?grain=${grain}`)
      .then(res => { if (!dead) setData(res); })
      .catch(e => { if (!dead) setError(e.message); });
    return () => { dead = true; };
  }, [grain, refreshKey]);

  const rows = useMemo(
    () => (data?.buckets || []).map(b => ({ ...b, tick: tick(b.key, grain) })),
    [data, grain],
  );

  const totals = useMemo(() => rows.reduce((a, r) => ({
    bookings: a.bookings + r.bookings,
    enquiries: a.enquiries + r.enquiries,
    revenue: a.revenue + (r.revenue || 0),
  }), { bookings: 0, enquiries: 0, revenue: 0 }), [rows]);

  const best = useMemo(
    () => rows.reduce((a, r) => (r.bookings > (a?.bookings ?? -1) ? r : a), null),
    [rows],
  );

  return (
    <div className="panel" style={{ display: 'flex', flexDirection: 'column' }}>
      <div className="panel-header" style={{ marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, width: '100%', flexWrap: 'wrap' }}>
          <h2>Sales over time</h2>
          <div style={{ display: 'flex', gap: 4, marginLeft: 'auto' }}>
            {GRAINS.map(g => (
              <button
                key={g.key}
                onClick={() => setGrain(g.key)}
                aria-pressed={grain === g.key}
                className={grain === g.key ? 'primary' : ''}
                style={{ padding: '4px 12px', fontSize: 'var(--fs-small)' }}
              >
                {g.label}
              </button>
            ))}
          </div>
        </div>
        <span style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>
          {grain === 'month'
            ? 'Every month on record'
            : !data
              ? 'Reading the month…'
              : `${data.period} — ${n0(totals.bookings)} bookings, ${n0(totals.enquiries)} enquiries, ${money(totals.revenue)}`}
          {best && best.bookings > 0 && grain !== 'month' &&
            ` · busiest ${grain}: ${best.tick} (${n0(best.bookings)})`}
        </span>
      </div>

      {/* A workbook loaded into a month it was not written for keeps the dates
          it was written with, so the axis below can legitimately run outside
          the month named above it. Plotting that silently would be a chart
          disagreeing with its own title, so it is said out loud. */}
      {data && data.dates_outside_period && data.covers && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: 8,
          margin: '0 0 14px', padding: '9px 12px',
          border: '1px solid var(--warning)', background: 'var(--critical-light)',
          fontSize: 'var(--fs-small)', lineHeight: 1.5, color: 'var(--warning)',
        }}>
          <AlertTriangle size={14} style={{ flex: 'none', marginTop: 1 }} />
          <span>
            These rows are filed under <b>{data.period}</b> but carry dates from{' '}
            <b>{dt(data.covers[0])} – {dt(data.covers[1])}</b>, so the axis below
            follows the dates rather than the month. Usually it means a workbook
            was uploaded into a different month than it was written for.
          </span>
        </div>
      )}

      <div style={{ height: 300, width: '100%' }}>
        {error ? (
          <div style={{ display: 'flex', height: '100%', alignItems: 'center',
                        justifyContent: 'center', color: 'var(--critical)', fontSize: 'var(--fs-body)' }}>
            {error}
          </div>
        ) : !rows.length ? (
          <div style={{ display: 'flex', height: '100%', alignItems: 'center',
                        justifyContent: 'center', color: 'var(--ink-muted)', fontSize: 'var(--fs-body)' }}>
            {data ? 'Nothing recorded for this period yet.' : 'Reading the month…'}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            {/* Enquiries run an order of magnitude above bookings, so they are a
                line rather than a second bar - same axis, no second scale. */}
            <ComposedChart data={rows} margin={{ top: 10, right: 12, left: -18, bottom: 0 }}
                           barSize={grain === 'day' ? 12 : 30}>
              <CartesianGrid vertical={false} stroke="var(--grid)" strokeWidth={1} />
              <XAxis dataKey="tick" axisLine={false} tickLine={false} tick={AXIS} dy={8}
                     interval={grain === 'day' ? 2 : 0} />
              <YAxis axisLine={false} tickLine={false} tick={AXIS} />
              <RechartsTooltip content={props => <Tip {...props} grain={grain} />}
                               cursor={{ fill: 'var(--grid)', opacity: 0.35 }} />
              <Legend wrapperStyle={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)', paddingTop: 10 }}
                      iconType="circle"
                      payload={[
                        { value: 'Bookings', type: 'circle', id: 'b', color: 'var(--viz-1)' },
                        { value: 'Enquiries', type: 'circle', id: 'e', color: 'var(--viz-2)' },
                      ]} />
              <Bar dataKey="bookings" name="Bookings" fill="var(--viz-1)" radius={[3, 3, 0, 0]} />
              <Line type="monotone" dataKey="enquiries" name="Enquiries" stroke="var(--viz-2)"
                    strokeWidth={2} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
