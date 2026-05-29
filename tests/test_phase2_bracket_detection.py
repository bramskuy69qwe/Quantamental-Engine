"""Phase 2.8 — TP/SL bracket detection (core engine + per-adapter).

Covers core.bracket_detection.detect_brackets (two-tier: venue-native
shared-link → (symbol, position_side) + 2s time-window) and the thin
per-adapter detect_bracket() delegations (Binance/Bybit/MEXC). T2.8 is
DETECT ONLY — no calc_id writes (that's T2.9).

Run: pytest tests/test_phase2_bracket_detection.py -v
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.bracket_detection import (  # noqa: E402
    detect_brackets, is_entry_leg, is_protective_leg, DEFAULT_WINDOW_MS,
)


def _o(otype, ps="LONG", ts=1000, *, symbol="BTCUSDT", reduce_only=None,
       link="", eoid=None):
    return {
        "symbol": symbol,
        "order_type": otype,
        "position_side": ps,
        "created_at_ms": ts,
        "reduce_only": reduce_only,
        "client_order_id": link,
        "exchange_order_id": eoid or f"{otype}-{ts}",
    }


def _ids(group):
    return {o["exchange_order_id"] for o in group}


# ── leg classification ─────────────────────────────────────────────────


class TestLegClassification:
    def test_entry_types(self):
        assert is_entry_leg(_o("limit"))
        assert is_entry_leg(_o("market"))
        assert is_entry_leg(_o("stop_loss_entry"))     # FE-13 entry-stop
        assert not is_entry_leg(_o("take_profit"))
        assert not is_entry_leg(_o("stop_loss"))
        assert not is_entry_leg(_o("market", reduce_only=1))  # reduce-only close

    def test_protective_types(self):
        assert is_protective_leg(_o("take_profit"))
        assert is_protective_leg(_o("take_profit_market"))
        assert is_protective_leg(_o("stop_loss"))
        assert is_protective_leg(_o("stop_market"))
        assert is_protective_leg(_o("trailing_stop"))
        assert is_protective_leg(_o("market", reduce_only=1))  # reduce-only close
        assert not is_protective_leg(_o("stop_loss_entry"))    # entry-stop, not protective
        assert not is_protective_leg(_o("limit"))


# ── tier 2: (symbol, position_side) + time-window ──────────────────────


class TestTimeWindowClustering:
    def test_entry_tp_sl_within_window_is_one_bracket(self):
        orders = [
            _o("limit", "LONG", 1000, eoid="E"),
            _o("take_profit", "LONG", 1100, eoid="TP"),
            _o("stop_loss", "LONG", 1200, eoid="SL"),
        ]
        groups = detect_brackets(orders)
        assert len(groups) == 1
        assert _ids(groups[0]) == {"E", "TP", "SL"}

    def test_two_entries_far_apart_split_into_two_brackets(self):
        orders = [
            _o("limit", "LONG", 1000, eoid="E1"),
            _o("take_profit", "LONG", 1100, eoid="TP1"),
            _o("limit", "LONG", 9000, eoid="E2"),     # >2s later → new cluster
            _o("stop_loss", "LONG", 9100, eoid="SL2"),
        ]
        groups = detect_brackets(orders)
        assert len(groups) == 2
        assert {frozenset(_ids(g)) for g in groups} == {
            frozenset({"E1", "TP1"}), frozenset({"E2", "SL2"})}

    def test_different_position_side_not_grouped(self):
        # LONG entry + SHORT tp are different cohorts; neither cohort has
        # both an entry AND a protective → no bracket.
        orders = [
            _o("limit", "LONG", 1000, eoid="EL"),
            _o("take_profit", "SHORT", 1050, eoid="TPS"),
        ]
        assert detect_brackets(orders) == []

    def test_window_boundary_inclusive(self):
        # exactly window_ms apart → siblings; window_ms+1 → split.
        within = [_o("limit", "LONG", 1000, eoid="E"),
                  _o("stop_loss", "LONG", 1000 + DEFAULT_WINDOW_MS, eoid="SL")]
        assert len(detect_brackets(within)) == 1
        beyond = [_o("limit", "LONG", 1000, eoid="E"),
                  _o("stop_loss", "LONG", 1001 + DEFAULT_WINDOW_MS, eoid="SL")]
        assert detect_brackets(beyond) == []   # entry alone + SL alone, neither a bracket

    def test_standalone_tp_sl_no_entry_is_not_bracket(self):
        # protective-only cluster (TP+SL on an existing position) → matcher
        # territory, not a bracket.
        orders = [_o("take_profit", "LONG", 1000, eoid="TP"),
                  _o("stop_loss", "LONG", 1050, eoid="SL")]
        assert detect_brackets(orders) == []

    def test_two_entries_only_is_not_bracket(self):
        orders = [_o("limit", "LONG", 1000, eoid="E1"),
                  _o("market", "LONG", 1050, eoid="E2")]
        assert detect_brackets(orders) == []

    def test_empty(self):
        assert detect_brackets([]) == []

    def test_span_beyond_window_splits_anchor_bounded(self):
        # T236: anchor-bounded clustering — a drip of orders each within
        # window_ms of the PREVIOUS but spanning >window_ms total must NOT
        # chain into one oversized bracket. E@0, TP@1900, SL@3800: SL is
        # 3800ms from the anchor (>2000) → splits. Anchor cluster {E,TP}
        # is a bracket; SL alone is not → exactly one bracket of {E,TP}.
        orders = [
            _o("limit", "LONG", 0, eoid="E"),
            _o("take_profit", "LONG", 1900, eoid="TP"),
            _o("stop_loss", "LONG", 3800, eoid="SL"),
        ]
        groups = detect_brackets(orders)
        assert len(groups) == 1
        assert _ids(groups[0]) == {"E", "TP"}   # NOT {E,TP,SL}

    def test_reduce_only_market_close_forms_bracket(self):
        # An entry + a reduce_only market close (order_type='market',
        # reduce_only=1) within window → bracket (protective via reduce_only).
        orders = [
            _o("limit", "LONG", 1000, eoid="E"),
            _o("market", "LONG", 1100, reduce_only=1, eoid="RC"),
        ]
        groups = detect_brackets(orders)
        assert len(groups) == 1 and _ids(groups[0]) == {"E", "RC"}

    def test_different_symbols_not_grouped(self):
        orders = [
            _o("limit", "LONG", 1000, symbol="BTCUSDT", eoid="EB"),
            _o("take_profit", "LONG", 1050, symbol="ETHUSDT", eoid="TE"),
        ]
        # Different (symbol,_) cohorts → neither has entry+protective.
        assert detect_brackets(orders) == []


# ── tier 1: venue-native shared link (Bybit orderLinkId) ───────────────


class TestSharedLinkClustering:
    def test_shared_link_groups_regardless_of_time(self):
        # Same orderLinkId across legs placed >2s apart → still one bracket.
        orders = [
            _o("limit", "LONG", 1000, link="brk1", eoid="E"),
            _o("take_profit", "LONG", 9000, link="brk1", eoid="TP"),
            _o("stop_loss", "LONG", 20000, link="brk1", eoid="SL"),
        ]
        groups = detect_brackets(orders, link_field="client_order_id")
        assert len(groups) == 1
        assert _ids(groups[0]) == {"E", "TP", "SL"}

    def test_distinct_links_fall_to_time_window(self):
        # Unique per-order link (Binance-style) → tier-1 singletons fall to
        # tier-2 window clustering.
        orders = [
            _o("limit", "LONG", 1000, link="web_aaa", eoid="E"),
            _o("take_profit", "LONG", 1100, link="web_bbb", eoid="TP"),
            _o("stop_loss", "LONG", 1200, link="web_ccc", eoid="SL"),
        ]
        groups = detect_brackets(orders, link_field="client_order_id")
        assert len(groups) == 1
        assert _ids(groups[0]) == {"E", "TP", "SL"}

    def test_shared_link_without_entry_is_not_bracket(self):
        orders = [
            _o("take_profit", "LONG", 1000, link="brk1", eoid="TP"),
            _o("stop_loss", "LONG", 1050, link="brk1", eoid="SL"),
        ]
        assert detect_brackets(orders, link_field="client_order_id") == []

    def test_mixed_link_and_window_in_one_call(self):
        # One bracket via shared link (legs far apart), a SECOND via the
        # time-window fallback (distinct links, close together), in a single
        # call → both detected.
        orders = [
            # link bracket (BTC), spread 25s
            _o("limit", "LONG", 1000, link="brkA", symbol="BTCUSDT", eoid="EA"),
            _o("stop_loss", "LONG", 26000, link="brkA", symbol="BTCUSDT", eoid="SLA"),
            # window bracket (ETH), distinct links, within 2s
            _o("limit", "LONG", 5000, link="web_1", symbol="ETHUSDT", eoid="EB"),
            _o("take_profit", "LONG", 5100, link="web_2", symbol="ETHUSDT", eoid="TPB"),
        ]
        groups = detect_brackets(orders, link_field="client_order_id")
        assert len(groups) == 2
        assert {frozenset(_ids(g)) for g in groups} == {
            frozenset({"EA", "SLA"}), frozenset({"EB", "TPB"})}


# ── per-adapter delegation ─────────────────────────────────────────────


class TestAdapterDelegation:
    def test_binance_detect_bracket(self):
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        orders = [_o("limit", "LONG", 1000, eoid="E"),
                  _o("take_profit", "LONG", 1100, eoid="TP")]
        groups = BinanceUSDMAdapter.detect_bracket(orders)
        assert len(groups) == 1 and _ids(groups[0]) == {"E", "TP"}

    def test_binance_ignores_shared_client_order_id(self):
        # Discriminates link_field=None: a SHARED client_order_id on two
        # legs placed >window apart must NOT group on Binance (it has no
        # tier-1 key) → window split → no bracket. A mutation switching
        # Binance to link_field="client_order_id" would group them → 1
        # bracket, failing this test.
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        orders = [_o("limit", "LONG", 1000, link="web_x", eoid="E"),
                  _o("stop_loss", "LONG", 60000, link="web_x", eoid="SL")]
        assert BinanceUSDMAdapter.detect_bracket(orders) == []

    def test_bybit_uses_orderlinkid(self):
        from core.adapters.bybit.rest_adapter import BybitLinearAdapter
        # Spread >2s but shared orderLinkId → bybit groups via link.
        orders = [_o("limit", "LONG", 1000, link="brk", eoid="E"),
                  _o("stop_loss", "LONG", 30000, link="brk", eoid="SL")]
        groups = BybitLinearAdapter.detect_bracket(orders)
        assert len(groups) == 1 and _ids(groups[0]) == {"E", "SL"}

    def test_mexc_symbol_window_no_position_side(self):
        from core.adapters.mexc.rest_adapter import MexcLinearAdapter
        # MEXC orders carry no position_side / reduce_only — cluster by
        # (symbol, "") + window, entry/protective by order_type.
        orders = [_o("limit", ps=None, ts=1000, reduce_only=None, eoid="E"),
                  _o("take_profit", ps=None, ts=1100, reduce_only=None, eoid="TP")]
        groups = MexcLinearAdapter.detect_bracket(orders)
        assert len(groups) == 1 and _ids(groups[0]) == {"E", "TP"}

    def test_mexc_ignores_shared_client_order_id(self):
        # Discriminates link_field=None for MEXC (same as Binance).
        from core.adapters.mexc.rest_adapter import MexcLinearAdapter
        orders = [_o("limit", ps=None, ts=1000, reduce_only=None, link="c", eoid="E"),
                  _o("stop_loss", ps=None, ts=60000, reduce_only=None, link="c", eoid="SL")]
        assert MexcLinearAdapter.detect_bracket(orders) == []


# ── no-mutation guarantee ──────────────────────────────────────────────


class TestNoMutation:
    def test_input_not_mutated(self):
        orders = [_o("limit", "LONG", 1000, eoid="E"),
                  _o("take_profit", "LONG", 1100, eoid="TP")]
        snapshot = [dict(o) for o in orders]
        detect_brackets(orders)
        assert orders == snapshot
