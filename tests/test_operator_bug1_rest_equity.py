"""
v3.0 operator-bug #1 — REST equity oscillation (Binance wallet-vs-margin balance).

SYMPTOM (operator, live-driving /v3): the Dashboard equity curve "keeps jumping
back and forth to 278$", tripping the drawdown warning, even though equity never
actually dropped below 300 that day. Reported as carried from a previous version.

MECHANISM (investigated independently of the report, per CLAUDE.md
§ "Re-investigation discipline"). Not a chart bug — the engine PERSISTED the
dip. Live `account_snapshots` rows alternated:

    20:45:49  total_equity = 278.41   <- dip
    20:45:14  total_equity = 307.54
    20:44:39  total_equity = 307.44
    20:42:19  total_equity = 278.41   <- dip

and the dip value was exact to 8 decimals:

    307.42758028 - 29.01955329 = 278.40802699   (equity - unrealized)

`core/adapters/binance/rest_adapter.py` mapped Binance's `totalWalletBalance`
(settled cash, EXCLUDING open-position PnL) onto `NormalizedAccount.
total_equity`. Every REST account poll therefore overwrote equity with a figure
short by exactly the open unrealized PnL; the next mark tick recomputed
`balance + unrealized` and restored it. `/fapi/v2/account` ships the correct
figure as `totalMarginBalance`.

This is the SAME bug class as FE-9 (`test_fe9_equity_race.py`) — a balance-only
source writing `total_equity` — on the REST path instead of the WS path. The
FE-9 invariant is documented in `data_cache.apply_position_update_incremental`:
apply_mark_price is the sole continuous equity authority.

KNOCK-ON: `_recalculate_portfolio` ratchets `min_total_equity` monotonically
down, so the phantom low latched and never left (the live snapshot reported
min_equity 278.408 against total_equity 307.43). That is what surfaced as the
operator's "warning".

FIX SHAPE — split the two conflated concepts instead of swapping one field.
`total_equity` and `wallet_balance` are now distinct on NormalizedAccount,
because `data_cache` ALSO fed `balance_usdt` from `na.total_equity`: swapping
the adapter alone would have made apply_mark_price double-count unrealized.

Run: pytest tests/test_operator_bug1_rest_equity.py -v
"""
from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.adapters.protocols import NormalizedAccount


# The exact live figures the bug was diagnosed from (2026-07-23 20:45 UTC).
LIVE_WALLET     = 278.40802699
LIVE_UNREALIZED = 29.01955329
LIVE_EQUITY     = 307.42758028


def _binance_adapter(account_payload):
    """Build a BinanceUSDMAdapter without ccxt/network, stubbed to return
    `account_payload` from /fapi/v2/account (pattern: test_task99_adapter_bundle)."""
    from core.adapters.binance.rest_adapter import BinanceUSDMAdapter

    ad = BinanceUSDMAdapter.__new__(BinanceUSDMAdapter)
    ad._api_key = ""
    ad._api_secret = ""
    ad._proxy = ""
    ad._ex = MagicMock()
    ad._ex.fapiPrivateV2GetAccount.return_value = account_payload
    ad._ex.fapiPrivateGetCommissionRate.return_value = {}
    ad._markets_loaded = False
    ad._current_priority = "normal"

    async def _run(fn):          # bypass the rate-limit machinery
        return fn()
    ad._run = _run
    return ad


def _live_payload(**over):
    payload = {
        "totalWalletBalance":     str(LIVE_WALLET),
        "totalMarginBalance":     str(LIVE_EQUITY),
        "totalUnrealizedProfit":  str(LIVE_UNREALIZED),
        "availableBalance":       "297.52300378",
        "totalInitialMargin":     "9.9045765",
        "totalMaintMargin":       "0.1",
        "feeTier":                "0",
    }
    payload.update(over)
    return payload


# ── the adapter mapping ─────────────────────────────────────────────────────

