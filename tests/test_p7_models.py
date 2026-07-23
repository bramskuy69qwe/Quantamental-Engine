"""
v3.0 P7 — Models tab backend pins.

Covers: G-M2 generic lossless workbook capture (types + SIGNS + all
sheets, non-finite F2 encoding), G-M1 verbatim report store + fetch,
G-M3 overview feed (latest completed run + sparkline, no report bloat),
G-M4 source/tags columns + §6-3b auto-seed, G-M5 dry-run preview +
combined create+import (rollback on failure), G-M6 usage reverse feed,
G-M7 filename + contract count.

Per the LOW-023 constraint, route LOGIC is tested via direct handler
calls with the module `db` monkeypatched to a temp DatabaseManager —
NOT a second TestClient. GET-route 200 smokes ride tests/test_routes.py
(extended with /api/models/overview this phase). Never POSTs a write
endpoint through the shared TestClient (F5 discipline).
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import UploadFile
from starlette.requests import Request

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import api.routes_models as rm
import core.backtest_adapters.workbook_capture as wc
from core.backtest_adapters import get_backtest_adapter
from core.backtest_adapters.base import BacktestAdapterError
from core.backtest_adapters.workbook_capture import capture_workbook
from core.database import DatabaseManager

FIXTURES = Path(__file__).parent / "fixtures" / "multicharts"
FIXTURE_XLSX = (FIXTURES / "mc_synthetic.xlsx").read_bytes()


# ── fixtures / helpers (test_v27_phase3_model_routes idioms) ────────────────

@pytest_asyncio.fixture
async def mdb(monkeypatch):
    """Temp DB wired as routes_models' module `db` singleton."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database = DatabaseManager(path=tmp.name)
    await database.initialize()
    monkeypatch.setattr(rm, "db", database)
    yield database
    await database.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


def _req(path: str = "/x", method: str = "GET") -> Request:
    return Request({
        "type": "http", "http_version": "1.1", "method": method,
        "path": path, "raw_path": path.encode(), "root_path": "",
        "scheme": "http", "query_string": b"", "headers": [],
        "client": ("test", 0), "server": ("test", 80),
    })


def _json_req(payload: dict, method: str = "POST") -> Request:
    body = json.dumps(payload).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http", "http_version": "1.1", "method": method,
        "path": "/x", "raw_path": b"/x", "root_path": "",
        "scheme": "http", "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("test", 0), "server": ("test", 80),
    }, receive)


def _upload(data: bytes, filename: str = "r.xlsx") -> UploadFile:
    return UploadFile(file=BytesIO(data), filename=filename)


def _jbody(resp):
    return json.loads(resp.body)


def _sheet(cap, name):
    return next(s for s in cap["sheets"] if s["name"] == name)


async def _import_fixture(db, model_id, filename="mc_synthetic.xlsx"):
    """One committed import through the REAL upload handler (JSON lane)."""
    resp = await rm.upload_model_backtest(
        _req(method="POST"), model_id,
        file=_upload(FIXTURE_XLSX, filename),
        app_id="multicharts", format="json")
    assert resp.status_code == 200, resp.body
    return _jbody(resp)


# ═══ G-M2 — generic lossless capture ════════════════════════════════════════

