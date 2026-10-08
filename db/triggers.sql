-- =====================================================================
-- Change notification.
--
-- Every write to a fact or target table announces itself on the `dsr_change`
-- channel. The API holds one connection LISTENing on that channel and fans the
-- events out to every open dashboard over server-sent events.
--
-- The point of doing it in the database rather than in the API is that the
-- database sees ALL writes. A row inserted by the dashboard, by the bulk loader,
-- by tools/sql.py, or by some future agent writing directly all reach the same
-- trigger, so no dashboard can drift out of date because a write took a
-- different path in.
--
-- Re-runnable: every trigger is dropped and recreated.
-- =====================================================================

SET search_path = dsr, public;

CREATE OR REPLACE FUNCTION notify_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    payload json;
    row_id  text;
BEGIN
    -- TRUNCATE is statement-level: there is no NEW/OLD row to report.
    IF TG_OP = 'TRUNCATE' THEN
        payload := json_build_object('table', TG_TABLE_NAME, 'op', TG_OP);
    ELSE
        -- to_jsonb(...)->>0 pulls the primary key out without the function
        -- needing to know each table's key column name.
        BEGIN
            row_id := CASE WHEN TG_OP = 'DELETE'
                           THEN to_jsonb(OLD) ->> (TG_ARGV[0])
                           ELSE to_jsonb(NEW) ->> (TG_ARGV[0]) END;
        EXCEPTION WHEN others THEN
            row_id := NULL;
        END;
        payload := json_build_object('table', TG_TABLE_NAME,
                                     'op', TG_OP,
                                     'id', row_id);
    END IF;

    -- pg_notify payloads are capped at 8000 bytes; this one is a few dozen.
    -- Notifications are delivered on COMMIT, so a listener never sees a change
    -- that later rolled back.
    PERFORM pg_notify('dsr_change', payload::text);
    RETURN NULL;                      -- AFTER trigger: return value is ignored
END $$;

COMMENT ON FUNCTION notify_change() IS
  'Announces a row change on the dsr_change channel. Takes the table''s primary
   key column name as its single trigger argument.';

-- Watched tables and their primary key column.
DO $$
DECLARE
    spec record;
BEGIN
    FOR spec IN
        SELECT * FROM (VALUES
            ('vehicle',                     'vehicle_id'),
            ('lead',                        'lead_id'),
            ('test_drive',                  'test_drive_id'),
            ('booking',                     'booking_id'),
            ('allotment',                   'allotment_id'),
            ('registration',                'registration_id'),
            ('target_consultant_scorecard', 'scorecard_id'),
            ('target_channel_funnel',       'id'),
            ('target_booking_commitment',   'id'),
            ('target_daily_tracker',        'id')
        ) AS t(tbl, pk)
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON dsr.%I',
                       spec.tbl || '_notify', spec.tbl);
        EXECUTE format(
            'CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON dsr.%I '
            'FOR EACH ROW EXECUTE FUNCTION dsr.notify_change(%L)',
            spec.tbl || '_notify', spec.tbl, spec.pk);

        -- One extra statement-level trigger so a workbook reload, which
        -- truncates, also tells the dashboards to refetch.
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON dsr.%I',
                       spec.tbl || '_notify_truncate', spec.tbl);
        EXECUTE format(
            'CREATE TRIGGER %I AFTER TRUNCATE ON dsr.%I '
            'FOR EACH STATEMENT EXECUTE FUNCTION dsr.notify_change(%L)',
            spec.tbl || '_notify_truncate', spec.tbl, spec.pk);
    END LOOP;
END $$;


-- ---------------------------------------------------------------------
-- Make an enquiry written straight into Supabase show up on the dashboard.
--
-- The chat agent is connected to Supabase directly, so it writes through
-- PostgREST, which only exposes `public`. `public.lead` is an auto-updatable
-- view over `dsr.lead`, so the agent's INSERT already succeeds today - and the
-- row is invisible. A naive insert supplies a name and a phone and nothing
-- else, so the row lands with period_id NULL, created_at NULL and
-- is_current_period false, and every headline view is scoped
-- `WHERE is_current_period`. The agent is told "success" and the dashboard
-- never moves.
--
-- The fix belongs on the view, not the table. The ETL sets search_path to
-- `dsr, public`, so the loader's INSERTs resolve to dsr.lead and never pass
-- through here - which matters, because the loader deliberately inserts the
-- 2024 historical dump with period_id NULL. Filling that in on the base table
-- would file 1,787 archive rows into 2024 reporting months that should not
-- exist. On the view, only writes arriving from outside are touched.
-- ---------------------------------------------------------------------

