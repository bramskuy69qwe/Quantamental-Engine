"""
Income history, equity backfill, trade history, and funding rate wrappers.

Split from exchange.py for maintainability. Uses the adapter layer for
all exchange-specific REST calls.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Iterable, List, Optional
from datetime import datetime, timezone, timedelta

from core.state import app_state
from core.tz import now_in_account_tz
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

    now_local = now_in_account_tz(app_state.active_account_id)

    # Start of today (local midnight) -> UTC ms
    today_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_ms = int(today_midnight.astimezone(timezone.utc).timestamp() * 1000)

    # Start of current week (Monday midnight local) -> UTC ms
    days_since_monday = now_local.weekday()  # 0 = Monday
    monday_midnight = (now_local - timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    monday_ms = int(monday_midnight.astimezone(timezone.utc).timestamp() * 1000)

    bod_eq = None
    bod_ts = None
    sow_eq = None
    sow_ts = None

    try:
        today_income = await fetch_income_history(start_ms=today_ms, limit=1000)
        today_pnl = sum(float(i.get("income", 0)) for i in today_income)
        bod_eq = round(current_equity - today_pnl, 4)
        bod_ts = today_midnight.isoformat()
    except Exception as e:
        app_state.ws_status.add_log(f"BOD equity fetch error: {e}")

    try:
        week_income = await fetch_income_history(start_ms=monday_ms, limit=1000)
        week_pnl = sum(float(i.get("income", 0)) for i in week_income)
        sow_eq = round(current_equity - week_pnl, 4)
        sow_ts = monday_midnight.isoformat()
    except Exception as e:
        app_state.ws_status.add_log(f"SOW equity fetch error: {e}")

    # Apply through DataCache — locked, auto-recalculates portfolio
    if bod_eq is not None or sow_eq is not None:
        await app_state._data_cache.apply_bod_sow_equity(
            bod_equity=bod_eq, bod_timestamp=bod_ts,
            sow_equity=sow_eq, sow_timestamp=sow_ts,
        )


async def fetch_income_for_backfill(start_ms: int, end_ms: int) -> List[Dict]:
    """
    Paginated fetch of ALL income types from start_ms to end_ms (ms UTC).
    Advances cursor by last event timestamp + 1 until end_ms is covered
    or the exchange returns fewer than 1000 records.
    """
    adapter = _get_adapter()
    adapter.set_priority("background")  # backfill is low-priority
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


# ── Window-aware income paging (2026-07-10) ──────────────────────────────────
# Binance's income endpoint returns at most ~7 days from a given startTime (and
# at most `limit` rows). A single no-startTime fetch therefore silently drops
# every trade older than 7 days after an offline gap — gap detection then never
# sees those symbols and their trades never reach closed_positions / Position
# History (the 2026-07-10 PUNDIX/TAC/IN miss). The fetch below anchors at the
# last captured income row and pages FORWARD in <=7-day windows to now.
_INCOME_WINDOW_MS = 7 * MS_PER_DAY            # Binance income window per request
_INCOME_PAGE_LIMIT = 1000                     # Binance income max rows / request
_INCOME_ANCHOR_OVERLAP_MS = 60 * 60 * 1000    # re-fetch the last hour (dedup-safe)
_INCOME_MAX_PAGES = 200                       # safety backstop (~3.8y of empty steps)


async def _fetch_income_windowed(
    income_type: str, start_ms: int, now_ms: int,
) -> List[Dict]:
    """Page ``fetch_income_history`` forward from ``start_ms`` to ``now_ms`` to
    cover offline gaps longer than Binance's ~7-day income window.

    Advance rule (the burst case matters — e.g. 800+ REALIZED_PNL events in one
    day exceeds the 1000-row page): on a FULL page (>= limit rows) the window may
    hold more rows past the limit, so continue from ``max_time + 1``; on a SHORT
    page the window is fully returned, so skip a full 7-day window; on an EMPTY
    (quiet) window, step a full 7 days. De-duplicated by
    (symbol, type, time, tradeId); the DB upsert also dedups on ``trade_key``.
    """
    rows: List[Dict] = []
    seen: set = set()
    cursor = int(start_ms)
    for _ in range(_INCOME_MAX_PAGES):
        if cursor >= now_ms:
            break
        batch = await fetch_income_history(
            income_type=income_type, start_ms=cursor, limit=_INCOME_PAGE_LIMIT,
        )
        if not batch:
            cursor += _INCOME_WINDOW_MS           # quiet window — probe the next
            continue
        max_t = cursor
        for r in batch:
            t = int(r.get("time", 0) or 0)
            if t > max_t:
                max_t = t
            key = (r.get("symbol"), r.get("incomeType"), t, r.get("tradeId"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(r)
        if len(batch) >= _INCOME_PAGE_LIMIT:
            # FULL page — the 7-day window holds more rows than the 1000-row
            # limit. Re-fetch from max_t (NOT max_t+1) so a same-millisecond
            # group straddling the row-limit boundary isn't dropped: a heavy
            # scalp day can put >1000 income rows in one 7-day window (IN alone
            # did 841 in a day), and advancing past max_t would skip any rows at
            # exactly max_t beyond the limit. The seen-set dedups the re-fetched
            # rows. The guard keeps progress if a page were somehow all one ms.
            cursor = max_t if max_t > cursor else cursor + 1
        else:
            cursor += _INCOME_WINDOW_MS           # window fully returned
    else:
        # MAX_PAGES exhausted without reaching now — surface it (parity with
        # fetch_all_user_trades) rather than silently returning partial income.
        if cursor < now_ms:
            log.warning(
                "_fetch_income_windowed(%s): hit MAX_PAGES=%d at cursor=%d "
                "(< now=%d) — income may be incomplete",
                income_type, _INCOME_MAX_PAGES, cursor, now_ms,
            )
    return rows


async def fetch_exchange_trade_history(limit: int = 200, since_ms: Optional[int] = None) -> None:
    """
    Fetch recent realized-PnL income entries from Binance, then augment each
    row with direction, exit_price, entry_price (computed), and fee (from
    COMMISSION income events matched by tradeId).  Stores newest-first.

    ``since_ms`` (2026-07-10): explicit fetch-window floor. Normally the window
    is anchored at the last captured income row (get_last_income_time), which is
    forward-only — it CANNOT reach income the old 7-day fetch already stranded
    behind a newer trade of another symbol (e.g. an offline gap where a later
    symbol was captured first). Pass ``since_ms`` for a one-time WIDE backfill
    that re-ingests that stranded income into exchange_history (so the income
    ledger + analytics reflect it). Upsert dedups on trade_key, so re-ingesting
    is safe.
    """
    try:
        # Window-aware anchor (2026-07-10): cover any offline gap since the last
        # captured income row, not just Binance's default ~7-day window. On a
        # steady periodic run the anchor is ~now -> a single page; on a restart
        # after a long offline gap it pages across the whole gap so the older
        # trades reach exchange_history -> gap detection -> userTrades recovery.
        now_ms = int(time.time() * 1000)
        if since_ms is not None:
            _start_ms = int(since_ms)             # explicit one-time wide backfill
        else:
            _anchor = await db.get_last_income_time(account_id=app_state.active_account_id)
            _start_ms = (_anchor - _INCOME_ANCHOR_OVERLAP_MS) if _anchor else (now_ms - _INCOME_WINDOW_MS)

        # Primary: REALIZED_PNL events
        raw_pnl = await _fetch_income_windowed("REALIZED_PNL", _start_ms, now_ms)

        # Secondary: COMMISSION events keyed by tradeId -> fee amount (always positive)
        raw_commission = await _fetch_income_windowed("COMMISSION", _start_ms, now_ms)
        fee_map: Dict[str, float] = {}
        for c in raw_commission:
            tid = str(c.get("tradeId", ""))
            if tid:
                fee_map[tid] = abs(float(c.get("income", 0) or 0))

        # Funding fees: FUNDING_FEE events grouped by symbol with timestamps
        raw_funding = await _fetch_income_windowed("FUNDING_FEE", _start_ms, now_ms)
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

        # PA-1b: Precompute open_time per close fill using FIFO position accounting.
        # For each (symbol, direction), builds a FIFO queue of opening fills.
        # Closing fills consume from the queue head (oldest first).
        # The queue head's timestamp = the position's open_time for that close.
        close_open_times: Dict[str, int] = {}  # fill_id -> open_time_ms

        for sym, sym_fills_raw in fills_by_symbol.items():
            sorted_fills = sorted(sym_fills_raw, key=lambda f: int(f.get("time", 0)))
            for direction in ("LONG", "SHORT"):
                open_side  = "BUY" if direction == "LONG" else "SELL"
                close_side = "SELL" if direction == "LONG" else "BUY"
                fifo_queue: List[List] = []  # [[time_ms, remaining_qty], ...]
                for fill in sorted_fills:
                    fill_side = fill.get("side", "")
                    fill_qty  = float(fill.get("qty", 0))
                    fill_time = int(fill.get("time", 0))
                    fill_id   = str(fill.get("id", ""))
                    if fill_side == open_side:
                        fifo_queue.append([fill_time, fill_qty])
                    elif fill_side == close_side:
                        open_time_fifo = fifo_queue[0][0] if fifo_queue else 0
                        close_open_times[fill_id] = open_time_fifo
                        if not fifo_queue and fill_id:
                            log.debug("PA-1b: orphan close fill %s %s — no matching open", sym, fill_id)
                        # Consume FIFO
                        remaining = fill_qty
                        while remaining > 1e-8 and fifo_queue:
                            if fifo_queue[0][1] <= remaining + 1e-8:
                                remaining -= fifo_queue[0][1]
                                fifo_queue.pop(0)
                            else:
                                fifo_queue[0][1] -= remaining
                                remaining = 0

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

            # PA-1b: open_time from FIFO precomputation (replaces backward-walk)
            open_time = close_open_times.get(tid, 0)

            # Collect opening fills for fee calculation
            open_side = "BUY" if direction == "LONG" else ("SELL" if direction == "SHORT" else "")
            open_fills: List[Dict] = []
            if open_side and open_time > 0:
                sym_fills = fills_by_symbol.get(sym, [])
                open_fills = [t for t in sym_fills
                              if t.get("side") == open_side
                              and open_time <= int(t.get("time", 0)) <= close_ms]

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
            # tradeId appended for uniqueness: multi-fill closes (and especially
            # simultaneous LONG+SHORT hedge-mode closes on the same symbol) emit
            # multiple REALIZED_PNL events with the same (time, symbol, incomeType).
            # Without tradeId, they collide on trade_key and the DB upsert keeps only
            # one — silently dropping the rest. Result: exchange_history is missing
            # the dropped rows, backfill_fills_from_exchange_history can't see them,
            # and Position History never shows the corresponding closed_positions.
            r["trade_key"]   = f"{r.get('time', '')}_{r.get('symbol', '')}_{r.get('incomeType', '')}_{r.get('tradeId', '')}"

        raw_pnl.sort(key=lambda x: x.get("time", 0), reverse=True)
        app_state.exchange_trade_history = raw_pnl

        try:
            await db.upsert_exchange_history(raw_pnl, account_id=app_state.active_account_id)
        except Exception as e:
            app_state.ws_status.add_log(f"exchange_history DB upsert error: {e}")
    except Exception as e:
        app_state.ws_status.add_log(f"Exchange trade history error: {e}")


async def fetch_all_user_trades(
    symbol: str,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    *,
    page_limit: int = 1000,
    max_pages: int = 50,
) -> List[Any]:
    """Paginate Binance ``userTrades`` to recover the FULL fill set for one
    symbol in ``[start_ms, end_ms]`` — real opens AND closes, each with its
    own per-fill commission and a deterministic ``is_close`` (hedge-mode
    side+positionSide). This is the ground-truth source the fill-backfill
    uses instead of the REALIZED_PNL income reconstruction (which had only
    closes + re-summed, inflated fees).

    Strategy: paginate by ``fromId`` from the account's earliest trade on the
    symbol, advancing ``fromId = max_id + 1`` per page until a short page or
    ``max_pages``. (Binance caps a startTime/endTime range at 7 days, so
    time-windowed paging can't recover an older session — fromId has no such
    limit.) The ``[start_ms, end_ms]`` window is applied as an in-memory
    filter. Returns ``NormalizedTrade`` objects de-duplicated by trade id,
    sorted ascending by ``timestamp_ms``.

    NB to capture every position's OPEN, ``start_ms`` must precede the
    session's first entry — group_fills_into_positions SKIPS a closing fill
    that has no prior open in the stream (orphan). Callers pass a generous
    lower bound.
    """
    adapter = _get_adapter()
    try:
        adapter.set_priority("background")
    except Exception:
        pass
    # fromId pagination from the account's earliest trade on this symbol,
    # walking forward (id ascending) page by page. NB Binance caps a
    # startTime/endTime userTrades range at 7 DAYS, so a >7d-old startTime
    # silently returns an empty window — fromId paging has no such limit and
    # is the only way to recover a full multi-day / older session. The window
    # (start_ms/end_ms) is applied as an IN-MEMORY filter on the result.
    seen: set = set()
    out: List[Any] = []
    from_id = 1
    pages = 0
    for _ in range(max_pages):
        pages += 1
        page = await adapter.fetch_user_trades(symbol, limit=page_limit, from_id=from_id)
        if not page:
            break
        max_id = from_id
        added = 0
        for t in page:
            try:
                tid = int(getattr(t, "trade_id", "") or getattr(t, "exchange_fill_id", ""))
            except (TypeError, ValueError):
                tid = None
            if tid is not None:
                if tid in seen:
                    continue
                seen.add(tid)
                if tid > max_id:
                    max_id = tid
            out.append(t)
            added += 1
        if len(page) < page_limit:
            break
        if added == 0 or max_id < from_id:
            break  # no forward progress — guard against an infinite loop
        from_id = max_id + 1
    else:
        log.warning(
            "fetch_all_user_trades(%s): hit max_pages=%d — result may be "
            "incomplete (raise max_pages)", symbol, max_pages,
        )

    def _in_window(t) -> bool:
        ts = int(getattr(t, "timestamp_ms", 0) or 0)
        if start_ms is not None and ts < start_ms:
            return False
        if end_ms is not None and ts > end_ms:
            return False
        return True

    out = [t for t in out if _in_window(t)]
    out.sort(key=lambda t: int(getattr(t, "timestamp_ms", 0) or 0))
    log.info("fetch_all_user_trades(%s): %d fills over %d page(s)", symbol, len(out), pages)
    return out


def user_trade_to_fill_dict(t: Any, account_id: int, source: str = "exchange_usertrades") -> Dict[str, Any]:
    """Map one Binance ``userTrades`` NormalizedTrade to a ``fills`` row dict.

    Single source of truth for the userTrades→fill shape, shared by the
    backfill builder and the operator re-fix script. ``exchange_fill_id`` =
    the Binance ``tradeId`` (the fills dedup key); ``direction`` is the
    positionSide; ``is_close`` is the adapter's hedge-aware flag.
    """
    return {
        "account_id":        account_id,
        "exchange_fill_id":  str(getattr(t, "trade_id", "") or getattr(t, "exchange_fill_id", "")),
        "exchange_order_id": str(getattr(t, "exchange_order_id", "") or ""),
        "symbol":            getattr(t, "symbol", "") or "",
        "side":              getattr(t, "side", "") or "",
        "direction":         getattr(t, "direction", "") or "",
        "price":             float(getattr(t, "price", 0) or 0),
        "quantity":          float(getattr(t, "quantity", 0) or 0),
        "fee":               abs(float(getattr(t, "fee", 0) or 0)),
        "fee_asset":         getattr(t, "fee_asset", "USDT") or "USDT",
        "is_close":          int(bool(getattr(t, "is_close", False))),
        "realized_pnl":      float(getattr(t, "realized_pnl", 0) or 0),
        "role":              getattr(t, "role", "") or "",
        "source":            source,
        "timestamp_ms":      int(getattr(t, "timestamp_ms", 0) or 0),
    }


async def backfill_fills_from_user_trades(
    symbols: Iterable[str],
    start_ms: int,
    end_ms: Optional[int] = None,
    *,
    account_id: Optional[int] = None,
    source: str = "exchange_usertrades",
) -> Dict[str, Any]:
    """Build TRUE fills from Binance ``userTrades`` for the given symbols and
    window, upserting them into the ``fills`` table.

    This is the correct offline-recovery primitive: every fill is a real
    exchange execution carrying its real side, positionSide (``direction``),
    ``is_close``, per-fill ``commission`` and ``realized_pnl`` — so the
    downstream ``group_fills_into_positions`` sees genuine opens AND closes
    and produces correct positions + fees. It replaces the
    REALIZED_PNL-income path (``fetch_exchange_trade_history`` →
    ``backfill_fills_from_exchange_history``) which had close-only synthetic
    fills with opening commissions re-summed per partial close (8–70× fee
    inflation) and undersized synthetic opens (position collapse).

    Idempotent: fills dedupe on ``(account_id, exchange_fill_id)`` where
    ``exchange_fill_id`` = the Binance ``tradeId``. Does NOT rebuild
    ``closed_positions`` — the caller runs the rebuild afterwards from the
    corrected fills. Returns ``{"fills_upserted": N, "per_symbol": {...},
    "skipped_zero_qty": K}``.
    """
    aid = account_id if account_id is not None else app_state.active_account_id
    per_symbol: Dict[str, int] = {}
    total = 0
    skipped_zero = 0
    for sym in symbols:
        trades = await fetch_all_user_trades(sym, start_ms, end_ms)
        n = 0
        for t in trades:
            qty = float(getattr(t, "quantity", 0) or 0)
            if qty <= 0:
                skipped_zero += 1
                continue
            await db.upsert_fill(user_trade_to_fill_dict(t, aid, source))
            n += 1
            total += 1
        per_symbol[sym] = n
        log.info("userTrades fill-backfill: %s -> %d fills upserted", sym, n)
    return {"fills_upserted": total, "per_symbol": per_symbol, "skipped_zero_qty": skipped_zero}


async def _apply_recovered_fills(account_id: int, symbol: str, trades: List[Any]) -> Dict[str, int]:
    """Apply pre-fetched userTrades for ONE symbol — the DB-WRITE phase, run
    SERIALLY (see ``recover_offline_trades``): collision-safe true-fill upsert
    → delete synthetic backfill fills → rebuild closed_positions.

    Collision-safe: a userTrades fill whose tradeId already exists as a real
    (non-backfill) fill is PRESERVED, not overwritten — live WS data wins.
    """
    existing_real = await db.get_real_fill_ids(account_id, symbol)
    inserted = preserved = skipped_zero = 0
    for t in trades:
        if float(getattr(t, "quantity", 0) or 0) <= 0:
            skipped_zero += 1
            continue
        fd = user_trade_to_fill_dict(t, account_id)
        if fd["exchange_fill_id"] in existing_real:
            preserved += 1
            continue
        await db.upsert_fill(fd)
        inserted += 1
    if inserted == 0 and preserved == 0:
        # No userTrades available (empty / failed / older-than-retention /
        # max_pages-truncated fetch). Leave the symbol's existing fills +
        # closed_positions intact rather than deleting backfill rows with
        # nothing to replace them — avoids data loss AND the rebuild-every-
        # restart thrash (audit H3). The symbol re-selects next run + retries.
        log.info("recover %s: no userTrades returned — skipped (retry next run)", symbol)
        return {
            "fills_inserted": 0, "fills_preserved": 0, "skipped_zero_qty": skipped_zero,
            "backfill_fills_deleted": 0, "positions_rebuilt": 0,
            "positions_deleted": 0, "fill_tpids_updated": 0, "skipped_empty": True,
        }
    deleted = await db.delete_backfill_fills(account_id, symbol)
    rebuilt = await db.rebuild_closed_positions_for_symbol(account_id, symbol)
    log.info(
        "recover %s: +%d fills (%d preserved), -%d backfill, %d positions",
        symbol, inserted, preserved, deleted, rebuilt["rebuilt"],
    )
    return {
        "fills_inserted":         inserted,
        "fills_preserved":        preserved,
        "skipped_zero_qty":       skipped_zero,
        "backfill_fills_deleted": deleted,
        "positions_rebuilt":      rebuilt["rebuilt"],
        "positions_deleted":      rebuilt["deleted"],
        "fill_tpids_updated":     rebuilt["fill_tpids_updated"],
    }


async def recover_offline_trades(
    account_id: Optional[int] = None,
    *,
    days: int = 90,
    concurrency: int = 5,
) -> Dict[str, Any]:
    """Auto-recover offline-traded fills + closed_positions from Binance
    ``userTrades`` — the CORRECT replacement for the income-reconstruction
    backfill (``DatabaseManager.backfill_fills_from_exchange_history``), which
    rebuilt close-only fills with re-summed opening commissions (8–70× fee
    inflation) and undersized synthetic opens (position collapse).

    SCOPED to GAPPED symbols only (``db.get_offline_gap_symbols``): a symbol is
    recovered iff it has synthetic ``exchange_history_backfill`` fills (income-
    path corruption) OR ``exchange_history`` shows a trade newer than its newest
    recorded fill (an offline WS gap). Purely-online symbols qualify for
    neither and are left untouched — preserving their live fills + calc linkage.
    Per symbol: collision-safe true-fill upsert → delete synthetic backfill
    fills → rebuild closed_positions (``_apply_recovered_fills``). Symbols are
    fetched concurrently but applied SERIALLY (shared aiosqlite connection).

    Idempotent + self-terminating (a recovered symbol drops out of the gap set
    next run), concurrency-limited for startup I/O overlap. Best-effort: a
    per-symbol failure is logged + collected, never aborts the others.

    Returns ``{"symbols": N, "recovered": {sym: {...}}, "errors": {sym: repr}}``.
    """
    aid = account_id if account_id is not None else app_state.active_account_id
    cutoff_ms = int((time.time() - days * 86400) * 1000)
    try:
        symbols = await db.get_offline_gap_symbols(aid, cutoff_ms)
    except Exception as e:
        log.warning("recover_offline_trades: gap-symbol query failed: %r", e)
        return {"symbols": 0, "recovered": {}, "errors": {"_query": repr(e)}}
    if not symbols:
        return {"symbols": 0, "recovered": {}, "errors": {}}

    log.info("recover_offline_trades: %d gapped symbol(s): %s",
             len(symbols), ", ".join(symbols))

    # Phase 1: fetch userTrades CONCURRENTLY (network I/O — the slow part;
    # touches no DB).
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _fetch(sym: str):
        async with sem:
            try:
                return sym, await fetch_all_user_trades(sym)
            except Exception as e:  # noqa: BLE001 — collected per-symbol
                return sym, e

    fetched = await asyncio.gather(*[_fetch(s) for s in symbols])

    # Phase 2: apply SERIALLY. The engine shares ONE aiosqlite connection, so a
    # connection == one transaction context — running the per-symbol writes
    # concurrently would interleave multi-statement transactions (the rebuild's
    # delete+insert+commit, the upsert loop) and cross commit/rollback
    # boundaries. The slow (network) fetch above is already overlapped.
    recovered: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    for sym, trades in fetched:
        if isinstance(trades, BaseException):
            errors[sym] = repr(trades)
            log.warning("recover_offline_trades: %s fetch failed: %r", sym, trades)
            continue
        try:
            recovered[sym] = await _apply_recovered_fills(aid, sym, trades)
        except Exception as e:
            errors[sym] = repr(e)
            log.warning("recover_offline_trades: %s apply failed: %r", sym, e)

    return {"symbols": len(symbols), "recovered": recovered, "errors": errors}


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
