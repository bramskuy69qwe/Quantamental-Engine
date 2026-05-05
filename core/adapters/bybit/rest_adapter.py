"""
Bybit Linear Perpetual REST adapter.

Wraps Bybit V5 API calls behind the ExchangeAdapter protocol using CCXT.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from core.adapters.base import BaseExchangeAdapter
from core.adapters.registry import register_adapter
from core.adapters.protocols import (
    NormalizedAccount,
    NormalizedIncome,
    NormalizedOrder,
    NormalizedPosition,
    NormalizedTrade,
)
from core.adapters.bybit.constants import OHLCV_LIMIT, ORDER_TYPE_FROM_BYBIT

log = logging.getLogger("adapters.bybit.rest")


@register_adapter("bybit", "linear_perpetual")
class BybitLinearAdapter(BaseExchangeAdapter):
    """Bybit Linear Perpetual (USDT) REST adapter."""

    exchange_id = "bybit"
    market_type = "linear_perpetual"

    def __init__(self, api_key: str, api_secret: str, proxy: str = ""):
        super().__init__(api_key, api_secret, proxy)
        self._ex = self._make_ccxt("bybit", {
            "defaultType": "linear",
        })

    @property
    def ohlcv_limit(self) -> int:
        return OHLCV_LIMIT

    # ── Account ──────────────────────────────────────────────────────────────

    async def fetch_account(self) -> NormalizedAccount:
        def _fetch():
            return self._ex.fetch_balance(params={"type": "unified"})

        raw = await self._run(_fetch)
        info = raw.get("info", {})

        # Bybit V5 unified account structure
        result = info.get("result", {})
        account_list = result.get("list", [{}])
        account = account_list[0] if account_list else {}

        total_equity = float(account.get("totalEquity", 0) or 0)
        available = float(account.get("totalAvailableBalance", 0) or 0)
        unrealized = float(account.get("totalPerpUPL", 0) or 0)
        initial_margin = float(account.get("totalInitialMargin", 0) or 0)
        maint_margin = float(account.get("totalMaintenanceMargin", 0) or 0)

        # Try USDT coin entry for wallet balance
        coins = account.get("coin", [])
        for coin in coins:
            if coin.get("coin") == "USDT":
                total_equity = float(coin.get("equity", total_equity) or total_equity)
                available = float(coin.get("availableToWithdraw", available) or available)
                unrealized = float(coin.get("unrealisedPnl", unrealized) or unrealized)
                break

        return NormalizedAccount(
            total_equity=total_equity,
            available_margin=available,
            unrealized_pnl=unrealized,
            initial_margin=initial_margin,
            maint_margin=maint_margin,
            fee_tier="",
            maker_fee=0.0002,  # Bybit default VIP0
            taker_fee=0.00055,  # Bybit default VIP0
        )

    # ── Positions ────────────────────────────────────────────────────────────

    async def fetch_positions(self) -> List[NormalizedPosition]:
        def _fetch():
            return self._ex.fetch_positions(params={"settleCoin": "USDT"})

        raw_list = await self._run(_fetch)
        positions = []
        for r in raw_list or []:
            contracts = float(r.get("contracts", 0) or 0)
            if contracts == 0:
                continue

            side_raw = r.get("side", "")
            side = "LONG" if side_raw == "long" else "SHORT"

            positions.append(NormalizedPosition(
                symbol=self.normalize_symbol(r.get("symbol", "")),
                side=side,
                size=contracts,
                contract_size=float(r.get("contractSize", 1) or 1),
                entry_price=float(r.get("entryPrice", 0) or 0),
                mark_price=float(r.get("markPrice", 0) or 0),
                liquidation_price=float(r.get("liquidationPrice", 0) or 0),
                unrealized_pnl=float(r.get("unrealizedPnl", 0) or 0),
                initial_margin=float(r.get("initialMargin", 0) or 0),
                notional=float(r.get("notional", 0) or 0),
            ))
        return positions

    # ── Open orders ──────────────────────────────────────────────────────────

    async def fetch_open_orders(self) -> List[NormalizedOrder]:
        def _fetch():
            return self._ex.fetch_open_orders(params={"category": "linear"})

        raw_orders = await self._run(_fetch)
        orders = []
        for o in raw_orders or []:
            otype = o.get("type", "")
            # CCXT normalizes Bybit order types; also check stopOrderType
            info = o.get("info", {})
            stop_order_type = info.get("stopOrderType", "")
            if stop_order_type == "TakeProfit":
                unified_type = "take_profit"
            elif stop_order_type in ("StopLoss", "Stop"):
                unified_type = "stop_loss"
            else:
                unified_type = ORDER_TYPE_FROM_BYBIT.get(otype, otype.lower())

            orders.append(NormalizedOrder(
                symbol=self.normalize_symbol(o.get("symbol", "")),
                order_type=unified_type,
                stop_price=float(o.get("stopPrice", 0) or 0),
                quantity=float(o.get("amount", 0) or 0),
                side=o.get("side", "").upper(),
            ))
        return orders

    # ── User trades ──────────────────────────────────────────────────────────

    async def fetch_user_trades(self, symbol: str, limit: int = 200) -> List[NormalizedTrade]:
        def _fetch():
            return self._ex.fetch_my_trades(
                symbol, limit=limit, params={"category": "linear"}
            )

        raw = await self._run(_fetch)
        trades = []
        for t in raw or []:
            trades.append(NormalizedTrade(
                symbol=self.normalize_symbol(t.get("symbol", "")),
                side=t.get("side", "").upper(),
                price=float(t.get("price", 0) or 0),
                quantity=float(t.get("amount", 0) or 0),
                fee=float(t.get("fee", {}).get("cost", 0) or 0) if isinstance(t.get("fee"), dict) else 0,
                timestamp_ms=int(t.get("timestamp", 0)),
                trade_id=str(t.get("id", "")),
            ))
        return trades

    # ── Income history ───────────────────────────────────────────────────────

    async def fetch_income(
        self,
        income_type: str = "",
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        limit: int = 1000,
    ) -> List[NormalizedIncome]:
        """Fetch closed PnL via Bybit V5 get-closed-pnl endpoint."""
        def _fetch():
            params = {"category": "linear", "limit": min(limit, 100)}
            if start_ms is not None:
                params["startTime"] = start_ms
            if end_ms is not None:
                params["endTime"] = end_ms
            # Use private V5 closed-pnl endpoint
            return self._ex.private_get_v5_position_closed_pnl(params=params)

        try:
            raw = await self._run(_fetch)
            result_list = raw.get("result", {}).get("list", [])
        except Exception as e:
            log.warning("Bybit fetch_income failed: %s", e)
            return []

        results = []
        for r in result_list:
            results.append(NormalizedIncome(
                symbol=self.normalize_symbol(r.get("symbol", "")),
                income_type="realized_pnl",
                amount=float(r.get("closedPnl", 0) or 0),
                timestamp_ms=int(r.get("updatedTime", 0) or 0),
                trade_id=str(r.get("orderId", "")),
            ))
        return results

    # ── Aggregate trades ─────────────────────────────────────────────────────

    async def fetch_agg_trades(self, symbol: str, start_ms: int, end_ms: int) -> List[Dict]:
        """Bybit V5 public trades — returns raw dicts with 'p' and 'T' keys for compatibility."""
        def _fetch():
            return self._ex.fetch_trades(symbol, since=start_ms, limit=1000,
                                         params={"category": "linear"})

        raw = await self._run(_fetch)
        # Normalize to same format as Binance aggTrades for _agg_extremes compatibility
        return [
            {"p": str(t.get("price", 0)), "T": t.get("timestamp", 0)}
            for t in (raw or [])
            if t.get("timestamp", 0) <= end_ms
        ]

    # ── OHLCV ────────────────────────────────────────────────────────────────

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str = "4h", limit: int = 200, since_ms: Optional[int] = None
    ) -> List:
        def _fetch():
            kwargs = {"symbol": symbol, "timeframe": timeframe, "limit": min(limit, OHLCV_LIMIT)}
            if since_ms is not None:
                kwargs["since"] = since_ms
            return self._ex.fetch_ohlcv(**kwargs)

        return await self._run(_fetch)

    # ── Listen key (Bybit uses HMAC auth on WS connect, no listen key needed) ─

    async def create_listen_key(self) -> str:
        """Bybit authenticates WS via HMAC signature, not listen keys.
        Return a placeholder — the WS adapter handles auth differently."""
        return "bybit_ws_auth"

    async def keepalive_listen_key(self, key: str) -> None:
        """No-op for Bybit — WS auth doesn't expire like Binance listen keys."""
        pass

    # ── Funding rates ────────────────────────────────────────────────────────

    async def fetch_funding_rates(
        self, symbol: str, start_ms: int, end_ms: int, limit: int = 200
    ) -> List[Dict]:
        def _fetch():
            return self._ex.fetch_funding_rate_history(
                symbol, since=start_ms, limit=limit,
                params={"category": "linear", "endTime": end_ms}
            )

        try:
            raw = await self._run(_fetch)
            return [
                {
                    "symbol": r.get("symbol", ""),
                    "fundingRate": r.get("fundingRate", 0),
                    "fundingRateTimestamp": r.get("timestamp", 0),
                }
                for r in (raw or [])
            ]
        except Exception as e:
            log.warning("Bybit fetch_funding_rates failed: %s", e)
            return []

    # ── Symbol normalization ─────────────────────────────────────────────────

    def normalize_symbol(self, raw_symbol: str) -> str:
        """Bybit linear uses BTCUSDT format natively (same as unified)."""
        # CCXT may return BTC/USDT:USDT — strip to BTCUSDT
        return raw_symbol.replace("/", "").replace(":USDT", "").replace(":USD", "").upper()

    def denormalize_symbol(self, unified_symbol: str) -> str:
        """Convert unified BTCUSDT to CCXT format BTC/USDT:USDT for Bybit linear."""
        # For most CCXT Bybit calls, the plain symbol works
        # But fetch_positions etc. may need the CCXT format
        return unified_symbol
