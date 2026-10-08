/**
 * What the month is made of, and how that is moving.
 *
 * "Sales over time" above already answers how much came in on each day. It
 * cannot answer what the volume consists of - whether Digital is growing while
 * Walk-in flattens, whether interest is drifting from Taigun to Virtus, or
 * whether the enquiries arriving are converting better or worse than last
 * week. Those are the questions a sales manager asks of a DSR, and none of
 * them are visible in a single bar per day.
 *
 * Three panels, all reading one endpoint so they always agree:
 *
 *   Channel mix   - stacked, because the question is share as well as volume.
 *   Model mix     - the same, for demand rather than source.
 *   Conversion    - a rate and a running total, which are different units, so
 *                   they get an axis each rather than being forced onto one.
 *
 * Enquiries and bookings only. Retails and test drives are deliberately absent:
 * every date on the Reg Report tab is blank and the test drive tab holds a 2024
 * export, so neither can be placed on a day without inventing the date. The
 * same reason the timeline above leaves them out.
 */

import React, { useEffect, useMemo, useState } from 'react';
import {
  BarChart, Bar, ComposedChart, Line, XAxis, YAxis, CartesianGrid,
  ResponsiveContainer, Tooltip as RechartsTooltip, Legend,
} from 'recharts';
import { AlertTriangle } from 'lucide-react';
import { api, n0, money, dt } from '../api/client';

const GRAINS = [
  { key: 'day', label: 'Day' },
  { key: 'week', label: 'Week' },
];

const AXIS = { fill: 'var(--ink-muted)', fontSize: 'var(--fs-small)' };

/* The ordinal ramp, which exists for exactly this - categories that need to be
   told apart without any of them shouting. "Other" is deliberately the quietest
   thing in the stack. */
const RAMP = ['var(--o1)', 'var(--o2)', 'var(--o3)', 'var(--o4)', 'var(--o5)',
              'var(--viz-2)'];
const colourFor = (name, i) =>
  (name === 'Other' ? 'var(--ink-muted)' : RAMP[i % RAMP.length]);

/** A bucket key reads as a date, not a label. */
function tick(key, grain) {
  const d = new Date(`${key}T00:00:00Z`);
  if (Number.isNaN(+d)) return key;
  const day = d.getUTCDate();
  const mon = d.toLocaleDateString('en-IN', { month: 'short', timeZone: 'UTC' });
  return grain === 'week' ? `${day} ${mon}` : String(day);
}

function heading(key, grain) {
  const d = new Date(`${key}T00:00:00Z`);
  if (Number.isNaN(+d)) return key;
  const full = d.toLocaleDateString('en-IN',
    { day: 'numeric', month: 'long', timeZone: 'UTC' });
  return grain === 'week' ? `Week of ${full}` : full;
}

function Tip({ active, payload, grain, unit }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload || {};
  // A stack is read as a total plus its parts, so the total is worth stating
  // rather than leaving the eye to add six numbers.
  const total = payload.reduce((a, s) => a + (Number(s.value) || 0), 0);
  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--grid)',
      padding: '10px 14px', borderRadius: 'var(--radius-sm)',
      boxShadow: 'var(--shadow-md)', color: 'var(--ink)', fontSize: 'var(--fs-small)',
      maxWidth: 260,
    }}>
      <div style={{ fontWeight: 700, marginBottom: 6 }}>{heading(p.key, grain)}</div>
      {payload.filter(s => s.value).map((s, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, lineHeight: 1.7 }}>
          <span style={{
            width: 8, height: 8, borderRadius: '50%',
            background: s.color || s.fill, flexShrink: 0,
          }} />
          <span style={{ color: 'var(--ink-2)' }}>{s.name}</span>
          <b style={{ marginLeft: 'auto' }}>
            {unit === 'pct' ? `${s.value}%`
              : unit === 'money' ? money(s.value)
              : n0(s.value)}
          </b>
        </div>
      ))}
      {unit === 'count' && (
        <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid var(--grid)',
                      display: 'flex', gap: 8 }}>
          <span style={{ color: 'var(--ink-muted)' }}>Total</span>
          <b style={{ marginLeft: 'auto' }}>{n0(total)}</b>
        </div>
      )}
    </div>
  );
}

