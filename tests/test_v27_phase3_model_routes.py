"""
v2.7 Phase 3 — model-library routes (JSON API + backtest upload +
calculator prefill).

Per the LOW-023 constraint, route LOGIC is tested via direct handler
calls with the module `db` monkeypatched to a temp DatabaseManager —
NOT a second TestClient (which hangs the suite). GET-route 200 smokes
ride tests/test_routes.py's parametrized lists.

(Fragments slim-down 2026-07-30: the fragment-render + htmx form-lane
tests retired with the /fragments/models/* doors and their templates —
React does CRUD via /api/models; backtest-upload is JSON-only.)

Run: pytest tests/test_v27_phase3_model_routes.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from io import BytesIO
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import UploadFile
from starlette.requests import Request

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import api.routes_models as rm
from core.database import DatabaseManager

FIXTURES = Path(__file__).parent / "fixtures" / "multicharts"


# ── Fixtures / helpers ───────────────────────────────────────────────────────

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


def _json_req(payload: dict, path: str = "/x", method: str = "POST") -> Request:
    body = json.dumps(payload).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http", "http_version": "1.1", "method": method,
        "path": path, "raw_path": path.encode(), "root_path": "",
        "scheme": "http", "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("test", 0), "server": ("test", 80),
    }, receive)


def _jbody(resp) -> dict | list:
    return json.loads(resp.body)


def _upload(data: bytes, filename: str = "r.xlsx") -> UploadFile:
    return UploadFile(file=BytesIO(data), filename=filename)


PRESET = {"risk_pct": 1.5, "apply_regime_multiplier": True,
          "window_seconds": 300}
STRATEGY = {"entry_logic": "OR breakout", "exit_logic": "", "notes": "v1",
            "target_universe": "", "regime_config": ""}


# ── JSON API (contract intact + extended) ────────────────────────────────────

@pytest.mark.asyncio
async def test_json_list_and_get_decode_and_hide_raw_columns(mdb):
    mid = await mdb.create_potential_model(
        "M1", "micro", "d", {"a": 1}, risk_preset=PRESET, strategy=STRATEGY)
    listed = _jbody(await rm.api_list_models())
    assert listed[0]["risk_preset"] == PRESET
    assert listed[0]["strategy"]["entry_logic"] == "OR breakout"
    assert listed[0]["config"] == {"a": 1}
    for raw in ("config_json", "risk_preset_json", "strategy_json"):
        assert raw not in listed[0]
    one = _jbody(await rm.api_get_model(mid))
    assert one["risk_preset"] == PRESET
    assert "risk_preset_json" not in one


@pytest.mark.asyncio
async def test_json_create_accepts_new_fields(mdb):
    resp = await rm.api_create_model(_json_req({
        "name": "M2", "type": "macro", "description": "x",
        "risk_preset": PRESET, "strategy": STRATEGY,
    }))
    mid = _jbody(resp)["model_id"]
    d = await mdb.get_potential_model(mid)
    assert d["risk_preset"] == PRESET and d["strategy"] == STRATEGY


@pytest.mark.asyncio
async def test_json_create_validation(mdb):
    assert (await rm.api_create_model(_json_req({"name": ""}))).status_code == 400
    assert (await rm.api_create_model(
        _json_req({"name": "x", "type": "bogus"}))).status_code == 400
    assert (await rm.api_create_model(
        _json_req({"name": "x", "risk_preset": "not-a-dict"}))).status_code == 400


@pytest.mark.asyncio
async def test_json_rejects_non_finite_numbers_anywhere(mdb):
    """Holistic-audit F2: json.loads accepts NaN/Infinity/1e400 but
    starlette's JSONResponse(allow_nan=False) 500s on render — ONE
    poisoned model kills GET /api/models for the whole list. Reject at
    the door. Door-guard-only is sufficient BECAUSE the only writers are
    these now-guarded Python routes (browser JSON.stringify emits null
    for NaN, so JS callers can't poison) — a read-side clamp would MASK
    corrupt state, against the fail-loud rule."""
    for poison in (
        {"risk_preset": {"size_override_default": float("inf")}},
        {"risk_preset": {"risk_pct": float("nan")}},
        {"strategy": {"nested": {"deep": [1.0, float("inf")]}}},
        {"config": {"a": float("nan")}},
    ):
        resp = await rm.api_create_model(_json_req({"name": "P", **poison}))
        assert resp.status_code == 400, poison
        assert "NaN or Infinity" in _jbody(resp)["error"]
    assert await mdb.list_potential_models() == []

    # Clean create still round-trips through the JSON renderer.
    resp = await rm.api_create_model(_json_req(
        {"name": "Clean", "risk_preset": {"risk_pct": 1.5}}))
    assert _jbody(resp)["status"] == "created"
    listed = _jbody(await rm.api_list_models())
    assert listed[0]["risk_preset"] == {"risk_pct": 1.5}


@pytest.mark.asyncio
async def test_directly_poisoned_row_demonstrates_f2_blast_radius(mdb):
    """The F2 MECHANISM, demonstrated (audit fold): a poisoned row
    inserted BELOW the API (db-layer json.dumps has allow_nan=True)
    makes the whole-list render raise — the loud failure the door guard
    exists to prevent, and a tripwire if starlette's allow_nan behavior
    ever changes."""
    await mdb.create_potential_model(
        "Poisoned", "both", "", {}, risk_preset={"r": float("nan")})
    with pytest.raises(ValueError):
        await rm.api_list_models()


@pytest.mark.asyncio
async def test_json_null_name_and_bad_types_are_400_not_500(mdb):
    """F16 fold: {"name": null} previously passed validation (str(None)
    = "None") then crashed at .strip() → 500."""
    assert (await rm.api_create_model(
        _json_req({"name": None}))).status_code == 400
    assert (await rm.api_create_model(
        _json_req({"name": "x", "description": 123}))).status_code == 400
    mid = await mdb.create_potential_model("M", "both", "", {})
    assert (await rm.api_update_model(
        _json_req({"name": None}, method="PUT"), mid)).status_code == 400


@pytest.mark.asyncio
async def test_json_put_validates_type_and_404s(mdb):
    mid = await mdb.create_potential_model("M", "both", "", {},
                                           risk_preset=PRESET)
    # 3.1 fold: PUT now rejects a bogus type (pre-existing hole).
    resp = await rm.api_update_model(
        _json_req({"name": "M", "type": "bogus"}, method="PUT"), mid)
    assert resp.status_code == 400
    resp = await rm.api_update_model(
        _json_req({"name": "M", "type": "macro"}, method="PUT"), 99999)
    assert resp.status_code == 404
    resp = await rm.api_update_model(
        _json_req({"name": "M2", "type": "macro",
                   "risk_preset": {"risk_pct": 9.0}}, method="PUT"), mid)
    assert _jbody(resp)["status"] == "updated"
    d = await mdb.get_potential_model(mid)
    assert d["name"] == "M2" and d["risk_preset"] == {"risk_pct": 9.0}


# ── Form mutations (status span + hx-swap-oob list refresh) ─────────────────


@pytest.mark.asyncio
async def test_json_old_contract_passthrough(mdb):
    """Pre-v2.7 JSON bodies (no new fields) through the ROUTE layer:
    create writes {}; update preserves stored presets (None-semantics)."""
    resp = await rm.api_create_model(_json_req(
        {"name": "OldStyle", "type": "macro", "description": "d",
         "config": {"a": 1}}))
    mid = _jbody(resp)["model_id"]
    d = await mdb.get_potential_model(mid)
    assert d["risk_preset"] == {} and d["strategy"] == {}
    await mdb.update_potential_model(mid, "OldStyle", "macro", "d", {"a": 1},
                                     risk_preset={"risk_pct": 3.0})
    await rm.api_update_model(_json_req(
        {"name": "OldStyle2", "type": "macro"}, method="PUT"), mid)
    d = await mdb.get_potential_model(mid)
    assert d["name"] == "OldStyle2"
    assert d["risk_preset"] == {"risk_pct": 3.0}  # preserved, not cleared


# ── Backtest upload ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_happy_path_persists_run_and_settings(mdb):
    # Fragments slim-down (2026-07-30): the route is JSON-only — success
    # returns the run envelope instead of the retired backtest-list fragment.
    mid = await mdb.create_potential_model("MC", "micro", "", {})
    resp = await rm.upload_model_backtest(
        _req(method="POST"), mid,
        file=_upload((FIXTURES / "mc_synthetic.xlsx").read_bytes()),
        app_id="multicharts",
    )
    body = _jbody(resp)
    assert body["model_id"] == mid
    runs = await mdb.list_model_backtests(mid)
    assert len(runs) == 1
    assert body["run_id"] == runs[0]["id"]
    assert runs[0]["summary"]["net_profit"] == 250.0
    # §6-3b: Settings-sheet params persisted under summary_json.
    assert runs[0]["summary"]["settings"]["Point Value"] == "$50"
    assert len(await mdb.get_backtest_trades(runs[0]["id"])) == 10


@pytest.mark.asyncio
async def test_upload_error_lanes_are_json_with_status(mdb):
    # Fragments slim-down (2026-07-30): error lanes now carry real status
    # codes + {"error": ...} JSON (the 200-banner htmx contract retired
    # with model_backtest_list.html).
    mid = await mdb.create_potential_model("MC", "micro", "", {})
    cases = [
        # (model_id, bytes, app_id, expected status, expected error text)
        (mid, b"garbage", "multicharts", 400, "not a MultiCharts"),
        (mid, b"x", "no_such_app", 400, "No backtest adapter registered"),
        (mid, b"", "multicharts", 400, "Empty file."),
        (99999, b"x", "multicharts", 404, "Model not found."),
        (mid, b"y" * (rm.MAX_UPLOAD_BYTES + 1), "multicharts", 400,
         "File too large"),
    ]
    for model_id, data, app_id, status, expected in cases:
        resp = await rm.upload_model_backtest(
            _req(method="POST"), model_id,
            file=_upload(data), app_id=app_id)
        assert resp.status_code == status, expected
        assert expected in _jbody(resp)["error"]
    assert await mdb.list_model_backtests(mid) == []


@pytest.mark.asyncio
async def test_upload_post_parse_db_failure_is_json_500(mdb, monkeypatch):
    """The post-parse failure lane: create_model_backtest raising must
    yield the 'nothing saved' JSON error (its atomicity guarantees the
    DB state) — a real 500, not an unhandled exception."""
    mid = await mdb.create_potential_model("MC", "micro", "", {})

    async def _boom(*a, **k):
        raise RuntimeError("simulated insert failure")

    monkeypatch.setattr(mdb, "create_model_backtest", _boom)
    resp = await rm.upload_model_backtest(
        _req(method="POST"), mid,
        file=_upload((FIXTURES / "mc_synthetic.xlsx").read_bytes()),
        app_id="multicharts")
    assert resp.status_code == 500
    assert "Import failed after parse" in _jbody(resp)["error"]


# ── Calculator prefill ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prefill_returns_risk_preset(mdb):
    mid = await mdb.create_potential_model("P", "both", "", {},
                                           risk_preset=PRESET)
    body = _jbody(await rm.calculator_prefill(mid))
    assert body == {"model_id": mid, "name": "P", "risk_preset": PRESET}
    assert (await rm.calculator_prefill(99999)).status_code == 404


# ── Fragment handlers (GET) ──────────────────────────────────────────────────


# ── Template compile-render (MED-047 discipline) ────────────────────────────

_MODEL_CTX = {
    "id": 1, "name": "T", "type": "both", "description": "d",
    "created_at": "2026-07-16", "updated_at": None,
    "risk_preset": {"risk_pct": 1.0, "apply_regime_multiplier": True},
    "strategy": {"entry_logic": "e", "exit_logic": "", "notes": "",
                 "target_universe": "", "regime_config": ""},
}
_RUN_CTX = {
    "id": 7, "name": "@ES 1 Minute", "source_app": "multicharts",
    "date_from": "2026-01-01T00:00:00", "date_to": "2026-02-01T00:00:00",
    "summary": {"net_profit": 250.0, "win_rate": 0.5, "profit_factor": 2.0,
                "total_trades": 10},
}
_ADAPTERS = [{"app_id": "multicharts", "display_name": "MultiCharts",
              "accepted_extensions": [".xlsx", ".xml"]}]


