from __future__ import annotations

import json as _json
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("database")


class BacktestMixin:
    """backtest_sessions, backtest_trades, backtest_equity domain methods."""

    async def create_backtest_session(
        self, name: str, session_type: str,
        date_from: str, date_to: str, config: Dict[str, Any],
        model_id: Optional[int] = None, source_app: str = "",
    ) -> int:
        """Insert a new backtest_sessions row; return new id.

        model_id / source_app (v2.7): set on imported 3rd-party runs
        (via db_models.create_model_backtest); engine-run sessions leave
        the defaults (model_id NULL).
        """
        async with self._conn.execute(
            """INSERT INTO backtest_sessions
               (name, type, status, date_from, date_to, config_json, model_id, source_app)
               VALUES (?, ?, 'running', ?, ?, ?, ?, ?)""",
            (name, session_type, date_from, date_to, _json.dumps(config),
             model_id, source_app),
        ) as cur:
            new_id = cur.lastrowid
        await self._conn.commit()
        return new_id

    async def finish_backtest_session(
        self, session_id: int, status: str, summary: Dict[str, Any]
    ) -> None:
        """Set final status and summary_json on a backtest session."""
        await self._conn.execute(
            "UPDATE backtest_sessions SET status=?, summary_json=? WHERE id=?",
            (status, _json.dumps(summary), session_id),
        )
        await self._conn.commit()

    # ── Route-orphaned trio (get/list/delete session) ─────────────────────
    # The backtest-runner retirement (2026-08-04, operator decision) removed
    # their only prod callers (api/routes_backtest.py). KEPT deliberately:
    # the table still holds real engine-run + historical Quantower
    # ('microstructure') rows — those rows are now UNREADABLE through any
    # door until a reader is added (recorded, not accidental). The import
    # lane's own tests use GET and LIST as fixtures for the
    # model_id-IS-NULL filtering; DELETE has zero callers of any kind and
    # survives purely on the table-level-API convention (audit-precise:
    # the first draft said "these methods" for all three). Same convention
    # as insert_trade_history / insert_position_changes.

    async def get_backtest_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        """Return a backtest_sessions row with decoded config/summary dicts, or None."""
        async with self._conn.execute(
            "SELECT * FROM backtest_sessions WHERE id=?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["config"] = _json.loads(d.get("config_json") or "{}")
        d["summary"] = _json.loads(d.get("summary_json") or "{}")
        return d

    async def list_backtest_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return up to limit ENGINE-RUN sessions, newest first, decoded.

        v2.7 (plan task 1.8): imported model runs (model_id IS NOT NULL)
        are excluded — they render only in the model library. The Backtest
        tab's templates read summary keys imported runs don't carry
        (total_return_pct, r_stats.*, sortino) and treat max_drawdown as a
        fraction, so surfacing them here would render zeros / garbage.
        Use db_models.list_model_backtests(model_id) for imported runs.
        """
        async with self._conn.execute(
            "SELECT * FROM backtest_sessions WHERE model_id IS NULL "
            "ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["config"] = _json.loads(d.get("config_json") or "{}")
            d["summary"] = _json.loads(d.get("summary_json") or "{}")
            result.append(d)
        return result

    async def delete_backtest_session(self, session_id: int) -> None:
        """Delete a backtest session and all its associated trades and equity rows."""
        await self._conn.execute("DELETE FROM backtest_sessions WHERE id=?", (session_id,))
        await self._conn.commit()

    async def insert_backtest_trades(self, session_id: int, trades: List[Dict[str, Any]]) -> None:
        """Bulk-insert backtest_trades rows for a session."""
        rows = [
            (
                session_id,
                t.get("symbol", ""),
                t.get("side", ""),
                t.get("entry_dt", ""),
                t.get("exit_dt", ""),
                float(t.get("entry_price", 0)),
                float(t.get("exit_price", 0)),
                float(t.get("size_usdt", 0)),
                float(t.get("contracts", 0)),
                float(t.get("r_multiple", 0)),
                float(t.get("pnl_usdt", 0)),
                t.get("regime_label", ""),
                t.get("exit_reason", ""),
            )
            for t in trades
        ]
        if not rows:
            return
        await self._conn.executemany(
            """INSERT INTO backtest_trades
               (session_id, symbol, side, entry_dt, exit_dt, entry_price, exit_price,
                size_usdt, contracts, r_multiple, pnl_usdt, regime_label, exit_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        await self._conn.commit()

    async def get_backtest_trades(self, session_id: int) -> List[Dict[str, Any]]:
        """Return all backtest_trades rows for a session, ordered by entry date."""
        async with self._conn.execute(
            "SELECT * FROM backtest_trades WHERE session_id=? ORDER BY entry_dt ASC",
            (session_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def insert_backtest_equity(self, session_id: int, curve: List[Dict[str, Any]]) -> None:
        """Bulk-insert equity curve rows for a session (each with dt, equity, drawdown)."""
        rows = [(session_id, p["dt"], float(p["equity"]), float(p["drawdown"])) for p in curve]
        if not rows:
            return
        await self._conn.executemany(
            "INSERT INTO backtest_equity (session_id, dt, equity, drawdown) VALUES (?, ?, ?, ?)",
            rows,
        )
        await self._conn.commit()

    async def get_backtest_equity(self, session_id: int) -> List[Dict[str, Any]]:
        """Return equity curve rows for a session, ordered chronologically."""
        async with self._conn.execute(
            "SELECT dt, equity, drawdown FROM backtest_equity WHERE session_id=? ORDER BY dt ASC",
            (session_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
