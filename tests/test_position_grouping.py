"""
Phase 0.0.1 tests for ``core/position_grouping.py``.

Covers:
  - ``is_same_fill`` dedup rule (every distinguishing axis)
  - ``group_fills_into_positions`` chronological-walk grouping
    (single position, scale-in, partial close, full close, hedge mode,
    qty-epsilon, sequential direction flip)
  - ``PositionRecord`` shape + canonical field semantics
    (calc_id propagation, fees, realized_pnl math fallback, synthetic
    terminal_position_id format, ``source``, ``backfill_completed=0``)

Run: pytest tests/test_position_grouping.py -v
"""
from __future__ import annotations

import pytest

from core.position_grouping import (
    FILL_DEDUP_PRICE_TOLERANCE_PCT,
    FILL_DEDUP_TOLERANCE_MS,
    group_fills_into_positions,
    is_same_fill,
)


# ── Fixture builder ─────────────────────────────────────────────────────


def _fill(
    *,
    ts: int,
    symbol: str = "BSBUSDT",
    side: str = "BUY",
    direction: str = "LONG",
    price: float = 100.0,
    quantity: float = 1.0,
    is_close: int = 0,
    fee: float = 0.0,
    realized_pnl: float = 0.0,
    account_id: int = 1,
    exchange_fill_id: str = "",
    calc_id: str = "",
    source: str = "binance_ws",
):
    """Build a fill dict matching the ``fills`` table column shape."""
    return {
        "account_id":           account_id,
        "exchange_fill_id":     exchange_fill_id or f"fid-{ts}",
        "symbol":               symbol,
        "side":                 side,
        "direction":            direction,
        "price":                price,
        "quantity":             quantity,
        "fee":                  fee,
        "is_close":             is_close,
        "realized_pnl":         realized_pnl,
        "timestamp_ms":         ts,
        "source":               source,
        "calc_id":              calc_id,
    }


# ── is_same_fill ────────────────────────────────────────────────────────


class TestIsSameFillExposesConstants:
    """Constants are part of the public API — callers in Phase 0.0.2/0.0.3
    import them. Pin the documented values so an accidental change here
    surfaces in this test rather than silently shifting dedup behavior."""

    def test_timestamp_tolerance_is_2_seconds(self):
        assert FILL_DEDUP_TOLERANCE_MS == 2000

    def test_price_tolerance_is_exact(self):
        assert FILL_DEDUP_PRICE_TOLERANCE_PCT == 0.0


class TestIsSameFillMatch:
    def test_identical_fills_match(self):
        a = _fill(ts=1000)
        b = _fill(ts=1000)
        assert is_same_fill(a, b) is True

    def test_within_2s_skew_matches(self):
        a = _fill(ts=1000)
        b = _fill(ts=1000 + FILL_DEDUP_TOLERANCE_MS)
        assert is_same_fill(a, b) is True

    def test_beyond_2s_skew_does_not_match(self):
        a = _fill(ts=1000)
        b = _fill(ts=1000 + FILL_DEDUP_TOLERANCE_MS + 1)
        assert is_same_fill(a, b) is False

    def test_qty_within_float_epsilon_matches(self):
        # 0.1 + 0.2 == 0.30000000000000004 — classic IEEE-754 drift.
        # Dedup should still treat these as the same trade.
        a = _fill(ts=1000, quantity=0.3)
        b = _fill(ts=1000, quantity=0.1 + 0.2)
        assert is_same_fill(a, b) is True


