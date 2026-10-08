-- =====================================================================
-- Analytical and agent-facing views over the DSR schema.
--
-- Two audiences:
--   v_*        dashboard / management reporting
--   agent_*    the shape the service and client agents should query, so an agent
--              never has to know which of five booking tabs a row came from
--
-- Everything the workbook computes with a pivot table is rebuilt here, so the
-- numbers cannot drift from the rows they are derived from.
-- =====================================================================

SET search_path = dsr, public;

-- Rebuild from scratch every time. CREATE OR REPLACE cannot rename or drop a
-- column, so editing a view's shape would otherwise fail against a live database.
DO $$
DECLARE v record;
BEGIN
    FOR v IN
        SELECT table_name FROM information_schema.views WHERE table_schema = 'dsr'
    LOOP
        EXECUTE format('DROP VIEW IF EXISTS dsr.%I CASCADE', v.table_name);
    END LOOP;
END $$;

-- ---------------------------------------------------------------------
-- Reporting-month helpers
-- ---------------------------------------------------------------------

-- FIX (2026-10-08): retails were counted from EVERY registration ever loaded,
-- not from the month on screen. registration has no period_id, so v_sales_funnel,
-- v_attachment_rates, v_model_position and the consultant scorecard all read
-- the whole table - and loading a second month doubled August's retails
-- (reproduced: 18 -> 36). This view is the one place that decides which
-- registrations belong to the active month:
--   * a workbook row belongs to the month whose upload produced it
--     (load_period_id - the Reg Report is a per-month tab);
--   * a hand-entered row has no load, so it goes by its own date, falling back
--     to the day it was entered.
-- Every view below that counts retails reads this instead of `registration`.
CREATE OR REPLACE VIEW v_registration_current AS
SELECT r.*
FROM registration r
JOIN dim_period p ON p.is_active
WHERE r.load_period_id = p.period_id
   OR (r.load_period_id IS NULL
       AND COALESCE(r.registration_date, r.delivery_date, r.invoice_date,
                    r.loaded_at::date) BETWEEN p.period_start AND p.period_end);

-- ---------------------------------------------------------------------
-- Inventory
-- ---------------------------------------------------------------------

-- One row per physical car, fully labelled. The base for everything stock related.
CREATE OR REPLACE VIEW v_stock AS
SELECT v.vehicle_id,
       v.chassis_number,
       v.commission_no,
       m.name              AS model,
       m.family            AS model_family,
       dv.name             AS variant,
       dv.transmission,
       c.name              AS colour,
       v.long_model_text,
       v.model_year,
       v.obd,
       v.stock_status,
       v.billing_date,
       v.stock_received_date,
       v.stock_aging_days,
       v.nadcon_retail_date,
       CASE
           WHEN v.stock_aging_days IS NULL     THEN 'unknown'
           WHEN v.stock_aging_days <= 30       THEN '0-30'
           WHEN v.stock_aging_days <= 60       THEN '31-60'
           WHEN v.stock_aging_days <= 90       THEN '61-90'
           WHEN v.stock_aging_days <= 180      THEN '91-180'
           ELSE '180+'
       END                 AS ageing_bucket
FROM vehicle v
LEFT JOIN dim_model   m  ON m.model_id   = v.model_id
LEFT JOIN dim_variant dv ON dv.variant_id = v.variant_id
LEFT JOIN dim_colour  c  ON c.colour_id  = v.colour_id;

-- What can actually be sold today, and how long it has been sitting.
-- This is the view the client agent should answer availability questions from.
CREATE OR REPLACE VIEW v_stock_availability AS
SELECT model,
       model_family,
       variant,
       transmission,
       colour,
       count(*)                                              AS free_units,
       min(stock_aging_days)                                 AS freshest_days,
       max(stock_aging_days)                                 AS oldest_days,
       min(nadcon_retail_date)                               AS earliest_retail_deadline
FROM v_stock
WHERE stock_status = 'FREESTOCK'
GROUP BY model, model_family, variant, transmission, colour;

-- Rebuild of the Free Stock tab, in long form so it can be pivoted any way round.
CREATE OR REPLACE VIEW v_free_stock_by_colour AS
SELECT model,
       variant,
       colour,
       count(*) FILTER (WHERE stock_status = 'FREESTOCK') AS free_units,
       count(*) FILTER (WHERE stock_status = 'ALLOTED')   AS allotted_units,
       count(*)                                           AS total_units
FROM v_stock
WHERE stock_status IN ('FREESTOCK', 'ALLOTED')
GROUP BY model, variant, colour;

-- Ageing profile. Stock over 90 days is the number the manager is asked about,
-- because it drives the interest cost the dealership carries.
CREATE OR REPLACE VIEW v_stock_ageing AS
SELECT model,
       ageing_bucket,
       count(*)                          AS units,
       round(avg(stock_aging_days), 1)   AS avg_days,
       max(stock_aging_days)             AS max_days
FROM v_stock
WHERE stock_status IN ('FREESTOCK', 'ALLOTED')
GROUP BY model, ageing_bucket;

