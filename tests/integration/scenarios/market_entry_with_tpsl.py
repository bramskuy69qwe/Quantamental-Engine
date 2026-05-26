"""Market entry with TP+SL attached. 6/6 correlation (spec §4.1).

Pre-P1.T1 this scenario was "entry wildcard" for market orders. Under
the new strict matcher entry IS evaluated for MARKET via fill price
against calc.effective_entry with the loose entry_tolerance_pct band
(default 0.25%). Fill price was loosened from 0.5060 (1.2% drift,
fails new criterion) to 0.5010 (0.2% drift, within tolerance).
"""
from datetime import datetime, timedelta, timezone
from tests.integration.scenario import *

_now = datetime.now(timezone.utc)
_ts = lambda m: (_now - timedelta(minutes=m)).isoformat()

scenario = Scenario(
    name="market_entry_with_tpsl",
    description="Market entry strict 6/6 correlation per spec §4.1.",
    events=[
        ScenarioEvent(t_ms=1000, type="calc_created", payload={
            "timestamp": _ts(5), "ticker": "XRPUSDT", "side": "BUY",
            "effective_entry": 0.5000, "tp_price": 0.5500, "sl_price": 0.4800,
            "calc_id": "calc-mkt-tpsl",
        }),
        ScenarioEvent(t_ms=2000, type="order_persisted", payload={
            "exchange_order_id": "MKT-1", "symbol": "XRPUSDT", "side": "BUY",
            "order_type": "market", "status": "new", "price": 0.5050,
            "quantity": 100, "exchange_position_id": "POS-MKT",
        }),
        ScenarioEvent(t_ms=2100, type="order_persisted", payload={
            "exchange_order_id": "TP-MKT", "symbol": "XRPUSDT", "side": "SELL",
            "order_type": "take_profit_market", "status": "new",
            "stop_price": 0.5500, "quantity": 100, "reduce_only": True,
            "exchange_position_id": "POS-MKT",
        }),
        ScenarioEvent(t_ms=2200, type="order_persisted", payload={
            "exchange_order_id": "SL-MKT", "symbol": "XRPUSDT", "side": "SELL",
            "order_type": "stop_market", "status": "new",
            "stop_price": 0.4800, "quantity": 100, "reduce_only": True,
            "exchange_position_id": "POS-MKT",
        }),
        ScenarioEvent(t_ms=3000, type="fill_received", payload={
            "exchange_fill_id": "F-MKT-E", "exchange_order_id": "MKT-1",
            "symbol": "XRPUSDT", "side": "BUY", "price": 0.5010,
            "quantity": 100, "timestamp_ms": 3000,
            "exchange_position_id": "POS-MKT",
        }),
    ],
    expected=ExpectedState(
        orders=[
            # Market order correlated via strict 6/6 (entry-vs-fill in tolerance)
            ExpectedOrder("MKT-1", calc_id="calc-mkt-tpsl",
                          tp_trigger_price=0.5500, sl_trigger_price=0.4800),
        ],
        fills=[
            # Entry slippage computed against pre_trade_log effective_entry
            ExpectedFill("F-MKT-E", calc_id="calc-mkt-tpsl", fill_type="entry",
                         slippage_actual=(0.5010 - 0.5000) / 0.5000,
                         slippage_tolerance=0.0001),
        ],
    ),
)
