"""P3 Pre-Trade backend pins (v3.0): the JSON mirrors for the React page.

Handler-direct calls with the writers/fetchers STUBBED — never through the
shared TestClient for anything that could write (the F5 discipline; see
tests/test_p2_config.py). What's pinned here:

- `_json_safe` collapses non-finite floats to null (the F2 'both doors'
  discipline — json.dumps would emit bare NaN/Infinity tokens, invalid JSON).
- `POST /calculator/calculate?format=json` returns the calc dict as JSON,
  keeps the auto_refresh persistence gate (auto_refresh=1 → NO publish), and
  carries the post-attached keys (model_id / tp_levels /
  link_window_seconds_override).
- `GET /calculator/link-window-status/{id}?format=json` mirrors the state
  machine: PENDING mints+echoes t0, PENDING past the 5s cap → terminal ERROR,
  matcher-linked calc → LINKED, live row → LINKABLE with a real countdown.
  (The HTML rendering of the same states is pinned by test_task139/146.)
- `GET /api/calculator/orderbook/{t}` top-5 slice + uppercase.
- `GET /api/calculator/context` shape.
"""
from __future__ import annotations

import asyncio
import json as _jsonlib
import math
import time

import pytest

import api.routes_calculator as rc
from core.state import app_state


def _body(resp):
    return _jsonlib.loads(resp.body)


# ── _json_safe ─────────────────────────────────────────────────────────────

class TestJsonSafe:
    def test_non_finite_floats_collapse_to_none_nested(self):
        out = rc._json_safe({
            "a": float("nan"),
            "b": {"c": float("inf"), "d": 1.5},
            "e": [float("-inf"), 2, "x", None, True],
        })
        assert out == {"a": None, "b": {"c": None, "d": 1.5},
                       "e": [None, 2, "x", None, True]}

    def test_passthrough_types(self):
        src = {"i": 3, "s": "t", "n": None, "t": True, "f": 0.25}
        assert rc._json_safe(src) == src


# ── calculate?format=json ──────────────────────────────────────────────────

class TestCalculateJsonDoor:
    def _stub(self, monkeypatch, published):
        monkeypatch.setattr(rc.ws_manager, "set_calculator_symbol",
                            lambda *a, **k: None)

        async def _noop(*a, **k):
            return None
        monkeypatch.setattr(rc, "fetch_orderbook", _noop)
        monkeypatch.setattr(rc, "fetch_ohlcv", _noop)

        async def _pub(ch, payload):
            published.append((ch, payload))
        monkeypatch.setattr(rc.event_bus, "publish", _pub)

        monkeypatch.setattr(rc, "run_risk_calculator", lambda **k: {
            "calc_id": "abc123", "ticker": k["ticker"], "eligible": True,
            "size": 0.012, "est_r": float("nan"),   # the poison the door must strip
        })

    # Direct handler calls must supply every Form-defaulted arg explicitly —
    # FastAPI's Form(...) defaults are sentinel objects at the Python level.
    _FORM_DEFAULTS = dict(
        tp_price=110.0, tp_amount_pct=100.0, sl_amount_pct=100.0,
        model_name="", model_desc="", order_type="market",
        apply_regime_multiplier="1", link_window_seconds_override="",
        size_override="", tp_levels="", model_id="",
    )

    def test_json_door_returns_calc_with_post_attached_keys(self, monkeypatch):
        published = []
        self._stub(monkeypatch, published)
        resp = asyncio.run(rc.calculate_risk(
            request=None, ticker="btcusdt", average=100.0, sl_price=95.0,
            auto_refresh="0", format="json", **self._FORM_DEFAULTS,
        ))
        data = _body(resp)
        assert data["calc_id"] == "abc123"
        assert data["ticker"] == "BTCUSDT"
        assert data["est_r"] is None                       # NaN stripped
        for k in ("model_id", "tp_levels", "link_window_seconds_override"):
            assert k in data
        # default auto_refresh="0" → manual calc → persisted via publish
        assert len(published) == 1 and published[0][0] == "risk:risk_calculated"

    def test_auto_refresh_still_suppresses_persistence(self, monkeypatch):
        published = []
        self._stub(monkeypatch, published)
        resp = asyncio.run(rc.calculate_risk(
            request=None, ticker="BTCUSDT", average=100.0, sl_price=95.0,
            auto_refresh="1", format="json", **self._FORM_DEFAULTS,
        ))
        assert _body(resp)["calc_id"] == "abc123"
        assert published == []                             # compute-only

    def test_error_exits_stay_html_in_json_mode(self, monkeypatch):
        """Parse-failure exits are the P2 convention: HTML alert + 4xx; the
        React client strips them. The JSON door only changes the SUCCESS
        rendering."""
        published = []
        self._stub(monkeypatch, published)
        resp = asyncio.run(rc.calculate_risk(
            request=None, ticker="BTCUSDT", average=float("nan"),
            sl_price=95.0, format="json",
        ))
        assert resp.status_code == 400
        assert b"finite" in resp.body


