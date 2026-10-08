"""
Dynamic in-memory data provider and fallback store.
Supports real-time dashboard writes and state updates both in serverless mode
and as a transparent fallback when PostgreSQL is not configured.
"""
from __future__ import annotations

import datetime
from typing import Any
from .data_bundle import DATA


class DynamicStore:
    """In-memory mutable store for dashboard entries and live updates."""

    def __init__(self):
        self.next_id = 1000
        self.leads: list[dict[str, Any]] = []
        self.bookings: list[dict[str, Any]] = []
        self.test_drives: list[dict[str, Any]] = []
        self.vehicles: list[dict[str, Any]] = []
        self.allotments: list[dict[str, Any]] = []
        self.registrations: list[dict[str, Any]] = []
        self.booking_patches: dict[int, dict[str, Any]] = {}
        self.deleted: set[tuple[str, int]] = set()

    def add_lead(self, payload: dict) -> dict:
        self.next_id += 1
        item = dict(payload)
        item["id"] = self.next_id
        item["lead_id"] = self.next_id
        item["loaded_at"] = datetime.datetime.now().isoformat()
        item["who"] = item.get("lead_name")
        item["kind"] = "lead"
        self.leads.insert(0, item)
        return {"lead_id": self.next_id, "period": "AUG2026", "in_active_period": True}

    def add_booking(self, payload: dict) -> dict:
        self.next_id += 1
        item = dict(payload)
        item["id"] = self.next_id
        item["booking_id"] = self.next_id
        item["loaded_at"] = datetime.datetime.now().isoformat()
        item["who"] = item.get("customer_name")
        item["kind"] = "booking"
        item["source_sheet"] = "Dashboard entry"
        item["is_current_period"] = True
        item["booking_date"] = str(item.get("booking_date") or datetime.date.today().isoformat())
        self.bookings.insert(0, item)
        return {"booking_id": self.next_id, "period": "AUG2026", "in_active_period": True}

    def patch_booking(self, booking_id: int, payload: dict) -> dict:
        patches = {k: v for k, v in payload.items() if v is not None}
        if booking_id not in self.booking_patches:
            self.booking_patches[booking_id] = {}
        self.booking_patches[booking_id].update(patches)
        for b in self.bookings:
            if b.get("booking_id") == booking_id or b.get("id") == booking_id:
                b.update(patches)
        return {"booking_id": booking_id, "updated": patches}

    def add_test_drive(self, payload: dict) -> dict:
        self.next_id += 1
        item = dict(payload)
        item["id"] = self.next_id
        item["test_drive_id"] = self.next_id
        item["loaded_at"] = datetime.datetime.now().isoformat()
        item["who"] = item.get("lead_name")
        item["kind"] = "test drive"
        self.test_drives.insert(0, item)
        return {"test_drive_id": self.next_id, "period": "AUG2026", "in_active_period": True}

    def add_vehicle(self, payload: dict) -> dict:
        self.next_id += 1
        item = dict(payload)
        item["id"] = self.next_id
        item["vehicle_id"] = self.next_id
        item["loaded_at"] = datetime.datetime.now().isoformat()
        item["who"] = item.get("chassis_number")
        item["kind"] = "vehicle"
        self.vehicles.insert(0, item)
        return {"vehicle_id": self.next_id, "chassis_number": item.get("chassis_number")}

    def add_allotment(self, payload: dict) -> dict:
        self.next_id += 1
        item = dict(payload)
        item["id"] = self.next_id
        item["allotment_id"] = self.next_id
        item["loaded_at"] = datetime.datetime.now().isoformat()
        item["who"] = f"Booking #{item.get('booking_id')}"
        item["kind"] = "allotment"
        self.allotments.insert(0, item)
        b_id = item.get("booking_id")
        if b_id:
            try:
                self.patch_booking(int(b_id), {"fulfilment_status": "ALLOTED"})
            except Exception:
                pass
        return {"allotment_id": self.next_id}

    def add_registration(self, payload: dict) -> dict:
        self.next_id += 1
        item = dict(payload)
        item["id"] = self.next_id
        item["registration_id"] = self.next_id
        item["loaded_at"] = datetime.datetime.now().isoformat()
        item["who"] = f"Booking #{item.get('booking_id')}"
        item["kind"] = "registration"
        self.registrations.insert(0, item)
        b_id = item.get("booking_id")
        if b_id:
            try:
                self.patch_booking(int(b_id), {"fulfilment_status": "RETAILED"})
            except Exception:
                pass
        return {"registration_id": self.next_id}

    def delete_entry(self, table: str, row_id: int) -> dict:
        tbl = table.lower().rstrip("s")
        self.deleted.add((tbl, row_id))
        self.leads = [x for x in self.leads if x.get("id") != row_id]
        self.bookings = [x for x in self.bookings if x.get("id") != row_id]
        self.test_drives = [x for x in self.test_drives if x.get("id") != row_id]
        self.allotments = [x for x in self.allotments if x.get("id") != row_id]
        self.registrations = [x for x in self.registrations if x.get("id") != row_id]
        self.vehicles = [x for x in self.vehicles if x.get("id") != row_id]
        return {"deleted": True, "table": table, "id": row_id}

    def get_recent_activity(self, limit: int = 25) -> list[dict[str, Any]]:
        all_items = (
            self.bookings + self.leads + self.test_drives +
            self.allotments + self.registrations + self.vehicles
        )
        all_items.sort(key=lambda x: str(x.get("loaded_at", "")), reverse=True)
        return all_items[:limit]


