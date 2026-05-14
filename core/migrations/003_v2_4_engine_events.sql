-- migration: per_account
-- name: 003_v2_4_engine_events
-- description: Create engine_events audit trail table + indexes

CREATE TABLE IF NOT EXISTS engine_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   INTEGER NOT NULL,
    event_type   TEXT    NOT NULL,
    payload_json TEXT    NOT NULL DEFAULT '{}',
    timestamp    TEXT    NOT NULL,
    source       TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_engine_events_account_time
    ON engine_events (account_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_engine_events_type
    ON engine_events (event_type);
