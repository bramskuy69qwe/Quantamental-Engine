"""
Task 146 regression tests — FE-MED-032 (Calculator PENDING state has
no upper bound).

FE-MED-032 was filed Task 140 as a latent failure mode of Task 139's
PENDING short-circuit. If `handle_risk_calculated` fails to run
(event-bus consumer crash, DB INSERT constraint violation, disk error),
the pre-Task-146 route returned PENDING indefinitely. Frontend polled
1Hz forever; widget never surfaced the failure — silent-broken
instead of visibly-broken.

Fix (Task 146): cap PENDING at 5 seconds. Mechanism is server-side via
a `t0` query param echoed across the polling chain (Option 2 from
the task spec, chosen over Option 1 client-side JS for testability +
htmx-native idiom + no setTimeout throttling on inactive tabs).

Behavior:
  - First PENDING poll (t0=0): server sets t0 to current epoch_ms,
    echoes in the hx-get URL of the PENDING fragment.
  - Subsequent PENDING polls (t0>0): server compares now - t0 vs
    PENDING_TIMEOUT_MS (5000).
    - Within window → render PENDING, preserve t0.
    - Exceeded window → render ERROR (terminal — no hx-trigger).
  - Pretrade row appears in DB (race resolves) → normal state machine
    runs; t0 is irrelevant.

ERROR state is a new branch in `link_window_countdown.html` —
terminal, friendly user-facing text ("Submission failed to record —
please retry"), red border, no exception strings.

Run: pytest tests/test_task146_pending_timeout.py -v
"""
from __future__ import annotations

from pathlib import Path

import jinja2
import pytest


def _read_template(rel: str) -> str:
    return Path(rel).read_text(encoding="utf-8")


def _make_env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )


# ── Source-pin: route handler accepts t0 + has timeout logic ────────────────

class TestRouteHandlerAcceptsT0:
    def test_route_signature_includes_t0(self):
        src = Path("api/routes_calculator.py").read_text(encoding="utf-8")
        idx = src.find("async def calculator_link_window_status")
        assert idx > 0
        # Signature spans to closing `):`
        end = src.find("):", idx)
        sig = src[idx:end]
        assert "t0:" in sig.replace(" ", ""), (
            "FE-MED-032: route signature must accept `t0` query param. "
            "Without it, the PENDING timeout can't be tracked across "
            "polling chain (stateless server)."
        )

    def test_timeout_constant_defined(self):
        src = Path("api/routes_calculator.py").read_text(encoding="utf-8")
        idx = src.find("async def calculator_link_window_status")
        end = src.find("\n@router", idx)
        body = src[idx:end] if end > 0 else src[idx:]
        assert "PENDING_TIMEOUT_MS" in body, (
            "FE-MED-032: timeout constant must be named (not a magic "
            "number) so future maintainers can find + tune it."
        )
        # Default 5000 (5s — sub-second race + 5-cycle generous buffer)
        assert "5000" in body, (
            "Task 146 chose 5s; verify the literal is present so any "
            "future tuning shows up in diff."
        )

    def test_anchor_comments_reference_fe_med_032(self):
        for path in (
            "api/routes_calculator.py",
            "templates/fragments/link_window_countdown.html",
        ):
            src = _read_template(path) if path.endswith(".html") else Path(path).read_text(encoding="utf-8")
            assert "FE-MED-032" in src, (
                f"FE-MED-032 anchor missing in {path}"
            )


# ── Template branches: PENDING echoes t0, ERROR terminal ────────────────────

class TestPendingBranchEchoesT0:
    def test_pending_hx_get_has_t0_param(self):
        src = _read_template("templates/fragments/link_window_countdown.html")
        # Locate PENDING branch
        pending_idx = src.find('s == "PENDING"')
        # Find next branch (elif/else)
        end_idx = src.find("{% elif", pending_idx + 1)
        body = src[pending_idx:end_idx] if end_idx > 0 else src[pending_idx:]
        assert "?t0=" in body, (
            "FE-MED-032: PENDING branch must echo t0 in hx-get URL. "
            "Without it, the timeout chain breaks on each poll."
        )
        # The interpolation should reference the t0 context var
        assert "{{ t0 }}" in body


