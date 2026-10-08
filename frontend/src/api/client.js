/**
 * API client for Volkswagen Elite Motors CRM Dashboard.
 * Connects to FastAPI backend and Supabase cloud database.
 */

export async function api(path) {
  const res = await fetch(path);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function sendJson(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data && data.detail;
    const msg = Array.isArray(detail)
      ? detail.map(d => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("\n")
      : (detail || `${res.status} ${res.statusText}`);
    throw new Error(msg);
  }
  return data;
}

/**
 * `onProgress(done, total)` fires as each call lands. The whole payload takes
 * the better part of five seconds against a database a round trip away, so the
 * loading screen can say how far along it is instead of spinning blindly.
 */
export const DASHBOARD_CALLS = 16;

/**
 * One request for the whole dashboard.
 *
 * Profiling put every round trip to this database at ~370 ms and showed the SQL
 * itself is free, so sixteen endpoints cost ~5 s of almost pure waiting.
 * Postgres builds the same payload as JSON in a single statement. The sixteen
 * routes still exist and this falls back to them, so a failure here is slow
 * rather than fatal.
 */
async function fetchBundled(onProgress) {
  const res = await fetch("/api/dashboard");
  if (!res.ok) throw new Error(`bundle unavailable (${res.status})`);
  const d = await res.json();
  if (onProgress) onProgress(DASHBOARD_CALLS);
  // A month with no targets on its scorecard has none: these used to fall back
  // to August's (84 / 66 / 450 / 300) and show them as any month's.
  const stage = name => (d.funnel?.stages || []).find(s => s.stage === name)?.target;
  return {
    // FIX (2026-10-08): each target fell back to August 2026's figure (84
    // bookings, 66 retails, 450 enquiries, 300 test drives) when the month had
    // none, so a month with no targets loaded showed August's as if they were
    // its own. A missing target is now null, and the panels say "no target".
    kpi: {
      ...d.kpi,
      booking_target: d.kpi?.booking_target ?? stage("Bookings") ?? null,
      retail_target: d.kpi?.retail_target ?? stage("Retails") ?? null,
      leads_target: d.kpi?.leads_target ?? stage("Enquiries") ?? null,
      td_target: d.kpi?.td_target ?? stage("Test drives") ?? null,
    },
    trends: d.trends || {},
    funnel: d.funnel || {},
    board: d.board || [],
    sources: d.sources || [],
    models: d.models || [],
    ageing: d.ageing || [],
    backorders: d.backorders || [],
    periods: d.periods || [],
    options: d.options || {},
    // FIX (2026-10-08): was hard-coded to [], so "Recently Recorded" never
    // showed anything; the bundle now carries the feed (app/main.py).
    activity: d.activity || [],
    orderbook: d.orderbook || [],
    scorecards: d.scorecards || [],
    commitments: d.commitments || [],
    attachments: d.attachments || null,
    dataQuality: d.dataQuality || [],
    isLive: true,
  };
}

export async function fetchDashboardData(onProgress) {
  try {
    return await fetchBundled(onProgress);
  } catch (err) {
    console.warn("Bundled dashboard unavailable, falling back to per-endpoint:", err.message);
  }
  let done = 0;
  const step = promise => {
    promise.then(
      () => onProgress && onProgress(++done),
      () => onProgress && onProgress(++done),
    );
    return promise;
  };
  try {
    const [
      kpi, trends, funnel, board, sources, models, ageing, backorders,
      periods, options, activity, orderbook,
      scorecards, commitments, attachments, dataQuality
    ] = await Promise.all([
      step(api("/api/kpi")),
      step(api("/api/kpi/trends")),
      step(api("/api/funnel")),
      step(api("/api/leaderboard")),
      step(api("/api/leads/sourcewise")),
      step(api("/api/models/position")),
      step(api("/api/stock/ageing")),
      step(api("/api/backorders")),
      step(api("/api/periods")),
      step(api("/api/entry-options")),
      step(api("/api/recent-activity?limit=15")),
      // The booking trend plots one point per day, so it needs the whole month,
      // not the first page.
      step(api("/api/bookings?limit=1000")),
      step(api("/api/scorecards")),
      step(api("/api/commitments")),
      step(api("/api/attachments")),
      step(api("/api/data-quality")),
    ]);

    // Enrich KPI with targets from funnel stages if not directly set
    const targetsByStage = {};
    (funnel?.stages || []).forEach(s => {
      if (s.stage && s.target != null) targetsByStage[s.stage] = s.target;
    });

    // FIX (2026-10-08): same as the bundled path - no August targets standing
    // in for a month that has none.
    const enrichedKpi = {
      ...kpi,
      booking_target: kpi.booking_target ?? targetsByStage["Bookings"] ?? null,
      retail_target: kpi.retail_target ?? targetsByStage["Retails"] ?? null,
      leads_target: kpi.leads_target ?? targetsByStage["Enquiries"] ?? null,
      td_target: kpi.td_target ?? targetsByStage["Test drives"] ?? null,
    };

    return {
      kpi: enrichedKpi, trends, funnel, board, sources, models, ageing, backorders,
      periods, options, activity, orderbook,
      scorecards, commitments, attachments, dataQuality,
      isLive: true,
    };
  } catch (err) {
    console.warn("Live API fetch error, checking snapshot fallback:", err);
    // Offline snapshot fallback
    const snap = await fetch("/snapshot_data.json").then(r => r.json()).catch(() => null);
    if (!snap) throw err;
    return {
      kpi: {
        bookings: snap.funnel?.bookings || 42,
        booking_target: snap.targets?.booking_target || 84,
        enquiries: snap.funnel?.enquiries || 367,
        leads_target: snap.targets?.leads_target || 450,
        retails: snap.funnel?.retails || 18,
        retail_target: snap.targets?.retail_target || 66,
        test_drives: snap.funnel?.test_drives || 128,
        td_target: snap.targets?.td_target || 300,
        free_stock: 69,
        stock_over_90_days: 20,
        backorders: 11,
        bookings_missing_crm_entry: 15,
        booking_amount_collected: 943001,
      },
      funnel: {
        period: snap.funnel?.period || "AUG2026",
        stages: [
          { stage: "Enquiries", value: snap.funnel?.enquiries || 367, target: snap.targets?.leads_target || 450 },
          { stage: "Qualified", value: snap.funnel?.qualified || 361, target: null },
          { stage: "Test drives", value: snap.funnel?.test_drives || 128, target: snap.targets?.td_target || 300 },
          { stage: "Bookings", value: snap.funnel?.bookings || 42, target: snap.targets?.booking_target || 84 },
          { stage: "Retails", value: snap.funnel?.retails || 18, target: snap.targets?.retail_target || 66 },
        ],
      },
      board: snap.board || [],
      sources: snap.sources || [],
      models: snap.models || [],
      ageing: snap.ageing || [],
      backorders: snap.backorders || [],
      periods: [{ label: "AUG2026", is_active: true, period_start: "2026-08-01", period_end: "2026-08-31" }],
      options: { consultants: [], models: [], sources: [], colours: [], open_bookings: [], free_chassis: [] },
      activity: [],
      orderbook: [],
      trends: {},
      scorecards: [],
      commitments: [],
      attachments: null,
      dataQuality: [],
      isLive: false,
    };
  }
}

export async function uploadReportFile(file, period, uploadedBy, tableType, mode) {
  const formData = new FormData();
  formData.append("file", file);
  if (period) formData.append("period", period);
  if (uploadedBy) formData.append("uploaded_by", uploadedBy);
  if (tableType && tableType !== "auto") formData.append("table_type", tableType);
  // FIX (2026-10-08): the replace/append choice in the upload dialog was never
  // sent for CSV and text files. A sectioned text DSR now honours it; a
  // single-table CSV is always added, and the reply's `mode` says so.
  if (mode) formData.append("mode", mode);

  // A DSR workbook takes the better part of two minutes to ingest: ~2,600 rows
  // against a database a round trip away. Anything that goes wrong in that
  // window used to surface as the same four words - "Report upload failed" -
  // whether the server was down, a proxy gave up, or the workbook itself was
  // rejected. Those need different answers from whoever is standing there, so
  // they now say different things.
  const started = Date.now();
  let res;
  try {
    res = await fetch("/api/upload-report", { method: "POST", body: formData });
  } catch (err) {
    // fetch only rejects when the request never completed: the server is not
    // listening, the connection dropped, or the page navigated mid-upload.
    const secs = Math.round((Date.now() - started) / 1000);
    throw new Error(
      `Could not reach the server (${err.message}). ` +
      (secs > 20
        ? `The connection dropped after ${secs}s — the upload may still be running on the server. Refresh before trying again.`
        : "Check that the API is running, then try again.")
    );
  }

  const body = await res.text();
  let data = null;
  try { data = JSON.parse(body); } catch { /* not JSON - see below */ }

  if (!res.ok) {
    const secs = Math.round((Date.now() - started) / 1000);
    if (data && data.detail) {
      // The server rejected it and said why: a bad workbook, a missing period.
      throw new Error(data.detail);
    }
    // No JSON means this did not come from the API at all - it is a proxy or
    // gateway page. Saying so is the difference between "my file is wrong" and
    // "something between me and the server gave up".
    throw new Error(
      `Upload failed with HTTP ${res.status} after ${secs}s, and the response ` +
      `was not from the API. Something between the browser and the server ` +
      `(dev-server proxy, gateway) ended the request — the ingest may still be ` +
      `running. Refresh in a minute before retrying.`
    );
  }

  return data ?? {};
}

export const uploadExcelWorkbook = uploadReportFile;

/**
 * Ingest a workbook without holding the HTTP request open.
 *
 * A DSR workbook takes ~100 seconds to ingest. Render's gateway ends any
 * request at about 60, and a dev-server proxy defaults to the same, so a
 * synchronous upload was reported as a 502 while the ingest carried on and
 * finished — the month loaded, and the person who pressed the button was told
 * it had failed. Nothing can time out a request that returns in milliseconds,
 * so the upload now starts a job and this polls it.
 *
 * `onProgress(state)` fires on each poll so the modal can say where it is.
 */
export async function uploadWorkbookInBackground(
  file, period, uploadedBy, onProgress, opts = {},
) {
  const { mode = "replace", covers = "month", coversDate, coversDateEnd } = opts;
  const formData = new FormData();
  formData.append("file", file);
  if (period) formData.append("period", period);
  if (uploadedBy) formData.append("uploaded_by", uploadedBy);
  formData.append("mode", mode);
  formData.append("covers", covers);
  // Only sent for a day or a week; the server derives the month from it.
  if (coversDate) formData.append("covers_date", coversDate);
  // The far end of a week. Recorded with the load so the run is traceable to
  // the span the dealership said it covers.
  if (coversDateEnd) formData.append("covers_date_end", coversDateEnd);

  let res;
  try {
    res = await fetch("/api/upload-report/start", { method: "POST", body: formData });
  } catch (err) {
    throw new Error(`Could not reach the server (${err.message}). Check the API is running.`);
  }
  const startBody = await res.text();
  let started = null;
  try { started = JSON.parse(startBody); } catch { /* handled below */ }
  if (!res.ok) {
    throw new Error((started && started.detail)
      || `Could not start the ingest (HTTP ${res.status}).`);
  }
  if (!started || !started.job_id) {
    throw new Error("The server accepted the file but did not return a job id.");
  }

  // FIX (2026-10-09): on Vercel the server cannot run a job in the background
  // (a serverless function is frozen once it replies), so it does the whole
  // load before answering and the reply already carries the outcome. There is
  // nothing to poll - and a poll could reach a different instance that has
  // never heard of the job. See start_upload in app/entry.py.
  if (started.state === "done") return started.result || {};
  if (started.state === "failed") {
    throw new Error(started.error || "The ingest failed on the server.");
  }

  // Poll until it finishes. Failures to reach the server are tolerated for a
  // while: the ingest is running server-side regardless of this connection,
  // which is the whole point of doing it this way.
  const deadline = Date.now() + 15 * 60 * 1000;
  let consecutiveErrors = 0;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 2000));
    let job;
    try {
      const p = await fetch(`/api/upload-report/status/${started.job_id}`);
      if (p.status === 404) {
        throw new Error("The ingest job is no longer on the server — it may have restarted mid-load. "
                        + "Refresh and check whether the month arrived before uploading again.");
      }
      job = await p.json();
      consecutiveErrors = 0;
    } catch (err) {
      if (err.message && err.message.startsWith("The ingest job is no longer")) throw err;
      if (++consecutiveErrors >= 10) {
        throw new Error("Lost contact with the server while the ingest was running. "
                        + "It may still have finished — refresh before uploading again.");
      }
      continue;
    }

    if (onProgress) onProgress(job);
    if (job.state === "done") return job.result || {};
    if (job.state === "failed") throw new Error(job.error || "The ingest failed on the server.");
  }
  throw new Error("The ingest is taking unusually long. It may still finish — "
                  + "refresh in a few minutes before uploading again.");
}

