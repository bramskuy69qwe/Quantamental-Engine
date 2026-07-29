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

The legacy ``/admin/calc_link`` surface (api/routes_admin.py) DELEGATES
here as of LB-F2 (linkage battery 2026-07-14) — its historical raw
``UPDATE orders SET calc_id`` bypass (no link_status, no choke-point) is
gone. It remains the documented Phase-3 fallback (plan §11), to be
removed once the needs-link tab is proven stable.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any, Dict, List

import config
from core import correlation_log
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


def _parse_tags(raw: Any) -> List[str]:
    """Normalise a pre_trade_log ``tags`` cell to a list of strings.

    v3.0 operator-bug #5: pre_trade_log.tags is a DORMANT column — the
    ``insert_pre_trade_log`` writer (core/db_trades.py) never populates it, so
    it is NULL on every live row today (the calc's session tags ride the
    calc_created EVENT instead). This parser is deliberately format-tolerant
    (JSON array | comma/space-separated | already-a-list) so the resolver's tag
    chips light up automatically if that column is ever wired, with no frontend
    change. Until then it returns [] and the frontend omits the tag chips.
    """
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(t).strip() for t in raw if str(t).strip()]
    s = str(raw).strip()
    if not s:
        return []
    if s.startswith("["):
        import json
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(t).strip() for t in parsed if str(t).strip()]
        except (ValueError, TypeError):
            pass
    return [t.strip() for t in s.replace(",", " ").split() if t.strip()]


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

    corr-tap: attr_match_attempt via=manual_link (CL.T3b-entry, spec §5.6
    — the manual-link path is part of the match-attempt category). Thin
    wrapper so every invocation emits exactly one envelope (mandate 1),
    whatever the discriminated outcome or exception.
    """
    _ctx: Dict[str, Any] = {}
    outcome = "error"
    _err = None
    try:
        outcome = await _manual_link_order_impl(
            account_id, order_id, calc_id, _ctx,
        )
        return outcome
    except Exception as e:
        _err = type(e).__name__
        raise
    finally:
        payload: Dict[str, Any] = {
            "outcome": ("LINKED" if outcome == "linked"
                        else "ERROR" if _err else "SKIPPED"),
            "via": "manual_link",
            "result": outcome,
            # identity tuple VERBATIM incl. "" (mandate 2): calc_id is the
            # operator's REQUESTED calc (existing_calc_id rides along on
            # the already_linked path)
            "calc_id": (calc_id or "").strip(),
            "exchange_order_id": _ctx.get("exchange_order_id", ""),
            "terminal_position_id": _ctx.get("terminal_position_id", ""),
            "lifecycle_id": "",
            "order_id": order_id,
            # dedup_key (mandate 3): an operator double-click double-submit
            # is a one-grep find
            "dedup_key": f"manual:{order_id}:{(calc_id or '').strip()}",
        }
        if _err:
            payload["error_type"] = _err
        elif outcome != "linked":
            payload["reason"] = outcome
        if "existing_calc_id" in _ctx:
            payload["existing_calc_id"] = _ctx["existing_calc_id"]
        correlation_log.emit(
            "link_actions", "internal", "internal",
            correlation_log.CAT_ATTR_MATCH_ATTEMPT, payload,
            account_id=account_id,
        )


async def _manual_link_order_impl(
    account_id: int, order_id: int, calc_id: str, _ctx: Dict[str, Any],
) -> str:
    """The manual-link body (see :func:`manual_link_order` for the
    contract). ``_ctx`` collects identity facts (exchange_order_id, tpid,
    the pre-existing calc on the already_linked path) for the wrapper's
    attr_match_attempt envelope."""
    calc_id = (calc_id or "").strip()
    if not calc_id:
        return "missing_calc_id"

    async with db._conn.execute(
        "SELECT link_status, calc_id, exchange_order_id, "
        "       terminal_position_id FROM orders "
        "WHERE account_id = ? AND id = ?",
        (account_id, order_id),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return "order_not_found"
    current_link, existing_calc, eid = row[0], row[1], (row[2] or "")
    _ctx["exchange_order_id"] = eid
    _ctx["terminal_position_id"] = row[3] or ""
    if existing_calc:
        _ctx["existing_calc_id"] = existing_calc
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
        # P4 audit (COMPLETENESS-001): backfill amendments orphaned (calc_id
        # NULL) before this manual link, so the calc_id-scoped consumers
        # (cumulative count, deviation badge, tp/sl drift) can see them — the
        # same propagate-on-link discipline as bracket inheritance + fills.
        # Only when the link actually applied (rowcount>0); atomic via the
        # shared commit below.
        if cur2.rowcount > 0:
            await db.backfill_amendment_calc_id(order_id, calc_id)
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
                apply_fn=_apply_calc, account_id=account_id,
                event_payload={"order_id": order_id},
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

    # 4. LB-F1 (linkage battery 2026-07-14): replay the junction for an
    #    already-filled order. The Defect-8 replay fired only from the
    #    auto lane (_enrich_order_best_effort), so a manual link placed
    #    AFTER the entry fill left positions_calcs empty — the
    #    VELVET/ETH gap shape (live badge unattributed, close-fill stamp
    #    no-ops; only the close row recovered via earliest-fill
    #    fallback). A throwaway OrderManager(db) is used instead of
    #    the order_manager singleton so the replay always runs on THIS
    #    module's db binding (prod: the same singleton; tests: the
    #    patched temp DB) — construction is three attribute assignments.
    #    Idempotent + best-effort; the attr_junction_form
    #    via=post_link_replay envelope traces the decision.
    try:
        from core.order_manager import OrderManager
        await OrderManager(db)._ensure_junction_if_linked(account_id, eid)
    except Exception:
        log.warning(
            "manual_link_order: junction replay failed for order=%s calc=%s",
            order_id, calc_id, exc_info=True,
        )

    try:
        from core.trade_event_log import log_trade_event
        from core.auth_state import current_operator_id
        # P9 holistic-audit (plan §9.3 "manual_links" operator attribution):
        # record WHO manually linked, on the event — NOT on orders.operator_id,
        # which holds the PLACEMENT operator (T3 first-known-wins COALESCE) and
        # must not be clobbered by the linker. Best-effort (None if no active
        # session / resolver fault); manual_link is an HTTP operator action,
        # not a hot path, so the DB resolve is fine.
        operator_id = await current_operator_id(db, account_id)
        log_trade_event(
            account_id, calc_id, "manual_link_added",
            {"order_id": order_id, "exchange_order_id": eid,
             "operator_id": operator_id},
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

    corr-tap: attr_match_attempt via=mark_unplanned (CL.T3b-entry, spec
    §5.6) — the operator's "this order has no plan" decision; same
    wrapper shape as :func:`manual_link_order`.
    """
    _ctx: Dict[str, Any] = {}
    outcome = "error"
    _err = None
    try:
        outcome = await _mark_order_unplanned_impl(account_id, order_id, _ctx)
        return outcome
    except Exception as e:
        _err = type(e).__name__
        raise
    finally:
        payload: Dict[str, Any] = {
            "outcome": ("UNPLANNED" if outcome == "marked"
                        else "ERROR" if _err else "SKIPPED"),
            "via": "mark_unplanned",
            "result": outcome,
            "calc_id": "",
            "exchange_order_id": _ctx.get("exchange_order_id", ""),
            "terminal_position_id": _ctx.get("terminal_position_id", ""),
            "lifecycle_id": "",
            "order_id": order_id,
            "dedup_key": f"manual:{order_id}:unplanned",
        }
        if _err:
            payload["error_type"] = _err
        elif outcome != "marked":
            payload["reason"] = outcome
        correlation_log.emit(
            "link_actions", "internal", "internal",
            correlation_log.CAT_ATTR_MATCH_ATTEMPT, payload,
            account_id=account_id,
        )


