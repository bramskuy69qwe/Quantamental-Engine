"""Position identity owner — attribution reconciler R1 (pure extraction).

Program doc: ``docs/design/attribution_reconciler_plan.md`` (rev 2). R1
MOVES the OrderManager-hosted identity sites here VERBATIM — no behavior
change; rules, gates, corr-taps, and failure semantics are byte-for-byte
the order_manager.py originals @ ``02eb743`` except:

- corr envelopes emitted from moved code carry
  ``component="position_identity"`` (plan §2.3 — allowed in R1, spec §3
  component-set erratum E36 lands at R5; verified no tooling or test
  filters on these categories' component),
- the HA-28 SKIP-dedup memo is SPLIT (plan §4-R1 named friction): this
  module owns the memo for the replay tap; OrderManager keeps its own for
  the bracket-inheritance tap,
- the ``position:opened``/``scale_in`` event emissions MOVE WITH the
  junction builder (plan §3 row offered contract-return OR events-move,
  "decide at R1": decided events-move, BECAUSE the Defect-8 replay lane
  also reaches the builder and historically emitted these events through
  it — a contract-return would have silently dropped events on the
  replay lane, a behavior change R1 forbids).

R1 deliberate carry (plan §4-R1 anchor): identity reads/writes use
``db._conn`` directly, verbatim from order_manager — the Phase-6
public-helper convention is deferred to a later phase so R1 stays a pure
move (routing through helpers would be a behavior-relevant refactor of
commit/transaction boundaries).

Later phases (R2 canonical key / R3 retro-reconcile / R4 seal+coherence)
change decisions ONLY where a battery-ledger finding says so, each
flipping a named strict-xfail in ``tests/test_linkage_battery_*``.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core import correlation_log
from core.event_bus import event_bus, DOMAIN_POSITION

log = logging.getLogger("position_identity")


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
    rule, shared by :meth:`PositionIdentity.position_primary_calc`
    (close-path T2.2/T2.5/T2.6) and
    :meth:`OrderManager._enrich_positions_calc_id` (live + rehydrate
    T2.3/T2.12) so ALL surfaces converge (R1). Before T240 the two
    implemented the rule separately — the primary-calc read took the max
    single ROW (not per-calc summed), so a multi-order calc could be
    mis-ranked, diverging the live PositionInfo.calc_id from the sealed
    closed_positions.calc_id for the same position.
    """
    per_calc: Dict[str, float] = {}
    for cid, qty in ordered_rows:
        if not cid:
            continue
        per_calc[cid] = per_calc.get(cid, 0.0) + (qty or 0.0)
    if not per_calc:
        return None
    return max(per_calc.items(), key=lambda kv: kv[1])[0]


