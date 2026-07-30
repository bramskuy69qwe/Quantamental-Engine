"""
Add Account, wired in React (2026-07-30) — operator report: "add account in
config not working".

MECHANISM (investigated, not assumed): the React Config page rendered its
"+ Add Account" button `disabled`, with the title "Not wired in P2 — add
accounts via the current /config page". So on the React app the button did
nothing at all, and the workaround it named was the Jinja `/config` page —
the last of its kind after the retirement. Two things blocked the wiring:

  1. `POST /accounts` (the JSON door React can use) accepted neither
     `environment` nor `params_source`; only the HTML-returning
     `/accounts/add-and-reload` twin did. So the JSON lane could not create a
     testnet/paper account or seed params from an existing one.
  2. Nothing exposed the adapter catalog as JSON, so React could not build the
     exchange dropdown. → new `GET /api/config/exchanges`.

Also fixed here: the Jinja modal's `<form hx-post="/accounts">` meant a bare
Enter-key submit painted the raw JSON body into the result div and never
reloaded (the submit BUTTON overrode with add-and-reload, so only the keyboard
path was broken).

Credentials: every value below is fake. Route logic runs through direct
handler calls with `account_registry` stubbed — nothing touches live data.

Run: pytest tests/test_add_account_react.py -v
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tests._srcpin import code as _code   # noqa: E402

_SRC = Path(__file__).parent.parent / "frontend" / "src"


def _body(resp) -> dict:
    return json.loads(resp.body.decode("utf-8"))


# ── POST /accounts — the JSON door React posts to ────────────────────────────

class TestCreateAccountJsonDoor:
    @pytest.fixture(autouse=True)
    def _stub(self, monkeypatch):
        """Capture what reaches account_registry instead of writing anything."""
        import api.routes_accounts as ra
        self.calls = []

        async def _add_account(name, exchange, market_type, api_key, api_secret,
                               broker_account_id="", environment="live",
                               params_template=None):
            self.calls.append({
                "name": name, "exchange": exchange, "market_type": market_type,
                "environment": environment, "params_template": params_template,
                # str() would be masked by SensitiveStr — record the type only
                "key_type": type(api_key).__name__,
            })
            return 42

        monkeypatch.setattr(ra.account_registry, "add_account", _add_account)
        monkeypatch.setattr(ra.account_registry, "get_account_params",
                            lambda aid: {"individual_risk_per_trade": 0.01, "_from": aid})
        self.ra = ra

    async def _create(self, **over):
        # Every parameter is passed explicitly: a DIRECT handler call bypasses
        # FastAPI's dependency resolution, so an omitted argument arrives as the
        # raw `Form(...)` object rather than its default value. The declared
        # defaults are pinned separately, below.
        args = dict(name="New Acct", exchange="binance", market_type="future",
                    api_key="FAKE-KEY", api_secret="FAKE-SECRET",
                    environment="live", params_source="defaults")
        args.update(over)
        return await self.ra.create_account(request=None, **args)

    def test_declared_defaults_preserve_prior_behaviour(self):
        """The two new parameters are ADDITIVE: a caller that omits them must
        get exactly the pre-change behaviour. Asserted on the signature, which
        is what governs a real request."""
        import inspect
        sig = inspect.signature(self.ra.create_account)
        assert sig.parameters["environment"].default.default == "live"
        assert sig.parameters["params_source"].default.default == "defaults"

    @pytest.mark.asyncio
    async def test_happy_path_returns_the_new_id(self):
        resp = await self._create()
        assert resp.status_code == 200
        assert _body(resp) == {"status": "ok", "id": 42, "name": "New Acct"}

    @pytest.mark.asyncio
    async def test_environment_reaches_the_registry(self):
        """THE fix: without this the JSON door could only ever make a LIVE
        account, so React could not offer testnet/paper."""
        await self._create(environment="testnet")
        assert self.calls[0]["environment"] == "testnet"

    @pytest.mark.asyncio
    async def test_params_source_copies_from_another_account(self):
        await self._create(params_source="copy_7")
        assert self.calls[0]["params_template"] == {
            "individual_risk_per_trade": 0.01, "_from": 7}

    @pytest.mark.asyncio
    async def test_defaults_seed_no_params_template(self):
        await self._create(params_source="defaults")
        assert self.calls[0]["params_template"] is None

    @pytest.mark.asyncio
    async def test_unparseable_params_source_degrades_to_defaults(self):
        """A malformed selector must not fail the create."""
        for bad in ("copy_", "copy_abc", "garbage"):
            self.calls.clear()
            resp = await self._create(params_source=bad)
            assert resp.status_code == 200, bad
            assert self.calls[0]["params_template"] is None, bad

    @pytest.mark.asyncio
    async def test_blank_name_is_rejected(self):
        resp = await self._create(name="   ")
        assert resp.status_code == 400
        assert "name is required" in _body(resp)["error"]
        assert self.calls == [], "nothing may be created"

    @pytest.mark.asyncio
    async def test_name_is_stripped(self):
        await self._create(name="  Padded  ")
        assert self.calls[0]["name"] == "Padded"

    @pytest.mark.asyncio
    async def test_bad_exchange_is_rejected_before_any_write(self):
        resp = await self._create(exchange="not_a_real_exchange")
        assert resp.status_code == 400
        assert _body(resp)["status"] == "error"
        assert self.calls == []

    @pytest.mark.asyncio
    async def test_credentials_are_wrapped_before_leaving_the_route(self):
        """HIGH-029: the raw key must not sit unmasked in a stack frame."""
        await self._create()
        assert self.calls[0]["key_type"] == "SensitiveStr"


# ── GET /api/config/exchanges — the catalog the dropdown needs ───────────────

class TestExchangeCatalogDoor:
    @pytest.mark.asyncio
    async def test_returns_exchanges_and_market_types(self):
        import api.routes_config as rc
        body = json.loads((await rc.api_config_exchanges()).body.decode("utf-8"))
        assert body["exchanges"] and body["market_types"]
        first = body["exchanges"][0]
        assert set(first) >= {"value", "label", "is_beta"}

    @pytest.mark.asyncio
    async def test_canonical_exchange_is_first_and_not_beta(self):
        """Binance sorts first so the dropdown's default selection is the
        operator-verified adapter, not a Beta one."""
        import api.routes_config as rc
        body = json.loads((await rc.api_config_exchanges()).body.decode("utf-8"))
        assert body["exchanges"][0]["value"] == "binance"
        assert body["exchanges"][0]["is_beta"] is False

    @pytest.mark.asyncio
    async def test_beta_adapters_are_labelled(self):
        import api.routes_config as rc
        body = json.loads((await rc.api_config_exchanges()).body.decode("utf-8"))
        for x in body["exchanges"]:
            assert ("(Beta)" in x["label"]) == x["is_beta"], x

    @pytest.mark.asyncio
    async def test_market_types_accept_the_form_default(self):
        """The dialog defaults market_type to 'future'; the catalog must offer
        it, or the dropdown's initial value would be unselectable."""
        import api.routes_config as rc
        body = json.loads((await rc.api_config_exchanges()).body.decode("utf-8"))
        assert "future" in body["market_types"]


