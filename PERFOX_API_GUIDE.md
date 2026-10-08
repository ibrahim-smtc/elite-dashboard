# Perfox API Integration Guide

This document contains the API endpoints required for the Perfox inbound/outbound agent to sync leads with the main CRM Database (Supabase).

---

## Customer PII is not stored (policy, 2026-10-08)

A customer's **phone number, email address and postal address are never
stored**. Every endpoint below still *accepts* them — sending one is not an
error — but the value is replaced with `[REDACTED]` before it reaches the
database, and a phone or email typed inside a message is cut out of the text
(`[PHONE REDACTED]`). The same rule is enforced by database triggers, so it
also applies to anything the agent writes to Supabase directly.

What this means for the agent:

- **Leads come back without a phone number.** `mobile` reads `[REDACTED]`. An
  outbound agent cannot call leads back from this data — the number has to
  come from somewhere that is allowed to hold it.
- **Orders are found by the customer's name**, not by phone.
  `get_order_status` takes a name only.
- **Customer names are kept** — they were not part of the instruction, and an
  order cannot be looked up without one.

---

## 0. Before anything else: can Perfox actually reach this API?

Perfox runs in the cloud. It cannot reach `localhost`, `127.0.0.1`, or a private
LAN address on your machine, no matter how the URL is written. If the agent has
no reachable URL it will not error — the model simply answers **without** data,
which reads as confident, detailed, and completely invented.

Two things must be true:

**1. The server listens on a public interface.** By default it binds to
loopback only. Start it with:

```bash
HOST=0.0.0.0 python run.py
```

**2. There is a public URL.** On a laptop that means a tunnel:

```bash
ngrok http 8000
```

Use the `https://….ngrok-free.app` address ngrok prints as the Base URL below.

> **Security — read this before opening the port.** `HOST=0.0.0.0` exposes the
> *whole* API, not just the agent routes. That includes destructive endpoints:
> `DELETE /api/periods/{label}` wipes a reporting month, and
> `POST /api/upload-report` replaces one. Always set `AGENT_API_KEY` (below)
> before exposing the app, keep the tunnel URL private, and shut the tunnel down
> when you are not testing. The API key protects `/api/crm/*` only.

### Authentication

Set a secret in `.env`:

```
AGENT_API_KEY=some-long-random-string
```

Every `/api/crm/*` request must then carry it, either way:

```
X-API-Key: some-long-random-string
Authorization: Bearer some-long-random-string
```

If `AGENT_API_KEY` is unset the routes stay open — convenient on loopback, unsafe
the moment the port is open.

---

## 1. Fetch Live Leads
This endpoint allows the Perfox agent to pull a fresh batch of uncontacted leads directly from the client's live Supabase database. These leads are auto-synced the moment a client uploads their daily tracking excel file.

**Endpoint**: `POST /api/crm/fetch-leads`
**Base URL**: `http://<your-server-ip>:8000` (Replace `<your-server-ip>` with the actual server IP/domain)
**Content-Type**: `application/json`

### Request Payload:
```json
{
  "limit": 50,          // Optional: how many to pull (default 50)
  "status": "New",      // Optional: default "New". Matched NULL-safely, so a
                        // lead nobody has touched counts as New.
  "period": "active",   // Optional: "active" (default) | "AUG2026" | "all"
  "search": null        // Optional: matches the lead's name
}
```

### Example cURL:
```bash
curl -X POST https://<your-public-url>/api/crm/fetch-leads \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"limit": 50, "status": "New"}'
```

### Expected Response:
An array of lead objects:
```json
[
  {
    "lead_id": 52196,
    "lead_name": "Nikilesh S",
    "mobile": "[REDACTED]",
    "source_id": 1,
    "source": "WALKIN",
    "consultant_id": 87,
    "consultant": "Sanjeev",
    "model_id": 1,
    "model": "VIRTUS",
    "variant_of_interest": null,
    "lead_status": "New",
    "qualified_stage": "Qualified",
    "rating": "Warm",
    "created_at": "2026-08-01T00:00:00",
    "period": "AUG2026"
  }
]
```

> Note: this endpoint previously had no period filter and matched
> `lead_status = 'New'` on a column that is NULL for every row the dashboard or
> a workbook writes. Since `NULL = 'New'` is never true in SQL, it could only
> ever return rows from the 1,800-row **2024** historical dump — a lead entered
> on the dashboard minutes earlier was invisible. Both are fixed; the default is
> now the active reporting month.

---

