"""
v2.7 holistic-audit Task D — attribution surfaces + docs truth.

Pins for:
- F11: Pre-Trade Log Model column resolves the model_id FK when the
  free-text name is empty (picker-tagged calcs were invisible — the
  plan-time surface disagreed with the close-time stamp), with the
  close-row stamp's precedence: free text wins → library name →
  "(deleted model)" for dangling ids.
- F12: summary_json["settings"] renders read-only in the run list
  (persisted since P3 with zero consumers; plan §6-3b promised the
  render).
- F16 residual: non-dict / malformed JSON bodies on POST/PUT
  /api/models → 400 (previously 500 at body.get / request.json).

The F6 pins (position:closed model_names) live next to the P5 gate
pins they extend — tests/test_order_manager.py::TestModelNameGateV27.

Per LOW-023, route logic is tested via direct handler calls with the
module `db` monkeypatched to a temp DatabaseManager — NOT a second
TestClient. Fragment render correctness uses the api.helpers templates
env (compile-render discipline, MED-047).

Run: pytest tests/test_v27_taskd_attribution_surfaces.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from types import SimpleNamespace

import pytest
import pytest_asyncio
from starlette.requests import Request

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import api.routes_history as rh
import api.routes_models as rm
from api.helpers import templates
from core.database import DatabaseManager


# ── Fixtures / helpers ───────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def tdb(monkeypatch):
    """Temp DB wired as the routes_history + routes_models module `db`."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database = DatabaseManager(path=tmp.name)
    await database.initialize()
    monkeypatch.setattr(rh, "db", database)
    monkeypatch.setattr(rm, "db", database)
    # active_account_id is a read-only property on the real AppState —
    # patch the MODULE's app_state reference with a stub instead
    # (frag_history_pre_trade reads only .active_account_id).
    monkeypatch.setattr(rh, "app_state", SimpleNamespace(active_account_id=1))
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


def _raw_body_req(body: bytes, method: str = "POST") -> Request:
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http", "http_version": "1.1", "method": method,
        "path": "/x", "raw_path": b"/x", "root_path": "",
        "scheme": "http", "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("test", 0), "server": ("test", 80),
    }, receive)


def _html(resp) -> str:
    return resp.body.decode()


def _ptl_row(**over):
    """Minimal pre_trade_log insert dict (insert_pre_trade_log defaults
    the rest)."""
    row = {
        "account_id": 1, "ticker": "BTCUSDT", "side": "long",
        "average": 100.0, "sl_price": 95.0, "tp_price": 110.0,
        "size": 1.0, "notional": 100.0, "est_r": 2.0, "eligible": 1,
        "calc_id": "calc-x", "model_name": "", "model_id": None,
    }
    row.update(over)
    return row


# ── F11: DB batch name lookup ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_model_names_by_ids_found_and_missing(tdb):
    mid_a = await tdb.create_potential_model("Alpha", "both", "", {})
    mid_b = await tdb.create_potential_model("Beta", "micro", "", {})
    names = await tdb.get_model_names_by_ids([mid_a, mid_b, 99999])
    assert names == {mid_a: "Alpha", mid_b: "Beta"}  # dangling id absent


@pytest.mark.asyncio
async def test_get_model_names_by_ids_empty_and_none_tolerant(tdb):
    assert await tdb.get_model_names_by_ids([]) == {}
    assert await tdb.get_model_names_by_ids([None]) == {}


# ── F11: Pre-Trade Log fragment resolves the FK ──────────────────────────────

@pytest.mark.asyncio
async def test_pre_trade_fragment_renders_fk_model_name(tdb):
    """Picker-tagged rows (model_id set, free text empty) render the
    library name — the F11 mechanism (template read free text only)."""
    mid = await tdb.create_potential_model("Breakout v2", "both", "", {})
    await tdb.insert_pre_trade_log(_ptl_row(model_id=mid))
    html = _html(await rh.frag_history_pre_trade(_req()))
    assert "Breakout v2" in html