class TestWorkbookCapture:
    def test_all_sheets_captured_in_workbook_order(self):
        cap = capture_workbook(FIXTURE_XLSX)
        assert cap["format"] == "workbook.v1"
        assert [s["name"] for s in cap["sheets"]] == [
            "Strategy Analysis", "Strategy Analysis Graphs", "List of Trades",
            "Trade Analysis", "Trade Analysis Graphs", "Periodical Analysis",
            "Periodical Analysis Graphs", "Settings",
        ]

    def test_image_only_graphs_sheets_captured_empty(self):
        cap = capture_workbook(FIXTURE_XLSX)
        for name in ("Strategy Analysis Graphs", "Trade Analysis Graphs",
                     "Periodical Analysis Graphs"):
            assert _sheet(cap, name)["rows"] == []

    def test_signs_and_strings_preserved_verbatim(self):
        """The MC gotchas: signed-negative drawdown/PF cells and the
        '$50' Point-Value string must survive capture UNTOUCHED — the
        capture layer never normalizes (that's the derived layer's job)."""
        cap = capture_workbook(FIXTURE_XLSX)
        sa = _sheet(cap, "Strategy Analysis")["rows"]
        by_label = {r[0]: r[1] for r in sa if r and len(r) > 1}
        assert by_label["Max Strategy Drawdown"] == -120.0
        assert by_label["Max Strategy Drawdown (%)"] == -0.0012
        assert by_label["Profit Factor"] == -1.9          # NOT recomputed here
        assert by_label["% Profitable"] == 0.5
        st = _sheet(cap, "Settings")["rows"]
        st_by = {r[0]: r[1] for r in st if r and len(r) > 1}
        assert st_by["Point Value"] == "$50"              # string, verbatim
        lot = _sheet(cap, "List of Trades")["rows"]
        # entry row 4 (idx 3): Drawdown ($) signed-negative at header col 14
        header = lot[2]
        dd_col = header.index("Drawdown ($)")
        assert lot[3][dd_col] == -25.0

    def test_structure_preserved_blank_rows_and_header_row3(self):
        cap = capture_workbook(FIXTURE_XLSX)
        lot = _sheet(cap, "List of Trades")["rows"]
        assert lot[0] == ["List of Trades"]   # title row
        assert lot[1] == []                   # interior blank row PRESERVED
        assert lot[2][:4] == ["Trade #", "Order #", "Type", "Signal"]
        # trailing unpaired Entry row is present verbatim (capture ≠ pairing)
        assert any(r and r[0] == 11 for r in lot[3:])

    def test_datetimes_wrapped_typed(self):
        cap = capture_workbook(FIXTURE_XLSX)
        st = _sheet(cap, "Settings")["rows"]
        start = next(r[1] for r in st if r and r[0] == "Start Date")
        assert isinstance(start, dict) and start["t"] == "dt"
        assert start["v"].startswith("2026-06-24T09:30")

    def test_nonfinite_cells_encoded_json_safe(self):
        """F2 discipline: a non-finite float must never become a bare
        JSON token — it encodes as {"t":"n","v":"inf"|"nan"}. Pinned at
        the ENCODER (xlsx itself cannot round-trip inf/nan as numeric
        cells — openpyxl drops them — so the guard is defense against
        future openpyxl/shape drift, not a file-reachable path)."""
        assert wc._encode_cell(float("inf"), "General") == {"t": "n", "v": "inf"}
        assert wc._encode_cell(float("-inf"), "General") == {"t": "n", "v": "-inf"}
        assert wc._encode_cell(float("nan"), "General") == {"t": "n", "v": "nan"}
        json.dumps(wc._encode_cell(float("nan"), "0.00"), allow_nan=False)

    def test_capture_serializes_with_allow_nan_false(self):
        json.dumps(capture_workbook(FIXTURE_XLSX), allow_nan=False)

    def test_rejects_non_workbook_bytes(self):
        with pytest.raises(BacktestAdapterError):
            capture_workbook(b"<xml>not a zip</xml>")

    def test_cell_cap_fails_loud_not_truncated(self, monkeypatch):
        monkeypatch.setattr(wc, "MAX_CAPTURE_CELLS", 10)
        with pytest.raises(BacktestAdapterError, match="too large"):
            capture_workbook(FIXTURE_XLSX)

    def test_adapter_capture_method_delegates(self):
        adapter = get_backtest_adapter("multicharts")
        assert adapter.capture(FIXTURE_XLSX, "f.xlsx") == \
            capture_workbook(FIXTURE_XLSX)

    def test_parse_fills_contracts(self):
        """G-M7: the raw contract count rides each normalized trade."""
        adapter = get_backtest_adapter("multicharts")
        result = adapter.parse(FIXTURE_XLSX, "f.xlsx")
        assert result.trades and all(t.contracts == 2.0 for t in result.trades)


# ═══ G-M1 — verbatim report store + fetch ═══════════════════════════════════

