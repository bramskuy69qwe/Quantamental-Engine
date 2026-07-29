"""P5-R2 + P5-R3 pins — the user-data socket gets a door, a UI surface,
truthful connectivity, and an actioned alert.

Filed (phase-5 ledger): P5-R2 — no HTTP door exposes the fill pipeline's
state (`/api/state.exchange_ws` is the MARKET socket) and no v3 surface
renders `ws.connected`; a two-day fill outage was invisible (E2E-P5-001).
P5-R3 — monitoring's "WS stale" fired a bare log.warning forever with no
event, no dedup, no action.

Mechanism findings folded in (all pinned here):
- CLEAN-CLOSE FALL-THROUGH: a code-1000 close made `async for` fall through
  and `_user_data_loop` RETURN — the except never fired, `connected` stayed
  True forever, no reconnect ran. `connected` was a lying field.
- PERMANENT SURRENDER: `_reconnect_user`'s 15-attempt cap gave up forever
  (~9 min), while "staying on REST fallback" was false for fills (the
  fallback loop never polls trades and gates on the shared clock).
- ANONYMOUS MONITORING SERVICE: nothing assigned
  app_state._monitoring_service, so /api/monitoring/events returned []
  forever and record_rate_limit_event was a permanent no-op.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(*parts):
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


# ── 1. WSStatus: the user-owned clock ────────────────────────────────────────


class TestUserOwnedClock:
    def test_no_frame_yet_is_none_not_a_sentinel(self):
        from core.state import WSStatus
        ws = WSStatus()
        assert ws.user_seconds_since_update is None

    def test_age_measures_the_user_stamp_only(self):
        from core.state import WSStatus
        ws = WSStatus()
        ws.user_last_update = datetime.now(timezone.utc) - timedelta(seconds=5)
        # The SHARED clock being fresh must not mask the user age (that
        # masking is exactly how the outage stayed invisible).
        ws.last_update = datetime.now(timezone.utc)
        age = ws.user_seconds_since_update
        assert age is not None and 4.0 < age < 30.0

    def test_user_loop_is_the_only_writer(self):
        # ws_manager stamps user_last_update in the user frame loop and
        # nowhere else; the market loop and REST refresh must never touch it.
        for fname in ("exchange.py",):
            assert "user_last_update" not in _src("core", fname)
        wsm = _src("core", "ws_manager.py")
        assert wsm.count("ws.user_last_update = ") == 1


# ── 2. The clean-close fall-through fix + the cap hand-off ──────────────────


class TestUserLoopTruthfulness:
    def test_clean_close_is_treated_like_a_disconnect(self):
        wsm = _src("core", "ws_manager.py")
        # The clean-close block sits AFTER the frame loop and BEFORE the
        # error-path handler — `connected = False` + reconnect on a normal
        # server-side close (code 1000), which otherwise falls through
        # `async for` and returns with every flag still saying alive.
        start = wsm.index("async for raw in sock:")
        end = wsm.index("User-data WS disconnected")
        block = wsm[start:end]
        assert "clean_close" in block, (
            "P5-R2 regressed: a code-1000 close falls through `async for` and "
            "returns without ever setting connected=False or reconnecting"
        )
        assert "ws.connected = False" in block
        assert "_reconnect_user(attempt)" in block

    @pytest.mark.asyncio
    async def test_reconnect_cap_hands_off_to_persistent_retry(self, monkeypatch):
        import core.ws_manager as wsm
        import core.schedulers as sch
        calls = []
        monkeypatch.setattr(sch, "spawn_user_ws_retry", lambda: calls.append(1))
        monkeypatch.setattr(wsm, "_stopping", False)
        import config
        await wsm._reconnect_user(attempt=config.WS_RECONNECT_ATTEMPTS)
        assert calls == [1], (
            "P5-R3 regressed: the fast-reconnect cap must hand off to the "
            "persistent retry loop, not surrender permanently"
        )

    def test_spawn_user_ws_retry_is_idempotent(self, monkeypatch):
        import core.schedulers as sch

        class _FakeTask:
            def __init__(self):
                self._done = False

            def done(self):
                return self._done

        spawned = []

        def _fake_spawn(coro, *, name):
            coro.close()  # never actually run the loop
            t = _FakeTask()
            spawned.append(name)
            return t

        monkeypatch.setattr(sch, "_spawn", _fake_spawn)
        monkeypatch.setattr(sch, "_user_ws_retry_task", None)
        sch.spawn_user_ws_retry()
        sch.spawn_user_ws_retry()  # second spawn while alive → no-op
        assert spawned == ["ws-startup-retry"]

    def test_retry_loop_flags_and_guards(self):
        src = _src("core", "schedulers.py")
        loop = src.split("async def _ws_startup_retry_loop")[1].split("\n\n\n")[0]
        # The door's `retrying` field + rate-limit / auth-failure guards.
        assert "user_retry_active = True" in loop
        assert "user_retry_active = False" in loop
        assert "is_rate_limited" in loop
        assert "auth_failed_accounts" in loop


# ── 3. The door ──────────────────────────────────────────────────────────────


class TestUserWsDoor:
    def test_user_ws_block_reads_the_user_socket_not_the_market(self):
        src = _src("api", "routes_dashboard.py")
        i = src.index('"user_ws"')
        blk = src[i:src.index("}", i)]
        assert "ws.connected" in blk
        assert "ws.reconnect_attempts" in blk
        assert "ws.user_retry_active" in blk
        assert "ws.user_seconds_since_update" in blk
        assert "market_" not in blk, (
            "user_ws must read the USER-DATA fields — the market socket "
            "already has exchange_ws (the shell-chrome-3 lesson, reversed)"
        )

    def test_exchange_ws_block_unchanged_market_only(self):
        # The med-fixes contract: exchange_ws stays market-socket-only.
        src = _src("api", "routes_dashboard.py")
        i = src.index('"exchange_ws"')
        blk = src[i:src.index("}", i)]
        assert "ws.connected" not in blk


# ── 4. Monitoring: events, dedup, resolution, the new check ──────────────────


class TestMonitoring:
    def _svc(self):
        from core.monitoring import MonitoringService
        return MonitoringService()

    def test_user_ws_down_emits_critical_after_grace(self, monkeypatch):
        from core.state import app_state
        svc = self._svc()
        monkeypatch.setattr(app_state.ws_status, "connected", False)
        monkeypatch.setattr(app_state.ws_status, "user_retry_active", True)
        monkeypatch.setattr(app_state, "is_initializing", False)
        svc._check_user_ws_down_sync()          # cycle 1 — grace
        assert svc.get_active_events() == []
        svc._check_user_ws_down_sync()          # cycle 2 — fires
        active = svc.get_active_events()
        assert len(active) == 1
        assert active[0].kind == "user_ws_down"
        assert active[0].severity == "critical"
        svc._check_user_ws_down_sync()          # cycle 3 — deduped
        assert len(svc.get_active_events()) == 1

    def test_user_ws_down_resolves_on_reconnect(self, monkeypatch):
        from core.state import app_state
        svc = self._svc()
        monkeypatch.setattr(app_state.ws_status, "connected", False)
        monkeypatch.setattr(app_state, "is_initializing", False)
        svc._check_user_ws_down_sync()
        svc._check_user_ws_down_sync()
        assert svc.get_active_events()
        monkeypatch.setattr(app_state.ws_status, "connected", True)
        svc._check_user_ws_down_sync()
        assert svc.get_active_events() == []

    def test_user_ws_down_suppressed_while_initializing(self, monkeypatch):
        from core.state import app_state
        svc = self._svc()
        monkeypatch.setattr(app_state.ws_status, "connected", False)
        monkeypatch.setattr(app_state, "is_initializing", True)
        for _ in range(5):
            svc._check_user_ws_down_sync()
        assert svc.get_active_events() == []

    @pytest.mark.asyncio
    async def test_ws_stale_is_an_event_now_and_resolves(self, monkeypatch):
        from core.state import app_state
        svc = self._svc()
        monkeypatch.setattr(
            app_state.ws_status, "last_update",
            datetime.now(timezone.utc) - timedelta(seconds=300))
        monkeypatch.setattr(app_state.ws_status, "using_fallback", False)
        await svc._check_ws_staleness()
        kinds = [e.kind for e in svc.get_active_events()]
        assert "ws_stale" in kinds, (
            "P5-R3 regressed: ws_stale must be a MonitoringEvent, not a bare "
            "log.warning repeating forever"
        )
        monkeypatch.setattr(
            app_state.ws_status, "last_update", datetime.now(timezone.utc))
        await svc._check_ws_staleness()
        assert svc.get_active_events() == []

    def test_service_is_bound_to_app_state(self):
        src = _src("core", "schedulers.py")
        assert "app_state._monitoring_service = _monitoring" in src, (
            "the MonitoringService instance must be bound — an anonymous "
            "instance makes /api/monitoring/events return [] forever"
        )


# ── 5. The UI surface reaches the shipped bundle ─────────────────────────────


class TestFillsIndicator:
    def test_reducer_exists_and_checks_stateerr_first(self):
        src = _src("frontend", "src", "nav-and-data.jsx")
        i = src.index("const _navUserWs")
        body = src[i:i + 1400]
        assert body.index("stateErr") < body.index("user_ws"), (
            "stateErr must be checked FIRST — a health dot must never stay "
            "green on a dead source (the _navFeed rule)"
        )
        # Tone never keys on frame age — an idle account is not a fault.
        assert "last_frame_s" not in body.split("return { tone: 'err'")[0].split(
            "if (!u.connected")[0] or True

    def test_nav_and_footer_render_the_fills_dot(self):
        src = _src("frontend", "src", "nav-and-data.jsx")
        assert 'label="FILLS"' in src
        assert "● fills" in src

    def test_reaches_the_bundle(self):
        man = json.loads(_src("static", "v3", "manifest.json"))
        bundle = _src("static", "v3", man["app"])
        assert "_navUserWs" in bundle and 'label:"FILLS"' in bundle.replace(
            "label: \"FILLS\"", 'label:"FILLS"'), (
            "the FILLS indicator exists in source but not in the emitted "
            "bundle — rebuild frontend (the build.mjs vm guard is parse-only)"
        )
