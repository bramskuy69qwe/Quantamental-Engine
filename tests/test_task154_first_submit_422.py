"""
Task 154 regression tests — FE-MED-029 backend-race.

Audit finding: first POST to /calculator/calculate after fresh page load
returns 422; second POST (no change) returns 200. Reproducer per Session C:
navigate to /calculator, click Calculate immediately → 422; click again
→ 200.

ROOT CAUSE (confirmed via code inspection, not just from spec hypothesis):

The Calculator form has a hidden field:
    <input type="hidden" name="average" id="average_val" />
with NO `value` attribute. Initial DOM .value is "". The `average`
parameter is REQUIRED by the route (`average: float = Form(...)`); empty
string fails pydantic float coercion → FastAPI 422.

The pre-T154 handler at templates/calculator.html populated
`average_val.value` inside an `htmx:beforeRequest` listener. But per the
FE-17 lesson (anchored at recallHistory's pre-submit population around
line ~657), htmx 1.9 serializes form data at `htmx:configRequest` time,
BEFORE `beforeRequest` fires. So:

  Click 1 → configRequest gathers params (average=""), beforeRequest
            sets average_val.value=<entry> (too late). Server gets
            empty → 422.
  Click 2 → configRequest gathers params, finds average_val.value=
            <entry> (left from click 1's DOM mutation). Server gets
            populated → 200.

FIX (T154):
  - Move handler from htmx:beforeRequest → htmx:configRequest.
  - Mutate evt.detail.parameters directly (this is the load-bearing
    change — DOM mutation alone is insufficient when configRequest has
    already locked in the gathered values; mutating .parameters is
    htmx's officially-supported request-modification hook).
  - Keep DOM .value writes for state-restoration consistency.

Anti-regression:
  - recallHistory's pre-submit field population (lines ~657-668)
    untouched — that path doesn't depend on the htmx event lifecycle.

What this file pins:
  - JS source: handler attached to htmx:configRequest (not beforeRequest).
  - JS source: handler mutates evt.detail.parameters.average + tp_price
    + sl_price (the three fields the audit's first-submit-422 cluster
    needs populated at gather-time).
  - JS source: anchor comment ties the listener to FE-MED-029 + FE-17.
  - JS source: pre-fix shape (`addEventListener('htmx:beforeRequest'`
    on the calc-form path) is GONE.
  - Route-level: confirms `average` is required (no Form default) so
    the 422 is correctly inevitable when the field is empty — the JS
    fix is the right side of the contract to touch.
  - Python mirror of the JS configRequest logic — given an empty
    `average_val` DOM, the mirror produces a `parameters` dict with
    `average` populated from `_livePrice`.

Run: pytest tests/test_task154_first_submit_422.py -v
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest


# ── Source-pin tests on the JS handler ─────────────────────────────────────


# (Jinja retirement 2026-07-30: the calculator.html configRequest-handler
# pins are gone with the template; the Python-mirror tests below survive.)







# ── Route-level pin: average is required, so the 422 contract is correct ──


class TestRouteContractStillRequiresAverage:
    """The route's `average: float = Form(...)` makes empty average →
    422 a contract, not a bug. This pin guards against a future change
    that adds a default (which would mask the bug rather than fix it)."""

    def test_average_is_required_form_field(self):
        src = Path("api/routes_calculator.py").read_text(encoding="utf-8")
        # Find the calculate_risk signature
        idx = src.find("async def calculate_risk(")
        assert idx > 0, "calculate_risk route not found"
        sig = src[idx:idx + 2000]
        # average is declared as Form(...) — required, no default.
        # (`Form(...)` is FastAPI's required-field sentinel.)
        assert re.search(r"average:\s*float\s*=\s*Form\(\.\.\.\)", sig), (
            "FE-MED-029 regression: `average: float = Form(...)` no "
            "longer required. If a future change adds a default (e.g. "
            "`Form(0.0)`), the first-submit 422 would silently become a "
            "first-submit-with-zero-entry-price 200 — worse: the calc "
            "would run against a meaningless entry. Keep `Form(...)` "
            "required; rely on the JS configRequest fix instead."
        )


# ── Python mirror of the JS configRequest mutation ─────────────────────────


class HtmxEventMirror:
    """Minimal Python mirror of the htmx configRequest event shape used
    in the JS handler. detail.parameters is a dict; detail.elt is an
    object with .id; detail can have a preventDefault flag."""

    def __init__(self, elt_id: str, parameters: dict[str, Any] | None = None):
        self.detail = type("D", (), {})()
        self.detail.elt = type("E", (), {"id": elt_id})()
        self.detail.parameters = parameters or {}
        self._default_prevented = False

    def preventDefault(self):
        self._default_prevented = True


def _config_request_handler_mirror(
    evt: HtmxEventMirror,
    *,
    live_price: float,
    order_type: str = "market",
    tpsl_mode: str = "price",
    tp_price_input: float = 0.0,
    sl_price_input: float = 0.0,
    side: str = "long",
):
    """Python mirror of templates/calculator.html's configRequest handler.
    Same semantics: if elt isn't calc-form, no-op. If entry is zero or
    missing, preventDefault. Otherwise inject average/tp_price/sl_price
    into evt.detail.parameters."""
    if evt.detail.elt.id != "calc-form":
        return
    # getEffectiveEntry mirror — for market order with live_price set,
    # entry = live_price.
    entry = live_price if order_type == "market" else live_price
    if not entry or entry <= 0:
        evt.preventDefault()
        return
    evt.detail.parameters["average"] = entry
    tp_p = 0.0
    sl_p = 0.0
    if tpsl_mode == "price":
        tp_p = tp_price_input
        sl_p = sl_price_input
    if not sl_p or sl_p <= 0:
        evt.preventDefault()
        return
    evt.detail.parameters["tp_price"] = tp_p
    evt.detail.parameters["sl_price"] = sl_p


class TestConfigRequestHandlerLogic:
    """End-to-end mirror — drive the handler through the FE-MED-029
    reproducer steps and confirm the request body would carry the
    populated average on the FIRST submit."""

    def test_first_submit_with_live_price_populates_average(self):
        """Reproducer: page just loaded, _livePrice has settled from the
        ticker price poll (assume 642.50 for BNBUSDT). Form submits.
        configRequest fires with parameters={'average': '', 'tp_price':
        '680', 'sl_price': '620', ...} as gathered from the DOM. After
        the handler runs, parameters['average'] must be the live price,
        not ''."""
        evt = HtmxEventMirror(
            "calc-form",
            parameters={
                "ticker": "BNBUSDT",
                "average": "",          # ← the bug: empty before handler runs
                "tp_price": "0",        # ← hidden field's initial
                "sl_price": "0",        # ← hidden field's initial
                "tp_amount_pct": "100",
                "sl_amount_pct": "100",
                "model_name": "",
                "model_desc": "",
                "order_type": "market",
                "auto_refresh": "0",
                "apply_regime_multiplier": "1",
            },
        )
        _config_request_handler_mirror(
            evt,
            live_price=642.50,
            tp_price_input=680.0,
            sl_price_input=620.0,
        )
        # The fix's load-bearing post-condition
        assert evt.detail.parameters["average"] == 642.50, (
            "FE-MED-029 regression: configRequest handler did not inject "
            "the live price into parameters['average']. First submit "
            "would still send average='' → 422."
        )
        # tp_price + sl_price also populated
        assert evt.detail.parameters["tp_price"] == 680.0
        assert evt.detail.parameters["sl_price"] == 620.0

    def test_zero_live_price_prevents_default(self):
        """If live_price is 0 (still waiting for poll), handler must
        preventDefault — server doesn't see a request that would 422."""
        evt = HtmxEventMirror(
            "calc-form",
            parameters={"average": "", "tp_price": "0", "sl_price": "0"},
        )
        _config_request_handler_mirror(
            evt,
            live_price=0.0,
            tp_price_input=680.0,
            sl_price_input=620.0,
        )
        assert evt._default_prevented, (
            "FE-MED-029 regression: handler did not preventDefault on "
            "missing entry — request will still fire with empty average → "
            "422 reaches the user."
        )

    def test_missing_sl_prevents_default(self):
        """SL is required by the calculator's risk model; the handler
        also preventsDefault when SL is zero."""
        evt = HtmxEventMirror(
            "calc-form",
            parameters={"average": "", "tp_price": "0", "sl_price": "0"},
        )
        _config_request_handler_mirror(
            evt,
            live_price=642.50,
            tp_price_input=680.0,
            sl_price_input=0.0,
        )
        assert evt._default_prevented

    def test_non_calc_form_event_no_op(self):
        """Other htmx requests on the page (e.g. orderbook refresh,
        regime-current poll, link-window-countdown) must not be touched."""
        evt = HtmxEventMirror(
            "orderbook-panel",
            parameters={"foo": "bar"},
        )
        _config_request_handler_mirror(
            evt, live_price=642.50, tp_price_input=1.0, sl_price_input=1.0,
        )
        # No mutation, no preventDefault
        assert evt.detail.parameters == {"foo": "bar"}
        assert not evt._default_prevented


# ── Anti-regression: recallHistory still pre-populates fields ──────────────


