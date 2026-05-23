-- migration: global
-- name: 012_v2_5_accounts_broker_unique
-- description: Add UNIQUE constraint on (exchange, broker_account_id) for
--              the accounts table (Task 160, MED-024).

-- Mechanism (T158 triage; mis-tiered HIGH-shape closed in T160):
-- `find_by_broker_id` in core/account_registry.py returns the FIRST cache
-- entry matching a broker_id, scanning ALL accounts irrespective of
-- exchange. With no UNIQUE constraint on the (exchange, broker_account_id)
-- tuple, two accounts sharing the same broker_account_id on the same
-- exchange route Quantower fills non-deterministically — fills land on
-- the wrong account silently. Unrecoverable after the fact (the fill
-- gets attributed to a wrong account_id in pre_trade_log + fills + closed_positions).
--
-- Constraint shape:
--   UNIQUE (exchange, broker_account_id) — same broker_account_id on
--   different exchanges is fine (Bybit account #12345 vs Binance
--   account #12345 are different real-world entities).
--
-- NULL handling: SQLite treats NULL as distinct from any other NULL in
-- UNIQUE indexes (per SQL standard) — multiple NULL broker_account_id
-- values are allowed. Empty string '' is NOT NULL; the partial WHERE
-- clause excludes it so unset accounts (stored as '') don't trip the
-- constraint.
--
-- Duplicate handling: this migration ASSUMES no duplicates exist. If
-- duplicates are present, CREATE UNIQUE INDEX raises sqlite3.IntegrityError
-- and the migration runner aborts loudly. The inline shadow-migration
-- path in core/database.py runs an explicit Python pre-check with a more
-- operator-friendly message; that path handles single-DB installs (the
-- common case). This standalone file handles split-DB setups.

CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_broker_unique
    ON accounts (exchange, broker_account_id)
    WHERE broker_account_id IS NOT NULL AND broker_account_id != '';
