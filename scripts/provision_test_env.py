"""
Provision a fresh worktree/clone's ``data/`` dir so the full test suite
reproduces the operator's green gate outside the main working tree.

Why this exists
───────────────
A fresh git worktree fails ~110 tests (``sqlite3.OperationalError: no
such table: account_settings / pre_trade_log / engine_events /
trade_events``) because ``data/`` lacks the SPLIT LAYOUT:
``core/db_router.py`` bakes ``SPLIT_MARKER = DATA_DIR/.split-complete-v1``
and ``db_account_settings._resolve_db_path`` short-circuits to the
legacy ``risk_engine.db`` fallback whenever ``split_done()`` is False —
even when a test patched ``config.DATA_DIR`` to a perfect tmp
split-layout. Two sessions burned on this wall (2026-07-17 red-herring,
2026-07-21 root-cause + this script). Verified result: worktree gate ==
main-tree gate exactly (4092 passed / 7 skipped / 3 deselected on the
``.venv`` interpreter — user-site Python lacks ``pytest-timeout``;
always run the suite with ``.venv/Scripts/python.exe``).

What it does (the app's own provisioning machinery, in boot order)
──────────────────────────────────────────────────────────────────
1.  ``DatabaseManager(DB_PATH).initialize()`` — canonical legacy schema
2.  upsert accounts registry row id=1 (live-mirror values, EMPTY creds)
3.  ``core.migrations.000_split_databases`` — dry-run printed, then run
4.  re-``initialize()`` the legacy DB (the split renames it to
    ``.pre-split-backup``; the live env keeps BOTH files)
5.  seed the ``accounts`` table INTO the per-account DB — the split
    does not copy it, but migration 001 + ``convert_thresholds`` both
    ``SELECT ... FROM accounts`` there; a missing table poisons every
    later per-account migration via the runner's failed-targets set
6.  ``initialize()`` global.db / per-account / ohlcv DBs (live split
    DBs carry the full canonical superset schema, same as the app's
    ``DbRouter``/shadow-provisioning produces)
7.  SQL migrations 001-014, statement-by-statement, tolerating ONLY
    "duplicate column name" (a fresh ``initialize()`` already embodies
    the historical ALTERs of 005/011/013/014 — semantically applied)
8.  ``convert_thresholds()``
9.  mirror live ``account_settings`` prefs (tz/thresholds — parity so
    the gate exercises the same config shape as the operator's env)
10. credential scrub + fail-loud verification (see below)

Credential safety (audit finding, 2026-07-21)
─────────────────────────────────────────────
``config.py``'s bare ``load_dotenv()`` parent-walks from a worktree and
loads the MAIN tree's live ``.env``; ``core/database.py``'s fresh-DB
seeds (v1.3-seed on ``accounts``, ``_migrate_env_connections`` on
``connections``) then ENCRYPT the real BINANCE_*/FRED/FINNHUB/COINGECKO
keys into every empty DB ``initialize()`` touches. This script PREVENTS
that (blanks the ``config`` credential attrs before any DB init) and
additionally scrubs + verifies every provisioned DB afterwards, failing
loud on any residual. Blob probe uses ``LIKE '%gAAAA%'`` — the app
prefixes tokens with ``v2:``, so an anchored ``gAAAA%`` misses them.

Guards (this tool must never touch the operator's live data)
────────────────────────────────────────────────────────────
- refuses to run in a PRIMARY checkout (``.git`` is a directory — the
  operator's live ``data/`` lives there); linked worktrees have a
  ``.git`` FILE. ``--allow-primary-checkout`` exists solely for fresh
  clones (e.g. CI) that have no live data.
- a non-empty ``data/`` requires an explicit ``--wipe``.
- ``--wipe`` HARD-refuses (no override) if any DB under ``data/`` holds
  rows in real-trading tables (fills / trade_history / exchange_history
  / closed_positions / position_changes) — live-shaped data is never
  deleted by this tool, flags or not.

Usage
─────
    .venv/Scripts/python.exe scripts/provision_test_env.py          # fresh dir
    .venv/Scripts/python.exe scripts/provision_test_env.py --wipe  # reprovision
"""
from __future__ import annotations

