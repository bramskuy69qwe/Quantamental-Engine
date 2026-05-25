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
# Task 160 (MED-024): exception class for "no such table" path in the
# duplicate pre-check (aiosqlite re-exports sqlite3's OperationalError).
from aiosqlite import OperationalError as _aiosqlite_OperationalError

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
from core.db_auth      import AuthMixin

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
    -- HIGH-027 (Task 104a) per-calc override of the account-level
    -- link_window_seconds. NULL means use account default. Surfaced to
    -- operator via the calculator UI in Task 104b.
    link_window_seconds_override INTEGER DEFAULT NULL,
    size              REAL NOT NULL DEFAULT 0,
    notional          REAL NOT NULL DEFAULT 0,
    est_profit        REAL NOT NULL DEFAULT 0,
    est_loss          REAL NOT NULL DEFAULT 0,
    est_r             REAL NOT NULL DEFAULT 0,
    est_exposure      REAL NOT NULL DEFAULT 0,
    eligible          INTEGER NOT NULL DEFAULT 0,
    notes             TEXT NOT NULL DEFAULT '',
    -- Task 157: regime decision recorded at plan time. NULL on every
    -- column = "pre-T157 row, decision unrecorded" (forward-analytics
    -- excludes; does NOT coerce to 1.0 which would falsely read as
    -- "regime ran and chose x1"). Defaults left as NULL deliberately.
    regime_label             TEXT,
    regime_multiplier        REAL,
    regime_mode              TEXT,
    apply_regime_multiplier  INTEGER
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
    broker_account_id TEXT,
    -- HIGH-027 (Task 104a) account-level default link window. Pretrade
    -- entries older than this many seconds at fill time are rejected by
    -- compute_exec_match. Per-calc override available via
    -- pre_trade_log.link_window_seconds_override. Default 21600 s = 6 h
    -- (conservative for crypto-futures swing/intraday workflows, tunable
    -- via the settings UI in Task 104b).
    link_window_seconds INTEGER NOT NULL DEFAULT 21600
);
-- Task 160 (MED-024): partial UNIQUE on (exchange, broker_account_id) so
-- Quantower fill routing cannot land on the wrong account. Partial WHERE
-- excludes NULL/empty broker_account_id rows (accounts that haven't been
-- broker-linked yet — multiple unset accounts are valid).
CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_broker_unique
    ON accounts (exchange, broker_account_id)
    WHERE broker_account_id IS NOT NULL AND broker_account_id != '';

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
    tp_price             REAL    DEFAULT NULL,
    sl_price             REAL    DEFAULT NULL,
    UNIQUE(account_id, terminal_position_id, exit_time_ms)
);
CREATE INDEX IF NOT EXISTS idx_closed_pos_ts     ON closed_positions (account_id, exit_time_ms DESC);
CREATE INDEX IF NOT EXISTS idx_closed_pos_symbol ON closed_positions (symbol, exit_time_ms DESC);

-- ── Phase 0 (P0.T1): calc-linkage schema foundation ──────────────────────
-- Per docs/design/calc_linkage_spec.md §3.1. Four new tables backing the
-- matcher (Phase 1), junction attribution (Phase 2), amendment tracking
-- (Phase 4), funding attribution (Phase 5), and reverse-query (Phase 7).
-- All four carry ``lifecycle_id`` (UUID, see §3.5) generated at the
-- first opening fill (Phase 2.1) and indexed for the single-key audit
-- query (``GET /context/lifecycle/{id}``, Phase 7).

