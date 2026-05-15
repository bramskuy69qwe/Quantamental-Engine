-- migration: per_account
-- name: 010_v2_4_position_fill_snapshots
-- description: Position state snapshots at fill time for is_close derivation

CREATE TABLE IF NOT EXISTS position_fill_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL,
    fill_id         TEXT,
    symbol          TEXT    NOT NULL,
    mode            TEXT    NOT NULL DEFAULT 'one_way',
    position_side   TEXT,
    qty_before      REAL    NOT NULL DEFAULT 0,
    qty_after       REAL    NOT NULL DEFAULT 0,
    is_open         INTEGER NOT NULL DEFAULT 0,
    is_close        INTEGER NOT NULL DEFAULT 0,
    is_partial_close INTEGER NOT NULL DEFAULT 0,
    timestamp_ms    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_pfs_fill ON position_fill_snapshots (fill_id);
CREATE INDEX IF NOT EXISTS idx_pfs_symbol_ts ON position_fill_snapshots (symbol, timestamp_ms DESC);
