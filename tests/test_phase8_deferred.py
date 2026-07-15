"""
Phase-8 deferred follow-ups (filed task 304 HANDOFF; closed this task).

Covers the two LOW audit items:

  #3a — base.html poll IIFEs stack duplicate setInterval timers across hx-boost
        <body> swaps. The P8.T7 notif IIFE was the only guarded one; the
        connection-poll and hold-time ticker timers are now guarded too.

  #3b — the cockpit per-calc Cancel button targets #ck-calc-alert, but the
        endpoint returned 409/404/500 on non-success, which htmx's global
        responseError handler swallows into a generic toast + retry fragment
        (never swapping the body). The endpoint now returns 200 for EVERY
        outcome with a status-discriminated alert body so htmx swaps it.

(Item #2 — the Export-Audit button — lives in test_phase8_position_events.py
where the drawer-render helpers already exist. Item #1 — /positions/open — was
left deferred: no JSON consumer is wired today.)

Run: pytest tests/test_phase8_deferred.py -v
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── #3b: cancel endpoint returns 200 + status-discriminated body ──────────────


class TestCancelRouteReturns200:
    """Intent (Rule 8): htmx swaps ONLY 2xx bodies into the hx-target. A 409/404/
    500 from this endpoint is swallowed by the global htmx:responseError handler
    (generic toast + "Couldn't load this section." retry), so the operator never
    sees the specific "not cancellable" / "race lost" reason. status_code MUST be
    200 for every outcome, with the outcome carried in the alert class + text."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "result, css_class, needle",
        [
            ("cancelled",        "alert-success", "Calc cancelled"),
            ("not_found",        "alert-error",   "not found"),
            ("not_cancellable",  "alert-warning", "no longer cancellable"),
            ("race_lost",        "alert-warning", "state changed during"),
            ("anything_else",    "alert-error",   "Cancel failed"),   # final else branch
        ],
    )
    async def test_every_outcome_is_200_with_discriminated_body(
        self, monkeypatch, result, css_class, needle,
    ):
        import api.routes_calculator as rc
        import core.handlers as handlers

        async def _fake_cancel(aid, calc_id, reason):
            return result

        # cancel_calc imports cancel_calc_by_operator from core.handlers at call
        # time, so patch the attribute on the module it's pulled from.
        monkeypatch.setattr(handlers, "cancel_calc_by_operator", _fake_cancel)
        monkeypatch.setattr(rc, "app_state", SimpleNamespace(active_account_id=1))

        resp = await rc.cancel_calc(request=None, calc_id="CALC-1", reason="")

        assert resp.status_code == 200          # load-bearing: htmx swaps only 2xx
        body = resp.body.decode()
        assert css_class in body                # outcome discriminated by class...
        assert needle.lower() in body.lower()   # ...and by text

    @pytest.mark.asyncio
    async def test_reason_is_forwarded_to_handler(self, monkeypatch):
        import api.routes_calculator as rc
        import core.handlers as handlers
        seen = {}

        async def _fake_cancel(aid, calc_id, reason):
            seen.update(aid=aid, calc_id=calc_id, reason=reason)
            return "cancelled"

        monkeypatch.setattr(handlers, "cancel_calc_by_operator", _fake_cancel)
        monkeypatch.setattr(rc, "app_state", SimpleNamespace(active_account_id=7))
        await rc.cancel_calc(request=None, calc_id="C9", reason="fat finger")
        assert seen == {"aid": 7, "calc_id": "C9", "reason": "fat finger"}


# ── #3a: poll-IIFE guards survive hx-boost <body> swaps ───────────────────────


class TestPollIifeGuards:
    """Intent (Rule 8): a boosted nav re-runs base.html's inline <script> IIFEs;
    window-scoped setInterval timers STACK one extra per nav unless guarded by a
    window._X flag (the P8.T7 notif IIFE is the reference pattern). These pin the
    guards so a future edit that drops one re-introduces the leak loudly."""

    def _base(self):
        with open("templates/base.html", encoding="utf-8") as fh:
            return fh.read()

    def test_hold_time_ticker_is_guarded(self):
        # Assert the load-bearing EARLY-RETURN, not just the flag name — a guard
        # that kept `window._holdTick = true` but dropped the `return` would
        # re-introduce the stacking leak while a name-only check stayed green.
        assert "if(window._holdTick) return" in self._base()

    def test_notif_poll_guard_still_present(self):
        # Regression anchor: the originally-guarded IIFE must stay guarded.
        assert "window._notifPoll" in self._base()


class TestListenerStackingGuards:
    """Phase-8 deferred #3c (closed task 307): the same hx-boost re-execution as
    #3a, but for `document(.body).addEventListener`. Listeners on the PERSISTENT
    document/body node accumulate one copy per boosted nav (the body node
    survives the innerHTML swap) — unlike element-scoped listeners, which die
    with the swapped element. The user-visible one was `htmx:responseError` → N
    duplicate error toasts + N target-swaps after N navs. Each previously
    UNguarded listener must now register once behind a window flag. Proximity
    checks ensure the flag actually wraps its listener (not a decorative name)."""

    def _base(self):
        with open("templates/base.html", encoding="utf-8") as fh:
            return fh.read()

    def test_account_added_guarded(self):
        src = self._base()
        i = src.index("_acctAddedBound")
        assert 'addEventListener("account-added"' in src[i:i + 240]

    def test_echarts_dispose_guarded(self):
        src = self._base()
        i = src.index("_echartsDisposeBound")
        assert "htmx:beforeSwap" in src[i:i + 280]

    def test_htmx_error_listeners_guarded(self):
        # the user-visible duplicate-toast one: BOTH error listeners sit under
        # one register-once guard (the IIFE ends right after them).
        src = self._base()
        i = src.index("_htmxErrBound")
        seg = src[i:i + 1500]
        assert "htmx:responseError" in seg and "htmx:sendError" in seg

    def test_steppers_listener_guarded(self):
        src = self._base()
        i = src.index("_stepperBound")
        assert "htmx:afterSettle" in src[i:i + 240]

    def test_dashtab_listener_guarded(self):
        src = self._base()
        i = src.index("_dashTabBound")
        assert "htmx:afterSettle" in src[i:i + 340]

    def test_hptab_listener_guarded(self):
        src = self._base()
        i = src.index("_hpTabBound")
        assert "htmx:afterSettle" in src[i:i + 340]

    def test_known_persistent_listener_guards_all_present(self):
        # Completeness anchor for the persistent-node LISTENER guards (#3c) + the
        # pre-existing notif listener guard. (The #3a TIMER guard _holdTick is a
        # setInterval, not a listener — covered by TestPollIifeGuards above; the
        # _connPoll plugin poller was removed with the Quantower UI in v2.6.)
        # A NEW unguarded document(.body).addEventListener added later
        # won't be covered here — update the guard AND this anchor together.
        src = self._base()
        for flag in ("_acctAddedBound", "_echartsDisposeBound", "_htmxErrBound",
                     "_stepperBound", "_dashTabBound", "_hpTabBound",
                     "_notifPoll"):
            assert flag in src, f"missing boost-stacking guard: {flag}"