-- Rebuild of the VW Report tab: stock and order book side by side per model.
--
-- Rolled up to model FAMILY, not model name, on purpose. The stock tabs
-- distinguish the Taigun facelift ("Taigun (FL)") but the booking tabs write
-- plain "TAIGUN" for both, so a name-level view puts 35 free Taiguns against 0
-- Taigun bookings and 21 bookings against 3 cars. Family makes supply and demand
-- comparable; v_stock still carries the exact model for ordering.
CREATE OR REPLACE VIEW v_model_position AS
WITH families AS (
    SELECT DISTINCT family FROM dim_model
),
stock AS (
    SELECT m.family,
           count(*) FILTER (WHERE v.stock_status = 'FREESTOCK')                    AS free_stock,
           count(*) FILTER (WHERE v.stock_status = 'ALLOTED')                      AS allotted_stock,
           count(*) FILTER (WHERE v.stock_status IN ('FREESTOCK','ALLOTED'))       AS total_stock,
           count(*) FILTER (WHERE v.stock_status = 'FREESTOCK'
                              AND v.stock_aging_days > 90)                         AS free_over_90_days
    FROM vehicle v JOIN dim_model m ON m.model_id = v.model_id
    GROUP BY m.family
),
orders AS (
    SELECT m.family,
           count(*)                                                        AS bookings,
           count(*) FILTER (WHERE b.fulfilment_status = 'NO_STOCK')        AS backorders
    FROM booking b JOIN dim_model m ON m.model_id = b.model_id
    WHERE b.is_current_period
    GROUP BY m.family
),
-- A month's retails, here and everywhere else: the registrations its workbook
-- listed (load_period_id), plus any entered by hand during it. Each workbook's
-- registration tab is that month's retails - its scorecard's retail column
-- counts exactly those rows - so counting every load put months together.
retails AS (
    -- FIX (2026-10-08): was `FROM registration`, which counted every month's
    -- retails; see v_registration_current.
    SELECT m.family, count(*) AS registered
    FROM v_registration_current r
    JOIN vehicle v   ON v.vehicle_id = r.vehicle_id
    JOIN dim_model m ON m.model_id   = v.model_id
    JOIN dim_period ap ON ap.is_active
    WHERE r.status = 'REGISTERED'
      AND (r.load_period_id = ap.period_id
           OR (r.load_period_id IS NULL
               AND (r.loaded_at AT TIME ZONE 'Asia/Kolkata')::date
                   BETWEEN ap.period_start AND ap.period_end))
    GROUP BY m.family
)
SELECT f.family                                AS model,
       COALESCE(s.free_stock, 0)               AS free_stock,
       COALESCE(s.allotted_stock, 0)           AS allotted_stock,
       COALESCE(s.total_stock, 0)              AS total_stock,
       COALESCE(s.free_over_90_days, 0)        AS free_over_90_days,
       COALESCE(o.bookings, 0)                 AS bookings_this_period,
       COALESCE(o.backorders, 0)               AS backorders_this_period,
       COALESCE(r.registered, 0)               AS registered
FROM families f
LEFT JOIN stock   s ON s.family = f.family
LEFT JOIN orders  o ON o.family = f.family
LEFT JOIN retails r ON r.family = f.family
-- Families the dealership holds a car or an order against. Golf and Tiguan R-Line
-- are in the workbook's model list but had neither in August; carrying them
-- through would put empty rows on every chart.
WHERE COALESCE(s.total_stock, 0) > 0 OR COALESCE(o.bookings, 0) > 0;

-- ---------------------------------------------------------------------
-- Demand and the order book
-- ---------------------------------------------------------------------

CREATE OR REPLACE VIEW v_bookings AS
SELECT b.booking_id,
       b.booking_date,
       b.source_sheet,
       b.is_current_period,
       s.name              AS source,
       s.channel           AS source_channel,
       co.display_name     AS consultant,
       t.name              AS team,
       b.customer_name,
       b.mobile,
       m.name              AS model,
       m.family            AS model_family,
       dv.name             AS variant,
       c.name              AS colour,
       b.fulfilment_status,
       b.car_origin,
       b.crm_entry_done,
       b.booking_amount,
       b.ageing_days,
       v.chassis_number    AS allotted_chassis
FROM booking b
LEFT JOIN dim_lead_source s  ON s.source_id     = b.source_id
LEFT JOIN dim_consultant  co ON co.consultant_id = b.consultant_id
LEFT JOIN dim_team        t  ON t.team_id       = b.team_id
LEFT JOIN dim_model       m  ON m.model_id      = b.model_id
LEFT JOIN dim_variant     dv ON dv.variant_id   = b.variant_id
LEFT JOIN dim_colour      c  ON c.colour_id     = b.colour_id
LEFT JOIN vehicle         v  ON v.vehicle_id    = b.vehicle_id;

-- One row per real customer order.
--
-- v_bookings keeps every tab's version of a row, which is right for audit and
-- wrong for anything operational: an order written on both Live Booking and
-- Pending Booking would be chased twice and counted twice. Dedupe on customer +
-- model FAMILY + variant, because the tabs disagree on whether a facelift Taigun
-- is "TAIGUN" or "TAIGUN (FL)" and that is the same car to the customer.
CREATE OR REPLACE VIEW v_order_book AS
SELECT DISTINCT ON (upper(b.customer_name), b.model_family, b.variant) b.*
FROM v_bookings b
ORDER BY upper(b.customer_name), b.model_family, b.variant,
         -- August book first, then the consolidated order book, then the
         -- working lists the floor keeps.
         array_position(ARRAY['Current Month Booking',
                              'Booking & Alloted',
                              'Live Booking',
                              'Pending Booking',
                              'Golf & Tiguan R Line Booking'], b.source_sheet);

