"""
Database router — picks the correct SQLite file for a given call.

Layout target (post-split):
    data/
      global.db                              ← regime, news, calendar, accounts,
                                               settings, backtest, potential_models
      per_account/
        <terminal>__<broker>__<id>.db        ← snapshots, position_changes,
                                               pre_trade_log, execution_log,
                                               trade_history, exchange_history,
                                               equity_cashflow
      ohlcv/
        <broker>.db                          ← market data cache, per exchange

R1a (current state): the actual file split has NOT happened yet. Every accessor
returns the legacy combined DB (`core.database.db` → `config.DB_PATH`). New code
can already import `db_router` and use the routing API; behaviour is identical
to the legacy singleton until the split migration runs.

R1b (next step): user runs `python -m core.migrations.000_split_databases` once.
The migration writes `data/.split-complete-v1`; from that point the router
returns separate `DatabaseManager` instances per file.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

import config
from core.database import DatabaseManager, db as _legacy_db

log = logging.getLogger("db_router")


# ── Path conventions ──────────────────────────────────────────────────────────

GLOBAL_DB_PATH    = os.path.join(config.DATA_DIR, "global.db")
PER_ACCOUNT_DIR   = os.path.join(config.DATA_DIR, "per_account")
OHLCV_DIR         = os.path.join(config.DATA_DIR, "ohlcv")
SPLIT_MARKER      = os.path.join(config.DATA_DIR, ".split-complete-v1")


def _safe(s: str) -> str:
    """Sanitise a string for use in a filename."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in (s or "").lower())


def per_account_path(terminal: str, broker: str, broker_account_id: str) -> str:
    """Filesystem-safe per-account DB path."""
    return os.path.join(
        PER_ACCOUNT_DIR,
        f"{_safe(terminal)}__{_safe(broker)}__{_safe(broker_account_id)}.db",
    )


def ohlcv_path(broker: str) -> str:
    return os.path.join(OHLCV_DIR, f"{_safe(broker)}.db")


def split_done() -> bool:
    """True iff the split migration has produced the marker file."""
    return os.path.exists(SPLIT_MARKER)


# ── Router ────────────────────────────────────────────────────────────────────

AccountKey = Tuple[str, str, str]   # (terminal, broker, broker_account_id)


