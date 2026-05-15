"""
MEXC Futures REST adapter — read-only via capability flags.

First user of the v2.4 capability system (Task 9). orders=False means
the calculator gate blocks sizing recommendations for MEXC accounts.
The engine observes positions, fills, and orders but cannot place trades.

Uses CCXT (ccxt.mexc with defaultType=swap) for consistency with
Binance/Bybit adapters.

Auth: HMAC-SHA256 signature in headers (ApiKey, Request-Time, Signature).
Base URL: https://contract.mexc.com (routed via CCXT).
Rate limits: 20 requests / 2 seconds per endpoint category.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from core.adapters.base import BaseExchangeAdapter
from core.adapters.registry import register_adapter
from core.adapters.protocols import (
    NormalizedAccount,
    NormalizedPosition,
    NormalizedOrder,
    NormalizedTrade,
    NormalizedIncome,
    NormalizedFundingRate,
)

log = logging.getLogger("adapters.mexc")

OHLCV_LIMIT = 2000


@register_adapter("mexc", "linear_perpetual")
class MexcLinearAdapter(BaseExchangeAdapter):
    """MEXC USDⓈ-M Futures REST adapter (read-only)."""

    exchange_id = "mexc"
    market_type = "linear_perpetual"

    # v2.4 Task 9: capability flags — read-only adapter
    capabilities = {
        "orders":            False,  # read-only — no order placement
        "conditional_orders": False,
        "market_data":       True,
        "account_query":     True,
        "position_query":    True,
        "historical_equity": False,  # no historical equity endpoint
    }

    def __init__(self, api_key: str, api_secret: str, proxy: str = ""):
        super().__init__(api_key, api_secret, proxy)
        self._ex = self._make_ccxt("mexc", {
            "defaultType": "swap",
        })

    @property
    def ohlcv_limit(self) -> int:
        return OHLCV_LIMIT

    # ── Account ──────────────────────────────────────────────────────────────

    async def fetch_account(self) -> NormalizedAccount:
        raw = await self._run(self._ex.fetch_balance)
        usdt = raw.get("USDT", raw.get("total", {}))
        return NormalizedAccount(
            currency="USDT",
            total_equity=float(usdt.get("total", 0) or 0),
            available_margin=float(usdt.get("free", 0) or 0),
            unrealized_pnl=0.0,  # CCXT doesn't split this for MEXC
        )

    # ── Positions ────────────────────────────────────────────────────────────

    async def fetch_positions(self) -> List[NormalizedPosition]:
        raw = await self._run(self._ex.fetch_positions)
        positions = []
        for p in raw:
            size = abs(float(p.get("contracts", 0) or 0))
            if size == 0:
                continue
            side = p.get("side", "").upper()
            if side not in ("LONG", "SHORT"):
                side = "LONG" if float(p.get("contracts", 0) or 0) > 0 else "SHORT"
            positions.append(NormalizedPosition(
                symbol=p.get("symbol", ""),
                side=side,
                size=size,
                entry_price=float(p.get("entryPrice", 0) or 0),
                mark_price=float(p.get("markPrice", 0) or 0),
                liquidation_price=float(p.get("liquidationPrice", 0) or 0),
                unrealized_pnl=float(p.get("unrealizedPnl", 0) or 0),
                initial_margin=float(p.get("initialMargin", 0) or 0),
                notional=float(p.get("notional", 0) or 0),
                position_id=str(p.get("id", "")),
            ))
        return positions

    # ── Orders ───────────────────────────────────────────────────────────────

    async def fetch_open_orders(self) -> List[NormalizedOrder]:
        raw = await self._run(self._ex.fetch_open_orders)
        orders = []
        for o in raw:
            orders.append(NormalizedOrder(
                exchange_order_id=str(o.get("id", "")),
                client_order_id=str(o.get("clientOrderId", "")),
                symbol=o.get("symbol", ""),
                side=(o.get("side", "") or "").upper(),
                order_type=(o.get("type", "") or "").lower(),
                status=(o.get("status", "") or "").lower(),
                price=float(o.get("price", 0) or 0),
                stop_price=float(o.get("stopPrice", 0) or 0),
                quantity=float(o.get("amount", 0) or 0),
                filled_qty=float(o.get("filled", 0) or 0),
                avg_fill_price=float(o.get("average", 0) or 0),
                created_at_ms=int(o.get("timestamp", 0) or 0),
                updated_at_ms=int(o.get("lastTradeTimestamp", 0) or 0),
            ))
        return orders

    # ── Trades / Fills ───────────────────────────────────────────────────────

    async def fetch_user_trades(self, symbol: str, limit: int = 200) -> List[NormalizedTrade]:
        raw = await self._run(self._ex.fetch_my_trades, symbol, None, limit)
        trades = []
        for t in raw:
            trades.append(NormalizedTrade(
                exchange_fill_id=str(t.get("id", "")),
                exchange_order_id=str(t.get("order", "")),
                symbol=t.get("symbol", ""),
                side=(t.get("side", "") or "").upper(),
                price=float(t.get("price", 0) or 0),
                quantity=float(t.get("amount", 0) or 0),
                fee=abs(float((t.get("fee") or {}).get("cost", 0) or 0)),
                fee_asset=(t.get("fee") or {}).get("currency", "USDT"),
                role="maker" if t.get("takerOrMaker") == "maker" else "taker",
                timestamp_ms=int(t.get("timestamp", 0) or 0),
            ))
        return trades

    # ── Market Data ──────────────────────────────────────────────────────────

    async def load_markets(self) -> None:
        if self._markets_loaded:
            return
        await self._run(self._ex.load_markets)
        self._markets_loaded = True

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str = "4h", limit: int = 220,
        since_ms: Optional[int] = None,
    ) -> List:
        return await self._run(
            self._ex.fetch_ohlcv, symbol, timeframe, since_ms, limit
        )

    async def fetch_orderbook(self, symbol: str, limit: int = 20) -> Dict:
        raw = await self._run(self._ex.fetch_order_book, symbol, limit)
        return {
            "bids": raw.get("bids", []),
            "asks": raw.get("asks", []),
        }

    async def fetch_mark_price(self, symbol: str) -> float:
        ticker = await self._run(self._ex.fetch_ticker, symbol)
        return float(ticker.get("last", 0) or 0)

    async def fetch_server_time(self) -> int:
        import time
        return int(time.time() * 1000)

    async def fetch_income(
        self, income_type: str = "", start_ms: Optional[int] = None,
        end_ms: Optional[int] = None, limit: int = 1000,
    ) -> List[NormalizedIncome]:
        # MEXC doesn't have a direct income endpoint via CCXT;
        # return empty — equity reconstruction not supported for MEXC
        return []

    async def fetch_current_funding_rates(
        self, symbols: List[str]
    ) -> Dict[str, NormalizedFundingRate]:
        result = {}
        for symbol in symbols:
            try:
                raw = await self._run(self._ex.fetch_funding_rate, symbol)
                result[symbol] = NormalizedFundingRate(
                    symbol=symbol,
                    funding_rate=float(raw.get("fundingRate", 0) or 0),
                    next_funding_time_ms=int(raw.get("fundingTimestamp", 0) or 0),
                    mark_price=float(raw.get("markPrice", 0) or 0),
                )
            except Exception:
                pass
        return result

    async def fetch_price_extremes(
        self, symbol: str, start_ms: int, end_ms: int,
        precision: str = "auto",
    ) -> Tuple[Optional[float], Optional[float]]:
        try:
            candles = await self.fetch_ohlcv(symbol, "1h", 500, since_ms=start_ms)
            if not candles:
                return None, None
            highs = [c[2] for c in candles if c[0] <= end_ms]
            lows = [c[3] for c in candles if c[0] <= end_ms]
            return (max(highs) if highs else None, min(lows) if lows else None)
        except Exception:
            return None, None

    def get_precision(self, symbol: str) -> Dict[str, int]:
        if not self._markets_loaded or symbol not in self._ex.markets:
            return {"price": 8, "amount": 8}
        market = self._ex.markets[symbol]
        prec = market.get("precision", {})
        return {"price": prec.get("price", 8), "amount": prec.get("amount", 8)}

    def round_price(self, symbol: str, price: float) -> float:
        import math
        prec = self.get_precision(symbol)
        d = prec["price"]
        if isinstance(d, int) and d >= 0:
            f = 10 ** d
            return math.floor(price * f) / f
        return price

    def round_amount(self, symbol: str, amount: float) -> float:
        import math
        prec = self.get_precision(symbol)
        d = prec["amount"]
        if isinstance(d, int) and d >= 0:
            f = 10 ** d
            return math.floor(amount * f) / f
        return amount

    def normalize_symbol(self, raw_symbol: str) -> str:
        return raw_symbol

    def denormalize_symbol(self, unified_symbol: str) -> str:
        return unified_symbol

    def get_ccxt_instance(self):
        return self._ex