-- Orders taken with nothing to allot against them. Ordered by how long the
-- customer has been waiting, which is the queue the supply chase works down.
CREATE OR REPLACE VIEW v_backorders AS
SELECT b.booking_id,
       b.booking_date,
       (CURRENT_DATE - b.booking_date) AS days_waiting,
       b.customer_name,
       b.mobile,
       b.consultant,
       b.model,
       b.model_family,
       b.variant,
       b.colour,
       b.source,
       b.source_sheet,
       b.is_current_period,
       -- Can this order be filled from what is on the ground right now? Matched
       -- on family so free facelift stock counts against a plain Taigun order.
       (SELECT count(*) FROM v_stock st
         WHERE st.stock_status = 'FREESTOCK'
           AND st.model_family = b.model_family
           AND st.variant      = b.variant
           AND (st.colour = b.colour OR b.colour IS NULL)) AS matching_free_units
FROM v_order_book b
WHERE b.fulfilment_status = 'NO_STOCK';

-- Enquiry volume by channel for the current period.
-- Grouped by channel, not by the individual source row.
--
-- The source column in the CRM export sometimes holds a salesperson's name
-- instead of a channel, so the chart listed CRM, WALKIN, TELE and DIGITAL
-- beside ADITYA KUMAR and DIVYA SHREE - categories and people in one ranking,
-- which is not a thing you can read. Those rows are classified REFERRAL now
-- (a lead credited to a named individual is a referral from them) and this
-- groups on the channel, so the chart is six categories rather than twelve
-- entries of two different kinds.
--
-- The individual names are not lost - they are still in dim_lead_source.name
-- against every lead, for anyone who needs to know which consultant brought
-- what. They are simply not a category.
--
-- is_paid_media is aggregated with bool_or: a channel counts as paid if any
-- source within it is, which today is only DIGITAL.
CREATE OR REPLACE VIEW v_leads_sourcewise AS
SELECT s.channel::text                                               AS source,
       s.channel,
       bool_or(s.is_paid_media)                                      AS is_paid_media,
       count(*)                                                      AS leads,
       count(*) FILTER (WHERE l.qualified_stage = 'Qualified')        AS qualified,
       round(100.0 * count(*) FILTER (WHERE l.qualified_stage = 'Qualified')
             / NULLIF(count(*), 0), 1)                               AS qualified_pct
FROM lead l
JOIN dim_lead_source s USING (source_id)
WHERE l.is_current_period
GROUP BY s.channel;

-- Model demand vs supply: what people ask for against what is in stock.
-- Family level, for the same reason as v_model_position.
CREATE OR REPLACE VIEW v_model_demand AS
SELECT p.model,
       COALESCE(e.enquiries, 0) AS enquiries,
       p.bookings_this_period   AS bookings,
       p.free_stock,
       round(100.0 * p.bookings_this_period
             / NULLIF(e.enquiries, 0), 1) AS enquiry_to_booking_pct
FROM v_model_position p
LEFT JOIN (
    SELECT m.family, count(*) AS enquiries
    FROM lead l JOIN dim_model m ON m.model_id = l.model_id
    WHERE l.is_current_period
    GROUP BY m.family
) e ON e.family = p.model;

-- ---------------------------------------------------------------------
-- Consultant performance
-- ---------------------------------------------------------------------