class TestIsSameFillMismatch:
    def test_different_symbol_does_not_match(self):
        a = _fill(ts=1000, symbol="BSBUSDT")
        b = _fill(ts=1000, symbol="BTCUSDT")
        assert is_same_fill(a, b) is False

    def test_different_side_does_not_match(self):
        a = _fill(ts=1000, side="BUY")
        b = _fill(ts=1000, side="SELL")
        assert is_same_fill(a, b) is False

    def test_different_direction_does_not_match(self):
        # Same side BUY but different direction (LONG open vs SHORT close)
        # — synthetic ambiguity that the side+direction combo guards
        # against.
        a = _fill(ts=1000, side="BUY", direction="LONG", is_close=0)
        b = _fill(ts=1000, side="BUY", direction="SHORT", is_close=1)
        assert is_same_fill(a, b) is False

    def test_different_is_close_does_not_match(self):
        a = _fill(ts=1000, is_close=0)
        b = _fill(ts=1000, is_close=1)
        assert is_same_fill(a, b) is False

    def test_different_quantity_does_not_match(self):
        a = _fill(ts=1000, quantity=1.0)
        b = _fill(ts=1000, quantity=2.0)
        assert is_same_fill(a, b) is False

    def test_different_price_does_not_match_under_exact_tolerance(self):
        # FILL_DEDUP_PRICE_TOLERANCE_PCT = 0.0 → exact match required.
        a = _fill(ts=1000, price=100.00)
        b = _fill(ts=1000, price=100.01)
        assert is_same_fill(a, b) is False


class TestIsSameFillCaseInsensitive:
    """Side and direction come from different sources (WS payload, REST
    response, backfill heuristic) with inconsistent casing. The dedup
    rule normalizes both to uppercase before comparing."""

    def test_lowercase_side_matches_uppercase(self):
        a = _fill(ts=1000, side="BUY")
        b = _fill(ts=1000, side="buy")
        assert is_same_fill(a, b) is True

    def test_lowercase_direction_matches_uppercase(self):
        a = _fill(ts=1000, direction="LONG")
        b = _fill(ts=1000, direction="long")
        assert is_same_fill(a, b) is True


# ── group_fills_into_positions: basic lifecycle ─────────────────────────


class TestSinglePosition:
    def test_open_then_close_emits_one_record(self):
        fills = [
            _fill(ts=1000, side="BUY", direction="LONG",
                  price=100.0, quantity=1.0, is_close=0),
            _fill(ts=2000, side="SELL", direction="LONG",
                  price=110.0, quantity=1.0, is_close=1,
                  realized_pnl=10.0),
        ]
        rows = group_fills_into_positions(fills)
        assert len(rows) == 1
        r = rows[0]
        assert r["symbol"] == "BSBUSDT"
        assert r["direction"] == "LONG"
        assert r["quantity"] == 1.0
        assert r["entry_price"] == 100.0
        assert r["exit_price"] == 110.0
        assert r["entry_time_ms"] == 1000
        assert r["exit_time_ms"] == 2000
        assert r["realized_pnl"] == 10.0
        assert r["hold_time_ms"] == 1000


class TestScaleIn:
    def test_two_opens_then_close_uses_vwap_entry(self):
        # Two opens at different prices → VWAP entry.
        # qty-weighted: (100*1 + 120*3) / 4 = 115
        fills = [
            _fill(ts=1000, side="BUY", direction="LONG",
                  price=100.0, quantity=1.0, is_close=0),
            _fill(ts=1500, side="BUY", direction="LONG",
                  price=120.0, quantity=3.0, is_close=0),
            _fill(ts=2000, side="SELL", direction="LONG",
                  price=130.0, quantity=4.0, is_close=1,
                  realized_pnl=60.0),
        ]
        rows = group_fills_into_positions(fills)
        assert len(rows) == 1
        r = rows[0]
        assert r["entry_price"] == pytest.approx(115.0)
        assert r["quantity"] == 4.0
        assert r["entry_time_ms"] == 1000   # earliest open
        assert r["exit_price"] == 130.0


class TestPartialClose:
    def test_open_partial_close_then_full_close_emits_one_record(self):
        # Open 4, partial-close 1, then close remaining 3.
        # Position considered closed only when qty back to 0.
        fills = [
            _fill(ts=1000, side="BUY", direction="LONG",
                  price=100.0, quantity=4.0, is_close=0),
            _fill(ts=1500, side="SELL", direction="LONG",
                  price=110.0, quantity=1.0, is_close=1,
                  realized_pnl=10.0),
            _fill(ts=2000, side="SELL", direction="LONG",
                  price=120.0, quantity=3.0, is_close=1,
                  realized_pnl=60.0),
        ]
        rows = group_fills_into_positions(fills)
        assert len(rows) == 1
        r = rows[0]
        assert r["quantity"] == 4.0   # total qty closed
        # Exit price is VWAP of closes: (110*1 + 120*3) / 4 = 117.5
        assert r["exit_price"] == pytest.approx(117.5)
        assert r["exit_time_ms"] == 2000   # last close
        assert r["realized_pnl"] == pytest.approx(70.0)