import argparse
import glob
import os
import runpy
import shutil
import sqlite3
import sys
from typing import Iterator, List, Tuple

# ── Live-mirror constants (operator prefs — non-sensitive; parity with the
#    green-gate environment. Creds are ALWAYS empty by construction.) ────────
ACCOUNT_ROW = {
    "id": 1,
    "name": "Account 1 (Binance Futures)",
    "exchange": "binance",
    "market_type": "future",
    "broker_account_id": "binance",  # names the per-account DB file; a NULL
    # here makes the split fall back to "1" and tests that hardcode
    # quantower__binancefutures__binance.db (test_data_cache_dd) go red
    "created_at": "2026-04-08 09:25:33",
}
ACCOUNT_SETTINGS = {
    "timezone": "Asia/Jakarta",
    "dd_rolling_window_days": 30,
    "dd_warning_threshold": 0.08,
    "dd_limit_threshold": 0.095,
    "dd_recovery_threshold": 0.5,
    "dd_enforcement_mode": "advisory",
    "weekly_pnl_warning_threshold": 0.04,
    "weekly_pnl_limit_threshold": 0.0475,
    "weekly_pnl_enforcement_mode": "advisory",
    "strategy_preset": None,
    "analytics_default_period": "monthly",
    "week_start_dow": 1,
}
# Tables whose rows mark a data dir as LIVE-shaped (never wiped by this tool).
LIVE_TABLES = (
    "fills",
    "trade_history",
    "exchange_history",
    "closed_positions",
    "position_changes",
)
# config attributes the fresh-DB seeds read (see module docstring).
CREDENTIAL_ATTRS = (
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "FRED_API_KEY",
    "FINNHUB_API_KEY",
    "COINGECKO_API_KEY",
)

_TXN_MARKERS = {
    "BEGIN",
    "BEGIN TRANSACTION",
    "COMMIT",
    "COMMIT TRANSACTION",
    "END",
    "END TRANSACTION",
}


# ── Pure helpers (import-safe: no config/core imports at module level) ───────


def _statements(sql_text: str) -> Iterator[str]:
    """Split migration SQL into executable statements.

    - leading ``--`` comment lines before a statement are skipped
    - BEGIN/COMMIT (incl. ``... TRANSACTION`` spellings) are dropped —
      statements execute individually here, so txn markers are no-ops
    - a trailing statement WITHOUT a terminating ``;`` is still yielded
      (sqlite3.complete_statement never confirms it; flushing the buffer
      at EOF closes that silent-drop hole)
    """
    buf: List[str] = []

    def _flush() -> str:
        stmt = "\n".join(buf).strip()
        buf.clear()
        return stmt

    def _emit(stmt: str) -> bool:
        if not stmt:
            return False
        return stmt.rstrip(";").strip().upper() not in _TXN_MARKERS

    for line in sql_text.splitlines():
        if line.strip().startswith("--") and not buf:
            continue
        buf.append(line)
        if sqlite3.complete_statement("\n".join(buf)):
            stmt = _flush()
            if _emit(stmt):
                yield stmt
    tail = _flush()
    # EOF flush: only comments/whitespace is not a statement
    if _emit(tail) and any(
        ln.strip() and not ln.strip().startswith("--") for ln in tail.splitlines()
    ):
        yield tail


def _db_files(data_dir: str) -> List[str]:
    return sorted(
        f
        for f in glob.glob(os.path.join(data_dir, "**", "*"), recursive=True)
        if f.endswith(".db") or f.endswith(".pre-split-backup")
    )


