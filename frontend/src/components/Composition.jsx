/**
 * The month as shares rather than counts.
 *
 * Everything on this panel answers "of the whole, how much is X", and a ring
 * is the shape people read as a share before they read anything else. The
 * three rings that stood here had that shape and very little else.
 *
 * Colour was dealt out by position in a list sorted largest-first, and the
 * first slot on the ramp is its palest. So the biggest slice in every ring was
 * the least visible thing in it - Virtus, the top seller at 48%, Candy White at
 * 31%, Allotted at 43%, all drawn a shade off the background - and because
 * Recharts sets legend text in the slice colour, the same three had the three
 * labels nobody could read. The paint ring coloured Carbon Steel Gray red,
 * because it happened to land on the sixth slot. No ring showed a number, and
 * all three printed "42 bookings" in the middle, under a heading that already
 * said it. The paint ring was smaller than the other two, because its legend
 * lived inside the chart and took the height.
 *
 * These keep the ring and fix what it was carrying:
 *
 *   Prominence follows size, or, for the order book, progress. The largest
 *   model is the strongest shade; the order book darkens clockwise through the
 *   stages a booking moves through, so the ring reads as a pipeline.
 *
 *   Paint is drawn in paint. It is the one place on the sheet where colour is
 *   the data rather than a code for it, and Other is hatched so it cannot pass
 *   for a grey paint or for Candy White.
 *
 *   The middle says something different in each ring - the leading share and
 *   what leads - and follows the pointer, so a ring answers a question instead
 *   of repeating the total.
 *
 *   The legend is a small table in ink with the count and the share on every
 *   row. It sits outside the chart, so all three rings are the same size
 *   however many categories they hold.
 *
 * Colour has twelve values, so its tail is folded into Other by the endpoint.
 *
 * The weekday chart is not a share at all. It is here because it answers the
 * question the shares provoke: enquiries arrive midweek and bookings close at
 * the weekend, which is a rostering fact rather than a sales one.
 */

import React, { useEffect, useState } from 'react';
import {
  PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  ResponsiveContainer, Tooltip as RechartsTooltip, Legend,
} from 'recharts';
import { api, n0 } from '../api/client';

const AXIS = { fill: 'var(--ink-muted)', fontSize: 'var(--fs-small)' };

/* The ordinal ramp, used now only by the two-way splits below. It is dealt by
   position, so it does not keep a category the same colour across charts - an
   earlier note here said it did. "Other" stays the quietest thing present. */
const RAMP = ['var(--o1)', 'var(--o2)', 'var(--o3)', 'var(--o4)', 'var(--o5)',
              'var(--viz-2)'];
const colourFor = (name, i) =>
  (name === 'Other' || name === 'Unspecified' ? 'var(--ink-muted)' : RAMP[i % RAMP.length]);

function BarTip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null;
  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--grid)',
      padding: '10px 14px', borderRadius: 'var(--radius-sm)',
      boxShadow: 'var(--shadow-md)', color: 'var(--ink)', fontSize: 'var(--fs-small)',
    }}>
      <div style={{ fontWeight: 700, marginBottom: 6 }}>{label}</div>
      {payload.map((s, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, lineHeight: 1.7 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%',
                         background: s.color || s.fill, flexShrink: 0 }} />
          <span style={{ color: 'var(--ink-2)' }}>{s.name}</span>
          <b style={{ marginLeft: 'auto' }}>{n0(s.value)}</b>
        </div>
      ))}
    </div>
  );
}

/* Approximate paint for a colour name. Matched on the word that names the
   hue, so "Deep Black Pearl" and "Deep Black Pearlescent" land on the same
   swatch, and checked in order so Carbon Steel Gray is the dark grey before
   "gray" alone can claim it, and Lava Blue the deep blue before "blue". A name
   that matches nothing falls back to plain ink rather than an invented hue. */
const PAINT = [
  [/white/i, '#f4f4f1'],
  [/black/i, '#17181b'],
  [/silver/i, '#b9bcc1'],
  [/carbon|graphite|charcoal/i, '#4b4f55'],
  [/gr[ae]y/i, '#83878d'],
  [/lava|lapiz|night|navy/i, '#1f3a6b'],
  [/blue/i, '#2f6cb2'],
  [/red|cherry|ruby|maroon/i, '#9d1c25'],
  [/yellow|curcuma|gold/i, '#dba427'],
  [/green|avocado|olive/i, '#667546'],
  [/orange|copper/i, '#c3622e'],
  [/brown|bronze|beige/i, '#7a5a3e'],
];
const paintFor = name => (PAINT.find(([re]) => re.test(name)) || [])[1] || null;

/* The endpoint sends model families in capitals. Everywhere else on the sheet
   they read as words - "Virtus", "Taigun (FL)" - so these do too; short and
   bracketed tokens are codes and keep their capitals. */
function label(name) {
  if (name !== name.toUpperCase()) return name;
  return name.split(/\s+/).map(w =>
    (w.length <= 3 || /[()\d]/.test(w)) ? w : w[0] + w.slice(1).toLowerCase(),
  ).join(' ');
}

