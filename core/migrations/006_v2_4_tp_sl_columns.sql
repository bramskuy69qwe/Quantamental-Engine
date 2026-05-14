-- migration: per_account
-- name: 006_v2_4_tp_sl_columns
-- description: Placeholder for tp/sl trigger columns — actual orders table is in legacy DB

-- orders and fills tables live in the legacy risk_engine.db, not in
-- per-account DBs. Their schema changes are handled via inline ALTER
-- in database.py:initialize(). This migration is a no-op placeholder
-- to maintain the numbered sequence from v2.4.md Priority 6c.

SELECT 1;