class DbRouter:
    """
    Routes DB access to one of:
      - the global DB (shared, no account scope)
      - a per-(terminal, broker, broker_account_id) DB
      - a per-broker OHLCV cache

    Until the split migration has run, every accessor returns the legacy
    singleton in `core.database` so existing callers continue to work.
    """

    def __init__(self) -> None:
        self._global: Optional[DatabaseManager] = None
        self._accounts: Dict[AccountKey, DatabaseManager] = {}
        self._account_keys: Dict[int, AccountKey] = {}
        self._ohlcv: Dict[str, DatabaseManager] = {}

    # ── Accessors ─────────────────────────────────────────────────────────────

    @property
    def global_db(self) -> DatabaseManager:
        """Manager for the shared (regime/news/accounts/settings/backtest) DB.

        Always returns the legacy `core.database.db` singleton — pre-split it
        points at the combined file, post-split it auto-resolves to
        `data/global.db`. Returning the same singleton keeps exactly one
        connection per process (no duplicate writers, no double init)."""
        return _legacy_db

    def account_db(
        self,
        *,
        terminal: Optional[str] = None,
        broker: Optional[str] = None,
        broker_account_id: Optional[str] = None,
        account_id: Optional[int] = None,
    ) -> DatabaseManager:
        """
        Per-account DB manager.

        Pre-split: returns the legacy combined DB regardless of arguments.

        Post-split: caller supplies either an `account_id` (looked up against
        the accounts table in global.db) or the explicit (terminal, broker,
        broker_account_id) tuple. Resolved managers are cached.
        """
        if not split_done():
            return _legacy_db

        # Resolve via account_id lookup if explicit tuple isn't provided
        if not (terminal and broker and broker_account_id):
            if account_id is None:
                raise ValueError(
                    "account_db: pass either account_id=... or "
                    "terminal+broker+broker_account_id"
                )
            terminal, broker, broker_account_id = self._resolve_account_id(account_id)

        key: AccountKey = (terminal, broker, broker_account_id)
        if key not in self._accounts:
            self._accounts[key] = DatabaseManager(per_account_path(*key))
        return self._accounts[key]

    def _resolve_account_id(self, account_id: int) -> AccountKey:
        """Look up (terminal, broker, broker_account_id) for an internal
        accounts.id by reading global.db synchronously. Result is cached
        on the instance so the lookup happens once per account_id."""
        cached = self._account_keys.get(account_id)
        if cached is not None:
            return cached

        import sqlite3
        with sqlite3.connect(GLOBAL_DB_PATH) as conn:
            cur = conn.execute(
                "SELECT exchange, market_type, broker_account_id "
                "FROM accounts WHERE id = ?",
                (account_id,),
            )
            row = cur.fetchone()
        if row is None:
            raise LookupError(
                f"account_db: no accounts row with id={account_id} in {GLOBAL_DB_PATH}"
            )
        exchange, market_type, broker_account_id = row
        # Same broker normalisation the migration script uses
        e = (exchange or "").strip().lower()
        m = (market_type or "").strip().lower()
        broker = "binancefutures" if (e == "binance" and m == "future") else (e or "unknown")
        terminal = "quantower"
        broker_account_id = (broker_account_id or "").strip() or str(account_id)

        key: AccountKey = (terminal, broker, broker_account_id)
        self._account_keys[account_id] = key
        return key

    def ohlcv_db(self, broker: str) -> DatabaseManager:
        """Per-exchange OHLCV cache manager."""
        if not split_done():
            return _legacy_db
        if broker not in self._ohlcv:
            self._ohlcv[broker] = DatabaseManager(ohlcv_path(broker))
        return self._ohlcv[broker]

    # ── Read accessor (post-split: per-account file; pre-split: legacy db) ────

    @property
    def account_read(self) -> DatabaseManager:
        """Per-account DB manager for READS, resolved against the *active*
        account. Pre-split falls back to the legacy combined DB.

        Usage:
            rows = await db_router.account_read.get_all_pre_trade_log(days=30)
        """
        if not split_done():
            return _legacy_db
        from core.state import app_state
        return self.account_db(account_id=app_state.active_account_id)

    # ── Dual-write proxy ──────────────────────────────────────────────────────

    @property
    def account(self) -> "_AccountDualWriter":
        """Return a proxy that mirrors per-account writes to both the legacy
        compat shim (`global.db`) and the active account's per-account file.

        Usage:
            await db_router.account.insert_account_snapshot(snap)

        The proxy resolves the active account from `app_state.active_account_id`
        unless `account_id=` is passed explicitly in kwargs.
        """
        return _AccountDualWriter(self)

    # ── Per-account lifecycle ─────────────────────────────────────────────────

    async def initialize_account(self, account_id: int) -> Optional[DatabaseManager]:
        """Open + schema-init the per-account DB for the given account_id.
        Pre-split: no-op (returns None). Post-split: opens the file, creates
        the schema if missing, caches the manager."""
        if not split_done():
            return None
        per = self.account_db(account_id=account_id)
        if per._conn is None:
            await per.initialize()
        return per

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """
        Initialise the global DB and any per-account / OHLCV DBs that have
        already been opened. Pre-split this is a no-op — `main.py` continues
        to call `db.initialize()` on the legacy singleton.
        """
        if not split_done():
            return
        await self.global_db.initialize()
        for instance in self._accounts.values():
            await instance.initialize()
        for instance in self._ohlcv.values():
            await instance.initialize()

    async def close(self) -> None:
        if not split_done():
            return
        if self._global is not None:
            await self._global.close()
        for instance in self._accounts.values():
            await instance.close()
        for instance in self._ohlcv.values():
            await instance.close()


# ── Dual-write proxy ──────────────────────────────────────────────────────────

class _AccountDualWriter:
    """
    Forwards arbitrary method calls to BOTH:
      1. the legacy `db` singleton (which post-split = global.db, the compat
         shim that all existing readers still query), and
      2. the active account's per-account `DatabaseManager`.

    Pre-split: behaviour collapses to "call the legacy db once" because both
    accessors return the same singleton.

    Post-split: the call hits global.db first (so readers see the new row),
    then mirrors the same call against the per-account file. Per-account
    failures are logged but do NOT break the primary write — losing a mirror
    row is recoverable; losing the canonical row is not.
    """

    def __init__(self, router: DbRouter) -> None:
        self._router = router

    def __getattr__(self, method_name: str):
        async def _dual_call(*args, **kwargs):
            # Always do the canonical write first (legacy / compat shim path)
            primary = getattr(_legacy_db, method_name)
            primary_result = await primary(*args, **kwargs)

            # Mirror to per-account file post-split only
            if not split_done():
                return primary_result

            # Resolve active account
            account_id = kwargs.get("account_id")
            if account_id is None:
                # Try to fish it out of the first dict arg (snap, payload, etc.)
                for arg in args:
                    if isinstance(arg, dict) and "account_id" in arg:
                        account_id = arg.get("account_id")
                        break
            if account_id is None:
                from core.state import app_state
                account_id = app_state.active_account_id

            try:
                per = self._router.account_db(account_id=account_id)
                if per._conn is None:
                    await per.initialize()
                mirror = getattr(per, method_name)
                await mirror(*args, **kwargs)
            except Exception as exc:
                log.warning(
                    "db_router.account: mirror write %s -> per-account "
                    "(account_id=%s) failed: %r",
                    method_name, account_id, exc,
                )
            return primary_result

        return _dual_call


# Module-level singleton
db_router = DbRouter()
