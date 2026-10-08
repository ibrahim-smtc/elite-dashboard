-- =====================================================================
-- Volkswagen Elite Motors - DSR operational database
-- Source of truth: "DSR August 2026.xlsx" (Daily Sales Report)
--
-- Layout
--   dim_*      reference data (consultants, models, variants, colours, sources)
--   facts      vehicle, lead, test_drive, booking, allotment, registration
--   target_*   targets that cannot be derived from the facts (they are set, not measured)
--
-- Pivot sheets in the workbook (Free Stock, Modewise, VW Report, Leads Sourcewise,
-- ZOHO Entry, Modelwise Booking, Comparision) are NOT tables - they are rebuilt as
-- views in views.sql so they can never drift from the underlying rows.
-- =====================================================================

DROP SCHEMA IF EXISTS dsr CASCADE;
CREATE SCHEMA dsr;
SET search_path = dsr, public;

-- ---------------------------------------------------------------------
-- Enumerated domains
-- ---------------------------------------------------------------------

-- Where a vehicle sits in the stock lifecycle.
CREATE TYPE stock_status AS ENUM ('FREESTOCK', 'ALLOTED', 'RETAILED', 'REGISTERED');

-- Where a booking sits in the fulfilment lifecycle. NO_STOCK = order taken with
-- nothing to allot against it yet (a back order).
CREATE TYPE fulfilment_status AS ENUM ('BOOKED', 'NO_STOCK', 'ALLOTED', 'RETAILED', 'CANCELLED');

-- "FRESH CAR" vs "PUNCHED CAR" in the DSR: whether the unit was ordered fresh for
-- this customer or drawn from a VIN already punched into the system.
CREATE TYPE car_origin AS ENUM ('FRESH_CAR', 'PUNCHED_CAR');

-- Where a row came from. WORKBOOK rows are rebuilt on every load of the DSR
-- file; MANUAL rows were entered through the dashboard and must survive it.
CREATE TYPE row_origin AS ENUM ('WORKBOOK', 'MANUAL');

-- FIX (2026-10-08): this file had drifted from the live database. The loader
-- (reset / stamp_load) and the month delete/clear routes all read and write a
-- `load_period_id` column on the five fact tables, and db/triggers.sql attaches
-- a trigger to a `public.lead` view - neither was created anywhere in the repo,
-- so building a database from these files (README quick start, or
-- tools/setup_cloud_db.py) failed at triggers.sql and again at the first load.
-- load_period_id is now declared on lead, test_drive, booking, allotment and
-- registration below; public.lead is created in db/triggers.sql. A database
-- that already has them (the live one) is unaffected - this file is only run
-- to build a new schema.

-- The channel a consultant works. The DSR splits every consultant's scorecard
-- into their primary channel plus a catch-all second row.
CREATE TYPE channel_group AS ENUM (
    'WALKIN', 'TELE', 'DIGITAL', 'REFERRAL', 'CRM',
    'WORKSHOP', 'EVENT', 'HYPERLOCAL', 'OTHER'
);

-- ---------------------------------------------------------------------
-- Reference data
-- ---------------------------------------------------------------------

CREATE TABLE dim_team (
    team_id     smallserial PRIMARY KEY,
    name        text NOT NULL UNIQUE          -- NETHRA, PRINCE (team-manager names)
);

CREATE TABLE dim_consultant (
    consultant_id    smallserial PRIMARY KEY,
    full_name        text NOT NULL UNIQUE,     -- canonical, upper case
    display_name     text NOT NULL,            -- title case, for the dashboard
    team_id          smallint REFERENCES dim_team(team_id),
    primary_channel  channel_group,
    is_active        boolean NOT NULL DEFAULT true
);
COMMENT ON TABLE dim_consultant IS
  'Sales consultants. The workbook spells the same person several ways
   (ABINAND P / ABHINAND P); the ETL folds those onto one row.';

CREATE TABLE dim_model (
    model_id     smallserial PRIMARY KEY,
    name         text NOT NULL UNIQUE,          -- TAIGUN, TAIGUN (FL), VIRTUS, TAYRON, GOLF GTI, TIGUAN R-LINE
    family       text NOT NULL,                 -- TAIGUN, VIRTUS, TAYRON, GOLF, TIGUAN (facelift folded in)
    is_cbu       boolean NOT NULL DEFAULT false -- imported (Golf/Tiguan/Tayron) vs locally built
);

