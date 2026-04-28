"""
Global application state — single source of truth updated by the WS manager
and read by every FastAPI route handler.
"""
from __future__ import annotations
import json
import os
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

import config

TZ_LOCAL = timezone(timedelta(hours=config.TIMEZONE_OFFSET_HOURS))


# ── Parameter defaults ────────────────────────────────────────────────────────

DEFAULT_PARAMS: Dict[str, Any] = {
    "individual_risk_per_trade": 0.01,   # 1 % of equity
    "max_w_loss_percent":        0.05,   # 5 % weekly drawdown
    "max_dd_percent":            0.10,   # 10 % max drawdown
    "max_exposure":              3.0,    # 3× equity notional
    "max_position_count":        10,
    "max_correlated_exposure":   0.5,    # 50 % equity per sector
    "auto_export_hours":         24,     # export every 24 h
    # warning / hard-stop thresholds (fraction of limit)
    "weekly_loss_warning_pct":   0.80,
    "weekly_loss_limit_pct":     0.95,
    "max_dd_warning_pct":        0.80,
    "max_dd_limit_pct":          0.95,
}


@dataclass
class RegimeState:
    label:          str   = "neutral"
    multiplier:     float = 1.0
    confidence:     str   = "low"    # low / medium / high
    stability_bars: int   = 0        # consecutive days with same label
    computed_at:    Optional[datetime] = None
    mode:           str   = "macro_only"   # full / macro_only
    signals:        Dict[str, float] = field(default_factory=dict)

    @property
    def is_stale(self) -> bool:
        if self.computed_at is None:
            return True
        age_min = (datetime.now(timezone.utc) - self.computed_at).total_seconds() / 60
        return age_min > config.REGIME_STALE_MINUTES


@dataclass
class PositionInfo:
    ticker:                  str   = ""
    order_timestamp:         Optional[str] = None
    entry_timestamp:         Optional[str] = None
    contract_amount:         float = 0.0
    contract_size:           float = 1.0
    direction:               str   = ""   # LONG / SHORT
    position_value_usdt:     float = 0.0
    position_value_asset:    float = 0.0
    average:                 float = 0.0
    fair_price:              float = 0.0
    liquidation_price:       float = 0.0
    individual_margin_ratio: float = 0.0
    individual_margin_used:  float = 0.0
    individual_unrealized:   float = 0.0
    session_mfe:             float = 0.0  # max favorable excursion this session (visual only)
    session_mae:             float = 0.0  # max adverse excursion this session (visual only)
    individual_funding_fees: float = 0.0
    individual_realized:     float = 0.0
    individual_tpsl:         bool  = False
    individual_tp_price:     float = 0.0
    individual_sl_price:     float = 0.0
    individual_tp_amount:    float = 0.0
    individual_sl_amount:    float = 0.0
    individual_tp_usdt:      float = 0.0
    individual_sl_usdt:      float = 0.0
    model_name:              str   = ""
    sector:                  str   = ""


@dataclass
class ExchangeInfo:
    name:          str   = config.EXCHANGE_NAME
    account_id:    str   = ""
    server_time:   str   = ""
    latency_ms:    float = 0.0
    maker_fee:     float = config.MAKER_FEE
    taker_fee:     float = config.TAKER_FEE


@dataclass
class AccountState:
    balance_usdt:            float = 0.0
    available_margin:        float = 0.0
    total_equity:            float = 0.0
    total_unrealized:        float = 0.0
    total_realized:          float = 0.0
    total_position_value:    float = 0.0
    total_margin_used:       float = 0.0
    total_margin_ratio:      float = 0.0
    total_tp_usdt:           float = 0.0
    total_sl_usdt:           float = 0.0
    daily_unrealized:        float = 0.0
    daily_realized:          float = 0.0
    daily_pnl:               float = 0.0
    daily_pnl_percent:       float = 0.0
    # BOD / SOW snapshots
    bod_equity:              float = 0.0
    sow_equity:              float = 0.0
    bod_timestamp:           str   = ""
    sow_timestamp:           str   = ""
    # Rolling highs/lows (reset every BOD)
    max_total_equity:        float = 0.0
    min_total_equity:        float = 0.0
    # Cashflows
    cashflows:               float = 0.0


