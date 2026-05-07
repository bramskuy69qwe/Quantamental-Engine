"""
OrderManager — domain logic for order lifecycle.

Decoupled from WebSocket transport. platform_bridge parses messages and
delegates here; schedulers call for REST fallback; both produce identical
dict inputs.

Instantiated once on PlatformBridge.__init__() as self._order_manager.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from core.event_bus import event_bus
from core.order_state import validate_transition, ACTIVE_STATES, OrderStatus
from core.state import app_state, PositionInfo

log = logging.getLogger("order_manager")


class OrderManager:
    """Domain logic for order lifecycle. No WS/HTTP knowledge."""

    def __init__(self, db) -> None:
        self._db = db
        self._open_orders: List[Dict] = []   # cached for dashboard reads

    @property
    def open_orders(self) -> List[Dict]:
        return self._open_orders

    # ── Order Snapshot Processing ───────────────────────────────────────────

    async def process_order_snapshot(
        self, account_id: int, orders: List[Dict[str, Any]]
    ) -> None:
        """Upsert orders, detect cancellations, enrich positions with TP/SL.

        Total: 4 queries regardless of order count (not N+1).
        """
        if not orders and not self._open_orders:
            return

        # 1. Fetch all current active orders in ONE query
        existing = await self._db.get_active_orders_map(account_id)

        # 2. Validate state transitions in memory
        valid_orders: List[Dict] = []
        for o in orders:
            o.setdefault("account_id", account_id)
            eid = o.get("exchange_order_id")
            if eid and eid in existing:
                current_status = existing[eid].get("status", "")
                new_status = o.get("status", "new")
                if not validate_transition(current_status, new_status):
                    log.warning(
                        "Invalid transition %s->%s for order %s, skipping",
                        current_status, new_status, eid,
                    )
                    continue
            valid_orders.append(o)

        # 3. Batch upsert in single transaction (1 query)
        if valid_orders:
            await self._db.upsert_order_batch(valid_orders)

        # 4. Mark active orders NOT in snapshot as canceled (1 query)
        #    allow_cancel_all=True only when snapshot explicitly contained orders
        #    (prevents mass-cancel on broken/empty snapshots)
        active_ids = [
            o["exchange_order_id"]
            for o in orders
            if o.get("exchange_order_id")
        ]
        canceled = await self._db.mark_stale_orders_canceled(
            account_id, active_ids,
            allow_cancel_all=len(orders) > 0 and not active_ids,
        )
        if canceled:
            log.info("Marked %d missing orders as canceled", canceled)

        # 5. Rebuild cache from DB + enrich positions (via refresh_cache)
        await self.refresh_cache(account_id)

    # ── Single-Order Update (WS path) ────────────────────────────────────────

    async def process_order_update(
        self, account_id: int, order: Dict[str, Any]
    ) -> bool:
        """Validate and persist a single order update from WS.

        SR-1: This replaces the old ws_manager bypass that called
        db.upsert_order_batch directly without transition validation.

        Returns True if the order was accepted and persisted, False if
        the transition was invalid (e.g., filled→new stale replay).
        """
        order.setdefault("account_id", account_id)
        eid = order.get("exchange_order_id")

        if eid:
            existing = await self._db.get_active_orders_map(account_id)
            if eid in existing:
                current_status = existing[eid].get("status", "")
                new_status = order.get("status", "new")
                if not validate_transition(current_status, new_status):
                    log.warning(
                        "SR-1: rejected invalid transition %s→%s for order %s (WS update)",
                        current_status, new_status, eid,
                    )
                    return False

        await self._db.upsert_order_batch([order])
        await self.refresh_cache(account_id)
        return True

    # ── Cache Refresh ──────────────────────────────────────────────────────

    async def refresh_cache(self, account_id: int) -> None:
        """Rebuild _open_orders from DB and enrich positions.

        SR-1: This is the sole controlled entry point for cache rebuilds.
        External callers must use this instead of writing _open_orders directly.
        """
        self._open_orders = await self._db.query_open_orders_all(account_id)
        self.enrich_positions_tpsl(app_state.positions)

    # ── TP/SL Enrichment ────────────────────────────────────────────────────

    def enrich_positions_tpsl(self, positions: List[PositionInfo]) -> None:
        """Set TP/SL on positions from cached open orders.

        When multiple TP/SL exist for the same position, pick the one
        closest to mark price (triggers next).
        """
        for pos in positions:
            mark = pos.fair_price or pos.average
            if not mark:
                # No valid price — skip TP/SL selection (would be arbitrary)
                pos.individual_tp_price = 0.0
                pos.individual_sl_price = 0.0
                pos.individual_tpsl = False
                continue

            tp_orders = [
                o for o in self._open_orders
                if o.get("symbol") == pos.ticker
                and o.get("position_side") == pos.direction
                and o.get("order_type") in ("take_profit",)
                and o.get("status") in ("new", "partially_filled")
            ]
            sl_orders = [
                o for o in self._open_orders
                if o.get("symbol") == pos.ticker
                and o.get("position_side") == pos.direction
                and o.get("order_type") in ("stop_loss",)
                and o.get("status") in ("new", "partially_filled")
            ]

            if tp_orders:
                best = min(tp_orders, key=lambda o: abs(o.get("stop_price", 0) - mark))
                pos.individual_tp_price = best.get("stop_price", 0.0)
            else:
                pos.individual_tp_price = 0.0

            if sl_orders:
                best = min(sl_orders, key=lambda o: abs(o.get("stop_price", 0) - mark))
                pos.individual_sl_price = best.get("stop_price", 0.0)
            else:
                pos.individual_sl_price = 0.0

            pos.individual_tpsl = pos.individual_tp_price > 0 or pos.individual_sl_price > 0

    # ── Fill Processing ─────────────────────────────────────────────────────

    async def process_fill(
        self, account_id: int, fill: Dict[str, Any]
    ) -> None:
        """Record fill, update parent order, refresh position fees from DB."""
        fill.setdefault("account_id", account_id)
        exchange_order_id = fill.get("exchange_order_id", "")

        # 1+2. Upsert fill + update parent order in ONE commit
        await self._db.upsert_fill_and_update_order(fill, exchange_order_id)

        # 3. Refresh position fees from DB (SUM query, not accumulate)
        pos_id = fill.get("terminal_position_id", "")
        if pos_id:
            fees = await self._db.get_position_fees(account_id, pos_id)
            for pos in app_state.positions:
                if pos.position_id == pos_id:
                    pos.individual_fees = fees
                    break

        # 4. If closing fill, schedule deferred close row
        if fill.get("is_close"):
            loop = asyncio.get_running_loop()
            loop.call_later(
                2.0,
                lambda f=fill: asyncio.ensure_future(
                    self._build_close_row_for_fill(account_id, f)
                ),
            )

    # ── Position Close ─────────────────────────────────────────────────────

    async def _build_close_row_for_fill(
        self, account_id: int, fill: Dict[str, Any]
    ) -> None:
        """Build a closed_positions row for a partial or full close.

        Groups closing fills from the same parent order into a single row.
        Computes VWAP entry/exit, proportional fees, exit reason, and
        implementation shortfall from pre_trade_log.
        """
        try:
            pos_id    = fill.get("terminal_position_id", "")
            symbol    = fill.get("symbol", fill.get("ticker", ""))
            direction = fill.get("direction", "")

            # ── Opening fills → VWAP entry price ────────────────────────
            opens = await self._db.get_position_fills(
                account_id, pos_id, symbol, direction, is_close=False,
            )
            if opens:
                total_open_qty = sum(f["quantity"] for f in opens)
                entry_price = (
                    sum(f["price"] * f["quantity"] for f in opens) / total_open_qty
                    if total_open_qty else 0.0
                )
                entry_time = min(f["timestamp_ms"] for f in opens)
            else:
                # Fallback: use position's cached average price
                pos = next(
                    (p for p in app_state.positions if p.position_id == pos_id),
                    None,
                )
                entry_price    = pos.average if pos else 0.0
                entry_time     = 0
                total_open_qty = 0.0

            # ── Closing fills from same order (group partial fills) ─────
            exchange_order_id = fill.get("exchange_order_id", "")
            if exchange_order_id:
                close_fills = await self._db.get_fills_by_order(
                    account_id, exchange_order_id,
                )
                close_fills = [f for f in close_fills if f.get("is_close")]
            else:
                close_fills = [fill]

            if not close_fills:
                log.warning("No closing fills for %s %s — skipping", symbol, direction)
                return

            total_close_qty = sum(f["quantity"] for f in close_fills)
            exit_price = (
                sum(f["price"] * f["quantity"] for f in close_fills) / total_close_qty
                if total_close_qty else 0.0
            )
            exit_time    = max(f["timestamp_ms"] for f in close_fills)
            realized_pnl = sum(f.get("realized_pnl", 0) for f in close_fills)

            # ── Fees: closing fees + proportional entry fees ────────────
            close_fees  = sum(f.get("fee", 0) for f in close_fills)
            entry_fees  = sum(f.get("fee", 0) for f in opens) if opens else 0.0
            prop_entry  = (
                entry_fees * (total_close_qty / total_open_qty)
                if total_open_qty else 0.0
            )
            total_fees  = close_fees + prop_entry

            # ── Exit reason from parent order type ──────────────────────
            exit_reason = await self._determine_exit_reason(
                account_id, exchange_order_id,
            )

            # ── Implementation shortfall vs pre_trade_log ───────────────
            shortfall = await self._compute_shortfall(
                account_id, symbol, direction,
                entry_price, exit_price, entry_time,
            )
            model_name = shortfall.pop("model_name", "")

            # ── Persist ─────────────────────────────────────────────────
            net_pnl = realized_pnl - total_fees
            await self._db.insert_closed_position({
                "account_id":           account_id,
                "exchange_position_id": fill.get("exchange_position_id", ""),
                "terminal_position_id": pos_id,
                "symbol":               symbol,
                "direction":            direction,
                "quantity":             total_close_qty,
                "entry_price":          entry_price,
                "exit_price":           exit_price,
                "entry_time_ms":        entry_time,
                "exit_time_ms":         exit_time,
                "realized_pnl":         realized_pnl,
                "total_fees":           total_fees,
                "net_pnl":              net_pnl,
                "hold_time_ms":         exit_time - entry_time if entry_time else 0,
                "exit_reason":          exit_reason,
                "model_name":           model_name,
                "source":               fill.get("source", ""),
                **shortfall,
            })

            await event_bus.publish("risk:position_closed", {
                "symbol": symbol, "direction": direction,
                "realized_pnl": realized_pnl, "net_pnl": net_pnl,
            })
            log.info(
                "Closed position row: %s %s qty=%.4f pnl=%.2f exit=%s",
                symbol, direction, total_close_qty, realized_pnl, exit_reason,
            )
        except Exception:
            log.exception(
                "_build_close_row_for_fill failed for %s",
                fill.get("symbol", "?"),
            )

    async def build_final_close_row(self, prev: PositionInfo) -> None:
        """Safety net: when position fully disappears, check for unrecorded
        closing fills and build remaining rows.

        Called with a 2 s delay after a position disappears from the
        snapshot, giving time for in-flight fills to arrive first.
        """
        try:
            account_id = app_state.active_account_id
            unrecorded = await self._db.get_unrecorded_closing_fills(
                account_id, prev.position_id, prev.ticker, prev.direction,
            )
            if not unrecorded:
                log.debug(
                    "No unrecorded closing fills for %s %s",
                    prev.ticker, prev.direction,
                )
                return

            # Group by exchange_order_id → one closed_positions row per order
            groups: Dict[str, List[Dict]] = {}
            for f in unrecorded:
                key = f.get("exchange_order_id", "") or f"_fill_{f.get('id', '')}"
                groups.setdefault(key, []).append(f)

            for _order_id, fills in groups.items():
                await self._build_close_row_for_fill(account_id, fills[0])

            log.info(
                "Final close safety net: %d group(s) for %s %s",
                len(groups), prev.ticker, prev.direction,
            )
        except Exception:
            log.exception(
                "build_final_close_row failed for %s %s",
                prev.ticker, prev.direction,
            )

    # ── Helpers ─────────────────────────────────────────────────────────────

    async def _determine_exit_reason(
        self, account_id: int, exchange_order_id: str
    ) -> str:
        """Derive exit reason from the parent order's order_type."""
        if not exchange_order_id:
            return "manual"
        order = await self._db.get_order_by_exchange_id(
            account_id, exchange_order_id,
        )
        if not order:
            return "manual"
        otype = order.get("order_type", "")
        if "take_profit" in otype:
            return "tp_hit"
        if "trailing" in otype:
            return "trailing_stop"
        if "stop_loss" in otype or "stop" in otype:
            return "sl_hit"
        if otype == "market":
            return "manual"
        if otype == "limit":
            return "limit_close"
        return "manual"

    async def _compute_shortfall(
        self,
        account_id: int,
        symbol: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        entry_time_ms: int,
    ) -> Dict[str, Any]:
        """Compare actual entry/exit vs pre_trade_log intended prices.

        Returns dict with shortfall_entry, shortfall_exit (in bps),
        and model_name. All default to 0 / "" if no matching log found.
        """
        result: Dict[str, Any] = {
            "shortfall_entry": 0.0,
            "shortfall_exit":  0.0,
            "model_name":      "",
        }
        if not entry_time_ms or not entry_price:
            return result

        ptl = await self._db.get_pre_trade_for_shortfall(
            account_id, symbol, entry_time_ms,
        )
        if not ptl:
            return result

        result["model_name"] = ptl.get("model_name", "")
        intended_entry = ptl.get("effective_entry", 0) or ptl.get("average", 0)

        if intended_entry > 0:
            # bps: (actual − intended) / intended × 10 000
            # LONG positive = worse (overpaid); SHORT flip sign
            diff = (entry_price - intended_entry) / intended_entry * 10_000
            result["shortfall_entry"] = round(
                diff if direction == "LONG" else -diff, 2,
            )

        # Pick whichever intended exit is closer to actual exit
        intended_tp = ptl.get("tp_price", 0)
        intended_sl = ptl.get("sl_price", 0)
        if intended_tp and intended_sl:
            intended_exit = (
                intended_tp
                if abs(exit_price - intended_tp) < abs(exit_price - intended_sl)
                else intended_sl
            )
        else:
            intended_exit = intended_tp or intended_sl

        if intended_exit and exit_price:
            diff = (exit_price - intended_exit) / intended_exit * 10_000
            result["shortfall_exit"] = round(
                diff if direction == "LONG" else -diff, 2,
            )

        return result