def guard_refusals(root: str, allow_primary: bool = False) -> List[str]:
    """Structural refusals — reasons this tool must not run at *root*."""
    reasons = []
    gitp = os.path.join(root, ".git")
    if not os.path.exists(gitp):
        reasons.append(f"no .git at {root} — not a repo checkout")
    elif os.path.isdir(gitp) and not allow_primary:
        reasons.append(
            "primary checkout (.git is a directory) — the operator's live "
            "data/ lives here; this tool provisions DISPOSABLE worktrees. "
            "Pass --allow-primary-checkout ONLY on a fresh clone with no "
            "live data/."
        )
    return reasons


def looks_live(data_dir: str) -> List[str]:
    """Evidence that *data_dir* holds live-shaped data (rows in real-trading
    tables). Non-empty result = HARD refusal for any destructive step.

    Phase-7 exemption: ``closed_positions`` rows whose
    ``terminal_position_id`` starts with ``e2e:`` are the sandbox seed
    fixtures (``e2e/scripts/seed-sandbox.py`` marks every row it inserts),
    not live data — counting them made EVERY sandbox re-provision refuse
    over its own seeds (hit twice in the Phase-7 re-run; the operator-side
    workaround was verify-then-delete-data/ by hand). A REAL live DB never
    carries the marker, so the exemption cannot weaken the gate for live
    trees; every other table still counts every row."""
    evidence = []
    for path in _db_files(data_dir):
        try:
            conn = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True)
        except sqlite3.Error:
            continue
        try:
            for table in LIVE_TABLES:
                if not conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone():
                    continue
                if table == "closed_positions":
                    n = conn.execute(
                        "SELECT COUNT(*) FROM closed_positions "
                        "WHERE COALESCE(terminal_position_id, '') NOT LIKE 'e2e:%'"
                    ).fetchone()[0]
                else:
                    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if n:
                    evidence.append(f"{path}:{table}:{n}")
        except sqlite3.DatabaseError:
            pass  # not a real DB (stray -wal/-shm-shaped file) — no evidence
        finally:
            conn.close()
    return evidence


def blank_config_credentials(config_module) -> List[str]:
    """Prevent core.database's fresh-DB seeds from materializing real keys
    (they check truthiness of these attrs at initialize() time)."""
    blanked = []
    for attr in CREDENTIAL_ATTRS:
        if getattr(config_module, attr, ""):
            blanked.append(attr)
        setattr(config_module, attr, "")
    return blanked


def scrub_credentials(data_dir: str) -> Tuple[List[str], int]:
    """Blank accounts creds + drop connections rows in every DB under
    *data_dir*; verify zero residual blobs. Raises RuntimeError on residual
    (fail loud — never ship credentials silently)."""
    scrubbed = []
    residual = 0
    for path in _db_files(data_dir):
        conn = sqlite3.connect(path)
        try:
            has = lambda n: conn.execute(  # noqa: E731
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (n,)
            ).fetchone()
            if has("accounts"):
                n = conn.execute(
                    "UPDATE accounts SET api_key_enc='', api_secret_enc='' "
                    "WHERE COALESCE(api_key_enc,'') != '' "
                    "   OR COALESCE(api_secret_enc,'') != ''"
                ).rowcount
                if n:
                    scrubbed.append(f"{path}:accounts:{n}")
            if has("connections"):
                n = conn.execute("DELETE FROM connections").rowcount
                if n:
                    scrubbed.append(f"{path}:connections:{n}")
            conn.commit()
            if has("accounts"):
                residual += conn.execute(
                    "SELECT COUNT(*) FROM accounts WHERE api_key_enc LIKE '%gAAAA%' "
                    "OR api_secret_enc LIKE '%gAAAA%'"
                ).fetchone()[0]
        except sqlite3.DatabaseError:
            pass  # non-DB file caught by _db_files' loose suffix match
        finally:
            conn.close()
    if residual:
        raise RuntimeError(
            f"credential scrub left {residual} blob-bearing row(s) under "
            f"{data_dir} — refusing to finish"
        )
    return scrubbed, residual