class TestReportStore:
    @pytest.mark.asyncio
    async def test_import_stores_and_report_endpoint_serves_capture(self, mdb):
        mid = await mdb.create_potential_model("MC", "micro", "", {})
        res = await _import_fixture(mdb, mid)
        assert res["summary"]["source_file"] == "mc_synthetic.xlsx"  # G-M7
        resp = await rm.api_model_run_report(mid, res["run_id"])
        assert resp.status_code == 200
        data = _jbody(resp)
        assert data["report"]["format"] == "workbook.v1"
        assert len(data["report"]["sheets"]) == 8
        # the capture round-trips byte-faithful through the DB
        assert data["report"] == json.loads(
            json.dumps(capture_workbook(FIXTURE_XLSX)))
        assert len(data["equity"]) == 10
        assert data["trades"][0]["contracts"] == 2.0
        assert data["run"]["summary"]["source_file"] == "mc_synthetic.xlsx"
        assert "report_json" not in data["run"]

    @pytest.mark.asyncio
    async def test_report_404s_unknown_and_cross_model(self, mdb):
        m1 = await mdb.create_potential_model("A", "micro", "", {})
        m2 = await mdb.create_potential_model("B", "micro", "", {})
        res = await _import_fixture(mdb, m1)
        for model_id, run_id in ((m1, 999999), (m2, res["run_id"]), (999, 1)):
            resp = await rm.api_model_run_report(model_id, run_id)
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_legacy_run_without_capture_reports_null(self, mdb):
        mid = await mdb.create_potential_model("L", "micro", "", {})
        rid = await mdb.create_model_backtest(
            mid, "multicharts",
            {"session_name": "legacy", "summary": {"net_profit": 1.0},
             "trades": [], "equity_curve": []})
        data = _jbody(await rm.api_model_run_report(mid, rid))
        assert data["report"] is None

    @pytest.mark.asyncio
    async def test_run_list_never_carries_report_json(self, mdb):
        mid = await mdb.create_potential_model("MC", "micro", "", {})
        await _import_fixture(mdb, mid)
        runs = await mdb.list_model_backtests(mid)
        assert runs and all("report_json" not in r for r in runs)
        resp = await rm.api_model_runs(mid)
        body = _jbody(resp)
        assert body["runs"] and all(
            "report_json" not in r and "summary_json" not in r
            for r in body["runs"])


# ═══ G-M3 — overview feed ═══════════════════════════════════════════════════

class TestOverviewFeed:
    @pytest.mark.asyncio
    async def test_latest_completed_run_and_counts(self, mdb):
        m1 = await mdb.create_potential_model("With", "micro", "", {})
        m2 = await mdb.create_potential_model("Without", "macro", "", {})
        r1 = await _import_fixture(mdb, m1, "first.xlsx")
        r2 = await _import_fixture(mdb, m1, "second.xlsx")
        # a FAILED run must never become the latest
        failed = await mdb.create_backtest_session(
            "f", "imported", "", "", {}, model_id=m1, source_app="multicharts")
        await mdb.finish_backtest_session(failed, "failed", {})
        feed = {m["id"]: m for m in await mdb.list_models_overview()}
        assert feed[m1]["runs_count"] == 2
        assert feed[m1]["latest_run"]["id"] == r2["run_id"] > r1["run_id"]
        assert feed[m1]["latest_run"]["summary"]["net_profit"] == 250.0
        assert len(feed[m1]["spark"]) == 10
        assert feed[m2]["runs_count"] == 0
        assert feed[m2]["latest_run"] is None and feed[m2]["spark"] == []

    @pytest.mark.asyncio
    async def test_spark_downsampled_keeps_first_and_last(self, mdb):
        mid = await mdb.create_potential_model("S", "micro", "", {})
        sid = await mdb.create_backtest_session(
            "s", "imported", "", "", {}, model_id=mid, source_app="x")
        curve = [{"dt": f"2026-01-01T{i // 3600:02d}:{(i // 60) % 60:02d}:{i % 60:02d}",
                  "equity": 1000.0 + i, "drawdown": 0.0} for i in range(200)]
        await mdb.insert_backtest_equity(sid, curve)
        await mdb.finish_backtest_session(sid, "completed", {})
        feed = (await mdb.list_models_overview())[0]
        assert len(feed["spark"]) == 48
        assert feed["spark"][0] == 1000.0 and feed["spark"][-1] == 1199.0

    @pytest.mark.asyncio
    async def test_route_cleans_raw_json_columns(self, mdb):
        await mdb.create_potential_model("C", "micro", "", {}, source={"app": "MC"})
        body = _jbody(await rm.api_models_overview())
        m = body["models"][0]
        for raw in rm._RAW_JSON_KEYS:
            assert raw not in m
        assert m["source"] == {"app": "MC"}


# ═══ G-M4 — source binding + tags ═══════════════════════════════════════════

