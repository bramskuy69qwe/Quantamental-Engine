"""
ExchangeFactory — per-account CCXT instance cache.

Replaces the module-level singleton in exchange.py with a per-account
cache keyed by account_id.  The existing get_exchange() function in
exchange.py delegates here via account_registry.

Module-level singleton:
    from core.exchange_factory import exchange_factory
    ex = exchange_factory.get(account_id, api_key, api_secret, "binance", "future")
    exchange_factory.invalidate(account_id)    # call before account switch
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

import ccxt

import config

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
        cls = getattr(ccxt, exchange, ccxt.binance)
        ex = cls(params)
    return ex


class ExchangeFactory:
    """Cache of CCXT Exchange objects keyed by account_id."""

    def __init__(self) -> None:
        self._instances: Dict[int, ccxt.Exchange] = {}

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
        log.info("ExchangeFactory: invalidated account_id=%d", account_id)

    def invalidate_all(self) -> None:
        self._instances.clear()


# Module-level singleton
exchange_factory = ExchangeFactory()
