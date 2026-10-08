/**
 * Test drives - the showroom's test drives, and nothing else.
 *
 * Every drive comes from one table, dsr.test_drive_booking: no car bookings,
 * no general enquiries. Two kinds of row matter here.
 *
 *   Enquiries  test drives asked for and still waiting for a time. The
 *              database files one from every test-drive enquiry the AI agent
 *              or the website saves; the team gives it a slot.
 *   Bookings   test drives with their slot - booked by the AI agent on the
 *              call, by the sales desk, or for a walk-in - and how each one
 *              went: attended, no-show, cancelled.
 *
 * Sample drives (made up, for showing the section) are drawn dashed and can
 * be hidden; they never hold a slot a real customer could take. See
 * app/test_drives.py and db/test_drives.sql.
 */

import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Search } from 'lucide-react';
import { api, sendJson } from '../api/client';
import useClosing from './useClosing';

const BASE = '/api/test-drive-board';
const DAY = 86400000;

/* Dates are days, not instants: build and read them as UTC so no timezone
   can slide a drive onto the day before. */
const isoAdd = (iso, n) => new Date(Date.parse(`${iso}T00:00:00Z`) + n * DAY).toISOString().slice(0, 10);
const fmt = (iso, opts) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-IN', { timeZone: 'UTC', ...opts });
const dayLong = iso => fmt(iso, { weekday: 'short', day: 'numeric', month: 'short' });
const shortDate = iso => fmt(iso, { day: 'numeric', month: 'short' });
const monthOf = iso => `${iso.slice(0, 7)}-01`;
const addMonths = (m, n) => {
  const d = new Date(`${m}T00:00:00Z`);
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + n, 1)).toISOString().slice(0, 10);
};
const daysIn = m => {
  const d = new Date(`${m}T00:00:00Z`);
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).getUTCDate();
};
const monthName = m => fmt(m, { month: 'long', year: 'numeric' });
/* Weeks run Monday to Sunday. A month is loaded padded out to whole weeks,
   so the week view never shows a day it has not loaded. */
const weekStart = iso => isoAdd(iso, -((new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7));
const rangeOf = m => {
  const start = weekStart(m);
  const end = isoAdd(weekStart(isoAdd(m, daysIn(m) - 1)), 7);          // exclusive
  return { start, days: Math.round((Date.parse(end) - Date.parse(start)) / DAY) };
};
// The showroom's clock, whatever the viewer's: today's past slots cannot be booked.
const nowIST = () => new Date().toLocaleTimeString('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit' });
const todayIST = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });   // YYYY-MM-DD

const WEEKDAYS = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'];
/* The agent says "for Friday", not a date. Turn the first weekday it names
   into the next such day on or after today; "tomorrow" into tomorrow. */
function dateFromHint(hint, today) {
  if (!hint) return null;
  const h = hint.toLowerCase();
  if (h === 'today') return today;
  if (h === 'tomorrow') return isoAdd(today, 1);
  const want = WEEKDAYS.indexOf(h);
  if (want < 0) return null;
  const now = new Date(`${today}T00:00:00Z`).getUTCDay();
  return isoAdd(today, (want - now + 7) % 7);
}

/* A drive's status, in the order a drive's life runs. Enquiries are drives
   still owed a time. */
const STATUS = {
  requested: { label: 'Enquiry', many: 'enquiries', one: 'enquiry' },
  booked:    { label: 'Booked', many: 'booked', one: 'booked' },
  attended:  { label: 'Attended', many: 'attended', one: 'attended' },
  no_show:   { label: 'No-show', many: 'no-shows', one: 'no-show' },
  cancelled: { label: 'Cancelled', many: 'cancelled', one: 'cancelled' },
};
const SHOWN = ['booked', 'attended', 'no_show', 'cancelled', 'requested'];   // the month bar's switches
const SLOTTED = ['booked', 'attended', 'no_show'];                          // drives that hold their slot
const ENQUIRY_ROWS = 8;
// What an enquiry still waits for, or, once its day has passed with no
// booking, that the customer did not come. One with no day yet sits on the
// day it came in.
const askLabel = x => (x.fromCall ? `From a call${x.when_hint ? ` · asked for ${x.when_hint}` : ''}`
  : x.status === 'no_show' ? `No-show${x.asked_time ? ` · asked for ${x.asked_time}` : ''}`
  : !x.date ? 'Day to confirm' : x.asked_time ? `Asked for ${x.asked_time}` : 'Time to confirm');

/* ---------------------------------------------------------------- dialogs */

function Dialog({ open, title, onClose, children, wide }) {
  const { render, leaving } = useClosing(open);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = e => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!render) return null;
  return (
    <div className={`drawer-scrim ${leaving ? 'is-leaving' : ''}`}
         style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
         onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="xp-panel tdb-dialog" role="dialog" aria-modal="true" aria-label={title}
           style={{ maxWidth: wide ? 560 : 480 }}>
        <div className="tdb-dialog-head">
          <h2>{title}</h2>
          <button type="button" className="rail-quiet" onClick={onClose} aria-label="Close">Close</button>
        </div>
        {children}
      </div>
    </div>
  );
}

