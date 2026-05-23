-- migration: per_account
-- name: 011_v2_5_pretrade_regime_columns
-- description: Add per-trade regime decision columns to pre_trade_log
--              (Task 157, FOUNDATION FOR FORWARD TWO-TRACK).

-- Task 156 (regime-logging investigation) found that risk_engine emits
-- regime_label / regime_multiplier / apply_regime_multiplier in the calc
-- dict but `insert_pre_trade_log` never persisted them — the live engine's
-- exact sizing decision was unrecoverable to "what label / multiplier did
-- the engine actually apply at trade time?" fidelity. T156 caveat (d):
-- compute_current_regime()'s live-classification fallback never writes
-- regime_labels, so reconstruction from raw signals diverges in the
-- fallback path.
--
-- Task 157 closes that gap going forward by recording the decision at
-- plan time. Counterfactual replay of NEW models against historical
-- trades is already feasible via the regime_signals timestamp join
-- (T156 verdict); this work is for the live "actual" arm of the
-- forward two-track + sub-day-fidelity audit of engine sizing decisions.
--
-- Schema decisions:
--   • Four nullable columns. NULL = "row pre-dates this logging" — the
--     forward-analytics layer can exclude these rows cleanly. Defaulting
--     regime_multiplier to 1.0 (the toggle-OFF value) would falsely read
--     as "regime ran and chose x1" on pre-T157 rows. NULL is the right
--     sentinel for "we don't know what was applied."
--   • apply_regime_multiplier stored as INTEGER (SQLite has no bool);
--     0 / 1 / NULL.
--   • regime_label / regime_mode TEXT — kept untyped here to avoid
--     coupling DB schema to config.REGIME_MULTIPLIERS keys (which can
--     shift as the model evolves).
--
-- Additive-only: existing rows keep all prior column values, gain four
-- NULLs. No backfill of historical rows; T156 documented why
-- reconstruction is feasible-but-not-prerequisite.

ALTER TABLE pre_trade_log ADD COLUMN regime_label TEXT;
ALTER TABLE pre_trade_log ADD COLUMN regime_multiplier REAL;
ALTER TABLE pre_trade_log ADD COLUMN regime_mode TEXT;
ALTER TABLE pre_trade_log ADD COLUMN apply_regime_multiplier INTEGER;
