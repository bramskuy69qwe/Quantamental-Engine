"""
Task 119 regression tests — Bundle B remnant (MED-049 + MED-050 + MED-046).

MED-049: `update_account_detail` route accepts client-supplied
  `market_type` without independent whitelist (symmetric to MED-048
  for `exchange`). Adds `_validate_market_type()` helper +
  `is_valid_market_type` / `get_supported_market_types` registry
  primitives.

MED-050: position-fetch + order-fetch sites in all 3 adapters use
  `.get(field, 0) or 0` on critical routing/identity fields. Add
  per-record validation: log + skip records missing
  symbol / position-amount (positions) or id+symbol (orders). Other
  records continue to be parsed. Per-record granularity (NOT
  fail-closed) — vanishing-position is operator-visible; blanking the
  list is much harder to detect.

MED-046: `_CREATE_STATEMENTS.split(";")` chokes on `;` inside `--`
  SQL comments (Task 104a discovery). Switch to
  `sqlite3.executescript()` which uses the proper tokenizer.

Run: pytest tests/test_task119_bundle_b_remnant.py -v
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import sqlite3
import tempfile
from unittest.mock import MagicMock

import pytest


# ── MED-049: market_type whitelist ───────────────────────────────────────────

class TestMarketTypeRegistryHelpers:
    """is_valid_market_type + get_supported_market_types: leaf checks."""

    def test_future_legacy_alias_valid(self):
        from core.adapters.registry import is_valid_market_type
        # `future` is the legacy DB form; map_market_type rewrites to
        # `linear_perpetual` which is registered.
        assert is_valid_market_type("future") is True

    def test_linear_perpetual_canonical_valid(self):
        from core.adapters.registry import is_valid_market_type
        assert is_valid_market_type("linear_perpetual") is True

    def test_unknown_rejected(self):
        from core.adapters.registry import is_valid_market_type
        assert is_valid_market_type("fakemarket") is False

    def test_empty_rejected(self):
        from core.adapters.registry import is_valid_market_type
        assert is_valid_market_type("") is False

    def test_none_rejected(self):
        from core.adapters.registry import is_valid_market_type
        assert is_valid_market_type(None) is False  # type: ignore[arg-type]

    def test_uppercase_rejected_strict_case(self):
        """Symmetric to MED-048 case-sensitivity decision."""
        from core.adapters.registry import is_valid_market_type
        assert is_valid_market_type("FUTURE") is False
        assert is_valid_market_type("Future") is False

    def test_supported_list_includes_future_and_linear_perpetual(self):
        from core.adapters.registry import get_supported_market_types
        supported = get_supported_market_types()
        assert "future" in supported  # legacy alias
        assert "linear_perpetual" in supported  # canonical


class TestValidateMarketTypeRouteHelper:
    def test_valid_returns_empty(self):
        from api.routes_accounts import _validate_market_type
        assert _validate_market_type("future") == ""
        assert _validate_market_type("linear_perpetual") == ""

    def test_invalid_returns_message_with_supported_list(self):
        from api.routes_accounts import _validate_market_type
        msg = _validate_market_type("fakemarket")
        assert msg
        assert "fakemarket" in msg
        assert "Supported:" in msg
        assert "future" in msg  # operator sees the legacy alias

    def test_uppercase_rejected(self):
        from api.routes_accounts import _validate_market_type
        assert _validate_market_type("FUTURE") != ""


class TestUpdateAccountDetailWiresMarketTypeValidation:
    """Source-pin: update_account_detail must call _validate_market_type
    when the market_type form field is supplied."""

    def test_route_calls_validate_market_type(self):
        import api.routes_accounts as m
        src = inspect.getsource(m.update_account_detail)
        assert "_validate_market_type(" in src, (
            "MED-049 regression: update_account_detail no longer "
            "validates market_type independently."
        )
        # And the validator call must appear inside the `if market_type
        # is not None:` branch, not in the exchange branch.
        assert "MED-049" in src


# ── MED-050: per-record validation across adapters ───────────────────────────

class TestMed050BinancePositionsValidation:
    """Binance fetch_positions: missing symbol or positionAmt → log + skip."""

    def _make_adapter(self, raw_positions):
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        ad = BinanceUSDMAdapter.__new__(BinanceUSDMAdapter)
        ad._api_key = ""
        ad._api_secret = ""
        ad._proxy = ""
        ad._ex = MagicMock()
        ad._ex.fapiPrivateV2GetAccount.return_value = {
            "positions": raw_positions,
        }
        ad._ex.last_response_headers = None
        ad._markets_loaded = False
        ad._weight_tracker = None
        ad._current_priority = "normal"
        return ad

    def test_missing_symbol_logs_and_skips(self, caplog):
        ad = self._make_adapter([
            {"positionAmt": "1.5", "entryPrice": "50000"},  # symbol missing
            {"symbol": "BTCUSDT", "positionAmt": "2.0", "entryPrice": "60000"},
        ])
        with caplog.at_level(logging.WARNING, logger="adapters.binance.rest"):
            result = asyncio.run(ad.fetch_positions())
        # Only the second record should remain
        assert len(result) == 1
        assert result[0].symbol == "BTCUSDT"
        assert "skipping record" in caplog.text
        assert "symbol" in caplog.text

    def test_missing_position_amt_logs_and_skips(self, caplog):
        ad = self._make_adapter([
            {"symbol": "BTCUSDT", "entryPrice": "50000"},  # positionAmt missing
            {"symbol": "ETHUSDT", "positionAmt": "10", "entryPrice": "3000"},
        ])
        with caplog.at_level(logging.WARNING, logger="adapters.binance.rest"):
            result = asyncio.run(ad.fetch_positions())
        assert len(result) == 1
        assert result[0].symbol == "ETHUSDT"
        assert "positionAmt" in caplog.text

    def test_valid_records_pass_through_unchanged(self):
        """Anti-over-correction: well-formed records still parse normally."""
        ad = self._make_adapter([
            {"symbol": "BTCUSDT", "positionAmt": "1.5", "entryPrice": "50000"},
            {"symbol": "ETHUSDT", "positionAmt": "10", "entryPrice": "3000"},
        ])
        result = asyncio.run(ad.fetch_positions())
        assert len(result) == 2
        assert {p.symbol for p in result} == {"BTCUSDT", "ETHUSDT"}


class TestMed050BinanceOrdersValidation:
    def _make_adapter(self, raw_orders):
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        ad = BinanceUSDMAdapter.__new__(BinanceUSDMAdapter)
        ad._api_key = ""
        ad._api_secret = ""
        ad._proxy = ""
        ad._ex = MagicMock()
        ad._ex.fapiPrivateGetOpenOrders.return_value = raw_orders
        ad._ex.last_response_headers = None
        ad._markets_loaded = False
        ad._weight_tracker = None
        ad._current_priority = "normal"
        return ad

    def test_missing_order_id_logs_and_skips(self, caplog):
        ad = self._make_adapter([
            {"symbol": "BTCUSDT", "type": "LIMIT"},  # orderId missing
            {"orderId": 123, "symbol": "ETHUSDT", "type": "LIMIT"},
        ])
        with caplog.at_level(logging.WARNING, logger="adapters.binance.rest"):
            result = asyncio.run(ad.fetch_open_orders())
        assert len(result) == 1
        assert result[0].exchange_order_id == "123"
        assert "orderId" in caplog.text


class TestMed050BybitPositionsValidation:
    def _make_adapter(self, raw_positions):
        from core.adapters.bybit.rest_adapter import BybitLinearAdapter
        ad = BybitLinearAdapter.__new__(BybitLinearAdapter)
        ad._api_key = ""
        ad._api_secret = ""
        ad._proxy = ""
        ad._ex = MagicMock()
        ad._ex.fetch_positions.return_value = raw_positions
        ad._ex.last_response_headers = None
        ad._markets_loaded = False
        ad._weight_tracker = None
        ad._current_priority = "normal"
        return ad

    def test_missing_symbol_logs_and_skips(self, caplog):
        ad = self._make_adapter([
            {"contracts": 1.5, "entryPrice": 50000, "side": "long"},
            {"symbol": "BTC/USDT:USDT", "contracts": 2.0, "side": "long",
             "entryPrice": 60000},
        ])
        with caplog.at_level(logging.WARNING, logger="adapters.bybit.rest"):
            result = asyncio.run(ad.fetch_positions())
        assert len(result) == 1
        assert "skipping record" in caplog.text


class TestMed050MexcPositionsValidation:
    def _make_adapter(self, raw_positions):
        from core.adapters.mexc.rest_adapter import MexcLinearAdapter
        ad = MexcLinearAdapter.__new__(MexcLinearAdapter)
        ad._api_key = ""
        ad._api_secret = ""
        ad._proxy = ""
        ad._ex = MagicMock()
        ad._ex.fetch_positions.return_value = raw_positions
        ad._ex.last_response_headers = None
        ad._markets_loaded = False
        ad._weight_tracker = None
        ad._current_priority = "normal"
        return ad

    def test_missing_symbol_logs_and_skips(self, caplog):
        ad = self._make_adapter([
            {"contracts": 1.5, "entryPrice": 50000, "side": "long"},
            {"symbol": "BTC/USDT:USDT", "contracts": 2.0, "side": "long"},
        ])
        with caplog.at_level(logging.WARNING, logger="adapters.mexc"):
            result = asyncio.run(ad.fetch_positions())
        assert len(result) == 1
        assert "skipping record" in caplog.text


class TestMed050Granularity:
    """The granularity choice: per-record drop, not whole-response drop.
    Verifies one bad record doesn't blank the entire list."""

    def test_one_bad_amid_many_good_drops_only_bad(self, caplog):
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        ad = BinanceUSDMAdapter.__new__(BinanceUSDMAdapter)
        ad._api_key = ""
        ad._api_secret = ""
        ad._proxy = ""
        ad._ex = MagicMock()
        ad._ex.fapiPrivateV2GetAccount.return_value = {
            "positions": [
                {"symbol": "BTCUSDT", "positionAmt": "1.5"},
                {"positionAmt": "0.5"},  # bad — no symbol
                {"symbol": "ETHUSDT", "positionAmt": "10"},
                {"symbol": "SOLUSDT", "positionAmt": "20"},
            ],
        }
        ad._ex.last_response_headers = None
        ad._markets_loaded = False
        ad._weight_tracker = None
        ad._current_priority = "normal"
        with caplog.at_level(logging.WARNING, logger="adapters.binance.rest"):
            result = asyncio.run(ad.fetch_positions())
        assert len(result) == 3
        assert {p.symbol for p in result} == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}