function BookingForm({ setup, draft, onCancel, onSaved }) {
  const [form, setForm] = useState(draft);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setForm(draft); setError(null); }, [draft]);

  // The day's own drives, fetched for the day chosen, so a slot taken on any
  // day - not only the month on screen - is never offered as free.
  const [dayDrives, setDayDrives] = useState([]);
  useEffect(() => {
    let dead = false;
    if (!form.date) return undefined;
    api(`${BASE}?start=${form.date}&days=1&samples=false`)
      .then(r => { if (!dead) setDayDrives(r.bookings || []); })
      .catch(() => { if (!dead) setDayDrives([]); });
    return () => { dead = true; };
  }, [form.date]);

  const now = nowIST();
  const last = setup.slots[setup.slots.length - 1];
  const taken = useMemo(() => new Set(dayDrives
    .filter(b => b.car_id === form.car_id && b.start && SLOTTED.includes(b.status) && b.id !== form.request_id)
    .map(b => b.start)), [dayDrives, form.car_id, form.request_id]);
  const free = !form.date || form.date < setup.today ? []
    : setup.slots.filter(s => !taken.has(s) && !(form.date === setup.today && s <= now));
  const carName = setup.cars.find(c => c.id === form.car_id)?.name || 'car';
  // When the day offers no time, say why, and offer the next day.
  const why = !form.date || free.length ? null
    : form.date < setup.today ? 'That day has passed.'
    : form.date === setup.today && now >= last ? `Today’s slots have all gone; the last was ${last}.`
    : `The ${carName} is booked in every slot ${form.date === setup.today ? 'left today' : 'that day'}.`;
  const nextDay = form.date >= setup.today ? isoAdd(form.date, 1) : (now < last ? setup.today : isoAdd(setup.today, 1));
  const set = (k, v) => { setError(null); setForm(f => ({ ...f, [k]: v })); };

  const save = async e => {
    e.preventDefault();
    // Say what is missing, and go to it, rather than leave a button that does nothing.
    const missing = !form.date ? ['date', 'Choose the day of the drive.']
      : why ? ['date', `${why} Choose another day.`]
      : !free.includes(form.start) ? ['start', 'Choose a time for the drive.']
      : !form.customer.trim() ? ['customer', 'Enter the customer’s name.']
      : null;
    if (missing) {
      setError(missing[1]);
      e.currentTarget.elements.namedItem(missing[0])?.focus();
      return;
    }
    setBusy(true); setError(null);
    try {
      const row = await sendJson('POST', BASE, {
        car_id: form.car_id, date: form.date, start: form.start,
        // PII POLICY (2026-10-08): the customer's phone number and home
        // address are not stored, so the form does not ask for them and none
        // is sent (the server would only replace them with [REDACTED]).
        customer: form.customer.trim(),
        consultant: form.consultant, location: form.location,
        source: form.source, call_id: form.call_id || null,
        request_id: form.request_id || null,
      });
      onSaved(row);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="tdb-form" onSubmit={save} noValidate>
      {form.fromCall && (
        <div className="tdb-fromcall">
          <b>From a call on {fmt(form.fromCall.called_at.slice(0, 10), { day: 'numeric', month: 'short' })}</b>
          {form.fromCall.when_hint ? <> &middot; the agent noted &ldquo;{form.fromCall.when_hint}&rdquo;</> : null}
          <div>{form.fromCall.summary}</div>
        </div>
      )}
      {form.fromMissed && (
        <div className="tdb-fromcall">
          <b>Booking {form.fromMissed.customer} again</b>
          <div>
            {form.fromMissed.start
              ? `Missed the drive on ${dayLong(form.fromMissed.date)} at ${form.fromMissed.start}.`
              : `Asked for ${dayLong(form.fromMissed.date)}, and the day passed with no booking.`}
            {' '}The no-show stays on record.
          </div>
        </div>
      )}
      {form.fromRequest && (
        <div className="tdb-fromcall">
          <b>Enquiry{form.fromRequest.source === 'AI agent' ? ' taken by the AI agent' : ''}
            {' '}on {shortDate(form.fromRequest.enquired_on)}</b>
          {(form.fromRequest.date || form.fromRequest.asked_time) && (
            <> &middot; asked for {[form.fromRequest.date && dayLong(form.fromRequest.date), form.fromRequest.asked_time]
              .filter(Boolean).join(' at ')}</>
          )}
          {form.fromRequest.note && <div>{form.fromRequest.note}</div>}
        </div>
      )}
      <div className="tdb-grid2">
        <label>Car
          <select value={form.car_id} onChange={e => set('car_id', e.target.value)}>
            {setup.cars.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label>Date
          <input type="date" name="date" value={form.date} min={setup.today}
                 onChange={e => set('date', e.target.value)} required />
        </label>
        <label>Time
          <select name="start" value={free.includes(form.start) ? form.start : ''}
                  onChange={e => set('start', e.target.value)} required>
            {!free.includes(form.start) && <option value="" disabled>Choose a free slot</option>}
            {free.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label>Sales executive
          <select value={form.consultant} onChange={e => set('consultant', e.target.value)}>
            <option value="">Assign later</option>
            {setup.consultants.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label>Customer
          <input name="customer" value={form.customer} onChange={e => set('customer', e.target.value)}
                 required maxLength={80} placeholder="Full name" />
        </label>
      </div>
      {why && (
        <div className="tdb-nofree" role="status">
          <span>{why}</span>
          <button type="button" className="rail-quiet" onClick={() => set('date', nextDay)}>
            Try {dayLong(nextDay)}
          </button>
        </div>
      )}
      <fieldset className="tdb-choice">
        <legend>Where</legend>
        {['Showroom', 'Home'].map(v => (
          <label key={v}><input type="radio" name="loc" checked={form.location === v}
                                onChange={() => set('location', v)} /> {v === 'Home' ? 'At home' : 'Showroom'}</label>
        ))}
        {/* PII POLICY (2026-10-08): the address field that appeared here for a
            drive at the customer's home was removed - addresses are not stored. */}
      </fieldset>
      <fieldset className="tdb-choice">
        <legend>Booked by</legend>
        {['Staff', 'Walk-in', 'AI agent'].map(v => (
          <label key={v}><input type="radio" name="src" checked={form.source === v}
                                onChange={() => set('source', v)} /> {v}</label>
        ))}
      </fieldset>
      {error && <div className="tdb-error" role="alert">{error}</div>}
      <div className="tdb-actions">
        <button type="button" className="rail-quiet" onClick={onCancel}>Cancel</button>
        <button type="submit" className="primary" disabled={busy}>
          {busy ? 'Booking…' : 'Book test drive'}
        </button>
      </div>
    </form>
  );
}

/* A test drive's details, with everything the agent noted. An enquiry is
   scheduled from here; a booking is marked attended, no-show or cancelled;
   a no-show is booked again. */
function BookingDetail({ booking, car, onChanged, onSchedule, onBookAgain }) {
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const enquiry = booking.status === 'requested';
  // An enquiry whose day passed with no booking: a no-show that never had a slot.
  const missed = booking.status === 'no_show' && !booking.start;
  // Whether a customer came or not is known only once the drive's time has come.
  const due = !enquiry && !!booking.date
    && (booking.date < todayIST() || (booking.date === todayIST() && booking.start <= nowIST()));
  const change = async status => {
    setBusy(status); setError(null);
    try {
      onChanged(await sendJson('PATCH', `${BASE}/${booking.id}`, { status }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  };
  const when = enquiry || missed
    ? `${booking.date ? dayLong(booking.date) : 'Day to confirm'} · ${booking.asked_time ? `asked for ${booking.asked_time}` : missed ? 'no time fixed' : 'time to confirm'}`
    : `${dayLong(booking.date)} · ${booking.start}`;
  const from = booking.call_id ? ' · from a call' : booking.from_enquiry ? ' · from an enquiry' : '';
  return (
    <div className="tdb-detail">
      {booking.sample && <div className="tdb-samplenote">A sample drive, made up for showing the section.</div>}
      {missed && <div className="tdb-missednote">Marked a no-show automatically: the day asked for passed with no booking.</div>}
      <dl>
        <dt>When</dt><dd>{when}</dd>
        {(enquiry || missed) && <><dt>Came in</dt><dd>{dayLong(booking.enquired_on)}</dd></>}
        <dt>Car</dt><dd>{car ? car.name : 'Model not recorded'}</dd>
        <dt>Customer</dt><dd>{booking.customer}{booking.phone ? ` · ${booking.phone}` : ''}</dd>
        <dt>Where</dt><dd>{booking.location === 'Home' ? `At home${booking.address ? `: ${booking.address}` : ''}` : 'Showroom'}</dd>
        <dt>Executive</dt><dd>{booking.consultant || 'Not assigned'}</dd>
        <dt>Booked by</dt><dd>{booking.source}{from}</dd>
        {booking.note && (
          <><dt>{booking.source === 'AI agent' ? 'Agent’s note' : 'Note'}</dt><dd className="tdb-notetext">{booking.note}</dd></>
        )}
        <dt>Status</dt><dd><span className="tdb-pill" data-status={booking.status}>{STATUS[booking.status]?.label}</span></dd>
      </dl>
      {error && <div className="tdb-error" role="alert">{error}</div>}
      <div className="tdb-actions">
        {enquiry ? (
          <>
            <button type="button" className="rail-quiet" disabled={!!busy} onClick={() => change('cancelled')}>
              {busy === 'cancelled' ? 'Cancelling…' : 'Cancel enquiry'}
            </button>
            <button type="button" className="primary" onClick={() => onSchedule(booking)}>Schedule</button>
          </>
        ) : (
          <>
            {booking.status !== 'cancelled' && (
              <button type="button" className="rail-quiet" disabled={!!busy} onClick={() => change('cancelled')}>
                {busy === 'cancelled' ? 'Cancelling…' : missed ? 'Cancel enquiry' : 'Cancel drive'}
              </button>
            )}
            {/* A missed enquiry never had a slot to have attended, or to go back to. */}
            {due && !missed && booking.status !== 'no_show' && booking.status !== 'cancelled' && (
              <button type="button" disabled={!!busy} onClick={() => change('no_show')}>No-show</button>
            )}
            {due && !missed && booking.status !== 'attended' && booking.status !== 'cancelled' && (
              <button type="button" className="primary" disabled={!!busy} onClick={() => change('attended')}>
                Mark attended
              </button>
            )}
            {!missed && booking.status !== 'booked' && (
              <button type="button" disabled={!!busy} onClick={() => change('booked')}>Back to booked</button>
            )}
            {booking.status === 'no_show' && (
              <button type="button" className={missed ? 'primary' : ''} disabled={!!busy} onClick={() => onBookAgain(booking)}>
                Book again
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- headline */

/* Four figures a manager reads first: today, the week ahead, the enquiries
   waiting for a time, and how this month's drives turned out. */
function Headline({ stats, carName, onEnquiries }) {
  if (!stats) return <div className="tdb-kpis is-loading" aria-busy="true" />;
  const done = stats.attended + stats.no_shows;
  const rate = done ? Math.round((stats.attended / done) * 100) : null;
  const next = stats.next;
  return (
    <div className="tdb-kpis">
      <div className="tdb-kpi">
        <span className="tdb-kpi-label">Today</span>
        <b className="tdb-kpi-value">{stats.today}</b>
        <span className="tdb-kpi-sub">
          {stats.today === 1 ? 'test drive' : 'test drives'}
          {stats.today_left ? ` · ${stats.today_left} still to come` : ''}
        </span>
      </div>
      <div className="tdb-kpi">
        <span className="tdb-kpi-label">Next 7 days</span>
        <b className="tdb-kpi-value">{stats.week}</b>
        <span className="tdb-kpi-sub">
          {next ? `Next: ${dayLong(next.date)} ${next.start} · ${carName(next.car_id) || 'car not set'}` : 'Nothing booked yet'}
        </span>
      </div>
      <button type="button" className={`tdb-kpi tdb-kpi-btn ${stats.waiting ? 'is-warn' : ''}`} onClick={onEnquiries}>
        <span className="tdb-kpi-label">Enquiries waiting</span>
        <b className="tdb-kpi-value">{stats.waiting}</b>
        <span className="tdb-kpi-sub">{stats.waiting ? 'Need a time · open the list' : 'Every enquiry has its slot'}</span>
      </button>
      <div className={`tdb-kpi ${stats.unmarked ? 'is-warn' : ''}`}>
        <span className="tdb-kpi-label">This month</span>
        <b className="tdb-kpi-value">{rate === null ? '–' : `${rate}%`}</b>
        <span className="tdb-kpi-sub">
          {done ? `attended · ${stats.attended} came, ${stats.no_shows} missed` : 'No drives finished yet'}
          {stats.unmarked ? ` · ${stats.unmarked} past drive${stats.unmarked === 1 ? '' : 's'} to mark` : ''}
        </span>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- search */

/* Find a customer's test drives in any month; picking one opens its day with
   the drive on top. */
function SearchBox({ setup, samples, onPick }) {
  const [q, setQ] = useState('');
  const [results, setResults] = useState(null);       // null: nothing asked yet
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef(null);

  useEffect(() => {
    const t = q.trim();
    if (t.length < 2) { setResults(null); setOpen(false); return undefined; }
    let dead = false;
    const wait = setTimeout(() => {
      api(`${BASE}/search?q=${encodeURIComponent(t)}&samples=${samples}`)
        .then(r => { if (!dead) { setResults(r.results || []); setActive(0); setOpen(true); } })
        .catch(() => { if (!dead) { setResults([]); setOpen(true); } });
    }, 220);
    return () => { dead = true; clearTimeout(wait); };
  }, [q, samples]);

  useEffect(() => {
    if (!open) return undefined;
    const away = e => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, [open]);

  const carName = id => setup.cars.find(c => c.id === id)?.name;
  const meta = d => [
    STATUS[d.status]?.label,
    carName(d.car_id),
    d.date ? `${fmt(d.date, { day: 'numeric', month: 'short', year: 'numeric' })}${d.start ? ` · ${d.start}` : ''}` : 'day to confirm',
    d.sample ? 'sample' : null,
  ].filter(Boolean).join(' · ');
  const choose = d => { setOpen(false); onPick(d); };
  const onKey = e => {
    if (e.key === 'Escape') { setOpen(false); return; }
    if (!results || !results.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive(i => Math.min(i + 1, results.length - 1)); }
    if (e.key === 'ArrowUp') { e.preventDefault(); setActive(i => Math.max(i - 1, 0)); }
    if (e.key === 'Enter') { e.preventDefault(); choose(results[active]); }
  };

  return (
    <div className="tdb-search" ref={boxRef}>
      <Search size={14} aria-hidden="true" />
      <input type="search" value={q} placeholder="Search by customer name" role="combobox"
             aria-label="Search test drives by customer name" aria-expanded={open}
             aria-controls="tdb-search-results" aria-autocomplete="list"
             onChange={e => setQ(e.target.value)} onKeyDown={onKey}
             onFocus={() => { if (results) setOpen(true); }} />
      {open && results && (
        <div className="tdb-results" id="tdb-search-results" role="listbox" aria-label="Test drives found">
          {results.length ? results.map((d, i) => (
            <button key={d.id} type="button" role="option" aria-selected={i === active}
                    className={i === active ? 'is-active' : ''}
                    onMouseEnter={() => setActive(i)} onClick={() => choose(d)}>
              <i className="tdb-dot" data-status={d.status} />
              <span className="tdb-res-name">{d.customer}</span>
              <span className="tdb-res-meta">{meta(d)}</span>
            </button>
          )) : <div className="tdb-res-none">No test drive for &ldquo;{q.trim()}&rdquo;.</div>}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ marks */

/* A day's counts as dots and numbers, in the strip and the week's cells. */
// A cancelled drive has its own grey count: it is never added to the drives that are on.
function Marks({ drives, enquiries, cancelled = 0 }) {
  if (!drives && !enquiries && !cancelled) return null;
  return (
    <span className="tdb-marks">
      {drives > 0 && <span className="tdb-mark" title={`${drives} test drive${drives === 1 ? '' : 's'}`}><i className="tdb-dot" data-status="booked" />{drives}</span>}
      {enquiries > 0 && <span className="tdb-mark" title={`${enquiries} enquir${enquiries === 1 ? 'y' : 'ies'}`}><i className="tdb-dot" data-status="requested" />{enquiries}</span>}
      {cancelled > 0 && <span className="tdb-mark is-cancelled" title={`${cancelled} cancelled`}><i className="tdb-dot" data-status="cancelled" />{cancelled}</span>}
    </span>
  );
}

/* ------------------------------------------------------------------- week */

/* The week at a glance: cars down the side, days across, each cell the test
   drives and enquiries for that car that day, tinted deeper the busier it
   is. A click opens the day. */
function WeekView({ setup, day, drives, enquiries, carOf, onDay, onJump }) {
  const start = weekStart(day);
  const days = Array.from({ length: 7 }, (_, i) => isoAdd(start, i));
  const cell = {};
  const add = (car, d, k) => { const key = `${car}|${d}`; cell[key] = cell[key] || { drives: 0, enquiries: 0 }; cell[key][k] += 1; };
  drives.filter(x => days.includes(x.on)).forEach(x => add(carOf(x), x.on, 'drives'));
  enquiries.filter(x => days.includes(x.on)).forEach(x => add(carOf(x), x.on, 'enquiries'));
  const rows = setup.cars.map(c => ({ id: c.id, name: c.name }));
  if (days.some(d => cell[`null|${d}`])) rows.push({ id: null, name: 'Model not recorded' });
  const at = (id, d) => cell[`${id}|${d}`] || { drives: 0, enquiries: 0 };
  const sum = list => list.reduce((a, t) => ({ drives: a.drives + t.drives, enquiries: a.enquiries + t.enquiries }),
    { drives: 0, enquiries: 0 });
  const max = Math.max(1, ...rows.flatMap(r => days.map(d => at(r.id, d).drives)));

  return (
    <div className="tdb-week">
      <div className="tdb-weekbar">
        <button type="button" className="tdb-nav" onClick={() => onJump(-7)} aria-label="Previous week">&#8249;</button>
        <b>{fmt(days[0], { day: 'numeric', month: 'short' })} &ndash; {fmt(days[6], { day: 'numeric', month: 'short', year: 'numeric' })}</b>
        <button type="button" className="tdb-nav" onClick={() => onJump(7)} aria-label="Next week">&#8250;</button>
        <span className="tdb-hint">Click a day to open it.</span>
      </div>
      <div className="tdb-weekwrap">
        <table className="tdb-weektable">
          <thead>
            <tr>
              <th scope="col" className="tdb-wcar">Car</th>
              {days.map(d => (
                <th key={d} scope="col" className={`${d === setup.today ? 'is-today' : ''} ${d === day ? 'is-sel' : ''}`}>
                  <span>{d === setup.today ? 'Today' : fmt(d, { weekday: 'short' })}</span>
                  <b>{fmt(d, { day: 'numeric' })}</b>
                </th>
              ))}
              <th scope="col" className="tdb-wsum">Week</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id || 'none'}>
                <th scope="row" className="tdb-wcar"><b>{r.name}</b></th>
                {days.map(d => {
                  const t = at(r.id, d);
                  return (
                    <td key={d} className={d === day ? 'is-sel' : ''}>
                      <button type="button" className="tdb-wcell" onClick={() => onDay(d)}
                              aria-label={`${r.name}, ${dayLong(d)}: ${t.drives} test drives, ${t.enquiries} enquiries`}
                              style={t.drives ? { background: `color-mix(in srgb, var(--s1) ${Math.round(5 + (t.drives / max) * 15)}%, var(--surface))` } : undefined}>
                        <Marks {...t} />
                      </button>
                    </td>
                  );
                })}
                <td className="tdb-wsum"><Marks {...sum(days.map(d => at(r.id, d)))} /></td>
              </tr>
            ))}
            <tr className="tdb-wtotal">
              <th scope="row" className="tdb-wcar"><b>All cars</b></th>
              {days.map(d => <td key={d}><Marks {...sum(rows.map(r => at(r.id, d)))} /></td>)}
              <td className="tdb-wsum"><Marks {...sum(rows.flatMap(r => days.map(d => at(r.id, d))))} /></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- calendar */

/* The month of test drives. A row per demo car, half-hour slots across; an
   enquiry that names its day waits in its car's lane above the slots until
   someone gives it a time. The month bar's figures switch each status on and
   off; car, executive and sample filters narrow the strip, the day and the
   week alike. */
function Calendar({ setup, drives, calls = [], month, setMonth, day, setDay, onSlot, onOpen, onCall, onPick,
                    view, setView, show, setShow, car, setCar, exec, setExec, samples, setSamples,
                    loading, loadError, onRetry }) {
  const strip = useMemo(() => Array.from({ length: daysIn(month) }, (_, i) => isoAdd(month, i)), [month]);
  const past = day < setup.today;
  const isThisMonth = month === monthOf(setup.today);
  const now = nowIST();
  const known = new Set(setup.cars.map(c => c.id));
  const carOf = x => (known.has(x.car_id) ? x.car_id : null);
  const carById = id => setup.cars.find(c => c.id === id);

  // Filters: car and executive narrow everything; the status switches decide what shows.
  const scoped = drives.filter(x => (!car || x.car_id === car) && (!exec || x.consultant === exec));
  const visible = scoped.filter(x => show.includes(x.status));
  const slotted = visible.filter(x => SLOTTED.includes(x.status) && x.start);
  // A no-show with no slot is an enquiry whose day passed with no booking. It
  // never held a slot, so it stays in its car's Enquiries lane, in red.
  const missed = visible.filter(x => x.status === 'no_show' && !x.start);
  /* A test drive promised on a call with nothing saved for the caller - the
     Enquiries tab's second list, read from the agent's call log - is an
     enquiry too: on the day of the call, until someone schedules it. It has
     no executive, so an executive filter leaves it out. */
  const promised = exec || !show.includes('requested') ? [] : calls
    .filter(r => r.called_at && (!car || r.car_id === car))
    .map(r => ({
      id: `call-${r.call_id}`, fromCall: r, status: 'requested', car_id: r.car_id || null,
      on: new Date(r.called_at).toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' }),
      date: null, start: null, asked_time: null, when_hint: r.when_hint,
      customer: r.name || 'Unknown caller', phone: r.phone || '', source: 'AI agent',
      location: 'Showroom', address: '', consultant: '', sample: false,
    }));
  // Every enquiry has a day here (`on`): the one it asks for, or the one it came in on.
  const enquiries = [...visible.filter(x => x.status === 'requested'), ...promised];
  const openEntry = x => (x.fromCall ? onCall(x.fromCall) : onOpen(x));

  // Each day's counts for the strip, from what is showing.
  const tally = {};
  const add = (d, k) => { tally[d] = tally[d] || { drives: 0, enquiries: 0, cancelled: 0 }; tally[d][k] += 1; };
  [...slotted, ...missed].forEach(x => add(x.on, 'drives'));
  enquiries.forEach(x => add(x.on, 'enquiries'));
  visible.filter(x => x.status === 'cancelled').forEach(x => add(x.on, 'cancelled'));

  // The month's figures answer to the car and executive filters, not to the
  // switches: a status switched off still says how many it is hiding.
  const inMonth = x => x.on >= month && x.on < addMonths(month, 1);
  const totals = Object.fromEntries(SHOWN.map(s => [s, scoped.filter(x => inMonth(x) && x.status === s).length]));
  totals.requested += promised.filter(inMonth).length;
  const execs = [...new Set(drives.map(x => x.consultant).filter(Boolean).concat(exec ? [exec] : []))].sort();
  const filtered = !!car || !!exec || SHOWN.some(s => show.includes(s) !== (s !== 'cancelled'));
  const toggle = s => setShow(v => (v.includes(s) ? v.filter(x => x !== s) : [...v, s]));

  // The day.
  const all = drives.filter(x => x.on === day && SLOTTED.includes(x.status) && x.start);  // every slot held
  const daySlotted = slotted.filter(x => x.on === day).sort((a, b) => a.start.localeCompare(b.start));
  const dayCancelled = visible.filter(x => x.on === day && x.status === 'cancelled');
  const dayEnquiries = enquiries.filter(x => x.on === day);
  const dayMissed = missed.filter(x => x.on === day);
  const dayDrives = daySlotted.length + dayMissed.length;
  const shownIds = new Set(daySlotted.map(x => x.id));
  // A real drive wins its slot over a sample one.
  const at = (carId, slot) => {
    const here = all.filter(b => b.car_id === carId && b.start === slot);
    return here.find(b => !b.sample) || here[0];
  };
  const held = new Set(all.filter(b => !b.sample).map(b => `${b.car_id}|${b.start}`));
  const freeSlots = past ? 0 : setup.cars.length * setup.slots.length
    - held.size - (day === setup.today ? setup.cars.length * setup.slots.filter(s => s <= now).length : 0);
  const count = s => daySlotted.filter(x => x.status === s).length + (s === 'no_show' ? dayMissed.length : 0);
  const laneFor = carId => [...dayEnquiries, ...dayMissed].filter(x => carOf(x) === carId);
  const unplaced = laneFor(null);

  /* A lane spans every slot column, so on a narrow screen its blocks would
     wrap at the far edge; held to the visible width and pinned beside the
     car column, they stay in view however far the slots scroll. */
  const wrapRef = useRef(null);
  const [laneW, setLaneW] = useState(null);
  useLayoutEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return undefined;
    const measure = () => {
      const corner = wrap.querySelector('.tdb-corner');
      setLaneW(wrap.clientWidth - (corner ? corner.offsetWidth : 0));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [view]);

  // Keep the chosen day in view inside the strip, without scrolling the page.
  const stripRef = useRef(null);
  useEffect(() => {
    const box = stripRef.current;
    const el = box && box.querySelector('[aria-selected="true"]');
    if (el) box.scrollLeft = el.offsetLeft - box.clientWidth / 2 + el.clientWidth / 2;
  }, [day, month]);

  const go = n => {
    const m = addMonths(month, n);
    setMonth(m);
    setDay(m === monthOf(setup.today) ? setup.today : m);
  };
  const goToday = () => { setMonth(monthOf(setup.today)); setDay(setup.today); };
  const jump = n => {
    const d = isoAdd(day, n);
    if (monthOf(d) !== month) setMonth(monthOf(d));
    setDay(d);
  };
  const openDay = d => { if (monthOf(d) !== month) setMonth(monthOf(d)); setDay(d); setView('day'); };
  const wk = view === 'week' ? weekStart(day) : null;

  const lane = list => (
    <div className="tdb-lane">
      <div className="tdb-lane-in">
        <span className="tdb-lane-tag">Enquiries</span>
        {list.map(x => (
          <button key={x.id} type="button" className={`tdb-entry ${x.sample ? 'is-sample' : ''}`}
                  data-status={x.fromCall ? 'call' : x.status} onClick={() => openEntry(x)}
                  title={x.fromCall
                    ? `${x.customer} · test drive promised on a call, not saved yet · click to schedule`
                    : `${x.customer} · ${x.status === 'no_show' ? 'enquiry, day passed with no booking' : 'enquiry'} · ${askLabel(x).toLowerCase()}${x.date ? '' : ` · came in ${shortDate(x.enquired_on)}`}`}>
            <b>{x.customer}</b>
            <span>{askLabel(x)}</span>
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <div className="tdb-board" aria-busy={loading}>
      <div className="tdb-monthbar">
        <button type="button" className="tdb-nav" onClick={() => go(-1)} aria-label="Previous month">&#8249;</button>
        <b className="tdb-month" aria-live="polite">{monthName(month)}</b>
        <button type="button" className="tdb-nav" onClick={() => go(1)} aria-label="Next month">&#8250;</button>
        {(!isThisMonth || day !== setup.today) && (
          <button type="button" className="rail-quiet tdb-today" onClick={goToday}>Today</button>
        )}
        <div className={`tdb-monthsum ${loadError ? 'is-bad' : ''}`} title={loadError || undefined}>
          {loadError
            ? (loading ? 'This month could not be loaded' : 'Refresh failed · showing the last figures loaded')
            : loading ? 'Loading…'
            : SHOWN.map(s => {
                const on = show.includes(s);
                return (
                  <button key={s} type="button" className="tdb-kind" aria-pressed={on}
                          title={on ? `Hide ${STATUS[s].many}` : `Show ${STATUS[s].many}`} onClick={() => toggle(s)}>
                    <i className="tdb-dot" data-status={s} />{totals[s]} {totals[s] === 1 ? STATUS[s].one : STATUS[s].many}
                  </button>
                );
              })}
        </div>
      </div>

      <div className="tdb-toolbar">
        <div className="tdb-seg" role="group" aria-label="View">
          {[['day', 'Day'], ['week', 'Week']].map(([k, label]) => (
            <button key={k} type="button" aria-pressed={view === k} className={view === k ? 'primary' : ''}
                    onClick={() => setView(k)}>{label}</button>
          ))}
        </div>
        <select className="tdb-exec" value={car} onChange={e => setCar(e.target.value)} aria-label="Car">
          <option value="">All cars</option>
          {setup.cars.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select className="tdb-exec" value={exec} onChange={e => setExec(e.target.value)} aria-label="Sales executive">
          <option value="">All executives</option>
          {execs.map(n => <option key={n} value={n}>{n}</option>)}
        </select>
        <label className="tdb-check">
          <input type="checkbox" checked={samples} onChange={e => setSamples(e.target.checked)} /> Sample drives
        </label>
        {filtered && (
          <button type="button" className="rail-quiet tdb-clear"
                  onClick={() => { setShow(SHOWN.filter(s => s !== 'cancelled')); setCar(''); setExec(''); }}>
            Clear filters
          </button>
        )}
        <SearchBox setup={setup} samples={samples} onPick={onPick} />
      </div>

      <div className="tdb-strip" role="tablist" aria-label={`Days of ${monthName(month)}`} ref={stripRef}>
        {strip.map(d => {
          const t = tally[d] || { drives: 0, enquiries: 0, cancelled: 0 };
          return (
            <button key={d} type="button" role="tab" aria-selected={d === day}
                    aria-label={`${dayLong(d)}: ${t.drives} test drive${t.drives === 1 ? '' : 's'}, ${t.enquiries} enquir${t.enquiries === 1 ? 'y' : 'ies'}${t.cancelled ? `, ${t.cancelled} cancelled` : ''}`}
                    className={`tdb-day ${d === day ? 'is-on' : ''} ${d < setup.today ? 'is-past' : ''} ${wk && d >= wk && d <= isoAdd(wk, 6) ? 'in-week' : ''}`}
                    onClick={() => setDay(d)}>
              <span className="tdb-dow">{d === setup.today ? 'Today' : fmt(d, { weekday: 'short' })}</span>
              <span className="tdb-dom">{fmt(d, { day: 'numeric' })}</span>
              {t.drives || t.enquiries || t.cancelled ? <Marks {...t} /> : <span className="tdb-mon">{fmt(d, { month: 'short' })}</span>}
            </button>
          );
        })}
      </div>

      {view === 'week' ? (
        <WeekView setup={setup} day={day} drives={[...slotted, ...missed]} enquiries={enquiries} carOf={carOf}
                  onDay={openDay} onJump={jump} />
      ) : (
        <>
          <div className="tdb-daysum">
            <b>{dayLong(day)}</b>
            {/* Until the month is in, a count of nothing would read as a day with nothing on. */}
            {loading
              ? <span>{loadError ? 'Not loaded' : 'Loading…'}</span>
              : <span className="tdb-tally"><i className="tdb-dot" data-status="booked" /><span><b>{dayDrives}</b> test drive{dayDrives === 1 ? '' : 's'}</span></span>}
            {dayEnquiries.length > 0 && (
              <span className="tdb-tally"><i className="tdb-dot" data-status="requested" /><span><b>{dayEnquiries.length}</b> enquir{dayEnquiries.length === 1 ? 'y' : 'ies'} waiting</span></span>
            )}
            {count('attended') > 0 && <span><b>{count('attended')}</b> attended</span>}
            {count('no_show') > 0 && <span><b>{count('no_show')}</b> no-show{count('no_show') === 1 ? '' : 's'}</span>}
            {dayCancelled.length > 0 && <span><b>{dayCancelled.length}</b> cancelled</span>}
            {past ? <span>Past day</span> : !loading && <span><b>{Math.max(0, freeSlots)}</b> free slots left</span>}
          </div>

          <div className="tdb-gridwrap" ref={wrapRef} style={laneW ? { '--lane-w': `${laneW}px` } : undefined}>
            <div className="tdb-grid" style={{ '--slots': setup.slots.length }}>
              <div className="tdb-corner">Car</div>
              {setup.slots.map(s => <div key={s} className="tdb-time">{s}</div>)}
              {setup.cars.filter(c => !car || c.id === car).map(c => {
                const waiting = laneFor(c.id);
                return (
                  <React.Fragment key={c.id}>
                    <div className={`tdb-car ${waiting.length ? 'has-lane' : ''}`}>
                      <b>{c.name}</b>
                      <span>{c.summary}</span>
                    </div>
                    {waiting.length > 0 && lane(waiting)}
                    {setup.slots.map(s => {
                      const b = at(c.id, s);
                      if (b) {
                        return (
                          <button key={s} type="button" data-status={b.status}
                                  className={`tdb-slot tdb-block ${shownIds.has(b.id) ? '' : 'is-dim'} ${b.sample ? 'is-sample' : ''}`}
                                  onClick={() => onOpen(b)}
                                  title={`${b.customer} · ${s} · ${b.location === 'Home' ? 'at home' : 'showroom'} · ${STATUS[b.status].label}${b.sample ? ' · sample' : ''}`}>
                            <b>{b.customer.split(' ')[0]}</b>
                            <span>{b.location === 'Home' ? 'Home' : STATUS[b.status].label}</span>
                          </button>
                        );
                      }
                      const gone = past || (day === setup.today && s <= now);
                      return gone
                        ? <div key={s} className="tdb-slot tdb-past" aria-hidden="true" />
                        : (
                          <button key={s} type="button" className="tdb-slot tdb-empty"
                                  onClick={() => onSlot(c.id, s)}
                                  aria-label={`Book ${c.name} at ${s}`} title={`Book ${c.name} at ${s}`} />
                        );
                    })}
                  </React.Fragment>
                );
              })}
              {!car && unplaced.length > 0 && (
                <>
                  <div className="tdb-car tdb-car-none">
                    <b>Model not recorded</b>
                    <span>Enquiries with no car named</span>
                  </div>
                  {lane(unplaced)}
                </>
              )}
            </div>
          </div>

          <div className="tdb-legend">
            {SLOTTED.map(k => (
              <span key={k}><i className="tdb-swatch" data-status={k} /> {STATUS[k].label}</span>
            ))}
            <span><i className="tdb-swatch" data-status="requested" /> Enquiry</span>
            {samples && <span><i className="tdb-swatch is-sample" /> Sample</span>}
            <span className="tdb-hint">
              {past ? 'This day has passed, so its slots cannot be booked.'
                : `Click an empty slot to book. ${setup.slot_minutes}-minute slots, ${setup.slots[0]} to 19:00.`}
            </span>
          </div>

          <h3 className="tdb-h3">Agenda &middot; {dayLong(day)}</h3>
          {loading && loadError ? (
            <div className="tdb-error tdb-failed">
              <span>{monthName(month)}&rsquo;s test drives could not be loaded ({loadError}).</span>
              <button type="button" className="rail-quiet" onClick={onRetry}>Try again</button>
            </div>
          ) : !daySlotted.length && !dayMissed.length && !dayEnquiries.length && !dayCancelled.length ? (
            <div className="tdb-empty-day">
              {loading ? 'Loading…'
                : drives.some(x => x.on === day) ? 'Nothing on this day matches the filters.'
                : past ? 'No test drives on this day.'
                : 'No test drives booked yet. Click a slot above to book one.'}
            </div>
          ) : (
            <div className="tdb-agenda">
              {[...daySlotted, ...dayMissed, ...dayCancelled].map(b => (
                <div key={b.id} className={`tdb-row ${b.sample ? 'is-sample' : ''}`}>
                  <span className="tdb-at">{b.start || '—'}</span>
                  <div className="tdb-who">
                    <div><b>{b.customer}</b> &middot; {carById(b.car_id)?.name || 'Model not recorded'}
                      {b.sample && <span className="tdb-samplechip">Sample</span>}</div>
                    <div className="tdb-meta">
                      {[b.location === 'Home' ? `Home${b.address ? `: ${b.address}` : ''}` : 'Showroom',
                        b.phone, b.consultant || 'Executive not assigned', b.source,
                        b.status === 'no_show' && !b.start
                          ? `enquiry${b.asked_time ? ` for ${b.asked_time}` : ''}, never booked` : null].filter(Boolean).join(' · ')}
                    </div>
                  </div>
                  <span className="tdb-pill" data-status={b.status}>{STATUS[b.status].label}</span>
                  <button type="button" className="rail-quiet" onClick={() => onOpen(b)}>Open</button>
                </div>
              ))}
              {dayEnquiries.map(x => (
                <div key={x.id} className={`tdb-row tdb-rec ${x.sample ? 'is-sample' : ''}`}>
                  <span className="tdb-at" title="No slot yet">{x.asked_time || '—'}</span>
                  <div className="tdb-who">
                    <div><b>{x.customer}</b> &middot; {carById(x.car_id)?.name || 'Model not recorded'}
                      {x.sample && <span className="tdb-samplechip">Sample</span>}</div>
                    <div className="tdb-meta">
                      {(x.fromCall
                        ? [x.phone, 'promised on a call, not saved yet', x.when_hint && `asked for ${x.when_hint}`]
                        : [x.location === 'Home' ? `Home${x.address ? `: ${x.address}` : ''}` : 'Showroom',
                           x.phone, x.source, askLabel(x).toLowerCase()]).filter(Boolean).join(' · ')}
                    </div>
                  </div>
                  <span className="tdb-pill" data-status="requested">{x.fromCall ? 'From a call' : 'Enquiry'}</span>
                  <button type="button" className="rail-quiet" onClick={() => openEntry(x)}>
                    {x.fromCall ? 'Schedule' : 'Open'}
                  </button>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* -------------------------------------------------------------- enquiries */

/* Test-drive enquiries waiting for a time - every one already in the
   database - and test drives the agent promised on a call with nothing on
   record. Nothing here is a car booking or a general enquiry. */
function Enquiries({ setup, waiting, requests, unavailable, car, onSchedule, onScheduleCall, onOpen }) {
  const carName = id => setup.cars.find(c => c.id === id)?.name;
  const [all, setAll] = useState(false);
  const list = waiting
    .filter(d => !car || d.car_id === car)
    .sort((a, b) => (a.date || '9999').localeCompare(b.date || '9999')
      || b.enquired_on.localeCompare(a.enquired_on) || b.created_at.localeCompare(a.created_at));
  const shown = all ? list : list.slice(0, ENQUIRY_ROWS);
  return (
    <>
      <h3 className="tdb-h3">Waiting for a time &middot; {list.length}</h3>
      <p className="tdb-lede">
        Test-drive enquiries saved by the AI agent or the website whose day or time is not fixed yet - or
        whose time was already taken. Each is also on the calendar, in its car&rsquo;s Enquiries lane: on the
        day it asks for, or on the day it came in. Schedule one to give it a slot.
      </p>
      {list.length ? (
        <>
          <div className="tdb-agenda">
            {shown.map(d => (
              <div key={d.id} className={`tdb-row tdb-req ${d.sample ? 'is-sample' : ''}`}>
                <span className="tdb-at" title="The day the enquiry came in">{shortDate(d.enquired_on)}</span>
                <div className="tdb-who">
                  <div>
                    <b>{d.customer}</b>
                    {d.phone ? ` · ${d.phone}` : ''}
                    {carName(d.car_id) ? ` · ${carName(d.car_id)}` : ' · car not named'}
                    {(d.date || d.asked_time) && (
                      <span className="tdb-hintchip">
                        asked for {[d.date && fmt(d.date, { weekday: 'short', day: 'numeric', month: 'short' }), d.asked_time].filter(Boolean).join(' ')}
                      </span>
                    )}
                    {d.sample && <span className="tdb-samplechip">Sample</span>}
                  </div>
                  <div className="tdb-meta tdb-summary">
                    {[d.source, d.location === 'Home' ? `Home${d.address ? `: ${d.address}` : ''}` : null, d.note].filter(Boolean).join(' · ')}
                  </div>
                </div>
                <button type="button" className="rail-quiet" onClick={() => onOpen(d)}>Open</button>
                <button type="button" className="primary" onClick={() => onSchedule(d)}>Schedule</button>
              </div>
            ))}
          </div>
          {list.length > ENQUIRY_ROWS && (
            <button type="button" className="rail-quiet tdb-more" onClick={() => setAll(v => !v)}>
              {all ? 'Show fewer' : `Show all ${list.length}`}
            </button>
          )}
        </>
      ) : <div className="tdb-empty-day">Nothing waiting: every test-drive enquiry has its slot.</div>}

      <h3 className="tdb-h3 tdb-h3-gap">Promised on a call &middot; {requests.length}</h3>
      <p className="tdb-lede">
        Calls where the AI agent offered or promised a test drive and nothing was saved for the caller.
        Read live from the call log; the car is the one the caller asked about.
      </p>
      {unavailable ? <div className="tdb-empty-day">The call log cannot be read here: {unavailable}</div>
        : !requests.length ? <div className="tdb-empty-day">Every test drive promised on a call is on record.</div>
        : (
          <div className="tdb-agenda">
            {requests.map(r => (
              <div key={r.call_id} className="tdb-row tdb-req">
                <span className="tdb-at">{fmt((r.called_at || '').slice(0, 10), { day: 'numeric', month: 'short' })}</span>
                <div className="tdb-who">
                  <div>
                    <b>{r.name || 'Unknown caller'}</b>
                    {r.phone ? ` · ${r.phone}` : ''}
                    {carName(r.car_id) ? ` · ${carName(r.car_id)}` : ' · car not named'}
                    {r.when_hint ? <span className="tdb-hintchip">asked for {r.when_hint}</span> : null}
                  </div>
                  <div className="tdb-meta tdb-summary">{r.summary}</div>
                </div>
                <button type="button" className="primary" onClick={() => onScheduleCall(r)}>Schedule</button>
              </div>
            ))}
          </div>
        )}
    </>
  );
}

/* --------------------------------------------------------------- the cars */

function FleetAndTeam({ setup }) {
  const models = setup.cars.reduce((n, c) => n + c.models.length, 0);
  const variants = setup.cars.reduce((n, c) => n + c.models.reduce((m, x) => m + x.variants.length, 0), 0);
  return (
    <>
      <section>
        <h3 className="tdb-h3">Cars &middot; {models} models, {variants} variants</h3>
        <p className="tdb-lede">
          The line-up as the catalogue holds it, busiest first. The database records stock but not
          which cars are demonstrators, so test drives are booked on one demo car per model; a customer
          can be shown any of its variants.
        </p>
        <div className="tdb-cars">
          {setup.cars.map(c => (
            <div key={c.id} className="tdb-carcard">
              <div className="tdb-carhead">
                <b>{c.name}</b>
                <span>{[c.summary || 'No variants listed', c.gearboxes.join(', ')].filter(Boolean).join(' · ')}</span>
              </div>
              {c.models.map(m => (
                <div key={m.name} className="tdb-model">
                  {c.models.length > 1 && (
                    <div className="tdb-modelname">{m.name} &middot; {m.variants.length} variants</div>
                  )}
                  {m.variants.length ? (
                    <ul className="tdb-variants">
                      {m.variants.map(v => (
                        <li key={v.id}><span>{v.name}</span>{v.gearbox && <em>{v.gearbox}</em>}</li>
                      ))}
                    </ul>
                  ) : <div className="tdb-meta">The catalogue lists no variants for this model yet.</div>}
                </div>
              ))}
            </div>
          ))}
        </div>
      </section>
      <section className="tdb-teamwrap">
        <h3 className="tdb-h3">Sales executives &middot; {setup.consultants.length}</h3>
        <p className="tdb-lede">Every active consultant in the database, offered when a drive is booked.</p>
        <div className="tdb-team">
          {setup.consultants.map(c => <span key={c}>{c}</span>)}
        </div>
      </section>
    </>
  );
}

/* ------------------------------------------------------------------- page */

export default function TestDriveBoard({ refreshKey }) {
  const [loaded, setLoaded] = useState(null);          // the cars, team and slots, as /setup sent them
  const [drives, setDrives] = useState([]);
  const [stats, setStats] = useState(null);
  const [queue, setQueue] = useState({ waiting: [], requests: [], unavailable: null });
  const [tab, setTab] = useState('calendar');
  const [month, setMonth] = useState(null);
  const [day, setDay] = useState(null);
  const [draft, setDraft] = useState(null);
  const [opened, setOpened] = useState(null);
  const [error, setError] = useState(null);
  const [loadedFor, setLoadedFor] = useState(null);   // the month (and sample setting) the drives belong to
  const [monthError, setMonthError] = useState(null);  // { key, message }: which month failed to load, and why
  const [retry, setRetry] = useState(0);
  const [view, setView] = useState('day');
  const [show, setShow] = useState(SHOWN.filter(s => s !== 'cancelled'));
  const [car, setCar] = useState('');
  const [exec, setExec] = useState('');
  const [samples, setSamples] = useState(true);
  const [tick, setTick] = useState(0);                 // a drive saved here: read everything again
  const [, setClock] = useState(0);

  useEffect(() => {
    api(`${BASE}/setup`)
      .then(s => { setLoaded(s); setMonth(monthOf(s.today)); setDay(s.today); })
      .catch(e => setError(e.message));
  }, []);

  /* Drawn again every half minute, with today read from the clock each time
     rather than once at opening: on a board left open all day, slots grey
     out as their time goes, and today turns over at midnight. */
  useEffect(() => {
    const t = setInterval(() => setClock(c => c + 1), 30000);
    return () => clearInterval(t);
  }, []);
  const setup = loaded && { ...loaded, today: todayIST() };

  /* The month in view, padded out to whole weeks for the week view. Read
     again when the month changes, when the dashboard hears the database
     change (refreshKey: an agent's booking, a drive filed from an enquiry),
     and after a drive is saved here. Paging quickly through months fetches
     only the one the board stops on. */
  useEffect(() => {
    if (!month) return undefined;
    let dead = false;
    const range = rangeOf(month);
    const key = `${month}|${samples}`;
    const wait = setTimeout(() => {
      api(`${BASE}?start=${range.start}&days=${range.days}&samples=${samples}`)
        .then(r => { if (!dead) { setDrives(r.bookings || []); setLoadedFor(key); setMonthError(null); } })
        .catch(e => { if (!dead) setMonthError({ key, message: e.message }); });
    }, 120);
    return () => { dead = true; clearTimeout(wait); };
  }, [month, refreshKey, tick, samples, retry]);

  // The headline and the waiting list are quick reads and follow every change.
  useEffect(() => {
    let dead = false;
    api(`${BASE}/stats?samples=${samples}`).then(s => { if (!dead) setStats(s); }).catch(() => {});
    api(`${BASE}/requests?calls=false&samples=${samples}`)
      .then(r => { if (!dead) setQueue(q => ({ ...q, waiting: r.waiting || [] })); })
      .catch(() => {});
    return () => { dead = true; };
  }, [refreshKey, tick, samples]);

  // The call log is slow: read on opening, and after a drive is saved here.
  useEffect(() => {
    let dead = false;
    api(`${BASE}/requests?samples=${samples}`)
      .then(r => { if (!dead) setQueue({ waiting: r.waiting || [], requests: r.requests || [], unavailable: r.unavailable || null }); })
      .catch(e => { if (!dead) setQueue(q => ({ ...q, requests: [], unavailable: e.message })); });
    return () => { dead = true; };
  }, [tick, samples]);

  if (error) return <div className="panel"><div className="tdb-error">{error}</div></div>;
  if (!setup || !day || !month) return <div className="panel"><div className="tdb-empty-day">Opening test drives…</div></div>;

  const blank = { customer: '', phone: '', consultant: '', location: 'Showroom', address: '', source: 'Staff',
                  call_id: null, fromCall: null, request_id: null, fromRequest: null, fromMissed: null };
  const carName = id => setup.cars.find(c => c.id === id)?.name;
  // The first day a drive can still go in: today while a slot is still ahead, else tomorrow.
  const firstOpen = nowIST() < setup.slots[setup.slots.length - 1] ? setup.today : isoAdd(setup.today, 1);
  const forward = d => (d && d >= firstOpen ? d : firstOpen);

  const bookSlot = (carId, start) => setDraft({ ...blank, car_id: carId, date: day, start });
  // An enquiry becomes a booking: its car and day, and the time asked for.
  const scheduleEnquiry = d => {
    setOpened(null);
    setDraft({ ...blank, car_id: carName(d.car_id) ? d.car_id : setup.cars[0].id, date: forward(d.date),
               start: d.asked_time || '', customer: d.customer, phone: d.phone || '',
               consultant: d.consultant || '', location: d.location || 'Showroom', address: d.address || '',
               source: d.source || 'Staff', call_id: d.call_id, request_id: d.id, fromRequest: d });
  };
  const scheduleCall = r => {
    setDraft({ ...blank, car_id: r.car_id || setup.cars[0].id, date: forward(dateFromHint(r.when_hint, setup.today)),
               start: '', customer: r.name || '', phone: r.phone || '', source: 'AI agent',
               call_id: r.call_id, fromCall: r });
  };
  // A customer who missed a drive, or the day they asked for, booked again: a
  // new drive, so the no-show stays on record.
  const bookAgain = d => {
    setOpened(null);
    setDraft({ ...blank, car_id: carName(d.car_id) ? d.car_id : setup.cars[0].id, date: firstOpen, start: '',
               customer: d.customer, phone: d.phone || '', consultant: d.consultant || '',
               location: d.location || 'Showroom', address: d.address || '', fromMissed: d });
  };
  const saved = row => {
    setDraft(null);
    if (monthOf(row.date) !== month) setMonth(monthOf(row.date));
    setDay(row.date); setTab('calendar'); setView('day');
    setTick(t => t + 1);
  };
  const changed = row => { setOpened(null); setDrives(b => b.map(x => (x.id === row.id ? row : x))); setTick(t => t + 1); };
  const pick = d => {
    const on = d.on;
    if (monthOf(on) !== month) setMonth(monthOf(on));
    setDay(on); setTab('calendar'); setView('day');
    setOpened(d);
  };
  const waitingCount = queue.waiting.length + queue.requests.length;
  const monthKey = `${month}|${samples}`;

  return (
    <div className="panel tdb">
      <div className="tdb-top">
        <div className="tdb-eyebrow">Elite VW, Bengaluru &middot; Test drives</div>
        <div className="tdb-tabs" role="tablist" aria-label="Test drive views">
          {[['calendar', 'Calendar'], ['enquiries', `Enquiries${waitingCount ? ` · ${waitingCount}` : ''}`], ['fleet', 'Cars and team']].map(([k, label]) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k}
                    className={tab === k ? 'is-on' : ''} onClick={() => setTab(k)}>{label}</button>
          ))}
        </div>
      </div>
      <div className="tdb-note">
        Test drives only &middot; booked by the AI agent on a call, by the sales desk, or for a walk-in &middot;
        enquiries are test drives asked for and still waiting for a time
        {samples && <> &middot; dashed drives are samples, made up for showing the section</>}
      </div>

      <Headline stats={stats} carName={carName} onEnquiries={() => setTab('enquiries')} />

      {tab === 'calendar' && (
        <Calendar setup={setup} drives={drives} month={month} setMonth={setMonth} day={day} setDay={setDay}
                  calls={queue.requests} onCall={scheduleCall}
                  onSlot={bookSlot} onOpen={setOpened} onPick={pick}
                  view={view} setView={setView} show={show} setShow={setShow}
                  car={car} setCar={setCar} exec={exec} setExec={setExec}
                  samples={samples} setSamples={setSamples}
                  loading={loadedFor !== monthKey}
                  loadError={monthError?.key === monthKey ? monthError.message : null}
                  onRetry={() => setRetry(n => n + 1)} />
      )}
      {tab === 'enquiries' && (
        <Enquiries setup={setup} {...queue} car={car} onSchedule={scheduleEnquiry}
                   onScheduleCall={scheduleCall} onOpen={setOpened} />
      )}
      {tab === 'fleet' && <FleetAndTeam setup={setup} />}

      <Dialog open={!!draft} title="Book a test drive" onClose={() => setDraft(null)} wide>
        {draft && <BookingForm setup={setup} draft={draft} onCancel={() => setDraft(null)} onSaved={saved} />}
      </Dialog>
      <Dialog open={!!opened} title={opened?.status === 'requested' ? 'Test-drive enquiry' : 'Test drive'}
              onClose={() => setOpened(null)}>
        {opened && <BookingDetail booking={opened} car={setup.cars.find(c => c.id === opened.car_id)}
                                  onChanged={changed} onSchedule={scheduleEnquiry} onBookAgain={bookAgain} />}
      </Dialog>
    </div>
  );
}
