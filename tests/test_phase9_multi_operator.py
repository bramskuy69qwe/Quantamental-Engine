"""
Phase 9 Task 1 (P9.T1) — MINIMAL multi-session banner (plan §9 / spec §12.1).

Single-tenant localhost has no auth and a single global active account, so an
"operator" is a per-browser SEAT token (a localStorage UUID). This task wires
the minimal advisory flow (NO hard read-only lock — that's the full P9.T1; NO
idle timeout — P9.T4; NO operator_id propagation — P9.T3):

  - register_session: a seat learns whether it OWNS the account's session or a
    FOREIGN seat is active. Starting a row only when none is active, and never
    starting one for the foreign case, is load-bearing (a non-owner must not
    silently claim the session — only an explicit takeover does).
  - takeover_session: displace the foreign active session and become owner,
    recording takeover_from_session_id for the handoff audit trail.

Intent (Rule 8):
  - foreign seat must NOT start a row (no silent claim) and must surface state;
  - same-seat re-register reuses the row (repeated page loads don't spam rows);
  - takeover ends the prior session AND links back to it (audit);
  - both flows are account-scoped (one account's session never leaks to another);
  - the route validates the seat token; the banner + guarded IIFE are wired.

Run: pytest tests/test_phase9_multi_operator.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from types import SimpleNamespace

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.auth_state import register_session, takeover_session


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


async def _count(db, account_id, *, active_only=False):
    sql = "SELECT COUNT(*) FROM operator_sessions WHERE account_id=?"
    if active_only:
        sql += " AND session_end_ts IS NULL"
    async with db._conn.execute(sql, (account_id,)) as cur:
        return (await cur.fetchone())[0]


# ── register_session ──────────────────────────────────────────────────────────


class TestRegister:
    @pytest.mark.asyncio
    async def test_no_active_starts_row_and_owns(self, db):
        res = await register_session(db, 1, "seat-A")
        assert res["state"] == "owner"
        assert res["session_id"] > 0
        assert await _count(db, 1, active_only=True) == 1

    @pytest.mark.asyncio
    async def test_same_seat_reuses_no_new_row(self, db):
        # Repeated page loads from the SAME browser must not spam rows.
        await register_session(db, 1, "seat-A")
        res = await register_session(db, 1, "seat-A")
        assert res["state"] == "owner" and res.get("reused") is True
        assert await _count(db, 1) == 1            # still exactly one row

    @pytest.mark.asyncio
    async def test_foreign_seat_does_not_start_row(self, db):
        # A non-owner must NOT silently claim the session — only takeover does.
        await register_session(db, 1, "seat-A")    # A owns it
        res = await register_session(db, 1, "seat-B")
        assert res["state"] == "foreign"
        assert res["foreign_operator_id"] == "seat-A"
        assert "since_ms" in res
        assert await _count(db, 1) == 1            # B did NOT add a row
        assert await _count(db, 1, active_only=True) == 1

    @pytest.mark.asyncio
    async def test_account_scoped(self, db):
        await register_session(db, 1, "seat-A")
        res = await register_session(db, 2, "seat-A")   # different account
        assert res["state"] == "owner"             # account 2 sees no active
        assert await _count(db, 2, active_only=True) == 1


# ── takeover_session ──────────────────────────────────────────────────────────


class TestTakeover:
    @pytest.mark.asyncio
    async def test_displaces_foreign_and_links_audit(self, db):
        await register_session(db, 1, "seat-A")
        prior = await db.get_active_operator_session(1)
        res = await takeover_session(db, 1, "seat-B")
        assert res["state"] == "owner"
        assert res["took_over_from"] == prior["id"]
        # prior ended, new row active and linked back to prior (handoff audit).
        ended = await db.get_operator_session(prior["id"])
        assert ended["session_end_ts"] is not None
        new = await db.get_operator_session(res["session_id"])
        assert new["operator_id"] == "seat-B"
        assert new["takeover_from_session_id"] == prior["id"]
        assert await _count(db, 1, active_only=True) == 1   # exactly one active

    @pytest.mark.asyncio
    async def test_already_owner_is_noop(self, db):
        r1 = await register_session(db, 1, "seat-A")
        res = await takeover_session(db, 1, "seat-A")
        assert res["state"] == "owner"
        assert res["took_over_from"] is None
        assert res["session_id"] == r1["session_id"]    # same row, no churn
        assert await _count(db, 1) == 1

    @pytest.mark.asyncio
    async def test_no_active_just_starts(self, db):
        res = await takeover_session(db, 1, "seat-A")
        assert res["state"] == "owner" and res["took_over_from"] is None
        assert await _count(db, 1, active_only=True) == 1


# ── route handlers ────────────────────────────────────────────────────────────


def _wire(monkeypatch, db, account_id=1):
    import api.routes_auth as ra
    monkeypatch.setattr(ra, "db", db)
    # operator_id_by_account mirrors the real app_state shape — P9.T3 added a
    # write-through to it on owner-register / takeover.
    monkeypatch.setattr(ra, "app_state", SimpleNamespace(
        active_account_id=account_id, operator_id_by_account={}))
    return ra


class TestRoutes:
    @pytest.mark.asyncio
    async def test_register_returns_owner_json(self, db, monkeypatch):
        ra = _wire(monkeypatch, db)
        resp = await ra.operator_session_register(operator_id="seat-A")
        assert resp.status_code == 200
        body = json.loads(bytes(resp.body))
        assert body["state"] == "owner" and body["account_id"] == 1

    @pytest.mark.asyncio
    async def test_register_foreign_after_other_seat(self, db, monkeypatch):
        ra = _wire(monkeypatch, db)
        await ra.operator_session_register(operator_id="seat-A")
        resp = await ra.operator_session_register(operator_id="seat-B")
        body = json.loads(bytes(resp.body))
        assert body["state"] == "foreign" and body["foreign_operator_id"] == "seat-A"

    @pytest.mark.asyncio
    async def test_takeover_route(self, db, monkeypatch):
        ra = _wire(monkeypatch, db)
        await ra.operator_session_register(operator_id="seat-A")
        resp = await ra.operator_session_takeover(operator_id="seat-B")
        body = json.loads(bytes(resp.body))
        assert body["state"] == "owner" and body["took_over_from"] is not None

    @pytest.mark.asyncio
    async def test_empty_seat_is_400(self, db, monkeypatch):
        ra = _wire(monkeypatch, db)
        resp = await ra.operator_session_register(operator_id="   ")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_overlong_seat_is_400(self, db, monkeypatch):
        ra = _wire(monkeypatch, db)
        resp = await ra.operator_session_register(operator_id="x" * 65)
        assert resp.status_code == 400


# ── wiring ────────────────────────────────────────────────────────────────────


class TestWiring:
    def test_routes_registered(self):
        import api.routes_auth as ra
        paths = {getattr(r, "path", None) for r in ra.router.routes}
        assert "/operator/session/register" in paths
        assert "/operator/session/takeover" in paths

    def test_router_includes_auth(self):
        # The aggregate router must mount the auth routes (else they 404 live).
        from api.router import router as agg
        paths = {getattr(r, "path", None) for r in agg.routes}
        assert "/operator/session/register" in paths

    def test_base_html_banner_and_guarded_iife(self):
        with open("templates/base.html", encoding="utf-8") as fh:
            src = fh.read()
        assert 'id="operator-session-banner"' in src        # the banner element
        assert "operatorTakeover" in src                     # takeover hook
        assert "/operator/session/register" in src           # on-load register
        # boost-guard (per #3a): the IIFE must early-return on re-execution.
        assert "if (window._opSeat) return" in src
        # the banner must CONSUME the plumbed foreign-session data (spec §12.1
        # "Operator X is active"), not drop it — and only via textContent (XSS).
        assert "since_ms" in src and "foreign_operator_id" in src
        assert "textContent" in src
