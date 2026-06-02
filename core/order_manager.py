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
from core.state import app_state, PositionInfo, deviation_badge_level

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


def _most_contributing_calc_id(
    ordered_rows: List[Tuple[str, float]],
) -> Optional[str]:
    """Spec §3.2 / §12.4 "most-contributing calc": the ``calc_id`` with the
    largest **summed** ``contributed_qty`` across its junction rows.

    A calc may place >1 opening order on a position, and the junction is
    keyed ``UNIQUE(position_id, calc_id, order_id)`` — so one calc can own
    multiple rows for the same position. The spec defines contribution at
    the CALC level (§12.4: junction ``contributed_qty = SUM(fill_qty)``
    grouped by ``(position lifecycle, calc_id)``), so the primary must be
    chosen by the per-calc SUM, not the largest single row.

    ``ordered_rows`` is an iterable of ``(calc_id, contributed_qty)`` that
    MUST already be sorted by ``first_fill_ts ASC`` — dict insertion order
    then encodes the earliest-first_fill tie-break, and ``max`` returns the
    first maximal element, so ties resolve to the earliest calc (§3.2).
    Returns ``None`` when there are no calc-bearing rows.

    T240 (P2.T12 review): the single source of truth for the §3.2 selection
    rule, shared by :meth:`OrderManager._position_primary_calc` (close-path
    T2.2/T2.5/T2.6) and :meth:`OrderManager._enrich_positions_calc_id`
    (live + rehydrate T2.3/T2.12) so ALL surfaces converge (R1). Before
    T240 the two implemented the rule separately — ``_position_primary_calc``
    took the max single ROW (not per-calc summed), so a multi-order calc
    could be mis-ranked, diverging the live PositionInfo.calc_id from the
    sealed closed_positions.calc_id for the same position.
    """
    per_calc: Dict[str, float] = {}
    for cid, qty in ordered_rows:
        if not cid:
            continue
        per_calc[cid] = per_calc.get(cid, 0.0) + (qty or 0.0)
    if not per_calc:
        return None
    return max(per_calc.items(), key=lambda kv: kv[1])[0]


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
        # T2.9 (spec §4.5): propagate a matched entry's calc_id onto its
        # bracket TP/SL siblings. Runs AFTER enrichment so the entry's
        # calc_id is committed when this reads it; idempotent + best-effort.
        await self._propagate_bracket_calc_id(account_id, order.get("symbol") or "")
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
        if not symbol:
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
                return

            # Cheap pre-checks: need ≥1 entry-with-calc_id AND ≥1
            # protective-without-calc_id, else there is nothing to inherit.
            if not any(is_entry_leg(o) and o.get("calc_id") for o in candidates):
                return
            if not any(is_protective_leg(o) and not o.get("calc_id")
                       for o in candidates):
                return

            updates: List[Tuple[str, int]] = []
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
                    updates.append((src_calc, leg["id"]))

            if not updates:
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

            for src_calc, oid in updates:
                async def _apply_leg(src_calc=src_calc, oid=oid) -> None:
                    cur = await self._db._conn.execute(
                        "UPDATE orders SET calc_id = ?, link_status = ? "
                        "WHERE id = ? AND calc_id IS NULL",
                        (src_calc, LinkStatus.LINKED.value, oid),
                    )
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
            await self._db._conn.commit()
            log.info(
                "T2.9 bracket inheritance: stamped calc_id on %d TP/SL leg(s) "
                "for %s", len(updates), symbol,
            )
        except Exception:
            log.debug(
                "bracket calc_id propagation skipped for %s", symbol,
                exc_info=True,
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
                    "operator_id":   None,  # Phase 9 (operator session)
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
                    )

    def _emit_amendment_event(
        self, account_id: int, *, order_id: int, calc_id: Optional[str],
        position_id: str, field: str, old: float, new: float, ts_ms: int,
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
        is Phase 9. The formal §9 in-process ``event_bus`` topic is Phase 6
        (plan §6 row 6.4) — same trade-event-now / event_bus-later split as
        ``partial_close`` / ``position_opened``. Best-effort: an emission fault
        never blocks amendment persistence.

        Dispatched via ``asyncio.to_thread`` by the caller (the sync
        ``log_trade_event`` opens its own sqlite3 conn — T212/P3.T2 hot-path
        convention). NB the sibling :meth:`_emit_fill_events` predates that
        convention and is still called sync — same exposure, filed as a
        separate consistency cleanup, not retrofitted here (Rule 3).
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
                "operator_id": None,  # Phase 9 (operator session)
            }, source="order_manager")
        except Exception:
            log.debug("position_amended event emission failed", exc_info=True)

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
                            # T2.11 (spec §8/§9 position:partial_close payload):
                            # carry qty_reduced + realized_pnl_partial so the
                            # multi-TP ladder is reconstructable from the event
                            # stream. tp_level_idx is omitted — mapping a TP
                            # fill to its tp_levels rung needs calc.tp_levels
                            # parsing + price matching (deferred; not load-
                            # bearing for the ladder lifecycle).
                            log_trade_event(account_id, calc_id, "partial_close", {
                                "symbol": fill.get("symbol", ""),
                                "position_id": pos_id,
                                "fill_price": fill.get("price", 0),
                                "fill_qty": fill.get("quantity", 0),
                                "qty_reduced": fill.get("quantity", 0),
                                "remaining_qty": pos.contract_amount,
                                "realized_pnl_partial": fill.get("realized_pnl", 0),
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
        # Rows ordered by first_fill_ts ASC. Primary = the calc with the
        # largest SUMMED contributed_qty (spec §3.2/§12.4 per-CALC, not the
        # largest single row), tie-break earliest first_fill — via the shared
        # _most_contributing_calc_id helper so this (close-path) and
        # _enrich_positions_calc_id (live/rehydrate) cannot diverge (T240/R1).
        primary_cid = _most_contributing_calc_id([(r[0], r[2]) for r in links])
        if primary_cid is None:
            return None, None
        # lifecycle_id is shared across a position's junction rows; prefer the
        # primary calc's, fall back to any non-null.
        lifecycle_id = (
            next((r[1] for r in links if r[0] == primary_cid and r[1]), None)
            or next((r[1] for r in links if r[1]), None)
        )
        return primary_cid, lifecycle_id

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
        if not any(p.position_id for p in positions):
            return
        try:
            async with self._db._conn.execute(
                "SELECT position_id, calc_id, contributed_qty, planned_size "
                "FROM positions_calcs WHERE account_id = ? "
                "ORDER BY first_fill_ts ASC, id ASC",
                (account_id,),
            ) as cur:
                rows = await cur.fetchall()
        except Exception:
            # Read failed — leave fields untouched (don't clear on error).
            log.debug("calc_id enrichment: junction read failed", exc_info=True)
            return
        # Aggregate per (position, calc): sum contributed_qty (a calc may
        # place >1 order on a position → multiple junction rows) and carry
        # the calc's planned_size snapshot. Rows arrive ordered by
        # first_fill_ts ASC, and dict preserves insertion order, so a calc's
        # first appearance fixes its tie-break rank (earliest first_fill).
        per_pos: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for pid, cid, qty, planned in rows:
            if not pid or not cid:
                continue
            calcs = per_pos.setdefault(pid, {})
            agg = calcs.get(cid)
            if agg is None:
                agg = {"qty": 0.0, "planned": None}
                calcs[cid] = agg
            agg["qty"] += (qty or 0.0)
            if agg["planned"] is None and planned:
                agg["planned"] = planned

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
            # P4 audit (P4T3-001): the config read and the amendment count are
            # SEPARATE failure modes — a single shared try would let a config
            # failure skip the amendment count (and vice versa). Config first
            # (defaults already set, so a failure can't strand red_pct=0). The
            # amendment-count failure is logged at WARNING, not debug: it masks
            # live amendments for THIS refresh (a real amended position paints
            # green), so it must be diagnosable. Self-heals on the next
            # successful refresh (the badge is htmx-polled) — bounded, transient.
            try:
                cfg = await read_account_config_async(self._db, account_id)
                yellow_pct, red_pct = cfg.yellow_deviation_pct, cfg.red_deviation_pct
            except Exception:
                log.debug("deviation-badge config read failed", exc_info=True)
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
            if not pos.position_id:
                continue  # binance one-way / pre-snapshot — no junction key
            calcs = per_pos.get(pos.position_id)
            if not calcs:
                pos.calc_id = ""
                pos.contributing_calc_ids = []
                pos.size_delta_pct = 0.0
                pos.amendment_count = 0
                pos.deviation_badge = "red"  # no-calc / UNPLANNED (spec §10.2)
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
            pos.deviation_badge = deviation_badge_level(
                has_calc=True, size_delta_pct=pos.size_delta_pct,
                amendment_count=pos.amendment_count,
                yellow_pct=yellow_pct, red_pct=red_pct,
            )

    # ── Position Close ─────────────────────────────────────────────────────

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
                "cumulative_amendment_count": cumulative_amendment_count,
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
            await self._complete_position_calcs(account_id, prev.position_id)
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
        for eoid, otype in rows:
            (tp_orders if "take_profit" in (otype or "").lower()
             else non_tp_orders).append(eoid)
        if tp_orders and non_tp_orders:
            return "MIXED"
        if len(tp_orders) >= 2:
            return "TP_LADDER_COMPLETE"
        return fallback

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