class TestSourceAndTags:
    @pytest.mark.asyncio
    async def test_create_update_roundtrip(self, mdb):
        resp = await rm.api_create_model(_json_req({
            "name": "S", "type": "micro",
            "source": {"app": "MultiCharts", "symbol": "@ES", "point_value": 50},
            "tags": [" orb ", "es", ""],
        }))
        mid = _jbody(resp)["model_id"]
        got = _jbody(await rm.api_get_model(mid))
        assert got["source"]["symbol"] == "@ES"
        assert got["tags"] == ["orb", "es"]          # trimmed + de-blanked
        # update with tags=None leaves them untouched; a list overwrites
        await rm.api_update_model(_json_req({"name": "S", "type": "micro"}), mid)
        assert _jbody(await rm.api_get_model(mid))["tags"] == ["orb", "es"]
        await rm.api_update_model(
            _json_req({"name": "S", "type": "micro", "tags": ["new"]}), mid)
        assert _jbody(await rm.api_get_model(mid))["tags"] == ["new"]

    @pytest.mark.asyncio
    async def test_validation_rejects_bad_shapes(self, mdb):
        cases = [
            {"name": "x", "source": ["not", "a", "dict"]},
            {"name": "x", "source": {"pv": float("inf")}},
            {"name": "x", "tags": "not-a-list"},
            {"name": "x", "tags": [1, 2]},
            {"name": "x", "tags": ["y" * 49]},
        ]
        for body in cases:
            resp = await rm.api_create_model(_json_req(body))
            assert resp.status_code == 400, body

    @pytest.mark.asyncio
    async def test_upload_auto_seeds_empty_source_only(self, mdb):
        """§6-3b: an import binds the Settings-derived source ONLY when
        the model has none — operator-entered bindings are never
        overwritten."""
        empty = await mdb.create_potential_model("E", "micro", "", {})
        bound = await mdb.create_potential_model(
            "B", "micro", "", {}, source={"app": "Manual", "symbol": "NQ"})
        res = await _import_fixture(mdb, empty)
        assert res["source_seeded"] is True
        src = (await mdb.get_potential_model(empty))["source"]
        assert src["symbol"] == "@ES" and src["point_value"] == 50.0
        assert src["app"] == "MultiCharts" and src["initial_capital"] == 100000.0
        res2 = await _import_fixture(mdb, bound)
        assert res2["source_seeded"] is False
        assert (await mdb.get_potential_model(bound))["source"]["symbol"] == "NQ"


# ═══ G-M5 — dry-run preview + combined create+import ════════════════════════

