"""
Task 104b regression tests for HIGH-027 frontend.

Backend half landed in Task 104a (schema, compute_exec_match window,
caller updates). This task adds:
- compute_link_window_status helper (state machine: LINKABLE /
  EXPIRING_SOON / EXPIRED / LINKED_CONFIRMED).
- Account settings UI (preset dropdown + server validation).
- Per-calc override (calculator form + persistence).
- Countdown polling fragment.

Run: pytest tests/test_task104b_link_window_ui.py -v
"""
from __future__ import annotations

import asyncio
import inspect
import time
from pathlib import Path

import pytest


# ── compute_link_window_status state machine ─────────────────────────────────

class TestComputeLinkWindowStatus:
    """Four-state helper. Tests at the unit level — no DB, no HTTP."""

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def test_linkable_state_remaining_seconds_positive(self):
        from core.exec_link import compute_link_window_status
        now = self._now_ms()
        pretrade_ts = now - 60 * 1000  # 1 min ago
        r = compute_link_window_status(
            pretrade_ts_ms=pretrade_ts,
            account_link_window_seconds=21600,  # 6 h
            now_ms=now,
        )
        assert r["status"] == "LINKABLE"
        assert r["remaining_s"] > 0
        assert r["effective_window_s"] == 21600

    def test_expiring_soon_when_under_5_min(self):
        from core.exec_link import compute_link_window_status
        now = self._now_ms()
        # 6 h window, opened 5h57m ago → 3 min remaining → expiring soon
        pretrade_ts = now - (6 * 3600 - 180) * 1000
        r = compute_link_window_status(
            pretrade_ts_ms=pretrade_ts,
            account_link_window_seconds=21600,
            now_ms=now,
        )
        assert r["status"] == "EXPIRING_SOON"
        assert 0 < r["remaining_s"] <= 300

    def test_expired_when_past_window(self):
        from core.exec_link import compute_link_window_status
        now = self._now_ms()
        pretrade_ts = now - 8 * 3600 * 1000  # 8 h ago
        r = compute_link_window_status(
            pretrade_ts_ms=pretrade_ts,
            account_link_window_seconds=21600,
            now_ms=now,
        )
        assert r["status"] == "EXPIRED"
        assert r["remaining_s"] == 0

    def test_linked_confirmed_takes_precedence_over_expired(self):
        """Load-bearing pin: even when past the window, an operator-confirmed
        link must render as LINKED_CONFIRMED, not EXPIRED."""
        from core.exec_link import compute_link_window_status
        now = self._now_ms()
        pretrade_ts = now - 24 * 3600 * 1000  # 24 h ago — way past 6h window
        r = compute_link_window_status(
            pretrade_ts_ms=pretrade_ts,
            account_link_window_seconds=21600,
            exec_link_confirmed=True,
            now_ms=now,
        )
        assert r["status"] == "LINKED_CONFIRMED", (
            "Confirmed-past-expiry must show as LINKED_CONFIRMED, not EXPIRED. "
            f"Got {r['status']!r}."
        )

    def test_per_calc_override_overrides_account_default(self):
        """24 h override beats 6 h account default for a 12 h fill."""
        from core.exec_link import compute_link_window_status
        now = self._now_ms()
        pretrade_ts = now - 12 * 3600 * 1000  # 12 h ago

        # Without override → EXPIRED (12h > 6h)
        r1 = compute_link_window_status(
            pretrade_ts_ms=pretrade_ts,
            account_link_window_seconds=21600,
            now_ms=now,
        )
        assert r1["status"] == "EXPIRED"

        # With 24 h override → LINKABLE
        r2 = compute_link_window_status(
            pretrade_ts_ms=pretrade_ts,
            account_link_window_seconds=21600,
            override_seconds=86400,
            now_ms=now,
        )
        assert r2["status"] == "LINKABLE"
        assert r2["effective_window_s"] == 86400

    def test_missing_pretrade_ts_returns_expired(self):
        """Defensive: pretrade row without a timestamp → EXPIRED. Caller
        should never reach here, but the helper must not crash."""
        from core.exec_link import compute_link_window_status
        r = compute_link_window_status(
            pretrade_ts_ms=None,
            account_link_window_seconds=21600,
        )
        assert r["status"] == "EXPIRED"
        assert r["remaining_s"] == 0

    def test_zero_window_returns_expired(self):
        from core.exec_link import compute_link_window_status
        now = self._now_ms()
        r = compute_link_window_status(
            pretrade_ts_ms=now,
            account_link_window_seconds=0,
            now_ms=now,
        )
        assert r["status"] == "EXPIRED"

    def test_constants(self):
        """Pin EXPIRING_SOON_THRESHOLD_S and MAX_LINK_WINDOW_SECONDS so the
        template (which uses these implicitly via the state classification)
        and the validators stay in sync."""
        from core.exec_link import (
            DEFAULT_LINK_WINDOW_SECONDS,
            EXPIRING_SOON_THRESHOLD_S,
            MAX_LINK_WINDOW_SECONDS,
        )
        assert DEFAULT_LINK_WINDOW_SECONDS == 21600
        assert EXPIRING_SOON_THRESHOLD_S == 300
        assert MAX_LINK_WINDOW_SECONDS == 86400


# ── Account settings: link_window_seconds validation + persistence ───────────

