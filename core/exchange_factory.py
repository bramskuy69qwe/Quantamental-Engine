"""
ExchangeFactory — per-account CCXT instance cache + adapter resolution.

Replaces the module-level singleton in exchange.py with a per-account
cache keyed by account_id.  The existing get_exchange() function in
exchange.py delegates here via account_registry.

Module-level singleton:
    from core.exchange_factory import exchange_factory
    ex = exchange_factory.get(account_id, api_key, api_secret, "binance", "future")
    exchange_factory.invalidate(account_id)    # call before account switch

Adapter API (new):
    from core.exchange_factory import exchange_factory
    adapter = exchange_factory.get_adapter(account_id, api_key, api_secret, "binance", "future")
    ws_adapter = exchange_factory.get_ws_adapter(account_id, "binance", "future")
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

import ccxt

import config
from core.adapters import get_adapter, get_ws_adapter as _get_ws, map_market_type
from core.adapters.protocols import ExchangeAdapter, WSAdapter

log = logging.getLogger("exchange_factory")


def _make_ccxt_instance(
    api_key: str,
    api_secret: str,
    exchange: str,
    market_type: str,
) -> ccxt.Exchange:
    """Create a new CCXT exchange instance from credentials."""
    params = {
        "apiKey":  api_key,
        "secret":  api_secret,
        "options": {
            "defaultType": market_type,
            # Skip fetch_currencies() during load_markets() — that call hits
            # api.binance.com/sapi/v1/capital/config/getall (Spot API, unreachable
            # when only fapi.binance.com is accessible via proxy).
            "fetchCurrencies": False,
        },
        "enableRateLimit": True,
    }
    # ccxt sync uses requests — proxy is set via the "proxies" key.
    if config.HTTP_PROXY:
        params["proxies"] = {"http": config.HTTP_PROXY, "https": config.HTTP_PROXY}
        log.info("Using proxy for CCXT sync: %s", config.HTTP_PROXY)

    if exchange == "binance" and market_type == "future":
        # binanceusdm routes ALL endpoints (including load_markets / fetch_ohlcv)
        # through fapi.binance.com — never touching api.binance.com (Spot).
        # ccxt.binance({defaultType: "future"}) still calls api.binance.com/api/v3/exchangeInfo
        # during load_markets(), which fails when the Spot API is geo-restricted.
        ex = ccxt.binanceusdm(params)
    elif exchange == "binance":
        ex = ccxt.binance(params)
    else:
        cls = getattr(ccxt, exchange, None)
        if cls is None:
            raise ValueError(
                f"Unknown exchange '{exchange}'. No CCXT class found. "
                f"Check the exchange name in your account settings."
            )
        ex = cls(params)
    return ex


class ExchangeFactory:
    """Cache of CCXT Exchange objects and adapters keyed by account_id."""

    def __init__(self) -> None:
        self._instances: Dict[int, ccxt.Exchange] = {}
        self._adapters: Dict[int, ExchangeAdapter] = {}
        self._ws_adapters: Dict[int, WSAdapter] = {}

    def get(
        self,
        account_id: int,
        api_key: str,
        api_secret: str,
        exchange: str = "binance",
        market_type: str = "future",
    ) -> ccxt.Exchange:
        """Return cached CCXT instance, creating it on first call."""
        if account_id not in self._instances:
            self._instances[account_id] = _make_ccxt_instance(
                api_key, api_secret, exchange, market_type
            )
            log.info(
                "ExchangeFactory: created CCXT instance account_id=%d exchange=%s",
                account_id, exchange,
            )
        return self._instances[account_id]

    def invalidate(self, account_id: int) -> None:
        """Remove cached instance (call before account switch or deletion)."""
        self._instances.pop(account_id, None)
        self._adapters.pop(account_id, None)
        self._ws_adapters.pop(account_id, None)
        log.info("ExchangeFactory: invalidated account_id=%d", account_id)

    def invalidate_all(self) -> None:
        self._instances.clear()
        self._adapters.clear()
        self._ws_adapters.clear()

    # ── Adapter API ──────────────────────────────────────────────────────────

    def get_adapter(
        self,
        account_id: int,
        api_key: str,
        api_secret: str,
        exchange: str = "binance",
        market_type: str = "future",
    ) -> ExchangeAdapter:
        """Return cached adapter instance, creating on first call."""
        if account_id not in self._adapters:
            adapter_market = map_market_type(exchange, market_type)
            self._adapters[account_id] = get_adapter(
                exchange, adapter_market,
                api_key=api_key,
                api_secret=api_secret,
                proxy=config.HTTP_PROXY,
            )
            log.info(
                "ExchangeFactory: created adapter account_id=%d exchange=%s market=%s",
                account_id, exchange, adapter_market,
            )
        return self._adapters[account_id]

    def get_ws_adapter(
        self,
        account_id: int,
        exchange: str = "binance",
        market_type: str = "future",
    ) -> WSAdapter:
        """Return cached WS adapter instance."""
        if account_id not in self._ws_adapters:
            adapter_market = map_market_type(exchange, market_type)
            self._ws_adapters[account_id] = _get_ws(exchange, adapter_market)
            log.info(
                "ExchangeFactory: created WS adapter account_id=%d exchange=%s",
                account_id, exchange,
            )
        return self._ws_adapters[account_id]


# Module-level singleton
exchange_factory = ExchangeFactory()
