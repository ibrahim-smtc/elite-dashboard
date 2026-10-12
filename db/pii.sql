-- =====================================================================
-- Customer PII protection, enforced by the database.
--
-- PII POLICY (2026-10-08, revised 2026-10-12): a customer's full phone
-- number, email address and postal address must not be stored. The app already
-- applies this on every route it owns (etl/pii.py), but the app is not the only
-- thing that writes here: the Perfox agent has direct SQL access to Supabase
-- and writes into dsr.lead, public.lead and public.enquiries itself. A rule
-- enforced only in Python would be bypassed by exactly the writer least likely
-- to follow it.
--
-- So every table that can hold a phone, an email or an address gets a BEFORE
-- INSERT OR UPDATE trigger here. Whatever arrives - from the loader, the API,
-- an agent, tools/sql.py, the Supabase table editor - is protected before the
-- row is written.
--
--   pii_mask_phone(v)  a phone column: first three digits kept, the rest '*'
--                      (9845012345 -> 984*******)
--   pii_mask_email(v)  an email column: first three characters of the name
--                      part kept, then '***@' and the domain
--                      (ravi.kumar@gmail.com -> rav***@gmail.com)
--   pii_redact(v)      an address column: anything given becomes '[REDACTED]',
--                      nothing given stays NULL
--   pii_scrub(t)       free text: phone numbers and emails inside it are masked
--                      as above, the rest of the text is kept
--
-- (Revision 2026-10-12: phone and email used to become '[REDACTED]' like the
-- address; the manager asked for masking instead. Rows stored before the change
-- keep '[REDACTED]' - masking it again leaves it as it is - because the
-- original values are gone. Uploading a month's workbook again stores them
-- masked.)
--
-- Every rule and pattern below is the same as etl/pii.py, character for
-- character; keep the two in step. Every function is idempotent - masking a
-- masked value changes nothing - because the trigger runs on every UPDATE.
--
-- Needs PostgreSQL 15 or later (regexp_instr / regexp_substr).
--
-- Re-runnable. Run after db/triggers.sql (it guards public.enquiries, which
-- that file creates) and after db/test_drives.sql. This file only affects rows
-- written from now on - rows already stored are handled by
-- db/pii_backfill.sql.
-- =====================================================================

SET search_path = dsr, public;