@pytest.mark.asyncio
async def test_pre_trade_fragment_free_text_wins_over_fk(tdb):
    """Same precedence as the close-row stamp: the operator's free text
    beats the FK-joined library name."""
    mid = await tdb.create_potential_model("LibraryName", "both", "", {})
    await tdb.insert_pre_trade_log(
        _ptl_row(model_name="OperatorTyped", model_id=mid))
    html = _html(await rh.frag_history_pre_trade(_req()))
    assert "OperatorTyped" in html
    assert "LibraryName" not in html


@pytest.mark.asyncio
async def test_pre_trade_fragment_dangling_fk_renders_deleted(tdb):
    """FK policy: ids dangle by design after a model delete — readers
    render '(deleted model)', not '—' and not a crash."""
    await tdb.insert_pre_trade_log(_ptl_row(model_id=424242))
    html = _html(await rh.frag_history_pre_trade(_req()))
    assert "(deleted model)" in html


# ── F12: Settings render in the run list ─────────────────────────────────────

_RUN_BASE = {
    "id": 7, "name": "@ES 1 Minute", "source_app": "multicharts",
    "date_from": "2026-01-01T00:00:00", "date_to": "2026-02-01T00:00:00",
    "summary": {"net_profit": 250.0, "win_rate": 0.5, "profit_factor": 2.0,
                "total_trades": 10},
}


# ── F16 residual: non-dict / malformed JSON bodies → 400 ─────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    json.dumps([1, 2, 3]).encode(),     # valid JSON, non-dict: list
    json.dumps("a string").encode(),    # valid JSON, non-dict: string
    json.dumps(42).encode(),            # valid JSON, non-dict: number
    b"{not json",                       # malformed
    b"",                                # empty body
])
async def test_create_model_non_dict_body_400(tdb, body):
    resp = await rm.api_create_model(_raw_body_req(body))
    assert resp.status_code == 400, (
        "non-dict/malformed bodies previously 500'd at body.get / "
        "request.json — the door guard must 400"
    )
    assert json.loads(resp.body)["error"] == "Body must be a JSON object"


@pytest.mark.asyncio
async def test_update_model_non_dict_body_400(tdb):
    mid = await tdb.create_potential_model("X", "both", "", {})
    resp = await rm.api_update_model(
        _raw_body_req(json.dumps([1]).encode(), method="PUT"), mid)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_model_valid_dict_still_works(tdb):
    """The guard must not reject the happy path."""
    resp = await rm.api_create_model(
        _raw_body_req(json.dumps({"name": "Ok"}).encode()))
    body = json.loads(resp.body)
    assert body.get("status") == "created"


# ── F16-residual class sweep: same mechanism at the other request.json()
# sites (the audit's finding was a sample — broad re-grep surfaced 8 more
# bare-`.get`-after-parse sites in routes_backtest / routes_regime /
# routes_admin / routes_accounts; JSON lanes → 400, HTML-alert lanes
# degrade to {} like their malformed-JSON lane). One pin per lane shape. ──

@pytest.mark.asyncio
async def test_fetch_ohlcv_non_dict_body_400():
    import api.routes_backtest as rb
    resp = await rb.api_fetch_ohlcv(_raw_body_req(b'[1, 2]'))
    assert resp.status_code == 400
    assert json.loads(resp.body)["error"] == "Body must be a JSON object"


@pytest.mark.asyncio
async def test_backtest_run_non_dict_body_400():
    import api.routes_backtest as rb
    resp = await rb.api_backtest_run(_raw_body_req(b'"config"'))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_regime_backfill_non_dict_body_400():
    import api.routes_regime as rr
    resp = await rr.api_regime_backfill(_raw_body_req(b'42'))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_admin_dd_toggle_non_dict_body_degrades_to_400():
    """HTML-alert lane: non-dict degrades to {} (the malformed-JSON
    convention) and the route's own validation 400s."""
    import api.routes_admin as ra
    resp = await ra.dd_enforcement_toggle(_raw_body_req(b'[]'))
    assert resp.status_code == 400
    assert b"Invalid mode" in resp.body
