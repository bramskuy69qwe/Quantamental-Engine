"""
000_split_databases — split the legacy combined SQLite file into:

    data/global.db                        <- regime, news, calendar, accounts,
                                             settings, backtest, potential_models
    data/per_account/<terminal>__<broker>__<id>.db
                                          <- per-account transactional tables
    data/ohlcv/<broker>.db                <- market-data cache, per exchange

Run once, manually:

    python -m core.migrations.000_split_databases --dry-run    # preview file plan
    python -m core.migrations.000_split_databases              # execute

After successful execution the script writes `data/.split-complete-v1` to
mark the layout as split. `core.db_router` reads that marker on every call;
once present, it routes to the new file layout instead of the legacy combined
DB.

The original `data/risk_engine.db` is renamed to
`data/risk_engine.db.pre-split-backup` (NOT deleted) so the user can roll back
by deleting the marker and renaming the backup back into place.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from typing import Dict, List, Tuple

# Allow running as `python -m core.migrations.000_split_databases`
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import config
from core.db_router import (
    GLOBAL_DB_PATH,
    OHLCV_DIR,
    PER_ACCOUNT_DIR,
    SPLIT_MARKER,
    ohlcv_path,
    per_account_path,
)


# ── Table classification ──────────────────────────────────────────────────────

GLOBAL_TABLES = [
    "accounts",
    "settings",
    "migrations_log",
    "regime_signals",
    "regime_labels",
    "news_items",
    "economic_calendar",
    "backtest_sessions",
    "backtest_trades",
    "backtest_equity",
    "potential_models",
]

PER_ACCOUNT_TABLES = [
    "account_snapshots",
    "position_changes",
    "pre_trade_log",
    "execution_log",
    "trade_history",
    "exchange_history",
    "equity_cashflow",
    # position_history_notes is keyed by trade_key; trade_keys are unique per
    # trade so we copy them with whichever account "owned" the matching row.
    # Handled separately below.
]

OHLCV_TABLES = ["ohlcv_cache"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _norm_broker(exchange: str, market_type: str) -> str:
    """Normalise an accounts row's (exchange, market_type) into a broker tag.

    e.g. ('binance', 'future') -> 'binancefutures'
         ('binance', 'spot')   -> 'binance'
    """
    e = (exchange or "").strip().lower()
    m = (market_type or "").strip().lower()
    if e == "binance" and m == "future":
        return "binancefutures"
    return e or "unknown"


def _accounts_from_legacy(src: sqlite3.Connection) -> List[Dict]:
    cur = src.execute("SELECT id, name, exchange, market_type, broker_account_id FROM accounts")
    rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "exchange": r[2],
            "market_type": r[3],
            "broker_account_id": (r[4] or "").strip() or str(r[0]),
            "terminal": "quantower",   # only terminal supported in v2.1
        }
        for r in rows
    ]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return cur.fetchone() is not None


def _row_count(conn: sqlite3.Connection, table: str, where: str = "", params: tuple = ()) -> int:
    if not _table_exists(conn, table):
        return 0
    sql = f"SELECT COUNT(*) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    return conn.execute(sql, params).fetchone()[0]


def _copy_schema(src: sqlite3.Connection, dst: sqlite3.Connection, table: str) -> None:
    """Copy CREATE TABLE + CREATE INDEX statements for a table from src to dst."""
    cur = src.execute(
        "SELECT type, sql FROM sqlite_master "
        "WHERE (type='table' OR type='index') AND tbl_name=? AND sql IS NOT NULL",
        (table,),
    )
    for _kind, sql in cur.fetchall():
        dst.execute(sql)


def _copy_table_filtered(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    table: str,
    where: str = "",
    params: tuple = (),
) -> int:
    """Copy rows from src.<table> to dst.<table>. Returns row count copied."""
    if not _table_exists(src, table):
        return 0
    if not _table_exists(dst, table):
        _copy_schema(src, dst, table)
    sql = f"SELECT * FROM {table}"
    if where:
        sql += f" WHERE {where}"
    rows = src.execute(sql, params).fetchall()
    if not rows:
        return 0
    placeholders = ",".join("?" for _ in rows[0])
    dst.executemany(f"INSERT OR IGNORE INTO {table} VALUES ({placeholders})", rows)
    return len(rows)


# ── Plan / execute ────────────────────────────────────────────────────────────

def build_plan(legacy_path: str) -> Dict:
    """Read the legacy DB and return a plan describing what will be written."""
    if not os.path.exists(legacy_path):
        return {"error": f"Legacy DB not found at {legacy_path}"}

    src = sqlite3.connect(legacy_path)
    accounts = _accounts_from_legacy(src)

    plan = {
        "legacy_path": legacy_path,
        "global": {
            "path": GLOBAL_DB_PATH,
            "tables": [(t, _row_count(src, t)) for t in GLOBAL_TABLES],
        },
        "per_account": [],
        "ohlcv": {
            "path": ohlcv_path("binancefutures"),
            "tables": [(t, _row_count(src, t)) for t in OHLCV_TABLES],
        },
        "backup_path": legacy_path + ".pre-split-backup",
    }

    for acct in accounts:
        path = per_account_path(acct["terminal"], _norm_broker(acct["exchange"], acct["market_type"]), acct["broker_account_id"])
        per_acct = {
            "account_id": acct["id"],
            "name": acct["name"],
            "terminal": acct["terminal"],
            "broker": _norm_broker(acct["exchange"], acct["market_type"]),
            "broker_account_id": acct["broker_account_id"],
            "path": path,
            "tables": [
                (t, _row_count(src, t, "account_id = ?", (acct["id"],)))
                for t in PER_ACCOUNT_TABLES
            ],
        }
        plan["per_account"].append(per_acct)

    src.close()
    return plan


def render_plan(plan: Dict) -> str:
    if "error" in plan:
        return f"ERROR: {plan['error']}"
    lines = []
    lines.append(f"Source:        {plan['legacy_path']}")
    lines.append(f"Backup target: {plan['backup_path']}")
    lines.append("")
    lines.append(f"GLOBAL -> {plan['global']['path']}")
    for t, n in plan["global"]["tables"]:
        lines.append(f"   {t:<25} {n:>10} rows")
    lines.append("")
    for acc in plan["per_account"]:
        lines.append(
            f"ACCOUNT {acc['account_id']} ({acc['name']}, "
            f"{acc['terminal']}/{acc['broker']}/{acc['broker_account_id']}) -> {acc['path']}"
        )
        for t, n in acc["tables"]:
            lines.append(f"   {t:<25} {n:>10} rows")
        lines.append("")
    lines.append(f"OHLCV -> {plan['ohlcv']['path']}")
    for t, n in plan["ohlcv"]["tables"]:
        lines.append(f"   {t:<25} {n:>10} rows")
    return "\n".join(lines)


def execute(plan: Dict) -> None:
    """Execute the split. Idempotent on row inserts (uses INSERT OR IGNORE)."""
    if "error" in plan:
        raise RuntimeError(plan["error"])

    os.makedirs(os.path.dirname(GLOBAL_DB_PATH), exist_ok=True)
    os.makedirs(PER_ACCOUNT_DIR, exist_ok=True)
    os.makedirs(OHLCV_DIR, exist_ok=True)

    src = sqlite3.connect(plan["legacy_path"])

    # Global DB
    # Holds canonical global tables PLUS a backwards-compatibility copy of every
    # per-account table (full unfiltered set). This keeps existing callers like
    # `db.insert_account_snapshot(...)` working post-split without forcing the
    # whole codebase to migrate to db_router.account_db() in one shot.
    # Future cleanup: drop per-account tables from global.db once all writers
    # have moved to db_router.
    g = sqlite3.connect(plan["global"]["path"])
    g.execute("PRAGMA journal_mode=WAL")
    for table in GLOBAL_TABLES:
        n = _copy_table_filtered(src, g, table)
        print(f"  global: {table} <- {n} rows")
    print("  global: copying per-account tables as compatibility shim")
    for table in PER_ACCOUNT_TABLES:
        n = _copy_table_filtered(src, g, table)
        print(f"  global (compat): {table} <- {n} rows")
    if _table_exists(src, "position_history_notes"):
        n = _copy_table_filtered(src, g, "position_history_notes")
        print(f"  global (compat): position_history_notes <- {n} rows")
    if _table_exists(src, "ohlcv_cache"):
        # Some callers query ohlcv_cache via the legacy db handle. Keep a copy
        # in global.db too — the canonical home is data/ohlcv/<broker>.db.
        n = _copy_table_filtered(src, g, "ohlcv_cache")
        print(f"  global (compat): ohlcv_cache <- {n} rows")
    g.commit()
    g.close()

    # Per-account DBs
    for acc in plan["per_account"]:
        a = sqlite3.connect(acc["path"])
        a.execute("PRAGMA journal_mode=WAL")
        for table in PER_ACCOUNT_TABLES:
            n = _copy_table_filtered(src, a, table, "account_id = ?", (acc["account_id"],))
            print(f"  account {acc['account_id']}: {table} <- {n} rows")
        # position_history_notes — copy any rows whose trade_key shows up
        # in this account's exchange_history (best-effort heuristic).
        if _table_exists(src, "position_history_notes") and _table_exists(src, "exchange_history"):
            keys = src.execute(
                "SELECT DISTINCT trade_key FROM exchange_history WHERE account_id = ?",
                (acc["account_id"],),
            ).fetchall()
            if keys:
                if not _table_exists(a, "position_history_notes"):
                    _copy_schema(src, a, "position_history_notes")
                placeholders = ",".join("?" for _ in keys)
                rows = src.execute(
                    f"SELECT * FROM position_history_notes "
                    f"WHERE trade_key IN ({placeholders})",
                    [k[0] for k in keys],
                ).fetchall()
                if rows:
                    pf = ",".join("?" for _ in rows[0])
                    a.executemany(
                        f"INSERT OR IGNORE INTO position_history_notes VALUES ({pf})",
                        rows,
                    )
                    print(f"  account {acc['account_id']}: position_history_notes <- {len(rows)} rows")
        a.commit()
        a.close()

    # OHLCV per broker (only one broker exists today)
    o = sqlite3.connect(plan["ohlcv"]["path"])
    o.execute("PRAGMA journal_mode=WAL")
    for table in OHLCV_TABLES:
        n = _copy_table_filtered(src, o, table)
        print(f"  ohlcv: {table} <- {n} rows")
    o.commit()
    o.close()

    src.close()

    # Backup the legacy file (rename, do NOT delete)
    if not os.path.exists(plan["backup_path"]):
        shutil.move(plan["legacy_path"], plan["backup_path"])
        print(f"  backup: {plan['legacy_path']} -> {plan['backup_path']}")
    else:
        print(f"  backup already exists at {plan['backup_path']}; leaving legacy file in place")

    # Marker
    with open(SPLIT_MARKER, "w", encoding="utf-8") as f:
        f.write("split-complete-v1\n")
    print(f"  marker: {SPLIT_MARKER}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="000_split_databases",
        description="Split the legacy combined SQLite DB into global / per-account / ohlcv files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the file plan and row counts without writing anything.",
    )
    parser.add_argument(
        "--source",
        default=config.DB_PATH,
        help=f"Path to the legacy DB to split (default: {config.DB_PATH}).",
    )
    args = parser.parse_args(argv)

    if os.path.exists(SPLIT_MARKER):
        print(f"Split already complete (marker found at {SPLIT_MARKER}). Nothing to do.")
        return 0

    print(f"Building plan from {args.source} ...\n")
    plan = build_plan(args.source)
    print(render_plan(plan))

    if "error" in plan:
        return 2

    if args.dry_run:
        print("\nDRY RUN -- no files written. Re-run without --dry-run to execute.")
        return 0

    print("\nExecuting split ...")
    execute(plan)
    print("\nSplit complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
