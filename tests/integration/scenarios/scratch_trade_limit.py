"""Limit entry fills, SL hits immediately."""
from datetime import datetime, timedelta, timezone
from tests.integration.scenario import *

_now = datetime.now(timezone.utc)
_ts = lambda m: (_now - timedelta(minutes=m)).isoformat()

scenario = Scenario(
    name="scratch_trade_limit",
    description="Limit entry fills, SL fires immediately. SL slippage computed against parent stop_price.",
    events=[
        ScenarioEvent(t_ms=1000, type="calc_created", payload={
            "timestamp": _ts(30), "ticker": "ETHUSDT", "side": "BUY",
            "effective_entry": 3000.0, "tp_price": 3300.0, "sl_price": 2900.0,
            "calc_id": "calc-scratch",
        }),
        ScenarioEvent(t_ms=2000, type="order_persisted", payload={
            "exchange_order_id": "E-LIM", "symbol": "ETHUSDT", "side": "BUY",
            "order_type": "limit", "status": "new", "price": 3000,
            "quantity": 0.1, "exchange_position_id": "POS-E",
        }),
        ScenarioEvent(t_ms=2100, type="order_persisted", payload={
            "exchange_order_id": "TP-LIM", "symbol": "ETHUSDT", "side": "SELL",
            "order_type": "take_profit_market", "status": "new",
            "stop_price": 3300, "quantity": 0.1, "reduce_only": True,
            "exchange_position_id": "POS-E",
        }),
        ScenarioEvent(t_ms=2200, type="order_persisted", payload={
            "exchange_order_id": "SL-LIM", "symbol": "ETHUSDT", "side": "SELL",
            "order_type": "stop_market", "status": "new",
            "stop_price": 2900, "quantity": 0.1, "reduce_only": True,
            "exchange_position_id": "POS-E",
        }),
        ScenarioEvent(t_ms=3000, type="fill_received", payload={
            "exchange_fill_id": "F-ENTRY", "exchange_order_id": "E-LIM",
            "symbol": "ETHUSDT", "side": "BUY", "price": 3000.0,
            "quantity": 0.1, "timestamp_ms": 3000,
            "exchange_position_id": "POS-E",
        }),
        ScenarioEvent(t_ms=4000, type="fill_received", payload={
            "exchange_fill_id": "F-SL", "exchange_order_id": "SL-LIM",
            "symbol": "ETHUSDT", "side": "SELL", "price": 2895.0,
            "quantity": 0.1, "is_close": True, "timestamp_ms": 4000,
            "exchange_position_id": "POS-E",
        }),
    ],
    expected=ExpectedState(
        orders=[
            ExpectedOrder("E-LIM", calc_id="calc-scratch",
                          tp_trigger_price=3300.0, sl_trigger_price=2900.0),
        ],
        fills=[
            ExpectedFill("F-ENTRY", calc_id="calc-scratch", fill_type="entry",
                         slippage_actual=0.0, slippage_tolerance=0.0001),
            ExpectedFill("F-SL", fill_type="sl",
                         slippage_actual=(2895 - 2900) / 2900,
                         slippage_tolerance=0.0001),
        ],
    ),
)