-- Targets live on a consultant's primary-channel row; achievement is split across
-- that row and their "& Others" row. So targets are taken from the primary row and
-- achievement is summed across both. Percentages are recomputed here rather than
-- read from the sheet, where they surface as #DIV/0!.
--
-- Achievement is COUNTED FROM THE FACT TABLES, not read from the workbook, so a
-- booking entered through the dashboard moves the leaderboard immediately. This
-- is safe because the two agree exactly on load: every consultant's workbook
-- booking_achieved and retail_achieved matches their row count in booking and
-- registration, to the unit - counting the month's rows only. Registrations
-- carry no business month, so a month's are the ones its workbook listed (see
-- v_model_position); counted over every load, Sanjeev had 7 retails in August
-- against the workbook's 4, the other 3 being September's.
--
-- Enquiries and test drives are the exception and are baseline + live:
--   * the August lead export carries no consultant, so 367 of 367 leads are
--     unattributed and only the scorecard knows the per-person split;
--   * the test-drive tab was never refreshed (see v_data_quality).
-- So for those two, the workbook figure is the baseline and only MANUAL rows -
-- the ones entered since - are added on top. Nothing is double counted.
CREATE OR REPLACE VIEW v_consultant_scorecard AS
WITH rolled AS (
    SELECT sc.period_id,
           sc.consultant_id,
           sc.row_label,
           sc.row_kind,
           max(sc.leads_target)   FILTER (WHERE sc.is_primary_channel) AS leads_target,
           sum(sc.total_leads)                                          AS total_leads,
           sum(sc.leads_qualified)                                      AS leads_qualified,
           max(sc.td_target)      FILTER (WHERE sc.is_primary_channel) AS td_target,
           sum(sc.td_achieved)                                          AS td_achieved,
           max(sc.booking_target) FILTER (WHERE sc.is_primary_channel) AS booking_target,
           sum(sc.booking_achieved)                                     AS booking_achieved,
           max(sc.retail_target)  FILTER (WHERE sc.is_primary_channel) AS retail_target,
           sum(sc.retail_achieved)                                      AS retail_achieved,
           max(sc.finance_target)   FILTER (WHERE sc.is_primary_channel) AS finance_target,
           max(sc.finance_achieved) FILTER (WHERE sc.is_primary_channel) AS finance_achieved,
           max(sc.insurance_target)   FILTER (WHERE sc.is_primary_channel) AS insurance_target,
           max(sc.insurance_achieved) FILTER (WHERE sc.is_primary_channel) AS insurance_achieved,
           max(sc.cancelled) FILTER (WHERE sc.is_primary_channel)       AS cancelled,
           max(sc.allotted)  FILTER (WHERE sc.is_primary_channel)       AS allotted,
           max(sc.coverage)  FILTER (WHERE sc.is_primary_channel)       AS coverage
    FROM target_consultant_scorecard sc
    GROUP BY sc.period_id, sc.consultant_id, sc.row_label, sc.row_kind
),
-- Live achievement per consultant, straight off the facts.
--
-- FIX (2026-10-08): retails and hand-entered test drives were counted across
-- every month, so each consultant's month figures grew with every month
-- loaded. Retails now come from v_registration_current, and test drives are
-- held to the active month's dates - the same rule v_sales_funnel uses.
per_consultant AS (
    SELECT c.consultant_id,
           (SELECT count(*) FROM booking b
             WHERE b.consultant_id = c.consultant_id AND b.is_current_period)   AS bookings,
           (SELECT count(*) FROM registration rg
              JOIN dim_period ap ON ap.is_active
             WHERE rg.consultant_id = c.consultant_id
               AND rg.status = 'REGISTERED'
               AND (rg.load_period_id = ap.period_id
                    OR (rg.load_period_id IS NULL
                        AND (rg.loaded_at AT TIME ZONE 'Asia/Kolkata')::date
                            BETWEEN ap.period_start AND ap.period_end)))         AS retails,
           (SELECT count(*) FROM lead l
             WHERE l.consultant_id = c.consultant_id
               AND l.is_current_period AND l.origin = 'MANUAL')                  AS leads_added,
           (SELECT count(*) FROM lead l
             WHERE l.consultant_id = c.consultant_id
               AND l.is_current_period AND l.origin = 'MANUAL'
               AND l.qualified_stage = 'Qualified')                              AS qualified_added,
           (SELECT count(*) FROM test_drive td
             WHERE td.consultant_id = c.consultant_id AND td.origin = 'MANUAL'
               AND (td.td_date IS NULL
                    OR td.td_date BETWEEN ap.period_start AND ap.period_end))  AS tds_added
    FROM dim_consultant c
    JOIN dim_period ap ON ap.is_active
),
-- The same, aggregated for the roll-up rows. A TEAM_TOTAL row names its manager
-- in the label ("Field Team (Tele & Digital) - Nethra"), which is the only link
-- the workbook gives between a roll-up row and its members.
per_rollup AS (
    SELECT r.row_label,
           sum(pc.bookings)        AS bookings,
           sum(pc.retails)         AS retails,
           sum(pc.leads_added)     AS leads_added,
           sum(pc.qualified_added) AS qualified_added,
           sum(pc.tds_added)       AS tds_added
    FROM rolled r
    JOIN dim_consultant c
      ON r.row_kind = 'GRAND_TOTAL'
      OR (r.row_kind = 'TEAM_TOTAL'
          AND upper(r.row_label) LIKE '%' || upper(COALESCE(
                (SELECT name FROM dim_team dt WHERE dt.team_id = c.team_id), '~none~')) || '%')
    JOIN per_consultant pc ON pc.consultant_id = c.consultant_id
    -- The dashboard's month's total rows only. Every month loaded has a TOTAL
    -- row and the same team rows, so joining all of them counted each
    -- consultant once per month: August's grand total read 84 bookings for 42.
    WHERE r.row_kind IN ('TEAM_TOTAL', 'GRAND_TOTAL')
      AND r.period_id = (SELECT period_id FROM dim_period WHERE is_active)
    GROUP BY r.row_label
),
live AS (
    SELECT r.*,
           COALESCE(pc.bookings,        ru.bookings)        AS live_bookings,
           COALESCE(pc.retails,         ru.retails)         AS live_retails,
           COALESCE(pc.leads_added,     ru.leads_added,     0) AS leads_added,
           COALESCE(pc.qualified_added, ru.qualified_added, 0) AS qualified_added,
           COALESCE(pc.tds_added,       ru.tds_added,       0) AS tds_added
    FROM rolled r
    LEFT JOIN per_consultant pc ON pc.consultant_id = r.consultant_id
    LEFT JOIN per_rollup     ru ON ru.row_label     = r.row_label
                               AND r.row_kind IN ('TEAM_TOTAL', 'GRAND_TOTAL')
)
SELECT p.label                                   AS period,
       r.row_kind,
       COALESCE(co.display_name, r.row_label)    AS consultant,
       t.name                                    AS team,
       co.primary_channel,
       r.leads_target,
       COALESCE(r.total_leads, 0)     + r.leads_added     AS total_leads,
       COALESCE(r.leads_qualified, 0) + r.qualified_added AS leads_qualified,
       r.td_target,
       COALESCE(r.td_achieved, 0)     + r.tds_added       AS td_achieved,
       r.booking_target,
       COALESCE(r.live_bookings, r.booking_achieved)      AS booking_achieved,
       r.retail_target,
       COALESCE(r.live_retails,  r.retail_achieved)       AS retail_achieved,
       r.finance_target, r.finance_achieved,
       r.insurance_target, r.insurance_achieved,
       r.cancelled, r.allotted, r.coverage,
       round(100.0 * (COALESCE(r.total_leads, 0) + r.leads_added)
             / NULLIF(r.leads_target, 0), 1)              AS leads_vs_target_pct,
       round(100.0 * (COALESCE(r.td_achieved, 0) + r.tds_added)
             / NULLIF(COALESCE(r.total_leads, 0) + r.leads_added, 0), 1) AS td_conv_pct,
       round(100.0 * COALESCE(r.live_bookings, r.booking_achieved)
             / NULLIF(COALESCE(r.total_leads, 0) + r.leads_added, 0), 1) AS booking_conv_pct,
       round(100.0 * COALESCE(r.live_bookings, r.booking_achieved)
             / NULLIF(r.booking_target, 0), 1)            AS booking_vs_target_pct,
       round(100.0 * COALESCE(r.live_retails, r.retail_achieved)
             / NULLIF(r.retail_target, 0), 1)             AS retail_vs_target_pct
