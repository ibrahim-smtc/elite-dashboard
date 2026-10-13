-- =====================================================================
-- Dashboard sign-in roles, and the manager-only reveal of customer PII.
--
-- ROLE-BASED ACCESS (2026-10-13): everyone signs in to the dashboard with a
-- Supabase Auth account (app/auth.py). Supabase checks the password; THIS table
-- decides what the account may do. An account that is not listed here cannot
-- use the dashboard at all, even with a correct password - so an account
-- created by mistake in Supabase gets nothing.
--
--   manager   sees the dashboard, and can reveal one customer's full phone
--             number and email at a time (each reveal is logged below)
--   employee  sees the dashboard with phone numbers and emails masked only
--
-- Manage the list with tools/dashboard_users.py (add / remove / list).
--
-- Re-runnable. Run after db/pii.sql (pii_decrypt needs pgcrypto).
-- =====================================================================

SET search_path = dsr, public;

CREATE TABLE IF NOT EXISTS dsr.dashboard_user (
    email    text PRIMARY KEY CHECK (email = lower(btrim(email))),
    role     text NOT NULL CHECK (role IN ('manager', 'employee')),
    added_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE dsr.dashboard_user IS
  'Who may sign in to the dashboard, and as what. The password lives in Supabase
   Auth; an account not listed here is refused. See app/auth.py.';

-- Every time a manager reveals a customer's phone/email: who, when, which
-- record. Kept for audit (DPDP Rule 6 asks for access logs kept a year).
CREATE TABLE IF NOT EXISTS dsr.pii_reveal_log (
    reveal_id  bigserial PRIMARY KEY,
    at         timestamptz NOT NULL DEFAULT now(),
    user_email text NOT NULL,
    table_name text NOT NULL,
    row_id     text NOT NULL,
    fields     text[] NOT NULL
);
CREATE INDEX IF NOT EXISTS pii_reveal_log_at ON dsr.pii_reveal_log (at DESC);

COMMENT ON TABLE dsr.pii_reveal_log IS
  'Audit log: each manager reveal of a customer phone/email (app/pii_reveal.py).';

-- Decrypt one value with the PRIVATE key, which the app passes in for this
-- one call and which is never stored here (it lives in the app server's
-- PII_PRIVATE_KEY secret). The database keeps only the public key.
CREATE OR REPLACE FUNCTION dsr.pii_decrypt(e bytea, private_key text) RETURNS text
LANGUAGE sql STABLE
SET search_path = dsr, extensions, public, pg_catalog AS $$
    SELECT CASE WHEN e IS NULL THEN NULL
                ELSE pgp_pub_decrypt(e, dearmor(private_key)) END;
$$;

COMMENT ON FUNCTION dsr.pii_decrypt(bytea, text) IS
  'Decrypts a *_enc value with a private key given for this call only. Only the
   dashboard server calls it, for a signed-in manager (app/pii_reveal.py).';