CREATE TABLE dim_variant (
    variant_id       smallserial PRIMARY KEY,
    model_id         smallint NOT NULL REFERENCES dim_model(model_id),
    name             text NOT NULL,            -- "1.5 DSG SPORT", "GT LINE AT", "TOPLINE AT"
    long_model_text  text,                     -- factory description, e.g. "VIRTUS 1.0L TSI 85kW AT GT Line"
    model_code       text,                     -- D22LDY, CW2HFZ - the code stock is ordered against
    transmission     text,                     -- MT / AT / DSG
    UNIQUE (model_id, name)
);

CREATE TABLE dim_colour (
    colour_id    smallserial PRIMARY KEY,
    name         text NOT NULL UNIQUE,         -- "Candy White", "Lava Blue Metallic"
    colour_code  text                          -- B4B4, 0F0F, 2T2T - VW paint code
);

CREATE TABLE dim_lead_source (
    source_id      smallserial PRIMARY KEY,
    name           text NOT NULL UNIQUE,       -- canonical: WALKIN, TELE, DIGITAL, REFERENCE, CRM...
    channel        channel_group NOT NULL,
    is_paid_media  boolean NOT NULL DEFAULT false
);
COMMENT ON TABLE dim_lead_source IS
  'The workbook uses two vocabularies for the same channels - CRM exports say
   Walk In / Tele In / Central Webin, the DSR tabs say WALKIN / TELE / DIGI.
   The ETL maps both onto these rows.';

CREATE TABLE dim_period (
    period_id     smallserial PRIMARY KEY,
    label         text NOT NULL UNIQUE,        -- 'AUG2026'
    period_start  date NOT NULL,
    period_end    date NOT NULL,
    -- The month the dashboard is reporting on. Exactly one row is active, and
    -- every headline view is scoped to it. Without this the KPI views would
    -- return one row per period the moment a second month existed.
    is_active     boolean NOT NULL DEFAULT false,
    CHECK (period_end >= period_start)
);

-- At most one active period, enforced rather than assumed.
CREATE UNIQUE INDEX dim_period_one_active ON dim_period ((true)) WHERE is_active;

COMMENT ON COLUMN dim_period.is_active IS
  'The reporting month the dashboard shows. Switch it with
   POST /api/period/{label}/activate, which also recomputes is_current_period
   across the fact tables.';

-- ---------------------------------------------------------------------
-- Inventory - one row per physical car
-- ---------------------------------------------------------------------

CREATE TABLE vehicle (
    vehicle_id           serial PRIMARY KEY,
    chassis_number       text NOT NULL UNIQUE,       -- MEXA26D21TT022886, the real identity of the unit
    commission_no        text,                       -- VW order/commission number
    engine_number        text,
    model_id             smallint REFERENCES dim_model(model_id),
    variant_id           smallint REFERENCES dim_variant(variant_id),
    colour_id            smallint REFERENCES dim_colour(colour_id),
    model_code           text,
    long_model_text      text,
    model_year           smallint,
    obd                  text,                       -- OBD1 / OBD2 emission generation
    options              text,                       -- factory option codes, space separated
    billing_date         date,                       -- invoiced by VW to the dealer
    stock_received_date  date,                       -- physically landed at the dealership
    stock_aging_days     integer,                    -- as reported in the DSR snapshot
    stock_status         stock_status NOT NULL,
    nadcon_retail_date   date,                       -- retail deadline set by VW (NADCON)
    -- provenance: MANUAL rows survive a workbook reload, WORKBOOK rows do not
    origin                    row_origin NOT NULL DEFAULT 'WORKBOOK',
    loaded_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                timestamptz NOT NULL DEFAULT now(),
    entered_by                text,
    CHECK (stock_aging_days IS NULL OR stock_aging_days >= 0)
);
COMMENT ON COLUMN vehicle.stock_aging_days IS
  'Days since billing, as printed in the DSR. Kept verbatim rather than recomputed so
   the loaded data still reconciles against the workbook the manager signed off.';
