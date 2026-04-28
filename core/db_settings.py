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
            "SELECT id, name, exchange, market_type, is_active, created_at FROM accounts ORDER BY id ASC"
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
            "broker_account_id",
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

    async def set_active_account(self, account_id: int) -> None:
        """Set is_active=1 on new account, 0 on all others."""
        await self._conn.execute("UPDATE accounts SET is_active=0")
        await self._conn.execute("UPDATE accounts SET is_active=1 WHERE id=?", (account_id,))
        await self._conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES ('active_account_id', ?, datetime('now'))"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (str(account_id),),
        )
        await self._conn.commit()