function Panel({ title, note, children, height = 260 }) {
  return (
    <div className="panel" style={{ display: 'flex', flexDirection: 'column' }}>
      <div className="panel-header" style={{ marginBottom: 14 }}>
        <h2>{title}</h2>
        <span style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>{note}</span>
      </div>
      <div style={{ height, width: '100%' }}>{children}</div>
    </div>
  );
}

function Message({ children, tone }) {
  return (
    <div style={{
      display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center',
      color: tone === 'bad' ? 'var(--critical)' : 'var(--ink-muted)', fontSize: 'var(--fs-body)',
    }}>
      {children}
    </div>
  );
}

export default function Trends({ refreshKey }) {
  const [grain, setGrain] = useState('week');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let dead = false;
    setError(null);
    // Dropped before the next request, for the same reason the timeline drops
    // it: otherwise the old grain's buckets stay on screen while the new ones
    // load, and the summary line describes the wrong thing for a second.
    setData(null);
    api(`/api/sales/trends?grain=${grain}`)
      .then(res => { if (!dead) setData(res); })
      .catch(e => { if (!dead) setError(e.message); });
    return () => { dead = true; };
  }, [grain, refreshKey]);

  /* Recharts stacks by key, so the nested per-series objects are flattened onto
     the row. Prefixed, because a model and a channel could share a name. */
  const rows = useMemo(() => (data?.buckets || []).map(b => {
    const row = { ...b, tick: tick(b.key, grain) };
    (data.sources || []).forEach(s => { row[`s_${s}`] = b.by_source?.[s] || 0; });
    (data.models || []).forEach(m => { row[`m_${m}`] = b.by_model?.[m] || 0; });
    return row;
  }), [data, grain]);

  const totals = useMemo(() => rows.reduce((a, r) => ({
    enquiries: a.enquiries + r.enquiries,
    bookings: a.bookings + r.bookings,
  }), { enquiries: 0, bookings: 0 }), [rows]);

  const overall = totals.enquiries
    ? Math.round((1000 * totals.bookings) / totals.enquiries) / 10
    : null;

  const busiestChannel = useMemo(() => {
    if (!data?.sources?.length) return null;
    const sum = {};
    rows.forEach(r => data.sources.forEach(s => {
      sum[s] = (sum[s] || 0) + (r[`s_${s}`] || 0);
    }));
    const [name, n] = Object.entries(sum).sort((a, b) => b[1] - a[1])[0] || [];
    return name ? `${name} leads on ${n0(n)}` : null;
  }, [rows, data]);

  const loading = !data && !error;
  const empty = !loading && !error && !rows.length;

  const body = (render) => error ? <Message tone="bad">{error}</Message>
    : loading ? <Message>Reading the month…</Message>
    : empty ? <Message>Nothing recorded for this period yet.</Message>
    : render();

  const axisCommon = {
    dataKey: 'tick', axisLine: false, tickLine: false, tick: AXIS, dy: 8,
    interval: grain === 'day' ? 2 : 0,
  };

  return (
    <section style={{ marginBottom: 26 }}>
      <div className="panel-header" style={{ marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 14,
                      width: '100%', flexWrap: 'wrap' }}>
          <h2>What the month is made of</h2>
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
          {loading ? 'Reading the month…'
            : `${data?.period ?? ''} — ${n0(totals.enquiries)} enquiries, `
              + `${n0(totals.bookings)} bookings`
              + (overall != null ? ` · ${overall}% convert` : '')
              + (busiestChannel ? ` · ${busiestChannel}` : '')}
        </span>
      </div>

      {/* Same disclosure the timeline makes: a workbook loaded into a month it
          was not written for keeps its own dates, so the axis can legitimately
          run outside the month named above it. */}
      {data?.dates_outside_period && data?.covers && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: 8,
          margin: '0 0 14px', padding: '9px 12px',
          border: '1px solid var(--warning)', background: 'var(--critical-light)',
          fontSize: 'var(--fs-small)', lineHeight: 1.5, color: 'var(--warning)',
        }}>
          <AlertTriangle size={14} style={{ flex: 'none', marginTop: 1 }} />
          <span>
            Filed under <b>{data.period}</b> but carrying dates from{' '}
            <b>{dt(data.covers[0])} – {dt(data.covers[1])}</b>, so these follow
            the dates rather than the month.
          </span>
        </div>
      )}

      <div className="grid-2" style={{ marginBottom: 20 }}>
        <Panel title="Where enquiries come from"
               note="Channel mix, largest at the base">
          {body(() => (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} margin={{ top: 6, right: 12, left: -18, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--grid)" />
                <XAxis {...axisCommon} />
                <YAxis axisLine={false} tickLine={false} tick={AXIS} />
                <RechartsTooltip content={p => <Tip {...p} grain={grain} unit="count" />}
                                 cursor={{ fill: 'var(--grid)', opacity: 0.35 }} />
                <Legend wrapperStyle={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)', paddingTop: 8 }}
                        iconType="circle" />
                {(data?.sources || []).map((s, i) => (
                  <Bar key={s} dataKey={`s_${s}`} name={s} stackId="src"
                       fill={colourFor(s, i)} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          ))}
        </Panel>

        <Panel title="Which models are drawing interest"
               note="Enquiries by model of interest">
          {body(() => (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} margin={{ top: 6, right: 12, left: -18, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--grid)" />
                <XAxis {...axisCommon} />
                <YAxis axisLine={false} tickLine={false} tick={AXIS} />
                <RechartsTooltip content={p => <Tip {...p} grain={grain} unit="count" />}
                                 cursor={{ fill: 'var(--grid)', opacity: 0.35 }} />
                <Legend wrapperStyle={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)', paddingTop: 8 }}
                        iconType="circle" />
                {(data?.models || []).map((m, i) => (
                  <Bar key={m} dataKey={`m_${m}`} name={m} stackId="mdl"
                       fill={colourFor(m, i)} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          ))}
        </Panel>
      </div>

      <Panel title="Conversion and cash"
             note="Bookings per hundred enquiries, against advance collected to date"
             height={280}>
        {body(() => (
          <ResponsiveContainer width="100%" height="100%">
            {/* A percentage and a rupee total share no scale, so they get an
                axis each. Forcing them onto one would flatten whichever is
                smaller into the floor. */}
            <ComposedChart data={rows} margin={{ top: 6, right: 8, left: -14, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--grid)" />
              <XAxis {...axisCommon} />
              <YAxis yAxisId="pct" axisLine={false} tickLine={false} tick={AXIS}
                     unit="%" />
              <YAxis yAxisId="cash" orientation="right" axisLine={false} tickLine={false}
                     tick={AXIS} tickFormatter={v => `${Math.round(v / 100000)}L`} />
              <RechartsTooltip content={p => <Tip {...p} grain={grain} unit="mixed" />}
                               cursor={{ fill: 'var(--grid)', opacity: 0.35 }} />
              <Legend wrapperStyle={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)', paddingTop: 8 }}
                      iconType="circle" />
              <Bar yAxisId="pct" dataKey="conversion" name="Conversion %"
                   fill="var(--viz-1)" radius={[3, 3, 0, 0]} />
              {/* connectNulls, so a quiet bucket breaks the conversion bar but
                  does not tear the cumulative line, which never goes down. */}
              <Line yAxisId="cash" type="monotone" dataKey="cumulative_revenue"
                    name="Advance collected" stroke="var(--viz-2)" strokeWidth={2}
                    dot={false} connectNulls />
            </ComposedChart>
          </ResponsiveContainer>
        ))}
      </Panel>
    </section>
  );
}
