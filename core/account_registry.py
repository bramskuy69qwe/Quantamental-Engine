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
from typing import Dict, List, Optional, Any

log = logging.getLogger("account_registry")


class AccountRegistry:
    """Thread-safe cache of accounts keyed by account_id."""

    def __init__(self) -> None:
        self._cache: Dict[int, Dict[str, Any]] = {}   # account_id → full creds dict
        self._active_id: int = 1
        self._lock = asyncio.Lock()

    # ── Startup ───────────────────────────────────────────────────────────────

    async def load_all(self) -> None:
        """Read all accounts from DB, decrypt credentials, populate cache."""
        from core.database import db
        from core.crypto import decrypt

        rows = await db.get_all_accounts()   # metadata only (no secrets)

        # Determine active_id from settings
        active_str = await db.get_setting("active_account_id")
        try:
            active_id = int(active_str or "1")
        except ValueError:
            active_id = 1

        async with self._lock:
            self._cache.clear()
            for meta in rows:
                acct_id = meta["id"]
                full = await db.get_account(acct_id)   # includes encrypted secrets
                if full is None:
                    continue
                api_key    = decrypt(full.get("api_key_enc", ""))
                api_secret = decrypt(full.get("api_secret_enc", ""))
                self._cache[acct_id] = {
                    "id":          acct_id,
                    "name":        full["name"],
                    "exchange":    full["exchange"],
                    "market_type": full["market_type"],
                    "api_key":     api_key,
                    "api_secret":  api_secret,
                    "is_active":   full.get("is_active", 0),
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
        from core.database import db
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
    ) -> int:
        from core.database import db
        from core.crypto import encrypt

        key_enc = encrypt(api_key)
        sec_enc = encrypt(api_secret)
        new_id = await db.insert_account(name, exchange, market_type, key_enc, sec_enc)
        async with self._lock:
            self._cache[new_id] = {
                "id":          new_id,
                "name":        name,
                "exchange":    exchange,
                "market_type": market_type,
                "api_key":     api_key,
                "api_secret":  api_secret,
                "is_active":   0,
            }
        log.info("AccountRegistry: added account id=%d name=%r", new_id, name)
        return new_id

    async def update_account(
        self,
        account_id: int,
        name: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ) -> None:
        from core.database import db
        from core.crypto import encrypt

        kwargs: Dict[str, Any] = {}
        if name is not None:
            kwargs["name"] = name
        if api_key is not None:
            kwargs["api_key_enc"] = encrypt(api_key)
        if api_secret is not None:
            kwargs["api_secret_enc"] = encrypt(api_secret)
        if kwargs:
            await db.update_account(account_id, **kwargs)

        async with self._lock:
            if account_id in self._cache:
                if name is not None:
                    self._cache[account_id]["name"] = name
                if api_key is not None:
                    self._cache[account_id]["api_key"] = api_key
                if api_secret is not None:
                    self._cache[account_id]["api_secret"] = api_secret

    async def delete_account(self, account_id: int) -> None:
        from core.database import db
        await db.delete_account(account_id)
        async with self._lock:
            self._cache.pop(account_id, None)

    async def list_accounts(self) -> List[Dict[str, Any]]:
        """Return metadata list (no secrets) for UI dropdowns."""
        async with self._lock:
            return [
                {
                    "id":          v["id"],
                    "name":        v["name"],
                    "exchange":    v["exchange"],
                    "market_type": v["market_type"],
                    "is_active":   v["is_active"],
                }
                for v in self._cache.values()
            ]

    def list_accounts_sync(self) -> List[Dict[str, Any]]:
        """Synchronous version for _ctx() template helper."""
        return [
            {
                "id":          v["id"],
                "name":        v["name"],
                "exchange":    v["exchange"],
                "market_type": v["market_type"],
                "is_active":   v["is_active"],
            }
            for v in self._cache.values()
        ]

    async def test_connection(self, account_id: int) -> Dict[str, Any]:
        """Test API key by making a lightweight REST call. Returns latency or error."""
        import time
        from core.exchange_factory import exchange_factory

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
                await loop.run_in_executor(pool, ex.fetch_time)
                latency_ms = round((time.monotonic() - t0) * 1000, 1)
            return {"ok": True, "latency_ms": latency_ms}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


# Module-level singleton
account_registry = AccountRegistry()
