"""
Phase 9 Task 4 (P9.T4) — operator-session idle timeout (plan §9 row 9.4).

A closed/asleep browser used to leave an active ``operator_sessions`` row
forever. P9.T4 fixes that with a heartbeat + reaper:

  - The page POSTs ``/operator/session/heartbeat`` every ~60s, bumping
    ``last_seen_ts`` on its active session (``heartbeat_session`` — a
    foreign/absent seat is a NO-OP, it never claims ownership).
  - A background loop (``schedulers._operator_session_reaper_loop``) calls
    ``reap_idle_sessions`` which ends sessions quiet beyond
    ``OPERATOR_SESSION_IDLE_SEC`` and invalidates the T3 operator-on-duty
    cache for each reaped (account, seat).

Intent (Rule 8) — what these pin that a refactor must not break:
  - "idle" is HEARTBEAT-driven (now - COALESCE(last_seen_ts, session_start_ts)),
    NOT max-age — an actively-heartbeating session is never reaped, but a
    quiet one IS;
  - the COALESCE reaps pre-T4 rows (last_seen_ts NULL) on their age;
  - a heartbeat from a FOREIGN seat does not bump/claim anything;
  - the reaper is global (all accounts) + best-effort (a fault never throws);
  - reaping invalidates the T3 cache ONLY for the matching (account, seat),
    so WS orders stop being stamped with a gone operator but a still-active
    new owner's cache (post-takeover) is preserved;
  - the heartbeat route write-throughs the cache (self-heals after restart).

Run: pytest tests/test_phase9_t4_session_timeout.py -v
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from types import SimpleNamespace

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.auth_state import (
    OPERATOR_SESSION_IDLE_SEC,
    heartbeat_session,
    reap_idle_sessions,
    register_session,
)
from core.state import app_state


@pytest_asyncio.fixture
async def db():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    d = DatabaseManager(path=tmp.name)
    await d.initialize()
    yield d
    await d.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


async def _set_last_seen(db, sid, ts):
    await db._conn.execute(
        "UPDATE operator_sessions SET last_seen_ts=? WHERE id=?", (ts, sid))
    await db._conn.commit()


async def _active_count(db, account_id):
    async with db._conn.execute(
        "SELECT COUNT(*) FROM operator_sessions "
        "WHERE account_id=? AND session_end_ts IS NULL", (account_id,)) as cur:
        return (await cur.fetchone())[0]


# ── 1. reaper (DB layer) ───────────────────────────────────────────────


class TestReaperDB:
    @pytest.mark.asyncio
    async def test_reaps_idle_session(self, db):
        sid = await db.start_operator_session(1, "A")
        await _set_last_seen(db, sid, 1000)               # long ago
        reaped = await db.reap_idle_operator_sessions(idle_ms=60_000, now_ms=70_000)
        assert [r["id"] for r in reaped] == [sid]
        row = await db.get_operator_session(sid)
        assert row["session_end_ts"] is not None          # ended
        assert await _active_count(db, 1) == 0

    @pytest.mark.asyncio
    async def test_keeps_fresh_session(self, db):
        sid = await db.start_operator_session(1, "A")
        await _set_last_seen(db, sid, 69_000)             # 1s before now
        reaped = await db.reap_idle_operator_sessions(idle_ms=60_000, now_ms=70_000)
        assert reaped == []
        assert await _active_count(db, 1) == 1

    @pytest.mark.asyncio
    async def test_coalesce_reaps_null_last_seen_on_start_age(self, db):
        # A pre-T4 row (last_seen_ts NULL) is reaped on its session_start age.
        await db._conn.execute(
            "INSERT INTO operator_sessions (account_id, operator_id, session_start_ts) "
            "VALUES (1, 'old', 1000)")                     # last_seen_ts NULL
        await db._conn.commit()
        reaped = await db.reap_idle_operator_sessions(idle_ms=60_000, now_ms=70_000)
        assert len(reaped) == 1 and reaped[0]["operator_id"] == "old"

    @pytest.mark.asyncio
    async def test_reap_returns_account_and_operator(self, db):
        sid = await db.start_operator_session(5, "seatX")
        await _set_last_seen(db, sid, 1000)
        reaped = await db.reap_idle_operator_sessions(idle_ms=1, now_ms=70_000)
        assert reaped[0]["account_id"] == 5
        assert reaped[0]["operator_id"] == "seatX"

    @pytest.mark.asyncio
    async def test_reap_is_global_multi_account(self, db):
        s1 = await db.start_operator_session(1, "A"); await _set_last_seen(db, s1, 1000)
        s2 = await db.start_operator_session(2, "B"); await _set_last_seen(db, s2, 1000)
        s3 = await db.start_operator_session(3, "C"); await _set_last_seen(db, s3, 69_000)
        reaped = {r["account_id"] for r in
                  await db.reap_idle_operator_sessions(idle_ms=60_000, now_ms=70_000)}
        assert reaped == {1, 2}
        assert await _active_count(db, 3) == 1            # fresh kept

    @pytest.mark.asyncio
    async def test_reap_empty_when_none_idle(self, db):
        sid = await db.start_operator_session(1, "A")
        await _set_last_seen(db, sid, 69_500)
        assert await db.reap_idle_operator_sessions(idle_ms=60_000, now_ms=70_000) == []

    @pytest.mark.asyncio
    async def test_reap_skips_already_ended(self, db):
        sid = await db.start_operator_session(1, "A")
        await _set_last_seen(db, sid, 1000)
        await db.end_operator_session(sid)
        assert await db.reap_idle_operator_sessions(idle_ms=1, now_ms=70_000) == []

    def test_reap_update_rechecks_idle_predicate(self):
        # The reaper SELECTs idle rows then UPDATEs them; the UPDATE must
        # RE-CHECK the idle predicate (not blindly end the SELECT'd ids) so a
        # session heartbeated between the two is spared. This is the one piece
        # of bespoke defensive logic — pin it against silent deletion (Rule 8):
        # idle_expr is defined once and must be referenced in BOTH queries
        # (def + SELECT + UPDATE = 3 mentions).
        from core.db_auth import AuthMixin
        src = inspect.getsource(AuthMixin.reap_idle_operator_sessions)
        assert src.count("idle_expr") >= 3, "UPDATE must re-check the idle predicate"


# ── 2. touch + heartbeat ───────────────────────────────────────────────


class TestTouchAndHeartbeat:
    @pytest.mark.asyncio
    async def test_touch_bumps_active(self, db):
        sid = await db.start_operator_session(1, "A")
        assert await db.touch_operator_session(sid, last_seen_ms=12345) is True
        assert (await db.get_operator_session(sid))["last_seen_ts"] == 12345

    @pytest.mark.asyncio
    async def test_touch_noop_on_ended(self, db):
        sid = await db.start_operator_session(1, "A")
        await db.end_operator_session(sid)
        assert await db.touch_operator_session(sid) is False

    @pytest.mark.asyncio
    async def test_heartbeat_bumps_owner(self, db):
        sid = await db.start_operator_session(1, "A")
        await _set_last_seen(db, sid, 1000)
        res = await heartbeat_session(db, 1, "A")
        assert res == {"ok": True, "bumped": True}
        assert (await db.get_operator_session(sid))["last_seen_ts"] > 1000

    @pytest.mark.asyncio
    async def test_heartbeat_noop_foreign(self, db):
        sid = await db.start_operator_session(1, "A")
        await _set_last_seen(db, sid, 1000)
        res = await heartbeat_session(db, 1, "B")         # different seat
        assert res == {"ok": True, "bumped": False}
        assert (await db.get_operator_session(sid))["last_seen_ts"] == 1000  # untouched

    @pytest.mark.asyncio
    async def test_heartbeat_noop_no_session(self, db):
        assert await heartbeat_session(db, 1, "A") == {"ok": True, "bumped": False}

    @pytest.mark.asyncio
    async def test_heartbeat_keeps_session_alive_vs_reaper(self, db):
        # The load-bearing intent: heartbeat bumps last_seen so the reaper
        # spares an open page even though its session STARTED long ago.
        sid = await db.start_operator_session(1, "A", start_ts_ms=1000)
        await heartbeat_session(db, 1, "A")               # bumps last_seen ≈ now
        # idle window 30min; "now" just after the heartbeat → not idle.
        reaped = await reap_idle_sessions(db)             # default 30-min idle
        assert reaped == 0
        assert await _active_count(db, 1) == 1


# ── 3. register reuse bumps last_seen ──────────────────────────────────


class TestRegisterReuseBumps:
    @pytest.mark.asyncio
    async def test_register_reuse_bumps_last_seen(self, db):
        r1 = await register_session(db, 1, "A")           # start
        await _set_last_seen(db, r1["session_id"], 1000)  # backdate
        r2 = await register_session(db, 1, "A")           # reuse → touch
        assert r2.get("reused") is True
        assert (await db.get_operator_session(r1["session_id"]))["last_seen_ts"] > 1000


# ── 4. reap orchestrator + T3 cache invalidation ───────────────────────


class TestReapOrchestrator:
    @pytest.mark.asyncio
    async def test_invalidates_cache_for_reaped_seat(self, db, monkeypatch):
        monkeypatch.setattr(app_state, "operator_id_by_account", {1: "A"})
        sid = await db.start_operator_session(1, "A")
        await _set_last_seen(db, sid, 1000)
        n = await reap_idle_sessions(db, idle_sec=1, now_ms=70_000)
        assert n == 1
        assert 1 not in app_state.operator_id_by_account   # cache cleared

    @pytest.mark.asyncio
    async def test_keeps_cache_for_nonmatching_seat(self, db, monkeypatch):
        # Reaping seat A must NOT clear a cache that points at a different
        # seat B (e.g. a takeover already moved the cache to a fresh owner).
        monkeypatch.setattr(app_state, "operator_id_by_account", {1: "B"})
        sid = await db.start_operator_session(1, "A")
        await _set_last_seen(db, sid, 1000)
        await reap_idle_sessions(db, idle_sec=1, now_ms=70_000)
        assert app_state.operator_id_by_account.get(1) == "B"   # preserved

    @pytest.mark.asyncio
    async def test_best_effort_on_fault(self, db, monkeypatch):
        async def _boom(**_kw):
            raise RuntimeError("db down")
        monkeypatch.setattr(db, "reap_idle_operator_sessions", _boom)
        assert await reap_idle_sessions(db) == 0           # no raise

    @pytest.mark.asyncio
    async def test_returns_count(self, db):
        for aid in (1, 2):
            sid = await db.start_operator_session(aid, "A")
            await _set_last_seen(db, sid, 1000)
        assert await reap_idle_sessions(db, idle_sec=1, now_ms=70_000) == 2

    @pytest.mark.asyncio
    async def test_uses_default_idle_constant(self, db):
        # A session last-seen just inside the default window is NOT reaped;
        # one just outside IS — pins reap_idle_sessions to the 30-min default.
        import time as _t
        now = int(_t.time() * 1000)
        fresh = await db.start_operator_session(1, "fresh")
        await _set_last_seen(db, fresh, now - (OPERATOR_SESSION_IDLE_SEC - 60) * 1000)
        stale = await db.start_operator_session(2, "stale")
        await _set_last_seen(db, stale, now - (OPERATOR_SESSION_IDLE_SEC + 60) * 1000)
        n = await reap_idle_sessions(db)                   # default idle, now=real
        assert n == 1
        assert (await db.get_operator_session(fresh))["session_end_ts"] is None
        assert (await db.get_operator_session(stale))["session_end_ts"] is not None


# ── 5. heartbeat route + cache write-through ───────────────────────────


def _wire(monkeypatch, db, account_id=1):
    import api.routes_auth as ra
    ns = SimpleNamespace(active_account_id=account_id, operator_id_by_account={})
    monkeypatch.setattr(ra, "db", db)
    monkeypatch.setattr(ra, "app_state", ns)
    return ra, ns


class TestHeartbeatRoute:
    @pytest.mark.asyncio
    async def test_owner_bumps_and_caches(self, db, monkeypatch):
        ra, ns = _wire(monkeypatch, db)
        await ra.operator_session_register(operator_id="A")     # start session
        ns.operator_id_by_account.clear()                       # simulate cold cache (restart)
        resp = await ra.operator_session_heartbeat(operator_id="A")
        body = json.loads(bytes(resp.body))
        assert body["bumped"] is True and body["account_id"] == 1
        assert ns.operator_id_by_account[1] == "A"             # write-through self-heal

    @pytest.mark.asyncio
    async def test_foreign_no_cache_write(self, db, monkeypatch):
        ra, ns = _wire(monkeypatch, db)
        await ra.operator_session_register(operator_id="A")     # A owns (cache=A)
        resp = await ra.operator_session_heartbeat(operator_id="B")
        body = json.loads(bytes(resp.body))
        assert body["bumped"] is False
        assert ns.operator_id_by_account.get(1) == "A"         # B didn't overwrite

    @pytest.mark.asyncio
    async def test_empty_seat_400(self, db, monkeypatch):
        ra, _ = _wire(monkeypatch, db)
        resp = await ra.operator_session_heartbeat(operator_id="   ")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_overlong_seat_400(self, db, monkeypatch):
        ra, _ = _wire(monkeypatch, db)
        resp = await ra.operator_session_heartbeat(operator_id="x" * 65)
        assert resp.status_code == 400


# ── 6. wiring ──────────────────────────────────────────────────────────


class TestWiring:
    def test_heartbeat_route_registered(self):
        import api.routes_auth as ra
        paths = {getattr(r, "path", None) for r in ra.router.routes}
        assert "/operator/session/heartbeat" in paths

    def test_heartbeat_route_in_aggregate_router(self):
        from api.router import router as agg
        paths = {getattr(r, "path", None) for r in agg.routes}
        assert "/operator/session/heartbeat" in paths

    def test_reaper_loop_wired(self):
        from core import schedulers
        assert hasattr(schedulers, "_operator_session_reaper_loop")
        src = inspect.getsource(schedulers.start_background_tasks)
        assert "_operator_session_reaper_loop" in src

    def test_base_html_heartbeat(self):
        with open("templates/base.html", encoding="utf-8") as fh:
            src = fh.read()
        assert "/operator/session/heartbeat" in src
        assert "setInterval" in src
        # The heartbeat must be INSIDE the window._opSeat guard so the timer is
        # created once per full load (no hx-boost stacking — the #3a/#3c lesson).
        guard = src.index("if (window._opSeat) return")
        hb = src.index("/operator/session/heartbeat")
        assert guard < hb, "heartbeat setInterval must be inside the guarded IIFE"

    @pytest.mark.asyncio
    async def test_schema_has_last_seen_ts(self, db):
        # The column exists on an initialized DB (CREATE + ALTER paths).
        async with db._conn.execute("PRAGMA table_info(operator_sessions)") as cur:
            cols = {r[1] for r in await cur.fetchall()}
        assert "last_seen_ts" in cols
