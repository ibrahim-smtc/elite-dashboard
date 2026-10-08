/**
 * What the agent said on the phone.
 *
 * Perfox answers the calls and the dashboard reports the month, and until now
 * those were two systems to open. Nobody on the floor was going to check the
 * second one to find out what a customer had been told that morning, so the
 * call log lives here, next to the bookings it produces.
 *
 * A row per call, newest first, with the agent's own summary - which is the
 * part a sales manager actually reads. Opening a call fetches its recordings
 * at that moment rather than with the list: the URLs Perfox issues are
 * presigned and last fifteen minutes, so any fetched up front would be dead
 * before most people scrolled to them.
 *
 * `direction` is not shown. Every call on record reports "unknown", so a
 * column of it would be a column of nothing.
 */

import React, { useEffect, useMemo, useState } from 'react';
import { Phone, Globe, Play, ChevronDown, AlertTriangle } from 'lucide-react';
import { api, n0 } from '../api/client';

/* The combined leg is both halves of the conversation mixed, which is what
   someone checking a call wants; the single legs are there for when you need
   to hear one side clearly. Ordered so the useful one is first. */
const LEG_ORDER = ['combined', 'caller', 'ai'];
const LEG_LABEL = { combined: 'Full call', caller: 'Customer', ai: 'Agent' };

function mmss(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function when(iso) {
  const d = new Date(iso);
  if (Number.isNaN(+d)) return null;
  return {
    date: d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }),
    time: d.toLocaleTimeString('en-IN', {
      hour: 'numeric', minute: '2-digit', hour12: true,
    }),
  };
}

/* A phone call and a call from the website are different things to a manager -
   one is a lead who found the number, the other is a lead already on the site. */
function ChannelMark({ channel }) {
  const web = channel === 'web_voice';
  const Icon = web ? Globe : Phone;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6,
                   color: 'var(--ink-2)', whiteSpace: 'nowrap' }}>
      <Icon size={12} style={{ flex: 'none', color: 'var(--ink-muted)' }} />
      {web ? 'Web' : 'Phone'}
    </span>
  );
}

/**
 * The conversation, turn by turn.
 *
 * The part most people will actually use. A recording needs someone to sit and
 * listen; this can be read in ten seconds and pasted into a follow-up - and
 * these calls switch between English, Hindi and Punjabi mid-sentence, which the
 * one-line summary never captures.
 */
function Transcript({ callId }) {
  const [state, setState] = useState({ loading: true });

  useEffect(() => {
    let dead = false;
    setState({ loading: true });
    api(`/api/calls/${callId}/transcript`)
      .then(r => { if (!dead) setState({ loading: false, data: r }); })
      .catch(e => { if (!dead) setState({ loading: false, error: e.message }); });
    return () => { dead = true; };
  }, [callId]);

  if (state.loading) {
    return <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>Reading the transcript…</div>;
  }
  if (state.error) {
    return (
      <div style={{ display: 'flex', gap: 7, alignItems: 'flex-start',
                    fontSize: 'var(--fs-small)', color: 'var(--critical)' }}>
        <AlertTriangle size={13} style={{ flex: 'none', marginTop: 1 }} />
        <span>{state.error}</span>
      </div>
    );
  }

  const { turns = [], tools = [], truncated } = state.data || {};
  if (!turns.length) {
    return <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>Nothing was said on this call.</div>;
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10,
                    marginBottom: 9, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 'var(--fs-small)', textTransform: 'uppercase',
                       letterSpacing: '0.07em', color: 'var(--ink-muted)' }}>
          Transcript
        </span>
        <span style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>
          {n0(turns.length)} turns
          {tools.length > 0 && <> · agent looked something up {n0(tools.length)}×</>}
        </span>
      </div>

      {/* Capped and scrollable: a four-minute call is forty-odd turns, and
          letting that push the rest of the sheet down means scrolling past a
          conversation to reach the next panel. */}
      <div style={{
        maxHeight: 280, overflowY: 'auto', paddingRight: 8,
        display: 'flex', flexDirection: 'column', gap: 9,
      }}>
        {turns.map((t, i) => {
          const mine = t.who === 'agent';
          return (
            <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
              <span style={{
                flex: 'none', width: 62, fontSize: 'var(--fs-micro)', lineHeight: 1.6,
                textTransform: 'uppercase', letterSpacing: '0.06em',
                color: mine ? 'var(--viz-1)' : 'var(--ink-muted)',
                fontWeight: mine ? 600 : 400,
              }}>
                {mine ? 'Agent' : 'Customer'}
              </span>
              {/* No white-space:pre - the text arrives as prose, and these are
                  Devanagari and Gurmukhi as often as Latin, so it has to wrap
                  normally rather than be held to a monospace column. */}
              <span style={{ fontSize: 'var(--fs-small)', lineHeight: 1.65,
                             color: mine ? 'var(--ink-2)' : 'var(--ink)' }}>
                {t.text}
              </span>
            </div>
          );
        })}
      </div>

      {truncated && (
        <div style={{ fontSize: 'var(--fs-small)', color: 'var(--warning)', marginTop: 8 }}>
          This transcript was longer than we fetched, so the end is missing.
        </div>
      )}
    </div>
  );
}