COMMENT ON COLUMN vehicle.nadcon_retail_date IS
  'NADCON is the VW India dealer system; this is the date the unit must be retailed by.';

CREATE INDEX ON vehicle (stock_status);
CREATE INDEX ON vehicle (model_id, variant_id, colour_id);
CREATE INDEX ON vehicle (stock_aging_days DESC);

-- ---------------------------------------------------------------------
-- Demand - leads, test drives, bookings
-- ---------------------------------------------------------------------

CREATE TABLE lead (
    lead_id             serial PRIMARY KEY,
    lead_record_id      text,                       -- Salesforce id (00QIi...), absent on the Aug tab
    created_at          timestamp,
    lead_name           text,
    mobile              text,
    email               text,
    source_id           smallint REFERENCES dim_lead_source(source_id),
    lead_type           text,                       -- Retail / Corporate B2B / Corporate B2C
    model_of_interest   text,                       -- free text as exported
    variant_of_interest text,
    colour_of_interest  text,
    model_id            smallint REFERENCES dim_model(model_id),   -- resolved where possible
    lead_owner          text,
    consultant_id       smallint REFERENCES dim_consultant(consultant_id),
    lead_status         text,
    rating              text,                       -- Hot / Warm / Cold
    qualified_stage     text,                       -- Qualified / New / Lost / Submit for Lost Aproval
    test_drive_given    boolean,
    trade_in            boolean,
    trade_in_vehicle    text,
    dealership          text,
    -- What the customer actually wrote. Enquiries arriving from the chat agent
    -- carry a subject and a message, and there was nowhere to keep them - so
    -- the substance of the enquiry was dropped and only the contact kept.
    enquiry_note        text,
    period_id           smallint REFERENCES dim_period(period_id),
    -- provenance: MANUAL rows survive a workbook reload, WORKBOOK rows do not
    origin                    row_origin NOT NULL DEFAULT 'WORKBOOK',
    loaded_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                timestamptz NOT NULL DEFAULT now(),
    entered_by                text,
    is_current_period   boolean NOT NULL DEFAULT false,
    -- FIX (2026-10-08): was missing from this file (see the note at the top).
    -- The month whose upload produced this row, independent of period_id.
    load_period_id      smallint REFERENCES dim_period(period_id)
);
COMMENT ON TABLE lead IS
  'Two populations live here. is_current_period = true is the August 2026 enquiry
   book (the Leads tab, 367 rows, thin - only date/name/source/model populated).
   false is the 2024 historical CRM dump on the TD Leads tab (1787 rows, fully
   populated) kept for year-on-year comparison.';

CREATE INDEX ON lead (source_id);
CREATE INDEX ON lead (created_at);
CREATE INDEX ON lead (is_current_period);
CREATE INDEX ON lead (mobile);

CREATE TABLE test_drive (
    test_drive_id      serial PRIMARY KEY,
    test_drive_number  text UNIQUE,                 -- TDN-11512712
    lead_record_id     text,
    lead_name          text,
    mobile             text,
    email              text,
    source_id          smallint REFERENCES dim_lead_source(source_id),
    stage              text,
    model_of_interest  text,
    model_id           smallint REFERENCES dim_model(model_id),
    model_code         text,
    start_km           integer,
    end_km             integer,
    total_distance_km  integer,
    td_date            date,
    status             text,                        -- Completed / ...
    created_at         timestamp,
    outlet             text,
    consultant_id      smallint REFERENCES dim_consultant(consultant_id),
    -- provenance: MANUAL rows survive a workbook reload, WORKBOOK rows do not
    origin                    row_origin NOT NULL DEFAULT 'WORKBOOK',
    loaded_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                timestamptz NOT NULL DEFAULT now(),
    entered_by                text,
    -- FIX (2026-10-08): was missing from this file (see the note at the top).
    load_period_id            smallint REFERENCES dim_period(period_id),
    CHECK (end_km IS NULL OR start_km IS NULL OR end_km >= start_km)
);

CREATE INDEX ON test_drive (td_date);
CREATE INDEX ON test_drive (consultant_id);

