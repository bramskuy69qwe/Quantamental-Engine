"""
Proactive API weight tracker with priority-aware fan-out coordination.

Tracks estimated weight consumption per rolling window. Requests carry
a priority tier that determines threshold behavior:

  urgent     — real-time state (WS fallback, position refresh): never blocks
  normal     — periodic operations (startup, snapshots): standard thresholds
  background — batch operations (backfill, history): strictest thresholds

v2.4 scope: client-side estimation only. Server-side header
reconciliation (X-MBX-USED-WEIGHT-1M) deferred to v2.5.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Literal, Optional

log = logging.getLogger("weight_tracker")

Priority = Literal["urgent", "normal", "background"]


@dataclass
class WeightBudget:
    current_weight: int = 0
    max_weight: int = 1200
    window_start_ms: int = 0
    window_seconds: int = 60


@dataclass
class ReserveResult:
    ok: bool = True
    throttled: bool = False
    blocked: bool = False
    delay_ms: int = 0
    current_pct: float = 0.0
    priority: str = "normal"


# Per-priority threshold overrides: (throttle_pct, block_pct)
_PRIORITY_THRESHOLDS: Dict[str, tuple] = {
    "urgent":     (0.95, 1.01),   # throttle only at extreme; never blocks (> 100%)
    "normal":     (0.85, 0.95),   # standard thresholds
    "background": (0.70, 0.85),   # strictest — yields early for real-time traffic
}

# Per-priority throttle delay multiplier
_DELAY_MULTIPLIER: Dict[str, float] = {
    "urgent":     0.25,   # minimal delay
    "normal":     1.0,    # standard delay
    "background": 2.0,    # longer delay — let real-time traffic through
}


# Binance fAPI default endpoint weights
_BINANCE_WEIGHTS: Dict[str, int] = {
    "fetch_account": 5,
    "fetch_positions": 5,
    "fetch_open_orders": 40,
    "fetch_income": 30,
    "fetch_ohlcv": 5,
    "fetch_orderbook": 10,
    "fetch_mark_price": 1,
    "fetch_server_time": 1,
    "fetch_user_trades": 5,
    "fetch_exchange_trades": 5,
    "load_markets": 40,
    "fetch_funding_rates": 1,
    "fetch_price_extremes": 5,
}


class WeightTracker:
    """Per-adapter rolling-window weight tracker with priority fan-out.

    Thread-safe via asyncio.Lock. Shared across all callers of the
    same adapter instance.
    """

    def __init__(
        self,
        adapter_name: str = "",
        max_weight: int = 1200,
        window_seconds: int = 60,
    ) -> None:
        self.adapter_name = adapter_name
        self.max_weight = max_weight
        self.window_seconds = window_seconds
        self._budget = WeightBudget(
            max_weight=max_weight, window_seconds=window_seconds
        )
        self._lock = asyncio.Lock()

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _maybe_reset_window(self) -> None:
        now = self._now_ms()
        elapsed = now - self._budget.window_start_ms
        if elapsed >= self.window_seconds * 1000:
            self._budget.current_weight = 0
            self._budget.window_start_ms = now

    def estimate_cost(self, endpoint: str) -> int:
        return _BINANCE_WEIGHTS.get(endpoint, 1)

    async def reserve(
        self, cost: int, priority: Priority = "normal"
    ) -> ReserveResult:
        """Reserve weight budget with priority-aware thresholds."""
        async with self._lock:
            self._maybe_reset_window()

            if self._budget.window_start_ms == 0:
                self._budget.window_start_ms = self._now_ms()

            projected = self._budget.current_weight + cost
            pct = projected / self.max_weight if self.max_weight > 0 else 1.0

            throttle_t, block_t = _PRIORITY_THRESHOLDS.get(
                priority, (0.85, 0.95)
            )

            if pct >= block_t:
                return ReserveResult(
                    ok=False, blocked=True, current_pct=pct, priority=priority,
                )

            if pct >= throttle_t:
                elapsed = self._now_ms() - self._budget.window_start_ms
                remaining = max(0, self.window_seconds * 1000 - elapsed)
                base_delay = max(remaining // 2, 500)
                multiplier = _DELAY_MULTIPLIER.get(priority, 1.0)
                delay = int(base_delay * multiplier)

                self._budget.current_weight = projected
                return ReserveResult(
                    ok=True, throttled=True, delay_ms=delay,
                    current_pct=pct, priority=priority,
                )

            self._budget.current_weight = projected
            return ReserveResult(ok=True, current_pct=pct, priority=priority)

    def reconcile(self, used_weight: int, reset_time_ms: int = 0) -> None:
        """Update from server-side response header (v2.5)."""
        self._budget.current_weight = used_weight
        if reset_time_ms:
            self._budget.window_start_ms = reset_time_ms

    def current_pct(self) -> float:
        self._maybe_reset_window()
        return self._budget.current_weight / self.max_weight if self.max_weight > 0 else 0.0

    @property
    def current_weight(self) -> int:
        self._maybe_reset_window()
        return self._budget.current_weight
