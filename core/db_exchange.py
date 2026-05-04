from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

log = logging.getLogger("database")


class ExchangeMixin:
    """exchange_history domain methods."""

    _EXCHANGE_HISTORY_SORT_COLS = {
        "time", "symbol", "income", "entry_price", "exit_price",
        "notional", "fee", "direction", "open_time", "qty", "mfe", "mae",
        "hold_ms",
    }

    async def upsert_exchange_history(self, rows: List[Dict], account_id: int = 1) -> None:
        """Upsert a batch of augmented Binance income rows keyed by trade_key."""
        if not rows:
            return
        normalized = [
            {
                "account_id":  account_id,
                "trade_key":  str(r.get("trade_key", "")),
                "time":       int(r.get("time", 0) or 0),
                "symbol":     str(r.get("symbol", "")),
                "incomeType": str(r.get("incomeType", "")),
                "income":     float(r.get("income", 0) or 0),
                "direction":  str(r.get("direction", "")),
                "entry_price": float(r.get("entry_price", 0) or 0),
                "exit_price":  float(r.get("exit_price", 0) or 0),
                "qty":         float(r.get("qty", 0) or 0),
                "notional":    float(r.get("notional", 0) or 0),
                "open_time":   int(r.get("open_time", 0) or 0),
                "fee":         float(r.get("fee", 0) or 0),
                "asset":       str(r.get("asset", "")),
            }
            for r in rows
            if r.get("trade_key")
        ]
        if not normalized:
            return
        try:
            await self._conn.executemany(
                """INSERT INTO exchange_history
                       (account_id, trade_key, time, symbol, income_type, income, direction,
                        entry_price, exit_price, qty, notional, open_time, fee, asset)
                   VALUES (:account_id, :trade_key, :time, :symbol, :incomeType, :income, :direction,
                           :entry_price, :exit_price, :qty, :notional, :open_time, :fee, :asset)
                   ON CONFLICT(trade_key) DO UPDATE SET
                     account_id  = excluded.account_id,
                     income      = excluded.income,
                     direction   = excluded.direction,
                     entry_price = excluded.entry_price,
                     exit_price  = excluded.exit_price,
                     qty         = excluded.qty,
                     notional    = excluded.notional,
                     open_time   = excluded.open_time,
                     fee         = excluded.fee""",
                normalized,
            )
            await self._conn.commit()
        except sqlite3.Error as exc:
            log.error("upsert_exchange_history failed: %r", exc)
            try:
                await self._conn.rollback()
            except Exception:
                pass
            raise

    async def update_exchange_mfe_mae(self, trade_key: str, mfe: float, mae: float) -> None:
        """Write accurate MFE/MAE for a closed trade (reconciler only)."""
        await self._conn.execute(
            "UPDATE exchange_history SET mfe=?, mae=? WHERE trade_key=?",
            (mfe, mae, trade_key),
        )
        await self._conn.commit()

    async def get_uncalculated_exchange_rows(self, symbol: str) -> List[Dict]:
        """Return exchange_history rows for symbol where mfe or mae is still 0 and open_time is known."""
        async with self._conn.execute(
            "SELECT * FROM exchange_history WHERE symbol=? AND (mfe=0 OR mae=0) AND open_time>0",
            (symbol,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def query_exchange_history(
        self, *,
        page: int = 1, per_page: int = 20,
        sort_by: str = "time", sort_dir: str = "DESC",
        search: str = "", date_from: str = "", date_to: str = "",
        tz_local=None,
        account_id: int = 1,
    ) -> tuple:
        """Paginated SQL query of exchange_history with search + date filters."""
        clauses: list = ["account_id = ?", "income_type != 'OPEN'"]
        params: list = [account_id]

        if search:
            clauses.append("symbol LIKE ?")
            params.append(f"%{search}%")
        if date_from and tz_local:
            from_ms = int(datetime.fromisoformat(date_from).replace(tzinfo=tz_local).timestamp() * 1000)
            clauses.append("time >= ?")
            params.append(from_ms)
        if date_to and tz_local:
            to_ms = int(datetime.fromisoformat(date_to).replace(tzinfo=tz_local).timestamp() * 1000)
            clauses.append("time <= ?")
            params.append(to_ms)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        col = sort_by if sort_by in self._EXCHANGE_HISTORY_SORT_COLS else "time"
        order = "DESC" if sort_dir.upper() == "DESC" else "ASC"
        # hold_ms is a computed alias — expand to the expression for ORDER BY
        order_expr = "(time - open_time)" if col == "hold_ms" else col

        async with self._conn.execute(
            f"SELECT COUNT(*) FROM exchange_history{where}", params
        ) as cur:
            total = (await cur.fetchone())[0]

        offset = (max(page, 1) - 1) * per_page
        async with self._conn.execute(
            f"SELECT *, (time - open_time) AS hold_ms"
            f" FROM exchange_history{where}"
            f" ORDER BY {order_expr} {order} LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows], total
