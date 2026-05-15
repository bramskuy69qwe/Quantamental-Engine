"""Limit order placed but never fills, gets canceled. calc_id still correlated."""
from datetime import datetime, timedelta, timezone
from tests.integration.scenario import *

_now = datetime.now(timezone.utc)
_ts = lambda m: (_now - timedelta(minutes=m)).isoformat()

scenario = Scenario(
    name="canceled_entry",
    description="Limit entry + TP/SL placed, then canceled. calc_id correlation succeeds on unfilled entry.",
    events=[
        ScenarioEvent(t_ms=1000, type="calc_created", payload={
            "timestamp": _ts(10), "ticker": "SOLUSDT", "side": "BUY",
            "effective_entry": 150.0, "tp_price": 165.0, "sl_price": 145.0,
            "calc_id": "calc-canc",
        }),
        ScenarioEvent(t_ms=2000, type="order_persisted", payload={
            "exchange_order_id": "E-CANC", "symbol": "SOLUSDT", "side": "BUY",
            "order_type": "limit", "status": "new", "price": 150.0,
            "quantity": 1, "exchange_position_id": "POS-C",
        }),
        ScenarioEvent(t_ms=2100, type="order_persisted", payload={
            "exchange_order_id": "TP-CANC", "symbol": "SOLUSDT", "side": "SELL",
            "order_type": "take_profit_market", "status": "new",
            "stop_price": 165, "quantity": 1, "reduce_only": True,
            "exchange_position_id": "POS-C",
        }),
        ScenarioEvent(t_ms=2200, type="order_persisted", payload={
            "exchange_order_id": "SL-CANC", "symbol": "SOLUSDT", "side": "SELL",
            "order_type": "stop_market", "status": "new",
            "stop_price": 145, "quantity": 1, "reduce_only": True,
            "exchange_position_id": "POS-C",
        }),
        ScenarioEvent(t_ms=5000, type="order_canceled", payload={
            "exchange_order_id": "E-CANC", "symbol": "SOLUSDT", "side": "BUY",
            "order_type": "limit", "status": "canceled", "price": 150.0,
            "exchange_position_id": "POS-C",
        }),
    ],
    expected=ExpectedState(
        orders=[
            ExpectedOrder("E-CANC", calc_id="calc-canc",
                          tp_trigger_price=165.0, sl_trigger_price=145.0),
        ],
    ),
)