# ── Provisioning steps (heavy imports deferred — import-safe module) ─────────


def _init_db(path: str) -> None:
    import asyncio

    from core.database import DatabaseManager

    async def go():
        m = DatabaseManager(path)
        await m.initialize()
        await m.close()

    asyncio.run(go())


def _run_split() -> None:
    saved = sys.argv[:]
    for argv in (["000_split_databases", "--dry-run"], ["000_split_databases"]):
        sys.argv = argv
        try:
            runpy.run_module("core.migrations.000_split_databases", run_name="__main__")
        except SystemExit as e:  # argparse/main() exit — 0 is success
            if e.code not in (0, None):
                sys.argv = saved
                raise RuntimeError(f"split migration failed rc={e.code}")
    sys.argv = saved


def _apply_migrations(data_dir: str) -> int:
    """Duplicate-column-tolerant reconcile (see module docstring, step 7)."""
    from core.migrations import runner

    applied = 0
    for m in runner.discover():
        for target in runner._find_targets(data_dir, m.scope):
            conn = sqlite3.connect(target)
            try:
                runner._ensure_log_table(conn)
                if runner._is_applied(conn, m.name):
                    continue
                dups = 0
                for stmt in _statements(m.sql):
                    try:
                        conn.execute(stmt)
                    except sqlite3.OperationalError as e:
                        if "duplicate column name" in str(e):
                            dups += 1
                            continue
                        raise
                conn.execute(
                    "INSERT INTO migrations_log (name, applied_at) "
                    "VALUES (?, datetime('now'))",
                    (m.name,),
                )
                conn.commit()
                applied += 1
                note = f" ({dups} dup-col stmts skipped)" if dups else ""
                print(f"  applied {m.name} -> {os.path.basename(target)}{note}")
            finally:
                conn.close()
    return applied


