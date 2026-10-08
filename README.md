# Volkswagen Elite Motors — DSR database & dashboard

A PostgreSQL database and dashboard built from `DSR August 2026.xlsx`, the Daily
Sales Report for Volkswagen Elite Motors (authorised dealership, Hosur Road,
Bengaluru). It is the data layer the dealership's **service agent** and **client
agent** will read from.

The workbook is 22 hand-maintained tabs. This turns the row-level ones into a
normalised schema, rebuilds every pivot tab as a view, and reports where the tabs
disagree with each other instead of quietly picking a winner.

It is not a read-only report. Records are entered through the dashboard, and
**every open dashboard repaints itself the moment the database changes** —
including changes that did not come from the dashboard.

- **Dashboard** — `python run.py`, then <http://127.0.0.1:8000>
- **API docs** — <http://127.0.0.1:8000/docs>
- **Shareable snapshot** — <https://claude.ai/code/artifact/1868430f-61c6-4158-b015-317acac035e1>
  (a frozen export, no server needed — the one to send your manager)

---

## Quick start

```bash
pip install -r requirements.txt
```

```bash
powershell -File tools/pg.ps1 start
```

```bash
python tools/sql.py -f db/schema.sql && python tools/sql.py -f db/triggers.sql && python tools/sql.py -f db/test_drives.sql && python tools/sql.py -f db/pii.sql && python -m etl.load_dsr && python tools/sql.py -f db/views.sql
```

> **Customer PII is never stored (policy, 2026-10-08).** Phone numbers, email
> addresses and postal addresses are replaced with `[REDACTED]` on every way
> in — workbook, CSV, the forms, the agent APIs — by `etl/pii.py`, and again
> by database triggers in `db/pii.sql` for anything that writes to the
> database directly. Phones and emails typed inside notes or chat messages are
> cut out of the text. Customer names are kept. To change the **live**
> database, use `tools/migrate.py`, which dry-runs by default; existing rows are
> cleaned with `db/pii_backfill.sql`.

```bash
python run.py
```

To refresh after the workbook is updated, re-run `python -m etl.load_dsr`. It
replaces the rows that came from the workbook and **leaves hand-entered records
alone** — see *Entering data* below. Then `python tools/build_snapshot.py` for a
fresh shareable page.

---

## What is in the database

Schema `dsr`, 18 tables and 21 views.

### Reference

| Table | Rows | Notes |
|---|---|---|
| `dim_consultant` | 30 | Folds `ABINAND P` / `ABHINAND P` / `Abinand P` onto one row. 9 are currently on the floor; the rest appear only in the 2024 historical dump and are `is_active = false`. |
| `dim_team` | 2 | Prince and Nethra — the DSR names teams after their managers. |
| `dim_model` | 6 | Taigun, Taigun (FL), Virtus, Tayron, Golf GTI, Tiguan R-Line. `family` folds the facelift into `TAIGUN`. |
| `dim_variant` | 28 | Trim plus the factory `model_code` stock is ordered against (`D22LDY`, `CW2HFZ`). |
| `dim_colour` | 18 | VW paint names and codes. |
| `dim_lead_source` | 12 | Maps both vocabularies — CRM exports say `Walk In`/`Central Webin`, DSR tabs say `WALKIN`/`CRM`. |
| `dim_period` | 1+ | `AUG2026` is active. New months appear as records are filed against them. |

### Facts

| Table | Rows | From |
|---|---|---|
| `vehicle` | 107 | Stock & Allotted + Reg Report, keyed on chassis number |
| `lead` | 2,154 | Leads (367, August) + TD Leads (1,787, 2024 historical) |
| `test_drive` | 31 | TD tab — **note: this tab is stale**, see below |
| `booking` | 133 | Five overlapping tabs, each tagged with `source_sheet` |
| `allotment` | 20 | Alloted tab |
| `registration` | 21 | Reg Report — RTO milestones plus the finance/insurance/EW/SVP mix |

### Targets

Targets are set by management and cannot be derived from the facts, so they are
stored: `target_consultant_scorecard` (24), `target_channel_funnel` (8),
`target_booking_commitment` (33), `target_daily_tracker` (14).

`etl_run` records one row per load with per-table counts and any warnings.

### Views