class TestBinanceAccountMapping:
    def test_equity_is_margin_balance_not_wallet_balance(self):
        """Load-bearing pin. Pre-fix total_equity was totalWalletBalance
        (278.41) — the phantom dip the operator watched the curve snap to."""
        na = asyncio.run(_binance_adapter(_live_payload()).fetch_account())

        assert na.total_equity == pytest.approx(LIVE_EQUITY), (
            "operator-bug #1 regression: total_equity must be Binance's "
            "totalMarginBalance (wallet + unrealized). Pre-fix it was "
            f"totalWalletBalance = {LIVE_WALLET} — the persisted dip value."
        )
        assert na.total_equity != pytest.approx(LIVE_WALLET)

    def test_wallet_balance_carries_the_settled_cash_figure(self):
        na = asyncio.run(_binance_adapter(_live_payload()).fetch_account())
        assert na.wallet_balance == pytest.approx(LIVE_WALLET)
        assert na.unrealized_pnl == pytest.approx(LIVE_UNREALIZED)

    def test_the_identity_holds(self):
        """equity == wallet + unrealized. This identity failing IS the bug."""
        na = asyncio.run(_binance_adapter(_live_payload()).fetch_account())
        assert na.wallet_balance + na.unrealized_pnl == pytest.approx(
            na.total_equity
        ), "wallet + unrealized must reconstruct equity"

    def test_missing_margin_balance_derives_rather_than_regressing(self):
        """Fail-safe: if totalMarginBalance is ever absent we reconstruct the
        identity. Regressing to the wallet-only value would silently
        reintroduce the oscillation."""
        payload = _live_payload()
        del payload["totalMarginBalance"]
        na = asyncio.run(_binance_adapter(payload).fetch_account())

        assert na.total_equity == pytest.approx(LIVE_WALLET + LIVE_UNREALIZED)
        assert na.total_equity != pytest.approx(LIVE_WALLET)

    def test_source_no_longer_maps_wallet_balance_onto_equity(self):
        """Source pin (FE-9 style): the literal defect line must not return."""
        from core.adapters.binance import rest_adapter

        src = inspect.getsource(rest_adapter.BinanceUSDMAdapter.fetch_account)
        assert 'total_equity=float(info.get("totalWalletBalance"' not in src, (
            "operator-bug #1 regression: totalWalletBalance must never be "
            "assigned to total_equity — it excludes unrealized PnL."
        )


# ── the consumer: balance_usdt must be the WALLET figure ────────────────────

class TestDataCacheBalanceSemantics:
    def test_rest_apply_takes_balance_from_wallet_not_equity(self):
        from core.data_cache import DataCache
        from core.state import app_state

        cache = DataCache(MagicMock())
        na = NormalizedAccount(
            total_equity=LIVE_EQUITY, wallet_balance=LIVE_WALLET,
            unrealized_pnl=LIVE_UNREALIZED, available_margin=297.52,
            initial_margin=9.9, maint_margin=0.1,
        )
        assert asyncio.run(cache.apply_account_update_rest(na)) is True

        acc = app_state.account_state
        assert acc.balance_usdt == pytest.approx(LIVE_WALLET)
        assert acc.total_equity == pytest.approx(LIVE_EQUITY)

    def test_absent_wallet_figure_is_derived_from_the_identity(self):
        """Adapters that report no separate wallet figure (sentinel 0.0) must
        still yield a wallet-shaped balance_usdt, not the equity figure —
        otherwise apply_mark_price double-counts unrealized."""
        from core.data_cache import DataCache
        from core.state import app_state

        cache = DataCache(MagicMock())
        na = NormalizedAccount(
            total_equity=LIVE_EQUITY, wallet_balance=0.0,
            unrealized_pnl=LIVE_UNREALIZED, available_margin=297.52,
        )
        assert asyncio.run(cache.apply_account_update_rest(na)) is True

        acc = app_state.account_state
        assert acc.balance_usdt == pytest.approx(LIVE_EQUITY - LIVE_UNREALIZED)


# ── the oscillation itself ──────────────────────────────────────────────────

