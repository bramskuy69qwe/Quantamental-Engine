# SQL Migration System

How the engine manages schema evolution across split SQLite databases.

**Last updated**: 2026-05-15 (v2.4 Phase 1)

---

## Runner

**Location**: `core/migrations/runner.py`

The runner discovers `*.sql` files in `core/migrations/` with numeric
prefixes (e.g. `001_*.sql`), sorted by filename. It applies each
migration to the appropriate database files based on the declared scope.

**Entry points**:
- `run_all(data_dir, migrations_dir)` — apply all pending migrations.
  Called from `main.py` at startup, after `db.initialize()`.
- `run_pending_for_db(db_path, migrations_dir)` — apply all
  per-account migrations to a single DB. For provisioning new accounts.

**Prerequisite**: the `data/.split-complete-v1` marker must exist.
If absent, the runner is a silent no-op.

---

## File format

Every `.sql` migration file must start with a header block:

```sql
-- migration: per_account
-- name: 001_v2_4_account_tz
-- description: Add account_settings table with timezone column
```

| Header | Required | Values |
|--------|----------|--------|
| `-- migration:` | Yes | `per_account` or `global` |
| `-- name:` | Yes | Unique identifier (recorded in `migrations_log`) |
| `-- description:` | No | One-line summary |

**Scope routing**:
- `per_account` — applied to every `data/per_account/*.db` file
- `global` — applied once to `data/global.db`

Missing or invalid headers are a hard error (runner raises `ValueError`
during discovery, before any SQL runs).

---

## Idempotency

Each target DB has a `migrations_log` table:

```sql
CREATE TABLE migrations_log (
    name       TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);
```

Before applying a migration, the runner checks `migrations_log` for the
migration name. If present, the migration is silently skipped.

The runner creates `migrations_log` if it doesn't exist (handles fresh
databases).

---

## Error handling

- If a migration fails on a target DB, that DB is blacklisted for all
  subsequent migrations in the same `run_all()` call.
- Other target DBs continue independently.
- Errors are logged with full traceback but do not crash the app.

---

## DDL auto-commit gotcha

SQLite's `executescript()` has non-standard transaction semantics:

1. Issues an implicit `COMMIT` before executing.
2. Runs each statement sequentially.
3. Stops at the first error.

DDL statements (`CREATE TABLE`, `ALTER TABLE`) are auto-committed by
SQLite, so a failed migration may leave partial schema changes that
cannot be rolled back.

**Mitigations**:
- Use `IF NOT EXISTS` on `CREATE TABLE`.
- Use `OR IGNORE` on `INSERT`.
- Prefer the table-rebuild pattern (below) for column additions.
- Wrap multi-statement migrations in explicit `BEGIN; ... COMMIT;` for
  transactional DDL (SQLite supports this within explicit transactions).

---

## Table-rebuild pattern

Used when `ALTER TABLE ADD COLUMN` isn't safe (multiple columns, or
partial-failure recovery needed). Example from migration 002:

```sql
BEGIN;

CREATE TABLE _account_settings_rebuild (
    -- full schema with all columns including new ones
);

INSERT INTO _account_settings_rebuild (existing_col1, existing_col2)
    SELECT existing_col1, existing_col2 FROM account_settings;

DROP TABLE account_settings;

ALTER TABLE _account_settings_rebuild RENAME TO account_settings;

COMMIT;
```

The `BEGIN; ... COMMIT;` makes the entire rebuild atomic. If any
statement fails, the transaction rolls back and the original table is
preserved.

---

## Python data migrations

For transforms that require cross-DB reads or non-SQL logic, use a
Python module alongside the SQL runner:

- **Example**: `core/migrations/convert_thresholds.py` reads
  `account_params` from the legacy `risk_engine.db` (read-only) and
  writes computed values to per-account `account_settings`.
- Uses the same idempotency pattern: checks `migrations_log`, records
  on success.
- Wired in `main.py` after the SQL runner call.

Use Python data migrations when:
- Reading from one DB and writing to another.
- Computation is needed (not just SQL transforms).
- Legacy DB access is required.

---

## v2.4 migration index

| Number | Name | Scope | Adds |
|--------|------|-------|------|
| 001 | `001_v2_4_account_tz` | per_account | `account_settings` table + `timezone` column |
| 002 | `002_v2_4_dd_thresholds` | per_account | 8 DD + weekly PnL threshold columns (table-rebuild) |
| 003 | `003_v2_4_engine_events` | per_account | `engine_events` audit trail table + 2 indexes |
| 004 | `004_v2_4_account_preferences` | per_account | `strategy_preset`, `analytics_default_period`, `week_start_dow` (table-rebuild) |
| — | `convert_thresholds_from_account_params_v1` | per_account (Python) | Populates DD/weekly thresholds from legacy `account_params` via Option A math |

---

## Cross-references

- Config storage policy: [`docs/config.md`](config.md)
- v2.4 plan (6c coordinated migration list): [`v2.4.md`](../v2.4.md)
