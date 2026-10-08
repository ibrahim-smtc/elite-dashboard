"""
Data entry: the write side of the DSR database.

Payloads speak the dealership's language rather than the schema's - a booking
arrives with `consultant: "sanjeev"`, `model: "Virtus"`, `colour: "Candy White"`,
and the shared resolvers in etl/dimensions.py turn those into foreign keys,
creating a dimension row the first time a name is seen. That is deliberate: a
sales consultant typing into the dashboard should not have to know an id, and a
new trim arriving mid-month should not need a schema change.

Every row written here is stamped origin = 'MANUAL', which is what protects it
from the next workbook reload.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from etl import dimensions as dims
from etl import normalize as nz
from etl import pii


# =====================================================================
# Payloads
# =====================================================================

class _Payload(BaseModel):
    # Reject unknown keys rather than silently dropping a mistyped field - a
    # booking amount lost to a typo is worse than a 422.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    entered_by: str | None = Field(
        None, max_length=80, description="Who is entering this, for the audit trail")


class LeadIn(_Payload):
    lead_name: str = Field(..., min_length=2, max_length=120)
    source: str = Field(..., description="Walk In, Tele In, Digital, Reference, CRM...")

    # PII POLICY (2026-10-08): a phone or email typed into the name field is
    # cut out of it; the name itself is kept.
    @field_validator("lead_name")
    @classmethod
    def _name(cls, v):
        return pii.scrub_text(v)
    mobile: str | None = None
    email: str | None = Field(None, max_length=160)
    model_of_interest: str | None = Field(None, max_length=160)
    consultant: str | None = None
    rating: str | None = Field(None, description="Hot / Warm / Cold")
    lead_type: str | None = Field(None, description="Retail / Corporate B2B / Corporate B2C")
    qualified: bool = Field(True, description="Counts toward qualified enquiries")
    created_on: date | None = Field(None, description="Defaults to today")

    # PII POLICY (2026-10-08): customer phone numbers and emails are never
    # stored (etl/pii.py). They are replaced here, at the edge of the request,
    # so nothing after this point ever holds the real value. This used to
    # validate the number as a 10-digit mobile; a number that is about to be
    # discarded is not worth refusing a form over, so it no longer does.
    @field_validator("mobile", "email")
    @classmethod
    def _mobile(cls, v):
        return pii.redact(v)


class BookingIn(_Payload):
    customer_name: str = Field(..., min_length=2, max_length=120)
    consultant: str = Field(..., min_length=2)

    # PII POLICY (2026-10-08): a phone or email typed into the name field is
    # cut out of it; the name itself is kept.
    @field_validator("customer_name")
    @classmethod
    def _name(cls, v):
        return pii.scrub_text(v)
    source: str = Field(..., description="Walkin, Tele, Digital, Reference, CRM")
    model: str = Field(..., description="Taigun, Virtus, Tayron, Golf GTI...")
    variant: str | None = Field(None, description="GT Line AT, 1.5 DSG Sport...")
    colour: str | None = None
    mobile: str | None = None
    booking_date: date | None = Field(None, description="Defaults to today")
    model_year: int | None = Field(None, ge=2000, le=2100)
    booking_amount: float | None = Field(None, ge=0)
    fulfilment_status: str = Field("BOOKED", description="BOOKED / NO_STOCK / ALLOTED / RETAILED / CANCELLED")
    car_origin: str | None = Field(None, description="FRESH CAR / PUNCHED CAR")
    crm_entry_done: bool | None = None
    notes: str | None = Field(None, max_length=400)

    # PII POLICY (2026-10-08): phone redacted, phone/email cut out of notes.
    @field_validator("mobile")
    @classmethod
    def _mobile(cls, v):
        return LeadIn._mobile(v)

    @field_validator("notes")
    @classmethod
    def _notes(cls, v):
        return pii.scrub_text(v)

    @field_validator("fulfilment_status")
    @classmethod
    def _status(cls, v):
        resolved = nz.fulfilment_status(v)
        if resolved is None:
            raise ValueError("expected BOOKED, NO_STOCK, ALLOTED, RETAILED or CANCELLED")
        return resolved


class BookingPatch(_Payload):
    """Partial update. Only the fields present are touched."""
    fulfilment_status: str | None = None
    crm_entry_done: bool | None = None
    booking_amount: float | None = Field(None, ge=0)
    colour: str | None = None
    mobile: str | None = None
    notes: str | None = Field(None, max_length=400)

    @field_validator("fulfilment_status")
    @classmethod
    def _status(cls, v):
        if v is None:
            return None
        return BookingIn._status(v)

    # PII POLICY (2026-10-08): an edit cannot put a phone number back in.
    @field_validator("mobile")
    @classmethod
    def _mobile(cls, v):
        return pii.redact(v)

    @field_validator("notes")
    @classmethod
    def _notes(cls, v):
        return pii.scrub_text(v)


class TestDriveIn(_Payload):
    lead_name: str = Field(..., min_length=2, max_length=120)
    consultant: str | None = None

    # PII POLICY (2026-10-08): a phone or email typed into the name field is
    # cut out of it; the name itself is kept.
    @field_validator("lead_name")
    @classmethod
    def _name(cls, v):
        return pii.scrub_text(v)
    source: str | None = None
    model_of_interest: str | None = Field(None, max_length=160)
    mobile: str | None = None
    td_date: date | None = Field(None, description="Defaults to today")
    start_km: int | None = Field(None, ge=0)
    end_km: int | None = Field(None, ge=0)
    test_drive_number: str | None = Field(None, max_length=40)

    # PII POLICY (2026-10-08): phone redacted (etl/pii.py).
    @field_validator("mobile")
    @classmethod
    def _mobile(cls, v):
        return LeadIn._mobile(v)


class VehicleIn(_Payload):
    chassis_number: str = Field(..., min_length=6, max_length=40)
    model: str
    variant: str | None = None
    colour: str | None = None
    commission_no: str | None = None
    engine_number: str | None = None
    model_year: int | None = Field(None, ge=2000, le=2100)
    billing_date: date | None = None
    stock_received_date: date | None = None
    stock_status: str = Field("FREESTOCK", description="FREESTOCK / ALLOTED / RETAILED / REGISTERED")
    nadcon_retail_date: date | None = None

    @field_validator("stock_status")
    @classmethod
    def _status(cls, v):
        resolved = nz.stock_status(v)
        if resolved is None:
            raise ValueError("expected FREESTOCK, ALLOTED, RETAILED or REGISTERED")
        return resolved


class AllotmentIn(_Payload):
    booking_id: int
    chassis_number: str = Field(..., min_length=6, max_length=40)
    allotted_date: date | None = Field(None, description="Defaults to today")
    remarks: str | None = Field(None, max_length=300)

    # PII POLICY (2026-10-08): phone/email cut out of free-text remarks.
    @field_validator("remarks")
    @classmethod
    def _remarks(cls, v):
        return pii.scrub_text(v)


class RegistrationIn(_Payload):
    customer_name: str = Field(..., min_length=2, max_length=120)
    chassis_number: str | None = None

    # PII POLICY (2026-10-08): a phone or email typed into the name field is
    # cut out of it; the name itself is kept.
    @field_validator("customer_name")
    @classmethod
    def _name(cls, v):
        return pii.scrub_text(v)
    consultant: str | None = None
    source: str | None = None
    registration_no: str | None = Field(None, max_length=30)
    registration_date: date | None = None
    invoice_date: date | None = None
    delivery_date: date | None = None
    finance_type: str | None = Field(None, description="YES / FULL CASH / OH / LEASING")
    bank: str | None = None
    has_insurance: bool | None = None
    has_extended_warranty: bool | None = None
    has_service_value_package: bool | None = None
    is_corporate: bool | None = None
    accessories: float | None = Field(None, ge=0)
    elite_discount: float | None = Field(None, ge=0)
    vw_offers: str | None = Field(None, max_length=120)


# =====================================================================
# Writers
#
# Each takes a connection and returns the new row's id. They assume they are
# inside a transaction the caller commits, so a half-written booking is never
# visible - and, because notifications are delivered on commit, a dashboard is
# never told about a change that then rolled back.
# =====================================================================

def _one(cx, sql: str, params: tuple):
    row = cx.execute(sql, params).fetchone()
    return next(iter(row.values())) if isinstance(row, dict) else row[0]


def create_lead(cx, body: LeadIn) -> dict:
    on = body.created_on or date.today()
    period_id, period_label, is_current = dims.period_for(cx, on)
    lead_id = _one(cx, """
        INSERT INTO lead (lead_name, mobile, email, source_id, lead_type,
                          model_of_interest, model_id, consultant_id, rating,
                          qualified_stage, lead_status, created_at, period_id,
                          is_current_period, origin, entered_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'New',%s,%s,%s,'MANUAL',%s)
        RETURNING lead_id
    """, (
        body.lead_name, body.mobile, body.email,
        dims.resolve_source(cx, body.source), body.lead_type,
        body.model_of_interest,
        dims.resolve_model(cx, nz.model_from_text(body.model_of_interest)),
        dims.resolve_consultant(cx, body.consultant, activate=True),
        body.rating,
        "Qualified" if body.qualified else "New",
        on, period_id, is_current, body.entered_by,
    ))
    return {"lead_id": lead_id, "period": period_label, "in_active_period": is_current}


def create_booking(cx, body: BookingIn) -> dict:
    on = body.booking_date or date.today()
    period_id, period_label, is_current = dims.period_for(cx, on)
    consultant_id = dims.resolve_consultant(cx, body.consultant, activate=True)
    if consultant_id is None:
        raise ValueError(f"{body.consultant!r} is not a usable consultant name")
    variant_id = dims.resolve_variant(cx, body.model, body.variant)
    booking_id = _one(cx, """
        INSERT INTO booking (booking_date, customer_name, mobile, source_id,
                             consultant_id, team_id, model_id, variant_id,
                             colour_id, model_year, fulfilment_status,
                             car_origin, crm_entry_done, booking_amount, notes,
                             source_sheet, period_id, is_current_period,
                             origin, entered_by)
        VALUES (%s,%s,%s,%s,%s,
                (SELECT team_id FROM dim_consultant WHERE consultant_id = %s),
                %s,%s,%s,%s,%s,%s,%s,%s,%s,'Dashboard entry',%s,%s,'MANUAL',%s)
        RETURNING booking_id
    """, (
        on, body.customer_name, body.mobile,
        dims.resolve_source(cx, body.source), consultant_id, consultant_id,
        dims.resolve_model(cx, body.model), variant_id,
        dims.resolve_colour(cx, body.colour), body.model_year,
        body.fulfilment_status, nz.car_origin(body.car_origin),
        body.crm_entry_done, body.booking_amount, body.notes,
        period_id, is_current, body.entered_by,
    ))
    return {"booking_id": booking_id, "period": period_label,
            "in_active_period": is_current}


def update_booking(cx, booking_id: int, body: BookingPatch) -> bool:
    """Apply only the supplied fields. Returns False if the id does not exist."""
    sets: list[str] = []
    params: list = []
    simple = {
        "fulfilment_status": body.fulfilment_status,
        "crm_entry_done": body.crm_entry_done,
        "booking_amount": body.booking_amount,
        "mobile": body.mobile,
        "notes": body.notes,
    }
    supplied = body.model_dump(exclude_unset=True)
    for column, value in simple.items():
        if column in supplied:
            sets.append(f"{column} = %s")
            params.append(value)
    if "colour" in supplied:
        sets.append("colour_id = %s")
        params.append(dims.resolve_colour(cx, body.colour))
    if not sets:
        raise ValueError("no fields to update")
    params.append(booking_id)
    return cx.execute(
        f"UPDATE booking SET {', '.join(sets)} WHERE booking_id = %s", params
    ).rowcount > 0


def create_test_drive(cx, body: TestDriveIn) -> int:
    return _one(cx, """
        INSERT INTO test_drive (test_drive_number, lead_name, mobile, source_id,
                                model_of_interest, model_id, start_km, end_km,
                                total_distance_km, td_date, status, created_at,
                                consultant_id, outlet, origin, entered_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Completed',now(),%s,
                'Volkswagen Elite Motors','MANUAL',%s)
        RETURNING test_drive_id
    """, (
        body.test_drive_number, body.lead_name, body.mobile,
        dims.resolve_source(cx, body.source), body.model_of_interest,
        dims.resolve_model(cx, nz.model_from_text(body.model_of_interest)),
        body.start_km, body.end_km,
        (body.end_km - body.start_km)
        if body.end_km is not None and body.start_km is not None else None,
        body.td_date or date.today(),
        dims.resolve_consultant(cx, body.consultant, activate=True),
        body.entered_by,
    ))


def upsert_vehicle(cx, body: VehicleIn) -> int:
    """
    Add a car to stock, or update it if the chassis is already known.

    Chassis number is the real identity of a unit, so this is an upsert - the
    same car arriving twice updates rather than duplicating.
    """
    chassis = nz.upper(body.chassis_number)
    variant_id = dims.resolve_variant(cx, body.model, body.variant)
    return _one(cx, """
        INSERT INTO vehicle (chassis_number, commission_no, engine_number,
                             model_id, variant_id, colour_id, model_year,
                             billing_date, stock_received_date, stock_status,
                             nadcon_retail_date, stock_aging_days,
                             origin, entered_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                CASE WHEN %s IS NULL THEN NULL
                     ELSE GREATEST(0, CURRENT_DATE - %s) END,
                'MANUAL',%s)
        ON CONFLICT (chassis_number) DO UPDATE SET
            stock_status        = EXCLUDED.stock_status,
            colour_id           = COALESCE(EXCLUDED.colour_id, vehicle.colour_id),
            variant_id          = COALESCE(EXCLUDED.variant_id, vehicle.variant_id),
            engine_number       = COALESCE(EXCLUDED.engine_number, vehicle.engine_number),
            nadcon_retail_date  = COALESCE(EXCLUDED.nadcon_retail_date, vehicle.nadcon_retail_date),
            stock_received_date = COALESCE(EXCLUDED.stock_received_date, vehicle.stock_received_date)
        RETURNING vehicle_id
    """, (
        chassis, body.commission_no, nz.upper(body.engine_number),
        dims.resolve_model(cx, body.model), variant_id,
        dims.resolve_colour(cx, body.colour), body.model_year,
        body.billing_date, body.stock_received_date, body.stock_status,
        body.nadcon_retail_date, body.billing_date, body.billing_date,
        body.entered_by,
    ))


def create_allotment(cx, body: AllotmentIn) -> int:
    """
    Allot a car to a booking: writes the allotment, links the booking to the
    vehicle and moves both their statuses on. This is the one write that has to
    touch three tables to leave the data consistent, which is why it is a single
    transaction rather than three API calls.
    """
    chassis = nz.upper(body.chassis_number)
    row = cx.execute("SELECT vehicle_id, long_model_text, stock_aging_days "
                     "FROM vehicle WHERE chassis_number = %s", (chassis,)).fetchone()
    if row is None:
        raise ValueError(f"no car in stock with chassis {chassis}")
    vehicle_id = row["vehicle_id"] if isinstance(row, dict) else row[0]
    long_text = row["long_model_text"] if isinstance(row, dict) else row[1]
    aging = row["stock_aging_days"] if isinstance(row, dict) else row[2]

    booking = cx.execute("SELECT customer_name, consultant_id FROM booking "
                         "WHERE booking_id = %s", (body.booking_id,)).fetchone()
    if booking is None:
        raise ValueError(f"no booking with id {body.booking_id}")
    customer = booking["customer_name"] if isinstance(booking, dict) else booking[0]
    consultant_id = booking["consultant_id"] if isinstance(booking, dict) else booking[1]

    on = body.allotted_date or date.today()
    allotment_id = _one(cx, """
        INSERT INTO allotment (vehicle_id, booking_id, customer_name, consultant_id,
                               long_model_text, stock_aging_days, allotted_date,
                               tat_days, vin, remarks, origin, entered_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,
                -- days left in the month to turn this into a retail
                (SELECT GREATEST(0, period_end - %s) FROM dim_period
                  WHERE %s BETWEEN period_start AND period_end LIMIT 1),
                %s,%s,'MANUAL',%s)
        RETURNING allotment_id
    """, (vehicle_id, body.booking_id, customer, consultant_id, long_text, aging,
          on, on, on, chassis, body.remarks, body.entered_by))

    cx.execute("UPDATE booking SET vehicle_id = %s, fulfilment_status = 'ALLOTED' "
               "WHERE booking_id = %s", (vehicle_id, body.booking_id))
    cx.execute("UPDATE vehicle SET stock_status = 'ALLOTED' WHERE vehicle_id = %s",
               (vehicle_id,))
    return allotment_id


def create_registration(cx, body: RegistrationIn) -> int:
    """Record a retail. Also moves the car to REGISTERED so stock stays honest."""
    chassis = nz.upper(body.chassis_number) if body.chassis_number else None
    vehicle_id = None
    if chassis:
        row = cx.execute("SELECT vehicle_id FROM vehicle WHERE chassis_number = %s",
                         (chassis,)).fetchone()
        if row is None:
            raise ValueError(f"no car in stock with chassis {chassis}")
        vehicle_id = row["vehicle_id"] if isinstance(row, dict) else row[0]

    registration_id = _one(cx, """
        INSERT INTO registration (vehicle_id, chassis_number, customer_name,
                                  consultant_id, source_id, status,
                                  registration_no, registration_date, invoice_date,
                                  delivery_date, finance_type, bank, has_insurance,
                                  has_extended_warranty, has_service_value_package,
                                  is_corporate, accessories, elite_discount,
                                  vw_offers, origin, entered_by)
        VALUES (%s,%s,%s,%s,%s,'REGISTERED',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                'MANUAL',%s)
        RETURNING registration_id
    """, (
        vehicle_id, chassis, body.customer_name,
        dims.resolve_consultant(cx, body.consultant, activate=True),
        dims.resolve_source(cx, body.source),
        nz.upper(body.registration_no), body.registration_date, body.invoice_date,
        body.delivery_date, nz.upper(body.finance_type), nz.upper(body.bank),
        body.has_insurance, body.has_extended_warranty,
        body.has_service_value_package, body.is_corporate,
        body.accessories, body.elite_discount, body.vw_offers, body.entered_by,
    ))

    if vehicle_id:
        cx.execute("UPDATE vehicle SET stock_status = 'REGISTERED' "
                   "WHERE vehicle_id = %s", (vehicle_id,))
        cx.execute("UPDATE booking SET fulfilment_status = 'RETAILED' "
                   "WHERE vehicle_id = %s AND fulfilment_status <> 'CANCELLED'",
                   (vehicle_id,))
    return registration_id


def _release_vehicle(cx, vehicle_id: int | None) -> None:
    """
    Put a car back where it belongs after its allotment or retail is undone.

    Without this, deleting an allotment leaves the unit stuck on ALLOTED: it is
    neither sellable nor counted as free, and the stock figures quietly drift
    away from the cars actually standing on the floor.
    """
    if vehicle_id is None:
        return
    cx.execute("""
        UPDATE vehicle SET stock_status = CASE
            -- still retailed by another registration
            WHEN EXISTS (SELECT 1 FROM registration r
                          WHERE r.vehicle_id = vehicle.vehicle_id) THEN 'REGISTERED'
            -- still held for a customer by another allotment
            WHEN EXISTS (SELECT 1 FROM allotment a
                          WHERE a.vehicle_id = vehicle.vehicle_id) THEN 'ALLOTED'
            ELSE 'FREESTOCK'
        END::stock_status
        WHERE vehicle_id = %s
    """, (vehicle_id,))
    # A booking that was pointing at this car goes back to being an open order.
    cx.execute("""
        UPDATE booking SET fulfilment_status = 'BOOKED', vehicle_id = NULL
        WHERE vehicle_id = %s
          AND fulfilment_status IN ('ALLOTED', 'RETAILED')
          AND NOT EXISTS (SELECT 1 FROM allotment a
                           WHERE a.booking_id = booking.booking_id)
    """, (vehicle_id,))


# FIX (2026-10-08): DELETE /api/entries/{table}/{id} failed with a 500 on every
# call. delete_row() took (cx, table, pk_column, row_id) but the route passes
# only (table, row_id), so Python raised "missing 1 required positional
# argument: 'row_id'". The caller has no business knowing each table's key
# column anyway, so delete_row() now looks it up here and takes (table, row_id).
DELETABLE_TABLES = {
    "lead": "lead_id", "booking": "booking_id", "test_drive": "test_drive_id",
    "allotment": "allotment_id", "registration": "registration_id",
    "vehicle": "vehicle_id",
}


def delete_row(cx, table: str, row_id: int) -> bool:
    """
    Remove a hand-entered row, and undo what it did.

    Workbook rows are refused - they belong to the source file and would reappear
    on the next load anyway, so deleting one here would look like it worked and
    then silently undo itself.

    Deleting an allotment or a registration is not just a row disappearing: the
    car it named has to go back to being free stock and the booking back to being
    an open order, or the stock counts stop matching the forecourt.
    """
    if table not in DELETABLE_TABLES:
        raise ValueError(f"{table} is not deletable")
    pk_column = DELETABLE_TABLES[table]

    row = cx.execute(
        f"SELECT origin, {'vehicle_id' if table in {'allotment', 'registration'} else 'NULL AS vehicle_id'} "
        f"FROM {table} WHERE {pk_column} = %s", (row_id,)).fetchone()
    if row is None:
        return False
    origin = row["origin"] if isinstance(row, dict) else row[0]
    vehicle_id = row["vehicle_id"] if isinstance(row, dict) else row[1]
    if origin != "MANUAL":
        raise PermissionError(
            "this row came from the DSR workbook - edit the workbook and reload "
            "instead, or the next load will bring it back")

    deleted = cx.execute(
        f"DELETE FROM {table} WHERE {pk_column} = %s", (row_id,)).rowcount > 0
    if deleted and table in {"allotment", "registration"}:
        _release_vehicle(cx, vehicle_id)
    return deleted