CREATE TABLE booking (
    booking_id                serial PRIMARY KEY,
    booking_date              date,
    contract_no               text,
    invoice_ref               text,                 -- "BND" etc. on the Booking & Alloted tab
    source_id                 smallint REFERENCES dim_lead_source(source_id),
    consultant_id             smallint REFERENCES dim_consultant(consultant_id),
    team_id                   smallint REFERENCES dim_team(team_id),
    customer_name             text,
    mobile                    text,
    model_id                  smallint REFERENCES dim_model(model_id),
    variant_id                smallint REFERENCES dim_variant(variant_id),
    colour_id                 smallint REFERENCES dim_colour(colour_id),
    model_year                smallint,
    long_model_text           text,
    fulfilment_status         fulfilment_status,
    car_origin                car_origin,
    crm_entry_done            boolean,              -- the ZOHO / SFDC ENTRY column
    booking_amount            numeric(12,2),
    booking_amount_receipted  boolean,
    ageing_days               integer,
    -- ON DELETE SET NULL: a workbook reload rebuilds vehicle rows, and a
    -- hand-entered booking must not be deleted along with the car it named.
    vehicle_id                integer REFERENCES vehicle(vehicle_id) ON DELETE SET NULL,
    notes                     text,
    source_sheet              text NOT NULL,        -- which DSR tab the row came from
    period_id                 smallint REFERENCES dim_period(period_id),
    is_current_period         boolean NOT NULL DEFAULT false,
    -- provenance: MANUAL rows survive a workbook reload, WORKBOOK rows do not
    origin                    row_origin NOT NULL DEFAULT 'WORKBOOK',
    loaded_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                timestamptz NOT NULL DEFAULT now(),
    entered_by                text,
    -- FIX (2026-10-08): was missing from this file (see the note at the top).
    load_period_id            smallint REFERENCES dim_period(period_id),
    CHECK (booking_amount IS NULL OR booking_amount >= 0)
);
COMMENT ON TABLE booking IS
  'The workbook records bookings on five overlapping tabs - Current Month Booking
   (August), Booking & Alloted (open order book incl. carry-over), Live Booking
   (back orders), Pending Booking (unfulfilled), Golf & Tiguan R Line Booking (CBU).
   source_sheet preserves which view a row came from; is_current_period marks the
   August book so the two are never double counted.';

CREATE INDEX ON booking (booking_date);
CREATE INDEX ON booking (consultant_id);
CREATE INDEX ON booking (fulfilment_status);
CREATE INDEX ON booking (source_sheet);
CREATE INDEX ON booking (is_current_period);

-- ---------------------------------------------------------------------
-- Fulfilment - allotment, then registration and delivery
-- ---------------------------------------------------------------------

CREATE TABLE allotment (
    allotment_id      serial PRIMARY KEY,
    vehicle_id        integer REFERENCES vehicle(vehicle_id) ON DELETE SET NULL,
    booking_id        integer REFERENCES booking(booking_id) ON DELETE SET NULL,
    customer_name     text,
    consultant_id     smallint REFERENCES dim_consultant(consultant_id),
    long_model_text   text,
    colour            text,
    stock_aging_days  integer,
    allotted_date     date,
    tat_days          integer,      -- days left in the month to retail the unit
    vin               text,
    obd               text,
    -- provenance: MANUAL rows survive a workbook reload, WORKBOOK rows do not
    origin                    row_origin NOT NULL DEFAULT 'WORKBOOK',
    loaded_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                timestamptz NOT NULL DEFAULT now(),
    entered_by                text,
    -- FIX (2026-10-08): was missing from this file (see the note at the top).
    load_period_id            smallint REFERENCES dim_period(period_id),
    remarks           text
);
COMMENT ON COLUMN allotment.tat_days IS
  'Turnaround window printed in the DSR: days remaining to convert this allotment
   into a retail before month end.';

CREATE INDEX ON allotment (allotted_date);

