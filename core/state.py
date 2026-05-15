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
from typing import Dict, List, Optional, Any, Set

import logging

import config

log = logging.getLogger("state")


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

PARAM_BOUNDS: Dict[str, tuple] = {
    "individual_risk_per_trade": (0.0001, 0.10),
    "max_w_loss_percent":        (0.001,  0.30),
    "max_dd_percent":            (0.01,   0.50),
    "max_exposure":              (0.1,    20.0),
    "max_position_count":        (1,      100),
    "max_correlated_exposure":   (0.05,   1.0),
    "auto_export_hours":         (1,      168),
    "weekly_loss_warning_pct":   (0.50,   0.99),
    "weekly_loss_limit_pct":     (0.50,   1.00),
    "max_dd_warning_pct":        (0.50,   0.99),
    "max_dd_limit_pct":          (0.50,   1.00),
}


def validate_params(params: Dict[str, Any]) -> List[str]:
    """Validate param values against PARAM_BOUNDS. Returns list of error messages."""
    errors = []
    for key, (lo, hi) in PARAM_BOUNDS.items():
        if key not in params:
            continue
        val = params[key]
        try:
            val = float(val)
        except (TypeError, ValueError):
            errors.append(f"{key}: must be a number")
            continue
        if val < lo or val > hi:
            errors.append(f"{key}: must be between {lo} and {hi} (got {val})")
    return errors


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
    position_id:             str   = ""     # broker-side position ID
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
    individual_fees:         float = 0.0  # cumulative fees, computed from fills DB (never accumulated in cache)
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
    dd_degraded:              bool  = False  # True when DD window has data gaps
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
    rate_limited_until: Optional[datetime] = None  # RL-1: 429/418 backoff
    logs:               List[str] = field(default_factory=list)

    def add_log(self, msg: str):
        try:
            from core.tz import now_in_account_tz
            ts = now_in_account_tz(AppState().active_account_id).strftime("%H:%M:%S")
        except Exception:
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
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

    @property
    def is_rate_limited(self) -> bool:
        """True when a 429/418 backoff is active."""
        return (
            self.rate_limited_until is not None
            and self.rate_limited_until > datetime.now(timezone.utc)
        )


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
        self._positions_legacy: List[PositionInfo] = []
        self._data_cache = None          # set by main.py after DataCache init
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

        # Rolling DD episode tracking (keyed by account_id)
        self.dd_episode_peaks: Dict[int, float] = {}
        self.dd_previous_states: Dict[int, str] = {}
        # Tracks which accounts have had would_have_blocked_dd logged this episode
        self.dd_would_have_blocked_logged: Set[int] = set()
        # Accounts where trader manually overrode the dd_state gate
        self.dd_manually_unblocked: Set[int] = set()

        # True while the background startup fetch is still in progress
        self.is_initializing: bool = True

        # Live regime state (updated by background loop every 10 min)
        self.current_regime: Optional[RegimeState] = None

        # ── Multi-account / multi-platform ────────────────────────────────────
        # SR-2: active_account_id is now a read-only @property backed by
        # account_registry.active_id.  All writes go through
        # account_registry.set_active().  See property definition below.
        self.active_platform:   str = "standalone"

    # ── SR-2: single-owner account identity ───────────────────────────────────

    @property
    def active_account_id(self) -> int:
        """Read-through to AccountRegistry — the sole owner of active account
        identity.  Returns 1 (safe default) before the registry is loaded."""
        from core.account_registry import account_registry
        return account_registry.active_id

    # ── DataCache-backed property for positions ────────────────────────────────

    @property
    def positions(self) -> List[PositionInfo]:
        if self._data_cache is not None:
            return self._data_cache.positions
        return self._positions_legacy

    @positions.setter
    def positions(self, value: List[PositionInfo]) -> None:
        if self._data_cache is not None:
            log.warning(
                "Direct write to app_state.positions bypasses DataCache — "
                "migrate caller to use data_cache.apply_*() methods"
            )
        self._positions_legacy = value

    def reset_for_account_switch(self, new_account_id: Optional[int] = None) -> None:
        """Clear all runtime state and load new account's params."""
        self.account_state        = AccountState()
        self._positions_legacy    = []
        if self._data_cache is not None:
            self._data_cache.clear()
        self.portfolio            = PortfolioStats()
        self.ohlcv_cache          = {}
        self.orderbook_cache      = {}
        self.mark_price_cache     = {}
        self.dd_episode_peaks     = {}
        self.dd_previous_states   = {}
        self.dd_would_have_blocked_logged = set()
        self.dd_manually_unblocked = set()
        self.exchange_trade_history = []
        self.pre_trade_log        = []
        self.is_initializing      = True
        self.current_regime       = None
        self.ws_status            = WSStatus()
        self.ws_status.add_log("State reset for account switch.")

        # Load per-account params and fees for the new account
        if new_account_id is not None:
            from core.account_registry import account_registry
            self.params = DEFAULT_PARAMS.copy()
            acct_params = account_registry.get_account_params(new_account_id)
            if acct_params:
                self.params.update(acct_params)
            maker, taker = account_registry.get_account_fees(new_account_id)
            self.exchange_info.maker_fee = maker
            self.exchange_info.taker_fee = taker

    # ── Parameter persistence ─────────────────────────────────────────────────

    def load_params(self):
        """Load params for the active account from the registry cache.
        Falls back to params.json (legacy) then defaults."""
        from core.account_registry import account_registry
        acct_params = account_registry.get_account_params(self.active_account_id)
        if acct_params:
            self.params = DEFAULT_PARAMS.copy()
            self.params.update(acct_params)
        elif os.path.exists(config.PARAMS_FILE):
            # Legacy fallback for first run before migration
            try:
                with open(config.PARAMS_FILE) as f:
                    saved = json.load(f)
                self.params.update(saved)
            except (ValueError, OSError, KeyError):
                pass

        # Also load per-account fees into exchange_info
        maker, taker = account_registry.get_account_fees(self.active_account_id)
        self.exchange_info.maker_fee = maker
        self.exchange_info.taker_fee = taker

    async def save_params_async(self) -> None:
        """Save params to DB for the active account."""
        from core.account_registry import account_registry
        await account_registry.update_account_params(self.active_account_id, self.params)

    def save_params(self):
        """Synchronous save — schedule the async version."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.save_params_async())
            else:
                loop.run_until_complete(self.save_params_async())
        except RuntimeError:
            pass  # no event loop — skip (startup edge case)

    # ── SR-3: recalculate_portfolio deleted (F4) ────────────────────────────────
    # All callers now use DataCache._recalculate_portfolio().
    # Direct access raises AttributeError (no method, no property).

    # ── SR-3: crash recovery — shared restore function ────────────────────────

    def restore_from_snapshot(self, snapshot: dict) -> None:
        """Restore the 10-field crash-recovery set from a DB snapshot dict.

        Called by main.py (startup) and routes_accounts.py (account switch).
        Fields restored:
          AccountState:   total_equity, balance_usdt, bod_equity, sow_equity,
                          max_total_equity, min_total_equity
          PortfolioStats: dd_baseline_equity (derived), drawdown,
                          dd_state, weekly_pnl_state (MP-1)
        """
        acc = self.account_state
        acc.total_equity     = snapshot.get("total_equity", 0.0)
        acc.balance_usdt     = snapshot.get("balance_usdt", 0.0)
        acc.bod_equity       = snapshot.get("bod_equity", 0.0)
        acc.sow_equity       = snapshot.get("sow_equity", 0.0)
        acc.max_total_equity = snapshot.get("max_total_equity", 0.0)
        acc.min_total_equity = snapshot.get("min_total_equity", 0.0)
        pf = self.portfolio
        pf.dd_baseline_equity = acc.bod_equity if acc.bod_equity > 0 else acc.total_equity
        pf.drawdown           = snapshot.get("drawdown", 0.0)
        # MP-1: restore gate states so they survive restart
        pf.dd_state           = snapshot.get("dd_state", "ok")
        pf.weekly_pnl_state   = snapshot.get("weekly_pnl_state", "ok")

    # ── BOD reset ─────────────────────────────────────────────────────────────

    def perform_bod_reset(self):
        from core.tz import now_in_account_tz
        now_local = now_in_account_tz(self.active_account_id)
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
