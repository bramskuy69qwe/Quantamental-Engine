"""P4 History+Linkage backend pins (v3.0): G-O6 funding book, G-O7 lifecycle
fields, the linkage JSON mirrors, and the history-table JSON doors.

Handler-direct calls with readers/stubs monkeypatched — never through the
shared TestClient for anything that could write (F5 discipline). The mirrors
are READ-ONLY; writes stay on the existing choke-pointed endpoints.
"""
from __future__ import annotations

import asyncio
import json as _jsonlib

import pytest

import api.routes_cockpit as rk
import api.routes_orders as ro
import api.routes_history as rh
from core.state import app_state, PositionInfo


def _body(resp):
    return _jsonlib.loads(resp.body)


def _pos(**over):
    p = PositionInfo(
        position_id="P-1", ticker="BTCUSDT", direction="LONG",
        contract_amount=0.012, average=93412.1, fair_price=93580.4,
        position_value_usdt=1123.0, individual_unrealized=2.02,
        individual_fees=0.04, individual_funding_fees=-0.012,
        session_mfe=2.31, session_mae=-0.44,
        individual_tp_price=94100.0, individual_sl_price=93180.0,
        calc_id="c-abc", deviation_badge="green",
    )
    for k, v in over.items():
        setattr(p, k, v)
    return p


class _Snap:
    """Swap app_state.positions for the test, restore after."""
    def __enter__(self):
        self._old = app_state.positions
        return self

    def set(self, positions):
        app_state.positions = positions

    def __exit__(self, *a):
        app_state.positions = self._old


# ── G-O7: PositionInfo lifecycle fields ────────────────────────────────────

class TestG07Fields:
    def test_quartet_defaults_and_preserve_membership(self):
        p = PositionInfo()
        assert (p.planned_tp, p.planned_sl, p.tp_drift_pct, p.sl_drift_pct) == (0.0, 0.0, 0.0, 0.0)
        from core.data_cache import _PRESERVE_FIELDS
        for f in ("planned_tp", "planned_sl", "tp_drift_pct", "sl_drift_pct"):
            assert f in _PRESERVE_FIELDS, f

    def test_enrich_stamps_and_clears_the_quartet(self):
        """Source pin: the enrichment stamps the numerics beside the drift
        booleans AND clears them in the no-junction branch (stale-inherit
        guard). The behavioral coverage of _enrich itself is the linkage
        battery's job."""
        from pathlib import Path
        src = Path("core/order_manager.py").read_text(encoding="utf-8")
        assert "pos.tp_drift_pct = (" in src and "pos.sl_drift_pct = (" in src
        # clearing branch sits with the other no-calc resets
        i = src.find('pos.deviation_badge = "red"')
        assert i > 0
        cleared = src[i - 500:i]
        for f in ("pos.planned_tp = 0.0", "pos.sl_drift_pct = 0.0"):
            assert f in cleared, f


# ── /api/linkage/positions ─────────────────────────────────────────────────

class TestLinkagePositions:
    def test_row_serialization_and_link_status(self):
        with _Snap() as s:
            s.set([
                _pos(planned_tp=94000.0, planned_sl=93200.0,
                     tp_drift_pct=0.106, sl_drift_pct=-0.021),
                _pos(position_id="P-2", ticker="AVAXUSDT", calc_id="",
                     deviation_badge="red"),
            ])
            data = _body(asyncio.run(rk.api_linkage_positions()))
        rows = data["positions"]
        assert len(rows) == 2
        r = rows[0]
        assert r["symbol"] == "BTCUSDT" and r["link_status"] == "LINKED"
        assert r["tp_plan"] == 94000.0 and r["sl_plan"] == 93200.0
        assert r["tp_drift_pct"] == 0.106 and r["sl_drift_pct"] == -0.021
        assert r["tp_live"] == 94100.0 and r["sl_live"] == 93180.0
        assert rows[1]["link_status"] == "UNPLANNED"


# ── /api/linkage/calcs ─────────────────────────────────────────────────────

class TestLinkageCalcs:
    def test_expiry_ms_rides_each_row(self, monkeypatch):
        from core.database import db

        async def _calcs(aid, limit=50):
            return [{"calc_id": "c-1", "ticker": "BTCUSDT",
                     "timestamp": "2026-07-22T00:00:00+00:00",
                     "window_seconds": 300}]
        monkeypatch.setattr(db, "get_active_calcs", _calcs)
        data = _body(asyncio.run(rk.api_linkage_calcs()))
        row = data["calcs"][0]
        assert row["expiry_ms"] == rk._calc_expiry_ms(
            "2026-07-22T00:00:00+00:00", 300)
        assert row["expiry_ms"] is not None


# ── /api/linkage/closes ────────────────────────────────────────────────────