# ── React wiring (source pins — see tests/_srcpin.py for the discipline) ─────

class TestReactAddAccountWiring:
    def _code(self) -> str:
        return _code((_SRC / "pages-config.jsx").read_text(encoding="utf-8"))

    def test_button_is_no_longer_disabled(self):
        """The whole bug: the button rendered `disabled`, so clicking it did
        nothing. Pin the click handler, not the absence of a word."""
        code = self._code()
        idx = code.index("+ Add Account")
        seg = code[max(0, idx - 400):idx]
        assert "onClick={() => setAdding(true)}" in seg
        assert "disabled" not in seg, "the Add Account button must not be disabled"

    def test_dialog_posts_the_json_door_with_all_fields(self):
        code = self._code()
        assert "CfgAddAccountDialog" in code
        idx = code.index("_cfgPostForm('/accounts'")
        assert "json: true" in code[idx:idx + 120]
        for field in ("environment", "params_source", "api_key", "api_secret",
                      "market_type", "exchange"):
            assert field in code, field

    def test_dialog_reads_the_exchange_catalog(self):
        code = self._code()
        assert "/api/config/exchanges" in code

    def test_submit_is_blocked_until_the_required_fields_are_filled(self):
        """The engine rejects a blank name; the client must not offer a submit
        that is guaranteed to fail."""
        code = self._code()
        assert "const incomplete = !f.name.trim()" in code
        idx = code.index("const submit = async ()")
        assert "if (busy || incomplete) return;" in code[idx:idx + 160]

    def test_dialog_is_mounted_outside_the_grid(self):
        """ModelDialog is position:absolute and Pane is position:relative — a
        dialog mounted in a tile would be clipped to it."""
        code = self._code()
        close = code.index("</GridWorkspace>")
        assert "<CfgAddAccountDialog" in code[close:close + 500]
        tab = code.index("const CfgAccountsTab")
        assert "<CfgAddAccountDialog" not in code[tab:close]

    def test_page_root_anchors_the_overlay(self):
        code = self._code()
        root = code.index('data-screen-label="08 Config"')
        assert "position: 'relative'" in code[root:root + 400]

    def test_new_account_is_selected_after_creation(self):
        code = self._code()
        idx = code.index("onCreated=")
        assert "setAcct(id)" in code[idx:idx + 200]

    def test_secret_field_is_masked(self):
        code = self._code()
        idx = code.index("value={f.api_secret}")
        assert 'type="password"' in code[max(0, idx - 200):idx + 200]


# ── The Jinja modal's keyboard-submit lane ──────────────────────────────────

class TestJinjaModalFormAction:
    def test_form_posts_the_html_door_not_the_json_one(self):
        """A bare Enter submit used to hit /accounts (JSON) and paint the raw
        body into the result div, never reloading. Both submit paths must use
        the HTML door that re-renders and reloads."""
        src = Path("templates/base.html").read_text(encoding="utf-8")
        idx = src.index('id="add-account-modal"')
        seg = src[idx:idx + 3000]
        assert 'hx-post="/accounts/add-and-reload"' in seg
        assert 'hx-post="/accounts"\n' not in seg
        assert '<form hx-post="/accounts"' not in seg
