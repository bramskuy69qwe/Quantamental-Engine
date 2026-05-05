"""
AccountRegistry — in-memory cache of account credentials loaded from the DB.

Provides the active account's decrypted API key/secret to any module that
calls get_exchange().  All DB access is async; a sync wrapper is provided
for the CCXT call path which runs inside ThreadPoolExecutor.

Module-level singleton:
    from core.account_registry import account_registry
    await account_registry.load_all()          # call once in lifespan startup
    creds = await account_registry.get_active()
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from core.database import db
from core.crypto import decrypt, encrypt, safe_exchange_error
from core.exchange_factory import exchange_factory
from core.audit import log_event as _audit

log = logging.getLogger("account_registry")


class AccountRegistry:
    """Thread-safe cache of accounts keyed by account_id."""

    def __init__(self) -> None:
        self._cache: Dict[int, Dict[str, Any]] = {}   # account_id → full creds dict
        self._active_id: int = 1
        self._lock = asyncio.Lock()

    # ── Startup ───────────────────────────────────────────────────────────────

    async def load_all(self) -> None:
        """Read all accounts from DB, decrypt credentials, load params, populate cache."""
        from core.state import DEFAULT_PARAMS

        rows = await db.get_all_accounts()   # metadata only (no secrets)

        # Determine active_id from settings
        active_str = await db.get_setting("active_account_id")
        try:
            active_id = int(active_str or "1")
        except ValueError:
            active_id = 1

        # Load all account params in one query
        all_params = await db.get_all_account_params()

        async with self._lock:
            self._cache.clear()
            for meta in rows:
                acct_id = meta["id"]
                full = await db.get_account(acct_id)   # includes encrypted secrets
                if full is None:
                    continue
                api_key    = decrypt(full.get("api_key_enc", ""))
                api_secret = decrypt(full.get("api_secret_enc", ""))

                # Per-account params: from DB, or seed defaults
                params = all_params.get(acct_id)
                if not params:
                    params = DEFAULT_PARAMS.copy()
                    await db.set_account_params(acct_id, params)

                self._cache[acct_id] = {
                    "id":                acct_id,
                    "name":              full["name"],
                    "exchange":          full["exchange"],
                    "market_type":       full["market_type"],
                    "api_key":           api_key,
                    "api_secret":        api_secret,
                    "is_active":         full.get("is_active", 0),
                    "broker_account_id": full.get("broker_account_id") or "",
                    "maker_fee":         full.get("maker_fee", 0.0002),
                    "taker_fee":         full.get("taker_fee", 0.0005),
                    "environment":       full.get("environment", "live"),
                    "params":            params,
                }
            if active_id in self._cache:
                self._active_id = active_id
            else:
                fallback = next(iter(self._cache), None)
                if fallback is not None:
                    log.warning(
                        "AccountRegistry: saved active_id=%d not found in cache — "
                        "falling back to account_id=%d",
                        active_id, fallback,
                    )
                    self._active_id = fallback
                else:
                    log.warning(
                        "AccountRegistry: no accounts loaded — active_id stays at %d "
                        "(get_active_sync will return empty dict until accounts are added)",
                        self._active_id,
                    )

        log.info(
            "AccountRegistry loaded %d account(s); active_id=%d",
            len(self._cache), self._active_id,
        )

    # ── Active account ────────────────────────────────────────────────────────

    async def get_active(self) -> Dict[str, Any]:
        async with self._lock:
            return dict(self._cache.get(self._active_id, {}))

    def get_active_sync(self) -> Dict[str, Any]:
        """Synchronous accessor for use inside ThreadPoolExecutor (CCXT)."""
        return dict(self._cache.get(self._active_id, {}))

    @property
    def active_id(self) -> int:
        return self._active_id

    async def set_active(self, account_id: int) -> None:
        """Mark account as active in DB + cache."""
        await db.set_active_account(account_id)
        async with self._lock:
            self._active_id = account_id
            # Refresh is_active flags in cache
            for aid, creds in self._cache.items():
                creds["is_active"] = 1 if aid == account_id else 0

    # ── CRUD ──────────────────────────────────────────────────────────────────

    async def add_account(
        self,
        name: str,
        exchange: str,
        market_type: str,
        api_key: str,
        api_secret: str,
        broker_account_id: str = "",
        environment: str = "live",
        params_template: Optional[Dict[str, float]] = None,
    ) -> int:
        from core.state import DEFAULT_PARAMS
        import config as _cfg

        key_enc = encrypt(api_key)
        sec_enc = encrypt(api_secret)
        new_id = await db.insert_account(
            name, exchange, market_type, key_enc, sec_enc,
            broker_account_id=broker_account_id,
        )
        # Set environment
        if environment != "live":
            await db.update_account(new_id, environment=environment)

        # Per-account params: from template or defaults
        params = dict(params_template) if params_template else DEFAULT_PARAMS.copy()
        await db.set_account_params(new_id, params)

        async with self._lock:
            self._cache[new_id] = {
                "id":                new_id,
                "name":              name,
                "exchange":          exchange,
                "market_type":       market_type,
                "api_key":           api_key,
                "api_secret":        api_secret,
                "is_active":         0,
                "broker_account_id": broker_account_id,
                "maker_fee":         _cfg.MAKER_FEE,
                "taker_fee":         _cfg.TAKER_FEE,
                "environment":       environment,
                "params":            params,
            }
        log.info("AccountRegistry: added account id=%d name=%r env=%s", new_id, name, environment)
        _audit("add", "account", name, f"id={new_id} env={environment}")
        return new_id

    async def update_account(
        self,
        account_id: int,
        name: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        broker_account_id: Optional[str] = None,
    ) -> None:
        kwargs: Dict[str, Any] = {}
        if name is not None:
            kwargs["name"] = name
        if api_key is not None:
            kwargs["api_key_enc"] = encrypt(api_key)
        if api_secret is not None:
            kwargs["api_secret_enc"] = encrypt(api_secret)
        if broker_account_id is not None:
            kwargs["broker_account_id"] = broker_account_id
        if kwargs:
            await db.update_account(account_id, **kwargs)

        async with self._lock:
            if account_id in self._cache:
                acct_name = self._cache[account_id].get("name", str(account_id))
                if name is not None:
                    self._cache[account_id]["name"] = name
                if api_key is not None:
                    self._cache[account_id]["api_key"] = api_key
                if api_secret is not None:
                    self._cache[account_id]["api_secret"] = api_secret
                if broker_account_id is not None:
                    self._cache[account_id]["broker_account_id"] = broker_account_id
        detail = "credentials_changed" if (api_key or api_secret) else "metadata_updated"
        acct_name = name or self._cache.get(account_id, {}).get("name", str(account_id))
        _audit("update", "account", acct_name, detail)

    async def delete_account(self, account_id: int) -> None:
        async with self._lock:
            acct_name = self._cache.get(account_id, {}).get("name", str(account_id))
        await db.delete_account(account_id)
        async with self._lock:
            self._cache.pop(account_id, None)
        _audit("delete", "account", acct_name)

    def _account_meta(self, v: Dict[str, Any]) -> Dict[str, Any]:
        """Extract non-secret metadata from a cache entry."""
        return {
            "id":                v["id"],
            "name":              v["name"],
            "exchange":          v["exchange"],
            "market_type":       v["market_type"],
            "is_active":         v["is_active"],
            "broker_account_id": v.get("broker_account_id", ""),
            "maker_fee":         v.get("maker_fee", 0.0002),
            "taker_fee":         v.get("taker_fee", 0.0005),
            "environment":       v.get("environment", "live"),
        }

    async def list_accounts(self) -> List[Dict[str, Any]]:
        """Return metadata list (no secrets) for UI dropdowns."""
        async with self._lock:
            return [self._account_meta(v) for v in self._cache.values()]

    def list_accounts_sync(self) -> List[Dict[str, Any]]:
        """Synchronous version for _ctx() template helper."""
        return [self._account_meta(v) for v in self._cache.values()]

    def find_by_broker_id(self, broker_id: str) -> Optional[Dict[str, Any]]:
        """Find account by broker_account_id (used for Quantower fill routing)."""
        if not broker_id:
            return None
        for v in self._cache.values():
            if v.get("broker_account_id") == broker_id:
                return {
                    "id":      v["id"],
                    "name":    v["name"],
                    "exchange": v["exchange"],
                }
        return None

    # ── Per-account params ──────────────────────────────────────────────────

    def get_account_params(self, account_id: int) -> Dict[str, Any]:
        """Return risk params for an account (from cache)."""
        entry = self._cache.get(account_id)
        if not entry:
            from core.state import DEFAULT_PARAMS
            return DEFAULT_PARAMS.copy()
        return dict(entry.get("params", {}))

    async def update_account_params(self, account_id: int, params: Dict[str, float]) -> None:
        """Update risk params in DB and cache."""
        await db.set_account_params(account_id, params)
        async with self._lock:
            if account_id in self._cache:
                self._cache[account_id]["params"] = dict(params)

    # ── Per-account fees ─────────────────────────────────────────────────

    def get_account_fees(self, account_id: int) -> tuple:
        """Return (maker_fee, taker_fee) for an account."""
        entry = self._cache.get(account_id)
        if not entry:
            import config as _cfg
            return (_cfg.MAKER_FEE, _cfg.TAKER_FEE)
        return (entry.get("maker_fee", 0.0002), entry.get("taker_fee", 0.0005))

    async def update_account_fees(self, account_id: int, maker: float, taker: float) -> None:
        """Update fees in DB and cache."""
        await db.update_account(account_id, maker_fee=maker, taker_fee=taker)
        async with self._lock:
            if account_id in self._cache:
                self._cache[account_id]["maker_fee"] = maker
                self._cache[account_id]["taker_fee"] = taker

    # ── Connection test ──────────────────────────────────────────────────

    async def test_connection(self, account_id: int, fetch_fees: bool = True) -> Dict[str, Any]:
        """Test API key with 30s timeout. Optionally auto-fetch fee tier."""
        async with self._lock:
            creds = self._cache.get(account_id)
        if not creds:
            return {"ok": False, "error": "Account not found"}

        try:
            ex = exchange_factory.get(
                creds["id"], creds["api_key"], creds["api_secret"],
                creds["exchange"], creds["market_type"],
            )
            loop = asyncio.get_event_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                t0 = time.monotonic()
                await asyncio.wait_for(
                    loop.run_in_executor(pool, ex.fetch_time),
                    timeout=30.0,
                )
                latency_ms = round((time.monotonic() - t0) * 1000, 1)

            result: Dict[str, Any] = {"ok": True, "latency_ms": latency_ms}

            # Auto-fetch fees if requested
            if fetch_fees:
                fees = await self._fetch_fees(ex, account_id)
                if fees:
                    result["fees_updated"] = True
                    result["maker_fee"] = fees[0]
                    result["taker_fee"] = fees[1]

            return result
        except asyncio.TimeoutError:
            return {"ok": False, "error": "Connection timed out (30s)"}
        except Exception as exc:
            return {"ok": False, "error": safe_exchange_error(exc)}

    async def _fetch_fees(self, ex: Any, account_id: int) -> Optional[tuple]:
        """Try to fetch trading fees from exchange. Returns (maker, taker) or None."""
        try:
            loop = asyncio.get_event_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fees = await asyncio.wait_for(
                    loop.run_in_executor(pool, ex.fetch_trading_fees),
                    timeout=30.0,
                )
            # CCXT returns {symbol: {maker, taker}}; pick first or default pair
            if isinstance(fees, dict):
                # Try to find a common pair, or take first entry
                for sym in ("BTC/USDT:USDT", "BTC/USDT", "BTCUSDT"):
                    if sym in fees:
                        maker = fees[sym].get("maker", 0)
                        taker = fees[sym].get("taker", 0)
                        if maker > 0 or taker > 0:
                            await self.update_account_fees(account_id, maker, taker)
                            return (maker, taker)
                # Fallback: first entry with nonzero fees
                for sym, data in fees.items():
                    maker = data.get("maker", 0)
                    taker = data.get("taker", 0)
                    if maker > 0 or taker > 0:
                        await self.update_account_fees(account_id, maker, taker)
                        return (maker, taker)
        except (asyncio.TimeoutError, Exception) as e:
            log.warning("Fee fetch failed for account %d: %s", account_id, safe_exchange_error(e))
        return None


# Module-level singleton
account_registry = AccountRegistry()
