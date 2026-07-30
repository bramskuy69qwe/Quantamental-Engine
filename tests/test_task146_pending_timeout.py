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

Behavior (fragments slim-down 2026-07-30: the route is JSON-only —
link_window_countdown.html is retired; the t0 chain now rides the JSON
body and the React Pre-Trade page echoes it back on each poll):
  - First PENDING poll (t0=0): server sets t0 to current epoch_ms,
    echoes it in the JSON body.
  - Subsequent PENDING polls (t0>0): server compares now - t0 vs
    PENDING_TIMEOUT_MS (5000).
    - Within window → status PENDING, t0 preserved.
    - Exceeded window → status ERROR (terminal — client stops polling).
  - Pretrade row appears in DB (race resolves) → normal state machine
    runs; t0 is irrelevant.

Run: pytest tests/test_task146_pending_timeout.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _body_json(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


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
        # (2026-07-30: the countdown template retired with the fragments
        # slim-down — the route body is the sole surviving anchor site.)
        src = Path("api/routes_calculator.py").read_text(encoding="utf-8")
        assert "FE-MED-032" in src, "FE-MED-032 anchor missing in routes_calculator.py"


# ── Route handler integration: timeout decision logic ───────────────────────

class TestRouteHandlerTimeoutDecision:
    """Test the timeout decision logic by importing the route and
    calling it with a mocked DB that always returns None (simulates
    the consumer-crash failure mode). The route is JSON-only since the
    fragments slim-down — assertions pin the JSON body."""

    @pytest.mark.asyncio
    async def test_first_poll_sets_t0_and_returns_pending(self, monkeypatch):
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
        body = _body_json(response)
        assert body["status"] == "PENDING", "First poll should return PENDING"
        # The t0 echo should be non-zero (set to now(), not the default 0)
        assert body.get("t0", 0) > 0, (
            "First poll should set t0 to now() (non-zero), not echo "
            "the default 0."
        )
        assert body["calc_id"] == "test_calc"

    @pytest.mark.asyncio
    async def test_recent_t0_returns_pending(self, monkeypatch):
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
        body = _body_json(response)
        assert body["status"] == "PENDING"
        # t0 preserved (not reset)
        assert body["t0"] == recent_t0

    @pytest.mark.asyncio
    async def test_old_t0_returns_error(self, monkeypatch):
        """With t0 set to >5s ago AND pretrade missing → ERROR
        (terminal — the client stops polling on it)."""
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
        body = _body_json(response)
        assert body["status"] == "ERROR"
        # Terminal — no t0 echo (nothing left to chain)
        assert "t0" not in body


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
        """Pretrade appears mid-polling → the state machine wins
        regardless of t0."""
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
        # debug 2026-06-08: countdown now checks calc status for a terminal
        # LINKED state; 'active' = not-yet-matched -> falls through to LINKABLE.
        mock_db.get_calc_status = AsyncMock(return_value="active")
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
        body = _body_json(response)
        # Should NOT be ERROR — pretrade was found, state machine wins.
        # (Exact status depends on the iso timestamp's relation to now —
        # LINKABLE / EXPIRING_SOON / EXPIRED; the key invariant is the
        # PENDING-timeout ERROR is NOT triggered when pretrade exists.)
        assert body["status"] != "ERROR"
        assert body["status"] in {
            "LINKABLE", "EXPIRING_SOON", "EXPIRED", "LINKED", "LINKED_CONFIRMED",
        }

    @pytest.mark.asyncio
    async def test_matched_calc_returns_terminal_linked(self, monkeypatch):
        """debug 2026-06-08: once the matcher links the calc (status 'matched'),
        the countdown shows a terminal LINKED state — not the bare time-window
        countdown (which an auto-matched calc would otherwise show until expiry,
        so the operator never sees the link land)."""
        from api import routes_calculator
        from unittest.mock import AsyncMock, MagicMock
        from starlette.requests import Request

        mock_db = MagicMock()
        mock_db.get_pretrade_timestamp_for_link_window = AsyncMock(return_value={
            "timestamp": "2026-06-08T05:19:33+00:00",
            "link_window_seconds_override": None,
        })
        mock_db.get_account_link_window_seconds = AsyncMock(return_value=300)
        mock_db.has_confirmed_fill_for_calc = AsyncMock(return_value=False)
        mock_db.get_calc_status = AsyncMock(return_value="matched")
        monkeypatch.setattr("core.database.db", mock_db, raising=False)

        scope = {
            "type": "http", "method": "GET", "path": "/x",
            "headers": [], "query_string": b"",
            "path_params": {"calc_id": "test_calc"},
        }
        response = await routes_calculator.calculator_link_window_status(
            Request(scope), calc_id="test_calc", t0=0,
        )
        body = _body_json(response)
        assert body["status"] == "LINKED"  # terminal — client stops polling
        assert "t0" not in body