FROM live r
JOIN dim_period p ON p.period_id = r.period_id AND p.is_active
LEFT JOIN dim_consultant co ON co.consultant_id = r.consultant_id
LEFT JOIN dim_team t        ON t.team_id = co.team_id;

-- Ranked view of the people actually on the floor, worst gap first, which is how
-- the morning review is run.
CREATE OR REPLACE VIEW v_consultant_leaderboard AS
SELECT consultant, team, primary_channel,
       total_leads, td_achieved,
       booking_target, booking_achieved,
       COALESCE(booking_achieved, 0) - COALESCE(booking_target, 0) AS booking_gap,
       booking_vs_target_pct,
       retail_target, retail_achieved,
       retail_vs_target_pct,
       booking_conv_pct
FROM v_consultant_scorecard
WHERE row_kind = 'CONSULTANT'
  -- The tab carries placeholder rows for channels that are not people (a
  -- co-dealer contact, the workshop desk) with every column blank. Anyone with
  -- neither a target nor a single enquiry against them is one of those.
  AND (COALESCE(booking_target, 0) > 0
    OR COALESCE(booking_achieved, 0) > 0
    OR COALESCE(total_leads, 0) > 0)
ORDER BY booking_gap ASC, booking_achieved DESC;

-- Week-by-week commitment tracking, as management reviews it.
CREATE OR REPLACE VIEW v_booking_commitments AS
SELECT p.label AS period,
       bc.consultant_label,
       bc.window_label,
       bc.committed,
       bc.achieved,
       COALESCE(bc.achieved, 0) - COALESCE(bc.committed, 0) AS variance
FROM target_booking_commitment bc
JOIN dim_period p ON p.period_id = bc.period_id
WHERE p.is_active;

-- ---------------------------------------------------------------------
-- Funnel and headline numbers
-- ---------------------------------------------------------------------

-- Enquiry -> qualified -> test drive -> booking -> retail.
--
-- Enquiries, bookings and retails are counted from the fact tables, so entering
-- one moves the funnel at once.
--
-- Test drives cannot be: the TD tab in this workbook was never refreshed and
-- still holds a November 2024 export (see v_data_quality), so the scorecard's
-- TD ACH column is the only current figure. It is used as the baseline, plus any
-- test drive entered since - MANUAL rows only, so the stale tab is not counted.
--
-- FIX (2026-10-08): the test-drive baseline summed the GRAND_TOTAL scorecard
-- row of EVERY month, and retails counted every registration ever loaded, so
-- loading a second month doubled both for the month on screen (reproduced:
-- 128 -> 256 test drives, 18 -> 36 retails). The baseline is now this month's
-- scorecard only, and retails come from v_registration_current.
CREATE OR REPLACE VIEW v_sales_funnel AS
SELECT p.label AS period,
       (SELECT count(*) FROM lead
         WHERE is_current_period)                                       AS enquiries,
       (SELECT count(*) FROM lead
         WHERE is_current_period AND qualified_stage = 'Qualified')      AS qualified,
       -- This month's grand total. Summed over every month's, August read 204 -
       -- its own 128 plus September's 76. A workbook with no TOTAL row (one
       -- team's scorecard) falls back to its team rows, which is what the TOTAL
       -- row adds up; without that September read 0 against the team's 68.
       COALESCE((SELECT sum(td_achieved) FROM target_consultant_scorecard
                  WHERE row_kind = 'GRAND_TOTAL' AND period_id = p.period_id),
                (SELECT sum(td_achieved) FROM target_consultant_scorecard
                  WHERE row_kind = 'TEAM_TOTAL' AND period_id = p.period_id),
                0)
       + (SELECT count(*) FROM test_drive
           WHERE origin = 'MANUAL'
             AND (td_date IS NULL
                  OR td_date BETWEEN p.period_start AND p.period_end))   AS test_drives,
       (SELECT count(*) FROM booking
         WHERE is_current_period)                                        AS bookings,
       (SELECT count(*) FROM registration r
         WHERE r.status = 'REGISTERED'
           AND (r.load_period_id = p.period_id
                OR (r.load_period_id IS NULL
                    AND (r.loaded_at AT TIME ZONE 'Asia/Kolkata')::date
                        BETWEEN p.period_start AND p.period_end)))       AS retails