CREATE TABLE IF NOT EXISTS positions_calcs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id     INTEGER NOT NULL,
    calc_id         TEXT    NOT NULL,
    order_id        INTEGER NOT NULL,
    account_id      INTEGER NOT NULL,
    contributed_qty REAL    NOT NULL DEFAULT 0,
    first_fill_ts   INTEGER NOT NULL DEFAULT 0,
    last_fill_ts    INTEGER NOT NULL DEFAULT 0,
    planned_size    REAL    DEFAULT NULL,
    size_delta_pct  REAL    DEFAULT NULL,
    planned_tp      REAL    DEFAULT NULL,
    planned_sl      REAL    DEFAULT NULL,
    lifecycle_id    TEXT    DEFAULT NULL,
    UNIQUE (position_id, calc_id, order_id)
);
CREATE INDEX IF NOT EXISTS idx_pc_position  ON positions_calcs (position_id);
CREATE INDEX IF NOT EXISTS idx_pc_calc      ON positions_calcs (calc_id);
CREATE INDEX IF NOT EXISTS idx_pc_order     ON positions_calcs (order_id);
CREATE INDEX IF NOT EXISTS idx_pc_account   ON positions_calcs (account_id, calc_id);
CREATE INDEX IF NOT EXISTS idx_pc_lifecycle ON positions_calcs (lifecycle_id);

CREATE TABLE IF NOT EXISTS order_amendments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id      INTEGER NOT NULL,
    calc_id       TEXT    DEFAULT NULL,
    field         TEXT    NOT NULL,
    old_value     REAL    DEFAULT NULL,
    new_value     REAL    DEFAULT NULL,
    ts_ms         INTEGER NOT NULL,
    operator_id   TEXT    DEFAULT NULL,
    deviation_pct REAL    DEFAULT NULL,
    lifecycle_id  TEXT    DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_oa_order        ON order_amendments (order_id);
CREATE INDEX IF NOT EXISTS idx_oa_calc         ON order_amendments (calc_id);
CREATE INDEX IF NOT EXISTS idx_oa_calc_ts      ON order_amendments (calc_id, ts_ms);
CREATE INDEX IF NOT EXISTS idx_oa_lifecycle    ON order_amendments (lifecycle_id);

CREATE TABLE IF NOT EXISTS funding_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id     INTEGER NOT NULL,
    calc_id         TEXT    DEFAULT NULL,
    account_id      INTEGER NOT NULL,
    symbol          TEXT    NOT NULL,
    amount          REAL    NOT NULL DEFAULT 0,
    mark_price      REAL    DEFAULT NULL,
    funding_rate    REAL    DEFAULT NULL,
    ts_ms           INTEGER NOT NULL,
    venue_event_id  TEXT    NOT NULL,
    lifecycle_id    TEXT    DEFAULT NULL,
    UNIQUE (venue_event_id)
);
CREATE INDEX IF NOT EXISTS idx_fe_position    ON funding_events (position_id);
CREATE INDEX IF NOT EXISTS idx_fe_account_ts  ON funding_events (account_id, ts_ms);
CREATE INDEX IF NOT EXISTS idx_fe_lifecycle   ON funding_events (lifecycle_id);

CREATE TABLE IF NOT EXISTS calc_match_audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        INTEGER NOT NULL,
    calc_id         TEXT    NOT NULL,
    criterion       TEXT    NOT NULL,
    calc_value      TEXT    DEFAULT NULL,
    order_value     TEXT    DEFAULT NULL,
    tolerance_used  REAL    DEFAULT NULL,
    matched         INTEGER NOT NULL DEFAULT 0,
    ts_ms           INTEGER NOT NULL,
    winning         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cma_order ON calc_match_audit (order_id);
CREATE INDEX IF NOT EXISTS idx_cma_calc  ON calc_match_audit (calc_id);

-- ── Phase 0 (P0.T2): operator session scaffold ───────────────────────────
-- Per spec §3.1 + §12.1. Multi-operator-per-account lock + takeover
-- audit. P0.T2 ships the table + minimal CRUD; the lock-enforcement
-- + takeover-prompt + operator_id propagation across action rows is
-- deferred to Phase 9 per implementation_plan.md §14.3 P0.T2 row.

