"""Tests for dd_gate shared logic + order_manager gate + is_new_entry classification."""
import json
import os
import sqlite3

import pytest

from core.dd_gate import dd_gate_allows_new_entry, is_new_entry
from core.migrations.runner import run_all


def _make_env(tmp_path, account_id=1, enforcement_mode="enforced"):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / ".split-complete-v1").write_text("v1")
    pa = data / "per_account"
    pa.mkdir(exist_ok=True)
    db_path = str(pa / "test__broker__1.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO accounts VALUES (?, 'Test')", (account_id,))
    conn.commit()
    conn.close()

    import core.migrations.runner as runner
    real_mdir = os.path.dirname(os.path.abspath(runner.__file__))
    run_all(str(data), real_mdir)

    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE account_settings SET dd_enforcement_mode=?, "
        "dd_warning_threshold=0.04, dd_limit_threshold=0.08 WHERE account_id=?",
        (enforcement_mode, account_id),
    )
    conn.commit()
    conn.close()
    return str(data), db_path


def _set_state(monkeypatch, data_dir, dd_state="limit"):
    monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)
    from core.state import app_state
    app_state.portfolio.dd_state = dd_state
    app_state.portfolio.drawdown = 0.09
    app_state.dd_manually_unblocked = set()
    return app_state


# ── is_new_entry classification ──────────────────────────────────────────────


class TestIsNewEntry:
    def test_market_buy_is_entry(self):
        assert is_new_entry({"side": "BUY", "order_type": "market"}) is True

    def test_limit_buy_is_entry(self):
        assert is_new_entry({"side": "BUY", "order_type": "limit"}) is True

    def test_reduce_only_is_not_entry(self):
        assert is_new_entry({"side": "SELL", "reduce_only": True}) is False

    def test_close_position_is_not_entry(self):
        assert is_new_entry({"close_position": True}) is False

    def test_stop_loss_is_not_entry(self):
        assert is_new_entry({"order_type": "stop_loss"}) is False

    def test_take_profit_is_not_entry(self):
        assert is_new_entry({"order_type": "take_profit"}) is False

    def test_trailing_stop_is_not_entry(self):
        assert is_new_entry({"order_type": "trailing_stop"}) is False

    def test_stop_market_is_not_entry(self):
        assert is_new_entry({"order_type": "stop_market"}) is False

    def test_take_profit_market_is_not_entry(self):
        assert is_new_entry({"order_type": "take_profit_market"}) is False

    def test_empty_order_is_entry(self):
        assert is_new_entry({}) is True


# ── dd_gate_allows_new_entry ─────────────────────────────────────────────────


class TestDDGateAllowsNewEntry:
    def test_ok_state_allowed(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path, enforcement_mode="enforced")
        _set_state(monkeypatch, data_dir, dd_state="ok")
        allowed, reason = dd_gate_allows_new_entry(1)
        assert allowed is True
        assert reason is None

    def test_warning_state_allowed(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path, enforcement_mode="enforced")
        _set_state(monkeypatch, data_dir, dd_state="warning")
        allowed, reason = dd_gate_allows_new_entry(1)
        assert allowed is True

    def test_limit_enforced_blocked(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path, enforcement_mode="enforced")
        _set_state(monkeypatch, data_dir, dd_state="limit")
        allowed, reason = dd_gate_allows_new_entry(1)
        assert allowed is False
        assert "dd_state=limit" in reason

    def test_limit_advisory_allowed(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path, enforcement_mode="advisory")
        _set_state(monkeypatch, data_dir, dd_state="limit")
        allowed, reason = dd_gate_allows_new_entry(1)
        assert allowed is True
        assert reason is None

    def test_limit_enforced_overridden_allowed(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path, enforcement_mode="enforced")
        app_state = _set_state(monkeypatch, data_dir, dd_state="limit")
        app_state.dd_manually_unblocked.add(1)
        allowed, reason = dd_gate_allows_new_entry(1)
        assert allowed is True


# ── OrderManager.check_dd_gate_for_order ─────────────────────────────────────


class TestOrderManagerGate:
    def test_new_entry_blocked_when_enforced(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path, enforcement_mode="enforced")
        _set_state(monkeypatch, data_dir, dd_state="limit")

        from core.order_manager import OrderManager
        om = OrderManager(db=None)

        order = {"side": "BUY", "order_type": "market", "symbol": "BTCUSDT"}
        allowed, reason = om.check_dd_gate_for_order(1, order)
        assert allowed is False
        assert "dd_state=limit" in reason

        # Event logged
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT payload_json FROM engine_events WHERE event_type='calculator_blocked'"
        ).fetchall()
        conn.close()
        assert len(rows) >= 1
        payload = json.loads(rows[0][0])
        assert payload["gate"] == "order_manager_dd"

    def test_reduce_only_allowed_when_enforced(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path, enforcement_mode="enforced")
        _set_state(monkeypatch, data_dir, dd_state="limit")

        from core.order_manager import OrderManager
        om = OrderManager(db=None)

        order = {"side": "SELL", "reduce_only": True, "symbol": "BTCUSDT"}
        allowed, reason = om.check_dd_gate_for_order(1, order)
        assert allowed is True

    def test_tp_sl_allowed_when_enforced(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path, enforcement_mode="enforced")
        _set_state(monkeypatch, data_dir, dd_state="limit")

        from core.order_manager import OrderManager
        om = OrderManager(db=None)

        for order_type in ["stop_loss", "take_profit", "trailing_stop"]:
            order = {"order_type": order_type, "symbol": "BTCUSDT"}
            allowed, reason = om.check_dd_gate_for_order(1, order)
            assert allowed is True, f"{order_type} should be allowed"
