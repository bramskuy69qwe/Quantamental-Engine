"""
Reconciliation Worker — calculates accurate MFE/MAE for closed positions.

Triggered by risk:trade_closed events. Waits for Binance to settle,
re-fetches exchange history, then computes MFE/MAE using multi-resolution
data (aggTrades for short trades, 1m/1h for longer ones) for every
uncalculated row (mfe=0, open_time>0) for the affected symbol.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict

from core.state import app_state
from core.database import db
from core.exchange import fetch_hl_for_trade, calc_mfe_mae, fetch_exchange_trade_history

log = logging.getLogger("reconciler")

_SETTLE_DELAY    = 8   # seconds after close for Binance to finalise income entry
_BACKFILL_SEM    = 3   # max concurrent symbols during backfill


class ReconcilerWorker:

    async def _reconcile_symbol(self, ticker: str, direction: str = "") -> None:
        """Process all uncalculated exchange_history rows for one symbol."""
        rows = await db.get_uncalculated_exchange_rows(ticker)
        if not rows:
            log.info(f"Reconciler: no uncalculated rows for {ticker}")
            return

        for row in rows:
            trade_key   = row["trade_key"]
            open_ms     = row["open_time"]
            close_ms    = row["time"]
            entry_price = row["entry_price"]
            quantity    = row["qty"]
            row_dir     = row["direction"] or direction

            if not open_ms or not close_ms or not entry_price or not quantity:
                log.warning(f"Reconciler: skipping {trade_key} — missing bounds")
                continue

            duration_s = (close_ms - open_ms) / 1000
            trade_high, trade_low = await fetch_hl_for_trade(ticker, open_ms, close_ms)
            if trade_high is None:
                log.warning(f"Reconciler: no price data for {trade_key}")
                continue

            mfe, mae = calc_mfe_mae(trade_high, trade_low, entry_price, row_dir, quantity)
            await db.update_exchange_mfe_mae(trade_key, mfe, mae)
            log.info(
                f"Reconciler: {trade_key} hold={duration_s:.0f}s "
                f"high={trade_high} low={trade_low} mfe={mfe} mae={mae}"
            )

    async def on_trade_closed(self, payload: Dict) -> None:
        """
        Event-driven path — triggered by risk:trade_closed.
        Waits for Binance to settle, refreshes history (fixes open_time for
        partial-close rows), then reconciles the affected symbol.
        """
        ticker    = payload.get("ticker", "")
        direction = payload.get("direction", "")
        if not ticker:
            return
        log.info(f"Reconciler triggered for {ticker}")

        await asyncio.sleep(_SETTLE_DELAY)

        try:
            await fetch_exchange_trade_history()
            await self._reconcile_symbol(ticker, direction)
        except Exception as e:
            app_state.ws_status.add_log(f"Reconciler error ({ticker}): {e}")
            log.exception(f"Reconciler failed for {ticker}")

    async def backfill_all(self) -> None:
        """
        Startup backfill — processes all exchange_history rows with mfe=0.

        Performance optimisations vs the naive sequential loop:
        1. fetch_exchange_trade_history() is called ONCE up-front, updating
           open_time for all symbols (including partial-close rows with open_time=0).
        2. Symbols are processed concurrently with a semaphore (_BACKFILL_SEM)
           to exploit I/O overlap while respecting Binance rate limits.
        """
        # Single up-front history refresh — corrects open_time for all symbols
        try:
            await fetch_exchange_trade_history()
        except Exception as e:
            log.warning(f"Backfill: history pre-fetch failed: {e}")

        async with db._conn.execute(
            "SELECT DISTINCT symbol FROM exchange_history"
            " WHERE (mfe=0 OR mae=0) AND open_time>0"
        ) as cur:
            symbols = [r[0] for r in await cur.fetchall()]

        if not symbols:
            return
        log.info(f"Reconciler backfill: {len(symbols)} symbols")

        sem = asyncio.Semaphore(_BACKFILL_SEM)

        async def _process(sym: str) -> None:
            async with sem:
                try:
                    await self._reconcile_symbol(sym)
                except Exception as e:
                    log.exception(f"Backfill failed for {sym}: {e}")

        await asyncio.gather(*[_process(sym) for sym in symbols])