CREATE TABLE IF NOT EXISTS operator_sessions (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id               INTEGER NOT NULL,
    operator_id              TEXT    NOT NULL,
    session_start_ts         INTEGER NOT NULL,
    session_end_ts           INTEGER DEFAULT NULL,
    takeover_from_session_id INTEGER DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_op_sess_account_start ON operator_sessions (account_id, session_start_ts DESC);
CREATE INDEX IF NOT EXISTS idx_op_sess_active       ON operator_sessions (account_id, session_end_ts);
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
    AuthMixin,
):
    """Async SQLite manager. Keep open for app lifetime; use WAL for concurrency.

    Multiple instances are now supported — pass a custom `path` to point at a
    different SQLite file. Used by `core.db_router` to route per-account vs
    global vs OHLCV-cache traffic to separate files.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self._conn: Optional[aiosqlite.Connection] = None
        self.path: str = path if path is not None else config.DB_PATH

    # ── HIGH-002 (Task 144, Phase 6 monitoring/reconciler) ──────────────────

    async def check_db_alive(self, timeout_s: Optional[float] = None) -> bool:
        """Liveness probe — `SELECT 1`. Returns True on success, False
        on any exception (including timeout). Used by the monitoring
        layer's db_health check.

        Optional `timeout_s` wraps the fetch in `asyncio.wait_for`.
        The original monitoring caller applied the timeout to the
        `fetchone()` call only (not the `execute()`), so behavior is
        preserved byte-for-byte when caller passes timeout_s.
        """
        import asyncio as _asyncio
        try:
            async with self._conn.execute("SELECT 1") as cur:
                if timeout_s is not None:
                    await _asyncio.wait_for(cur.fetchone(), timeout=timeout_s)
                else:
                    await cur.fetchone()
            return True
        except Exception:
            return False

    async def initialize(self) -> None:
        """Create DB file + all tables (idempotent). Call once in lifespan startup."""
        import os
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        # Task 160 (MED-024): duplicate pre-check must run BEFORE
        # executescript because _CREATE_STATEMENTS includes the partial
        # UNIQUE INDEX on (exchange, broker_account_id). If the accounts
        # table already exists with duplicate rows, executescript hits
        # the CREATE UNIQUE INDEX and raises a cryptic sqlite3.IntegrityError.
        # The pre-check below queries existing duplicates and raises
        # RuntimeError with a clear, operator-actionable message instead.
        # On a fresh DB (no accounts table yet), the SELECT raises
        # OperationalError("no such table") which we swallow — the
        # executescript that follows creates the table.
        try:
            async with self._conn.execute(
                """SELECT exchange, broker_account_id, COUNT(*) AS n,
                          GROUP_CONCAT(id) AS ids
                   FROM accounts
                   WHERE broker_account_id IS NOT NULL
                     AND broker_account_id != ''
                   GROUP BY exchange, broker_account_id
                   HAVING n > 1"""
            ) as cur:
                dup_rows = await cur.fetchall()
        except _aiosqlite_OperationalError:
            dup_rows = []  # fresh DB — no accounts table yet
        if dup_rows:
            details = "; ".join(
                f"({r[0]!r}, {r[1]!r}) → {r[2]} rows (account ids: {r[3]})"
                for r in dup_rows
            )
            raise RuntimeError(
                "MED-024 migration aborted: accounts table has duplicate "
                "(exchange, broker_account_id) tuples — these create silent "
                "Quantower fill-misrouting risk and must be resolved before "
                "the UNIQUE index can land. Duplicates: " + details + ". "
                "Resolution: identify which account is the canonical owner "
                "of each broker_account_id and clear or correct the others "
                "via the Config UI / direct DB edit, then restart."
            )

        # MED-046 (Task 119): use executescript() so the schema blob may
        # contain SQL comments with semicolons. The prior naive
        # ``.split(";")`` loop hit `sqlite3.OperationalError: incomplete
        # input` whenever a ``--`` comment line contained a `;`
        # (Task 104a discovery). executescript() parses the full blob
        # via sqlite3's tokenizer and handles comments correctly.
        # PRAGMA statements at the top are no-ops here (already issued
        # above) but executescript runs them harmlessly.
        await self._conn.executescript(_CREATE_STATEMENTS)
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
            # v2.4: calc_id for calculator-order correlation
            "ALTER TABLE orders ADD COLUMN calc_id TEXT",
            "ALTER TABLE fills ADD COLUMN calc_id TEXT",
            "ALTER TABLE orders ADD COLUMN tp_trigger_price REAL",
            "ALTER TABLE orders ADD COLUMN sl_trigger_price REAL",
            "ALTER TABLE closed_positions ADD COLUMN calc_id TEXT",
            # CRIT-008 (Task 88.1): legacy DB was missing pre_trade_log.calc_id.
            # Migration 005 adds it on per-account DBs, where pre_trade_log
            # doesn't actually exist; it never landed on the legacy DB until now.
            "ALTER TABLE pre_trade_log ADD COLUMN calc_id TEXT",
            # v2.4 Priority 2a: slippage measurement
            "ALTER TABLE fills ADD COLUMN slippage_actual REAL",
            "ALTER TABLE fills ADD COLUMN fill_type TEXT",
            # v2.4 Task 69: TP/SL denormalization on closed_positions
            "ALTER TABLE closed_positions ADD COLUMN tp_price REAL DEFAULT NULL",
            "ALTER TABLE closed_positions ADD COLUMN sl_price REAL DEFAULT NULL",
            # v2.4 Task 82: exec link confirmation tracking on fills
            "ALTER TABLE fills ADD COLUMN exec_link_confirmed INTEGER DEFAULT 0",
            "ALTER TABLE fills ADD COLUMN exec_link_confirmed_at TEXT DEFAULT NULL",
            "ALTER TABLE fills ADD COLUMN exec_link_confirmed_by TEXT DEFAULT NULL",
            # HIGH-027 (Task 104a): bounded calc-to-fill matching window.
            # Account-level default 6 h; per-pretrade override allowed. CREATE
            # TABLE above already includes the columns for fresh installs;
            # these ALTERs cover legacy DBs.
            "ALTER TABLE accounts ADD COLUMN link_window_seconds INTEGER NOT NULL DEFAULT 21600",
            "ALTER TABLE pre_trade_log ADD COLUMN link_window_seconds_override INTEGER DEFAULT NULL",
            # Task 157: per-trade regime decision logging. NULL-default
            # columns; pre-T157 rows excluded from forward analytics via
            # IS NOT NULL filter. Standalone migration 011_v2_5_pretrade_
            # regime_columns.sql covers split-DB setups too.
            "ALTER TABLE pre_trade_log ADD COLUMN regime_label TEXT",
            "ALTER TABLE pre_trade_log ADD COLUMN regime_multiplier REAL",
            "ALTER TABLE pre_trade_log ADD COLUMN regime_mode TEXT",
            "ALTER TABLE pre_trade_log ADD COLUMN apply_regime_multiplier INTEGER",
            # ── Phase 0 (P0.T3): calc-linkage column additions ───────────
            # Per spec §3.2 "pre_trade_log (additions)" + §3.5
            # (lifecycle_id). All NULL-default so legacy rows aren't
            # surprised — Phase 1+ matcher writes explicit values on
            # new calcs. account_id already added above (v1.3 migration);
            # 15 net-new columns here.
            "ALTER TABLE pre_trade_log ADD COLUMN status TEXT DEFAULT NULL",
            "ALTER TABLE pre_trade_log ADD COLUMN window_seconds INTEGER DEFAULT NULL",
            "ALTER TABLE pre_trade_log ADD COLUMN operator_id TEXT DEFAULT NULL",
            "ALTER TABLE pre_trade_log ADD COLUMN superseded_by_calc_id TEXT DEFAULT NULL",
            "ALTER TABLE pre_trade_log ADD COLUMN cancelled_reason TEXT DEFAULT NULL",
            "ALTER TABLE pre_trade_log ADD COLUMN planned_size REAL DEFAULT NULL",
            "ALTER TABLE pre_trade_log ADD COLUMN overridden_size REAL DEFAULT NULL",
            "ALTER TABLE pre_trade_log ADD COLUMN planned_tp REAL DEFAULT NULL",
            "ALTER TABLE pre_trade_log ADD COLUMN overridden_tp REAL DEFAULT NULL",
            "ALTER TABLE pre_trade_log ADD COLUMN planned_sl REAL DEFAULT NULL",
            "ALTER TABLE pre_trade_log ADD COLUMN overridden_sl REAL DEFAULT NULL",
            "ALTER TABLE pre_trade_log ADD COLUMN tp_levels TEXT DEFAULT NULL",
            "ALTER TABLE pre_trade_log ADD COLUMN filled_pct REAL DEFAULT NULL",
            "ALTER TABLE pre_trade_log ADD COLUMN tags TEXT DEFAULT NULL",
            "ALTER TABLE pre_trade_log ADD COLUMN lifecycle_id TEXT DEFAULT NULL",
            # Per spec §3.2 "accounts (additions)" + §3.3 config_json
            # schema. NULL default; reader applies per-field defaults
            # per spec §3.3 (window_seconds=300, entry_tolerance_pct=
            # 0.25, snapshot_drift_tolerance_pct=0.5, etc.) when the
            # account's config_json is missing or has unset fields.
            # The reader helper is Phase 1 work (P1.T2 core/account_
            # config.py); the column ships here so existing accounts
            # immediately have the slot.
            "ALTER TABLE accounts ADD COLUMN config_json TEXT DEFAULT NULL",
            # ── Phase 0 (P0.T4): orders + closed_positions column adds ─
            # Per spec §3.2. All NULL-default so legacy rows aren't
            # surprised — Phase 1+/2+/4+ writes explicit values on new
            # orders/positions. calc_id, tp_trigger_price,
            # sl_trigger_price already on orders (v2.4 migrations);
            # exit_reason, funding_fees, calc_id, tp_price, sl_price
            # already on closed_positions (existing). 6 new orders cols
            # + 16 new closed_positions cols.
            "ALTER TABLE orders ADD COLUMN link_status TEXT DEFAULT NULL",
            "ALTER TABLE orders ADD COLUMN operator_id TEXT DEFAULT NULL",
            "ALTER TABLE orders ADD COLUMN cancel_reason_category TEXT DEFAULT NULL",
            "ALTER TABLE orders ADD COLUMN cancel_reason_raw TEXT DEFAULT NULL",
            "ALTER TABLE orders ADD COLUMN cancel_ts_ms INTEGER DEFAULT NULL",
            "ALTER TABLE orders ADD COLUMN lifecycle_id TEXT DEFAULT NULL",
            # closed_positions: 16 net-new columns. exit_reason is the
            # one re-mapped column (existing TEXT col now holds the
            # spec §3.4 enum — re-map of legacy values is P0.T5).
            # funding_fees already exists and is being repurposed
            # (Phase 5.4 will populate from SUM(funding_events.amount)).
            "ALTER TABLE closed_positions ADD COLUMN close_note TEXT DEFAULT NULL",
            "ALTER TABLE closed_positions ADD COLUMN entry_px_delta_pct REAL DEFAULT NULL",
            "ALTER TABLE closed_positions ADD COLUMN size_delta_pct REAL DEFAULT NULL",
            "ALTER TABLE closed_positions ADD COLUMN tp_drift_pct REAL DEFAULT NULL",
            "ALTER TABLE closed_positions ADD COLUMN sl_drift_pct REAL DEFAULT NULL",
            "ALTER TABLE closed_positions ADD COLUMN exit_vs_target_pct REAL DEFAULT NULL",
            "ALTER TABLE closed_positions ADD COLUMN realized_r REAL DEFAULT NULL",
            "ALTER TABLE closed_positions ADD COLUMN planned_r REAL DEFAULT NULL",
            "ALTER TABLE closed_positions ADD COLUMN hold_time_actual_ms INTEGER DEFAULT NULL",
            "ALTER TABLE closed_positions ADD COLUMN hold_time_planned_ms INTEGER DEFAULT NULL",
            "ALTER TABLE closed_positions ADD COLUMN cumulative_amendment_count INTEGER DEFAULT NULL",
            "ALTER TABLE closed_positions ADD COLUMN liquidation_px REAL DEFAULT NULL",
            "ALTER TABLE closed_positions ADD COLUMN bankruptcy_px REAL DEFAULT NULL",
            "ALTER TABLE closed_positions ADD COLUMN insurance_fund_fee REAL DEFAULT NULL",
            "ALTER TABLE closed_positions ADD COLUMN adl_indicator INTEGER DEFAULT NULL",
            "ALTER TABLE closed_positions ADD COLUMN lifecycle_id TEXT DEFAULT NULL",
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

        # HIGH-003 (Task 88.1): indexes on hot calc_id lookup columns. Must run
        # after the ALTERs above so the columns definitely exist. Idempotent via
        # IF NOT EXISTS. orders.exchange_order_id is already covered by the
        # UNIQUE(account_id, exchange_order_id) auto-index — no separate index needed.
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pretrade_calc_id ON pre_trade_log (calc_id)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_calc_id ON orders (calc_id)"
        )
        # P0.T3 + P0.T4 spec §3.5: every table carrying lifecycle_id
        # has an index. orders + closed_positions get their indexes in
        # P0.T4 alongside the column additions above.
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pretrade_lifecycle "
            "ON pre_trade_log (lifecycle_id)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_lifecycle "
            "ON orders (lifecycle_id)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_closed_pos_lifecycle "
            "ON closed_positions (lifecycle_id)"
        )

        # Task 160 (MED-024): UNIQUE index install is now done by
        # _CREATE_STATEMENTS (canonical schema). Duplicate pre-check
        # runs at the top of initialize() before executescript fires,
        # so an existing-duplicates DB gets the loud RuntimeError there.
        # Re-run a no-op idempotent CREATE here so that DBs where the
        # accounts table existed before _CREATE_STATEMENTS gained the
        # CREATE UNIQUE INDEX line still get the index installed on
        # first post-T160 startup (executescript runs CREATE TABLE IF
        # NOT EXISTS which skips the existing table; the CREATE UNIQUE
        # INDEX IF NOT EXISTS following it still fires).
        await self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_broker_unique "
            "ON accounts (exchange, broker_account_id) "
            "WHERE broker_account_id IS NOT NULL AND broker_account_id != ''"
        )
        await self._conn.commit()

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

        # ── Task 69: backfill closed_positions.tp_price/sl_price from pre_trade_log
        # Idempotent: only updates rows that have calc_id but NULL tp_price.
        # Wrapped in try/except because pre_trade_log.calc_id may not exist in
        # DBs that haven't run migration 005 yet (e.g. test fixtures).
        try:
            await self._conn.execute("""
                UPDATE closed_positions
                SET tp_price = (SELECT p.tp_price FROM pre_trade_log p
                                WHERE p.calc_id = closed_positions.calc_id LIMIT 1),
                    sl_price = (SELECT p.sl_price FROM pre_trade_log p
                                WHERE p.calc_id = closed_positions.calc_id LIMIT 1)
                WHERE calc_id IS NOT NULL AND calc_id != '' AND tp_price IS NULL
            """)
            await self._conn.commit()
        except _sqlite3.OperationalError:
            pass  # pre_trade_log.calc_id not yet available — backfill skipped

        # ── Task 76: default empty exit_reason to 'manual' on closed_positions
        # Idempotent: only updates rows where exit_reason is empty string.
        await self._conn.execute(
            "UPDATE closed_positions SET exit_reason = 'manual' "
            "WHERE exit_reason = '' OR exit_reason IS NULL"
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