class TestFullClose:
    def test_open_single_full_close_emits_one_record(self):
        fills = [
            _fill(ts=1000, side="BUY", direction="LONG",
                  price=50.0, quantity=10.0, is_close=0),
            _fill(ts=2000, side="SELL", direction="LONG",
                  price=55.0, quantity=10.0, is_close=1,
                  realized_pnl=50.0),
        ]
        rows = group_fills_into_positions(fills)
        assert len(rows) == 1
        assert rows[0]["quantity"] == 10.0
        assert rows[0]["realized_pnl"] == 50.0


# ── Hedge mode ──────────────────────────────────────────────────────────


class TestHedgeMode:
    """LONG and SHORT positions held simultaneously on the same symbol —
    the grouping key is ``(account_id, symbol, direction)``, so each
    direction tracks independently."""

    def test_simultaneous_long_and_short_emit_two_records(self):
        # Open LONG at 100, open SHORT at 105, close LONG at 110, close SHORT at 95.
        # LONG: pnl = (110-100)*1 = +10. SHORT: pnl = (105-95)*1 = +10.
        fills = [
            _fill(ts=1000, side="BUY", direction="LONG",
                  price=100.0, quantity=1.0, is_close=0),
            _fill(ts=1100, side="SELL", direction="SHORT",
                  price=105.0, quantity=1.0, is_close=0),
            _fill(ts=2000, side="SELL", direction="LONG",
                  price=110.0, quantity=1.0, is_close=1,
                  realized_pnl=10.0),
            _fill(ts=2100, side="BUY", direction="SHORT",
                  price=95.0, quantity=1.0, is_close=1,
                  realized_pnl=10.0),
        ]
        rows = group_fills_into_positions(fills)
        assert len(rows) == 2
        by_dir = {r["direction"]: r for r in rows}
        assert "LONG" in by_dir and "SHORT" in by_dir
        assert by_dir["LONG"]["entry_price"] == 100.0
        assert by_dir["LONG"]["exit_price"] == 110.0
        assert by_dir["SHORT"]["entry_price"] == 105.0
        assert by_dir["SHORT"]["exit_price"] == 95.0


# ── Float-precision qty epsilon ─────────────────────────────────────────


class TestQtyEpsilon:
    """Floating-point drift in qty arithmetic must not prevent the
    close detection. ``_QTY_EPS = 1e-6`` absorbs IEEE-754 ULP drift
    from the qty arithmetic."""

    def test_open_then_close_with_float_drift_still_closes(self):
        # 0.1 + 0.2 = 0.30000000000000004 in IEEE-754. Open 0.3, close
        # via two 0.1+0.2 fills — residual qty is ~4e-17, well under
        # _QTY_EPS=1e-6. Position should still close.
        fills = [
            _fill(ts=1000, side="BUY", direction="LONG",
                  price=100.0, quantity=0.3, is_close=0),
            _fill(ts=1500, side="SELL", direction="LONG",
                  price=110.0, quantity=0.1, is_close=1,
                  realized_pnl=1.0),
            _fill(ts=2000, side="SELL", direction="LONG",
                  price=110.0, quantity=0.2, is_close=1,
                  realized_pnl=2.0),
        ]
        rows = group_fills_into_positions(fills)
        assert len(rows) == 1
        # Total close qty is sum of close fills (0.1 + 0.2 in float),
        # which is approx 0.3.
        assert rows[0]["quantity"] == pytest.approx(0.3)


