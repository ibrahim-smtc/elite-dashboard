/**
 * The loading sheet.
 *
 * The payload is sixteen calls against a database a round trip away and takes
 * the better part of five seconds, so this is not a moment to fill with a
 * spinner. Two things make the wait shorter than it is:
 *
 *  - The skeleton is the real layout - rail, hero, tiles - at the real sizes,
 *    so the page does not jump when the data lands; it fills in.
 *  - The progress is real. Every block reports when its own call returns, and
 *    the count is the count.
 *
 * The motif is the dye itself: aizome cloth is dipped again and again, each dip
 * deepening the blue, so the blocks soak rather than shimmer.
 */

import React from 'react';

function Block({ h = 14, w = '100%', delay = 0, soaked = false, radius = 2 }) {
  return (
    <div
      className={soaked ? 'skel skel-soaked' : 'skel'}
      style={{ height: h, width: w, borderRadius: radius, animationDelay: `${delay}ms` }}
    />
  );
}

export default function Loading({ done = 0, total = 16 }) {
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  // A block is "soaked" once the data behind roughly that part of the page has
  // arrived, so the sheet fills from the top the way a dipped length does.
  const soakedThrough = Math.round((done / Math.max(total, 1)) * 10);

  return (
    <div className="shell" aria-busy="true" aria-live="polite">
      <aside className="rail">
        <div className="rail-identity">
          <span className="rail-seal">VW</span>
          <div style={{ flex: 1 }}>
            <Block h={11} w="82%" />
            <div style={{ height: 6 }} />
            <Block h={8} w="60%" delay={90} />
          </div>
        </div>

        <div className="rail-block">
          <Block h={30} delay={140} />
          <Block h={9} w="70%" delay={180} />
        </div>

        <div className="rail-block" style={{ gap: 11 }}>
          {[0, 1, 2, 3].map(i => (
            <Block key={i} h={10} w={`${72 - i * 7}%`} delay={220 + i * 70} />
          ))}
        </div>

        <div className="rail-foot">
          <Block h={10} w="54%" delay={520} />
        </div>
      </aside>

      <main className="sheet">
        {/* The count is the honest part: sixteen calls, and this many back. */}
        <div style={{
          display: 'flex', alignItems: 'baseline', gap: 14,
          marginBottom: 22, color: 'var(--ink-muted)', fontSize: 'var(--fs-small)',
        }}>
          <span style={{ letterSpacing: '0.16em', textTransform: 'uppercase', fontSize: 'var(--fs-micro)' }}>
            Drawing the sheet
          </span>
          <span style={{ fontVariantNumeric: 'tabular-nums' }}>{done} of {total}</span>
          <span style={{
            flex: 1, height: 1, position: 'relative',
            background: 'var(--grid)', transform: 'translateY(-3px)',
          }}>
            <span style={{
              position: 'absolute', inset: '0 auto 0 0', width: `${pct}%`,
              background: 'var(--shu)', transition: 'width var(--t-slow) var(--ease-out)',
            }} />
          </span>
        </div>

        <div className="panel" style={{ marginBottom: 18 }}>
          <div style={{ display: 'flex', gap: 28, alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ minWidth: 150 }}>
              <Block h={9} w="70%" />
              <div style={{ height: 12 }} />
              <Block h={44} w="55%" delay={80} soaked={soakedThrough >= 1} radius={3} />
            </div>
            <div style={{ flex: '1 1 320px' }}>
              <Block h={9} w="34%" delay={120} />
              <div style={{ height: 12 }} />
              <Block h={10} delay={160} soaked={soakedThrough >= 2} radius={3} />
            </div>
          </div>
        </div>

        <div className="grid-tiles">
          {Array.from({ length: 8 }, (_, i) => (
            <div key={i} className="kpi-tile">
              <Block h={9} w="64%" delay={i * 60} />
              <div style={{ height: 14 }} />
              <Block h={26} w="45%" delay={i * 60 + 40} soaked={soakedThrough >= i + 2} radius={3} />
              <div style={{ height: 14 }} />
              <Block h={5} delay={i * 60 + 80} radius={3} />
              <div style={{ height: 10 }} />
              <Block h={8} w="80%" delay={i * 60 + 110} />
            </div>
          ))}
        </div>

        <div className="grid-2" style={{ marginTop: 34 }}>
          {[0, 1].map(i => (
            <div key={i} className="panel">
              <Block h={11} w="38%" delay={i * 120} />
              <div style={{ height: 8 }} />
              <Block h={8} w="56%" delay={i * 120 + 50} />
              <div style={{ height: 24 }} />
              <Block h={172} delay={i * 120 + 90} radius={3} />
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
