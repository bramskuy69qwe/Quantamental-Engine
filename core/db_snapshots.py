from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

log = logging.getLogger("database")


class SnapshotsMixin:
    """account_snapshots + position_changes domain methods."""

    async def get_last_account_state(self, account_id: int = 1) -> Optional[Dict[str, Any]]:
        """Return the most recent account_snapshots row for account_id, or None."""
        async with self._conn.execute(
            "SELECT * FROM account_snapshots WHERE account_id=? ORDER BY id DESC LIMIT 1",
            (account_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def insert_account_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Insert a full account_snapshots row from the given state dict."""
        try:
            await self._conn.execute(
                """INSERT INTO account_snapshots (
                    account_id, snapshot_ts, total_equity, balance_usdt, available_margin,
                    total_unrealized, total_realized, total_position_value,
                    total_margin_used, total_margin_ratio, daily_pnl, daily_pnl_percent,
                    bod_equity, sow_equity, max_total_equity, min_total_equity,
                    total_exposure, drawdown, total_weekly_pnl,
                    weekly_pnl_state, dd_state, open_positions, trigger_channel
                ) VALUES (
                    :account_id, :snapshot_ts, :total_equity, :balance_usdt, :available_margin,
                    :total_unrealized, :total_realized, :total_position_value,
                    :total_margin_used, :total_margin_ratio, :daily_pnl, :daily_pnl_percent,
                    :bod_equity, :sow_equity, :max_total_equity, :min_total_equity,
                    :total_exposure, :drawdown, :total_weekly_pnl,
                    :weekly_pnl_state, :dd_state, :open_positions, :trigger_channel
                )""",
                {"account_id": snapshot.get("account_id", 1), **snapshot},
            )
            await self._conn.commit()
        except sqlite3.Error as exc:
            log.error("insert_account_snapshot failed: %r", exc)
            try:
                await self._conn.rollback()
            except Exception:
                pass
            raise

    async def insert_position_changes(
        self, positions: List[Dict[str, Any]], trigger: str, account_id: int = 1
    ) -> None:
        if not positions:
            return
        ts = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                account_id,
                ts,
                p.get("ticker", ""),
                p.get("direction", ""),
                p.get("contract_amount", 0.0),
                p.get("average", 0.0),
                p.get("fair_price", 0.0),
                p.get("position_value_usdt", 0.0),
                p.get("individual_unrealized", 0.0),
                p.get("individual_margin_used", 0.0),
                p.get("sector", ""),
                trigger,
            )
            for p in positions
        ]
        try:
            await self._conn.executemany(
                """INSERT INTO position_changes (
                    account_id, snapshot_ts, ticker, direction, contract_amount, average,
                    fair_price, position_value_usdt, individual_unrealized,
                    individual_margin_used, sector, trigger_channel
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            await self._conn.commit()
        except sqlite3.Error as exc:
            log.error("insert_position_changes failed: %r", exc)
            try:
                await self._conn.rollback()
            except Exception:
                pass
            raise

    async def get_recent_snapshots(self, minutes: int = 5, account_id: int = 1) -> List[Dict[str, Any]]:
        """Return account_snapshots rows from the last N minutes, oldest first."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=minutes)
        ).isoformat()
        async with self._conn.execute(
            "SELECT * FROM account_snapshots WHERE account_id=? AND snapshot_ts >= ? ORDER BY snapshot_ts ASC",
            (account_id, cutoff),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def clear_backfill_snapshots(self, account_id: int = 1) -> int:
        """Delete synthetic exchange_backfill rows for the given account. Returns count deleted."""
        async with self._conn.execute(
            "DELETE FROM account_snapshots WHERE trigger_channel = 'exchange_backfill' AND account_id = ?",
            (account_id,),
        ) as cur:
            count = cur.rowcount
        await self._conn.commit()
        log.info("Cleared %d exchange_backfill snapshots", count)
        return count

    async def get_earliest_snapshot_ms(self, account_id: int = 1) -> Optional[int]:
        """Return epoch-milliseconds of the earliest account_snapshot for this account, or None."""
        async with self._conn.execute(
            "SELECT snapshot_ts FROM account_snapshots WHERE account_id=? ORDER BY snapshot_ts ASC LIMIT 1",
            (account_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        ts_str = str(row[0])
        try:
            if ts_str.endswith("Z"):
                ts_str = ts_str[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except Exception:
            return None

    async def insert_backfill_snapshots(
        self, records: List[tuple], before_ms: int, account_id: int = 1
    ) -> int:
        """
        Bulk-insert synthetic account_snapshots reconstructed from exchange income history.
        Only inserts rows with ts_ms < before_ms to avoid overlapping real snapshots.
        Returns number of rows inserted.
        """
        inserted = 0
        for ts_ms, equity in records:
            if ts_ms >= before_ms:
                continue
            dt_utc = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            snapshot_ts = dt_utc.isoformat()
            try:
                await self._conn.execute(
                    """INSERT INTO account_snapshots (
                        account_id, snapshot_ts, total_equity, balance_usdt, available_margin,
                        total_unrealized, total_realized, total_position_value,
                        total_margin_used, total_margin_ratio, daily_pnl, daily_pnl_percent,
                        bod_equity, sow_equity, max_total_equity, min_total_equity,
                        total_exposure, drawdown, total_weekly_pnl,
                        weekly_pnl_state, dd_state, open_positions, trigger_channel
                    ) VALUES (
                        ?, ?, ?, 0.0, 0.0,
                        0.0, 0.0, 0.0,
                        0.0, 0.0, 0.0, 0.0,
                        0.0, 0.0, 0.0, 0.0,
                        0.0, 0.0, 0.0,
                        '', '', 0, 'exchange_backfill'
                    )""",
                    (account_id, snapshot_ts, equity),
                )
                inserted += 1
            except Exception as exc:
                log.debug("insert_backfill_snapshots row skip: %r", exc)
        if inserted:
            await self._conn.commit()
        return inserted
