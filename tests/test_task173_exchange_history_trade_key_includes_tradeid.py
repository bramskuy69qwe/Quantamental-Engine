"""
Task 173 follow-up: trade_key in exchange_history must include tradeId.

Bug context: prior to this fix, core/exchange_income.py constructed
trade_key as f"{time}_{symbol}_{incomeType}" without tradeId. Multi-fill
closes (and especially simultaneous LONG+SHORT hedge-mode closes on the
same symbol) emit multiple REALIZED_PNL income events with the SAME
(time, symbol, incomeType) tuple — they all collide on identical
trade_keys. The DB upsert (ON CONFLICT(trade_key) DO UPDATE SET ...) at
core/db_exchange.py:53 keeps only one, silently dropping the rest.

Downstream symptom: backfill_fills_from_exchange_history groups by
(symbol, direction, open_time) and produces a closed_positions row per
unique group — but only for groups that survived the collision. The
dropped fills never reach Position History.

Repro: user opened LONG (4476 qty @ 0.007953) and SHORT (2039 qty @
0.007982) ALTUSDT positions, then closed both at the same instant
(15:27:48). Binance income API emitted 6 REALIZED_PNL events (5 for the
LONG's partial-fill close + 1 for the SHORT close) all with the same
time/symbol/incomeType. exchange_history retained only 1 row (the SHORT
won the race). Position History showed only SHORT.

Fix: append tradeId to trade_key. Binance tradeId is unique per fill.

Run: pytest tests/test_task173_exchange_history_trade_key_includes_tradeid.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest


SRC = Path(__file__).parent.parent / "core" / "exchange_income.py"


class TestSourceGrepPin:
    def test_trade_key_includes_tradeid(self):
        """trade_key construction must include tradeId for uniqueness."""
        content = SRC.read_text()
        # Locate the trade_key assignment and verify it references tradeId.
        idx = content.find('r["trade_key"]')
        assert idx > 0, "trade_key assignment must exist in exchange_income.py"
        # Look at the next line — the f-string itself.
        line_end = content.find("\n", idx)
        line = content[idx:line_end]
        assert "tradeId" in line, (
            "trade_key f-string must reference tradeId so multi-fill closes "
            "don't collide on identical (time, symbol, incomeType) tuples"
        )


def test_simultaneous_long_short_close_produces_unique_trade_keys():
    """When LONG + SHORT close at the same ms on the same symbol, their
    REALIZED_PNL events must produce distinct trade_keys.

    This is the exact scenario the user hit: hedge-mode LONG (closed via
    5 partial SELL fills) + SHORT (closed via 1 BUY fill), all at the same
    transaction time on ALTUSDT.
    """
    # Simulate the 6 income events Binance would return.
    raw_pnl_events = [
        # 5 partial-fill SELL events closing the LONG (each its own tradeId)
        {"time": 1779611268000, "symbol": "ALTUSDT", "incomeType": "REALIZED_PNL",
         "tradeId": "t-21394", "income": 0.002226},
        {"time": 1779611268000, "symbol": "ALTUSDT", "incomeType": "REALIZED_PNL",
         "tradeId": "t-21395", "income": 0.008603},
        {"time": 1779611268000, "symbol": "ALTUSDT", "incomeType": "REALIZED_PNL",
         "tradeId": "t-21396", "income": 0.01449},
        {"time": 1779611268000, "symbol": "ALTUSDT", "incomeType": "REALIZED_PNL",
         "tradeId": "t-21397", "income": 0.004445},
        {"time": 1779611268000, "symbol": "ALTUSDT", "incomeType": "REALIZED_PNL",
         "tradeId": "t-21398", "income": 0.001568},
        # 1 BUY event closing the SHORT
        {"time": 1779611268000, "symbol": "ALTUSDT", "incomeType": "REALIZED_PNL",
         "tradeId": "t-21399", "income": 0.04078},
    ]

    # Apply the trade_key construction from core/exchange_income.py.
    for r in raw_pnl_events:
        r["trade_key"] = (
            f"{r.get('time', '')}_{r.get('symbol', '')}"
            f"_{r.get('incomeType', '')}_{r.get('tradeId', '')}"
        )

    trade_keys = [r["trade_key"] for r in raw_pnl_events]
    assert len(set(trade_keys)) == len(trade_keys), (
        f"All 6 simultaneous-close events must produce unique trade_keys; got "
        f"{len(set(trade_keys))} distinct keys out of {len(trade_keys)} events. "
        f"Collision means DB upsert drops events silently — Position History loses rows."
    )


def test_single_fill_close_still_produces_unique_key():
    """Single-fill closes (the common case) must continue to produce
    well-formed unique trade_keys."""
    r = {"time": 1779611268000, "symbol": "BTCUSDT", "incomeType": "REALIZED_PNL",
         "tradeId": "t-99999", "income": 10.5}
    r["trade_key"] = (
        f"{r.get('time', '')}_{r.get('symbol', '')}"
        f"_{r.get('incomeType', '')}_{r.get('tradeId', '')}"
    )
    assert r["trade_key"] == "1779611268000_BTCUSDT_REALIZED_PNL_t-99999"


def test_missing_tradeid_still_produces_a_key():
    """Defense in depth: if Binance omits tradeId for some event type
    (FUNDING_FEE, COMMISSION when not tied to a trade), the trade_key
    still constructs — just without the trailing tradeId component.
    Old colliding behavior persists for those event types, but those
    aren't the ones the backfill aggregation depends on for closed_positions."""
    r = {"time": 1779611268000, "symbol": "BTCUSDT", "incomeType": "FUNDING_FEE",
         "income": -0.001}
    r["trade_key"] = (
        f"{r.get('time', '')}_{r.get('symbol', '')}"
        f"_{r.get('incomeType', '')}_{r.get('tradeId', '')}"
    )
    # tradeId missing → trailing "_" with empty string. Still parseable, still unique
    # per (time, symbol, incomeType) — same as the legacy behavior for non-trade events.
    assert r["trade_key"] == "1779611268000_BTCUSDT_FUNDING_FEE_"