# ── Edge cases ──────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_fills_returns_empty(self):
        assert group_fills_into_positions([]) == []

    def test_close_without_prior_open_is_skipped(self):
        # First fill is a close — no prior open in the window.
        # Common case: rebuild script reads fills from a date range that
        # doesn't include the open. Helper should ignore, not crash.
        fills = [
            _fill(ts=1000, side="SELL", direction="LONG",
                  price=110.0, quantity=1.0, is_close=1,
                  realized_pnl=10.0),
        ]
        assert group_fills_into_positions(fills) == []

    def test_zero_qty_fill_is_skipped(self):
        fills = [
            _fill(ts=1000, side="BUY", direction="LONG",
                  price=100.0, quantity=0.0, is_close=0),
            _fill(ts=2000, side="BUY", direction="LONG",
                  price=100.0, quantity=1.0, is_close=0),
            _fill(ts=3000, side="SELL", direction="LONG",
                  price=110.0, quantity=1.0, is_close=1),
        ]
        rows = group_fills_into_positions(fills)
        assert len(rows) == 1
        assert rows[0]["quantity"] == 1.0   # zero-qty fill ignored

    def test_open_without_close_is_not_emitted(self):
        # Position still live at end of input — closed_positions tracks
        # closed positions only.
        fills = [
            _fill(ts=1000, side="BUY", direction="LONG",
                  price=100.0, quantity=1.0, is_close=0),
        ]
        assert group_fills_into_positions(fills) == []

    def test_missing_symbol_or_direction_is_skipped(self):
        fills = [
            _fill(ts=1000, symbol="", quantity=1.0),
            _fill(ts=1500, direction="", quantity=1.0),
            _fill(ts=2000, side="BUY", direction="LONG",
                  price=100.0, quantity=1.0, is_close=0),
            _fill(ts=3000, side="SELL", direction="LONG",
                  price=110.0, quantity=1.0, is_close=1),
        ]
        # Only the valid LONG round-trip emits.
        rows = group_fills_into_positions(fills)
        assert len(rows) == 1

    def test_sequential_long_then_short_same_symbol_emits_two_records(self):
        # Close a LONG fully, then open and close a SHORT on the same
        # symbol. Two distinct logical positions; chronological-walk
        # discovers both because direction differs.
        fills = [
            _fill(ts=1000, side="BUY",  direction="LONG",
                  price=100.0, quantity=1.0, is_close=0),
            _fill(ts=2000, side="SELL", direction="LONG",
                  price=110.0, quantity=1.0, is_close=1,
                  realized_pnl=10.0),
            _fill(ts=3000, side="SELL", direction="SHORT",
                  price=110.0, quantity=1.0, is_close=0),
            _fill(ts=4000, side="BUY",  direction="SHORT",
                  price=100.0, quantity=1.0, is_close=1,
                  realized_pnl=10.0),
        ]
        rows = group_fills_into_positions(fills)
        assert len(rows) == 2
        assert {r["direction"] for r in rows} == {"LONG", "SHORT"}

    def test_accounts_isolated(self):
        # Same symbol/direction/time but different accounts → independent
        # state. Both round-trip emits separately.
        fills = [
            _fill(ts=1000, account_id=1, side="BUY",  direction="LONG",
                  price=100.0, quantity=1.0, is_close=0),
            _fill(ts=1000, account_id=2, side="BUY",  direction="LONG",
                  price=100.0, quantity=1.0, is_close=0),
            _fill(ts=2000, account_id=1, side="SELL", direction="LONG",
                  price=110.0, quantity=1.0, is_close=1, realized_pnl=10.0),
            _fill(ts=2000, account_id=2, side="SELL", direction="LONG",
                  price=120.0, quantity=1.0, is_close=1, realized_pnl=20.0),
        ]
        rows = group_fills_into_positions(fills)
        assert len(rows) == 2
        by_acct = {r["account_id"]: r for r in rows}
        assert by_acct[1]["exit_price"] == 110.0
        assert by_acct[2]["exit_price"] == 120.0


# ── PositionRecord shape + canonical fields ─────────────────────────────


