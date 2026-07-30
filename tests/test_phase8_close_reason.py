"""
Phase 8 Task 6 (P8.T6) — manual-close reason.

Spec §10.5: a manual close (engine classifies it MANUAL_OTHER post-WS) is
operator-refinable to a MANUAL_* subtype + a free-text close_note, captured to
closed_positions.exit_reason + close_note. (The spec's *pre-submission* modal is
impossible — observe-only; this is the achievable post-arrival capability.)

Intent (Rule 8):
  - update_close_reason persists exit_reason + close_note, account-scoped;
  - the operator's refined reason + note SURVIVE a close-row REPLACE rebuild
    (the T176-class preserve in insert_closed_position) — the load-bearing
    anti-silent-drift guarantee;
  - the endpoint validates the reason ∈ MANUAL_* and (fragments slim-down
    2026-07-30) returns a JSON ok — the htmx badge re-render retired with
    close_reason_cell.html; the React modal only checks response.ok.

Run: pytest tests/test_phase8_close_reason.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest_asyncio.fixture
async def db():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    d = DatabaseManager(path=tmp.name)
    await d.initialize()
    await d._conn.execute("INSERT OR IGNORE INTO accounts (id, name) VALUES (1, 'Test')")
    await d._conn.execute("INSERT OR IGNORE INTO accounts (id, name) VALUES (2, 'Other')")
    await d._conn.commit()
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


async def _insert_close(d, **over):
    row = {
        "account_id": 1, "terminal_position_id": "POS-1", "exit_time_ms": 1000,
        "symbol": "BTCUSDT", "direction": "LONG", "quantity": 1.0,
        "entry_price": 100.0, "exit_price": 110.0, "exit_reason": "MANUAL_OTHER",
    }
    row.update(over)
    await d.insert_closed_position(row)


async def _id(d, tpid="POS-1", exit_ms=1000):
    async with d._conn.execute(
        "SELECT id FROM closed_positions WHERE terminal_position_id=? AND exit_time_ms=?",
        (tpid, exit_ms),
    ) as cur:
        r = await cur.fetchone()
    return r["id"] if r else None


async def _read(d, tpid="POS-1", exit_ms=1000):
    async with d._conn.execute(
        "SELECT exit_reason, close_note FROM closed_positions "
        "WHERE terminal_position_id=? AND exit_time_ms=?",
        (tpid, exit_ms),
    ) as cur:
        r = await cur.fetchone()
    return (r["exit_reason"], r["close_note"]) if r else None


# ── update_close_reason (DB) ──────────────────────────────────────────────────


class TestUpdateCloseReason:
    @pytest.mark.asyncio
    async def test_sets_reason_and_note(self, db):
        await _insert_close(db)
        ok = await db.update_close_reason(1, await _id(db), "MANUAL_INTERVENTION", "spiked, bailed")
        assert ok is True
        assert await _read(db) == ("MANUAL_INTERVENTION", "spiked, bailed")

    @pytest.mark.asyncio
    async def test_blank_note_is_null(self, db):
        await _insert_close(db)
        await db.update_close_reason(1, await _id(db), "MANUAL_NEW_OPPORTUNITY", "")
        assert await _read(db) == ("MANUAL_NEW_OPPORTUNITY", None)

    @pytest.mark.asyncio
    async def test_account_scoped(self, db):
        await _insert_close(db)  # account 1
        ok = await db.update_close_reason(2, await _id(db), "MANUAL_OTHER", "x")
        assert ok is False                       # wrong account → no update
        assert await _read(db) == ("MANUAL_OTHER", None)

    @pytest.mark.asyncio
    async def test_not_found(self, db):
        assert await db.update_close_reason(1, 99999, "MANUAL_OTHER", "x") is False


# ── REPLACE-preserve (the load-bearing anti-drift guarantee) ──────────────────


class TestReplacePreserve:
    @pytest.mark.asyncio
    async def test_refined_reason_and_note_survive_rebuild(self, db):
        await _insert_close(db)  # MANUAL_OTHER, close_note NULL
        await db.update_close_reason(1, await _id(db), "MANUAL_INTERVENTION", "my note")
        # a close-row rebuild REPLACEs the row (same natural key), recomputing
        # exit_reason=MANUAL_OTHER and omitting close_note — must NOT wipe.
        await _insert_close(db, exit_reason="MANUAL_OTHER")
        assert await _read(db) == ("MANUAL_INTERVENTION", "my note")

    @pytest.mark.asyncio
    async def test_non_manual_recompute_still_wins(self, db):
        # the preserve rule only fires when the caller recomputes MANUAL_OTHER;
        # a genuine reclassification to a non-manual reason must win (caller-wins).
        await _insert_close(db)
        await db.update_close_reason(1, await _id(db), "MANUAL_INTERVENTION", "n")
        await _insert_close(db, exit_reason="TP_PLANNED")
        reason, note = await _read(db)
        assert reason == "TP_PLANNED"            # caller wins (different family)
        assert note == "n"                       # close_note still preserved (operator-only)

    @pytest.mark.asyncio
    async def test_builder_does_not_wipe_when_no_operator_value(self, db):
        # no operator refinement: a rebuild just recomputes MANUAL_OTHER cleanly.
        await _insert_close(db)
        await _insert_close(db, exit_reason="MANUAL_OTHER")
        assert await _read(db) == ("MANUAL_OTHER", None)


# ── endpoint ──────────────────────────────────────────────────────────────────


class TestEndpoint:
    @pytest.mark.asyncio
    async def test_valid_updates_and_returns_json_ok(self, db, monkeypatch):
        import json
        import api.routes_history as rh
        from types import SimpleNamespace
        monkeypatch.setattr(rh, "db", db)
        monkeypatch.setattr(rh, "app_state", SimpleNamespace(active_account_id=1))
        await _insert_close(db)
        resp = await rh.update_close_reason(await _id(db), exit_reason="MANUAL_INTERVENTION", close_note="note")
        assert resp.status_code == 200
        body = json.loads(resp.body.decode("utf-8"))
        assert body["status"] == "ok"
        assert body["exit_reason"] == "MANUAL_INTERVENTION"
        assert await _read(db) == ("MANUAL_INTERVENTION", "note")

    @pytest.mark.asyncio
    async def test_invalid_reason_rejected(self, db, monkeypatch):
        import api.routes_history as rh
        from types import SimpleNamespace
        monkeypatch.setattr(rh, "db", db)
        monkeypatch.setattr(rh, "app_state", SimpleNamespace(active_account_id=1))
        await _insert_close(db)
        resp = await rh.update_close_reason(await _id(db), exit_reason="TP_PLANNED", close_note="")
        assert resp.status_code == 400
        assert await _read(db) == ("MANUAL_OTHER", None)   # unchanged

    @pytest.mark.asyncio
    async def test_not_found_404(self, db, monkeypatch):
        import api.routes_history as rh
        from types import SimpleNamespace
        monkeypatch.setattr(rh, "db", db)
        monkeypatch.setattr(rh, "app_state", SimpleNamespace(active_account_id=1))
        resp = await rh.update_close_reason(99999, exit_reason="MANUAL_OTHER", close_note="")
        assert resp.status_code == 404


# ── wiring ────────────────────────────────────────────────────────────────────
# (The badge-macro render + closes-table wiring classes retired with
# close_reason_badge.html / close_reason_cell.html / closed_positions_table.html
# in the fragments slim-down, 2026-07-30 — the React History/Linkage pages
# render the badge from the JSON rows.)


class TestWiring:
    def test_endpoint_registered(self):
        import api.routes_history as rh
        assert any(
            getattr(r, "path", None) == "/history/close_reason/{closed_pos_id}"
            and "PUT" in getattr(r, "methods", set())
            for r in rh.router.routes
        )
