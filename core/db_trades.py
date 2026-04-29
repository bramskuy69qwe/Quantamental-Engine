from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

log = logging.getLogger("database")


class TradesMixin:
    """pre_trade_log, execution_log, trade_history, position_notes domain methods."""

    _PRE_TRADE_SORT_COLS = {
        "timestamp", "ticker", "side", "average", "sl_price", "tp_price",
        "atr_c", "size", "notional", "est_r", "eligible", "model_name",
    }
    _EXECUTION_SORT_COLS = {
        "entry_timestamp", "ticker", "side", "entry_price_actual",
        "size_filled", "slippage", "order_type", "maker_fee", "latency_snapshot",
    }
    _TRADE_HISTORY_SORT_COLS = {
        "exit_timestamp", "ticker", "direction", "entry_price", "exit_price",
        "individual_realized", "individual_realized_r", "total_funding_fees",
        "total_fees", "slippage_exit", "holding_time",
    }

    async def _paginated_query(
        self,
        table: str,
        ts_col: str,
        allowed_sort: set,
        date_from: Optional[str],
        date_to: Optional[str],
        search: Optional[str],
        filters: Dict[str, Optional[str]],
        sort_by: str,
        sort_dir: str,
        page: int,
        per_page: int,
        account_id: int = 1,
    ) -> tuple:
        """Generic paginated, filtered, sorted query. Returns (rows, total)."""
        clauses: list = ["account_id = ?"]
        params: list = [account_id]

        if date_from:
            clauses.append(f"{ts_col} >= ?")
            params.append(date_from)
        if date_to:
            clauses.append(f"{ts_col} <= ?")
            params.append(date_to)
        if search:
            like = f"%{search}%"
            clauses.append("(ticker LIKE ?)")
            params.append(like)
        for col, val in filters.items():
            if val:
                clauses.append(f"{col} = ?")
                params.append(val)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        if sort_by not in allowed_sort:
            sort_by = ts_col
        if sort_dir not in ("ASC", "DESC"):
            sort_dir = "DESC"

        count_sql = f"SELECT COUNT(*) FROM {table}{where}"
        async with self._conn.execute(count_sql, params) as cur:
            total = (await cur.fetchone())[0]

        offset = (max(page, 1) - 1) * per_page
        data_sql = (
            f"SELECT * FROM {table}{where} "
            f"ORDER BY {sort_by} {sort_dir} "
            f"LIMIT ? OFFSET ?"
        )
        async with self._conn.execute(data_sql, params + [per_page, offset]) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows], total

    async def insert_pre_trade_log(self, row: Dict[str, Any]) -> None:
        """Insert a pre_trade_log row from a risk-calculator result dict."""
        try:
            await self._conn.execute(
                """INSERT INTO pre_trade_log (
                    account_id, timestamp, ticker, average, side, one_percent_depth, individual_risk,
                    tp_price, tp_amount_pct, tp_usdt, sl_price, sl_amount_pct, sl_usdt,
                    model_name, model_desc, risk_usdt, atr_c, atr_category,
                    est_slippage, effective_entry, size, notional,
                    est_profit, est_loss, est_r, est_exposure, eligible
                ) VALUES (
                    :account_id, :timestamp, :ticker, :average, :side, :one_percent_depth, :individual_risk,
                    :tp_price, :tp_amount_pct, :tp_usdt, :sl_price, :sl_amount_pct, :sl_usdt,
                    :model_name, :model_desc, :risk_usdt, :atr_c, :atr_category,
                    :est_slippage, :effective_entry, :size, :notional,
                    :est_profit, :est_loss, :est_r, :est_exposure, :eligible
                )""",
                {
                    "account_id":        row.get("account_id", 1),
                    "timestamp":         row.get("timestamp", datetime.now(timezone.utc).isoformat()),
                    "ticker":            row.get("ticker", ""),
                    "average":           row.get("average", 0),
                    "side":              row.get("side", ""),
                    "one_percent_depth": row.get("one_percent_depth", 0),
                    "individual_risk":   row.get("individual_risk_pct", row.get("individual_risk", 0)),
                    "tp_price":          row.get("tp_price", 0),
                    "tp_amount_pct":     row.get("tp_amount_pct", 0),
                    "tp_usdt":           row.get("tp_usdt", 0),
                    "sl_price":          row.get("sl_price", 0),
                    "sl_amount_pct":     row.get("sl_amount_pct", 0),
                    "sl_usdt":           row.get("sl_usdt", 0),
                    "model_name":        row.get("model_name", ""),
                    "model_desc":        row.get("model_desc", ""),
                    "risk_usdt":         row.get("risk_usdt", 0),
                    "atr_c":             str(row.get("atr_c", "")),
                    "atr_category":      row.get("atr_category", ""),
                    "est_slippage":      row.get("est_slippage", 0),
                    "effective_entry":   row.get("effective_entry", 0),
                    "size":              row.get("size", 0),
                    "notional":          row.get("notional", 0),
                    "est_profit":        row.get("est_profit", 0),
                    "est_loss":          row.get("est_loss", 0),
                    "est_r":             row.get("est_r", 0),
                    "est_exposure":      row.get("est_exposure", 0),
                    "eligible":          1 if row.get("eligible") else 0,
                },
            )
            await self._conn.commit()
        except sqlite3.Error as exc:
            log.error("insert_pre_trade_log failed: %r", exc)
            try:
                await self._conn.rollback()
            except Exception:
                pass
            raise

    async def insert_execution_log(self, row: Dict[str, Any]) -> None:
        """Insert an execution_log row for a manually-logged fill."""
        try:
            await self._conn.execute(
                """INSERT INTO execution_log (
                    account_id, entry_timestamp, ticker, side, entry_price_actual, size_filled,
                    slippage, order_type, maker_fee, taker_fee,
                    latency_snapshot, orderbook_depth_snapshot, source_terminal
                ) VALUES (
                    :account_id, :entry_timestamp, :ticker, :side, :entry_price_actual, :size_filled,
                    :slippage, :order_type, :maker_fee, :taker_fee,
                    :latency_snapshot, :orderbook_depth_snapshot, :source_terminal
                )""",
                {
                    "account_id":               row.get("account_id", 1),
                    "entry_timestamp":          row.get("entry_timestamp", datetime.now(timezone.utc).isoformat()),
                    "ticker":                   row.get("ticker", ""),
                    "side":                     row.get("side", ""),
                    "entry_price_actual":       row.get("entry_price_actual", 0),
                    "size_filled":              row.get("size_filled", 0),
                    "slippage":                 row.get("slippage", 0),
                    "order_type":               row.get("order_type", "limit"),
                    "maker_fee":                row.get("maker_fee", 0),
                    "taker_fee":                row.get("taker_fee", 0),
                    "latency_snapshot":         row.get("latency_snapshot", 0),
                    "orderbook_depth_snapshot": str(row.get("orderbook_depth_snapshot", "")),
                    "source_terminal":          row.get("source_terminal", "manual"),
                },
            )
            await self._conn.commit()
        except sqlite3.Error as exc:
            log.error("insert_execution_log failed: %r", exc)
            try:
                await self._conn.rollback()
            except Exception:
                pass
            raise

    async def insert_trade_history(self, row: Dict[str, Any]) -> None:
        """Insert a trade_history row for a manually-logged closed trade."""
        try:
            await self._conn.execute(
                """INSERT INTO trade_history (
                    account_id, exit_timestamp, ticker, direction, entry_price, exit_price,
                    individual_realized, individual_realized_r, total_funding_fees,
                    total_fees, slippage_exit, holding_time, notes
                ) VALUES (
                    :account_id, :exit_timestamp, :ticker, :direction, :entry_price, :exit_price,
                    :individual_realized, :individual_realized_r, :total_funding_fees,
                    :total_fees, :slippage_exit, :holding_time, :notes
                )""",
                {
                    "account_id":            row.get("account_id", 1),
                    "exit_timestamp":        row.get("exit_timestamp", datetime.now(timezone.utc).isoformat()),
                    "ticker":                row.get("ticker", ""),
                    "direction":             row.get("direction", ""),
                    "entry_price":           row.get("entry_price", 0),
                    "exit_price":            row.get("exit_price", 0),
                    "individual_realized":   row.get("individual_realized", 0),
                    "individual_realized_r": row.get("individual_realized_r", 0),
                    "total_funding_fees":    row.get("total_funding_fees", 0),
                    "total_fees":            row.get("total_fees", 0),
                    "slippage_exit":         row.get("slippage_exit", 0),
                    "holding_time":          str(row.get("holding_time", "")),
                    "notes":                 row.get("notes", ""),
                },
            )
            await self._conn.commit()
        except sqlite3.Error as exc:
            log.error("insert_trade_history failed: %r", exc)
            try:
                await self._conn.rollback()
            except Exception:
                pass
            raise

    async def get_all_pre_trade_log(self, days: int = 365, account_id: int = 1) -> List[Dict[str, Any]]:
        """Return pre_trade_log rows within the last N days, newest first."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        async with self._conn.execute(
            "SELECT * FROM pre_trade_log WHERE account_id=? AND timestamp >= ? ORDER BY timestamp DESC",
            (account_id, cutoff),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_all_execution_log(self, days: int = 365, account_id: int = 1) -> List[Dict[str, Any]]:
        """Return execution_log rows within the last N days, newest first."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        async with self._conn.execute(
            "SELECT * FROM execution_log WHERE account_id=? AND entry_timestamp >= ? ORDER BY entry_timestamp DESC",
            (account_id, cutoff),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_all_trade_history(self, days: int = 365, account_id: int = 1) -> List[Dict[str, Any]]:
        """Return trade_history rows within the last N days, newest first."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        async with self._conn.execute(
            "SELECT * FROM trade_history WHERE account_id=? AND exit_timestamp >= ? ORDER BY exit_timestamp DESC",
            (account_id, cutoff),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def query_pre_trade_log(
        self, *, date_from: Optional[str] = None, date_to: Optional[str] = None,
        search: Optional[str] = None, ticker: Optional[str] = None,
        side: Optional[str] = None, sort_by: str = "timestamp",
        sort_dir: str = "DESC", page: int = 1, per_page: int = 20,
        account_id: int = 1,
    ) -> tuple:
        """Return paginated, filtered pre_trade_log rows as (rows, total)."""
        return await self._paginated_query(
            "pre_trade_log", "timestamp", self._PRE_TRADE_SORT_COLS,
            date_from, date_to, search, {"ticker": ticker, "side": side},
            sort_by, sort_dir, page, per_page, account_id,
        )

    async def query_execution_log(
        self, *, date_from: Optional[str] = None, date_to: Optional[str] = None,
        search: Optional[str] = None, ticker: Optional[str] = None,
        side: Optional[str] = None, sort_by: str = "entry_timestamp",
        sort_dir: str = "DESC", page: int = 1, per_page: int = 20,
        account_id: int = 1,
    ) -> tuple:
        """Return paginated, filtered execution_log rows as (rows, total)."""
        return await self._paginated_query(
            "execution_log", "entry_timestamp", self._EXECUTION_SORT_COLS,
            date_from, date_to, search, {"ticker": ticker, "side": side},
            sort_by, sort_dir, page, per_page, account_id,
        )

    async def query_trade_history(
        self, *, date_from: Optional[str] = None, date_to: Optional[str] = None,
        search: Optional[str] = None, ticker: Optional[str] = None,
        direction: Optional[str] = None, sort_by: str = "exit_timestamp",
        sort_dir: str = "DESC", page: int = 1, per_page: int = 20,
        account_id: int = 1,
    ) -> tuple:
        """Return paginated, filtered trade_history rows as (rows, total)."""
        return await self._paginated_query(
            "trade_history", "exit_timestamp", self._TRADE_HISTORY_SORT_COLS,
            date_from, date_to, search, {"ticker": ticker, "direction": direction},
            sort_by, sort_dir, page, per_page, account_id,
        )

    async def update_pre_trade_notes(self, row_id: int, notes: str) -> None:
        """Update the notes field on a single pre_trade_log row."""
        await self._conn.execute(
            "UPDATE pre_trade_log SET notes = ? WHERE id = ?", (notes, row_id)
        )
        await self._conn.commit()

    async def update_trade_history_notes(self, row_id: int, notes: str) -> None:
        await self._conn.execute(
            "UPDATE trade_history SET notes = ? WHERE id = ?", (notes, row_id)
        )
        await self._conn.commit()

    async def get_position_notes(self, trade_keys: List[str]) -> Dict[str, str]:
        """Return {trade_key: notes} for the given keys (only rows that exist)."""
        if not trade_keys:
            return {}
        placeholders = ",".join("?" * len(trade_keys))
        async with self._conn.execute(
            f"SELECT trade_key, notes FROM position_history_notes WHERE trade_key IN ({placeholders})",
            trade_keys,
        ) as cur:
            rows = await cur.fetchall()
        return {r["trade_key"]: r["notes"] for r in rows}

    async def upsert_position_note(self, trade_key: str, notes: str) -> None:
        """Insert or replace the note for a trade_key in position_history_notes."""
        await self._conn.execute(
            "INSERT INTO position_history_notes (trade_key, notes) VALUES (?, ?)"
            " ON CONFLICT(trade_key) DO UPDATE SET notes = excluded.notes",
            (trade_key, notes),
        )
        await self._conn.commit()
