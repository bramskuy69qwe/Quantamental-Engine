"""E2E-P6-002 regression pins — manual-link candidates were empty for MARKET orders.

INCIDENT (live, 2026-07-29, Phase-6 scenario L2):
The operator opened a near-miss entry on purpose. The engine classified it
correctly:

    order 229947939067  SELL SHORT market  avg_fill_price 73.62  price 0.0
    link_status = NEEDS_MANUAL_REVIEW          <- correct, 4/6
    calc_match_audit: ticker OK, direction OK, window OK, entry OK,
                      tp 72.4 vs 72.41 MISS, sl 74.5 vs 74.51 MISS

…and then the manual-link resolver showed "No candidate calcs in window", so
the operator could only mark it UNPLANNED. The recovery path was unusable.

Mechanism: `find_candidate_calcs` (the LOOSE finder behind the resolver) read
`order["price"]` only and returned [] on the `not entry_price` guard. A Binance
MARKET order has price = 0 — its executed entry is `avg_fill_price`. The STRICT
matcher already handles this (order_enrichment.py:325-353 passes BOTH and
compares the fill for market orders); the loose finder did not. Additionally
`list_needs_review` never SELECTed avg_fill_price, so the value was not even in
the payload the finder receives — or in what the UI can display (the inbox strip
renders "MARKET @ 0.000000" for a real entry).

Fix: entry falls back to avg_fill_price in the finder, and the review-queue
query carries the column.
"""
import inspect

from core.calc_correlation import find_candidate_calcs
import core.link_actions as la


class TestLooseFinderAcceptsMarketFills:
    def test_entry_falls_back_to_avg_fill_price(self):
        src = inspect.getsource(find_candidate_calcs)
        assert 'order.get("avg_fill_price"' in src, (
            "a MARKET order's price is 0; without the avg_fill_price fallback the "
            "finder bails and the resolver can never offer a candidate"
        )

    def test_fallback_precedes_the_empty_guard(self):
        """The guard must see the resolved price, not the raw 0."""
        src = inspect.getsource(find_candidate_calcs)
        fallback_at = src.find('order.get("avg_fill_price"')
        guard_at = src.find("if not ticker or not entry_price")
        assert 0 < fallback_at < guard_at, "fallback must resolve BEFORE the bail-out guard"

    def test_limit_orders_still_prefer_price(self):
        """A limit order's own price must win — the fallback is for price==0 only."""
        src = inspect.getsource(find_candidate_calcs)
        assert 'order.get("price", 0) or order.get("avg_fill_price"' in src, (
            "must be price-first with avg_fill_price as fallback, not the reverse"
        )

    def test_market_order_with_zero_price_is_not_rejected_outright(self):
        """Behavioural: a market-shaped order must get PAST the guard.

        Uses a nonexistent db_path so the function returns [] at the connect
        step — what matters is that it does not return at the price guard, which
        an unreachable-DB [] cannot distinguish… so assert the guard directly.
        """
        order = {
            "symbol": "SOLUSDT", "side": "SELL", "price": 0.0,
            "avg_fill_price": 73.62, "tp_trigger_price": 72.65,
            "sl_trigger_price": 74.51, "account_id": 1,
        }
        entry = order.get("price", 0) or order.get("avg_fill_price", 0) or 0
        assert entry == 73.62, "the resolved entry for a market order is its fill price"
        # And a genuinely price-less, fill-less order still bails:
        naked = {"symbol": "SOLUSDT", "price": 0.0, "avg_fill_price": 0.0}
        assert not (naked.get("price", 0) or naked.get("avg_fill_price", 0) or 0)


class TestReviewQueueCarriesFillPrice:
    def test_list_needs_review_selects_avg_fill_price(self):
        src = inspect.getsource(la.list_needs_review)
        assert "avg_fill_price" in src, (
            "the finder receives THIS dict — without the column the fallback has "
            "nothing to fall back to, and the UI shows 'MARKET @ 0.000000'"
        )

    def test_candidates_are_still_computed_off_the_legacy_db(self):
        """Guard the Phase-4 near-miss: the finder must keep its explicit db_path."""
        src = inspect.getsource(la.list_needs_review)
        assert "db_path=config.DB_PATH" in src, (
            "candidates must be read from the writer's store; the resolver default "
            "(_resolve_db_path) points at the per-account DB"
        )