def provision(root: str) -> None:
    """Run the full sequence. ``data/`` must not exist or be empty; callers
    (main) own the guards + wipe decision."""
    os.chdir(root)
    if root not in sys.path:
        sys.path.insert(0, root)

    import config

    if config.DATA_DIR != "data":
        raise RuntimeError(f"unexpected config.DATA_DIR={config.DATA_DIR!r}")

    blanked = blank_config_credentials(config)
    print(f"step 0: blanked config credential attrs: {blanked or 'none were set'}")

    print("step 1: initialize legacy DB (canonical schema)")
    os.makedirs("data", exist_ok=True)
    _init_db(config.DB_PATH)

    print("step 2: upsert accounts registry row (EMPTY creds)")
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute(
        "INSERT OR IGNORE INTO accounts "
        "(id, name, exchange, market_type, api_key_enc, api_secret_enc, "
        " is_active, created_at, broker_account_id) VALUES (?,?,?,?,'','',1,?,?)",
        (
            ACCOUNT_ROW["id"],
            ACCOUNT_ROW["name"],
            ACCOUNT_ROW["exchange"],
            ACCOUNT_ROW["market_type"],
            ACCOUNT_ROW["created_at"],
            ACCOUNT_ROW["broker_account_id"],
        ),
    )
    # initialize() may have pre-seeded id=1 (v1.3-seed shape) — force values
    conn.execute(
        "UPDATE accounts SET name=?, exchange=?, market_type=?, "
        "api_key_enc='', api_secret_enc='', is_active=1, broker_account_id=? "
        "WHERE id=?",
        (
            ACCOUNT_ROW["name"],
            ACCOUNT_ROW["exchange"],
            ACCOUNT_ROW["market_type"],
            ACCOUNT_ROW["broker_account_id"],
            ACCOUNT_ROW["id"],
        ),
    )
    conn.commit()
    conn.close()

    print("step 3: split migration (dry-run, then execute)")
    _run_split()

    print("step 4: re-initialize legacy DB (split renamed it to backup)")
    _init_db(config.DB_PATH)

    print("step 5: seed accounts table into the per-account DB")
    from core.db_router import per_account_path

    pa_path = per_account_path("quantower", "binancefutures", ACCOUNT_ROW["broker_account_id"])
    if not os.path.exists(pa_path):
        raise RuntimeError(f"per-account DB missing after split: {pa_path}")
    src = sqlite3.connect(config.DB_PATH)
    create_sql = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='accounts'"
    ).fetchone()[0]
    src.close()
    conn = sqlite3.connect(pa_path)
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='accounts'"
    ).fetchone():
        conn.execute(create_sql)
    conn.execute(
        "INSERT OR IGNORE INTO accounts "
        "(id, name, exchange, market_type, api_key_enc, api_secret_enc, "
        " is_active, created_at, broker_account_id) VALUES (?,?,?,?,'','',1,?,NULL)",
        (
            ACCOUNT_ROW["id"],
            ACCOUNT_ROW["name"],
            ACCOUNT_ROW["exchange"],
            ACCOUNT_ROW["market_type"],
            "2026-04-28 06:06:11",  # live per-account row's created_at
        ),
    )
    conn.commit()
    conn.close()

    print("step 6: initialize split DBs (canonical superset, as the app does)")
    for p in (
        os.path.join("data", "global.db"),
        pa_path,
        os.path.join("data", "ohlcv", "binancefutures.db"),
    ):
        print(f"  initialize: {p}")
        _init_db(p)

    print("step 7: SQL migrations (duplicate-column-tolerant reconcile)")
    total = _apply_migrations("data")
    print(f"  total applied: {total}")

    print("step 8: convert_thresholds()")
    from core.migrations.convert_thresholds import convert_thresholds

    convert_thresholds()

    print("step 9: mirror live account_settings prefs")
    cols = ", ".join(f"{k}=?" for k in ACCOUNT_SETTINGS)
    conn = sqlite3.connect(pa_path)
    conn.execute(
        f"UPDATE account_settings SET {cols} WHERE account_id=?",
        (*ACCOUNT_SETTINGS.values(), ACCOUNT_ROW["id"]),
    )
    conn.commit()
    conn.close()

    print("step 10: credential scrub + verification")
    scrubbed, _ = scrub_credentials("data")
    print(f"  scrubbed: {scrubbed or 'nothing (prevention held)'}")

    print("final layout:")
    for p in _db_files("data") + [os.path.join("data", ".split-complete-v1")]:
        if os.path.exists(p):
            print(f"  {os.path.getsize(p):>10}  {p}")
    print("PROVISION OK")


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="provision_test_env",
        description="Provision a fresh worktree/clone's data/ dir for the test gate.",
    )
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="Delete an existing (non-live-shaped) data/ dir before provisioning.",
    )
    parser.add_argument(
        "--allow-primary-checkout",
        action="store_true",
        help="Permit running where .git is a directory (fresh clones ONLY — "
        "never the operator's main working tree).",
    )
    args = parser.parse_args(argv)

    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))

    reasons = guard_refusals(root, allow_primary=args.allow_primary_checkout)
    if reasons:
        for r in reasons:
            print(f"REFUSED: {r}")
        return 2

    data_dir = os.path.join(root, "data")
    if os.path.isdir(data_dir) and os.listdir(data_dir):
        if not args.wipe:
            print(
                f"REFUSED: {data_dir} is non-empty — pass --wipe to reprovision "
                "(refused regardless if the data looks live)."
            )
            return 2
        evidence = looks_live(data_dir)
        if evidence:
            print("REFUSED (no override): data/ holds live-shaped rows:")
            for e in evidence:
                print(f"  {e}")
            return 3
        print(f"wiping {data_dir}")
        shutil.rmtree(data_dir)

    provision(root)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
