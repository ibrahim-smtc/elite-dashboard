/**
 * The transient line that says what just happened.
 *
 * Toasts arrive from App as a plain array and are dropped from it after 4.5s.
 * That is all the state a toast needs, but it gives an element no chance to
 * leave: React unmounts it the instant it falls out of the array, so a toast
 * that eased in simply ceased to exist. It fires on every refresh, upload and
 * save, which made it the most-seen transient on the sheet and the only one
 * whose exit was a hard cut.
 *
 * So this component holds on to a toast for one animation after it has gone
 * from the array, renders it with `.leaving`, and only then lets it go. The
 * departing toast keeps its space in the stack while it fades, so the ones
 * below it do not jump up to fill a gap that is still visibly occupied.
 *
 * Nothing above this component changed; the lifetime is entirely local.
 */

import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';

/* Must outlast --t-slow (320ms), or the toast is unmounted mid-fade. */
const EXIT_MS = 340;

export default function ToastContainer({ toasts = [] }) {
  const [leaving, setLeaving] = useState([]);
  const previous = useRef(toasts);
  const timers = useRef([]);

  /* Layout, not plain effect. A plain effect runs after the browser has
     painted, so the frame where React drops the toast from the array is
     painted with the toast already gone - it blinks out, comes back, and
     only then fades. Measured at ~31ms of absence. A layout effect re-adds
     it in the same commit, before anything reaches the screen. */
  useLayoutEffect(() => {
    const present = new Set(toasts.map(t => t.id));
    const gone = previous.current.filter(t => !present.has(t.id));
    previous.current = toasts;
    if (!gone.length) return;

    setLeaving(current => [...current, ...gone]);
    gone.forEach(t => {
      const timer = setTimeout(
        () => setLeaving(current => current.filter(x => x.id !== t.id)),
        EXIT_MS,
      );
      timers.current.push(timer);
    });
  }, [toasts]);

  // Unmounting mid-exit would otherwise leave timers setting state on nothing.
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  /* Departing first: App appends new toasts and expires the oldest, so the one
     on its way out is always above the ones that remain. */
  const shown = [
    ...leaving.map(t => ({ ...t, leaving: true })),
    ...toasts,
  ];
  if (!shown.length) return null;

  return (
    <div className="toast-box">
      {shown.map(t => (
        <div
          key={t.id}
          className={`toast ${t.bad ? 'bad' : ''} ${t.leaving ? 'leaving' : ''}`}
        >
          <span className="toast-dot" />
          <span>{t.message}</span>
        </div>
      ))}
    </div>
  );
}
