"""TP modified mid-trade, fill uses modified trigger for slippage."""
from datetime import datetime, timedelta, timezone
from tests.integration.scenario import *

_now = datetime.now(timezone.utc)
_ts = lambda m: (_now - timedelta(minutes=m)).isoformat()

scenario = Scenario(
    name="tp_pulled_in",
    description="TP modified from 0.1430 to 0.13558. Fill at 0.14014. Slippage uses modified trigger.",
    events=[
        ScenarioEvent(t_ms=1000, type="calc_created", payload={
            "timestamp": _ts(60), "ticker": "DOGEUSDT", "side": "BUY",
            "effective_entry": 0.13000, "tp_price": 0.14300, "sl_price": 0.12500,
            "calc_id": "calc-tp-mod",
        }),
        ScenarioEvent(t_ms=2000, type="order_persisted", payload={
            "exchange_order_id": "E-DOGE", "symbol": "DOGEUSDT", "side": "BUY",
            "order_type": "limit", "status": "new", "price": 0.13000,
            "quantity": 100, "exchange_position_id": "POS-D",
        }),
        ScenarioEvent(t_ms=2100, type="order_persisted", payload={
            "exchange_order_id": "TP-DOGE", "symbol": "DOGEUSDT", "side": "SELL",
            "order_type": "take_profit_market", "status": "new",
            "stop_price": 0.14300, "quantity": 100, "reduce_only": True,
            "exchange_position_id": "POS-D",
        }),
        ScenarioEvent(t_ms=2200, type="order_persisted", payload={
            "exchange_order_id": "SL-DOGE", "symbol": "DOGEUSDT", "side": "SELL",
            "order_type": "stop_market", "status": "new",
            "stop_price": 0.12500, "quantity": 100, "reduce_only": True,
            "exchange_position_id": "POS-D",
        }),
        ScenarioEvent(t_ms=3000, type="fill_received", payload={
            "exchange_fill_id": "F-DOGE-E", "exchange_order_id": "E-DOGE",
            "symbol": "DOGEUSDT", "side": "BUY", "price": 0.13000,
            "quantity": 100, "timestamp_ms": 3000,
            "exchange_position_id": "POS-D",
        }),
        # TP modified: pulled in from 0.14300 to 0.13558
        ScenarioEvent(t_ms=4000, type="order_modified", payload={
            "exchange_order_id": "TP-DOGE", "symbol": "DOGEUSDT", "side": "SELL",
            "order_type": "take_profit_market", "status": "new",
            "stop_price": 0.13558, "quantity": 100, "reduce_only": True,
            "exchange_position_id": "POS-D",
        }),
        # TP fills at 0.14014 — slippage computed vs MODIFIED 0.13558
        ScenarioEvent(t_ms=5000, type="fill_received", payload={
            "exchange_fill_id": "F-DOGE-TP", "exchange_order_id": "TP-DOGE",
            "symbol": "DOGEUSDT", "side": "SELL", "price": 0.14014,
            "quantity": 100, "is_close": True, "timestamp_ms": 5000,
            "exchange_position_id": "POS-D",
        }),
    ],
    expected=ExpectedState(
        fills=[
            ExpectedFill("F-DOGE-E", calc_id="calc-tp-mod", fill_type="entry",
                         slippage_actual=0.0, slippage_tolerance=0.0001),
            # Critical: slippage vs MODIFIED 0.13558, not original 0.14300
            ExpectedFill("F-DOGE-TP", fill_type="tp",
                         slippage_actual=(0.14014 - 0.13558) / 0.13558,
                         slippage_tolerance=0.0001),
        ],
    ),
)
