"""
Phase 0 Task 6 (P0.T6) tests — state-machine enforcement helpers.

Verifies:

  1. CalcStatus enum + CALC_TRANSITIONS match spec §5 exactly:
     - Every catalogued transition is allowed
     - Terminal states accept no transitions out
     - Active states have the expected outgoing edges
  2. LinkStatus enum + LINK_TRANSITIONS match spec §6 exactly:
     - LINKED is forward-terminal (no transitions out)
     - NEEDS_MANUAL_REVIEW → LINKED + → UNPLANNED both allowed
     - UNLINKED → UNPLANNED allowed
  3. validate_transition / assert_transition behavior:
     - Unknown statuses (typos) return False / raise
     - IllegalStateTransition carries calc_id / order_id + current + target
  4. transition() choke-point:
     - On valid: calls apply_fn, emits event when target has topic
     - On invalid: raises IllegalStateTransition, DOES NOT call apply_fn
     - Event payload includes from_status, to_status, calc_id/order_id
     - reason + event_payload merge into emitted payload
     - apply_fn failure propagates (does NOT swallow); event NOT emitted
     - event_bus.publish failure does NOT roll back the DB UPDATE

Run: pytest tests/test_state_machines.py -v
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core import calc_state, link_state
from core.calc_state import CalcStatus, IllegalStateTransition as CalcIllegal
from core.link_state import LinkStatus, IllegalStateTransition as LinkIllegal


# ── 1. CalcStatus transitions match spec §5 ────────────────────────────


class TestCalcTransitionMatrix:
    @pytest.mark.parametrize("current, target", [
        # active → outgoing edges
        ("active", "matched"),
        ("active", "superseded"),
        ("active", "expired"),
        ("active", "cancelled_by_operator"),
        ("active", "partially_actioned"),
        # matched → outgoing edges
        ("matched", "completed_via_position"),
        ("matched", "released"),
        # released → outgoing edges (Phase 1.7)
        ("released", "matched"),
        ("released", "expired"),
        ("released", "superseded"),
        ("released", "cancelled_by_operator"),
        # partially_actioned → outgoing
        ("partially_actioned", "completed_via_position"),
        ("partially_actioned", "expired"),
    ])
    def test_valid_transition_returns_true(self, current, target):
        assert calc_state.validate_transition(current, target) is True

    @pytest.mark.parametrize("current, target", [
        # Terminal states accept nothing
        ("superseded", "active"),
        ("superseded", "matched"),
        ("expired", "active"),
        ("expired", "matched"),
        ("cancelled_by_operator", "active"),
        ("completed_via_position", "matched"),
        # Disallowed transitions (not in spec §5)
        ("active", "completed_via_position"),       # must go through matched/partially
        ("active", "released"),                     # only post-match
        ("matched", "active"),                      # no rollback
        ("matched", "expired"),                     # expired only from active/released/partially
        ("released", "completed_via_position"),     # must go through matched again
    ])
    def test_invalid_transition_returns_false(self, current, target):
        assert calc_state.validate_transition(current, target) is False

    def test_unknown_current_returns_false(self):
        assert calc_state.validate_transition("nope", "matched") is False

    def test_unknown_target_returns_false(self):
        assert calc_state.validate_transition("active", "frobnicate") is False

    def test_terminal_states_set_matches_spec(self):
        assert calc_state.TERMINAL_STATES == {
            CalcStatus.SUPERSEDED,
            CalcStatus.EXPIRED,
            CalcStatus.CANCELLED_BY_OPERATOR,
            CalcStatus.COMPLETED_VIA_POSITION,
        }
        for s in calc_state.TERMINAL_STATES:
            assert calc_state.CALC_TRANSITIONS[s] == set()

    def test_event_topic_map_covers_all_emitting_targets(self):
        # Per spec §5/§9: 6 transition events catalogued. P6.T3 — the map now
        # stores the calc:* EVENT name (the §9 "{domain}:{event}" suffix minus
        # the implicit calc domain); transition() prepends
        # engine:account:{id}:calc: via publish_engine.
        expected = {
            CalcStatus.MATCHED:                "linked",
            CalcStatus.SUPERSEDED:             "superseded",
            CalcStatus.EXPIRED:                "expired",
            CalcStatus.CANCELLED_BY_OPERATOR:  "cancelled",
            CalcStatus.COMPLETED_VIA_POSITION: "completed",
            CalcStatus.PARTIALLY_ACTIONED:     "partially_filled",
        }
        for status, event in expected.items():
            assert calc_state.TRANSITION_EVENT_MAP[status] == event


# ── 2. LinkStatus transitions match spec §6 ────────────────────────────


class TestLinkTransitionMatrix:
    @pytest.mark.parametrize("current, target", [
        ("NEEDS_MANUAL_REVIEW", "LINKED"),     # operator-link
        ("NEEDS_MANUAL_REVIEW", "UNPLANNED"),  # operator-mark
        ("UNLINKED", "UNPLANNED"),             # operator downgrade
        ("UNLINKED", "LINKED"),                # rare manual link after-the-fact
    ])
    def test_valid_transition_returns_true(self, current, target):
        assert link_state.validate_transition(current, target) is True

    @pytest.mark.parametrize("current, target", [
        # LINKED is forward-terminal
        ("LINKED", "NEEDS_MANUAL_REVIEW"),
        ("LINKED", "UNLINKED"),
        ("LINKED", "UNPLANNED"),
        # UNPLANNED is terminal
        ("UNPLANNED", "LINKED"),
        ("UNPLANNED", "NEEDS_MANUAL_REVIEW"),
        # NEEDS_MANUAL_REVIEW cannot become UNLINKED (would lose review state)
        ("NEEDS_MANUAL_REVIEW", "UNLINKED"),
    ])
    def test_invalid_transition_returns_false(self, current, target):
        assert link_state.validate_transition(current, target) is False

    def test_unknown_status_returns_false(self):
        assert link_state.validate_transition("nope", "LINKED") is False
        assert link_state.validate_transition("LINKED", "FROB") is False


# ── 3. Exception carries identifying context ───────────────────────────


class TestExceptionCarriesContext:
    def test_calc_exception_carries_calc_id_current_target(self):
        with pytest.raises(CalcIllegal) as exc_info:
            calc_state.assert_transition("calc-abc", "expired", "matched")
        assert exc_info.value.calc_id == "calc-abc"
        assert exc_info.value.current == "expired"
        assert exc_info.value.target == "matched"
        assert "calc-abc" in str(exc_info.value)

    def test_link_exception_carries_order_id_current_target(self):
        with pytest.raises(LinkIllegal) as exc_info:
            link_state.assert_transition(42, "LINKED", "NEEDS_MANUAL_REVIEW")
        assert exc_info.value.order_id == 42
        assert exc_info.value.current == "LINKED"
        assert exc_info.value.target == "NEEDS_MANUAL_REVIEW"
        assert "42" in str(exc_info.value)


# ── 4. transition() choke-point behavior (calc_state) ──────────────────


class TestCalcTransitionChokePoint:
    @pytest.mark.asyncio
    async def test_valid_calls_apply_then_emits_event(self, monkeypatch):
        # Capture event publishes via a mock.
        published = []

        async def fake_publish(channel, payload):
            published.append((channel, dict(payload)))

        from core import event_bus as ebmod
        monkeypatch.setattr(ebmod.event_bus, "publish", fake_publish)

        applied = {"called": False}

        async def apply_fn():
            applied["called"] = True

        await calc_state.transition(
            "calc-1", "active", "matched",
            apply_fn=apply_fn,
            account_id=2,
            event_payload={"order_id": 100},
        )
        assert applied["called"] is True
        assert len(published) == 1
        topic, payload = published[0]
        # P6.T3: per-account hierarchical topic (was the flat "calc:linked").
        assert topic == "engine:account:2:calc:linked"
        assert payload["calc_id"] == "calc-1"
        assert payload["from_status"] == "active"
        assert payload["to_status"] == "matched"
        assert payload["order_id"] == 100

    @pytest.mark.asyncio
    async def test_reason_included_in_event_payload(self, monkeypatch):
        published = []

        async def fake_publish(channel, payload):
            published.append((channel, dict(payload)))

        from core import event_bus as ebmod
        monkeypatch.setattr(ebmod.event_bus, "publish", fake_publish)

        async def apply_fn():
            pass

        await calc_state.transition(
            "calc-2", "active", "cancelled_by_operator",
            apply_fn=apply_fn,
            account_id=1,
            reason="operator gave up",
        )
        topic, payload = published[0]
        assert topic == "engine:account:1:calc:cancelled"
        assert payload["reason_note"] == "operator gave up"

    @pytest.mark.asyncio
    async def test_invalid_raises_does_not_call_apply(self):
        applied = {"called": False}

        async def apply_fn():
            applied["called"] = True

        with pytest.raises(CalcIllegal):
            await calc_state.transition(
                "calc-3", "expired", "matched",  # illegal
                apply_fn=apply_fn,
                account_id=1,
            )
        assert applied["called"] is False

    @pytest.mark.asyncio
    async def test_apply_failure_propagates(self):
        # If the caller's apply_fn raises, the helper re-raises.
        async def apply_fn():
            raise RuntimeError("db down")

        with pytest.raises(RuntimeError, match="db down"):
            await calc_state.transition(
                "calc-4", "active", "matched",
                apply_fn=apply_fn,
                account_id=1,
            )

    @pytest.mark.asyncio
    async def test_apply_failure_skips_event_emission(self, monkeypatch):
        # If apply_fn fails, the event MUST NOT fire (no partial state).
        published = []

        async def fake_publish(channel, payload):
            published.append((channel, dict(payload)))

        from core import event_bus as ebmod
        monkeypatch.setattr(ebmod.event_bus, "publish", fake_publish)

        async def apply_fn():
            raise RuntimeError("db down")

        with pytest.raises(RuntimeError):
            await calc_state.transition(
                "calc-5", "active", "matched",
                apply_fn=apply_fn,
                account_id=1,
            )
        assert published == []

    @pytest.mark.asyncio
    async def test_event_publish_failure_does_not_rollback(self, monkeypatch):
        # Critical invariant: a downstream event-bus failure must NOT
        # cause the caller to think the DB UPDATE didn't land. The
        # helper logs + swallows publish errors.
        async def failing_publish(channel, payload):
            raise RuntimeError("event_bus down")

        from core import event_bus as ebmod
        monkeypatch.setattr(ebmod.event_bus, "publish", failing_publish)

        applied = {"called": False}

        async def apply_fn():
            applied["called"] = True

        # No exception even though publish failed.
        await calc_state.transition(
            "calc-6", "active", "matched",
            apply_fn=apply_fn,
            account_id=1,
        )
        assert applied["called"] is True

    @pytest.mark.asyncio
    async def test_target_without_event_skips_publish(self, monkeypatch):
        # Phase 1.7 released transition has no catalogued event.
        published = []

        async def fake_publish(channel, payload):
            published.append((channel, dict(payload)))

        from core import event_bus as ebmod
        monkeypatch.setattr(ebmod.event_bus, "publish", fake_publish)

        async def apply_fn():
            pass

        await calc_state.transition(
            "calc-7", "matched", "released",
            apply_fn=apply_fn,
            account_id=1,
        )
        # released has no event in TRANSITION_EVENT_MAP; should NOT publish.
        assert published == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("current,target,event", [
        ("active",  "matched",                "linked"),
        ("active",  "superseded",             "superseded"),
        ("active",  "expired",                "expired"),
        ("active",  "cancelled_by_operator",  "cancelled"),
        ("matched", "completed_via_position", "completed"),
        ("active",  "partially_actioned",     "partially_filled"),
    ])
    async def test_emits_per_account_hierarchical_topic(
        self, monkeypatch, current, target, event,
    ):
        # P6.T3 (closes the audit's two Rule-8 gaps): EVERY calc transition
        # event must ride the spec §9 per-account topic
        # engine:account:{id}:calc:{event}. This pins (a) the hierarchical shape
        # for ALL 6 events — a regression to a flat "calc:{event}" topic FAILS
        # here — and (b) the account segment — a wrong/transposed account_id in
        # transition() FAILS here (account 7 ≠ the default 1).
        published = []

        async def fake_publish(channel, payload):
            published.append((channel, dict(payload)))

        from core import event_bus as ebmod
        monkeypatch.setattr(ebmod.event_bus, "publish", fake_publish)

        async def apply_fn():
            pass

        await calc_state.transition(
            "calc-acct", current, target, apply_fn=apply_fn, account_id=7,
        )
        assert len(published) == 1
        topic, _ = published[0]
        assert topic == f"engine:account:7:calc:{event}"


# ── 5. transition() choke-point behavior (link_state) ──────────────────


class TestLinkTransitionChokePoint:
    @pytest.mark.asyncio
    async def test_valid_calls_apply(self):
        applied = {"called": False}

        async def apply_fn():
            applied["called"] = True

        await link_state.transition(
            100, "NEEDS_MANUAL_REVIEW", "LINKED",
            apply_fn=apply_fn,
        )
        assert applied["called"] is True

    @pytest.mark.asyncio
    async def test_invalid_raises_does_not_call_apply(self):
        applied = {"called": False}

        async def apply_fn():
            applied["called"] = True

        with pytest.raises(LinkIllegal):
            await link_state.transition(
                100, "LINKED", "NEEDS_MANUAL_REVIEW",  # forward-terminal
                apply_fn=apply_fn,
            )
        assert applied["called"] is False

    @pytest.mark.asyncio
    async def test_no_event_topic_skips_publish_silently(self, monkeypatch):
        # Phase 6 may add link-status events; until then,
        # TRANSITION_EVENT_MAP is empty. transition() should complete
        # cleanly without publishing.
        published = []

        async def fake_publish(channel, payload):
            published.append((channel, dict(payload)))

        from core import event_bus as ebmod
        monkeypatch.setattr(ebmod.event_bus, "publish", fake_publish)

        async def apply_fn():
            pass

        await link_state.transition(
            100, "NEEDS_MANUAL_REVIEW", "UNPLANNED",
            apply_fn=apply_fn,
        )
        assert published == []
