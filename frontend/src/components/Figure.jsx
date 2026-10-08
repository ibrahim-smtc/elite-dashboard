/**
 * A figure that travels to its new value instead of jumping to it.
 *
 * The sheet is live. A lead arrives over SSE and 267 becomes 268 with nothing
 * to mark the moment: anyone not staring at that exact tile sees a number that
 * is merely different from the one they remember, which is indistinguishable
 * from having misread it the first time. Counting the last stretch turns a
 * changed number into a change you watched happen.
 *
 * Three rules keep it from becoming a gimmick.
 *
 *   It never runs on first paint. Nothing has changed when a page loads, and a
 *   dashboard that spins every figure up from zero on arrival makes you wait to
 *   read it. The count reports an event; it is not an entrance.
 *
 *   It never runs under prefers-reduced-motion.
 *
 *   It snaps when the figure has not been revised but replaced. Switching the
 *   reporting month takes enquiries from 267 to 4,208, and counting through
 *   four thousand numbers is a progress bar nobody asked for. "Revised" is
 *   judged both ways, because the tiles are not on one scale: a count moves by
 *   ones, and booking revenue moves by tens of thousands of rupees and is still
 *   the same figure nudged.
 */

import React, { useEffect, useRef, useState } from 'react';
import { n0 } from '../api/client';

const DURATION = 420;

/* A small step on a count, or a small step in proportion. Either one means the
   figure was revised; failing both means it was replaced. */
const SMALL_ABSOLUTE = 250;
const SMALL_RELATIVE = 0.2;

function isRevision(from, to) {
  const delta = Math.abs(to - from);
  if (delta <= SMALL_ABSOLUTE) return true;
  const scale = Math.max(Math.abs(from), Math.abs(to), 1);
  return delta / scale <= SMALL_RELATIVE;
}

export function useTweenedNumber(target) {
  const value = Number.isFinite(Number(target)) ? Number(target) : 0;
  const [shown, setShown] = useState(value);
  const from = useRef(value);
  const first = useRef(true);
  const frame = useRef(0);

  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

    if (first.current || reduced || !isRevision(from.current, value)) {
      first.current = false;
      from.current = value;
      setShown(value);
      return undefined;
    }

    const origin = from.current;
    const delta = value - origin;
    if (delta === 0) return undefined;

    const start = performance.now();
    const step = now => {
      const p = Math.min(1, (now - start) / DURATION);
      // Decelerating, matching --ease-out on everything else, so the figure
      // arrives rather than coasting to a halt.
      setShown(origin + delta * (1 - Math.pow(1 - p, 3)));
      if (p < 1) {
        frame.current = requestAnimationFrame(step);
      } else {
        from.current = value;
        frame.current = 0;
      }
    };
    frame.current = requestAnimationFrame(step);

    return () => {
      if (frame.current) cancelAnimationFrame(frame.current);
      frame.current = 0;
      // Settle on the target, not on wherever the tween was cut short, so a
      // fast second update counts from the real figure and never from a frame.
      from.current = value;
    };
  }, [value]);

  return shown;
}

/**
 * `format` receives a number and returns the string to show, so a figure keeps
 * whatever formatting it already had - lakhs, crores, Indian digit grouping.
 * `decimals` is what the formatter expects to be given, not what it prints:
 * n0 and money want whole units, pct wants the one decimal it renders.
 */
export default function Figure({ value, format = n0, decimals = 0, className, style }) {
  const live = useTweenedNumber(value);
  const q = Math.pow(10, decimals);
  const quantised = Math.round(live * q) / q;

  return (
    <span
      className={className}
      style={style}
      /* The figure changes many times a second mid-count. Without this a
         screen reader would announce every frame, and the tween - which exists
         purely to catch the eye - would turn into noise for someone who cannot
         see it. The settled value is read from the surrounding label. */
      aria-hidden={false}
      aria-live="off"
    >
      {format(quantised)}
    </span>
  );
}
