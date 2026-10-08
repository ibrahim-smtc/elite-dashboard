/**
 * The export sheet.
 *
 * The dashboard could always be loaded FROM a workbook and never written back
 * INTO one, so anyone who wanted the order book in Excel took a screenshot of a
 * table. This is the other direction, laid out as two doors:
 *
 *   A  where the file goes      format, and which destination receives it
 *   B  what goes into it        which tables, which layout, which months
 *
 * They are independent on purpose. A manager who wants "the order book, in
 * Excel, on this machine" never has to read the half about sheet layout, and
 * the counts under B are read off the database before anything is built, so the
 * green line at the bottom of B is a measurement rather than a promise.
 *
 * Nothing here writes. Export is a read, so it can be repeated freely and there
 * is no confirmation step to sit through.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import useClosing from './useClosing';
import {
  X, Download, FileSpreadsheet, FileText, HardDrive, Cloud, CheckCircle2,
  AlertCircle, Loader2, Info, Database, Sparkles, Lock, RefreshCw,
} from 'lucide-react';
import { fetchExportManifest, runExport, n0 } from '../api/client';

// Destination icons, keyed the way the server keys the destinations.
const DEST_ICON = {
  local: HardDrive,
  google_drive: Cloud,
  dropbox: Cloud,
  onedrive: Cloud,
};

const FORMAT_ICON = { xlsx: FileSpreadsheet, csv: FileText };

export default function ExportDataModal({ isOpen, onClose, onExported }) {
  const [manifest, setManifest] = useState(null);
  const [loadingManifest, setLoadingManifest] = useState(false);

  const [format, setFormat] = useState('xlsx');
  const [destination, setDestination] = useState('local');
  const [scope, setScope] = useState('current');
  const [template, setTemplate] = useState('manager');
  const [groups, setGroups] = useState([]);
  const [naming, setNaming] = useState('auto');

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  // Bumped by Retry, to re-run the manifest effect without reopening the modal.
  const [reloadKey, setReloadKey] = useState(0);

  // The manifest is re-read when the scope changes, because the counts it
  // carries are the counts FOR that scope - "every month on record" is a
  // different number of bookings, and the green line would otherwise report the
  // month's figure for a file containing the year's.
  useEffect(() => {
    if (!isOpen) return undefined;
    let cancelled = false;
    setLoadingManifest(true);
    setError(null);
    fetchExportManifest(scope)
      .then(data => {
        if (cancelled) return;
        setManifest(data);
        // Everything is on by default: the common case is "give me the month",
        // and turning one thing off is less work than turning four things on.
        setGroups(prev => (prev.length ? prev : (data.groups || []).map(g => g.key)));
      })
      .catch(err => {
        if (cancelled) return;
        // Keep no stale manifest behind a failure: a half-drawn picker offering
        // sources it can no longer count is worse than an honest empty state.
        setManifest(null);
        setError(err.message || 'Could not read what is available to export.');
      })
      .finally(() => { if (!cancelled) setLoadingManifest(false); });
    return () => { cancelled = true; };
  }, [isOpen, scope, reloadKey]);

  // Closing and reopening should not resurrect the last run's success banner.
  useEffect(() => {
    if (!isOpen) { setResult(null); setError(null); }
  }, [isOpen]);

  // Esc closes, which every other overlay on the sheet already does.
  useEffect(() => {
    if (!isOpen) return undefined;
    const onKey = e => { if (e.key === 'Escape' && !busy) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, busy, onClose]);

  const toggleGroup = useCallback(key => {
    setGroups(prev => (prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]));
    setResult(null);
  }, []);

  const chosen = useMemo(
    () => (manifest?.groups || []).filter(g => groups.includes(g.key)),
    [manifest, groups],
  );

  // What the current selection will actually produce. Sheets are counted from
  // the datasets inside the chosen groups, not from the number of groups.
  const tally = useMemo(() => {
    const sheets = chosen.reduce((n, g) => n + (g.datasets?.length || 0), 0);
    const rows = chosen.reduce((n, g) => n + (g.rows || 0), 0);
    return { sheets, rows };
  }, [chosen]);

  // What the file will be called. 'auto' sends nothing and lets the server
  // stamp the month and the minute, which is what makes two exports of the same
  // month distinguishable; the other two are for people filing over the top of
  // last month's copy on purpose.
  const periodLabel = manifest?.period?.label;
  const filename = useMemo(() => {
    if (naming === 'month' && periodLabel) return `DSR-${periodLabel}`;
    if (naming === 'short') return 'dsr-export';
    return undefined;
  }, [naming, periodLabel]);

  const destinations = manifest?.destinations || [];
  const activeDest = destinations.find(d => d.key === destination);
  const canRun = !busy && tally.sheets > 0 && (!activeDest || activeDest.status === 'ready');

  const handleExport = async () => {
    if (!canRun) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const out = await runExport({ format, scope, template, groups, destination, filename });
      setResult(out);
      if (onExported) {
        onExported(
          out.destination === 'google_drive'
            ? `${out.filename} sent to Google Drive · ${n0(out.rows)} rows`
            : `${out.filename} downloaded · ${n0(out.rows)} rows`,
          out,
        );
      }
    } catch (err) {
      setError(err.message || 'The export could not be built.');
    } finally {
      setBusy(false);
    }
  };

  const { render, leaving } = useClosing(isOpen);
  if (!render) return null;

  const period = manifest?.period?.label || '…';
  const formats = manifest?.formats || [];
  const templates = manifest?.templates || [];

  return (
    <div
      className={`drawer-scrim ${leaving ? 'is-leaving' : ''}`}
      style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}
      onMouseDown={e => { if (e.target === e.currentTarget && !busy) onClose(); }}
    >
      <div className="xp-modal" role="dialog" aria-modal="true" aria-label="Export reports and data">
        <div className="xp-head">
          <span className="xp-head-icon"><Download size={17} /></span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h2>
              Export Reports &amp; Data
              <span className="xp-ver">v1.0 Exporter</span>
            </h2>
            <p>
              Choose where the file should go, then what goes into it. Built from the live
              record, so an export and this sheet can never disagree.
            </p>
          </div>
          <button onClick={onClose} disabled={busy} style={{ padding: '6px', borderRadius: '50%' }}
                  aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <div className={`xp-body${manifest ? '' : ' xp-body-bare'}`}>
          {/* Until the manifest lands there is nothing real to choose between,
              and drawing the two cards empty produces a picker with no formats,
              no destinations and no sources - which reads as a broken screen
              rather than as a server that has not answered yet. */}
          {!manifest && (
            <div className="xp-standin">
              {loadingManifest ? (
                <>
                  <Loader2 size={20} style={{ animation: 'spin 0.9s linear infinite',
                                              color: 'var(--s1)' }} />
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 'var(--fs-body)' }}>
                      Reading what is available to export…
                    </div>
                    <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)', marginTop: 3 }}>
                      Counting the rows behind each source.
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <AlertCircle size={20} style={{ color: 'var(--critical)' }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 'var(--fs-body)', color: 'var(--critical)' }}>
                      The export picker could not load
                    </div>
                    <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-2)', marginTop: 4,
                                  lineHeight: 1.55 }}>
                      {error || 'The server did not answer.'}
                    </div>
                  </div>
                  <button onClick={() => { setError(null); setReloadKey(k => k + 1); }}
                          style={{ flex: 'none' }}>
                    <RefreshCw size={14} />
                    <span>Retry</span>
                  </button>
                </>
              )}
            </div>
          )}

          {manifest && <>
          {/* ---------------------------------------------------------- */}
          {/* Option A — where the file goes                              */}
          {/* ---------------------------------------------------------- */}
          <section className="xp-opt xp-opt-a">
            <span className="xp-tag">Recommended</span>

            <div className="xp-opt-title">
              <FileSpreadsheet size={16} />
              <span>Option A: File &amp; Cloud Destination</span>
            </div>
            <p className="xp-opt-sub">
              Download a formatted file to this computer, or push it to connected cloud
              storage (XLSX, CSV, ZIP).
            </p>

            <div>
              <div className="xp-legend">Send the file to</div>
              <div className="xp-chips">
                {destinations.map(d => {
                  const Icon = DEST_ICON[d.key] || Cloud;
                  const off = d.status !== 'ready';
                  return (
                    <button
                      key={d.key}
                      type="button"
                      className={`xp-chip${destination === d.key ? ' is-on' : ''}${off ? ' is-off' : ''}`}
                      onClick={() => { if (!off) { setDestination(d.key); setResult(null); } }}
                      disabled={off}
                      title={off
                        ? `${d.label} is not connected on this server${d.requires ? ` — set ${d.requires}` : ''}`
                        : d.note}
                    >
                      {off ? <Lock size={12} /> : <Icon size={13} />}
                      <span>{d.label}</span>
                    </button>
                  );
                })}
              </div>
              {activeDest?.note && (
                <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)', marginTop: 6 }}>
                  {activeDest.note}
                </div>
              )}
            </div>

            {/* The dropzone's mirror image: the same well, the same dashes,
                running the other way. */}
            <div className="xp-well">
              <Download size={26} style={{ color: 'var(--s1)' }} />
              <div style={{ fontWeight: 600, fontSize: 'var(--fs-body)' }}>Choose a file format</div>
              <div className="xp-fmts">
                {formats.map(f => {
                  const Icon = FORMAT_ICON[f.key] || FileText;
                  return (
                    <button
                      key={f.key}
                      type="button"
                      className={`xp-fmt${format === f.key ? ' is-on' : ''}`}
                      onClick={() => { setFormat(f.key); setResult(null); }}
                      title={f.note}
                    >
                      <Icon size={15} style={{ color: format === f.key ? 'var(--s1)' : 'var(--ink-muted)' }} />
                      <b>{f.label}</b>
                      <span>{f.ext}</span>
                    </button>
                  );
                })}
              </div>
              <div className="xp-well-note">
                {format === 'xlsx'
                  ? 'One workbook, one sheet per table, with filters and frozen headers.'
                  : 'One CSV per table — zipped together when more than one is selected.'}
              </div>
            </div>

            <label className="xp-check">
              <input
                type="checkbox"
                checked={template === 'manager'}
                onChange={e => { setTemplate(e.target.checked ? 'manager' : 'raw'); setResult(null); }}
              />
              <span>
                Open with a summary cover sheet
                <span className="xp-count"> — month, scope and row counts up front</span>
              </span>
            </label>

            <label className="xp-field">
              <span>File name</span>
              <select
                value={naming}
                onChange={e => { setNaming(e.target.value); setResult(null); }}
              >
                <option value="auto">Auto — month and timestamp</option>
                <option value="month">DSR-{period} — overwrites last copy</option>
                <option value="short">dsr-export — plain</option>
              </select>
            </label>
          </section>

          {/* ---------------------------------------------------------- */}
          {/* Option B — what goes into it                                */}
          {/* ---------------------------------------------------------- */}
          <section className="xp-opt xp-opt-b">
            <span className="xp-tag">Live data sync</span>

            <div className="xp-opt-title">
              <Database size={16} />
              <span>Option B: Build from Live CRM</span>
            </div>
            <p className="xp-opt-sub">
              Compiles the dashboard's own tables — bookings, enquiries, stock and
              scorecards — straight out of the database as you export.
            </p>

            <div>
              <div className="xp-legend">Source selector</div>
              <div className="xp-rows">
                {(manifest?.groups || []).map(g => (
                  <label key={g.key} className="xp-check">
                    <input
                      type="checkbox"
                      checked={groups.includes(g.key)}
                      onChange={() => toggleGroup(g.key)}
                    />
                    <span>
                      {g.label}
                      <span className="xp-count"> — {n0(g.rows)} rows</span>
                    </span>
                  </label>
                ))}
                {loadingManifest && !manifest && (
                  <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)', padding: '6px 0' }}>
                    Reading what is available…
                  </div>
                )}
              </div>
            </div>

            <label className="xp-field">
              <span>Sheet layout</span>
              <select
                value={template}
                onChange={e => { setTemplate(e.target.value); setResult(null); }}
              >
                {templates.map(t => (
                  <option key={t.key} value={t.key}>{t.label}</option>
                ))}
              </select>
            </label>

            <label className="xp-field">
              <span>Reporting scope</span>
              <select value={scope} onChange={e => { setScope(e.target.value); setResult(null); }}>
                <option value="current">{period} · active month only</option>
                <option value="all">Every month on record</option>
              </select>
            </label>

            <div className={`xp-verdict${tally.sheets ? '' : ' is-empty'}`}>
              {tally.sheets ? <CheckCircle2 size={14} style={{ flex: 'none', marginTop: 1 }} />
                            : <AlertCircle size={14} style={{ flex: 'none', marginTop: 1 }} />}
              <span>
                {tally.sheets ? (
                  <>
                    Generates <b>{tally.sheets} {format === 'xlsx' ? 'sheets' : 'CSV files'}</b>
                    {' '}· <b>{n0(tally.rows)} rows</b> ready to
                    {destination === 'local' ? ' download' : ' send'}
                    {manifest?.source === 'snapshot' && ' (from the offline snapshot)'}.
                  </>
                ) : (
                  <>Nothing selected — tick at least one source above.</>
                )}
              </span>
            </div>
          </section>
          </>}

          {/* Only a failure of the export ITSELF belongs here. A manifest that
              never arrived is reported by the stand-in above instead, which has
              the Retry. */}
          {error && manifest && (
            <div className="xp-msg xp-msg-bad">
              <AlertCircle size={15} style={{ flex: 'none', marginTop: 1 }} />
              <span>{error}</span>
            </div>
          )}

          {result && (
            <div className="xp-msg xp-msg-good">
              <CheckCircle2 size={15} style={{ flex: 'none', marginTop: 1 }} />
              <span>
                <b>{result.filename}</b> — {n0(result.rows)} rows across {result.sheets}{' '}
                {format === 'xlsx' ? 'sheets' : 'files'}
                {result.destination === 'google_drive' ? ' uploaded to Google Drive' : ' downloaded'}.
                {result.drive?.link && (
                  <> <a href={result.drive.link} target="_blank" rel="noreferrer"
                        style={{ color: 'var(--s1)' }}>Open in Drive</a></>
                )}
              </span>
            </div>
          )}
        </div>

        <div className="xp-foot">
          <div className="xp-foot-note">
            <Info size={13} />
            <span>Exports are read-only — nothing on the dashboard changes.</span>
          </div>
          <div className="xp-foot-actions">
            <button onClick={onClose} disabled={busy}>Cancel</button>
            <button className="xp-go" onClick={handleExport} disabled={!canRun}>
              {busy
                ? <Loader2 size={15} style={{ animation: 'spin 0.9s linear infinite' }} />
                : <Sparkles size={15} />}
              <span>
                {busy
                  ? 'Building…'
                  : destination === 'local'
                    ? `Generate & Download ${format === 'xlsx' ? 'Workbook' : 'CSV'}`
                    : `Generate & Send to ${activeDest?.label || 'Cloud'}`}
              </span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
