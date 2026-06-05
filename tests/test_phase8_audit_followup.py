"""
Phase 8 holistic-audit follow-up — regressions for the fixes + coverage for the
gaps the 5-agent audit surfaced.

Fixes pinned here:
  - HIGH: non-finite (NaN/Inf) calc inputs are rejected at the calculator route
    AND in calculate_position_size (the matcher/deviation poison class);
  - LOW: find_candidate_calcs / _cancelled_order_for_calc are account-scoped
    (combined-DB fallback safety, matcher-aligned);
  - LOW: _fmt renders a non-finite value as an em-dash, not literal "nan"/"inf".

Coverage gaps closed here (behaviors that shipped untested):
  - MANUAL_DISCIPLINE_BREAK + MANUAL_NEW_OPPORTUNITY: REPLACE-preserve, endpoint
    accept, and badge label (only MANUAL_INTERVENTION was exercised);
  - position_size_drift notification routing + message;
  - position_events detail-summary branches (tp_modified / sl_modified /
    position_amended / order_placed / symbol-fallback) — each dereferences
    p.get(...) and was unrendered.

Run: pytest tests/test_phase8_audit_followup.py -v
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── shared closed_positions DB fixture (mirrors test_phase8_close_reason) ──────


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


# ── HIGH: non-finite calc inputs rejected ─────────────────────────────────────


class TestCalculatorRouteFiniteGuard:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("field,bad", [
        ("average", "nan"), ("average", "inf"), ("average", "1e400"),
        ("sl_price", "nan"), ("sl_price", "-inf"),
        ("tp_price", "nan"), ("tp_amount_pct", "inf"), ("sl_amount_pct", "nan"),
    ])
    async def test_nonfinite_input_rejected_400(self, monkeypatch, field, bad):
        import api.routes_calculator as rc
        monkeypatch.setattr(rc.ws_manager, "set_calculator_symbol", lambda *a, **k: None)
        kwargs = dict(ticker="BTCUSDT", average=100.0, sl_price=95.0, tp_price=110.0,
                      tp_amount_pct=100.0, sl_amount_pct=100.0)
        kwargs[field] = float(bad)
        resp = await rc.calculate_risk(request=None, **kwargs)
        assert resp.status_code == 400
        assert field.encode() in resp.body and b"finite" in resp.body


class TestCalcPositionSizeFiniteGuard:
    def _bypass_gates(self, monkeypatch):
        # get past the engine-ready + adapter-capability gates so execution
        # reaches the finite guard (the NaN path returns there, before ATR).
        monkeypatch.setattr("core.monitoring.ReadyStateEvaluator.evaluate",
                            lambda self: (True, ""))
        monkeypatch.setattr("core.exchange._get_adapter", lambda: object())
        monkeypatch.setattr("core.adapters.protocols.require_capability",
                            lambda adapter, cap: None)

    @pytest.mark.parametrize("avg,sl", [
        (float("nan"), 95.0), (float("inf"), 95.0),
        (100.0, float("nan")), (100.0, float("-inf")),
    ])
    def test_nonfinite_is_ineligible_not_poisoned(self, monkeypatch, avg, sl):
        from core.risk_engine import calculate_position_size
        self._bypass_gates(monkeypatch)
        r = calculate_position_size("BTCUSDT", avg, sl, 1000.0, "long")
        assert r["eligible"] is False
        assert r["ineligible_reason"] == "Invalid entry or SL price."
        assert r["size"] == 0.0                       # not NaN/Inf


# ── LOW: _fmt non-finite -> em-dash ───────────────────────────────────────────


class TestFmtFiniteGuard:
    def test_nonfinite_renders_dash(self):
        from api.helpers import _fmt
        assert _fmt(float("nan")) == "—"
        assert _fmt(float("inf")) == "—"
        assert _fmt(float("-inf")) == "—"

    def test_finite_unchanged(self):
        from api.helpers import _fmt
        assert _fmt(1234.5, 2) == "1,234.50"
        assert _fmt(0) == "0.00"
        assert _fmt("n/a") == "n/a"                    # non-numeric passthrough


# ── LOW: find_candidate_calcs account scoping ─────────────────────────────────


class TestCandidateCalcAccountScope:
    def _make_combined_db(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        conn = sqlite3.connect(tmp.name)
        conn.executescript("""
            CREATE TABLE pre_trade_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL DEFAULT 1,
                calc_id TEXT, ticker TEXT, side TEXT,
                effective_entry REAL, tp_price REAL, sl_price REAL,
                timestamp TEXT, status TEXT DEFAULT 'active'
            );
            CREATE TABLE orders (
                account_id INTEGER, calc_id TEXT, exchange_order_id TEXT,
                cancel_ts_ms INTEGER, status TEXT
            );
        """)
        ts = datetime.now(timezone.utc).isoformat()
        # identical calc under TWO accounts, same ticker/price
        for aid, cid in ((1, "CALC-A1"), (2, "CALC-A2")):
            conn.execute(
                "INSERT INTO pre_trade_log (account_id, calc_id, ticker, side, "
                "effective_entry, tp_price, sl_price, timestamp, status) "
                "VALUES (?,?,?,?,?,?,?,?,'active')",
                (aid, cid, "BTCUSDT", "long", 100.0, 110.0, 95.0, ts),
            )
        conn.commit()
        conn.close()
        return tmp.name

    def test_only_active_account_candidates_returned(self):
        from core.calc_correlation import find_candidate_calcs
        path = self._make_combined_db()
        try:
            order = {"symbol": "BTCUSDT", "price": 100.0, "side": "long",
                     "tp_trigger_price": 110.0, "sl_trigger_price": 95.0,
                     "account_id": 1}
            cands = find_candidate_calcs(order, db_path=path)
            ids = {c.calc_id for c in cands}
            assert ids == {"CALC-A1"}                  # account 2's calc excluded
        finally:
            os.unlink(path)


# ── coverage: MANUAL_* refined subtypes (preserve + endpoint + badge) ─────────


async def _insert_close(d, **over):
    row = {
        "account_id": 1, "terminal_position_id": "POS-1", "exit_time_ms": 1000,
        "symbol": "BTCUSDT", "direction": "LONG", "quantity": 1.0,
        "entry_price": 100.0, "exit_price": 110.0, "exit_reason": "MANUAL_OTHER",
    }
    row.update(over)
    await d.insert_closed_position(row)


async def _id(d):
    async with d._conn.execute(
        "SELECT id FROM closed_positions WHERE terminal_position_id='POS-1' "
        "AND exit_time_ms=1000") as cur:
        r = await cur.fetchone()
    return r["id"] if r else None


async def _read(d):
    async with d._conn.execute(
        "SELECT exit_reason, close_note FROM closed_positions "
        "WHERE terminal_position_id='POS-1' AND exit_time_ms=1000") as cur:
        r = await cur.fetchone()
    return (r["exit_reason"], r["close_note"]) if r else None


class TestRefinedManualSubtypes:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("reason,note", [
        ("MANUAL_DISCIPLINE_BREAK", "broke my rules"),
        ("MANUAL_NEW_OPPORTUNITY", "better setup elsewhere"),
    ])
    async def test_refined_reason_survives_replace_rebuild(self, db, reason, note):
        await _insert_close(db)                        # engine: MANUAL_OTHER
        await db.update_close_reason(1, await _id(db), reason, note)
        await _insert_close(db)                        # rebuild recomputes MANUAL_OTHER
        assert await _read(db) == (reason, note)        # operator value preserved

    @pytest.mark.asyncio
    @pytest.mark.parametrize("reason", ["MANUAL_DISCIPLINE_BREAK", "MANUAL_NEW_OPPORTUNITY"])
    async def test_endpoint_accepts_subtype(self, db, monkeypatch, reason):
        import api.routes_history as rh
        monkeypatch.setattr(rh, "db", db)
        monkeypatch.setattr(rh, "app_state", SimpleNamespace(active_account_id=1))
        await _insert_close(db)
        resp = await rh.update_close_reason(await _id(db), exit_reason=reason, close_note="x")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_endpoint_rejects_junk_reason(self, db, monkeypatch):
        import api.routes_history as rh
        monkeypatch.setattr(rh, "db", db)
        monkeypatch.setattr(rh, "app_state", SimpleNamespace(active_account_id=1))
        await _insert_close(db)
        resp = await rh.update_close_reason(await _id(db), exit_reason="HACK", close_note="")
        assert resp.status_code == 400

    def test_badge_labels(self):
        from api.helpers import templates
        m = templates.env.get_template("fragments/history/close_reason_badge.html").module
        assert "Discipline" in str(m.manual_close_badge("MANUAL_DISCIPLINE_BREAK", "", 1))
        assert "New Opp" in str(m.manual_close_badge("MANUAL_NEW_OPPORTUNITY", "", 1))


# ── coverage: position_size_drift notification ────────────────────────────────


class TestSizeDriftNotification:
    @pytest.mark.asyncio
    async def test_routes_and_messages(self):
        from core.notifications import NotificationCenter
        nc = NotificationCenter()
        await nc.on_event("engine:account:1:position:size_drift",
                          {"position_id": "P1", "delta": 0.3})
        items, _ = nc.poll(1, 0)
        assert [i["type"] for i in items] == ["position_size_drift"]
        assert "Size drift" in items[0]["message"] and "P1" in items[0]["message"]


# ── coverage: position_events detail-summary branches ─────────────────────────


def _evt(event_type, payload):
    return {"id": 0, "timestamp": "2026-06-01T10:00:00", "event_type": event_type,
            "source": "ws", "calc_id": "C", "payload_json": json.dumps(payload),
            "_payload": payload}


class TestPositionEventsDetailBranches:
    def _render(self, events):
        from api.helpers import templates
        return templates.env.get_template(
            "fragments/history/position_events.html"
        ).render(events=events, has_calc=True, truncated=False, events_cap=500)

    def test_all_summary_branches_render(self):
        html = self._render([
            _evt("position_amended", {"field": "tp_price", "old": 110.0, "new": 115.0}),
            _evt("tp_modified", {"from_price": 110.0, "to_price": 115.0}),
            _evt("sl_modified", {"from_price": 95.0, "to_price": 97.0}),
            _evt("order_placed", {"side": "BUY", "order_type": "LIMIT"}),
            _evt("order_canceled", {"symbol": "BTCUSDT"}),          # symbol-fallback
            _evt("calc_created", {}),                                # raw json fallback
        ])
        assert "tp_price:" in html                                  # position_amended
        assert "BUY" in html and "LIMIT" in html                    # order_placed
        assert "BTCUSDT" in html                                    # symbol-fallback
        # each event renders its chip
        for et in ("position_amended", "tp_modified", "sl_modified",
                   "order_placed", "order_canceled", "calc_created"):
            assert et in html

    def test_amended_missing_old_does_not_crash(self):
        # position_amended whose 'old' is absent must fall through, not raise
        html = self._render([_evt("position_amended", {"field": "tp_price"})])
        assert "position_amended" in html
