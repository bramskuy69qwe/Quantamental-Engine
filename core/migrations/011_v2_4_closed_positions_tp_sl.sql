-- migration: per_account
-- name: 011_v2_4_closed_positions_tp_sl
-- description: Add tp_price/sl_price to closed_positions and backfill from pre_trade_log

-- Schema additions (IF NOT EXISTS pattern via ADD COLUMN — duplicate is a no-op error
-- caught by runner). These are also applied by database.py inline ALTERs on startup.
ALTER TABLE closed_positions ADD COLUMN tp_price REAL DEFAULT NULL;
ALTER TABLE closed_positions ADD COLUMN sl_price REAL DEFAULT NULL;

-- One-shot backfill: populate from pre_trade_log via calc_id.
-- Rows without calc_id (legacy/manual) remain NULL — displayed as "—" in UI.
-- Idempotent: only touches rows where tp_price IS NULL.
UPDATE closed_positions
SET tp_price = (SELECT p.tp_price FROM pre_trade_log p
                WHERE p.calc_id = closed_positions.calc_id LIMIT 1),
    sl_price = (SELECT p.sl_price FROM pre_trade_log p
                WHERE p.calc_id = closed_positions.calc_id LIMIT 1)
WHERE calc_id IS NOT NULL AND calc_id != '' AND tp_price IS NULL;
