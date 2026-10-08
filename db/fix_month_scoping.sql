-- Count the dashboard's month only.
--
-- With September's workbook loaded beside August's, these figures added the two
-- months together whichever month the dashboard was set to:
--   * the headline's test drives  - 204 for August: its own 128 + September's 76;
--   * each consultant's retails   - Sanjeev 7 for August against the workbook's 4;
--   * the scorecard's team and grand totals - August's grand total read
--     84 bookings for 42, and 70 retails;
--   * the Models page's registered cars, and the finance and insurance
--     attachment rates (35 cars instead of 18).
-- A month's retails are the registrations its workbook listed (each workbook's
-- registration tab is that month's retails - its scorecard counts exactly those
-- rows) plus any entered by hand during it.
--
-- Same columns as before, so nothing that reads these views changes. Safe to
-- run more than once. Run it in the Supabase SQL Editor.

SET search_path = dsr, public;

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
    SELECT m.family, count(*) AS registered
    FROM registration r
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
             WHERE td.consultant_id = c.consultant_id AND td.origin = 'MANUAL')  AS tds_added
    FROM dim_consultant c
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

CREATE OR REPLACE VIEW v_sales_funnel AS
SELECT p.label AS period,
       (SELECT count(*) FROM lead
         WHERE is_current_period)                                       AS enquiries,
       (SELECT count(*) FROM lead
         WHERE is_current_period AND qualified_stage = 'Qualified')      AS qualified,
       -- This month's grand total. Summed over every month's, August read 204 -
       -- its own 128 plus September's 76.
       (SELECT COALESCE(sum(td_achieved), 0) FROM target_consultant_scorecard
         WHERE row_kind = 'GRAND_TOTAL' AND period_id = p.period_id)
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

-- What the dashboard now shows for its month.
SELECT k.period, k.test_drives, k.bookings, k.retails,
       (SELECT booking_achieved FROM v_consultant_scorecard WHERE row_kind = 'GRAND_TOTAL') AS scorecard_total_bookings,
       (SELECT retail_achieved FROM v_consultant_scorecard WHERE row_kind = 'GRAND_TOTAL')  AS scorecard_total_retails,
       (SELECT retail_achieved FROM v_consultant_scorecard
         WHERE row_kind = 'CONSULTANT' AND consultant = 'Sanjeev')                        AS sanjeev_retails,
       (SELECT registrations FROM v_attachment_rates)                                    AS cars_in_attachment_rates
  FROM v_daily_kpi k;