class TestPositionRecordShape:
    """The emitted record must match the keys read by
    ``db_orders.insert_closed_position``. Missing keys would silently
    take the ``.get(..., default)`` fallback there — usually 0 or "" —
    which masks data-loss bugs."""

    REQUIRED_KEYS = frozenset({
        "account_id", "exchange_position_id", "terminal_position_id",
        "symbol", "direction", "quantity", "entry_price", "exit_price",
        "entry_time_ms", "exit_time_ms", "realized_pnl", "total_fees",
        "net_pnl", "funding_fees", "hold_time_ms", "exit_reason",
        "model_name", "source", "calc_id", "mfe", "mae",
        "backfill_completed",
    })

    def _one_record(self):
        fills = [
            _fill(ts=1000, side="BUY", direction="LONG",
                  price=100.0, quantity=1.0, is_close=0),
            _fill(ts=2000, side="SELL", direction="LONG",
                  price=110.0, quantity=1.0, is_close=1,
                  realized_pnl=10.0),
        ]
        rows = group_fills_into_positions(fills)
        assert len(rows) == 1
        return rows[0]

    def test_required_keys_present(self):
        r = self._one_record()
        missing = self.REQUIRED_KEYS - set(r.keys())
        assert not missing, f"missing keys in PositionRecord: {missing}"

    def test_source_marks_as_rebuilt(self):
        # Sentinel for the dryrun script's filter (``WHERE source !=
        # 'rebuilt_from_fills'``) and for grep-based audit later.
        r = self._one_record()
        assert r["source"] == "rebuilt_from_fills"

    def test_backfill_completed_is_zero(self):
        # Reconciler picks up rows with backfill_completed=0 to compute
        # MFE/MAE with T175's gross-PnL floor. Don't pre-compute here.
        r = self._one_record()
        assert r["backfill_completed"] == 0

    def test_mfe_mae_left_to_reconciler(self):
        r = self._one_record()
        assert r["mfe"] == 0.0
        assert r["mae"] == 0.0

    def test_terminal_position_id_is_deterministic_rebuilt_prefix(self):
        # Format: rebuilt:{symbol}:{direction}:{entry_time_ms}
        # Same inputs → same ID across reruns (idempotent rebuild).
        r = self._one_record()
        assert r["terminal_position_id"] == "rebuilt:BSBUSDT:LONG:1000"

    def test_terminal_position_id_idempotent_across_reruns(self):
        r1 = self._one_record()
        r2 = self._one_record()
        assert r1["terminal_position_id"] == r2["terminal_position_id"]

    def test_hold_time_clamped_non_negative(self):
        # Defensive: if exit_time < entry_time (clock skew / data bug),
        # hold_time_ms must not go negative.
        fills = [
            _fill(ts=5000, side="BUY", direction="LONG",
                  price=100.0, quantity=1.0, is_close=0),
            _fill(ts=4000, side="SELL", direction="LONG",
                  price=110.0, quantity=1.0, is_close=1,
                  realized_pnl=10.0),
        ]
        rows = group_fills_into_positions(fills)
        assert rows[0]["hold_time_ms"] == 0


class TestCalcIdPropagation:
    def test_calc_id_from_earliest_open(self):
        fills = [
            _fill(ts=1000, side="BUY", direction="LONG",
                  price=100.0, quantity=1.0, is_close=0,
                  calc_id="calc-first"),
            _fill(ts=1500, side="BUY", direction="LONG",
                  price=100.0, quantity=1.0, is_close=0,
                  calc_id="calc-second"),
            _fill(ts=2000, side="SELL", direction="LONG",
                  price=110.0, quantity=2.0, is_close=1,
                  realized_pnl=20.0),
        ]
        rows = group_fills_into_positions(fills)
        assert rows[0]["calc_id"] == "calc-first"

    def test_calc_id_empty_when_no_open_has_one(self):
        fills = [
            _fill(ts=1000, side="BUY", direction="LONG",
                  price=100.0, quantity=1.0, is_close=0),
            _fill(ts=2000, side="SELL", direction="LONG",
                  price=110.0, quantity=1.0, is_close=1,
                  realized_pnl=10.0),
        ]
        rows = group_fills_into_positions(fills)
        assert rows[0]["calc_id"] == ""

    def test_calc_id_skips_empty_open_to_find_filled_one(self):
        # First open has empty calc_id, second has one. Helper should
        # pick the first non-empty rather than the earliest.
        fills = [
            _fill(ts=1000, side="BUY", direction="LONG",
                  price=100.0, quantity=1.0, is_close=0,
                  calc_id=""),
            _fill(ts=1500, side="BUY", direction="LONG",
                  price=100.0, quantity=1.0, is_close=0,
                  calc_id="calc-second"),
            _fill(ts=2000, side="SELL", direction="LONG",
                  price=110.0, quantity=2.0, is_close=1,
                  realized_pnl=20.0),
        ]
        rows = group_fills_into_positions(fills)
        assert rows[0]["calc_id"] == "calc-second"