-- An address column. The blank words are etl/normalize.BLANKS: the sheet's own
-- ways of writing "nothing here", which count as nothing given.
CREATE OR REPLACE FUNCTION dsr.pii_redact(v text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN v IS NULL
          OR lower(regexp_replace(v, '^[[:space:]]+|[[:space:]]+$', '', 'g')) IN
             ('', '-', '--', 'n/a', 'na', 'nil', 'none', 'null',
              '#div/0!', '#value!', '#ref!', '#n/a', '#name?', '#num!')
        THEN NULL
        ELSE '[REDACTED]'
    END;
$$;

COMMENT ON FUNCTION dsr.pii_redact(text) IS
  'PII policy: an address column keeps only the fact that a value was given
   ([REDACTED]), never the value. See etl/pii.py.';


-- A phone number, however written, as its first three digits and a '*' for
-- each digit after them. More than ten digits keeps the last ten (drops a +91
-- or a leading 0); fewer than four is not a phone number and is removed.
CREATE OR REPLACE FUNCTION dsr.pii_mask_digits(t text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN length(d) < 4 THEN '[REDACTED]'
        ELSE left(d, 3) || repeat('*', length(d) - 3)
    END
      FROM (SELECT right(regexp_replace(coalesce(t, ''), '[^0-9]', '', 'g'), 10) AS d) x;
$$;


-- One email address: the first three characters of the name part (only the
-- first one when the name part is three characters or fewer), '***@', domain.
CREATE OR REPLACE FUNCTION dsr.pii_mask_email_address(a text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN length(l) > 3 THEN left(l, 3) ELSE left(l, 1) END
           || '***@' || substr(a, length(l) + 2)
      FROM (SELECT split_part(a, '@', 1) AS l) x;
$$;


CREATE OR REPLACE FUNCTION dsr.pii_mask_phone(v text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN dsr.pii_redact(v) IS NULL THEN NULL
        -- Already masked, or removed before masking existed: keep as it is.
        WHEN s = '[REDACTED]' OR s ~ '^[0-9]{3}\*+$' THEN s
        -- Excel hands a number typed into a cell over as 9845012345.0.
        ELSE dsr.pii_mask_digits(regexp_replace(s, '\.0+$', ''))
    END
      FROM (SELECT regexp_replace(v, '^[[:space:]]+|[[:space:]]+$', '', 'g') AS s) x;
$$;

COMMENT ON FUNCTION dsr.pii_mask_phone(text) IS
  'PII policy: a phone column keeps the first three digits, the rest become *.
   See etl/pii.py.';


CREATE OR REPLACE FUNCTION dsr.pii_mask_email(v text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN dsr.pii_redact(v) IS NULL THEN NULL
        WHEN s = '[REDACTED]' OR s ~ '^[^@[:space:]]{0,3}\*\*\*@[^[:space:]]+$' THEN s
        -- No recognisable email in it: removed, never shown.
        WHEN m IS NULL THEN '[REDACTED]'
        ELSE dsr.pii_mask_email_address(m)
    END
      FROM (SELECT s, substring(s FROM
                     '([A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})') AS m
              FROM (SELECT regexp_replace(v, '^[[:space:]]+|[[:space:]]+$', '', 'g') AS s) y) x;
$$;

COMMENT ON FUNCTION dsr.pii_mask_email(text) IS
  'PII policy: an email column keeps the first three characters of the name
   part and the domain (rav***@gmail.com). See etl/pii.py.';


-- Every match of one pattern in a text, masked where it stands.
CREATE OR REPLACE FUNCTION dsr.pii_mask_matches(t text, pattern text, how text)
RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    pos   int := 1;
    hit   int;
    found text;
    mask  text;
BEGIN
    IF t IS NULL THEN
        RETURN NULL;
    END IF;
    LOOP
        EXIT WHEN pos > length(t);
        hit := regexp_instr(t, pattern, pos);
        EXIT WHEN hit = 0;
        found := regexp_substr(t, pattern, hit);
        mask := CASE how WHEN 'email' THEN dsr.pii_mask_email_address(found)
                         ELSE dsr.pii_mask_digits(found) END;
        t := overlay(t PLACING mask FROM hit FOR length(found));
        pos := hit + length(mask);
    END LOOP;
    RETURN t;
END $$;


CREATE OR REPLACE FUNCTION dsr.pii_scrub(t text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT dsr.pii_mask_matches(
             dsr.pii_mask_matches(
               dsr.pii_mask_matches(t,
                 -- email (first, so an address with digits in it goes whole)
                 '[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}',
                 'email'),
               -- Indian mobile, with or without +91 / 0 and spacing
               '(?<![0-9])(\+?91[ -]?|0)?([6-9][0-9]{4}[ -]?[0-9]{5}|[6-9][0-9]{2}[ -][0-9]{3}[ -][0-9]{4})(?![0-9])',
               'phone'),
             -- landline with STD code
             '(?<![0-9])0[0-9]{2,4}[ -]?[0-9]{6,8}(?![0-9])',
             'phone');
$$;

COMMENT ON FUNCTION dsr.pii_scrub(text) IS
  'PII policy: masks phone numbers and email addresses inside free text and
   keeps the rest of it. See etl/pii.py.';


-- One trigger function for every table. Each trigger names its columns as
-- arguments - 'phone:<column>', 'email:<column>', 'redact:<column>' (an
-- address) or 'scrub:<column>' (free text) - so adding a column to the policy
-- is one argument, not a new function.
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
                WHEN 'phone'  THEN dsr.pii_mask_phone(val)
                WHEN 'email'  THEN dsr.pii_mask_email(val)
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
  'BEFORE INSERT OR UPDATE: applies pii_mask_phone / pii_mask_email / pii_redact
   / pii_scrub to the columns named in the trigger arguments. The PII policy
   backstop for writes that do not go through the app.';


-- FIX (2026-10-09): the live Supabase test_drive_booking table had lost its
-- `phone` column (dropped by hand after the PII mandate), while the app
-- (app/test_drives.py) and db/test_drives.sql still read and write it. The
-- Test Drives board would fail on that database, and db/pii_backfill.sql died
-- with `column "phone" does not exist` and rolled back, leaving home addresses
-- unredacted. Put the column back: from here on it only ever holds NULL or a
-- masked number (the trigger below), never a full one. No-op if present.
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
-- phone or email inside it is masked.
DO $$
DECLARE
    spec record;
BEGIN
    FOR spec IN
        SELECT * FROM (VALUES
            ('dsr',    'lead',         ARRAY['phone:mobile', 'email:email', 'scrub:enquiry_note',
                                             'scrub:lead_name']),
            ('dsr',    'booking',      ARRAY['phone:mobile', 'scrub:notes', 'scrub:customer_name']),
            ('dsr',    'test_drive',   ARRAY['phone:mobile', 'email:email', 'scrub:lead_name']),
            ('dsr',    'registration', ARRAY['phone:contact_no', 'email:email', 'redact:address',
                                             'scrub:customer_name', 'scrub:nadcon_punched_customer']),
            ('dsr',    'allotment',    ARRAY['scrub:remarks', 'scrub:customer_name']),
            -- The test-drive board (db/test_drives.sql): stores the customer's phone
            -- and, for a drive at their home, their address. Apply this file AFTER
            -- db/test_drives.sql, or this table is skipped (it does not exist yet).
            ('dsr',    'test_drive_booking',
                                       ARRAY['phone:phone', 'redact:address',
                                             'scrub:customer', 'scrub:note']),
            -- What the chat agent writes. Named so it sorts before
            -- enquiries_to_lead and runs first: the lead that trigger files is
            -- built from an enquiry row that is already clean.
            ('public', 'enquiries',    ARRAY['phone:mobile', 'email:email', 'scrub:full_name',
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
