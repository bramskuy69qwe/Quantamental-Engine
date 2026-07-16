-- migration: global
-- name: 013_v2_7_model_library_global
-- description: v2.7 Phase 1 — model-library columns on the two GLOBAL
--              tables (potential_models risk/strategy/updated_at;
--              backtest_sessions model_id/source_app + index).

-- Dual-track twin of the inline ALTERs in core/database.py (migration-011
-- precedent): inline covers the legacy risk_engine.db the live app opens;
-- this file covers data/global.db so split-DB setups don't schema-drift.
-- KNOWN CLASS LIMIT (shared with 005/011, flagged v2.7 P1 audit): if the
-- 000 split is ever RE-RUN after this ships, _copy_schema clones the
-- already-migrated legacy schema into fresh split DBs with an EMPTY
-- migrations_log, and these bare ALTERs then fail "duplicate column" —
-- the split task must stamp migrations_log at split time (or these
-- ALTERs need guarding). Today's targets pre-date the columns, and the
-- runner's migrations_log makes each application one-shot.
--
-- updated_at: nullable TEXT (SQLite forbids non-constant defaults in ADD
-- COLUMN); stamped by update_potential_model; NULL = never updated.
-- model_id: FK-IN-NAME-ONLY (no REFERENCES) — after a model delete, ids
-- dangle by design and readers LEFT JOIN with a "(deleted model)"
-- fallback (v2.7 plan §2 FK policy).

ALTER TABLE potential_models ADD COLUMN risk_preset_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE potential_models ADD COLUMN strategy_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE potential_models ADD COLUMN updated_at TEXT;
ALTER TABLE backtest_sessions ADD COLUMN model_id INTEGER DEFAULT NULL;
ALTER TABLE backtest_sessions ADD COLUMN source_app TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_bt_sessions_model ON backtest_sessions (model_id);