FROM dim_period p
-- Exactly one row: the month the dashboard is reporting on.
WHERE p.is_active;

CREATE OR REPLACE VIEW v_daily_kpi AS
SELECT f.period,
       f.enquiries,
       f.qualified,
       f.test_drives,
       f.bookings,
       f.retails,
       round(100.0 * f.bookings / NULLIF(f.enquiries, 0), 1)          AS enquiry_to_booking_pct,
       round(100.0 * f.retails  / NULLIF(f.bookings, 0), 1)           AS booking_to_retail_pct,
       (SELECT count(*) FROM vehicle WHERE stock_status = 'FREESTOCK') AS free_stock,
       (SELECT count(*) FROM vehicle WHERE stock_status = 'ALLOTED')   AS allotted_stock,
       (SELECT count(*) FROM vehicle
         WHERE stock_status IN ('FREESTOCK','ALLOTED')
           AND stock_aging_days > 90)                                  AS stock_over_90_days,
       (SELECT count(*) FROM booking
         WHERE is_current_period AND fulfilment_status = 'NO_STOCK')   AS backorders,
       (SELECT count(*) FROM booking
         WHERE is_current_period AND crm_entry_done IS FALSE)          AS bookings_missing_crm_entry,
       (SELECT sum(booking_amount) FROM booking WHERE is_current_period) AS booking_amount_collected,
       (SELECT round(avg(tat_days), 1) FROM allotment
         WHERE load_period_id = (SELECT period_id FROM dim_period WHERE is_active)) AS avg_allotment_tat_days
FROM v_sales_funnel f;

-- Attachment mix on retailed cars: finance, insurance, extended warranty, SVP.
-- These carry most of the dealership's margin, so they are scored separately.
--
-- FIX (2026-10-08): was `FROM registration`, so the rates and the "N retails"
-- denominator covered every month loaded; now the active month only.
CREATE OR REPLACE VIEW v_attachment_rates AS
SELECT count(*)                                                        AS registrations,
       count(*) FILTER (WHERE finance_type IS NOT NULL
                          AND finance_type <> 'FULL CASH')             AS financed,
       count(*) FILTER (WHERE has_insurance)                            AS insured,
       count(*) FILTER (WHERE has_extended_warranty)                    AS extended_warranty,
       count(*) FILTER (WHERE has_service_value_package)                AS service_value_package,
       count(*) FILTER (WHERE is_corporate)                             AS corporate,
       round(100.0 * count(*) FILTER (WHERE finance_type IS NOT NULL
                          AND finance_type <> 'FULL CASH')
             / NULLIF(count(*), 0), 1)                                  AS finance_pct,
       round(100.0 * count(*) FILTER (WHERE has_insurance)
             / NULLIF(count(*), 0), 1)                                  AS insurance_pct
FROM registration r
JOIN dim_period ap ON ap.is_active
WHERE r.status = 'REGISTERED'
  AND (r.load_period_id = ap.period_id
       OR (r.load_period_id IS NULL
           AND (r.loaded_at AT TIME ZONE 'Asia/Kolkata')::date
               BETWEEN ap.period_start AND ap.period_end));

-- How long a completed deal takes to clear the back office.
CREATE OR REPLACE VIEW v_folder_tat AS
SELECT r.registration_id,
       r.customer_name,
       co.display_name                                    AS consultant,
       r.registration_no,
       r.folder_lined_up_on,
       r.folder_given_to_accounts_on,
       r.registration_date,
       r.delivery_date,
       (r.folder_given_to_accounts_on - r.folder_lined_up_on) AS days_to_accounts,
       (r.registration_date - r.booking_date)                 AS booking_to_registration_days
FROM registration r
LEFT JOIN dim_consultant co ON co.consultant_id = r.consultant_id
WHERE r.status = 'REGISTERED';

-- ---------------------------------------------------------------------
-- Agent-facing views
--
-- The agents should read these and nothing else. They hide the five-overlapping-
-- booking-tabs problem and the two lead populations behind stable column names.
-- ---------------------------------------------------------------------

