-- migration: per_account
-- name: 001_v2_4_account_tz
-- description: Add account_settings table with timezone column

CREATE TABLE IF NOT EXISTS account_settings (
    account_id  INTEGER PRIMARY KEY,
    timezone    TEXT NOT NULL DEFAULT 'UTC'
);

-- Seed row for the account this DB belongs to.
-- Default UTC; user reconfigures via UI later (v2.4 Phase 5).
INSERT OR IGNORE INTO account_settings (account_id, timezone)
    SELECT id, 'UTC' FROM accounts LIMIT 1;
