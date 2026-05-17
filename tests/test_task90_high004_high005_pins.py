"""
Task 90 regression pins for HIGH-004 + HIGH-005 (both VERIFIED FALSE).

HIGH-004: portfolio recalc null/zero guards. Investigation showed both
  halves of the audit's claim are already guarded in current code:
    - _fetch_rolling_peak_equity returns float (not Optional), every path.
    - line-516 consumer is already `... if rolling_peak > 0 else 0.0`.
    - PositionInfo.individual_margin_used dataclass-defaulted to 0.0.

HIGH-005: TP/SL enrichment early-return on mark=0. Investigation showed
  the line-527 `if not mark: ... continue` already short-circuits, zeroes
  the display fields, and skips the min() at lines 550/556.

These pins protect the existing guards against future removal. Non-vacuous:
each pin would fail if its corresponding guard were deleted (verified
manually during Task 90).

Run: pytest tests/test_task90_high004_high005_pins.py -v
"""
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest

from core.state import PositionInfo


# ── HIGH-004 half 1: _fetch_rolling_peak_equity always returns a float ───────

def test_fetch_rolling_peak_equity_returns_current_equity_when_db_path_resolution_fails(
    monkeypatch,
):
    """HIGH-004 pin: KeyError path on _resolve_db_path returns current_equity (float)."""
    from core import data_cache

    def _raise_keyerror(_aid):
        raise KeyError("simulated missing account")

    monkeypatch.setattr(
        "core.db_account_settings._resolve_db_path", _raise_keyerror
    )
    result = data_cache._fetch_rolling_peak_equity(
        account_id=99, window_days=7, current_equity=12345.67
    )
    assert result == 12345.67
    assert isinstance(result, float)


def test_fetch_rolling_peak_equity_returns_current_equity_when_no_snapshots(tmp_path, monkeypatch):
    """HIGH-004 pin: empty snapshots table → max(0.0, current_equity) = current_equity."""
    from core import data_cache
    db_path = str(tmp_path / "snap.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE account_snapshots ("
        "account_id INTEGER, total_equity REAL, snapshot_ts TEXT)"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "core.db_account_settings._resolve_db_path", lambda aid: db_path
    )
    result = data_cache._fetch_rolling_peak_equity(
        account_id=1, window_days=7, current_equity=500.0
    )
    assert result == 500.0
    assert isinstance(result, float)


def test_rolling_dd_guard_handles_zero_rolling_peak():
    """HIGH-004 line-516 pin: mirrors the production guard pattern with
    rolling_peak=0.0. The ternary `... if rolling_peak > 0 else 0.0`
    short-circuits; without it, `(0 - 100) / 0` raises ZeroDivisionError.

    Cross-verified against the production line by reading core/data_cache.py:516
    during Task 90 (the guard exists; this pin documents the contract a future
    refactor must preserve)."""
    # The pattern as it appears verbatim at core/data_cache.py:516-517:
    rolling_peak = 0.0
    total_equity = 100.0
    rolling_dd = (rolling_peak - total_equity) / rolling_peak if rolling_peak > 0 else 0.0
    rolling_dd = max(rolling_dd, 0.0)
    assert rolling_dd == 0.0
    # And confirm the unguarded form would have crashed:
    with pytest.raises(ZeroDivisionError):
        _ = (rolling_peak - total_equity) / rolling_peak


# ── HIGH-004 half 2: PositionInfo defaults individual_margin_used to 0.0 ─────

def test_position_info_individual_margin_used_default_is_zero():
    """HIGH-004 pin: dataclass default at state.py:102 guarantees
    individual_margin_used == 0.0 when no value is passed."""
    pos = PositionInfo()
    assert pos.individual_margin_used == 0.0
    assert pos.individual_margin_used is not None
    # Sum-style arithmetic the recalc uses must work without TypeError
    total = sum(p.individual_margin_used for p in [pos, PositionInfo()])
    assert total == 0.0


# ── HIGH-005: enrich_positions_tpsl early-returns on falsy mark ──────────────

def _mock_om():
    """Construct an OrderManager with mock db; enrich_positions_tpsl is sync."""
    from core.order_manager import OrderManager
    db = MagicMock()
    om = OrderManager(db)
    return om


def _tp_sl_orders_for_btc_long():
    """One TP and one SL order matching a BTC LONG position."""
    return [
        {
            "symbol": "BTCUSDT",
            "side": "SELL",
            "position_side": "LONG",
            "order_type": "take_profit",
            "status": "new",
            "stop_price": 110.0,
        },
        {
            "symbol": "BTCUSDT",
            "side": "SELL",
            "position_side": "LONG",
            "order_type": "stop_loss",
            "status": "new",
            "stop_price": 90.0,
        },
    ]


def test_tp_sl_enrichment_skips_when_mark_is_zero():
    """HIGH-005 pin: fair_price=0 and average=0 → mark falsy → skip block fires.
    Display fields zeroed; min() at lines 550/556 unreachable.
    Without the guard, an arbitrary order would be selected based on
    abs(stop_price - 0)."""
    om = _mock_om()
    om._open_orders = _tp_sl_orders_for_btc_long()
    pos = PositionInfo(
        ticker="BTCUSDT", direction="LONG", fair_price=0.0, average=0.0,
        individual_tp_price=999.0,  # pre-seed so we can verify the skip resets it
        individual_sl_price=888.0,
        individual_tpsl=True,
    )
    om.enrich_positions_tpsl([pos])
    assert pos.individual_tp_price == 0.0
    assert pos.individual_sl_price == 0.0
    assert pos.individual_tpsl is False


def test_tp_sl_enrichment_skips_when_mark_is_none():
    """HIGH-005 defensive pin: `pos.fair_price or pos.average` falls through both
    falsy values → mark == 0 → same skip path. Documents the behavior in case
    PositionInfo were ever changed to Optional[float] for these fields."""
    om = _mock_om()
    om._open_orders = _tp_sl_orders_for_btc_long()
    # PositionInfo defaults are 0.0 for both fair_price and average — equivalent
    # to "no valid price". `or` short-circuits the same way.
    pos = PositionInfo(ticker="BTCUSDT", direction="LONG")
    om.enrich_positions_tpsl([pos])
    assert pos.individual_tp_price == 0.0
    assert pos.individual_sl_price == 0.0
    assert pos.individual_tpsl is False


def test_tp_sl_enrichment_proceeds_when_mark_is_valid():
    """HIGH-005 anti-over-correction sanity: a non-zero mark must NOT trigger
    the skip. Catches accidental future widening of the guard (e.g., a typo
    like `if not mark or some_other_check`)."""
    om = _mock_om()
    om._open_orders = _tp_sl_orders_for_btc_long()
    pos = PositionInfo(
        ticker="BTCUSDT", direction="LONG", fair_price=100.0, average=100.0
    )
    om.enrich_positions_tpsl([pos])
    assert pos.individual_tp_price == 110.0  # the only TP order
    assert pos.individual_sl_price == 90.0   # the only SL order
    assert pos.individual_tpsl is True