class TestNoOscillationAcrossRestThenMark:
    """The mechanism pin: a REST poll followed by a mark tick must agree.

    Pre-fix this sequence produced 278.41 -> 307.43 -> 278.41 -> ... which is
    precisely the alternation captured in the live account_snapshots rows.
    """

    def _apply_sequence(self, na):
        from core.data_cache import DataCache
        from core.state import app_state

        cache = DataCache(MagicMock())
        asyncio.run(cache.apply_account_update_rest(na))
        equity_after_rest = app_state.account_state.total_equity

        # apply_mark_price with no open positions recomputes
        # total_equity = balance_usdt + total_unrealized (unrealized -> 0).
        cache._positions = []
        cache.apply_mark_price("BTCUSDT", 100.0)
        equity_after_mark = app_state.account_state.total_equity
        return equity_after_rest, equity_after_mark

    def test_rest_then_mark_do_not_disagree(self):
        na = NormalizedAccount(
            total_equity=LIVE_WALLET,      # flat account: no open positions
            wallet_balance=LIVE_WALLET,
            unrealized_pnl=0.0,
            available_margin=LIVE_WALLET,
        )
        after_rest, after_mark = self._apply_sequence(na)

        assert after_rest == pytest.approx(after_mark), (
            "operator-bug #1 regression: the REST poll and the following mark "
            f"tick disagree ({after_rest} vs {after_mark}) — that disagreement "
            "IS the oscillation the operator saw on the equity curve."
        )

    def test_phantom_low_does_not_latch_into_min_total_equity(self):
        """The knock-on. _recalculate_portfolio ratchets min_total_equity down
        and never back up, so a single phantom dip poisons the drawdown range
        for the rest of the session."""
        from core.state import app_state

        acc = app_state.account_state
        acc.min_total_equity = 0.0          # let the first apply seed it
        self._apply_sequence(NormalizedAccount(
            total_equity=LIVE_WALLET, wallet_balance=LIVE_WALLET,
            unrealized_pnl=0.0, available_margin=LIVE_WALLET,
        ))

        assert acc.min_total_equity >= LIVE_WALLET - 1e-6, (
            "a value below the true equity latched into min_total_equity — "
            "that is the source of the operator's spurious warning."
        )


# ── cross-adapter consistency ───────────────────────────────────────────────

class TestEveryAdapterReportsBothFigures:
    def test_normalized_account_exposes_wallet_balance(self):
        assert hasattr(NormalizedAccount(), "wallet_balance")
        assert NormalizedAccount().wallet_balance == 0.0

    @pytest.mark.parametrize("mod_path,cls_name", [
        ("core.adapters.binance.rest_adapter", "BinanceUSDMAdapter"),
        ("core.adapters.bybit.rest_adapter",   "BybitLinearAdapter"),
        ("core.adapters.mexc.rest_adapter",    "MexcLinearAdapter"),
    ])
    def test_adapter_sets_wallet_balance(self, mod_path, cls_name):
        """Every adapter must populate wallet_balance explicitly. Leaving it at
        the 0.0 sentinel pushes the consumer onto the derivation fallback,
        which is correct but silently assumes the adapter's unrealized split
        is trustworthy."""
        import importlib

        mod = importlib.import_module(mod_path)
        cls = getattr(mod, cls_name, None)
        if cls is None:                       # adapter class renamed
            pytest.skip(f"{cls_name} not present in {mod_path}")
        src = inspect.getsource(cls.fetch_account)
        assert "wallet_balance=" in src, (
            f"{cls_name}.fetch_account must set wallet_balance explicitly "
            "(operator-bug #1: equity and settled cash are different numbers)."
        )


class TestFe9InvariantStillDocumented:
    def test_mark_price_remains_the_sole_equity_authority(self):
        """The FE-9 comment is the guardrail that made this bug diagnosable —
        it names the invariant the REST path was violating. Keep it."""
        src = (Path(__file__).parent.parent / "core" / "data_cache.py").read_text(
            encoding="utf-8"
        )
        assert "sole equity authority" in src.lower()
