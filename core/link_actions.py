"""
Operator link-status actions (Phase 3.2 / P3.T2).

Backend handlers for the manual-link workflow (spec §6 operator-action
transitions + §10.3 needs-link tab). Three operations:

- :func:`manual_link_order`  — operator links a NEEDS_MANUAL_REVIEW /
  UNLINKED order to a calc (→ ``LINKED``).
- :func:`mark_order_unplanned` — operator downgrades a NEEDS_MANUAL_REVIEW
  / UNLINKED order to ``UNPLANNED``.
- :func:`list_needs_review`   — the review queue (NEEDS_MANUAL_REVIEW +
  UNLINKED orders) with per-order candidate calcs + per-criterion diff.

EVERY ``orders.link_status`` write here routes through the
``core.link_state.transition`` choke-point (the operator-move entry point
P3.T1 wired) — spec §3.6 forbids raw UPDATEs. These are the operator
*decided→decided* transitions (NEEDS_MANUAL_REVIEW→LINKED,
UNLINKED→UNPLANNED, …); the matcher's engine-classification path uses
``link_state.auto_classify`` instead.

This mirrors ``core.handlers.cancel_calc_by_operator`` (the calc-side
operator action): read current state → ``transition(apply_fn=…)`` where
``apply_fn`` does the TOCTOU-guarded UPDATE and raises
:class:`core.link_state.LinkTransitionRaceLost` on rowcount 0 → caller maps
exceptions to a discriminated string result. Route handlers stay thin
wrappers (api/routes_orders.py) so this logic is unit-testable without a
TestClient (see HANDOFF gotcha #9).

The legacy ``/admin/calc_link`` surface (api/routes_admin.py) does a raw
``UPDATE orders SET calc_id`` with NO link_status and NO choke-point — it
predates this and is the documented Phase-3 fallback (plan §11), to be
removed once the needs-link tab is proven stable. Do not extend it.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any, Dict, List

import config
from core.database import db
from core.calc_state import (
    CalcStatus,
    CalcTransitionRaceLost,
    transition as calc_transition,
)
from core.link_state import (
    IllegalStateTransition,
    LinkStatus,
    LinkTransitionRaceLost,
    transition as link_transition,
)

log = logging.getLogger("link_actions")


async def manual_link_order(account_id: int, order_id: int, calc_id: str) -> str:
    """Operator manually links an order to a calc (spec §6 operator-link).

    Transitions ``orders.link_status`` (NEEDS_MANUAL_REVIEW | UNLINKED) →
    LINKED through ``link_state.transition`` and stamps ``orders.calc_id``,
    then mirrors the auto-matcher by flipping the calc
    ``active|released → matched`` (so the manually-linked calc's lifecycle
    proceeds instead of being expiry-swept) and propagates ``calc_id`` onto
    the order's opening fills.

    Returns a discriminated outcome string: ``linked`` | ``missing_calc_id``
    | ``order_not_found`` | ``already_linked`` | ``calc_not_found`` |
    ``invalid_transition`` | ``race_lost`` | ``error``.

    Scope note: the live ``positions_calcs`` junction is built on the fill
    hot path (T2.1), so a manual link that lands AFTER the opening fills
    already arrived does NOT retro-create junction rows — position-level
    attribution (PositionInfo.calc_id, closed_positions primary) for such
    an order relies on the offline rebuild. The order + its opening fills
    carry the calc_id; the junction backfill on late link is a follow-up.
    """
    calc_id = (calc_id or "").strip()
    if not calc_id:
        return "missing_calc_id"

    async with db._conn.execute(
        "SELECT link_status, calc_id, exchange_order_id FROM orders "
        "WHERE account_id = ? AND id = ?",
        (account_id, order_id),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return "order_not_found"
    current_link, existing_calc, eid = row[0], row[1], (row[2] or "")
    if existing_calc:
        return "already_linked"  # maintains calc_id present ⟺ LINKED

    async with db._conn.execute(
        "SELECT status FROM pre_trade_log WHERE calc_id = ? AND account_id = ?",
        (calc_id, account_id),
    ) as cur:
        crow = await cur.fetchone()
    if crow is None:
        return "calc_not_found"
    calc_status = crow[0]

    # 1. Order link transition: current → LINKED (validates the operator
    #    move NEEDS_MANUAL_REVIEW|UNLINKED → LINKED; a NULL or UNPLANNED
    #    current is rejected by the choke-point → invalid_transition).
    async def _apply_link() -> None:
        cur2 = await db._conn.execute(
            "UPDATE orders SET calc_id = ?, link_status = ? "
            "WHERE account_id = ? AND id = ? AND link_status = ? "
            "  AND calc_id IS NULL",
            (calc_id, LinkStatus.LINKED.value, account_id, order_id, current_link),
        )
        await db._conn.commit()
        if cur2.rowcount == 0:
            raise LinkTransitionRaceLost(
                order_id, current_link or "(null)", LinkStatus.LINKED.value,
            )

    try:
        await link_transition(
            order_id, current_link, LinkStatus.LINKED.value,
            apply_fn=_apply_link, event_payload={"calc_id": calc_id},
        )
    except IllegalStateTransition:
        return "invalid_transition"
    except LinkTransitionRaceLost as exc:
        log.info("%s", exc)
        return "race_lost"
    except Exception:
        log.warning(
            "manual_link_order: link transition failed for order=%s calc=%s",
            order_id, calc_id, exc_info=True,
        )
        return "error"

    # 2. Mirror the auto-matcher: flip the calc active|released → matched so
    #    its lifecycle proceeds (calc:linked fires via the choke-point).
    #    Best-effort — the order is already linked; a calc already past
    #    active|released (matched scale-in, or expired/cancelled via operator
    #    override) is left as-is.
    if calc_status in (CalcStatus.ACTIVE.value, CalcStatus.RELEASED.value):
        async def _apply_calc() -> None:
            cur3 = await db._conn.execute(
                "UPDATE pre_trade_log SET status = ? "
                "WHERE calc_id = ? AND status = ?",
                (CalcStatus.MATCHED.value, calc_id, calc_status),
            )
            await db._conn.commit()
            if cur3.rowcount == 0:
                raise CalcTransitionRaceLost(
                    calc_id, calc_status, CalcStatus.MATCHED.value,
                )

        try:
            await calc_transition(
                calc_id=calc_id, current_status=calc_status,
                target_status=CalcStatus.MATCHED.value,
                apply_fn=_apply_calc, event_payload={"order_id": order_id},
            )
        except CalcTransitionRaceLost as exc:
            log.info("manual_link_order: calc flip raced: %s", exc)
        except Exception:
            log.warning(
                "manual_link_order: calc active→matched failed for calc=%s",
                calc_id, exc_info=True,
            )

    # 3. Propagate calc_id to the order's OPENING fills (closing fills get
    #    the position primary via T2.2, not the order). Best-effort.
    try:
        await db._conn.execute(
            "UPDATE fills SET calc_id = ? "
            "WHERE account_id = ? AND exchange_order_id = ? "
            "  AND is_close = 0 AND calc_id IS NULL",
            (calc_id, account_id, eid),
        )
        await db._conn.commit()
    except Exception:
        log.debug("manual_link_order: fill calc_id propagation failed", exc_info=True)

    try:
        from core.trade_event_log import log_trade_event
        log_trade_event(
            account_id, calc_id, "manual_link_added",
            {"order_id": order_id, "exchange_order_id": eid},
            source="manual_link",
        )
    except Exception:
        log.debug("manual_link_added event failed", exc_info=True)

    return "linked"


async def mark_order_unplanned(account_id: int, order_id: int) -> str:
    """Operator downgrades an order to UNPLANNED (spec §6 operator-mark).

    Transitions ``orders.link_status`` (NEEDS_MANUAL_REVIEW | UNLINKED) →
    UNPLANNED through the choke-point. These source states carry
    ``calc_id = NULL`` (the calc_id ⟺ LINKED invariant), so no calc_id is
    touched.

    Returns: ``marked`` | ``order_not_found`` | ``invalid_transition`` |
    ``race_lost`` | ``error``.
    """
    async with db._conn.execute(
        "SELECT link_status FROM orders WHERE account_id = ? AND id = ?",
        (account_id, order_id),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return "order_not_found"
    current_link = row[0]

    async def _apply_unplanned() -> None:
        cur2 = await db._conn.execute(
            "UPDATE orders SET link_status = ? "
            "WHERE account_id = ? AND id = ? AND link_status = ?",
            (LinkStatus.UNPLANNED.value, account_id, order_id, current_link),
        )
        await db._conn.commit()
        if cur2.rowcount == 0:
            raise LinkTransitionRaceLost(
                order_id, current_link or "(null)", LinkStatus.UNPLANNED.value,
            )

    try:
        await link_transition(
            order_id, current_link, LinkStatus.UNPLANNED.value,
            apply_fn=_apply_unplanned,
        )
    except IllegalStateTransition:
        return "invalid_transition"
    except LinkTransitionRaceLost as exc:
        log.info("%s", exc)
        return "race_lost"
    except Exception:
        log.warning(
            "mark_order_unplanned: transition failed for order=%s",
            order_id, exc_info=True,
        )
        return "error"
    return "marked"


async def list_needs_review(account_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    """Return the manual-link review queue (spec §6.2 / §10.3): orders with
    ``link_status`` in {NEEDS_MANUAL_REVIEW, UNLINKED}, each annotated with
    its candidate calcs + per-criterion drift/match diff.

    Candidates come from ``core.calc_correlation.find_candidate_calcs`` (the
    LOOSE finder — 5% drift / 168h, ≥1 matching leg — intentionally shows
    near-misses the strict matcher rejected; norm_side-correct per T212 L2).
    Best-effort per-order: a candidate-finder failure annotates an empty
    list rather than dropping the order from the queue.
    """
    from core.calc_correlation import find_candidate_calcs

    async with db._conn.execute(
        "SELECT id, exchange_order_id, symbol, side, order_type, price, "
        "       tp_trigger_price, sl_trigger_price, created_at_ms, link_status "
        "FROM orders "
        "WHERE account_id = ? AND link_status IN (?, ?) "
        "ORDER BY created_at_ms DESC LIMIT ?",
        (account_id, LinkStatus.NEEDS_MANUAL_REVIEW.value,
         LinkStatus.UNLINKED.value, int(limit)),
    ) as cur:
        rows = await cur.fetchall()
        cols = [c[0] for c in cur.description]

    out: List[Dict[str, Any]] = []
    for r in rows:
        order = dict(zip(cols, r))
        order.setdefault("account_id", account_id)
        try:
            # find_candidate_calcs is sync (opens its own sqlite3 conn);
            # offload so the per-order loop doesn't block the event loop —
            # don't add a new sync-in-async callsite to the MED-005 backlog.
            candidates = await asyncio.to_thread(
                find_candidate_calcs, order, db_path=config.DB_PATH,
            )
            order["candidates"] = [asdict(c) for c in candidates]
        except Exception:
            log.debug(
                "needs_review: candidate finder failed for order=%s",
                order.get("id"), exc_info=True,
            )
            order["candidates"] = []
        out.append(order)
    return out
