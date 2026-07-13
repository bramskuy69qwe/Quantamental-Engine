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

    async def get_last_income_time(self, account_id: int = 1) -> Optional[int]:
        """MAX(time) across this account's exchange_history rows — the anchor for
        a window-aware income fetch. Binance's income endpoint returns at most
        ~7 days from a given startTime, so after an offline gap > 7 days the
        no-startTime fetch silently drops the older trades; anchoring at the last
        captured row lets the fetch page forward across the whole gap. Returns
        None on a fresh (empty) exchange_history."""
        async with self._conn.execute(
            "SELECT MAX(time) FROM exchange_history WHERE account_id=?",
            (account_id,),
        ) as cur:
            r = await cur.fetchone()
            return int(r[0]) if r and r[0] else None

    async def update_exchange_mfe_mae(self, trade_key: str, mfe: float, mae: float) -> None:
        """Write accurate MFE/MAE for a closed trade (reconciler only)."""
        await self._conn.execute(
            "UPDATE exchange_history SET mfe=?, mae=?, backfill_completed=1 WHERE trade_key=?",
            (mfe, mae, trade_key),
        )
        await self._conn.commit()

    # ── HIGH-002 (Task 143, Phase 6 platform_bridge) ────────────────────────
    # Helpers below replace `db._conn` direct access in
    # `core/platform_bridge.py::handle_historical_fill`. All scoped to
    # exchange_history; merge + open-time-resolution logic for closing fills.

    async def find_realized_pnl_for_merge(
        self, *, time_ms: int, symbol: str, direction: str, account_id: int,
    ) -> Optional[Dict]:
        """Find an existing REALIZED_PNL row matching (time, symbol,
        direction, account_id) — used by handle_historical_fill to detect
        partial-fills-from-same-order and merge them rather than insert
        a duplicate.

        Returns the matching row (dict) or None if no match. Caller
        decides whether to aggregate or insert based on this result.

        Original query carried `LIMIT 1` — when multiple rows match
        (would only happen on prior duplicate-insert bug), the DB's
        natural order picks one; behavior preserved.
        """
        async with self._conn.execute(
            "SELECT trade_key, income, qty, fee, exit_price, notional"
            " FROM exchange_history"
            " WHERE time=? AND symbol=? AND direction=?"
            " AND income_type='REALIZED_PNL' AND account_id=? LIMIT 1",
            (time_ms, symbol, direction, account_id),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def merge_realized_pnl_into(
        self, *, trade_key: str,
        income_delta: float, new_total_qty: float, fee_delta: float,
        wavg_exit: float, notional_delta: float,
    ) -> None:
        """Aggregate-merge a partial fill into an existing REALIZED_PNL
        row. Adds income/fee/notional deltas, replaces qty with the new
        total, replaces exit_price with the caller-computed weighted
        average. Commits.

        Caller is responsible for computing weighted-average exit and
        new total qty — this helper only persists. No idempotency check;
        calling twice double-merges.
        """
        await self._conn.execute(
            "UPDATE exchange_history SET"
            " income=income+?, qty=?, fee=fee+?,"
            " exit_price=?, notional=notional+?"
            " WHERE trade_key=?",
            (income_delta, new_total_qty, fee_delta,
             wavg_exit, notional_delta, trade_key),
        )
        await self._conn.commit()

    async def find_nearest_open_time_before(
        self, *, symbol: str, account_id: int,
        before_ms: int, window_ms: int = 604_800_000,
    ) -> Optional[int]:
        """Find the most recent OPEN-fill timestamp for `symbol`
        strictly before `before_ms` and within `window_ms` of it
        (default 7 days). Used to resolve open_time on closing fills.

        Returns the MAX(time) or None if no qualifying OPEN fill.
        """
        async with self._conn.execute(
            "SELECT MAX(time) FROM exchange_history"
            " WHERE symbol=? AND income_type='OPEN'"
            " AND account_id=? AND time<=? AND time>?-?",
            (symbol, account_id, before_ms, before_ms, window_ms),
        ) as cur:
            r = await cur.fetchone()
            return r[0] if r and r[0] else None

    async def find_earliest_open_time(
        self, *, symbol: str, account_id: int,
    ) -> Optional[int]:
        """Fallback OPEN-time resolution: earliest OPEN fill for the
        symbol within the account. Used when no time-windowed match
        exists for the closing fill (rare; covers reconciliation gaps).
        """
        async with self._conn.execute(
            "SELECT MIN(time) FROM exchange_history"
            " WHERE symbol=? AND income_type='OPEN' AND account_id=?",
            (symbol, account_id),
        ) as cur:
            r = await cur.fetchone()
            return r[0] if r and r[0] else None

    async def set_close_fill_open_time(
        self, *, trade_key: str, open_time: int, current_close_ts: int,
    ) -> None:
        """Set open_time on a closing fill's trade_key, but ONLY if the
        existing open_time is 0 (unresolved) or equal to the current
        close timestamp (placeholder). Prevents overwriting a properly-
        resolved open_time on re-entry. Commits.

        The (open_time=0 OR open_time=?) guard matches the original
        platform_bridge logic byte-for-byte.
        """
        await self._conn.execute(
            "UPDATE exchange_history SET open_time=?"
            " WHERE trade_key=? AND (open_time=0 OR open_time=?)",
            (open_time, trade_key, current_close_ts),
        )
        await self._conn.commit()

    # ── HIGH-002 (Task 144, Phase 6 monitoring/reconciler) ──────────────────
    # Helpers below replace `db._conn` direct access in monitoring.py +
    # reconciler.py. Shared "pending reconciler work" filter:
    # `WHERE NOT backfill_completed AND open_time>0 AND trade_key NOT LIKE 'qt:%'`
    # — excludes Quantower-sourced individual fills (round-trip pairing
    # doesn't apply) and rows that haven't been opened yet.

    async def count_pending_reconciler_rows(self) -> int:
        """Count rows in exchange_history that the reconciler still
        needs to backfill (MFE/MAE). Used by the monitoring layer's
        reconciler-backlog health check.

        Excludes Quantower-sourced rows (trade_key starts with 'qt:')
        and rows with no open_time (haven't been entered yet).
        """
        async with self._conn.execute(
            "SELECT COUNT(*) FROM exchange_history"
            " WHERE NOT backfill_completed AND open_time>0"
            " AND trade_key NOT LIKE 'qt:%'"
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def get_pending_reconciler_symbols(self) -> List[str]:
        """Return distinct symbols with pending-reconciler rows in
        exchange_history. Used by the reconciler backfill loop to
        decide which symbols to process. Same WHERE filter as
        count_pending_reconciler_rows (count vs list shape).
        """
        async with self._conn.execute(
            "SELECT DISTINCT symbol FROM exchange_history"
            " WHERE NOT backfill_completed AND open_time>0"
            " AND trade_key NOT LIKE 'qt:%'"
        ) as cur:
            return [r[0] for r in await cur.fetchall()]

    async def get_uncalculated_exchange_rows(self, symbol: str) -> List[Dict]:
        """Return exchange_history rows for symbol where backfill has not completed."""
        async with self._conn.execute(
            "SELECT * FROM exchange_history WHERE symbol=? AND NOT backfill_completed AND open_time>0",
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
