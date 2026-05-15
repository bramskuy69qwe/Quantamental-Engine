"""
Proactive API weight tracker for exchange adapters.

Tracks estimated weight consumption per rolling window and provides
reserve/throttle/block decisions BEFORE requests are sent.

v2.4 scope: client-side estimation only. Server-side header
reconciliation (X-MBX-USED-WEIGHT-1M) deferred to v2.5 — CCXT
abstracts the HTTP layer, making per-response header access non-trivial.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

log = logging.getLogger("weight_tracker")


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
    """Per-adapter rolling-window weight tracker.

    Thread-safe via asyncio.Lock. Shared across all callers of the
    same adapter instance.
    """

    def __init__(
        self,
        adapter_name: str = "",
        max_weight: int = 1200,
        window_seconds: int = 60,
        warn_pct: float = 0.70,
        throttle_pct: float = 0.85,
        block_pct: float = 0.95,
    ) -> None:
        self.adapter_name = adapter_name
        self.max_weight = max_weight
        self.window_seconds = window_seconds
        self.warn_pct = warn_pct
        self.throttle_pct = throttle_pct
        self.block_pct = block_pct
        self._budget = WeightBudget(
            max_weight=max_weight, window_seconds=window_seconds
        )
        self._lock = asyncio.Lock()

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _maybe_reset_window(self) -> None:
        """Reset weight counter if the window has expired."""
        now = self._now_ms()
        elapsed = now - self._budget.window_start_ms
        if elapsed >= self.window_seconds * 1000:
            self._budget.current_weight = 0
            self._budget.window_start_ms = now

    def estimate_cost(self, endpoint: str) -> int:
        """Look up estimated weight for an endpoint. Default 1."""
        return _BINANCE_WEIGHTS.get(endpoint, 1)

    async def reserve(self, cost: int) -> ReserveResult:
        """Reserve weight budget. Returns decision (ok/throttled/blocked)."""
        async with self._lock:
            self._maybe_reset_window()

            if self._budget.window_start_ms == 0:
                self._budget.window_start_ms = self._now_ms()

            projected = self._budget.current_weight + cost
            pct = projected / self.max_weight if self.max_weight > 0 else 1.0

            if pct >= self.block_pct:
                return ReserveResult(
                    ok=False, blocked=True, current_pct=pct,
                )

            if pct >= self.throttle_pct:
                # Delay until window resets
                elapsed = self._now_ms() - self._budget.window_start_ms
                remaining = max(0, self.window_seconds * 1000 - elapsed)
                delay = max(remaining // 2, 500)  # at least 500ms
                self._budget.current_weight = projected
                return ReserveResult(
                    ok=True, throttled=True, delay_ms=delay, current_pct=pct,
                )

            self._budget.current_weight = projected
            return ReserveResult(ok=True, current_pct=pct)

    def reconcile(self, used_weight: int, reset_time_ms: int = 0) -> None:
        """Update from server-side response header.

        v2.4: not called in production (CCXT abstracts headers).
        Available for future wiring or manual correction.
        """
        self._budget.current_weight = used_weight
        if reset_time_ms:
            self._budget.window_start_ms = reset_time_ms

    def current_pct(self) -> float:
        """Current weight usage as fraction of max (0.0 to 1.0+)."""
        self._maybe_reset_window()
        return self._budget.current_weight / self.max_weight if self.max_weight > 0 else 0.0

    @property
    def current_weight(self) -> int:
        self._maybe_reset_window()
        return self._budget.current_weight
