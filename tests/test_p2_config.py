"""P2 Config unit tests (v3.0): the preset table + its sizing envelope.

The endpoint smokes + apply-preset end-to-end live in tests/test_routes.py (the
isolated TestClient, LOW-023). Here we pin the pure preset data: coverage vs the
DD-posture table, the full sizing key set, and that every preset's sizing passes
the real param bounds (so apply-preset never 400s on its own values).
"""
from core.strategy_presets import STRATEGY_PRESETS, PRESET_PARAMS

_NAMED = {"scalping", "day_trading", "swing", "position", "custom"}
_SIZING_KEYS = {
    "individual_risk_per_trade", "max_w_loss_percent", "max_dd_percent",
    "max_exposure", "max_position_count", "max_correlated_exposure",
}


def test_preset_tables_cover_the_same_named_presets():
    assert set(STRATEGY_PRESETS) == _NAMED
    assert set(PRESET_PARAMS) == _NAMED


def test_non_custom_presets_have_full_sizing_and_custom_is_empty():
    for name in ("scalping", "day_trading", "swing", "position"):
        assert set(PRESET_PARAMS[name]) == _SIZING_KEYS, name
    assert PRESET_PARAMS["custom"] == {}


def test_preset_sizing_passes_param_bounds():
    """Every preset's sizing must satisfy validate_params — else apply-preset
    would 400 on its own preset values."""
    from core.state import validate_params
    for name in ("scalping", "day_trading", "swing", "position"):
        sizing = {k: float(v) for k, v in PRESET_PARAMS[name].items()}
        assert validate_params(sizing) == [], f"{name}: {validate_params(sizing)}"


def test_apply_preset_endpoint_composes_writers(monkeypatch):
    """The /api/config/apply-preset handler composes BOTH writers (DD settings +
    sizing params) + publishes, with the writers STUBBED — so it never touches
    live data. This is the isolated stand-in for the end-to-end POST: the
    account_settings writer resolves config.DATA_DIR (the LIVE per-account DB),
    which the shared TestClient's temp-DB rebind does NOT isolate (the F5 gap),
    so a real POST would mutate operator data."""
    import asyncio
    import json as _json
    import core.strategy_presets as sp
    import core.account_registry as ar
    import core.event_bus as eb
    import api.routes_config as rc
    from core.state import app_state

    calls = {"settings": None, "params": None, "published": False}
    monkeypatch.setattr(sp, "apply_preset",
                        lambda aid, name, **k: calls.__setitem__("settings", (aid, name)))
    monkeypatch.setattr(ar.account_registry, "get_account_params", lambda aid: {})

    async def _upd(aid, params):
        calls["params"] = (aid, dict(params))
    monkeypatch.setattr(ar.account_registry, "update_account_params", _upd)

    async def _pub(ch, payload):
        calls["published"] = True
    monkeypatch.setattr(eb.event_bus, "publish", _pub)

    class _Req:
        async def json(self):
            return {"preset": "swing"}

    params_snap = dict(app_state.params)
    try:
        resp = asyncio.run(rc.api_config_apply_preset(_Req()))
    finally:
        app_state.params.clear()
        app_state.params.update(params_snap)

    data = _json.loads(resp.body)
    assert data["status"] == "ok" and data["preset"] == "swing"
    assert calls["settings"] == (app_state.active_account_id, "swing")
    assert calls["params"][1]["max_exposure"] == 5.0   # swing sizing envelope
    assert calls["published"] is True


def test_apply_preset_unknown_rejected():
    import asyncio
    import api.routes_config as rc

    class _Req:
        async def json(self):
            return {"preset": "nope"}

    resp = asyncio.run(rc.api_config_apply_preset(_Req()))
    assert resp.status_code == 400
