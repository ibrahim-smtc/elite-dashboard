import React from 'react';
import { Car, Layers, History } from 'lucide-react';
import { n0, dt } from '../api/client';

export default function StockAndModels({ models = [], ageing = [], activity = [] }) {
  // One bucket vocabulary, taken from the API rather than re-derived here. The
  // cards used to fold 91-180 and 180+ into a single ">90", so this panel and
  // the Stock Ageing chart above it banded the same cars differently.
  const BANDS = [
    { key: '0-30', label: '0–30 days', sub: 'Fresh stock', fill: 'var(--viz-a1)' },
    { key: '31-60', label: '31–60 days', sub: 'Healthy turn', fill: 'var(--viz-a2)' },
    { key: '61-90', label: '61–90 days', sub: 'Watchlist', fill: 'var(--viz-a3)' },
    { key: '91-180', label: '91–180 days', sub: 'Interest cost', fill: 'var(--viz-a4)' },
    { key: '180+', label: 'Over 180 days', sub: 'Write-down risk', fill: 'var(--viz-a5)' },
  ];

  const unitsIn = key =>
    ageing.filter(a => a.ageing_bucket === key)
          .reduce((sum, a) => sum + Number(a.units || 0), 0);

  // The ramp is the chart's ramp. Ageing is an ordered quantity, so it wears one
  // hue getting darker - a green-to-red traffic light beside a single-hue chart
  // meant the same forty-four cars were encoded two different ways on one screen.
  const bucketCards = BANDS.map(b => ({ ...b, count: unitsIn(b.key) }));


  // Per-model breakdown on the same five bands as the cards and the chart.
  const byModel = {};
  ageing.forEach(a => {
    const m = a.model || 'Unknown';
    if (!byModel[m]) {
      byModel[m] = Object.fromEntries([...BANDS.map(b => [b.key, 0]), ['total', 0]]);
    }
    const u = Number(a.units || 0);
    if (a.ageing_bucket in byModel[m]) byModel[m][a.ageing_bucket] += u;
    byModel[m].total += u;
  });
  const modelAgeingList = Object.entries(byModel)
    .map(([model, data]) => ({ model, ...data }))
    .sort((a, b) => b.total - a.total);

  // Totals for Model Performance
  const totBookings = models.reduce((s, m) => s + Number(m.bookings_this_period ?? m.bookings ?? 0), 0);
  const totRetails = models.reduce((s, m) => s + Number(m.registered ?? m.retails ?? 0), 0);
  const totFree = models.reduce((s, m) => s + Number(m.free_stock ?? 0), 0);
  const totStock = models.reduce((s, m) => s + Number(m.total_stock ?? ((m.free_stock || 0) + (m.allotted_stock || 0))), 0);

  return (
    <div className="grid-2">
      {/* Model Performance */}
      <div className="panel">
        <div className="panel-head">
          <div>
            <h2>Model Performance &amp; Inventory</h2>
            <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)', marginTop: '2px' }}>
              Bookings and free stock breakdown by vehicle model
            </div>
          </div>
          <Car size={18} style={{ color: 'var(--ink-muted)' }} />
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th className="num">Bookings</th>
                <th className="num">Retails</th>
                <th className="num" title="Free stock">Free</th>
                <th className="num" title="Total stock on the floor">On floor</th>
              </tr>
            </thead>
            <tbody>
              {models.length > 0 ? (
                models.map((m, idx) => {
                  const bk = Number(m.bookings_this_period ?? m.bookings ?? 0);
                  const rt = Number(m.registered ?? m.retails ?? 0);
                  const free = Number(m.free_stock ?? 0);
                  const total = Number(m.total_stock ?? ((m.free_stock || 0) + (m.allotted_stock || 0)));

                  return (
                    <tr key={m.model || idx}>
                      <td style={{ fontWeight: '600' }}>{m.model}</td>
                      <td className="num" style={{ fontWeight: '700', color: 'var(--s1)' }}>
                        {n0(bk)}
                      </td>
                      <td className="num" style={{ fontWeight: '600' }}>{n0(rt)}</td>
                      <td className="num" style={{ fontWeight: '600', color: 'var(--good-text)' }}>
                        {n0(free)}
                      </td>
                      <td className="num" style={{ color: 'var(--ink-muted)' }}>
                        {n0(total)}
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', color: 'var(--ink-muted)' }}>
                    No model data available.
                  </td>
                </tr>
              )}
            </tbody>
            {models.length > 0 && (
              <tfoot>
                <tr style={{ borderTop: '2px solid var(--axis)', fontWeight: '700', background: 'var(--surface-sub)' }}>
                  <td style={{ padding: '8px 10px' }}>Total Ground Position</td>
                  <td className="num" style={{ color: 'var(--s1)' }}>{n0(totBookings)}</td>
                  <td className="num">{n0(totRetails)}</td>
                  <td className="num" style={{ color: 'var(--good-text)' }}>{n0(totFree)}</td>
                  <td className="num" style={{ color: 'var(--ink-muted)' }}>{n0(totStock)}</td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </div>

      {/* Stock Ageing & Recent Cloud Activity */}
      <div className="panel" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div>
          <div className="panel-head" style={{ marginBottom: '10px' }}>
            <div>
              <h2>Inventory Ageing Distribution</h2>
              <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)', marginTop: '2px' }}>
                Days on floor since Volkswagen billing date
              </div>
            </div>
            <Layers size={18} style={{ color: 'var(--ink-muted)' }} />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: '8px' }}>
            {bucketCards.map(b => (
              <div key={b.key} style={{
                background: 'var(--surface-sub)',
                border: '1px solid var(--grid)',
                borderRadius: 'var(--radius-sm)',
                padding: '11px 10px 12px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 7 }}>
                  <span style={{ width: 7, height: 7, flex: 'none', background: b.fill }} />
                  <span style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-muted)', letterSpacing: '0.04em' }}>
                    {b.label}
                  </span>
                </div>
                <div style={{
                  fontSize: '22px', fontWeight: 600, letterSpacing: '-0.018em',
                  lineHeight: 1, color: 'var(--ink)',
                  fontVariantNumeric: 'lining-nums tabular-nums',
                }}>
                  {n0(b.count)}
                </div>
                <div style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-muted)', marginTop: '5px' }}>
                  {b.sub}
                </div>
              </div>
            ))}
          </div>

          {modelAgeingList.length > 0 && (
            <div style={{ marginTop: '16px' }}>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Model</th>
                      {BANDS.map(b => (
                        <th key={b.key} className="num" title={b.sub}>{b.key}</th>
                      ))}
                      <th className="num">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {modelAgeingList.map(item => (
                      <tr key={item.model}>
                        <td style={{ fontWeight: 600 }}>{item.model}</td>
                        {BANDS.map(b => (
                          <td key={b.key} className="num"
                              style={{ color: item[b.key] ? 'var(--ink)' : 'var(--ink-muted)' }}>
                            {item[b.key] || '–'}
                          </td>
                        ))}
                        <td className="num" style={{ fontWeight: 600 }}>{item.total}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        {/* Live Cloud Activity Feed */}
        <div style={{ flex: 1, borderTop: '1px solid var(--grid)', paddingTop: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '10px' }}>
            <History size={15} style={{ color: 'var(--s1)' }} />
            <h3 style={{ margin: 0, fontSize: 'var(--fs-body)' }}>Recently Recorded</h3>
          </div>

          <div style={{ maxHeight: '150px', overflowY: 'auto', fontSize: 'var(--fs-small)', display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {activity.length > 0 ? (
              activity.slice(0, 5).map((act, i) => (
                <div key={i} style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  padding: '6px 10px',
                  background: 'var(--surface-sub)',
                  borderRadius: '6px',
                }}>
                  <span>
                    <b>+{act.kind || 'entry'}</b>: {act.who || 'Record'}
                  </span>
                  <span style={{ color: 'var(--ink-muted)' }}>
                    {dt(act.loaded_at)} {act.entered_by ? `· by ${act.entered_by}` : ''}
                  </span>
                </div>
              ))
            ) : (
              <div style={{ color: 'var(--ink-muted)' }}>
                Bookings, leads and test drives appear here as they are recorded.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