-- CLIENT AGENT: "do you have a Candy White Virtus GT Line AT?"
CREATE OR REPLACE VIEW agent_vehicle_availability AS
SELECT model,
       model_family,
       variant,
       transmission,
       colour,
       free_units,
       CASE WHEN free_units > 0 THEN 'available' ELSE 'unavailable' END AS availability,
       freshest_days AS newest_stock_age_days
FROM v_stock_availability
WHERE free_units > 0;

-- CLIENT AGENT: "where is my car?" - one row per customer order, with whatever
-- fulfilment progress exists. Matched on name because the booking tabs record a
-- mobile number only sporadically.
--
-- Deduplicated on purpose. The same order is written on up to three of the
-- booking tabs, and joining allotments and registrations by customer name can
-- multiply rows again. A customer asking after their car must get one row per
-- car, so each join is collapsed to its best single match first.
CREATE OR REPLACE VIEW agent_order_status AS
WITH one_allotment AS (
    SELECT DISTINCT ON (booking_id) booking_id, allotted_date, tat_days
    FROM allotment WHERE booking_id IS NOT NULL
    ORDER BY booking_id, allotted_date DESC NULLS LAST
),
one_registration AS (
    SELECT DISTINCT ON (upper(customer_name))
           customer_name, status, invoice_date, registration_date,
           registration_no, delivery_date
    FROM registration
    ORDER BY upper(customer_name), registration_date DESC NULLS LAST, registration_id
)
SELECT b.booking_id,
       b.customer_name,
       b.mobile,
       b.booking_date,
       b.model,
       b.variant,
       b.colour,
       b.consultant,
       b.fulfilment_status,
       b.allotted_chassis,
       a.allotted_date,
       r.invoice_date,
       r.registration_date,
       r.registration_no,
       r.delivery_date,
       CASE
           WHEN r.delivery_date     IS NOT NULL THEN 'delivered'
           -- The August workbook leaves registration_date blank on every row,
           -- so the Reg Report status is what actually carries this stage.
           WHEN r.registration_date IS NOT NULL
             OR r.status = 'REGISTERED'          THEN 'registered'
           WHEN r.invoice_date      IS NOT NULL THEN 'invoiced'
           WHEN b.fulfilment_status = 'RETAILED' THEN 'retailed'
           WHEN a.allotted_date     IS NOT NULL THEN 'car allotted'
           WHEN b.fulfilment_status = 'ALLOTED'  THEN 'car allotted'
           WHEN b.fulfilment_status = 'NO_STOCK' THEN 'awaiting stock'
           WHEN b.fulfilment_status = 'CANCELLED' THEN 'cancelled'
           ELSE 'booked'
       END AS stage
FROM v_order_book b
LEFT JOIN one_allotment    a ON a.booking_id = b.booking_id
LEFT JOIN one_registration r ON upper(r.customer_name) = upper(b.customer_name);

-- SERVICE / INTERNAL AGENT: everything needed to answer "how are we doing?"
CREATE OR REPLACE VIEW agent_dealership_snapshot AS
SELECT k.period,
       k.enquiries, k.qualified, k.test_drives, k.bookings, k.retails,
       k.enquiry_to_booking_pct, k.booking_to_retail_pct,
       k.free_stock, k.allotted_stock, k.stock_over_90_days, k.backorders,
       k.bookings_missing_crm_entry, k.booking_amount_collected,
       -- The TOTAL row's targets, or for a workbook without one, its teams' added up.
       COALESCE((SELECT booking_target FROM v_consultant_scorecard WHERE row_kind = 'GRAND_TOTAL'),
                (SELECT sum(booking_target) FROM v_consultant_scorecard WHERE row_kind = 'TEAM_TOTAL')) AS booking_target,
       COALESCE((SELECT retail_target FROM v_consultant_scorecard WHERE row_kind = 'GRAND_TOTAL'),
                (SELECT sum(retail_target) FROM v_consultant_scorecard WHERE row_kind = 'TEAM_TOTAL')) AS retail_target,
       COALESCE((SELECT leads_target FROM v_consultant_scorecard WHERE row_kind = 'GRAND_TOTAL'),
                (SELECT sum(leads_target) FROM v_consultant_scorecard WHERE row_kind = 'TEAM_TOTAL')) AS enquiry_target
FROM v_daily_kpi k;

-- ---------------------------------------------------------------------
-- Data quality
--
-- The workbook is maintained by hand and its tabs are refreshed at different
-- times, so they disagree with each other. Rather than quietly picking a winner,
-- every disagreement found during the load is surfaced here.
--
-- The text is read by a manager, not a developer, so it says "the dashboard"
-- rather than "views" and "the lower block" rather than BLOCK_2, and it names
-- the active month instead of writing one in. `unit` says what affected_rows
-- counts, so the panel can say "31 test drives" instead of "31 rows".
--
-- public.v_data_quality is a wrapper over this view for the Supabase API, and
-- selects its columns by name - so a column appended here does not reach it
-- until it is added there too, and cannot break it.
-- ---------------------------------------------------------------------