CREATE TABLE registration (
    registration_id             serial PRIMARY KEY,
    vehicle_id                  integer REFERENCES vehicle(vehicle_id) ON DELETE SET NULL,
    chassis_number              text,
    customer_name               text,
    consultant_id               smallint REFERENCES dim_consultant(consultant_id),
    source_id                   smallint REFERENCES dim_lead_source(source_id),
    status                      text,          -- REGISTERED / ALLOTED
    booking_date                date,
    allotted_date               date,
    nadcon_retail_date          date,
    contact_no                  text,
    address                     text,
    email                       text,
    nadcon_punched_customer     text,
    -- back-office paper trail: the DSR tracks how fast a folder clears accounts
    folder_lined_up_on          date,
    folder_given_to_accounts_on date,
    time_given                  time,
    folder_sent_to_ho           date,
    invoice_date                date,
    registration_date           date,
    registration_no             text,
    voiw_id                     text,
    delivery_date               date,
    -- attachments / value-adds sold with the car
    finance_type                text,          -- YES / FULL CASH / OH / LEASING
    bank                        text,
    has_insurance               boolean,
    has_extended_warranty       boolean,
    has_service_value_package   boolean,
    is_corporate                boolean,
    -- DWA is recorded as a yes/no flag on the tab, not an amount.
    dwa                         boolean,
    dwa_actual                  boolean,
    accessories                 numeric(12,2),
    -- The offer mix, verbatim: "VW-40K, EXCH-20K, LOY-40K" is a factory
    -- contribution plus an exchange bonus plus a loyalty bonus. Kept as text
    -- because the components matter more than a single total.
    vw_offers                   text,
    -- provenance: MANUAL rows survive a workbook reload, WORKBOOK rows do not
    origin                    row_origin NOT NULL DEFAULT 'WORKBOOK',
    loaded_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                timestamptz NOT NULL DEFAULT now(),
    entered_by                text,
    -- FIX (2026-10-08): was missing from this file (see the note at the top).
    -- Registrations carry no business month of their own, so this is also
    -- what the views use to decide which month a workbook retail belongs to.
    load_period_id            smallint REFERENCES dim_period(period_id),
    elite_discount              numeric(12,2)
);
COMMENT ON TABLE registration IS
  'One row per retailed/registered unit, from the Reg Report tab. Carries both the
   RTO milestones and the attachment mix (finance, insurance, EW, SVP) the
   scorecards are measured on.

   In the August workbook the columns from FOLDER SENT TO HO rightwards -
   invoice_date, registration_date, registration_no, voiw_id, delivery_date - are
   blank on every row: the tab tracks the folder as far as accounts and stops.
   status still says REGISTERED, so that is what the agent views read for the
   fulfilment stage. See v_data_quality.';

CREATE INDEX ON registration (registration_date);
CREATE INDEX ON registration (consultant_id);

-- ---------------------------------------------------------------------
-- Targets - set by management, not derivable from the facts above
-- ---------------------------------------------------------------------

CREATE TABLE target_consultant_scorecard (
    scorecard_id             serial PRIMARY KEY,
    period_id                smallint NOT NULL REFERENCES dim_period(period_id),
    consultant_id            smallint REFERENCES dim_consultant(consultant_id),
    row_label                text NOT NULL,   -- consultant name, or 'S/R Team', 'Field Team', 'TOTAL'
    row_kind                 text NOT NULL,   -- CONSULTANT | TEAM_TOTAL | GRAND_TOTAL | OTHER
    lead_type                text,            -- 'Walkin' / 'Tele' (primary) or 'CRM & Others' / 'Digital & Others'
    is_primary_channel       boolean NOT NULL DEFAULT true,
    leads_target             numeric(10,2),
    total_leads              numeric(10,2),
    leads_qualified          numeric(10,2),
    td_target                numeric(10,2),
    td_achieved              numeric(10,2),
    booking_target           numeric(10,2),
    booking_achieved         numeric(10,2),
    booking_achieved_total   numeric(10,2),
    retail_target            numeric(10,2),
    retail_achieved          numeric(10,2),
    retail_achieved_total    numeric(10,2),
    finance_target           numeric(10,2),
    finance_achieved         numeric(10,2),
    insurance_target         numeric(10,2),
    insurance_achieved       numeric(10,2),
    ew_target                numeric(10,2),
    ew_achieved              numeric(10,2),
    svp                      numeric(10,2),
    dwa_eva                  numeric(10,2),
    dwa_achieved             numeric(10,2),
    taigun_target            numeric(10,2),
    taigun_achieved          numeric(10,2),
    punched_vin_target       numeric(10,2),
    punched_vin_achieved     numeric(10,2),
    referral_target          numeric(10,2),
    referral_achieved        numeric(10,2),
    cancelled                numeric(10,2),
    allotted                 numeric(10,2),
    coverage                 numeric(10,2),
    CHECK (row_kind IN ('CONSULTANT','TEAM_TOTAL','GRAND_TOTAL','OTHER'))
);
COMMENT ON TABLE target_consultant_scorecard IS
  'The SC Performance tab, one row per consultant per lead type. Conversion
   percentages from the sheet are deliberately not stored - views recompute them so
   a DIV/0 error in the workbook cannot propagate into the database.';

