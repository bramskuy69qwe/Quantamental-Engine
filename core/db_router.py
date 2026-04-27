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
from typing import Dict, Optional, Tuple

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
        self._ohlcv: Dict[str, DatabaseManager] = {}

    # ── Accessors ─────────────────────────────────────────────────────────────

    @property
    def global_db(self) -> DatabaseManager:
        """Manager for the shared (regime/news/accounts/settings/backtest) DB."""
        if not split_done():
            return _legacy_db
        if self._global is None:
            self._global = DatabaseManager(GLOBAL_DB_PATH)
        return self._global

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

        Pre-split: returns the legacy combined DB regardless of arguments —
        callers can pass anything (or nothing) and the result is the same.

        Post-split: caller must supply either the (terminal, broker, id) tuple
        or an `account_id`. The latter is resolved against the accounts table
        in `global_db`. Implementation of the account_id lookup is deferred to
        R1b once at least one caller actually needs it.
        """
        if not split_done():
            return _legacy_db

        if not (terminal and broker and broker_account_id):
            # R1b will implement the account_id → tuple lookup via global_db.
            raise NotImplementedError(
                "account_db(account_id=...) lookup is pending R1b. "
                "For now, pass terminal+broker+broker_account_id explicitly."
            )

        key: AccountKey = (terminal, broker, broker_account_id)
        if key not in self._accounts:
            self._accounts[key] = DatabaseManager(per_account_path(*key))
        return self._accounts[key]

    def ohlcv_db(self, broker: str) -> DatabaseManager:
        """Per-exchange OHLCV cache manager."""
        if not split_done():
            return _legacy_db
        if broker not in self._ohlcv:
            self._ohlcv[broker] = DatabaseManager(ohlcv_path(broker))
        return self._ohlcv[broker]

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


# Module-level singleton
db_router = DbRouter()
