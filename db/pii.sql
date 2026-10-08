-- =====================================================================
-- Customer PII redaction, enforced by the database.
--
-- PII POLICY (2026-10-08): a customer's phone number, email address and postal
-- address must not be stored. The app already removes them on every route it
-- owns (etl/pii.py), but the app is not the only thing that writes here: the
-- Perfox agent has direct SQL access to Supabase and writes into dsr.lead,
-- public.lead and public.enquiries itself. A rule enforced only in Python would
-- be bypassed by exactly the writer least likely to follow it.
--
-- So every table that can hold a phone, an email or an address gets a BEFORE
-- INSERT OR UPDATE trigger here. Whatever arrives - from the loader, the API,
-- an agent, tools/sql.py, the Supabase table editor - is redacted before the
-- row is written.
--
--   pii_redact(v)  a column holding only a phone / email / address:
--                  anything given becomes '[REDACTED]', nothing given stays NULL
--   pii_scrub(t)   free text: phone numbers and emails inside it are replaced
--                  with [PHONE REDACTED] / [EMAIL REDACTED], the rest is kept
--
-- The three patterns below are the same text as etl/pii.py; keep them in step.
--
-- Re-runnable. Run after db/triggers.sql (it guards public.enquiries, which
-- that file creates). This file only affects rows written from now on - the
-- rows already in the database are cleaned by db/pii_backfill.sql.
-- =====================================================================

SET search_path = dsr, public;

CREATE OR REPLACE FUNCTION dsr.pii_redact(v text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        -- The sheet's own words for "nothing here" (etl/normalize.BLANKS).
        WHEN v IS NULL
          OR lower(btrim(v)) IN ('', '-', '--', 'n/a', 'na', 'nil', 'none', 'null')
        THEN NULL
        ELSE '[REDACTED]'
    END;
$$;

COMMENT ON FUNCTION dsr.pii_redact(text) IS
  'PII policy: a phone / email / address column keeps only the fact that a value
   was given ([REDACTED]), never the value. See etl/pii.py.';


CREATE OR REPLACE FUNCTION dsr.pii_scrub(t text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT regexp_replace(
             regexp_replace(
               regexp_replace(t,
                 -- email (first, so an address with digits in it goes whole)
                 '[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}',
                 '[EMAIL REDACTED]', 'g'),
               -- Indian mobile, with or without +91 / 0 and spacing
               '(?<![0-9])(\+?91[ -]?|0)?([6-9][0-9]{4}[ -]?[0-9]{5}|[6-9][0-9]{2}[ -][0-9]{3}[ -][0-9]{4})(?![0-9])',
               '[PHONE REDACTED]', 'g'),
             -- landline with STD code
             '(?<![0-9])0[0-9]{2,4}[ -]?[0-9]{6,8}(?![0-9])',
             '[PHONE REDACTED]', 'g');
$$;

COMMENT ON FUNCTION dsr.pii_scrub(text) IS
  'PII policy: removes phone numbers and email addresses from free text and keeps
   the rest of it. See etl/pii.py.';


-- One trigger function for every table. Each trigger names its columns as
-- arguments, 'redact:<column>' or 'scrub:<column>', so adding a column to the
-- policy is one argument, not a new function.
CREATE OR REPLACE FUNCTION dsr.pii_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    spec  text;
    col   text;
    val   text;
    cur   jsonb := to_jsonb(NEW);
    patch jsonb := '{}'::jsonb;
BEGIN
    FOREACH spec IN ARRAY TG_ARGV LOOP
        col := split_part(spec, ':', 2);
        val := cur ->> col;
        CONTINUE WHEN val IS NULL;
        patch := patch || jsonb_build_object(col,
            CASE split_part(spec, ':', 1)
                WHEN 'redact' THEN dsr.pii_redact(val)
                ELSE dsr.pii_scrub(val)
            END);
    END LOOP;
    IF patch <> '{}'::jsonb THEN
        NEW := jsonb_populate_record(NEW, patch);
    END IF;
    RETURN NEW;
END $$;

COMMENT ON FUNCTION dsr.pii_guard() IS
  'BEFORE INSERT OR UPDATE: applies pii_redact / pii_scrub to the columns named
   in the trigger arguments. The PII policy backstop for writes that do not go
   through the app.';


-- FIX (2026-10-09): the live Supabase test_drive_booking table had lost its
-- `phone` column (dropped by hand after the PII mandate), while the app
-- (app/test_drives.py) and db/test_drives.sql still read and write it. The
-- Test Drives board would fail on that database, and db/pii_backfill.sql died
-- with `column "phone" does not exist` and rolled back, leaving home addresses
-- unredacted. Put the column back: from here on it only ever holds NULL or
-- '[REDACTED]' (the trigger below), so it stores no PII. No-op if present.
DO $$
BEGIN
    IF to_regclass('dsr.test_drive_booking') IS NOT NULL THEN
        ALTER TABLE dsr.test_drive_booking ADD COLUMN IF NOT EXISTS phone text;
    END IF;
END $$;


-- Every column that can hold a customer's phone, email or address, and every
-- free-text column a customer's words can land in. Customer NAME columns are
-- scrubbed too: the CRM export sometimes writes the phone or the email into
-- the name field ("Naresh naresh@...", "Asif 98..."), so a name is kept but a
-- phone or email inside it is cut out.
DO $$
DECLARE
    spec record;
BEGIN
    FOR spec IN
        SELECT * FROM (VALUES
            ('dsr',    'lead',         ARRAY['redact:mobile', 'redact:email', 'scrub:enquiry_note',
                                             'scrub:lead_name']),
            ('dsr',    'booking',      ARRAY['redact:mobile', 'scrub:notes', 'scrub:customer_name']),
            ('dsr',    'test_drive',   ARRAY['redact:mobile', 'redact:email', 'scrub:lead_name']),
            ('dsr',    'registration', ARRAY['redact:contact_no', 'redact:email', 'redact:address',
                                             'scrub:customer_name', 'scrub:nadcon_punched_customer']),
            ('dsr',    'allotment',    ARRAY['scrub:remarks', 'scrub:customer_name']),
            -- The test-drive board (db/test_drives.sql): stores the customer's phone
            -- and, for a drive at their home, their address. Apply this file AFTER
            -- db/test_drives.sql, or this table is skipped (it does not exist yet).
            ('dsr',    'test_drive_booking',
                                       ARRAY['redact:phone', 'redact:address',
                                             'scrub:customer', 'scrub:note']),
            -- What the chat agent writes. Named so it sorts before
            -- enquiries_to_lead and runs first: the lead that trigger files is
            -- built from an enquiry row that is already clean.
            ('public', 'enquiries',    ARRAY['redact:mobile', 'redact:email', 'scrub:full_name',
                                             'scrub:subject', 'scrub:message'])
        ) AS t(sch, tbl, cols)
    LOOP
        CONTINUE WHEN to_regclass(format('%I.%I', spec.sch, spec.tbl)) IS NULL;
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I.%I',
                       spec.tbl || '_pii_guard', spec.sch, spec.tbl);
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE INSERT OR UPDATE ON %I.%I '
            'FOR EACH ROW EXECUTE FUNCTION dsr.pii_guard(%s)',
            spec.tbl || '_pii_guard', spec.sch, spec.tbl,
            (SELECT string_agg(quote_literal(c), ', ') FROM unnest(spec.cols) c));
    END LOOP;
END $$;
