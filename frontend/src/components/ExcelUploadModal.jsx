import React, { useState, useRef, useEffect } from 'react';
import useClosing from './useClosing';
import { X, UploadCloud, FileSpreadsheet, FileText, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import { uploadReportFile, uploadWorkbookInBackground, n0 } from '../api/client';

export default function ExcelUploadModal({ isOpen, onClose, onUploadComplete }) {
  const [file, setFile] = useState(null);
  const [period, setPeriod] = useState('');
  const [uploader, setUploader] = useState('Reporting Agent');
  const [tableType, setTableType] = useState('auto');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [step, setStep] = useState('');
  // How this file should meet the month already in the database, and what
  // slice of time it covers.
  const [mode, setMode] = useState('replace');
  const [covers, setCovers] = useState('month');
  const [coversDate, setCoversDate] = useState('');
  // A week is a span, not a point: the client says which dates it runs from
  // and to, rather than us guessing the week around a single date.
  const [coversDateEnd, setCoversDateEnd] = useState('');
  // What the month being uploaded into currently holds. An upload REPLACES that
  // month rather than adding to it, which is the right behaviour but invisible
  // -- so the modal says it, with the real figures, before anyone commits.
  const [replacing, setReplacing] = useState(null);

  useEffect(() => {
    const label = period.trim();
    if (!label) { setReplacing(null); return undefined; }
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/periods/${encodeURIComponent(label)}/contents`);
        if (cancelled) return;
        setReplacing(res.ok ? await res.json() : { missing: true, label });
      } catch {
        if (!cancelled) setReplacing(null);
      }
    }, 400);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [period]);
  // Counts up only while a request is in flight, and resets for the next one.
  useEffect(() => {
    if (!loading) return undefined;
    setElapsed(0);
    const started = Date.now();
    const id = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(id);
  }, [loading]);

  const fileInputRef = useRef(null);

  const { render, leaving } = useClosing(isOpen);
  if (!render) return null;

  const getFormatBadge = (name) => {
    const ext = (name.split('.').pop() || '').toLowerCase();
    if (['xlsx', 'xlsm', 'xls'].includes(ext)) {
      return { label: 'Excel Workbook', bg: 'var(--s3-light)', color: 'var(--good-text)', icon: FileSpreadsheet };
    }
    if (['csv'].includes(ext)) {
      return { label: 'CSV Spreadsheet', bg: 'var(--s1-light)', color: 'var(--s1)', icon: FileSpreadsheet };
    }
    if (['txt', 'tsv'].includes(ext)) {
      return { label: 'Text / Delimited Report', bg: 'var(--surface-sub)', color: 'var(--ink-2)', icon: FileText };
    }
    return null;
  };

  const validateAndSetFile = (f) => {
    if (f.name.match(/\.xlsx?$|\.xlsm$|\.csv$|\.txt$|\.tsv$/i)) {
      setFile(f);
      setError(null);
    } else {
      setError('Please select a valid report file (.xlsx, .xlsm, .csv, or .txt).');
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files.length) {
      validateAndSetFile(e.target.files[0]);
    }
  };

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    setResult(null);

    setStep('');
    try {
      // Excel goes through the background job: a ~100s ingest cannot survive a
      // 60s gateway, so the request returns at once and we poll. CSV and text
      // are quick and stay on the direct path.
      const isWorkbook = /\.(xlsx|xlsm|xls)$/i.test(file.name);
      const data = isWorkbook
        ? await uploadWorkbookInBackground(file, period, uploader,
            job => setStep(job.step || job.state || ''),
            { mode: effectiveMode, covers, coversDate, coversDateEnd })
        : await uploadReportFile(file, period, uploader, tableType);
      setResult(data);
      onUploadComplete(
        data.mode === 'append'
          ? `${data.filename} added to ${data.period}`
          : `${data.period} replaced from '${data.filename}'`,
        data);
    } catch (err) {
      setError(err.message || 'Ingestion failed');
    } finally {
      setLoading(false);
    }
  };

  // Replacing a whole month with one day's file would delete the rest of the
  // month, so day and week are append-only and the control says so.
  const effectiveMode = covers === 'month' ? mode : 'append';
  const needsDate = covers !== 'month';
  const needsRange = covers === 'week';
  const dateMissing = (needsDate && !coversDate) || (needsRange && !coversDateEnd);
  // Caught here rather than at the server, so the person fixes it while the
  // dates are in front of them.
  const rangeBackwards = needsRange && coversDate && coversDateEnd
                         && coversDateEnd < coversDate;
  const rangeCrossesMonths = needsRange && coversDate && coversDateEnd
                             && !rangeBackwards
                             && coversDate.slice(0, 7) !== coversDateEnd.slice(0, 7);

  const badge = file ? getFormatBadge(file.name) : null;
  const BadgeIcon = badge?.icon || FileSpreadsheet;

  return (
    <div className={`drawer-scrim ${leaving ? 'is-leaving' : ''}`} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}>
      <div className="xp-panel" style={{
        background: 'var(--surface)',
        border: '1px solid var(--border-strong)',
        borderRadius: 'var(--radius-lg)',
        maxWidth: '540px',
        width: '100%',
        maxHeight: '90vh',
        boxShadow: 'var(--shadow-lg)',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}>
        <div style={{
          padding: '18px 24px',
          borderBottom: '1px solid var(--grid)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <div>
            <h2 style={{ fontSize: 'var(--fs-head)' }}>Ingest DSR Report</h2>
            <p style={{ margin: '2px 0 0', fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>
              Loads bookings, stock, enquiries and targets. Choose below whether it
              replaces the month or is added to it.
            </p>
          </div>
          <button onClick={onClose} style={{ padding: '6px', borderRadius: '50%' }}>
            <X size={18} />
          </button>
        </div>

        <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px', overflowY: 'auto' }}>
          {/* Dropzone */}
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            style={{
              border: `2px dashed ${dragOver ? 'var(--s1)' : 'var(--axis)'}`,
              borderRadius: 'var(--radius-md)',
              padding: '28px 16px',
              textAlign: 'center',
              background: dragOver ? 'var(--s1-light)' : 'var(--surface-sub)',
              cursor: 'pointer',
              transition: 'border-color var(--t-fast) var(--ease-out), background var(--t-fast) var(--ease-out)',
            }}
          >
            <BadgeIcon size={36} style={{ color: file ? 'var(--s1)' : 'var(--ink-muted)', marginBottom: '8px' }} />
            <div style={{ fontWeight: '600', fontSize: 'var(--fs-body)', marginBottom: '4px' }}>
              {file ? file.name : 'Drop report file here, or browse'}
            </div>
            <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>
              {file
                ? `${(file.size / 1024).toFixed(1)} KB`
                : 'Supports Excel (.xlsx, .xlsm), CSV (.csv), and Text (.txt, .tsv)'}
            </div>

            {badge && (
              <div style={{ marginTop: '10px' }}>
                <span style={{
                  display: 'inline-block',
                  padding: '3px 10px',
                  borderRadius: '999px',
                  fontSize: 'var(--fs-small)',
                  fontWeight: '700',
                  background: badge.bg,
                  color: badge.color,
                }}>
                  {badge.label}
                </span>
              </div>
            )}

            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.xlsm,.xls,.csv,.txt,.tsv"
              onChange={handleFileChange}
              style={{ display: 'none' }}
            />
          </div>

          {/* How this file meets the month already in the database. */}
          <div>
            <div style={{
              fontSize: 'var(--fs-small)', fontWeight: 500, color: 'var(--ink-2)', marginBottom: 6,
            }}>How to apply it</div>
            <div style={{ display: 'flex', gap: 8 }}>
              {[
                { key: 'replace', title: 'Replace the month',
                  note: 'Clears what is there and loads this file in its place' },
                { key: 'append', title: 'Add to the month',
                  note: 'Keeps what is there and adds these rows' },
              ].map(o => {
                const on = effectiveMode === o.key;
                const locked = covers !== 'month' && o.key === 'replace';
                return (
                  <button
                    key={o.key}
                    type="button"
                    onClick={() => !locked && setMode(o.key)}
                    disabled={locked}
                    title={locked ? 'A day or a week can only be added to its month' : o.note}
                    style={{
                      flex: 1, flexDirection: 'column', alignItems: 'flex-start',
                      gap: 3, padding: '10px 12px', textAlign: 'left',
                      background: on ? 'var(--s1-light)' : 'var(--surface-sub)',
                      borderColor: on ? 'var(--s1)' : 'var(--border)',
                      opacity: locked ? 0.45 : 1,
                      cursor: locked ? 'not-allowed' : 'pointer',
                    }}
                  >
                    <b style={{ fontSize: 'var(--fs-small)', color: on ? 'var(--s1)' : 'var(--ink)' }}>
                      {o.title}
                    </b>
                    <span style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)', lineHeight: 1.4 }}>
                      {o.note}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* What slice of time the file covers. dim_period is monthly, so a
              day or a week is filed under the month it falls in - the date
              chooses that month, and appending is the only safe pairing. */}
          <div>
            <div style={{
              fontSize: 'var(--fs-small)', fontWeight: 500, color: 'var(--ink-2)', marginBottom: 6,
            }}>This file covers</div>
            <div style={{ display: 'flex', gap: 6, marginBottom: needsDate ? 10 : 0 }}>
              {['day', 'week', 'month'].map(c => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setCovers(c)}
                  aria-pressed={covers === c}
                  style={{
                    flex: 1, textTransform: 'capitalize', padding: '7px 10px',
                    fontSize: 'var(--fs-small)',
                    background: covers === c ? 'var(--s1-light)' : 'var(--surface-sub)',
                    borderColor: covers === c ? 'var(--s1)' : 'var(--border)',
                    color: covers === c ? 'var(--s1)' : 'var(--ink-2)',
                    fontWeight: covers === c ? 700 : 500,
                  }}
                >
                  {c}
                </button>
              ))}
            </div>
            {covers === 'day' && (
              <label className="field" style={{ margin: 0 }}>
                <span>Date this file covers <em>— it is filed under that month</em></span>
                <input type="date" value={coversDate}
                       onChange={e => setCoversDate(e.target.value)} />
              </label>
            )}

            {needsRange && (
              <>
                <div className="row-2">
                  <label className="field" style={{ margin: 0 }}>
                    <span>Week from</span>
                    <input
                      type="date"
                      value={coversDate}
                      onChange={e => {
                        const from = e.target.value;
                        setCoversDate(from);
                        // Offer the obvious seven-day week, still editable —
                        // a dealership week is not always Monday to Sunday.
                        if (from && !coversDateEnd) {
                          const d = new Date(`${from}T00:00:00Z`);
                          d.setUTCDate(d.getUTCDate() + 6);
                          setCoversDateEnd(d.toISOString().slice(0, 10));
                        }
                      }}
                    />
                  </label>
                  <label className="field" style={{ margin: 0 }}>
                    <span>Week to</span>
                    <input type="date" value={coversDateEnd} min={coversDate || undefined}
                           onChange={e => setCoversDateEnd(e.target.value)} />
                  </label>
                </div>
                {rangeBackwards && (
                  <div style={{ fontSize: 'var(--fs-small)', color: 'var(--critical)', marginTop: 6 }}>
                    The end date is before the start date.
                  </div>
                )}
                {rangeCrossesMonths && (
                  <div style={{ fontSize: 'var(--fs-small)', color: 'var(--warning)', marginTop: 6 }}>
                    This week spans two months. It will be filed under{' '}
                    <b>{new Date(`${coversDate}T00:00:00Z`).toLocaleDateString('en-IN',
                        { month: 'long', year: 'numeric', timeZone: 'UTC' })}</b>,
                    the month it starts in.
                  </div>
                )}
              </>
            )}
          </div>

          <div className="row-2">
            <label className="field" style={{ margin: 0 }}>
              <span>Target Data Type</span>
              <select value={tableType} onChange={e => setTableType(e.target.value)}>
                <option value="auto">Auto-Detect (Recommended)</option>
                <option value="booking">Bookings / Order Book</option>
                <option value="lead">Leads / Enquiries</option>
                <option value="vehicle">Vehicles / Stock Inventory</option>
              </select>
            </label>
            <label className="field" style={{ margin: 0 }}>
              <span>Reporting Period</span>
              <input
                value={period}
                onChange={e => setPeriod(e.target.value)}
                placeholder="e.g. AUG2026"
              />
            </label>
          </div>

          {replacing && (
            <div style={{
              border: '1px solid ' + (replacing.missing ? 'var(--grid)' : 'var(--warning)'),
              background: replacing.missing ? 'var(--surface-sub)' : 'var(--critical-light)',
              borderRadius: 'var(--radius-sm)',
              padding: '11px 14px',
              fontSize: 'var(--fs-small)',
              lineHeight: 1.6,
            }}>
              {replacing.missing ? (
                <>
                  <b>{replacing.label}</b> is a new month. Nothing will be replaced.
                </>
              ) : (
                effectiveMode === 'append' ? (
                <>
                  This <b>adds to</b> <b>{replacing.label}</b>, which currently holds{' '}
                  {n0(replacing.total)} rows. Nothing existing is removed. Rows identical
                  to ones already there are skipped, so re-sending the same file is safe.
                </>
              ) : (
                <>
                  This <b>replaces</b> what workbooks loaded into <b>{replacing.label}</b>
                  {(replacing.replaces_total ?? replacing.total) > 0
                    ? <> &mdash; {n0(replacing.replaces_total ?? replacing.total)} rows
                        {(replacing.replaces || replacing.counts)
                          && Object.keys(replacing.replaces || replacing.counts).length > 0 && (
                          <> ({Object.entries(replacing.replaces || replacing.counts)
                              .map(([k, v]) => `${n0(v)} ${k.replace(/_/g, ' ')}`)
                              .join(', ')})</>
                        )}. It is not added alongside.</>
                    : <>, which holds nothing from a workbook yet.</>}
                  {replacing.hand_entered > 0 && (
                    <div style={{ marginTop: 6 }}>
                      {n0(replacing.hand_entered)} {replacing.hand_entered === 1 ? 'row' : 'rows'} entered
                      by hand on the dashboard {replacing.hand_entered === 1 ? 'is' : 'are'} kept: a
                      replace only removes what a workbook loaded.
                    </div>
                  )}
                </>
              ))}
            </div>
          )}

          <label className="field" style={{ margin: 0 }}>
            <span>Uploaded By</span>
            <input
              value={uploader}
              onChange={e => setUploader(e.target.value)}
            />
          </label>

          {loading && (
            <div style={{
              background: 'var(--surface-sub)',
              borderRadius: '8px',
              padding: '14px',
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              fontSize: 'var(--fs-body)',
            }}>
              <Loader2 size={20} className="animate-spin" style={{ color: 'var(--s1)' }} />
              <div>
                <div style={{ fontWeight: '600' }}>
                  Ingesting the workbook&hellip;{' '}
                  <span style={{ fontVariantNumeric: 'tabular-nums' }}>{elapsed}s</span>
                </div>
                {/* A DSR workbook is roughly 2,600 rows written to a database a
                    round trip away, and it genuinely takes about a minute and a
                    half. Without saying so, a spinner at 60 seconds is
                    indistinguishable from a hung one, and people close the tab
                    on an ingest that was going to succeed. */}
                <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>
                  {step ? step.charAt(0).toUpperCase() + step.slice(1) + ' — ' : ''}
                  {elapsed < 120
                    ? 'this usually takes about two minutes. Leave this open.'
                    : 'taking longer than usual, still working. Leave this open.'}
                </div>
              </div>
            </div>
          )}

          {error && (
            <div style={{
              background: 'var(--critical-light)',
              border: '1px solid var(--critical)',
              borderRadius: '8px',
              padding: '12px 14px',
              color: 'var(--critical)',
              fontSize: 'var(--fs-small)',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
            }}>
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          )}

          {result && (
            <div style={{
              background: 'var(--s3-light)',
              border: '1px solid var(--s3)',
              borderRadius: '8px',
              padding: '14px',
              fontSize: 'var(--fs-small)',
            }}>
              <div style={{ fontWeight: '700', color: 'var(--good-text)', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                <CheckCircle2 size={16} />
                <span>Successfully Ingested {result.filename} ({result.period})!</span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: '8px' }}>
                {Object.entries(result.counts || {}).map(([tbl, cnt]) => (
                  <div key={tbl} style={{ 
                    background: 'var(--surface)', padding: '6px 10px', borderRadius: '4px', 
                    border: '1px solid var(--border)', wordBreak: 'break-word', lineHeight: '1.4'
                  }}>
                    <b style={{ display: 'block', fontSize: 'var(--fs-body)', marginBottom: '2px' }}>{cnt}</b> 
                    <span style={{ color: 'var(--ink-muted)', fontSize: 'var(--fs-small)', textTransform: 'uppercase' }}>{tbl}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div style={{
          padding: '16px 24px',
          borderTop: '1px solid var(--grid)',
          display: 'flex',
          justifyContent: 'flex-end',
          gap: '10px',
          background: 'var(--surface-sub)',
        }}>
          <button onClick={onClose} disabled={loading}>
            Close
          </button>
          <button
            className="primary"
            onClick={handleUpload}
            disabled={!file || loading || dateMissing || rangeBackwards}
            title={dateMissing ? `Pick the ${covers} this file covers` : undefined}
            style={{ background: 'var(--s3)', borderColor: 'var(--s3)' }}
          >
            <UploadCloud size={15} />
            <span>{loading ? 'Ingesting...' : 'Ingest into Dashboard'}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