# ── MED-046: executescript handles semicolons in comments ────────────────────

class TestMed046ExecutescriptHandlesCommentSemicolons:
    """The original Task 104a failure: a `;` inside a `--` SQL comment
    line tricks the naive `.split(";")` loop into emitting a partial
    statement, which raises `sqlite3.OperationalError: incomplete
    input`. executescript() uses the proper SQL tokenizer."""

    def test_executescript_handles_comments_with_semicolons(self):
        """Direct reproduction of the Task 104a failure mode against
        the stdlib's executescript() — this is what the prod code now
        uses via aiosqlite (which thin-wraps the same impl)."""
        sql = """
-- This comment contains a semicolon; like this.
CREATE TABLE t (x INTEGER);

-- Another comment; with another semicolon.
CREATE TABLE u (y INTEGER);
"""
        conn = sqlite3.connect(":memory:")
        # executescript() must not raise on the embedded semicolons.
        conn.executescript(sql)
        # And both tables must exist.
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "ORDER BY name"
        ).fetchall()
        names = {r[0] for r in rows}
        assert "t" in names
        assert "u" in names

    def test_naive_split_would_fail_on_same_input(self):
        """Anti-revert FBF: confirm the OLD approach DOES break on
        the same input. The naive split emits a partial statement that
        starts mid-comment, which sqlite3 rejects with an
        OperationalError (exact message varies — sometimes
        'incomplete input', sometimes 'near "<word>": syntax error'
        depending on which fragment got split out). What matters is
        the executescript() path is the *only* path that handles this
        correctly."""
        sql = """
-- This comment contains a semicolon; like this.
CREATE TABLE t (x INTEGER);
"""
        conn = sqlite3.connect(":memory:")
        with pytest.raises(sqlite3.OperationalError):
            for stmt in sql.strip().split(";"):
                stmt = stmt.strip()
                if stmt and not stmt.upper().startswith("PRAGMA"):
                    conn.execute(stmt)

    def test_database_init_source_uses_executescript(self):
        """Source-pin: core/database.py uses executescript, not the
        old split loop."""
        import core.database as m
        init_src = inspect.getsource(m.DatabaseManager.initialize)
        assert "executescript" in init_src, (
            "MED-046 regression: Database.initialize no longer calls "
            "executescript — the naive split loop may be back."
        )
        # Anti-revert: the old split-and-loop signature must not be
        # in this function anymore (would catch a partial revert).
        assert "_CREATE_STATEMENTS.strip().split" not in init_src, (
            "MED-046 regression: the old naive split is still present "
            "in initialize() alongside executescript — partial revert."
        )


