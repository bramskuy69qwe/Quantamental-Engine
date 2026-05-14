-- migration: per_account
-- name: 004_v2_4_account_preferences
-- description: Add strategy_preset, analytics_default_period, week_start_dow to account_settings

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
    weekly_pnl_enforcement_mode  TEXT    NOT NULL DEFAULT 'advisory',
    strategy_preset              TEXT,
    analytics_default_period     TEXT    NOT NULL DEFAULT 'monthly',
    week_start_dow               INTEGER NOT NULL DEFAULT 1
);

INSERT INTO _account_settings_rebuild (
    account_id, timezone,
    dd_rolling_window_days, dd_warning_threshold, dd_limit_threshold,
    dd_recovery_threshold, dd_enforcement_mode,
    weekly_pnl_warning_threshold, weekly_pnl_limit_threshold,
    weekly_pnl_enforcement_mode
)
SELECT
    account_id, timezone,
    dd_rolling_window_days, dd_warning_threshold, dd_limit_threshold,
    dd_recovery_threshold, dd_enforcement_mode,
    weekly_pnl_warning_threshold, weekly_pnl_limit_threshold,
    weekly_pnl_enforcement_mode
FROM account_settings;

DROP TABLE account_settings;

ALTER TABLE _account_settings_rebuild RENAME TO account_settings;

COMMIT;