/* Perfox scores each call out of ten for whether the customer's need was met
   and how they sounded. Both are shown as a word with a colour behind it, not
   as a number: "6/10" invites arithmetic across a column that should be read a
   row at a time. */
const SENTIMENT_STYLE = {
  positive: { label: 'Positive', fg: 'var(--good-text)', bg: 'var(--s3-light)' },
  neutral:  { label: 'Neutral',  fg: 'var(--ink-2)',     bg: 'var(--sunken)' },
  negative: { label: 'Negative', fg: 'var(--critical)',  bg: 'var(--critical-light)' },
};

const VERDICT_STYLE = {
  'Resolved':        { fg: 'var(--good-text)', bg: 'var(--s3-light)' },
  'Needs follow-up': { fg: 'var(--warning)',   bg: 'var(--critical-light)' },
  'Abandoned':       { fg: 'var(--critical)',  bg: 'var(--critical-light)' },
  'Unscored':        { fg: 'var(--ink-muted)', bg: 'var(--sunken)' },
};

function Pill({ text, fg, bg, title }) {
  return (
    <span title={title} style={{
      display: 'inline-block', padding: '2px 9px', borderRadius: 2,
      fontSize: 'var(--fs-small)', lineHeight: 1.6, whiteSpace: 'nowrap',
      color: fg, background: bg, border: `1px solid ${fg}`,
    }}>
      {text}
    </span>
  );
}

function Sentiment({ value, score }) {
  const s = SENTIMENT_STYLE[value];
  if (!s) return <span style={{ color: 'var(--ink-muted)' }}>—</span>;
  return <Pill text={s.label} fg={s.fg} bg={s.bg}
               title={score != null ? `Scored ${score} out of 10` : undefined} />;
}

function Verdict({ value }) {
  const v = VERDICT_STYLE[value];
  if (!v) return <span style={{ color: 'var(--ink-muted)' }}>—</span>;
  return <Pill text={value} fg={v.fg} bg={v.bg} />;
}

function Recordings({ callId }) {
  const [state, setState] = useState({ loading: true });

  useEffect(() => {
    let dead = false;
    setState({ loading: true });
    api(`/api/calls/${callId}/recordings`)
      .then(r => { if (!dead) setState({ loading: false, data: r }); })
      .catch(e => { if (!dead) setState({ loading: false, error: e.message }); });
    return () => { dead = true; };
  }, [callId]);

  if (state.loading) {
    return <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>Fetching the recording…</div>;
  }
  if (state.error) {
    return (
      <div style={{ display: 'flex', gap: 7, alignItems: 'flex-start',
                    fontSize: 'var(--fs-small)', color: 'var(--critical)' }}>
        <AlertTriangle size={13} style={{ flex: 'none', marginTop: 1 }} />
        <span>{state.error}</span>
      </div>
    );
  }

  const recs = [...(state.data?.recordings || [])].sort(
    (a, b) => LEG_ORDER.indexOf(a.leg) - LEG_ORDER.indexOf(b.leg));

  if (!recs.length) {
    return <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>No recording was kept for this call.</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {recs.map(r => (
        <div key={r.leg} style={{ display: 'flex', alignItems: 'center', gap: 12,
                                  flexWrap: 'wrap' }}>
          <span style={{ fontSize: 'var(--fs-small)', textTransform: 'uppercase',
                         letterSpacing: '0.07em', color: 'var(--ink-muted)',
                         minWidth: 66 }}>
            {LEG_LABEL[r.leg] || r.leg}
          </span>
          {/* preload="none" deliberately: three legs across an open call would
              otherwise pull several megabytes of audio nobody asked to hear. */}
          <audio controls preload="none" src={r.url}
                 style={{ height: 34, flex: '1 1 260px', minWidth: 0 }} />
        </div>
      ))}
      {state.data?.expires_in_seconds != null && (
        <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>
          These links are issued for {Math.round(state.data.expires_in_seconds / 60)} minutes.
          Reopen the call if playback stops working.
        </div>
      )}
    </div>
  );
}

