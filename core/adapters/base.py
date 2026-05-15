"""
BaseExchangeAdapter — shared infrastructure for all exchange adapters.

Provides: thread pool executor, CCXT instance creation, async helper.
"""
from __future__ import annotations

import asyncio
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional

import re as _re

import ccxt

from core.adapters.errors import (
    RateLimitError, AuthenticationError, ConnectionError,
    ValidationError, ExchangeError,
)

log = logging.getLogger("adapters.base")

# Shared thread pool for all blocking CCXT REST calls across adapters.
_REST_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="adapter-rest")


class BaseExchangeAdapter:
    """Base class with shared infrastructure for exchange adapters."""

    exchange_id: str = ""
    market_type: str = ""

    def __init__(self, api_key: str, api_secret: str, proxy: str = ""):
        self._api_key = api_key
        self._api_secret = api_secret
        self._proxy = proxy
        self._ex: Optional[ccxt.Exchange] = None
        self._markets_loaded: bool = False
        self._weight_tracker: Optional[Any] = None

    def _make_ccxt(self, exchange_class: str, options: Optional[Dict] = None) -> ccxt.Exchange:
        """Create a CCXT exchange instance."""
        params: Dict[str, Any] = {
            "apiKey": self._api_key,
            "secret": self._api_secret,
            "options": options or {},
            "enableRateLimit": True,
        }
        if self._proxy:
            params["proxies"] = {"http": self._proxy, "https": self._proxy}

        cls = getattr(ccxt, exchange_class)
        return cls(params)

    def _get_weight_tracker(self):
        """Lazy-init weight tracker."""
        if self._weight_tracker is None:
            try:
                from core.rate_limit.weight_tracker import WeightTracker
                self._weight_tracker = WeightTracker(
                    adapter_name=self.exchange_id,
                )
            except Exception:
                pass
        return self._weight_tracker

    async def _run(self, fn: Callable, *args, priority: str = "normal") -> Any:
        """Run a blocking CCXT call in the shared thread pool.

        Translates ccxt exceptions to neutral adapter error types at the
        boundary — consumers never need to import ccxt for error handling.
        """
        # v2.4: proactive weight tracking with priority-aware fan-out
        endpoint = getattr(fn, "__name__", "")
        tracker = self._get_weight_tracker()
        if tracker:
            cost = tracker.estimate_cost(endpoint)
            try:
                result = await tracker.reserve(cost, priority=priority)
                if result.blocked:
                    log.warning(
                        "Weight tracker blocked %s [%s] (%.0f%% of budget)",
                        endpoint, priority, result.current_pct * 100,
                    )
                    raise RateLimitError(
                        f"Weight budget exceeded ({result.current_pct:.0%}, priority={priority})",
                    )
                if result.throttled:
                    log.info(
                        "Weight tracker throttling %s [%s] for %dms (%.0f%%)",
                        endpoint, priority, result.delay_ms, result.current_pct * 100,
                    )
                    await asyncio.sleep(result.delay_ms / 1000)
            except RateLimitError:
                raise
            except Exception:
                pass  # tracker failure must not block requests

        loop = asyncio.get_event_loop()
        try:
            if args:
                return await loop.run_in_executor(_REST_POOL, fn, *args)
            return await loop.run_in_executor(_REST_POOL, fn)
        except (ccxt.RateLimitExceeded, ccxt.DDoSProtection) as e:
            # Parse "banned until <epoch_ms>" for precise retry hint
            match = _re.search(r"banned until (\d+)", str(e))
            retry_ms = int(match.group(1)) if match else None
            raise RateLimitError(str(e), retry_after_ms=retry_ms) from e
        except ccxt.AuthenticationError as e:
            raise AuthenticationError(str(e)) from e
        except (ccxt.NetworkError, ccxt.RequestTimeout) as e:
            raise ConnectionError(str(e)) from e
        except (ccxt.InvalidOrder, ccxt.InsufficientFunds) as e:
            raise ValidationError(str(e)) from e
        except (ccxt.ExchangeError, ccxt.ExchangeNotAvailable) as e:
            raise ExchangeError(str(e)) from e

    def get_ccxt_instance(self) -> ccxt.Exchange:
        """Return underlying CCXT instance (escape hatch)."""
        if self._ex is None:
            raise RuntimeError("Adapter not initialized — CCXT instance is None")
        return self._ex

    async def load_markets(self) -> None:
        """Load exchange market info (precision, limits, etc.)."""
        if self._markets_loaded:
            return
        await self._run(self._ex.load_markets)
        self._markets_loaded = True

    def get_precision(self, symbol: str) -> Dict[str, int]:
        """Return precision info for a symbol."""
        if not self._markets_loaded or symbol not in self._ex.markets:
            return {"price": 8, "amount": 8}
        market = self._ex.markets[symbol]
        prec = market.get("precision", {})
        return {
            "price": prec.get("price", 8),
            "amount": prec.get("amount", 8),
        }

    def round_price(self, symbol: str, price: float) -> float:
        """Round price to exchange-required precision."""
        prec = self.get_precision(symbol)
        decimals = prec["price"]
        if isinstance(decimals, int) and decimals >= 0:
            factor = 10 ** decimals
            return math.floor(price * factor) / factor
        return price

    def round_amount(self, symbol: str, amount: float) -> float:
        """Round amount to exchange-required precision."""
        prec = self.get_precision(symbol)
        decimals = prec["amount"]
        if isinstance(decimals, int) and decimals >= 0:
            factor = 10 ** decimals
            return math.floor(amount * factor) / factor
        return amount

    def normalize_symbol(self, raw_symbol: str) -> str:
        """Default: uppercase, strip delimiters. Override for exchange-specific formats."""
        return raw_symbol.upper().replace("/", "").replace("-", "").replace(" ", "")

    def denormalize_symbol(self, unified_symbol: str) -> str:
        """Default: passthrough. Override for exchanges needing different format."""
        return unified_symbol
