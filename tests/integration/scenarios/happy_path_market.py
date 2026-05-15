"""Market entry with TP+SL, normal slippage, hits TP."""
from datetime import datetime, timedelta, timezone
from tests.integration.scenario import *

_now = datetime.now(timezone.utc)
_ts = lambda m: (_now - timedelta(minutes=m)).isoformat()

scenario = Scenario(
    name="happy_path_market",
    description="Market entry fills, TP child placed, TP fills. Slippage computed.",
    events=[
        ScenarioEvent(t_ms=1000, type="calc_created", payload={
            "timestamp": _ts(60), "ticker": "BTCUSDT", "side": "BUY",
            "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
            "calc_id": "calc-happy",
        }),
        ScenarioEvent(t_ms=2000, type="order_persisted", payload={
            "exchange_order_id": "ENTRY-1", "symbol": "BTCUSDT", "side": "BUY",
            "order_type": "market", "status": "new", "price": 50000,
            "quantity": 0.01, "exchange_position_id": "POS-1",
        }),
        ScenarioEvent(t_ms=2500, type="order_persisted", payload={
            "exchange_order_id": "TP-1", "symbol": "BTCUSDT", "side": "SELL",
            "order_type": "take_profit_market", "status": "new",
            "stop_price": 55000, "quantity": 0.01, "reduce_only": True,
            "exchange_position_id": "POS-1",
        }),
        ScenarioEvent(t_ms=2600, type="order_persisted", payload={
            "exchange_order_id": "SL-1", "symbol": "BTCUSDT", "side": "SELL",
            "order_type": "stop_market", "status": "new",
            "stop_price": 48000, "quantity": 0.01, "reduce_only": True,
            "exchange_position_id": "POS-1",
        }),
        ScenarioEvent(t_ms=3000, type="fill_received", payload={
            "exchange_fill_id": "FILL-ENTRY", "exchange_order_id": "ENTRY-1",
            "symbol": "BTCUSDT", "side": "BUY", "price": 50050.0,
            "quantity": 0.01, "fee": 0.025, "timestamp_ms": 3000,
            "exchange_position_id": "POS-1",
        }),
        ScenarioEvent(t_ms=5000, type="fill_received", payload={
            "exchange_fill_id": "FILL-TP", "exchange_order_id": "TP-1",
            "symbol": "BTCUSDT", "side": "SELL", "price": 54980.0,
            "quantity": 0.01, "fee": 0.027, "is_close": True,
            "timestamp_ms": 5000, "exchange_position_id": "POS-1",
        }),
    ],
    expected=ExpectedState(
        orders=[
            ExpectedOrder("ENTRY-1", calc_id="*",
                          tp_trigger_price=55000.0, sl_trigger_price=48000.0),
        ],
        fills=[
            ExpectedFill("FILL-ENTRY", calc_id="*", fill_type="entry",
                         slippage_actual=0.001, slippage_tolerance=0.0001),
            ExpectedFill("FILL-TP", fill_type="tp",
                         slippage_actual=(54980 - 55000) / 55000,
                         slippage_tolerance=0.0001),
        ],
    ),
)