class TestAccountLinkWindowEndpoint:
    """Source-pin + behavior pins for /accounts/{id}/update accepting
    link_window_seconds with validation."""

    def test_routes_accounts_update_handler_accepts_link_window_seconds(self):
        from api import routes_accounts
        src = inspect.getsource(routes_accounts.update_account_detail)
        assert "link_window_seconds" in src, (
            "HIGH-027 wiring regression: update_account_detail no longer "
            "accepts link_window_seconds Form param."
        )

    def test_routes_accounts_validates_negative(self):
        """Source pin: the validator rejects values < 1."""
        from api import routes_accounts
        src = inspect.getsource(routes_accounts.update_account_detail)
        assert "at least 1 second" in src

    def test_routes_accounts_validates_upper_bound(self):
        """Source pin: the validator references MAX_LINK_WINDOW_SECONDS."""
        from api import routes_accounts
        src = inspect.getsource(routes_accounts.update_account_detail)
        assert "MAX_LINK_WINDOW_SECONDS" in src

    @pytest.mark.asyncio
    async def test_account_registry_update_persists_link_window(self):
        """End-to-end inside the registry: update_account(link_window_seconds=...)
        propagates to the DB write + cache update."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from core.account_registry import AccountRegistry

        ar = AccountRegistry.__new__(AccountRegistry)
        ar._lock = asyncio.Lock()
        ar._cache = {7: {"id": 7, "name": "t", "link_window_seconds": 21600}}
        ar._active_id = 7

        captured = {}
        async def _fake_update(account_id, **kwargs):
            captured["account_id"] = account_id
            captured["kwargs"] = kwargs

        with patch("core.account_registry.db",
                   MagicMock(update_account=_fake_update)), \
             patch("core.account_registry._audit"):
            await ar.update_account(7, link_window_seconds=14400)

        assert captured["kwargs"].get("link_window_seconds") == 14400
        assert ar._cache[7]["link_window_seconds"] == 14400


# ── Calculator per-calc override: form + persistence + endpoint ──────────────

class TestCalculatorOverrideWiring:
    """Source-pin pattern for the calc form's override input + the calculate
    handler's parse-and-validate-and-attach logic."""

    def test_calculator_handler_accepts_override_form_param(self):
        from api import routes_calculator
        src = inspect.getsource(routes_calculator.calculate_risk)
        assert "link_window_seconds_override" in src
        # The parser must coerce blank/invalid to "no override"
        assert "MAX_LINK_WINDOW_SECONDS" in src

    def test_calculator_attaches_override_to_calc_dict(self):
        """The handler must put the parsed override in calc['link_window_seconds_override']
        before publishing — handle_risk_calculated forwards the dict to
        insert_pre_trade_log."""
        from api import routes_calculator
        src = inspect.getsource(routes_calculator.calculate_risk)
        assert 'calc["link_window_seconds_override"]' in src

    def test_db_trades_insert_persists_override(self):
        """The INSERT and the values dict both reference the override column."""
        from core import db_trades
        src = inspect.getsource(db_trades.TradesMixin.insert_pre_trade_log)
        assert "link_window_seconds_override" in src
        # The INSERT column list must include it (catches a half-fix where
        # the dict-value was added but the SQL still misses it).
        assert ":link_window_seconds_override" in src

    def test_calculator_template_has_override_input(self):
        """Template-source pin: calculator.html must include the override
        select named link_window_seconds_override."""
        path = Path("templates") / "calculator.html"
        src = path.read_text(encoding="utf-8")
        assert 'name="link_window_seconds_override"' in src

    def test_countdown_endpoint_registered(self):
        """The polling endpoint must exist on the router. We assert by
        importing the module and checking the function's presence + path."""
        from api import routes_calculator
        # The function exists
        assert hasattr(routes_calculator,
                       "calculator_link_window_status")
        src = inspect.getsource(routes_calculator.calculator_link_window_status)
        # Path declaration is the route decorator immediately above
        module_src = inspect.getsource(routes_calculator)
        assert "/calculator/link-window-status/{calc_id}" in module_src


# ── Template wiring pins ────────────────────────────────────────────────────

class TestTemplateWiring:
    def test_calc_result_template_includes_countdown_polling(self):
        """HIGH-027 wiring pin (Task 104b): calc_result.html includes the
        countdown element with HTMX polling. Catches a regression where the
        countdown gets accidentally removed during template refactor."""
        path = Path("templates") / "fragments" / "calc_result.html"
        src = path.read_text(encoding="utf-8")
        assert 'id="link-window-countdown"' in src
        assert "/calculator/link-window-status/" in src
        assert 'hx-trigger="load, every 5s"' in src

    def test_account_detail_template_has_link_window_section(self):
        """Account settings editor must render the link-window section
        with a preset dropdown named link_window_seconds."""
        path = Path("templates") / "fragments" / "account_detail.html"
        src = path.read_text(encoding="utf-8")
        assert 'name="link_window_seconds"' in src
        # Must show all four UX states' presets — at minimum the default 6h
        assert "6 h (default)" in src
        # Must reference the current value in the UI
        assert "lw_current" in src

    def test_countdown_fragment_renders_all_four_states(self):
        """All four state branches must exist in the countdown fragment;
        otherwise a state transition would render a blank element."""
        path = Path("templates") / "fragments" / "link_window_countdown.html"
        src = path.read_text(encoding="utf-8")
        for state in ("LINKABLE", "EXPIRING_SOON", "EXPIRED", "LINKED_CONFIRMED"):
            assert state in src, (
                f"HIGH-027 frontend regression: countdown fragment is missing "
                f"the {state!r} branch."
            )
        # Active polling on the still-running states
        assert 'hx-trigger="every 5s"' in src
        # Visual differentiation: each state must have its own border color
        # (red for EXPIRED, green for LINKABLE / LINKED_CONFIRMED, amber for
        # EXPIRING_SOON). Approximated via the var(--*) css custom-property
        # references.
        assert "var(--red)" in src
        assert "var(--green)" in src
        assert "var(--amber)" in src