/* ---- Export ---- */

/**
 * What can be exported, with live row counts, so the picker can say what a
 * selection will produce before anyone commits to building it.
 */
export async function fetchExportManifest(scope = "current") {
  const res = await fetch(`/api/export/manifest?scope=${encodeURIComponent(scope)}`);
  if (res.ok) return res.json();

  // A 404 here means something specific and fixable: the page is newer than the
  // server it is talking to. run.py starts uvicorn with reload=False, so a
  // backend left running from before the export routes existed serves the new
  // bundle happily and then 404s on them. Saying "Not Found" sends someone
  // hunting through the frontend for a bug that is not there.
  if (res.status === 404) {
    const err = new Error(
      "The export service is not running on the server yet. The API needs to be " +
      "restarted so it picks up the export routes."
    );
    err.status = 404;
    throw err;
  }

  const data = await res.json().catch(() => null);
  const err = new Error((data && data.detail) || `${res.status} ${res.statusText}`);
  err.status = res.status;
  throw err;
}

/**
 * Build an export and put it where it was asked to go.
 *
 * A local export comes back as bytes rather than JSON, so this saves the blob
 * itself and reports what it saved. The row and sheet counts ride on response
 * headers because a blob tells the browser nothing about what is inside it.
 */
export async function runExport({
  format, scope, template, groups, datasets, destination, filename,
}) {
  const res = await fetch("/api/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // `filename` is left out when undefined, which is what tells the server to
    // stamp its own month-and-minute name.
    body: JSON.stringify({
      format, scope, template, groups, datasets, destination, filename,
    }),
  });

  if (!res.ok) {
    // A failure is JSON even when success is not.
    const data = await res.json().catch(() => null);
    throw new Error((data && data.detail) || `${res.status} ${res.statusText}`);
  }

  // A cloud destination answers with JSON; only a local one sends a file.
  const type = res.headers.get("Content-Type") || "";
  if (type.includes("application/json")) return res.json();

  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") || "";
  // What the server actually called it, which is not necessarily what was
  // asked for - it strips anything that cannot go in a file name, and adds the
  // extension the chosen format needs.
  const savedAs =
    res.headers.get("X-Export-Filename") ||
    (disposition.match(/filename="?([^"]+)"?/) || [])[1] ||
    "dsr-export";

  // The one thing a fetch cannot do on its own: hand the file to the user. The
  // object URL is revoked on the next frame - revoking it immediately cancels
  // the download in Firefox.
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = savedAs;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);

  return {
    status: "success",
    destination: destination || "local",
    filename: savedAs,
    bytes: blob.size,
    rows: Number(res.headers.get("X-Export-Rows") || 0),
    sheets: Number(res.headers.get("X-Export-Sheets") || 0),
  };
}

export async function activatePeriod(label) {
  return sendJson("POST", `/api/period/${encodeURIComponent(label)}/activate`);
}

/* ---- Formatting Helpers ---- */
export const n0 = v => (v == null ? "–" : Number(v).toLocaleString("en-IN"));
export const pct = v => (v == null ? "–" : Number(v).toFixed(1) + "%");

export function money(v) {
  if (v == null) return "–";
  const num = Number(v);
  if (num >= 1e7) return "₹" + (num / 1e7).toFixed(2) + " Cr";
  if (num >= 1e5) return "₹" + (num / 1e5).toFixed(2) + " L";
  return "₹" + num.toLocaleString("en-IN");
}

export function dt(s) {
  if (!s) return "–";
  return new Date(s).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}
