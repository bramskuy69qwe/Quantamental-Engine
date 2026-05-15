-- migration: per_account
-- name: 007_v2_4_trade_events
-- description: Create trade_events table for per-trade lifecycle logging

CREATE TABLE IF NOT EXISTS trade_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   INTEGER NOT NULL,
    calc_id      TEXT,
    event_type   TEXT    NOT NULL,
    payload_json TEXT    NOT NULL DEFAULT '{}',
    source       TEXT    NOT NULL,
    timestamp    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trade_events_calc_id
    ON trade_events (calc_id);

CREATE INDEX IF NOT EXISTS idx_trade_events_account_time
    ON trade_events (account_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_trade_events_type
    ON trade_events (event_type);
