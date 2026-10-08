-- =====================================================================
-- Test drives: every one the showroom books, in one table - booked by the
-- AI agent on the call, and filed on their own from test-drive enquiries.
--
-- Two ways in, one rule.
--
--   BOOK   The agent saves the caller's enquiry, then runs
--          dsr.book_test_drive(lead_id, model, day, time, place, address)
--          while the caller is on the line. It books the slot, or answers
--          slot_taken with the nearest free times, or invalid with what to
--          ask - so the agent never tells a caller "booked" untruthfully.
--
--   NOTE   A safety net for the calls where the agent saves the enquiry but
--          does not book: the trigger lead_test_drive reads the enquiry's
--          note ("Test drive for Tiguan at showroom on 26th Oct at 10 AM")
--          and books the slot when the note says enough and the slot is
--          free, or files a request for the team to give a time.
--
--   The rule: one live test drive per customer per car. A customer who
--   calls again - to confirm, or to move the drive - finds the drive they
--   already have, by enquiry or by phone and first name, never a second.
--
-- Depends on schema.sql (lead, dim_model, dim_consultant, touch_updated_at)
-- and triggers.sql (notify_change, model_family_from_text).
-- Re-runnable: every object is created if missing or replaced.
-- =====================================================================

SET search_path = dsr, public;

