"""
Binance USD-M Futures REST adapter.

Wraps all Binance-specific fapiPrivate* calls behind the ExchangeAdapter protocol.
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
from core.adapters.binance.constants import OHLCV_LIMIT, ORDER_TYPE_FROM_BINANCE

log = logging.getLogger("adapters.binance.rest")


@register_adapter("binance", "linear_perpetual")
class BinanceUSDMAdapter(BaseExchangeAdapter):
    """Binance USD-M Futures REST adapter."""

    exchange_id = "binance"
    market_type = "linear_perpetual"

    def __init__(self, api_key: str, api_secret: str, proxy: str = ""):
        super().__init__(api_key, api_secret, proxy)
        self._ex = self._make_ccxt("binanceusdm", {
            "defaultType": "future",
            "fetchCurrencies": False,
        })

    @property
    def ohlcv_limit(self) -> int:
        return OHLCV_LIMIT

    # ── Account ──────────────────────────────────────────────────────────────

    async def fetch_account(self) -> NormalizedAccount:
        # /fapi/v2/account has balances + feeTier but NOT commission rates.
        # /fapi/v1/commissionRate (per-symbol) has the actual maker/taker rates.
        def _fetch():
            account = self._ex.fapiPrivateV2GetAccount()
            # Fetch commission rates for BTCUSDT as representative rate
            try:
                comm = self._ex.fapiPrivateGetCommissionRate({"symbol": "BTCUSDT"})
            except Exception:
                comm = {}
            return account, comm

        info, comm = await self._run(_fetch)
        return NormalizedAccount(
            total_equity=float(info.get("totalWalletBalance", 0) or 0),
            available_margin=float(info.get("availableBalance", 0) or 0),
            unrealized_pnl=float(info.get("totalUnrealizedProfit", 0) or 0),
            initial_margin=float(info.get("totalInitialMargin", 0) or 0),
            maint_margin=float(info.get("totalMaintMargin", 0) or 0),
            fee_tier=str(info.get("feeTier", "")),
            maker_fee=float(comm.get("makerCommissionRate", 0) or 0),
            taker_fee=float(comm.get("takerCommissionRate", 0) or 0),
        )

    # ── Positions ────────────────────────────────────────────────────────────

    async def fetch_positions(self) -> List[NormalizedPosition]:
        def _fetch():
            account = self._ex.fapiPrivateV2GetAccount()
            return account.get("positions", [])

        raw_list = await self._run(_fetch)
        positions = []
        for r in raw_list or []:
            amt = float(r.get("positionAmt", 0) or 0)
            if amt == 0:
                continue
            positions.append(NormalizedPosition(
                symbol=r.get("symbol", ""),
                side="LONG" if amt > 0 else "SHORT",
                size=abs(amt),
                contract_size=1.0,
                entry_price=float(r.get("entryPrice", 0) or 0),
                mark_price=float(r.get("markPrice", 0) or 0),
                liquidation_price=float(r.get("liquidationPrice", 0) or 0),
                unrealized_pnl=float(r.get("unrealizedProfit", 0) or 0),
                initial_margin=float(r.get("initialMargin", 0) or 0),
                notional=abs(float(r.get("notional", 0) or 0)),
            ))
        return positions

    # ── Open orders ──────────────────────────────────────────────────────────

    async def fetch_open_orders(self) -> List[NormalizedOrder]:
        def _fetch():
            return self._ex.fapiPrivateGetOpenOrders() or []

        raw_orders = await self._run(_fetch)
        orders = []
        for o in raw_orders:
            otype = o.get("type", "")
            unified_type = ORDER_TYPE_FROM_BINANCE.get(otype, otype.lower())
            orders.append(NormalizedOrder(
                symbol=o.get("symbol", ""),
                order_type=unified_type,
                stop_price=float(o.get("stopPrice", 0) or 0),
                quantity=float(o.get("origQty", 0) or 0),
                side=o.get("side", ""),
            ))
        return orders

    # ── User trades ──────────────────────────────────────────────────────────

    async def fetch_user_trades(self, symbol: str, limit: int = 200) -> List[NormalizedTrade]:
        def _fetch():
            return self._ex.fapiPrivateGetUserTrades(
                params={"symbol": symbol, "limit": limit}
            ) or []

        raw = await self._run(_fetch)
        trades = []
        for t in raw:
            trades.append(NormalizedTrade(
                symbol=t.get("symbol", ""),
                side=t.get("side", ""),
                price=float(t.get("price", 0) or 0),
                quantity=float(t.get("qty", 0) or 0),
                fee=float(t.get("commission", 0) or 0),
                timestamp_ms=int(t.get("time", 0)),
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
        def _fetch():
            params: Dict = {"limit": limit}
            if income_type:
                params["incomeType"] = income_type
            if start_ms is not None:
                params["startTime"] = start_ms
            if end_ms is not None:
                params["endTime"] = end_ms
            return self._ex.fapiPrivateGetIncome(params=params) or []

        raw = await self._run(_fetch)
        results = []
        for r in raw:
            results.append(NormalizedIncome(
                symbol=r.get("symbol", ""),
                income_type=r.get("incomeType", "").lower(),
                amount=float(r.get("income", 0) or 0),
                timestamp_ms=int(r.get("time", 0)),
                trade_id=str(r.get("tradeId", "")),
            ))
        return results

    # ── Aggregate trades ─────────────────────────────────────────────────────

    async def fetch_agg_trades(self, symbol: str, start_ms: int, end_ms: int) -> List[Dict]:
        def _fetch():
            return self._ex.fapiPublicGetAggTrades(params={
                "symbol": symbol,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 1000,
            }) or []

        return await self._run(_fetch)

    # ── OHLCV ────────────────────────────────────────────────────────────────

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str = "4h", limit: int = 220, since_ms: Optional[int] = None
    ) -> List:
        def _fetch():
            kwargs = {"symbol": symbol, "timeframe": timeframe, "limit": limit}
            if since_ms is not None:
                kwargs["since"] = since_ms
            return self._ex.fetch_ohlcv(**kwargs)

        return await self._run(_fetch)

    # ── Listen key ───────────────────────────────────────────────────────────

    async def create_listen_key(self) -> str:
        def _create():
            resp = self._ex.fapiPrivatePostListenKey()
            return resp.get("listenKey", "")

        return await self._run(_create)

    async def keepalive_listen_key(self, key: str) -> None:
        def _keepalive():
            self._ex.fapiPrivatePutListenKey({"listenKey": key})

        await self._run(_keepalive)

    # ── Current funding rates (live) ─────────────────────────────────────────

    async def fetch_current_funding_rates(self, symbols: List[str]) -> Dict[str, Dict]:
        """Fetch live funding rate + next funding time + mark price via premiumIndex."""
        if not symbols:
            return {}

        def _fetch():
            return self._ex.fapiPublicGetPremiumIndex() or []

        try:
            raw_list = await self._run(_fetch)
        except Exception:
            return {s: {"funding_rate": 0.0, "next_funding_time": 0, "mark_price": 0.0} for s in symbols}

        wanted = set(symbols)
        results: Dict[str, Dict] = {}
        for raw in raw_list:
            sym = raw.get("symbol", "")
            if sym in wanted:
                results[sym] = {
                    "funding_rate": float(raw.get("lastFundingRate", 0) or 0),
                    "next_funding_time": int(raw.get("nextFundingTime", 0) or 0),
                    "mark_price": float(raw.get("markPrice", 0) or 0),
                }
        for s in symbols:
            if s not in results:
                results[s] = {"funding_rate": 0.0, "next_funding_time": 0, "mark_price": 0.0}
        return results

    # ── Historical funding rates (optional capability) ────────────────────────

    async def fetch_funding_rates(
        self, symbol: str, start_ms: int, end_ms: int, limit: int = 1000
    ) -> List[Dict]:
        def _fetch():
            return self._ex.fapiPublicGetFundingRate(params={
                "symbol": symbol,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": limit,
            }) or []

        return await self._run(_fetch)

    # ── Open interest history (optional capability) ──────────────────────────

    async def fetch_open_interest_hist(
        self, symbol: str, period: str, start_ms: int, end_ms: int, limit: int = 500
    ) -> List[Dict]:
        def _fetch():
            return self._ex.fapiDataGetOpenInterestHist(params={
                "symbol": symbol,
                "period": period,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": limit,
            }) or []

        return await self._run(_fetch)
