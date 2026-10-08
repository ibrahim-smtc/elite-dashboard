/**
 * Lead sources and model demand.
 *
 * Both charts previously ran an eight-colour palette of their own, which
 * survived the theme change and was the last thing on the page not made of ink.
 * Sources are now a ranked bar in a single hue - the bar length already carries
 * the magnitude, so varying colour per source added nothing but noise, and a
 * horizontal bar reads names like "WORKSHOP REFERRAL" that a donut cannot.
 */

import React from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer,
  Tooltip as RechartsTooltip, Legend, LabelList,
} from 'recharts';

const AXIS = { fill: 'var(--ink-muted)', fontSize: 'var(--fs-small)' };

function Tip({ active, payload, label, rows }) {
  if (!active || !payload || !payload.length) return null;
  const point = payload[0].payload || {};
  return (
    <div style={{
      background: 'var(--surface)',
      border: '1px solid var(--grid)',
      padding: '10px 14px',
      borderRadius: 'var(--radius-sm)',
      boxShadow: 'var(--shadow-md)',
      color: 'var(--ink)',
      fontSize: 'var(--fs-small)',
    }}>
      <div style={{ fontWeight: 700, marginBottom: 6 }}>{label}</div>
      {payload.map((entry, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, lineHeight: 1.7 }}>
          <span style={{
            width: 8, height: 8, borderRadius: '50%',
            background: entry.color || entry.fill, flexShrink: 0,
          }} />
          <span style={{ color: 'var(--ink-2)' }}>{entry.name}</span>
          <b style={{ marginLeft: 'auto' }}>{entry.value}</b>
        </div>
      ))}
      {rows && point.qualified != null && (
        <div style={{ marginTop: 6, color: 'var(--ink-muted)' }}>
          {point.qualified} qualified &middot; {point.qualified_pct}%
        </div>
      )}
    </div>
  );
}

function Empty({ children }) {
  return (
    <div style={{
      display: 'flex', height: '100%', alignItems: 'center',
      justifyContent: 'center', color: 'var(--ink-muted)', fontSize: 'var(--fs-body)',
    }}>
      {children}
    </div>
  );
}

export default function Visualizations({ sources = [], models = [] }) {
  const sourceData = sources
    .filter(s => s.leads > 0)
    .sort((a, b) => b.leads - a.leads)
    .map(s => ({
      source: s.source,
      Leads: Number(s.leads) || 0,
      qualified: Number(s.qualified) || 0,
      qualified_pct: s.qualified_pct,
    }));

  // v_model_position names the count bookings_this_period; v_model_demand names
  // it bookings. This chart is fed the former, so reading m.bookings drew every
  // bar at zero. Accept either, so it keeps working whichever view supplies it.
  const barData = models.map(m => ({
    family: m.family || m.model || 'Unknown',
    Bookings: m.bookings_this_period ?? m.bookings ?? 0,
    'Free Stock': m.free_stock ?? 0,
  }));

  return (
    <div className="grid-2">
      {/* Lead sources - one series, so the title names it and no legend is needed. */}
      <div className="panel" style={{ display: 'flex', flexDirection: 'column' }}>
        <div className="panel-header">
          <h2>Lead Sources</h2>
          <span style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>
            Enquiries this period, largest first
          </span>
        </div>
        <div style={{ height: '300px', width: '100%' }}>
          {sourceData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={sourceData}
                layout="vertical"
                margin={{ top: 4, right: 44, left: 4, bottom: 0 }}
                barSize={17}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" horizontal={false} />
                <XAxis type="number" axisLine={false} tickLine={false} tick={AXIS} />
                <YAxis
                  type="category"
                  dataKey="source"
                  width={146}
                  axisLine={false}
                  tickLine={false}
                  tick={{ ...AXIS, fontSize: 'var(--fs-small)' }}
                  interval={0}
                />
                <RechartsTooltip
                  content={props => <Tip {...props} rows />}
                  cursor={{ fill: 'var(--grid)', opacity: 0.4 }}
                />
                <Bar dataKey="Leads" fill="var(--viz-1)" radius={[0, 3, 3, 0]}>
                  <LabelList
                    dataKey="Leads"
                    position="right"
                    style={{ fill: 'var(--ink-muted)', fontSize: 'var(--fs-small)' }}
                  />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <Empty>No lead data for this period</Empty>
          )}
        </div>
      </div>

      {/* Model demand vs supply */}
      <div className="panel" style={{ display: 'flex', flexDirection: 'column' }}>
        <div className="panel-header">
          <h2>Model Demand vs Supply</h2>
          <span style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>
            Bookings against cars on the floor
          </span>
        </div>
        <div style={{ height: '300px', width: '100%' }}>
          {barData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={barData}
                margin={{ top: 16, right: 10, left: -20, bottom: 0 }}
                barGap={2}
                barSize={30}
              >
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--grid)" />
                <XAxis
                  dataKey="family"
                  axisLine={false}
                  tickLine={false}
                  tick={AXIS}
                  dy={10}
                />
                <YAxis axisLine={false} tickLine={false} tick={AXIS} />
                <RechartsTooltip
                  content={props => <Tip {...props} />}
                  cursor={{ fill: 'var(--grid)', opacity: 0.4 }}
                />
                <Legend
                  wrapperStyle={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)', paddingTop: '10px' }}
                  iconType="circle"
                  payload={[
                    { value: 'Bookings', type: 'circle', id: 'b', color: 'var(--viz-1)' },
                    { value: 'Free Stock', type: 'circle', id: 'f', color: 'var(--viz-2)' },
                  ]}
                />
                <Bar dataKey="Bookings" fill="var(--viz-1)" radius={[3, 3, 0, 0]} />
                <Bar dataKey="Free Stock" fill="var(--viz-2)" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <Empty>No model data available</Empty>
          )}
        </div>
      </div>
    </div>
  );
}
