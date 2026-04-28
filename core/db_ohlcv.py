from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("database")


class OhlcvMixin:
    """ohlcv_cache domain methods."""

    async def upsert_ohlcv(self, symbol: str, timeframe: str, candles: List[List]) -> int:
        """
        Bulk-upsert OHLCV candles. candles = [[ts_ms, o, h, l, c, vol], ...]
        Returns number of rows written.
        """
        if not candles:
            return 0
        rows = [
            (symbol, timeframe, int(c[0]), float(c[1]), float(c[2]),
             float(c[3]), float(c[4]), float(c[5]))
            for c in candles
        ]
        await self._conn.executemany(
            """INSERT INTO ohlcv_cache (symbol, timeframe, ts_ms, open, high, low, close, volume)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(symbol, timeframe, ts_ms) DO UPDATE SET
                 open=excluded.open, high=excluded.high, low=excluded.low,
                 close=excluded.close, volume=excluded.volume""",
            rows,
        )
        await self._conn.commit()
        return len(rows)

    async def get_ohlcv(
        self, symbol: str, timeframe: str,
        since_ms: Optional[int] = None, until_ms: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[List]:
        """Return [[ts_ms, o, h, l, c, vol], ...] ordered oldest-first."""
        clauses = ["symbol=?", "timeframe=?"]
        params: list = [symbol, timeframe]
        if since_ms is not None:
            clauses.append("ts_ms >= ?")
            params.append(since_ms)
        if until_ms is not None:
            clauses.append("ts_ms <= ?")
            params.append(until_ms)
        where = " WHERE " + " AND ".join(clauses)
        sql = f"SELECT ts_ms, open, high, low, close, volume FROM ohlcv_cache{where} ORDER BY ts_ms ASC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        async with self._conn.execute(sql, params) as cur:
            return [list(r) for r in await cur.fetchall()]

    async def get_ohlcv_range(self, symbol: str, timeframe: str) -> Dict[str, Any]:
        """Return {min_ts_ms, max_ts_ms, count} for the stored range."""
        async with self._conn.execute(
            "SELECT MIN(ts_ms), MAX(ts_ms), COUNT(*) FROM ohlcv_cache WHERE symbol=? AND timeframe=?",
            (symbol, timeframe),
        ) as cur:
            row = await cur.fetchone()
        return {"min_ts_ms": row[0], "max_ts_ms": row[1], "count": row[2] or 0}