@dataclass
class PortfolioStats:
    total_exposure:           float = 0.0   # total notional / equity
    total_weekly_pnl:         float = 0.0
    total_weekly_pnl_percent: float = 0.0
    total_correlated_exposure: Dict[str, float] = field(default_factory=dict)
    drawdown:                 float = 0.0   # (max_eq - cur_eq) / max_eq
    dd_baseline_equity:       float = 0.0   # resets every BOD
    # States
    weekly_pnl_state:  str = "ok"           # ok / warning / limit
    dd_state:          str = "ok"


@dataclass
class WSStatus:
    connected:          bool  = False
    last_update:        Optional[datetime] = None
    latency_ms:         float = 0.0
    reconnect_attempts: int   = 0
    using_fallback:     bool  = False
    logs:               List[str] = field(default_factory=list)

    def add_log(self, msg: str):
        ts = datetime.now(TZ_LOCAL).strftime("%H:%M:%S")
        self.logs.append(f"[{ts}] {msg}")
        if len(self.logs) > config.WS_LOG_MAX_DISPLAY:
            self.logs = self.logs[-config.WS_LOG_MAX_DISPLAY:]

    @property
    def seconds_since_update(self) -> float:
        if self.last_update is None:
            return 9999.0
        return (datetime.now(timezone.utc) - self.last_update).total_seconds()

    @property
    def is_stale(self) -> bool:
        return self.seconds_since_update > config.WS_FALLBACK_TIMEOUT


# ── Singleton ─────────────────────────────────────────────────────────────────

