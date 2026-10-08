/**
 * The one figure the sheet exists for.
 *
 * It reads top to bottom the way the number is actually used: what it is, what
 * it says, what it means, and how far through the month that puts us.
 *
 * It knows which kind of month it is looking at. It used to say "Bookings this
 * month" while showing August on the twenty-ninth of September - a month four
 * weeks over - and in a running month it could not say whether fifty per cent
 * was good, because fifty per cent on the fifteenth is on track and on the
 * twenty-eighth is a crisis. So the label names the month, and a badge beside
 * it says where that month stands: closed, or which day it has reached and
 * how many bookings that day should have brought.
 *
 * The figures speak plainly. An earlier pass had them say "42 short" and "12
 * behind", which is the language of a scolding rather than a report; a
 * dashboard states quantities and lets the reader judge. So they are always
 * Achieved, To goal and Advance collected, in ink - and the judgement lives in
 * one place only, the colour of the bar, where it can be read at a glance
 * without a word being raised.
 *
 * In a running month the bar carries a tick at the position bookings should
 * have reached by now, if the target were spread evenly across the days. The
 * gap between the end of the bar and the tick is the pace, readable without a
 * number. "By now" means the last day with anything in the record, not today:
 * the workbook is filled in after the fact, and a day nobody has entered yet is
 * not a day of lost bookings. The first two days are too few to judge, so they
 * get no tick and no alarm.
 */

import React from 'react';
import { n0, pct, money } from '../api/client';
import HeroField from './HeroField';
import Figure from './Figure';

const DAY = 86400000;

/* Dates arrive as YYYY-MM-DD. They are periods, not instants, so they are read
   as whole UTC days - a timezone must never move the first of the month back
   into the last day of the one before. */
const dayOf = s => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s || ''));
  return m ? Date.UTC(+m[1], +m[2] - 1, +m[3]) / DAY : null;
};
const today = () => {
  const n = new Date();
  return Date.UTC(n.getFullYear(), n.getMonth(), n.getDate()) / DAY;
};
const dateLabel = (day, opts) =>
  new Date(day * DAY).toLocaleDateString('en-IN', { ...opts, timeZone: 'UTC' });

/* The last day anything was recorded, bookings or enquiries. Enquiries arrive
   almost every day, so their last date is the best evidence of how far the
   record has been filled in - a quiet day for bookings alone would pull it
   back. */
function lastRecorded(trends = {}) {
  let last = null;
  for (const series of [trends.bookings, trends.enquiries]) {
    for (const p of series || []) {
      if ((Number(p.n) || 0) <= 0) continue;
      const d = dayOf(p.d);
      if (d != null && (last == null || d > last)) last = d;
    }
  }
  return last;
}

/* Where in its own month the active period stands. */
export function monthState(period = {}, trends = {}, now = today()) {
  const start = dayOf(period.period_start);
  const end = dayOf(period.period_end);
  if (start == null || end == null || end < start) return null;
  const recorded = lastRecorded(trends);
  const through = recorded == null ? null : Math.min(Math.max(recorded, start), end);
  return {
    total: end - start + 1,
    closed: now > end,
    days: through == null ? 0 : through - start + 1,
    name: dateLabel(end, { month: 'long', year: 'numeric' }),
    through: through == null ? null : dateLabel(through, { day: 'numeric', month: 'short' }),
  };
}

/* Fewer days than this and a pace is mostly noise: two bookings on day one is
   either far ahead or far behind depending on nothing at all. */
const MIN_PACE_DAYS = 3;
/* Within a tenth of the mark is near, not failing. */
const NEAR = 0.9;