class TestFeesAndPnl:
    def test_total_fees_sums_across_opens_and_closes(self):
        fills = [
            _fill(ts=1000, side="BUY", direction="LONG",
                  price=100.0, quantity=1.0, is_close=0, fee=0.10),
            _fill(ts=2000, side="SELL", direction="LONG",
                  price=110.0, quantity=1.0, is_close=1,
                  realized_pnl=10.0, fee=0.11),
        ]
        rows = group_fills_into_positions(fills)
        assert rows[0]["total_fees"] == pytest.approx(0.21)
        assert rows[0]["net_pnl"] == pytest.approx(10.0 - 0.21)

    def test_fee_rate_fallback_applies_when_fills_have_no_fee(self):
        # fee_rate_fallback × notional × 2 (both sides).
        # notional = total_close_qty * exit_price = 1.0 * 110.0 = 110.
        # fee = 0.0004 * 110 * 2 = 0.088.
        fills = [
            _fill(ts=1000, side="BUY", direction="LONG",
                  price=100.0, quantity=1.0, is_close=0, fee=0.0),
            _fill(ts=2000, side="SELL", direction="LONG",
                  price=110.0, quantity=1.0, is_close=1,
                  realized_pnl=10.0, fee=0.0),
        ]
        rows = group_fills_into_positions(fills, fee_rate_fallback=0.0004)
        assert rows[0]["total_fees"] == pytest.approx(0.088)
        assert rows[0]["net_pnl"] == pytest.approx(10.0 - 0.088)

    def test_realized_pnl_math_fallback_when_close_fills_report_zero(self):
        # When close fill carries realized_pnl=0 (e.g. backfill that
        # didn't preserve it), helper falls back to gross-pnl math:
        # LONG: (exit - entry) * qty.
        fills = [
            _fill(ts=1000, side="BUY", direction="LONG",
                  price=100.0, quantity=2.0, is_close=0),
            _fill(ts=2000, side="SELL", direction="LONG",
                  price=110.0, quantity=2.0, is_close=1,
                  realized_pnl=0.0),
        ]
        rows = group_fills_into_positions(fills)
        # gross = (110 - 100) * 2 = 20
        assert rows[0]["realized_pnl"] == pytest.approx(20.0)

    def test_realized_pnl_math_fallback_for_short(self):
        # SHORT: (entry - exit) * qty.
        fills = [
            _fill(ts=1000, side="SELL", direction="SHORT",
                  price=100.0, quantity=2.0, is_close=0),
            _fill(ts=2000, side="BUY", direction="SHORT",
                  price=90.0, quantity=2.0, is_close=1,
                  realized_pnl=0.0),
        ]
        rows = group_fills_into_positions(fills)
        # gross = (100 - 90) * 2 = 20
        assert rows[0]["realized_pnl"] == pytest.approx(20.0)


# ── T198: attribution_out ──────────────────────────────────────────────


def _fill_id(fid: int, **kwargs):
    """Build a fill dict with an explicit ``id`` field (the sqlite row
    id that attribution emits as the contributing-fill identifier)."""
    f = _fill(**kwargs)
    f["id"] = fid
    return f


