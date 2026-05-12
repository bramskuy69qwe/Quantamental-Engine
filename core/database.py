"""
Async SQLite persistence layer (aiosqlite).

Tables:
  account_snapshots  – written on every WS ACCOUNT_UPDATE / REST refresh
  pre_trade_log      – every risk-calculator run (replaces pre_trade_log.csv)
  position_changes   – snapshot of all open positions on each refresh
  execution_log      – filled trades (manual via UI)
  trade_history      – closed trades (manual via UI)

Module-level singleton:
    from core.database import db
    await db.initialize()          # call once in lifespan startup
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

import config

from core.db_snapshots import SnapshotsMixin
from core.db_trades    import TradesMixin
from core.db_exchange  import ExchangeMixin
from core.db_analytics import AnalyticsMixin
from core.db_equity    import EquityMixin
from core.db_settings  import SettingsMixin
from core.db_ohlcv     import OhlcvMixin
from core.db_backtest  import BacktestMixin
from core.db_models    import ModelsMixin
from core.db_regime    import RegimeMixin
from core.db_news      import NewsMixin
from core.db_orders    import OrdersMixin

log = logging.getLogger("database")


_CREATE_STATEMENTS = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS account_snapshots (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_ts          TEXT    NOT NULL,
    total_equity         REAL    NOT NULL,
    balance_usdt         REAL    NOT NULL DEFAULT 0,
    available_margin     REAL    NOT NULL DEFAULT 0,
    total_unrealized     REAL    NOT NULL DEFAULT 0,
    total_realized       REAL    NOT NULL DEFAULT 0,
    total_position_value REAL    NOT NULL DEFAULT 0,
    total_margin_used    REAL    NOT NULL DEFAULT 0,
    total_margin_ratio   REAL    NOT NULL DEFAULT 0,
    daily_pnl            REAL    NOT NULL DEFAULT 0,
    daily_pnl_percent    REAL    NOT NULL DEFAULT 0,
    bod_equity           REAL    NOT NULL DEFAULT 0,
    sow_equity           REAL    NOT NULL DEFAULT 0,
    max_total_equity     REAL    NOT NULL DEFAULT 0,
    min_total_equity     REAL    NOT NULL DEFAULT 0,
    total_exposure       REAL    NOT NULL DEFAULT 0,
    drawdown             REAL    NOT NULL DEFAULT 0,
    total_weekly_pnl     REAL    NOT NULL DEFAULT 0,
    weekly_pnl_state     TEXT    NOT NULL DEFAULT 'ok',
    dd_state             TEXT    NOT NULL DEFAULT 'ok',
    open_positions       INTEGER NOT NULL DEFAULT 0,
    trigger_channel      TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON account_snapshots (snapshot_ts DESC);

CREATE TABLE IF NOT EXISTS pre_trade_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT NOT NULL,
    ticker            TEXT NOT NULL,
    average           REAL NOT NULL DEFAULT 0,
    side              TEXT NOT NULL DEFAULT '',
    one_percent_depth REAL NOT NULL DEFAULT 0,
    individual_risk   REAL NOT NULL DEFAULT 0,
    tp_price          REAL NOT NULL DEFAULT 0,
    tp_amount_pct     REAL NOT NULL DEFAULT 0,
    tp_usdt           REAL NOT NULL DEFAULT 0,
    sl_price          REAL NOT NULL DEFAULT 0,
    sl_amount_pct     REAL NOT NULL DEFAULT 0,
    sl_usdt           REAL NOT NULL DEFAULT 0,
    model_name        TEXT NOT NULL DEFAULT '',
    model_desc        TEXT NOT NULL DEFAULT '',
    risk_usdt         REAL NOT NULL DEFAULT 0,
    atr_c             TEXT NOT NULL DEFAULT '',
    atr_category      TEXT NOT NULL DEFAULT '',
    est_slippage      REAL NOT NULL DEFAULT 0,
    effective_entry   REAL NOT NULL DEFAULT 0,
    size              REAL NOT NULL DEFAULT 0,
    notional          REAL NOT NULL DEFAULT 0,
    est_profit        REAL NOT NULL DEFAULT 0,
    est_loss          REAL NOT NULL DEFAULT 0,
    est_r             REAL NOT NULL DEFAULT 0,
    est_exposure      REAL NOT NULL DEFAULT 0,
    eligible          INTEGER NOT NULL DEFAULT 0,
    notes             TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_pretrade_ts     ON pre_trade_log (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_pretrade_ticker ON pre_trade_log (ticker);

CREATE TABLE IF NOT EXISTS position_changes (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_ts            TEXT NOT NULL,
    ticker                 TEXT NOT NULL,
    direction              TEXT NOT NULL DEFAULT '',
    contract_amount        REAL NOT NULL DEFAULT 0,
    average                REAL NOT NULL DEFAULT 0,
    fair_price             REAL NOT NULL DEFAULT 0,
    position_value_usdt    REAL NOT NULL DEFAULT 0,
    individual_unrealized  REAL NOT NULL DEFAULT 0,
    individual_margin_used REAL NOT NULL DEFAULT 0,
    sector                 TEXT NOT NULL DEFAULT '',
    trigger_channel        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_pos_ts     ON position_changes (snapshot_ts DESC);
CREATE INDEX IF NOT EXISTS idx_pos_ticker ON position_changes (ticker, snapshot_ts DESC);

CREATE TABLE IF NOT EXISTS execution_log (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_timestamp          TEXT NOT NULL,
    ticker                   TEXT NOT NULL,
    side                     TEXT NOT NULL DEFAULT '',
    entry_price_actual       REAL NOT NULL DEFAULT 0,
    size_filled              REAL NOT NULL DEFAULT 0,
    slippage                 REAL NOT NULL DEFAULT 0,
    order_type               TEXT NOT NULL DEFAULT 'limit',
    maker_fee                REAL NOT NULL DEFAULT 0,
    taker_fee                REAL NOT NULL DEFAULT 0,
    latency_snapshot         REAL NOT NULL DEFAULT 0,
    orderbook_depth_snapshot TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_exec_ts ON execution_log (entry_timestamp DESC);

CREATE TABLE IF NOT EXISTS trade_history (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    exit_timestamp        TEXT NOT NULL,
    ticker                TEXT NOT NULL,
    direction             TEXT NOT NULL DEFAULT '',
    entry_price           REAL NOT NULL DEFAULT 0,
    exit_price            REAL NOT NULL DEFAULT 0,
    individual_realized   REAL NOT NULL DEFAULT 0,
    individual_realized_r REAL NOT NULL DEFAULT 0,
    total_funding_fees    REAL NOT NULL DEFAULT 0,
    total_fees            REAL NOT NULL DEFAULT 0,
    slippage_exit         REAL NOT NULL DEFAULT 0,
    holding_time          TEXT NOT NULL DEFAULT '',
    notes                 TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_history_ts ON trade_history (exit_timestamp DESC);

CREATE TABLE IF NOT EXISTS position_history_notes (
    trade_key TEXT PRIMARY KEY,
    notes     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS exchange_history (
    trade_key   TEXT    PRIMARY KEY,
    time        INTEGER NOT NULL,
    symbol      TEXT    NOT NULL DEFAULT '',
    income_type TEXT    NOT NULL DEFAULT '',
    income      REAL    NOT NULL DEFAULT 0.0,
    direction   TEXT    NOT NULL DEFAULT '',
    entry_price REAL    NOT NULL DEFAULT 0.0,
    exit_price  REAL    NOT NULL DEFAULT 0.0,
    qty         REAL    NOT NULL DEFAULT 0.0,
    notional    REAL    NOT NULL DEFAULT 0.0,
    open_time   INTEGER NOT NULL DEFAULT 0,
    fee         REAL    NOT NULL DEFAULT 0.0,
    asset       TEXT    NOT NULL DEFAULT '',
    mfe         REAL    NOT NULL DEFAULT 0.0,
    mae         REAL    NOT NULL DEFAULT 0.0,
    backfill_completed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_exchist_time   ON exchange_history(time DESC);
CREATE INDEX IF NOT EXISTS idx_exchist_symbol ON exchange_history(symbol);

CREATE TABLE IF NOT EXISTS equity_cashflow (
    ts_ms   INTEGER PRIMARY KEY,
    amount  REAL    NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_cashflow_ts ON equity_cashflow (ts_ms DESC);

CREATE TABLE IF NOT EXISTS accounts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL,
    exchange          TEXT    NOT NULL DEFAULT 'binance',
    market_type       TEXT    NOT NULL DEFAULT 'future',
    api_key_enc       TEXT    NOT NULL DEFAULT '',
    api_secret_enc    TEXT    NOT NULL DEFAULT '',
    is_active         INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    broker_account_id TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS account_params (
    account_id  INTEGER NOT NULL,
    key         TEXT    NOT NULL,
    value       REAL    NOT NULL,
    PRIMARY KEY (account_id, key),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS connections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    provider    TEXT    NOT NULL UNIQUE,
    label       TEXT    NOT NULL,
    api_key_enc TEXT    NOT NULL DEFAULT '',
    extra_enc   TEXT    NOT NULL DEFAULT '',
    is_active   INTEGER NOT NULL DEFAULT 1,
    key_version INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── Backtesting ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ohlcv_cache (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol     TEXT    NOT NULL,
    timeframe  TEXT    NOT NULL,
    ts_ms      INTEGER NOT NULL,
    open       REAL    NOT NULL DEFAULT 0,
    high       REAL    NOT NULL DEFAULT 0,
    low        REAL    NOT NULL DEFAULT 0,
    close      REAL    NOT NULL DEFAULT 0,
    volume     REAL    NOT NULL DEFAULT 0,
    UNIQUE(symbol, timeframe, ts_ms)
);
CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_tf_ts ON ohlcv_cache (symbol, timeframe, ts_ms ASC);

CREATE TABLE IF NOT EXISTS backtest_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    name        TEXT    NOT NULL DEFAULT '',
    type        TEXT    NOT NULL DEFAULT 'macro',
    status      TEXT    NOT NULL DEFAULT 'pending',
    date_from   TEXT    NOT NULL DEFAULT '',
    date_to     TEXT    NOT NULL DEFAULT '',
    config_json TEXT    NOT NULL DEFAULT '{}',
    summary_json TEXT   NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS backtest_trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   INTEGER NOT NULL REFERENCES backtest_sessions(id) ON DELETE CASCADE,
    symbol       TEXT    NOT NULL DEFAULT '',
    side         TEXT    NOT NULL DEFAULT '',
    entry_dt     TEXT    NOT NULL DEFAULT '',
    exit_dt      TEXT    NOT NULL DEFAULT '',
    entry_price  REAL    NOT NULL DEFAULT 0,
    exit_price   REAL    NOT NULL DEFAULT 0,
    size_usdt    REAL    NOT NULL DEFAULT 0,
    r_multiple   REAL    NOT NULL DEFAULT 0,
    pnl_usdt     REAL    NOT NULL DEFAULT 0,
    regime_label TEXT    NOT NULL DEFAULT '',
    exit_reason  TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_bt_trades_session ON backtest_trades (session_id);

CREATE TABLE IF NOT EXISTS backtest_equity (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES backtest_sessions(id) ON DELETE CASCADE,
    dt         TEXT    NOT NULL DEFAULT '',
    equity     REAL    NOT NULL DEFAULT 0,
    drawdown   REAL    NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_bt_equity_session ON backtest_equity (session_id, dt ASC);

CREATE TABLE IF NOT EXISTS potential_models (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    name        TEXT    NOT NULL DEFAULT '',
    type        TEXT    NOT NULL DEFAULT 'both',
    description TEXT    NOT NULL DEFAULT '',
    config_json TEXT    NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS regime_signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_name TEXT    NOT NULL,
    date        TEXT    NOT NULL,
    value       REAL    NOT NULL,
    source      TEXT    NOT NULL DEFAULT '',
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(signal_name, date)
);
CREATE INDEX IF NOT EXISTS idx_regime_sig_name_date ON regime_signals (signal_name, date ASC);

CREATE TABLE IF NOT EXISTS regime_labels (
    date         TEXT    PRIMARY KEY,
    label        TEXT    NOT NULL,
    mode         TEXT    NOT NULL DEFAULT 'full',
    signals_json TEXT    NOT NULL DEFAULT '{}',
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS news_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT    NOT NULL,
    external_id  TEXT    NOT NULL,
    headline     TEXT    NOT NULL,
    summary      TEXT    NOT NULL DEFAULT '',
    url          TEXT    NOT NULL DEFAULT '',
    image_url    TEXT    NOT NULL DEFAULT '',
    category     TEXT    NOT NULL DEFAULT '',
    tickers      TEXT    NOT NULL DEFAULT '',
    published_at TEXT    NOT NULL,
    fetched_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news_items (published_at DESC);

CREATE TABLE IF NOT EXISTS economic_calendar (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_time   TEXT    NOT NULL,
    country      TEXT    NOT NULL,
    event_name   TEXT    NOT NULL,
    impact       TEXT    NOT NULL DEFAULT '',
    currency     TEXT    NOT NULL DEFAULT '',
    unit         TEXT    NOT NULL DEFAULT '',
    previous     REAL,
    estimate     REAL,
    actual       REAL,
    fetched_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(event_time, country, event_name)
);
CREATE INDEX IF NOT EXISTS idx_calendar_time ON economic_calendar (event_time ASC);

-- ── v2.2.2: Order Center tables ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS orders (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id          INTEGER NOT NULL,
    exchange_order_id   TEXT,
    terminal_order_id   TEXT    NOT NULL DEFAULT '',
    client_order_id     TEXT    NOT NULL DEFAULT '',
    symbol              TEXT    NOT NULL,
    side                TEXT    NOT NULL,
    order_type          TEXT    NOT NULL DEFAULT '',
    status              TEXT    NOT NULL DEFAULT 'new',
    price               REAL    NOT NULL DEFAULT 0,
    stop_price          REAL    NOT NULL DEFAULT 0,
    quantity            REAL    NOT NULL DEFAULT 0,
    filled_qty          REAL    NOT NULL DEFAULT 0,
    avg_fill_price      REAL    NOT NULL DEFAULT 0,
    reduce_only         INTEGER NOT NULL DEFAULT 0,
    time_in_force       TEXT    NOT NULL DEFAULT '',
    position_side       TEXT    NOT NULL DEFAULT '',
    exchange_position_id TEXT   NOT NULL DEFAULT '',
    terminal_position_id TEXT   NOT NULL DEFAULT '',
    source              TEXT    NOT NULL DEFAULT '',
    created_at_ms       INTEGER NOT NULL DEFAULT 0,
    updated_at_ms       INTEGER NOT NULL DEFAULT 0,
    last_seen_ms        INTEGER NOT NULL DEFAULT 0,
    UNIQUE(account_id, exchange_order_id)
);
CREATE INDEX IF NOT EXISTS idx_orders_terminal ON orders (terminal_order_id);
CREATE INDEX IF NOT EXISTS idx_orders_status   ON orders (account_id, status, updated_at_ms DESC);
CREATE INDEX IF NOT EXISTS idx_orders_symbol   ON orders (symbol, updated_at_ms DESC);
CREATE INDEX IF NOT EXISTS idx_orders_tpsl     ON orders (account_id, symbol, position_side, order_type, status);

CREATE TABLE IF NOT EXISTS fills (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id           INTEGER NOT NULL,
    exchange_fill_id     TEXT,
    terminal_fill_id     TEXT    NOT NULL DEFAULT '',
    exchange_order_id    TEXT    NOT NULL DEFAULT '',
    symbol               TEXT    NOT NULL,
    side                 TEXT    NOT NULL,
    direction            TEXT    NOT NULL DEFAULT '',
    price                REAL    NOT NULL DEFAULT 0,
    quantity             REAL    NOT NULL DEFAULT 0,
    fee                  REAL    NOT NULL DEFAULT 0,
    fee_asset            TEXT    NOT NULL DEFAULT 'USDT',
    exchange_position_id TEXT    NOT NULL DEFAULT '',
    terminal_position_id TEXT    NOT NULL DEFAULT '',
    is_close             INTEGER NOT NULL DEFAULT 0,
    realized_pnl         REAL    NOT NULL DEFAULT 0,
    role                 TEXT    NOT NULL DEFAULT '',
    source               TEXT    NOT NULL DEFAULT '',
    timestamp_ms         INTEGER NOT NULL DEFAULT 0,
    UNIQUE(account_id, exchange_fill_id)
);
CREATE INDEX IF NOT EXISTS idx_fills_terminal  ON fills (terminal_fill_id);
CREATE INDEX IF NOT EXISTS idx_fills_order     ON fills (exchange_order_id);
CREATE INDEX IF NOT EXISTS idx_fills_position  ON fills (terminal_position_id, is_close);
CREATE INDEX IF NOT EXISTS idx_fills_ts        ON fills (account_id, timestamp_ms DESC);

CREATE TABLE IF NOT EXISTS closed_positions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id           INTEGER NOT NULL,
    exchange_position_id TEXT    NOT NULL DEFAULT '',
    terminal_position_id TEXT    NOT NULL DEFAULT '',
    symbol               TEXT    NOT NULL,
    direction            TEXT    NOT NULL DEFAULT '',
    quantity             REAL    NOT NULL DEFAULT 0,
    entry_price          REAL    NOT NULL DEFAULT 0,
    exit_price           REAL    NOT NULL DEFAULT 0,
    entry_time_ms        INTEGER NOT NULL DEFAULT 0,
    exit_time_ms         INTEGER NOT NULL DEFAULT 0,
    realized_pnl         REAL    NOT NULL DEFAULT 0,
    total_fees           REAL    NOT NULL DEFAULT 0,
    net_pnl              REAL    NOT NULL DEFAULT 0,
    funding_fees         REAL    NOT NULL DEFAULT 0,
    mfe                  REAL    NOT NULL DEFAULT 0,
    mae                  REAL    NOT NULL DEFAULT 0,
    backfill_completed   INTEGER NOT NULL DEFAULT 0,
    hold_time_ms         INTEGER NOT NULL DEFAULT 0,
    exit_reason          TEXT    NOT NULL DEFAULT '',
    model_name           TEXT    NOT NULL DEFAULT '',
    notes                TEXT    NOT NULL DEFAULT '',
    shortfall_entry      REAL    NOT NULL DEFAULT 0,
    shortfall_exit       REAL    NOT NULL DEFAULT 0,
    source               TEXT    NOT NULL DEFAULT '',
    UNIQUE(account_id, terminal_position_id, exit_time_ms)
);
CREATE INDEX IF NOT EXISTS idx_closed_pos_ts     ON closed_positions (account_id, exit_time_ms DESC);
CREATE INDEX IF NOT EXISTS idx_closed_pos_symbol ON closed_positions (symbol, exit_time_ms DESC);
"""


