/**
 * Managing reporting months.
 *
 * Deleting a month cannot be undone from here - the only way back is to upload
 * that month's workbook again - so the flow is deliberately slow: the panel
 * first asks the server what the month actually contains, shows it, and only
 * then accepts the label typed back. The server enforces the same three rules
 * independently (label must match, the active month is refused, the last month
 * is refused); nothing here is the only thing standing between a click and the
 * data.
 */

import React, { useEffect, useState } from 'react';
import useClosing from './useClosing';
import { X, Trash2, Eraser, AlertTriangle } from 'lucide-react';
import { api, sendJson, n0, dt } from '../api/client';

export default function PeriodManager({ isOpen, periods = [], onClose, onChanged }) {
  const [target, setTarget] = useState(null);      // label pending the action
  const [mode, setMode] = useState('delete');      // 'delete' empties and removes; 'clear' only empties
  const [contents, setContents] = useState(null);  // what the server says it holds
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!isOpen) { setTarget(null); setContents(null); setTyped(''); setError(null); }
  }, [isOpen]);

  const { render, leaving } = useClosing(isOpen);
  if (!render) return null;

  const ask = async (label, how = 'delete') => {
    setTarget(label); setMode(how); setTyped(''); setError(null); setContents(null);
    try {
      setContents(await api(`/api/periods/${encodeURIComponent(label)}/contents`));
    } catch (e) {
      setError(e.message);
    }
  };

  const remove = async () => {
    setBusy(true); setError(null);
    try {
      const q = `confirm=${encodeURIComponent(typed.trim())}`;
      const res = mode === 'clear'
        ? await sendJson('POST', `/api/periods/${encodeURIComponent(target)}/clear?${q}`)
        : await sendJson('DELETE', `/api/periods/${encodeURIComponent(target)}?${q}`);
      onChanged(mode === 'clear'
        ? `Emptied ${res.cleared} — ${n0(res.total)} rows removed`
        : `Removed ${res.deleted} — ${n0(res.total)} rows`);
      setTarget(null); setContents(null); setTyped('');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const ordered = [...periods].sort((a, b) =>
    String(b.period_start || '').localeCompare(String(a.period_start || '')));
  const canDelete = typed.trim().toUpperCase() === String(target || '').toUpperCase();

  return (
    <div
      className={`drawer-scrim ${leaving ? 'is-leaving' : ''}`}
      style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="xp-panel" style={{
        background: 'var(--surface)', border: '1px solid var(--axis)',
        borderRadius: 'var(--radius-lg)', maxWidth: 560, width: '100%',
        maxHeight: '88vh', boxShadow: 'var(--shadow-lg)', overflow: 'hidden',
        display: 'flex', flexDirection: 'column',
      }}>
        <div style={{
          padding: '18px 24px', borderBottom: '1px solid var(--grid)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div>
            <h2 style={{ fontSize: 'var(--fs-head)' }}>Reporting months</h2>
            <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)', marginTop: 3 }}>
              Uploading a workbook replaces the month it belongs to &mdash; it is never added alongside
            </div>
          </div>
          <button onClick={onClose} aria-label="Close" style={{ padding: '6px 8px' }}>
            <X size={15} />
          </button>
        </div>

        <div style={{ padding: '10px 24px 24px', overflowY: 'auto' }}>
          {ordered.map(p => {
            const isTarget = target === p.label;
            return (
              <div key={p.label} style={{
                padding: '14px 0',
                borderBottom: '1px solid var(--grid)',
              }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                  <span style={{ fontSize: 'var(--fs-lead)', fontWeight: 600 }}>
                    {p.label}
                  </span>
                  {p.is_active && (
                    <span style={{
                      fontSize: 'var(--fs-micro)', letterSpacing: '0.12em', textTransform: 'uppercase',
                      color: 'var(--shu-ink)', border: '1px solid var(--shu)',
                      borderRadius: 2, padding: '1px 6px',
                    }}>
                      Showing now
                    </span>
                  )}
                  <span style={{ marginLeft: 'auto', fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>
                    {n0(p.leads)} enquiries &middot; {n0(p.bookings)} bookings
                  </span>
                </div>
                <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)', marginTop: 4 }}>
                  {dt(p.period_start)} &ndash; {dt(p.period_end)}
                </div>

                {!isTarget && (
                  <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
                    {/* Clearing keeps the month in the switcher, so it is safe
                        even on the month being shown - the sheet just reads
                        zero until something is uploaded for it. */}
                    <button onClick={() => ask(p.label, 'clear')} style={{ borderColor: 'transparent' }}>
                      <Eraser size={13} />
                      <span>Empty this month</span>
                    </button>
                    {!p.is_active && (
                      <button
                        onClick={() => ask(p.label, 'delete')}
                        style={{ color: 'var(--critical)', borderColor: 'transparent' }}
                      >
                        <Trash2 size={13} />
                        <span>Remove the month</span>
                      </button>
                    )}
                  </div>
                )}
                {p.is_active && !isTarget && (
                  <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)', marginTop: 8 }}>
                    To remove this month entirely, switch to another one first.
                  </div>
                )}

                {isTarget && (
                  <div style={{
                    marginTop: 12, padding: '14px 16px',
                    border: '1px solid var(--critical)',
                    borderRadius: 'var(--radius-sm)',
                    background: 'var(--critical-light)',
                  }}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                      <AlertTriangle size={14} style={{ color: 'var(--critical)', flex: 'none', marginTop: 2 }} />
                      <div style={{ fontSize: 'var(--fs-small)', lineHeight: 1.6 }}>
                        {contents ? (
                          <>
                            This removes <b>{n0(contents.total)} rows</b> from {p.label}
                            {Object.keys(contents.counts || {}).length > 0 && (
                              <> &mdash; {Object.entries(contents.counts)
                                .map(([k, v]) => `${n0(v)} ${k.replace(/_/g, ' ')}`)
                                .join(', ')}</>
                            )}.
                            {contents.hand_entered > 0 && (
                              <div style={{ color: 'var(--critical)', marginTop: 6 }}>
                                {n0(contents.hand_entered)} of these were entered by hand on the
                                dashboard, not loaded from a workbook. Re-uploading will not bring
                                them back.
                              </div>
                            )}
                            <div style={{ marginTop: 6, color: 'var(--ink-muted)' }}>
                              {mode === 'clear'
                                ? `${p.label} stays in the month switcher and reads zero until a workbook is uploaded for it.`
                                : `${p.label} disappears from the switcher. The only way back is to upload its workbook again.`}
                            </div>
                          </>
                        ) : 'Checking what this month holds…'}
                      </div>
                    </div>

                    <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
                      <input
                        value={typed}
                        onChange={e => setTyped(e.target.value)}
                        placeholder={`Type ${p.label} to confirm`}
                        aria-label={`Type ${p.label} to confirm deletion`}
                        style={{ flex: '1 1 180px' }}
                        autoFocus
                      />
                      <button
                        onClick={remove}
                        disabled={!canDelete || busy || !contents}
                        style={canDelete && !busy
                          ? { background: 'var(--critical)', borderColor: 'var(--critical)', color: 'var(--surface)' }
                          : undefined}
                      >
                        {busy
                          ? (mode === 'clear' ? 'Emptying…' : 'Removing…')
                          : (mode === 'clear' ? 'Empty it' : 'Remove permanently')}
                      </button>
                      <button onClick={() => { setTarget(null); setTyped(''); setError(null); }}>
                        Cancel
                      </button>
                    </div>

                    {error && (
                      <div style={{ marginTop: 10, fontSize: 'var(--fs-small)', color: 'var(--critical)' }}>
                        {error}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {!ordered.length && (
            <div style={{ padding: '28px 0', textAlign: 'center', color: 'var(--ink-muted)', fontSize: 'var(--fs-body)' }}>
              No months on record yet.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
