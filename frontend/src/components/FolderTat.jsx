/**
 * How long paperwork sits before it reaches accounts.
 *
 * v_folder_tat has been in the schema since the beginning and drawn nowhere.
 * It is the one genuinely back-office measure the workbook carries: when a
 * folder was lined up, when accounts received it, and the days in between. A
 * car can be sold and delivered while its file sits on a desk, and nothing
 * else on the sheet would say so.
 *
 * The bad row is shown rather than hidden. One folder reports reaching accounts
 * ten days before it was lined up, which is the workbook holding those two
 * dates the wrong way round - averaging it in turned a real 0.2 days into
 * -0.1, paperwork arriving before it exists.
 *
 * Shown was not the same as findable. The warning said the offending files
 * were listed below while the table stayed in date order and cut off at ten,
 * which put September's one impossible file at row seventeen of thirty-five,
 * behind a "show all" button - the banner pointed somewhere the table did not
 * go. Flagged files now sort to the top, and the two dates that disagree are
 * marked rather than only the days between them, because those two cells are
 * what somebody has to go and correct in the workbook.
 */

import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { api, n0 } from '../api/client';

function Stat({ label, value, tone }) {
  return (
    <div>
      <div style={{ fontSize: 'var(--fs-micro)', textTransform: 'uppercase',
                    letterSpacing: '0.08em', color: 'var(--ink-muted)' }}>
        {label}
      </div>
      <div style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.03em',
                    marginTop: 4,
                    color: tone === 'bad' ? 'var(--critical)' : 'var(--ink)' }}>
        {value}
      </div>
    </div>
  );
}

export default function FolderTat() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let dead = false;
    api('/api/folder-tat')
      .then(r => { if (!dead) setData(r); })
      .catch(e => { if (!dead) setError(e.message); });
    return () => { dead = true; };
  }, []);

  const rows = data?.rows || [];

  const isBroken = r => r.days != null && r.days < 0;
  /* Flagged first, everything else left in the date order the API sent. */
  const ordered = useMemo(() => (
    rows.some(isBroken)
      ? [...rows.filter(isBroken), ...rows.filter(r => !isBroken(r))]
      : rows
  ), [rows]);
  const shown = showAll ? ordered : ordered.slice(0, 10);

  return (
    <div className="panel">
      <div className="panel-header" style={{ marginBottom: 14 }}>
        <h2>Folder turnaround</h2>
        <span style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)' }}>
          Days from a file being lined up to accounts receiving it
        </span>
      </div>

      {error ? (
        <div style={{ display: 'flex', gap: 8, fontSize: 'var(--fs-body)',
                      color: 'var(--critical)' }}>
          <AlertTriangle size={14} style={{ flex: 'none', marginTop: 2 }} />
          <span>{error}</span>
        </div>
      ) : !data ? (
        <div style={{ fontSize: 'var(--fs-body)', color: 'var(--ink-muted)' }}>Reading the files…</div>
      ) : !rows.length ? (
        <div style={{ fontSize: 'var(--fs-body)', color: 'var(--ink-muted)' }}>
          No registrations have been filed yet.
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 34, flexWrap: 'wrap',
                        marginBottom: 18 }}>
            <Stat label="Files" value={n0(data.total)} />
            <Stat label="Average days" value={data.avg_days ?? '—'} />
            <Stat label="Same day" value={n0(data.same_day)} />
            <Stat label="Over 3 days" value={n0(data.over_3_days)}
                  tone={data.over_3_days > 0 ? 'bad' : undefined} />
          </div>

          {data.impossible > 0 && (
            <div style={{
              display: 'flex', alignItems: 'flex-start', gap: 8,
              margin: '0 0 14px', padding: '9px 12px',
              border: '1px solid var(--warning)', background: 'var(--critical-light)',
              fontSize: 'var(--fs-small)', lineHeight: 1.5, color: 'var(--warning)',
            }}>
              <AlertTriangle size={14} style={{ flex: 'none', marginTop: 1 }} />
              <span>
                {n0(data.impossible)} file{data.impossible === 1 ? '' : 's'} reached
                accounts <b>before</b> being lined up, so the workbook holds those
                two dates the wrong way round.{' '}
                {data.impossible === 1 ? 'It is' : 'They are'} listed first, with
                the disagreeing dates marked, and left out of the average.
              </span>
            </div>
          )}

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>Consultant</th>
                  <th>Lined up</th>
                  <th>To accounts</th>
                  <th className="num">Days</th>
                </tr>
              </thead>
              <tbody>
                {shown.map(r => {
                  const bad = isBroken(r);
                  /* The days figure is the symptom; these two cells are the
                     fault, and the pair of them is what gets corrected. */
                  const wrong = bad
                    ? { color: 'var(--critical)', fontWeight: 600 }
                    : undefined;
                  return (
                    <tr key={r.id}>
                      <td style={{ whiteSpace: 'normal' }}>{r.customer || '—'}</td>
                      <td>{r.consultant || '—'}</td>
                      <td style={wrong}>{r.lined_up || '—'}</td>
                      <td style={wrong}>{r.to_accounts || '—'}</td>
                      <td className="num"
                          style={{ color: bad ? 'var(--critical)' : undefined,
                                   fontWeight: bad ? 600 : undefined }}>
                        {r.days ?? '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {rows.length > 10 && (
            <button className="rail-quiet" onClick={() => setShowAll(s => !s)}
                    style={{ marginTop: 12, padding: '5px 12px', fontSize: 'var(--fs-small)' }}>
              {showAll ? 'Show recent only' : `Show all ${n0(rows.length)} files`}
            </button>
          )}
        </>
      )}
    </div>
  );
}