store = DynamicStore()


def get_snapshot() -> dict[str, Any]:
    return DATA


def get_kpi() -> dict[str, Any]:
    base = dict(DATA.get("kpi", {
        "period": "AUG2026",
        "enquiries": 367,
        "qualified": 361,
        "test_drives": 128.0,
        "bookings": 42,
        "retails": 18,
        "enquiry_to_booking_pct": 11.4,
        "booking_to_retail_pct": 42.9,
        "free_stock": 69,
        "allotted_stock": 20,
        "stock_over_90_days": 20,
        "backorders": 11,
        "bookings_missing_crm_entry": 15,
        "booking_amount_collected": 943001.0,
        "avg_allotment_tat_days": 3.5,
    }))

    extra_leads = len(store.leads)
    extra_bookings = len(store.bookings)
    extra_tds = len(store.test_drives)
    extra_retails = len(store.registrations)
    for patch in store.booking_patches.values():
        if patch.get("fulfilment_status") == "RETAILED":
            extra_retails += 1

    base["enquiries"] = base.get("enquiries", 367) + extra_leads
    base["qualified"] = base.get("qualified", 361) + extra_leads
    base["test_drives"] = base.get("test_drives", 128.0) + extra_tds
    base["bookings"] = base.get("bookings", 42) + extra_bookings
    base["retails"] = base.get("retails", 18) + extra_retails

    if base["enquiries"] > 0:
        base["enquiry_to_booking_pct"] = round(base["bookings"] / base["enquiries"] * 100, 1)
    if base["bookings"] > 0:
        base["booking_to_retail_pct"] = round(base["retails"] / base["bookings"] * 100, 1)

    return base


def get_funnel() -> dict[str, Any]:
    kpi_data = get_kpi()
    targets = DATA.get("targets", {})
    return {
        "period": kpi_data.get("period", "AUG2026"),
        "stages": [
            {"stage": "Enquiries",   "value": kpi_data.get("enquiries", 367),   "target": targets.get("leads_target", 450)},
            {"stage": "Qualified",   "value": kpi_data.get("qualified", 361),   "target": None},
            {"stage": "Test drives", "value": kpi_data.get("test_drives", 128), "target": targets.get("td_target", 300)},
            {"stage": "Bookings",    "value": kpi_data.get("bookings", 42),    "target": targets.get("booking_target", 84)},
            {"stage": "Retails",     "value": kpi_data.get("retails", 18),     "target": targets.get("retail_target", 66)},
        ],
    }


def get_leaderboard() -> list[dict[str, Any]]:
    board = [dict(b) for b in DATA.get("board", [])]
    # Apply dynamic bookings/leads to consultants
    for b in store.bookings:
        c_name = b.get("consultant")
        if not c_name:
            continue
        for row in board:
            if c_name.lower() in row.get("consultant", "").lower():
                row["booking_achieved"] = row.get("booking_achieved", 0) + 1
                row["booking_gap"] = row["booking_achieved"] - row.get("booking_target", 0)
                if row.get("booking_target", 0) > 0:
                    row["booking_vs_target_pct"] = round(row["booking_achieved"] / row["booking_target"] * 100, 1)
                break
    return board


def get_scorecards(row_kind: str | None = None) -> list[dict[str, Any]]:
    board = get_leaderboard()
    teams = DATA.get("teams", [])
    all_rows = []
    for b in board:
        r = dict(b)
        r["row_kind"] = "CONSULTANT"
        all_rows.append(r)
    for t in teams:
        r = dict(t)
        r["row_kind"] = "TEAM_TOTAL"
        all_rows.append(r)
    if row_kind:
        return [r for r in all_rows if r.get("row_kind") == row_kind]
    return all_rows


def get_leads_sourcewise() -> list[dict[str, Any]]:
    sources = [dict(s) for s in DATA.get("sources", [])]
    for l in store.leads:
        src = (l.get("source") or "WALKIN").upper()
        found = False
        for s in sources:
            if s.get("source", "").upper() == src:
                s["leads"] = s.get("leads", 0) + 1
                s["qualified"] = s.get("qualified", 0) + (1 if l.get("qualified", True) else 0)
                found = True
                break
        if not found:
            sources.append({"source": src, "channel": src, "leads": 1, "qualified": 1, "is_paid_media": False})
    return sources