export default function AgentCalls() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let dead = false;
    api('/api/calls')
      .then(r => { if (!dead) setData(r); })
      .catch(e => { if (!dead) setError(e.message); });
    return () => { dead = true; };
  }, []);

  const calls = data?.calls || [];
  const shown = useMemo(
    () => (showAll ? calls : calls.slice(0, 8)), [calls, showAll]);

  const note = !data && !error ? 'Reading the call log…'
    : error ? null
    : `${n0(data.total)} calls · ${mmss(data.talk_seconds)} on the phone`
      + ` · ${n0(data.resolved)} resolved`
      + (data.negative ? ` · ${n0(data.negative)} left unhappy` : '');

  return (
    <section style={{ marginBottom: 26 }}>
      <div className="panel">
        <div className="panel-header" style={{ marginBottom: 14 }}>
          <h2>Calls the agent handled</h2>
          <span style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>{note}</span>
        </div>

        {error ? (
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start',
                        fontSize: 'var(--fs-body)', color: 'var(--critical)', padding: '10px 0' }}>
            <AlertTriangle size={14} style={{ flex: 'none', marginTop: 2 }} />
            <span>{error}</span>
          </div>
        ) : !data ? (
          <div style={{ fontSize: 'var(--fs-body)', color: 'var(--ink-muted)', padding: '10px 0' }}>
            Reading the call log…
          </div>
        ) : !calls.length ? (
          <div style={{ fontSize: 'var(--fs-body)', color: 'var(--ink-muted)', padding: '10px 0' }}>
            The agent has not taken any calls yet.
          </div>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th style={{ width: 34 }} aria-label="Open" />
                    <th>When</th>
                    <th>Caller</th>
                    <th>Channel</th>
                    <th className="num">Length</th>
                    <th>Action verdict</th>
                    <th>Sentiment</th>
                    <th>What was said</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map(c => {
                    const isOpen = open === c.id;
                    return (
                      <React.Fragment key={c.id}>
                        <tr
                          onClick={() => setOpen(isOpen ? null : c.id)}
                          style={{ cursor: 'pointer' }}
                          aria-expanded={isOpen}
                        >
                          <td style={{ textAlign: 'center', color: 'var(--ink-muted)' }}>
                            {c.has_recording
                              ? <Play size={12} style={{
                                  transform: isOpen ? 'rotate(90deg)' : 'none',
                                  transition: 'transform var(--t-fast) var(--ease-out)' }} />
                              : <ChevronDown size={12} style={{
                                  transform: isOpen ? 'rotate(180deg)' : 'none',
                                  transition: 'transform var(--t-fast) var(--ease-out)' }} />}
                          </td>
                          <td>{(() => {
                            const w = when(c.started_at);
                            if (!w) return '—';
                            return (
                              <>
                                <div>{w.date}</div>
                                <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>
                                  {w.time}
                                </div>
                              </>
                            );
                          })()}</td>
                          <td style={{ whiteSpace: 'normal' }}>
                            <div>{c.name || 'Unknown caller'}</div>
                            {c.phone && (
                              <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>
                                {c.phone}
                              </div>
                            )}
                          </td>
                          <td><ChannelMark channel={c.channel} /></td>
                          <td className="num">{mmss(c.duration_seconds)}</td>
                          <td><Verdict value={c.verdict} /></td>
                          <td><Sentiment value={c.sentiment} score={c.sentiment_score} /></td>
                          {/* The summary is the column people read, so it gets
                              the room the fixed columns do not need. */}
                          <td style={{ whiteSpace: 'normal', width: '100%',
                                       color: 'var(--ink-2)' }}>
                            <div style={{ maxWidth: 520 }}>
                            {c.summary
                              ? (isOpen ? c.summary
                                        : c.summary.length > 120
                                          ? c.summary.slice(0, 120) + '…'
                                          : c.summary)
                              : <span style={{ color: 'var(--ink-muted)' }}>No summary</span>}
                            </div>
                          </td>
                        </tr>
                        {isOpen && (
                          <tr>
                            <td />
                            <td colSpan={7} style={{ whiteSpace: 'normal',
                                                     padding: '4px 0 18px' }}>
                              <div className="call-detail">
                                <div>
                                  {/* Transcript first. It is the thing that
                                      gets read; the audio is for when the
                                      wording matters or the transcript looks
                                      wrong. */}
                                  <Transcript callId={c.id} />
                                  <div style={{ marginTop: 14, paddingTop: 12,
                                                borderTop: '1px solid var(--grid)' }}>
                                    {c.has_recording
                                      ? <Recordings callId={c.id} />
                                      : <span style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>
                                          This call was not recorded.
                                        </span>}
                                  </div>
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {calls.length > 8 && (
              <button
                className="rail-quiet"
                onClick={() => setShowAll(s => !s)}
                style={{ marginTop: 12, padding: '5px 12px', fontSize: 'var(--fs-small)' }}
              >
                {showAll ? 'Show recent only' : `Show all ${n0(calls.length)} calls`}
              </button>
            )}
          </>
        )}
      </div>
    </section>
  );
}