/* A booking moves through these in order, so the ring runs clockwise in it. */
const PIPELINE = ['Booked', 'Awaiting stock', 'Allotted', 'Retailed'];
const byPipeline = rows => [...rows].sort((a, b) => {
  const ia = PIPELINE.indexOf(a.name), ib = PIPELINE.indexOf(b.name);
  return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
});
/* Largest first, with Other last however large it is: it is the remainder,
   not a contender. */
const bySize = rows => [...rows].sort((a, b) => {
  const oa = a.name === 'Other', ob = b.name === 'Other';
  if (oa !== ob) return oa ? 1 : -1;
  return b.value - a.value;
});

/* Prominence, strongest first. The ramp's first step is a shade off the
   ground in both themes - that is where the old rings put their biggest
   slice - so it is last here, reached only by a fifth category. o5 is the
   strongest in the day theme and the night one alike, because the ramp
   inverts with the ground. */
const PROMINENT = ['var(--o5)', 'var(--o4)', 'var(--o3)', 'var(--o2)', 'var(--o1)'];
const HATCH = 'url(#ring-hatch)';

/* Three ways to colour a slice, one per ring. */
const bySizeColour = (_r, i) => PROMINENT[Math.min(i, PROMINENT.length - 1)];
/* A pipeline darkens toward done, so the ring reads as progress: the stage
   furthest along is the strongest, whatever its size. */
const byStageColour = (_r, i, n) => PROMINENT[Math.min(Math.max(n - 1 - i, 0), PROMINENT.length - 1)];
/* Paint is the one ring where colour is the data. Other is hatched so it can
   be neither a grey paint nor Candy White. */
const paintColour = r => (r.name === 'Other' ? HATCH : paintFor(r.name) || 'var(--ink-muted)');

/** A ring that says what it shows. The middle carries the leading share - or,
    under the pointer, the share of whatever the pointer is on - and the legend
    carries every number, so nothing needs a hover to be read. */
