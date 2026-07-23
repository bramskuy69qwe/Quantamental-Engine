-- migration: global
-- name: 015_v3_0_p7_models_global
-- description: v3.0 P7 — models-tab columns on the three GLOBAL tables
--              (backtest_sessions report_json verbatim-capture store;
--              backtest_trades contracts; potential_models
--              source_json/tags_json).

-- Dual-track twin of the inline ALTERs in core/database.py (013
-- precedent): inline covers the legacy risk_engine.db the live app
-- opens; this file covers data/global.db so split-DB setups don't
-- schema-drift. Same KNOWN CLASS LIMIT as 005/011/013: a RE-RUN of the
-- 000 split after this ships clones the migrated legacy schema with an
-- empty migrations_log and these bare ALTERs then fail "duplicate
-- column" — the split task must stamp migrations_log at split time.
--
-- report_json: the VERBATIM whole-workbook capture for imported runs
-- ({"format":"workbook.v1","sheets":[…]}); '{}' = engine-run / pre-P7.
-- source_json/tags_json (G-M4, §3 RATIFIED): the model owns its
-- backtest source binding; the ACCOUNT is the exchange-agnostic entity.

ALTER TABLE backtest_sessions ADD COLUMN report_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE backtest_trades ADD COLUMN contracts REAL NOT NULL DEFAULT 0;
ALTER TABLE potential_models ADD COLUMN source_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE potential_models ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]';