Pivot tabs in the workbook (Free Stock, Modewise, VW Report, Leads Sourcewise,
ZOHO Entry, Modelwise Booking, Comparision) are **not** tables — they are rebuilt
as views so they can never drift from the rows underneath.

`v_stock`, `v_stock_availability`, `v_free_stock_by_colour`, `v_stock_ageing`,
`v_model_position`, `v_model_demand`, `v_bookings`, `v_order_book`,
`v_backorders`, `v_leads_sourcewise`, `v_consultant_scorecard`,
`v_consultant_leaderboard`, `v_booking_commitments`, `v_sales_funnel`,
`v_daily_kpi`, `v_attachment_rates`, `v_folder_tat`, `v_data_quality`.

Two of those matter more than the rest:

- **`v_bookings`** is every tab's version of every row — 133 of them. Right for
  audit, wrong for operations.
- **`v_order_book`** is one row per real customer order — 72. The same order is
  written on up to three tabs, so anything that counts orders or drives a chase
  list reads this one. Without it the back-order queue reads 34 instead of 21 and
  the same customer gets called twice.

---

## Entering data, and why the dashboard moves on its own

### How a change reaches the screen

```
write (dashboard / psql / loader / agent)
  → AFTER trigger on the table  → pg_notify('dsr_change', …)   db/triggers.sql
  → one LISTEN connection held by the API                       app/events.py
  → coalesced ~400ms, fanned out as server-sent events
  → browser refetches and repaints                              /api/events
```

The notification is raised by a **database trigger**, not by the API. That is the
whole point: the database sees every write, so a record entered in the dashboard,
a row inserted with `tools/sql.py`, a workbook reload, or a future agent writing
directly all land on the same trigger. No dashboard can go stale because a write
took a different route in.

`GET /api/live-status` shows whether the listener is attached and how many
dashboards are watching. The browser's `EventSource` reconnects by itself; the
indicator in the header reads `live`, `updated · N tables`, or `reconnecting`.

The LISTEN runs on a background thread with a synchronous connection rather than
on the event loop with an async one. psycopg's async mode refuses to run on the
`ProactorEventLoop` that asyncio uses by default on Windows, and the usual
workaround — forcing `WindowsSelectorEventLoopPolicy` process-wide — only works
if the app is started through `run.py` and breaks silently under
`uvicorn app.main:app`. A thread behaves the same way everywhere.

### The forms

**+ New entry** in the header opens a drawer with six tabs: Enquiry, Booking,
Test drive, Stock, Allot, Retail. `Ctrl`/`Cmd`+`Enter` saves, and the form clears
itself for the next one, so a run of entries never needs the mouse. The order-book
panel also edits in place — change a booking's status or tick its CRM box and it
is written immediately.

Payloads speak the dealership's language, not the schema's:

```json
POST /api/bookings
{ "customer_name": "Meera Krishnan", "consultant": "sanjeev",
  "source": "Walkin", "model": "Virtus", "variant": "GT Line AT",
  "colour": "Candy White", "booking_amount": 30000 }
```

`etl/dimensions.py` resolves those names to foreign keys and creates the
dimension row the first time a name is seen — the same code the bulk loader uses,
so the API cannot invent a second `SANJEEV` beside the loader's. A new trim
arriving mid-month needs no schema change.

| Endpoint | |
|---|---|
| `POST /api/leads` | a new enquiry |
| `POST /api/bookings` · `PATCH /api/bookings/{id}` | an order, or a change to one |
| `POST /api/test-drives` | a drive given |
| `POST /api/vehicles` | a car into stock (upserts on chassis number) |
| `POST /api/allotments` | give a car to a booking — one transaction, writes the allotment and moves both statuses |
| `POST /api/registrations` | a retail, plus the attachment mix |
| `DELETE /api/entries/{entity}/{id}` | remove a hand-entered row |
| `GET /api/entry-options` | what the forms offer, from the dimension tables |
| `GET /api/recent-activity` | what has been entered here |

### Hand-entered rows survive a workbook reload

Every fact row carries `origin`: `WORKBOOK` or `MANUAL`. The loader deletes and
rebuilds only `WORKBOOK` rows, so a reload refreshes the source data and leaves
the dealership's own work in place. It says so when it runs:

```
notes:
  - kept 2 manually entered booking(s) through the reload
```

Deleting a workbook row through the API is refused with a 409 — it belongs to the
source file and the next load would bring it straight back.

`vehicle` is never deleted, only upserted on chassis number, so a car keeps its id
and anything referencing it stays intact. The few foreign keys that can cross
origins (a manual booking allotted a workbook car) are `ON DELETE SET NULL`.

### The scorecard is counted, not copied

Consultant bookings and retails are **counted from the fact tables**, so an entry
moves the leaderboard at once. That is only safe because the two agree exactly on
load: every consultant's workbook `booking_achieved` and `retail_achieved` matches
their row count in `booking` and `registration`, to the unit.

Enquiries and test drives are the exception, and are baseline + live: the August
lead export carries no consultant (so only the scorecard knows the per-person
split) and the test-drive tab was never refreshed. For those two the workbook
figure is the baseline and only `MANUAL` rows are added on top — nothing is
double counted.

### Reporting month

`dim_period` has one active row, and every headline view is scoped to it (a
partial unique index enforces the "one" — without it the KPI views would return a
row per month as soon as a second existed).

A record dated in a month that has no period **creates** it rather than being
dropped or folded into the month on screen. So a booking dated 1 September
creates `SEP2026`, and the response says so:

```json
{ "booking_id": 139, "period": "SEP2026", "in_active_period": false }
```

The dashboard turns that into a toast with a *View SEP2026* button. Switch months
from the header dropdown, or `POST /api/period/{label}/activate` — which realigns
`is_current_period` across the fact tables in the same transaction, so every view
moves together.

The entry forms default their date to today, unless today falls outside the month
being reported on, in which case they default to that month's last day and say
why. Today is 10 September and the workbook is August, so entries default to
31 August — which is what makes the figures on screen respond.

---

## The agent surface

The `agent_*` views and `/agent/*` endpoints are the layer the two agents should
use. They hide the five-overlapping-booking-tabs problem and the two lead
populations behind stable column names, so an agent never has to know which tab a
row came from.

**Client agent** — customer-facing:

| Endpoint | Answers |
|---|---|
| `GET /agent/availability?model=&variant=&colour=` | "Do you have a white Virtus GT Line AT?" Substring matching, so loose phrasing resolves. |
| `GET /agent/order-status?name=` | "Where is my car?" Returns a stage: booked → awaiting stock → car allotted → invoiced → registered → delivered. Requires a name; it will not return the whole order book. (Lookup by `?mobile=` was removed under the PII policy, 2026-10-08 — phone numbers are not stored.) |
| `GET /agent/model-catalogue` | Models and trims the dealership actually transacts, with live free stock. |

**Service agent** — internal:

| Endpoint | Answers |
|---|---|
| `GET /agent/snapshot` | "How is the dealership doing this month?" in one call. |
| `GET /agent/consultant?name=` | One consultant's scorecard against target. |
| `GET /agent/action-list` | What needs chasing: stock past its retail deadline, ageing over 90 days, back orders, bookings missing from the CRM. |

---

## August 2026, as loaded

| | Actual | Target |
|---|---|---|
| Enquiries | 367 | 450 |
| Qualified | 361 | — |
| Test drives | 128 | 300 |
| Bookings | 42 | 84 |
| Retails | 18 | 66 |

69 cars free, 20 allotted, 20 standing over 90 days. ₹9.43 L booking amount
collected. Average allotment turnaround 3.5 days.

Everything reconciles against the workbook: all five booking tabs match their
sheet row counts exactly, both lead populations match (367 / 1,787), the SC
Performance grand total matches (355 / 345 / 42 / 18), and lead sources match
channel by channel.

---

## Where the workbook disagrees with itself

`v_data_quality` reports these; the dashboard shows them in a panel. They are
findings about the source, not bugs in the load.

