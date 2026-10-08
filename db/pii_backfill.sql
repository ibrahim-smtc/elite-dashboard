-- =====================================================================
-- One-off: remove customer PII that is ALREADY in the database.
--
-- PII POLICY (2026-10-08): db/pii.sql stops new phone numbers, emails and
-- addresses being stored. This cleans the rows written before that existed.
--
-- IRREVERSIBLE. Once this commits, the original values are gone from the
-- database - that is the point of it. Supabase's own backups and point-in-time
-- recovery still hold them until those age out.
--
-- Run it through tools/migrate.py, which does a dry run first and reports how
-- many values it would remove:
--     python tools/migrate.py db/pii_backfill.sql            # dry run
--     python tools/migrate.py db/pii_backfill.sql --commit   # do it
--
-- Needs db/pii.sql applied first (it uses pii_redact / pii_scrub). Only rows
-- that still hold PII are touched, so it is safe to run again.
-- =====================================================================

SET search_path = dsr, public;

-- Customer names are scrubbed as well: a phone or email the CRM export wrote
-- into the name field is cut out, and the name is kept (see db/pii.sql).
UPDATE dsr.lead
   SET mobile       = dsr.pii_redact(mobile),
       email        = dsr.pii_redact(email),
       enquiry_note = dsr.pii_scrub(enquiry_note),
       lead_name    = dsr.pii_scrub(lead_name)
 WHERE mobile       IS DISTINCT FROM dsr.pii_redact(mobile)
    OR email        IS DISTINCT FROM dsr.pii_redact(email)
    OR enquiry_note IS DISTINCT FROM dsr.pii_scrub(enquiry_note)
    OR lead_name    IS DISTINCT FROM dsr.pii_scrub(lead_name);

UPDATE dsr.booking
   SET mobile        = dsr.pii_redact(mobile),
       notes         = dsr.pii_scrub(notes),
       customer_name = dsr.pii_scrub(customer_name)
 WHERE mobile        IS DISTINCT FROM dsr.pii_redact(mobile)
    OR notes         IS DISTINCT FROM dsr.pii_scrub(notes)
    OR customer_name IS DISTINCT FROM dsr.pii_scrub(customer_name);

UPDATE dsr.test_drive
   SET mobile    = dsr.pii_redact(mobile),
       email     = dsr.pii_redact(email),
       lead_name = dsr.pii_scrub(lead_name)
 WHERE mobile    IS DISTINCT FROM dsr.pii_redact(mobile)
    OR email     IS DISTINCT FROM dsr.pii_redact(email)
    OR lead_name IS DISTINCT FROM dsr.pii_scrub(lead_name);

UPDATE dsr.registration
   SET contact_no              = dsr.pii_redact(contact_no),
       email                   = dsr.pii_redact(email),
       address                 = dsr.pii_redact(address),
       customer_name           = dsr.pii_scrub(customer_name),
       nadcon_punched_customer = dsr.pii_scrub(nadcon_punched_customer)
 WHERE contact_no              IS DISTINCT FROM dsr.pii_redact(contact_no)
    OR email                   IS DISTINCT FROM dsr.pii_redact(email)
    OR address                 IS DISTINCT FROM dsr.pii_redact(address)
    OR customer_name           IS DISTINCT FROM dsr.pii_scrub(customer_name)
    OR nadcon_punched_customer IS DISTINCT FROM dsr.pii_scrub(nadcon_punched_customer);

UPDATE dsr.allotment
   SET remarks       = dsr.pii_scrub(remarks),
       customer_name = dsr.pii_scrub(customer_name)
 WHERE remarks       IS DISTINCT FROM dsr.pii_scrub(remarks)
    OR customer_name IS DISTINCT FROM dsr.pii_scrub(customer_name);

-- The test-drive board stores a phone and, for drives at the customer's home,
-- an address (db/test_drives.sql). Skipped if that file was never applied.
DO $$
BEGIN
    IF to_regclass('dsr.test_drive_booking') IS NOT NULL THEN
        -- FIX (2026-10-09): see db/pii.sql - the live table had lost this
        -- column, and the UPDATE below failed on it. No-op if present.
        ALTER TABLE dsr.test_drive_booking ADD COLUMN IF NOT EXISTS phone text;
        UPDATE dsr.test_drive_booking
           SET phone    = dsr.pii_redact(phone),
               address  = dsr.pii_redact(address),
               customer = dsr.pii_scrub(customer),
               note     = dsr.pii_scrub(note)
         WHERE phone    IS DISTINCT FROM dsr.pii_redact(phone)
            OR address  IS DISTINCT FROM dsr.pii_redact(address)
            OR customer IS DISTINCT FROM dsr.pii_scrub(customer)
            OR note     IS DISTINCT FROM dsr.pii_scrub(note);
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('public.enquiries') IS NOT NULL THEN
        UPDATE public.enquiries
           SET mobile    = dsr.pii_redact(mobile),
               email     = dsr.pii_redact(email),
               full_name = dsr.pii_scrub(full_name),
               subject   = dsr.pii_scrub(subject),
               message   = dsr.pii_scrub(message)
         WHERE mobile    IS DISTINCT FROM dsr.pii_redact(mobile)
            OR email     IS DISTINCT FROM dsr.pii_redact(email)
            OR full_name IS DISTINCT FROM dsr.pii_scrub(full_name)
            OR subject   IS DISTINCT FROM dsr.pii_scrub(subject)
            OR message   IS DISTINCT FROM dsr.pii_scrub(message);
    END IF;
END $$;
