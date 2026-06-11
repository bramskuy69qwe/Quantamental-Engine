"""
Calc lifecycle state machine — status enum, valid transitions, transition
choke-point.

Mirrors ``core/order_state.py`` for ``order.status``; extended with a
``transition()`` choke-point that validates + (optionally) emits the
spec-defined event on the in-process event_bus per spec §3.6.

State machine (spec §5):

    active ──supersede──> superseded
       │
       ├──order full-match──> matched ──> completed_via_position
       │                          │
       │                     ──order cancel──> released ──> matched (re-match)
       │
       ├──partial fill + no further──> partially_actioned ──> completed_via_position
       ├──operator cancel──> cancelled_by_operator
       └──window expires──> expired

Events emitted (spec §5):
    calc:linked            on transition to ``matched``
    calc:superseded        on transition to ``superseded``
    calc:cancelled         on transition to ``cancelled_by_operator``
    calc:expired           on transition to ``expired``
    calc:partially_filled  on transition to ``partially_actioned``
    calc:completed         on transition to ``completed_via_position``

NOTE: ``calc:created`` (on insert) is NOT a transition — emitted at row
creation by the matcher handler, not from this state machine.

Phase 0.6 (P0.T6) ships this helper; Phase 1.1 (P1.T1) wires the
matcher to route every status change through ``transition()`` so events
fire automatically and illegal transitions raise.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Awaitable, Callable, Dict, Optional, Set

from core import correlation_log

log = logging.getLogger("calc_state")


class CalcStatus(str, Enum):
    ACTIVE                 = "active"
    MATCHED                = "matched"
    SUPERSEDED             = "superseded"
    EXPIRED                = "expired"
    CANCELLED_BY_OPERATOR  = "cancelled_by_operator"
    COMPLETED_VIA_POSITION = "completed_via_position"
    PARTIALLY_ACTIONED     = "partially_actioned"
    RELEASED               = "released"


# Spec §5 covers all transitions except RELEASED, which is a forward
# extension per Phase 1.7 (calc release on order cancel): when a
# linked order is cancelled by the operator, the calc transitions
# back to ``released`` and is eligible for re-match within its
# original window. Transitions OUT of ``released`` mirror the
# original outgoing edges of ``active`` (re-match, expire, supersede,
# cancel) so the calc continues its lifecycle naturally.
CALC_TRANSITIONS: Dict[CalcStatus, Set[CalcStatus]] = {
    CalcStatus.ACTIVE: {
        CalcStatus.MATCHED,                 # full match found
        CalcStatus.SUPERSEDED,              # operator recalc creates newer
        CalcStatus.EXPIRED,                 # window elapsed
        CalcStatus.CANCELLED_BY_OPERATOR,
        CalcStatus.PARTIALLY_ACTIONED,      # partial fill, no further action
    },
    CalcStatus.MATCHED: {
        CalcStatus.COMPLETED_VIA_POSITION,  # position closes
        CalcStatus.RELEASED,                # linked order cancelled (Phase 1.7)
    },
    CalcStatus.RELEASED: {
        CalcStatus.MATCHED,                 # replacement order re-matches (Phase 1.7)
        CalcStatus.EXPIRED,                 # window elapses before re-match
        CalcStatus.SUPERSEDED,              # operator recalculates instead
        CalcStatus.CANCELLED_BY_OPERATOR,
    },
    CalcStatus.PARTIALLY_ACTIONED: {
        CalcStatus.COMPLETED_VIA_POSITION,  # remaining qty fills + position closes
        CalcStatus.EXPIRED,                 # window elapses with residual planned qty
    },
    # Terminal — no transitions out
    CalcStatus.SUPERSEDED:             set(),
    CalcStatus.EXPIRED:                set(),
    CalcStatus.CANCELLED_BY_OPERATOR:  set(),
    CalcStatus.COMPLETED_VIA_POSITION: set(),
}


TERMINAL_STATES = {
    CalcStatus.SUPERSEDED,
    CalcStatus.EXPIRED,
    CalcStatus.CANCELLED_BY_OPERATOR,
    CalcStatus.COMPLETED_VIA_POSITION,
}

ACTIVE_STATES = {
    CalcStatus.ACTIVE,
    CalcStatus.MATCHED,
    CalcStatus.RELEASED,
    CalcStatus.PARTIALLY_ACTIONED,
}


# Per spec §5/§9: each transition target maps to its calc:* EVENT name — the
# §9 "{domain}:{event}" topic suffix with the domain dropped (this module is
# calc-only, so the domain is implicitly event_bus.DOMAIN_CALC). P6.T3:
# transition() builds the full per-account topic
# ``engine:account:{id}:calc:{event}`` via event_bus.publish_engine. No entry =
# no event (e.g. the ``released → matched`` re-match, and RELEASED itself —
# covered by Phase 1.7's replacement-modal scaffold, which surfaces UI directly).
TRANSITION_EVENT_MAP: Dict[CalcStatus, str] = {
    CalcStatus.MATCHED:                "linked",
    CalcStatus.SUPERSEDED:             "superseded",
    CalcStatus.EXPIRED:                "expired",
    CalcStatus.CANCELLED_BY_OPERATOR:  "cancelled",
    CalcStatus.COMPLETED_VIA_POSITION: "completed",
    # NB (holistic-audit [3]): calc:partially_filled has NO live producer — nothing
    # transitions a calc INTO partially_actioned yet (spec §16; pre-Phase-6 gap).
    # Phase 6 wired the POSITION-side position:partial_close event, but the
    # CALC-side partially_actioned producer remains deferred, so this entry is
    # forward-scaffolding (it lights up the moment a producer is added).
    CalcStatus.PARTIALLY_ACTIONED:     "partially_filled",
}


class IllegalStateTransition(Exception):
    """Raised when a state-machine transition is rejected.

    Carries the calc_id, current status, and attempted target so the
    caller (or audit logs) can identify the offending site.
    """

    def __init__(
        self, calc_id: str, current: str, target: str,
        message: Optional[str] = None,
    ) -> None:
        self.calc_id = calc_id
        self.current = current
        self.target = target
        msg = message or (
            f"illegal calc transition: {current!r} → {target!r} "
            f"(calc_id={calc_id!r})"
        )
        super().__init__(msg)


class CalcTransitionRaceLost(Exception):
    """Raised by a caller-supplied ``apply_fn`` when its UPDATE affects
    0 rows — another writer flipped ``pre_trade_log.status`` out of the
    expected ``current_status`` between the caller's SELECT and the
    apply_fn UPDATE.

    Consolidates T211 ``_StatusFlipLostRace`` (order_enrichment matcher
    path) and T214 ``_SupersedeLostRace`` (handlers supersede path) —
    same shape, both raised when a TOCTOU-guarded UPDATE loses the race.
    Catching this in :func:`transition`'s caller is the signal to skip
    event-bus emission for a calc that no longer holds the expected
    state.

    Carries the calc_id, expected (matcher-time) status, and the target
    status the apply_fn was attempting — useful for logs.
    """

    def __init__(
        self, calc_id: str, expected: str, target: str,
        message: Optional[str] = None,
    ) -> None:
        self.calc_id = calc_id
        self.expected = expected
        self.target = target
        msg = message or (
            f"calc {calc_id!r} moved out of {expected!r} before "
            f"UPDATE to {target!r}; transition skipped"
        )
        super().__init__(msg)


def validate_transition(current: str, target: str) -> bool:
    """Return ``True`` if ``current → target`` is a valid transition.

    Unknown statuses (anything not in :class:`CalcStatus`) return
    ``False`` — defensive against typos and stale enum strings.
    """
    try:
        return CalcStatus(target) in CALC_TRANSITIONS[CalcStatus(current)]
    except (ValueError, KeyError):
        return False


def assert_transition(calc_id: str, current: str, target: str) -> None:
    """Raise :class:`IllegalStateTransition` unless the transition is valid.

    Convenience wrapper around :func:`validate_transition` that carries
    the calc_id into the exception so the audit trail is unambiguous.
    """
    if not validate_transition(current, target):
        raise IllegalStateTransition(calc_id, current, target)


# Type alias: the caller-supplied DB-apply callback. Always async.
ApplyFn = Callable[[], Awaitable[None]]


async def transition(
    calc_id: str,
    current_status: str,
    target_status: str,
    *,
    apply_fn: ApplyFn,
    account_id: int,
    reason: Optional[str] = None,
    event_payload: Optional[Dict] = None,
) -> None:
    """Choke-point transition: validate → DB UPDATE → emit event.

    Order matters: validation MUST come before UPDATE (so failures
    don't leave half-applied state), and the event MUST come after
    UPDATE (so handlers querying DB see the new state, not the old).

    Args:
        calc_id: target calc identifier (carried into the event payload
            and into :class:`IllegalStateTransition` on failure).
        current_status: the calc's current ``pre_trade_log.status`` value
            (caller reads this before invoking; we don't re-read to
            avoid a TOCTOU window between the read and the validate-
            then-apply sequence).
        target_status: the desired new status.
        apply_fn: async callable that performs the actual
            ``UPDATE pre_trade_log SET status = ?, ...`` — supplied by
            the caller because the full SET clause varies (e.g.,
            ``superseded`` writes ``superseded_by_calc_id`` too;
            ``cancelled_by_operator`` writes ``cancelled_reason``).
        account_id: owning account — scopes the emitted event onto the
            P6 per-account topic ``engine:account:{account_id}:calc:{event}``
            (spec §9). Required (keyword-only) so every transition site
            supplies it explicitly; every calc operation is account-scoped.
        reason: optional free-text reason (cancelled_by_operator,
            superseded). Included in the emitted event payload as
            ``reason_note``.
        event_payload: additional fields to merge into the emitted
            event payload (e.g., ``filled_pct`` for partially_actioned,
            ``new_calc_id`` for superseded).

    Raises:
        IllegalStateTransition: when the transition is not in
            :data:`CALC_TRANSITIONS`. ``apply_fn`` is NOT called.
    """
    assert_transition(calc_id, current_status, target_status)

    # 2. Apply DB UPDATE.
    await apply_fn()

    # corr-tap: calc_transition (CL.T3a, spec §5.5) — fires for EVERY applied
    # transition at this chokepoint (the bus event below fires only for
    # catalogued targets). A failed apply_fn (e.g. CalcTransitionRaceLost)
    # emits nothing: the transition did not apply.
    correlation_log.emit(
        "calc_state", "internal", "internal",
        correlation_log.CAT_CALC_TRANSITION,
        {
            "calc_id": calc_id,
            "from":    current_status,
            "to":      target_status,
            "reason":  reason,
        },
        account_id=account_id,
    )

    # 3. Emit transition event (if this target has a catalogued event).
    target_enum = CalcStatus(target_status)
    event = TRANSITION_EVENT_MAP.get(target_enum)
    if event is not None:
        from core.event_bus import event_bus, DOMAIN_CALC
        payload = {
            "calc_id": calc_id,
            "from_status": current_status,
            "to_status": target_status,
        }
        if reason is not None:
            # T215 H1: spec §9 lists ``reason`` for calc:superseded and
            # ``reason_note`` for calc:cancelled — internally inconsistent.
            # Emit BOTH keys (same value) so spec-conformant consumers
            # can key off either; back-compat with the existing
            # ``reason_note`` convention is preserved.
            payload["reason"] = reason
            payload["reason_note"] = reason
        if target_enum is CalcStatus.SUPERSEDED:
            # T215 H1: spec §9 names the field ``old_calc_id`` for the
            # calc:superseded event (the calc that was superseded), with
            # ``new_calc_id`` carried via event_payload. We already emit
            # ``calc_id`` (=old) for transition-payload uniformity across
            # all calc:* events; add the spec alias so downstream
            # consumers (Phase 1.7 replacement modal, audit-export
            # bundle) read the spec name without breaking the existing
            # uniformity.
            payload["old_calc_id"] = calc_id
        if event_payload:
            payload.update(event_payload)
        try:
            # P6.T3: per-account hierarchical topic
            # engine:account:{account_id}:calc:{event} (spec §9), built in one
            # place by event_bus.publish_engine (P6.T1 wrapper).
            await event_bus.publish_engine(account_id, DOMAIN_CALC, event, payload)
        except Exception:
            # Event-bus publish is best-effort — never roll back the DB
            # UPDATE on an event failure. Log + move on.
            log.exception(
                "calc_state.transition: event_bus.publish_engine failed for "
                "account=%s event=calc:%s calc_id=%r",
                account_id, event, calc_id,
            )