class TestErrorBranchTerminal:
    def test_error_branch_present(self):
        src = _read_template("templates/fragments/link_window_countdown.html")
        assert 's == "ERROR"' in src, (
            "FE-MED-032: ERROR branch must exist in countdown template."
        )

    def test_error_branch_has_no_hx_trigger(self):
        """ERROR is terminal — polling stops on render. Render via
        Jinja so doc-comments are stripped; pin against the actual
        rendered output, not the template source."""
        env = _make_env()
        tpl = env.get_template("fragments/link_window_countdown.html")
        html = tpl.render(
            calc_id="test_calc_abc",
            lw={"status": "ERROR", "effective_window_s": 21600, "remaining_s": 0},
        )
        assert "hx-trigger" not in html, (
            "ERROR is terminal — must NOT include hx-trigger or "
            "polling continues forever (defeating the timeout)."
        )
        assert "hx-get=" not in html

    def test_error_branch_has_user_friendly_text(self):
        """No raw exception strings; user-facing message + retry hint."""
        src = _read_template("templates/fragments/link_window_countdown.html")
        error_idx = src.find('s == "ERROR"')
        end_idx = src.find("{% elif", error_idx + 1)
        body = src[error_idx:end_idx] if end_idx > 0 else src[error_idx:]
        # Friendly phrase per task spec
        assert "failed to record" in body.lower() or "submission failed" in body.lower()
        # Suggests action
        assert "retry" in body.lower()
        # Should NOT contain Python-error-style strings
        for forbidden in ("Traceback", "Exception", "AttributeError", "OperationalError"):
            assert forbidden not in body, (
                f"ERROR branch must not surface raw exception text "
                f"({forbidden!r} found). FE-MED-031 family — keep "
                f"user-facing copy friendly."
            )


# ── Compile-render: ERROR branch renders cleanly ────────────────────────────

class TestErrorRendersCleanly:
    def test_error_render(self):
        env = _make_env()
        tpl = env.get_template("fragments/link_window_countdown.html")
        html = tpl.render(
            calc_id="test_calc_abc",
            lw={
                "status": "ERROR",
                "effective_window_s": 21600,
                "remaining_s": 0,
            },
        )
        # Terminal: no polling attributes
        assert "hx-get=" not in html
        assert "hx-trigger=" not in html
        # Friendly text visible
        assert "retry" in html.lower()
        assert "failed" in html.lower()


class TestPendingRendersWithT0:
    def test_pending_url_contains_t0(self):
        env = _make_env()
        tpl = env.get_template("fragments/link_window_countdown.html")
        html = tpl.render(
            calc_id="test_calc_abc",
            t0=1234567890123,
            lw={
                "status": "PENDING",
                "effective_window_s": 21600,
                "remaining_s": 0,
            },
        )
        assert "hx-get=" in html
        assert "?t0=1234567890123" in html, (
            f"PENDING render missing t0 query param. HTML: {html!r}"
        )
        assert 'hx-trigger="every 1s"' in html


# ── Route handler integration: timeout decision logic ───────────────────────

