"""
v2.7 Phase 3 — model-library routes (JSON API + fragments + Form
mutations + backtest upload + calculator prefill).

Per the LOW-023 constraint, route LOGIC is tested via direct handler
calls with the module `db` monkeypatched to a temp DatabaseManager —
NOT a second TestClient (which hangs the suite). GET-route 200 smokes
ride tests/test_routes.py's parametrized lists (extended this phase).
Fragment RENDER correctness uses the api.helpers templates env
(compile-render discipline, MED-047 — same env the app renders with,
so the fmt/fmt_price globals are present).

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
from api.helpers import templates
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


def _html(resp) -> str:
    return resp.body.decode()


_FORM_DEFAULTS = dict(
    name="", model_type="both", description="", risk_pct="",
    sizing_rule="", window_seconds="", tp_methodology="",
    sl_methodology="", apply_regime_multiplier="",
    size_override_default="", entry_logic="", exit_logic="",
    target_universe="", regime_config="", notes="",
)


def _form_args(**over):
    args = dict(_FORM_DEFAULTS)
    args.update(over)
    return args


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
async def test_form_create_parses_preset_and_refreshes_list_oob(mdb):
    resp = await rm.create_model_form(_req(method="POST"), **_form_args(
        name="Breakout", model_type="micro", description="d",
        risk_pct="1.5", window_seconds="300", apply_regime_multiplier="1",
        entry_logic="OR breakout", notes="v1",
    ))
    html = _html(resp)
    assert "saved ✓" in html
    assert 'id="model-list" hx-swap-oob="innerHTML"' in html
    assert "Breakout" in html  # the oob list carries the new model
    rows = await mdb.list_potential_models()
    assert rows[0]["risk_preset"] == {
        "apply_regime_multiplier": True, "risk_pct": 1.5,
        "window_seconds": 300,
    }
    assert rows[0]["strategy"]["entry_logic"] == "OR breakout"


@pytest.mark.asyncio
async def test_form_create_validation_errors_are_200_spans(mdb):
    for over, msg in [
        (dict(name=""), "Name is required"),
        (dict(name="x", model_type="bogus"), "Type must be"),
        (dict(name="x", risk_pct="abc"), "must be numeric"),
        (dict(name="x", risk_pct="150"), "Risk % must be in"),
        (dict(name="x", window_seconds="0"), "Window seconds"),
    ]:
        resp = await rm.create_model_form(_req(method="POST"),
                                          **_form_args(**over))
        assert resp.status_code == 200
        assert msg in _html(resp)
    assert await mdb.list_potential_models() == []


@pytest.mark.asyncio
async def test_form_update_and_unknown_model(mdb):
    mid = await mdb.create_potential_model("Old", "both", "", {},
                                           risk_preset={"risk_pct": 1.0})
    resp = await rm.update_model_form(_req(method="POST"), mid, **_form_args(
        name="New", model_type="macro", risk_pct="2.0"))
    assert "updated ✓" in _html(resp)
    d = await mdb.get_potential_model(mid)
    assert d["name"] == "New"
    assert d["risk_preset"] == {"apply_regime_multiplier": False,
                                "risk_pct": 2.0}
    resp = await rm.update_model_form(_req(method="POST"), 99999,
                                      **_form_args(name="X"))
    assert "Model not found" in _html(resp)


@pytest.mark.asyncio
async def test_form_delete_removes_model_and_runs(mdb):
    mid = await mdb.create_potential_model("Doomed", "both", "", {})
    await mdb.create_model_backtest(mid, "multicharts", {
        "session_name": "r", "summary": {"net_profit": 1.0},
        "trades": [], "equity_curve": [],
    })
    resp = await rm.delete_model_form(mid)
    html = _html(resp)
    assert "Model deleted." in html
    assert 'id="model-list" hx-swap-oob="innerHTML"' in html
    assert await mdb.get_potential_model(mid) is None
    assert await mdb.list_model_backtests(mid) == []


@pytest.mark.asyncio
async def test_form_edit_roundtrip_full_snapshot_semantics(mdb):
    """Audit fold: the edit form is a full snapshot — a re-submitted
    checked box stays True; an absent box overwrites True to False."""
    mid = await mdb.create_potential_model(
        "Snap", "both", "", {}, risk_preset={"apply_regime_multiplier": True,
                                             "risk_pct": 1.0})
    # The rendered edit form carries checked state — resubmit keeps it.
    await rm.update_model_form(_req(method="POST"), mid, **_form_args(
        name="Snap", risk_pct="1.0", apply_regime_multiplier="1"))
    d = await mdb.get_potential_model(mid)
    assert d["risk_preset"]["apply_regime_multiplier"] is True
    # Unchecking (absent field) overwrites to False — snapshot semantics.
    await rm.update_model_form(_req(method="POST"), mid, **_form_args(
        name="Snap", risk_pct="1.0"))
    d = await mdb.get_potential_model(mid)
    assert d["risk_preset"]["apply_regime_multiplier"] is False


@pytest.mark.asyncio
async def test_form_edit_preserves_legacy_config(mdb):
    """P3 audit MED-1 pin: the new form has no config editor — editing a
    legacy model (backtest.html panel, config.signals/...) must pass the
    stored config through, not wipe it to {}."""
    legacy_config = {"signals": ["rsi"], "risk": {"r": 1}, "regime": "bull"}
    mid = await mdb.create_potential_model("Legacy", "both", "", legacy_config)
    resp = await rm.update_model_form(_req(method="POST"), mid,
                                      **_form_args(name="Legacy renamed"))
    assert "updated ✓" in _html(resp)
    d = await mdb.get_potential_model(mid)
    assert d["name"] == "Legacy renamed"
    assert d["config"] == legacy_config


@pytest.mark.asyncio
async def test_delete_oob_carries_refreshed_empty_list(mdb):
    mid = await mdb.create_potential_model("OnlyOne", "both", "", {})
    html = _html(await rm.delete_model_form(mid))
    assert "No models yet" in html  # the oob list really re-rendered


@pytest.mark.asyncio
async def test_model_name_is_escaped_in_fragments(mdb):
    """XSS pin: autoescape must stay on for the fragment renders."""
    evil = '<script>alert(1)</script>&"'
    await mdb.create_potential_model(evil, "both", "", {})
    listed = _html(await rm.frag_model_list(_req()))
    assert "<script>alert(1)</script>" not in listed
    assert "&lt;script&gt;" in listed


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
    mid = await mdb.create_potential_model("MC", "micro", "", {})
    resp = await rm.upload_model_backtest(
        _req(method="POST"), mid,
        file=_upload((FIXTURES / "mc_synthetic.xlsx").read_bytes()),
        app_id="multicharts",
    )
    html = _html(resp)
    assert "multicharts" in html and "text-red" not in html
    runs = await mdb.list_model_backtests(mid)
    assert len(runs) == 1
    assert runs[0]["summary"]["net_profit"] == 250.0
    # §6-3b: Settings-sheet params persisted under summary_json.
    assert runs[0]["summary"]["settings"]["Point Value"] == "$50"
    assert len(await mdb.get_backtest_trades(runs[0]["id"])) == 10


@pytest.mark.asyncio
async def test_upload_error_lanes_render_banner_not_500(mdb):
    mid = await mdb.create_potential_model("MC", "micro", "", {})
    cases = [
        # (model_id, bytes, app_id, expected banner text)
        (mid, b"garbage", "multicharts", "not a MultiCharts"),
        (mid, b"x", "no_such_app", "No backtest adapter registered"),
        (mid, b"", "multicharts", "Empty file."),
        (99999, b"x", "multicharts", "Model not found."),
        (mid, b"y" * (rm.MAX_UPLOAD_BYTES + 1), "multicharts",
         "File too large"),
    ]
    for model_id, data, app_id, expected in cases:
        resp = await rm.upload_model_backtest(
            _req(method="POST"), model_id,
            file=_upload(data), app_id=app_id)
        assert resp.status_code == 200, expected
        assert expected in _html(resp)
    assert await mdb.list_model_backtests(mid) == []


@pytest.mark.asyncio
async def test_upload_post_parse_db_failure_renders_banner(mdb, monkeypatch):
    """The post-parse failure lane: create_model_backtest raising must
    yield the 'nothing saved' banner (its atomicity guarantees the DB
    state), not a 500."""
    mid = await mdb.create_potential_model("MC", "micro", "", {})

    async def _boom(*a, **k):
        raise RuntimeError("simulated insert failure")

    monkeypatch.setattr(mdb, "create_model_backtest", _boom)
    resp = await rm.upload_model_backtest(
        _req(method="POST"), mid,
        file=_upload((FIXTURES / "mc_synthetic.xlsx").read_bytes()),
        app_id="multicharts")
    assert resp.status_code == 200
    assert "Import failed after parse" in _html(resp)


# ── Calculator prefill ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prefill_returns_risk_preset(mdb):
    mid = await mdb.create_potential_model("P", "both", "", {},
                                           risk_preset=PRESET)
    body = _jbody(await rm.calculator_prefill(mid))
    assert body == {"model_id": mid, "name": "P", "risk_preset": PRESET}
    assert (await rm.calculator_prefill(99999)).status_code == 404


# ── Fragment handlers (GET) ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fragment_handlers_render(mdb):
    empty = _html(await rm.frag_model_list(_req()))
    assert "No models yet" in empty

    mid = await mdb.create_potential_model(
        "FragModel", "micro", "desc", {}, risk_preset=PRESET,
        strategy=STRATEGY)
    listed = _html(await rm.frag_model_list(_req()))
    assert "FragModel" in listed and "MICRO" in listed

    detail = _html(await rm.frag_model_detail(_req(), mid))
    assert "FragModel" in detail
    assert "Imported backtests" in detail
    assert "backtest-upload" in detail  # upload form embedded

    blank = _html(await rm.frag_model_form_blank(_req()))
    assert "New model" in blank and 'hx-post="/models"' in blank

    edit = _html(await rm.frag_model_form_edit(_req(), mid))
    assert "Edit model" in edit and "FragModel" in edit
    assert f'/models/{mid}/update' in edit

    missing = _html(await rm.frag_model_detail(_req(), 99999))
    assert "Model not found" in missing

    runs_frag = _html(await rm.frag_model_backtests(_req(), mid))
    assert "No imported backtests yet" in runs_frag


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


@pytest.mark.parametrize("template,ctx,expect", [
    ("fragments/model_list.html", {"models": []}, "No models yet"),
    ("fragments/model_list.html", {"models": [_MODEL_CTX]}, "BOTH"),
    ("fragments/model_detail.html",
     {"model": _MODEL_CTX, "runs": [_RUN_CTX], "adapters": _ADAPTERS},
     "Risk preset"),
    ("fragments/model_form.html", {"model": None}, "New model"),
    ("fragments/model_form.html", {"model": _MODEL_CTX}, "Edit model"),
    ("fragments/model_backtest_list.html",
     {"runs": [_RUN_CTX], "error": ""}, "50.0%"),
    ("fragments/model_backtest_list.html",
     {"runs": [], "error": "boom"}, "boom"),
    ("fragments/model_backtest_upload.html",
     {"model": _MODEL_CTX, "adapters": _ADAPTERS}, "Import report"),
    ("fragments/model_backtest_upload.html",
     {"model": _MODEL_CTX, "adapters": []}, "Import report"),
])
def test_fragment_templates_compile_render(template, ctx, expect):
    html = templates.env.get_template(template).render(**ctx)
    assert expect in html