function Ring({ title, note, rows = [], colourOf, outlined = false }) {
  const [active, setActive] = useState(null);
  const total = rows.reduce((a, d) => a + d.value, 0);
  const share = v => (total ? (100 * v) / total : 0);

  // The leader is the largest real category; Other never leads.
  const leader = rows.reduce(
    (best, r, i) => (r.name !== 'Other' && (best < 0 || r.value > rows[best].value) ? i : best), -1);
  const focus = active != null ? rows[active] : rows[leader];

  return (
    <div className="panel">
      <div className="panel-header" style={{ marginBottom: 6 }}>
        <h2>{title}</h2>
        <span style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>{note}</span>
      </div>
      {!rows.length || !total ? (
        <div className="ring-empty">Nothing recorded yet.</div>
      ) : (
        <>
          <div className="ring-chart" onMouseLeave={() => setActive(null)}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                {outlined && (
                  <defs>
                    <pattern id="ring-hatch" width="5" height="5"
                             patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                      <rect width="5" height="5" style={{ fill: 'var(--surface)' }} />
                      <line x1="0" y1="0" x2="0" y2="5"
                            style={{ stroke: 'var(--ink-muted)', strokeWidth: 1.6 }} />
                    </pattern>
                  </defs>
                )}
                {/* Clockwise from twelve o'clock, so the ring reads in the same
                    order as the legend beneath it. */}
                <Pie data={rows} dataKey="value" nameKey="name"
                     innerRadius="62%" outerRadius="88%"
                     startAngle={90} endAngle={-270}
                     paddingAngle={1} minAngle={3}
                     onMouseEnter={(_d, i) => setActive(i)}
                     onMouseLeave={() => setActive(null)}>
                  {rows.map((r, i) => (
                    <Cell key={r.name}
                          fill={colourOf(r, i, rows.length)}
                          fillOpacity={active == null || active === i ? 1 : 0.28}
                          // Paint has white and black in it, which vanish against
                          // one theme or the other without an edge; the blue rings
                          // read cleaner separated by a gap of the ground.
                          stroke={outlined ? 'var(--axis)' : 'var(--surface)'}
                          strokeWidth={outlined ? 1 : 2} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
            {focus && (
              <div className="ring-centre" aria-hidden="true">
                <div className="ring-share">{Math.round(share(focus.value))}%</div>
                <div className="ring-name">{label(focus.name)}</div>
              </div>
            )}
          </div>

          <ul className="ring-legend">
            {rows.map((r, i) => {
              const fill = colourOf(r, i, rows.length);
              const hatch = fill === HATCH;
              return (
                <li key={r.name}
                    className={active != null && active !== i ? 'is-dim' : undefined}
                    onMouseEnter={() => setActive(i)}
                    onMouseLeave={() => setActive(null)}>
                  <span className={`ring-swatch${hatch ? ' is-hatch' : ''}`}
                        data-outlined={outlined || undefined}
                        style={hatch ? undefined : { background: fill }}
                        aria-hidden="true" />
                  <span className="ring-label">{label(r.name)}</span>
                  <b>{n0(r.value)}</b>
                  <span className="ring-pct">{Math.round(share(r.value))}%</span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}

/** A two-way split is a single bar. A ring for two slices is a worse bar. */
function Split({ label, data }) {
  const total = (data || []).reduce((a, d) => a + d.value, 0);
  if (!total) return null;
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 'var(--fs-small)', textTransform: 'uppercase',
                       letterSpacing: '0.08em', color: 'var(--ink-muted)' }}>
          {label}
        </span>
      </div>
      <div style={{ display: 'flex', height: 10, overflow: 'hidden' }}>
        {data.map((d, i) => (
          <div key={d.name} title={`${d.name}: ${d.value}`}
               style={{ width: `${(100 * d.value) / total}%`,
                        background: colourFor(d.name, i) }} />
        ))}
      </div>
      <div style={{ display: 'flex', gap: 16, marginTop: 7, flexWrap: 'wrap' }}>
        {data.map((d, i) => (
          <span key={d.name} style={{ display: 'flex', alignItems: 'center', gap: 6,
                                      fontSize: 'var(--fs-small)', color: 'var(--ink-2)' }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%',
                           background: colourFor(d.name, i) }} />
            {d.name}
            <b style={{ color: 'var(--ink)' }}>{n0(d.value)}</b>
            <span style={{ color: 'var(--ink-muted)' }}>
              {Math.round((100 * d.value) / total)}%
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

export default function Composition({ refreshKey }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let dead = false;
    setError(null);
    api('/api/composition')
      .then(res => { if (!dead) setData(res); })
      .catch(e => { if (!dead) setError(e.message); });
    return () => { dead = true; };
  }, [refreshKey]);

  if (error) {
    return (
      <section style={{ marginBottom: 26 }}>
        <div className="panel">
          <div style={{ color: 'var(--critical)', fontSize: 'var(--fs-body)' }}>{error}</div>
        </div>
      </section>
    );
  }

  const peakEnq = (data?.weekday || []).reduce(
    (a, d) => (d.enquiries > (a?.enquiries ?? -1) ? d : a), null);
  const peakBook = (data?.weekday || []).reduce(
    (a, d) => (d.bookings > (a?.bookings ?? -1) ? d : a), null);

  return (
    <section style={{ marginBottom: 26 }}>
      <div className="panel-header" style={{ marginBottom: 14 }}>
        <h2>How the month splits</h2>
        <span style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>
          {!data ? 'Reading the month…'
            : `${data.period} — every ring totals the month's ${n0(
                (data.order_book || []).reduce((a, d) => a + d.value, 0))} bookings`}
        </span>
      </div>

      <div style={{
        display: 'grid', gap: 20, marginBottom: 20,
        gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
      }}>
        <Ring title="Where the order book stands"
              note="Every booking, clockwise through its stages"
              rows={byPipeline(data?.order_book || [])} colourOf={byStageColour} />
        <Ring title="What is selling"
              note="Bookings by model family"
              rows={bySize(data?.by_model || [])} colourOf={bySizeColour} />
        <Ring title="Colours customers choose"
              note="Bookings by paint, rarest folded into Other"
              rows={bySize(data?.by_colour || [])} colourOf={paintColour} outlined />
      </div>

      <div className="grid-2">
        <div className="panel">
          <div className="panel-header" style={{ marginBottom: 16 }}>
            <h2>Two-way splits</h2>
            <span style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>
              Where the car came from, and who sold it
            </span>
          </div>
          <Split label="Car origin" data={data?.by_origin} />
          <Split label="Team" data={data?.by_team} />
        </div>

        <div className="panel" style={{ display: 'flex', flexDirection: 'column' }}>
          <div className="panel-header" style={{ marginBottom: 14 }}>
            <h2>Which days are busy</h2>
            <span style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>
              {peakEnq && peakBook
                ? `Enquiries peak ${peakEnq.day} (${n0(peakEnq.enquiries)}), `
                  + `bookings ${peakBook.day} (${n0(peakBook.bookings)})`
                : 'Enquiries and bookings by day of the week'}
            </span>
          </div>
          <div style={{ height: 232, width: '100%' }}>
            <ResponsiveContainer width="100%" height="100%">
              {/* Two scales an order of magnitude apart, so bookings get the
                  right-hand axis - otherwise they are a flat line on the floor
                  under the enquiry bars. */}
              <BarChart data={data?.weekday || []}
                        margin={{ top: 6, right: 4, left: -18, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--grid)" />
                <XAxis dataKey="day" axisLine={false} tickLine={false} tick={AXIS} dy={8} />
                <YAxis yAxisId="e" axisLine={false} tickLine={false} tick={AXIS} />
                <YAxis yAxisId="b" orientation="right" axisLine={false}
                       tickLine={false} tick={AXIS} />
                <RechartsTooltip content={BarTip}
                                 cursor={{ fill: 'var(--grid)', opacity: 0.35 }} />
                <Legend wrapperStyle={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)', paddingTop: 8 }}
                        iconType="circle" />
                <Bar yAxisId="e" dataKey="enquiries" name="Enquiries"
                     fill="var(--viz-1)" radius={[3, 3, 0, 0]} />
                <Bar yAxisId="b" dataKey="bookings" name="Bookings"
                     fill="var(--viz-2)" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </section>
  );
}
