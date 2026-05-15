"""SL modified closer (risk-reducing). Asserts sl_modified event."""
from datetime import datetime, timedelta, timezone
from tests.integration.scenario import *

_now = datetime.now(timezone.utc)
_ts = lambda m: (_now - timedelta(minutes=m)).isoformat()

scenario = Scenario(
    name="sl_moved_closer",
    description="Long position, SL moved from 49000 to 49500 (risk-reducing).",
    events=[
        ScenarioEvent(t_ms=1000, type="calc_created", payload={
            "timestamp": _ts(30), "ticker": "BTCUSDT", "side": "BUY",
            "effective_entry": 50000.0, "tp_price": 52000.0, "sl_price": 49000.0,
            "calc_id": "calc-sl-mv",
        }),
        ScenarioEvent(t_ms=2000, type="order_persisted", payload={
            "exchange_order_id": "E-SLM", "symbol": "BTCUSDT", "side": "BUY",
            "order_type": "limit", "status": "new", "price": 50000,
            "quantity": 0.01, "exchange_position_id": "POS-SLM",
        }),
        ScenarioEvent(t_ms=2100, type="order_persisted", payload={
            "exchange_order_id": "SL-SLM", "symbol": "BTCUSDT", "side": "SELL",
            "order_type": "stop_market", "status": "new",
            "stop_price": 49000, "quantity": 0.01, "reduce_only": True,
            "exchange_position_id": "POS-SLM",
        }),
        ScenarioEvent(t_ms=2200, type="order_persisted", payload={
            "exchange_order_id": "TP-SLM", "symbol": "BTCUSDT", "side": "SELL",
            "order_type": "take_profit_market", "status": "new",
            "stop_price": 52000, "quantity": 0.01, "reduce_only": True,
            "exchange_position_id": "POS-SLM",
        }),
        ScenarioEvent(t_ms=3000, type="fill_received", payload={
            "exchange_fill_id": "F-SLM-E", "exchange_order_id": "E-SLM",
            "symbol": "BTCUSDT", "side": "BUY", "price": 50000.0,
            "quantity": 0.01, "timestamp_ms": 3000,
            "exchange_position_id": "POS-SLM",
        }),
        # SL modified: 49000 → 49500 (closer to entry = risk-reducing)
        ScenarioEvent(t_ms=4000, type="order_modified", payload={
            "exchange_order_id": "SL-SLM", "symbol": "BTCUSDT", "side": "SELL",
            "order_type": "stop_market", "status": "new",
            "stop_price": 49500, "quantity": 0.01, "reduce_only": True,
            "exchange_position_id": "POS-SLM",
        }),
    ],
    expected=ExpectedState(
        # calc_id=None: SL modification changed sl_trigger_price from 49000→49500,
        # breaking triple-match against pre_trade_log (sl_price=49000). This is
        # correct — modification alters the trigger context.
        orders=[
            ExpectedOrder("E-SLM", calc_id=None,
                          tp_trigger_price=52000.0, sl_trigger_price=49500.0),
        ],
        fills=[
            ExpectedFill("F-SLM-E", fill_type="entry"),
        ],
    ),
)