-- The model a customer names in free text, mapped to the dealership's
-- catalogue. Mirrors etl/normalize._FAMILY_PATTERNS, including its order:
-- "TIGUAN R-LINE" has to be tested before "TAIGUN" would ever match, and GOLF
-- resolves to GOLF GTI because that is the only Golf sold here.
CREATE OR REPLACE FUNCTION dsr.model_family_from_text(t text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN upper(t) LIKE '%TIGUAN R-LINE%' THEN 'TIGUAN R-LINE'
        WHEN upper(t) LIKE '%TAYRON%'        THEN 'TAYRON'
        WHEN upper(t) LIKE '%GOLF%'          THEN 'GOLF GTI'
        WHEN upper(t) LIKE '%VIRTUS%'        THEN 'VIRTUS'
        WHEN upper(t) LIKE '%TAIGUN%'        THEN 'TAIGUN'
        ELSE NULL END;
$$;


-- The trim a customer names, in the spelling the sheets already use. Only the
-- named lines are matched; "Sport" is deliberately absent, because "Taigun
-- Sport" is a model line rather than a trim and would mislabel every one.
--
-- Nothing is derived when more than one matches. A dropdown label that lists
-- what is on offer - "Taigun Sport (GT Line / GT Plus Sport)" - is a menu, not
-- a choice, and reading the first match out of it invented a trim the customer
-- never picked.
CREATE OR REPLACE FUNCTION dsr.trim_from_text(t text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    WITH hit AS (
        SELECT v.trim_name
          FROM (VALUES ('GT Plus',     '%GT PLUS%'),
                       ('GT Line',     '%GT LINE%'),
                       ('Comfortline', '%COMFORTLINE%'),
                       ('Highline',    '%HIGHLINE%'),
                       ('Topline',     '%TOPLINE%'),
                       ('Trendline',   '%TRENDLINE%')) AS v(trim_name, pat)
         WHERE upper(t) LIKE v.pat
    )
    SELECT trim_name FROM hit WHERE (SELECT count(*) FROM hit) = 1;
$$;


-- A colour the dealership actually stocks, if the customer named one. Longest
-- match wins, so "Wild Cherry Red Metallic" is not truncated to "Wild Cherry
-- Red". Matched against dim_colour rather than a hand-written list, so it
-- tracks the catalogue.
CREATE OR REPLACE FUNCTION dsr.colour_from_text(t text) RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT c.name FROM dsr.dim_colour c
     WHERE t IS NOT NULL AND upper(t) LIKE '%' || upper(c.name) || '%'
     ORDER BY length(c.name) DESC
     LIMIT 1;
$$;


CREATE OR REPLACE FUNCTION dsr.lead_insert_from_api() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    d    date;
    pid  smallint;
    act  boolean;
BEGIN
    -- An enquiry with no date is one that just came in.
    NEW.created_at := coalesce(NEW.created_at, now());
    d := NEW.created_at::date;

    IF NEW.period_id IS NULL THEN
        SELECT period_id, is_active INTO pid, act
          FROM dsr.dim_period
         WHERE d BETWEEN period_start AND period_end
         LIMIT 1;

        -- First enquiry of a month the dealership has not opened yet: create
        -- the month rather than dropping the lead. Same rule as period_for().
        IF pid IS NULL THEN
            INSERT INTO dsr.dim_period (label, period_start, period_end)
            VALUES (upper(to_char(d, 'MON')) || to_char(d, 'YYYY'),
                    date_trunc('month', d)::date,
                    (date_trunc('month', d) + interval '1 month'
                                            - interval '1 day')::date)
            ON CONFLICT (label) DO UPDATE SET label = EXCLUDED.label
            RETURNING period_id, is_active INTO pid, act;
        END IF;

        NEW.period_id := pid;
    END IF;

    -- Visible exactly when the lead belongs to the month being reported on.
    IF NEW.is_current_period IS NULL THEN
        SELECT is_active INTO act FROM dsr.dim_period
         WHERE period_id = NEW.period_id;
        NEW.is_current_period := coalesce(act, false);
    END IF;

    -- An enquiry with no channel counts in the headline total but drops out of
    -- the Lead Sources split, so the chart and the KPI disagree by one for
    -- every lead the agent files. A chat enquiry is a digital lead, so that is
    -- the channel it gets. Looked up by name rather than by id, because the
    -- surrogate key is not stable across a rebuild.
    IF NEW.source_id IS NULL THEN
        SELECT source_id INTO NEW.source_id
          FROM dsr.dim_lead_source WHERE name = 'DIGITAL';
    END IF;

    -- Resolve the model the customer named to the catalogue, so the enquiry
    -- counts in Model Demand and not only in the headline total. 95% of leads
    -- carry a model_id; one arriving without it is the odd one out.
    IF NEW.model_id IS NULL AND NEW.model_of_interest IS NOT NULL THEN
        SELECT m.model_id INTO NEW.model_id
          FROM dsr.dim_model m
         WHERE m.name = dsr.model_family_from_text(NEW.model_of_interest);
    END IF;

    -- Someone enquiring through the website is a retail customer. The two
    -- corporate types are entered by the fleet desk and never come from here,
    -- and Retail is 96% of every lead_type on the table.
    NEW.lead_type := coalesce(NEW.lead_type, 'Retail');

    -- Assigned onto NEW rather than inlined, so that an INSERT through this
    -- view can RETURNING lead_id - which is how public.enquiries learns which
    -- lead its row became.
    NEW.lead_id := coalesce(NEW.lead_id, nextval('dsr.lead_lead_id_seq'));

    INSERT INTO dsr.lead (
        lead_id, lead_record_id, created_at, lead_name, mobile, email,
        source_id, lead_type, model_of_interest, variant_of_interest,
        colour_of_interest, model_id, lead_owner, consultant_id, lead_status,
        rating, qualified_stage, test_drive_given, trade_in, trade_in_vehicle,
        dealership, period_id, origin, loaded_at, updated_at, entered_by,
        is_current_period)
    VALUES (
        NEW.lead_id,
        NEW.lead_record_id, NEW.created_at, NEW.lead_name, NEW.mobile,
        NEW.email, NEW.source_id, NEW.lead_type, NEW.model_of_interest,
        NEW.variant_of_interest, NEW.colour_of_interest, NEW.model_id,
        NEW.lead_owner, NEW.consultant_id,
        coalesce(NEW.lead_status, 'New'),
        NEW.rating,
        coalesce(NEW.qualified_stage, 'New'),
        NEW.test_drive_given, NEW.trade_in, NEW.trade_in_vehicle,
        NEW.dealership, NEW.period_id,
        -- MANUAL, not the WORKBOOK default. reset() deletes only
        -- origin = 'WORKBOOK', so an enquiry left as WORKBOOK would be
        -- silently deleted by the next monthly upload.
        coalesce(NEW.origin, 'MANUAL'),
        coalesce(NEW.loaded_at, now()),
        coalesce(NEW.updated_at, now()),
        coalesce(NEW.entered_by, 'agent'),
        NEW.is_current_period);

    RETURN NEW;
END $$;

COMMENT ON FUNCTION dsr.lead_insert_from_api() IS
  'Fills in the reporting month, the visibility flag and MANUAL provenance for
   leads written through public.lead - the path the chat agent uses via
   Supabase. Without it an agent enquiry is stored correctly and displayed
   nowhere.';

-- FIX (2026-10-08): public.lead was never created anywhere in the repo - it
-- only existed on the live Supabase database, made by hand - so on a database
-- built from these files the DROP TRIGGER below failed with 'relation
-- "public.lead" does not exist' and the rest of this file never ran.
--
-- Created only when absent, so the live view is left exactly as it is: CREATE
-- OR REPLACE VIEW would fail there if its column list differed by even one
-- column. The columns are the ones lead_insert_from_api() reads from NEW, plus
-- load_period_id; enquiry_note is deliberately not exposed (enquiry_to_lead()
-- sets it on dsr.lead directly).
DO $$
BEGIN
    IF to_regclass('public.lead') IS NULL THEN
        CREATE VIEW public.lead AS
        SELECT lead_id, lead_record_id, created_at, lead_name, mobile, email,
               source_id, lead_type, model_of_interest, variant_of_interest,
               colour_of_interest, model_id, lead_owner, consultant_id,
               lead_status, rating, qualified_stage, test_drive_given, trade_in,
               trade_in_vehicle, dealership, period_id, origin, loaded_at,
               updated_at, entered_by, is_current_period, load_period_id
          FROM dsr.lead;
    END IF;
END $$;

DROP TRIGGER IF EXISTS lead_insert_instead ON public.lead;
CREATE TRIGGER lead_insert_instead
    INSTEAD OF INSERT ON public.lead
    FOR EACH ROW EXECUTE FUNCTION dsr.lead_insert_from_api();


-- ---------------------------------------------------------------------
-- A table the agent cannot miss.
--
-- The chat agent has had write access to Supabase all along - it reads and
-- writes on demand when asked - but of five enquiries submitted through the
-- website today, it wrote exactly one. It is not failing; it is choosing not
-- to call the tool, and then telling the customer their enquiry was received.
--
-- Part of why is that there was nothing obvious to write to. The only target
-- was public.lead: a twenty-seven column view over a monthly reporting schema,
-- with period_id, is_current_period, qualified_stage and load_period_id. An
-- agent listing the tables sees nothing called "enquiry" anywhere, and a
-- Perfox "insert a row" action has twenty-seven columns to map.
--
-- So this is a five-column table named after the thing it holds, whose columns
-- are exactly the fields the enquiry form collects. A trigger turns each row
-- into a proper lead, so the dashboard picks it up with no further work.
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.enquiries (
    enquiry_id        bigserial PRIMARY KEY,
    full_name         text,
    email             text,
    mobile            text,
    subject           text,
    message           text,
    model_of_interest text,
    variant_of_interest text,
    colour_of_interest  text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    -- Filled in by the trigger: which lead this enquiry became. Gives the
    -- agent something to read back, and makes it obvious the row was filed.
    lead_id           integer
);

-- Added after the table first shipped, so CREATE TABLE IF NOT EXISTS above
-- would skip them on an existing database.
ALTER TABLE public.enquiries
    ADD COLUMN IF NOT EXISTS variant_of_interest text,
    ADD COLUMN IF NOT EXISTS colour_of_interest  text;

COMMENT ON TABLE public.enquiries IS
  'Customer enquiries captured by the chat agent. Insert a row here and it
   becomes a lead on the dashboard automatically - nothing else to set.';
COMMENT ON COLUMN public.enquiries.lead_id IS
  'Set by the trigger; the dsr.lead row this enquiry produced.';

-- Reachable with the credentials the agent already uses (which bypass RLS),
-- but not through the public anon key that is shipped in the website bundle -
-- this table is writable, and the widget is on a page anyone can open.
ALTER TABLE public.enquiries ENABLE ROW LEVEL SECURITY;


CREATE OR REPLACE FUNCTION public.enquiry_to_lead() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    new_lead integer;
BEGIN
    IF NEW.lead_id IS NULL AND coalesce(NEW.full_name, NEW.mobile) IS NOT NULL THEN
        -- Straight through public.lead, so the reporting month, the visibility
        -- flag, the DIGITAL channel and MANUAL provenance are all decided in
        -- one place rather than duplicated here.
        INSERT INTO public.lead (lead_name, mobile, email, model_of_interest,
                                 variant_of_interest, colour_of_interest,
                                 created_at)
        VALUES (NEW.full_name, NEW.mobile, NEW.email,
                -- The form has no model field, but the customer names one in
                -- the subject or the message ("Virtus GT availability").
                coalesce(NEW.model_of_interest,
                         dsr.model_family_from_text(
                             concat_ws(' ', NEW.subject, NEW.message))),
                -- Taken from the form when it asks, and otherwise read out of
                -- what the customer wrote. Neither is guessed: an enquiry that
                -- names no trim or colour keeps NULL.
                coalesce(NEW.variant_of_interest,
                         dsr.trim_from_text(
                             concat_ws(' ', NEW.subject, NEW.message))),
                coalesce(NEW.colour_of_interest,
                         dsr.colour_from_text(
                             concat_ws(' ', NEW.subject, NEW.message))),
                coalesce(NEW.created_at, now()))
        RETURNING lead_id INTO new_lead;

        -- What the customer actually wrote. public.lead does not expose
        -- enquiry_note, so it is set on the base table.
        UPDATE dsr.lead
           SET enquiry_note = nullif(concat_ws(' | ', NEW.subject, NEW.message), '')
         WHERE lead_id = new_lead;

        NEW.lead_id := new_lead;
    END IF;
    RETURN NEW;
END $$;

COMMENT ON FUNCTION public.enquiry_to_lead() IS
  'Turns a row in public.enquiries into a dashboard lead.';

DROP TRIGGER IF EXISTS enquiries_to_lead ON public.enquiries;
CREATE TRIGGER enquiries_to_lead
    BEFORE INSERT ON public.enquiries
    FOR EACH ROW EXECUTE FUNCTION public.enquiry_to_lead();


-- ---------------------------------------------------------------------
-- Catch a lead written straight into dsr.lead, whichever door it came through.
--
-- lead_insert_instead already fixes writes arriving through public.lead, which
-- is what PostgREST exposes. But the agent has full SQL and found the base
-- table, so it writes there instead - and the view trigger never fires. On
-- 2026-09-23 that produced a lead with period_id NULL, source_id NULL and
-- origin WORKBOOK: stored, invisible on every chart, and due to be deleted by
-- the next monthly upload.
--
-- The discriminator is entered_by. The ETL loader never sets it - all 4,202
-- workbook rows have it NULL - so a row that names who entered it did not come
-- from a workbook. That matters, because load_leads() files the 2024 TD Leads
-- archive with period_id NULL on purpose, and a trigger that filled those in
-- would invent 1,787 rows of 2024 reporting months.
--
-- Everything here fills a gap. A value supplied explicitly is kept, so the
-- dashboard's own entry form - which already sets all of this - passes through
-- untouched.
-- ---------------------------------------------------------------------

CREATE OR REPLACE FUNCTION dsr.lead_fill_direct() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    d    date;
    pid  smallint;
    act  boolean;
BEGIN
    IF NEW.entered_by IS NULL THEN
        RETURN NEW;                      -- a bulk load; leave it entirely alone
    END IF;

    NEW.created_at := coalesce(NEW.created_at, now());
    d := NEW.created_at::date;

    IF NEW.period_id IS NULL THEN
        SELECT period_id, is_active INTO pid, act
          FROM dsr.dim_period
         WHERE d BETWEEN period_start AND period_end
         LIMIT 1;

        IF pid IS NULL THEN
            INSERT INTO dsr.dim_period (label, period_start, period_end)
            VALUES (upper(to_char(d, 'MON')) || to_char(d, 'YYYY'),
                    date_trunc('month', d)::date,
                    (date_trunc('month', d) + interval '1 month'
                                            - interval '1 day')::date)
            ON CONFLICT (label) DO UPDATE SET label = EXCLUDED.label
            RETURNING period_id, is_active INTO pid, act;
        END IF;

        NEW.period_id := pid;
        NEW.is_current_period := coalesce(act, false);
    END IF;

    -- Without a channel the lead counts in the headline total but drops out of
    -- the Lead Sources split, so the chart and the tile above it disagree.
    IF NEW.source_id IS NULL THEN
        SELECT source_id INTO NEW.source_id
          FROM dsr.dim_lead_source WHERE name = 'DIGITAL';
    END IF;

    IF NEW.model_id IS NULL AND NEW.model_of_interest IS NOT NULL THEN
        SELECT m.model_id INTO NEW.model_id
          FROM dsr.dim_model m
         WHERE m.name = dsr.model_family_from_text(NEW.model_of_interest);
    END IF;

    NEW.lead_type := coalesce(NEW.lead_type, 'Retail');

    -- Not coalesced: origin defaults to WORKBOOK at the column, so a row that
    -- did not set it is indistinguishable from one that did. Since the loader
    -- never sets entered_by, anything reaching here is by definition not
    -- workbook output - and reset() deletes only WORKBOOK rows, so leaving it
    -- would have this lead swept away by the next monthly import.
    NEW.origin := 'MANUAL';

    RETURN NEW;
END $$;

COMMENT ON FUNCTION dsr.lead_fill_direct() IS
  'Fills the reporting month, channel, model and provenance for leads written
   directly into dsr.lead - the path the chat agent uses. Keyed on entered_by,
   which the ETL loader never sets, so a bulk load is never touched.';

DROP TRIGGER IF EXISTS lead_fill_direct ON dsr.lead;
CREATE TRIGGER lead_fill_direct
    BEFORE INSERT ON dsr.lead
    FOR EACH ROW EXECUTE FUNCTION dsr.lead_fill_direct();
