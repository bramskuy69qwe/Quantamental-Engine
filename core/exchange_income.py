"""
Income history, equity backfill, trade history, and funding rate wrappers.

Split from exchange.py for maintainability. Uses the adapter layer for
all exchange-specific REST calls.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta

from core.state import app_state, TZ_LOCAL
from core.exchange import get_exchange, _REST_POOL
from core.database import db
from core.constants import MS_PER_DAY


def _get_adapter():
    """Late-import wrapper to avoid circular import with core.exchange."""
    from core.exchange import _get_adapter as _ga
    return _ga()

log = logging.getLogger("exchange")


# ── Income history (REALIZED_PNL, FUNDING_FEE, COMMISSION, etc.) ─────────────

async def fetch_income_history(
    income_type: str = "",
    start_ms: Optional[int] = None,
    limit: int = 1000,
) -> List[Dict]:
    """
    Fetch income history via adapter.
    income_type: "REALIZED_PNL", "FUNDING_FEE", "COMMISSION", "" (all)

    Returns raw dicts for backward compatibility with existing consumers
    that expect {"income": ..., "incomeType": ..., "time": ..., "symbol": ...}.
    """
    adapter = _get_adapter()
    normalized = await adapter.fetch_income(
        income_type=income_type, start_ms=start_ms, limit=limit,
    )
    # Convert back to dict format for existing consumers
    return [
        {
            "symbol": ni.symbol,
            "incomeType": ni.income_type.upper(),
            "income": ni.amount,
            "time": ni.timestamp_ms,
            "tradeId": ni.trade_id,
        }
        for ni in normalized
    ]


async def fetch_bod_sow_equity() -> None:
    """
    Derive BOD and SOW equity from Binance income history so values survive
    server restarts and reflect real exchange data.

    BOD equity  = current_equity - sum(income(today midnight -> now))
    SOW equity  = current_equity - sum(income(Monday midnight -> now))
    """
    current_equity = app_state.account_state.total_equity
    if current_equity == 0:
        return

    now_local = datetime.now(TZ_LOCAL)

    # Start of today (local midnight) -> UTC ms
    today_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_ms = int(today_midnight.astimezone(timezone.utc).timestamp() * 1000)

    # Start of current week (Monday midnight local) -> UTC ms
    days_since_monday = now_local.weekday()  # 0 = Monday
    monday_midnight = (now_local - timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    monday_ms = int(monday_midnight.astimezone(timezone.utc).timestamp() * 1000)

    try:
        today_income = await fetch_income_history(start_ms=today_ms, limit=1000)
        today_pnl = sum(float(i.get("income", 0)) for i in today_income)
        app_state.account_state.bod_equity = round(current_equity - today_pnl, 4)
        if app_state.account_state.bod_timestamp == "":
            app_state.account_state.bod_timestamp = today_midnight.isoformat()
    except Exception as e:
        app_state.ws_status.add_log(f"BOD equity fetch error: {e}")

    try:
        week_income = await fetch_income_history(start_ms=monday_ms, limit=1000)
        week_pnl = sum(float(i.get("income", 0)) for i in week_income)
        app_state.account_state.sow_equity = round(current_equity - week_pnl, 4)
        if app_state.account_state.sow_timestamp == "":
            app_state.account_state.sow_timestamp = monday_midnight.isoformat()
    except Exception as e:
        app_state.ws_status.add_log(f"SOW equity fetch error: {e}")


async def fetch_income_for_backfill(start_ms: int, end_ms: int) -> List[Dict]:
    """
    Paginated fetch of ALL income types from start_ms to end_ms (ms UTC).
    Advances cursor by last event timestamp + 1 until end_ms is covered
    or the exchange returns fewer than 1000 records.
    """
    adapter = _get_adapter()
    all_events: List[Dict] = []
    cursor = start_ms

    while cursor < end_ms:
        normalized = await adapter.fetch_income(
            start_ms=cursor, end_ms=end_ms, limit=1000,
        )
        if not normalized:
            break
        batch = [
            {
                "symbol": ni.symbol,
                "incomeType": ni.income_type.upper(),
                "income": ni.amount,
                "time": ni.timestamp_ms,
                "tradeId": ni.trade_id,
            }
            for ni in normalized
        ]
        all_events.extend(batch)
        if len(batch) < 1000:
            break
        cursor = int(batch[-1]["time"]) + 1

    return all_events


async def build_equity_backfill(
    start_ms: int, end_ms: int, current_equity: float
) -> tuple:
    """
    Reconstruct historical equity data points from Binance income events.

    Works backwards from current_equity:
        equity_at_T = current_equity - sum(income events with time > T)

    Returns (equity_records, cashflow_records):
      - equity_records:   [(ts_ms, equity)]  sorted ascending
      - cashflow_records: [(ts_ms, amount)]  sorted ascending — TRANSFER events only
    Both lists are empty if no income events are found or current_equity is 0.
    """
    if current_equity == 0:
        return [], []

    try:
        events = await fetch_income_for_backfill(start_ms, end_ms)
    except Exception as e:
        log.warning("fetch_income_for_backfill failed: %r", e)
        return [], []

    if not events:
        return [], []

    # Sort descending by time to walk backwards
    events_sorted = sorted(events, key=lambda e: int(e.get("time", 0)), reverse=True)
    type_counts: Dict[str, int] = {}
    transfer_abs_sum = 0.0

    records: List[tuple] = []
    cashflow_records: List[tuple] = []
    running_deduct = 0.0
    for event in events_sorted:
        etype = str(event.get("incomeType", "UNKNOWN"))
        type_counts[etype] = type_counts.get(etype, 0) + 1
        income = float(event.get("income", 0) or 0)
        # Reconstruct trading equity from PnL drivers only.
        if etype in {"REALIZED_PNL", "FUNDING_FEE"}:
            running_deduct += income
        equity_at_event = round(current_equity - running_deduct, 4)
        if equity_at_event < 0:
            continue
        records.append((int(event["time"]), equity_at_event))
        if etype == "TRANSFER":
            transfer_abs_sum += abs(income)
            cashflow_records.append((int(event["time"]), income))

    if not records:
        return [], []

    # Return oldest-first
    records.sort(key=lambda r: r[0])
    cashflow_records.sort(key=lambda r: r[0])

    # ── Trim pre-deposit era ─────────────────────────────────────────────────
    max_eq = max(eq for _, eq in records)
    trim_threshold = max_eq * 0.02
    first_valid = next(
        (i for i, (_, eq) in enumerate(records) if eq >= trim_threshold), 0
    )
    records = records[first_valid:]

    if not records:
        return [], []

    # ── Fill idle gaps ───────────────────────────────────────────────────────
    filled: List[tuple] = []
    for i, (ts, eq) in enumerate(records):
        filled.append((ts, eq))
        if i + 1 < len(records):
            next_ts = records[i + 1][0]
            fill_ts = ts + MS_PER_DAY
            while fill_ts < next_ts - MS_PER_DAY // 2:
                filled.append((fill_ts, eq))
                fill_ts += MS_PER_DAY

    return filled, cashflow_records


async def fetch_user_trades(symbol: str, limit: int = 500) -> List[Dict]:
    """Fetch recent trade fills for a symbol via adapter.

    Returns raw dicts for backward compatibility with existing consumers
    that expect {"id": ..., "side": ..., "price": ..., "qty": ..., "time": ...}.
    """
    adapter = _get_adapter()
    try:
        normalized = await adapter.fetch_user_trades(symbol, limit=limit)
        return [
            {
                "id": nt.trade_id,
                "symbol": nt.symbol,
                "side": nt.side,
                "price": nt.price,
                "qty": nt.quantity,
                "commission": nt.fee,
                "time": nt.timestamp_ms,
            }
            for nt in normalized
        ]
    except Exception as e:
        app_state.ws_status.add_log(f"User trades fetch error ({symbol}): {e}")
        return []


async def fetch_exchange_trade_history(limit: int = 200) -> None:
    """
    Fetch recent realized-PnL income entries from Binance, then augment each
    row with direction, exit_price, entry_price (computed), and fee (from
    COMMISSION income events matched by tradeId).  Stores newest-first.

    Fallback path only — when the Quantower plugin is connected, exchange_history
    is populated by the plugin's historical_fill events instead.
    """
    try:
        from core.platform_bridge import platform_bridge  # late import: circular dep
        if platform_bridge.is_connected:
            log.debug(
                "fetch_exchange_trade_history: plugin connected — skipping "
                "Binance backfill (Quantower is canonical)"
            )
            return
    except Exception:
        pass

    try:
        # Primary: REALIZED_PNL events
        raw_pnl = await fetch_income_history(income_type="REALIZED_PNL", limit=limit)

        # Secondary: COMMISSION events keyed by tradeId -> fee amount (always positive)
        raw_commission = await fetch_income_history(income_type="COMMISSION", limit=limit)
        fee_map: Dict[str, float] = {}
        for c in raw_commission:
            tid = str(c.get("tradeId", ""))
            if tid:
                fee_map[tid] = abs(float(c.get("income", 0) or 0))

        # Funding fees: FUNDING_FEE events grouped by symbol with timestamps
        raw_funding = await fetch_income_history(income_type="FUNDING_FEE", limit=limit)
        funding_by_symbol: Dict[str, List[tuple]] = {}
        for f in raw_funding:
            sym = f.get("symbol", "")
            if sym:
                funding_by_symbol.setdefault(sym, []).append(
                    (int(f.get("time", 0)), abs(float(f.get("income", 0) or 0)))
                )

        # Tertiary: userTrades per symbol -> exit price, direction, qty, open_time
        symbols = list({r.get("symbol", "") for r in raw_pnl if r.get("symbol")})
        trade_lookup: Dict[str, Dict] = {}
        fills_by_symbol: Dict[str, List[Dict]] = {}

        _sym_sem = asyncio.Semaphore(5)

        async def _fetch_sym(s: str):
            async with _sym_sem:
                return s, await fetch_user_trades(s, limit=500)

        _sym_results = await asyncio.gather(
            *[_fetch_sym(s) for s in symbols], return_exceptions=True
        )
        for _res in _sym_results:
            if isinstance(_res, BaseException):
                log.warning("fetch_user_trades failed for a symbol: %r", _res)
                continue
            sym, fills = _res
            fills_by_symbol[sym] = fills
            for t in fills:
                trade_lookup[str(t.get("id", ""))] = t

        # Augment each PnL event
        for r in raw_pnl:
            tid      = str(r.get("tradeId", ""))
            trade    = trade_lookup.get(tid, {})
            sym      = r.get("symbol", "")
            close_ms = int(r.get("time", 0))

            side       = trade.get("side", "")
            direction  = "LONG" if side == "SELL" else ("SHORT" if side == "BUY" else "")
            exit_price = float(trade.get("price", 0) or 0)
            qty        = float(trade.get("qty",   0) or 0)
            income_val = float(r.get("income", 0) or 0)

            # entry_price derived from: PnL = (exit-entry)*qty (LONG) or (entry-exit)*qty (SHORT)
            if direction == "LONG" and exit_price > 0 and qty > 0:
                entry_price = exit_price - income_val / qty
            elif direction == "SHORT" and exit_price > 0 and qty > 0:
                entry_price = exit_price + income_val / qty
            else:
                entry_price = 0.0

            # open_time: oldest opening-direction fill of the CURRENT leg only.
            open_side  = "BUY"  if direction == "LONG"  else ("SELL" if direction == "SHORT" else "")
            close_side = "SELL" if direction == "LONG"  else ("BUY"  if direction == "SHORT" else "")
            open_time  = 0
            open_fills: List[Dict] = []
            if open_side:
                sym_fills = fills_by_symbol.get(sym, [])
                prev_close_fills = [t for t in sym_fills
                                    if t.get("side") == close_side
                                    and int(t.get("time", 0)) < close_ms]
                prev_leg_end_ms = max(
                    (int(t.get("time", 0)) for t in prev_close_fills), default=0
                )
                open_fills = [t for t in sym_fills
                              if t.get("side") == open_side
                              and prev_leg_end_ms < int(t.get("time", 0)) < close_ms]
                if not open_fills:
                    _SEVEN_DAYS_MS = 7 * 24 * 3600 * 1000
                    open_fills = [t for t in sym_fills
                                  if t.get("side") == open_side
                                  and close_ms - _SEVEN_DAYS_MS < int(t.get("time", 0)) < close_ms]
                if open_fills:
                    open_time = int(min(open_fills, key=lambda t: int(t.get("time", 0)))
                                    .get("time", 0))

            notional = round(exit_price * qty, 2) if exit_price and qty else 0.0

            entry_fee = sum(abs(float(f.get("commission", 0) or 0)) for f in open_fills)
            funding_fee = sum(
                amt for ts, amt in funding_by_symbol.get(sym, [])
                if open_time and open_time <= ts <= close_ms
            )
            exit_fee = fee_map.get(tid, 0.0)

            r["direction"]   = direction
            r["exit_price"]  = exit_price
            r["entry_price"] = round(entry_price, 6) if entry_price else 0.0
            r["fee"]         = round(entry_fee + funding_fee + exit_fee, 6)
            r["qty"]         = qty
            r["open_time"]   = open_time
            r["notional"]    = notional
            r["trade_key"]   = f"{r.get('time', '')}_{r.get('symbol', '')}_{r.get('incomeType', '')}"

        raw_pnl.sort(key=lambda x: x.get("time", 0), reverse=True)
        app_state.exchange_trade_history = raw_pnl

        try:
            await db.upsert_exchange_history(raw_pnl, account_id=app_state.active_account_id)
        except Exception as e:
            app_state.ws_status.add_log(f"exchange_history DB upsert error: {e}")
    except Exception as e:
        app_state.ws_status.add_log(f"Exchange trade history error: {e}")


async def fetch_funding_rates(symbols: List[str]) -> Dict[str, Dict]:
    """
    Fetch current funding rate + next funding time + mark price for each symbol
    via the exchange adapter.

    Returns:
        {symbol: {"funding_rate": float, "next_funding_time": int, "mark_price": float}}
    """
    if not symbols:
        return {}

    try:
        adapter = _get_adapter()
        return await adapter.fetch_current_funding_rates(symbols)
    except Exception as e:
        log.warning("fetch_funding_rates failed: %r", e)
        return {s: {"funding_rate": 0.0, "next_funding_time": 0, "mark_price": 0.0} for s in symbols}