CREATE TABLE IF NOT EXISTS dsr.test_drive_booking (
    booking_id  text PRIMARY KEY
                DEFAULT substr(md5(random()::text || clock_timestamp()::text), 1, 12),
    -- The model family the drive is on, as the board names it ("taigun",
    -- "tiguan"): one demo car per family.
    car_id      text,
    td_date     date,
    start_time  text CHECK (start_time IS NULL OR start_time ~ '^\d{2}:\d{2}$'),
    -- The time the customer asked for, kept even when it could not be the
    -- slot - outside the board's hours, or already taken.
    asked_time  text,
    customer    text NOT NULL,
    phone       text,
    consultant  text,
    location    text NOT NULL DEFAULT 'Showroom' CHECK (location IN ('Showroom', 'Home')),
    address     text,
    source      text NOT NULL DEFAULT 'Staff' CHECK (source IN ('AI agent', 'Staff', 'Walk-in')),
    status      text NOT NULL DEFAULT 'booked'
                CHECK (status IN ('requested', 'booked', 'attended', 'no_show', 'cancelled')),
    call_id     text,
    -- The enquiry this drive came from - the latest, when a customer called
    -- more than once. A plain column, not a foreign key: a month's leads can
    -- be cleared and reloaded, and its drives must survive.
    lead_id     integer,
    note        text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Sample drives: made-up test drives that fill the calendar for showing the
-- section, flagged so they never hold a slot a real customer could take (the
-- slot index, the agent's free-slot check and its booking all pass over
-- them) and so they go in one statement:
--     DELETE FROM dsr.test_drive_booking WHERE sample;
ALTER TABLE dsr.test_drive_booking ADD COLUMN IF NOT EXISTS sample boolean NOT NULL DEFAULT false;

-- Only a request, or a drive called off, may be without its car, day and
-- slot - and a no-show that was only ever an enquiry: the customer asked for
-- a day, it passed with no booking, so it has its day but never had a slot
-- (lapse_test_drive_enquiries). (Replaced rather than created, so a re-run
-- also widens an older one.)
ALTER TABLE dsr.test_drive_booking DROP CONSTRAINT IF EXISTS test_drive_booking_placed;
ALTER TABLE dsr.test_drive_booking ADD CONSTRAINT test_drive_booking_placed CHECK (
    status IN ('requested', 'cancelled')
    OR (status = 'no_show' AND td_date IS NOT NULL AND start_time IS NULL)
    OR (car_id IS NOT NULL AND td_date IS NOT NULL AND start_time IS NOT NULL));

COMMENT ON TABLE dsr.test_drive_booking IS
  'Test drives: booked by the AI agent on the call (book_test_drive), on the
   Test Drives board, or filed from test-drive enquiries (lead_test_drive).
   status = requested means the day or time is still to be confirmed; a
   no_show with no start_time is an enquiry whose day passed with no booking.';

-- One drive per car per slot. Cancelled drives, requests and sample drives
-- hold no slot. (Dropped and made again, so a re-run also narrows an older one.)
DROP INDEX IF EXISTS dsr.test_drive_booking_slot;
CREATE UNIQUE INDEX test_drive_booking_slot
    ON dsr.test_drive_booking (car_id, td_date, start_time)
    WHERE status IN ('booked', 'attended', 'no_show') AND NOT sample;
CREATE INDEX IF NOT EXISTS test_drive_booking_day  ON dsr.test_drive_booking (td_date);
CREATE INDEX IF NOT EXISTS test_drive_booking_lead ON dsr.test_drive_booking (lead_id);

DROP TRIGGER IF EXISTS test_drive_booking_touch ON dsr.test_drive_booking;
CREATE TRIGGER test_drive_booking_touch
    BEFORE UPDATE ON dsr.test_drive_booking
    FOR EACH ROW EXECUTE FUNCTION dsr.touch_updated_at();

-- Every open dashboard refetches when a drive is filed, booked or changed.
DROP TRIGGER IF EXISTS test_drive_booking_notify ON dsr.test_drive_booking;
CREATE TRIGGER test_drive_booking_notify
    AFTER INSERT OR UPDATE OR DELETE ON dsr.test_drive_booking
    FOR EACH ROW EXECUTE FUNCTION dsr.notify_change('booking_id');


-- ---------------------------------------------------------------------
-- Small helpers.
-- ---------------------------------------------------------------------

-- The board's name for a model family: "TIGUAN" -> "tiguan". The same rule as
-- _slug() in app/test_drives.py.
CREATE OR REPLACE FUNCTION dsr.car_id_for(family text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT nullif(btrim(regexp_replace(lower(family), '[^a-z0-9]+', '-', 'g'), '-'), '');
$$;

-- The board's car for a model named in free text: the catalogue's reading
-- first, then any family the text names as a whole word ("Tiguan" is the
-- Tiguan R-Line). Words are compared, not built into a pattern, so a family
-- with odd characters in it can never break the lookup.
CREATE OR REPLACE FUNCTION dsr.car_for_model(t text) RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT coalesce(
        (SELECT dsr.car_id_for(dm.family) FROM dsr.dim_model dm
          WHERE dm.name = dsr.model_family_from_text(t) LIMIT 1),
        (SELECT dsr.car_id_for(dm.family) FROM dsr.dim_model dm
          WHERE upper(dm.family) = ANY (regexp_split_to_array(upper(coalesce(t, '')), '[^A-Z0-9-]+'))
          ORDER BY length(dm.family) DESC LIMIT 1));
$$;

-- What the agent says the car is called: "Virtus", "Tiguan R-Line".
CREATE OR REPLACE FUNCTION dsr.car_name(car text) RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT CASE WHEN count(*) = 1 THEN initcap(min(dm.name)) ELSE initcap(min(dm.family)) END
      FROM dsr.dim_model dm WHERE dsr.car_id_for(dm.family) = car;
$$;

-- make_date that answers NULL for a day that does not exist (31 Feb).
CREATE OR REPLACE FUNCTION dsr.safe_date(y int, m int, d int) RETURNS date
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    RETURN make_date(y, m, d);
EXCEPTION WHEN others THEN
    RETURN NULL;
END $$;

-- Phone and first name together: one person. A phone alone is not enough -
-- the agent's test calls put several names on one number.
CREATE OR REPLACE FUNCTION dsr.phone10(p text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT nullif(right(regexp_replace(coalesce(p, ''), '\D', '', 'g'), 10), '');
$$;
CREATE OR REPLACE FUNCTION dsr.first_name(n text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT nullif(split_part(lower(btrim(coalesce(n, ''))), ' ', 1), '');
$$;

-- The board's half-hour slots: 09:30 to the last start at 18:30.
CREATE OR REPLACE FUNCTION dsr.test_drive_slots() RETURNS SETOF text
LANGUAGE sql IMMUTABLE AS $$
    SELECT to_char(s, 'HH24:MI')
      FROM generate_series(timestamp '2000-01-01 09:30', timestamp '2000-01-01 18:30',
                           interval '30 minutes') s;
$$;

-- Is this enquiry a request for a test drive? The agent says so outright
-- (lead_type test_drive). Otherwise only an unclassified or retail enquiry
-- whose note asks for one - not one telling of a drive already taken, and
-- not one the agent filed as service, insurance or anything else.
CREATE OR REPLACE FUNCTION dsr.is_test_drive_request(lead_type text, note text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
    SELECT coalesce(lead_type, '') = 'test_drive'
        OR (coalesce(lead_type, 'Retail') = 'Retail'
            AND coalesce(note, '') ~* '\mtest[\s-]?drives?\M'
            AND coalesce(note, '') !~* '\m(took|taken|had|given|completed|done)\s+(a\s+|the\s+|my\s+)?test[\s-]?drives?\M'
            AND coalesce(note, '') !~* '\mtest[\s-]?drives?\s+(was\s+|is\s+)?(already\s+)?(done|given|completed|taken)\M');
$$;


-- ---------------------------------------------------------------------
-- Reading a day, a time and a place.
-- ---------------------------------------------------------------------

-- When and where a test drive was agreed, read from the agent's note, or
-- from the day and time the agent passes to book_test_drive.
--
--   scope  Read from the first "test drive" on, with anything in brackets
--          left out: "Call back after 6 PM. Test drive Saturday at 11 AM"
--          is a drive at 11, and "(No. 12/3, Mayur Vihar)" is an address,
--          not 12 March or 2 May.
--   date   Whichever date expression comes first: 2026-10-26, 26th Oct,
--          October 26, on 26/10, today, tomorrow, Saturday, Monday next
--          week. Only whole month names count, so Market and Deccan are not
--          months. A weekday means the next one - "Monday" said on a Monday
--          is a week away. A day already past is no date at all.
--   time   The first time of day in scope: "10 AM", "11:00 AM", "11:30",
--          "at 4.30" - not "11.30 lakh". A bare hour before 8 is afternoon.
--   place  Home when the note says the drive is at a home, house or
--          residence (not "works from home"), with the address from the
--          first brackets after it; otherwise the showroom.
CREATE OR REPLACE FUNCTION dsr.test_drive_when(
    note text, base date,
    OUT td_date date, OUT asked_time text, OUT place text, OUT address text)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    raw    text := coalesce(note, '');
    t      text := lower(coalesce(note, ''));
    s      text;
    tp     text;
    p      int;
    pos    int;
    best   int := 2147483647;
    cand   date;
    m      text[];
    months constant text[] := ARRAY['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'];
    -- ISO day of the week, Monday = 1.
    days   constant text[] := ARRAY['mon','tues','wednes','thurs','fri','satur','sun'];
    mon    constant text := '(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?';
    h int; mi int; delta int;
BEGIN
    -- Where.
    tp := regexp_replace(t, '\mwork(s|ing)?\s+from\s+home\M', ' ', 'g');
    IF tp ~ '\m(at|from)\s+(\S+\s+){0,2}(home|house|residence|place|flat|apartment)\M'
       OR tp ~ '\mto\s+(\S+\s+){0,2}(home|house|residence)\M'
       OR tp ~ '\mhome\s+(test\s*)?drive\M' OR tp ~ '\mdoorstep\M' THEN
        place := 'Home';
        m := regexp_match(raw, '(home|house|residence|place|flat|apartment)[^(]{0,60}\(([^)]{3,160})\)', 'i');
        address := nullif(btrim(m[2]), '');
    ELSE
        place := 'Showroom';
    END IF;

    -- Scope.
    s := regexp_replace(t, '\([^)]*\)', ' ', 'g');
    p := regexp_instr(s, 'test[\s-]?drive');
    IF p > 0 THEN
        s := substr(s, p);
    END IF;

    -- Date: the earliest expression in scope.
    pos := regexp_instr(s, '\m\d{4}-\d{1,2}-\d{1,2}\M');
    IF pos > 0 THEN
        m := regexp_match(substr(s, pos), '^(\d{4})-(\d{1,2})-(\d{1,2})');
        cand := dsr.safe_date(m[1]::int, m[2]::int, m[3]::int);
        IF cand IS NOT NULL AND pos < best THEN best := pos; td_date := cand; END IF;
    END IF;

    pos := regexp_instr(s, '\m\d{1,2}(?:st|nd|rd|th)?\s*(?:of\s+)?' || mon || '\M');
    IF pos > 0 THEN
        m := regexp_match(substr(s, pos), '^(\d{1,2})(?:st|nd|rd|th)?\s*(?:of\s+)?' || mon);
        cand := dsr.safe_date(extract(year FROM base)::int, array_position(months, left(m[2], 3)), m[1]::int);
        -- Only a genuine turn of the year: "5th Jan" written in December.
        IF cand < base - 180 THEN cand := (cand + interval '1 year')::date; END IF;
        IF cand IS NOT NULL AND pos < best THEN best := pos; td_date := cand; END IF;
    END IF;

    pos := regexp_instr(s, '\m' || mon || '\s+\d{1,2}(?:st|nd|rd|th)?\M');
    IF pos > 0 THEN
        m := regexp_match(substr(s, pos), '^' || mon || '\s+(\d{1,2})');
        cand := dsr.safe_date(extract(year FROM base)::int, array_position(months, left(m[1], 3)), m[2]::int);
        IF cand < base - 180 THEN cand := (cand + interval '1 year')::date; END IF;
        IF cand IS NOT NULL AND pos < best THEN best := pos; td_date := cand; END IF;
    END IF;

    -- Day/month only where it plainly is a date: with a year, or after "on".
    pos := regexp_instr(s, '\m(?:on|date|dated|dt)\s+\d{1,2}/\d{1,2}(?:/\d{2,4})?\M');
    IF pos = 0 THEN
        pos := regexp_instr(s, '\m\d{1,2}/\d{1,2}/\d{2,4}\M');
    END IF;
    IF pos > 0 THEN
        m := regexp_match(substr(s, pos), '(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?');
        cand := dsr.safe_date(
            CASE WHEN m[3] IS NULL THEN extract(year FROM base)::int
                 WHEN length(m[3]) = 2 THEN 2000 + m[3]::int
                 ELSE m[3]::int END,
            m[2]::int, m[1]::int);
        IF m[3] IS NULL AND cand < base - 180 THEN cand := (cand + interval '1 year')::date; END IF;
        IF cand IS NOT NULL AND pos < best THEN best := pos; td_date := cand; END IF;
    END IF;

    pos := regexp_instr(s, '\mday after tomorrow\M');
    IF pos > 0 AND pos < best THEN best := pos; td_date := base + 2; END IF;
    pos := regexp_instr(s, '\mtomorrow\M');
    IF pos > 0 AND pos < best THEN best := pos; td_date := base + 1; END IF;
    pos := regexp_instr(s, '\mtoday\M');
    IF pos > 0 AND pos < best THEN best := pos; td_date := base; END IF;

    pos := regexp_instr(s, '\m(mon|tues|wednes|thurs|fri|satur|sun)day\M');
    IF pos > 0 AND pos < best THEN
        m := regexp_match(substr(s, pos), '^(mon|tues|wednes|thurs|fri|satur|sun)day');
        delta := (array_position(days, m[1]) - extract(isodow FROM base)::int + 7) % 7;
        IF delta = 0 THEN delta := 7; END IF;
        cand := base + delta;
        -- "Saturday next week", said on a Monday, is not five days away.
        IF s ~ '\mnext\s+week\M' AND date_trunc('week', cand) = date_trunc('week', base) THEN
            cand := cand + 7;
        END IF;
        best := pos;
        td_date := cand;
    END IF;

    IF td_date < base THEN
        td_date := NULL;
    END IF;

    -- Time: the first in scope.
    FOR m IN SELECT regexp_matches(s, '\m(\d{1,2})(?:[:.](\d{2}))?\s*([ap])\.?\s*m\M', 'g') LOOP
        h := m[1]::int % 12 + CASE WHEN m[3] = 'p' THEN 12 ELSE 0 END;
        mi := coalesce(m[2]::int, 0);
        IF h BETWEEN 7 AND 21 AND mi < 60 THEN
            asked_time := lpad(h::text, 2, '0') || ':' || lpad(mi::text, 2, '0');
            EXIT;
        END IF;
    END LOOP;
    IF asked_time IS NULL THEN
        -- "11:30", or "at 4.30"; a dotted number on its own is a price.
        FOR m IN SELECT regexp_matches(s, '(?:\m(\d{1,2}):(\d{2})\M|\mat\s+(\d{1,2})\.(\d{2})\M)', 'g') LOOP
            h := coalesce(m[1], m[3])::int;
            mi := coalesce(m[2], m[4])::int;
            IF h BETWEEN 1 AND 7 THEN h := h + 12; END IF;
            IF h BETWEEN 8 AND 21 AND mi < 60 THEN
                asked_time := lpad(h::text, 2, '0') || ':' || lpad(mi::text, 2, '0');
                EXIT;
            END IF;
        END LOOP;
    END IF;
    IF asked_time IS NULL AND s ~ '\mnoon\M' THEN
        asked_time := '12:00';
    END IF;
END $$;


-- ---------------------------------------------------------------------
-- A customer's live drives.
-- ---------------------------------------------------------------------

-- Free slots on one car on one day, earliest first; today's past times left out.
CREATE OR REPLACE FUNCTION dsr.test_drive_open(car text, d date) RETURNS SETOF text
LANGUAGE sql STABLE AS $$
    SELECT s FROM dsr.test_drive_slots() s
     WHERE (d > (now() AT TIME ZONE 'Asia/Kolkata')::date
            OR s > to_char(now() AT TIME ZONE 'Asia/Kolkata', 'HH24:MI'))
       AND NOT EXISTS (SELECT 1 FROM dsr.test_drive_booking b
                        WHERE b.car_id = car AND b.td_date = d AND b.start_time = s
                          AND b.status IN ('booked', 'attended', 'no_show') AND NOT b.sample)
     ORDER BY s;
$$;

-- The drives a customer still has coming on a car: filed for this enquiry,
-- or for the same phone and first name from an earlier call. A booking
-- first, then the newest. Live means a booking or request from `from_day`
-- on, or a request with no day yet filed in the last 30 days.
CREATE OR REPLACE FUNCTION dsr.live_drives(
    p_lead_id integer, p_phone text, p_name text, p_car text, from_day date)
RETURNS SETOF dsr.test_drive_booking
LANGUAGE sql STABLE AS $$
    SELECT b.* FROM dsr.test_drive_booking b
     WHERE b.status IN ('requested', 'booked') AND NOT b.sample
       AND (b.lead_id = p_lead_id
            OR (dsr.phone10(p_phone) IS NOT NULL
                AND dsr.phone10(b.phone) = dsr.phone10(p_phone)
                AND dsr.first_name(b.customer) = dsr.first_name(p_name)
                AND (b.car_id IS NULL OR p_car IS NULL OR b.car_id = p_car)))
       AND (b.td_date >= from_day OR (b.td_date IS NULL AND b.created_at >= from_day - 30))
     ORDER BY (b.status = 'booked') DESC, b.created_at DESC;
$$;


-- ---------------------------------------------------------------------
-- LAPSE: an enquiry whose day has gone by.
-- ---------------------------------------------------------------------

-- An enquiry that asked for a day, and saw the day pass with no booking, is a
-- no-show: the customer asked for that day and did not come. It keeps its
-- day and never gains a slot, as it never held one. An enquiry with no day
-- never lapses. Run by the board as it reads, and before the agent files or
-- books, so everyone sees the same; with nothing to mark it writes nothing
-- (so sends no change notice), and a failure here never stops the caller.
-- Returns how many it marked.
CREATE OR REPLACE FUNCTION dsr.lapse_test_drive_enquiries() RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
    today date := (now() AT TIME ZONE 'Asia/Kolkata')::date;
    n     integer := 0;
BEGIN
    IF EXISTS (SELECT 1 FROM dsr.test_drive_booking
                WHERE status = 'requested' AND td_date < today) THEN
        UPDATE dsr.test_drive_booking SET status = 'no_show', start_time = NULL
         WHERE status = 'requested' AND td_date < today;
        GET DIAGNOSTICS n = ROW_COUNT;
    END IF;
    RETURN n;
EXCEPTION WHEN others THEN
    RAISE WARNING 'test-drive enquiries not marked no-show: %', SQLERRM;
    RETURN 0;
END $$;


-- ---------------------------------------------------------------------
-- NOTE: filing a test drive from an enquiry.
-- ---------------------------------------------------------------------

-- Returns the booking_id the enquiry is filed under. `base` is the day the
-- note's "tomorrow" and "Saturday" count from: today in India when the
-- trigger fires as the enquiry is saved, the enquiry's own day for the
-- backfill. Safe to call again for the same enquiry.
CREATE OR REPLACE FUNCTION dsr.file_test_drive(l dsr.lead, base date DEFAULT NULL) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
    b0      date := coalesce(base, l.created_at::date, (now() AT TIME ZONE 'Asia/Kolkata')::date);
    today   date := (now() AT TIME ZONE 'Asia/Kolkata')::date;
    nowt    text := to_char(now() AT TIME ZONE 'Asia/Kolkata', 'HH24:MI');
    w       record;
    car     text;
    slot    text;
    whole   boolean;
    who     text := coalesce(nullif(btrim(l.lead_name), ''), 'Unnamed');
    src     text := CASE WHEN coalesce(l.entered_by, '') ILIKE '%agent%' THEN 'AI agent' ELSE 'Staff' END;
    exec_   text;
    tgt     dsr.test_drive_booking;
    id_     text;
    moved   text;
BEGIN
    -- Close the enquiries whose day has gone by first, so a new call files a
    -- new drive rather than reopening a missed one.
    PERFORM dsr.lapse_test_drive_enquiries();
    SELECT * INTO w FROM dsr.test_drive_when(concat_ws(' ', l.enquiry_note, l.model_of_interest), b0);

    SELECT dsr.car_id_for(dm.family) INTO car FROM dsr.dim_model dm WHERE dm.model_id = l.model_id;
    IF car IS NULL THEN
        car := coalesce(dsr.car_for_model(l.model_of_interest), dsr.car_for_model(l.enquiry_note));
    END IF;
    SELECT c.display_name INTO exec_ FROM dsr.dim_consultant c WHERE c.consultant_id = l.consultant_id;

    IF w.asked_time ~ '^(09:30|1[0-8]:(00|30))$' THEN
        slot := w.asked_time;
    END IF;
    -- Enough to book on its own: a car, a day not past and within two
    -- months, and a slot on the grid that has not gone by today. A day that
    -- has gone by (an older enquiry, filed late) stays an enquiry on that day.
    whole := car IS NOT NULL AND w.td_date IS NOT NULL AND slot IS NOT NULL
             AND w.td_date >= today AND w.td_date <= b0 + 60
             AND NOT (w.td_date = today AND slot <= nowt);

    -- Filed before with exactly this: nothing to do (a re-run, an edit
    -- that changed nothing the drive depends on).
    SELECT b.booking_id INTO id_ FROM dsr.test_drive_booking b
     WHERE b.lead_id = l.lead_id
       AND b.car_id IS NOT DISTINCT FROM car
       AND b.td_date IS NOT DISTINCT FROM w.td_date
       AND coalesce(b.start_time, b.asked_time) IS NOT DISTINCT FROM coalesce(slot, w.asked_time)
     LIMIT 1;
    IF id_ IS NOT NULL THEN
        RETURN id_;
    END IF;

    SELECT * INTO tgt FROM dsr.live_drives(l.lead_id, l.mobile, who, car, b0) LIMIT 1;

    IF tgt.booking_id IS NOT NULL AND tgt.status = 'requested' THEN
        -- A request waiting for its time: fill it in with what this note adds.
        BEGIN
            UPDATE dsr.test_drive_booking
               SET car_id = coalesce(car, car_id),
                   td_date = coalesce(w.td_date, td_date),
                   start_time = CASE WHEN whole THEN slot END,
                   asked_time = coalesce(w.asked_time, asked_time),
                   location = CASE WHEN w.place = 'Home' THEN 'Home' ELSE location END,
                   address = coalesce(w.address, address),
                   status = CASE WHEN whole THEN 'booked' ELSE 'requested' END,
                   lead_id = l.lead_id, note = l.enquiry_note
             WHERE booking_id = tgt.booking_id;
        EXCEPTION WHEN unique_violation THEN
            -- The slot is someone else's: it stays a request, with the time asked.
            UPDATE dsr.test_drive_booking
               SET car_id = coalesce(car, car_id), td_date = coalesce(w.td_date, td_date),
                   asked_time = coalesce(w.asked_time, asked_time),
                   location = CASE WHEN w.place = 'Home' THEN 'Home' ELSE location END,
                   address = coalesce(w.address, address), lead_id = l.lead_id, note = l.enquiry_note
             WHERE booking_id = tgt.booking_id;
        END;
        RETURN tgt.booking_id;
    END IF;

    IF tgt.booking_id IS NOT NULL THEN
        -- Already booked. The same slot, or a note that names none, is the
        -- customer confirming it: the booking stands.
        IF NOT whole OR (tgt.car_id, tgt.td_date, tgt.start_time) = (car, w.td_date, slot) THEN
            RETURN tgt.booking_id;
        END IF;
        -- A different slot is the customer asking to move it. A note is not
        -- enough to move a confirmed booking: the ask is filed as a request
        -- beside it, and booking it (on the board, or by the agent) moves
        -- the drive and closes the request.
        moved := format('Asked to move the drive booked for %s %s. ',
                        to_char(tgt.td_date, 'Dy DD Mon'), tgt.start_time);
        INSERT INTO dsr.test_drive_booking
               (car_id, td_date, asked_time, customer, phone, consultant,
                location, address, source, status, lead_id, note)
        VALUES (car, w.td_date, w.asked_time, who, l.mobile, exec_, w.place, w.address, src,
                'requested', l.lead_id, moved || coalesce(l.enquiry_note, ''))
        RETURNING booking_id INTO id_;
        RETURN id_;
    END IF;

    BEGIN
        INSERT INTO dsr.test_drive_booking
               (car_id, td_date, start_time, asked_time, customer, phone, consultant,
                location, address, source, status, lead_id, note)
        VALUES (car, w.td_date, CASE WHEN whole THEN slot END, w.asked_time, who, l.mobile, exec_,
                w.place, w.address, src, CASE WHEN whole THEN 'booked' ELSE 'requested' END,
                l.lead_id, l.enquiry_note)
        RETURNING booking_id INTO id_;
    EXCEPTION WHEN unique_violation THEN
        -- That slot on that car is taken: file it as a request, with the
        -- time the customer asked for, for the team to settle.
        INSERT INTO dsr.test_drive_booking
               (car_id, td_date, asked_time, customer, phone, consultant,
                location, address, source, status, lead_id, note)
        VALUES (car, w.td_date, w.asked_time, who, l.mobile, exec_, w.place, w.address, src,
                'requested', l.lead_id, l.enquiry_note)
        RETURNING booking_id INTO id_;
    END;
    RETURN id_;
END $$;

-- The same, for one enquiry at a time where a failure must not spread: the
-- trigger, so an enquiry always saves, and the backfill, so one odd row
-- cannot stop the rest.
CREATE OR REPLACE FUNCTION dsr.try_file_test_drive(l dsr.lead, base date DEFAULT NULL) RETURNS text
LANGUAGE plpgsql AS $$
BEGIN
    RETURN dsr.file_test_drive(l, base);
EXCEPTION WHEN others THEN
    RAISE WARNING 'test drive for lead % not filed: %', l.lead_id, SQLERRM;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION dsr.lead_to_test_drive() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- The note's "tomorrow" is tomorrow in India, counted from now: the
    -- enquiry is being saved during the call.
    PERFORM dsr.try_file_test_drive(NEW, (now() AT TIME ZONE 'Asia/Kolkata')::date);
    RETURN NULL;
END $$;

-- Enquiries entered by the agent, the website webhook or by hand (MANUAL),
-- never the monthly workbook's: it carries no test-drive requests, and a
-- reload re-inserts every row.
DROP TRIGGER IF EXISTS lead_test_drive ON dsr.lead;
CREATE TRIGGER lead_test_drive
    AFTER INSERT OR UPDATE OF lead_type, enquiry_note, model_id ON dsr.lead
    FOR EACH ROW
    WHEN (NEW.origin::text = 'MANUAL' AND dsr.is_test_drive_request(NEW.lead_type, NEW.enquiry_note))
    EXECUTE FUNCTION dsr.lead_to_test_drive();


-- ---------------------------------------------------------------------
-- BOOK: the two statements the AI agent runs on the call.
-- ---------------------------------------------------------------------

-- SLOTS: what is free for a model on a day.
CREATE OR REPLACE FUNCTION dsr.test_drive_free_slots(p_model text, p_day text)
RETURNS TABLE (status text, car text, test_drive_date date, free_times text, message text)
LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_column
DECLARE
    today date := (now() AT TIME ZONE 'Asia/Kolkata')::date;
    car_  text := dsr.car_for_model(p_model);
    d     date;
    times text;
BEGIN
    IF car_ IS NULL THEN
        RETURN QUERY SELECT 'invalid', NULL::text, NULL::date, NULL::text,
            'Model not recognised. Ask which model: Taigun, Virtus, Tayron, Tiguan R-Line or Golf GTI.';
        RETURN;
    END IF;
    d := (dsr.test_drive_when(p_day, today)).td_date;
    IF d IS NULL THEN
        RETURN QUERY SELECT 'invalid', dsr.car_name(car_), NULL::date, NULL::text,
            'Day not understood or already past. Ask for a day from today on, for example 9 Oct or Friday.';
        RETURN;
    END IF;
    SELECT string_agg(s, ', ') INTO times FROM dsr.test_drive_open(car_, d) s;
    RETURN QUERY SELECT CASE WHEN times IS NULL THEN 'full' ELSE 'ok' END, dsr.car_name(car_), d, times,
        CASE WHEN times IS NULL THEN 'No free test drive slots that day. Ask for another day.'
             ELSE 'Free times on ' || to_char(d, 'Dy DD Mon') || '.' END;
END $$;

-- BOOK: put the caller's test drive in its slot. The customer's live drive
-- on that car - filed for this enquiry, or from an earlier call - is moved
-- there rather than a second one made, and any request still open beside it
-- is closed.
CREATE OR REPLACE FUNCTION dsr.book_test_drive(
    p_lead_id integer, p_model text, p_day text, p_time text,
    p_place text DEFAULT 'Showroom', p_address text DEFAULT '')
RETURNS TABLE (status text, booking_id text, car text, test_drive_date date,
               test_drive_time text, message text)
LANGUAGE plpgsql AS $$
#variable_conflict use_column
DECLARE
    l      dsr.lead;
    today  date := (now() AT TIME ZONE 'Asia/Kolkata')::date;
    nowt   text := to_char(now() AT TIME ZONE 'Asia/Kolkata', 'HH24:MI');
    w      record;
    car_   text;
    slot   text;
    place_ text := CASE WHEN coalesce(p_place, '') ILIKE '%home%' THEN 'Home' ELSE 'Showroom' END;
    addr   text := nullif(btrim(coalesce(p_address, '')), '');
    who    text;
    mine   text;
    id_    text;
    near   text;
BEGIN
    PERFORM dsr.lapse_test_drive_enquiries();
    SELECT * INTO l FROM dsr.lead WHERE lead_id = p_lead_id;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'invalid', NULL::text, NULL::text, NULL::date, NULL::text,
            'No enquiry with that lead_id. Save the enquiry first, then book with its lead_id.';
        RETURN;
    END IF;
    who := coalesce(nullif(btrim(l.lead_name), ''), 'Unnamed');

    -- The model the agent names; the enquiry's only when it names none. A
    -- model the showroom does not sell is refused, not swapped for another.
    car_ := CASE WHEN nullif(btrim(coalesce(p_model, '')), '') IS NULL
                 THEN dsr.car_for_model(l.model_of_interest)
                 ELSE dsr.car_for_model(p_model) END;
    IF car_ IS NULL THEN
        RETURN QUERY SELECT 'invalid', NULL::text, NULL::text, NULL::date, NULL::text,
            'Model not recognised. Ask which model: Taigun, Virtus, Tayron, Tiguan R-Line or Golf GTI.';
        RETURN;
    END IF;

    SELECT * INTO w FROM dsr.test_drive_when(concat_ws(' ', p_day, p_time), today);
    IF w.td_date IS NULL THEN
        RETURN QUERY SELECT 'invalid', NULL::text, dsr.car_name(car_), NULL::date, NULL::text,
            'Day not understood or already past. Ask for a day from today on, for example 9 Oct or Friday.';
        RETURN;
    END IF;
    IF w.asked_time IS NULL THEN
        RETURN QUERY SELECT 'invalid', NULL::text, dsr.car_name(car_), w.td_date, NULL::text,
            'Time not understood. Ask for a time such as 11:30 or 4 pm.';
        RETURN;
    END IF;
    slot := w.asked_time;
    IF slot !~ '^(09:30|1[0-8]:(00|30))$' OR (w.td_date = today AND slot <= nowt) THEN
        SELECT string_agg(s, ', ') INTO near FROM (
            SELECT s FROM dsr.test_drive_open(car_, w.td_date) s
             ORDER BY abs(extract(epoch FROM (s::time - slot::time))) LIMIT 3) x;
        RETURN QUERY SELECT 'invalid', NULL::text, dsr.car_name(car_), w.td_date, slot,
            coalesce('Test drives start on the hour or half hour, 09:30 to 18:30, and not in the past. Nearest free times: '
                     || near || '.', 'No free test drive slots that day. Ask for another day.');
        RETURN;
    END IF;

    SELECT d.booking_id INTO mine FROM dsr.live_drives(p_lead_id, l.mobile, who, car_, today) d LIMIT 1;

    IF EXISTS (SELECT 1 FROM dsr.test_drive_booking b
                WHERE b.car_id = car_ AND b.td_date = w.td_date AND b.start_time = slot
                  AND b.status IN ('booked', 'attended', 'no_show') AND NOT b.sample
                  AND b.booking_id IS DISTINCT FROM mine) THEN
        SELECT string_agg(s, ', ') INTO near FROM (
            SELECT s FROM dsr.test_drive_open(car_, w.td_date) s
             ORDER BY abs(extract(epoch FROM (s::time - slot::time))) LIMIT 3) x;
        RETURN QUERY SELECT 'slot_taken', NULL::text, dsr.car_name(car_), w.td_date, slot,
            coalesce('That slot is taken. Nearest free times: ' || near || '.',
                     'That day is fully booked. Ask for another day.');
        RETURN;
    END IF;

    BEGIN
        IF mine IS NOT NULL THEN
            UPDATE dsr.test_drive_booking
               SET car_id = car_, td_date = w.td_date, start_time = slot, asked_time = slot,
                   location = place_,
                   address = CASE WHEN place_ = 'Home' THEN coalesce(addr, address) END,
                   status = 'booked', source = 'AI agent', lead_id = p_lead_id
             WHERE booking_id = mine
            RETURNING booking_id INTO id_;
        ELSE
            INSERT INTO dsr.test_drive_booking
                   (car_id, td_date, start_time, asked_time, customer, phone, consultant,
                    location, address, source, status, lead_id, note)
            VALUES (car_, w.td_date, slot, slot, who, l.mobile,
                    (SELECT c.display_name FROM dsr.dim_consultant c WHERE c.consultant_id = l.consultant_id),
                    place_, CASE WHEN place_ = 'Home' THEN addr END, 'AI agent', 'booked',
                    p_lead_id, l.enquiry_note)
            RETURNING booking_id INTO id_;
        END IF;
        -- Any other request still open for this customer and car is now settled.
        UPDATE dsr.test_drive_booking b SET status = 'cancelled'
         WHERE b.booking_id IN (SELECT d.booking_id FROM dsr.live_drives(p_lead_id, l.mobile, who, car_, today) d)
           AND b.status = 'requested' AND b.booking_id <> id_;
    EXCEPTION WHEN unique_violation THEN
        RETURN QUERY SELECT 'slot_taken', NULL::text, dsr.car_name(car_), w.td_date, slot,
            'That slot was just taken. Check the free times again.';
        RETURN;
    END;

    RETURN QUERY SELECT 'booked', id_, dsr.car_name(car_), w.td_date, slot,
        format('Booked: %s, %s at %s, %s.', dsr.car_name(car_), to_char(w.td_date, 'Dy DD Mon'), slot,
               CASE WHEN place_ = 'Home' THEN 'at the customer''s home' ELSE 'at the showroom' END);
END $$;


-- ---------------------------------------------------------------------
-- BACKFILL: recent test-drive enquiries already on record, filed the way the
-- trigger files new ones, each counted from its own day, so that every
-- test-drive enquiry is in the section. One whose day has passed is filed as
-- an enquiry on that day, never booked: booking it now would show a slot
-- nobody held. Only enquiries never filed before: a re-run must not bring
-- back a drive the team has since cancelled or moved. One odd row is skipped
-- with a warning rather than stopping the rest.
-- ---------------------------------------------------------------------
SELECT l.lead_id, dsr.try_file_test_drive(l, l.created_at::date) AS booking_id
  FROM dsr.lead l
 WHERE l.origin::text = 'MANUAL'
   AND dsr.is_test_drive_request(l.lead_type, l.enquiry_note)
   AND NOT EXISTS (SELECT 1 FROM dsr.test_drive_booking b WHERE b.lead_id = l.lead_id)
   AND l.created_at >= now() - interval '30 days'
 ORDER BY l.created_at;

-- LAPSE now, so an enquiry whose day has already gone by shows as the
-- no-show it is from the start.
SELECT dsr.lapse_test_drive_enquiries() AS enquiries_marked_no_show;