class TestDryRunAndCombinedImport:
    @pytest.mark.asyncio
    async def test_upload_dry_run_previews_and_writes_nothing(self, mdb):
        mid = await mdb.create_potential_model("D", "micro", "", {})
        resp = await rm.upload_model_backtest(
            _req(method="POST"), mid, file=_upload(FIXTURE_XLSX),
            app_id="multicharts", format="json", dry_run="1")
        body = _jbody(resp)
        assert body["preview"] is True
        assert body["trades_count"] == 10
        assert body["summary"]["net_profit"] == 250.0
        assert body["source_suggestion"]["symbol"] == "@ES"
        assert len(body["sheets"]) == 8
        assert await mdb.list_model_backtests(mid) == []       # nothing saved
        assert (await mdb.get_potential_model(mid))["source"] == {}  # no seed

    @pytest.mark.asyncio
    async def test_upload_dry_run_without_json_fails_loud(self, mdb):
        """P7 audit LOW-1 fold: the htmx lane has no preview UI — a bare
        ?dry_run=1 must 400, never silently commit a real import."""
        mid = await mdb.create_potential_model("D", "micro", "", {})
        resp = await rm.upload_model_backtest(
            _req(method="POST"), mid, file=_upload(FIXTURE_XLSX),
            app_id="multicharts", dry_run="1")
        assert resp.status_code == 400
        assert "dry_run requires format=json" in _jbody(resp)["error"]
        assert await mdb.list_model_backtests(mid) == []

    @pytest.mark.asyncio
    async def test_upload_json_errors_carry_status(self, mdb):
        resp = await rm.upload_model_backtest(
            _req(method="POST"), 999, file=_upload(FIXTURE_XLSX),
            app_id="multicharts", format="json")
        assert resp.status_code == 404 and "error" in _jbody(resp)
        mid = await mdb.create_potential_model("D", "micro", "", {})
        resp = await rm.upload_model_backtest(
            _req(method="POST"), mid, file=_upload(b"garbage"),
            app_id="multicharts", format="json")
        assert resp.status_code == 400 and "error" in _jbody(resp)

    @pytest.mark.asyncio
    async def test_html_lane_unchanged_and_still_captures(self, mdb):
        """The Jinja lane keeps its 200+fragment contract AND now stores
        the verbatim capture (shared path)."""
        mid = await mdb.create_potential_model("H", "micro", "", {})
        resp = await rm.upload_model_backtest(
            _req(method="POST"), mid, file=_upload(FIXTURE_XLSX),
            app_id="multicharts")
        assert resp.status_code == 200
        assert "text-red" not in resp.body.decode()
        runs = await mdb.list_model_backtests(mid)
        assert len(runs) == 1
        data = await mdb.get_model_backtest_report(mid, runs[0]["id"])
        assert data["report"]["format"] == "workbook.v1"

    @pytest.mark.asyncio
    async def test_combined_import_creates_binds_and_returns_ids(self, mdb):
        resp = await rm.api_create_model_and_import(
            file=_upload(FIXTURE_XLSX, "es.xlsx"), app_id="multicharts",
            payload=json.dumps({"name": "Combo", "type": "micro",
                                "tags": ["es"]}))
        body = _jbody(resp)
        model = await mdb.get_potential_model(body["model_id"])
        assert model["name"] == "Combo"
        assert model["source"]["symbol"] == "@ES"     # bound from Settings
        assert model["tags"] == ["es"]
        data = await mdb.get_model_backtest_report(
            body["model_id"], body["run_id"])
        assert data["report"] is not None
        assert data["run"]["summary"]["source_file"] == "es.xlsx"

    @pytest.mark.asyncio
    async def test_combined_import_dry_run_creates_nothing(self, mdb):
        resp = await rm.api_create_model_and_import(
            file=_upload(FIXTURE_XLSX), app_id="multicharts",
            payload="", dry_run="1")
        assert _jbody(resp)["preview"] is True
        assert await mdb.list_potential_models() == []

    @pytest.mark.asyncio
    async def test_combined_import_rolls_back_model_on_import_failure(
            self, mdb, monkeypatch):
        async def _boom(*a, **k):
            raise RuntimeError("disk full")
        monkeypatch.setattr(mdb, "create_model_backtest", _boom)
        resp = await rm.api_create_model_and_import(
            file=_upload(FIXTURE_XLSX), app_id="multicharts",
            payload=json.dumps({"name": "Doomed", "type": "micro"}))
        assert resp.status_code == 500
        assert await mdb.list_potential_models() == []   # rolled back

    @pytest.mark.asyncio
    async def test_combined_import_rejects_bad_payload(self, mdb):
        for payload in ("", "not json", json.dumps(["list"]),
                        json.dumps({"name": ""})):
            resp = await rm.api_create_model_and_import(
                file=_upload(FIXTURE_XLSX), app_id="multicharts",
                payload=payload)
            assert resp.status_code == 400, payload
        assert await mdb.list_potential_models() == []


# ═══ G-M6 — usage reverse feed ══════════════════════════════════════════════

class TestUsageFeed:
    @pytest.mark.asyncio
    async def test_usage_shapes_and_model_filter(self, mdb):
        mid = await mdb.create_potential_model("U", "micro", "", {})
        other = await mdb.create_potential_model("O", "micro", "", {})
        await mdb._conn.execute(
            "INSERT INTO closed_positions (account_id, symbol, direction, "
            "net_pnl, exit_time_ms, terminal_position_id, model_id) "
            "VALUES (1, 'BTCUSDT', 'long', 12.5, 1750000000000, 'tp1', ?)",
            (mid,))
        await mdb._conn.execute(
            "INSERT INTO closed_positions (account_id, symbol, direction, "
            "net_pnl, exit_time_ms, terminal_position_id, model_id) "
            "VALUES (1, 'ETHUSDT', 'short', -3.0, 1750000000001, 'tp2', ?)",
            (other,))
        await mdb._conn.execute(
            "INSERT INTO pre_trade_log (timestamp, ticker, side, model_id) "
            "VALUES ('2026-07-01T00:00:00', 'BTCUSDT', 'long', ?)", (mid,))
        await mdb._conn.commit()
        body = _jbody(await rm.api_model_usage(mid))
        assert [c["symbol"] for c in body["closed"]] == ["BTCUSDT"]
        assert body["closed"][0]["net_pnl"] == 12.5
        assert [p["ticker"] for p in body["plans"]] == ["BTCUSDT"]
        assert _jbody(await rm.api_model_usage(other))["plans"] == []

    @pytest.mark.asyncio
    async def test_usage_404_unknown_model(self, mdb):
        resp = await rm.api_model_usage(12345)
        assert resp.status_code == 404