async def _mark_order_unplanned_impl(
    account_id: int, order_id: int, _ctx: Dict[str, Any],
) -> str:
    """The mark-unplanned body (see :func:`mark_order_unplanned`)."""
    async with db._conn.execute(
        "SELECT link_status, exchange_order_id, terminal_position_id "
        "FROM orders WHERE account_id = ? AND id = ?",
        (account_id, order_id),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return "order_not_found"
    current_link = row[0]
    _ctx["exchange_order_id"] = row[1] or ""
    _ctx["terminal_position_id"] = row[2] or ""

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

    # v3.0 operator-bug #5: the resolver detail (frontend LkLinkResolver) shows
    # the order's Size / Notional / Operator / Client-order-id — columns that
    # already exist on `orders` but were never selected here. quantity drives
    # both Size and the computed Notional (price × quantity).
    async with db._conn.execute(
        # E2E-P6-002: avg_fill_price is REQUIRED here — a market order's `price`
        # is 0, so without it find_candidate_calcs bails and the resolver can
        # never offer a candidate (see its entry_price comment). It is also the
        # only honest number to DISPLAY for a market entry.
        "SELECT id, exchange_order_id, symbol, side, order_type, price, "
        "       avg_fill_price, "
        "       quantity, client_order_id, operator_id, "
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

    # v3.0 operator-bug #5: enrich every candidate with its calc's
    # model / R-multiple / tags. CandidateCalc (calc_correlation) carries only
    # the match-diff legs, so the resolver's "momentum_v3 · R 2.25 · #session"
    # meta line was dropped in P4 (HANDOFF: "not in the needs_review payload").
    # These live on pre_trade_log keyed by calc_id — one batch fetch across ALL
    # candidates in the queue (no N+1). Best-effort: a lookup miss leaves the
    # candidate's meta as None and the frontend simply omits the line.
    all_calc_ids = [
        c.get("calc_id") for o in out for c in o.get("candidates", [])
        if c.get("calc_id")
    ]
    if all_calc_ids:
        try:
            ptl_by_id = await db.get_pretrade_logs_by_calc_ids(all_calc_ids)
        except Exception:
            log.debug("needs_review: pre_trade_log enrichment failed", exc_info=True)
            ptl_by_id = {}
        for o in out:
            for c in o.get("candidates", []):
                ptl = ptl_by_id.get(c.get("calc_id"))
                if not ptl:
                    continue
                # model_name is the operator's free-text label; fall back to the
                # model_id FK (F11 rendering rule) so picker-tagged calcs that
                # carry no free text still show an identity.
                c["model"] = ptl.get("model_name") or (
                    f"model #{ptl['model_id']}" if ptl.get("model_id") else None
                )
                c["model_id"] = ptl.get("model_id")
                c["r"] = ptl.get("est_r")
                c["tags"] = _parse_tags(ptl.get("tags"))
    return out
