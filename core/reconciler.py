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

import ccxt

from core.state import app_state
from core.database import db
from core.exchange import (
    fetch_hl_for_trade, calc_mfe_mae, fetch_exchange_trade_history,
    handle_rate_limit_error,
)

log = logging.getLogger("reconciler")

_SETTLE_DELAY    = 8   # seconds after close for Binance to finalise income entry
_BACKFILL_SEM    = 3   # max concurrent symbols during backfill
# RL-1: global semaphore limiting concurrent fetch_hl_for_trade across ALL
# reconciler paths (backfill + event-driven). Prevents burst when multiple
# positions close simultaneously.
_HL_SEM = asyncio.Semaphore(2)


class ReconcilerWorker:

    async def _reconcile_symbol(self, ticker: str, direction: str = "") -> None:
        """Process all uncalculated exchange_history rows for one symbol."""
        rows = await db.get_uncalculated_exchange_rows(ticker)
        if not rows:
            log.info(f"Reconciler: no uncalculated rows for {ticker}")
            return

        for row in rows:
            # RL-1: abort if rate-limited (don't cascade 429s across rows)
            if app_state.ws_status.is_rate_limited:
                log.info("Reconciler: aborting — rate limited")
                return

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
            async with _HL_SEM:  # RL-1: limit concurrent REST bursts
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
        except (ccxt.RateLimitExceeded, ccxt.DDoSProtection) as e:
            handle_rate_limit_error(e)
            log.warning("Rate limit hit in on_trade_closed for %s: %s", ticker, e)
        except Exception as e:
            app_state.ws_status.add_log(f"Reconciler error ({ticker}): {e}")
            log.error("Reconciler failed for %s: %s", ticker, e)

    async def backfill_all(self) -> None:
        """
        Startup backfill — processes all exchange_history rows pending backfill.

        Performance optimisations vs the naive sequential loop:
        1. fetch_exchange_trade_history() is called ONCE up-front, updating
           open_time for all symbols (including partial-close rows with open_time=0).
        2. Symbols are processed concurrently with a semaphore (_BACKFILL_SEM)
           to exploit I/O overlap while respecting Binance rate limits.
        """
        # Single up-front history refresh — corrects open_time for all symbols
        try:
            await fetch_exchange_trade_history()
        except (ccxt.RateLimitExceeded, ccxt.DDoSProtection) as e:
            handle_rate_limit_error(e)
            log.warning("Rate limit hit in backfill history pre-fetch: %s", e)
            return
        except Exception as e:
            log.warning(f"Backfill: history pre-fetch failed: {e}")

        # Exclude Quantower-sourced rows (trade_key starts with 'qt:') — these
        # are individual fills, not round-trip trades, so MFE/MAE pairing doesn't apply.
        async with db._conn.execute(
            "SELECT DISTINCT symbol FROM exchange_history"
            " WHERE NOT backfill_completed AND open_time>0"
            " AND trade_key NOT LIKE 'qt:%'"
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
                except (ccxt.RateLimitExceeded, ccxt.DDoSProtection) as e:
                    handle_rate_limit_error(e)
                    log.warning("Rate limit hit in backfill for %s: %s", sym, e)
                except Exception as e:
                    log.error("Backfill failed for %s: %s", sym, e)

        await asyncio.gather(*[_process(sym) for sym in symbols])

        # Also backfill MFE/MAE on closed_positions table
        await self._reconcile_closed_positions()

    async def on_position_closed(self, payload: Dict) -> None:
        """Triggered by risk:position_closed — compute MFE/MAE for the new row."""
        ticker = payload.get("symbol", "")
        if not ticker:
            return
        await asyncio.sleep(_SETTLE_DELAY)
        try:
            await self._reconcile_closed_positions(symbol=ticker)
        except (ccxt.RateLimitExceeded, ccxt.DDoSProtection) as e:
            handle_rate_limit_error(e)
            log.warning("Rate limit hit in on_position_closed for %s: %s", ticker, e)
        except Exception as e:
            log.error("Reconciler closed_positions failed for %s: %s", ticker, e)

    async def _reconcile_closed_positions(self, symbol: str = "") -> None:
        """Compute MFE/MAE for closed_positions rows missing them."""
        rows = await db.get_uncalculated_closed_positions(
            account_id=app_state.active_account_id,
        )
        if symbol:
            rows = [r for r in rows if r.get("symbol") == symbol]
        if not rows:
            return

        for row in rows:
            # RL-1: abort if rate-limited
            if app_state.ws_status.is_rate_limited:
                log.info("Reconciler closed_positions: aborting — rate limited")
                return

            open_ms  = row["entry_time_ms"]
            close_ms = row["exit_time_ms"]
            entry_p  = row["entry_price"]
            qty      = row["quantity"]
            direction = row["direction"]
            if not all((open_ms, close_ms, entry_p, qty)):
                continue
            try:
                async with _HL_SEM:  # RL-1: limit concurrent REST bursts
                    trade_high, trade_low = await fetch_hl_for_trade(
                        row["symbol"], open_ms, close_ms,
                    )
                if trade_high is None:
                    continue
                mfe, mae = calc_mfe_mae(
                    trade_high, trade_low, entry_p, direction, qty,
                )
                await db.update_closed_position_mfe_mae(row["id"], mfe, mae)
                log.info(
                    "Reconciler closed_pos: %s %s mfe=%.2f mae=%.2f",
                    row["symbol"], direction, mfe, mae,
                )
            except (ccxt.RateLimitExceeded, ccxt.DDoSProtection) as e:
                handle_rate_limit_error(e)
                log.warning("Rate limit hit in reconcile_closed_pos id=%d: %s", row["id"], e)
                return
            except Exception as e:
                log.warning(
                    "Reconciler closed_pos failed for id=%d: %s", row["id"], e,
                )
