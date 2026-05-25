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

Phase 0.6 (P0.T6) ships this helper; Phase 3.1 (P3.T1) wires the
matcher and the manual-link endpoint to route every link_status change
through ``transition()``.
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


# Spec §6 + §3.4 operator-action transitions. Initial-arrival
# transitions (None → any) are handled by the matcher at insert time,
# not via this state machine.
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

    target_enum = LinkStatus(target_status)
    topic = TRANSITION_EVENT_MAP.get(target_enum)
    if topic is not None:
        from core.event_bus import event_bus
        payload = {
            "order_id": order_id,
            "from_status": current_status,
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
                "link_state.transition: event_bus.publish failed for "
                "topic=%r order_id=%r",
                topic, order_id,
            )
