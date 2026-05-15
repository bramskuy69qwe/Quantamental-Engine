"""
OrdersMixin — write, read, and utility methods for orders / fills / closed_positions.

All queries operate on the 3 tables created in v2.2.2.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("database")


class OrdersMixin:
    """Domain methods for the orders, fills, and closed_positions tables."""

    # ── Allowed sort columns (whitelist to prevent SQL injection) ────────────

    _ORDERS_SORT_COLS = {
        "updated_at_ms", "created_at_ms", "symbol", "side", "order_type",
        "quantity", "price", "stop_price", "status", "filled_qty",
    }
    _FILLS_SORT_COLS = {
        "timestamp_ms", "symbol", "side", "price", "quantity", "fee",
        "realized_pnl", "role", "direction",
    }
    _CLOSED_POS_SORT_COLS = {
        "exit_time_ms", "entry_time_ms", "symbol", "direction", "quantity",
        "entry_price", "exit_price", "realized_pnl", "net_pnl", "total_fees",
        "hold_time_ms", "exit_reason", "mfe", "mae",
    }

    # ── Write methods ───────────────────────────────────────────────────────

    async def upsert_order_batch(self, rows: List[Dict[str, Any]]) -> None:
        """Batch upsert orders in a single transaction."""
        if not rows:
            return
        now_ms = int(time.time() * 1000)
        sql = """
            INSERT INTO orders (
                account_id, exchange_order_id, terminal_order_id, client_order_id,
                symbol, side, order_type, status, price, stop_price,
                quantity, filled_qty, avg_fill_price, reduce_only,
                time_in_force, position_side, exchange_position_id,
                terminal_position_id, source, created_at_ms, updated_at_ms,
                last_seen_ms
            ) VALUES (
                :account_id, :exchange_order_id, :terminal_order_id, :client_order_id,
                :symbol, :side, :order_type, :status, :price, :stop_price,
                :quantity, :filled_qty, :avg_fill_price, :reduce_only,
                :time_in_force, :position_side, :exchange_position_id,
                :terminal_position_id, :source, :created_at_ms, :updated_at_ms,
                :last_seen_ms
            )
            ON CONFLICT(account_id, exchange_order_id) DO UPDATE SET
                terminal_order_id   = excluded.terminal_order_id,
                client_order_id     = excluded.client_order_id,
                status              = excluded.status,
                price               = excluded.price,
                stop_price          = excluded.stop_price,
                quantity            = excluded.quantity,
                filled_qty          = excluded.filled_qty,
                avg_fill_price      = excluded.avg_fill_price,
                order_type          = excluded.order_type,
                reduce_only         = excluded.reduce_only,
                time_in_force       = excluded.time_in_force,
                position_side       = excluded.position_side,
                exchange_position_id = excluded.exchange_position_id,
                updated_at_ms       = excluded.updated_at_ms,
                last_seen_ms        = excluded.last_seen_ms
            WHERE excluded.updated_at_ms >= orders.updated_at_ms
               OR orders.updated_at_ms IS NULL
        """
        try:
            async with self._conn.cursor() as cur:
                for row in rows:
                    await cur.execute(sql, {
                        "account_id":           row.get("account_id", 1),
                        "exchange_order_id":    row.get("exchange_order_id"),
                        "terminal_order_id":    row.get("terminal_order_id", ""),
                        "client_order_id":      row.get("client_order_id", ""),
                        "symbol":               row.get("symbol", ""),
                        "side":                 row.get("side", ""),
                        "order_type":           row.get("order_type", ""),
                        "status":               row.get("status", "new"),
                        "price":                row.get("price", 0),
                        "stop_price":           row.get("stop_price", 0),
                        "quantity":             row.get("quantity", 0),
                        "filled_qty":           row.get("filled_qty", 0),
                        "avg_fill_price":       row.get("avg_fill_price", 0),
                        "reduce_only":          int(row.get("reduce_only", False)),
                        "time_in_force":        row.get("time_in_force", ""),
                        "position_side":        row.get("position_side", ""),
                        "exchange_position_id": row.get("exchange_position_id", ""),
                        "terminal_position_id": row.get("terminal_position_id", ""),
                        "source":               row.get("source", ""),
                        "created_at_ms":        row.get("created_at_ms", 0),
                        "updated_at_ms":        row.get("updated_at_ms", now_ms),
                        "last_seen_ms":         now_ms,
                    })
            await self._conn.commit()
        except Exception:
            log.exception("upsert_order_batch failed")

    async def upsert_fill(self, row: Dict[str, Any]) -> None:
        """Insert or update a single fill (deduped by exchange_fill_id)."""
        sql = """
            INSERT INTO fills (
                account_id, exchange_fill_id, terminal_fill_id, exchange_order_id,
                symbol, side, direction, price, quantity, fee, fee_asset,
                exchange_position_id, terminal_position_id, is_close,
                realized_pnl, role, source, timestamp_ms
            ) VALUES (
                :account_id, :exchange_fill_id, :terminal_fill_id, :exchange_order_id,
                :symbol, :side, :direction, :price, :quantity, :fee, :fee_asset,
                :exchange_position_id, :terminal_position_id, :is_close,
                :realized_pnl, :role, :source, :timestamp_ms
            )
            ON CONFLICT(account_id, exchange_fill_id) DO UPDATE SET
                terminal_fill_id     = excluded.terminal_fill_id,
                terminal_position_id = excluded.terminal_position_id,
                price                = excluded.price,
                quantity             = excluded.quantity,
                fee                  = excluded.fee,
                fee_asset            = excluded.fee_asset,
                role                 = excluded.role,
                realized_pnl         = excluded.realized_pnl,
                timestamp_ms         = excluded.timestamp_ms
        """
        try:
            await self._conn.execute(sql, {
                "account_id":           row.get("account_id", 1),
                "exchange_fill_id":     row.get("exchange_fill_id"),
                "terminal_fill_id":     row.get("terminal_fill_id", ""),
                "exchange_order_id":    row.get("exchange_order_id", ""),
                "symbol":               row.get("symbol", ""),
                "side":                 row.get("side", ""),
                "direction":            row.get("direction", ""),
                "price":                row.get("price", 0),
                "quantity":             row.get("quantity", 0),
                "fee":                  row.get("fee", 0),
                "fee_asset":            row.get("fee_asset", "USDT"),
                "exchange_position_id": row.get("exchange_position_id", ""),
                "terminal_position_id": row.get("terminal_position_id", ""),
                "is_close":             int(row.get("is_close", False)),
                "realized_pnl":         row.get("realized_pnl", 0),
                "role":                 row.get("role", ""),
                "source":               row.get("source", ""),
                "timestamp_ms":         row.get("timestamp_ms", 0),
            })
            await self._conn.commit()
        except Exception:
            log.exception("upsert_fill failed")

    async def insert_closed_position(self, row: Dict[str, Any]) -> None:
        """Insert a closed_positions row (deduped by position_id + exit_time).

        Uses REPLACE so a re-computed close row (e.g. after late fill) wins
        over the earlier version rather than being silently dropped.
        """
        sql = """
            INSERT OR REPLACE INTO closed_positions (
                account_id, exchange_position_id, terminal_position_id,
                symbol, direction, quantity, entry_price, exit_price,
                entry_time_ms, exit_time_ms, realized_pnl, total_fees,
                net_pnl, funding_fees, mfe, mae, hold_time_ms,
                exit_reason, model_name, notes,
                shortfall_entry, shortfall_exit, source, calc_id
            ) VALUES (
                :account_id, :exchange_position_id, :terminal_position_id,
                :symbol, :direction, :quantity, :entry_price, :exit_price,
                :entry_time_ms, :exit_time_ms, :realized_pnl, :total_fees,
                :net_pnl, :funding_fees, :mfe, :mae, :hold_time_ms,
                :exit_reason, :model_name, :notes,
                :shortfall_entry, :shortfall_exit, :source, :calc_id
            )
        """
        try:
            await self._conn.execute(sql, {
                "account_id":           row.get("account_id", 1),
                "exchange_position_id": row.get("exchange_position_id", ""),
                "terminal_position_id": row.get("terminal_position_id", ""),
                "symbol":               row.get("symbol", ""),
                "direction":            row.get("direction", ""),
                "quantity":             row.get("quantity", 0),
                "entry_price":          row.get("entry_price", 0),
                "exit_price":           row.get("exit_price", 0),
                "entry_time_ms":        row.get("entry_time_ms", 0),
                "exit_time_ms":         row.get("exit_time_ms", 0),
                "realized_pnl":         row.get("realized_pnl", 0),
                "total_fees":           row.get("total_fees", 0),
                "net_pnl":              row.get("net_pnl", 0),
                "funding_fees":         row.get("funding_fees", 0),
                "mfe":                  row.get("mfe", 0),
                "mae":                  row.get("mae", 0),
                "hold_time_ms":         row.get("hold_time_ms", 0),
                "exit_reason":          row.get("exit_reason", ""),
                "model_name":           row.get("model_name", ""),
                "notes":                row.get("notes", ""),
                "shortfall_entry":      row.get("shortfall_entry", 0),
                "shortfall_exit":       row.get("shortfall_exit", 0),
                "source":               row.get("source", ""),
                "calc_id":              row.get("calc_id"),
            })
            await self._conn.commit()
        except Exception:
            log.exception("insert_closed_position failed")

    async def update_order_from_fill(
        self, exchange_order_id: str, fill: Dict[str, Any]
    ) -> None:
        """Best-effort update of parent order's filled_qty/avg_fill_price from a fill."""
        if not exchange_order_id:
            return
        now_ms = int(time.time() * 1000)
        try:
            # avg_fill_price must be computed BEFORE filled_qty is incremented,
            # so we compute it first and set filled_qty second.
            await self._conn.execute(
                """UPDATE orders SET
                    avg_fill_price = CASE
                        WHEN filled_qty = 0 THEN :price
                        ELSE (avg_fill_price * filled_qty + :price * :qty)
                             / (filled_qty + :qty)
                    END,
                    filled_qty     = filled_qty + :qty,
                    updated_at_ms  = :now_ms
                WHERE exchange_order_id = :oid AND account_id = :aid""",
                {
                    "qty":    fill.get("quantity", 0),
                    "price":  fill.get("price", 0),
                    "now_ms": now_ms,
                    "oid":    exchange_order_id,
                    "aid":    fill.get("account_id", 1),
                },
            )
            await self._conn.commit()
        except Exception:
            log.warning("update_order_from_fill: order %s not found", exchange_order_id)

    async def upsert_fill_and_update_order(
        self, row: Dict[str, Any], exchange_order_id: str = "",
    ) -> None:
        """Upsert fill + update parent order in a SINGLE commit.

        Replaces the old pattern of upsert_fill() + update_order_from_fill()
        which did 2 separate commits per fill event.
        """
        fill_sql = """
            INSERT INTO fills (
                account_id, exchange_fill_id, terminal_fill_id, exchange_order_id,
                symbol, side, direction, price, quantity, fee, fee_asset,
                exchange_position_id, terminal_position_id, is_close,
                realized_pnl, role, source, timestamp_ms
            ) VALUES (
                :account_id, :exchange_fill_id, :terminal_fill_id, :exchange_order_id,
                :symbol, :side, :direction, :price, :quantity, :fee, :fee_asset,
                :exchange_position_id, :terminal_position_id, :is_close,
                :realized_pnl, :role, :source, :timestamp_ms
            )
            ON CONFLICT(account_id, exchange_fill_id) DO UPDATE SET
                terminal_fill_id     = excluded.terminal_fill_id,
                terminal_position_id = excluded.terminal_position_id,
                price                = excluded.price,
                quantity             = excluded.quantity,
                fee                  = excluded.fee,
                fee_asset            = excluded.fee_asset,
                role                 = excluded.role,
                realized_pnl         = excluded.realized_pnl,
                timestamp_ms         = excluded.timestamp_ms
        """
        try:
            await self._conn.execute(fill_sql, {
                "account_id":           row.get("account_id", 1),
                "exchange_fill_id":     row.get("exchange_fill_id"),
                "terminal_fill_id":     row.get("terminal_fill_id", ""),
                "exchange_order_id":    row.get("exchange_order_id", ""),
                "symbol":               row.get("symbol", ""),
                "side":                 row.get("side", ""),
                "direction":            row.get("direction", ""),
                "price":                row.get("price", 0),
                "quantity":             row.get("quantity", 0),
                "fee":                  row.get("fee", 0),
                "fee_asset":            row.get("fee_asset", "USDT"),
                "exchange_position_id": row.get("exchange_position_id", ""),
                "terminal_position_id": row.get("terminal_position_id", ""),
                "is_close":             int(row.get("is_close", False)),
                "realized_pnl":         row.get("realized_pnl", 0),
                "role":                 row.get("role", ""),
                "source":               row.get("source", ""),
                "timestamp_ms":         row.get("timestamp_ms", 0),
            })
            if exchange_order_id:
                now_ms = int(time.time() * 1000)
                await self._conn.execute(
                    """UPDATE orders SET
                        avg_fill_price = CASE
                            WHEN filled_qty = 0 THEN :price
                            ELSE (avg_fill_price * filled_qty + :price * :qty)
                                 / (filled_qty + :qty)
                        END,
                        filled_qty     = filled_qty + :qty,
                        updated_at_ms  = :now_ms
                    WHERE exchange_order_id = :oid AND account_id = :aid""",
                    {
                        "qty":    row.get("quantity", 0),
                        "price":  row.get("price", 0),
                        "now_ms": now_ms,
                        "oid":    exchange_order_id,
                        "aid":    row.get("account_id", 1),
                    },
                )
            await self._conn.commit()
        except Exception:
            log.exception("upsert_fill_and_update_order failed")

    async def mark_stale_orders_canceled(
        self, account_id: int, active_ids: List[str],
        *, allow_cancel_all: bool = False,
        exclude_prefix: str = "",
        only_prefix: str = "",
    ) -> int:
        """Mark active orders NOT in snapshot as canceled. Returns count affected.

        If active_ids is empty and allow_cancel_all is False, skip cancellation
        to avoid mass-cancel on empty/broken snapshots.

        exclude_prefix: skip orders whose exchange_order_id starts with this prefix
            (e.g., 'algo:' to protect algo orders during basic snapshot processing)
        only_prefix: only affect orders whose exchange_order_id starts with this prefix
            (e.g., 'algo:' to scope stale-cancel to algo orders only)
        """
        now_ms = int(time.time() * 1000)
        scope_clause = ""
        if exclude_prefix:
            scope_clause = f" AND exchange_order_id NOT LIKE '{exclude_prefix}%'"
        elif only_prefix:
            scope_clause = f" AND exchange_order_id LIKE '{only_prefix}%'"

        if not active_ids:
            if not allow_cancel_all:
                log.debug("mark_stale_orders_canceled: empty active_ids, skipping")
                return 0
            cur = await self._conn.execute(
                "UPDATE orders SET status='canceled', updated_at_ms=? "
                f"WHERE account_id=? AND status IN ('new','partially_filled'){scope_clause}",
                (now_ms, account_id),
            )
            await self._conn.commit()
            return cur.rowcount

        placeholders = ",".join("?" for _ in active_ids)
        cur = await self._conn.execute(
            f"UPDATE orders SET status='canceled', updated_at_ms=? "
            f"WHERE account_id=? AND status IN ('new','partially_filled') "
            f"AND exchange_order_id NOT IN ({placeholders}){scope_clause}",
            [now_ms, account_id] + active_ids,
        )
        await self._conn.commit()
        return cur.rowcount

    async def mark_stale_orders(
        self, account_id: int, stale_threshold_ms: int = 300_000
    ) -> int:
        """Mark active orders not seen in stale_threshold_ms as canceled."""
        now_ms = int(time.time() * 1000)
        cutoff = now_ms - stale_threshold_ms
        cur = await self._conn.execute(
            "UPDATE orders SET status='canceled', updated_at_ms=? "
            "WHERE account_id=? AND status IN ('new','partially_filled') "
            "AND last_seen_ms < ? AND last_seen_ms > 0",
            (now_ms, account_id, cutoff),
        )
        await self._conn.commit()
        return cur.rowcount

    # ── Read methods (paginated) ────────────────────────────────────────────

    _ALLOWED_TABLES = {"orders", "fills", "closed_positions"}

    async def _paginated_order_query(
        self,
        table: str,
        ts_col: str,
        allowed_sort: set,
        account_id: int,
        page: int = 1,
        per_page: int = 25,
        sort_by: str = "",
        sort_dir: str = "DESC",
        search: str = "",
        date_from_ms: Optional[int] = None,
        date_to_ms: Optional[int] = None,
        extra_where: str = "",
        extra_params: Optional[list] = None,
    ) -> Tuple[List[Dict], int]:
        """Paginated query for order-domain tables (ms-based timestamps)."""
        if table not in self._ALLOWED_TABLES:
            raise ValueError(f"Invalid table: {table}")
        clauses: list = ["account_id = ?"]
        params: list = [account_id]

        if extra_where:
            clauses.append(extra_where)
            if extra_params:
                params.extend(extra_params)

        if date_from_ms is not None:
            clauses.append(f"{ts_col} >= ?")
            params.append(date_from_ms)
        if date_to_ms is not None:
            clauses.append(f"{ts_col} <= ?")
            params.append(date_to_ms)
        if search:
            clauses.append("(symbol LIKE ?)")
            params.append(f"%{search}%")

        where = " WHERE " + " AND ".join(clauses)

        if sort_by not in allowed_sort:
            sort_by = ts_col
        if sort_dir not in ("ASC", "DESC"):
            sort_dir = "DESC"

        async with self._conn.execute(
            f"SELECT COUNT(*) FROM {table}{where}", params
        ) as cur:
            total = (await cur.fetchone())[0]

        offset = (max(page, 1) - 1) * per_page
        async with self._conn.execute(
            f"SELECT * FROM {table}{where} ORDER BY {sort_by} {sort_dir} LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows], total

    async def query_open_orders(
        self, account_id: int, page: int = 1, per_page: int = 25,
        sort_by: str = "created_at_ms", sort_dir: str = "DESC", search: str = "",
    ) -> Tuple[List[Dict], int]:
        """Open Orders tab — active orders only."""
        return await self._paginated_order_query(
            "orders", "created_at_ms", self._ORDERS_SORT_COLS,
            account_id, page, per_page, sort_by, sort_dir, search,
            extra_where="status IN ('new','partially_filled')",
        )

    async def query_order_history(
        self, account_id: int, page: int = 1, per_page: int = 25,
        sort_by: str = "updated_at_ms", sort_dir: str = "DESC", search: str = "",
        date_from_ms: Optional[int] = None, date_to_ms: Optional[int] = None,
    ) -> Tuple[List[Dict], int]:
        """Order History tab — all statuses."""
        return await self._paginated_order_query(
            "orders", "updated_at_ms", self._ORDERS_SORT_COLS,
            account_id, page, per_page, sort_by, sort_dir, search,
            date_from_ms, date_to_ms,
        )

    async def query_fills(
        self, account_id: int, page: int = 1, per_page: int = 25,
        sort_by: str = "timestamp_ms", sort_dir: str = "DESC", search: str = "",
        date_from_ms: Optional[int] = None, date_to_ms: Optional[int] = None,
    ) -> Tuple[List[Dict], int]:
        """Trade History (fills) tab."""
        return await self._paginated_order_query(
            "fills", "timestamp_ms", self._FILLS_SORT_COLS,
            account_id, page, per_page, sort_by, sort_dir, search,
            date_from_ms, date_to_ms,
        )

    async def query_closed_positions(
        self, account_id: int, page: int = 1, per_page: int = 25,
        sort_by: str = "exit_time_ms", sort_dir: str = "DESC", search: str = "",
        date_from_ms: Optional[int] = None, date_to_ms: Optional[int] = None,
    ) -> Tuple[List[Dict], int]:
        """Position History tab."""
        return await self._paginated_order_query(
            "closed_positions", "exit_time_ms", self._CLOSED_POS_SORT_COLS,
            account_id, page, per_page, sort_by, sort_dir, search,
            date_from_ms, date_to_ms,
        )

    # ── Utility methods ─────────────────────────────────────────────────────

    async def get_active_orders_map(self, account_id: int) -> Dict[str, Dict]:
        """Return {exchange_order_id: row} for all active orders."""
        async with self._conn.execute(
            "SELECT * FROM orders WHERE account_id=? "
            "AND status IN ('new','partially_filled')",
            (account_id,),
        ) as cur:
            rows = await cur.fetchall()
            return {r["exchange_order_id"]: dict(r) for r in rows if r["exchange_order_id"]}

    async def query_open_orders_all(self, account_id: int) -> List[Dict]:
        """Unpaginated list of all active orders (for cache rebuild)."""
        async with self._conn.execute(
            "SELECT * FROM orders WHERE account_id=? "
            "AND status IN ('new','partially_filled') "
            "ORDER BY created_at_ms DESC",
            (account_id,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_position_fees(self, account_id: int, terminal_position_id: str) -> float:
        """SUM(fee) for all fills of a position. Never accumulate in cache."""
        async with self._conn.execute(
            "SELECT COALESCE(SUM(fee), 0) FROM fills "
            "WHERE account_id=? AND terminal_position_id=?",
            (account_id, terminal_position_id),
        ) as cur:
            row = await cur.fetchone()
            return float(row[0]) if row else 0.0

    async def get_position_fills(
        self, account_id: int, pos_id: str, symbol: str,
        direction: str, is_close: Optional[bool] = None,
    ) -> List[Dict]:
        """Get fills for a position, optionally filtered by is_close.

        Falls back to (symbol, direction) only when terminal_position_id
        is empty/NULL, preventing cross-position contamination.
        """
        sql = (
            "SELECT * FROM fills WHERE account_id=? "
            "AND (terminal_position_id=? OR "
            "(COALESCE(terminal_position_id, '') = '' AND symbol=? AND direction=?))"
        )
        params: list = [account_id, pos_id, symbol, direction]
        if is_close is not None:
            sql += " AND is_close=?"
            params.append(int(is_close))
        sql += " ORDER BY timestamp_ms ASC"
        async with self._conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_fills_by_order(
        self, account_id: int, exchange_order_id: str
    ) -> List[Dict]:
        """Get all fills for a specific order."""
        async with self._conn.execute(
            "SELECT * FROM fills WHERE account_id=? AND exchange_order_id=? "
            "ORDER BY timestamp_ms ASC",
            (account_id, exchange_order_id),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_unrecorded_closing_fills(
        self, account_id: int, pos_id: str, symbol: str, direction: str
    ) -> List[Dict]:
        """Find closing fills that don't yet have a closed_positions row.

        A closed_positions row covers a time *range* (entry→exit).  We check
        whether the fill's timestamp falls within any existing row's window
        for the same position, which handles batched partial fills correctly.
        """
        async with self._conn.execute(
            """SELECT f.* FROM fills f
            WHERE f.account_id=? AND f.is_close=1
              AND (f.terminal_position_id=? OR
                   (COALESCE(f.terminal_position_id, '') = '' AND f.symbol=? AND f.direction=?))
              AND NOT EXISTS (
                  SELECT 1 FROM closed_positions cp
                  WHERE cp.account_id = f.account_id
                    AND cp.terminal_position_id = f.terminal_position_id
                    AND f.timestamp_ms BETWEEN cp.entry_time_ms AND cp.exit_time_ms
              )
            ORDER BY f.timestamp_ms ASC""",
            (account_id, pos_id, symbol, direction),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_order_by_exchange_id(
        self, account_id: int, exchange_order_id: str
    ) -> Optional[Dict]:
        """Look up a single order by exchange_order_id (for exit_reason)."""
        if not exchange_order_id:
            return None
        async with self._conn.execute(
            "SELECT * FROM orders WHERE account_id=? AND exchange_order_id=?",
            (account_id, exchange_order_id),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None  # get_order_by_exchange_id

    async def get_pre_trade_for_shortfall(
        self, account_id: int, symbol: str, entry_time_ms: int,
        window_ms: int = 300_000,
    ) -> Optional[Dict]:
        """Find the most recent pre_trade_log entry for symbol within window before entry.

        pre_trade_log.timestamp is ISO-8601 text; entry_time_ms is epoch-ms.
        We convert the window bounds to ISO for comparison.
        """
        from datetime import datetime, timezone, timedelta

        entry_dt = datetime.fromtimestamp(entry_time_ms / 1000, tz=timezone.utc)
        window_start = (entry_dt - timedelta(milliseconds=window_ms)).isoformat()
        window_end   = (entry_dt + timedelta(seconds=30)).isoformat()  # small grace

        async with self._conn.execute(
            "SELECT * FROM pre_trade_log "
            "WHERE account_id=? AND ticker=? AND timestamp BETWEEN ? AND ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (account_id, symbol, window_start, window_end),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None  # get_pre_trade_for_shortfall

    # ── Backfill from exchange_history ──────────────────────────────────────

    async def backfill_fills_from_exchange_history(
        self, account_id: int = 1, days: int = 30,
    ) -> Dict[str, int]:
        """One-time migration: copy exchange_history rows into fills + closed_positions.

        OPEN → is_close=0, REALIZED_PNL → is_close=1.
        Skips rows that already exist via UNIQUE constraints.
        Returns {"fills_inserted": N, "closed_inserted": M}.
        """
        cutoff_ms = int((time.time() - days * 86400) * 1000)

        async with self._conn.execute(
            "SELECT * FROM exchange_history "
            "WHERE time >= ? AND account_id = ? "
            "ORDER BY time ASC",
            (cutoff_ms, account_id),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]

        fills_inserted = 0
        for r in rows:
            is_close = r.get("income_type") == "REALIZED_PNL"
            fill = {
                "account_id":           account_id,
                "exchange_fill_id":     r.get("trade_key", ""),
                "terminal_fill_id":     "",
                "exchange_order_id":    "",
                "symbol":               r.get("symbol", ""),
                "side":                 "SELL" if (
                    (r.get("direction") == "LONG" and is_close)
                    or (r.get("direction") == "SHORT" and not is_close)
                ) else "BUY",
                "direction":            r.get("direction", ""),
                "price":                r.get("exit_price") if is_close else r.get("entry_price", 0),
                "quantity":             r.get("qty", 0),
                "fee":                  r.get("fee", 0),
                "fee_asset":            r.get("asset", "USDT"),
                "exchange_position_id": "",
                "terminal_position_id": "",
                "is_close":             int(is_close),
                "realized_pnl":         r.get("income", 0) if is_close else 0,
                "role":                 "",
                "source":               "exchange_history_backfill",
                "timestamp_ms":         r.get("time", 0),
            }
            # PA-1a: skip if a matching WS fill already exists (dedup at write time).
            # WS fills use tradeId as key; backfill uses trade_key — different keys
            # for the same fill. Match on (symbol, side, quantity, timestamp ±1s).
            try:
                async with self._conn.execute(
                    "SELECT 1 FROM fills WHERE account_id=? AND symbol=? AND side=? "
                    "AND quantity=? AND ABS(timestamp_ms - ?) < 1000 LIMIT 1",
                    (account_id, fill["symbol"], fill["side"],
                     fill["quantity"], fill["timestamp_ms"]),
                ) as cur:
                    if await cur.fetchone():
                        continue  # WS fill exists — skip backfill duplicate
            except Exception:
                pass  # If check fails, proceed with insert (safe: upsert is idempotent)
            try:
                await self.upsert_fill(fill)
                fills_inserted += 1
            except Exception:
                pass

        # Build closed_positions from REALIZED_PNL rows.
        # Group by (symbol, direction, open_time) so multi-fill closes produce
        # one row instead of duplicates.  The synthetic position ID ensures the
        # UNIQUE(account_id, terminal_position_id, exit_time_ms) deduplicates.
        closes = [r for r in rows if r.get("income_type") == "REALIZED_PNL"]

        from collections import defaultdict
        groups: Dict[tuple, List[Dict]] = defaultdict(list)
        for c in closes:
            open_time = c.get("open_time", 0)
            if not open_time or not c.get("time", 0):
                continue
            key = (c.get("symbol", ""), c.get("direction", ""), open_time)
            groups[key].append(c)

        closed_inserted = 0
        for (symbol, direction, open_time), fills in groups.items():
            total_qty = sum(f.get("qty", 0) for f in fills)
            total_pnl = sum(f.get("income", 0) for f in fills)
            total_fee = sum(f.get("fee", 0) for f in fills)
            exit_time = max(f.get("time", 0) for f in fills)
            # VWAP exit price
            notional  = sum(f.get("exit_price", 0) * f.get("qty", 0) for f in fills)
            exit_price = notional / total_qty if total_qty else 0
            entry_price = fills[0].get("entry_price", 0)
            # Synthetic position ID: deterministic, same across reruns
            syn_pos_id = f"bf:{symbol}:{direction}:{open_time}"
            # Carry best MFE/MAE from any fill in the group
            best_mfe = max(f.get("mfe", 0) for f in fills)
            best_mae = min(f.get("mae", 0) for f in fills)

            try:
                await self.insert_closed_position({
                    "account_id":           account_id,
                    "exchange_position_id": "",
                    "terminal_position_id": syn_pos_id,
                    "symbol":               symbol,
                    "direction":            direction,
                    "quantity":             total_qty,
                    "entry_price":          entry_price,
                    "exit_price":           exit_price,
                    "entry_time_ms":        open_time,
                    "exit_time_ms":         exit_time,
                    "realized_pnl":         total_pnl,
                    "total_fees":           total_fee,
                    "net_pnl":              total_pnl - total_fee,
                    "hold_time_ms":         exit_time - open_time,
                    "exit_reason":          "",
                    "mfe":                  best_mfe,
                    "mae":                  best_mae,
                    "source":               "exchange_history_backfill",
                })
                closed_inserted += 1
            except Exception:
                pass

        log.info(
            "Backfill complete: %d fills, %d closed_positions from exchange_history",
            fills_inserted, closed_inserted,
        )
        return {"fills_inserted": fills_inserted, "closed_inserted": closed_inserted}

    # ── MFE/MAE for closed_positions ───────────────────────────────────────

    async def get_uncalculated_closed_positions(
        self, account_id: int,
    ) -> List[Dict]:
        """Return closed_positions rows where backfill has not completed."""
        async with self._conn.execute(
            "SELECT * FROM closed_positions "
            "WHERE account_id=? AND NOT backfill_completed "
            "AND entry_time_ms > 0 AND exit_time_ms > 0 "
            "ORDER BY exit_time_ms DESC LIMIT 200",
            (account_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def update_closed_position_mfe_mae(
        self, row_id: int, mfe: float, mae: float,
    ) -> None:
        """Update MFE/MAE on a specific closed_positions row."""
        await self._conn.execute(
            "UPDATE closed_positions SET mfe=?, mae=?, backfill_completed=1 WHERE id=?",
            (mfe, mae, row_id),
        )
        await self._conn.commit()

    # ── Data consistency ───────────────────────────────────────────────────

    async def validate_order_data_consistency(
        self, account_id: int,
    ) -> Dict[str, Any]:
        """Check for orphan fills, qty mismatches, stale orders, unclosed positions."""
        result: Dict[str, Any] = {}

        # Orphan fills (reference non-existent orders)
        async with self._conn.execute(
            "SELECT COUNT(*) FROM fills f "
            "WHERE f.account_id=? AND f.exchange_order_id != '' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM orders o WHERE o.exchange_order_id = f.exchange_order_id"
            ")",
            (account_id,),
        ) as cur:
            result["orphan_fills"] = (await cur.fetchone())[0]

        # Stale active orders (not seen in 24h+)
        cutoff = int(time.time() * 1000) - 86_400_000
        async with self._conn.execute(
            "SELECT COUNT(*) FROM orders "
            "WHERE account_id=? AND status IN ('new','partially_filled') "
            "AND last_seen_ms < ? AND last_seen_ms > 0",
            (account_id, cutoff),
        ) as cur:
            result["stale_orders_24h"] = (await cur.fetchone())[0]

        # Closed positions missing MFE/MAE
        async with self._conn.execute(
            "SELECT COUNT(*) FROM closed_positions "
            "WHERE account_id=? AND NOT backfill_completed "
            "AND entry_time_ms > 0 AND exit_time_ms > 0",
            (account_id,),
        ) as cur:
            result["closed_missing_mfe_mae"] = (await cur.fetchone())[0]

        # Row counts
        for table in ("orders", "fills", "closed_positions"):
            async with self._conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE account_id=?",
                (account_id,),
            ) as cur:
                result[f"{table}_count"] = (await cur.fetchone())[0]

        return result