| Severity | Finding |
|---|---|
| high | **The TD tab is stale.** It holds a November 2024 export, not August 2026 activity. Funnel views take test drives from the scorecard's TD ACH column (128) instead of counting the 31 rows on that tab. |
| high | **15 August bookings were never punched into the CRM** (ZOHO ENTRY = NO). Until someone enters them the dealership is not credited for them in VW-side reporting. |
| high | **34 free units are past their NADCON retail deadline**, the oldest standing 216 days against a deadline of 31 Jan 2026. |
| medium | **The Comparision tab disagrees with the base tabs** — it reports 350 enquiries / 37 bookings / 20 retails where the rows give 367 / 42 / 18. |
| medium | **Daily Tracker holds two conflicting target blocks** — the upper block sets Akhilesh's enquiry target at 63, the lower at 45. Both are loaded, tagged `BLOCK_1` / `BLOCK_2`; views read `BLOCK_2` (the full roster). |
| medium | **The August lead export is missing consultant, status and rating columns**, so per-consultant enquiry counts have to come from the scorecard rather than from `lead`. |
| medium | **The registration report stops at accounts.** On the Reg Report tab every column from FOLDER SENT TO HO rightwards — invoice date, registration date, registration number, VOIW id, delivery date — is blank on all 21 rows. The tab tracks the folder as far as accounts and no further, so fulfilment stage is read from the status column instead. |

Two more things worth knowing:

- **Taigun bookings vs Taigun (FL) stock.** The stock tabs distinguish the
  facelift; the booking tabs write plain `TAIGUN` for both. A model-name join puts
  35 free Taiguns against 0 Taigun bookings. `v_model_position` and
  `v_model_demand` roll up to `family` so supply and demand are comparable.
- **Back orders: 11 or 21?** 11 were taken in August; 21 are open across the whole
  order book, the longest waiting 495 days, and exactly one of them could be
  filled from free stock today. Both numbers are correct for their scope and the
  dashboard labels which is which. (Counting `v_bookings` instead of
  `v_order_book` gives 34 — that figure is double-counted.)

- **DWA and VW OFFERS are not amounts.** On the Reg Report, DWA reads YES/NO and
  VW OFFERS reads `VW-40K, EXCH-20K, LOY-40K` — a factory contribution plus an
  exchange bonus plus a loyalty bonus. They are stored as a boolean and as text;
  typing them as numerics silently emptied both columns on the first load.

---

## Layout

```
DSR August 2026.xlsx        source workbook
db/schema.sql               tables, enums, indexes, comments
db/triggers.sql             change notification (pg_notify)
db/pii.sql                  customer PII redaction triggers (policy 2026-10-08)
db/pii_backfill.sql         one-off: redact PII already in the database
db/views.sql                analytical + agent views (re-runnable)
etl/pii.py                  customer PII redaction, used by every ingestion path
tools/migrate.py            apply SQL to the live DB in one transaction, dry run first
etl/normalize.py            cleaning and canonicalisation
etl/dimensions.py           dimension resolution, shared by loader and API
etl/load_dsr.py             workbook -> Postgres (keeps MANUAL rows)
app/main.py                 FastAPI: /api/* dashboard, /agent/* tools
app/entry.py                writes, the event stream, period switching
app/write.py                payload validation and the writers
app/events.py               LISTEN -> server-sent events
app/db.py                   connection pool
app/static/index.html       the dashboard (live, with entry forms)
app/static/snapshot.html    generated standalone snapshot
tools/pg.ps1                start / stop / status the server
tools/sql.py                query tool (stands in for psql)
tools/build_snapshot.py     rebuild the standalone snapshot
tools/snapshot_template.html
run.py                      python run.py
```

---

## Notes on the PostgreSQL install

PostgreSQL 17.11 lives at `C:\Users\Praneet\pgsql17`, data directory
`C:\Users\Praneet\pgsql17\data`, port 5432, database `elite_dsr`, user `postgres`,
password `postgres` (local development only — change it before this goes anywhere
shared).

It was installed from the PostgreSQL binaries published on Maven Central rather
than through winget or the EnterpriseDB installer: **`get.enterprisedb.com` is
blocked on this network** (CloudFront returns 403 at the host level), and that CDN
is what winget, Chocolatey and Scoop all download from. The binaries are the same
server build; what they do not include is the client tools, which is why
`tools/sql.py` exists in place of `psql`.

Because there is no installer, there is no Windows service — start the server with
`tools/pg.ps1 start`. To register it as a service instead, see the comment block
at the top of that script (needs an Administrator shell).

Connection string is read from `DATABASE_URL` by both the loader and the app; see
`.env.example`.