class TestRouteHandlerTimeoutDecision:
    """Test the timeout decision logic by importing the route and
    calling it with a mocked DB that always returns None (simulates
    the consumer-crash failure mode)."""

    @pytest.mark.asyncio
    async def test_first_poll_sets_t0_and_renders_pending(self, monkeypatch):
        """With t0=0 (first poll) AND pretrade missing → PENDING with
        t0 set to ~now."""
        from api import routes_calculator
        from unittest.mock import AsyncMock, MagicMock
        from starlette.requests import Request

        # Mock the db helpers used by the route to simulate the
        # consumer-crash scenario: pretrade row never appears.
        mock_db = MagicMock()
        mock_db.get_pretrade_timestamp_for_link_window = AsyncMock(return_value=None)
        mock_db.get_account_link_window_seconds = AsyncMock(return_value=21600)
        mock_db.has_confirmed_fill_for_calc = AsyncMock(return_value=False)
        # Patch the module-level db import (route imports as `_db`)
        monkeypatch.setattr("core.database.db", mock_db, raising=False)

        # Build a minimal Request stub
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/calculator/link-window-status/test_calc",
            "headers": [],
            "query_string": b"",
            "path_params": {"calc_id": "test_calc"},
        }
        req = Request(scope)

        response = await routes_calculator.calculator_link_window_status(
            req, calc_id="test_calc", t0=0,
        )
        body = response.body.decode("utf-8")
        # First poll: PENDING with a fresh t0 (non-zero, non-default)
        assert "Confirming calc" in body, "First poll should render PENDING"
        # The t0 in the URL should be non-zero
        assert "?t0=0" not in body, (
            "First poll should set t0 to now() (non-zero), not echo "
            "the default 0."
        )
        assert "?t0=" in body

    @pytest.mark.asyncio
    async def test_recent_t0_renders_pending(self, monkeypatch):
        """With t0 set to ~now (within timeout window) AND pretrade
        missing → still PENDING, t0 preserved."""
        import time
        from api import routes_calculator
        from unittest.mock import AsyncMock, MagicMock
        from starlette.requests import Request

        mock_db = MagicMock()
        mock_db.get_pretrade_timestamp_for_link_window = AsyncMock(return_value=None)
        mock_db.get_account_link_window_seconds = AsyncMock(return_value=21600)
        mock_db.has_confirmed_fill_for_calc = AsyncMock(return_value=False)
        monkeypatch.setattr("core.database.db", mock_db, raising=False)

        recent_t0 = int(time.time() * 1000) - 1000  # 1s ago — within 5s window
        scope = {
            "type": "http", "method": "GET", "path": "/x",
            "headers": [], "query_string": b"",
            "path_params": {"calc_id": "test_calc"},
        }
        req = Request(scope)
        response = await routes_calculator.calculator_link_window_status(
            req, calc_id="test_calc", t0=recent_t0,
        )
        body = response.body.decode("utf-8")
        assert "Confirming calc" in body
        # t0 preserved (not reset)
        assert f"?t0={recent_t0}" in body

    @pytest.mark.asyncio
    async def test_old_t0_renders_error(self, monkeypatch):
        """With t0 set to >5s ago AND pretrade missing → ERROR
        (terminal, no hx-trigger)."""
        import time
        from api import routes_calculator
        from unittest.mock import AsyncMock, MagicMock
        from starlette.requests import Request

        mock_db = MagicMock()
        mock_db.get_pretrade_timestamp_for_link_window = AsyncMock(return_value=None)
        mock_db.get_account_link_window_seconds = AsyncMock(return_value=21600)
        mock_db.has_confirmed_fill_for_calc = AsyncMock(return_value=False)
        monkeypatch.setattr("core.database.db", mock_db, raising=False)

        old_t0 = int(time.time() * 1000) - 10_000  # 10s ago — past 5s window
        scope = {
            "type": "http", "method": "GET", "path": "/x",
            "headers": [], "query_string": b"",
            "path_params": {"calc_id": "test_calc"},
        }
        req = Request(scope)
        response = await routes_calculator.calculator_link_window_status(
            req, calc_id="test_calc", t0=old_t0,
        )
        body = response.body.decode("utf-8")
        # ERROR state rendered
        assert "failed to record" in body.lower() or "submission failed" in body.lower()
        # Terminal — no hx-trigger
        assert "hx-trigger" not in body
        assert "hx-get=" not in body


# ── Anti-regression: PENDING → LINKABLE on normal race-resolve ──────────────

class TestNormalRaceResolveStillWorks:
    """Task 139 anti-regression: once the pretrade row appears in DB,
    the route returns LINKABLE/EXPIRED/etc via the normal state
    machine. The PENDING timeout logic must NOT short-circuit
    successful resolution."""

    @pytest.mark.asyncio
    async def test_pretrade_found_returns_linkable_regardless_of_t0(
        self, monkeypatch,
    ):
        """Pretrade appears mid-polling → LINKABLE wins regardless of t0."""
        import time
        from api import routes_calculator
        from unittest.mock import AsyncMock, MagicMock
        from starlette.requests import Request

        # Pretrade now exists — simulates the race resolving
        now_ms = int(time.time() * 1000)
        recent_ts_iso = "2026-05-19T12:00:00+00:00"
        mock_db = MagicMock()
        mock_db.get_pretrade_timestamp_for_link_window = AsyncMock(return_value={
            "timestamp": recent_ts_iso,
            "link_window_seconds_override": None,
        })
        mock_db.get_account_link_window_seconds = AsyncMock(return_value=21600)
        mock_db.has_confirmed_fill_for_calc = AsyncMock(return_value=False)
        monkeypatch.setattr("core.database.db", mock_db, raising=False)

        # Even with an old t0 — once pretrade is in DB, the normal
        # state machine runs, NOT the PENDING-timeout ERROR branch.
        old_t0 = now_ms - 10_000  # past 5s window
        scope = {
            "type": "http", "method": "GET", "path": "/x",
            "headers": [], "query_string": b"",
            "path_params": {"calc_id": "test_calc"},
        }
        req = Request(scope)
        response = await routes_calculator.calculator_link_window_status(
            req, calc_id="test_calc", t0=old_t0,
        )
        body = response.body.decode("utf-8")
        # Should NOT be ERROR — pretrade was found, state machine wins
        assert "failed to record" not in body.lower()
        assert "submission failed" not in body.lower()
        # Should be LINKED_CONFIRMED, LINKABLE, EXPIRING_SOON, or EXPIRED
        # (depends on the iso timestamp's relation to now; here ~6h
        # back, so likely EXPIRING_SOON or EXPIRED depending on
        # exact timing). The key invariant: PENDING-timeout ERROR
        # is NOT triggered when pretrade exists.
