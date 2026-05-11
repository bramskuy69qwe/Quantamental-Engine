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
from core.adapters.binance.constants import (
    OHLCV_LIMIT,
    ORDER_TYPE_FROM_BINANCE,
    BINANCE_STATUS_MAP,
)

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
            raw_status = o.get("status", "")
            status = BINANCE_STATUS_MAP.get(raw_status, "new")
            if raw_status and raw_status not in BINANCE_STATUS_MAP:
                log.warning("Unmapped Binance order status: %s → defaulting to 'new'", raw_status)
            orders.append(NormalizedOrder(
                exchange_order_id=str(o.get("orderId", "")),
                client_order_id=o.get("clientOrderId", ""),
                symbol=o.get("symbol", ""),
                side=o.get("side", ""),
                order_type=unified_type,
                status=status,
                price=float(o.get("price", 0) or 0),
                stop_price=float(o.get("stopPrice", 0) or 0),
                quantity=float(o.get("origQty", 0) or 0),
                filled_qty=float(o.get("executedQty", 0) or 0),
                avg_fill_price=float(o.get("avgPrice", 0) or 0),
                reduce_only=bool(o.get("reduceOnly", False)),
                time_in_force=o.get("timeInForce", ""),
                position_side=o.get("positionSide", ""),
                created_at_ms=int(o.get("time", 0)),
                updated_at_ms=int(o.get("updateTime", 0)),
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
            tid = str(t.get("id", ""))
            trades.append(NormalizedTrade(
                exchange_fill_id=tid,
                exchange_order_id=str(t.get("orderId", "")),
                symbol=t.get("symbol", ""),
                side=t.get("side", ""),
                direction=t.get("positionSide", ""),
                price=float(t.get("price", 0) or 0),
                quantity=float(t.get("qty", 0) or 0),
                fee=float(t.get("commission", 0) or 0),
                fee_asset=t.get("commissionAsset", "USDT"),
                role="maker" if t.get("maker") else "taker",
                is_close=bool(float(t.get("realizedPnl", 0) or 0) != 0),
                realized_pnl=float(t.get("realizedPnl", 0) or 0),
                timestamp_ms=int(t.get("time", 0)),
                trade_id=tid,
            ))
        return trades

    # ── Order history ───────────────────────────────────────────────────────

    async def fetch_order_history(self, symbol: str = "", limit: int = 100) -> List[NormalizedOrder]:
        def _fetch():
            params: Dict = {"limit": limit}
            if symbol:
                params["symbol"] = symbol
            return self._ex.fapiPrivateGetAllOrders(params=params) or []

        raw_orders = await self._run(_fetch)
        orders = []
        for o in raw_orders:
            otype = o.get("type", "")
            unified_type = ORDER_TYPE_FROM_BINANCE.get(otype, otype.lower())
            raw_status = o.get("status", "")
            status = BINANCE_STATUS_MAP.get(raw_status, "new")
            if raw_status and raw_status not in BINANCE_STATUS_MAP:
                log.warning("Unmapped Binance order status: %s → defaulting to 'new'", raw_status)
            orders.append(NormalizedOrder(
                exchange_order_id=str(o.get("orderId", "")),
                client_order_id=o.get("clientOrderId", ""),
                symbol=o.get("symbol", ""),
                side=o.get("side", ""),
                order_type=unified_type,
                status=status,
                price=float(o.get("price", 0) or 0),
                stop_price=float(o.get("stopPrice", 0) or 0),
                quantity=float(o.get("origQty", 0) or 0),
                filled_qty=float(o.get("executedQty", 0) or 0),
                avg_fill_price=float(o.get("avgPrice", 0) or 0),
                reduce_only=bool(o.get("reduceOnly", False)),
                time_in_force=o.get("timeInForce", ""),
                position_side=o.get("positionSide", ""),
                created_at_ms=int(o.get("time", 0)),
                updated_at_ms=int(o.get("updateTime", 0)),
            ))
        return orders

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

    # ── Price extremes (replaces fetch_agg_trades) ─────────────────────────────

    async def fetch_price_extremes(
        self,
        symbol: str,
        start_ms: int,
        end_ms: int,
        precision: str = "auto",
    ) -> tuple:
        """Return (max_price, min_price) for the time window.

        Multi-resolution strategy based on precision hint:
          "high"  / "auto" + duration < 3 min → aggTrades (tick-level)
          "medium" / "auto" + 3 min-12 hr → hybrid (entry/exit aggTrades + 1m body)
          "low"  / "auto" + >= 12 hr → hybrid (agg + 1m + 1h sections)
        Falls back to OHLCV if aggTrades returns empty.
        """
        import asyncio as _aio
        from core.adapters.errors import RateLimitError
        from core.state import app_state

        _3_MIN = 3 * 60_000
        _12_HR = 12 * 3_600_000
        _1_HR = 3_600_000
        _60_S = 60_000
        _BUF = 1_000  # 1s buffer for Binance exclusive endTime

        duration = end_ms - start_ms

        # Choose resolution
        if precision == "high" or (precision == "auto" and duration < _3_MIN):
            use_tier = 1
        elif precision == "medium" or (precision == "auto" and duration <= _12_HR):
            use_tier = 2
        elif precision == "low" or (precision == "auto" and duration > _12_HR):
            use_tier = 3
        else:
            use_tier = 2  # fallback

        # ── Helpers ───────────────────────────────────────────────────────────

        async def _agg_extremes(start: int, end: int) -> tuple:
            """Paginated aggTrades → (max, min) in O(1) memory."""
            effective_end = end + _BUF
            max_p = None
            min_p = None
            cursor = max(0, start - _BUF)
            try:
                while cursor <= effective_end:
                    if app_state.ws_status.is_rate_limited:
                        return None, None
                    def _fetch(c=cursor):
                        return self._ex.fapiPublicGetAggTrades(params={
                            "symbol": symbol,
                            "startTime": c,
                            "endTime": effective_end,
                            "limit": 1000,
                        }) or []
                    batch = await self._run(_fetch)
                    if not batch:
                        break
                    for t in batch:
                        price = float(t["p"])
                        if max_p is None or price > max_p:
                            max_p = price
                        if min_p is None or price < min_p:
                            min_p = price
                    last_ts = int(batch[-1]["T"])
                    if last_ts >= effective_end or len(batch) < 1000:
                        break
                    cursor = last_ts + 1
                    await _aio.sleep(0.25)
            except RateLimitError:
                raise  # Let caller handle
            except Exception:
                return None, None
            return max_p, min_p

        async def _ohlcv_hl(start: int, end: int, tf: str) -> tuple:
            """OHLCV → (max_high, min_low)."""
            if start >= end:
                return None, None
            all_candles = []
            cursor = start
            while cursor < end:
                def _fetch(c=cursor):
                    return self._ex.fetch_ohlcv(symbol, tf, since=c, limit=1000) or []
                batch = await self._run(_fetch)
                if not batch:
                    break
                all_candles.extend([c for c in batch if c[0] <= end])
                if batch[-1][0] >= end or len(batch) < 1000:
                    break
                cursor = batch[-1][0] + 1
            if not all_candles:
                return None, None
            return max(c[2] for c in all_candles), min(c[3] for c in all_candles)

        def _merge(*pairs) -> tuple:
            highs = [h for h, l in pairs if h is not None]
            lows = [l for h, l in pairs if l is not None]
            if not highs:
                return None, None
            return max(highs), min(lows)

        # ── Tier 1: all aggTrades ─────────────────────────────────────────────
        if use_tier == 1:
            high, low = await _agg_extremes(start_ms, end_ms)
            if high is not None:
                return high, low
            return await _ohlcv_hl(start_ms, end_ms, "1m")

        # ── Tier 2: entry agg + body 1m + exit agg ───────────────────────────
        if use_tier == 2:
            results = await _aio.gather(
                _agg_extremes(start_ms, start_ms + _60_S),
                _ohlcv_hl(start_ms + _60_S, end_ms - _60_S, "1m"),
                _agg_extremes(end_ms - _60_S, end_ms),
                return_exceptions=True,
            )
            if any(isinstance(v, BaseException) for v in results):
                return await _ohlcv_hl(start_ms, end_ms, "1m")
            high, low = _merge(*results)
            if high is not None:
                return high, low
            return await _ohlcv_hl(start_ms, end_ms, "1m")

        # ── Tier 3: 5-section hybrid ─────────────────────────────────────────
        e1m_end = start_ms + _1_HR
        x1m_start = max(end_ms - _1_HR, e1m_end)
        results = await _aio.gather(
            _agg_extremes(start_ms, start_ms + _60_S),
            _ohlcv_hl(start_ms + _60_S, e1m_end, "1m"),
            _ohlcv_hl(e1m_end, x1m_start, "1h"),
            _ohlcv_hl(x1m_start, end_ms - _60_S, "1m"),
            _agg_extremes(end_ms - _60_S, end_ms),
            return_exceptions=True,
        )
        if any(isinstance(v, BaseException) for v in results):
            return await _ohlcv_hl(start_ms, end_ms, "1m")
        high, low = _merge(*results)
        if high is not None:
            return high, low
        return await _ohlcv_hl(start_ms, end_ms, "1m")

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

    # ── Orderbook / mark price / server time ──────────────────────────────────

    async def fetch_orderbook(self, symbol: str, limit: int = 20) -> Dict:
        return await self._run(lambda: self._ex.fetch_order_book(symbol, limit=limit))

    async def fetch_mark_price(self, symbol: str) -> float:
        def _fetch():
            ticker = self._ex.fetch_ticker(symbol)
            return float(ticker.get("last") or ticker.get("close") or 0)
        return await self._run(_fetch)

    async def fetch_server_time(self) -> int:
        return await self._run(self._ex.fetch_time)

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
