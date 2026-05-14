-- migration: per_account
-- name: 005_v2_4_calc_id
-- description: Add calc_id column to pre_trade_log for calculator-order correlation

-- Uses ALTER TABLE ADD COLUMN (simpler than rebuild since it's a single
-- nullable column). If pre_trade_log doesn't exist yet in this DB,
-- the ALTER is a no-op failure caught by the runner's error handling.

ALTER TABLE pre_trade_log ADD COLUMN calc_id TEXT;