# ── link-window-status?format=json ─────────────────────────────────────────

class TestLinkWindowJson:
    def _stub_db(self, monkeypatch, *, pretrade, window=300, confirmed=False,
                 calc_status="active"):
        from core.database import db

        async def _pt(**k):
            return pretrade

        async def _win(aid):
            return window

        async def _conf(**k):
            return confirmed

        async def _st(**k):
            return calc_status
        monkeypatch.setattr(db, "get_pretrade_timestamp_for_link_window", _pt)
        monkeypatch.setattr(db, "get_account_link_window_seconds", _win)
        monkeypatch.setattr(db, "has_confirmed_fill_for_calc", _conf)
        monkeypatch.setattr(db, "get_calc_status", _st)

    def _call(self, t0=0):
        return asyncio.run(rc.calculator_link_window_status(
            request=None, calc_id="c-1", t0=t0, format="json",
        ))

    def test_pending_first_poll_mints_t0(self, monkeypatch):
        self._stub_db(monkeypatch, pretrade=None)
        data = _body(self._call(t0=0))
        assert data["status"] == "PENDING"
        assert data["calc_id"] == "c-1"
        assert data["t0"] > 0
        assert abs(data["t0"] - time.time() * 1000) < 60_000

    def test_pending_preserves_t0_within_window(self, monkeypatch):
        self._stub_db(monkeypatch, pretrade=None)
        t0 = int(time.time() * 1000) - 1000            # 1s in — inside the 5s cap
        data = _body(self._call(t0=t0))
        assert data["status"] == "PENDING" and data["t0"] == t0

    def test_pending_past_cap_is_terminal_error(self, monkeypatch):
        self._stub_db(monkeypatch, pretrade=None)
        t0 = int(time.time() * 1000) - 6000            # past PENDING_TIMEOUT_MS
        data = _body(self._call(t0=t0))
        assert data["status"] == "ERROR"
        assert "t0" not in data                        # terminal — no chain echo

    def test_matcher_linked_calc_reports_linked(self, monkeypatch):
        self._stub_db(monkeypatch, pretrade={"timestamp": "2026-07-22T00:00:00"},
                      calc_status="matched")
        assert _body(self._call())["status"] == "LINKED"

    def test_live_row_reports_linkable_with_countdown(self, monkeypatch):
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        self._stub_db(monkeypatch, pretrade={
            "timestamp": now_iso, "link_window_seconds_override": None,
        }, window=21600)
        data = _body(self._call())
        assert data["status"] == "LINKABLE"
        assert data["effective_window_s"] == 21600
        assert 0 < data["remaining_s"] <= 21600
        assert data["expires_at_ms"] is not None


# ── orderbook + context mirrors ────────────────────────────────────────────

class TestOrderbookMirror:
    def test_top5_slice_and_uppercase(self, monkeypatch):
        async def _noop(t):
            return None
        monkeypatch.setattr(rc, "fetch_orderbook", _noop)
        snap = app_state.orderbook_cache.get("BTCUSDT")
        app_state.orderbook_cache["BTCUSDT"] = {
            "bids": [[str(100 - i), "1"] for i in range(8)],
            "asks": [[str(101 + i), "1"] for i in range(8)],
        }
        try:
            data = _body(asyncio.run(rc.api_calculator_orderbook("btcusdt")))
        finally:
            if snap is None:
                app_state.orderbook_cache.pop("BTCUSDT", None)
            else:
                app_state.orderbook_cache["BTCUSDT"] = snap
        assert data["ticker"] == "BTCUSDT"
        assert len(data["bids"]) == 5 and len(data["asks"]) == 5

    def test_fetch_failure_serves_cache_or_empty(self, monkeypatch):
        async def _boom(t):
            raise RuntimeError("net down")
        monkeypatch.setattr(rc, "fetch_orderbook", _boom)
        data = _body(asyncio.run(rc.api_calculator_orderbook("ZZZTEST")))
        assert data == {"ticker": "ZZZTEST", "bids": [], "asks": []}


class TestContextEndpoint:
    def test_shape(self, monkeypatch):
        from types import SimpleNamespace
        import core.account_config as ac

        async def _cfg(db_, aid):
            return SimpleNamespace(window_seconds=300)
        monkeypatch.setattr(ac, "read_account_config_async", _cfg)
        data = _body(asyncio.run(rc.api_calculator_context()))
        assert data["window_seconds"] == 300
        assert data["default_link_window_seconds"] == 21600
        assert data["max_link_window_seconds"] == 86400
