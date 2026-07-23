"""v3.0 P6 (Regime) backend pins.

Handler-direct + F5-safe (no TestClient; db readers monkeypatched on the
singleton; app_state.current_regime snapshotted/restored). P6's verify-first
verdict: the regime surface is ALREADY all-JSON — zero ?format=json doors —
so the only backend change is the additive GET /api/regime/multipliers.
These pins cover that endpoint plus the response shapes the React Regime
page binds (current-source discrimination, bare-array timeline/coverage/
signals, thresholds flatness — the Jinja loadThresholds iterates the
response as a flat dict, so /thresholds must NEVER grow a nested key).
"""
from __future__ import annotations

import asyncio
import json as _jsonlib
from types import SimpleNamespace

import pytest

import config
import api.routes_regime as rr
from core.database import db
from core.state import app_state


def _body(resp):
    return _jsonlib.loads(resp.body)


def _run(coro):
    return asyncio.run(coro)


class _RegimeSnap:
    """Swap app_state.current_regime temporarily."""

    def __init__(self, value):
        self._value = value

    def __enter__(self):
        self._old = app_state.current_regime
        app_state.current_regime = self._value
        return self

    def __exit__(self, *exc):
        app_state.current_regime = self._old
        return False


class TestMultipliersEndpoint:
    def test_serves_config_map(self):
        out = _body(_run(rr.api_regime_multipliers()))
        assert out == config.REGIME_MULTIPLIERS
        assert set(out) == {
            "risk_on_trending", "risk_on_choppy", "neutral",
            "risk_off_defensive", "risk_off_panic",
        }
        assert all(isinstance(v, (int, float)) for v in out.values())

    def test_thresholds_stays_flat(self):
        # The Jinja page renders /thresholds as a flat key→number dict; the
        # multiplier map must live on its OWN endpoint, never nested here.
        out = _body(_run(rr.api_regime_thresholds()))
        assert out == config.REGIME_THRESHOLDS
        assert "multipliers" not in out
        assert all(isinstance(v, (int, float)) for v in out.values())


class TestCurrentSourceDiscrimination:
    def test_live_source(self):
        live = SimpleNamespace(
            label="risk_on_trending", multiplier=1.2, confidence="high",
            stability_bars=12, mode="full", computed_at=None,
            signals={"vix_close": 14.2},
        )
        with _RegimeSnap(live):
            out = _body(_run(rr.api_regime_current()))
        assert out["source"] == "live"
        assert out["label"] == "risk_on_trending"
        assert out["stability_bars"] == 12
        assert out["computed_at"] is None

    def test_db_fallback_gets_config_multiplier(self, monkeypatch):
        async def fake_latest():
            return {"date": "2026-07-20", "label": "risk_off_panic",
                    "mode": "macro_only", "signals": {}}

        monkeypatch.setattr(db, "get_latest_regime_label", fake_latest)
        with _RegimeSnap(None):
            out = _body(_run(rr.api_regime_current()))
        assert out["source"] == "db"
        assert out["multiplier"] == config.REGIME_MULTIPLIERS["risk_off_panic"]

    def test_none_source(self, monkeypatch):
        async def fake_latest():
            return None

        monkeypatch.setattr(db, "get_latest_regime_label", fake_latest)
        with _RegimeSnap(None):
            out = _body(_run(rr.api_regime_current()))
        assert out == {"label": None, "multiplier": 1.0, "source": "none"}


class TestBareArrayShapes:
    """The React page binds these as BARE arrays (no envelope) — pin that."""

    def test_timeline(self, monkeypatch):
        rows = [{"date": "2026-07-01", "label": "neutral", "mode": "full",
                 "signals": {"vix_close": 15.0}}]

        async def fake(from_date="", to_date=""):
            return rows

        monkeypatch.setattr(db, "get_regime_labels", fake)
        out = _body(_run(rr.api_regime_timeline(from_date="", to_date="")))
        assert out == rows

    def test_coverage(self, monkeypatch):
        rows = [{"signal_name": "vix_close", "source": "yfinance",
                 "min_date": "2020-01-01", "max_date": "2026-07-20",
                 "count": 1650}]

        async def fake():
            return rows

        monkeypatch.setattr(db, "get_all_signal_coverage", fake)
        out = _body(_run(rr.api_regime_coverage()))
        assert out == rows

    def test_signals_requires_name(self):
        resp = _run(rr.api_regime_signals(signal_name="", from_date="", to_date=""))
        assert resp.status_code == 400
        assert _body(resp) == {"error": "signal_name required"}

    def test_signals_rows(self, monkeypatch):
        # db.get_regime_signals returns a DICT keyed by signal name; the
        # route unwraps it to the bare [{date,value}] array the cards bind.
        rows = [{"date": "2026-07-01", "value": 14.5}]

        async def fake(names, from_date="", to_date=""):
            assert names == ["vix_close"]
            return {"vix_close": rows}

        monkeypatch.setattr(db, "get_regime_signals", fake)
        out = _body(_run(rr.api_regime_signals(
            signal_name="vix_close", from_date="", to_date="")))
        assert out == rows
