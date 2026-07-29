"""E2E-P6-001 regression pins — TP/SL from the Binance ORDER FORM never linked.

INCIDENT (live, 2026-07-29, Phase-6 scenario H1):
The operator market-bought ETHUSDT with TP/SL set in Binance's order form. The
engine stored everything correctly and still never linked the trade:

    entry  8389766244548287091  market BUY LONG filled 08:44:29 (updated 08:44:35)
           tp_trigger_price=NULL  sl_trigger_price=NULL  link_status=NULL
    algo:3000002106845169  take_profit  stop 1970.0  reduce_only  status new
    algo:3000002106845170  stop_loss    stop 1860.0  reduce_only  status new

Mechanism: Binance conditional (algo) orders are invisible to the user-data WS;
the engine only learns them through `_algo_order_sync_loop`'s 15 s REST sweep →
`process_algo_snapshot`. That sweep landed AFTER the entry's last WS update, and
a filled market order receives no further WS events — so nothing ever re-ran the
entry's enrichment. `_populate_tp_sl_via_bracket` was therefore never given a
second chance, `tp/sl_trigger_price` stayed NULL, `_try_correlate` hard-returns
without both triggers (order_enrichment.py:316-323), and the order never even
reached the manual-link inbox (the queue selects NEEDS_MANUAL_REVIEW/UNLINKED,
and link_status stayed NULL).

`process_order_update` has carried `_re_enrich_parent_on_child_arrival` for
exactly this reason since 2026-06-08 ("market orders that fill before children
arrive never get correlated") — it was simply never wired into the algo path.

Fix: `process_algo_snapshot` re-enriches entries that still lack a trigger, for
(symbol, position_side) pairs carrying an active protective leg in the snapshot.
Self-limiting: once populated the query stops matching, so the 15 s sweep cannot
become a matcher loop, and naked positions are never touched.
"""
import inspect

import pytest

from core.order_manager import OrderManager


class TestAlgoSnapshotReenrichesParents:
    def test_process_algo_snapshot_calls_the_reenrich(self):
        src = inspect.getsource(OrderManager.process_algo_snapshot)
        assert "_reenrich_entries_missing_triggers" in src, (
            "the algo REST sweep is the ONLY path that discovers order-form TP/SL; "
            "without a parent re-enrich the entry's triggers stay NULL forever and "
            "auto-link can never happen on the bracket workflow"
        )

    def test_reenrich_is_self_limiting_on_missing_triggers(self):
        src = inspect.getsource(OrderManager._reenrich_entries_missing_triggers)
        assert "tp_trigger_price IS NULL OR sl_trigger_price IS NULL" in src, (
            "must only re-enrich entries that still LACK a trigger — otherwise the "
            "15 s sweep re-runs the matcher for every open position forever"
        )
        assert "reduce_only = 0" in src, "the parent is the ENTRY, not a protective leg"

    def test_reenrich_only_for_pairs_with_active_protective_legs(self):
        src = inspect.getsource(OrderManager._reenrich_entries_missing_triggers)
        assert "_TPSL_TYPES" in src and "reduce_only" in src, (
            "a naked position has no protective leg in the snapshot and must not be touched"
        )

    def test_reenrich_routes_through_enrich_order_best_effort(self):
        """Reuse the shared path so defect-8's junction-ensure fires too."""
        src = inspect.getsource(OrderManager._reenrich_entries_missing_triggers)
        assert "_enrich_order_best_effort" in src

    def test_reenrich_emits_the_attr_reenrich_corr_tap(self):
        src = inspect.getsource(OrderManager._reenrich_entries_missing_triggers)
        assert "CAT_ATTR_REENRICH_TRIGGER" in src, "the child→parent decision is a tapped seam"
        assert '"via": "algo_snapshot"' in src, "must be distinguishable from the WS twin"

    def test_ws_path_twin_still_present(self):
        """The WS-side hook must survive — the two paths are complementary."""
        src = inspect.getsource(OrderManager.process_order_update)
        assert "_re_enrich_parent_on_child_arrival" in src

    @pytest.mark.parametrize("otype", ["take_profit", "stop_loss"])
    def test_stored_algo_types_are_recognised(self, otype):
        """The live rows carry exactly these types — they MUST be in the filter set."""
        assert otype in OrderManager._TPSL_TYPES
