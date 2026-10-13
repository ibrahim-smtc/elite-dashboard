-- =====================================================================
-- One-off: protect customer PII that is ALREADY in the database.
--
-- PII POLICY (2026-10-08, revised 2026-10-12): db/pii.sql stops new full phone
-- numbers, emails and addresses being stored - phones and emails are masked
-- (984*******, rav***@gmail.com), addresses become [REDACTED]. This applies the
-- same rules to the rows written before that existed.
--
-- IRREVERSIBLE. Once this commits, the original values are gone from the
-- database - that is the point of it. Supabase's own backups and point-in-time
-- recovery still hold them until those age out. Values already [REDACTED] stay
-- [REDACTED]: there is nothing left to mask.
--
-- Run it through tools/migrate.py, which does a dry run first and reports how
-- many values are still stored in full:
--     python tools/migrate.py db/pii_backfill.sql            # dry run
--     python tools/migrate.py db/pii_backfill.sql --commit   # do it
--
-- Needs db/pii.sql applied first (it uses its functions). Only rows that still
-- hold PII are touched, so it is safe to run again. A phone/email column is
-- assigned to itself ("mobile = mobile"): the db/pii.sql trigger then encrypts
-- the full value (2026-10-13) and stores the mask. db/pii.sql already does
-- this for those columns when it is applied; this file covers the free text.
-- =====================================================================

SET search_path = dsr, public;

-- Customer names are scrubbed as well: a phone or email the CRM export wrote
-- into the name field is masked, and the name is kept (see db/pii.sql).
UPDATE dsr.lead
   SET mobile       = mobile,
       email        = email,
       enquiry_note = dsr.pii_scrub(enquiry_note),
       lead_name    = dsr.pii_scrub(lead_name)
 WHERE mobile       IS DISTINCT FROM dsr.pii_mask_phone(mobile)
    OR email        IS DISTINCT FROM dsr.pii_mask_email(email)
    OR enquiry_note IS DISTINCT FROM dsr.pii_scrub(enquiry_note)
    OR lead_name    IS DISTINCT FROM dsr.pii_scrub(lead_name);

UPDATE dsr.booking
   SET mobile        = mobile,
       notes         = dsr.pii_scrub(notes),
       customer_name = dsr.pii_scrub(customer_name)
 WHERE mobile        IS DISTINCT FROM dsr.pii_mask_phone(mobile)
    OR notes         IS DISTINCT FROM dsr.pii_scrub(notes)
    OR customer_name IS DISTINCT FROM dsr.pii_scrub(customer_name);

UPDATE dsr.test_drive
   SET mobile    = mobile,
       email     = email,
       lead_name = dsr.pii_scrub(lead_name)
 WHERE mobile    IS DISTINCT FROM dsr.pii_mask_phone(mobile)
    OR email     IS DISTINCT FROM dsr.pii_mask_email(email)
    OR lead_name IS DISTINCT FROM dsr.pii_scrub(lead_name);

UPDATE dsr.registration
   SET contact_no              = contact_no,
       email                   = email,
       address                 = dsr.pii_redact(address),
       customer_name           = dsr.pii_scrub(customer_name),
       nadcon_punched_customer = dsr.pii_scrub(nadcon_punched_customer)
 WHERE contact_no              IS DISTINCT FROM dsr.pii_mask_phone(contact_no)
    OR email                   IS DISTINCT FROM dsr.pii_mask_email(email)
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
           SET phone    = phone,
               address  = dsr.pii_redact(address),
               customer = dsr.pii_scrub(customer),
               note     = dsr.pii_scrub(note)
         WHERE phone    IS DISTINCT FROM dsr.pii_mask_phone(phone)
            OR address  IS DISTINCT FROM dsr.pii_redact(address)
            OR customer IS DISTINCT FROM dsr.pii_scrub(customer)
            OR note     IS DISTINCT FROM dsr.pii_scrub(note);
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('public.enquiries') IS NOT NULL THEN
        UPDATE public.enquiries
           SET mobile    = mobile,
               email     = email,
               full_name = dsr.pii_scrub(full_name),
               subject   = dsr.pii_scrub(subject),
               message   = dsr.pii_scrub(message)
         WHERE mobile    IS DISTINCT FROM dsr.pii_mask_phone(mobile)
            OR email     IS DISTINCT FROM dsr.pii_mask_email(email)
            OR full_name IS DISTINCT FROM dsr.pii_scrub(full_name)
            OR subject   IS DISTINCT FROM dsr.pii_scrub(subject)
            OR message   IS DISTINCT FROM dsr.pii_scrub(message);
    END IF;
END $$;