class TestAttributionOut:
    def test_basic_single_position_returns_open_and_close_ids(self):
        # One LONG opened+closed. Attribution should list both fill ids.
        fills = [
            _fill_id(101, ts=1000, side="BUY", direction="LONG",
                     price=80000.0, quantity=1.0, is_close=0),
            _fill_id(102, ts=2000, side="SELL", direction="LONG",
                     price=81000.0, quantity=1.0, is_close=1,
                     realized_pnl=1000.0),
        ]
        attribution = {}
        rows = group_fills_into_positions(fills, attribution_out=attribution)
        assert len(rows) == 1
        tpid = rows[0]["terminal_position_id"]
        assert tpid in attribution
        assert sorted(attribution[tpid]) == [101, 102]

    def test_multi_open_close_position_returns_all_contributing_ids(self):
        # Scale-in + multi-close LONG: 2 opens + 2 closes.
        fills = [
            _fill_id(201, ts=1000, side="BUY", direction="LONG",
                     price=100.0, quantity=2.0, is_close=0),
            _fill_id(202, ts=1500, side="BUY", direction="LONG",
                     price=102.0, quantity=3.0, is_close=0),
            _fill_id(203, ts=2000, side="SELL", direction="LONG",
                     price=105.0, quantity=2.0, is_close=1),
            _fill_id(204, ts=2500, side="SELL", direction="LONG",
                     price=106.0, quantity=3.0, is_close=1),
        ]
        attribution = {}
        rows = group_fills_into_positions(fills, attribution_out=attribution)
        assert len(rows) == 1
        tpid = rows[0]["terminal_position_id"]
        assert sorted(attribution[tpid]) == [201, 202, 203, 204]

    def test_separate_lifecycles_get_separate_attribution_entries(self):
        # Two LONG positions back-to-back (same symbol).
        fills = [
            _fill_id(301, ts=1000, side="BUY", direction="LONG",
                     price=100.0, quantity=1.0, is_close=0),
            _fill_id(302, ts=1500, side="SELL", direction="LONG",
                     price=101.0, quantity=1.0, is_close=1),
            _fill_id(303, ts=2000, side="BUY", direction="LONG",
                     price=102.0, quantity=1.0, is_close=0),
            _fill_id(304, ts=2500, side="SELL", direction="LONG",
                     price=103.0, quantity=1.0, is_close=1),
        ]
        attribution = {}
        rows = group_fills_into_positions(fills, attribution_out=attribution)
        assert len(rows) == 2
        tpids = [r["terminal_position_id"] for r in rows]
        assert len(attribution) == 2
        assert sorted(attribution[tpids[0]]) == [301, 302]
        assert sorted(attribution[tpids[1]]) == [303, 304]

    def test_fills_without_id_are_skipped_silently(self):
        # Mix: 1 fill with id, 1 without (e.g., synth in-memory fill
        # not yet persisted). Attribution lists only the one with id.
        fills = [
            _fill_id(401, ts=1000, side="BUY", direction="LONG",
                     price=100.0, quantity=1.0, is_close=0),
            # No id — simulates synth in-memory close (not in DB yet).
            _fill(ts=2000, side="SELL", direction="LONG",
                  price=101.0, quantity=1.0, is_close=1),
        ]
        attribution = {}
        rows = group_fills_into_positions(fills, attribution_out=attribution)
        assert len(rows) == 1
        tpid = rows[0]["terminal_position_id"]
        assert attribution[tpid] == [401]

    def test_attribution_out_default_none_unchanged_behavior(self):
        # No attribution_out passed: helper behaves as before; no side
        # effects.
        fills = [
            _fill_id(501, ts=1000, side="BUY", direction="LONG",
                     price=100.0, quantity=1.0, is_close=0),
            _fill_id(502, ts=2000, side="SELL", direction="LONG",
                     price=101.0, quantity=1.0, is_close=1),
        ]
        rows = group_fills_into_positions(fills)
        # Returns list of records unchanged.
        assert len(rows) == 1
        assert rows[0]["terminal_position_id"].startswith("rebuilt:")
