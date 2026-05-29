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
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core.event_bus import event_bus
from core.order_state import validate_transition, ACTIVE_STATES, OrderStatus, resolve_tpsl_direction
from core.state import app_state, PositionInfo

log = logging.getLogger("order_manager")


def _first_truthy(*vals: Any) -> Optional[float]:
    """Return the first non-null, non-zero value among ``vals``, else None.

    Backs the T2.4 junction ``planned_*`` snapshot source-priority: the
    spec's ``overridden_*`` / ``planned_*`` calc columns are preferred
    (if a future calculator ever populates them) over the legacy
    ``size`` / ``tp_price`` / ``sl_price`` the calculator writes today.
    The non-zero test also coerces an "absent" TP/SL — stored as ``0.0``
    in ``pre_trade_log`` (NOT NULL DEFAULT 0; HANDOFF lesson 7 / T1.7) —
    to ``None`` so the nullable junction column reflects "no planned
    level" rather than a literal 0.
    """
    for v in vals:
        if v:
            return v
    return None


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

        # 4. Mark active BASIC orders NOT in snapshot as canceled (1 query)
        #    Scoped to non-algo orders only (algo: prefix excluded).
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
            exclude_prefix="algo:",
        )
        if canceled:
            log.info("Marked %d missing basic orders as canceled", canceled)

        # 5. Rebuild cache from DB + enrich positions (via refresh_cache)
        await self.refresh_cache(account_id)

    # ── Algo Order Snapshot Processing ───────────────────────────────────────

    async def process_algo_snapshot(
        self, account_id: int, orders: List[Dict[str, Any]]
    ) -> None:
        """Upsert algo/conditional orders and mark stale algo orders canceled.

        Isolated from basic order snapshot: only affects orders with
        exchange_order_id starting with 'algo:'.
        """
        # 1. Upsert algo orders
        for o in orders:
            o.setdefault("account_id", account_id)
        if orders:
            await self._db.upsert_order_batch(orders)

        # 2. Mark stale algo orders canceled (scoped to algo: prefix)
        active_ids = [
            o["exchange_order_id"]
            for o in orders
            if o.get("exchange_order_id")
        ]
        canceled = await self._db.mark_stale_orders_canceled(
            account_id, active_ids,
            allow_cancel_all=len(orders) == 0,
            only_prefix="algo:",
        )
        if canceled:
            log.info("Marked %d stale algo orders as canceled", canceled)

        # 3. Rebuild cache + enrich
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

        prev_order = None
        if eid:
            existing = await self._db.get_active_orders_map(account_id)
            if eid in existing:
                prev_order = existing[eid]
                current_status = prev_order.get("status", "")
                new_status = order.get("status", "new")
                if not validate_transition(current_status, new_status):
                    log.warning(
                        "SR-1: rejected invalid transition %s→%s for order %s (WS update)",
                        current_status, new_status, eid,
                    )
                    return False

        await self._db.upsert_order_batch([order])
        await self._enrich_order_best_effort(order)
        # When a TP/SL child arrives, re-enrich the parent entry so its
        # tp/sl_trigger_price gets populated and correlation can run.
        # Without this, market orders that fill before children arrive
        # never get correlated (the parent has no further updates).
        await self._re_enrich_parent_on_child_arrival(account_id, order)
        self._emit_order_events(account_id, order)
        self._detect_modification_events(account_id, order, prev_order)
        # T216 (P1.T5): release the calc back to the re-match pool when
        # the operator cancels a working (unfilled) entry order.
        await self._release_calc_on_operator_cancel(account_id, order)
        self._publish_order_update(account_id, order)
        await self.refresh_cache(account_id)
        return True

    # ── DD-aware order gate (v2.4 Priority 1c) ─────────────────────────────

    def check_dd_gate_for_order(
        self, account_id: int, order: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        """Check whether *order* is allowed under current dd_state.

        New entries are gated when dd_state == limit + enforced mode.
        TP/SL modifications and reduce-only closes always pass.

        Returns ``(allowed, reason_or_None)``.
        """
        from core.dd_gate import dd_gate_allows_new_entry, is_new_entry

        if not is_new_entry(order):
            return True, None

        allowed, reason = dd_gate_allows_new_entry(account_id)
        if not allowed:
            try:
                from core.event_log import log_event
                log_event(account_id, "calculator_blocked", {
                    "gate": "order_manager_dd",
                    "order_type": "new_entry",
                    "symbol": order.get("symbol", ""),
                    "side": order.get("side", ""),
                }, source="order_manager")
            except Exception:
                log.warning("order dd gate log failed", exc_info=True)
        return allowed, reason

    # ── calc_id enrichment (v2.4) ────────────────────────────────────────────

    _TPSL_TYPES = frozenset({
        "stop_loss", "stop_market", "stop_loss_limit",
        "take_profit", "take_profit_market", "take_profit_limit",
    })

    async def _re_enrich_parent_on_child_arrival(
        self, account_id: int, order: Dict[str, Any]
    ) -> None:
        """When a TP/SL child order is persisted, re-enrich the parent entry.

        The parent's tp/sl_trigger_price gets populated from children, and
        correlation runs if calc_id is still NULL. Best-effort.
        """
        try:
            otype = (order.get("order_type") or "").lower()
            if not order.get("reduce_only") or otype not in self._TPSL_TYPES:
                return
            pos_id = order.get("exchange_position_id", "")
            if not pos_id:
                return

            import sqlite3, config
            conn = sqlite3.connect(config.DB_PATH)
            conn.row_factory = sqlite3.Row
            parent = conn.execute(
                "SELECT * FROM orders WHERE account_id = ? "
                "AND exchange_position_id = ? AND reduce_only = 0 LIMIT 1",
                (account_id, pos_id),
            ).fetchone()
            conn.close()

            if parent:
                from core.order_enrichment import enrich_order
                await enrich_order(dict(parent), config.DB_PATH)
        except Exception:
            log.debug("parent re-enrichment on child arrival skipped", exc_info=True)

    async def _enrich_order_best_effort(self, order: Dict[str, Any]) -> None:
        try:
            import config
            from core.order_enrichment import enrich_order
            await enrich_order(order, config.DB_PATH)
        except Exception:
            log.debug("order enrichment skipped", exc_info=True)

    def _snapshot_and_fix_isclose(self, account_id: int, fill: Dict[str, Any]):
        """Compute position fill snapshot, override adapter-supplied is_close.

        Returns the ``FillSnapshot`` so callers can inspect ``splits`` for
        the reversal-split path (Phase 0.0.4). Returns ``None`` on failure;
        callers should fall back to the single-fill path.

        Best-effort: on failure, the fill dict's adapter-supplied
        ``is_close`` is retained unchanged.
        """
        try:
            from core.position_snapshot import compute_fill_snapshot, persist_snapshot
            import config

            # Detect mode from fill's position_side (direction field)
            direction = fill.get("direction", "")
            mode = "hedge" if direction and direction not in ("BOTH", "") else "one_way"

            # Compute snapshot from current position state (pre-fill)
            snapshot = compute_fill_snapshot(fill, app_state.positions, mode=mode)

            # Override adapter-supplied is_close with snapshot-derived value
            fill["is_close"] = int(snapshot.is_close)

            # Persist snapshot to per-account DB (where position_fill_snapshots lives)
            try:
                from core.db_account_settings import _resolve_db_path
                pa_path = _resolve_db_path(account_id)
                persist_snapshot(snapshot, pa_path, account_id)
            except Exception:
                log.debug("snapshot persistence to per-account DB failed", exc_info=True)

            return snapshot

        except Exception:
            log.debug("is_close snapshot failed — using adapter value", exc_info=True)
            return None

    async def _reenrich_parent_after_fill(
        self, account_id: int, exchange_order_id: str,
    ) -> None:
        """Re-fire enrich_order on the parent order after a fill upsert.

        Called by ``_process_single_fill`` so the matcher gets a chance
        to evaluate avg_fill_price (now populated by
        ``upsert_fill_and_update_order``). For LIMIT orders the matcher
        already ran on the initial order_persisted event and either
        linked or set link_status (re-run is guarded by H3 in
        ``_try_correlate``). For MARKET orders this is the first call
        where avg_fill_price > 0 — without this hook, market correlation
        relies on the exchange firing a follow-up orders-WS update,
        which is adapter-dependent.

        Best-effort: failures logged, never raised.
        """
        if not exchange_order_id:
            return
        try:
            import sqlite3, config
            conn = sqlite3.connect(config.DB_PATH)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM orders "
                "WHERE account_id = ? AND exchange_order_id = ? "
                "  AND reduce_only = 0",
                (account_id, exchange_order_id),
            ).fetchone()
            conn.close()
            if row:
                from core.order_enrichment import enrich_order
                await enrich_order(dict(row), config.DB_PATH)
        except Exception:
            log.debug(
                "post-fill parent re-enrichment skipped for %s",
                exchange_order_id, exc_info=True,
            )

    def _enrich_fill_best_effort(self, fill: Dict[str, Any]) -> None:
        try:
            import config
            from core.order_enrichment import enrich_fill
            enrich_fill(fill, config.DB_PATH)
        except Exception:
            log.debug("fill enrichment skipped", exc_info=True)

    # ── Redis pub/sub publishers (v2.4 Phase 5) ─────────────────────────────

    def _publish_order_update(self, account_id: int, order: Dict[str, Any]) -> None:
        try:
            from core.pubsub.bus import get_bus
            from core.pubsub.channels import order_channel
            import asyncio
            asyncio.get_event_loop().create_task(get_bus().publish(
                order_channel(account_id), {
                    "exchange_order_id": order.get("exchange_order_id", ""),
                    "symbol": order.get("symbol", ""),
                    "side": order.get("side", ""),
                    "status": order.get("status", ""),
                }
            ))
        except Exception:
            pass

    def _publish_fill(self, account_id: int, fill: Dict[str, Any]) -> None:
        try:
            from core.pubsub.bus import get_bus
            from core.pubsub.channels import fill_channel
            import asyncio
            asyncio.get_event_loop().create_task(get_bus().publish(
                fill_channel(account_id), {
                    "exchange_fill_id": fill.get("exchange_fill_id", ""),
                    "symbol": fill.get("symbol", ""),
                    "side": fill.get("side", ""),
                    "price": fill.get("price", 0),
                    "quantity": fill.get("quantity", 0),
                }
            ))
        except Exception:
            pass

    # ── Trade event emission (v2.4) ──────────────────────────────────────────

    def _emit_order_events(self, account_id: int, order: Dict[str, Any]) -> None:
        """Emit trade events for order state changes. Best-effort."""
        try:
            from core.trade_event_log import log_trade_event
            from core.dd_gate import is_new_entry

            status = (order.get("status") or "").lower()
            eid = order.get("exchange_order_id", "")

            # Read calc_id from DB (may have just been set by enrichment)
            calc_id = None
            try:
                import sqlite3, config
                conn = sqlite3.connect(config.DB_PATH)
                row = conn.execute(
                    "SELECT calc_id FROM orders WHERE account_id=? AND exchange_order_id=?",
                    (account_id, eid),
                ).fetchone()
                conn.close()
                calc_id = row[0] if row else None
            except Exception:
                pass

            if status == "new" and is_new_entry(order):
                log_trade_event(account_id, calc_id, "order_placed", {
                    "symbol": order.get("symbol", ""),
                    "role": "entry",
                    "price": order.get("price", 0),
                    "side": order.get("side", ""),
                    "qty": order.get("quantity", 0),
                    "exchange_order_id": eid,
                }, source="order_manager")

            elif status in ("canceled", "expired"):
                log_trade_event(account_id, calc_id, "order_canceled", {
                    "symbol": order.get("symbol", ""),
                    "exchange_order_id": eid,
                    "order_type": order.get("order_type", ""),
                }, source="order_manager")

        except Exception:
            log.debug("order event emission failed", exc_info=True)

    async def _release_calc_on_operator_cancel(
        self, account_id: int, order: Dict[str, Any]
    ) -> None:
        """T216 (P1.T5 / plan §1 task 1.7): release a calc back to the
        re-match pool when its working entry order is cancelled.

        Spec §2 [C] / §4.4: when an order cancels before fill, its calc
        transitions ``matched → released`` and becomes eligible for
        re-match within its original window (the matcher already
        includes ``'released'`` in its candidate filter, T210).

        Cancel-reason classification (T216 decision): the engine is
        observe-only — it never initiates cancels, so it can't know
        from a "did we send a cancel" signal. For a working (unfilled,
        non-reduce-only) entry order, we DEFAULT to OPERATOR (the
        dominant case in the operator-mediated copy-paste workflow —
        the operator changed their mind in Quantower). Venue-initiated
        categories (GTC_EXPIRED / IOC_NO_FILL / VENUE_REJECTED / etc.,
        spec §3.4) need venue-specific reason-string mapping and are
        deferred to a follow-up task.

        Guards (all must hold to release):
          - status transitioned to 'canceled' (not 'expired' — that's
            venue-initiated GTC expiry, a different category)
          - not reduce_only (TP/SL close cancels aren't entry cancels)
          - filled_qty == 0 (a partial/full fill opened a position; the
            calc is matched + contributing and must NOT be released)
          - a linked calc_id exists and is currently 'matched'

        Idempotent: the transition UPDATE is scoped ``WHERE status='matched'``
        (T211 M3 pattern), so a repeat WS cancel for the same order is a
        no-op. Best-effort: failures log, never raise.

        NOTE: the snapshot-reconciliation cancel path
        (``mark_stale_orders_canceled``) is a bulk UPDATE that doesn't
        flow through here; releasing calcs for stale-canceled orders is
        a deferred follow-up.
        """
        status = (order.get("status") or "").lower()
        if status != "canceled":
            return
        if order.get("reduce_only"):
            return
        eid = order.get("exchange_order_id", "")
        if not eid:
            return

        try:
            async with self._db._conn.execute(
                "SELECT calc_id, filled_qty FROM orders "
                "WHERE account_id = ? AND exchange_order_id = ?",
                (account_id, eid),
            ) as cur:
                row = await cur.fetchone()
        except Exception:
            log.debug("release-on-cancel: order read failed for %s", eid, exc_info=True)
            return

        if not row:
            return
        calc_id = row[0]
        filled_qty = row[1] or 0.0
        if not calc_id:
            return  # UNPLANNED / unlinked order — nothing to release
        if filled_qty > 0:
            return  # position opened — calc stays matched + contributing

        # Capture the cancel reason on the order (T216: default OPERATOR).
        now_ms = int(time.time() * 1000)
        try:
            await self._db._conn.execute(
                "UPDATE orders SET cancel_reason_category = 'OPERATOR', "
                "cancel_reason_raw = ?, cancel_ts_ms = ? "
                "WHERE account_id = ? AND exchange_order_id = ?",
                (order.get("status", ""), now_ms, account_id, eid),
            )
            await self._db._conn.commit()
        except Exception:
            log.warning(
                "release-on-cancel: cancel-reason capture failed for %s",
                eid, exc_info=True,
            )

        # Release the calc: matched → released (TOCTOU-guarded).
        from core.calc_state import (
            CalcStatus,
            CalcTransitionRaceLost,
            transition,
        )

        async def _apply_release() -> None:
            cur2 = await self._db._conn.execute(
                "UPDATE pre_trade_log SET status = ? "
                "WHERE calc_id = ? AND status = ?",
                (CalcStatus.RELEASED.value, calc_id, CalcStatus.MATCHED.value),
            )
            await self._db._conn.commit()
            if cur2.rowcount == 0:
                # Calc wasn't 'matched' (already released, completed via
                # position, superseded, etc.) — nothing to release.
                raise CalcTransitionRaceLost(
                    calc_id, CalcStatus.MATCHED.value, CalcStatus.RELEASED.value,
                )

        try:
            # T217: no event_payload — RELEASED has no entry in
            # TRANSITION_EVENT_MAP (calc_state.py), so transition()
            # emits no event for this edge and any payload would be
            # dead. (Spec §9's calc:order_cancelled event is a separate,
            # deferred concern — see T216 notes.)
            await transition(
                calc_id=calc_id,
                current_status=CalcStatus.MATCHED.value,
                target_status=CalcStatus.RELEASED.value,
                apply_fn=_apply_release,
            )
            log.info("Released calc %s on operator cancel of order %s", calc_id, eid)
        except CalcTransitionRaceLost as exc:
            log.info("%s", exc)
        except Exception:
            log.warning(
                "calc release on cancel failed for calc_id=%s order=%s",
                calc_id, eid, exc_info=True,
            )

    async def _complete_calcs_on_close(
        self, account_id: int, calc_ids, position_id: str,
    ) -> None:
        """T221 (P1.T6 / plan §1 task 1.8): auto-complete contributing
        calcs when a position closes.

        Spec §2 [D/E] / §5 / §9: on position close, each contributing
        calc transitions ``→ completed_via_position`` and emits
        ``calc:completed`` (carrying ``position_id``). Valid source
        states are ``matched`` and ``partially_actioned`` (per
        ``CALC_TRANSITIONS``); calcs in any other state are skipped
        (released/superseded/cancelled/already-completed).

        TOCTOU-guarded (T211 M3): the UPDATE is scoped ``WHERE status =
        <read status>``; rowcount=0 → CalcTransitionRaceLost → event
        skipped. Best-effort per calc — one failure doesn't block the
        others or the close-row build (caller is already inside the
        close-row try/except).

        PHASE-1 SIMPLIFICATION (multi-TP): in Phase 1 this runs on every
        close-row build. For a single-close position (the common case)
        that's exactly-once + correct. For a multi-TP ladder (Phase
        2.11), the calc completes on the FIRST partial close (premature)
        and subsequent partial closes no-op via the guard. Phase 2.11
        (position-lifecycle tracking) will refine this to complete only
        on the FINAL close (size→0). Acceptable for Phase 1 — multi-TP
        lifecycle isn't wired yet, and the calc is genuinely being
        actioned via the position either way.
        """
        from core.calc_state import (
            CalcStatus,
            CalcTransitionRaceLost,
            transition,
        )

        completable = {
            CalcStatus.MATCHED.value,
            CalcStatus.PARTIALLY_ACTIONED.value,
        }

        for calc_id in calc_ids:
            if not calc_id:
                continue
            try:
                async with self._db._conn.execute(
                    "SELECT status FROM pre_trade_log "
                    "WHERE account_id = ? AND calc_id = ?",
                    (account_id, calc_id),
                ) as cur:
                    row = await cur.fetchone()
            except Exception:
                log.debug(
                    "complete-on-close: status read failed for calc_id=%s",
                    calc_id, exc_info=True,
                )
                continue
            if not row:
                continue
            current_status = row[0]
            if current_status not in completable:
                continue  # released/superseded/cancelled/already-completed

            # T215 M3: no default-arg capture — transition() awaits
            # apply_fn fully before the loop advances.
            async def _apply_complete() -> None:
                cur2 = await self._db._conn.execute(
                    "UPDATE pre_trade_log SET status = ? "
                    "WHERE calc_id = ? AND status = ?",
                    (CalcStatus.COMPLETED_VIA_POSITION.value,
                     calc_id, current_status),
                )
                await self._db._conn.commit()
                if cur2.rowcount == 0:
                    raise CalcTransitionRaceLost(
                        calc_id, current_status,
                        CalcStatus.COMPLETED_VIA_POSITION.value,
                    )

            try:
                await transition(
                    calc_id=calc_id,
                    current_status=current_status,
                    target_status=CalcStatus.COMPLETED_VIA_POSITION.value,
                    apply_fn=_apply_complete,
                    event_payload={"position_id": position_id},
                )
                log.info(
                    "Completed calc %s on close of position %s",
                    calc_id, position_id,
                )
            except CalcTransitionRaceLost as exc:
                log.info("%s", exc)
            except Exception:
                log.warning(
                    "calc complete-on-close failed for calc_id=%s pos=%s",
                    calc_id, position_id, exc_info=True,
                )

    def _detect_modification_events(
        self, account_id: int, order: Dict[str, Any], prev_order: Optional[Dict]
    ) -> None:
        """Detect TP/SL price modifications and emit trade events."""
        if not prev_order:
            return
        try:
            from core.trade_event_log import log_trade_event

            otype = (order.get("order_type") or "").lower()
            if otype not in ("stop_loss", "stop_market", "stop_loss_limit",
                             "take_profit", "take_profit_market", "take_profit_limit"):
                return

            new_stop = order.get("stop_price") or order.get("price", 0)
            old_stop = prev_order.get("stop_price") or prev_order.get("price", 0)
            if not new_stop or not old_stop or new_stop == old_stop:
                return

            # Determine event type
            is_tp = otype in ("take_profit", "take_profit_market", "take_profit_limit")
            event_type = "tp_modified" if is_tp else "sl_modified"

            # Time since entry (from position's first fill)
            time_since = 0
            try:
                import sqlite3, config as _cfg
                pos_id = order.get("exchange_position_id", "")
                if pos_id:
                    conn = sqlite3.connect(_cfg.DB_PATH)
                    row = conn.execute(
                        "SELECT MIN(timestamp_ms) FROM fills WHERE "
                        "account_id = ? AND exchange_position_id = ? AND is_close = 0",
                        (account_id, pos_id),
                    ).fetchone()
                    conn.close()
                    if row and row[0]:
                        import time
                        time_since = int(time.time() * 1000) - row[0]
            except Exception:
                pass

            # Read calc_id from parent entry order
            calc_id = None
            try:
                import sqlite3, config as _cfg2
                pos_id = order.get("exchange_position_id", "")
                conn = sqlite3.connect(_cfg2.DB_PATH)
                row = conn.execute(
                    "SELECT calc_id FROM orders WHERE account_id = ? AND "
                    "exchange_position_id = ? AND reduce_only = 0 AND calc_id IS NOT NULL LIMIT 1",
                    (account_id, pos_id),
                ).fetchone()
                conn.close()
                calc_id = row[0] if row else None
            except Exception:
                pass

            log_trade_event(account_id, calc_id, event_type, {  # type: ignore[arg-type]
                "symbol": order.get("symbol", ""),
                "exchange_order_id": order.get("exchange_order_id", ""),
                "from_price": old_stop,
                "to_price": new_stop,
                "time_since_entry_ms": time_since,
            }, source="order_manager")

        except Exception:
            log.debug("modification event detection failed", exc_info=True)

    def _emit_fill_events(self, account_id: int, fill: Dict[str, Any]) -> None:
        """Emit trade events for fills. Best-effort."""
        try:
            from core.trade_event_log import log_trade_event

            calc_id = fill.get("calc_id")
            # Try to read calc_id from parent order if not on fill
            if not calc_id:
                try:
                    import sqlite3, config
                    conn = sqlite3.connect(config.DB_PATH)
                    row = conn.execute(
                        "SELECT calc_id FROM orders WHERE account_id=? AND exchange_order_id=?",
                        (account_id, fill.get("exchange_order_id", "")),
                    ).fetchone()
                    conn.close()
                    calc_id = row[0] if row else None
                except Exception:
                    pass

            role = fill.get("role", "")
            log_trade_event(account_id, calc_id, "order_filled", {
                "symbol": fill.get("symbol", ""),
                "role": role,
                "fill_price": fill.get("price", 0),
                "fill_qty": fill.get("quantity", 0),
                "fee": fill.get("fee", 0),
                "exchange_order_id": fill.get("exchange_order_id", ""),
            }, source="order_manager")

            # position_opened: first fill for this calc_id
            if calc_id and not fill.get("is_close"):
                try:
                    import sqlite3, config as _cfg
                    conn = sqlite3.connect(_cfg.DB_PATH)
                    prior = conn.execute(
                        "SELECT COUNT(*) FROM fills WHERE calc_id=? AND account_id=? AND id != ("
                        "  SELECT id FROM fills WHERE account_id=? AND exchange_fill_id=? LIMIT 1"
                        ")",
                        (calc_id, account_id, account_id, fill.get("exchange_fill_id", "")),
                    ).fetchone()[0]
                    conn.close()
                    if prior == 0:
                        log_trade_event(account_id, calc_id, "position_opened", {
                            "symbol": fill.get("symbol", ""),
                            "fill_price": fill.get("price", 0),
                            "qty": fill.get("quantity", 0),
                            "exchange_position_id": fill.get("exchange_position_id", ""),
                        }, source="order_manager")
                except Exception:
                    pass

            # partial_close: reduce-only fill, position still open
            if fill.get("is_close"):
                try:
                    import sqlite3, config as _cfg2
                    pos_id = fill.get("terminal_position_id", "")
                    if pos_id:
                        # Check if position still has remaining qty
                        pos = next(
                            (p for p in app_state.positions if p.position_id == pos_id), None
                        )
                        if pos and pos.contract_amount > 0:
                            log_trade_event(account_id, calc_id, "partial_close", {
                                "symbol": fill.get("symbol", ""),
                                "fill_price": fill.get("price", 0),
                                "fill_qty": fill.get("quantity", 0),
                                "remaining_qty": pos.contract_amount,
                            }, source="order_manager")
                except Exception:
                    pass

        except Exception:
            log.debug("fill event emission failed", exc_info=True)

    # ── Cache Refresh ──────────────────────────────────────────────────────

    async def refresh_cache(self, account_id: int) -> None:
        """Rebuild _open_orders from DB and enrich positions.

        SR-1: This is the sole controlled entry point for cache rebuilds.
        External callers must use this instead of writing _open_orders directly.
        """
        self._open_orders = await self._db.query_open_orders_all(account_id)
        self.enrich_positions_tpsl(app_state.positions)
        # T2.3: stamp each live position's primary calc from the junction.
        await self._enrich_positions_calc_id(account_id, app_state.positions)

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
                and resolve_tpsl_direction(o.get("position_side", ""), o.get("side", "")) == pos.direction
                and o.get("order_type") in ("take_profit",)
                and o.get("status") in ("new", "partially_filled")
            ]
            sl_orders = [
                o for o in self._open_orders
                if o.get("symbol") == pos.ticker
                and resolve_tpsl_direction(o.get("position_side", ""), o.get("side", "")) == pos.direction
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
        """Record fill, update parent order, refresh position fees from DB.

        Phase 0.0.4 — reversal dispatch: when the snapshot reports that
        this single fill crosses net qty from positive to negative or
        vice-versa, two fill rows are written instead of one (the close
        portion of the OLD direction + the open portion of the NEW
        direction). The close keeps the original tradeId; the open gets
        a ``synth:{tradeId}:open`` synthetic id. Downstream callers
        (close-row builder, position_grouping, reconciler) walk the two
        rows as a normal close+open sequence — no further special-case
        handling required.
        """
        fill.setdefault("account_id", account_id)

        # v2.4 Priority 5a: derive is_close from position state snapshot.
        # Must run BEFORE fill is persisted so qty_before reflects pre-fill
        # state. app_state.positions is updated by a separate WS event
        # (ACCOUNT_UPDATE), so at fill-processing time it reflects the
        # state before this fill.
        snapshot = self._snapshot_and_fix_isclose(account_id, fill)

        if snapshot is not None and snapshot.splits:
            await self._process_reversal_split(account_id, fill, snapshot)
            return

        await self._process_single_fill(account_id, fill)

    async def _process_single_fill(
        self, account_id: int, fill: Dict[str, Any]
    ) -> None:
        """Standard single-fill write path. Used directly for non-reversal
        fills and called twice (once per portion) by the reversal-split
        dispatcher."""
        exchange_order_id = fill.get("exchange_order_id", "")

        # 1+2. Upsert fill + update parent order in ONE commit
        await self._db.upsert_fill_and_update_order(fill, exchange_order_id)
        # T211 H4: re-fire enrich_order on the parent so the matcher
        # gets a chance to run against the now-populated avg_fill_price.
        # The new strict matcher (spec §4.1 MARKET 6/6) needs
        # avg_fill_price > 0 to evaluate the entry criterion; the
        # initial enrich_order on order_persisted runs before any fill,
        # so it defers. Without this re-fire, market orders whose
        # exchange happens NOT to send a follow-up orders-WS update
        # after the fill would never auto-correlate. Best-effort —
        # exceptions are swallowed by _enrich_order_best_effort.
        await self._reenrich_parent_after_fill(account_id, exchange_order_id)
        self._enrich_fill_best_effort(fill)
        # T2.1: on an opening fill, attach the position↔calc junction row
        # and generate/propagate the position's lifecycle_id. Runs after
        # enrichment so the parent order's calc_id is populated (matcher
        # + propagation already ran above). No-op for closing fills.
        await self._link_position_calc_on_open(account_id, fill)
        # T2.2: on a closing fill, stamp the fill's calc_id + lifecycle_id
        # from the position's primary (most-contributing) calc. No-op for
        # opening fills. Runs before close-row scheduling so the fills row
        # carries position attribution.
        await self._stamp_closing_fill_attribution(account_id, fill)
        self._emit_fill_events(account_id, fill)
        self._publish_fill(account_id, fill)

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

    async def _process_reversal_split(
        self,
        account_id: int,
        fill: Dict[str, Any],
        snapshot: Any,
    ) -> None:
        """Multi-write path for reversal fills (Phase 0.0.4).

        Allocates the fill's fee and realized_pnl proportionally:
          - close portion (qty = |qty_before|) gets the full
            realized_pnl (it's the PnL from the close)
          - open portion (qty = fill_qty - |qty_before|) gets 0 pnl
          - fee is allocated by qty ratio so the sum equals the
            original fill's fee

        terminal_position_id semantics:
          - close portion KEEPS the original ``terminal_position_id``
            (the old position being closed)
          - open portion clears it — a new position is opening; its
            terminal_position_id will be assigned by the next
            ACCOUNT_UPDATE event from the platform / plugin
        """
        fill_qty_total = abs(float(fill.get("quantity", 0) or 0))
        fill_fee_total = float(fill.get("fee", 0) or 0)
        fill_realized_pnl_total = float(fill.get("realized_pnl", 0) or 0)

        for split in snapshot.splits:
            portion_qty = float(split.quantity)
            portion_ratio = portion_qty / fill_qty_total if fill_qty_total else 0.0
            portion_fee = fill_fee_total * portion_ratio
            portion_pnl = fill_realized_pnl_total if split.is_close else 0.0

            portion_fill = dict(fill)
            portion_fill["exchange_fill_id"] = split.exchange_fill_id
            portion_fill["is_close"] = int(split.is_close)
            portion_fill["direction"] = split.direction
            portion_fill["quantity"] = portion_qty
            portion_fill["fee"] = portion_fee
            portion_fill["realized_pnl"] = portion_pnl
            if not split.is_close:
                # The open portion creates a new position; clear the
                # OLD position's terminal_position_id so a stale pos_id
                # doesn't propagate to the new direction's records.
                portion_fill["terminal_position_id"] = ""

            await self._process_single_fill(account_id, portion_fill)

    # ── Position ↔ calc junction (Phase 2.1) ────────────────────────────────

    async def _position_primary_calc(
        self, account_id: int, position_id: str,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Return ``(calc_id, lifecycle_id)`` of a position's PRIMARY calc.

        Primary = the most-contributing junction row (largest
        ``contributed_qty``; tie-break earliest ``first_fill_ts`` —
        spec §3.2). ``(None, None)`` if the position has no junction.
        One source of truth for the §3.2 rule, shared by the closing-fill
        stamp (T2.2) and the live PositionInfo enrichment (T2.3).
        """
        if not position_id:
            return None, None
        try:
            async with self._db._conn.execute(
                "SELECT calc_id, lifecycle_id, contributed_qty "
                "FROM positions_calcs "
                "WHERE position_id = ? AND account_id = ? "
                "ORDER BY first_fill_ts ASC, id ASC",
                (position_id, account_id),
            ) as cur:
                links = await cur.fetchall()
        except Exception:
            log.debug(
                "primary-calc read failed for position %s", position_id,
                exc_info=True,
            )
            return None, None
        # Rows ordered by first_fill_ts ASC; max() returns the FIRST
        # maximal element, so ties resolve to the earliest entry.
        # default=None guards an empty result (no junction) without a
        # separate truthiness check that an empty-but-truthy iterable
        # could slip past.
        primary = max(links, key=lambda r: r[2] or 0.0, default=None)
        if primary is None:
            return None, None
        lifecycle_id = primary[1] or next((r[1] for r in links if r[1]), None)
        return primary[0], lifecycle_id

    async def _link_position_calc_on_open(
        self, account_id: int, fill: Dict[str, Any]
    ) -> None:
        """T2.1 (plan §2 task 2.1): on each opening fill, upsert the
        ``positions_calcs`` junction row and generate / propagate the
        position's ``lifecycle_id``.

        Spec §3.1 / §3.5 / §7. The junction is keyed by
        ``terminal_position_id`` (the engine's universal position
        identity — see the P2.T1 schema note in ``database.py``), one
        row per (position, calc, order). ``contributed_qty`` accumulates
        across fills of the same triple via the UPSERT.

        ``lifecycle_id`` (UUID v4) is the operator-facing trade
        reference: generated at the FIRST opening fill of a position and
        reused by every later fill / scale-in calc on that position
        (spec §3.5 — "multi-calc scale-ins share same lifecycle_id").
        Back-filled onto the contributing ``pre_trade_log`` + ``orders``
        rows (idempotent ``WHERE lifecycle_id IS NULL``).

        T2.4: also snapshots the calc's planned ``size`` / ``TP`` / ``SL``
        onto the junction row at contribution time (per-calc — a scale-in
        gets its own row with its own calc's plan). See the snapshot
        block below for source-column priority.

        Skips (no attribution possible) when:
          - the fill is a close (only opening fills seed the junction);
          - ``terminal_position_id`` is empty (reversal-open portion,
            or the Binance one-way pre-ACCOUNT_UPDATE window — the
            position key isn't known yet);
          - the parent order has no ``calc_id`` (UNPLANNED / unlinked —
            nothing to attribute).

        Best-effort: failures log + return; never break the fill hot
        path. All reads/writes go through ``self._db._conn`` (the
        single calc-linkage DB, ``config.DB_PATH``), matching the
        sibling Phase-1 transition sites.
        """
        if fill.get("is_close"):
            return
        pos_id = fill.get("terminal_position_id", "") or ""
        if not pos_id:
            return
        eoid = fill.get("exchange_order_id", "") or ""
        if not eoid:
            return

        try:
            async with self._db._conn.execute(
                "SELECT id, calc_id FROM orders "
                "WHERE account_id = ? AND exchange_order_id = ?",
                (account_id, eoid),
            ) as cur:
                orow = await cur.fetchone()
        except Exception:
            log.debug("junction link: order read failed for %s", eoid, exc_info=True)
            return
        if not orow:
            return
        order_id = orow[0]
        calc_id = orow[1]
        if not calc_id:
            return  # UNPLANNED / unlinked entry — nothing to attribute

        # Reuse the position's existing lifecycle_id if a prior fill on
        # this position already established one (multi-fill / scale-in);
        # otherwise this is the first opening fill → mint a UUID v4.
        #
        # ASSUMPTION (engine-wide invariant): terminal_position_id
        # identifies ONE position instance, never reused across a
        # close→reopen on the same symbol/direction slot. The whole
        # position subsystem already depends on this — get_position_fills
        # does a strict tpid match and _build_close_row_for_fill VWAPs
        # opens by tpid; a recurring tpid would corrupt those long before
        # it reached here. The live paths hold it: binance_ws leaves
        # PositionInfo.position_id="" (→ empty tpid → skipped above), and
        # Quantower emits a per-position-object id. IF a future adapter
        # emits a recurring slot-id, this lookup would bleed a closed
        # trade's lifecycle into a new one — fix is seal-at-close, but
        # that must distinguish full vs partial (Phase 2.11 multi-TP)
        # close, so it's deferred until an adapter actually violates the
        # invariant. See HANDOFF "lifecycle_id vs tpid-reuse".
        try:
            async with self._db._conn.execute(
                "SELECT lifecycle_id FROM positions_calcs "
                "WHERE position_id = ? AND account_id = ? "
                "  AND lifecycle_id IS NOT NULL LIMIT 1",
                (pos_id, account_id),
            ) as cur:
                lrow = await cur.fetchone()
        except Exception:
            log.debug("junction link: lifecycle lookup failed for %s", pos_id, exc_info=True)
            return
        lifecycle_id = lrow[0] if lrow and lrow[0] else str(uuid.uuid4())

        # T2.4 (plan §2 task 2.4): snapshot the calc's planned size / TP /
        # SL onto the junction row at contribution time (spec §3.1).
        # Source priority (spec deviation, forced by reality): spec §3.1
        # says planned_size ← calc.overridden_size or planned_size, but
        # those P0.T3 columns are NULL on EVERY live calc — the calculator
        # only ever writes the legacy size/tp_price/sl_price (verified
        # T231: 0/118 rows populate overridden_*/planned_*). So source the
        # spec columns first (forward-compat if a future calculator wires
        # them) and fall back to the legacy columns the calculator writes
        # today. Per-calc: each (position, calc, order) row snapshots ITS
        # OWN calc, so a scale-in's new junction row carries the new
        # calc's plan. size_delta_pct stays NULL — deferred to T2.5/close
        # (plan + spec §3.2; it needs the cumulative contributed_qty that
        # the UPSERT only knows SQL-side).
        planned_size = planned_tp = planned_sl = None
        try:
            async with self._db._conn.execute(
                "SELECT overridden_size, planned_size, size, "
                "       overridden_tp, planned_tp, tp_price, "
                "       overridden_sl, planned_sl, sl_price "
                "FROM pre_trade_log WHERE calc_id = ? AND account_id = ? "
                "ORDER BY id ASC LIMIT 1",
                (calc_id, account_id),
            ) as cur:
                prow = await cur.fetchone()
            if prow:
                planned_size = _first_truthy(prow[0], prow[1], prow[2])
                planned_tp = _first_truthy(prow[3], prow[4], prow[5])
                planned_sl = _first_truthy(prow[6], prow[7], prow[8])
        except Exception:
            log.debug(
                "junction link: planned_* snapshot read failed for calc %s",
                calc_id, exc_info=True,
            )

        qty = abs(float(fill.get("quantity", 0) or 0))
        ts = int(fill.get("timestamp_ms", 0) or 0)

        # Upsert the junction row (cumulative contributed_qty). The UPSERT
        # omits planned_* from DO UPDATE SET, so this first-contribution
        # snapshot is PRESERVED across later fills of the same triple
        # (snapshot-at-contribution-time). size_delta_pct left NULL —
        # computed at close in T2.5.
        await self._db.upsert_position_calc_link({
            "position_id":     pos_id,
            "calc_id":         calc_id,
            "order_id":        order_id,
            "account_id":      account_id,
            "contributed_qty": qty,
            "first_fill_ts":   ts,
            "last_fill_ts":    ts,
            "planned_size":    planned_size,
            "planned_tp":      planned_tp,
            "planned_sl":      planned_sl,
            "lifecycle_id":    lifecycle_id,
        })

        # Back-fill lifecycle_id onto the contributing calc + order + this
        # opening fill (spec §3.5 lists fills among the lifecycle_id
        # stamping targets). Idempotent via WHERE lifecycle_id IS NULL:
        # the first opening fill stamps; repeat fills no-op. A calc
        # contributes to one position lifecycle and an order belongs to
        # one position, so the stamped value is always the right one.
        # T232: the fill stamp closes the spec-§3.5 gap where forward
        # OPENING fills carried NULL fills.lifecycle_id (only closing
        # fills — T2.2 — and backfilled legacy fills had it), which would
        # have left the Phase-7 single-key /context/lifecycle/{id} fills
        # join incomplete for new positions.
        fill_id = fill.get("exchange_fill_id", "") or ""
        try:
            await self._db._conn.execute(
                "UPDATE pre_trade_log SET lifecycle_id = ? "
                "WHERE calc_id = ? AND lifecycle_id IS NULL",
                (lifecycle_id, calc_id),
            )
            await self._db._conn.execute(
                "UPDATE orders SET lifecycle_id = ? "
                "WHERE id = ? AND lifecycle_id IS NULL",
                (lifecycle_id, order_id),
            )
            if fill_id:
                await self._db._conn.execute(
                    "UPDATE fills SET lifecycle_id = ? "
                    "WHERE account_id = ? AND exchange_fill_id = ? "
                    "  AND lifecycle_id IS NULL",
                    (lifecycle_id, account_id, fill_id),
                )
            await self._db._conn.commit()
        except Exception:
            log.warning(
                "junction link: lifecycle back-fill failed for calc=%s order=%s",
                calc_id, order_id, exc_info=True,
            )

        log.info(
            "Linked position %s ↔ calc %s (order_id=%s, lifecycle=%s, qty=%.6f)",
            pos_id, calc_id, order_id, lifecycle_id, qty,
        )

    async def _stamp_closing_fill_attribution(
        self, account_id: int, fill: Dict[str, Any]
    ) -> None:
        """T2.2 (plan §2 task 2.2): stamp ``calc_id`` + ``lifecycle_id``
        on a closing fill, inherited from the position's PRIMARY calc.

        The primary is the most-contributing calc in the position's
        ``positions_calcs`` junction — largest ``contributed_qty``,
        tie-break earliest ``first_fill_ts`` (spec §3.2, the same basis
        as the close-row delta computation in T2.5/T2.6). All junction
        rows for one position share the same ``lifecycle_id``.

        Closing fills usually carry no calc_id of their own (reduce-only
        TP/SL/manual closes never pass through the matcher); this
        attributes them to the position they close. Overrides any value
        ``enrich_fill`` set from the close order — the position's primary
        is authoritative for position attribution.

        No-op (nothing to inherit) for opening fills, empty
        ``terminal_position_id``, or positions with no junction
        (UNPLANNED, or the binance_ws empty-tpid path). Best-effort; all
        I/O via ``self._db._conn``.
        """
        if not fill.get("is_close"):
            return
        pos_id = fill.get("terminal_position_id", "") or ""
        if not pos_id:
            return
        fill_id = fill.get("exchange_fill_id", "") or ""
        if not fill_id:
            return

        primary_calc_id, lifecycle_id = await self._position_primary_calc(
            account_id, pos_id,
        )
        if not primary_calc_id and not lifecycle_id:
            return  # no junction → nothing to inherit

        try:
            await self._db._conn.execute(
                "UPDATE fills SET calc_id = ?, lifecycle_id = ? "
                "WHERE account_id = ? AND exchange_fill_id = ?",
                (primary_calc_id, lifecycle_id, account_id, fill_id),
            )
            await self._db._conn.commit()
            log.info(
                "Stamped closing fill %s ← position %s primary calc %s "
                "(lifecycle %s)",
                fill_id, pos_id, primary_calc_id, lifecycle_id,
            )
        except Exception:
            log.warning(
                "close-fill stamp: update failed for fill=%s pos=%s",
                fill_id, pos_id, exc_info=True,
            )

    async def _enrich_positions_calc_id(
        self, account_id: int, positions: List[PositionInfo]
    ) -> None:
        """T2.3 (plan §2 task 2.3): set ``PositionInfo.calc_id`` to each
        live position's primary (most-contributing) junction calc.

        Called from ``refresh_cache`` (the controlled position-enrichment
        entry point), so it covers both stated triggers: the live
        first-fill case (a fill's order update drives a refresh) and
        restart rehydrate (the next order snapshot or the periodic
        refresh loop drives one). Re-evaluated each refresh so the
        primary stays current as the junction grows (scale-in);
        ``calc_id`` is also in ``_PRESERVE_FIELDS`` so a snapshot rebuild
        between refreshes doesn't blank the live value.

        ONE batched junction read per refresh (not per position) — this
        runs on every WS order update, so the fan-out is kept off the
        hot path. Best-effort and AUTHORITATIVE (T230 R2): calc_id mirrors
        the junction each refresh — set to the primary when a junction row
        exists, and CLEARED to "" when none does (UNPLANNED, pre-first-
        fill, or a same-(symbol,direction) reopen that inherited a stale
        calc_id via _PRESERVE_FIELDS). See the per-position loop below.
        """
        if not any(p.position_id for p in positions):
            return
        try:
            async with self._db._conn.execute(
                "SELECT position_id, calc_id, contributed_qty "
                "FROM positions_calcs WHERE account_id = ? "
                "ORDER BY first_fill_ts ASC, id ASC",
                (account_id,),
            ) as cur:
                rows = await cur.fetchall()
        except Exception:
            # Read failed — leave calc_id untouched (don't clear on error).
            log.debug("calc_id enrichment: junction read failed", exc_info=True)
            return
        # Primary calc per position: largest contributed_qty, tie-break
        # earliest first_fill_ts (spec §3.2). Rows are ordered by
        # first_fill_ts ASC and we only replace on a strict '>', so the
        # earliest row wins a tie — same rule as _position_primary_calc.
        primary: Dict[str, Tuple[str, float]] = {}
        for pid, cid, qty in rows:
            qty = qty or 0.0
            best = primary.get(pid)
            if best is None or qty > best[1]:
                primary[pid] = (cid, qty)
        # Authoritative: calc_id mirrors the junction on each refresh.
        # A position with no junction row is CLEARED — UNPLANNED, a
        # pre-first-fill position, or a same-(symbol,direction) reopen
        # that inherited a stale calc_id via _PRESERVE_FIELDS (T226
        # holistic-audit R2). Self-heals to the right calc once the new
        # position's first opening fill writes its junction.
        for pos in positions:
            if not pos.position_id:
                continue  # binance one-way / pre-snapshot — no junction key
            best = primary.get(pos.position_id)
            pos.calc_id = best[0] if (best and best[0]) else ""

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
            # Phase 0.0.5 (T188 / T178 Layer 3 fix): get_position_fills is
            # now STRICT — empty pos_id returns []. For the Binance
            # one-way path (engine's own WS never populates
            # terminal_position_id), resolve opens via the canonical
            # chronological-walk in position_grouping rather than the
            # cross-position-contaminating SQL fallback that was removed.
            if pos_id:
                opens = await self._db.get_position_fills(
                    account_id, pos_id, symbol, direction, is_close=False,
                )
            else:
                from core.position_grouping import find_opens_for_position_close_at
                close_ts = int(fill.get("timestamp_ms", 0) or 0)
                all_fills = await self._db.get_fills_for_symbol_direction(
                    account_id, symbol, direction,
                )
                opens = find_opens_for_position_close_at(
                    all_fills,
                    account_id=account_id,
                    symbol=symbol,
                    direction=direction,
                    close_ts_ms=close_ts,
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
            # HIGH-009: cap close-qty for fee allocation only — an overfill
            # (total_close_qty > total_open_qty) must not inflate prop_entry
            # beyond 100% of entry_fees. Uncapped total_close_qty is preserved
            # for exit_price (line 656) and the persisted "quantity" field
            # (line 699), which must reflect the actual close size.
            close_qty_for_fees = total_close_qty
            if total_open_qty and total_close_qty > total_open_qty:
                log.warning(
                    "overfill on %s %s: total_close_qty=%.6f exceeds "
                    "total_open_qty=%.6f; capping for fee allocation only",
                    symbol, direction, total_close_qty, total_open_qty,
                )
                close_qty_for_fees = total_open_qty
            prop_entry  = (
                entry_fees * (close_qty_for_fees / total_open_qty)
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

            # ── T2.6: closed_positions.calc_id + lifecycle_id = the
            # position's MOST-CONTRIBUTING calc (junction primary; spec
            # §3.2/§3.5), aligning the closed row with fills.calc_id (T2.2),
            # PositionInfo.calc_id (T2.3), and the T2.5 delta basis — closing
            # the R1 divergence where this row used the "earliest opening
            # fill with a calc_id" rule while everything else used the
            # most-contributing one. Fall back to that Phase-1 rule (calc_id
            # only; lifecycle stays NULL) when the position has no junction
            # — UNPLANNED, or the binance empty-tpid one-way path — so those
            # positions keep their earliest-fill attribution.
            primary_calc_id, primary_lifecycle = await self._position_primary_calc(
                account_id, pos_id,
            )
            close_calc_id = primary_calc_id
            close_lifecycle_id = primary_lifecycle
            if not close_calc_id and opens:
                for f in opens:
                    if f.get("calc_id"):
                        close_calc_id = f["calc_id"]
                        break

            # ── T2.5: close-time deltas vs the most-contributing calc ───
            # Spec §3.2 delta-basis rule. Best-effort (try/except → {}),
            # so a junction/calc read failure never blocks the close-row
            # write. Deterministically recomputed on every close-row build,
            # and preserved across INSERT OR REPLACE in insert_closed_position.
            deltas = await self._compute_close_deltas(
                account_id, pos_id, entry_price, total_open_qty,
                exit_price, entry_time, exit_time,
            )

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
                "calc_id":              close_calc_id,
                "lifecycle_id":         close_lifecycle_id,
                **shortfall,
                **deltas,
            })

            await event_bus.publish("risk:position_closed", {
                "symbol": symbol, "direction": direction,
                "realized_pnl": realized_pnl, "net_pnl": net_pnl,
            })

            # v2.4: emit position_closed trade event
            try:
                from core.trade_event_log import log_trade_event
                log_trade_event(account_id, close_calc_id, "position_closed", {
                    "symbol": symbol, "direction": direction,
                    "entry_price": round(entry_price, 8),
                    "exit_price": round(exit_price, 8),
                    "realized_pnl": round(realized_pnl, 4),
                    "net_pnl": round(net_pnl, 4),
                    "exit_reason": exit_reason,
                }, source="order_manager")
            except Exception:
                log.debug("position_closed trade event failed", exc_info=True)

            # T221 (P1.T6): auto-complete contributing calcs. Phase 1
            # contributing-calc set = distinct calc_ids across the
            # opening fills (the positions_calcs junction is Phase 2).
            # Runs AFTER the close row + events are persisted so a
            # completion failure can't undo the close. Best-effort.
            contributing_calc_ids = {
                f["calc_id"] for f in opens if f.get("calc_id")
            }
            if not contributing_calc_ids and close_calc_id:
                contributing_calc_ids = {close_calc_id}
            if contributing_calc_ids:
                await self._complete_calcs_on_close(
                    account_id, contributing_calc_ids, pos_id,
                )

            log.info(
                "Closed position row: %s %s qty=%.4f pnl=%.2f exit=%s",
                symbol, direction, total_close_qty, realized_pnl, exit_reason,
            )
        except Exception as e:
            log.exception(
                "_build_close_row_for_fill failed for %s",
                fill.get("symbol", "?"),
            )
            # HIGH-026 (Task 95): surface the failure as a structured engine event
            # so it appears in the event-log UI and survives log rotation. Both
            # callers (line 599 ensure_future, line 782 await-without-check) are
            # fire-and-forget, so re-raising buys nothing — the event log is the
            # only way operators learn about silently-failed close-row builds.
            # Inner try/except keeps event emission failure from masking the
            # original exception that already logged above.
            try:
                from core.event_log import log_event
                log_event(
                    account_id,
                    "close_row_build_failed",
                    {
                        "symbol": fill.get("symbol", ""),
                        "direction": fill.get("direction", ""),
                        "terminal_position_id": fill.get("terminal_position_id", ""),
                        "exchange_fill_id": fill.get("exchange_fill_id", ""),
                        "exchange_order_id": fill.get("exchange_order_id", ""),
                        "error_type": type(e).__name__,
                        "error_msg": str(e)[:500],
                    },
                    source="order_manager",
                )
            except Exception:
                log.debug("close_row_build_failed event emission failed", exc_info=True)

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

    async def _compute_close_deltas(
        self,
        account_id: int,
        pos_id: str,
        entry_price: float,
        actual_size: float,
        exit_price: float,
        entry_time: int,
        exit_time: int,
    ) -> Dict[str, Any]:
        """T2.5 (plan §2 task 2.5): close-time deltas vs the position's
        MOST-CONTRIBUTING calc (spec §3.2 delta-basis rule).

        Basis: ``_position_primary_calc`` (largest ``contributed_qty``;
        tie-break earliest ``first_fill_ts``) — the single source of truth
        for the §3.2 rule, shared with T2.2/T2.3. Planned size/TP/SL come
        from that calc's junction row (the T2.4 contribution-time
        snapshot); planned entry + planned_r come from its
        ``pre_trade_log`` row (no junction column exists for those).

        Computes the 6 deltas fully derivable from data available at
        close, all stored RAW/signed per the literal §3.2 formulas
        (``realized_r`` is direction-agnostic as written — a SHORT flips
        both numerator and denominator; the ``*_delta_pct`` are price
        deltas whose better/worse reading is a display concern):
          entry_px_delta_pct, size_delta_pct, exit_vs_target_pct,
          realized_r, planned_r, hold_time_actual_ms.

        Every key is omitted (→ stays NULL via the nullable column) when
        its planned denominator is missing/zero. Best-effort: any read
        failure or absent junction (UNPLANNED / binance empty-tpid)
        returns ``{}`` so the close-row write never blocks.

        Deliberately NOT computed here (left NULL until their owning task):
          - ``tp_drift_pct`` / ``sl_drift_pct`` → Phase 4.6 (need the final
            AMENDED TP/SL, which requires amendment tracking; the close
            order exposes only the single triggered level).
          - ``cumulative_amendment_count`` → Phase 4.3 (``order_amendments``
            is unwired today; a literal ``0`` would mean "zero amendments"
            rather than the truth "tracking not yet wired").
          - ``hold_time_planned_ms`` → no planned-duration column exists in
            ``pre_trade_log`` or the junction.
        """
        if not pos_id:
            return {}
        try:
            primary_calc_id, _lifecycle = await self._position_primary_calc(
                account_id, pos_id,
            )
            if not primary_calc_id:
                return {}  # no junction → UNPLANNED; nothing to compute against

            # Planned size/TP/SL from the primary calc's junction row (T2.4 snapshot).
            async with self._db._conn.execute(
                "SELECT planned_size, planned_tp, planned_sl "
                "FROM positions_calcs "
                "WHERE position_id = ? AND calc_id = ? AND account_id = ? "
                "ORDER BY id ASC LIMIT 1",
                (pos_id, primary_calc_id, account_id),
            ) as cur:
                jrow = await cur.fetchone()
            planned_size = jrow[0] if jrow else None
            planned_tp = jrow[1] if jrow else None
            planned_sl = jrow[2] if jrow else None

            # Planned entry + planned_r from the primary calc's pre_trade_log
            # row. planned_entry uses effective_entry (fallback average) — the
            # same basis the legacy _compute_shortfall uses for "intended entry".
            async with self._db._conn.execute(
                "SELECT effective_entry, average, est_r FROM pre_trade_log "
                "WHERE calc_id = ? AND account_id = ? ORDER BY id ASC LIMIT 1",
                (primary_calc_id, account_id),
            ) as cur:
                prow = await cur.fetchone()
            planned_entry = _first_truthy(prow[0], prow[1]) if prow else None
            planned_r = (prow[2] or None) if prow else None

            out: Dict[str, Any] = {}

            # entry_px_delta_pct = (actual_entry - planned_entry)/planned_entry*100
            if planned_entry and entry_price:
                out["entry_px_delta_pct"] = round(
                    (entry_price - planned_entry) / planned_entry * 100, 4)

            # size_delta_pct = (actual_size - planned_size)/planned_size*100.
            # Guard actual_size too: the close-row builder passes
            # total_open_qty=0 when opening fills can't be VWAP-resolved
            # (degraded/orphan DB) — without this guard size_delta_pct would
            # persist a spurious -100% instead of NULL, breaking the
            # "omit when inputs aren't real" contract the sibling deltas honor.
            if planned_size and actual_size:
                out["size_delta_pct"] = round(
                    (actual_size - planned_size) / planned_size * 100, 4)

            # exit_vs_target_pct = (actual_exit - relevant_planned_level)/level*100.
            # relevant level = whichever of planned_tp/planned_sl is CLOSER to
            # the actual exit (the _compute_shortfall closest-to-exit precedent).
            if exit_price:
                if planned_tp and planned_sl:
                    level = (planned_tp
                             if abs(exit_price - planned_tp) < abs(exit_price - planned_sl)
                             else planned_sl)
                else:
                    level = planned_tp or planned_sl
                if level:
                    out["exit_vs_target_pct"] = round(
                        (exit_price - level) / level * 100, 4)

            # realized_r = (exit - entry) / (planned_entry - planned_sl).
            # Price-distance denominator per spec §3.2 (NOT a USDT risk amount).
            if (planned_entry and planned_sl and planned_entry != planned_sl
                    and exit_price and entry_price):
                out["realized_r"] = round(
                    (exit_price - entry_price) / (planned_entry - planned_sl), 4)

            # planned_r = the calc's R estimate (pre_trade_log.est_r).
            if planned_r:
                out["planned_r"] = planned_r

            if entry_time:
                out["hold_time_actual_ms"] = exit_time - entry_time

            return out
        except Exception:
            # Best-effort: ANY failure (read OR arithmetic) yields no deltas —
            # the close-row write must never be blocked by this enrichment.
            log.debug("close-deltas failed for %s", pos_id, exc_info=True)
            return {}
