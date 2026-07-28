"""E2E-P4-001 regression pins — POST /api/config/apply-preset 500s with a target account.

Mechanism (investigated, reproduced live on the sandbox engine before fixing):
`account_registry.list_accounts()` is a COROUTINE function
(core/account_registry.py:320; the sync twin is `list_accounts_sync`, :325).
`api/routes_config.py` iterated it WITHOUT await inside the explicit-account_id
branch, so the set comprehension raised
`TypeError: 'coroutine' object is not iterable`. That escapes the route's own
try/except (which only wraps `apply_preset`), so FastAPI returned a bare 500
with an EMPTY body — no log line, no JSON error.

Blast radius: the branch runs whenever `account_id` is present in the body, and
the v3 Config UI ALWAYS sends it (`pages-config.jsx:690` posts
`{preset, account_id: tgt.id}`) — so Apply Preset was broken for EVERY preset
and EVERY target, including the active account. The omit-account_id path (legacy
callers) was unaffected, which is why no earlier test caught it.

Found by the Playwright Phase-4 sandbox mutation sweep.

The route is exercised directly with stubs — never through the shared TestClient:
apply-preset writes account_settings AND account_params, which resolve to the
operator's LIVE data dir (see MEMORY: no write-tests through the shared client).
"""
import asyncio
import json

import pytest

import api.routes_config as rc
from core.account_registry import account_registry


class _FakeRequest:
    def __init__(self, body: dict):
        self._body = body

    async def json(self):
        return self._body


@pytest.fixture
def stub_registry(monkeypatch):
    """Isolate the route from live stores: no settings/params are written."""
    async def _list_accounts():
        return [{"id": 1}, {"id": 2}]

    async def _update_account_params(aid, params):
        return None

    monkeypatch.setattr(account_registry, "list_accounts", _list_accounts)
    monkeypatch.setattr(account_registry, "get_account_params", lambda aid: {})
    monkeypatch.setattr(account_registry, "update_account_params", _update_account_params)
    monkeypatch.setattr("core.strategy_presets.apply_preset", lambda aid, preset: None)
    return account_registry


def _call(body: dict):
    return asyncio.run(rc.api_config_apply_preset(_FakeRequest(body)))


class TestApplyPresetAccountTarget:
    def test_explicit_account_id_does_not_500(self, stub_registry):
        resp = _call({"preset": "swing", "account_id": 2})
        assert resp.status_code == 200, (
            "explicit account_id must not 500 — the unawaited list_accounts() "
            "coroutine raised TypeError and returned an empty 500"
        )
        assert json.loads(resp.body)["account_id"] == 2

    def test_active_account_target_also_works(self, stub_registry):
        resp = _call({"preset": "swing", "account_id": 1})
        assert resp.status_code == 200
        assert json.loads(resp.body)["account_id"] == 1

    def test_unknown_account_id_still_404s(self, stub_registry):
        resp = _call({"preset": "swing", "account_id": 99})
        assert resp.status_code == 404, "the existence guard must survive the fix"

    def test_omitted_account_id_defaults_to_active(self, stub_registry):
        resp = _call({"preset": "swing"})
        assert resp.status_code == 200

    def test_list_accounts_is_async_and_has_a_sync_twin(self):
        """Pins the shape the bug turned on — a future sync/async flip must fail here."""
        assert asyncio.iscoroutinefunction(account_registry.list_accounts)
        assert not asyncio.iscoroutinefunction(account_registry.list_accounts_sync)
