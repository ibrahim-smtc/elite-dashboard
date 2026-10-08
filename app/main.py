"""
Volkswagen Elite Motors - DSR dashboard and API.

    python run.py                       # http://127.0.0.1:8000

Two groups of endpoints share one query layer:

  /api/*     everything the dashboard draws
  /agent/*   the narrow, stable surface the service and client agents call as tools

The /agent routes are deliberately small and answer one question each, because a
tool that returns a whole table forces the model to do the filtering.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import fallback
from .db import is_db_ready, fetch_all, fetch_one, filtered, pool, session
from .entry import router as entry_router
from .crm_api import router as crm_router
from .export import router as export_router
from .webhooks import router as webhooks_router
from .calls import router as calls_router
from .test_drives import router as test_drives_router  # prototype
from .mcp_server import router as mcp_router
from .events import broker

log = logging.getLogger("dsr.main")

STATIC = Path(__file__).resolve().parent / "static"
if not STATIC.exists():
    STATIC = Path(__file__).resolve().parent.parent / "public"


@asynccontextmanager
async def lifespan(app: FastAPI):
    is_vercel = bool(os.environ.get("VERCEL"))
    try:
        pool.open()
        if not is_vercel and os.environ.get("DATABASE_URL"):
            # Deliberately not pool.wait(): on timeout it closes the pool, and a
            # closed pool cannot be reopened, so one slow start would leave the
            # app serving fallback data until it was restarted. The ping below
            # warms a connection and is allowed to fail.
            is_db_ready()
    except Exception as exc:
        log.warning("Database connection pool not ready: %s", exc)

    # The change listener SSE thread runs on persistent hosts, not serverless environments
    if not is_vercel and os.environ.get("DATABASE_URL"):
        try:
            await broker.start()
        except Exception as exc:
            log.warning("Change broker not started: %s", exc)

    yield

    if not is_vercel and os.environ.get("DATABASE_URL"):
        try:
            await broker.stop()
        except Exception:
            pass
    try:
        pool.close()
    except Exception:
        pass


app = FastAPI(
    title="Volkswagen Elite Motors - DSR API",
    version="1.0.0",
    lifespan=lifespan,
    description=(
        "Read API over the Daily Sales Report database for Volkswagen Elite Motors, "
        "Hosur Road, Bengaluru. Stock, enquiries, the order book, consultant "
        "scorecards and fulfilment, loaded from the DSR workbook.\n\n"
        "`/agent/*` is the tool surface for the dealership's service and client agents.\n\n"
        "The database is read **and written** here: `/api/leads`, `/api/bookings`, "
        "`/api/test-drives`, `/api/vehicles`, `/api/allotments` and "
        "`/api/registrations` accept new records, and every open dashboard is "
        "pushed an update over `/api/events` the moment one lands."
    ),
)

# Everything that writes, plus the change stream.
app.include_router(entry_router)
app.include_router(crm_router)
# And the way back out: the live tables as an Excel workbook or a CSV set.
app.include_router(export_router)
app.include_router(webhooks_router)
app.include_router(calls_router)
app.include_router(test_drives_router)
# The Perfox "Dashboard Insights" agent's tool surface.
app.include_router(mcp_router)


# =====================================================================
# Dashboard data
# =====================================================================

# The whole dashboard, assembled inside one statement.
#
# Profiling said the SQL is free and the network is everything: against this
# database every query costs the same as SELECT 1 (~360 ms), because it is a
# round trip to Sydney. Sixteen endpoints, each taking its own pooled
# connection, spent ~5.2 s wall-clock to move 50 KB. Postgres will build all of
# it as JSON in a single statement, so the page now costs one round trip
# instead of sixteen checkouts.
# The dealership's targets for the month the dashboard is set to: its
# scorecard's TOTAL row - or, for a workbook with no TOTAL row (one team's
# scorecard, say), its team rows added up, which is what the TOTAL row is.
# With neither there are none; the front end used to fill in August's (84
# bookings, 66 retails, 450 enquiries, 300 test drives) and show them as any
# month's.
_TARGETS_SQL = """
    SELECT leads_target, td_target, booking_target, retail_target
      FROM v_consultant_scorecard WHERE row_kind = 'GRAND_TOTAL'
    UNION ALL
    SELECT sum(leads_target), sum(td_target), sum(booking_target), sum(retail_target)
      FROM v_consultant_scorecard
     WHERE row_kind = 'TEAM_TOTAL'
       AND NOT EXISTS (SELECT 1 FROM v_consultant_scorecard WHERE row_kind = 'GRAND_TOTAL')
    HAVING count(*) > 0
    LIMIT 1"""

_DASHBOARD_BUNDLE = """
SELECT
  (SELECT row_to_json(x) FROM v_daily_kpi x)                                        AS kpi,
  (SELECT row_to_json(x) FROM v_sales_funnel x)                                     AS funnel_raw,
  (SELECT row_to_json(x) FROM (__TARGETS__) x)                                     AS targets,
  (SELECT json_agg(x) FROM v_consultant_leaderboard x)                              AS board,
  (SELECT json_agg(x) FROM (SELECT * FROM v_leads_sourcewise ORDER BY leads DESC) x)        AS sources,
  (SELECT json_agg(x) FROM (SELECT * FROM v_model_position ORDER BY total_stock DESC, model) x) AS models,
  (SELECT json_agg(x) FROM (
        SELECT COALESCE(m.family, a.model) AS model, a.ageing_bucket,
               sum(a.units)::int AS units,
               round(sum(a.avg_days * a.units) / NULLIF(sum(a.units), 0), 1) AS avg_days,
               max(a.max_days) AS max_days
        FROM v_stock_ageing a LEFT JOIN dim_model m ON m.name = a.model
        GROUP BY 1, 2 ORDER BY 1, 2) x)                                             AS ageing,
  (SELECT json_agg(x) FROM (SELECT * FROM v_backorders
        ORDER BY is_current_period DESC, days_waiting DESC NULLS LAST) x)           AS backorders,
  (SELECT json_agg(x) FROM v_consultant_scorecard x)                                AS scorecards,
  (SELECT json_agg(x) FROM (SELECT * FROM v_booking_commitments
        ORDER BY consultant_label, window_label) x)                                 AS commitments,
  (SELECT row_to_json(x) FROM v_attachment_rates x)                                 AS attachments,
  (SELECT json_agg(x) FROM v_data_quality x)                                        AS "dataQuality",
  (SELECT json_agg(x) FROM (SELECT * FROM v_bookings WHERE is_current_period
        ORDER BY booking_date DESC NULLS LAST LIMIT 1000) x)                        AS orderbook,
  (SELECT json_agg(x) FROM (
        SELECT p.label, p.period_start, p.period_end, p.is_active,
               (SELECT count(*) FROM lead    l WHERE l.period_id = p.period_id) AS leads,
               (SELECT count(*) FROM booking b WHERE b.period_id = p.period_id) AS bookings
        FROM dim_period p ORDER BY p.period_start DESC) x)                          AS periods,
  -- FIX (2026-10-08): the bundle had no recent-activity feed, and the browser
  -- filled `activity` with [] whenever the bundle was used - which is always -
  -- so "Recently Recorded" under the stock panel was permanently empty. The
  -- query is /api/recent-activity's (app/entry.py), limited the same 15 rows
  -- the per-endpoint path asked for.
  (SELECT json_agg(x) FROM (
        SELECT * FROM (
            SELECT 'booking' AS kind, booking_id AS id, customer_name AS who,
                   loaded_at, entered_by FROM booking WHERE origin = 'MANUAL'
            UNION ALL
            SELECT 'lead', lead_id, lead_name, loaded_at, entered_by
              FROM lead WHERE origin = 'MANUAL'
            UNION ALL
            SELECT 'test drive', test_drive_id, lead_name, loaded_at, entered_by
              FROM test_drive WHERE origin = 'MANUAL'
            UNION ALL
            SELECT 'allotment', allotment_id, customer_name, loaded_at, entered_by
              FROM allotment WHERE origin = 'MANUAL'
            UNION ALL
            SELECT 'registration', registration_id, customer_name, loaded_at, entered_by
              FROM registration WHERE origin = 'MANUAL'
            UNION ALL
            SELECT 'vehicle', vehicle_id, chassis_number, loaded_at, entered_by
              FROM vehicle WHERE origin = 'MANUAL'
        ) a ORDER BY loaded_at DESC LIMIT 15) x)                                    AS activity,
  (SELECT json_build_object(
        'enquiries', (SELECT json_agg(t) FROM (
            SELECT d::date::text AS d,
                   (SELECT count(*) FROM lead l WHERE l.is_current_period
                      AND l.created_at::date = d::date) AS n
            FROM generate_series((SELECT period_start FROM dim_period WHERE is_active),
                                 (SELECT period_end   FROM dim_period WHERE is_active),
                                 interval '1 day') d) t),
        'bookings', (SELECT json_agg(t) FROM (
            SELECT d::date::text AS d,
                   (SELECT count(*) FROM booking b WHERE b.is_current_period
                      AND b.booking_date = d::date) AS n
            FROM generate_series((SELECT period_start FROM dim_period WHERE is_active),
                                 (SELECT period_end   FROM dim_period WHERE is_active),
                                 interval '1 day') d) t)))                          AS trends,
  (SELECT json_build_object(
        'consultants', (SELECT json_agg(display_name ORDER BY display_name)
                          FROM dim_consultant WHERE is_active),
        'sources',     (SELECT json_agg(name ORDER BY name) FROM dim_lead_source),
        'models',      (SELECT json_agg(name ORDER BY name) FROM dim_model),
        'colours',     (SELECT json_agg(name ORDER BY name) FROM dim_colour),
        'variants',    (SELECT json_agg(x) FROM (
                          SELECT m.name AS model, v.name AS variant, v.long_model_text
                          FROM dim_variant v JOIN dim_model m USING (model_id)
                          ORDER BY m.name, v.name) x),
        'fulfilment_statuses', json_build_array('BOOKED','NO_STOCK','ALLOTED','RETAILED','CANCELLED'),
        'open_bookings', (SELECT json_agg(x) FROM (
                          SELECT b.booking_id, b.customer_name, m.name AS model,
                                 dv.name AS variant, c.display_name AS consultant
                          FROM booking b
                          LEFT JOIN dim_model m ON m.model_id = b.model_id
                          LEFT JOIN dim_variant dv ON dv.variant_id = b.variant_id
                          LEFT JOIN dim_consultant c ON c.consultant_id = b.consultant_id
                          WHERE b.fulfilment_status IN ('BOOKED','NO_STOCK')
                          ORDER BY b.booking_date DESC NULLS LAST LIMIT 200) x),
        'free_chassis', (SELECT json_agg(x) FROM (
                          SELECT chassis_number, model, variant, colour, stock_aging_days
                          FROM v_stock WHERE stock_status = 'FREESTOCK'
                          ORDER BY stock_aging_days DESC NULLS LAST) x)))            AS options