class PositionIdentity:
    """ONE owner for fill→position→calc identity (reconciler plan §2).

    R1 = the moved rules verbatim; consumers (OrderManager methods) keep
    their names as thin delegates so the caller/test surface is stable.
    """

    # HA-28 (memo split — plan §4-R1): steady-state no-op SKIPPED replay
    # emits are on-change deduped; actionable outcomes (DELEGATED/FORMED)
    # and ERROR twins stay ungated (repetition there IS the signal).
    # Bounded LRU so a long-running engine can't leak the memo; an
    # eviction at worst re-emits one harmless no-op line later.
    _ATTR_SKIP_MEMO_MAX = 512

    def __init__(self, db) -> None:
        self._db = db

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

    # ── ⑨ close-fill tpid resolution (moved from _resolve_close_tpid) ──

    async def resolve_close_tpid(
        self, account_id: int, fill: Dict[str, Any]
    ) -> str:
        """⑨ (debug 2026-06-08): resolve the terminal_position_id for a CLOSING
        fill that arrived without one (observe-only Binance: the WS trade event
        carries no venue position id, and ws_manager's live-position lookup can
        miss on the full-close race). Tier-0 (LB-F5): the fill's own parent
        order. Then the live ``PositionInfo`` for ``(symbol, direction)`` —
        the position being closed, which carries the minted/snapshot-recovered
        tpid — then the persisted entry order's tpid
        (``get_open_entry_tpids_by_symbol_side``), which survives the
        position's removal from the snapshot. Returns "" when none resolve
        (genuine one-way / unlinked path — behaviour unchanged)."""
        from core.state import app_state

        symbol = fill.get("symbol", fill.get("ticker", "")) or ""
        direction = fill.get("direction", "") or ""

        # corr-tap: attr_tpid_resolve (CL.T3b-close, spec §5.6) — one
        # envelope per invocation, tier NAMED. The ⑨ close-tpid race is
        # exactly "which tier fired and why" — the §4.1 walkthrough's
        # seq-4474 line.
        _fid = str(fill.get("exchange_fill_id") or "")

        def _tap_resolve(outcome: str, tier: str = "", reason: str = "",
                         tpid: str = "", error_type: str = "") -> None:
            payload: Dict[str, Any] = {
                "outcome": outcome,
                "via": "close_fill",
                "symbol": symbol, "direction": direction,
                "terminal_position_id": tpid,
                "calc_id": "", "lifecycle_id": "",
                "exchange_order_id": str(fill.get("exchange_order_id") or ""),
            }
            if tier:
                payload["tier"] = tier
            if reason:
                payload["reason"] = reason
            if error_type:
                payload["error_type"] = error_type
            if _fid:
                payload["dedup_key"] = f"{_fid}:tpid_resolve"
            correlation_log.emit(
                "position_identity", "internal", "internal",
                correlation_log.CAT_ATTR_TPID_RESOLVE, payload,
                account_id=account_id, symbol=symbol or None,
            )

        if not symbol or not direction:
            _tap_resolve("SKIPPED", reason="no_symbol_or_direction")
            return ""
        # 0) LB-F5 (linkage battery 2026-07-15): the fill's OWN parent
        #    order — the strongest identity signal the fill carries
        #    (exchange_order_id → the persisted close order's tpid,
        #    stamped by the close-side Defect-1 twin in
        #    stamp_close_order_tpid, or by recovery/backfill tooling).
        #    Beats the (symbol, direction) heuristics below: on a
        #    same-slot reopen, tier-1 resolves the NEW live instance
        #    while the parent order pins the position this fill actually
        #    closes. Best-effort: any read failure (incl. stub DBs in
        #    tests) falls through to tier-1 with no envelope — only a
        #    genuine resolution emits.
        eoid = str(fill.get("exchange_order_id") or "")
        if eoid:
            parent_tpid = ""
            try:
                # R2 fold of the LB-F5 filed residual (battery plan §5):
                # tier-0 reads ONLY reduce-only parents — exactly what its
                # stamp twin writes — so a Defect-1-stamped NON-reduce-only
                # order (a one-way reversal: closer AND opener) can never
                # tier-0-route a late close leg onto the NEW position's
                # tpid. Costs nothing in the hedge deployment (LB-F5 audit
                # live-DB proof: 63/63 close parents reduce-only).
                async with self._db._conn.execute(
                    "SELECT terminal_position_id FROM orders "
                    "WHERE account_id = ? AND exchange_order_id = ? "
                    "  AND COALESCE(reduce_only, 0) = 1",
                    (account_id, eoid),
                ) as cur:
                    row = await cur.fetchone()
                parent_tpid = (row[0] or "") if row else ""
            except Exception:
                log.debug("close-tpid parent-order read failed for %s",
                          eoid, exc_info=True)
            if parent_tpid:
                _tap_resolve("RESOLVED", tier="parent_order",
                             tpid=parent_tpid)
                return parent_tpid
        # 1) the live position being closed (precise; present during a partial
        #    close and usually still present at full-close fill time).
        for p in app_state.positions:
            if p.ticker == symbol and p.direction == direction and p.position_id:
                _tap_resolve("RESOLVED", tier="live_position",
                             tpid=p.position_id)
                return p.position_id
        # 2) the persisted entry order's minted tpid (survives the position's
        #    removal from the snapshot on a full close).
        try:
            tpid_by_key = await self._db.get_open_entry_tpids_by_symbol_side(
                account_id)
        except Exception as e:
            log.debug("close-tpid order fallback read failed", exc_info=True)
            _tap_resolve("ERROR", tier="entry_order_fallback",
                         reason="fallback_read_failed",
                         error_type=type(e).__name__)
            return ""
        resolved = tpid_by_key.get((symbol, direction), "")
        if resolved:
            _tap_resolve("RESOLVED", tier="entry_order_fallback", tpid=resolved)
        else:
            # the genuine miss — the stranded-close shape stays a LINE
            _tap_resolve("UNRESOLVED", reason="no_match")
        return resolved

    # ── LB-F5 close-order tpid stamp (moved from _process_single_fill) ─

    async def stamp_close_order_tpid(
        self, account_id: int, fill: Dict[str, Any]
    ) -> None:
        """LB-F5 (linkage battery 2026-07-15) — close-side twin of the
        Defect-1 backfill: stamp the CLOSE order's tpid from its first
        tpid-carrying closing fill (whatever the fill carries post-⑨ —
        usually the ws live-position stamp, but a tier-1/2-resolved
        value freezes too; first-fill-time is when those heuristics
        are most reliable). A LATE sibling fill of the same close order —
        the position gone from the snapshot, the slot possibly reopened by
        a new position — then resolves via ⑨ tier-0 (parent_order)
        instead of the (symbol, direction) heuristics that pick the
        wrong instance. Same copy-rule as Defect-1: fill → parent order,
        empty-only guard, never a re-derivation.
        REDUCE-ONLY gate (battery LB-T2a caught the leak pre-commit):
        a one-way REVERSAL order is BOTH the old position's closer and
        the new one's opener — stamping it from the close leg would
        hand the OLD tpid to the open leg's Defect-7 order-fallback
        (junction + lifecycle keyed onto the dead position). Reversals
        are never reduce-only; every hedge-mode close lane (TP/SL
        legs, reduce closes) is — an unflagged close just falls back
        to the pre-existing heuristics, no worse than before."""
        exchange_order_id = fill.get("exchange_order_id", "")
        if fill.get("is_close") and (fill.get("terminal_position_id") or "") \
                and exchange_order_id:
            try:
                await self._db._conn.execute(
                    "UPDATE orders SET terminal_position_id = ? "
                    "WHERE account_id = ? AND exchange_order_id = ? "
                    "  AND COALESCE(terminal_position_id, '') = '' "
                    "  AND COALESCE(reduce_only, 0) = 1",
                    (fill["terminal_position_id"], account_id,
                     exchange_order_id),
                )
                await self._db._conn.commit()
            except Exception:
                log.debug("close-order tpid stamp failed for %s",
                          exchange_order_id, exc_info=True)

    # ── link-after-fill junction replay (moved verbatim) ───────────────

    async def ensure_junction_if_linked(self, account_id: int, eoid: str) -> None:
        """Defect-8 (debug 2026-06-08): on the observe path the matcher sets an
        order's calc_id AFTER its opening fill (once the TP/SL bracket arrives and
        re-enrichment runs). The fill-time link_position_calc_on_open already
        returned (calc_id was NULL then), so the positions_calcs junction was
        never written even though the order links. Re-trigger junction creation
        here by replaying the order's opening fill into the existing builder.

        Idempotent: skips when the order isn't linked, has no position key, or a
        junction row for (position_id, calc_id) already exists. Best-effort.

        KNOWN DIVERGENCE (battery LB-F8 / HA-42-corrected, R2 target): the
        exists-check below keys on the ORDER's stashed tpid while the
        replayed synthetic fill carries MAX(fills.tpid), which the builder
        prefers — a divergent stash makes every replay re-accumulate.
        R1 moves the rule verbatim; R2 makes guard ≡ write key.
        """
        # corr-tap: attr_junction_form via=post_link_replay (CL.T3b-entry,
        # spec §5.6) — the "should the junction be replayed?" decision.
        # On delegation the builder emits its own FORMED/SKIPPED envelope,
        # so the replay path produces two correlated decision lines.
        def _tap_replay(outcome: str, reason: Optional[str] = None,
                        **kw: Any) -> None:
            # HA-28: steady-state SKIPPED replays (junction_exists is the
            # big one — every WS update of a linked order) are on-change
            # deduped; DELEGATED/actionable + any future ERROR stay ungated.
            if outcome == "SKIPPED" and self._attr_skip_is_repeat(
                ("replay", account_id, eoid or ""), reason or ""
            ):
                return
            payload: Dict[str, Any] = {
                "outcome": outcome, "via": "post_link_replay",
                "exchange_order_id": eoid or "",
                "terminal_position_id": "", "calc_id": "",
                "lifecycle_id": "", **kw,
            }
            if reason:
                payload["reason"] = reason
            if eoid:
                # dedup_key (mandate 3, audit T3bE-4): the triggering
                # ORDER id is in scope here — a double-replay is the
                # §4.1 double-process class and must be a one-grep find.
                payload["dedup_key"] = f"replay:{eoid}"
            correlation_log.emit(
                "position_identity", "internal", "internal",
                correlation_log.CAT_ATTR_JUNCTION_FORM, payload,
                account_id=account_id,
            )

        if not eoid:
            _tap_replay("SKIPPED", "no_exchange_order_id")
            return
        try:
            async with self._db._conn.execute(
                "SELECT calc_id, terminal_position_id, id FROM orders "
                "WHERE account_id = ? AND exchange_order_id = ?",
                (account_id, eoid),
            ) as cur:
                orow = await cur.fetchone()
            if not orow:
                _tap_replay("SKIPPED", "order_row_missing")
                return
            if not orow[0]:
                _tap_replay("SKIPPED", "not_linked",
                            terminal_position_id=orow[1] or "")
                return
            calc_id = orow[0]
            stash_tpid = orow[1] or ""
            order_pk = orow[2]
            # R2 (LB-F8 fix — guard ≡ write key BY CONSTRUCTION): read the
            # opening-fills aggregate FIRST and derive the key the builder
            # will actually write under (fill tpid wins; the order stash
            # is the Defect-7 fallback), then exists-check THAT key. The
            # historical shape guarded the STASH while the synthetic fill
            # carried MAX(fills.tpid) → a divergent stash never satisfied
            # the guard and every replay re-accumulated the full SUM
            # (battery LB-T2e: N-fold unbounded contributed_qty inflation,
            # one per WS/bracket-child event). Write-key semantics also
            # mean no_position_key now fires only when BOTH the
            # fills-derived tpid AND the stash are empty (a stash-empty
            # order whose fills carry a tpid legitimately replays — the
            # builder would key it on the fill tpid anyway); the skip
            # precedence between no_opening_fill and junction_exists
            # swaps accordingly (fills are read first now).
            async with self._db._conn.execute(
                "SELECT COALESCE(MAX(terminal_position_id), ''), MAX(symbol), "
                "       MAX(direction), SUM(quantity), MAX(price), MIN(timestamp_ms) "
                "FROM fills WHERE account_id = ? AND exchange_order_id = ? "
                "  AND is_close = 0",
                (account_id, eoid),
            ) as cur:
                frow = await cur.fetchone()
            if not frow or not frow[3]:
                _tap_replay("SKIPPED", "no_opening_fill",
                            calc_id=calc_id, terminal_position_id=stash_tpid)
                return
            write_key = (frow[0] or "") or stash_tpid
            if not write_key:
                _tap_replay("SKIPPED", "no_position_key", calc_id=calc_id)
                return
            # R3 (R2-audit NIT-6 fix): the exists-check now includes
            # order_id — junction rows are PER-ORDER, and the old
            # (position_id, calc_id) guard meant a second order of the
            # same calc on the same position never replayed (its row
            # could never form via this lane — F9-family under-count).
            async with self._db._conn.execute(
                "SELECT 1 FROM positions_calcs "
                "WHERE position_id = ? AND calc_id = ? AND order_id = ? "
                "  AND account_id = ? LIMIT 1",
                (write_key, calc_id, order_pk, account_id),
            ) as cur:
                if await cur.fetchone():
                    _tap_replay("SKIPPED", "junction_exists",
                                calc_id=calc_id, terminal_position_id=write_key)
                    return
            synth_fill = {
                "account_id": account_id, "exchange_order_id": eoid,
                "terminal_position_id": frow[0] or "", "is_close": 0,
                "symbol": frow[1] or "", "direction": frow[2] or "",
                "quantity": frow[3], "price": frow[4] or 0.0,
                "timestamp_ms": frow[5] or 0,
            }
            _tap_replay("DELEGATED", calc_id=calc_id,
                        terminal_position_id=write_key)
            await self.link_position_calc_on_open(account_id, synth_fill)
        except Exception as e:
            log.debug("ensure junction post-link skipped for %s", eoid, exc_info=True)
            _tap_replay("ERROR", "exception", error_type=type(e).__name__)

    # ── §3.2 primary-calc read (moved verbatim) ────────────────────────

    async def position_primary_calc(
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
                "SELECT calc_id, lifecycle_id, contributed_qty, sealed_ts "
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
        # R5 (R4 residual (a)): prefer the UNSEALED rows as the selection
        # basis. On a venue-reused tpid the junction holds BOTH the sealed
        # (closed) trade's rows and the live trade's — without this, the
        # closed trade's contribution can out-rank (or tie-break ahead of)
        # the live trade's, welding the OLD identity onto the NEW trade's
        # close row / close-fill stamp / live badge. When NO unsealed rows
        # exist (the normal post-final-close case — everything sealed at
        # is_final), fall back to ALL rows so a REPLACE-rebuild of a final
        # row keeps its original primary instead of degrading to the
        # earliest-fill fallback. Residual (documented, plan §4-R4): two
        # SEALED trades sharing a reused tpid still rank jointly.
        unsealed = [r for r in links if r[3] is None]
        basis = unsealed or links
        # Rows ordered by first_fill_ts ASC. Primary = the calc with the
        # largest SUMMED contributed_qty (spec §3.2/§12.4 per-CALC, not the
        # largest single row), tie-break earliest first_fill — via the shared
        # _most_contributing_calc_id helper so this (close-path) and
        # _enrich_positions_calc_id (live/rehydrate) cannot diverge (T240/R1;
        # the enrich path applies the SAME unsealed-basis rule).
        primary_cid = _most_contributing_calc_id([(r[0], r[2]) for r in basis])
        if primary_cid is None:
            return None, None
        # lifecycle_id is shared across a position's junction rows; prefer the
        # primary calc's, fall back to any non-null (within the same basis —
        # the sealed trade's lifecycle must not leak into the live pair).
        lifecycle_id = (
            next((r[1] for r in basis if r[0] == primary_cid and r[1]), None)
            or next((r[1] for r in basis if r[1]), None)
        )
        return primary_cid, lifecycle_id

    # ── junction formation + lifecycle mint (moved; events stay at OM) ─

    async def link_position_calc_on_open(
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
          - ``terminal_position_id`` is empty on BOTH the fill AND the
            entry order (defect-7 falls back to the order's minted tpid
            when only the fill's is empty — the fill-before-mint race);
          - the parent order has no ``calc_id`` (UNPLANNED / unlinked —
            nothing to attribute).

        Best-effort: failures log + return; never break the fill hot
        path. All reads/writes go through ``self._db._conn`` (the
        single calc-linkage DB, ``config.DB_PATH``), matching the
        sibling Phase-1 transition sites. The position:opened/scale_in
        event emissions live at the END of this method (moved WITH the
        builder — R1 decision, module docstring) so the fill lane AND
        the Defect-8 replay lane keep their historical event behavior.
        """
        # corr-tap: attr_junction_form (CL.T3b-entry, spec §5.6) — one
        # envelope per invocation, no silent exits (mandate 1). The gates
        # below ARE the historical silent-skip class: "no_position_key"
        # is the empty-tpid shape that hid the junction-never-written
        # bug. ``_ident`` carries the identity tuple VERBATIM incl. ""
        # (mandate 2) as facts resolve; each emit snapshots it.
        _ident: Dict[str, Any] = {
            "exchange_order_id": "", "terminal_position_id": "",
            "calc_id": "", "lifecycle_id": "",
        }
        _fid = str(fill.get("exchange_fill_id") or "")

        def _tap_junction(outcome: str, reason: Optional[str] = None,
                          **kw: Any) -> None:
            payload: Dict[str, Any] = {"outcome": outcome, **_ident, **kw}
            if reason:
                payload["reason"] = reason
            if _fid:
                # dedup_key of the triggering fill (mandate 3): the same
                # fill replayed through the builder twice = one grep.
                payload["dedup_key"] = f"junction:{_fid}"
            correlation_log.emit(
                "position_identity", "internal", "internal",
                correlation_log.CAT_ATTR_JUNCTION_FORM, payload,
                account_id=account_id, symbol=fill.get("symbol") or None,
            )

        if fill.get("is_close"):
            _tap_junction("SKIPPED", "close_fill")
            return
        eoid = fill.get("exchange_order_id", "") or ""
        _ident["exchange_order_id"] = eoid
        if not eoid:
            _tap_junction("SKIPPED", "no_exchange_order_id")
            return
        pos_id = fill.get("terminal_position_id", "") or ""
        _ident["terminal_position_id"] = pos_id

        try:
            async with self._db._conn.execute(
                "SELECT id, calc_id, terminal_position_id FROM orders "
                "WHERE account_id = ? AND exchange_order_id = ?",
                (account_id, eoid),
            ) as cur:
                orow = await cur.fetchone()
        except Exception as e:
            log.debug("junction link: order read failed for %s", eoid, exc_info=True)
            _tap_junction("ERROR", "order_read_failed",
                          error_type=type(e).__name__)
            return
        if not orow:
            _tap_junction("SKIPPED", "order_row_missing")
            return
        order_id = orow[0]
        calc_id = orow[1]
        _ident["calc_id"] = calc_id or ""
        # Defect-7 (debug 2026-06-08, fill-before-mint race): the OPENING fill
        # can beat the ACCOUNT_UPDATE that mints the position, so
        # fill.terminal_position_id is empty even though the ENTRY ORDER carries
        # the minted id (from the data_cache mint via a later fill, or the
        # back-fill below). Fall back to the order's tpid so the positions_calcs
        # junction — and the Position-History drilldown that keys on it — still
        # forms. Without this, an order links (calc_id/LINKED + calc_match_audit)
        # but NO junction row is ever written for a race-affected open.
        if not pos_id:
            pos_id = orow[2] or ""
            _ident["terminal_position_id"] = pos_id
        if not pos_id:
            # neither the fill nor the order has a position key yet —
            # the canonical stranded-identity shape (spec §5.6 reason
            # vocabulary: no_position_key)
            _tap_junction("SKIPPED", "no_position_key", order_pk=order_id)
            return
        # Defect-1 (debug 2026-06-07): back-fill the entry order's
        # terminal_position_id from the (now-minted) position key so
        # reverse-query / context assembly (get_orders_by_position_id) can find
        # this order under its position. Idempotent (fills only an empty tpid);
        # piggybacks on the exchange_order_id row already read above. Runs for
        # UNLINKED orders too (before the calc_id gate) — the order belongs to
        # the position regardless of whether a calc was matched.
        try:
            await self._db._conn.execute(
                "UPDATE orders SET terminal_position_id = ? "
                "WHERE id = ? AND COALESCE(terminal_position_id, '') = ''",
                (pos_id, order_id),
            )
            await self._db._conn.commit()
        except Exception:
            log.debug("junction link: order tpid back-fill failed for %s",
                      eoid, exc_info=True)
        if not calc_id:
            # UNPLANNED / unlinked entry — nothing to attribute
            _tap_junction("SKIPPED", "not_linked", order_pk=order_id)
            return

        # R2 (LB-F6 fix — key migration, plan §2.1.3): this economic open
        # (calc_id, order_id) may already be keyed under a DIFFERENT
        # position_id — the LB-D5 dual-key shape: the first fill keyed the
        # Defect-7 order-stash fallback, a later fill carries the freshly
        # minted tpid, and nothing reconciled (two junction rows + two
        # lifecycles for ONE open). Migrate the stale row(s) to the
        # canonical key instead of forking a second identity: MERGE if a
        # row already exists under the new key (UNIQUE(position_id,
        # calc_id, order_id)), else re-key in place. In the same pass,
        # re-stamp the affected fills' tpids (plan §2.1.3 — any
        # fills-keyed recompute must stay coherent) AND correct the
        # order's stale stash (extension beyond the plan's junction+fills
        # list, named in the R2 report: a surviving stale stash keeps
        # feeding ⑨ tier-0 and the replay guard the dead key — the
        # LB-F8 stash-generator class). Best-effort; MIGRATED tap per
        # moved row (outcome-vocabulary addition → E36 at R5).
        # DIRECTION GATE (R2 audit MAJOR-1): only a fill that carried its
        # OWN tpid may trigger migration — when the triggering fill was
        # empty, pos_id above is the Defect-7 STASH fallback, and a stale
        # stash would migrate the CORRECT fills-derived row onto the dead
        # key (mutating correct fills). A stash-derived key never
        # migrates; the mirror-ordering residue (a bounded stash-keyed
        # dual row until the next tpid-carrying event converges it) is
        # pinned in the battery and is R3 retro-reconcile input. The
        # replay lane still migrates (its synth fill carries
        # MAX(fills.tpid) — fills-derived by construction).
        fill_carried_tpid = bool(fill.get("terminal_position_id") or "")
        try:
            stale_rows = []
            if fill_carried_tpid:
                async with self._db._conn.execute(
                    "SELECT id, position_id, contributed_qty, "
                    "       first_fill_ts, last_fill_ts "
                    "FROM positions_calcs "
                    "WHERE calc_id = ? AND order_id = ? AND account_id = ? "
                    "  AND position_id != ?",
                    (calc_id, order_id, account_id, pos_id),
                ) as cur:
                    stale_rows = await cur.fetchall()
            for srow in stale_rows:
                old_key = srow[1]
                # R5 (holistic-audit LOW-3 — the NIT-6 stance applied
                # symmetrically): never migrate a junction row keyed
                # under the offline-rebuild namespaces. Those rows are
                # operator-tooling-written (scripts/ backfill lane);
                # dragging one onto a live key would mutate
                # script-owned history AND re-key its rebuilt-namespace
                # fills. Structural fence, not reachability-argued.
                if old_key.startswith(("rebuilt:", "bf:")):
                    continue
                async with self._db._conn.execute(
                    "SELECT id FROM positions_calcs "
                    "WHERE position_id = ? AND calc_id = ? AND order_id = ? "
                    "  AND account_id = ? LIMIT 1",
                    (pos_id, calc_id, order_id, account_id),
                ) as cur:
                    target = await cur.fetchone()
                if target:
                    # COALESCE guards: ts columns are always set by the
                    # UPSERT in practice; the scalar MIN/MAX would NULL
                    # out on a NULL side otherwise.
                    await self._db._conn.execute(
                        "UPDATE positions_calcs SET "
                        "  contributed_qty = contributed_qty + ?, "
                        "  first_fill_ts = COALESCE("
                        "      MIN(first_fill_ts, ?), first_fill_ts, ?), "
                        "  last_fill_ts = COALESCE("
                        "      MAX(last_fill_ts, ?), last_fill_ts, ?) "
                        "WHERE id = ?",
                        (srow[2] or 0.0, srow[3], srow[3],
                         srow[4], srow[4], target[0]),
                    )
                    await self._db._conn.execute(
                        "DELETE FROM positions_calcs WHERE id = ?",
                        (srow[0],),
                    )
                else:
                    # R4 audit M2: the re-key must NOT transport a stale
                    # sealed_ts onto the canonical key — a stash-mis-keyed
                    # row (reversal-split shape) sealed by the OLD trade's
                    # close would arrive as the LIVE trade's only
                    # lifecycle row, frozen sealed → the next scale-in
                    # would be excluded from reuse and mint a phantom
                    # lifecycle. Reset on re-key; the canonical trade's
                    # own final close re-seals it. (The merge branch above
                    # is already correct — the target keeps ITS seal
                    # state.)
                    await self._db._conn.execute(
                        "UPDATE positions_calcs SET position_id = ?, "
                        "  sealed_ts = NULL "
                        "WHERE id = ?",
                        (pos_id, srow[0]),
                    )
                await self._db._conn.execute(
                    "UPDATE fills SET terminal_position_id = ? "
                    "WHERE account_id = ? AND exchange_order_id = ? "
                    "  AND is_close = 0 "
                    "  AND terminal_position_id IN ('', ?)",
                    (pos_id, account_id, eoid, old_key),
                )
                await self._db._conn.execute(
                    "UPDATE orders SET terminal_position_id = ? "
                    "WHERE id = ? AND terminal_position_id = ?",
                    (pos_id, order_id, old_key),
                )
                await self._db._conn.commit()
                _tap_junction("MIGRATED", old_key=old_key,
                              contributed_qty=srow[2] or 0.0,
                              order_pk=order_id)
        except Exception:
            # NIT-5 (R2 audit): a mid-loop failure must not leave
            # uncommitted statements riding the next unrelated commit.
            try:
                await self._db._conn.rollback()
            except Exception:
                pass
            log.debug("junction key migration failed for %s/%s",
                      calc_id, order_id, exc_info=True)

        # Reuse the position's existing lifecycle_id if a prior fill on
        # this position already established one (multi-fill / scale-in);
        # otherwise this is the first opening fill → mint a UUID v4.
        #
        # R4 (LB-F4/LB-I5 fix — seal-at-close): the lookup ignores SEALED
        # lifecycles (sealed_ts stamped on every junction row of the
        # position at its FINAL close — seal_position_lifecycles below),
        # so a venue-reused tpid slot mints a FRESH lifecycle for the new
        # economic trade instead of bleeding the closed trade's one.
        # Pre-R4 this SELECT took ANY row for the tpid, and the reuse
        # hazard was a documented deferred ASSUMPTION ("a recurring tpid
        # would bleed a closed trade's lifecycle into a new one").
        # Partial closes never seal (the seal fires only at is_final,
        # T2.11), so multi-TP ladders and scale-ins after a partial keep
        # lifecycle continuity.
        # OWN-TRIPLE exception: a row for THIS exact (position, calc,
        # order) triple supplies its lifecycle even when sealed — an
        # order belongs to exactly one economic trade, so a LATE fill of
        # a sealed trade's own order continues THAT trade (junction row,
        # fill stamps, and events stay coherent; the UPSERT's
        # lifecycle COALESCE keeps the row on its original lifecycle
        # anyway, and a fresh mint here would emit a spurious
        # position:opened for an already-closed position). A genuinely
        # new trade always arrives on a NEW order → never matches the
        # exception → mints fresh. ORDER BY prefers the own-triple row
        # when both it and an unsealed row (reused slot, new trade
        # already open) qualify.
        try:
            async with self._db._conn.execute(
                "SELECT lifecycle_id FROM positions_calcs "
                "WHERE position_id = ? AND account_id = ? "
                "  AND lifecycle_id IS NOT NULL "
                "  AND (sealed_ts IS NULL "
                "       OR (calc_id = ? AND order_id = ?)) "
                "ORDER BY (calc_id = ? AND order_id = ?) DESC "
                "LIMIT 1",
                (pos_id, account_id, calc_id, order_id, calc_id, order_id),
            ) as cur:
                lrow = await cur.fetchone()
        except Exception as e:
            log.debug("junction link: lifecycle lookup failed for %s", pos_id, exc_info=True)
            _tap_junction("ERROR", "lifecycle_lookup_failed",
                          error_type=type(e).__name__, order_pk=order_id)
            return
        lifecycle_id = lrow[0] if lrow and lrow[0] else str(uuid.uuid4())
        _ident["lifecycle_id"] = lifecycle_id
        # P6.T4: the lifecycle mint-vs-reuse signal IS the position-level
        # open-vs-scale-in distinction. No prior lifecycle → this fill OPENS the
        # position. Reuse → the position is already open; whether THIS is a
        # scale-in (a calc new to the position) vs just another fill of an
        # existing contribution is resolved by the junction-membership check
        # below (run BEFORE the upsert creates the row).
        is_first_open = not (lrow and lrow[0])
        calc_new_to_position = False
        if not is_first_open:
            try:
                async with self._db._conn.execute(
                    "SELECT 1 FROM positions_calcs "
                    "WHERE position_id = ? AND calc_id = ? AND account_id = ? LIMIT 1",
                    (pos_id, calc_id, account_id),
                ) as cur:
                    calc_new_to_position = (await cur.fetchone()) is None
            except Exception:
                log.debug(
                    "scale-in check failed for %s/%s", pos_id, calc_id, exc_info=True,
                )

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
        _junction_ok = await self._db.upsert_position_calc_link({
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

        # R3 (LB-F9 fix — mint-after-fill retro-reconcile; §5-Q2 decision:
        # DELTA-RECONCILE adopted with the design-review constraints).
        # (1) SWEEP: earlier opening fills of THIS order that predate the
        #     mint (tpid='') are stamped with the canonical key +
        #     lifecycle — the fill-before-mint first fill is no longer
        #     stranded (battery LB-T2d: the mint landed with a later fill
        #     and nothing ever folded the first one in).
        # (2) RECONCILE: the junction row's contributed_qty is set to
        #     SUM(ABS(quantity)) of the order's opening fills — keyed by
        #     ORDER (eoid), never raw fills.tpid (review MAJOR-2: a
        #     tpid-keyed recompute zeroes valid rows on rebuilt: shapes);
        #     EVIDENCE-GATED (no fills → NO-OP); on-change only. Also
        #     heals F8-inflated / F9-starved HISTORICAL rows for free at
        #     the next fill/replay event on the row.
        # DIRECTION GATE (same rule as the R2 migration, same reason): a
        # stash-derived Defect-7 event must neither stamp sibling fills
        # with a possibly-stale key nor reconcile across a transient
        # dual-key state (an ungated sweep double-counts the mirror
        # ordering's mid-state); only a fill that carried its OWN tpid —
        # incl. the replay's fills-derived synth fill — sweeps.
        # Emits a RECONCILED tap (attr_junction_form outcome, the R2
        # MIGRATED precedent → E36) only when the value actually moved.
        if fill_carried_tpid:
            try:
                cur_sweep = await self._db._conn.execute(
                    "UPDATE fills SET terminal_position_id = ? "
                    "WHERE account_id = ? AND exchange_order_id = ? "
                    "  AND is_close = 0 "
                    "  AND COALESCE(terminal_position_id, '') = ''",
                    (pos_id, account_id, eoid),
                )
                swept = cur_sweep.rowcount or 0
                # R5 (R3-audit NIT-6 rider): STRUCTURAL rebuilt-namespace
                # fence, not reachability-argued. The §2.2 fence promises
                # the owner's retro passes never mutate rows whose fills
                # live under the offline-rebuild namespaces; the tpid
                # sweep above is empty-only (rebuilt-safe by shape), but
                # this lifecycle stamp matched ANY of the order's opening
                # fills — including ones the fenced rebuild lane re-keyed
                # to `rebuilt:`/`bf:`. Exclude those namespaces outright.
                await self._db._conn.execute(
                    "UPDATE fills SET lifecycle_id = ? "
                    "WHERE account_id = ? AND exchange_order_id = ? "
                    "  AND is_close = 0 AND lifecycle_id IS NULL "
                    "  AND COALESCE(terminal_position_id, '') "
                    "      NOT LIKE 'rebuilt:%' "
                    "  AND COALESCE(terminal_position_id, '') "
                    "      NOT LIKE 'bf:%'",
                    (lifecycle_id, account_id, eoid),
                )
                async with self._db._conn.execute(
                    "SELECT contributed_qty FROM positions_calcs "
                    "WHERE position_id = ? AND calc_id = ? AND order_id = ? "
                    "  AND account_id = ?",
                    (pos_id, calc_id, order_id, account_id),
                ) as cur:
                    rrow = await cur.fetchone()
                async with self._db._conn.execute(
                    "SELECT SUM(ABS(quantity)) FROM fills "
                    "WHERE account_id = ? AND exchange_order_id = ? "
                    "  AND is_close = 0",
                    (account_id, eoid),
                ) as cur:
                    srow = await cur.fetchone()
                true_qty = srow[0] if srow else None
                row_qty = rrow[0] if rrow else None
                changed = (true_qty is not None and row_qty is not None
                           and abs(float(true_qty) - float(row_qty)) > 1e-12)
                if changed:
                    await self._db._conn.execute(
                        "UPDATE positions_calcs SET contributed_qty = ? "
                        "WHERE position_id = ? AND calc_id = ? "
                        "  AND order_id = ? AND account_id = ?",
                        (float(true_qty), pos_id, calc_id, order_id,
                         account_id),
                    )
                await self._db._conn.commit()
                # Tap AFTER the commit (R3-audit NIT-1, matching the R2
                # MIGRATED precedent) — a rolled-back reconcile must not
                # leave a RECONCILED line for a change that didn't persist.
                if changed:
                    _tap_junction(
                        "RECONCILED", order_pk=order_id,
                        old_qty=float(row_qty), new_qty=float(true_qty),
                        swept_fills=swept,
                    )
            except Exception:
                try:
                    await self._db._conn.rollback()
                except Exception:
                    pass
                log.debug(
                    "retro-reconcile failed for calc=%s order=%s",
                    calc_id, order_id, exc_info=True,
                )

        log.info(
            "Linked position %s ↔ calc %s (order_id=%s, lifecycle=%s, qty=%.6f)",
            pos_id, calc_id, order_id, lifecycle_id, qty,
        )
        # The decision line: FORMED only when the junction write actually
        # landed (audit T3bE-3 — the writer swallows its own failures, and
        # asserting FORMED on a failed write is the historical "junction
        # missing" shape this tap exists to expose). The paired db_write
        # envelope carries the rowcount on the same chain; flow (the
        # lifecycle backfills above) is unchanged on failure, matching
        # pre-tap behavior. The mint-vs-reuse signal IS the open-vs-
        # scale-in distinction (P6.T4).
        if _junction_ok:
            _tap_junction(
                "FORMED", order_pk=order_id,
                lifecycle_minted=is_first_open,
                scale_in=calc_new_to_position,
                contributed_qty=qty,
            )
        else:
            _tap_junction(
                "ERROR", "junction_write_failed", order_pk=order_id,
                lifecycle_minted=is_first_open,
                scale_in=calc_new_to_position,
                contributed_qty=qty,
            )

        # P6.T4 (spec §9): position lifecycle events on the per-account topic,
        # emitted AFTER the durable junction write. POSITION-level semantics
        # from the mint-vs-reuse signal — note the position_opened TRADE event
        # in _emit_fill_events is per-CALC-first-fill (so it ALSO fires on a
        # scale-in); these event_bus topics use the §9-correct position-first-
        # open vs scale_in split. Best-effort (publish_engine is enqueue-only).
        # Moved WITH the builder (R1 decision — module docstring): the
        # Defect-8 replay lane reaches here too and must keep emitting.
        try:
            if is_first_open:
                await event_bus.publish_engine(account_id, DOMAIN_POSITION, "opened", {
                    "position_id": pos_id,
                    "calc_ids":    [calc_id],
                    "symbol":      fill.get("symbol", ""),
                    "direction":   fill.get("direction", ""),
                    "entry_px":    fill.get("price", 0),
                    "size":        qty,
                })
            elif calc_new_to_position:
                await event_bus.publish_engine(account_id, DOMAIN_POSITION, "scale_in", {
                    "position_id": pos_id,
                    "new_calc_id": calc_id,
                    "added_qty":   qty,
                })
        except Exception:
            log.debug("position opened/scale_in event emit failed", exc_info=True)

    # ── R4: lifecycle seal-at-close (LB-F4/LB-I5) ──────────────────────

    async def seal_position_lifecycles(
        self, account_id: int, position_id: str, sealed_ts: int,
        symbol: Optional[str] = None,
    ) -> int:
        """Seal a fully-closed position's lifecycles (plan §2.1.5, R4).

        Stamps ``sealed_ts`` on every junction row of ``position_id``
        that isn't already sealed. Called by the close-row builder at
        the FINAL close only (the ``_complete_calcs_on_close`` moment —
        ``is_final``, size→0), NEVER on a partial rung, so scale-ins
        and multi-TP ladders keep lifecycle continuity mid-life.

        ``sealed_ts`` is the close row's ``exit_time_ms`` — data-derived
        and deterministic (no wall clock; the 1fe4178 flake lesson), and
        it makes the seal a queryable fact ("this trade sealed at its
        exit time"), the §5-Q3 observability upside of the column.

        Idempotent (``WHERE sealed_ts IS NULL``): a REPLACE-rebuild of
        the final row re-runs the builder and no-ops here. Best-effort:
        a seal failure must never block the close path — the consequence
        is only that a future tpid-reuse would bleed (the pre-R4
        behavior). Returns the number of rows sealed; emits a SEALED
        ``attr_junction_form`` line only when > 0 (the R2 MIGRATED /
        R3 RECONCILED outcome-riding precedent — no new registry
        category before E36).
        """
        if not position_id:
            return 0
        try:
            cur = await self._db._conn.execute(
                "UPDATE positions_calcs SET sealed_ts = ? "
                "WHERE position_id = ? AND account_id = ? "
                "  AND sealed_ts IS NULL",
                (sealed_ts, position_id, account_id),
            )
            await self._db._conn.commit()
            sealed = max(0, cur.rowcount or 0)
        except Exception:
            try:
                await self._db._conn.rollback()
            except Exception:
                pass
            log.debug("lifecycle seal failed for %s", position_id,
                      exc_info=True)
            return 0
        if sealed:
            correlation_log.emit(
                "position_identity", "internal", "internal",
                correlation_log.CAT_ATTR_JUNCTION_FORM,
                {
                    "outcome": "SEALED",
                    "terminal_position_id": position_id,
                    "calc_id": "", "lifecycle_id": "",
                    "exchange_order_id": "",
                    "sealed_ts": sealed_ts,
                    "rows_sealed": sealed,
                    "dedup_key": f"seal:{position_id}:{sealed_ts}",
                },
                account_id=account_id, symbol=symbol or None,
            )
        return sealed

    # ── close-time open-fill identity backfill (moved verbatim) ────────

    async def backfill_open_fill_tpids(
        self, account_id: int, opens: List[Dict[str, Any]], pos_id: str,
    ) -> int:
        """#3/#4 (debug 2026-06-08): stamp the minted terminal_position_id onto
        this position's OPENING fills, which the observe-only Binance path wrote
        empty (the position is minted only after the first open completes; the
        junction-link backfill stamps lifecycle_id but not the tpid). Without it
        the tpid-keyed open lookup AND the per-position fills/events drilldown
        miss them. Best-effort, keyed by exchange_fill_id, only where currently
        empty (idempotent; never reattributes an already-stamped fill). Mirrors
        the lifecycle_id back-fill in link_position_calc_on_open.

        2026-06-24: ALSO stamps calc_id + lifecycle_id on the open fills, from
        the position's primary calc. Close-build BACKSTOP for the link-timing
        race (the link-time fill backfill in order_enrichment.py is the primary
        fix; this runs only on the strict-lookup-miss + walk path and ALSO
        covers lifecycle_id, which link-time can't): the entry fill is enriched
        BEFORE the matcher links the order, so every fill-time attribution path
        (_propagate_calc_id_to_fill, link_position_calc_on_open) no-ops on
        calc_id=NULL and is never re-run — leaving the ENTRY fill of a linked
        position without calc_id/lifecycle even though the CLOSE fill has both
        (exec-link drawer blank, /context/calc fills list incomplete). By close
        the junction is authoritative, so this gives the open fills parity.
        Idempotent (COALESCE/NULLIF — only fills a currently-empty column).
        R3 NOTE: the mint-after-fill retro-sweep (link_position_calc_on_open)
        now stamps tpid+lifecycle at mint time, so this close-time backstop
        mostly no-ops on tpid — it REMAINS for calc_id parity (link-timing)
        and the no-later-event tails (stash-derived-only opens; reversal
        open legs heal here at close, on the strict-miss→walk path)."""
        fids = [
            f.get("exchange_fill_id") for f in opens
            if f.get("exchange_fill_id")
            and not (f.get("terminal_position_id") or "")
        ]
        all_open_fids = [
            f.get("exchange_fill_id") for f in opens if f.get("exchange_fill_id")
        ]
        primary_calc_id = lifecycle_id = None
        if all_open_fids:
            primary_calc_id, lifecycle_id = await self.position_primary_calc(
                account_id, pos_id,
            )
        if not fids and not (primary_calc_id or lifecycle_id):
            return 0
        try:
            for fid in fids:
                await self._db._conn.execute(
                    "UPDATE fills SET terminal_position_id = ? "
                    "WHERE account_id = ? AND exchange_fill_id = ? "
                    "  AND COALESCE(terminal_position_id, '') = ''",
                    (pos_id, account_id, fid),
                )
            if primary_calc_id or lifecycle_id:
                for fid in all_open_fids:
                    await self._db._conn.execute(
                        "UPDATE fills SET "
                        "  calc_id = COALESCE(NULLIF(calc_id, ''), ?), "
                        "  lifecycle_id = COALESCE(NULLIF(lifecycle_id, ''), ?) "
                        "WHERE account_id = ? AND exchange_fill_id = ?",
                        (primary_calc_id or None, lifecycle_id or None,
                         account_id, fid),
                    )
            await self._db._conn.commit()
            return len(fids)
        except Exception:
            log.debug("open-fill tpid/attribution backfill failed", exc_info=True)
            return 0
