"""
ConnectionsManager — in-memory cache of 3rd-party data provider API keys.

Stores encrypted credentials in the `connections` table and provides
decrypted keys at runtime via a DB-first, .env-fallback chain.

Module-level singleton:
    from core.connections import connections_manager
    await connections_manager.load_all()
    key = connections_manager.get_sync("fred")
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import config
from core.database import db
from core.crypto import decrypt, encrypt, mask_key
from core.audit import log_event as _audit

log = logging.getLogger("connections")


class ConnectionsManager:
    """Cache of 3rd-party API keys keyed by provider name."""

    def __init__(self) -> None:
        self._cache: Dict[str, Dict[str, Any]] = {}  # provider → {label, api_key, extra, is_active}
        self._lock = asyncio.Lock()

    async def load_all(self) -> None:
        """Read all connections from DB, decrypt keys, populate cache."""
        rows = await db.get_all_connections()
        async with self._lock:
            self._cache.clear()
            for row in rows:
                provider = row["provider"]
                api_key = decrypt(row.get("api_key_enc", ""))
                extra = decrypt(row.get("extra_enc", "")) if row.get("extra_enc") else ""
                self._cache[provider] = {
                    "provider":  provider,
                    "label":     row["label"],
                    "api_key":   api_key,
                    "extra":     extra,
                    "is_active": row.get("is_active", 1),
                }
        log.info("ConnectionsManager loaded %d connection(s)", len(self._cache))

    async def get(self, provider: str) -> Optional[str]:
        """Return decrypted API key for a provider, or None."""
        async with self._lock:
            entry = self._cache.get(provider)
        if entry and entry.get("is_active") and entry.get("api_key"):
            return entry["api_key"]
        return None

    def get_sync(self, provider: str) -> Optional[str]:
        """Synchronous accessor for config.py fallback chain."""
        entry = self._cache.get(provider)
        if entry and entry.get("is_active") and entry.get("api_key"):
            return entry["api_key"]
        return None

    async def upsert(
        self, provider: str, label: str, api_key: str, extra: str = "",
    ) -> None:
        """Add or update a connection (encrypts before storing)."""
        api_key_enc = encrypt(api_key)
        extra_enc = encrypt(extra) if extra else ""
        await db.upsert_connection(provider, label, api_key_enc, extra_enc)
        async with self._lock:
            self._cache[provider] = {
                "provider":  provider,
                "label":     label,
                "api_key":   api_key,
                "extra":     extra,
                "is_active": 1,
            }
        log.info("Connection upserted: %s", provider)
        _audit("upsert", "connection", provider)

    async def delete(self, provider: str) -> None:
        """Remove a connection."""
        await db.delete_connection(provider)
        async with self._lock:
            self._cache.pop(provider, None)
        log.info("Connection deleted: %s", provider)
        _audit("delete", "connection", provider)

    async def test(self, provider: str) -> Dict[str, Any]:
        """Test a connection with 10s timeout. Returns {status, msg}."""
        async with self._lock:
            entry = self._cache.get(provider)
        if not entry or not entry.get("api_key"):
            return {"status": "error", "msg": "No API key configured"}

        api_key = entry["api_key"]
        try:
            result = await asyncio.wait_for(
                self._test_provider(provider, api_key),
                timeout=10.0,
            )
            return result
        except asyncio.TimeoutError:
            return {"status": "error", "msg": "Connection timed out (10s)"}
        except Exception as e:
            return {"status": "error", "msg": str(e)}

    async def _test_provider(self, provider: str, api_key: str) -> Dict[str, Any]:
        """Provider-specific health check."""
        import httpx

        if provider == "fred":
            url = "https://api.stlouisfed.org/fred/series"
            params = {"series_id": "DGS10", "api_key": api_key, "file_type": "json"}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    return {"status": "ok", "msg": "FRED API connected"}
                return {"status": "error", "msg": f"FRED returned HTTP {resp.status_code}"}

        elif provider == "finnhub":
            url = "https://finnhub.io/api/v1/stock/market-status?exchange=US"
            headers = {"X-Finnhub-Token": api_key}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    return {"status": "ok", "msg": "Finnhub API connected"}
                return {"status": "error", "msg": f"Finnhub returned HTTP {resp.status_code}"}

        elif provider == "coingecko":
            url = "https://api.coingecko.com/api/v3/ping"
            headers = {"x-cg-demo-api-key": api_key} if api_key else {}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    return {"status": "ok", "msg": "CoinGecko API connected"}
                return {"status": "error", "msg": f"CoinGecko returned HTTP {resp.status_code}"}

        elif provider == "binance_market_data":
            # Test connectivity by fetching a single public funding rate
            url = "https://fapi.binance.com/fapi/v1/fundingRate"
            params = {"symbol": "BTCUSDT", "limit": 1}
            headers = {"X-MBX-APIKEY": api_key} if api_key else {}
            proxy = config.HTTP_PROXY if config.HTTP_PROXY else None
            async with httpx.AsyncClient(timeout=10, proxy=proxy) as client:
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code == 200:
                    return {"status": "ok", "msg": "Binance Futures API connected"}
                return {"status": "error", "msg": f"Binance returned HTTP {resp.status_code}"}

        elif provider == "bwe_news":
            # Test WS connectivity with a quick connect + disconnect
            import websockets
            ws_url = api_key or config.BWE_NEWS_WS_URL
            try:
                async with websockets.connect(
                    ws_url, ping_interval=None, ping_timeout=None,
                    additional_headers={"Origin": "https://bwenews-api.bwe-ws.com"},
                ) as ws:
                    await ws.send("ping")
                    resp_msg = await asyncio.wait_for(ws.recv(), timeout=5)
                    if "pong" in resp_msg.lower():
                        return {"status": "ok", "msg": "BWE News WS connected"}
                    return {"status": "ok", "msg": f"BWE WS connected (got: {resp_msg[:30]})"}
            except Exception as e:
                return {"status": "error", "msg": f"BWE WS failed: {e}"}

        return {"status": "error", "msg": f"Unknown provider: {provider}"}

    def list_connections(self) -> List[Dict[str, Any]]:
        """Return metadata list for UI. Never exposes full keys."""
        return [
            {
                "provider":     v["provider"],
                "label":        v["label"],
                "api_key_hint": mask_key(v.get("api_key", "")),
                "is_active":    v.get("is_active", 1),
                "has_key":      bool(v.get("api_key")),
            }
            for v in self._cache.values()
        ]

    def list_connections_sync(self) -> List[Dict[str, Any]]:
        """Synchronous version for template context."""
        return self.list_connections()


# Known providers shown by default in UI (even if not yet configured)
KNOWN_PROVIDERS = [
    {"provider": "binance_market_data", "label": "Binance Market Data (OI/Funding)"},
    {"provider": "bwe_news",            "label": "BWE News (Crypto)"},
    {"provider": "fred",                "label": "Federal Reserve (FRED)"},
    {"provider": "finnhub",             "label": "Finnhub"},
    {"provider": "coingecko",           "label": "CoinGecko"},
]

# Module-level singleton
connections_manager = ConnectionsManager()