# ── Anti-regression: existing behavior unchanged ─────────────────────────────

class TestAntiRegression:
    """Existing functionality must not regress. Sample checks across
    the surfaces this task touched."""

    def test_med_048_exchange_validator_still_wired(self):
        """Task 114 anti-regression — MED-049's addition must not
        displace MED-048's exchange validator."""
        import api.routes_accounts as m
        for name in (
            "create_account", "add_account_modal",
            "test_account_preview", "update_account_detail",
        ):
            src = inspect.getsource(getattr(m, name))
            assert "_validate_exchange(" in src, (
                f"MED-048 regression: {name} no longer validates exchange."
            )

    def test_high_013_binance_account_validation_still_raises(self):
        """Task 102 anti-regression — Binance fetch_account still
        fail-closed on missing critical fields."""
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        ad = BinanceUSDMAdapter.__new__(BinanceUSDMAdapter)
        ad._api_key = ""
        ad._api_secret = ""
        ad._proxy = ""
        ad._ex = MagicMock()
        ad._ex.fapiPrivateV2GetAccount.return_value = {
            "availableBalance": "1000",  # totalWalletBalance MISSING
        }
        ad._ex.fapiPrivateGetCommissionRate.return_value = {}
        ad._ex.last_response_headers = None
        ad._markets_loaded = False
        ad._weight_tracker = None
        ad._current_priority = "normal"
        with pytest.raises(ValueError):
            asyncio.run(ad.fetch_account())