## 2. Push New Leads (Optional)
If the Perfox agent needs to ingest entirely *new* leads (e.g. from an inbound call that doesn't exist in the database yet), you can push them directly into the live CRM using this endpoint.

**Endpoint**: `POST /api/crm/leads`
**Base URL**: `http://<your-server-ip>:8000`
**Content-Type**: `application/json`

### Request Payload:
```json
{
  "lead_name": "John Doe",
  "phone_number": "555-0199",       // Accepted, stored as [REDACTED]
  "source_id": null,                // Optional. Omitted = the DIGITAL source.
                                    // (FIX 2026-10-08: used to default to id 1,
                                    // which is not a fixed channel.)
  "consultant_id": null,            // Optional
  "model_id": null,                 // Optional
  "variant_of_interest": "Taigun",  // Optional
  "origin": "MANUAL",               // Optional
  "created_at": null,               // Optional: when the enquiry came in.
                                    // Omit for "now". Decides which reporting
                                    // month the lead is filed under.
  "email": null,                    // Optional; stored as [REDACTED]
  "lead_type": null,                // Optional: Retail / Corporate B2B / B2C
  "model_of_interest": null,        // Optional: free text
  "rating": null                    // Optional: Hot / Warm / Cold
}
```

### Example cURL:
```bash
curl -X POST http://<your-server-ip>:8000/api/crm/leads \
  -H "Content-Type: application/json" \
  -d '{
    "lead_name": "Test Perfox Lead",
    "source_id": 1
  }'
```

### Expected Response:
```json
{
    "status": "success",
    "lead_id": 32450,
    "message": "Lead created successfully",
    "period": "SEP2026",
    "in_active_period": false,
    "created_at": "2026-09-18T17:55:43"
}
```

### Does the lead show up on the dashboard?

Yes — every open dashboard updates **on its own, within about a quarter of a
second**, with no reload and no polling. The insert fires a Postgres trigger,
which the API is listening on, which pushes a server-sent event to every open
browser. This happens for *any* write path, so it works the same whether the row
came from the agent, the dashboard's own form, or a bulk workbook upload.

The one thing to check is **`in_active_period`**:

| Value | Meaning |
|---|---|
| `true` | The lead is in the month the dashboard is reporting on. It appears immediately. |
| `false` | The lead is stored and correct, but belongs to a different month. It will appear once that month is made active (period selector, top-left of the dashboard). |

A lead pushed with no `created_at` is filed under **today's** month. So if the
dashboard's active month is August and the agent pushes a lead in September,
`in_active_period` comes back `false` and the figure will not move — the lead is
safe, it is just filed under a month nobody is currently looking at. Switch the
active month to match the month leads are arriving in.

---

## 2b. Easiest path: give Perfox a webhook URL

Section 2 is a typed API: it insists on `lead_name`, calls the phone
`phone_number`, and rejects anything shaped differently. That is fine when
something is *written* to call it — but an agent platform that offers a
"send this somewhere when a form is submitted" setting sends **its own** JSON,
under its own field names, and gives you nowhere to write a mapping step.

This endpoint exists for that case. It takes the enquiry in whatever shape it
arrives and works out which field is the name and which is the phone.

**Endpoint**: `POST /api/webhooks/enquiry`

Paste this into the agent's webhook / "post submission to URL" setting:

```
https://elite-dashboard1.onrender.com/api/webhooks/enquiry
```

Opening that URL in a browser (a `GET`) returns a short description rather than
an error, so you can confirm it is live before saving it.

### It accepts any of these

All four of these file the same lead. Field names are matched with case and
punctuation ignored, so `Full Name`, `full_name` and `fullName` are one key.

```json
{"Full Name": "Asha Menon", "Mobile Number": "+91 98765 43210",
 "Email Address": "asha@example.com", "Subject": "Tiguan price",
 "Message": "Please call me back"}

{"full_name": "Asha Menon", "phone_number": "9876543210"}

{"event": "form.submitted", "data": {"name": "Asha Menon", "phone": "9876543210"}}

{"fields": [{"label": "Full Name",     "value": "Asha Menon"},
            {"label": "Mobile Number", "value": "9876543210"}]}
```

Recognised: name, email, phone/mobile, subject, message, model, and a timestamp.
Subject and message are kept together on the lead as the enquiry note — the
substance of what the customer asked, which section 2 has nowhere to put.

A payload with **neither** a name nor a phone number is rejected with `422`, so a
mis-wired mapping shows up in the agent's delivery log instead of quietly filing
blank rows.

### Response

```json
{
  "status": "success",
  "duplicate": false,
  "lead_id": 104469,
  "period": "AUG2026",
  "in_active_period": true,
  "visible_on_dashboard": true,
  "received": {"name": "Asha Menon", "phone": "[REDACTED]", ...}
}
```

`visible_on_dashboard` is the field to watch. When it is `false` the reply also
carries a `warning` saying which month the lead went to and what to do about it —
see *Which month do live enquiries land in?* below.

### Delivered twice is still one lead

Webhook providers retry when they do not get a prompt `2xx`. An identical
delivery (the same payload, or the same name and message) within 10 minutes returns the **original**
`lead_id` with `"duplicate": true` instead of inserting a second row, so a retry
storm cannot triple the enquiry count.

### Securing it

This route writes and is reachable from the internet. Set a secret:

```
WEBHOOK_SECRET=some-long-random-string
```

It is then accepted as `X-Webhook-Secret: <secret>`, as
`Authorization: Bearer <secret>`, or — for setup screens that let you set nothing
but a URL — as `?token=<secret>` on the end of the URL. With `WEBHOOK_SECRET`
unset the route is open, which is deliberate: paste the URL, watch it work, then
lock it down.

### Which month do live enquiries land in?

By default the month the enquiry's own date falls in — the same rule the rest of
the system follows. That is correct, and it has a sharp edge: the dashboard shows
exactly one active month, so an enquiry arriving today while the dashboard reports
on an earlier month is stored correctly and **displayed nowhere**.

If you want enquiries to appear on screen as they arrive, set:

```
AGENT_LEAD_PERIOD=active
```

Incoming enquiries are then filed into whichever month the dashboard is showing.
It is off by default because it is a reporting choice, not a correctness fix.

### Leads from here survive the monthly upload

They are written with `origin = MANUAL`. A workbook re-upload in replace mode
deletes only `origin = WORKBOOK` rows, so enquiries captured by the agent are not
swept away by the next monthly import.

### Testing it

```bash
curl -X POST https://elite-dashboard1.onrender.com/api/webhooks/enquiry   -H "Content-Type: application/json"   -d '{"Full Name": "Webhook Test", "Mobile Number": "9876500000", "Message": "testing"}'
```

---

## 3. Fetch Bookings

Answers "what has <customer> ordered", "which orders are awaiting a car", "what
was booked this month". Reads the same view the dashboard's order book draws, so
the agent and the screen cannot disagree.

**Endpoint**: `POST /api/crm/fetch-bookings`

### Request Payload:
```json
{
  "limit": 50,
  "period": "active",      // "active" (default) | a label like "AUG2026" | "all"
  "search": "praneet",     // Optional: matches the customer's name
  "status": null           // Optional: BOOKED / NO_STOCK / ALLOTED / RETAILED / CANCELLED
}
```

### Example cURL:
```bash
curl -X POST https://<your-public-url>/api/crm/fetch-bookings \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"search": "praneet gogoi", "period": "AUG2026"}'
```

### Expected Response:
```json
[
  {
    "booking_id": 4003,
    "booking_date": "2026-08-31",
    "customer_name": "praneet gogoi",
    "mobile": "[REDACTED]",
    "consultant": "Lokesh Reddy K",
    "model": "GOLF GTI",
    "variant": "GT",
    "colour": "Dolphin Grey",
    "fulfilment_status": "BOOKED",
    "booking_amount": 25000.0,
    "allotted_chassis": null,
    "source": "SHOWROOM REFERRAL"
  }
]
```

---

## 4. What this CRM does and does not hold

The agent should answer **only** from these. There is no rental, service-booking
or appointment data anywhere in this system, so any such answer is invented:

| Concept | Table | Agent endpoint |
|---|---|---|
| Enquiries / leads | `lead` | `/api/crm/fetch-leads` |
| Orders / bookings | `booking` | `/api/crm/fetch-bookings` |
| Test drives | `test_drive` | *(none yet)* |
| Deliveries / retails | `registration` | *(none yet)* |
| Stock / vehicles | `vehicle` | *(none yet)* |
| Car rentals | **does not exist** | — |
| Service appointments | **does not exist** | — |

Vehicle models are limited to: **GOLF GTI, TAIGUN, TAIGUN (FL), TAYRON,
TIGUAN R-LINE, VIRTUS**.

## 5. Reporting months

Every figure is scoped to a reporting month, and exactly one is "active" — the
month the dashboard is showing. `period` defaults to `"active"`, so an agent
asking for "this month's leads" gets the month on screen rather than the whole
history of the table.

If a customer's record does not come back, check the month before concluding it
is absent: a booking filed under August will not appear in an `"active"` query
while November is the active month. Pass an explicit label, or `"all"`.