class TestLinkageCloses:
    def _stub(self, monkeypatch, rows):
        from core.database import db
        from types import SimpleNamespace
        import core.account_config as ac

        async def _q(aid, **k):
            return rows, len(rows)
        monkeypatch.setattr(db, "query_closed_positions", _q)

        async def _cfg(db_, aid):
            return SimpleNamespace(yellow_deviation_pct=5.0, red_deviation_pct=15.0)
        monkeypatch.setattr(ac, "read_account_config_async", _cfg)

    def test_pending_reason_derivation(self, monkeypatch):
        rows = [
            {"id": 1, "exit_reason": "MANUAL_OTHER", "close_note": None,
             "calc_id": None},
            {"id": 2, "exit_reason": "MANUAL_OTHER", "close_note": "noted",
             "calc_id": None},
            {"id": 3, "exit_reason": "TP_PLANNED", "close_note": None,
             "calc_id": "c-1", "size_delta_pct": 0.0,
             "cumulative_amendment_count": 0, "tpsl_amended": 0},
        ]
        self._stub(monkeypatch, rows)
        data = _body(asyncio.run(rk.api_linkage_closes(limit=15)))
        pr = {r["id"]: r["pending_reason"] for r in data["closes"]}
        assert pr == {1: True, 2: False, 3: False}

    def test_limit_clamped(self, monkeypatch):
        captured = {}
        from core.database import db
        from types import SimpleNamespace
        import core.account_config as ac

        async def _q(aid, **k):
            captured.update(k)
            return [], 0
        monkeypatch.setattr(db, "query_closed_positions", _q)

        async def _cfg(db_, aid):
            return SimpleNamespace(yellow_deviation_pct=5.0, red_deviation_pct=15.0)
        monkeypatch.setattr(ac, "read_account_config_async", _cfg)
        asyncio.run(rk.api_linkage_closes(limit=999))
        assert captured["per_page"] == 50


# ── /api/linkage/funding (G-O6) ────────────────────────────────────────────

class TestLinkageFunding:
    def test_adverse_rule_and_net_sums(self, monkeypatch):
        import core.exchange as ex
        now_ms = 1_800_000_000_000

        async def _rates(symbols):
            return {
                "BTCUSDT":  {"funding_rate": 0.0001,  "next_funding_time": now_ms},
                "ETHUSDT":  {"funding_rate": 0.0001,  "next_funding_time": now_ms},
            }
        monkeypatch.setattr(ex, "fetch_funding_rates", _rates)
        with _Snap() as s:
            s.set([
                _pos(),                                             # LONG, rate>0 → pays
                _pos(position_id="P-2", ticker="ETHUSDT",
                     direction="SHORT", position_value_usdt=-1764.5,
                     individual_funding_fees=0.031),                # SHORT, rate>0 → earns
            ])
            data = _body(asyncio.run(rk.api_linkage_funding()))
        rows = {r["symbol"]: r for r in data["rows"]}
        assert rows["BTCUSDT"]["pays"] == "you" and rows["BTCUSDT"]["est_next"] < 0
        assert rows["ETHUSDT"]["pays"] == "venue" and rows["ETHUSDT"]["est_next"] > 0
        assert rows["ETHUSDT"]["notional"] == 1764.5          # abs()
        assert data["net_cum"] == pytest.approx(-0.012 + 0.031)
        assert data["next_funding_time_ms"] == now_ms
        assert data["schedule"] == ["00:00", "08:00", "16:00"]

    def test_rate_fetch_failure_degrades(self, monkeypatch):
        import core.exchange as ex

        async def _boom(symbols):
            raise RuntimeError("net down")
        monkeypatch.setattr(ex, "fetch_funding_rates", _boom)
        with _Snap() as s:
            s.set([_pos()])
            data = _body(asyncio.run(rk.api_linkage_funding()))
        assert data["rows"][0]["rate"] is None
        assert data["countdown_s"] is None


# ── History JSON doors ─────────────────────────────────────────────────────

class TestHistoryDoors:
    def test_rows_json_envelope(self):
        resp = ro._rows_json([{"a": 1}], total=41, page=2, per_page=20)
        data = _body(resp)
        assert data == {"rows": [{"a": 1}], "total": 41, "page": 2,
                        "per_page": 20, "total_pages": 3}

    def test_closed_positions_door_carries_stamped_badge(self, monkeypatch):
        from core.database import db
        from types import SimpleNamespace
        import core.account_config as ac

        async def _q(**k):
            return ([{"id": 1, "calc_id": "c-1", "size_delta_pct": 0.0,
                      "cumulative_amendment_count": 0, "tpsl_amended": 0,
                      "net_pnl": 1.0}], 1)
        monkeypatch.setattr(db, "query_closed_positions", _q)

        async def _cfg(db_, aid):
            return SimpleNamespace(yellow_deviation_pct=5.0, red_deviation_pct=15.0)
        monkeypatch.setattr(ac, "read_account_config_async", _cfg)
        resp = asyncio.run(ro.frag_closed_positions(
            request=None, page=1, per_page=20, format="json"))
        row = _body(resp)["rows"][0]
        assert row["deviation_badge"] == "green"    # stamped by the route

    def test_pre_trade_door_carries_model_display(self, monkeypatch):
        from core.database import db

        async def _q(**k):
            return ([{"id": 1, "model_id": 7, "model_name": ""}], 1)
        monkeypatch.setattr(db, "query_pre_trade_log", _q)

        async def _names(ids):
            return {7: "momentum_v3"}
        monkeypatch.setattr(db, "get_model_names_by_ids", _names)
        resp = asyncio.run(rh.frag_history_pre_trade(
            request=None, page=1, per_page=20, format="json"))
        assert _body(resp)["rows"][0]["model_display"] == "momentum_v3"