def get_models_position() -> list[dict[str, Any]]:
    return DATA.get("models", [])


def get_models_demand() -> list[dict[str, Any]]:
    return DATA.get("demand", [])


def get_stock_ageing() -> list[dict[str, Any]]:
    return DATA.get("ageing", [])


def get_backorders() -> list[dict[str, Any]]:
    return DATA.get("backorders", [])


def get_attachments() -> dict[str, Any]:
    return DATA.get("attach", {
        "registrations": 18,
        "financed": 13,
        "insured": 13,
        "extended_warranty": 1,
        "service_value_package": 1,
        "corporate": 6,
        "finance_pct": 72.2,
        "insurance_pct": 72.2,
    })


def get_commitments() -> list[dict[str, Any]]:
    return DATA.get("commit", [])


def get_data_quality() -> list[dict[str, Any]]:
    return DATA.get("dq", [])


def get_meta() -> dict[str, Any]:
    return {
        "latest_load": DATA.get("meta", {
            "source_file": "DSR August 2026.xlsx",
            "file_modified": "2026-09-08T13:14:37",
            "finished_at": "2026-09-10T17:04:44",
        }),
        "period": DATA.get("period", {
            "label": "AUG2026",
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
        }),
    }


def get_action_list() -> dict[str, Any]:
    return {
        "stock_past_retail_deadline": DATA.get("deadline", []),
        "ageing_over_90_days": [
            d for d in DATA.get("deadline", []) if d.get("stock_aging_days", 0) > 90
        ],
        "backorders": DATA.get("backorders", []),
        "bookings_missing_crm_entry": DATA.get("nocrm", []),
    }


def get_periods() -> list[dict[str, Any]]:
    return [{
        "label": "AUG2026",
        "is_active": True,
        "period_start": "2026-08-01",
        "period_end": "2026-08-31",
        "working_days": 26,
        "bookings": get_kpi().get("bookings", 42),
        "retails": get_kpi().get("retails", 18),
    }]


def get_entry_options() -> dict[str, Any]:
    board = DATA.get("board", [])
    avail = DATA.get("avail", [])
    consultants = sorted({r.get("consultant") for r in board if r.get("consultant")})
    models = sorted({r.get("model") for r in avail if r.get("model")})
    variants = []
    seen = set()
    for r in avail:
        key = (r.get("model"), r.get("variant"))
        if key not in seen and r.get("model") and r.get("variant"):
            seen.add(key)
            variants.append({
                "model": r.get("model"),
                "variant": r.get("variant"),
                "transmission": r.get("transmission"),
                "long_model_text": f"{r.get('model')} {r.get('variant')}",
            })
    colours = sorted({r.get("colour") for r in avail if r.get("colour")})
    return {
        "consultants": consultants,
        "sources": ["CRM", "TELE", "WALKIN", "DIGITAL", "REFERENCE", "WORKSHOP REFERRAL", "SHOWROOM REFERRAL"],
        "models": models,
        "variants": variants,
        "colours": colours,
        "fulfilment_statuses": ["BOOKED", "NO_STOCK", "ALLOTED", "RETAILED", "CANCELLED"],
        "open_bookings": [{"booking_id": b["booking_id"], "customer_name": b["customer_name"], "model": b["model"], "variant": b.get("variant", ""), "consultant": b["consultant"]} for b in get_bookings(50)],
        "free_chassis": [{"chassis_number": f"MEX{i}VW{1000+i}", "model": a.get("model"), "variant": a.get("variant"), "colour": a.get("colour"), "stock_aging_days": a.get("freshest_days", 14)} for i, a in enumerate(avail[:20])],
    }


def get_bookings(limit: int = 40) -> list[dict[str, Any]]:
    # Combine custom entered bookings + snapshot bookings
    combined = []

    # 1. Custom bookings first
    for b in store.bookings:
        combined.append(dict(b))

    # 2. Snapshot bookings
    nocrm = DATA.get("nocrm", [])
    for i, b in enumerate(nocrm, start=1):
        booking_row = {
            "booking_id": i,
            "customer_name": b.get("customer_name"),
            "model": b.get("model"),
            "variant": b.get("variant"),
            "colour": b.get("colour", "Candy White"),
            "consultant": b.get("consultant"),
            "booking_date": b.get("booking_date"),
            "fulfilment_status": "BOOKED",
            "crm_entry_done": False,
            "booking_amount": 25000,
            "source_sheet": "DSR August 2026",
            "is_current_period": True,
        }
        # Apply patches
        if i in store.booking_patches:
            booking_row.update(store.booking_patches[i])
        combined.append(booking_row)

    return combined[:limit]
