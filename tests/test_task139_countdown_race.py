"""
Task 139 regression tests — FE-HIGH-009 + FE-MED-030 (Calculator
countdown widget race-condition cluster).

Root cause (confirmed hypothesis 2):
  POST /calculator/calculate calls `await event_bus.publish(...)` which
  only enqueues to an asyncio.Queue — the actual `insert_pre_trade_log`
  runs on a separate task drained by `EventBus.run()`. The route
  handler returns `calc_result.html` containing an empty
  `<div hx-trigger="load,every 5s" hx-get="/calculator/link-window-
  status/{calc_id}">`. The browser fires `load` almost immediately;
  the GET races against the pending insert.

  When the GET wins the race, `/calculator/link-window-status/{calc_id}`
  queries pre_trade_log, finds no row, computes
  `compute_link_window_status(pretrade_ts_ms=None)` → returns
  `status="EXPIRED"`. The EXPIRED branch in
  `link_window_countdown.html` has NO `hx-trigger` (terminal state by
  design — once a calc is genuinely expired, polling should stop).
  So the widget renders EXPIRED + polling stops + widget is stuck
  visually on EXPIRED for the lifetime of the page.

  Same race explains FE-MED-030 (30s old calc shows EXPIRED): the
  FIRST poll fired during the race window, got EXPIRED, polling
  stopped. The visible "30s old" timing is the screenshot timing,
  not the poll timing — by the time the screenshot was taken the
  widget was already stuck at EXPIRED from the race-window poll.

Fix (Task 139): introduce a new "PENDING" state for the
  "calc_id not in DB yet" case. Route handler detects pretrade=None
  and returns the PENDING fragment. PENDING branch in
  link_window_countdown.html keeps polling at 1s (vs LINKABLE's
  5s — fast retry during the race window). Once the insert lands,
  the next poll picks up the real state.

  No change to `compute_link_window_status` — its "None ts → EXPIRED"
  behavior is correct as a pure function (e.g., called with a stale
  state argument, EXPIRED is the conservative answer). The fix lives
  at the route-handler layer where the "DB row missing" vs "DB row
  expired" distinction is observable.

Run: pytest tests/test_task139_countdown_race.py -v
"""
from __future__ import annotations

from pathlib import Path


# ── PENDING branch exists in the countdown fragment ─────────────────────────


# ── Route handler returns PENDING when pretrade row is missing ──────────────

class TestRouteHandlerReturnsPendingForMissingPretrade:
    """The route handler must distinguish 'calc_id not in DB yet'
    (transient race) from 'calc_id was in DB and timer ran out'
    (genuine EXPIRED). The former returns PENDING."""

    def test_route_handler_has_pending_branch(self):
        """Source-pin: routes_calculator.py contains explicit handling
        for the pretrade=None case that returns a PENDING-state
        context dict."""
        src = Path("api/routes_calculator.py").read_text(encoding="utf-8")
        idx = src.find("async def calculator_link_window_status")
        assert idx > 0
        end = src.find("\n@router", idx)
        body = src[idx:end] if end > 0 else src[idx:]
        assert "PENDING" in body, (
            "FE-HIGH-009: routes_calculator.py "
            "calculator_link_window_status must include a PENDING "
            "branch for the pretrade-not-found case."
        )

    def test_pending_branch_short_circuits_before_compute(self):
        """The PENDING return must happen BEFORE the call to
        compute_link_window_status."""
        src = Path("api/routes_calculator.py").read_text(encoding="utf-8")
        idx = src.find("async def calculator_link_window_status")
        end = src.find("\n@router", idx)
        body = src[idx:end] if end > 0 else src[idx:]
        pending_idx = body.find("PENDING")
        compute_idx = body.find("compute_link_window_status(")
        assert pending_idx > 0 and compute_idx > 0
        assert pending_idx < compute_idx, (
            "PENDING handling must short-circuit before the call to "
            "compute_link_window_status."
        )

    def test_anchor_comment_present(self):
        """Anchor comment in route handler so future maintainers
        understand why the PENDING short-circuit exists."""
        src = Path("api/routes_calculator.py").read_text(encoding="utf-8")
        idx = src.find("async def calculator_link_window_status")
        end = src.find("\n@router", idx)
        body = src[idx:end] if end > 0 else src[idx:]
        assert "FE-HIGH-009" in body or "Task 139" in body


# ── Compile-render: countdown fragment renders the PENDING state cleanly ────


# ── Route handler builds PENDING status dict directly ────────────────────────

class TestRouteHandlerPendingDictShape:
    """Source-pin: the PENDING branch in the route handler constructs
    a status dict with the right keys (so the template render doesn't
    KeyError) BEFORE rendering, NOT a call to compute_link_window_status."""

    def test_pending_dict_includes_required_keys(self):
        src = Path("api/routes_calculator.py").read_text(encoding="utf-8")
        idx = src.find("async def calculator_link_window_status")
        end = src.find("\n@router", idx)
        body = src[idx:end] if end > 0 else src[idx:]
        # Find the dict-literal PENDING (skip comment-block mentions).
        # The dict literal uses `"status": "PENDING"` with quotes.
        dict_pending_idx = body.find('"status": "PENDING"')
        assert dict_pending_idx > 0, (
            "PENDING status dict not found in route handler — the "
            "handler must construct a dict like "
            '{"status": "PENDING", "effective_window_s": ...} '
            "for the template render."
        )
        # The dict spans a few lines; window of 300 chars covers it
        window = body[dict_pending_idx:dict_pending_idx + 300]
        assert "effective_window_s" in window, (
            "PENDING status dict must include effective_window_s — "
            "the template's other branches read lw.effective_window_s "
            "and consistency keeps the render context shape stable."
        )