""".replace("__TARGETS__", _TARGETS_SQL)


@app.get("/api/dashboard", tags=["dashboard"])
def dashboard_bundle():
    """
    Everything the dashboard draws, in one round trip.

    The individual /api/* routes are unchanged - the agent surface and anything
    else still uses them, and the front end falls back to them if this fails.
    """
    if not is_db_ready():
        raise HTTPException(503, "The database is not reachable.")
    with session() as cx:
        row = cx.execute(_DASHBOARD_BUNDLE).fetchone()

    stages = row.get("funnel_raw") or {}
    targets = row.get("targets") or {}
    out = {k: (v if v is not None else []) for k, v in row.items()
           if k not in ("funnel_raw", "targets")}
    out["funnel"] = {
        "period": stages.get("period"),
        "stages": [
            {"stage": "Enquiries",   "value": stages.get("enquiries"),   "target": targets.get("leads_target")},
            {"stage": "Qualified",   "value": stages.get("qualified"),   "target": None},
            {"stage": "Test drives", "value": stages.get("test_drives"), "target": targets.get("td_target")},
            {"stage": "Bookings",    "value": stages.get("bookings"),    "target": targets.get("booking_target")},
            {"stage": "Retails",     "value": stages.get("retails"),     "target": targets.get("retail_target")},
        ],
    } if stages else {}
    return out


@app.get("/api/kpi", tags=["dashboard"])
def kpi():
    """Headline numbers for the current period."""
    if is_db_ready():
        try:
            row = fetch_one("SELECT * FROM v_daily_kpi")
            if row:
                return row
        except Exception:
            pass
    return fallback.get_kpi()


@app.get("/api/kpi/trends", tags=["dashboard"])
def kpi_trends():
    """
    Daily series behind the headline tiles, so a tile can show its shape and
    not just its total.

    Only two metrics have an honest daily series. Enquiries carry created_at and
    bookings carry booking_date; registrations do not - delivery_date is blank
    on every row of the Reg Report tab (see v_data_quality), so there is no
    retail trend to draw and this returns none rather than inventing one.

    Days with no activity are returned as zero rather than omitted, so the
    sparkline keeps an even time axis instead of bunching the gaps up.
    """
    empty = {"enquiries": [], "bookings": [], "period": None}
    if not is_db_ready():
        return empty
    try:
        with session() as cx:
            period = cx.execute(
                "SELECT label, period_start, period_end FROM dim_period WHERE is_active"
            ).fetchone()
            if not period:
                return empty

            def series(sql: str) -> list[dict]:
                rows = {r["d"]: r["n"] for r in cx.execute(sql).fetchall()}
                out, day = [], period["period_start"]
                while day <= period["period_end"]:
                    out.append({"d": day.isoformat(), "n": rows.get(day, 0)})
                    day += timedelta(days=1)
                return out

            return {
                "enquiries": series(
                    "SELECT created_at::date AS d, count(*) AS n FROM lead "
                    "WHERE is_current_period AND created_at IS NOT NULL GROUP BY 1"),
                "bookings": series(
                    "SELECT booking_date AS d, count(*) AS n FROM booking "
                    "WHERE is_current_period AND booking_date IS NOT NULL GROUP BY 1"),
                "period": {
                    "label": period["label"],
                    "start": period["period_start"].isoformat(),
                    "end": period["period_end"].isoformat(),
                },
            }
    except Exception:
        log.exception("kpi trends failed")
        return empty


def _trim_trailing_empty(buckets: list[dict], keys: tuple[str, ...]) -> list[dict]:
    """
    Drop the buckets after the last one with activity.

    A spine runs the length of the reporting month, so a month reported up to
    the 21st drew nine more days of zeros - a line that falls to the floor and
    stays there, which reads as business collapsing rather than as days that
    have not happened yet.

    Only the tail goes. A quiet Wednesday in the middle of the month is a real
    day on which nothing sold and the dip belongs on the chart; the days after
    the last one reported are not days at all yet. If nothing has any activity
    the first bucket is kept, so the axis still has something to draw.
    """
    last = -1
    for i, b in enumerate(buckets):
        if any(b.get(k) for k in keys):
            last = i
    if last < 0:
        return buckets[:1]
    return buckets[:last + 1]


@app.get("/api/sales/timeline", tags=["dashboard"])
def sales_timeline(
    grain: str = Query("day", pattern="^(day|week|month)$"),
    period: str | None = Query(None, description="Month label; defaults to the active one"),
):
    """
    Sales activity over time, at the grain the floor actually asks for.

    day and week are read within one reporting month; month spans every month on
    record, so the same endpoint answers "how did this week go" and "how do the
    months compare".

    Only bookings and enquiries are plotted. Retails would belong here too, but
    the Reg Report tab leaves delivery, registration and invoice dates blank on
    every row, so there is no date to put a retail on - see v_data_quality.
    Test drives carry dates from a 2024 export, which is the same problem.
    Buckets with no activity are returned as zero so the axis stays even.
    """
    empty = {"grain": grain, "period": None, "buckets": []}
    if not is_db_ready():
        return empty
    try:
        with session() as cx:
            if grain == "month":
                rows = cx.execute("""
                    -- period_id, not load_period_id: a workbook also carries
                    -- carry-over tabs (Pending, Live, Golf) which belong to
                    -- earlier months. Counting those would make the month view
                    -- disagree with the headline and with day/week, which read
                    -- the current month only.
                    SELECT p.label,
                           p.period_start AS bucket,
                           (SELECT count(*) FROM booking b
                             WHERE b.period_id = p.period_id) AS bookings,
                           (SELECT count(*) FROM lead l
                             WHERE l.period_id = p.period_id) AS enquiries,
                           (SELECT COALESCE(sum(b.booking_amount), 0) FROM booking b
                             WHERE b.period_id = p.period_id) AS revenue
                    FROM dim_period p
                    ORDER BY p.period_start
                """).fetchall()
                return {
                    "grain": "month",
                    "period": None,
                    "buckets": [{
                        "key": r["label"],
                        "label": r["label"],
                        "bookings": r["bookings"],
                        "enquiries": r["enquiries"],
                        "revenue": float(r["revenue"] or 0),
                    } for r in rows],
                }

            p = cx.execute(
                "SELECT label, period_start, period_end FROM dim_period "
                "WHERE upper(label) = upper(%s)" if period else
                "SELECT label, period_start, period_end FROM dim_period WHERE is_active",
                (period,) if period else ()).fetchone()
            if not p:
                return empty

            step = "1 day" if grain == "day" else "1 week"
            # The spine normally runs the length of the reporting month. But a
            # workbook loaded into a month it was not written for carries the
            # dates it was written with - the August DSR loaded into SEP2026
            # holds rows dated 1-31 August - and a spine over September then
            # matches none of them, drawing a flat zero line over real data.
            #
            # So: use the month's window whenever ANY dated row falls inside it
            # (the normal case, unchanged), and fall back to the range the data
            # actually occupies when none does. `covers` reports which, so the
            # sheet can say what it is plotting rather than quietly lying.
            rows = cx.execute(f"""
                WITH dated AS (
                    SELECT b.booking_date AS dt FROM booking b
                     WHERE b.is_current_period AND b.booking_date IS NOT NULL
                    UNION ALL
                    SELECT l.created_at::date FROM lead l
                     WHERE l.is_current_period AND l.created_at IS NOT NULL
                ),
                bounds AS (
                    SELECT
                      count(*) FILTER (WHERE dt BETWEEN %s::date AND %s::date) AS inside,
                      min(dt) AS lo, max(dt) AS hi
                    FROM dated
                ),
                win AS (
                    SELECT
                      CASE WHEN inside > 0 OR lo IS NULL THEN %s::date ELSE lo END AS lo,
                      CASE WHEN inside > 0 OR hi IS NULL THEN %s::date ELSE hi END AS hi,
                      inside
                    FROM bounds
                ),
                spine AS (
                    SELECT generate_series(
                        date_trunc('{grain}', (SELECT lo FROM win)),
                        date_trunc('{grain}', (SELECT hi FROM win)),
                        interval '{step}')::date AS bucket
                )
                SELECT s.bucket,
                       (SELECT lo FROM win) AS win_lo,
                       (SELECT hi FROM win) AS win_hi,
                       (SELECT count(*) FROM booking b
                         WHERE b.is_current_period AND b.booking_date IS NOT NULL
                           AND date_trunc('{grain}', b.booking_date) = s.bucket) AS bookings,
                       (SELECT count(*) FROM lead l
                         WHERE l.is_current_period AND l.created_at IS NOT NULL
                           AND date_trunc('{grain}', l.created_at) = s.bucket) AS enquiries,
                       (SELECT COALESCE(sum(b.booking_amount), 0) FROM booking b
                         WHERE b.is_current_period AND b.booking_date IS NOT NULL
                           AND date_trunc('{grain}', b.booking_date) = s.bucket) AS revenue
                FROM spine s ORDER BY s.bucket
            """, (p["period_start"], p["period_end"],
                  p["period_start"], p["period_end"])).fetchall()

            # The window the data occupies, not the bucket keys. date_trunc(week)
            # pulls the first bucket back to its Monday, so a September month
            # starts its first week on 31 August - reading this off the keys
            # flagged every Week view as straying outside its own month.
            covered = [rows[0]["win_lo"], rows[0]["win_hi"]] if rows else None
            outside = bool(covered and (covered[0] < p["period_start"]
                                        or covered[1] > p["period_end"]))

            buckets = [{
                "key": r["bucket"].isoformat(),
                "label": r["bucket"].isoformat(),
                "bookings": r["bookings"],
                "enquiries": r["enquiries"],
                "revenue": float(r["revenue"] or 0),
            } for r in rows]
            # Months are discrete and a month with nothing in it is worth
            # seeing; a day that has not been reported yet is not.
            if grain != "month":
                buckets = _trim_trailing_empty(buckets, ("bookings", "enquiries", "revenue"))

            return {
                "grain": grain,
                "period": p["label"],
                "period_range": [p["period_start"].isoformat(), p["period_end"].isoformat()],
                "covers": [covered[0].isoformat(), covered[1].isoformat()] if covered else None,
                # True when the rows filed under this month carry dates from
                # outside it - the sheet says so rather than showing a chart
                # whose axis silently disagrees with its title.
                "dates_outside_period": outside,
                "buckets": buckets,
            }
    except Exception:
        log.exception("sales timeline failed")
        return empty


@app.get("/api/sales/trends", tags=["dashboard"])
def sales_trends(
    grain: str = Query("week", pattern="^(day|week)$"),
    period: str | None = Query(None, description="Month label; defaults to the active one"),
):
    """
    How the month's mix is moving - by channel, by model, and by conversion.

    /api/sales/timeline answers "how much"; this answers "made up of what". The
    headline says 262 enquiries and 46 bookings, but not that Digital is growing
    while Walk-in flattens, or that Taigun interest is shifting to Virtus. Those
    are the questions a sales manager actually asks of a DSR.

    Only enquiries and bookings are trended, for the same reason the timeline
    plots only those two: every date on the Reg Report tab is blank and the test
    drive tab carries a 2024 export, so retails and test drives cannot be placed
    on a day without inventing one. See v_data_quality.

    The window is chosen exactly as the timeline chooses it - the reporting
    month when any dated row falls inside it, and the range the data actually
    occupies when none does - so the two panels never disagree about which dates
    they are showing.
    """
    empty = {"grain": grain, "period": None, "buckets": [], "sources": [], "models": []}
    if not is_db_ready():
        return empty
    try:
        with session() as cx:
            p = cx.execute(
                "SELECT label, period_start, period_end FROM dim_period "
                "WHERE upper(label) = upper(%s)" if period else
                "SELECT label, period_start, period_end FROM dim_period WHERE is_active",
                (period,) if period else ()).fetchone()
            if not p:
                return empty

            step = "1 day" if grain == "day" else "1 week"

            # Same rule as the timeline: prefer the month, fall back to where the
            # data actually is. Resolved once here and passed into the queries
            # below, so the panels cannot drift apart.
            win = cx.execute("""
                WITH dated AS (
                    SELECT b.booking_date AS dt FROM booking b
                     WHERE b.is_current_period AND b.booking_date IS NOT NULL
                    UNION ALL
                    SELECT l.created_at::date FROM lead l
                     WHERE l.is_current_period AND l.created_at IS NOT NULL
                ),
                bounds AS (
                    SELECT count(*) FILTER (WHERE dt BETWEEN %s::date AND %s::date) AS inside,
                           min(dt) AS lo, max(dt) AS hi FROM dated
                )
                SELECT CASE WHEN inside > 0 OR lo IS NULL THEN %s::date ELSE lo END AS lo,
                       CASE WHEN inside > 0 OR hi IS NULL THEN %s::date ELSE hi END AS hi
                FROM bounds
            """, (p["period_start"], p["period_end"],
                  p["period_start"], p["period_end"])).fetchone()

            lo, hi = win["lo"], win["hi"]

            totals = cx.execute(f"""
                WITH spine AS (
                    SELECT generate_series(date_trunc('{grain}', %s::date),
                                           date_trunc('{grain}', %s::date),
                                           interval '{step}')::date AS bucket
                )
                SELECT s.bucket,
                       (SELECT count(*) FROM lead l
                         WHERE l.is_current_period AND l.created_at IS NOT NULL
                           AND date_trunc('{grain}', l.created_at) = s.bucket) AS enquiries,
                       (SELECT count(*) FROM booking b
                         WHERE b.is_current_period AND b.booking_date IS NOT NULL
                           AND date_trunc('{grain}', b.booking_date) = s.bucket) AS bookings,
                       (SELECT COALESCE(sum(b.booking_amount), 0) FROM booking b
                         WHERE b.is_current_period AND b.booking_date IS NOT NULL
                           AND date_trunc('{grain}', b.booking_date) = s.bucket) AS revenue
                FROM spine s ORDER BY s.bucket
            """, (lo, hi)).fetchall()

            # Channel, not the individual source row. The CRM export puts a
            # salesperson's name in the source column on some leads, so
            # grouping by name stacked ADITYA KUMAR beside CRM and WALKIN -
            # people and categories in one stack. Same grouping as
            # v_leads_sourcewise, so this chart and Lead Sources agree.
            by_source = cx.execute(f"""
                SELECT date_trunc('{grain}', l.created_at)::date AS bucket,
                       COALESCE(src.channel::text, 'Unattributed') AS name,
                       count(*) AS n
                  FROM lead l LEFT JOIN dim_lead_source src USING (source_id)
                 WHERE l.is_current_period AND l.created_at IS NOT NULL
                 GROUP BY 1, 2
            """).fetchall()

            by_model = cx.execute(f"""
                SELECT date_trunc('{grain}', l.created_at)::date AS bucket,
                       COALESCE(m.name, 'Unspecified') AS name,
                       count(*) AS n
                  FROM lead l LEFT JOIN dim_model m USING (model_id)
                 WHERE l.is_current_period AND l.created_at IS NOT NULL
                 GROUP BY 1, 2
            """).fetchall()

    except Exception:
        log.exception("sales trends failed")
        return empty

    def fold(rows):
        """{bucket -> {series -> count}}, plus the series ordered by total size."""
        out, weight = {}, {}
        for r in rows:
            out.setdefault(r["bucket"], {})[r["name"]] = r["n"]
            weight[r["name"]] = weight.get(r["name"], 0) + r["n"]
        return out, [k for k, _ in sorted(weight.items(), key=lambda kv: -kv[1])]

    src_map, src_order = fold(by_source)
    mdl_map, mdl_order = fold(by_model)

    # A long tail of one-lead channels turns a stacked bar into a barcode. The
    # small ones are summed into "Other" rather than dropped, so the stack still
    # totals the enquiry count for that bucket.
    TOP = 6
    src_keep, src_rest = src_order[:TOP], set(src_order[TOP:])
    mdl_keep, mdl_rest = mdl_order[:TOP], set(mdl_order[TOP:])

    def series(m, keep, rest):
        out = {k: m.get(k, 0) for k in keep}
        spill = sum(v for k, v in m.items() if k in rest)
        if spill:
            out["Other"] = spill
        return out

    buckets, running = [], 0.0
    for r in totals:
        rev = float(r["revenue"] or 0)
        running += rev
        enq, bk = r["enquiries"], r["bookings"]
        buckets.append({
            "key": r["bucket"].isoformat(),
            "enquiries": enq,
            "bookings": bk,
            "revenue": rev,
            "cumulative_revenue": running,
            # Bookings per hundred enquiries in the same bucket. Null rather than
            # zero when nothing came in, so the line breaks instead of diving to
            # the floor on a quiet day and reading as a collapse in conversion.
            "conversion": round(100.0 * bk / enq, 1) if enq else None,
            "by_source": series(src_map.get(r["bucket"], {}), src_keep, src_rest),
            "by_model": series(mdl_map.get(r["bucket"], {}), mdl_keep, mdl_rest),
        })

    # Same as the timeline: stop at the last bucket with anything in it.
    # cumulative_revenue carries forward and is non-zero in every trailing
    # bucket, so it is deliberately not one of the keys tested - judging on it
    # would keep the entire empty tail.
    buckets = _trim_trailing_empty(buckets, ("enquiries", "bookings", "revenue"))

    # Reported from the window the data actually occupies, not from the bucket
    # keys. date_trunc(week) pulls the first bucket back to its Monday, so a
    # September month starts its first week on 31 August - reading the warning
    # off the keys flagged every Week view as straying outside its own month.
    return {
        "grain": grain,
        "period": p["label"],
        "period_range": [p["period_start"].isoformat(), p["period_end"].isoformat()],
        "covers": [lo.isoformat(), hi.isoformat()] if lo and hi else None,
        "dates_outside_period": bool(lo and hi and (lo < p["period_start"]
                                                    or hi > p["period_end"])),
        "sources": src_keep + (["Other"] if src_rest else []),
        "models": mdl_keep + (["Other"] if mdl_rest else []),
        "buckets": buckets,
    }


@app.get("/api/folder-tat", tags=["dashboard"])
def folder_tat():
    """
    How long paperwork sits before it reaches accounts.

    v_folder_tat has been in the schema all along and shown nowhere. It is the
    one back-office measure the workbook carries: when a folder was lined up,
    when it reached accounts, and how many days passed in between. A car can be
    sold and delivered while its file sits on someone's desk, and nothing else
    on the sheet would say so.

    Rows with no lined-up date are dropped rather than counted as zero-day
    turnarounds, which would flatter the average.
    """
    if not is_db_ready():
        return {"rows": [], "total": 0, "with_dates": 0, "avg_days": None,
                "over_3_days": 0}
    try:
        rows = fetch_all("""
            SELECT registration_id, customer_name, consultant, registration_no,
                   folder_lined_up_on, folder_given_to_accounts_on,
                   days_to_accounts, booking_to_registration_days
              FROM v_folder_tat
             ORDER BY folder_lined_up_on DESC NULLS LAST, registration_id DESC
        """)
    except Exception:
        log.exception("folder tat failed")
        return {"rows": [], "total": 0, "with_dates": 0, "avg_days": None,
                "over_3_days": 0}

    out = []
    for r in rows:
        out.append({
            "id": r["registration_id"],
            "customer": r["customer_name"],
            "consultant": r["consultant"],
            "registration_no": r["registration_no"],
            "lined_up": r["folder_lined_up_on"].isoformat() if r["folder_lined_up_on"] else None,
            "to_accounts": r["folder_given_to_accounts_on"].isoformat() if r["folder_given_to_accounts_on"] else None,
            "days": r["days_to_accounts"],
        })

    timed = [x["days"] for x in out if x["days"] is not None]
    # A folder cannot reach accounts before it was lined up, and one row says it
    # did by ten days - the workbook has those two dates the wrong way round.
    # Averaging it in turned a real 0.2 days into -0.1, which reads as paperwork
    # arriving before it exists. Counted and reported instead of silently kept
    # or silently dropped.
    sane = [d for d in timed if d >= 0]
    return {
        "rows": out,
        "total": len(out),
        "with_dates": len(timed),
        # Rounded to one place: this is a count of days, and two decimals on it
        # implies a precision the source dates do not have.
        "avg_days": round(sum(sane) / len(sane), 1) if sane else None,
        "same_day": sum(1 for d in sane if d == 0),
        "over_3_days": sum(1 for d in sane if d > 3),
        "impossible": len(timed) - len(sane),
    }


@app.get("/api/composition", tags=["dashboard"])
def composition(period: str | None = Query(None, description="Month label; defaults to the active one")):
    """
    Part-to-whole cuts of the month, for the panels that read as shares.

    Everything here answers "of the whole, how much is X" rather than "how many
    X over time", which is why these are the only charts on the sheet drawn as
    rings. The cuts were chosen because they have few enough categories to read
    as one: the order book sits in four states, the dealership sells four model
    families, and bookings split two ways by team and by where the car came
    from. Colour is the exception with twelve, so it is capped.

    The weekday block is not a share at all - it is here because it comes from
    the same two tables and answers the question the shares provoke: enquiries
    peak midweek while bookings land at the weekend, which is a staffing fact
    rather than a sales one.
    """
    empty = {"period": None, "order_book": [], "by_model": [], "by_colour": [],
             "by_origin": [], "by_team": [], "weekday": []}
    if not is_db_ready():
        return empty

    # The sheets shout their statuses in SQL-speak. On a client-facing panel
    # they are read by people, not by the loader.
    LABEL = {"BOOKED": "Booked", "ALLOTED": "Allotted",
             "NO_STOCK": "Awaiting stock", "RETAILED": "Retailed",
             "FRESH_CAR": "Fresh car", "PUNCHED_CAR": "Punched car"}

    def pairs(rows, cap=None):
        """[{name, value}], largest first, with a capped tail folded into Other."""
        out = [{"name": LABEL.get(r["name"], r["name"] or "Unspecified"),
                "value": r["n"]} for r in rows]
        out.sort(key=lambda d: -d["value"])
        if cap and len(out) > cap:
            spill = sum(d["value"] for d in out[cap:])
            out = out[:cap] + ([{"name": "Other", "value": spill}] if spill else [])
        return out

    try:
        with session() as cx:
            p = cx.execute(
                "SELECT label FROM dim_period WHERE upper(label) = upper(%s)" if period else
                "SELECT label FROM dim_period WHERE is_active",
                (period,) if period else ()).fetchone()
            if not p:
                return empty

            order_book = cx.execute("""
                SELECT fulfilment_status::text AS name, count(*) AS n
                  FROM booking WHERE is_current_period
                 GROUP BY 1
            """).fetchall()

            by_model = cx.execute("""
                SELECT COALESCE(m.name, 'Unspecified') AS name, count(*) AS n
                  FROM booking b LEFT JOIN dim_model m USING (model_id)
                 WHERE b.is_current_period GROUP BY 1
            """).fetchall()

            by_colour = cx.execute("""
                SELECT COALESCE(c.name, 'Unspecified') AS name, count(*) AS n
                  FROM booking b LEFT JOIN dim_colour c USING (colour_id)
                 WHERE b.is_current_period GROUP BY 1
            """).fetchall()

            by_origin = cx.execute("""
                SELECT COALESCE(car_origin::text, 'Unspecified') AS name, count(*) AS n
                  FROM booking WHERE is_current_period GROUP BY 1
            """).fetchall()

            by_team = cx.execute("""
                SELECT COALESCE(t.name, 'Unassigned') AS name, count(*) AS n
                  FROM booking b LEFT JOIN dim_team t USING (team_id)
                 WHERE b.is_current_period GROUP BY 1
            """).fetchall()

            # One row per weekday whether or not anything happened on it, so a
            # quiet Wednesday is a short bar rather than a missing one.
            weekday = cx.execute("""
                WITH d AS (SELECT generate_series(1, 7) AS dow)
                SELECT d.dow,
                       to_char(date '2026-01-05' + (d.dow - 1), 'Dy') AS day,
                       (SELECT count(*) FROM lead l
                         WHERE l.is_current_period AND l.created_at IS NOT NULL
                           AND extract(isodow FROM l.created_at) = d.dow) AS enquiries,
                       (SELECT count(*) FROM booking b
                         WHERE b.is_current_period AND b.booking_date IS NOT NULL
                           AND extract(isodow FROM b.booking_date) = d.dow) AS bookings
                  FROM d ORDER BY d.dow
            """).fetchall()

    except Exception:
        log.exception("composition failed")
        return empty

    return {
        "period": p["label"],
        "order_book": pairs(order_book),
        "by_model": pairs(by_model),
        # Twelve colours is a ring nobody can read; the tail is summed, not lost.
        "by_colour": pairs(by_colour, cap=6),
        "by_origin": pairs(by_origin),
        "by_team": pairs(by_team),
        "weekday": [{"day": r["day"], "enquiries": r["enquiries"],
                     "bookings": r["bookings"]} for r in weekday],
    }


@app.get("/api/funnel", tags=["dashboard"])
def funnel():
    """Enquiry to retail funnel, with the target for each stage where one is set."""
    if is_db_ready():
        try:
            stages = fetch_one("SELECT * FROM v_sales_funnel")
            targets = fetch_one(_TARGETS_SQL) or {}
            if stages:
                return {
                    "period": stages["period"],
                    "stages": [
                        {"stage": "Enquiries",   "value": stages["enquiries"],   "target": targets.get("leads_target")},
                        {"stage": "Qualified",   "value": stages["qualified"],   "target": None},
                        {"stage": "Test drives", "value": stages["test_drives"], "target": targets.get("td_target")},
                        {"stage": "Bookings",    "value": stages["bookings"],    "target": targets.get("booking_target")},
                        {"stage": "Retails",     "value": stages["retails"],     "target": targets.get("retail_target")},
                    ],
                }
        except Exception:
            pass
    return fallback.get_funnel()


@app.get("/api/leaderboard", tags=["dashboard"])
def leaderboard():
    """Consultants ranked by their gap to booking target."""
    if is_db_ready():
        try:
            res = fetch_all("SELECT * FROM v_consultant_leaderboard")
            if res:
                return res
        except Exception:
            pass
    return fallback.get_leaderboard()


@app.get("/api/scorecards", tags=["dashboard"])
def scorecards(row_kind: str | None = Query(None, pattern="^(CONSULTANT|TEAM_TOTAL|GRAND_TOTAL|OTHER)$")):
    if is_db_ready():
        try:
            if row_kind:
                res = fetch_all("SELECT * FROM v_consultant_scorecard WHERE row_kind = %s", (row_kind,))
            else:
                res = fetch_all("SELECT * FROM v_consultant_scorecard")
            if res:
                return res
        except Exception:
            pass
    return fallback.get_scorecards(row_kind)


@app.get("/api/stock", tags=["dashboard"])
def stock(status: str | None = None, model: str | None = None):
    if is_db_ready():
        try:
            return fetch_all(*filtered(
                "SELECT * FROM v_stock",
                [("stock_status::text = upper(%s)", status),
                 ("model ILIKE %s", model)],
                "ORDER BY stock_aging_days DESC NULLS LAST",
            ))
        except Exception:
            pass
    return []


@app.get("/api/stock/availability", tags=["dashboard"])
def stock_availability():
    if is_db_ready():
        try:
            res = fetch_all("""
                SELECT * FROM v_stock_availability
                ORDER BY model, variant, colour
            """)
            if res:
                return res
        except Exception:
            pass
    return fallback.get_snapshot().get("avail", [])


@app.get("/api/stock/ageing", tags=["dashboard"])
def stock_ageing():
    """
    Ageing bands per model FAMILY.

    v_stock_ageing keys on the model name, so TAIGUN and TAIGUN (FL) arrive as
    two separate models while v_model_position - and every table on the page -
    reports them as one TAIGUN of 47 units. Rolling up here keeps the two
    panels telling the same story; avg_days is re-weighted by units rather
    than averaged, or the smaller variant would count as much as the larger.
    """
    if is_db_ready():
        try:
            res = fetch_all("""
                SELECT COALESCE(m.family, a.model) AS model,
                       a.ageing_bucket,
                       sum(a.units)::int AS units,
                       round(sum(a.avg_days * a.units) / NULLIF(sum(a.units), 0), 1) AS avg_days,
                       max(a.max_days) AS max_days
                FROM v_stock_ageing a
                LEFT JOIN dim_model m ON m.name = a.model
                GROUP BY 1, 2
                ORDER BY 1, 2
            """)
            if res:
                return res
        except Exception:
            pass
    return fallback.get_stock_ageing()


@app.get("/api/models/position", tags=["dashboard"])
def model_position():
    if is_db_ready():
        try:
            res = fetch_all("SELECT * FROM v_model_position ORDER BY total_stock DESC, model")
            if res:
                return res
        except Exception:
            pass
    return fallback.get_models_position()


@app.get("/api/models/demand", tags=["dashboard"])
def model_demand():
    if is_db_ready():
        try:
            res = fetch_all("SELECT * FROM v_model_demand ORDER BY enquiries DESC")
            if res:
                return res
        except Exception:
            pass
    return fallback.get_models_demand()


@app.get("/api/leads/sourcewise", tags=["dashboard"])
def leads_sourcewise():
    if is_db_ready():
        try:
            res = fetch_all("SELECT * FROM v_leads_sourcewise ORDER BY leads DESC")
            if res:
                return res
        except Exception:
            pass
    return fallback.get_leads_sourcewise()


@app.get("/api/bookings", tags=["dashboard"])
def bookings(
    current_only: bool = True,
    status: str | None = None,
    consultant: str | None = None,
    limit: int = Query(200, le=1000),
):
    if is_db_ready():
        try:
            sql, params = filtered(
                "SELECT * FROM v_bookings",
                [("is_current_period", True if current_only else None),
                 ("fulfilment_status::text = %s", status),
                 ("consultant ILIKE %s", consultant)],
                "ORDER BY booking_date DESC NULLS LAST LIMIT %s",
            )
            res = fetch_all(sql, params + (limit,))
            if res:
                return res
        except Exception:
            pass
    return fallback.get_bookings(limit)


@app.get("/api/backorders", tags=["dashboard"])
def backorders():
    """Orders with no car against them, longest wait first."""
    if is_db_ready():
        try:
            # Sorted so the current month leads: the carry-over rows are all
            # ~500 days old and would otherwise fill the whole panel and
            # squash this month's orders - which are the ones still actionable.
            res = fetch_all("""
                SELECT * FROM v_backorders
                ORDER BY is_current_period DESC, days_waiting DESC NULLS LAST
            """)
            if res:
                return res
        except Exception:
            pass
    return fallback.get_backorders()


@app.get("/api/attachments", tags=["dashboard"])
def attachments():
    if is_db_ready():
        try:
            res = fetch_one("SELECT * FROM v_attachment_rates")
            if res:
                return res
        except Exception:
            pass
    return fallback.get_attachments()


@app.get("/api/commitments", tags=["dashboard"])
def commitments():
    if is_db_ready():
        try:
            res = fetch_all("""
                SELECT * FROM v_booking_commitments
                ORDER BY consultant_label,
                         array_position(ARRAY['TILL 12TH','13 TO 19','20 TO 26'], window_label)
            """)
            if res:
                return res
        except Exception:
            pass
    return fallback.get_commitments()


@app.get("/api/data-quality", tags=["dashboard"])
def data_quality():
    """
    Disagreements between the workbook's tabs, found during the load.
    """
    if is_db_ready():
        try:
            res = fetch_all("""
                SELECT * FROM v_data_quality
                ORDER BY array_position(ARRAY['high','medium','low'], severity)
            """)
            if res:
                return res
        except Exception:
            pass
    return fallback.get_data_quality()


@app.get("/api/meta", tags=["dashboard"])
def meta():
    """Provenance: which workbook this data came from and when it was loaded."""
    if is_db_ready():
        try:
            run = fetch_one("""
                SELECT source_file, file_modified, finished_at, row_counts, notes
                FROM etl_run ORDER BY run_id DESC LIMIT 1
            """)
            period = fetch_one("SELECT label, period_start, period_end FROM dim_period LIMIT 1")
            if run:
                return {"latest_load": run, "period": period}
        except Exception:
            pass
    return fallback.get_meta()


# =====================================================================
# Agent tool surface
# =====================================================================

@app.get("/agent/availability", tags=["agent: client"])
def agent_availability(
    model: str | None = Query(None, description="Model or family, e.g. Virtus, Taigun"),
    variant: str | None = Query(None, description="Trim, e.g. GT Line AT"),
    colour: str | None = Query(None, description="Colour name, e.g. Candy White"),
):
    """
    Is a car available right now? Substring matching on each field, so a customer's
    loose phrasing ("a white Virtus") still resolves.
    """
    if is_db_ready():
        try:
            return fetch_all(*filtered(
                "SELECT * FROM agent_vehicle_availability",
                [("(model ILIKE '%%' || %s || '%%' OR model_family ILIKE '%%' || %s || '%%')", model),
                 ("variant ILIKE '%%' || %s || '%%'", variant),
                 ("colour ILIKE '%%' || %s || '%%'", colour)],
                "ORDER BY model, variant, colour",
            ))
        except Exception:
            pass
    avail = fallback.get_snapshot().get("avail", [])
    res = []
    for a in avail:
        if model and model.lower() not in (a.get("model") or "").lower():
            continue
        if variant and variant.lower() not in (a.get("variant") or "").lower():
            continue
        if colour and colour.lower() not in (a.get("colour") or "").lower():
            continue
        res.append(a)
    return res


# PII POLICY (2026-10-08): customer phone numbers are no longer stored, so an
# order can only be found by name. A lookup by mobile used to compare against
# the stored number; it would now match nothing and the agent would tell a
# customer they have no order. A request with only a mobile is refused with a
# message the agent can act on ("ask for the name on the booking"). The
# parameter is still accepted, and ignored, so an agent that sends both keeps
# working.
@app.get("/agent/order-status", tags=["agent: client"])
def agent_order_status(
    name: str | None = Query(None, description="Customer name, full or partial"),
    mobile: str | None = Query(None, description="Ignored - phone numbers are not stored"),
):
    if not name:
        raise HTTPException(
            400, "Search by the customer's name. Phone numbers are not stored "
                 "(customer PII is redacted), so an order cannot be found by phone.")
    if is_db_ready():
        try:
            return fetch_all(*filtered(
                "SELECT * FROM agent_order_status",
                [("customer_name ILIKE '%%' || %s || '%%'", name)],
                "ORDER BY booking_date DESC NULLS LAST",
            ))
        except Exception:
            pass
    backorders = fallback.get_backorders()
    return [b for b in backorders
            if name.lower() in (b.get("customer_name") or "").lower()]


@app.get("/agent/model-catalogue", tags=["agent: client"])
def agent_model_catalogue():
    """Models and trims the dealership actually transacts, with live free stock."""
    if is_db_ready():
        try:
            return fetch_all("""
                SELECT m.name AS model, m.family, m.is_cbu,
                       dv.name AS variant, dv.transmission, dv.long_model_text,
                       count(v.vehicle_id) FILTER (WHERE v.stock_status = 'FREESTOCK') AS free_units
                FROM dim_model m
                JOIN dim_variant dv ON dv.model_id = m.model_id
                LEFT JOIN vehicle v ON v.variant_id = dv.variant_id
                GROUP BY m.name, m.family, m.is_cbu, dv.name, dv.transmission, dv.long_model_text
                ORDER BY m.name, dv.name
            """)
        except Exception:
            pass
    avail = fallback.get_snapshot().get("avail", [])
    return avail


@app.get("/agent/snapshot", tags=["agent: service"])
def agent_snapshot():
    """One call that answers "how is the dealership doing this month?"."""
    if is_db_ready():
        try:
            res = fetch_one("SELECT * FROM agent_dealership_snapshot")
            if res:
                return res
        except Exception:
            pass
    return fallback.get_kpi()


@app.get("/agent/consultant", tags=["agent: service"])
def agent_consultant(name: str = Query(..., description="Consultant name, full or partial")):
    """A single consultant's scorecard against target."""
    if is_db_ready():
        try:
            rows = fetch_all("""
                SELECT * FROM v_consultant_scorecard
                WHERE row_kind = 'CONSULTANT' AND consultant ILIKE '%%' || %s || '%%'
            """, (name,))
            if rows:
                return rows
        except Exception:
            pass
    board = fallback.get_leaderboard()
    matched = [r for r in board if name.lower() in (r.get("consultant") or "").lower()]
    if not matched:
        raise HTTPException(404, f"no consultant matching {name!r}")
    return matched


@app.get("/agent/action-list", tags=["agent: service"])
def agent_action_list():
    """
    What needs chasing today, in one payload: stock at risk, orders with no car,
    deals missing from the CRM.
    """
    if is_db_ready():
        try:
            return {
                "stock_past_retail_deadline": fetch_all("""
                    SELECT chassis_number, model, variant, colour,
                           stock_aging_days, nadcon_retail_date
                    FROM v_stock
                    WHERE stock_status = 'FREESTOCK' AND nadcon_retail_date < CURRENT_DATE
                    ORDER BY nadcon_retail_date
                """),
                "ageing_over_90_days": fetch_all("""
                    SELECT chassis_number, model, variant, colour, stock_aging_days
                    FROM v_stock
                    WHERE stock_status = 'FREESTOCK' AND stock_aging_days > 90
                    ORDER BY stock_aging_days DESC
                """),
                "backorders": fetch_all("""
                    SELECT customer_name, consultant, model, variant, colour,
                           days_waiting, matching_free_units
                    FROM v_backorders ORDER BY days_waiting DESC NULLS LAST
                """),
                "bookings_missing_crm_entry": fetch_all("""
                    SELECT customer_name, consultant, model, variant, booking_date
                    FROM v_bookings
                    WHERE is_current_period AND crm_entry_done IS FALSE
                    ORDER BY booking_date
                """),
            }
        except Exception:
            pass
    return fallback.get_action_list()


# =====================================================================
# Static dashboard
# =====================================================================

class RevalidatingStatic(StaticFiles):
    """
    Static files that must be revalidated rather than reused blind.

    The front end is served from fixed paths (`assets/bundle.js` has no content
    hash), and Starlette sends only ETag and Last-Modified. With no
    Cache-Control at all a browser falls back to *heuristic* caching - it may
    reuse the file for a while without asking - so a rebuilt dashboard kept
    running the previous bundle until someone hard-reloaded.

    `no-cache` does not mean "do not store": the browser still caches and still
    gets a cheap 304 from the ETag. It only has to ask first.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


if STATIC.exists():
    app.mount("/static", RevalidatingStatic(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def dashboard():
    index_file = STATIC / "index.html"
    if index_file.exists():
        return FileResponse(index_file, headers={"Cache-Control": "no-cache"})
    return {"message": "Volkswagen Elite Motors CRM API is running."}


@app.get("/snapshot", include_in_schema=False)
def snapshot_page():
    snap_file = STATIC / "snapshot.html"
    if snap_file.exists():
        return FileResponse(snap_file)
    return FileResponse(STATIC / "index.html")


@app.get("/health", tags=["system"])
def health():
    db_status = "connected" if is_db_ready() else "fallback_snapshot"
    return {
        "status": "ok",
        "database": db_status,
        "environment": "vercel" if os.environ.get("VERCEL") else "local",
        "config": _config_report(),
    }


def _config_report() -> dict:
    """Which configuration the running process can actually see.

    A variable set in a hosting dashboard and a variable present in the
    process are different facts, and when they disagree there is no way to
    tell from the outside which one is wrong - the panel says the key is
    missing, the dashboard says it is right there, and both are telling the
    truth about different things. This reports what the process has.

    Names and booleans only, never a value. It discloses nothing that the
    503 from /api/calls does not already state, and the service name is not
    a secret - it is the thing you need in order to know whether the page
    you edited belongs to the process that is answering you.

    `perfox_named` catches the failure this was written for: a variable whose
    name carries a trailing space or a typo is set, and is invisible, because
    the dashboard renders it identically to the correct one.
    """
    return {
        # Render injects these; absent means this is not a Render instance.
        "service": os.environ.get("RENDER_SERVICE_NAME") or None,
        "commit": (os.environ.get("RENDER_GIT_COMMIT") or "")[:7] or None,
        "database_url": bool(os.environ.get("DATABASE_URL", "").strip()),
        "perfox_api_key": bool(os.environ.get("PERFOX_API_KEY", "").strip()),
        "perfox_named": sorted(k for k in os.environ if "PERFOX" in k.upper()),
    }


# ---------------------------------------------------------------------
# Every other path belongs to the front end.
#
# The dashboard has real routes now - /sales, /accounts, /people - rather than
# hashes, which means the browser asks this server for them: on a direct visit,
# on a refresh, and on every link somebody pastes to a colleague. Without this
# they answered 404 and only the bare "/" worked, which is the classic way a
# single-page app looks broken to everyone except the person who clicked their
# way there.
#
# Registered last, so it catches only what nothing else claimed. The API is
# excluded explicitly: a typo under /api should come back as a JSON 404, not as
# a page of HTML that a fetch will fail to parse and report as something else
# entirely.
# ---------------------------------------------------------------------
_NOT_THE_APP = ("api/", "mcp", "static/", "docs", "redoc", "openapi.json", "health")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path.startswith(_NOT_THE_APP):
        raise HTTPException(status_code=404, detail="Not found")
    index_file = STATIC / "index.html"
    if index_file.exists():
        # no-cache for the same reason "/" uses it: the HTML names a hashed
        # bundle, and a stale copy points at a file that no longer exists.
        return FileResponse(index_file, headers={"Cache-Control": "no-cache"})
    return {"message": "Volkswagen Elite Motors CRM API is running."}
