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

import re
from pathlib import Path

import jinja2


def _read_template(rel_path: str) -> str:
    return Path(rel_path).read_text(encoding="utf-8")


def _make_env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )


# ── PENDING branch exists in the countdown fragment ─────────────────────────

class TestCountdownTemplateHasPendingBranch:
    """The new PENDING state must be a distinct branch in the
    countdown fragment, separate from EXPIRED (which is terminal)."""

    def test_pending_branch_present(self):
        src = _read_template("templates/fragments/link_window_countdown.html")
        assert "PENDING" in src, (
            "FE-HIGH-009 regression: link_window_countdown.html is "
            "missing the PENDING state branch. Without it, the route "
            "handler's 'calc not in DB' case falls through to the "
            "old EXPIRED branch (terminal — polling stops)."
        )

    def test_pending_branch_keeps_polling(self):
        """The PENDING branch must include `hx-trigger=` so the widget
        keeps polling — this is the entire point of the new state.
        EXPIRED is terminal (no hx-trigger); PENDING is transient
        (must have hx-trigger)."""
        src = _read_template("templates/fragments/link_window_countdown.html")
        m = re.search(
            r"(?:elif|if)\s+s\s*==\s*[\"']PENDING[\"'].*?\{%\s*(?:elif|else|endif)",
            src,
            re.DOTALL,
        )
        assert m, "PENDING branch structure not found in template"
        body = m.group(0)
        assert "hx-trigger" in body, (
            "FE-HIGH-009: PENDING branch must include hx-trigger so "
            "the widget keeps polling until the calc appears in DB."
        )
        assert "hx-get" in body, (
            "FE-HIGH-009: PENDING branch must include hx-get with "
            "the calc_id so polling targets the right endpoint."
        )

    def test_pending_polls_faster_than_linkable(self):
        """PENDING uses fast-retry cadence (1s) vs LINKABLE's 5s — the
        race window is typically sub-second, so fast retry minimizes
        the user-visible 'Confirming...' duration."""
        src = _read_template("templates/fragments/link_window_countdown.html")
        m = re.search(
            r"(?:elif|if)\s+s\s*==\s*[\"']PENDING[\"'].*?\{%\s*(?:elif|else|endif)",
            src,
            re.DOTALL,
        )
        assert m
        body = m.group(0)
        assert "every 1s" in body, (
            "PENDING should poll at 1s for fast race-window recovery. "
            "5s would mean the user sees 'Confirming...' for up to 5s "
            "on every calc submit — too long."
        )

    def test_expired_branch_still_terminal(self):
        """Anti-regression: don't accidentally add hx-trigger to the
        EXPIRED branch. EXPIRED is genuinely terminal — once a calc's
        window has actually elapsed, polling forever wastes cycles."""
        src = _read_template("templates/fragments/link_window_countdown.html")
        m = re.search(
            r"elif\s+s\s*==\s*[\"']EXPIRED[\"'].*?\{%\s*(?:elif|else|endif)",
            src,
            re.DOTALL,
        )
        assert m, "EXPIRED branch not found"
        body = m.group(0)
        assert "hx-trigger" not in body, (
            "Anti-regression: EXPIRED is terminal — must NOT poll."
        )
        assert "hx-get" not in body, (
            "Anti-regression: EXPIRED must NOT have hx-get either."
        )


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

class TestCountdownFragmentRendersPendingState:
    """MED-047 discipline: compile-render the fragment with a PENDING
    context. Without this, a Jinja2 syntax error in the new branch
    would slip past source-string greps."""

    def test_pending_renders_with_polling(self):
        env = _make_env()
        tpl = env.get_template("fragments/link_window_countdown.html")
        ctx = {
            "calc_id": "test_calc_abc123",
            "lw": {
                "status": "PENDING",
                "remaining_s": 0,
                "effective_window_s": 21600,
            },
        }
        html = tpl.render(**ctx)
        assert "test_calc_abc123" in html, "calc_id not interpolated"
        assert "hx-get=" in html, "PENDING render missing hx-get"
        assert "hx-trigger=" in html, "PENDING render missing hx-trigger"
        assert "every 1s" in html, "PENDING render missing 1s cadence"
        assert "expired" not in html.lower(), (
            "PENDING render must not show 'expired' text — that's "
            "the bug the fix exists to prevent."
        )

    def test_expired_still_renders_terminal_state(self):
        """Anti-regression: rendering with status='EXPIRED' still
        produces the terminal (no-polling) fragment."""
        env = _make_env()
        tpl = env.get_template("fragments/link_window_countdown.html")
        ctx = {
            "calc_id": "test_calc_abc123",
            "lw": {
                "status": "EXPIRED",
                "remaining_s": 0,
                "effective_window_s": 21600,
            },
        }
        html = tpl.render(**ctx)
        assert "PLAN EXPIRED" in html
        assert "hx-get=" not in html, (
            "Anti-regression: EXPIRED render must NOT include hx-get."
        )
        assert "hx-trigger=" not in html

    def test_linkable_still_polls_at_5s(self):
        """Anti-regression: LINKABLE polling cadence unchanged."""
        env = _make_env()
        tpl = env.get_template("fragments/link_window_countdown.html")
        ctx = {
            "calc_id": "test_calc_abc123",
            "lw": {
                "status": "LINKABLE",
                "remaining_s": 21000,
                "effective_window_s": 21600,
            },
        }
        html = tpl.render(**ctx)
        assert "Linkable for:" in html
        assert "every 5s" in html


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