class DatabaseManager(
    SnapshotsMixin,
    TradesMixin,
    ExchangeMixin,
    AnalyticsMixin,
    EquityMixin,
    SettingsMixin,
    OhlcvMixin,
    BacktestMixin,
    ModelsMixin,
    RegimeMixin,
    NewsMixin,
    OrdersMixin,
):
    """Async SQLite manager. Keep open for app lifetime; use WAL for concurrency.

    Multiple instances are now supported — pass a custom `path` to point at a
    different SQLite file. Used by `core.db_router` to route per-account vs
    global vs OHLCV-cache traffic to separate files.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self._conn: Optional[aiosqlite.Connection] = None
        self.path: str = path if path is not None else config.DB_PATH

    async def initialize(self) -> None:
        """Create DB file + all tables (idempotent). Call once in lifespan startup."""
        import os
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        for stmt in _CREATE_STATEMENTS.strip().split(";"):
            stmt = stmt.strip()
            if stmt and not stmt.upper().startswith("PRAGMA"):
                await self._conn.execute(stmt)
        await self._conn.commit()

        # Schema migrations — idempotent column additions (safe to retry on every start)
        import sqlite3 as _sqlite3
        for migration in [
            "ALTER TABLE pre_trade_log ADD COLUMN notes TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE exchange_history ADD COLUMN mfe REAL NOT NULL DEFAULT 0.0",
            "ALTER TABLE exchange_history ADD COLUMN mae REAL NOT NULL DEFAULT 0.0",
            # v1.3: multi-account support — account_id on all transactional tables
            "ALTER TABLE account_snapshots ADD COLUMN account_id INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE position_changes  ADD COLUMN account_id INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE pre_trade_log     ADD COLUMN account_id INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE execution_log     ADD COLUMN account_id INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE trade_history     ADD COLUMN account_id INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE exchange_history  ADD COLUMN account_id INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE equity_cashflow   ADD COLUMN account_id INTEGER NOT NULL DEFAULT 1",
            # v2.1: broker account identity (Binance UID) for Quantower reconciliation
            "ALTER TABLE accounts ADD COLUMN broker_account_id TEXT",
            # v2.1: fill source for debugging (manual UI, quantower, binance)
            "ALTER TABLE execution_log ADD COLUMN source_terminal TEXT NOT NULL DEFAULT 'manual'",
            # v2.2: per-account fees, environment, key versioning
            "ALTER TABLE accounts ADD COLUMN maker_fee REAL NOT NULL DEFAULT 0.0002",
            "ALTER TABLE accounts ADD COLUMN taker_fee REAL NOT NULL DEFAULT 0.0005",
            "ALTER TABLE accounts ADD COLUMN environment TEXT NOT NULL DEFAULT 'live'",
            "ALTER TABLE accounts ADD COLUMN key_version INTEGER NOT NULL DEFAULT 1",
            # AN-1: backfill_completed replaces mfe=0/mae=0 sentinel
            "ALTER TABLE exchange_history ADD COLUMN backfill_completed INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE closed_positions ADD COLUMN backfill_completed INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                await self._conn.execute(migration)
                await self._conn.commit()
            except _sqlite3.OperationalError as e:
                if "duplicate column name" in str(e).lower():
                    pass  # expected on repeat startup — column already exists
                else:
                    log.error("Schema migration failed (non-duplicate): %r | sql: %s", e, migration)
                    raise

        # ── One-shot data migrations (idempotent DELETE/UPDATE — safe to re-run) ─
        await self._conn.execute(
            "DELETE FROM regime_signals WHERE signal_name = 'btc_dominance'"
        )
        await self._conn.commit()

        # AN-1: mark already-computed rows so they aren't reprocessed on first
        # startup after migration.  Idempotent — rows already marked 1 stay 1.
        # Marks rows where either mfe or mae is nonzero (computation definitely
        # ran).  Rows where both are exactly 0.0 stay pending — the reconciler
        # will reprocess them once and set backfill_completed=1.
        await self._conn.execute(
            "UPDATE exchange_history SET backfill_completed=1"
            " WHERE backfill_completed=0 AND (mfe != 0 OR mae != 0)"
        )
        await self._conn.execute(
            "UPDATE closed_positions SET backfill_completed=1"
            " WHERE backfill_completed=0 AND (mfe != 0 OR mae != 0)"
        )
        await self._conn.commit()

        # ── account_id indexes (idempotent) ───────────────────────────────────
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_snapshots_account ON account_snapshots (account_id, snapshot_ts DESC)",
            "CREATE INDEX IF NOT EXISTS idx_pos_account       ON position_changes  (account_id, snapshot_ts DESC)",
            "CREATE INDEX IF NOT EXISTS idx_pretrade_account  ON pre_trade_log     (account_id, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_exec_account      ON execution_log     (account_id, entry_timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_history_account   ON trade_history     (account_id, exit_timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_exchist_account   ON exchange_history  (account_id, time DESC)",
            "CREATE INDEX IF NOT EXISTS idx_cashflow_account  ON equity_cashflow   (account_id, ts_ms DESC)",
        ]:
            try:
                await self._conn.execute(idx_sql)
            except _sqlite3.OperationalError:
                pass
        await self._conn.commit()

        # Seed default settings rows
        for key, val in [("active_account_id", "1"), ("active_platform", "standalone")]:
            await self._conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, val)
            )
        await self._conn.commit()

        # ── Migrations log ────────────────────────────────────────────────────
        # Tracks one-time data mutations so they NEVER re-run across restarts.
        await self._conn.execute(
            "CREATE TABLE IF NOT EXISTS migrations_log "
            "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        await self._conn.commit()

        async def _run_once(name: str, sql: str) -> None:
            async with self._conn.execute(
                "SELECT 1 FROM migrations_log WHERE name=?", (name,)
            ) as cur:
                if await cur.fetchone():
                    return  # already applied — skip
            await self._conn.execute(sql)
            await self._conn.execute(
                "INSERT INTO migrations_log VALUES (?,?)",
                (name, datetime.now(timezone.utc).isoformat()),
            )
            await self._conn.commit()
            log.info(f"Data migration applied: {name}")

        # v1: reset MFE/MAE computed with buggy open_time
        await _run_once(
            "reset_mfe_mae_buggy_open_time_v1",
            "UPDATE exchange_history SET mfe=0, mae=0 WHERE mfe!=0 OR mae!=0",
        )
        # v2: reset MFE/MAE computed with coarse 1m candles.
        await _run_once(
            "reset_mfe_mae_multi_resolution_v2",
            "UPDATE exchange_history SET mfe=0, mae=0",
        )
        # v3: reset short trades (<10 min) computed with 1m candles.
        await _run_once(
            "reset_mfe_mae_agg_trades_short_v3",
            "UPDATE exchange_history SET mfe=0, mae=0 "
            "WHERE open_time > 0 AND (time - open_time) < 600000",
        )
        # v4: reset all — MFE/MAE formula changed from net to gross (no fee deduction).
        await _run_once(
            "reset_mfe_mae_gross_formula_v4",
            "UPDATE exchange_history SET mfe=0, mae=0",
        )
        # v5: reset fee — now combined total (entry + funding + exit) instead of exit only.
        await _run_once(
            "reset_fee_combined_total_v5",
            "UPDATE exchange_history SET fee=0",
        )
        # AN-2: delete corrupted qt:-prefixed legacy Quantower rows.
        # All 148 rows confirmed mathematically impossible (MAE>245%, hold=7948d, etc.).
        # Archived to docs/archive/quantower_legacy_*_2026-05-12.csv before deletion.
        await _run_once(
            "an2_delete_qt_exchange_history_v1",
            "DELETE FROM exchange_history WHERE trade_key LIKE 'qt:%'",
        )
        await _run_once(
            "an2_delete_qt_fills_v1",
            "DELETE FROM fills WHERE exchange_fill_id LIKE 'qt:%'",
        )

        # v1.3-seed: import .env credentials as Account 1 if no accounts exist yet
        async with self._conn.execute("SELECT COUNT(*) FROM accounts") as cur:
            acct_count = (await cur.fetchone())[0]
        if acct_count == 0 and (config.BINANCE_API_KEY or config.BINANCE_API_SECRET):
            try:
                from core.crypto import encrypt as _enc
                key_enc = _enc(config.BINANCE_API_KEY)
                sec_enc = _enc(config.BINANCE_API_SECRET)
            except (ValueError, OSError, RuntimeError):
                key_enc = ""
                sec_enc = ""
            await self._conn.execute(
                "INSERT INTO accounts (name, exchange, market_type, api_key_enc, api_secret_enc, is_active)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("Account 1 (Binance Futures)", "binance", "future", key_enc, sec_enc, 1),
            )
            await self._conn.commit()
            log.info("Seeded Account 1 from .env credentials")

        # ── v2.2 data migrations ─────────────────────────────────────────────
        await self._migrate_params_json_to_db()
        await self._migrate_env_connections()

        log.info(f"SQLite initialized at {config.DB_PATH}")

    async def _migrate_params_json_to_db(self) -> None:
        """Migrate data/params.json → account_params table (one-time)."""
        import json
        import os

        params_count = await self.count_account_params()
        if params_count > 0:
            return  # already migrated

        params_path = os.path.join(config.DATA_DIR, "params.json")
        if not os.path.isfile(params_path):
            return  # no params.json to migrate

        try:
            with open(params_path, "r") as f:
                params = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.error("Failed to read params.json for migration: %s", e)
            return

        # Get all account IDs — every account gets a copy of the params
        async with self._conn.execute("SELECT id FROM accounts") as cur:
            account_ids = [r["id"] for r in await cur.fetchall()]

        if not account_ids:
            return

        for acct_id in account_ids:
            for key, value in params.items():
                await self._conn.execute(
                    "INSERT OR IGNORE INTO account_params (account_id, key, value)"
                    " VALUES (?, ?, ?)",
                    (acct_id, key, float(value)),
                )
        await self._conn.commit()

        # Rename original as backup
        migrated_path = params_path + ".migrated"
        try:
            os.rename(params_path, migrated_path)
        except OSError:
            pass  # not critical if rename fails

        log.info("Migrated params.json → account_params for %d account(s)", len(account_ids))

    async def _migrate_env_connections(self) -> None:
        """Seed connections table from .env keys (one-time)."""
        conn_count = await self.count_connections()
        if conn_count > 0:
            return  # already seeded

        from core.crypto import encrypt

        providers = [
            ("fred",      "Federal Reserve (FRED)",    config.FRED_API_KEY),
            ("finnhub",   "Finnhub",                   config.FINNHUB_API_KEY),
            ("coingecko", "CoinGecko",                 getattr(config, "COINGECKO_API_KEY", "")),
        ]

        seeded = 0
        for provider, label, raw_key in providers:
            if not raw_key:
                continue
            try:
                enc = encrypt(raw_key)
            except Exception:
                enc = ""
            await self._conn.execute(
                "INSERT OR IGNORE INTO connections (provider, label, api_key_enc)"
                " VALUES (?, ?, ?)",
                (provider, label, enc),
            )
            seeded += 1

        if seeded:
            await self._conn.commit()
            log.info("Seeded %d connection(s) from .env", seeded)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None


# Module-level singleton — all callers use `from core.database import db`.
db = DatabaseManager()
