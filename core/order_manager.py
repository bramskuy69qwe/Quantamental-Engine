"""
OrderManager — domain logic for order lifecycle.

Decoupled from WebSocket transport. ws_manager parses WS messages and
delegates here; schedulers call for REST fallback; both produce identical
dict inputs.

Instantiated once as the process-wide singleton in
core.order_manager_singleton (v2.6 Phase 1); every consumer reads that
shared instance.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from core import correlation_log
from core.auth_state import cached_operator_id
from core.event_bus import event_bus, DOMAIN_CALC, DOMAIN_POSITION, DOMAIN_ORDER
from core.order_state import validate_transition, ACTIVE_STATES, OrderStatus, resolve_tpsl_direction
# Reconciler R1 (docs/design/attribution_reconciler_plan.md): the identity
# sites moved to core.position_identity; the OrderManager methods below are
# thin delegates so the caller/test surface is unchanged. The shared
# selection-rule helpers moved with them and are re-imported here for the
# remaining in-file consumers (_enrich_positions_calc_id, close-row
# planned_entry).
from core.position_identity import (
    PositionIdentity,
    _first_truthy,
    _most_contributing_calc_id,
)
from core.state import app_state, PositionInfo, deviation_badge_level

log = logging.getLogger("order_manager")

# P6.T5 (spec §9 order:duplicate_detected): two orders with an IDENTICAL shape
# arriving within this window are treated as a likely accidental double-submit.
# 2s mirrors the bracket-detection window (T2.8); tight enough to separate an
# accidental double-paste from a deliberate scale-in (seconds-to-minutes apart).
# Heuristic + a module constant for now (config-driven window is a later refinement).
DUP_WINDOW_MS = 2000


# _first_truthy + _most_contributing_calc_id moved to core.position_identity
# (reconciler R1) — re-imported above for the in-file consumers.


class OrderManager:
    """Domain logic for order lifecycle. No WS/HTTP knowledge."""

    def __init__(self, db) -> None:
        self._db = db
        # Reconciler R1: the fill→position→calc identity owner. The
        # OrderManager identity methods below delegate here; v2.6 extracts
        # them together.
        self._identity = PositionIdentity(db)
        self._open_orders: List[Dict] = []   # cached for dashboard reads
        # 2026-06-15: STICKY per-tpid "this linked position's TP/SL was amended
        # or removed during its life". Set the moment drift_check first sees it
        # — the live pos.tpsl_amended is ephemeral (it resets at close when the
        # protective legs expire, and the position leaves app_state before the
        # deferred close-row build runs). Read by _build_close_row_for_fill and
        # persisted onto the closed_positions row so Position History shows
        # "amended" (matching the live badge). Pruned on the final close row.
        # Value is a SEVERITY level (2026-06-20): 1 = amended/moved or TP
        # removed (yellow), 2 = SL removed → unprotected/"fatal" (red). The
        # MAX level seen during life sticks.
        self._tpsl_amended_seen: Dict[str, int] = {}

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
            # LB-F3: the bulk UPDATE bypasses the WS per-order release —
            # sweep the stranded 'matched' calcs back to 'released'.
            await self.release_calcs_for_stale_cancels(account_id)

        # 4b. T2.9 (spec §4.5): bracket calc_id inheritance for the REST
        # reconciliation path (WS-drop fallback / catch-up). Per distinct
        # symbol in the batch; idempotent + best-effort.
        await self._propagate_bracket_calc_id_for_orders(account_id, orders)

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
            # LB-F3: same sweep as the basic path (algo legs are usually
            # reduce-only TP/SL → the sweep's gates make this a no-op,
            # but an algo ENTRY cancel is released like any other).
            await self.release_calcs_for_stale_cancels(account_id)

        # 2b. T2.9 (spec §4.5): bracket calc_id inheritance. Binance TP/SL
        # conditional orders arrive on THIS algo path while the entry came
        # via the basic-order path — both already persisted, so detection
        # reads them together regardless of which handler ingested each leg.
        await self._propagate_bracket_calc_id_for_orders(account_id, orders)

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

        NOTE (debug session 2026-06-07): this gate only validates orders
        present in get_active_orders_map (status new/partially_filled). A
        TERMINAL order (filled/canceled/expired/rejected) is NOT in that
        map, so a late/duplicate WS event that would downgrade it (e.g.
        filled→new) bypasses this gate entirely. Terminal-downgrade
        protection is therefore enforced at the DB layer — the
        upsert_order_batch ON CONFLICT WHERE guard (db_orders.py) — which
        is the single chokepoint covering this path AND the REST-snapshot /
        algo-batch paths that call upsert_order_batch directly.
        """
        order.setdefault("account_id", account_id)
        # P9.T3: stamp the operator on duty (active seat) onto this WS order
        # arrival for weak audit attribution ("operator on duty at
        # observation time"). O(1) cache read (no DB on the hot path); None
        # when no seat has registered since boot — acceptable (best-effort).
        # setdefault: never clobber an operator_id an upstream caller set.
        # upsert_order_batch's ON CONFLICT COALESCE preserves the first-known
        # value across later observations of the same order.
        order.setdefault("operator_id", cached_operator_id(account_id))
        eid = order.get("exchange_order_id")

        prev_order = None
        prev_status = ""
        if eid:
            existing = await self._db.get_active_orders_map(account_id)
            if eid in existing:
                prev_order = existing[eid]
                prev_status = prev_order.get("status", "")
                new_status = order.get("status", "new")
                if not validate_transition(prev_status, new_status):
                    log.warning(
                        "SR-1: rejected invalid transition %s→%s for order %s (WS update)",
                        prev_status, new_status, eid,
                    )
                    return False

        await self._db.upsert_order_batch([order])
        # corr-tap: order_status_applied (CL.T3a, spec §5.5) — the WS source.
        # ``before`` is "" when the order is not in the active map (first
        # arrival, or a terminal order outside the SR-1 gate — the DB-layer
        # ON CONFLICT guard owns terminal-downgrade protection; the paired
        # db_write line carries the authoritative rowcount). dedup_key uses
        # the NORMALIZED status/qty (duplicate-apply detection within this
        # category; the raw frame's key lives on the same corr chain).
        _status_after = order.get("status", "new")
        _osa = {
            "order_id": str(eid) if eid is not None else "",
            "before":   prev_status,
            "after":    _status_after,
            "source":   "ws",
        }
        if eid is not None:
            _osa["dedup_key"] = f"{eid}:{_status_after}:{order.get('quantity')}"
        correlation_log.emit(
            "order_manager", "internal", "internal",
            correlation_log.CAT_ORDER_STATUS_APPLIED, _osa,
            account_id=account_id, symbol=order.get("symbol"),
        )
        await self._enrich_order_best_effort(order)
        # When a TP/SL child arrives, re-enrich the parent entry so its
        # tp/sl_trigger_price gets populated and correlation can run.
        # Without this, market orders that fill before children arrive
        # never get correlated (the parent has no further updates).
        await self._re_enrich_parent_on_child_arrival(account_id, order)
        # T2.9 (spec §4.5): propagate a matched entry's calc_id onto its
        # bracket TP/SL siblings. Runs AFTER enrichment so the entry's
        # calc_id is committed when this reads it; idempotent + best-effort.
        await self._propagate_bracket_calc_id(account_id, order.get("symbol") or "")
        # P6.T5 (spec §9 order:duplicate_detected): flag 2+ identical-shape orders
        # arriving within DUP_WINDOW_MS (a likely accidental double-submit). New
        # arrivals only (prev_order is None) — an update/fill of an existing order
        # is not a new submission.
        await self._detect_duplicate_orders(account_id, order, prev_order)
        self._emit_order_events(account_id, order)
        # TP/SL price modifications flow through the P4.T1 amendment path
        # (ws_manager._apply_order_update → detect_and_persist_amendment, PRE the
        # SR-1 gate) which emits position_amended (field=tp_price/sl_price). The
        # legacy post-gate _detect_modification_events was dead (the SR-1 gate
        # rejects the new→new self-transition an amendment arrives as before this
        # line runs) and was removed; tp_modified/sl_modified survive only as
        # historical event types (read-side rendering kept).
        # T216 (P1.T5): release the calc back to the re-match pool when
        # the operator cancels a working (unfilled) entry order.
        await self._release_calc_on_operator_cancel(account_id, order)
        self._publish_order_update(account_id, order)
        await self.refresh_cache(account_id)
        return True

    async def _detect_duplicate_orders(
        self, account_id: int, order: Dict[str, Any], prev_order: Optional[Dict],
    ) -> None:
        """P6.T5 (spec §9 ``order:duplicate_detected``): emit when 2+ orders with
        an IDENTICAL shape arrived within :data:`DUP_WINDOW_MS` — a likely
        accidental double-submit (the operator pasted the same order twice).

        Identity = ``(symbol, side, order_type, price, stop_price, quantity)``,
        EXACT — a double-paste produces bit-identical values, so exact match is
        the lowest-false-positive interpretation of "near-identical". ``stop_price``
        is in the key so multi-TP rungs at DIFFERENT triggers are not flagged.

        Runs on NEW arrivals only (``prev_order is None`` — an update/fill of an
        existing order is not a new submission) and requires ``created_at_ms > 0``
        (no reliable arrival time → can't window; e.g. the MEXC-WS gap where
        ``created_at_ms`` is 0, same limitation as bracket detection). The just-
        persisted order is already in the table, so the query returns the whole
        cluster (this order + any prior dups); ≥2 ⇒ emit ``order_ids[]`` (internal
        ids) + ``dup_window_ms``. Best-effort: a detection fault never breaks the
        order-arrival path.

        **Known false-positive edges** (bounded; no consumer yet — forward-
        scaffolding, surfaced for operator judgment when the UI badge / Phase-7
        consumer lands): a deliberate scale-in at the EXACT same price+qty within
        2s; a cancel-then-repaste (cancel-replace) of the same shape within 2s
        (status is intentionally NOT filtered — the tight window is the discriminator).
        """
        if prev_order is not None:
            return
        try:
            created = int(order.get("created_at_ms", 0) or 0)
            if created <= 0:
                return
            symbol = order.get("symbol", "") or ""
            if not symbol:
                return
            side = order.get("side", "") or ""
            otype = order.get("order_type", "") or ""
            price = float(order.get("price", 0) or 0)
            stop_price = float(order.get("stop_price", 0) or 0)
            qty = float(order.get("quantity", 0) or 0)
            async with self._db._conn.execute(
                "SELECT id FROM orders "
                "WHERE account_id = ? AND symbol = ? AND side = ? AND order_type = ? "
                "  AND price = ? AND stop_price = ? AND quantity = ? "
                "  AND created_at_ms > 0 AND ABS(created_at_ms - ?) <= ? "
                "ORDER BY id ASC",
                (account_id, symbol, side, otype, price, stop_price, qty,
                 created, DUP_WINDOW_MS),
            ) as cur:
                ids = [r[0] for r in await cur.fetchall()]
            if len(ids) >= 2:
                await event_bus.publish_engine(
                    account_id, DOMAIN_ORDER, "duplicate_detected", {
                        "order_ids":     ids,
                        "dup_window_ms": DUP_WINDOW_MS,
                    },
                )
        except Exception:
            log.debug("duplicate-order detection failed", exc_info=True)

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
                # Domain filter, deliberately NO envelope: this method runs
                # on EVERY order update; only TP/SL-child arrivals are in
                # attr_reenrich_trigger's decision domain (spec §5.6 — the
                # child→parent decision, historical bug #g).
                return
            pos_id = order.get("exchange_position_id", "")

            import sqlite3, config
            conn = sqlite3.connect(config.DB_PATH)
            conn.row_factory = sqlite3.Row
            if pos_id:
                parent = conn.execute(
                    "SELECT * FROM orders WHERE account_id = ? "
                    "AND exchange_position_id = ? AND reduce_only = 0 LIMIT 1",
                    (account_id, pos_id),
                ).fetchone()
            else:
                # Defect-6 (debug 2026-06-08): the observe-only path (Binance
                # direct) carries no venue exchange_position_id, so the lookup
                # above can't find the parent. The OLD `if not pos_id: return`
                # meant an observe-path TP/SL child NEVER re-enriched its entry —
                # so the entry's tp/sl_trigger_price (and thus the calc matcher)
                # never ran once the children arrived AFTER the entry's own
                # enrichment (the common case: market entry fills, then the TP/SL
                # bracket lands). Resolve the parent by (symbol, position_side):
                # the most-recent entry (non-reduce_only) order for this position.
                sym = order.get("symbol", "")
                pside = str(order.get("position_side") or "")
                parent = conn.execute(
                    "SELECT * FROM orders WHERE account_id = ? AND symbol = ? "
                    "AND position_side = ? AND reduce_only = 0 "
                    "ORDER BY id DESC LIMIT 1",
                    (account_id, sym, pside),
                ).fetchone()
            conn.close()

            # corr-tap: attr_reenrich_trigger (CL.T3b-entry, spec §5.6) —
            # the child-arrival → parent-re-enrich decision (historical
            # bug #g: this inference silently not firing left market
            # entries permanently uncorrelated).
            child_eid = str(order.get("exchange_order_id") or "")
            _rt: Dict[str, Any] = {
                "outcome": "TRIGGERED" if parent else "SKIPPED",
                "via": "child_arrival",
                "child_exchange_order_id": child_eid,
                "parent_lookup": ("exchange_position_id" if pos_id
                                  else "symbol_position_side"),
                "parent_found": bool(parent),
                "parent_exchange_order_id":
                    str(parent["exchange_order_id"] or "") if parent else "",
                "calc_id": (parent["calc_id"] or "") if parent else "",
                "terminal_position_id":
                    (parent["terminal_position_id"] or "") if parent else "",
                "lifecycle_id": "",
            }
            if not parent:
                _rt["reason"] = "no_parent_found"
            if child_eid:
                _rt["dedup_key"] = (
                    f"{child_eid}:{order.get('status') or ''}"
                    f":{order.get('quantity') or ''}"
                )
            correlation_log.emit(
                "order_manager", "internal", "internal",
                correlation_log.CAT_ATTR_REENRICH_TRIGGER, _rt,
                account_id=account_id, symbol=order.get("symbol") or None,
            )

            if parent:
                # Route through _enrich_order_best_effort so defect-8's
                # junction-ensure also fires for a parent that links here.
                await self._enrich_order_best_effort(dict(parent))
        except Exception as e:
            log.debug("parent re-enrichment on child arrival skipped", exc_info=True)
            # corr-tap: attr_reenrich_trigger — failure twin
            correlation_log.emit(
                "order_manager", "internal", "internal",
                correlation_log.CAT_ATTR_REENRICH_TRIGGER,
                {"outcome": "ERROR", "via": "child_arrival",
                 "error_type": type(e).__name__,
                 "child_exchange_order_id":
                     str(order.get("exchange_order_id") or ""),
                 "calc_id": "", "terminal_position_id": "",
                 "lifecycle_id": ""},
                account_id=account_id, symbol=order.get("symbol") or None,
            )

    async def _enrich_order_best_effort(self, order: Dict[str, Any]) -> None:
        try:
            import config
            from core.order_enrichment import enrich_order
            await enrich_order(order, config.DB_PATH)
            # Defect-8 (debug 2026-06-08): if the matcher just linked this order
            # (observe-path calc_id is set AFTER the opening fill), ensure its
            # positions_calcs junction exists — the fill-time creation was skipped
            # because calc_id was NULL then, and nothing else re-creates it.
            await self._ensure_junction_if_linked(
                order.get("account_id", 1), order.get("exchange_order_id"),
            )
        except Exception:
            log.debug("order enrichment skipped", exc_info=True)

    # HA-28 (CL.T5): the bracket-inherit SKIP lines are the largest
    # nothing-to-do generators on THIS class — they fire per symbol on
    # EVERY snapshot pass for a steady linked position. On-change dedup
    # them (the §7.3 mandate, same exception the enrich/drift taps use):
    # emit on first occurrence + on transition, suppress steady repeats.
    # Only no-op SKIPPED outcomes route through here — actionable
    # outcomes (INHERITED) and ERROR twins stay ungated (repetition
    # there IS the signal). Bounded LRU so a long-running engine can't
    # leak the memo; an eviction at worst re-emits one harmless no-op
    # line later. Reconciler R1: the replay tap's `junction_exists` SKIP
    # dedup moved WITH the replay to PositionIdentity (its own memo —
    # the plan §4-R1 memo split); this copy now serves the
    # bracket-inheritance tap only.
    _ATTR_SKIP_MEMO_MAX = 512

    def _attr_skip_is_repeat(self, key: Any, sig: Any) -> bool:
        """True → this (key, sig) is an unchanged repeat, suppress the
        emit; False → new or transitioned, emit (and record). Insertion-
        ordered dict as a cheap LRU: re-record moves the key to the back;
        over the cap, the oldest insertion is evicted."""
        memo: Dict[Any, Any] = self.__dict__.setdefault("_attr_skip_memo", {})
        if memo.get(key) == sig:
            return True
        if key in memo:
            del memo[key]  # re-insert at the back (recency)
        memo[key] = sig
        while len(memo) > self._ATTR_SKIP_MEMO_MAX:
            del memo[next(iter(memo))]  # evict oldest
        return False

    async def _ensure_junction_if_linked(self, account_id: int, eoid: str) -> None:
        """Reconciler R1 delegate — the Defect-8 link-after-fill junction
        replay moved verbatim to
        :meth:`core.position_identity.PositionIdentity.ensure_junction_if_linked`.
        The replay reaches the owner's builder, which also owns the
        position:opened/scale_in emissions (R1 events-move decision), so
        both lanes keep their historical event behavior."""
        await self._identity.ensure_junction_if_linked(account_id, eoid)

    # ── TP/SL bracket calc_id inheritance (Phase 2.9, spec §4.5) ─────────────

    # Lookback (ms) for the bracket candidate query, measured back from the
    # symbol's most-recent order timestamp (data-derived, NOT wall-clock —
    # keeps it deterministic / replay-safe AND lets the synthetic small
    # timestamps in tests resolve like real epoch-ms ones). Generous: the
    # time-window detection tier needs only ~2s + clock skew, but the Bybit
    # shared-link tier (orderLinkId) can group legs placed further apart.
    # Purely a query-size bound; the precise "placed together" gate lives in
    # detect_brackets (2s window) or the shared-link key. LIMIT bounds the
    # row count on busy symbols.
    #
    # created_at_ms=0 note (T237 review 1a): a leg with created_at_ms=0 (the
    # MEXC-WS ingest gap — parse_order_update leaves it 0) is excluded by the
    # `>= lo` lower bound whenever the symbol has any real-epoch-ms order
    # (lo >> 0). This does NOT regress detection: detect_brackets cannot
    # time-cluster a 0-ts leg with a real-ts entry anyway (they'd read as
    # ~1.7e12 ms apart → split), so mixed-source MEXC brackets are the
    # already-documented MEXC-WS limitation, not introduced here. Pure-MEXC
    # (all legs 0) still works: ref_ts=0 → lo=0 → 0>=0 includes them.
    _BRACKET_LOOKBACK_MS = 300_000
    _BRACKET_CANDIDATE_LIMIT = 200

    def _detect_brackets(self, candidates: List[Dict[str, Any]]):
        """Resolve the active adapter's ``detect_bracket``; fall back to the
        venue-agnostic engine with no shared-link key (the Binance/MEXC
        shape). The fallback means propagation still works in tests + on the
        canonical (Binance) live venue; the only thing lost without the real
        adapter is Bybit's ``orderLinkId`` tier-1 grouping (Beta).

        Two distinct fallback causes, kept separate (T237 review 6a) so a
        REAL adapter fault doesn't masquerade as a silent grouping downgrade:
          - no resolvable adapter (no active account / uninitialised — the
            expected unit-test path) → silent fallback;
          - ``detect_bracket`` itself raised (a genuine adapter regression)
            → log.warning so a Bybit orderLinkId-grouping break is visible,
            THEN degrade to window-only rather than dropping detection.
        """
        from core.bracket_detection import detect_brackets
        try:
            from core.exchange import _get_adapter
            adapter = _get_adapter()
        except Exception:
            return detect_brackets(candidates, link_field=None)
        try:
            return adapter.detect_bracket(candidates)
        except Exception:
            log.warning(
                "adapter.detect_bracket failed; degrading to window-only "
                "detection (venue shared-link grouping lost)", exc_info=True,
            )
            return detect_brackets(candidates, link_field=None)

    async def _propagate_bracket_calc_id(
        self, account_id: int, symbol: str,
    ) -> None:
        """T2.9 (plan §2 task 2.9, spec §4.5): when an entry + its TP/SL are
        placed together as a bracket, propagate the entry's ``calc_id`` onto
        the protective (TP/SL) legs that don't already carry one.

        Consumes the T2.8 detection primitive (:meth:`_detect_brackets` →
        ``adapter.detect_bracket``). For each detected bracket whose ENTRY
        leg carries a ``calc_id`` (i.e. the matcher already linked it — spec
        §4.1), stamp that ``calc_id`` + ``link_status='LINKED'`` onto every
        protective leg in the bracket whose ``calc_id`` is still NULL.

        Why this is the ONLY way a TP/SL order ROW gets a ``calc_id``: the
        strict matcher (``order_enrichment._try_correlate``) returns early
        for reduce-only / close-type orders, so protective legs never pass
        through it. The matcher links the ENTRY; this inherits that link
        down to the siblings the operator placed with it (spec §4.5).

        Bounded by design (the T2.8 "best-effort heuristic"): only an entry
        that ALREADY carries a ``calc_id`` propagates, so a mis-grouped
        time-window cluster cannot fabricate a link — worst case a TP/SL
        sharing the window with an UNPLANNED entry stays NULL and routes
        through the standard matcher (spec §4.5).

        Runs on every order arrival for ``symbol`` (idempotent via
        ``WHERE calc_id IS NULL``); cheap pre-checks short-circuit when
        there is nothing to inherit. Best-effort — failures log + return,
        never break the ingest hot path. All I/O via ``self._db._conn``.

        Scope deviation (calc_id + link_status, NOT lifecycle_id): spec
        §4.5's deliverable is calc_id inheritance. The entry's
        ``lifecycle_id`` is minted at its first opening FILL (T2.1), which
        commonly has NOT happened when the protective leg arrives (TP/SL
        placed with, but filling after, the entry) — a COALESCE here would
        write NULL in the common case and the calc_id-IS-NULL idempotency
        guard would never revisit it (a half-correct partial). Protective-
        order ``lifecycle_id`` stamping stays a known gap, same as T2.1
        which stamps only the entry order; revisit if the Phase-7 lifecycle
        join needs protective-order rows.

        link_status NOTE (P3.T1 done): the ``orders.link_status`` write
        routes through ``core.link_state.auto_classify`` (spec §3.6) — the
        engine-classification sibling of ``transition()``, matching the
        matcher's link write in ``order_enrichment._try_correlate``. This
        NULL→LINKED set is an auto-classification, not an operator
        transition: the protective leg has no prior DECIDED link_status
        (the matcher early-returns for reduce-only/close types), so it is
        deliberately NOT routed through ``transition()`` (which validates
        between existing enum values and would reject a NULL/UNPLANNED
        source). Maintains the invariant "calc_id present ⟺
        link_status=LINKED" (plan §1 acceptance).
        """
        # corr-tap: attr_bracket_inherit (CL.T3b-entry, spec §5.6 mandate
        # 1) — one envelope per invocation: per-leg INHERITED lines when
        # something propagates, else one SKIPPED line with the reason.
        # This runs per order arrival per symbol, so the SKIPPED lines
        # are lifecycle-rate (same order of volume as the ws
        # order_status_applied tap).
        def _tap_bracket_skip(reason: str) -> None:
            # HA-28: on-change dedup the steady per-symbol-per-pass SKIPs
            # (a symbol with no bracket to inherit re-skips every snapshot
            # pass). Emits on first + on reason transition; INHERITED and
            # the ERROR twin below are separate emits and stay ungated.
            if self._attr_skip_is_repeat(("bracket", account_id, symbol or ""),
                                         reason):
                return
            correlation_log.emit(
                "order_manager", "internal", "internal",
                correlation_log.CAT_ATTR_BRACKET_INHERIT,
                {"outcome": "SKIPPED", "reason": reason, "calc_id": "",
                 "exchange_order_id": "", "terminal_position_id": "",
                 "lifecycle_id": ""},
                account_id=account_id, symbol=symbol or None,
            )

        if not symbol:
            _tap_bracket_skip("no_symbol")
            return
        try:
            from core.bracket_detection import is_entry_leg, is_protective_leg

            # ref_ts from the symbol's newest order → data-derived lookback
            # (see _BRACKET_LOOKBACK_MS). In tests MAX is a small synthetic
            # value so lo clamps to 0 (all rows); in prod lo ≈ now − 5min.
            async with self._db._conn.execute(
                "SELECT MAX(created_at_ms) FROM orders "
                "WHERE account_id = ? AND symbol = ?",
                (account_id, symbol),
            ) as cur:
                mrow = await cur.fetchone()
            ref_ts = int((mrow[0] if mrow else 0) or 0)
            lo = max(0, ref_ts - self._BRACKET_LOOKBACK_MS)

            cols = ("id", "exchange_order_id", "symbol", "position_side",
                    "order_type", "reduce_only", "client_order_id",
                    "created_at_ms", "calc_id")
            async with self._db._conn.execute(
                f"SELECT {', '.join(cols)} FROM orders "
                "WHERE account_id = ? AND symbol = ? AND created_at_ms >= ? "
                "ORDER BY created_at_ms DESC LIMIT ?",
                (account_id, symbol, lo, self._BRACKET_CANDIDATE_LIMIT),
            ) as cur:
                rows = await cur.fetchall()
            candidates = [dict(zip(cols, r)) for r in rows]
            if not candidates:
                _tap_bracket_skip("no_recent_orders")
                return

            # Cheap pre-checks: need ≥1 entry-with-calc_id AND ≥1
            # protective-without-calc_id, else there is nothing to inherit.
            if not any(is_entry_leg(o) and o.get("calc_id") for o in candidates):
                _tap_bracket_skip("no_linked_entry")
                return
            if not any(is_protective_leg(o) and not o.get("calc_id")
                       for o in candidates):
                _tap_bracket_skip("no_uninherited_protective")
                return

            updates: List[Tuple[str, int, str, int, str]] = []
            for grp in self._detect_brackets(candidates):
                # detect_brackets sorts each group by created_at_ms ASC, so
                # next() = the EARLIEST calc-bearing entry in the cluster.
                # T237 review 2: this is placement-time, ORDER-level
                # attribution — "this protective order was placed in a
                # bracket under calc X" — which is intentionally DISTINCT
                # from the close-time, POSITION-level most-contributing
                # primary (spec §3.2) that T2.2/T2.3/T2.5/T2.6 use. The
                # primary needs fill quantities and a junction, neither of
                # which exists when a bracket's protective leg arrives (often
                # pre-fill), so it is uncomputable here. The two only diverge
                # in the rare case of two entries with DIFFERENT calcs sharing
                # one protective leg within the 2s window (a scale-in placed
                # near-simultaneously); there the earliest-entry pick is a
                # deterministic best-effort and does NOT corrupt position
                # attribution — the closing fill + closed_positions row
                # re-derive from the junction primary (T2.2/T2.6), and no
                # live consumer reads a protective leg's orders.calc_id.
                entry = next(
                    (o for o in grp if is_entry_leg(o) and o.get("calc_id")),
                    None,
                )
                if not entry:
                    continue
                src_calc = entry["calc_id"]
                for leg in grp:
                    if leg.get("calc_id") or not is_protective_leg(leg):
                        continue
                    updates.append((
                        src_calc, leg["id"],
                        str(leg.get("exchange_order_id") or ""),
                        entry["id"],
                        str(entry.get("exchange_order_id") or ""),
                    ))

            if not updates:
                _tap_bracket_skip("no_bracket_grouped")
                return

            # P3.T1: route the link_status write through the link_state
            # auto-classification choke-point (spec §3.6). The protective
            # leg's link_status is NULL here (the matcher early-returns
            # for reduce-only/close types, so it never set one), making
            # this an engine auto-classification, not an operator
            # transition(). apply_fn does the UPDATE (calc_id +
            # link_status, guarded by WHERE calc_id IS NULL for
            # idempotency); the single commit stays AFTER the loop to
            # preserve the batch write. The link event map is empty
            # pre-Phase-6, so the commit-after-event ordering is moot
            # today (revisit when Phase 6 wires link-status events).
            from core.link_state import LinkStatus, auto_classify

            for src_calc, oid, leg_eid, entry_id, entry_eid in updates:
                _applied = {"n": 0}

                async def _apply_leg(src_calc=src_calc, oid=oid,
                                     _applied=_applied) -> None:
                    cur = await self._db._conn.execute(
                        "UPDATE orders SET calc_id = ?, link_status = ? "
                        "WHERE id = ? AND calc_id IS NULL",
                        (src_calc, LinkStatus.LINKED.value, oid),
                    )
                    _applied["n"] = cur.rowcount or 0
                    # P4.T5 audit (SCOPING-001): a protective leg amended BEFORE
                    # this inheritance ran was recorded (P4.T1) with the leg's
                    # then-NULL calc_id. The close-time drift + P4.T2/P4.T3
                    # counts are all scoped by calc_id, so an orphaned
                    # NULL-calc_id amendment would be silently missed — backfill
                    # it to the inherited calc_id (shared helper, same
                    # propagate-on-link discipline as fills.calc_id). Guarded on
                    # rowcount>0 (HOT-TXN-001): only when THIS call actually
                    # linked the leg — on a re-run the leg already carries its
                    # calc_id (so new amendments aren't orphaned) and the orders
                    # UPDATE no-ops, making the backfill a redundant no-op anyway.
                    if cur.rowcount > 0:
                        await self._db.backfill_amendment_calc_id(oid, src_calc)
                await auto_classify(
                    oid, LinkStatus.LINKED.value, apply_fn=_apply_leg,
                )
                # corr-tap: attr_bracket_inherit (CL.T3b-entry, spec §5.6)
                # — one line per stamped leg. ``applied=False`` = the
                # WHERE calc_id IS NULL idempotency guard no-oped (the
                # leg raced/linked since detection) — visible, not
                # silently merged.
                _bi: Dict[str, Any] = {
                    "outcome": "INHERITED",
                    "applied": _applied["n"] > 0,
                    "calc_id": src_calc,
                    "parent_order_id": entry_id,
                    "parent_exchange_order_id": entry_eid,
                    "child_order_id": oid,
                    "child_exchange_order_id": leg_eid,
                    "terminal_position_id": "",
                    "lifecycle_id": "",
                }
                if leg_eid:
                    _bi["dedup_key"] = f"{leg_eid}:inherit:{src_calc}"
                correlation_log.emit(
                    "order_manager", "internal", "internal",
                    correlation_log.CAT_ATTR_BRACKET_INHERIT, _bi,
                    account_id=account_id, symbol=symbol,
                )
            await self._db._conn.commit()
            log.info(
                "T2.9 bracket inheritance: stamped calc_id on %d TP/SL leg(s) "
                "for %s", len(updates), symbol,
            )
        except Exception as e:
            log.debug(
                "bracket calc_id propagation skipped for %s", symbol,
                exc_info=True,
            )
            # corr-tap: attr_bracket_inherit — failure twin (mandate 1:
            # the exception path is a line, not an absence)
            correlation_log.emit(
                "order_manager", "internal", "internal",
                correlation_log.CAT_ATTR_BRACKET_INHERIT,
                {"outcome": "ERROR", "error_type": type(e).__name__,
                 "calc_id": "", "exchange_order_id": "",
                 "terminal_position_id": "", "lifecycle_id": ""},
                account_id=account_id, symbol=symbol or None,
            )

    async def _propagate_bracket_calc_id_for_orders(
        self, account_id: int, orders: List[Dict[str, Any]],
    ) -> None:
        """Run :meth:`_propagate_bracket_calc_id` once per distinct symbol in
        a snapshot batch (REST reconciliation paths). Best-effort; the
        per-symbol helper short-circuits cheaply when there is nothing to
        inherit."""
        seen: set = set()
        for o in orders:
            sym = o.get("symbol") or ""
            if sym and sym not in seen:
                seen.add(sym)
                await self._propagate_bracket_calc_id(account_id, sym)

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
            # corr-tap: attr_reenrich_trigger (CL.T3b-entry, spec §5.6)
            correlation_log.emit(
                "order_manager", "internal", "internal",
                correlation_log.CAT_ATTR_REENRICH_TRIGGER,
                {"outcome": "SKIPPED", "via": "fill_arrival",
                 "reason": "no_exchange_order_id",
                 "parent_exchange_order_id": "", "parent_found": False,
                 "calc_id": "", "terminal_position_id": "",
                 "lifecycle_id": ""},
                account_id=account_id,
            )
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
            # corr-tap: attr_reenrich_trigger — the fill-arrival variant
            # of the child_arrival decision (the MARKET-order re-match
            # trigger: first run with avg_fill_price populated). Same
            # decision class as bug #g's site; via= distinguishes.
            _rt: Dict[str, Any] = {
                "outcome": "TRIGGERED" if row else "SKIPPED",
                "via": "fill_arrival",
                "parent_exchange_order_id": exchange_order_id,
                "parent_found": bool(row),
                "calc_id": (row["calc_id"] or "") if row else "",
                "terminal_position_id":
                    (row["terminal_position_id"] or "") if row else "",
                "lifecycle_id": (row["lifecycle_id"] or "") if row else "",
                "dedup_key": f"{exchange_order_id}:reenrich_fill",
            }
            if not row:
                _rt["reason"] = "parent_not_found_or_reduce_only"
            correlation_log.emit(
                "order_manager", "internal", "internal",
                correlation_log.CAT_ATTR_REENRICH_TRIGGER, _rt,
                account_id=account_id,
                symbol=(row["symbol"] if row else None),
            )
            if row:
                from core.order_enrichment import enrich_order
                await enrich_order(dict(row), config.DB_PATH)
        except Exception as e:
            log.debug(
                "post-fill parent re-enrichment skipped for %s",
                exchange_order_id, exc_info=True,
            )
            # corr-tap: attr_reenrich_trigger — failure twin
            correlation_log.emit(
                "order_manager", "internal", "internal",
                correlation_log.CAT_ATTR_REENRICH_TRIGGER,
                {"outcome": "ERROR", "via": "fill_arrival",
                 "error_type": type(e).__name__,
                 "parent_exchange_order_id": exchange_order_id,
                 "calc_id": "", "terminal_position_id": "",
                 "lifecycle_id": ""},
                account_id=account_id,
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

        NOTE: the bulk cancel paths (``mark_stale_orders`` /
        ``mark_stale_orders_canceled``) don't flow through here per-order;
        their stranded calcs are released by
        ``release_calcs_for_stale_cancels`` below (LB-F3), which routes
        each swept order through THIS method — one release rule.
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
                "SELECT calc_id, filled_qty, id FROM orders "
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
        order_row_id = row[2]  # internal id — matches calc:linked's order_id
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
            # emits no event for this edge. The spec §9 calc:order_cancelled
            # event is emitted SEPARATELY below (P6, no longer deferred) — it
            # is about the ORDER cancel, not the matched→released transition.
            await transition(
                calc_id=calc_id,
                current_status=CalcStatus.MATCHED.value,
                target_status=CalcStatus.RELEASED.value,
                apply_fn=_apply_release,
                account_id=account_id,
            )
            log.info("Released calc %s on operator cancel of order %s", calc_id, eid)
            # P6 (calc:order_cancelled event_bus topic, spec §9): fired only on
            # a SUCCESSFUL release (matched→released won the TOCTOU; a race-lost
            # calc skips to the except below and emits nothing). publish_engine
            # is enqueue-only (never raises). cancel_reason_category mirrors the
            # 'OPERATOR' default written onto the order above; raw = the cancel
            # status string.
            await event_bus.publish_engine(
                account_id, DOMAIN_CALC, "order_cancelled", {
                    "calc_id":                calc_id,
                    "order_id":               order_row_id,
                    "cancel_reason_category": "OPERATOR",
                    "raw":                    order.get("status", ""),
                },
            )
        except CalcTransitionRaceLost as exc:
            log.info("%s", exc)
        except Exception:
            log.warning(
                "calc release on cancel failed for calc_id=%s order=%s",
                calc_id, eid, exc_info=True,
            )

    async def release_calcs_for_stale_cancels(self, account_id: int) -> int:
        """LB-F3 (linkage battery 2026-07-14): release calcs stranded
        'matched' by the BULK cancel paths — ``mark_stale_orders`` (time
        threshold) and ``mark_stale_orders_canceled`` (snapshot
        reconciliation) are raw UPDATEs that never flow through the
        per-order WS release above, so their calcs stayed 'matched'
        forever and replacement orders landed UNPLANNED (candidate filter
        is status IN ('active','released')).

        Scans for canceled, zero-fill, non-reduce-only LINKED orders with
        no cancel_reason stamp (the stamp doubles as the processed marker
        — the WS path writes it, so WS-handled cancels are skipped) whose
        calc is still 'matched', and routes each through
        ``_release_calc_on_operator_cancel`` — ONE release rule (T216
        gates + TOCTOU transition + calc:order_cancelled event), no
        second implementation. Idempotent (the reason stamp + the
        matched-guard make re-runs no-ops) and self-healing: also
        releases calcs stranded by bulk cancels that ran before this
        sweep existed. Returns the number of orders routed.
        """
        try:
            async with self._db._conn.execute(
                "SELECT o.exchange_order_id FROM orders o "
                "JOIN pre_trade_log p ON p.calc_id = o.calc_id "
                "  AND p.account_id = o.account_id "
                "WHERE o.account_id = ? AND o.status = 'canceled' "
                "  AND o.calc_id IS NOT NULL "
                "  AND COALESCE(o.exchange_order_id, '') != '' "
                "  AND COALESCE(o.filled_qty, 0) = 0 "
                "  AND COALESCE(o.reduce_only, 0) = 0 "
                "  AND o.cancel_reason_category IS NULL "
                "  AND p.status = 'matched'",
                (account_id,),
            ) as cur:
                rows = await cur.fetchall()
        except Exception:
            log.warning(
                "stale-cancel calc release: scan failed", exc_info=True)
            return 0
        for (eoid,) in rows:
            await self._release_calc_on_operator_cancel(
                account_id,
                {"status": "canceled", "reduce_only": 0,
                 "exchange_order_id": eoid},
            )
        if rows:
            log.info(
                "Released %d calc(s) stranded by bulk stale-cancel",
                len(rows),
            )
        return len(rows)

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

        T2.11 (RESOLVED): the caller (``_build_close_row_for_fill``) now
        gates this on ``is_final`` (the FINAL close, size→0), so a multi-TP
        ladder completes the calc ONCE at full close rather than prematurely
        on the first partial. For a single-close position is_final is true
        immediately, so it stays exactly-once + correct. (Pre-T2.11 this ran
        on every close-row build and completed on the first partial; the
        status guard made the later partials no-op.)
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
                    account_id=account_id,
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

    # NOTE: the legacy `_detect_modification_events` (tp_modified/sl_modified
    # trade events) was DELETED here. It was called post-gate in
    # process_order_update, but a TP/SL price modification arrives as a new→new
    # self-transition that the SR-1 gate rejects first, so it never fired live.
    # The P4.T1 amendment path below (invoked PRE-gate from ws_manager) detects
    # the same TP/SL changes and emits position_amended (field=tp_price/sl_price)
    # — the single, spec-§9, event_bus-backed modification signal. The
    # tp_modified/sl_modified event TYPES are retained in trade_event_log +
    # rendered by the history table for any historical rows, but have no producer.

    # ── P4.T1: order amendment detection (spec §3.2 / plan §4.1) ─────────────
    #
    # CALLED FROM ws_manager._apply_order_update BEFORE process_order_update.
    # That ordering is load-bearing: the SR-1 transition gate in
    # process_order_update rejects the new→new (and pf→pf) self-transition that
    # an amendment arrives as (validate_transition has no self-edges —
    # order_state.py + test_order_manager.py:121/124, intentional anti-stale-
    # replay), so a post-gate hook would never see amendments. The detection
    # logic lives here (domain layer, has self._db, unit-testable); ws_manager
    # only supplies the pre-gate call site.
    #
    # Scope (deviation-discipline):
    #   - `leverage` (spec §3.2 field) is account/position-level, NOT on a
    #     per-order WS update → not detectable here. Documented gap.
    #   - `trailing_stop` is EXCLUDED: a trailing stop's trigger is moved
    #     AUTOMATICALLY by the venue (callback rate), so its stop_price changes
    #     are not operator amendments (same documented-exclusion class as
    #     leverage). _amendment_field_pairs returns () for it.
    #   - Invoked from BOTH ws_manager._apply_order_update (ORDER_TRADE_UPDATE)
    #     and _apply_algo_update (ALGO_UPDATE). The algo wiring is defensive:
    #     live Binance conditional orders are cancel-replace (a re-price mints a
    #     new `algo:{aid}` → `if not stored: return`), so it is a no-op there
    #     today — but the engine observes Quantower (which may model in-place
    #     algo modifies) and the call cannot mis-record (worst case no-op).
    #   - REST reconciliation (process_order_snapshot/algo BATCH) amendments are
    #     a separate path; covering it needs a dedup key first (order_amendments
    #     is immutable-insert) — deferred follow-up.
    _AMENDMENT_TP_TYPES = frozenset({
        "take_profit", "take_profit_market", "take_profit_limit",
    })
    _AMENDMENT_SL_TYPES = frozenset({
        "stop_loss", "stop_market", "stop_loss_limit",
    })
    # Non-reduce-only stop/TP orders used to OPEN a position carry the FE-13
    # `_entry` suffix (binance/bybit ws adapters). They are ENTRIES (→ spec
    # `entry_price` field), but their amendable trigger lives in `stop_price`,
    # not `price` (price==0 for a stop-market entry) — so they read the
    # stop_price column under the entry_price label. Without this they'd fall to
    # the plain-entry branch, read price==0, and the change guard would silently
    # drop every entry-stop trigger amendment.
    _AMENDMENT_ENTRY_STOP_TYPES = frozenset({
        "stop_loss_entry", "take_profit_entry",
    })
    _AMENDMENT_EXCLUDED_TYPES = frozenset({"trailing_stop"})

    def _amendment_field_pairs(
        self, order_type: Optional[str],
    ) -> Tuple[Tuple[str, str], ...]:
        """(spec §3.2 amendment field, orders column) pairs for this order_type.

        Reduce-only protective legs: take_profit→stop_price→'tp_price';
        stop_loss→stop_price→'sl_price'. Non-reduce-only entry stops (`*_entry`)
        →stop_price→'entry_price' (trigger is in stop_price; price==0 for a
        stop-market entry). Plain entries→price→'entry_price'. Always also
        quantity→'size'. `trailing_stop` is excluded (venue-automatic) → ().
        """
        otype = (order_type or "").lower()
        if otype in self._AMENDMENT_EXCLUDED_TYPES:
            return ()  # venue-automatic trigger — not an operator amendment
        if otype in self._AMENDMENT_TP_TYPES:
            price = ("tp_price", "stop_price")
        elif otype in self._AMENDMENT_SL_TYPES:
            price = ("sl_price", "stop_price")
        elif otype in self._AMENDMENT_ENTRY_STOP_TYPES:
            price = ("entry_price", "stop_price")
        else:
            price = ("entry_price", "price")
        return (price, ("size", "quantity"))

    async def detect_and_persist_amendment(
        self, account_id: int, incoming: Dict[str, Any],
    ) -> None:
        """P4.T1: write an order_amendments row per changed working-order field.

        Per-field baseline (old_value) is the most recent prior amendment's
        new_value for that (order, field) — chained — falling back to the
        stored order row on the first amendment. The orders row itself goes
        stale (the SR-1 gate rejects the amend upsert), so the amendment ledger
        is the authoritative chain (decided 2026-06-02). Only a real prior
        value changing to a *different* real value counts: a 0/absent old or
        new is a set/remove (a cancel — handled by the ws_manager
        CANCELED/EXPIRED path), so a market entry (price 0) never yields an
        entry_price amendment. calc_id + lifecycle_id are denormalized from the
        stored order (for a TP/SL leg, the T2.9-propagated calc_id when present;
        NULL otherwise — the order_id FK still links the row). deviation_pct is
        signed (new-old)/old*100. Best-effort; venue-agnostic (pure diff).
        """
        eid = incoming.get("exchange_order_id")
        if not eid:
            return
        stored = (await self._db.get_active_orders_map(account_id)).get(eid)
        if not stored:
            return  # unknown / not a working order → placement or terminal, not an amend
        order_id = stored.get("id")
        if not order_id:
            return

        otype = incoming.get("order_type") or stored.get("order_type")
        # Chained baseline: latest prior amendment new_value per field
        # (get_order_amendments returns ts ASC, so the last write wins).
        last_new: Dict[str, float] = {}
        for a in await self._db.get_order_amendments(order_id):
            last_new[a["field"]] = a["new_value"]

        ts_ms = int(incoming.get("updated_at_ms") or incoming.get("created_at_ms") or 0)
        calc_id = stored.get("calc_id")
        lifecycle_id = stored.get("lifecycle_id")
        # P4.T4 (spec §9 position:amended payload): the position this amendment
        # touches. "" for a pre-fill entry order (no position yet) or a
        # junction-less path — the order_id still links the event row.
        position_id = stored.get("terminal_position_id") or ""
        # P9.T3: operator on duty (active seat) at amendment-observation time.
        # O(1) cache read — this is the WS hot path; None when no seat has
        # registered (acceptable, weak attribution). Resolved once for all
        # fields changed in this update (an amendment carries one operator).
        operator_id = cached_operator_id(account_id)

        for field, col in self._amendment_field_pairs(otype):
            try:
                new = float(incoming.get(col) or 0.0)
                base = last_new.get(field)
                old = float(stored.get(col) or 0.0) if base is None else float(base or 0.0)
            except (TypeError, ValueError):
                continue
            # "Meaningfully different" without a math import; guard float noise.
            if old > 0 and new > 0 and abs(new - old) > max(1e-12, abs(old) * 1e-9):
                committed = await self._db.insert_order_amendment({
                    "order_id":      order_id,
                    "calc_id":       calc_id,
                    "field":         field,
                    "old_value":     old,
                    "new_value":     new,
                    "ts_ms":         ts_ms,
                    "operator_id":   operator_id,  # P9.T3 (active session seat)
                    "deviation_pct": (new - old) / old * 100.0 if old else None,
                    "lifecycle_id":  lifecycle_id,
                })
                # P4.T4: emit position:amended 1:1 with each persisted row (only
                # on a confirmed commit — a swallowed insert yields no event).
                # to_thread: log_trade_event opens its OWN sync sqlite3 conn to
                # the per-account DB — wrap it so this WS-hot-path coroutine
                # doesn't block the event loop on the file lock (T212/P3.T2
                # audit convention for new sync-sqlite-in-async callsites; safe
                # here — _emit_amendment_event never touches the aiosqlite _conn).
                if committed:
                    await asyncio.to_thread(
                        self._emit_amendment_event,
                        account_id,
                        order_id=order_id, calc_id=calc_id,
                        position_id=position_id, field=field,
                        old=old, new=new, ts_ms=ts_ms,
                        operator_id=operator_id,
                    )
                    # P6.T4 (spec §9 position:amended): the formal event_bus
                    # topic (P4.T4 shipped the trade event; plan §6 row 6.4
                    # catalogues the topic here). Emitted from THIS on-loop caller
                    # — NOT inside the to_thread'd _emit_amendment_event, since an
                    # asyncio.Queue is not thread-safe. Same 1:1-on-commit gate as
                    # the trade event. publish_engine is enqueue-only.
                    await event_bus.publish_engine(
                        account_id, DOMAIN_POSITION, "amended", {
                            "position_id": position_id,
                            "order_id":    order_id,
                            "field":       field,
                            "old":         old,
                            "new":         new,
                            "ts":          ts_ms,
                            "operator_id": operator_id,  # P9.T3
                        },
                    )

    def _emit_amendment_event(
        self, account_id: int, *, order_id: int, calc_id: Optional[str],
        position_id: str, field: str, old: float, new: float, ts_ms: int,
        operator_id: Optional[str] = None,
    ) -> None:
        """P4.T4 (spec §9 ``position:amended``): one trade event per persisted
        ``order_amendments`` row.

        Sibling of :meth:`_emit_fill_events` — trade-event emission lives here
        (co-located with the persist), NOT in the ``ws_manager`` seam: the
        per-row ``field``/``old``/``new`` only exist inside
        :meth:`detect_and_persist_amendment`'s detection loop, and emitting from
        the seam would duplicate across both ``_apply_order_update`` and
        ``_apply_algo_update``. Payload is the exact spec §9 key set;
        ``position_id`` is ``""`` for a pre-fill entry order and ``operator_id``
        is the active operator seat at observation time (P9.T3; ``None`` when no
        seat has registered). The formal §9 in-process ``event_bus`` topic is Phase 6
        (plan §6 row 6.4) — same trade-event-now / event_bus-later split as
        ``partial_close`` / ``position_opened``. Best-effort: an emission fault
        never blocks amendment persistence.

        Dispatched via ``asyncio.to_thread`` by the caller (the sync
        ``log_trade_event`` opens its own sqlite3 conn — T212/P3.T2 hot-path
        convention). The sibling :meth:`_emit_fill_events` now follows the same
        convention — its blocking writes run in :meth:`_write_fill_trade_events`
        via ``asyncio.to_thread`` (the consistency cleanup the P4.T4 audit filed).
        """
        try:
            from core.trade_event_log import log_trade_event

            log_trade_event(account_id, calc_id, "position_amended", {
                "position_id": position_id,
                "order_id":    order_id,
                "field":       field,
                "old":         old,
                "new":         new,
                "ts":          ts_ms,
                "operator_id": operator_id,  # P9.T3 (active session seat)
            }, source="order_manager")
        except Exception:
            log.debug("position_amended event emission failed", exc_info=True)

    async def _emit_fill_events(self, account_id: int, fill: Dict[str, Any]) -> None:
        """Emit fill trade events + the ``position:partial_close`` event_bus
        topic. Best-effort.

        Split across the loop / a worker thread (the consistency cleanup the
        P4.T4 audit filed; mirrors :meth:`_emit_amendment_event`):

        - The ``position:partial_close`` event_bus publish is an
          ``asyncio.Queue.put_nowait`` (``publish_engine_nowait``) — NOT
          thread-safe — so it runs HERE on the loop thread. ``app_state`` is
          read here too (loop thread), so ``remaining_qty`` is computed once
          and handed to the worker (no cross-thread ``app_state`` read).
        - The blocking trade-event writes (``log_trade_event`` opens its own
          sync sqlite3 conn to the per-account DB) are dispatched off-loop via
          ``asyncio.to_thread`` so this WS-hot-path coroutine doesn't block the
          event loop on the file lock (T212/P3.T2 convention; safe — the worker
          never touches the aiosqlite ``_conn``).
        """
        remaining_qty: Optional[float] = None
        # partial_close: reduce-only fill, position still open. Read app_state +
        # publish the bus event ON the loop thread (put_nowait is not thread-safe).
        try:
            if fill.get("is_close"):
                pos_id = fill.get("terminal_position_id", "")
                if pos_id:
                    pos = next(
                        (p for p in app_state.positions if p.position_id == pos_id), None
                    )
                    if pos and pos.contract_amount > 0:
                        remaining_qty = pos.contract_amount
                        # P6.T4 (spec §9 position:partial_close): mirror onto the
                        # per-account event_bus topic. tp_level_idx omitted (needs
                        # calc.tp_levels parsing + price matching — deferred).
                        # KNOWN (T238 F6, holistic-audit [7]): remaining_qty reads
                        # app_state.contract_amount, which on the FINAL closing fill
                        # still reflects PRE-fill size (>0) — so a final fill emits
                        # partial_close with a stale positive remaining_qty, then
                        # position:closed fires ~2s later. qty_reduced +
                        # realized_pnl_partial are authoritative; a consumer treats
                        # remaining_qty as best-effort.
                        event_bus.publish_engine_nowait(
                            account_id, DOMAIN_POSITION, "partial_close", {
                                "position_id":          pos_id,
                                "qty_reduced":          fill.get("quantity", 0),
                                "remaining_qty":        remaining_qty,
                                "realized_pnl_partial": fill.get("realized_pnl", 0),
                            },
                        )
        except Exception:
            log.debug("fill event_bus emission failed", exc_info=True)

        # Blocking trade-event writes → off the loop. remaining_qty carries both
        # the partial_close gate (None = not a tracked partial) and the value.
        try:
            await asyncio.to_thread(
                self._write_fill_trade_events, account_id, fill, remaining_qty,
            )
        except Exception:
            log.debug("fill trade-event emission failed", exc_info=True)

    def _write_fill_trade_events(
        self, account_id: int, fill: Dict[str, Any],
        remaining_qty: Optional[float],
    ) -> None:
        """Worker body of :meth:`_emit_fill_events`: the blocking trade-event
        writes (``log_trade_event``, own sync sqlite3 conn). Runs in a worker
        thread (``asyncio.to_thread``) — must NOT touch asyncio primitives (the
        partial_close event_bus publish stays on the loop in the caller).
        ``remaining_qty is not None`` ⇔ reduce-only fill with the position still
        open ⇒ emit the partial_close trade event (the same gate the caller used
        for the bus event). Best-effort."""
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

            # partial_close trade event: same gate as the caller's bus event.
            if remaining_qty is not None:
                # T2.11 (spec §8/§9 position:partial_close payload): carry
                # qty_reduced + realized_pnl_partial so the multi-TP ladder is
                # reconstructable from the event stream. tp_level_idx is omitted
                # — mapping a TP fill to its tp_levels rung needs calc.tp_levels
                # parsing + price matching (deferred; not load-bearing).
                log_trade_event(account_id, calc_id, "partial_close", {
                    "symbol": fill.get("symbol", ""),
                    "position_id": fill.get("terminal_position_id", ""),
                    "fill_price": fill.get("price", 0),
                    "fill_qty": fill.get("quantity", 0),
                    "qty_reduced": fill.get("quantity", 0),
                    "remaining_qty": remaining_qty,
                    "realized_pnl_partial": fill.get("realized_pnl", 0),
                }, source="order_manager")

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

        # ⑨ close-side tpid resolution (debug 2026-06-08): on the observe-only
        # Binance path a CLOSING fill can reach here with an empty
        # terminal_position_id — ws_manager copies it from the live position at
        # fill-creation, but that lookup misses when the ACCOUNT_UPDATE that
        # REMOVES the position beats the TRADE event (full-close race) or the
        # snapshot-recovered tpid hadn't been stamped yet. An empty tpid here
        # strands the closed_positions row, the close events, and the closing
        # fill's calc/lifecycle attribution (all key on it). Resolve it from the
        # position being closed (live PositionInfo, else the persisted entry
        # order's minted tpid) and stamp it onto the fill BEFORE the upsert, so
        # the persisted row AND every downstream step key on it. Mirrors the
        # open-side defect-7 fallback; no-op when already populated.
        if fill.get("is_close") and not (fill.get("terminal_position_id") or ""):
            resolved = await self._resolve_close_tpid(account_id, fill)
            if resolved:
                fill["terminal_position_id"] = resolved

        # 1+2. Upsert fill + update parent order in ONE commit
        await self._db.upsert_fill_and_update_order(fill, exchange_order_id)
        # LB-F5 close-order tpid stamp — reconciler R1 delegate (moved
        # verbatim to PositionIdentity.stamp_close_order_tpid; gates —
        # is_close + tpid-carrying + empty-only + reduce-only — live there).
        await self._identity.stamp_close_order_tpid(account_id, fill)
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
        await self._emit_fill_events(account_id, fill)
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

    async def _resolve_close_tpid(
        self, account_id: int, fill: Dict[str, Any]
    ) -> str:
        """Reconciler R1 delegate — ⑨ close-fill tpid resolution (tier-0
        parent_order → live position → entry-order map) moved verbatim to
        :meth:`core.position_identity.PositionIdentity.resolve_close_tpid`."""
        return await self._identity.resolve_close_tpid(account_id, fill)

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
        """Reconciler R1 delegate — the §3.2 primary-calc (calc_id,
        lifecycle_id) selection moved verbatim to
        :meth:`core.position_identity.PositionIdentity.position_primary_calc`."""
        return await self._identity.position_primary_calc(
            account_id, position_id)

    async def _link_position_calc_on_open(
        self, account_id: int, fill: Dict[str, Any]
    ) -> None:
        """Reconciler R1 delegate — T2.1 junction formation + lifecycle
        mint/backfill moved verbatim to
        :meth:`core.position_identity.PositionIdentity.link_position_calc_on_open`
        (which also owns the position:opened/scale_in emissions — the R1
        events-move decision, see the owner's module docstring)."""
        await self._identity.link_position_calc_on_open(account_id, fill)

    async def _stamp_closing_fill_attribution(
        self, account_id: int, fill: Dict[str, Any]
    ) -> None:
        """T2.2 (plan §2 task 2.2): stamp ``calc_id`` + ``lifecycle_id``
        on a closing fill, inherited from the position's PRIMARY calc.

        The primary is the most-contributing calc in the position's
        ``positions_calcs`` junction — largest ``contributed_qty``,
        tie-break earliest ``first_fill_ts`` (spec §3.2, the same basis
        as the close-row delta computation in T2.5/T2.6). Junction rows
        share one ``lifecycle_id`` per ECONOMIC trade (post-R4 a
        venue-reused tpid can carry a second, sealed trade's rows —
        the owner's unsealed-basis rule scopes the read, R5).

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
        # corr-tap: attr_close_stamp (CL.T5, HA-40, spec §5.6 class) — this
        # is a genuine attribution DECISION (inherit the position's primary
        # calc/lifecycle onto the reduce-only closing fill) that the spec's
        # §5.6 table never listed, so it shipped envelope-less. One envelope
        # per CLOSING-fill invocation (mandate 1), incl. the SKIPPED no-op
        # reasons (a close fill that SHOULD inherit but couldn't is the same
        # stranded-attribution shape mandate 1 exists to surface) and the
        # UPDATE failure twin. Opening fills (not is_close) are a domain
        # filter — no envelope (E25 precedent). The fills UPDATE itself is
        # covered by this decision tap rather than a db_write twin: the
        # ASSIGNED line carries the row's new calc_id/lifecycle_id, the
        # ERROR twin its failure (deviation: attr-decision tap over a
        # db_write twin because this IS a §5.6 decision, not a bare write).
        def _tap_close_stamp(outcome: str, *, calc_id: str = "",
                             lifecycle_id: str = "", reason: Optional[str] = None,
                             error_type: Optional[str] = None) -> None:
            payload: Dict[str, Any] = {
                "outcome": outcome,
                "terminal_position_id": pos_id,
                "calc_id": calc_id, "lifecycle_id": lifecycle_id,
                "exchange_order_id": fill.get("exchange_order_id", "") or "",
            }
            if fill_id:
                payload["dedup_key"] = f"{fill_id}:close_stamp"
            if reason:
                payload["reason"] = reason
            if error_type:
                payload["error_type"] = error_type
            correlation_log.emit(
                "order_manager", "internal", "internal",
                correlation_log.CAT_ATTR_CLOSE_STAMP, payload,
                account_id=account_id, symbol=fill.get("symbol") or None,
            )

        if not fill.get("is_close"):
            return  # domain filter: this method is meaningful only for closes
        pos_id = fill.get("terminal_position_id", "") or ""
        fill_id = fill.get("exchange_fill_id", "") or ""
        if not pos_id:
            _tap_close_stamp("SKIPPED", reason="empty_tpid")
            return
        if not fill_id:
            _tap_close_stamp("SKIPPED", reason="no_fill_id")
            return

        primary_calc_id, lifecycle_id = await self._position_primary_calc(
            account_id, pos_id,
        )
        if not primary_calc_id and not lifecycle_id:
            # no junction → nothing to inherit. A stranded close-fill: the
            # close has no attributable calc (UNPLANNED, or the empty-tpid
            # binance_ws path) — a line, not a silent return.
            _tap_close_stamp("SKIPPED", reason="no_junction")
            return

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
            _tap_close_stamp("ASSIGNED", calc_id=primary_calc_id or "",
                             lifecycle_id=lifecycle_id or "")
        except Exception as e:
            log.warning(
                "close-fill stamp: update failed for fill=%s pos=%s",
                fill_id, pos_id, exc_info=True,
            )
            _tap_close_stamp("ERROR", calc_id=primary_calc_id or "",
                             lifecycle_id=lifecycle_id or "",
                             reason="update_failed", error_type=type(e).__name__)

    async def _enrich_positions_calc_id(
        self, account_id: int, positions: List[PositionInfo]
    ) -> None:
        """T2.3 + T2.12 (plan §2 tasks 2.3 / 2.12): stamp each live
        position's junction-derived calc linkage onto its ``PositionInfo`` —
        the primary (most-contributing) ``calc_id`` (T2.3), the full
        ``contributing_calc_ids`` list, and the live ``size_delta_pct``
        (T2.12).

        Called from ``refresh_cache`` (the controlled position-enrichment
        entry point), so it covers both stated triggers: the live
        first-fill case (a fill's order update drives a refresh) and
        **restart rehydrate** — at startup ``_startup_fetch`` →
        ``process_order_snapshot`` → ``refresh_cache`` runs this, re-deriving
        all three fields from the persisted junction. (T2.12 needs NO
        separate exchange.py / startup hook: this authoritative re-derivation
        already runs at startup; a second hook would duplicate it and risk
        divergence — deviation from the plan's stated files, chosen for
        single-source correctness.) Re-evaluated each refresh so the values
        track the junction as it grows (scale-in); all three fields are in
        ``_PRESERVE_FIELDS`` so a snapshot rebuild between refreshes doesn't
        blank the live display.

        ONE batched junction read per refresh (not per position) — this
        runs on every WS order update, so the fan-out is kept off the
        hot path. Best-effort and AUTHORITATIVE (T230 R2): the fields mirror
        the junction each refresh — set from it when rows exist, and CLEARED
        (calc_id="", contributing_calc_ids=[], size_delta_pct=0.0) when none
        does (UNPLANNED, pre-first-fill, or a same-(symbol,direction) reopen
        that inherited stale values via _PRESERVE_FIELDS). See the loop below.

        ``size_delta_pct`` (T2.12 deviation): the live size deviation vs the
        primary calc's planned size — ``(Σ contributed_qty − primary
        planned_size) / planned_size × 100`` (signed, spec §3.2
        most-contributing basis; mirrors the T2.5 close-time size_delta).
        0.0 when there is no junction or no planned_size snapshot. The
        yellow/red badge thresholding and TP/SL live deviation are Phase 4.4
        (they need the order-amendment tracking that isn't wired yet).
        """
        # corr-tap: attr_enrich + attr_drift_check + attr_tpid_resolve
        # (CL.T3b-close, spec §5.6). These refresh-driven taps are
        # ON-CHANGE GATED (spec §7.3): this method runs per WS order
        # update, so each (position, outcome) emits on first stamp +
        # transition only, via the instance memo below. ERROR taps stay
        # ungated — if the DB is down, the repetition IS the signal.
        _memo: Dict[Any, Any] = self.__dict__.setdefault(
            "_attr_enrich_memo", {})

        def _emit_on_change(key: Any, sig: Any, category: str,
                            payload: Dict[str, Any],
                            symbol: Optional[str] = None) -> None:
            if _memo.get(key) == sig:
                return
            _memo[key] = sig
            correlation_log.emit(
                "order_manager", "internal", "internal", category, payload,
                account_id=account_id, symbol=symbol,
            )

        # memo hygiene — PRUNE ON ENTRY (audit T3bC-2: a tail cleanup is
        # unreachable on the early-return paths, so a flat interim would
        # gate-suppress a same-(ticker,direction) reopen's first stamp).
        # Pruning against the CURRENT positions list at the start covers
        # every exit path: a vanished position's keys are gone before any
        # emit decision for its successor, and a flat pass clears the map.
        _live_keys: set = set()
        for p in positions:
            kid = p.position_id or f"{p.ticker}:{p.direction}"
            _live_keys.add(("enrich", kid))
            _live_keys.add(("drift", kid))
            _live_keys.add(("recover", p.ticker, p.direction))
        for k in list(_memo):
            if k not in _live_keys:
                del _memo[k]

        # Unminted-snapshot recovery (debug 2026-06-08): a position first seen
        # via a REST snapshot (engine started while it was already open) has an
        # empty position_id — the snapshot path deliberately doesn't mint (no
        # stable first-open time across restarts; DataCache KNOWN GAP). Without
        # a tpid it can't match the junction below -> empty Plan badge + lost
        # linkage in the live view. Recover the tpid from the position's
        # persisted entry order (which carries the WS-minted id) so the junction
        # lookup, funding sum, and close-side all see it. Setting it here
        # self-persists: DataCache._preserve_metadata carries a now-present
        # position_id across the next snapshot rebuild. GATED on an empty-id
        # position existing, so the normal WS path (all minted) pays nothing.
        _recovered_now: set = set()
        if any(not p.position_id for p in positions):
            try:
                tpid_by_key = await self._db.get_open_entry_tpids_by_symbol_side(
                    account_id)
            except Exception as e:
                tpid_by_key = {}
                log.debug("tpid re-derivation read failed", exc_info=True)
                # corr-tap: attr_tpid_resolve ERROR (snapshot-recovery side)
                correlation_log.emit(
                    "order_manager", "internal", "internal",
                    correlation_log.CAT_ATTR_TPID_RESOLVE,
                    {"outcome": "ERROR", "via": "snapshot_recovery",
                     "reason": "recovery_read_failed",
                     "error_type": type(e).__name__,
                     "terminal_position_id": "", "calc_id": "",
                     "lifecycle_id": "", "exchange_order_id": ""},
                    account_id=account_id,
                )
            for pos in positions:
                if not pos.position_id:
                    recovered = tpid_by_key.get((pos.ticker, pos.direction))
                    if recovered:
                        pos.position_id = recovered
                        _recovered_now.add(recovered)
                    # corr-tap: attr_tpid_resolve via=snapshot_recovery —
                    # the historical unminted-snapshot bug (#1) as a line;
                    # gated so an unrecoverable position doesn't repeat
                    # per refresh.
                    _rk = ("recover", pos.ticker, pos.direction)
                    _rsig = ("RESOLVED", recovered) if recovered else (
                        "UNRESOLVED",)
                    _rp: Dict[str, Any] = {
                        "outcome": "RESOLVED" if recovered else "UNRESOLVED",
                        "via": "snapshot_recovery",
                        "symbol": pos.ticker, "direction": pos.direction,
                        "terminal_position_id": recovered or "",
                        "calc_id": "", "lifecycle_id": "",
                        "exchange_order_id": "",
                    }
                    if recovered:
                        _rp["tier"] = "entry_order"
                    else:
                        _rp["reason"] = "no_match"
                    _emit_on_change(
                        _rk, _rsig,
                        correlation_log.CAT_ATTR_TPID_RESOLVE, _rp,
                        symbol=pos.ticker,
                    )

        # P5.T7: live unrealized funding — stamped FIRST and INDEPENDENTLY of the
        # junction below, so a junction-read fault (the early returns) can't
        # strand a stale funding value (audit). ONE grouped SUM keyed by
        # terminal_position_id (covers UNPLANNED / no-calc positions with a
        # tpid). Best-effort: on a read fault, DON'T overwrite — leave the
        # preserved value (only stamp on success, incl. 0.0 for no-funding).
        _open_tpids = [p.position_id for p in positions if p.position_id]
        if _open_tpids:
            try:
                funding_by_pos = await self._db.sum_funding_by_positions(_open_tpids)
            except Exception:
                log.debug("live funding sum failed", exc_info=True)
            else:
                for _p in positions:
                    _p.individual_funding_fees = funding_by_pos.get(
                        _p.position_id, 0.0)

        if not any(p.position_id for p in positions):
            # every position lacks a key — each is a (gated) SKIPPED line,
            # not an absence (the no_position_key historical shape)
            for pos in positions:
                _emit_on_change(
                    ("enrich", f"{pos.ticker}:{pos.direction}"),
                    ("SKIPPED", "no_position_key"),
                    correlation_log.CAT_ATTR_ENRICH,
                    {"outcome": "SKIPPED", "reason": "no_position_key",
                     "terminal_position_id": "", "calc_id": "",
                     "lifecycle_id": "", "exchange_order_id": ""},
                    symbol=pos.ticker,
                )
            return
        try:
            async with self._db._conn.execute(
                "SELECT position_id, calc_id, contributed_qty, planned_size, "
                "planned_tp, planned_sl, sealed_ts "
                "FROM positions_calcs WHERE account_id = ? "
                "ORDER BY first_fill_ts ASC, id ASC",
                (account_id,),
            ) as cur:
                rows = await cur.fetchall()
        except Exception as e:
            # Read failed — leave fields untouched (don't clear on error).
            log.debug("calc_id enrichment: junction read failed", exc_info=True)
            # corr-tap: attr_enrich ERROR (ungated — rare; repetition = signal)
            correlation_log.emit(
                "order_manager", "internal", "internal",
                correlation_log.CAT_ATTR_ENRICH,
                {"outcome": "ERROR", "reason": "junction_read_failed",
                 "error_type": type(e).__name__,
                 "terminal_position_id": "", "calc_id": "",
                 "lifecycle_id": "", "exchange_order_id": ""},
                account_id=account_id,
            )
            return
        # Aggregate per (position, calc): sum contributed_qty (a calc may
        # place >1 order on a position → multiple junction rows) and carry
        # the calc's planned_size snapshot. Rows arrive ordered by
        # first_fill_ts ASC, and dict preserves insertion order, so a calc's
        # first appearance fixes its tie-break rank (earliest first_fill).
        # R5 (R4 residual (a)) — same UNSEALED-basis rule as the owner's
        # position_primary_calc (T240 convergence): a position with ANY
        # unsealed junction rows aggregates ONLY those, so on a
        # venue-reused tpid the sealed (closed) trade's rows can't paint
        # the LIVE trade's badge/calc. An all-sealed position (the brief
        # post-final-close window before the snapshot drops it) keeps the
        # full-rows basis.
        _has_unsealed = {r[0] for r in rows if r[6] is None and r[0]}
        per_pos: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for pid, cid, qty, planned, p_tp, p_sl, sealed in rows:
            if not pid or not cid:
                continue
            if sealed is not None and pid in _has_unsealed:
                continue  # sealed rows excluded when the trade has live rows
            calcs = per_pos.setdefault(pid, {})
            agg = calcs.get(cid)
            if agg is None:
                agg = {"qty": 0.0, "planned": None,
                       "planned_tp": None, "planned_sl": None}
                calcs[cid] = agg
            agg["qty"] += (qty or 0.0)
            if agg["planned"] is None and planned:
                agg["planned"] = planned
            # #1 (debug 2026-06-08): carry the calc's planned TP/SL snapshot so
            # the badge below can detect a live TP/SL drift (the Binance
            # cancel+create amendment the order_amendments ledger never sees).
            if agg["planned_tp"] is None and p_tp:
                agg["planned_tp"] = p_tp
            if agg["planned_sl"] is None and p_sl:
                agg["planned_sl"] = p_sl

        # P4.T3 live deviation badge: batch the amendment tally (ONE grouped
        # query for ALL contributing calcs) + read the account's yellow/red
        # thresholds ONCE here (not per position). Only needed for junction'd
        # positions; no-calc positions are "red" without thresholds.
        # Thresholds DEFAULT to the spec values so a transient read failure
        # degrades gracefully — leaving red_pct at 0.0 would make EVERY linked
        # position "off-plan"/red (audit P4T3-MED). Config read is internally
        # exception-safe and done FIRST, so an amendments-query failure can't
        # strand the thresholds; both reads are best-effort. (Config read per
        # refresh is acceptable + cacheable later.)
        from core.account_config import (
            DEFAULT_YELLOW_DEVIATION_PCT, DEFAULT_RED_DEVIATION_PCT,
            read_account_config_async,
        )
        amend_by_calc: Dict[str, int] = {}
        yellow_pct, red_pct = DEFAULT_YELLOW_DEVIATION_PCT, DEFAULT_RED_DEVIATION_PCT
        if per_pos:
            # read_account_config_async is exception-safe by contract (returns a
            # fully-defaulted AccountConfig on any error — account_config.py), so
            # it needs no guard here; a try would be dead code (re-audit BADGE-001).
            # The amendment count, in contrast, CAN raise (a transient DB error)
            # — its OWN try keeps that failure from stranding the badge, separate
            # from the config read (P4 audit P4T3-001: one shared try would let
            # either failure skip the other). Logged at WARNING, not debug: a
            # masked-amendment miss paints a real amended position green for THIS
            # refresh, so it must be diagnosable; self-heals on the next
            # successful htmx poll — bounded, transient.
            cfg = await read_account_config_async(self._db, account_id)
            yellow_pct, red_pct = cfg.yellow_deviation_pct, cfg.red_deviation_pct
            try:
                all_calc_ids = {cid for calcs in per_pos.values() for cid in calcs}
                amend_by_calc = await self._db.count_amendments_by_calcs(all_calc_ids)
            except Exception:
                log.warning(
                    "deviation-badge amendment count failed — amendments masked "
                    "this refresh (positions may paint green; self-heals next "
                    "refresh)", exc_info=True,
                )

        # Authoritative: the three fields mirror the junction on each refresh.
        # A position with no junction row is CLEARED — UNPLANNED, a
        # pre-first-fill position, or a same-(symbol,direction) reopen that
        # inherited stale values via _PRESERVE_FIELDS (T226 holistic-audit
        # R2). Self-heals once the new position's first opening fill writes
        # its junction.
        for pos in positions:
            # (individual_funding_fees already stamped above, before the early
            # returns — independent of the junction.)
            if not pos.position_id:
                # binance one-way / pre-snapshot — no junction key
                _emit_on_change(
                    ("enrich", f"{pos.ticker}:{pos.direction}"),
                    ("SKIPPED", "no_position_key"),
                    correlation_log.CAT_ATTR_ENRICH,
                    {"outcome": "SKIPPED", "reason": "no_position_key",
                     "terminal_position_id": "", "calc_id": "",
                     "lifecycle_id": "", "exchange_order_id": ""},
                    symbol=pos.ticker,
                )
                continue
            calcs = per_pos.get(pos.position_id)
            if not calcs:
                pos.calc_id = ""
                pos.contributing_calc_ids = []
                pos.size_delta_pct = 0.0
                pos.amendment_count = 0
                pos.tpsl_amended = False
                pos.deviation_badge = "red"  # no-calc / UNPLANNED (spec §10.2)
                _rec = pos.position_id in _recovered_now
                _ep: Dict[str, Any] = {
                    "outcome": "CLEARED", "reason": "no_junction",
                    "terminal_position_id": pos.position_id,
                    "calc_id": "", "lifecycle_id": "",
                    "exchange_order_id": "",
                    "badge": "red", "recovered": _rec,
                }
                if _rec:
                    _ep["recovery_source"] = "entry_order"
                # sig EXCLUDES the recovered flag (audit T3bC-1: it is True
                # only on the recovery pass, so including it would re-emit a
                # misleading "recovered:false" flip-back next pass; the
                # first-stamp line carries the recovery truth)
                _emit_on_change(
                    ("enrich", pos.position_id),
                    ("CLEARED", "", "red"),
                    correlation_log.CAT_ATTR_ENRICH, _ep,
                    symbol=pos.ticker,
                )
                continue
            items = list(calcs.items())  # insertion order = first_fill ASC
            # Primary via the SHARED selector (largest summed contributed_qty
            # per calc, earliest-first_fill tie-break) → identical rule to
            # _position_primary_calc (close path), so the live/rehydrated
            # PositionInfo.calc_id converges with the sealed closed_positions
            # calc_id (T240/R1). items are first_fill-ordered for the tie-break.
            primary_cid = _most_contributing_calc_id(
                [(cid, a["qty"]) for cid, a in items]
            )
            primary_agg = calcs[primary_cid]
            pos.calc_id = primary_cid
            # All contributing calcs, primary-first then by qty desc (stable
            # sort keeps first_fill order among equal-qty calcs).
            pos.contributing_calc_ids = [
                cid for cid, _ in sorted(
                    items, key=lambda kv: kv[1]["qty"], reverse=True,
                )
            ]
            # Live size deviation vs the primary calc's planned snapshot.
            planned = primary_agg["planned"]
            actual = sum(a["qty"] for _, a in items)
            pos.size_delta_pct = (
                (actual - planned) / planned * 100.0 if planned else 0.0
            )
            # P4.T3 live deviation badge (combined: spec §10.2 + plan §4.4).
            pos.amendment_count = sum(
                amend_by_calc.get(cid, 0) for cid in pos.contributing_calc_ids
            )
            # #1 (debug 2026-06-08): live TP/SL drift. On observe-only Binance an
            # operator TP/SL amendment is a venue cancel+create (a fresh algo
            # order), NOT an in-place modify — so detect_and_persist_amendment
            # never fires and order_amendments stays empty (amendment_count=0).
            # Detect it DIRECTLY: the position's CURRENT working TP/SL
            # (individual_tp/sl_price, from the live reduce-only orders) vs the
            # primary calc's planned snapshot. The matcher required an exact
            # (1e-8) TP/SL match at link time, so any later divergence beyond a
            # tiny relative tolerance is a real amendment → "amended" (yellow).
            # both-present guard skips a calc/position without that leg; a
            # missing live price (0.0) self-heals on the next refresh once the
            # working order is observed (same transient model as the count).
            _p_tp = primary_agg.get("planned_tp")
            _p_sl = primary_agg.get("planned_sl")
            _live_tp = pos.individual_tp_price or 0.0
            _live_sl = pos.individual_sl_price or 0.0
            # price drift: a planned leg whose live trigger moved beyond tolerance.
            _tp_drift = bool(_p_tp and _live_tp
                             and abs(_live_tp - _p_tp) / abs(_p_tp) > 0.001)
            _sl_drift = bool(_p_sl and _live_sl
                             and abs(_live_sl - _p_sl) / abs(_p_sl) > 0.001)
            # #1b (debug 2026-06-09): REMOVAL of a planned protective leg. The
            # operator canceled a TP/SL the calc planned, leaving the position
            # OFF-PLAN (e.g. an unprotected position with no stop). The price-drift
            # check above can't see this (it skips when the live leg is 0), so the
            # badge wrongly stayed green "on-plan" — operator-flagged as fatal
            # (a removed stop is more dangerous than a moved one). Gate removal on
            # the OTHER leg being live, so a fresh open whose bracket orders aren't
            # observed yet (BOTH 0) is NOT falsely flagged; the brief TP-before-SL
            # observation window self-heals on the next refresh.
            _sl_removed = bool(_p_sl and not _live_sl and _live_tp)
            _tp_removed = bool(_p_tp and not _live_tp and _live_sl)
            # Severity (2026-06-20): a REMOVED stop-loss leaves the position
            # unprotected — the most dangerous deviation (operator-flagged
            # "fatal") → level 2 = RED. A TP/SL price move or a removed
            # take-profit is "amended" → level 1 = yellow. 0 = on-plan.
            if _sl_removed:
                _amend_level = 2
            elif _tp_drift or _sl_drift or _tp_removed:
                _amend_level = 1
            else:
                _amend_level = 0
            tpsl_amended = _amend_level > 0
            pos.tpsl_amended = tpsl_amended
            # STICKY capture (#2 history-badge fix, 2026-06-15): once set for a
            # tpid it stays until the final close-row prunes it, so the close
            # row reflects the amendment even though pos.tpsl_amended resets to
            # False at close (legs gone → no drift). The MAX severity seen
            # sticks (a once-removed stop stays red in history even if re-added).
            # Only linked positions reach here (the no-calc branch above
            # continues before this), so the stash is inherently linked-only.
            if _amend_level and pos.position_id:
                if _amend_level > self._tpsl_amended_seen.get(pos.position_id, 0):
                    self._tpsl_amended_seen[pos.position_id] = _amend_level
            # LIVE badge uses the CURRENT-refresh sl_removed (reflects NOW — red
            # while unprotected, back to yellow once a stop is re-added); the
            # sticky stash above is the close-row's "worst during life".
            pos.deviation_badge = deviation_badge_level(
                has_calc=True, size_delta_pct=pos.size_delta_pct,
                amendment_count=pos.amendment_count, tpsl_amended=tpsl_amended,
                sl_removed=_sl_removed,
                yellow_pct=yellow_pct, red_pct=red_pct,
            )

            # corr-tap: attr_drift_check (CL.T3b-close, spec §5.6) — the
            # SL-removal badge bug (#h) becomes its own line: "planned_sl=X,
            # live_sl=0, sl_removed=…, badge=…" shows a wrong verdict in its
            # own output. Gated on the (badge, drift/removal flags) tuple —
            # badge TRANSITION + first stamp (§7.3); badge_before reads the
            # memo's previous tuple.
            _dkey = ("drift", pos.position_id)
            _prev = _memo.get(_dkey)
            _badge_before = _prev[0] if isinstance(_prev, tuple) else None
            _emit_on_change(
                _dkey,
                (pos.deviation_badge, _tp_drift, _sl_drift,
                 _tp_removed, _sl_removed),
                correlation_log.CAT_ATTR_DRIFT_CHECK,
                {
                    "outcome": "CHECKED",
                    "planned_tp": _p_tp, "planned_sl": _p_sl,
                    "live_tp": _live_tp, "live_sl": _live_sl,
                    "tp_drift": _tp_drift, "sl_drift": _sl_drift,
                    "tp_removed": _tp_removed, "sl_removed": _sl_removed,
                    "tpsl_amended": tpsl_amended,
                    "badge_before": _badge_before,
                    "badge": pos.deviation_badge,
                    "terminal_position_id": pos.position_id,
                    "calc_id": primary_cid, "lifecycle_id": "",
                    "exchange_order_id": "",
                },
                symbol=pos.ticker,
            )

            # corr-tap: attr_enrich (CL.T3b-close, spec §5.6) — the stamped
            # outcome; gated per (position, outcome) (§7.3).
            _rec = pos.position_id in _recovered_now
            _ep2: Dict[str, Any] = {
                "outcome": "STAMPED",
                "terminal_position_id": pos.position_id,
                "calc_id": primary_cid,
                "lifecycle_id": "",
                "exchange_order_id": "",
                "n_contributing": len(pos.contributing_calc_ids),
                "size_delta_pct": round(pos.size_delta_pct, 4),
                "amendment_count": pos.amendment_count,
                "badge": pos.deviation_badge,
                "recovered": _rec,
            }
            if _rec:
                _ep2["recovery_source"] = "entry_order"
            # sig EXCLUDES the recovered flag (audit T3bC-1 — see the
            # CLEARED branch note)
            _emit_on_change(
                ("enrich", pos.position_id),
                ("STAMPED", primary_cid, pos.deviation_badge,
                 len(pos.contributing_calc_ids)),
                correlation_log.CAT_ATTR_ENRICH, _ep2,
                symbol=pos.ticker,
            )

    # ── Position Close ─────────────────────────────────────────────────────

    async def _backfill_open_fill_tpids(
        self, account_id: int, opens: List[Dict[str, Any]], pos_id: str,
    ) -> int:
        """Reconciler R1 delegate — the close-time open-fill tpid/calc/
        lifecycle backfill moved verbatim to
        :meth:`core.position_identity.PositionIdentity.backfill_open_fill_tpids`."""
        return await self._identity.backfill_open_fill_tpids(
            account_id, opens, pos_id)

    async def _build_close_row_for_fill(
        self, account_id: int, fill: Dict[str, Any], *, force_final: bool = False,
    ) -> None:
        """Build a closed_positions row for a partial or full close.

        Groups closing fills from the same parent order into a single row.
        Computes VWAP entry/exit, proportional fees, exit reason, and
        implementation shortfall from pre_trade_log.

        T2.11 (multi-TP partial-close lifecycle): one row per closing ORDER
        is preserved (operator-confirmed model — each TP rung keeps its own
        partial row). What T2.11 adds on top: (1) calc completion is deferred
        to the FINAL close (size→0) instead of firing on the first partial
        (see ``_complete_calcs_on_close``); (2) the FINAL row's exit_reason
        is ladder-aware — TP_LADDER_COMPLETE or MIXED (see
        ``_classify_final_exit_reason``). ``force_final`` is set by the
        position-disappearance safety net (``build_final_close_row``), which
        knows the position is gone, so its row is unconditionally final.
        """
        # corr-tap: attr_close_build (CL.T3b-close, spec §5.6) — ONE envelope
        # per invocation via the finally below; ``_trace`` accumulates the
        # decision narrative so the historical close-recording bug class is
        # root-causable on one screen: "strict key POS-9 → 0 rows; walk →
        # 2 rows, both tpid-empty; backfilled 2; row written".
        _trace: Dict[str, Any] = {"walk_used": False, "backfilled": 0}
        try:
            pos_id    = fill.get("terminal_position_id", "")
            symbol    = fill.get("symbol", fill.get("ticker", ""))
            direction = fill.get("direction", "")
            _trace["strict_key"] = pos_id or ""

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
                opens = []
            _trace["opens_found_strict"] = len(opens)
            # #3/#4 fix (debug 2026-06-08): on the observe-only Binance path the
            # OPENING fills are written with an EMPTY terminal_position_id (the
            # position isn't minted until the first open completes), while ⑨ now
            # stamps the minted tpid on the CLOSING fill. So the strict tpid-keyed
            # open lookup above MISSES the opens → no entry VWAP → the close row
            # is never built (the close vanishes from Position History +
            # Recent-Closes) AND the per-position drilldown is empty. Fall back to
            # the canonical chronological walk (the same one the empty-pos_id path
            # uses — contamination-safe per T188) whenever the strict lookup found
            # nothing, then BACKFILL the resolved opens' tpid so they share the
            # close row's tpid for the fills/events drilldown. ⑨ REGRESSION: before
            # ⑨ the closing fill was empty-tpid so this position took the walk
            # path; ⑨'s stamp diverted it to the broken strict path. Covers linked
            # AND unlinked (UNPLANNED) positions — the walk needs no calc.
            if not opens:
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
                _trace["walk_used"] = True
                _trace["opens_found_walk"] = len(opens)
                if pos_id and opens:
                    _trace["backfilled"] = await self._backfill_open_fill_tpids(
                        account_id, opens, pos_id,
                    )
            # tpids AS FOUND (the backfill above updates the DB rows, not
            # these dicts) — "both tpid-empty" is the root-cause signal.
            _trace["open_fill_tpids"] = {
                "empty": sum(
                    1 for f in opens
                    if not (f.get("terminal_position_id") or "")
                ),
                "populated": sum(
                    1 for f in opens if f.get("terminal_position_id")
                ),
            }
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
            _trace["entry_source"] = (
                "opens_vwap" if opens else "position_average_fallback"
            )

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
                _trace["skip"] = "no_closing_fills"
                return
            _trace["n_close_fills"] = len(close_fills)

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

            # ── T2.11: is this the FINAL close (position size→0)? ───────
            # Data-derived from fills (Σ closing qty ≥ Σ opening qty),
            # deterministic and NOT racy with the ACCOUNT_UPDATE snapshot
            # (which may reflect pre- or post-fill state). force_final: the
            # position-disappearance safety net knows the position is gone.
            # Empty tpid (binance one-way) or missing opens → can't sum per
            # position, so preserve the pre-T2.11 "complete on this close"
            # behavior (is_final=True) rather than risk never completing.
            if force_final or not pos_id or total_open_qty <= 0:
                is_final = True
            else:
                pos_closes = await self._db.get_position_fills(
                    account_id, pos_id, symbol, direction, is_close=True,
                )
                # Scope the sum to closing fills AT OR BEFORE this close's
                # exit_time (T238 review F1, HIGH): each closing fill schedules
                # its OWN build +2s, so by the time an EARLIER rung's build runs
                # the LATER rungs may already be on disk. Summing all of them
                # would make the earlier rung's build see is_final=True and
                # mis-stamp its partial row with the ladder exit_reason (and
                # complete the calc early). Counting only fills ≤ this build's
                # exit_time gives the cumulative closed qty AS OF this close —
                # the correct per-row view, deterministic regardless of build
                # interleaving.
                total_closed_all = sum(
                    f["quantity"] for f in pos_closes
                    if int(f.get("timestamp_ms", 0) or 0) <= exit_time
                )
                # Relative epsilon (T238 review F4, MED): a flat 1e-9 absolute
                # is too tight for fractional crypto qty — a genuine full close
                # short by float/rounding (e.g. 1e-8) would miss is_final. Use
                # a 1ppm relative tolerance with an absolute floor.
                tol = max(1e-9, total_open_qty * 1e-6)
                is_final = total_closed_all >= total_open_qty - tol

            # ── Exit reason: per-order type, then (T2.11) ladder-aware on
            # the FINAL close — TP_LADDER_COMPLETE (≥2 TP closing orders, no
            # SL/manual) or MIXED (TP ladder finished off by SL/manual).
            # Non-final partial rows keep their per-order reason.
            exit_reason = await self._determine_exit_reason(
                account_id, exchange_order_id,
            )
            if is_final:
                exit_reason = await self._classify_final_exit_reason(
                    account_id, pos_id, fallback=exit_reason,
                )
            _trace["is_final"] = is_final
            _trace["exit_reason"] = exit_reason

            # P6.T7: liquidation_px = the realized LIQUIDATION-fill VWAP (NOT
            # this close row's exit_price). _classify_final_exit_reason sets
            # LIQUIDATION whenever ANY closing order for the position is a
            # liquidation (position-scoped), but exit_price is order-scoped — so
            # in a partial-liq-then-non-liq-final ordering they'd diverge. Source
            # liquidation_px from the liquidation fills directly so it's the liq
            # execution price regardless of close ordering (audit P6T7-LIQPX).
            # Falls back to exit_price when no liq fills are keyable (empty-tpid
            # one-way path, where this close IS the liquidation).
            liquidation_px = None
            if exit_reason == "LIQUIDATION":
                liquidation_px = await self._liquidation_vwap(account_id, pos_id)
                if liquidation_px is None:
                    liquidation_px = exit_price

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
            _trace["calc_id"] = close_calc_id or ""
            _trace["lifecycle_id"] = close_lifecycle_id or ""

            # ── T2.5: close-time deltas vs the most-contributing calc ───
            # Spec §3.2 delta-basis rule. Best-effort (try/except → {}),
            # so a junction/calc read failure never blocks the close-row
            # write. Deterministically recomputed on every close-row build,
            # and preserved across INSERT OR REPLACE in insert_closed_position.
            deltas = await self._compute_close_deltas(
                account_id, pos_id, entry_price, total_open_qty,
                exit_price, entry_time, exit_time,
            )

            # Contributing calcs for this position (distinct opening-fill
            # calc_ids; fallback to the primary when the junctionless / binance
            # empty-tpid path leaves opens without a calc_id). Computed ONCE
            # here and reused by the is_final completion below.
            contributing_calc_ids = {
                f["calc_id"] for f in opens if f.get("calc_id")
            }
            if not contributing_calc_ids and close_calc_id:
                contributing_calc_ids = {close_calc_id}

            # ── P4.T2 (spec §3.2): cumulative_amendment_count ───────────
            # Count order_amendments linked to the position's contributing
            # calcs — entry legs (matcher calc_id) AND protective TP/SL legs
            # (T2.9-inherited calc_id), both of which denormalize calc_id onto
            # the amendment row. Recomputed on every close-row build (like the
            # T2.5 deltas) and preserved across INSERT OR REPLACE. Best-effort.
            try:
                cumulative_amendment_count = (
                    await self._db.count_amendments_for_calcs(contributing_calc_ids)
                )
            except Exception:
                cumulative_amendment_count = 0

            # ── P5.T4/T5: funding fees + net PnL ────────────────────────
            # closed_positions.funding_fees = SUM(funding_events.amount) for
            # the position (spec §11[F]), written on the FINAL close row only
            # (is_final): T2.11 preserves per-partial rows, so stamping the full
            # position SUM on every partial would overcount when summed across
            # rows. Partial rows and the junctionless / binance empty-tpid path
            # carry 0.0. The SUM is computed ONCE here and never recomputed.
            #
            # DEFERRED-FUNDING (P6 reconcile — was a filed P5 gap, now CLOSED):
            # funding settles ~3x/day but the attribution poll runs every ~5min,
            # so funding that settles while this position is OPEN but is first
            # polled only AFTER it closed under-counts this one-shot SUM.
            # CORRECTED MECHANISM (the earlier "filed" note said the late row is
            # written-but-un-summed): the live attribution map is built from OPEN
            # positions, so a closed position's late funding actually ORPHANED
            # (never written) — not written-then-missed. The fix lives on the
            # funding side: handle_funding_incomes now falls back to a closed-
            # lifecycle window lookup (find_closed_position_for_funding) and
            # reconcile_closed_position_funding recomputes THIS row's
            # funding_fees/net_pnl from the now-written funding_events SUM. This
            # one-shot SUM stays the fast path for the common (caught-while-open)
            # case; the reconcile only touches rows that get late funding.
            #
            # OVERFILL edge (audit, documented): if closing fills on this tpid
            # exceed open qty across DISTINCT closing orders at distinct ts, each
            # can satisfy is_final and stamp the full SUM on its own row →
            # funding double-counts (same anomaly that over-attributes prop_entry
            # above; HIGH-009 caps prop_entry only, not is_final). Anomaly-gated
            # (you can't normally close more than you hold); not guarded here to
            # avoid destabilizing the T238-tuned is_final logic.
            #
            # Best-effort — a funding read fault must not block the close write.
            #
            # NOT added to _CLOSED_POS_DELTA_COLS (unlike the T2.5/P4 deltas):
            # closed_positions.funding_fees is NOT NULL DEFAULT 0, but that
            # preserve path uses None as the "not-computed" sentinel and would
            # spread None over the explicit default → constraint violation. It
            # also isn't needed: this builder is the SOLE writer of real-tpid
            # rows and recomputes the full SUM on every final-row build, while
            # the offline rebuild/backfill paths use bf:/rebuilt: synthetic tpids
            # that never REPLACE a live real-tpid row (same as net_pnl).
            funding_fees = 0.0
            if is_final and pos_id:
                try:
                    funding_fees = await self._db.sum_position_funding(pos_id)
                except Exception:
                    log.debug(
                        "funding sum failed for position %s", pos_id,
                        exc_info=True,
                    )
                    funding_fees = 0.0

            # P6 holistic-audit: make the §9 position:closed / position:liquidated
            # events idempotent per (account, tpid, exit_time). Two +2s builds can
            # reach this for the SAME final close — the per-fill deferred build and
            # the position-disappearance backstop (build_final_close_row,
            # force_final=True). Emit the §9 events ONLY when THIS build creates a
            # NEW close row, not on a REPLACE. get_unrecorded_closing_fills already
            # skips recorded fills, so the residual is just a narrow
            # both-build-before-either-commits race → the §9 events are
            # AT-LEAST-ONCE under disappearance; a subscriber must dedup on
            # position_id+close_ts_ms (or lifecycle_id). The flat
            # risk:position_closed is intentionally NOT gated (the reconciler
            # tolerates re-delivery + relies on per-partial firing).
            close_row_is_new = True
            try:
                async with self._db._conn.execute(
                    "SELECT 1 FROM closed_positions WHERE account_id = ? "
                    "AND terminal_position_id = ? AND exit_time_ms = ? LIMIT 1",
                    (account_id, pos_id, exit_time),
                ) as _cur:
                    close_row_is_new = (await _cur.fetchone()) is None
            except Exception:
                close_row_is_new = True   # best-effort: prefer emit over silent drop

            # ── Persist ─────────────────────────────────────────────────
            net_pnl = realized_pnl - total_fees + funding_fees
            _trace["close_row_is_new"] = close_row_is_new
            _trace["row_written"] = bool(await self._db.insert_closed_position({
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
                "funding_fees":         funding_fees,
                "hold_time_ms":         exit_time - entry_time if entry_time else 0,
                "exit_reason":          exit_reason,
                "model_name":           model_name,
                "source":               fill.get("source", ""),
                "calc_id":              close_calc_id,
                "lifecycle_id":         close_lifecycle_id,
                "cumulative_amendment_count": cumulative_amendment_count,
                # 2026-06-15: sticky "TP/SL amended/removed during life" for the
                # Position-History Plan badge. Severity (2026-06-20): 1 = amended
                # (yellow), 2 = SL removed → unprotected (red), None = never
                # amended. Only linked positions enter the stash (drift_check's
                # TP/SL compare runs only with a calc), so this is linked-only.
                "tpsl_amended": (self._tpsl_amended_seen.get(pos_id) or None),
                # P6.T7: realized liquidation execution price on a forced-liq
                # close (NULL otherwise; = the liquidation-fill VWAP, computed
                # above). bankruptcy_px / insurance_fund_fee / adl_indicator stay
                # schema-NULL (no venue-event source today).
                "liquidation_px":       liquidation_px,
                **shortfall,
                **deltas,
            }))

            # prune the sticky amended flag once the position is fully closed —
            # it has now been persisted onto the final closed_positions row.
            if is_final and pos_id:
                self._tpsl_amended_seen.pop(pos_id, None)

            await event_bus.publish("risk:position_closed", {
                "symbol": symbol, "direction": direction,
                "realized_pnl": realized_pnl, "net_pnl": net_pnl,
            })

            # P6.T2 (spec §9 position:closed FULL payload): the per-account topic
            # carries the complete close context for external models (Phase 7).
            # FINAL-close only (is_final) — a "position:closed" means the position
            # is flat; per-partial rungs already emit position:partial_close. This
            # is the key difference from the flat risk:position_closed above, which
            # is KEPT unconditionally for the existing reconciler subscriber (it
            # reconciles per-partial closed_positions rows) as a compat shim
            # (emit both; deprecate the flat one once subscribers migrate, §11).
            # Documented payload limits (match the data available at close):
            #   - model_names = [primary's model_name] — model_name is sourced by
            #     symbol+entry-window, not the primary calc (T234 known limit);
            #   - model_tags / hold_time_planned_ms / close_note have no source today;
            #   - mfe/mae are reconciler-computed AFTER close → None here (a
            #     subscriber reads the closed_positions row for the finalized pair).
            #   - lifecycle_id is an ADDITIVE §3.5 correlation key (the §9 example
            #     JSON omits it, but §3.5 surfaces lifecycle_id on all position:*
            #     events — intentional, not a leak).
            #   - funding_fees/net_pnl are AS-OF-CLOSE: the deferred-funding
            #     reconcile (task 259) may revise them in closed_positions after
            #     this event (same post-close mutability as mfe/mae) — the
            #     closed_positions row is the authoritative finalized value.
            try:
                if is_final and close_row_is_new:
                    await event_bus.publish_engine(
                        account_id, DOMAIN_POSITION, "closed", {
                            "position_id":                pos_id,
                            "symbol":                     symbol,
                            "direction":                  direction,
                            "contributing_calc_ids":      sorted(contributing_calc_ids),
                            "primary_calc_id":            close_calc_id,
                            "lifecycle_id":               close_lifecycle_id,
                            "model_names":                [model_name] if model_name else [],
                            "model_tags":                 [],
                            "open_ts_ms":                 entry_time,
                            "close_ts_ms":                exit_time,
                            "hold_time_actual_ms":        exit_time - entry_time if entry_time else 0,
                            "hold_time_planned_ms":       None,
                            "avg_entry_px":               entry_price,
                            "avg_exit_px":                exit_price,
                            "realized_pnl":               realized_pnl,
                            "total_fees":                 total_fees,
                            "funding_fees":               funding_fees,
                            "net_pnl":                    net_pnl,
                            # §9 deltas sub-object = exactly the 7 delta keys.
                            # The close-ROW `deltas` dict also carries
                            # hold_time_actual_ms, which §9 places at the payload
                            # TOP level (emitted above) — drop it from the nested
                            # block so the shape matches §9 (the **deltas spread
                            # into the closed_positions ROW still keeps the column).
                            "deltas": {
                                k: v for k, v in deltas.items()
                                if k != "hold_time_actual_ms"
                            },
                            "exit_reason":                exit_reason,
                            "was_manually_closed":        str(exit_reason).startswith("MANUAL"),
                            "close_note":                 None,
                            "cumulative_amendment_count": cumulative_amendment_count,
                            "mfe":                        None,  # reconciler post-close
                            "mae":                        None,
                        },
                    )
            except Exception:
                log.debug("position:closed event_bus emit failed", exc_info=True)

            # P6.T7 (spec §9 position:liquidated): a DEDICATED event for a forced
            # liquidation, fired ALONGSIDE position:closed (the general close
            # context) when the FINAL close was a liquidation. liquidation_px =
            # the realized close-fill execution price; bankruptcy_px /
            # insurance_fund_fee / adl_indicator have NO venue-event source today
            # (NULL — ingesting venue liquidation events is a separate "venue
            # status signals" task). Detection: a close order whose order_type is
            # "liquidation" (the Binance forced-liq fallback) → exit_reason=LIQUIDATION.
            try:
                if is_final and close_row_is_new and exit_reason == "LIQUIDATION":
                    await event_bus.publish_engine(
                        account_id, DOMAIN_POSITION, "liquidated", {
                            "position_id":        pos_id,
                            "liquidation_px":     liquidation_px,
                            "bankruptcy_px":      None,
                            "insurance_fund_fee": None,
                            "adl_indicator":      None,
                        },
                    )
            except Exception:
                log.debug("position:liquidated event_bus emit failed", exc_info=True)

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

            # R4 (reconciler seal-at-close, LB-F4/LB-I5): seal the
            # position's lifecycles at the FINAL close — the same moment
            # completion fires below — so the owner's mint/reuse lookup
            # ignores this trade if the venue ever reuses the tpid slot.
            # Partial rungs never reach here (is_final gate); sealed_ts =
            # this row's exit_time_ms (data-derived, idempotent re-run).
            # R4 audit M3 — EVIDENCE GATE: the `total_open_qty <= 0`
            # degraded lane (opens unresolvable — walk failure / stranded
            # tpids) sets is_final=True as a completion FALLBACK, so a
            # PARTIAL close there would wrongly seal a live position and
            # split its lifecycle on the next scale-in. Seal only when
            # finality is evidence-backed: real qty accounting
            # (total_open_qty > 0 → is_final came from Σclose ≥ Σopen) or
            # authoritative disappearance (force_final). The degraded
            # lane still seals at authoritative close via the
            # build_final_close_row backstop (audit M1 fold).
            if is_final and pos_id and (force_final or total_open_qty > 0):
                await self._identity.seal_position_lifecycles(
                    account_id, pos_id, exit_time, symbol=symbol,
                )

            # T221 (P1.T6) + T2.11: auto-complete contributing calcs ONLY on
            # the FINAL close (size→0). Pre-T2.11 this ran on every close-row
            # build, so a multi-TP ladder completed the calc prematurely on
            # the first partial (subsequent partials no-op'd via the status
            # guard). Now partial closes leave the calc matched /
            # partially_actioned and completion fires once, at full close.
            # Single-close positions are final immediately → behavior
            # unchanged for the common case. Contributing-calc set = distinct
            # calc_ids across the opening fills. Runs AFTER the close row +
            # events are persisted so a completion failure can't undo the
            # close. Best-effort.
            if is_final and contributing_calc_ids:
                await self._complete_calcs_on_close(
                    account_id, contributing_calc_ids, pos_id,
                )

            log.info(
                "Closed position row: %s %s qty=%.4f pnl=%.2f exit=%s",
                symbol, direction, total_close_qty, realized_pnl, exit_reason,
            )
        except Exception as e:
            _trace["error_type"] = type(e).__name__
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
        finally:
            # corr-tap: attr_close_build (CL.T3b-close, spec §5.6 mandate 1)
            # — exactly one envelope per invocation, whatever path exited.
            _fid = str(fill.get("exchange_fill_id") or "")
            if "error_type" in _trace:
                _outcome, _reason = "ERROR", None
            elif _trace.get("skip"):
                _outcome, _reason = "SKIPPED", _trace["skip"]
            elif _trace.get("row_written"):
                _outcome, _reason = "WRITTEN", None
            elif "row_written" in _trace:
                # the insert reported False (pollution-reject or swallowed
                # write failure) — the historical "close row NOT written"
                _outcome, _reason = "ERROR", "row_write_failed"
            else:
                _outcome, _reason = "ERROR", "build_incomplete"
            _cb: Dict[str, Any] = {
                "outcome": _outcome,
                "strict_key": _trace.get("strict_key", ""),
                "opens_found_strict": _trace.get("opens_found_strict"),
                "walk_used": _trace.get("walk_used", False),
                "opens_found_walk": _trace.get("opens_found_walk"),
                "open_fill_tpids": _trace.get("open_fill_tpids"),
                "backfilled": _trace.get("backfilled", 0),
                "entry_source": _trace.get("entry_source"),
                "n_close_fills": _trace.get("n_close_fills"),
                "is_final": _trace.get("is_final"),
                "force_final": force_final,
                "exit_reason": _trace.get("exit_reason"),
                "row_written": bool(_trace.get("row_written", False)),
                "close_row_is_new": _trace.get("close_row_is_new"),
                # identity tuple VERBATIM incl. "" (mandate 2)
                "terminal_position_id": _trace.get("strict_key", ""),
                "calc_id": _trace.get("calc_id", ""),
                "lifecycle_id": _trace.get("lifecycle_id", ""),
                "exchange_order_id": str(fill.get("exchange_order_id") or ""),
            }
            if _reason:
                _cb["reason"] = _reason
            if "error_type" in _trace:
                _cb["error_type"] = _trace["error_type"]
            if _fid:
                _cb["dedup_key"] = f"close:{_fid}"
            correlation_log.emit(
                "order_manager", "internal", "internal",
                correlation_log.CAT_ATTR_CLOSE_BUILD, _cb,
                account_id=account_id,
                symbol=fill.get("symbol", fill.get("ticker", "")) or None,
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
            if unrecorded:
                # Group by exchange_order_id → one closed_positions row per order
                groups: Dict[str, List[Dict]] = {}
                for f in unrecorded:
                    key = f.get("exchange_order_id", "") or f"_fill_{f.get('id', '')}"
                    groups.setdefault(key, []).append(f)

                for _order_id, fills in groups.items():
                    # Position has fully disappeared from the snapshot → these
                    # closing fills are the FINAL close (T2.11 force_final).
                    await self._build_close_row_for_fill(
                        account_id, fills[0], force_final=True,
                    )

                log.info(
                    "Final close safety net: %d group(s) for %s %s",
                    len(groups), prev.ticker, prev.direction,
                )
            else:
                log.debug(
                    "No unrecorded closing fills for %s %s",
                    prev.ticker, prev.direction,
                )

            # R4 audit M1: the recorded-but-never-final lane (unrecorded
            # EMPTY — the exact WS-gap shape this backstop exists for)
            # completes calcs below but previously never SEALED the
            # lifecycles, leaving the LB-F4 reuse hazard open on that
            # lane. Disappearance is the authoritative close → seal here
            # too, evidence-timestamped from the final recorded close row
            # (MAX exit_time_ms — the same final-row convention the
            # funding reconcile uses), falling back to the newest
            # recorded closing fill. No close evidence at all → skip the
            # seal (no timestamp to stamp; completion below still runs).
            # Idempotent vs the force_final builds above (WHERE sealed_ts
            # IS NULL) and vs re-entry.
            if prev.position_id:
                seal_ts = None
                try:
                    async with self._db._conn.execute(
                        "SELECT MAX(exit_time_ms) FROM closed_positions "
                        "WHERE account_id = ? AND terminal_position_id = ?",
                        (account_id, prev.position_id),
                    ) as cur:
                        row = await cur.fetchone()
                    seal_ts = row[0] if row and row[0] else None
                    if not seal_ts:
                        async with self._db._conn.execute(
                            "SELECT MAX(timestamp_ms) FROM fills "
                            "WHERE account_id = ? "
                            "  AND terminal_position_id = ? "
                            "  AND is_close = 1",
                            (account_id, prev.position_id),
                        ) as cur:
                            row = await cur.fetchone()
                        seal_ts = row[0] if row and row[0] else None
                except Exception:
                    log.debug(
                        "backstop seal-ts read failed for %s",
                        prev.position_id, exc_info=True,
                    )
                if seal_ts:
                    await self._identity.seal_position_lifecycles(
                        account_id, prev.position_id, int(seal_ts),
                        symbol=prev.ticker,
                    )

            # T2.11 (T238 review F1, HIGH): the position has DISAPPEARED from
            # the snapshot — authoritatively closed. The per-fill deferred
            # close builds gate calc completion on is_final (Σclose ≥ Σopen);
            # a missed / under-counted closing fill (WS gap) could leave that
            # sum permanently short, stranding contributing calcs in
            # `matched`. The unrecorded-rebuild above only covers UNRECORDED
            # fills — a recorded-but-never-final position would never
            # complete. Force-complete contributing calcs here regardless;
            # disappearance is the authoritative close signal. Idempotent
            # (status-guarded in _complete_calcs_on_close).
            #
            await self._complete_position_calcs(account_id, prev.position_id)

            # P6 deferred-funding reconcile (was a filed P5 gap): funding rides
            # on is_final in a BUILT close row, so a recorded-but-never-final
            # position (WS-gap: Σclose < Σopen, is_final never fires) leaves the
            # final row's funding_fees stamped 0 despite preserved funding_events
            # rows. Disappearance is the authoritative close → recompute
            # funding_fees/net_pnl from the SUM on the position's final close row.
            # Idempotent (recompute from SUM → identical when already-final
            # stamped it); no-op for empty-tpid / no-funding. Best-effort: a
            # reconcile fault must not break the disappearance backstop.
            try:
                await self._db.reconcile_closed_position_funding(
                    account_id, prev.position_id,
                )
            except Exception:
                log.debug(
                    "deferred-funding reconcile (backstop) failed for %s",
                    prev.position_id, exc_info=True,
                )
        except Exception:
            log.exception(
                "build_final_close_row failed for %s %s",
                prev.ticker, prev.direction,
            )

    async def _complete_position_calcs(
        self, account_id: int, position_id: str,
    ) -> None:
        """T2.11 backstop (T238 review F1): force-complete a fully-closed
        position's contributing calcs.

        Called from :meth:`build_final_close_row` when the position has
        disappeared from the snapshot. Gathers contributing calc_ids from
        the ``positions_calcs`` junction (Phase-2 source of truth), falling
        back to the distinct ``calc_id`` across the position's OPENING fills
        when there is no junction (UNPLANNED / pre-Phase-2). Delegates to
        :meth:`_complete_calcs_on_close`, which is status-guarded
        (matched / partially_actioned → completed_via_position) and
        idempotent, so re-running after the per-fill builds already completed
        is a safe no-op. Empty ``position_id`` (binance one-way) → no-op:
        that path completes via the per-fill is_final=True fallback instead.
        """
        if not position_id:
            return
        calc_ids: set = set()
        try:
            async with self._db._conn.execute(
                "SELECT DISTINCT calc_id FROM positions_calcs "
                "WHERE position_id = ? AND account_id = ? "
                "  AND calc_id IS NOT NULL",
                (position_id, account_id),
            ) as cur:
                calc_ids = {r[0] for r in await cur.fetchall() if r[0]}
            if not calc_ids:
                async with self._db._conn.execute(
                    "SELECT DISTINCT calc_id FROM fills "
                    "WHERE terminal_position_id = ? AND account_id = ? "
                    "  AND is_close = 0 AND calc_id IS NOT NULL",
                    (position_id, account_id),
                ) as cur:
                    calc_ids = {r[0] for r in await cur.fetchall() if r[0]}
        except Exception:
            log.debug(
                "force-complete: calc_id gather failed for %s", position_id,
                exc_info=True,
            )
            return
        if calc_ids:
            await self._complete_calcs_on_close(account_id, calc_ids, position_id)

    # ── Helpers ─────────────────────────────────────────────────────────────

    async def _determine_exit_reason(
        self, account_id: int, exchange_order_id: str
    ) -> str:
        """Derive the spec §3.4 exit_reason enum from the close order's type.

        T2.7 (plan §2 task 2.7): the forward close path now emits the
        canonical §3.4 enum (was legacy tp_hit/sl_hit/manual/limit_close/
        trailing_stop), aligning new rows with the §3.4 values the P0.T5
        backfill already applied to historical rows. Mapping mirrors that
        backfill's EXIT_REASON_REMAP (tp→TP_PLANNED, sl→SL_PLANNED,
        manual/none→MANUAL_OTHER):
          - take_profit*           → TP_PLANNED
          - trailing*, stop_loss*, stop → SL_PLANNED
          - market / limit / none / not-found → MANUAL_OTHER

        Always the *_PLANNED variant (never *_AMENDED). The AMENDED
        distinction is DEFERRED to Phase 4: spec §3.4 keys it on
        ``cumulative_amendment_count > 0`` (Phase 4.3, populated from the
        Phase-4.1 ws_manager amendment writer that is unwired today) AND a
        plan-vs-final-TP/SL price difference (Phase 4.6) — and the final
        amended TP/SL isn't reliably knowable at close (the close order
        exposes only the single triggered level; the same data-availability
        reason T2.5 deferred tp_drift/sl_drift). Re-classifying *_PLANNED →
        *_AMENDED is a Phase-4 re-derivation on the idempotent close-row
        rebuild seam.

        Deviations (deviation discipline): ``trailing`` has no §3.4 enum —
        a trailing stop is mechanically an SL, so it collapses to
        SL_PLANNED. ``limit_close`` likewise has no enum — an operator
        limit close is operator-initiated → MANUAL_OTHER (the finer
        MANUAL_* subtypes need operator close-note input; LIQUIDATION/ADL
        need venue status signals; EXPIRED needs the cancel-category map —
        all out of T2.7 scope, routed to the closest available enum here).
        """
        if not exchange_order_id:
            return "MANUAL_OTHER"
        order = await self._db.get_order_by_exchange_id(
            account_id, exchange_order_id,
        )
        if not order:
            return "MANUAL_OTHER"
        # order_type is canonically lowercased at every adapter ingest
        # point today; .lower() here hardens against a future adapter that
        # forgets and keeps this consistent with _classify_final_exit_reason
        # (P2 audit follow-up, 2026-05-29).
        otype = (order.get("order_type", "") or "").lower()
        # P6.T7: a forced-liquidation close. Binance sends order type "LIQUIDATION"
        # (not in ORDER_TYPE_FROM_BINANCE → the adapter's otype.lower() fallback
        # yields "liquidation"). Highest priority — a liquidation is neither a
        # planned TP nor SL. (bankruptcy_px / insurance_fund_fee / adl_indicator
        # need venue liquidation-event ingestion, not done — see position:liquidated.)
        if "liquidation" in otype:
            return "LIQUIDATION"
        if "take_profit" in otype:
            return "TP_PLANNED"
        if "trailing" in otype:
            return "SL_PLANNED"   # trailing stop is mechanically an SL
        if "stop_loss" in otype or "stop" in otype:
            return "SL_PLANNED"
        # market / limit / manual / anything else → operator-initiated close
        return "MANUAL_OTHER"

    async def _classify_final_exit_reason(
        self, account_id: int, pos_id: str, *, fallback: str,
    ) -> str:
        """T2.11 (spec §3.4 / §8): ladder-aware exit_reason for a FINAL close.

        Inspects the parent order types of ALL closing fills for the
        position (distinct closing orders), and returns:
          - ``TP_LADDER_COMPLETE`` — ≥2 distinct take_profit closing orders
            and NO stop/manual closing order (a multi-TP ladder that ran to
            completion via TPs, spec §8);
          - ``MIXED`` — at least one take_profit AND at least one non-TP
            (SL / trailing / manual) closing order (a TP ladder finished off
            by an SL hit or an operator manual close, spec §8);
          - ``fallback`` otherwise — a single closing order (or all-SL /
            all-manual), which keeps the per-order classification from
            :meth:`_determine_exit_reason` (TP_PLANNED / SL_PLANNED /
            MANUAL_OTHER).

        Empty ``pos_id`` (binance one-way / no terminal_position_id) → the
        join finds nothing → ``fallback`` (the per-order reason), so that
        path is unchanged. Best-effort: any read failure → ``fallback``.

        Known limitation (T238 review F5, LOW): the INNER JOIN drops a
        closing fill whose ``orders`` row is missing (close fill arrived,
        order record absent), which can downgrade a real ladder to the
        single-TP fallback. Orders rows are normally upserted on arrival, so
        this is a rare graceful-degradation edge, not data loss.
        """
        if not pos_id:
            return fallback
        try:
            async with self._db._conn.execute(
                "SELECT DISTINCT f.exchange_order_id, o.order_type "
                "FROM fills f "
                "JOIN orders o ON o.account_id = f.account_id "
                "  AND o.exchange_order_id = f.exchange_order_id "
                "WHERE f.account_id = ? AND f.terminal_position_id = ? "
                "  AND f.is_close = 1",
                (account_id, pos_id),
            ) as cur:
                rows = await cur.fetchall()
        except Exception:
            log.debug(
                "final exit_reason classify read failed for pos %s", pos_id,
                exc_info=True,
            )
            return fallback
        if not rows:
            return fallback
        tp_orders, non_tp_orders = [], []
        liq_present = False
        for eoid, otype in rows:
            ot = (otype or "").lower()
            if "liquidation" in ot:
                liq_present = True
            (tp_orders if "take_profit" in ot else non_tp_orders).append(eoid)
        # P6.T7: a liquidation DOMINATES the ladder classification — if any
        # closing order was a forced liquidation, the position was liquidated
        # (even if earlier TP rungs hit first), so the close reads LIQUIDATION
        # rather than MIXED/TP_LADDER_COMPLETE.
        if liq_present:
            return "LIQUIDATION"
        if tp_orders and non_tp_orders:
            return "MIXED"
        if len(tp_orders) >= 2:
            return "TP_LADDER_COMPLETE"
        return fallback

    async def _liquidation_vwap(
        self, account_id: int, pos_id: str,
    ) -> Optional[float]:
        """P6.T7: VWAP of the position's LIQUIDATION close fills — the realized
        forced-liquidation execution price.

        Order-scope-independent: sources the price from the fills of the
        liquidation closing order(s) (``order_type`` containing ``liquidation``),
        so it stays correct even when a partial liquidation precedes a
        non-liquidation final close (where this row's ``exit_price`` would be the
        non-liq order's VWAP). Returns ``None`` when there's no ``pos_id``
        (binance one-way empty-tpid — the caller falls back to this close's
        ``exit_price``, which IS the liquidation on that single-close path) or no
        liquidation fills are found. Best-effort.
        """
        if not pos_id:
            return None
        try:
            async with self._db._conn.execute(
                "SELECT f.price, f.quantity FROM fills f "
                "JOIN orders o ON o.account_id = f.account_id "
                "  AND o.exchange_order_id = f.exchange_order_id "
                "WHERE f.account_id = ? AND f.terminal_position_id = ? "
                "  AND f.is_close = 1 AND LOWER(o.order_type) LIKE '%liquidation%'",
                (account_id, pos_id),
            ) as cur:
                rows = await cur.fetchall()
        except Exception:
            log.debug("liquidation VWAP read failed for pos %s", pos_id, exc_info=True)
            return None
        tot_qty = sum(abs(float(q or 0)) for _, q in rows)
        if tot_qty <= 0:
            return None
        return sum(
            float(p or 0) * abs(float(q or 0)) for p, q in rows
        ) / tot_qty

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

        Computes the deltas derivable from data available at close, all
        stored RAW/signed per the literal §3.2 formulas (``realized_r`` is
        direction-agnostic as written — a SHORT flips both numerator and
        denominator; the ``*_delta_pct``/``*_drift_pct`` are price deltas
        whose better/worse reading is a display concern):
          entry_px_delta_pct, size_delta_pct, exit_vs_target_pct,
          realized_r, planned_r, hold_time_actual_ms,
          tp_drift_pct, sl_drift_pct (P4.T5).

        Every key is omitted (→ stays NULL via the nullable column) when
        its planned denominator is missing/zero (and the drift keys also
        when the leg was never amended — see below). Best-effort: any read
        failure or absent junction (UNPLANNED / binance empty-tpid)
        returns ``{}`` so the close-row write never blocks.

        Deliberately NOT computed here (left NULL until their owning task):
          - ``hold_time_planned_ms`` → no planned-duration column exists in
            ``pre_trade_log`` or the junction.

        ``cumulative_amendment_count`` is NOT returned here either, but it IS
        computed at close — P4.T2 supplies it directly in
        ``_build_close_row_for_fill`` via ``count_amendments_for_calcs`` (kept
        out of this return so the explicit value isn't overridden by the
        ``**deltas`` spread).
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

            # tp_drift_pct / sl_drift_pct (P4.T5, spec §3.2 + plan §4.6): the
            # FINAL AMENDED TP/SL trigger vs the primary calc's planned value.
            # "Final" = the latest order_amendments.new_value for that field on
            # the primary calc's legs AS OF this close's exit_time — the orders
            # row goes stale post-amendment (the SR-1 gate rejects the amend
            # upsert), so the amendment ledger is authoritative (P4.T1).
            # **ts_ms <= exit_time** (P4-CLOSE-001): for a multi-TP partial close
            # (T2.11, per-rung rows, recomputed each build / on a REPLACE) an
            # amendment that post-dates an earlier rung's close must NOT corrupt
            # that rung's as-of drift — mirrors the is_final closing-fill
            # timestamp cut. Scoped to the PRIMARY calc (same §3.2 basis as
            # planned_tp/sl). NULL when the leg was never amended (drift is
            # populated only for an AMENDED stop — the plan §4 criterion).
            # Documented approximations (own-task refinements, not bugs):
            #   - scale-in protective leg inherited under a NON-primary calc_id
            #     (T2.9 earliest-entry pick) stays NULL on this basis;
            #   - multi-TP ladder (SPEC-001): planned_tp is the single junction
            #     snapshot while final_tp is last-wins across the primary calc's
            #     TP legs, so the compared rung may differ (exact for the common
            #     single-TP/SL case). See test_multi_tp_scenario.txt.
            final_tp = final_sl = None
            try:
                last_amend: Dict[str, Any] = {}
                for a in await self._db.get_calc_amendments(primary_calc_id):
                    if int(a.get("ts_ms", 0) or 0) <= exit_time:
                        last_amend[a["field"]] = a["new_value"]
                final_tp = last_amend.get("tp_price")
                final_sl = last_amend.get("sl_price")
            except Exception:
                pass
            if planned_tp and final_tp is not None:
                out["tp_drift_pct"] = round(
                    (final_tp - planned_tp) / planned_tp * 100, 4)
            if planned_sl and final_sl is not None:
                out["sl_drift_pct"] = round(
                    (final_sl - planned_sl) / planned_sl * 100, 4)

            if entry_time:
                out["hold_time_actual_ms"] = exit_time - entry_time

            return out
        except Exception:
            # Best-effort: ANY failure (read OR arithmetic) yields no deltas —
            # the close-row write must never be blocked by this enrichment.
            log.debug("close-deltas failed for %s", pos_id, exc_info=True)
            return {}