export default function HeroMetric({ kpi = {}, period = {}, trends = {} }) {
  const bookings = Number(kpi.bookings || 0);
  const target = Number(kpi.booking_target || 0);
  const ratio = target > 0 ? (bookings / target) * 100 : 0;
  const toGoal = Math.max(0, target - bookings);
  const collected = kpi.booking_amount_collected;

  const month = monthState(period, trends);
  const closed = !!month?.closed;
  const pacing = !!month && !closed && target > 0 && month.days >= MIN_PACE_DAYS;
  const expected = pacing ? (target * month.days) / month.total : null;

  /* The one judgement on the section, and the bar is the only thing that
     shows it. A closed month is judged on its result, a running one against
     its pace, and one too young to judge is not judged at all. */
  const mark = closed ? target : expected;
  const standing = !(closed || pacing) || !(mark > 0) ? 'neutral'
    : bookings >= mark - (pacing ? 0.5 : 0) ? 'good'
    : bookings >= NEAR * mark ? 'near'
    : 'bad';
  const BAR = { good: 'var(--good)', near: 'var(--s1)', bad: 'var(--serious)', neutral: 'var(--s1)' };

  const badge = !month ? null
    : closed ? { text: 'Month closed', live: false }
    : pacing ? { text: `Day ${month.days} of ${month.total} · ${n0(Math.round(expected))} expected`, live: true }
    : month.days > 0 ? { text: `Day ${month.days} of ${month.total}`, live: true }
    : null;
  const badgeHint = pacing && month.through
    ? `Expected is measured to ${month.through}, the last day with figures in the record, not to today.`
    : undefined;

  // These all move when a booking lands, so they count with the figure rather
  // than snapping beside a number that is visibly counting.
  const stats = [
    ...(target > 0 ? [
      { label: 'Achieved', node: <Figure value={ratio} format={pct} decimals={1} /> },
      toGoal > 0
        ? { label: 'To goal', node: <Figure value={toGoal} format={n0} /> }
        : { label: 'To goal', node: 'Target met', tone: 'var(--good-text)' },
    ] : []),
    ...(collected != null
      ? [{ label: 'Advance collected', node: <Figure value={Number(collected)} format={money} /> }]
      : []),
  ];

  const fill = Math.min(100, Math.max(1.5, ratio));
  /* The percentage sits where the bar ends, so the bar and its value are read
     as one thing. Near either end it would run into the 0 or the target - on a
     phone the target label is a sixth of the bar - so there it steps aside;
     Achieved above already carries the exact figure. */
  const showPct = fill >= 8 && fill <= 78;

  return (
    <div className="hero-band">
      <HeroField />
      <div className="hero-head">
        <div className="hero-label">
          {month ? `Bookings · ${month.name}` : 'Bookings this month'}
        </div>
        {badge && (
          <div className="hero-badge" data-live={badge.live || undefined} title={badgeHint}>
            <span className="hero-badge-dot" aria-hidden="true" />
            {badge.text}
          </div>
        )}
      </div>

      <div className="hero-row">
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px' }}>
          <Figure className="hero-figure" value={bookings} format={n0} />
          {target > 0 && <span className="hero-of">/ {n0(target)}</span>}
        </div>

        <div className="hero-stats">
          {stats.map(s => (
            <div key={s.label} className="hero-stat">
              <div className="hero-stat-label">{s.label}</div>
              <div className="hero-stat-value" style={{ color: s.tone || 'var(--ink)' }}>
                {s.node}
              </div>
            </div>
          ))}
        </div>
      </div>

      {target > 0 && (
        <>
          <div className="hero-meter" role="img"
               aria-label={`${n0(bookings)} of ${n0(target)} bookings, ${Math.round(ratio)}% of target`}>
            <div className="hero-meter-fill"
                 style={{ width: `${fill}%`, background: BAR[standing] }} />
            {pacing && (
              <div className="hero-meter-tick"
                   style={{ left: `${(100 * month.days) / month.total}%` }}
                   title={`Expected by ${month.through}: ${n0(Math.round(expected))}`} />
            )}
          </div>
          <div className="hero-scale">
            <span>0</span>
            {showPct && (
              <span className="hero-scale-pct" style={{ left: `${fill}%` }}>
                {Math.round(ratio)}%
              </span>
            )}
            <span>Target {n0(target)}</span>
          </div>
        </>
      )}
    </div>
  );
}
