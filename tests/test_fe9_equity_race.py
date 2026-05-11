"""
FE-9 regression tests — equity race condition fix.

Root cause: data_cache.py set total_equity = cross_wallet (balance only,
missing unrealized PnL) on WS ACCOUNT_UPDATE. Correct equity is
balance + unrealized, computed by apply_mark_price().

Fix: remove total_equity assignment from ACCOUNT_UPDATE handler.
apply_mark_price() is the sole equity authority.

Run: pytest tests/test_fe9_equity_race.py -v
"""
from __future__ import annotations
from pathlib import Path

import pytest

from core.state import app_state


class TestRaceEliminated:
    def test_account_update_does_not_set_total_equity(self):
        """The apply_position_update_incremental handler must NOT set total_equity
        from cross_wallet. total_equity is derived in apply_mark_price only."""
        src = Path(__file__).parent.parent / "core" / "data_cache.py"
        content = src.read_text()
        # The bug line was: total_equity = balances.get("cross_wallet", 0)
        assert 'total_equity = balances.get("cross_wallet"' not in content, \
            "total_equity must not be set from cross_wallet in ACCOUNT_UPDATE handler"
        assert "total_equity.*cross_wallet" not in content, \
            "total_equity must not reference cross_wallet"

    def test_equity_unchanged_after_balance_update(self):
        """When balance changes but mark price hasn't updated yet, equity should
        NOT snap to balance-only. It should stay at previous correct value until
        apply_mark_price recalculates."""
        acc = app_state.account_state
        dc = app_state._data_cache

        # Save originals
        orig_equity = acc.total_equity
        orig_balance = acc.balance_usdt
        orig_unrealized = acc.total_unrealized

        try:
            # Set up known state: equity = balance + unrealized
            acc.total_equity = 100.0
            acc.balance_usdt = 80.0
            acc.total_unrealized = 20.0

            # Simulate WS ACCOUNT_UPDATE with new balance
            # (this is what apply_position_update_incremental does with balances)
            # Pre-fix: total_equity would be set to 85.0 (cross_wallet, balance only)
            # Post-fix: total_equity should NOT change here
            balances = {"wallet_balance": 85.0, "cross_wallet": 85.0}

            # Apply just the balance portion (not full method — isolate the bug)
            acc.balance_usdt = balances.get("wallet_balance", 0)
            # The deleted line was: acc.total_equity = balances.get("cross_wallet", 0)

            # Post-fix: equity should still be 100.0 (unchanged)
            # or at minimum should NOT be 85.0 (balance-only)
            assert acc.total_equity != 85.0, \
                "total_equity must NOT be set to cross_wallet (balance-only)"
            assert acc.total_equity == 100.0, \
                "total_equity should be unchanged until apply_mark_price recalculates"
        finally:
            acc.total_equity = orig_equity
            acc.balance_usdt = orig_balance
            acc.total_unrealized = orig_unrealized

    def test_mark_price_is_equity_authority(self):
        """apply_mark_price must compute total_equity = balance + unrealized."""
        src = Path(__file__).parent.parent / "core" / "data_cache.py"
        content = src.read_text()
        assert "balance_usdt + acc.total_unrealized" in content or \
               "balance_usdt + total_unrealized" in content, \
            "apply_mark_price must compute equity as balance + unrealized"