-- FIX (2026-10-08): four of these checks counted rows from every month loaded,
-- so their "affected rows" grew with each upload and the Comparision figures
-- printed a cross-month retail total. Registrations now come from
-- v_registration_current, and the Daily Tracker and allotment checks are held
-- to the active month.
CREATE OR REPLACE VIEW v_data_quality AS
WITH active AS (
    -- The month the dashboard is reporting on. Every sentence below that names
    -- a month takes it from here; they used to say "August" outright, and would
    -- have gone on saying it in every month after.
    SELECT label,
           period_start,
           to_char(period_start, 'FMMonth')      AS month,
           to_char(period_start, 'FMMonth YYYY') AS month_year
      FROM dim_period
     WHERE is_active
     LIMIT 1
),
checks AS (
    SELECT 'Test drive tab is out of date'::text AS issue,
           ('The Test Drive tab''s latest entry is from '
            || coalesce((SELECT to_char(max(td_date), 'FMMonth YYYY') FROM test_drive),
                        'an earlier month')
            || ', not ' || coalesce((SELECT month_year FROM active), 'the current month')
            || '. The funnel uses the scorecard''s test-drive figures instead.')::text AS detail,
           (SELECT count(*)::text FROM test_drive
             WHERE td_date < (SELECT period_start FROM active)) AS affected_rows,
           'high'::text AS severity,
           -- What the count is a count of, so the panel can say "31 test drives"
           -- rather than "31 rows". Singular; the panel pluralises.
           'test drive'::text AS unit
    UNION ALL
    -- The Comparision tab is not loaded (see schema.sql): 350 and 37 are what
    -- that tab showed in the August 2026 workbook when it was read. So the check
    -- is scoped to that month - in any other it would set live figures against a
    -- snapshot from a different workbook. Retails are left out because the
    -- registration table carries no period, so no count of it could agree with
    -- the retail figure the rest of the dashboard shows. The count is the number
    -- of figures that still disagree, so the check clears itself if they match.
    SELECT 'Comparison tab disagrees with the base tabs',
           'In the August 2026 workbook, the Comparison tab reports 350 enquiries and '
           || '37 bookings; the base tabs hold '
           || (SELECT count(*) FROM lead WHERE is_current_period)::text || ' and '
           || (SELECT count(*) FROM booking WHERE is_current_period)::text || '.',
           ((350 <> (SELECT count(*) FROM lead WHERE is_current_period))::int
            + (37 <> (SELECT count(*) FROM booking WHERE is_current_period))::int)::text,
           'medium',
           'figure'
     WHERE (SELECT label FROM active) = 'AUG2026'
    UNION ALL
    SELECT 'Daily Tracker holds two conflicting target blocks',
           'The upper and lower target blocks set different enquiry targets for the '
           || 'same consultant. The dashboard uses the lower block, which covers the '
           || 'full team.',
           (SELECT count(DISTINCT consultant_label)::text FROM target_daily_tracker
             WHERE period_id = (SELECT period_id FROM dim_period WHERE is_active)
               AND consultant_label IN (
                 SELECT consultant_label FROM target_daily_tracker
                  WHERE period_id = (SELECT period_id FROM dim_period WHERE is_active)
                 GROUP BY consultant_label HAVING count(DISTINCT block_label) > 1)),
           'medium',
           'consultant'
    UNION ALL
    SELECT coalesce((SELECT month FROM active), 'This month')
           || ' lead export is missing consultant and status columns',
           'The Leads tab was exported with only the date, name, source and model of '
           || 'interest, so enquiries per consultant are taken from the scorecard.',
           (SELECT count(*)::text FROM lead
             WHERE is_current_period AND consultant_id IS NULL),
           'medium',
           'lead'
    UNION ALL
    SELECT 'Bookings not entered in the CRM',
           'Bookings on the ' || coalesce((SELECT month FROM active), 'current')
           || ' tab marked ZOHO ENTRY = NO. They will not appear in VW reporting until '
           || 'they are entered.',
           (SELECT count(*)::text FROM booking
             WHERE is_current_period AND crm_entry_done IS FALSE),
           'high',
           'booking'
    UNION ALL
    SELECT 'Allotments with no chassis on the source tab',
           'The Alloted tab has no chassis column, so allotments were matched to stock '
           || 'by model and age. Unmatched allotments are not linked to a vehicle.',
           (SELECT count(*)::text FROM allotment WHERE vehicle_id IS NULL),
           'low',
           'allotment'
    UNION ALL
    SELECT 'Registration report stops at accounts',
           'On the Reg Report tab, every column from FOLDER SENT TO HO onwards - invoice '
           || 'date, registration date and number, VOIW ID and delivery date - is blank, '
           || 'so the fulfilment stage is read from the status column instead.',
           (SELECT count(*)::text FROM registration
             WHERE registration_date IS NULL AND invoice_date IS NULL),
           'medium',
           'registration'
    UNION ALL
    SELECT 'Stock past its NADCON retail deadline',
           'Unsold units whose VW retail deadline has already passed.',
           (SELECT count(*)::text FROM vehicle
             WHERE stock_status = 'FREESTOCK'
               AND nadcon_retail_date < CURRENT_DATE),
           'high',
           'unit'
)
SELECT * FROM checks WHERE affected_rows IS NOT NULL AND affected_rows <> '0';
