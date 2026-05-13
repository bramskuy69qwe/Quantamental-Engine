from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.state import TZ_LOCAL

log = logging.getLogger("database")


class AnalyticsMixin:
    """Analytics query methods: journal stats, equity series, trade stats, MFE/MAE, OHLC."""

    async def get_journal_stats(self, from_ms: int, to_ms: int, account_id: int = 1) -> Dict[str, Any]:
        """
        Single-pass aggregation over exchange_history for a time window.
        Excludes FUNDING_FEE and TRANSFER rows from trade counts/PnL but captures
        TRANSFER rows for deposit/withdrawal fields.
        """
        async with self._conn.execute(
            """
            SELECT
              SUM(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') THEN 1 ELSE 0 END)          AS total_trades,
              SUM(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') AND income > 0 THEN 1 ELSE 0 END) AS winning_trades,
              SUM(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') AND income < 0 THEN 1 ELSE 0 END) AS losing_trades,
              SUM(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') AND direction='LONG'  THEN 1 ELSE 0 END) AS num_longs,
              SUM(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') AND direction='SHORT' THEN 1 ELSE 0 END) AS num_shorts,
              SUM(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') THEN income ELSE 0 END)      AS total_pnl,
              SUM(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') THEN fee    ELSE 0 END)      AS total_fees,
              SUM(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') THEN qty * entry_price ELSE 0 END) AS trading_volume,
              AVG(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') AND income > 0 THEN income END) AS avg_profit,
              AVG(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') AND income < 0 THEN income END) AS avg_loss,
              MAX(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') THEN income END)             AS biggest_profit,
              MIN(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') THEN income END)             AS biggest_loss,
              SUM(CASE WHEN income_type='TRANSFER' AND income > 0 THEN income ELSE 0 END)              AS deposits,
              SUM(CASE WHEN income_type='TRANSFER' AND income < 0 THEN ABS(income) ELSE 0 END)        AS withdrawals
            FROM exchange_history
            WHERE account_id = ? AND time >= ? AND time <= ?
            """,
            (account_id, from_ms, to_ms),
        ) as cur:
            row = await cur.fetchone()
        result = dict(row) if row else {}
        for k in result:
            if result[k] is None:
                result[k] = 0.0
        return result

    async def get_daily_equity_series(self, from_ms: int, to_ms: int, account_id: int = 1) -> List[Dict[str, Any]]:
        """
        One row per LOCAL calendar day (last snapshot of that day) covering the range.
        Returns: [{day, total_equity, daily_pnl, daily_pnl_percent, drawdown}, ...]
        Ordered oldest-first for chart rendering.
        """
        try:
            offset_s = int(datetime.now(TZ_LOCAL).utcoffset().total_seconds())
        except (AttributeError, TypeError, OSError):
            offset_s = 0
        offset_h = offset_s // 3600
        tz_mod = f"{'+' if offset_h >= 0 else ''}{offset_h} hours"

        from_iso = datetime.utcfromtimestamp(from_ms / 1000).strftime("%Y-%m-%dT%H:%M:%S")
        to_iso   = datetime.utcfromtimestamp(to_ms   / 1000).strftime("%Y-%m-%dT%H:%M:%S")

        # NOTE: SQLite DATE(ts, modifier) accepts literal modifier strings only,
        # not bound parameters — the value is validated above to be safe (e.g. "+7 hours").
        sql = f"""
            SELECT
              DATE(snapshot_ts, '{tz_mod}') AS day,
              total_equity,
              daily_pnl,
              daily_pnl_percent,
              drawdown
            FROM account_snapshots
            WHERE account_id = ? AND snapshot_ts >= ? AND snapshot_ts <= ?
            GROUP BY DATE(snapshot_ts, '{tz_mod}')
            HAVING snapshot_ts = MAX(snapshot_ts)
            ORDER BY day ASC
        """
        async with self._conn.execute(sql, (account_id, from_iso, to_iso)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_daily_trade_stats(self, from_ms: int, to_ms: int, account_id: int = 1) -> Dict[str, Dict]:
        """
        Per-day aggregation from exchange_history: trade count, volume, win rate.
        Returns {"YYYY-MM-DD": {"trades": int, "volume": float, "win_rate": float}}
        """
        try:
            offset_s = int(datetime.now(TZ_LOCAL).utcoffset().total_seconds())
        except (AttributeError, TypeError, OSError):
            offset_s = 0
        offset_h = offset_s // 3600
        tz_mod = f"{'+' if offset_h >= 0 else ''}{offset_h} hours"

        sql = f"""
            SELECT
              DATE(datetime(time/1000, 'unixepoch', '{tz_mod}')) AS day,
              COUNT(*)                                              AS total_trades,
              SUM(qty * entry_price)                               AS volume,
              SUM(CASE WHEN income > 0 THEN 1 ELSE 0 END)         AS wins
            FROM exchange_history
            WHERE account_id = ? AND time >= ? AND time <= ?
              AND income_type NOT IN ('FUNDING_FEE', 'TRANSFER')
            GROUP BY DATE(datetime(time/1000, 'unixepoch', '{tz_mod}'))
        """
        async with self._conn.execute(sql, (account_id, from_ms, to_ms)) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        result: Dict[str, Dict] = {}
        for r in rows:
            total = r["total_trades"] or 0
            wins  = r["wins"] or 0
            result[r["day"]] = {
                "trades":   total,
                "volume":   r["volume"] or 0.0,
                "win_rate": round(wins / total, 4) if total else 0.0,
            }
        return result

    async def get_equity_period_boundaries(self, from_ms: int, to_ms: int, account_id: int = 1) -> Dict[str, float]:
        """Return {initial_equity, final_equity, max_drawdown} for a period."""
        from_iso = datetime.utcfromtimestamp(from_ms / 1000).strftime("%Y-%m-%dT%H:%M:%S")
        to_iso   = datetime.utcfromtimestamp(to_ms   / 1000).strftime("%Y-%m-%dT%H:%M:%S")
        async with self._conn.execute(
            "SELECT total_equity FROM account_snapshots WHERE account_id=? AND snapshot_ts >= ? ORDER BY snapshot_ts ASC LIMIT 1",
            (account_id, from_iso),
        ) as cur:
            row = await cur.fetchone()
            initial = float(row[0]) if row else 0.0
        async with self._conn.execute(
            "SELECT total_equity FROM account_snapshots WHERE account_id=? AND snapshot_ts <= ? ORDER BY snapshot_ts DESC LIMIT 1",
            (account_id, to_iso),
        ) as cur:
            row = await cur.fetchone()
            final = float(row[0]) if row else 0.0
        async with self._conn.execute(
            "SELECT MAX(drawdown) FROM account_snapshots WHERE account_id=? AND snapshot_ts >= ? AND snapshot_ts <= ?",
            (account_id, from_iso, to_iso),
        ) as cur:
            row = await cur.fetchone()
            max_dd = float(row[0]) if row and row[0] is not None else 0.0
        return {"initial_equity": initial, "final_equity": final, "max_drawdown": max_dd}

    async def get_traded_pairs_stats(self, from_ms: int, to_ms: int, account_id: int = 1) -> List[Dict[str, Any]]:
        """Per-symbol aggregation: count, long/short split, PnL breakdown, volume, fees."""
        async with self._conn.execute(
            """
            SELECT
              symbol,
              COUNT(*)                                                               AS total,
              SUM(CASE WHEN direction='LONG'  THEN 1 ELSE 0 END)                   AS longs,
              SUM(CASE WHEN direction='SHORT' THEN 1 ELSE 0 END)                   AS shorts,
              SUM(CASE WHEN direction='LONG'  THEN income ELSE 0 END)              AS pnl_long,
              SUM(CASE WHEN direction='SHORT' THEN income ELSE 0 END)              AS pnl_short,
              SUM(income)                                                            AS pnl_total,
              SUM(fee)                                                               AS fees_total,
              SUM(qty * entry_price)                                                 AS volume,
              SUM(CASE WHEN income > 0 THEN 1 ELSE 0 END)                          AS wins,
              AVG(CASE WHEN income > 0 THEN income END)                             AS avg_win,
              AVG(CASE WHEN income < 0 THEN income END)                             AS avg_loss
            FROM exchange_history
            WHERE account_id = ? AND time >= ? AND time <= ?
              AND income_type NOT IN ('FUNDING_FEE','TRANSFER')
            GROUP BY symbol
            ORDER BY total DESC
            """,
            (account_id, from_ms, to_ms),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        for r in rows:
            t = r["total"] or 1
            r["win_rate"] = round((r["wins"] or 0) / t, 4)
            for k in ("pnl_long", "pnl_short", "pnl_total", "fees_total", "volume", "avg_win", "avg_loss"):
                if r[k] is None:
                    r[k] = 0.0
        return rows

    async def get_mfe_mae_series(self, from_ms: int, to_ms: int, account_id: int = 1) -> List[Dict[str, Any]]:
        """Returns reconciled trades with MFE/MAE for scatter plot and ratio calcs."""
        async with self._conn.execute(
            """
            SELECT trade_key, symbol, direction, income, notional, mfe, mae,
                   entry_price, qty,
                   (time - open_time) AS hold_ms
            FROM exchange_history
            WHERE account_id = ? AND time >= ? AND time <= ?
              AND open_time > 0
              AND (mfe != 0 OR mae != 0)
              AND income_type NOT IN ('FUNDING_FEE','TRANSFER')
            ORDER BY time DESC
            """,
            (account_id, from_ms, to_ms),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_r_multiples(self, from_ms: int, to_ms: int, account_id: int = 1) -> List[float]:
        """
        Returns list of R-multiple floats for the period.
        Primary source: trade_history.individual_realized_r.
        Falls back to exchange_history.income / ABS(pre_trade.est_loss) for unmatched records.
        """
        r_values: List[float] = []
        from_iso = datetime.utcfromtimestamp(from_ms / 1000).isoformat()
        to_iso   = datetime.utcfromtimestamp(to_ms   / 1000).isoformat()
        async with self._conn.execute(
            """
            SELECT individual_realized_r FROM trade_history
            WHERE account_id = ? AND exit_timestamp >= ? AND exit_timestamp <= ?
              AND individual_realized_r != 0
            """,
            (account_id, from_iso, to_iso),
        ) as cur:
            for row in await cur.fetchall():
                r_values.append(float(row[0]))
        if len(r_values) < 5:
            async with self._conn.execute(
                """
                SELECT eh.income, pt.est_loss
                FROM exchange_history eh
                LEFT JOIN pre_trade_log pt
                  ON pt.ticker = eh.symbol
                  AND pt.account_id = eh.account_id
                  AND ABS(CAST(strftime('%s', pt.timestamp) AS INTEGER) * 1000
                          - eh.open_time) < 3600000
                WHERE eh.account_id = ? AND eh.time >= ? AND eh.time <= ?
                  AND eh.income_type NOT IN ('FUNDING_FEE','TRANSFER')
                  AND pt.est_loss < 0
                GROUP BY eh.trade_key
                ORDER BY eh.time DESC
                LIMIT 500
                """,
                (account_id, from_ms, to_ms),
            ) as cur:
                for row in await cur.fetchall():
                    income, est_loss = row
                    if est_loss and est_loss != 0:
                        r_values.append(round(float(income) / abs(float(est_loss)), 3))
        return r_values

    async def get_most_traded_pairs(self, from_ms: int, to_ms: int, limit: int = 5, account_id: int = 1) -> List[str]:
        """Return top-N symbols by trade count in the period."""
        async with self._conn.execute(
            """
            SELECT symbol, COUNT(*) AS cnt
            FROM exchange_history
            WHERE account_id = ? AND time >= ? AND time <= ?
              AND income_type NOT IN ('FUNDING_FEE','TRANSFER')
            GROUP BY symbol
            ORDER BY cnt DESC
            LIMIT ?
            """,
            (account_id, from_ms, to_ms, limit),
        ) as cur:
            return [row[0] for row in await cur.fetchall()]

    async def get_cumulative_pnl(self, account_id: int = 1) -> Dict[str, float]:
        """All-time cumulative PnL and PnL% from exchange_history."""
        async with self._conn.execute(
            """
            SELECT
              SUM(CASE WHEN income_type NOT IN ('FUNDING_FEE','TRANSFER') THEN income ELSE 0 END) AS total_pnl,
              SUM(CASE WHEN income_type='TRANSFER' AND income > 0 THEN income ELSE 0 END)         AS total_deposits,
              SUM(CASE WHEN income_type='TRANSFER' AND income < 0 THEN ABS(income) ELSE 0 END)   AS total_withdrawals
            FROM exchange_history
            WHERE account_id = ?
            """,
            (account_id,),
        ) as cur:
            row = dict(await cur.fetchone())
        for k in row:
            if row[k] is None:
                row[k] = 0.0
        return row

    async def get_equity_ohlc(self, tf_minutes: int = 60, limit: int = 100, account_id: int = 1) -> List[Dict[str, Any]]:
        """
        Build OHLC candles from account_snapshots for the given timeframe.
        Each candle covers tf_minutes minutes; returns at most `limit` candles.
        Returns: [{x: epoch_ms, o, h, l, c}] sorted oldest-first.
        """
        async with self._conn.execute(
            "SELECT snapshot_ts, total_equity, trigger_channel FROM account_snapshots WHERE account_id=? ORDER BY snapshot_ts ASC",
            (account_id,),
        ) as cur:
            rows = await cur.fetchall()

        tf_ms = tf_minutes * 60 * 1000
        candles: dict = {}

        raw_points: List[Dict[str, Any]] = []
        for row in rows:
            ts_str = str(row[0])
            equity = float(row[1])
            trigger_channel = str(row[2] or "")
            try:
                if ts_str.endswith("Z"):
                    ts_str = ts_str[:-1] + "+00:00"
                from datetime import timezone as _tz
                dt = datetime.fromisoformat(ts_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=_tz.utc)
                ts_ms = int(dt.timestamp() * 1000)
            except Exception:
                continue
            raw_points.append({"ts_ms": ts_ms, "equity": equity, "trigger_channel": trigger_channel})

            period = (ts_ms // tf_ms) * tf_ms
            if period not in candles:
                candles[period] = {"o": equity, "h": equity, "l": equity, "c": equity}
            else:
                c = candles[period]
                if equity > c["h"]: c["h"] = equity
                if equity < c["l"]: c["l"] = equity
                c["c"] = equity

        async with self._conn.execute(
            "SELECT ts_ms, amount FROM equity_cashflow WHERE account_id=? ORDER BY ts_ms ASC",
            (account_id,),
        ) as cur:
            cf_rows = await cur.fetchall()

        cf_by_period: dict = {}
        for row in cf_rows:
            cf_period = (int(row[0]) // tf_ms) * tf_ms
            cf_by_period[cf_period] = cf_by_period.get(cf_period, 0.0) + float(row[1])

        sorted_periods = sorted(candles.keys())
        dense_periods: List[int] = []
        if sorted_periods:
            p = sorted_periods[0]
            last = sorted_periods[-1]
            while p <= last:
                dense_periods.append(p)
                p += tf_ms

        result: List[Dict[str, Any]] = []
        # FE-10: initialize prev_close from first candle so dense_periods
        # before the first data point carry forward a real value instead of
        # being skipped (which causes a visual "drop to zero" on the left).
        prev_close: Optional[float] = None
        if sorted_periods:
            first_candle = candles[sorted_periods[0]]
            prev_close = first_candle["o"]
        for period in dense_periods:
            c = candles.get(period)
            if c is None:
                if prev_close is None:
                    continue
                o = h = l = close = prev_close
            else:
                # Anchor open to previous close so candles connect with no gap.
                o = prev_close if prev_close is not None else c["o"]
                close = c["c"]
                h = max(c["h"], o)
                l = min(c["l"], o)
            prev_close = close
            result.append({
                "x": period,
                "o": round(o, 2),
                "h": round(h, 2),
                "l": round(l, 2),
                "c": round(close, 2),
                "cf": round(cf_by_period.get(period, 0.0), 2),
            })
        return result[-limit:]
