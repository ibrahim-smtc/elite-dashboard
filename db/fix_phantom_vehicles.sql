-- =====================================================================
-- Phantom vehicles: one-off clean-up.
--
-- An upload on 21 September 2026 carried customers' names in the chassis
-- column of its stock sheets. Vehicles are keyed on chassis number, so every
-- name became a second "car" beside the real one: 100 phantom units, 66 of
-- them counted as free stock (123 free on the dashboard against 57 real).
-- Each phantom shares its commission and engine numbers with a real vehicle,
-- and no booking, allotment or registration points at any of them.
--
-- This removes a vehicle only when all three hold:
--   * its chassis_number is not a chassis number (a VIN has no spaces:
--     10-20 letters and digits, with both),
--   * a real vehicle with the same commission number exists, and
--   * nothing refers to it.
-- Safe to run again: a second run finds nothing. The loaders now skip such
-- rows (etl/normalize.py chassis()), so they cannot come back.
--
-- Run on 8 October 2026: removed 100 (66 of them free stock), left 130.
-- =====================================================================

WITH phantom AS (
    SELECT v.vehicle_id
      FROM dsr.vehicle v
     WHERE NOT (replace(v.chassis_number, ' ', '') ~ '^[A-Z0-9]{10,20}$'
                AND v.chassis_number ~ '[0-9]' AND v.chassis_number ~ '[A-Z]')
       AND EXISTS (SELECT 1 FROM dsr.vehicle r
                    WHERE r.commission_no = v.commission_no
                      AND r.vehicle_id <> v.vehicle_id
                      AND replace(r.chassis_number, ' ', '') ~ '^[A-Z0-9]{10,20}$'
                      AND r.chassis_number ~ '[0-9]' AND r.chassis_number ~ '[A-Z]')
       AND NOT EXISTS (SELECT 1 FROM dsr.booking      b WHERE b.vehicle_id = v.vehicle_id)
       AND NOT EXISTS (SELECT 1 FROM dsr.allotment    a WHERE a.vehicle_id = v.vehicle_id)
       AND NOT EXISTS (SELECT 1 FROM dsr.registration g WHERE g.vehicle_id = v.vehicle_id)
),
removed AS (
    DELETE FROM dsr.vehicle WHERE vehicle_id IN (SELECT vehicle_id FROM phantom)
    RETURNING stock_status
)
SELECT (SELECT count(*) FROM removed)                                         AS phantom_vehicles_removed,
       (SELECT count(*) FROM removed WHERE stock_status = 'FREESTOCK')         AS of_them_free_stock,
       (SELECT count(*) FROM dsr.vehicle) - (SELECT count(*) FROM removed)     AS vehicles_left;
