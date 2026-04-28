from __future__ import annotations

import logging
from typing import List

log = logging.getLogger("database")


class EquityMixin:
    """equity_cashflow domain methods."""

    async def clear_cashflow_events(self, account_id: int = 1) -> int:
        """Delete equity_cashflow rows for the given account. Returns count deleted."""
        async with self._conn.execute("DELETE FROM equity_cashflow WHERE account_id = ?", (account_id,)) as cur:
            count = cur.rowcount
        await self._conn.commit()
        log.info("Cleared %d cashflow events", count)
        return count

    async def insert_cashflow_events(self, records: List[tuple], account_id: int = 1) -> int:
        """
        Bulk-insert (ts_ms, amount) rows into equity_cashflow.
        Uses INSERT OR REPLACE so re-running a backfill is idempotent.
        Returns number of rows written.
        """
        inserted = 0
        for ts_ms, amount in records:
            try:
                await self._conn.execute(
                    "INSERT OR REPLACE INTO equity_cashflow (ts_ms, amount, account_id) VALUES (?, ?, ?)",
                    (int(ts_ms), float(amount), account_id),
                )
                inserted += 1
            except Exception as exc:
                log.debug("insert_cashflow_events row skip: %r", exc)
        if inserted:
            await self._conn.commit()
        return inserted
