-- migration: per_account
-- name: 002_v2_4_dd_thresholds
-- description: Add DD + weekly PnL threshold columns to account_settings

-- Uses the SQLite table-rebuild pattern (transactional DDL) to add
-- columns atomically.  If anything fails, the entire transaction rolls
-- back and account_settings is left unchanged.

BEGIN;

CREATE TABLE _account_settings_rebuild (
    account_id                   INTEGER PRIMARY KEY,
    timezone                     TEXT    NOT NULL DEFAULT 'UTC',
    dd_rolling_window_days       INTEGER NOT NULL DEFAULT 30,
    dd_warning_threshold         REAL,
    dd_limit_threshold           REAL,
    dd_recovery_threshold        REAL    NOT NULL DEFAULT 0.50,
    dd_enforcement_mode          TEXT    NOT NULL DEFAULT 'advisory',
    weekly_pnl_warning_threshold REAL,
    weekly_pnl_limit_threshold   REAL,
    weekly_pnl_enforcement_mode  TEXT    NOT NULL DEFAULT 'advisory'
);

INSERT INTO _account_settings_rebuild (account_id, timezone)
    SELECT account_id, timezone FROM account_settings;

DROP TABLE account_settings;

ALTER TABLE _account_settings_rebuild RENAME TO account_settings;

COMMIT;
