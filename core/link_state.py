"""
Order link-status state machine — link_status enum, valid transitions,
transition choke-point.

Mirrors ``core/calc_state.py`` for the parallel ``orders.link_status``
state machine. Same choke-point discipline: validate → DB UPDATE →
event emission, all through a single helper.

State machine (spec §6):

    (arriving) ──auto-match─────────────────────> LINKED
        │
        ├──candidates exist, none full-match────> NEEDS_MANUAL_REVIEW
        │                                              │
        │                                              ├──operator-link──> LINKED
        │                                              └──operator-mark──> UNPLANNED
        │
        └──zero candidates in window────────────> UNPLANNED  (auto)

Once an order reaches LINKED, the link is treated as terminal for the
forward path. NEEDS_MANUAL_REVIEW → LINKED is allowed (operator action);
UNLINKED → UNPLANNED is allowed (operator downgrade); but LINKED ↔
NEEDS_MANUAL_REVIEW is NOT allowed (a verified link should not be
un-verified — operators investigate the link via a separate workflow).

Phase 0.6 (P0.T6) ships this module; Phase 3.1 (P3.T1) wires every
``orders.link_status`` write through it (spec §3.6 — no raw UPDATEs):

  - :func:`auto_classify` — ENGINE-driven assignment from an *undecided*
    source (NULL on first arrival, or UNPLANNED on a matcher re-run).
    Used by the strict matcher (``order_enrichment._try_correlate``,
    §4.3) and bracket inheritance (``order_manager.
    _propagate_bracket_calc_id``, §4.5).
  - :func:`transition` — OPERATOR-driven moves between *decided* states
    (NEEDS_MANUAL_REVIEW → LINKED, UNLINKED → UNPLANNED, …), validated
    against :data:`LINK_TRANSITIONS`. Wired by the Phase-3.2/3.3
    manual-link / mark-unplanned endpoints.

The split exists because the matcher legitimately upgrades UNPLANNED →
LINKED when newly-arriving calcs bring a previously candidate-less order
into a match — a move :func:`transition` (correctly) rejects, since for
the OPERATOR state machine UNPLANNED is terminal.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Awaitable, Callable, Dict, Optional, Set

log = logging.getLogger("link_state")


class LinkStatus(str, Enum):
    LINKED              = "LINKED"
    NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"
    UNLINKED            = "UNLINKED"
    UNPLANNED           = "UNPLANNED"


# Spec §6 diagram covers LINKED + NEEDS_MANUAL_REVIEW + UNPLANNED;
# UNLINKED is listed in spec §3.4 enum but omitted from the §6 diagram.
# Implementation includes UNLINKED + its operator-action transitions
# (UNLINKED → UNPLANNED and the rarer UNLINKED → LINKED for late
# manual-link discovery) per Phase 3.1 (link_status auto-classification)
# + Phase 3.4 (POST /orders/{id}/mark_unplanned endpoint).
#
# Engine-driven classification (the matcher + bracket inheritance
# assigning link_status from an UNDECIDED source — NULL on first arrival
# or UNPLANNED on a matcher re-run) does NOT appear in this table: it has
# no prior DECIDED enum to validate a move FROM, and UNPLANNED→LINKED is
# a legitimate re-classification this operator machine deliberately
# rejects. P3.T1 routes those writes through :func:`auto_classify`
# instead, so every orders.link_status write still funnels through this
# module (spec §3.6).
LINK_TRANSITIONS: Dict[LinkStatus, Set[LinkStatus]] = {
    LinkStatus.LINKED: {
        # LINKED is treated as terminal forward — no transitions out.
        # If an operator needs to reclassify a LINKED order, that's a
        # separate workflow (audit-trail-preserving) outside this
        # state machine.
    },
    LinkStatus.NEEDS_MANUAL_REVIEW: {
        LinkStatus.LINKED,     # operator manually links
        LinkStatus.UNPLANNED,  # operator marks as unplanned
    },
    LinkStatus.UNLINKED: {
        LinkStatus.UNPLANNED,  # operator downgrades to UNPLANNED
        LinkStatus.LINKED,     # rare: operator manually links a previously-
                               # unlinked order (e.g., found the calc later)
    },
    # Terminal — no transitions out
    LinkStatus.UNPLANNED: set(),
}


TERMINAL_STATES = {
    LinkStatus.LINKED,
    LinkStatus.UNPLANNED,
}

REVIEWABLE_STATES = {
    LinkStatus.NEEDS_MANUAL_REVIEW,
    LinkStatus.UNLINKED,
}

# Engine auto-classification targets (spec §4.3 matcher + §4.5 bracket
# inheritance). The matcher emits exactly these three from an undecided
# source; UNLINKED is operator-set only (never auto-assigned — see
# core/calc_correlation.py:44), so it is deliberately excluded and an
# auto_classify() to UNLINKED fails loud.
AUTO_CLASSIFY_TARGETS: Set[LinkStatus] = {
    LinkStatus.LINKED,
    LinkStatus.NEEDS_MANUAL_REVIEW,
    LinkStatus.UNPLANNED,
}


# Spec §9 / §6 don't catalogue dedicated link-status transition events
# (the per-account event bus in Phase 6 may add them). Reserved here
# so Phase 6 can wire topics without touching call sites.
TRANSITION_EVENT_MAP: Dict[LinkStatus, str] = {
    # Intentionally empty until Phase 6 catalogues link-status events.
    # The transition() helper still publishes for any future entry.
}


class IllegalStateTransition(Exception):
    """Raised when a link-status transition is rejected.

    Carries the order_id, current status, and attempted target so the
    caller (or audit logs) can identify the offending site.
    """

    def __init__(
        self, order_id: int, current: str, target: str,
        message: Optional[str] = None,
    ) -> None:
        self.order_id = order_id
        self.current = current
        self.target = target
        msg = message or (
            f"illegal link transition: {current!r} → {target!r} "
            f"(order_id={order_id!r})"
        )
        super().__init__(msg)


class LinkTransitionRaceLost(Exception):
    """Raised by a caller-supplied ``apply_fn`` when its UPDATE affects 0
    rows — another writer flipped ``orders.link_status`` (or set
    ``calc_id``) out of the expected state between the caller's SELECT and
    the apply_fn UPDATE.

    Mirror of :class:`core.calc_state.CalcTransitionRaceLost` for the order
    link-status TOCTOU guard. The operator manual-link / mark-unplanned
    handlers (P3.T2) raise it from their apply_fn on rowcount 0 and catch
    it to report a benign "raced" outcome rather than a hard error.
    """

    def __init__(
        self, order_id: int, expected: str, target: str,
        message: Optional[str] = None,
    ) -> None:
        self.order_id = order_id
        self.expected = expected
        self.target = target
        msg = message or (
            f"order {order_id!r} moved out of {expected!r} before UPDATE "
            f"to {target!r}; transition skipped"
        )
        super().__init__(msg)


def validate_transition(current: str, target: str) -> bool:
    """Return ``True`` if ``current → target`` is a valid transition.

    Unknown statuses (anything not in :class:`LinkStatus`) return
    ``False`` — defensive against typos and stale enum strings.
    """
    try:
        return LinkStatus(target) in LINK_TRANSITIONS[LinkStatus(current)]
    except (ValueError, KeyError):
        return False


def assert_transition(order_id: int, current: str, target: str) -> None:
    """Raise :class:`IllegalStateTransition` unless the transition is valid."""
    if not validate_transition(current, target):
        raise IllegalStateTransition(order_id, current, target)


ApplyFn = Callable[[], Awaitable[None]]


async def transition(
    order_id: int,
    current_status: str,
    target_status: str,
    *,
    apply_fn: ApplyFn,
    reason: Optional[str] = None,
    event_payload: Optional[Dict] = None,
) -> None:
    """Choke-point transition: validate → DB UPDATE → emit event.

    Mirrors :func:`core.calc_state.transition`. See that docstring
    for the order-of-operations rationale (validate first, then
    UPDATE, then event so handlers query the new state).

    Args:
        order_id: target order identifier (carried into the event payload
            and into :class:`IllegalStateTransition` on failure).
        current_status: the order's current ``orders.link_status`` value.
        target_status: the desired new status.
        apply_fn: async callable that performs the actual
            ``UPDATE orders SET link_status = ?, ...``. Supplied by the
            caller because some transitions write additional fields
            (e.g., ``UNPLANNED`` may set ``cancel_reason_category``).
        reason: optional free-text rationale. Included in the emitted
            event payload as ``reason_note``.
        event_payload: additional fields to merge into the emitted
            event payload.

    Raises:
        IllegalStateTransition: when the transition is not in
            :data:`LINK_TRANSITIONS`. ``apply_fn`` is NOT called.
    """
    assert_transition(order_id, current_status, target_status)
    await apply_fn()
    await _emit_link_event(
        order_id, current_status, target_status, reason, event_payload,
    )


async def _emit_link_event(
    order_id: int,
    from_status: Optional[str],
    target_status: str,
    reason: Optional[str],
    event_payload: Optional[Dict],
) -> None:
    """Publish the catalogued event for ``target_status`` (if any).

    Shared by :func:`transition` and :func:`auto_classify`.
    :data:`TRANSITION_EVENT_MAP` is empty until Phase 6 catalogues
    link-status events, so today this is a no-op for every target —
    factored out so BOTH entry points light up together the moment
    Phase 6 fills the map. Best-effort: a publish failure logs + is
    swallowed, never rolling back the DB UPDATE the caller already
    applied.
    """
    topic = TRANSITION_EVENT_MAP.get(LinkStatus(target_status))
    if topic is None:
        return
    from core.event_bus import event_bus
    payload = {
        "order_id": order_id,
        "from_status": from_status,
        "to_status": target_status,
    }
    if reason is not None:
        payload["reason_note"] = reason
    if event_payload:
        payload.update(event_payload)
    try:
        await event_bus.publish(topic, payload)
    except Exception:
        log.exception(
            "link_state: event_bus.publish failed for topic=%r order_id=%r",
            topic, order_id,
        )


def assert_auto_classify(order_id: int, target: str) -> None:
    """Raise :class:`IllegalStateTransition` unless ``target`` is a valid
    engine auto-classification (one of :data:`AUTO_CLASSIFY_TARGETS`)."""
    try:
        ok = LinkStatus(target) in AUTO_CLASSIFY_TARGETS
    except ValueError:
        ok = False
    if not ok:
        allowed = sorted(s.value for s in AUTO_CLASSIFY_TARGETS)
        raise IllegalStateTransition(
            order_id, "(auto)", target,
            message=(
                f"{target!r} is not a valid auto-classification target "
                f"(order_id={order_id!r}); allowed: {allowed}"
            ),
        )


async def auto_classify(
    order_id: int,
    target_status: str,
    *,
    apply_fn: ApplyFn,
    reason: Optional[str] = None,
    event_payload: Optional[Dict] = None,
) -> None:
    """Engine-driven link-status classification choke-point.

    The strict matcher (``core/order_enrichment._try_correlate``, spec
    §4.3) and bracket inheritance (``core/order_manager.
    _propagate_bracket_calc_id``, spec §4.5) assign ``orders.link_status``
    from an *undecided* source — NULL on first arrival, or UNPLANNED on a
    matcher re-run (a previously candidate-less order upgrades to
    LINKED / NEEDS_MANUAL_REVIEW when new calcs arrive). Neither has a
    prior DECIDED enum to validate a transition FROM, so this is NOT
    :func:`transition` (which validates current→target between existing
    enum values and — correctly for the operator machine — rejects both
    NULL→X and UNPLANNED→X).

    Same choke-point discipline as :func:`transition`: validate target →
    DB UPDATE (the caller's ``apply_fn``, which carries its own
    idempotency / WHERE guards) → emit any catalogued event. Routing
    both write sites here keeps every ``orders.link_status`` write inside
    this module (spec §3.6), so a future linter can flag raw UPDATEs and
    Phase 6 can wire link-status events in one place.

    Args:
        order_id: target order identifier (carried into the event payload
            and into :class:`IllegalStateTransition` on a bad target).
        target_status: the classification to assign — must be one of
            :data:`AUTO_CLASSIFY_TARGETS` (LINKED / NEEDS_MANUAL_REVIEW /
            UNPLANNED). UNLINKED is operator-set only and fails loud here.
        apply_fn: async callable performing the actual ``UPDATE orders
            SET link_status = ?, ...`` (the matcher also sets ``calc_id``
            in the same statement; the bracket path adds a
            ``WHERE calc_id IS NULL`` idempotency guard).
        reason / event_payload: merged into the emitted event (forward-
            compat; the event map is empty until Phase 6).

    Raises:
        IllegalStateTransition: when ``target_status`` is not an
            auto-classification target. ``apply_fn`` is NOT called.
    """
    assert_auto_classify(order_id, target_status)
    await apply_fn()
    await _emit_link_event(
        order_id, None, target_status, reason, event_payload,
    )
