-- migration: per_account
-- name: 014_v2_7_model_library_per_account
-- description: v2.7 Phase 1 — pre_trade_log.model_id (the FK the
--              free-text model_name becomes).

-- Dual-track twin of the inline ALTER in core/database.py (see 013's
-- header for the rationale). closed_positions.model_id is deliberately
-- NOT here: closed_positions lives only in the legacy DB, so the inline
-- ALTER covers it (008_v2_4_closed_positions_calc_id precedent).
--
-- model_id is FK-IN-NAME-ONLY and cannot be a real FK here even in
-- principle: potential_models lives in global.db and SQLite foreign keys
-- cannot span database files. NULL = no model selected (also every
-- pre-v2.7 row).

ALTER TABLE pre_trade_log ADD COLUMN model_id INTEGER DEFAULT NULL;
