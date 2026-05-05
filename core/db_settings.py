from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("database")


class SettingsMixin:
    """settings + accounts domain methods."""

    async def get_setting(self, key: str) -> Optional[str]:
        """Return the value for key from the settings table, or None if not set."""
        async with self._conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        """Upsert a key-value pair into the settings table."""
        await self._conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value),
        )
        await self._conn.commit()

    async def get_all_accounts(self) -> List[Dict[str, Any]]:
        """Return all accounts (no decrypted secrets — just metadata)."""
        async with self._conn.execute(
            "SELECT id, name, exchange, market_type, is_active, created_at,"
            " broker_account_id, maker_fee, taker_fee, environment"
            " FROM accounts ORDER BY id ASC"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_account(self, account_id: int) -> Optional[Dict[str, Any]]:
        """Return full account row (including encrypted secrets) or None."""
        async with self._conn.execute(
            "SELECT * FROM accounts WHERE id=?", (account_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def insert_account(
        self,
        name: str,
        exchange: str,
        market_type: str,
        api_key_enc: str,
        api_secret_enc: str,
        broker_account_id: str = "",
    ) -> int:
        """Insert new account, return new id."""
        async with self._conn.execute(
            "INSERT INTO accounts"
            " (name, exchange, market_type, api_key_enc, api_secret_enc, is_active, broker_account_id)"
            " VALUES (?, ?, ?, ?, ?, 0, ?)",
            (name, exchange, market_type, api_key_enc, api_secret_enc, broker_account_id),
        ) as cur:
            new_id = cur.lastrowid
        await self._conn.commit()
        return new_id

    async def update_account(self, account_id: int, **kwargs) -> None:
        """Update arbitrary columns on accounts row."""
        allowed = {
            "name", "exchange", "market_type",
            "api_key_enc", "api_secret_enc", "is_active",
            "broker_account_id", "maker_fee", "taker_fee",
            "environment", "key_version",
        }
        cols = {k: v for k, v in kwargs.items() if k in allowed}
        if not cols:
            return
        set_clause = ", ".join(f"{k}=?" for k in cols)
        await self._conn.execute(
            f"UPDATE accounts SET {set_clause} WHERE id=?",
            list(cols.values()) + [account_id],
        )
        await self._conn.commit()

    async def delete_account(self, account_id: int) -> None:
        """Delete an account row by id."""
        await self._conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
        await self._conn.commit()

    # ── account_params ─────────────────────────────────────────────────────

    async def get_account_params(self, account_id: int) -> Dict[str, float]:
        """Return {key: value} dict of risk params for an account."""
        async with self._conn.execute(
            "SELECT key, value FROM account_params WHERE account_id=?", (account_id,)
        ) as cur:
            return {r["key"]: r["value"] for r in await cur.fetchall()}

    async def set_account_params(self, account_id: int, params: Dict[str, float]) -> None:
        """Upsert all key-value pairs for an account's risk params."""
        for key, value in params.items():
            await self._conn.execute(
                "INSERT INTO account_params (account_id, key, value) VALUES (?, ?, ?)"
                " ON CONFLICT(account_id, key) DO UPDATE SET value=excluded.value",
                (account_id, key, float(value)),
            )
        await self._conn.commit()

    async def set_account_param(self, account_id: int, key: str, value: float) -> None:
        """Upsert a single risk param for an account."""
        await self._conn.execute(
            "INSERT INTO account_params (account_id, key, value) VALUES (?, ?, ?)"
            " ON CONFLICT(account_id, key) DO UPDATE SET value=excluded.value",
            (account_id, key, float(value)),
        )
        await self._conn.commit()

    async def get_all_account_params(self) -> Dict[int, Dict[str, float]]:
        """Return {account_id: {key: value}} for all accounts."""
        result: Dict[int, Dict[str, float]] = {}
        async with self._conn.execute(
            "SELECT account_id, key, value FROM account_params ORDER BY account_id"
        ) as cur:
            for row in await cur.fetchall():
                result.setdefault(row["account_id"], {})[row["key"]] = row["value"]
        return result

    # ── connections ───────────────────────────────────────────────────────

    async def get_all_connections(self) -> List[Dict[str, Any]]:
        """Return all connections (including encrypted keys)."""
        async with self._conn.execute(
            "SELECT * FROM connections ORDER BY id ASC"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_connection(self, provider: str) -> Optional[Dict[str, Any]]:
        """Return a single connection row by provider name."""
        async with self._conn.execute(
            "SELECT * FROM connections WHERE provider=?", (provider,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def upsert_connection(
        self, provider: str, label: str, api_key_enc: str,
        extra_enc: str = "", is_active: int = 1,
    ) -> None:
        """Insert or update a connection."""
        await self._conn.execute(
            "INSERT INTO connections (provider, label, api_key_enc, extra_enc, is_active)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(provider) DO UPDATE SET"
            " label=excluded.label, api_key_enc=excluded.api_key_enc,"
            " extra_enc=excluded.extra_enc, is_active=excluded.is_active",
            (provider, label, api_key_enc, extra_enc, is_active),
        )
        await self._conn.commit()

    async def delete_connection(self, provider: str) -> None:
        """Delete a connection by provider name."""
        await self._conn.execute("DELETE FROM connections WHERE provider=?", (provider,))
        await self._conn.commit()

    async def count_account_params(self) -> int:
        """Return total row count in account_params table."""
        async with self._conn.execute("SELECT COUNT(*) FROM account_params") as cur:
            return (await cur.fetchone())[0]

    async def count_connections(self) -> int:
        """Return total row count in connections table."""
        async with self._conn.execute("SELECT COUNT(*) FROM connections") as cur:
            return (await cur.fetchone())[0]

    # ── active account ───────────────────────────────────────────────────

    async def set_active_account(self, account_id: int) -> None:
        """Set is_active=1 on new account, 0 on all others (atomic)."""
        await self._conn.execute("BEGIN")
        try:
            await self._conn.execute("UPDATE accounts SET is_active=0")
            await self._conn.execute("UPDATE accounts SET is_active=1 WHERE id=?", (account_id,))
            await self._conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES ('active_account_id', ?, datetime('now'))"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (str(account_id),),
            )
            await self._conn.commit()
        except Exception:
            await self._conn.execute("ROLLBACK")
            raise
