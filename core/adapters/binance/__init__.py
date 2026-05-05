"""
Binance USD-M Futures adapter package.

Importing this module auto-registers the Binance adapters in the registry.
"""
from core.adapters.binance.rest_adapter import BinanceUSDMAdapter  # noqa: F401
from core.adapters.binance.ws_adapter import BinanceWSAdapter      # noqa: F401
