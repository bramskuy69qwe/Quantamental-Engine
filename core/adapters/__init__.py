"""
Exchange adapter layer — public API.

Usage:
    from core.adapters import get_adapter, get_ws_adapter, to_position_info

    adapter = get_adapter("binance", "linear_perpetual", api_key=..., api_secret=...)
    account = await adapter.fetch_account()
    positions = await adapter.fetch_positions()

    ws = get_ws_adapter("binance", "linear_perpetual")
    url = ws.build_user_stream_url(listen_key)
"""
from __future__ import annotations

from typing import Optional

from core.adapters.protocols import (  # noqa: F401
    ExchangeAdapter,
    WSAdapter,
    NormalizedAccount,
    NormalizedPosition,
    NormalizedOrder,
    NormalizedTrade,
    NormalizedIncome,
    NormalizedFundingRate,
    WSEventType,
    SupportsListenKey,
    SupportsFundingRates,
    SupportsOpenInterest,
)
from core.adapters.registry import (  # noqa: F401
    get_rest_adapter,
    get_ws_adapter,
    list_registered,
)

# Import exchange packages to trigger registration via decorators
import core.adapters.binance  # noqa: F401
import core.adapters.bybit    # noqa: F401


def get_adapter(
    exchange_id: str,
    market_type: str,
    api_key: str = "",
    api_secret: str = "",
    proxy: str = "",
) -> ExchangeAdapter:
    """Convenience wrapper around registry lookup with standard kwargs."""
    return get_rest_adapter(
        exchange_id, market_type,
        api_key=api_key, api_secret=api_secret, proxy=proxy,
    )


# ── Conversion helpers ───────────────────────────────────────────────────────

def to_position_info(np: NormalizedPosition, sector: str = "") -> "PositionInfo":
    """Convert adapter NormalizedPosition to app_state PositionInfo.

    Bridges the adapter output to the existing 30+ consumers that read
    app_state.positions as List[PositionInfo].
    """
    from core.state import PositionInfo  # late import: avoid circular

    return PositionInfo(
        position_id=np.position_id,
        ticker=np.symbol,
        direction=np.side,
        contract_amount=np.size,
        contract_size=np.contract_size,
        position_value_usdt=np.notional,
        position_value_asset=np.size * np.contract_size,
        average=np.entry_price,
        fair_price=np.mark_price,
        liquidation_price=np.liquidation_price,
        individual_margin_used=np.initial_margin,
        individual_unrealized=np.unrealized_pnl,
        sector=sector,
    )


def map_market_type(exchange: str, legacy_type: str) -> str:
    """Map DB market_type values to adapter registry keys.

    DB stores: "future", "spot"
    Adapters register as: "linear_perpetual", "spot", "inverse_perpetual"
    """
    if legacy_type == "future":
        return "linear_perpetual"
    return legacy_type
