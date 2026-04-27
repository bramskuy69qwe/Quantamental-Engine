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
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import aiosqlite

import config

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
    mae         REAL    NOT NULL DEFAULT 0.0
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
"""


class DatabaseManager:
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
            except Exception:
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
        #     (was grabbing the oldest fill across ALL prior legs, not just the current leg)
        await _run_once(
            "reset_mfe_mae_buggy_open_time_v1",
            "UPDATE exchange_history SET mfe=0, mae=0 WHERE mfe!=0 OR mae!=0",
        )
        # v2: reset MFE/MAE computed with coarse 1m candles.
        #     Now using multi-resolution fetch (1m / hybrid) for accuracy.
        await _run_once(
            "reset_mfe_mae_multi_resolution_v2",
            "UPDATE exchange_history SET mfe=0, mae=0",
        )
        # v3: reset short trades (<10 min) computed with 1m candles.
        #     Now using aggTrades for exact tick-level price accuracy on short positions.
        await _run_once(
            "reset_mfe_mae_agg_trades_short_v3",
            "UPDATE exchange_history SET mfe=0, mae=0 "
            "WHERE open_time > 0 AND (time - open_time) < 600000",
        )
        # v4: reset all — MFE/MAE formula changed from net (after fee) to gross
        #     (no fee deduction) so values are directly comparable to the gross
        #     Realized PnL column. MFE is now always >= gross PnL by definition.
        await _run_once(
            "reset_mfe_mae_gross_formula_v4",
            "UPDATE exchange_history SET mfe=0, mae=0",
        )
        # v5: reset fee — now combined total (entry commission + funding fees + exit
        #     commission) instead of exit commission only.  Rows re-populate on next
        #     fetch_exchange_trade_history() call.
        await _run_once(
            "reset_fee_combined_total_v5",
            "UPDATE exchange_history SET fee=0",
        )

        # v1.3-seed: import .env credentials as Account 1 if no accounts exist yet
        async with self._conn.execute("SELECT COUNT(*) FROM accounts") as cur:
            acct_count = (await cur.fetchone())[0]
        if acct_count == 0 and (config.BINANCE_API_KEY or config.BINANCE_API_SECRET):
            try:
                from core.crypto import encrypt as _enc
                key_enc = _enc(config.BINANCE_API_KEY)
                sec_enc = _enc(config.BINANCE_API_SECRET)
            except Exception:
                # If ENV_MASTER_KEY not set yet, store empty (user must re-enter)
                key_enc = ""
                sec_enc = ""
            await self._conn.execute(
                "INSERT INTO accounts (name, exchange, market_type, api_key_enc, api_secret_enc, is_active)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("Account 1 (Binance Futures)", "binance", "future", key_enc, sec_enc, 1),
            )
            await self._conn.commit()
            log.info("Seeded Account 1 from .env credentials")

        log.info(f"SQLite initialized at {config.DB_PATH}")

    # ── Crash recovery ────────────────────────────────────────────────────────

    async def get_last_account_state(self, account_id: int = 1) -> Optional[Dict[str, Any]]:
        """Return the most recent account_snapshots row for account_id, or None."""
        async with self._conn.execute(
            "SELECT * FROM account_snapshots WHERE account_id=? ORDER BY id DESC LIMIT 1",
            (account_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    # ── Inserts ───────────────────────────────────────────────────────────────

    async def insert_account_snapshot(self, data: Dict[str, Any]) -> None:
        try:
            await self._conn.execute(
                """INSERT INTO account_snapshots (
                    account_id, snapshot_ts, total_equity, balance_usdt, available_margin,
                    total_unrealized, total_realized, total_position_value,
                    total_margin_used, total_margin_ratio, daily_pnl, daily_pnl_percent,
                    bod_equity, sow_equity, max_total_equity, min_total_equity,
                    total_exposure, drawdown, total_weekly_pnl,
                    weekly_pnl_state, dd_state, open_positions, trigger_channel
                ) VALUES (
                    :account_id, :snapshot_ts, :total_equity, :balance_usdt, :available_margin,
                    :total_unrealized, :total_realized, :total_position_value,
                    :total_margin_used, :total_margin_ratio, :daily_pnl, :daily_pnl_percent,
                    :bod_equity, :sow_equity, :max_total_equity, :min_total_equity,
                    :total_exposure, :drawdown, :total_weekly_pnl,
                    :weekly_pnl_state, :dd_state, :open_positions, :trigger_channel
                )""",
                {"account_id": data.get("account_id", 1), **data},
            )
            await self._conn.commit()
        except Exception as exc:
            log.error("insert_account_snapshot failed: %r", exc)
            try:
                await self._conn.rollback()
            except Exception:
                pass
            raise

    async def insert_position_changes(
        self, positions: List[Dict[str, Any]], trigger: str, account_id: int = 1
    ) -> None:
        if not positions:
            return
        ts = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                account_id,
                ts,
                p.get("ticker", ""),
                p.get("direction", ""),
                p.get("contract_amount", 0.0),
                p.get("average", 0.0),
                p.get("fair_price", 0.0),
                p.get("position_value_usdt", 0.0),
                p.get("individual_unrealized", 0.0),
                p.get("individual_margin_used", 0.0),
                p.get("sector", ""),
                trigger,
            )
            for p in positions
        ]
        try:
            await self._conn.executemany(
                """INSERT INTO position_changes (
                    account_id, snapshot_ts, ticker, direction, contract_amount, average,
                    fair_price, position_value_usdt, individual_unrealized,
                    individual_margin_used, sector, trigger_channel
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            await self._conn.commit()
        except Exception as exc:
            log.error("insert_position_changes failed: %r", exc)
            try:
                await self._conn.rollback()
            except Exception:
                pass
            raise

    async def insert_pre_trade_log(self, data: Dict[str, Any]) -> None:
        try:
            await self._conn.execute(
                """INSERT INTO pre_trade_log (
                    account_id, timestamp, ticker, average, side, one_percent_depth, individual_risk,
                    tp_price, tp_amount_pct, tp_usdt, sl_price, sl_amount_pct, sl_usdt,
                    model_name, model_desc, risk_usdt, atr_c, atr_category,
                    est_slippage, effective_entry, size, notional,
                    est_profit, est_loss, est_r, est_exposure, eligible
                ) VALUES (
                    :account_id, :timestamp, :ticker, :average, :side, :one_percent_depth, :individual_risk,
                    :tp_price, :tp_amount_pct, :tp_usdt, :sl_price, :sl_amount_pct, :sl_usdt,
                    :model_name, :model_desc, :risk_usdt, :atr_c, :atr_category,
                    :est_slippage, :effective_entry, :size, :notional,
                    :est_profit, :est_loss, :est_r, :est_exposure, :eligible
                )""",
                {
                    "account_id":        data.get("account_id", 1),
                    "timestamp":         data.get("timestamp", datetime.now(timezone.utc).isoformat()),
                    "ticker":            data.get("ticker", ""),
                    "average":           data.get("average", 0),
                    "side":              data.get("side", ""),
                    "one_percent_depth": data.get("one_percent_depth", 0),
                    "individual_risk":   data.get("individual_risk_pct", data.get("individual_risk", 0)),
                    "tp_price":          data.get("tp_price", 0),
                    "tp_amount_pct":     data.get("tp_amount_pct", 0),
                    "tp_usdt":           data.get("tp_usdt", 0),
                    "sl_price":          data.get("sl_price", 0),
                    "sl_amount_pct":     data.get("sl_amount_pct", 0),
                    "sl_usdt":           data.get("sl_usdt", 0),
                    "model_name":        data.get("model_name", ""),
                    "model_desc":        data.get("model_desc", ""),
                    "risk_usdt":         data.get("risk_usdt", 0),
                    "atr_c":             str(data.get("atr_c", "")),
                    "atr_category":      data.get("atr_category", ""),
                    "est_slippage":      data.get("est_slippage", 0),
                    "effective_entry":   data.get("effective_entry", 0),
                    "size":              data.get("size", 0),
                    "notional":          data.get("notional", 0),
                    "est_profit":        data.get("est_profit", 0),
                    "est_loss":          data.get("est_loss", 0),
                    "est_r":             data.get("est_r", 0),
                    "est_exposure":      data.get("est_exposure", 0),
                    "eligible":          1 if data.get("eligible") else 0,
                },
            )
            await self._conn.commit()
        except Exception as exc:
            log.error("insert_pre_trade_log failed: %r", exc)
            try:
                await self._conn.rollback()
            except Exception:
                pass
            raise

    async def insert_execution_log(self, data: Dict[str, Any]) -> None:
        try:
            await self._conn.execute(
                """INSERT INTO execution_log (
                    account_id, entry_timestamp, ticker, side, entry_price_actual, size_filled,
                    slippage, order_type, maker_fee, taker_fee,
                    latency_snapshot, orderbook_depth_snapshot
                ) VALUES (
                    :account_id, :entry_timestamp, :ticker, :side, :entry_price_actual, :size_filled,
                    :slippage, :order_type, :maker_fee, :taker_fee,
                    :latency_snapshot, :orderbook_depth_snapshot
                )""",
                {
                    "account_id":               data.get("account_id", 1),
                    "entry_timestamp":          data.get("entry_timestamp", datetime.now(timezone.utc).isoformat()),
                    "ticker":                   data.get("ticker", ""),
                    "side":                     data.get("side", ""),
                    "entry_price_actual":       data.get("entry_price_actual", 0),
                    "size_filled":              data.get("size_filled", 0),
                    "slippage":                 data.get("slippage", 0),
                    "order_type":               data.get("order_type", "limit"),
                    "maker_fee":                data.get("maker_fee", 0),
                    "taker_fee":                data.get("taker_fee", 0),
                    "latency_snapshot":         data.get("latency_snapshot", 0),
                    "orderbook_depth_snapshot": str(data.get("orderbook_depth_snapshot", "")),
                },
            )
            await self._conn.commit()
        except Exception as exc:
            log.error("insert_execution_log failed: %r", exc)
            try:
                await self._conn.rollback()
            except Exception:
                pass
            raise

    async def insert_trade_history(self, data: Dict[str, Any]) -> None:
        try:
            await self._conn.execute(
                """INSERT INTO trade_history (
                    account_id, exit_timestamp, ticker, direction, entry_price, exit_price,
                    individual_realized, individual_realized_r, total_funding_fees,
                    total_fees, slippage_exit, holding_time, notes
                ) VALUES (
                    :account_id, :exit_timestamp, :ticker, :direction, :entry_price, :exit_price,
                    :individual_realized, :individual_realized_r, :total_funding_fees,
                    :total_fees, :slippage_exit, :holding_time, :notes
                )""",
                {
                    "account_id":            data.get("account_id", 1),
                    "exit_timestamp":        data.get("exit_timestamp", datetime.now(timezone.utc).isoformat()),
                    "ticker":                data.get("ticker", ""),
                    "direction":             data.get("direction", ""),
                    "entry_price":           data.get("entry_price", 0),
                    "exit_price":            data.get("exit_price", 0),
                    "individual_realized":   data.get("individual_realized", 0),
                    "individual_realized_r": data.get("individual_realized_r", 0),
                    "total_funding_fees":    data.get("total_funding_fees", 0),
                    "total_fees":            data.get("total_fees", 0),
                    "slippage_exit":         data.get("slippage_exit", 0),
                    "holding_time":          str(data.get("holding_time", "")),
                    "notes":                 data.get("notes", ""),
                },
            )
            await self._conn.commit()
        except Exception as exc:
            log.error("insert_trade_history failed: %r", exc)
            try:
                await self._conn.rollback()
            except Exception:
                pass
            raise

    # ── Queries ───────────────────────────────────────────────────────────────

    async def get_recent_snapshots(self, minutes: int = 5, account_id: int = 1) -> List[Dict[str, Any]]:
        """Return account_snapshots rows from the last N minutes, oldest first."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=minutes)
        ).isoformat()
        async with self._conn.execute(
            "SELECT * FROM account_snapshots WHERE account_id=? AND snapshot_ts >= ? ORDER BY snapshot_ts ASC",
            (account_id, cutoff),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_all_pre_trade_log(self, days: int = 365, account_id: int = 1) -> List[Dict[str, Any]]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        async with self._conn.execute(
            "SELECT * FROM pre_trade_log WHERE account_id=? AND timestamp >= ? ORDER BY timestamp DESC",
            (account_id, cutoff),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_all_execution_log(self, days: int = 365, account_id: int = 1) -> List[Dict[str, Any]]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        async with self._conn.execute(
            "SELECT * FROM execution_log WHERE account_id=? AND entry_timestamp >= ? ORDER BY entry_timestamp DESC",
            (account_id, cutoff),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_all_trade_history(self, days: int = 365, account_id: int = 1) -> List[Dict[str, Any]]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        async with self._conn.execute(
            "SELECT * FROM trade_history WHERE account_id=? AND exit_timestamp >= ? ORDER BY exit_timestamp DESC",
            (account_id, cutoff),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # ── Paginated queries ──────────────────────────────────────────────────

    _PRE_TRADE_SORT_COLS = {
        "timestamp", "ticker", "side", "average", "sl_price", "tp_price",
        "atr_c", "size", "notional", "est_r", "eligible", "model_name",
    }
    _EXECUTION_SORT_COLS = {
        "entry_timestamp", "ticker", "side", "entry_price_actual",
        "size_filled", "slippage", "order_type", "maker_fee", "latency_snapshot",
    }
    _TRADE_HISTORY_SORT_COLS = {
        "exit_timestamp", "ticker", "direction", "entry_price", "exit_price",
        "individual_realized", "individual_realized_r", "total_funding_fees",
        "total_fees", "slippage_exit", "holding_time",
    }
    _EXCHANGE_HISTORY_SORT_COLS = {
        "time", "symbol", "income", "entry_price", "exit_price",
        "notional", "fee", "direction", "open_time", "qty", "mfe", "mae",
        "hold_ms",
    }

    async def _paginated_query(
        self,
        table: str,
        ts_col: str,
        allowed_sort: set,
        date_from: Optional[str],
        date_to: Optional[str],
        search: Optional[str],
        filters: Dict[str, Optional[str]],
        sort_by: str,
        sort_dir: str,
        page: int,
        per_page: int,
        account_id: int = 1,
    ) -> tuple:
        """Generic paginated, filtered, sorted query. Returns (rows, total)."""
        clauses: list = ["account_id = ?"]
        params: list = [account_id]

        if date_from:
            clauses.append(f"{ts_col} >= ?")
            params.append(date_from)
        if date_to:
            clauses.append(f"{ts_col} <= ?")
            params.append(date_to)
        if search:
            like = f"%{search}%"
            clauses.append("(ticker LIKE ?)")
            params.append(like)
        for col, val in filters.items():
            if val:
                clauses.append(f"{col} = ?")
                params.append(val)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        if sort_by not in allowed_sort:
            sort_by = ts_col
        if sort_dir not in ("ASC", "DESC"):
            sort_dir = "DESC"

        count_sql = f"SELECT COUNT(*) FROM {table}{where}"
        async with self._conn.execute(count_sql, params) as cur:
            total = (await cur.fetchone())[0]

        offset = (max(page, 1) - 1) * per_page
        data_sql = (
            f"SELECT * FROM {table}{where} "
            f"ORDER BY {sort_by} {sort_dir} "
            f"LIMIT ? OFFSET ?"
        )
        async with self._conn.execute(data_sql, params + [per_page, offset]) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows], total

    async def query_pre_trade_log(
        self, *, date_from: Optional[str] = None, date_to: Optional[str] = None,
        search: Optional[str] = None, ticker: Optional[str] = None,
        side: Optional[str] = None, sort_by: str = "timestamp",
        sort_dir: str = "DESC", page: int = 1, per_page: int = 20,
        account_id: int = 1,
    ) -> tuple:
        return await self._paginated_query(
            "pre_trade_log", "timestamp", self._PRE_TRADE_SORT_COLS,
            date_from, date_to, search, {"ticker": ticker, "side": side},
            sort_by, sort_dir, page, per_page, account_id,
        )

    async def query_execution_log(
        self, *, date_from: Optional[str] = None, date_to: Optional[str] = None,
        search: Optional[str] = None, ticker: Optional[str] = None,
        side: Optional[str] = None, sort_by: str = "entry_timestamp",
        sort_dir: str = "DESC", page: int = 1, per_page: int = 20,
        account_id: int = 1,
    ) -> tuple:
        return await self._paginated_query(
            "execution_log", "entry_timestamp", self._EXECUTION_SORT_COLS,
            date_from, date_to, search, {"ticker": ticker, "side": side},
            sort_by, sort_dir, page, per_page, account_id,
        )

    async def query_trade_history(
        self, *, date_from: Optional[str] = None, date_to: Optional[str] = None,
        search: Optional[str] = None, ticker: Optional[str] = None,
        direction: Optional[str] = None, sort_by: str = "exit_timestamp",
        sort_dir: str = "DESC", page: int = 1, per_page: int = 20,
        account_id: int = 1,
    ) -> tuple:
        return await self._paginated_query(
            "trade_history", "exit_timestamp", self._TRADE_HISTORY_SORT_COLS,
            date_from, date_to, search, {"ticker": ticker, "direction": direction},
            sort_by, sort_dir, page, per_page, account_id,
        )

    # ── Note updates ─────────────────────────────────────────────────────

    async def update_pre_trade_notes(self, row_id: int, notes: str) -> None:
        await self._conn.execute(
            "UPDATE pre_trade_log SET notes = ? WHERE id = ?", (notes, row_id)
        )
        await self._conn.commit()

    async def update_trade_history_notes(self, row_id: int, notes: str) -> None:
        await self._conn.execute(
            "UPDATE trade_history SET notes = ? WHERE id = ?", (notes, row_id)
        )
        await self._conn.commit()

    async def get_position_notes(self, trade_keys: List[str]) -> Dict[str, str]:
        """Return {trade_key: notes} for the given keys (only rows that exist)."""
        if not trade_keys:
            return {}
        placeholders = ",".join("?" * len(trade_keys))
        async with self._conn.execute(
            f"SELECT trade_key, notes FROM position_history_notes WHERE trade_key IN ({placeholders})",
            trade_keys,
        ) as cur:
            rows = await cur.fetchall()
        return {r["trade_key"]: r["notes"] for r in rows}

    async def upsert_position_note(self, trade_key: str, notes: str) -> None:
        await self._conn.execute(
            "INSERT INTO position_history_notes (trade_key, notes) VALUES (?, ?)"
            " ON CONFLICT(trade_key) DO UPDATE SET notes = excluded.notes",
            (trade_key, notes),
        )
        await self._conn.commit()

    async def upsert_exchange_history(self, rows: List[Dict], account_id: int = 1) -> None:
        """Upsert a batch of augmented Binance income rows keyed by trade_key."""
        if not rows:
            return
        normalized = [
            {
                "account_id":  account_id,
                "trade_key":  str(r.get("trade_key", "")),
                "time":       int(r.get("time", 0) or 0),
                "symbol":     str(r.get("symbol", "")),
                "incomeType": str(r.get("incomeType", "")),
                "income":     float(r.get("income", 0) or 0),
                "direction":  str(r.get("direction", "")),
                "entry_price": float(r.get("entry_price", 0) or 0),
                "exit_price":  float(r.get("exit_price", 0) or 0),
                "qty":         float(r.get("qty", 0) or 0),
                "notional":    float(r.get("notional", 0) or 0),
                "open_time":   int(r.get("open_time", 0) or 0),
                "fee":         float(r.get("fee", 0) or 0),
                "asset":       str(r.get("asset", "")),
            }
            for r in rows
            if r.get("trade_key")
        ]
        if not normalized:
            return
        try:
            await self._conn.executemany(
                """INSERT INTO exchange_history
                       (account_id, trade_key, time, symbol, income_type, income, direction,
                        entry_price, exit_price, qty, notional, open_time, fee, asset)
                   VALUES (:account_id, :trade_key, :time, :symbol, :incomeType, :income, :direction,
                           :entry_price, :exit_price, :qty, :notional, :open_time, :fee, :asset)
                   ON CONFLICT(trade_key) DO UPDATE SET
                     account_id  = excluded.account_id,
                     income      = excluded.income,
                     direction   = excluded.direction,
                     entry_price = excluded.entry_price,
                     exit_price  = excluded.exit_price,
                     qty         = excluded.qty,
                     notional    = excluded.notional,
                     open_time   = excluded.open_time,
                     fee         = excluded.fee""",
                normalized,
            )
            await self._conn.commit()
        except Exception as exc:
            log.error("upsert_exchange_history failed: %r", exc)
            try:
                await self._conn.rollback()
            except Exception:
                pass
            raise

    async def update_exchange_mfe_mae(self, trade_key: str, mfe: float, mae: float) -> None:
        """Write accurate MFE/MAE for a closed trade (reconciler only)."""
        await self._conn.execute(
            "UPDATE exchange_history SET mfe=?, mae=? WHERE trade_key=?",
            (mfe, mae, trade_key),
        )
        await self._conn.commit()

    async def get_uncalculated_exchange_rows(self, symbol: str) -> List[Dict]:
        """Return exchange_history rows for symbol where mfe or mae is still 0
        and open_time is known.  Catches both never-calculated rows (mfe=0) and
        partially-written rows (mfe written but mae left at 0 from a prior bug)."""
        async with self._conn.execute(
            "SELECT * FROM exchange_history WHERE symbol=? AND (mfe=0 OR mae=0) AND open_time>0",
            (symbol,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def query_exchange_history(
        self, *,
        page: int = 1, per_page: int = 20,
        sort_by: str = "time", sort_dir: str = "DESC",
        search: str = "", date_from: str = "", date_to: str = "",
        tz_local=None,
        account_id: int = 1,
    ) -> tuple:
        """Paginated SQL query of exchange_history with search + date filters."""
        clauses: list = ["account_id = ?"]
        params: list = [account_id]

        if search:
            clauses.append("symbol LIKE ?")
            params.append(f"%{search}%")
        if date_from and tz_local:
            from_ms = int(datetime.fromisoformat(date_from).replace(tzinfo=tz_local).timestamp() * 1000)
            clauses.append("time >= ?")
            params.append(from_ms)
        if date_to and tz_local:
            to_ms = int(datetime.fromisoformat(date_to).replace(tzinfo=tz_local).timestamp() * 1000)
            clauses.append("time <= ?")
            params.append(to_ms)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        col = sort_by if sort_by in self._EXCHANGE_HISTORY_SORT_COLS else "time"
        order = "DESC" if sort_dir.upper() == "DESC" else "ASC"
        # hold_ms is a computed alias — expand to the expression for ORDER BY
        order_expr = "(time - open_time)" if col == "hold_ms" else col

        async with self._conn.execute(
            f"SELECT COUNT(*) FROM exchange_history{where}", params
        ) as cur:
            total = (await cur.fetchone())[0]

        offset = (max(page, 1) - 1) * per_page
        async with self._conn.execute(
            f"SELECT *, (time - open_time) AS hold_ms"
            f" FROM exchange_history{where}"
            f" ORDER BY {order_expr} {order} LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows], total

    # ── Analytics query methods ───────────────────────────────────────────────

    async def get_journal_stats(self, from_ms: int, to_ms: int, account_id: int = 1) -> Dict[str, Any]:
        """
        Single-pass aggregation over exchange_history for a time window.
        Returns trade counts, PnL sums, win/loss breakdown, volume, and fee totals.
        Excludes FUNDING_FEE and TRANSFER rows from trade counts/PnL but captures
        TRANSFER rows for deposit/withdrawal fields.
        """
        async with self._conn.execute(
            """
            SELECT
              SUM(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') THEN 1 ELSE 0 END)          AS total_trades,
              SUM(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') AND income > 0 THEN 1 ELSE 0 END) AS winning_trades,
              SUM(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') AND income < 0 THEN 1 ELSE 0 END) AS losing_trades,
              SUM(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') AND direction='LONG'  THEN 1 ELSE 0 END) AS num_longs,
              SUM(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') AND direction='SHORT' THEN 1 ELSE 0 END) AS num_shorts,
              SUM(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') THEN income ELSE 0 END)      AS total_pnl,
              SUM(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') THEN fee    ELSE 0 END)      AS total_fees,
              SUM(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') THEN qty * entry_price ELSE 0 END) AS trading_volume,
              AVG(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') AND income > 0 THEN income END) AS avg_profit,
              AVG(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') AND income < 0 THEN income END) AS avg_loss,
              MAX(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') THEN income END)             AS biggest_profit,
              MIN(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') THEN income END)             AS biggest_loss,
              SUM(CASE WHEN income_type='TRANSFER' AND income > 0 THEN income ELSE 0 END)              AS deposits,
              SUM(CASE WHEN income_type='TRANSFER' AND income < 0 THEN ABS(income) ELSE 0 END)        AS withdrawals
            FROM exchange_history
            WHERE account_id = ? AND time >= ? AND time <= ?
            """,
            (account_id, from_ms, to_ms),
        ) as cur:
            row = await cur.fetchone()
        result = dict(row) if row else {}
        # Ensure no None values for numeric fields
        for k in result:
            if result[k] is None:
                result[k] = 0.0
        return result

    async def get_daily_equity_series(self, from_ms: int, to_ms: int, account_id: int = 1) -> List[Dict[str, Any]]:
        """
        One row per LOCAL calendar day (last snapshot of that day) covering the range.
        Returns: [{day, total_equity, daily_pnl, daily_pnl_percent, drawdown}, ...]
        Ordered oldest-first for chart rendering.

        Uses local TZ offset so that daily_pnl (which resets at midnight local time)
        aligns correctly with the calendar date it belongs to.
        """
        # Compute local TZ offset for SQLite DATE() modifier.
        # snapshot_ts is stored as UTC ISO; we shift into local time for grouping.
        try:
            from core.state import TZ_LOCAL as _TZ
            offset_s = int(datetime.now(_TZ).utcoffset().total_seconds())
        except Exception:
            offset_s = 0
        offset_h = offset_s // 3600
        tz_mod = f"{'+' if offset_h >= 0 else ''}{offset_h} hours"

        from_iso = datetime.utcfromtimestamp(from_ms / 1000).strftime("%Y-%m-%dT%H:%M:%S")
        to_iso   = datetime.utcfromtimestamp(to_ms   / 1000).strftime("%Y-%m-%dT%H:%M:%S")

        # NOTE: SQLite DATE(ts, modifier) accepts literal modifier strings only,
        # not bound parameters — the value is validated above to be safe (e.g. "+7 hours").
        sql = f"""
            SELECT
              DATE(snapshot_ts, '{tz_mod}') AS day,
              total_equity,
              daily_pnl,
              daily_pnl_percent,
              drawdown
            FROM account_snapshots
            WHERE account_id = ? AND snapshot_ts >= ? AND snapshot_ts <= ?
            GROUP BY DATE(snapshot_ts, '{tz_mod}')
            HAVING snapshot_ts = MAX(snapshot_ts)
            ORDER BY day ASC
        """
        async with self._conn.execute(sql, (account_id, from_iso, to_iso)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_daily_trade_stats(self, from_ms: int, to_ms: int, account_id: int = 1) -> Dict[str, Dict]:
        """
        Per-day aggregation from exchange_history: trade count, volume, win rate.
        Returns {"YYYY-MM-DD": {"trades": int, "volume": float, "win_rate": float}}
        """
        try:
            from core.state import TZ_LOCAL as _TZ
            offset_s = int(datetime.now(_TZ).utcoffset().total_seconds())
        except Exception:
            offset_s = 0
        offset_h = offset_s // 3600
        tz_mod = f"{'+' if offset_h >= 0 else ''}{offset_h} hours"

        sql = f"""
            SELECT
              DATE(datetime(time/1000, 'unixepoch', '{tz_mod}')) AS day,
              COUNT(*)                                              AS total_trades,
              SUM(qty * entry_price)                               AS volume,
              SUM(CASE WHEN income > 0 THEN 1 ELSE 0 END)         AS wins
            FROM exchange_history
            WHERE account_id = ? AND time >= ? AND time <= ?
              AND income_type NOT IN ('FUNDING_FEE', 'TRANSFER')
            GROUP BY DATE(datetime(time/1000, 'unixepoch', '{tz_mod}'))
        """
        async with self._conn.execute(sql, (account_id, from_ms, to_ms)) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        result: Dict[str, Dict] = {}
        for r in rows:
            total = r["total_trades"] or 0
            wins  = r["wins"] or 0
            result[r["day"]] = {
                "trades":   total,
                "volume":   r["volume"] or 0.0,
                "win_rate": round(wins / total, 4) if total else 0.0,
            }
        return result

    async def get_equity_period_boundaries(self, from_ms: int, to_ms: int, account_id: int = 1) -> Dict[str, float]:
        """
        Return {initial_equity, final_equity, max_drawdown} for a period.
        """
        from_iso = datetime.utcfromtimestamp(from_ms / 1000).strftime("%Y-%m-%dT%H:%M:%S")
        to_iso   = datetime.utcfromtimestamp(to_ms   / 1000).strftime("%Y-%m-%dT%H:%M:%S")
        async with self._conn.execute(
            "SELECT total_equity FROM account_snapshots WHERE account_id=? AND snapshot_ts >= ? ORDER BY snapshot_ts ASC LIMIT 1",
            (account_id, from_iso),
        ) as cur:
            row = await cur.fetchone()
            initial = float(row[0]) if row else 0.0
        async with self._conn.execute(
            "SELECT total_equity FROM account_snapshots WHERE account_id=? AND snapshot_ts <= ? ORDER BY snapshot_ts DESC LIMIT 1",
            (account_id, to_iso),
        ) as cur:
            row = await cur.fetchone()
            final = float(row[0]) if row else 0.0
        async with self._conn.execute(
            "SELECT MAX(drawdown) FROM account_snapshots WHERE account_id=? AND snapshot_ts >= ? AND snapshot_ts <= ?",
            (account_id, from_iso, to_iso),
        ) as cur:
            row = await cur.fetchone()
            max_dd = float(row[0]) if row and row[0] is not None else 0.0
        return {"initial_equity": initial, "final_equity": final, "max_drawdown": max_dd}

    async def get_traded_pairs_stats(self, from_ms: int, to_ms: int, account_id: int = 1) -> List[Dict[str, Any]]:
        """
        Per-symbol aggregation: count, long/short split, PnL breakdown, volume, fees.
        Only REALIZED_PNL rows (excludes FUNDING_FEE, TRANSFER).
        """
        async with self._conn.execute(
            """
            SELECT
              symbol,
              COUNT(*)                                                               AS total,
              SUM(CASE WHEN direction='LONG'  THEN 1 ELSE 0 END)                   AS longs,
              SUM(CASE WHEN direction='SHORT' THEN 1 ELSE 0 END)                   AS shorts,
              SUM(CASE WHEN direction='LONG'  THEN income ELSE 0 END)              AS pnl_long,
              SUM(CASE WHEN direction='SHORT' THEN income ELSE 0 END)              AS pnl_short,
              SUM(income)                                                            AS pnl_total,
              SUM(fee)                                                               AS fees_total,
              SUM(qty * entry_price)                                                 AS volume,
              SUM(CASE WHEN income > 0 THEN 1 ELSE 0 END)                          AS wins,
              AVG(CASE WHEN income > 0 THEN income END)                             AS avg_win,
              AVG(CASE WHEN income < 0 THEN income END)                             AS avg_loss
            FROM exchange_history
            WHERE account_id = ? AND time >= ? AND time <= ?
              AND income_type NOT IN ('FUNDING_FEE','TRANSFER')
            GROUP BY symbol
            ORDER BY total DESC
            """,
            (account_id, from_ms, to_ms),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        # Add win_rate computed field
        for r in rows:
            t = r["total"] or 1
            r["win_rate"] = round((r["wins"] or 0) / t, 4)
            for k in ("pnl_long", "pnl_short", "pnl_total", "fees_total", "volume", "avg_win", "avg_loss"):
                if r[k] is None:
                    r[k] = 0.0
        return rows

    async def get_mfe_mae_series(self, from_ms: int, to_ms: int, account_id: int = 1) -> List[Dict[str, Any]]:
        """
        Returns reconciled trades with MFE/MAE for scatter plot and ratio calcs.
        Only rows where both open_time and at least one of mfe/mae is non-zero.
        """
        async with self._conn.execute(
            """
            SELECT trade_key, symbol, direction, income, notional, mfe, mae,
                   entry_price, qty,
                   (time - open_time) AS hold_ms
            FROM exchange_history
            WHERE account_id = ? AND time >= ? AND time <= ?
              AND open_time > 0
              AND (mfe != 0 OR mae != 0)
              AND income_type NOT IN ('FUNDING_FEE','TRANSFER')
            ORDER BY time DESC
            """,
            (account_id, from_ms, to_ms),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_r_multiples(self, from_ms: int, to_ms: int, account_id: int = 1) -> List[float]:
        """
        Returns list of R-multiple floats for the period.
        Primary source: trade_history.individual_realized_r.
        Falls back to exchange_history.income / ABS(pre_trade.est_loss) for
        unmatched records (best-effort join on ticker + ±60 min window).
        """
        r_values: List[float] = []
        # Primary: manual trade_history entries
        from_iso = datetime.utcfromtimestamp(from_ms / 1000).isoformat()
        to_iso   = datetime.utcfromtimestamp(to_ms   / 1000).isoformat()
        async with self._conn.execute(
            """
            SELECT individual_realized_r FROM trade_history
            WHERE account_id = ? AND exit_timestamp >= ? AND exit_timestamp <= ?
              AND individual_realized_r != 0
            """,
            (account_id, from_iso, to_iso),
        ) as cur:
            for row in await cur.fetchall():
                r_values.append(float(row[0]))
        # Secondary fallback: exchange_history income / est_loss from pre_trade
        # Only use if very few manual entries to avoid double-counting
        if len(r_values) < 5:
            async with self._conn.execute(
                """
                SELECT eh.income, pt.est_loss
                FROM exchange_history eh
                LEFT JOIN pre_trade_log pt
                  ON pt.ticker = eh.symbol
                  AND pt.account_id = eh.account_id
                  AND ABS(CAST(strftime('%s', pt.timestamp) AS INTEGER) * 1000
                          - eh.open_time) < 3600000
                WHERE eh.account_id = ? AND eh.time >= ? AND eh.time <= ?
                  AND eh.income_type NOT IN ('FUNDING_FEE','TRANSFER')
                  AND pt.est_loss < 0
                GROUP BY eh.trade_key
                ORDER BY eh.time DESC
                LIMIT 500
                """,
                (account_id, from_ms, to_ms),
            ) as cur:
                for row in await cur.fetchall():
                    income, est_loss = row
                    if est_loss and est_loss != 0:
                        r_values.append(round(float(income) / abs(float(est_loss)), 3))
        return r_values

    async def get_most_traded_pairs(self, from_ms: int, to_ms: int, limit: int = 5, account_id: int = 1) -> List[str]:
        """Return top-N symbols by trade count in the period."""
        async with self._conn.execute(
            """
            SELECT symbol, COUNT(*) AS cnt
            FROM exchange_history
            WHERE account_id = ? AND time >= ? AND time <= ?
              AND income_type NOT IN ('FUNDING_FEE','TRANSFER')
            GROUP BY symbol
            ORDER BY cnt DESC
            LIMIT ?
            """,
            (account_id, from_ms, to_ms, limit),
        ) as cur:
            return [row[0] for row in await cur.fetchall()]

    async def get_cumulative_pnl(self, account_id: int = 1) -> Dict[str, float]:
        """
        All-time cumulative PnL and PnL% from exchange_history.
        Deposits/withdrawals (TRANSFER rows) are excluded from PnL
        but used to compute the true initial capital baseline.
        """
        async with self._conn.execute(
            """
            SELECT
              SUM(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') THEN income ELSE 0 END) AS total_pnl,
              SUM(CASE WHEN income_type='TRANSFER' AND income > 0 THEN income ELSE 0 END)         AS total_deposits,
              SUM(CASE WHEN income_type='TRANSFER' AND income < 0 THEN ABS(income) ELSE 0 END)   AS total_withdrawals
            FROM exchange_history
            WHERE account_id = ?
            """,
            (account_id,),
        ) as cur:
            row = dict(await cur.fetchone())
        for k in row:
            if row[k] is None:
                row[k] = 0.0
        return row

    async def clear_backfill_snapshots(self, account_id: int = 1) -> int:
        """Delete synthetic exchange_backfill rows for the given account. Returns count deleted."""
        async with self._conn.execute(
            "DELETE FROM account_snapshots WHERE trigger_channel = 'exchange_backfill' AND account_id = ?",
            (account_id,),
        ) as cur:
            count = cur.rowcount
        await self._conn.commit()
        log.info("Cleared %d exchange_backfill snapshots", count)
        return count

    async def get_earliest_snapshot_ms(self, account_id: int = 1) -> Optional[int]:
        """Return the epoch-milliseconds timestamp of the earliest account_snapshot for this account, or None."""
        async with self._conn.execute(
            "SELECT snapshot_ts FROM account_snapshots WHERE account_id=? ORDER BY snapshot_ts ASC LIMIT 1",
            (account_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        ts_str = str(row[0])
        try:
            if ts_str.endswith("Z"):
                ts_str = ts_str[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except Exception:
            return None

    async def insert_backfill_snapshots(
        self, records: List[tuple], before_ms: int, account_id: int = 1
    ) -> int:
        """
        Bulk-insert synthetic account_snapshots reconstructed from exchange income history.
        Only inserts rows with ts_ms < before_ms to avoid overlapping real snapshots.
        Columns not reconstructable (margin, PnL, etc.) are stored as 0.0.
        Returns number of rows inserted.
        """
        inserted = 0
        for ts_ms, equity in records:
            if ts_ms >= before_ms:
                continue
            dt_utc = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            snapshot_ts = dt_utc.isoformat()
            try:
                await self._conn.execute(
                    """INSERT INTO account_snapshots (
                        account_id, snapshot_ts, total_equity, balance_usdt, available_margin,
                        total_unrealized, total_realized, total_position_value,
                        total_margin_used, total_margin_ratio, daily_pnl, daily_pnl_percent,
                        bod_equity, sow_equity, max_total_equity, min_total_equity,
                        total_exposure, drawdown, total_weekly_pnl,
                        weekly_pnl_state, dd_state, open_positions, trigger_channel
                    ) VALUES (
                        ?, ?, ?, 0.0, 0.0,
                        0.0, 0.0, 0.0,
                        0.0, 0.0, 0.0, 0.0,
                        0.0, 0.0, 0.0, 0.0,
                        0.0, 0.0, 0.0,
                        '', '', 0, 'exchange_backfill'
                    )""",
                    (account_id, snapshot_ts, equity),
                )
                inserted += 1
            except Exception as exc:
                log.debug("insert_backfill_snapshots row skip: %r", exc)
        if inserted:
            await self._conn.commit()
        return inserted

    async def clear_cashflow_events(self, account_id: int = 1) -> int:
        """Delete equity_cashflow rows for the given account. Returns count deleted."""
        async with self._conn.execute("DELETE FROM equity_cashflow WHERE account_id = ?", (account_id,)) as cur:
            count = cur.rowcount
        await self._conn.commit()
        log.info("Cleared %d cashflow events", count)
        return count

    async def insert_cashflow_events(self, records: List[tuple], account_id: int = 1) -> int:
        """
        Bulk-insert (ts_ms, amount) rows into equity_cashflow.
        Uses INSERT OR REPLACE so re-running a backfill is idempotent.
        Returns number of rows written.
        """
        inserted = 0
        for ts_ms, amount in records:
            try:
                await self._conn.execute(
                    "INSERT OR REPLACE INTO equity_cashflow (ts_ms, amount, account_id) VALUES (?, ?, ?)",
                    (int(ts_ms), float(amount), account_id),
                )
                inserted += 1
            except Exception as exc:
                log.debug("insert_cashflow_events row skip: %r", exc)
        if inserted:
            await self._conn.commit()
        return inserted

    async def get_equity_ohlc(self, tf_minutes: int = 60, limit: int = 100, account_id: int = 1) -> List[Dict[str, Any]]:
        """
        Build OHLC candles from account_snapshots for the given timeframe.
        Each candle covers tf_minutes minutes; returns at most `limit` candles.
        Returns: [{x: epoch_ms, o, h, l, c}] sorted oldest-first.

        Fetches ALL snapshots so historical data is never artificially truncated —
        the final slice to `limit` happens after candle construction.
        """
        async with self._conn.execute(
            "SELECT snapshot_ts, total_equity, trigger_channel FROM account_snapshots WHERE account_id=? ORDER BY snapshot_ts ASC",
            (account_id,),
        ) as cur:
            rows = await cur.fetchall()

        tf_ms = tf_minutes * 60 * 1000
        candles: dict = {}  # period_start_ms -> {o, h, l, c}

        raw_points: List[Dict[str, Any]] = []
        for row in rows:
            ts_str = str(row[0])
            equity = float(row[1])
            trigger_channel = str(row[2] or "")
            try:
                # Handle both "+00:00" suffix and bare ISO strings
                if ts_str.endswith("Z"):
                    ts_str = ts_str[:-1] + "+00:00"
                from datetime import timezone as _tz
                dt = datetime.fromisoformat(ts_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=_tz.utc)
                ts_ms = int(dt.timestamp() * 1000)
            except Exception:
                continue
            raw_points.append({"ts_ms": ts_ms, "equity": equity, "trigger_channel": trigger_channel})

            period = (ts_ms // tf_ms) * tf_ms
            if period not in candles:
                candles[period] = {"o": equity, "h": equity, "l": equity, "c": equity}
            else:
                c = candles[period]
                if equity > c["h"]: c["h"] = equity
                if equity < c["l"]: c["l"] = equity
                c["c"] = equity

        # ── Aggregate cashflow (TRANSFER events) per period ─────────────────
        async with self._conn.execute(
            "SELECT ts_ms, amount FROM equity_cashflow WHERE account_id=? ORDER BY ts_ms ASC",
            (account_id,),
        ) as cur:
            cf_rows = await cur.fetchall()

        cf_by_period: dict = {}
        for row in cf_rows:
            cf_period = (int(row[0]) // tf_ms) * tf_ms
            cf_by_period[cf_period] = cf_by_period.get(cf_period, 0.0) + float(row[1])

        sorted_periods = sorted(candles.keys())
        dense_periods: List[int] = []
        if sorted_periods:
            p = sorted_periods[0]
            last = sorted_periods[-1]
            while p <= last:
                dense_periods.append(p)
                p += tf_ms

        # Fill missing periods with previous close to keep equity curve continuous.
        # Also anchor each candle's open to the previous close to eliminate
        # inter-period gaps caused by equity jumps between snapshot buckets.
        result: List[Dict[str, Any]] = []
        prev_close: Optional[float] = None
        for period in dense_periods:
            c = candles.get(period)
            if c is None:
                if prev_close is None:
                    continue
                o = h = l = close = prev_close
            else:
                # Anchor open to previous close so candles connect with no gap.
                # Extend high/low wicks to cover the new open if it falls outside.
                o = prev_close if prev_close is not None else c["o"]
                close = c["c"]
                h = max(c["h"], o)
                l = min(c["l"], o)
            prev_close = close
            result.append({
                "x": period,
                "o": round(o, 2),
                "h": round(h, 2),
                "l": round(l, 2),
                "c": round(close, 2),
                "cf": round(cf_by_period.get(period, 0.0), 2),
            })
        max_jump = 0.0
        max_jump_ts = 0
        max_jump_cf = 0.0
        for i in range(1, len(result)):
            jump = abs(float(result[i]["c"]) - float(result[i - 1]["c"]))
            if jump > max_jump:
                max_jump = jump
                max_jump_ts = int(result[i]["x"])
                max_jump_cf = float(result[i].get("cf", 0.0))
        raw_max_jump = 0.0
        raw_max_jump_ts = 0
        raw_pair_channels = []
        for i in range(1, len(raw_points)):
            jump = abs(float(raw_points[i]["equity"]) - float(raw_points[i - 1]["equity"]))
            if jump > raw_max_jump:
                raw_max_jump = jump
                raw_max_jump_ts = int(raw_points[i]["ts_ms"])
                raw_pair_channels = [
                    raw_points[i - 1]["trigger_channel"],
                    raw_points[i]["trigger_channel"],
                ]
        return result[-limit:]

    # ── Settings ──────────────────────────────────────────────────────────────

    async def get_setting(self, key: str) -> Optional[str]:
        async with self._conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        await self._conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value),
        )
        await self._conn.commit()

    # ── Account CRUD ──────────────────────────────────────────────────────────

    async def get_all_accounts(self) -> List[Dict[str, Any]]:
        """Return all accounts (no decrypted secrets — just metadata)."""
        async with self._conn.execute(
            "SELECT id, name, exchange, market_type, is_active, created_at FROM accounts ORDER BY id ASC"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_account(self, account_id: int) -> Optional[Dict[str, Any]]:
        """Return full account row (including encrypted secrets) or None."""
        async with self._conn.execute(
            "SELECT * FROM accounts WHERE id=?", (account_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def insert_account(
        self,
        name: str,
        exchange: str,
        market_type: str,
        api_key_enc: str,
        api_secret_enc: str,
        broker_account_id: str = "",
    ) -> int:
        """Insert new account, return new id."""
        async with self._conn.execute(
            "INSERT INTO accounts"
            " (name, exchange, market_type, api_key_enc, api_secret_enc, is_active, broker_account_id)"
            " VALUES (?, ?, ?, ?, ?, 0, ?)",
            (name, exchange, market_type, api_key_enc, api_secret_enc, broker_account_id),
        ) as cur:
            new_id = cur.lastrowid
        await self._conn.commit()
        return new_id

    async def update_account(self, account_id: int, **kwargs) -> None:
        """Update arbitrary columns on accounts row."""
        allowed = {
            "name", "exchange", "market_type",
            "api_key_enc", "api_secret_enc", "is_active",
            "broker_account_id",
        }
        cols = {k: v for k, v in kwargs.items() if k in allowed}
        if not cols:
            return
        set_clause = ", ".join(f"{k}=?" for k in cols)
        await self._conn.execute(
            f"UPDATE accounts SET {set_clause} WHERE id=?",
            list(cols.values()) + [account_id],
        )
        await self._conn.commit()

    async def delete_account(self, account_id: int) -> None:
        await self._conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
        await self._conn.commit()

    # ── OHLCV cache ───────────────────────────────────────────────────────────

    async def upsert_ohlcv(self, symbol: str, timeframe: str, candles: List[List]) -> int:
        """
        Bulk-upsert OHLCV candles. candles = [[ts_ms, o, h, l, c, vol], ...]
        Returns number of rows written.
        """
        if not candles:
            return 0
        rows = [
            (symbol, timeframe, int(c[0]), float(c[1]), float(c[2]),
             float(c[3]), float(c[4]), float(c[5]))
            for c in candles
        ]
        await self._conn.executemany(
            """INSERT INTO ohlcv_cache (symbol, timeframe, ts_ms, open, high, low, close, volume)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(symbol, timeframe, ts_ms) DO UPDATE SET
                 open=excluded.open, high=excluded.high, low=excluded.low,
                 close=excluded.close, volume=excluded.volume""",
            rows,
        )
        await self._conn.commit()
        return len(rows)

    async def get_ohlcv(
        self, symbol: str, timeframe: str,
        since_ms: Optional[int] = None, until_ms: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[List]:
        """Return [[ts_ms, o, h, l, c, vol], ...] ordered oldest-first."""
        clauses = ["symbol=?", "timeframe=?"]
        params: list = [symbol, timeframe]
        if since_ms is not None:
            clauses.append("ts_ms >= ?")
            params.append(since_ms)
        if until_ms is not None:
            clauses.append("ts_ms <= ?")
            params.append(until_ms)
        where = " WHERE " + " AND ".join(clauses)
        sql = f"SELECT ts_ms, open, high, low, close, volume FROM ohlcv_cache{where} ORDER BY ts_ms ASC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        async with self._conn.execute(sql, params) as cur:
            return [list(r) for r in await cur.fetchall()]

    async def get_ohlcv_range(self, symbol: str, timeframe: str) -> Dict[str, Any]:
        """Return {min_ts_ms, max_ts_ms, count} for the stored range."""
        async with self._conn.execute(
            "SELECT MIN(ts_ms), MAX(ts_ms), COUNT(*) FROM ohlcv_cache WHERE symbol=? AND timeframe=?",
            (symbol, timeframe),
        ) as cur:
            row = await cur.fetchone()
        return {"min_ts_ms": row[0], "max_ts_ms": row[1], "count": row[2] or 0}

    # ── Backtest sessions ─────────────────────────────────────────────────────

    async def create_backtest_session(
        self, name: str, session_type: str,
        date_from: str, date_to: str, config: Dict[str, Any],
    ) -> int:
        """Insert a new backtest_sessions row, return new id."""
        import json as _json
        async with self._conn.execute(
            """INSERT INTO backtest_sessions (name, type, status, date_from, date_to, config_json)
               VALUES (?, ?, 'running', ?, ?, ?)""",
            (name, session_type, date_from, date_to, _json.dumps(config)),
        ) as cur:
            new_id = cur.lastrowid
        await self._conn.commit()
        return new_id

    async def finish_backtest_session(
        self, session_id: int, status: str, summary: Dict[str, Any]
    ) -> None:
        import json as _json
        await self._conn.execute(
            "UPDATE backtest_sessions SET status=?, summary_json=? WHERE id=?",
            (status, _json.dumps(summary), session_id),
        )
        await self._conn.commit()

    async def get_backtest_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        import json as _json
        async with self._conn.execute(
            "SELECT * FROM backtest_sessions WHERE id=?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["config"] = _json.loads(d.get("config_json") or "{}")
        d["summary"] = _json.loads(d.get("summary_json") or "{}")
        return d

    async def list_backtest_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        import json as _json
        async with self._conn.execute(
            "SELECT * FROM backtest_sessions ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["config"] = _json.loads(d.get("config_json") or "{}")
            d["summary"] = _json.loads(d.get("summary_json") or "{}")
            result.append(d)
        return result

    async def delete_backtest_session(self, session_id: int) -> None:
        await self._conn.execute("DELETE FROM backtest_sessions WHERE id=?", (session_id,))
        await self._conn.commit()

    # ── Backtest trades & equity ──────────────────────────────────────────────

    async def insert_backtest_trades(self, session_id: int, trades: List[Dict[str, Any]]) -> None:
        rows = [
            (
                session_id,
                t.get("symbol", ""),
                t.get("side", ""),
                t.get("entry_dt", ""),
                t.get("exit_dt", ""),
                float(t.get("entry_price", 0)),
                float(t.get("exit_price", 0)),
                float(t.get("size_usdt", 0)),
                float(t.get("r_multiple", 0)),
                float(t.get("pnl_usdt", 0)),
                t.get("regime_label", ""),
                t.get("exit_reason", ""),
            )
            for t in trades
        ]
        if not rows:
            return
        await self._conn.executemany(
            """INSERT INTO backtest_trades
               (session_id, symbol, side, entry_dt, exit_dt, entry_price, exit_price,
                size_usdt, r_multiple, pnl_usdt, regime_label, exit_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        await self._conn.commit()

    async def get_backtest_trades(self, session_id: int) -> List[Dict[str, Any]]:
        async with self._conn.execute(
            "SELECT * FROM backtest_trades WHERE session_id=? ORDER BY entry_dt ASC",
            (session_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def insert_backtest_equity(self, session_id: int, curve: List[Dict[str, Any]]) -> None:
        rows = [(session_id, p["dt"], float(p["equity"]), float(p["drawdown"])) for p in curve]
        if not rows:
            return
        await self._conn.executemany(
            "INSERT INTO backtest_equity (session_id, dt, equity, drawdown) VALUES (?, ?, ?, ?)",
            rows,
        )
        await self._conn.commit()

    async def get_backtest_equity(self, session_id: int) -> List[Dict[str, Any]]:
        async with self._conn.execute(
            "SELECT dt, equity, drawdown FROM backtest_equity WHERE session_id=? ORDER BY dt ASC",
            (session_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def set_active_account(self, account_id: int) -> None:
        """Set is_active=1 on new account, 0 on all others."""
        await self._conn.execute("UPDATE accounts SET is_active=0")
        await self._conn.execute("UPDATE accounts SET is_active=1 WHERE id=?", (account_id,))
        await self._conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES ('active_account_id', ?, datetime('now'))"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (str(account_id),),
        )
        await self._conn.commit()

    # ── Potential models ────────────────────────────────────────────────────────

    async def create_potential_model(
        self, name: str, model_type: str, description: str, config: Dict[str, Any],
    ) -> int:
        import json as _json
        async with self._conn.execute(
            """INSERT INTO potential_models (name, type, description, config_json)
               VALUES (?, ?, ?, ?)""",
            (name, model_type, description, _json.dumps(config)),
        ) as cur:
            new_id = cur.lastrowid
        await self._conn.commit()
        return new_id

    async def list_potential_models(self) -> List[Dict[str, Any]]:
        import json as _json
        async with self._conn.execute(
            "SELECT * FROM potential_models ORDER BY id DESC"
        ) as cur:
            rows = await cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["config"] = _json.loads(d.get("config_json") or "{}")
            result.append(d)
        return result

    async def get_potential_model(self, model_id: int) -> Optional[Dict[str, Any]]:
        import json as _json
        async with self._conn.execute(
            "SELECT * FROM potential_models WHERE id=?", (model_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["config"] = _json.loads(d.get("config_json") or "{}")
        return d

    async def update_potential_model(
        self, model_id: int, name: str, model_type: str,
        description: str, config: Dict[str, Any],
    ) -> None:
        import json as _json
        await self._conn.execute(
            """UPDATE potential_models
               SET name=?, type=?, description=?, config_json=?
               WHERE id=?""",
            (name, model_type, description, _json.dumps(config), model_id),
        )
        await self._conn.commit()

    async def delete_potential_model(self, model_id: int) -> None:
        await self._conn.execute("DELETE FROM potential_models WHERE id=?", (model_id,))
        await self._conn.commit()

    # ── Regime signals & labels ──────────────────────────────────────────────────

    async def upsert_regime_signals(
        self, signal_name: str, rows: List[Dict[str, Any]], source: str = "",
    ) -> int:
        """Bulk upsert regime signal values. rows: [{"date": "YYYY-MM-DD", "value": float}, ...]"""
        if not rows:
            return 0
        await self._conn.executemany(
            """INSERT INTO regime_signals (signal_name, date, value, source, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(signal_name, date)
               DO UPDATE SET value=excluded.value, source=excluded.source, updated_at=excluded.updated_at""",
            [(signal_name, r["date"], r["value"], source) for r in rows],
        )
        await self._conn.commit()
        return len(rows)

    async def get_regime_signals(
        self, signal_names: List[str], from_date: str = "", to_date: str = "",
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Return {signal_name: [{date, value}, ...]} grouped and sorted by date ASC."""
        if not signal_names:
            return {}
        placeholders = ",".join("?" for _ in signal_names)
        query = f"SELECT signal_name, date, value FROM regime_signals WHERE signal_name IN ({placeholders})"
        params: list = list(signal_names)
        if from_date:
            query += " AND date >= ?"
            params.append(from_date)
        if to_date:
            query += " AND date <= ?"
            params.append(to_date)
        query += " ORDER BY date ASC"
        async with self._conn.execute(query, params) as cur:
            rows = await cur.fetchall()
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row[0], []).append({"date": row[1], "value": float(row[2])})
        return grouped

    async def get_regime_signal_range(self, signal_name: str) -> Dict[str, Any]:
        """Return {min_date, max_date, count} for a given signal."""
        async with self._conn.execute(
            "SELECT MIN(date), MAX(date), COUNT(*) FROM regime_signals WHERE signal_name=?",
            (signal_name,),
        ) as cur:
            row = await cur.fetchone()
        if not row or row[2] == 0:
            return {"min_date": None, "max_date": None, "count": 0}
        return {"min_date": row[0], "max_date": row[1], "count": row[2]}

    async def get_all_signal_coverage(self) -> List[Dict[str, Any]]:
        """Return per-signal coverage: [{signal_name, source, min_date, max_date, count}]."""
        async with self._conn.execute(
            """SELECT signal_name, source, MIN(date), MAX(date), COUNT(*)
               FROM regime_signals GROUP BY signal_name ORDER BY signal_name"""
        ) as cur:
            rows = await cur.fetchall()
        return [
            {"signal_name": r[0], "source": r[1], "min_date": r[2], "max_date": r[3], "count": r[4]}
            for r in rows
        ]

    async def upsert_regime_labels(self, rows: List[Dict[str, Any]]) -> int:
        """Bulk upsert classified regime labels. rows: [{"date", "label", "mode", "signals_json"}]."""
        import json as _json
        if not rows:
            return 0
        await self._conn.executemany(
            """INSERT INTO regime_labels (date, label, mode, signals_json, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(date)
               DO UPDATE SET label=excluded.label, mode=excluded.mode,
                             signals_json=excluded.signals_json, updated_at=excluded.updated_at""",
            [(r["date"], r["label"], r.get("mode", "full"),
              _json.dumps(r.get("signals", {})) if isinstance(r.get("signals"), dict) else r.get("signals_json", "{}"))
             for r in rows],
        )
        await self._conn.commit()
        return len(rows)

    async def get_regime_labels(
        self, from_date: str = "", to_date: str = "",
    ) -> List[Dict[str, Any]]:
        """Return regime labels sorted by date ASC."""
        import json as _json
        query = "SELECT date, label, mode, signals_json FROM regime_labels WHERE 1=1"
        params: list = []
        if from_date:
            query += " AND date >= ?"
            params.append(from_date)
        if to_date:
            query += " AND date <= ?"
            params.append(to_date)
        query += " ORDER BY date ASC"
        async with self._conn.execute(query, params) as cur:
            rows = await cur.fetchall()
        return [
            {"date": r[0], "label": r[1], "mode": r[2], "signals": _json.loads(r[3] or "{}")}
            for r in rows
        ]

    async def get_latest_regime_label(self) -> Optional[Dict[str, Any]]:
        """Return the most recent regime label, or None."""
        import json as _json
        async with self._conn.execute(
            "SELECT date, label, mode, signals_json FROM regime_labels ORDER BY date DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return {"date": row[0], "label": row[1], "mode": row[2], "signals": _json.loads(row[3] or "{}")}

    async def get_recent_regime_labels(self, n: int = 30) -> List[Dict[str, Any]]:
        """Return the N most recent regime labels, sorted date DESC."""
        async with self._conn.execute(
            "SELECT date, label FROM regime_labels ORDER BY date DESC LIMIT ?", (n,)
        ) as cur:
            rows = await cur.fetchall()
        return [{"date": r[0], "label": r[1]} for r in rows]

    async def get_all_regime_labels(self) -> List[Dict[str, Any]]:
        """Return all regime labels sorted date ASC — used for transition matrix."""
        async with self._conn.execute(
            "SELECT date, label FROM regime_labels ORDER BY date ASC"
        ) as cur:
            rows = await cur.fetchall()
        return [{"date": r[0], "label": r[1]} for r in rows]

    async def delete_regime_labels(self, from_date: str = "", to_date: str = "") -> int:
        """Delete regime labels in a date range (for reclassification). Returns count deleted."""
        query = "DELETE FROM regime_labels WHERE 1=1"
        params: list = []
        if from_date:
            query += " AND date >= ?"
            params.append(from_date)
        if to_date:
            query += " AND date <= ?"
            params.append(to_date)
        async with self._conn.execute(query, params) as cur:
            count = cur.rowcount
        await self._conn.commit()
        return count

    # ── News & Economic Calendar (v2.1) ──────────────────────────────────────

    async def upsert_news_items(self, rows: List[Dict[str, Any]]) -> int:
        """Bulk upsert news items. Each row needs source, external_id, headline, published_at."""
        if not rows:
            return 0
        await self._conn.executemany(
            """INSERT INTO news_items
                 (source, external_id, headline, summary, url, image_url, category,
                  tickers, published_at, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(source, external_id)
               DO UPDATE SET headline=excluded.headline, summary=excluded.summary,
                             url=excluded.url, image_url=excluded.image_url,
                             category=excluded.category, tickers=excluded.tickers,
                             published_at=excluded.published_at""",
            [(r["source"], str(r["external_id"]), r["headline"],
              r.get("summary", ""), r.get("url", ""), r.get("image_url", ""),
              r.get("category", ""), r.get("tickers", ""),
              r["published_at"]) for r in rows],
        )
        await self._conn.commit()
        return len(rows)

    async def get_news_feed(
        self, limit: int = 50, since: str = "", source: str = "",
    ) -> List[Dict[str, Any]]:
        """Return news items sorted by published_at DESC. Optional since (ISO) and source filters."""
        query = (
            "SELECT id, source, external_id, headline, summary, url, image_url, "
            "category, tickers, published_at FROM news_items WHERE 1=1"
        )
        params: list = []
        if since:
            query += " AND published_at >= ?"
            params.append(since)
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY published_at DESC LIMIT ?"
        params.append(int(limit))
        async with self._conn.execute(query, params) as cur:
            rows = await cur.fetchall()
        return [
            {"id": r[0], "source": r[1], "external_id": r[2], "headline": r[3],
             "summary": r[4], "url": r[5], "image_url": r[6], "category": r[7],
             "tickers": r[8], "published_at": r[9]}
            for r in rows
        ]

    async def get_news_by_id(self, item_id: int) -> Optional[Dict[str, Any]]:
        """Return a single news item by primary key."""
        async with self._conn.execute(
            "SELECT id, source, external_id, headline, summary, url, image_url, "
            "category, tickers, published_at, fetched_at FROM news_items WHERE id = ?",
            (item_id,),
        ) as cur:
            r = await cur.fetchone()
        if not r:
            return None
        return {
            "id": r[0], "source": r[1], "external_id": r[2], "headline": r[3],
            "summary": r[4], "url": r[5], "image_url": r[6], "category": r[7],
            "tickers": r[8], "published_at": r[9], "fetched_at": r[10],
        }

    async def upsert_calendar_events(self, rows: List[Dict[str, Any]]) -> int:
        """Bulk upsert economic calendar events keyed on (event_time, country, event_name)."""
        if not rows:
            return 0
        await self._conn.executemany(
            """INSERT INTO economic_calendar
                 (event_time, country, event_name, impact, currency, unit,
                  previous, estimate, actual, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(event_time, country, event_name)
               DO UPDATE SET impact=excluded.impact, currency=excluded.currency,
                             unit=excluded.unit, previous=excluded.previous,
                             estimate=excluded.estimate, actual=excluded.actual,
                             fetched_at=excluded.fetched_at""",
            [(r["event_time"], r["country"], r["event_name"],
              r.get("impact", ""), r.get("currency", ""), r.get("unit", ""),
              r.get("previous"), r.get("estimate"), r.get("actual"))
             for r in rows],
        )
        await self._conn.commit()
        return len(rows)

    async def get_calendar_events(
        self, from_date: str = "", to_date: str = "", impact: str = "",
    ) -> List[Dict[str, Any]]:
        """Return calendar events sorted by event_time ASC. Optional impact filter (csv)."""
        query = (
            "SELECT id, event_time, country, event_name, impact, currency, unit, "
            "previous, estimate, actual FROM economic_calendar WHERE 1=1"
        )
        params: list = []
        if from_date:
            query += " AND event_time >= ?"
            params.append(from_date)
        if to_date:
            query += " AND event_time <= ?"
            params.append(to_date)
        if impact:
            levels = [s.strip() for s in impact.split(",") if s.strip()]
            if levels:
                query += " AND impact IN (" + ",".join("?" * len(levels)) + ")"
                params.extend(levels)
        query += " ORDER BY event_time ASC"
        async with self._conn.execute(query, params) as cur:
            rows = await cur.fetchall()
        return [
            {"id": r[0], "event_time": r[1], "country": r[2], "event_name": r[3],
             "impact": r[4], "currency": r[5], "unit": r[6],
             "previous": r[7], "estimate": r[8], "actual": r[9]}
            for r in rows
        ]

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None


# Module-level singleton — points at the legacy combined DB (config.DB_PATH).
# Will be deprecated once `core.db_router` becomes the canonical entry point
# (R1b of the data-route refactor). Until then, all existing callers continue
# to import `db` from here and operate on the combined file.
db = DatabaseManager()