class AppState:
    """Thread-safe (asyncio-safe) singleton holding all runtime state."""

    _instance: Optional["AppState"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self._lock = asyncio.Lock()

        self.exchange_info   = ExchangeInfo()
        self.account_state   = AccountState()
        self.positions:  List[PositionInfo]  = []
        self.portfolio   = PortfolioStats()
        self.ws_status   = WSStatus()

        # OHLCV cache keyed by symbol: list of [ts, o, h, l, c, v]
        self.ohlcv_cache: Dict[str, List] = {}

        # Orderbook cache keyed by symbol
        self.orderbook_cache: Dict[str, Dict] = {}

        # Mark price cache keyed by symbol
        self.mark_price_cache: Dict[str, float] = {}

        # Loaded params (persisted to disk)
        self.params: Dict[str, Any] = DEFAULT_PARAMS.copy()

        # Pre-trade log (in-memory, last 30 days also in CSV)
        self.pre_trade_log: List[Dict] = []

        # Exchange-fetched realized PnL history (newest first)
        self.exchange_trade_history: List[Dict] = []

        # True while the background startup fetch is still in progress
        self.is_initializing: bool = True

        # Live regime state (updated by background loop every 10 min)
        self.current_regime: Optional[RegimeState] = None

        # ── Multi-account / multi-platform ────────────────────────────────────
        self.active_account_id: int = 1
        self.active_platform:   str = "standalone"

    def reset_for_account_switch(self) -> None:
        """Clear all runtime state before switching to a different account.
        Params are intentionally NOT reset — they persist per-session."""
        self.account_state        = AccountState()
        self.positions            = []
        self.portfolio            = PortfolioStats()
        self.ohlcv_cache          = {}
        self.orderbook_cache      = {}
        self.mark_price_cache     = {}
        self.exchange_trade_history = []
        self.pre_trade_log        = []
        self.is_initializing      = True
        self.current_regime       = None
        self.ws_status            = WSStatus()
        self.ws_status.add_log("State reset for account switch.")

    # ── Parameter persistence ─────────────────────────────────────────────────

    def load_params(self):
        if os.path.exists(config.PARAMS_FILE):
            try:
                with open(config.PARAMS_FILE) as f:
                    saved = json.load(f)
                self.params.update(saved)
            except (ValueError, OSError, KeyError):
                pass

    def save_params(self):
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(config.PARAMS_FILE, "w") as f:
            json.dump(self.params, f, indent=2)

    async def save_params_async(self) -> None:
        """Non-blocking version — offloads the file write to a thread so the
        event loop is not blocked by slow disk I/O (network mounts, HDD GC, etc.)."""
        import asyncio as _asyncio
        data = json.dumps(self.params, indent=2)
        path = config.PARAMS_FILE
        dir_ = config.DATA_DIR

        def _write():
            os.makedirs(dir_, exist_ok=True)
            with open(path, "w") as f:
                f.write(data)

        await _asyncio.get_event_loop().run_in_executor(None, _write)

    # ── Portfolio recalculation (called after any state update) ───────────────

    def recalculate_portfolio(self):
        acc  = self.account_state
        pos  = self.positions
        prm  = self.params
        pf   = self.portfolio

        total_equity = acc.total_equity

        # Total exposure = sum of all notional / equity.
        # If equity hasn't loaded yet (0), leave exposure at 0 — using 1.0 as a
        # fallback would produce a wildly incorrect value (notional treated as ×equity).
        if total_equity > 0:
            pf.total_exposure = sum(abs(p.position_value_usdt) for p in pos) / total_equity
        else:
            pf.total_exposure = 0.0

        # Correlated exposure per sector
        sector_net: Dict[str, float] = {}
        for p in pos:
            net = p.position_value_usdt if p.direction == "LONG" else -p.position_value_usdt
            sector_net[p.sector] = sector_net.get(p.sector, 0.0) + net
        pf.total_correlated_exposure = sector_net

        # Total TP / SL usdt
        acc.total_tp_usdt = sum(p.individual_tp_usdt for p in pos)
        acc.total_sl_usdt = sum(p.individual_sl_usdt for p in pos)

        # Daily PnL (current equity vs BOD equity)
        bod_eq = acc.bod_equity if acc.bod_equity > 0 else total_equity
        acc.daily_pnl         = acc.total_equity - bod_eq
        acc.daily_pnl_percent = acc.daily_pnl / bod_eq if bod_eq > 0 else 0.0

        # Weekly PnL
        sow_eq = acc.sow_equity if acc.sow_equity > 0 else total_equity
        pf.total_weekly_pnl = acc.total_equity - sow_eq
        pf.total_weekly_pnl_percent = pf.total_weekly_pnl / sow_eq if sow_eq > 0 else 0.0

        # Drawdown from BOD baseline
        baseline = pf.dd_baseline_equity if pf.dd_baseline_equity > 0 else total_equity
        max_eq   = max(acc.max_total_equity, total_equity)
        acc.max_total_equity = max_eq
        # Track min equity (only update once initialized > 0)
        if acc.min_total_equity > 0:
            acc.min_total_equity = min(acc.min_total_equity, total_equity)
        else:
            acc.min_total_equity = total_equity
        pf.drawdown = (max_eq - total_equity) / max_eq if max_eq > 0 else 0.0

        # Warnings / limits — only applies when weekly PnL is negative (a loss)
        weekly_loss_pct = -pf.total_weekly_pnl_percent  # positive when losing
        w_ratio = weekly_loss_pct / prm["max_w_loss_percent"] if prm["max_w_loss_percent"] > 0 else 0
        if weekly_loss_pct > 0 and w_ratio >= prm["weekly_loss_limit_pct"]:
            pf.weekly_pnl_state = "limit"
        elif weekly_loss_pct > 0 and w_ratio >= prm["weekly_loss_warning_pct"]:
            pf.weekly_pnl_state = "warning"
        else:
            pf.weekly_pnl_state = "ok"

        dd_ratio = pf.drawdown / prm["max_dd_percent"] if prm["max_dd_percent"] > 0 else 0
        if dd_ratio >= prm["max_dd_limit_pct"]:
            pf.dd_state = "limit"
        elif dd_ratio >= prm["max_dd_warning_pct"]:
            pf.dd_state = "warning"
        else:
            pf.dd_state = "ok"

    # ── BOD reset ─────────────────────────────────────────────────────────────

    def perform_bod_reset(self):
        now_local = datetime.now(TZ_LOCAL)
        acc = self.account_state
        acc.bod_equity       = acc.total_equity
        acc.bod_timestamp    = now_local.isoformat()
        acc.max_total_equity = acc.total_equity
        acc.min_total_equity = acc.total_equity
        acc.daily_realized   = 0.0
        acc.daily_unrealized = 0.0
        acc.daily_pnl        = 0.0
        acc.daily_pnl_percent = 0.0
        self.portfolio.dd_baseline_equity = acc.total_equity

        # SOW reset on Monday
        if now_local.weekday() == 0:
            acc.sow_equity    = acc.total_equity
            acc.sow_timestamp = now_local.isoformat()
            self.portfolio.total_weekly_pnl = 0.0
            self.portfolio.total_weekly_pnl_percent = 0.0
            self.portfolio.weekly_pnl_state = "ok"


# Module-level singleton
app_state = AppState()
