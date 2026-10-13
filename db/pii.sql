-- =====================================================================
-- Customer PII protection, enforced by the database.
--
-- PII POLICY (2026-10-08, revised 2026-10-12 and 2026-10-13): a customer's
-- full phone number and email address are never stored READABLE, and the
-- postal address is not stored at all.
--
-- ENCRYPTION (2026-10-13): the full phone number / email is kept only as
-- ciphertext, in a companion column (mobile -> mobile_enc, email -> email_enc,
-- contact_no -> contact_no_enc, phone -> phone_enc). The trigger below
-- encrypts it with pgcrypto's OpenPGP public-key encryption, using the PUBLIC
-- key in dsr.pii_key. A public key can only lock: nothing in this database, in
-- Supabase or on the app server can decrypt. The private key is kept offline
-- by the admin (tools/pii_keys.py). Until a key is installed, nothing is
-- encrypted and only the mask is stored - exactly the 2026-10-12 behaviour.
-- If encryption fails for any reason the row is still written, masked, and a
-- WARNING is raised - a lost ciphertext is better than a lost lead.
--
-- FAIL-CLOSED: a CHECK constraint on every phone/email column accepts only a
-- masked value, '[REDACTED]' or NULL. If this trigger were ever dropped or
-- disabled, a write carrying a full number fails instead of storing it. The app already
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


-- ---------------------------------------------------------------------
-- ENCRYPTION (2026-10-13)
-- ---------------------------------------------------------------------

-- pgcrypto: already installed on Supabase (in the `extensions` schema); a new
-- local database gets it here.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto') THEN
        IF to_regnamespace('extensions') IS NOT NULL THEN
            CREATE EXTENSION pgcrypto WITH SCHEMA extensions;
        ELSE
            CREATE EXTENSION pgcrypto;
        END IF;
    END IF;
END $$;