CREATE UNIQUE INDEX ON target_consultant_scorecard (period_id, row_label, COALESCE(lead_type,''));

CREATE TABLE target_channel_funnel (
    id               serial PRIMARY KEY,
    period_id        smallint NOT NULL REFERENCES dim_period(period_id),
    channel          text NOT NULL,          -- CRM, TELE, WALKIN, WS, REFERRAL, EVENT, IPOPI, REVSPOT
    total_leads      integer,
    qualified_leads  integer,
    bookings         integer,
    UNIQUE (period_id, channel)
);
COMMENT ON TABLE target_channel_funnel IS
  'Channel roll-up from the foot of the SC Performance tab. Includes channels that
   never reach the CRM export (IPOPI, REVSPOT, EVENT), so it is not derivable from
   the lead table and has to be stored.';

CREATE TABLE target_booking_commitment (
    id                serial PRIMARY KEY,
    period_id         smallint NOT NULL REFERENCES dim_period(period_id),
    consultant_label  text NOT NULL,         -- as written on the tab (AKILESH, PRINCE, ...)
    window_label      text NOT NULL,         -- 'TILL 12TH', '13 TO 19', '20 TO 26'
    committed         numeric(10,2),
    achieved          numeric(10,2),
    UNIQUE (period_id, consultant_label, window_label)
);
COMMENT ON TABLE target_booking_commitment IS
  'Week by week booking commitments vs achievement (Book Comm VS Ach tab). Labels
   are a mix of consultants and team managers and are kept verbatim.';

CREATE TABLE target_daily_tracker (
    id                serial PRIMARY KEY,
    period_id         smallint NOT NULL REFERENCES dim_period(period_id),
    consultant_label  text NOT NULL,
    block_label       text,                  -- which channel block on the tab the row sits under
    enq_target        numeric(10,2),
    enq_achieved      numeric(10,2),
    booking_target    numeric(10,2),
    booking_achieved  numeric(10,2),
    td_target         numeric(10,2),
    td_achieved       numeric(10,2),
    retail_target     numeric(10,2),
    retail_achieved   numeric(10,2),
    live_booking      numeric(10,2)
);
COMMENT ON TABLE target_daily_tracker IS
  'Daily Tracker tab: per consultant daily targets by channel block. The tab is a
   wide multi block grid; the ETL unpivots the overall block plus each channel block.';

-- ---------------------------------------------------------------------
-- Load provenance
-- ---------------------------------------------------------------------

CREATE TABLE etl_run (
    run_id         serial PRIMARY KEY,
    source_file    text NOT NULL,
    file_modified  timestamp,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    row_counts     jsonb,
    notes          text
);
COMMENT ON TABLE etl_run IS 'One row per load of a DSR workbook, with per-table row counts.';


-- ---------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------

CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END $$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['vehicle', 'lead', 'test_drive', 'booking',
                             'allotment', 'registration']
    LOOP
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE ON dsr.%I '
            'FOR EACH ROW EXECUTE FUNCTION dsr.touch_updated_at()',
            t || '_touch', t);
    END LOOP;
END $$;

CREATE INDEX ON booking (origin);
CREATE INDEX ON lead (origin);
CREATE INDEX ON vehicle (origin);

-- FIX (2026-10-08): reset() and the month delete/clear routes filter on
-- load_period_id on every upload; index it alongside the column it was missing.
CREATE INDEX ON lead (load_period_id);
CREATE INDEX ON booking (load_period_id);
CREATE INDEX ON test_drive (load_period_id);
CREATE INDEX ON allotment (load_period_id);
CREATE INDEX ON registration (load_period_id);
