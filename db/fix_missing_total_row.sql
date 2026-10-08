-- A month whose workbook has no TOTAL row on its scorecard.
--
-- Shivani Test DSR.xlsx replaced SEP2026. Its SC Performance holds one team
-- (S/R: five consultants) and no TOTAL row, so the dashboard's headline read 0
-- test drives for September though the team row records 68. The TOTAL row is
-- the team rows added up, so without one the team rows are used. The same for
-- the targets the agent's snapshot view reports.
--
-- Same columns as before, so nothing that reads these views changes. Safe to
-- run more than once. Run it in the Supabase SQL Editor.

SET search_path = dsr, public;

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

-- What the dashboard now shows for its month.
SELECT period, test_drives, booking_target, retail_target, enquiry_target
  FROM agent_dealership_snapshot;