-- The PUBLIC key(s) phone numbers and emails are encrypted with. Not secret.
-- One is active (used for new values); older ones stay so their ciphertexts
-- are still recognised after a key change. Installed with
-- tools/pii_keys.py install, which calls dsr.pii_install_key().
CREATE TABLE IF NOT EXISTS dsr.pii_key (
    key_id     text PRIMARY KEY,               -- OpenPGP key id (pgp_key_id)
    public_key text NOT NULL,                  -- ASCII-armored public key
    active     boolean NOT NULL DEFAULT true,
    added_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS pii_key_one_active ON dsr.pii_key (active) WHERE active;

COMMENT ON TABLE dsr.pii_key IS
  'PII policy (2026-10-13): public key(s) customer phones/emails are encrypted
   with. The matching private key is NOT in this database - it is kept offline.';

-- What is encrypted: the value as given, trimmed; a phone typed into Excel as
-- a number (9845012345.0) loses its ".0". The same as etl/pii.clean_phone /
-- clean_email, which the app sends.
CREATE OR REPLACE FUNCTION dsr.pii_plain(v text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT regexp_replace(regexp_replace(v, '^[[:space:]]+|[[:space:]]+$', '', 'g'),
                          '^([0-9]+)\.0+$', '\1');
$$;

-- The value encrypted with the active public key, or NULL when there is no
-- key or anything goes wrong (the row is then stored masked only, and a
-- WARNING says so). Never raises: encryption must not block a business write.
CREATE OR REPLACE FUNCTION dsr.pii_encrypt(v text) RETURNS bytea
LANGUAGE plpgsql VOLATILE
SET search_path = dsr, extensions, public, pg_catalog AS $$
DECLARE
    k text;
BEGIN
    IF v IS NULL THEN
        RETURN NULL;
    END IF;
    SELECT public_key INTO k FROM dsr.pii_key WHERE active;
    IF k IS NULL THEN
        RETURN NULL;
    END IF;
    RETURN pgp_pub_encrypt(v, dearmor(k), 'cipher-algo=aes256');
EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'PII encryption failed (%) - the value was stored masked only', SQLERRM;
    RETURN NULL;
END $$;

-- True when a ciphertext was made with one of this database's keys.
CREATE OR REPLACE FUNCTION dsr.pii_is_ours(e bytea) RETURNS boolean
LANGUAGE plpgsql STABLE
SET search_path = dsr, extensions, public, pg_catalog AS $$
DECLARE
    kid text;
BEGIN
    IF e IS NULL THEN
        RETURN false;
    END IF;
    kid := pgp_key_id(e);
    RETURN EXISTS (SELECT 1 FROM dsr.pii_key k WHERE k.key_id = kid);
EXCEPTION WHEN OTHERS THEN
    RETURN false;
END $$;

-- Install a public key (ASCII-armored) and make it the active one. Refuses a
-- private key, and any key pgcrypto cannot encrypt with (it needs RSA or
-- Elgamal, not ECC).
CREATE OR REPLACE FUNCTION dsr.pii_install_key(armored text) RETURNS text
LANGUAGE plpgsql
SET search_path = dsr, extensions, public, pg_catalog AS $$
DECLARE
    kid text;
BEGIN
    IF armored IS NULL OR position('PRIVATE KEY' IN upper(armored)) > 0 THEN
        RAISE EXCEPTION 'Refusing: this is not a public key. Never put the private key in the database.';
    END IF;
    -- The id a ciphertext made with this key will carry (pii_is_ours checks it).
    kid := pgp_key_id(pgp_pub_encrypt('test', dearmor(armored), 'cipher-algo=aes256'));
    UPDATE dsr.pii_key SET active = false WHERE active AND key_id <> kid;
    INSERT INTO dsr.pii_key (key_id, public_key, active) VALUES (kid, armored, true)
    ON CONFLICT (key_id) DO UPDATE SET public_key = EXCLUDED.public_key, active = true;
    RETURN kid;
END $$;


-- One trigger function for every table. Each trigger names its columns as
-- arguments - 'phone:<column>', 'email:<column>', 'redact:<column>' (an
-- address) or 'scrub:<column>' (free text) - so adding a column to the policy
-- is one argument, not a new function.
CREATE OR REPLACE FUNCTION dsr.pii_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    spec    text;
    kind    text;
    col     text;
    enc_col text;
    val     text;
    masked  text;
    has_enc boolean;
    cur     jsonb := to_jsonb(NEW);
    prev    jsonb := CASE WHEN TG_OP = 'UPDATE' THEN to_jsonb(OLD) END;
    patch   jsonb := '{}'::jsonb;
BEGIN
    FOREACH spec IN ARRAY TG_ARGV LOOP
        kind := split_part(spec, ':', 1);
        col  := split_part(spec, ':', 2);
        val  := cur ->> col;

        IF kind IN ('phone', 'email') THEN
            enc_col := col || '_enc';
            has_enc := cur ? enc_col;
            masked  := CASE kind WHEN 'phone' THEN dsr.pii_mask_phone(val)
                                 ELSE dsr.pii_mask_email(val) END;
            IF masked IS NULL THEN
                -- Nothing given (NULL, '', 'N/A'): no value, and no ciphertext.
                IF val IS NOT NULL THEN
                    patch := patch || jsonb_build_object(col, NULL);
                END IF;
                IF has_enc AND cur ->> enc_col IS NOT NULL THEN
                    patch := patch || jsonb_build_object(enc_col, NULL);
                END IF;
            ELSIF masked IS DISTINCT FROM val THEN
                -- A full value: kept only as ciphertext; the column shows the mask.
                patch := patch || jsonb_build_object(col, masked);
                IF has_enc THEN
                    patch := patch || jsonb_build_object(enc_col,
                                 dsr.pii_encrypt(dsr.pii_plain(val)));
                END IF;
            ELSIF has_enc AND cur ->> enc_col IS NOT NULL
                  AND (prev IS NULL OR (cur ->> enc_col) IS DISTINCT FROM (prev ->> enc_col))
                  AND NOT dsr.pii_is_ours((cur ->> enc_col)::bytea) THEN
                -- Already masked, and something was written into the ciphertext
                -- column that this database's key did not make: drop it.
                patch := patch || jsonb_build_object(enc_col, NULL);
            END IF;
        ELSE
            CONTINUE WHEN val IS NULL;
            patch := patch || jsonb_build_object(col,
                CASE kind WHEN 'redact' THEN dsr.pii_redact(val)
                          ELSE dsr.pii_scrub(val) END);
        END IF;
    END LOOP;
    IF patch <> '{}'::jsonb THEN
        NEW := jsonb_populate_record(NEW, patch);
    END IF;
    RETURN NEW;
END $$;

COMMENT ON FUNCTION dsr.pii_guard() IS
  'BEFORE INSERT OR UPDATE: a full phone/email is encrypted into <column>_enc
   and replaced by its mask; addresses become [REDACTED]; free text is masked.
   Applies to every writer - the app, the Perfox agent, the table editor.';


-- FIX (2026-10-09): the live Supabase test_drive_booking table had lost its
-- `phone` column (dropped by hand after the PII mandate), while the app
-- (app/test_drives.py) and db/test_drives.sql still read and write it. The
-- Test Drives board would fail on that database, and db/pii_backfill.sql died
-- with `column "phone" does not exist` and rolled back, leaving home addresses
-- unredacted. Put the column back: from here on it only ever holds NULL or a
-- masked number (the trigger below; the full one is in phone_enc, encrypted).
-- No-op if present.
DO $$
BEGIN
    IF to_regclass('dsr.test_drive_booking') IS NOT NULL THEN
        ALTER TABLE dsr.test_drive_booking ADD COLUMN IF NOT EXISTS phone text;
    END IF;
END $$;


-- The encrypted companion of every phone/email column (2026-10-13). bytea:
-- an OpenPGP message. Only the trigger writes it.
DO $$
DECLARE
    c record;
BEGIN
    FOR c IN
        SELECT * FROM (VALUES
            ('dsr', 'lead', 'mobile', 'phone'), ('dsr', 'lead', 'email', 'email'),
            ('dsr', 'booking', 'mobile', 'phone'),
            ('dsr', 'test_drive', 'mobile', 'phone'), ('dsr', 'test_drive', 'email', 'email'),
            ('dsr', 'registration', 'contact_no', 'phone'), ('dsr', 'registration', 'email', 'email'),
            ('dsr', 'test_drive_booking', 'phone', 'phone'),
            ('public', 'enquiries', 'mobile', 'phone'), ('public', 'enquiries', 'email', 'email')
        ) AS t(sch, tbl, col, kind)
    LOOP
        CONTINUE WHEN to_regclass(format('%I.%I', c.sch, c.tbl)) IS NULL;
        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN IF NOT EXISTS %I bytea',
                       c.sch, c.tbl, c.col || '_enc');
        EXECUTE format('COMMENT ON COLUMN %I.%I.%I IS %L', c.sch, c.tbl, c.col || '_enc',
                       'PII policy (2026-10-13): the full ' || c.col || ', encrypted with the '
                       'public key in dsr.pii_key. Decryptable only with the offline private key.');
    END LOOP;
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


-- Any full phone/email still stored (none on a database that has had this
-- file before) goes through the trigger above - encrypted and masked - so the
-- constraints below can be added. "SET col = col" is enough: the trigger sees
-- a full value arriving and does the rest.
DO $$
DECLARE
    c record;
BEGIN
    FOR c IN
        SELECT * FROM (VALUES
            ('dsr', 'lead', 'mobile', 'phone'), ('dsr', 'lead', 'email', 'email'),
            ('dsr', 'booking', 'mobile', 'phone'),
            ('dsr', 'test_drive', 'mobile', 'phone'), ('dsr', 'test_drive', 'email', 'email'),
            ('dsr', 'registration', 'contact_no', 'phone'), ('dsr', 'registration', 'email', 'email'),
            ('dsr', 'test_drive_booking', 'phone', 'phone'),
            ('public', 'enquiries', 'mobile', 'phone'), ('public', 'enquiries', 'email', 'email')
        ) AS t(sch, tbl, col, kind)
    LOOP
        CONTINUE WHEN to_regclass(format('%I.%I', c.sch, c.tbl)) IS NULL;
        EXECUTE format('UPDATE %I.%I SET %I = %I WHERE %I IS DISTINCT FROM dsr.%I(%I)',
                       c.sch, c.tbl, c.col, c.col, c.col,
                       CASE c.kind WHEN 'phone' THEN 'pii_mask_phone' ELSE 'pii_mask_email' END,
                       c.col);

        -- FAIL-CLOSED: only a mask, [REDACTED] or NULL may be stored here.
        EXECUTE format('ALTER TABLE %I.%I DROP CONSTRAINT IF EXISTS %I',
                       c.sch, c.tbl, c.tbl || '_' || c.col || '_protected');
        EXECUTE format('ALTER TABLE %I.%I ADD CONSTRAINT %I CHECK (%I IS NULL OR %I = %L OR %I ~ %L)',
                       c.sch, c.tbl, c.tbl || '_' || c.col || '_protected',
                       c.col, c.col, '[REDACTED]', c.col,
                       CASE c.kind WHEN 'phone' THEN '^[0-9]{3}\*+$'
                                   ELSE '^[^@[:space:]]{0,3}\*\*\*@[^[:space:]]+$' END);
    END LOOP;
END $$;
