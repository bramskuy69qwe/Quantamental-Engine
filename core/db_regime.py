from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("database")


class RegimeMixin:
    """regime_signals + regime_labels domain methods."""

    async def upsert_regime_signals(
        self, signal_name: str, rows: List[Dict[str, Any]], source: str = "",
    ) -> int:
        """Bulk upsert regime signal values. rows: [{"date": "YYYY-MM-DD", "value": float}, ...]"""
        if not rows:
            return 0
        await self._conn.executemany(
            """INSERT INTO regime_signals (signal_name, date, value, source, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(signal_name, date)
               DO UPDATE SET value=excluded.value, source=excluded.source, updated_at=excluded.updated_at""",
            [(signal_name, r["date"], r["value"], source) for r in rows],
        )
        await self._conn.commit()
        return len(rows)

    async def get_regime_signals(
        self, signal_names: List[str], from_date: str = "", to_date: str = "",
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Return {signal_name: [{date, value}, ...]} grouped and sorted by date ASC."""
        if not signal_names:
            return {}
        placeholders = ",".join("?" for _ in signal_names)
        query = f"SELECT signal_name, date, value FROM regime_signals WHERE signal_name IN ({placeholders})"
        params: list = list(signal_names)
        if from_date:
            query += " AND date >= ?"
            params.append(from_date)
        if to_date:
            query += " AND date <= ?"
            params.append(to_date)
        query += " ORDER BY date ASC"
        async with self._conn.execute(query, params) as cur:
            rows = await cur.fetchall()
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row[0], []).append({"date": row[1], "value": float(row[2])})
        return grouped

    async def get_regime_signal_range(self, signal_name: str) -> Dict[str, Any]:
        """Return {min_date, max_date, count} for a given signal."""
        async with self._conn.execute(
            "SELECT MIN(date), MAX(date), COUNT(*) FROM regime_signals WHERE signal_name=?",
            (signal_name,),
        ) as cur:
            row = await cur.fetchone()
        if not row or row[2] == 0:
            return {"min_date": None, "max_date": None, "count": 0}
        return {"min_date": row[0], "max_date": row[1], "count": row[2]}

    async def get_all_signal_coverage(self) -> List[Dict[str, Any]]:
        """Return per-signal coverage: [{signal_name, source, min_date, max_date, count}]."""
        async with self._conn.execute(
            """SELECT signal_name, source, MIN(date), MAX(date), COUNT(*)
               FROM regime_signals GROUP BY signal_name ORDER BY signal_name"""
        ) as cur:
            rows = await cur.fetchall()
        return [
            {"signal_name": r[0], "source": r[1], "min_date": r[2], "max_date": r[3], "count": r[4]}
            for r in rows
        ]

    async def upsert_regime_labels(self, rows: List[Dict[str, Any]]) -> int:
        """Bulk upsert classified regime labels. rows: [{"date", "label", "mode", "signals_json"}]."""
        import json as _json
        if not rows:
            return 0
        await self._conn.executemany(
            """INSERT INTO regime_labels (date, label, mode, signals_json, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(date)
               DO UPDATE SET label=excluded.label, mode=excluded.mode,
                             signals_json=excluded.signals_json, updated_at=excluded.updated_at""",
            [(r["date"], r["label"], r.get("mode", "full"),
              _json.dumps(r.get("signals", {})) if isinstance(r.get("signals"), dict) else r.get("signals_json", "{}"))
             for r in rows],
        )
        await self._conn.commit()
        return len(rows)

    async def get_regime_labels(
        self, from_date: str = "", to_date: str = "",
    ) -> List[Dict[str, Any]]:
        """Return regime labels sorted by date ASC."""
        import json as _json
        query = "SELECT date, label, mode, signals_json FROM regime_labels WHERE 1=1"
        params: list = []
        if from_date:
            query += " AND date >= ?"
            params.append(from_date)
        if to_date:
            query += " AND date <= ?"
            params.append(to_date)
        query += " ORDER BY date ASC"
        async with self._conn.execute(query, params) as cur:
            rows = await cur.fetchall()
        return [
            {"date": r[0], "label": r[1], "mode": r[2], "signals": _json.loads(r[3] or "{}")}
            for r in rows
        ]

    async def get_latest_regime_label(self) -> Optional[Dict[str, Any]]:
        """Return the most recent regime label, or None."""
        import json as _json
        async with self._conn.execute(
            "SELECT date, label, mode, signals_json FROM regime_labels ORDER BY date DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return {"date": row[0], "label": row[1], "mode": row[2], "signals": _json.loads(row[3] or "{}")}

    async def get_recent_regime_labels(self, n: int = 30) -> List[Dict[str, Any]]:
        """Return the N most recent regime labels, sorted date DESC."""
        async with self._conn.execute(
            "SELECT date, label FROM regime_labels ORDER BY date DESC LIMIT ?", (n,)
        ) as cur:
            rows = await cur.fetchall()
        return [{"date": r[0], "label": r[1]} for r in rows]

    async def get_all_regime_labels(self) -> List[Dict[str, Any]]:
        """Return all regime labels sorted date ASC — used for transition matrix."""
        async with self._conn.execute(
            "SELECT date, label FROM regime_labels ORDER BY date ASC"
        ) as cur:
            rows = await cur.fetchall()
        return [{"date": r[0], "label": r[1]} for r in rows]

    async def delete_regime_labels(self, from_date: str = "", to_date: str = "") -> int:
        """Delete regime labels in a date range (for reclassification). Returns count deleted."""
        query = "DELETE FROM regime_labels WHERE 1=1"
        params: list = []
        if from_date:
            query += " AND date >= ?"
            params.append(from_date)
        if to_date:
            query += " AND date <= ?"
            params.append(to_date)
        async with self._conn.execute(query, params) as cur:
            count = cur.rowcount
        await self._conn.commit()
        return count

    # ── Task 167: forward two-track (dual-P&L) ──────────────────────────────
    #
    # Per-trade dual-P&L is the forward arm of the regime-validation
    # mechanism described in v2.5_regime-plan.md. For each closed trade
    # joined to its plan-time pre_trade_log row, report:
    #
    #   actual_pnl         — closed_positions.net_pnl as realised
    #   regime_multiplier  — AS-APPLIED effective value at trade plan
    #                        time (post-toggle, post-stale; persisted
    #                        by T157+T165 from risk_engine.run_risk_
    #                        calculator)
    #   x1_pnl             — net_pnl / regime_multiplier (the
    #                        counterfactual: what the same trade would
    #                        have made under x1 sizing — i.e. with the
    #                        regime multiplier disabled)
    #   delta              — actual - x1 (positive = regime sizing
    #                        helped; negative = regime sizing cost)
    #
    # Linear-scaling assumption: P&L ∝ size at retail volume. Realised
    # P&L = (exit - entry) × quantity × direction-sign — linear in
    # quantity. Maker / taker fees = fee_rate × notional → linear in
    # quantity. Funding fees are also linear. The one nonlinearity is
    # slippage: larger trades eat more book depth, so slippage is
    # super-linear in size. At retail crypto volume this is a small
    # second-order effect; the regime-plan accepts this caveat
    # explicitly.
    #
    # Exclusions enforced in the query (not Python — keep the
    # division-safe contract local to the SQL):
    #   • regime_multiplier IS NULL  → pre-T157 row, decision
    #                                   unrecorded; can't compute x1.
    #   • regime_multiplier <= 0     → invalid (multiplier should never
    #                                   be 0 or negative; if it is,
    #                                   exclude to protect downstream
    #                                   division).
    #   • calc_id IS NULL/empty      → trade not linked to a calc
    #                                   (manual entry, pre-T87, etc.).
    #
    # Toggle-OFF (apply_regime_multiplier=0): regime_multiplier=1.0
    # was already forced by risk_engine. x1 = actual / 1.0 = actual.
    # Same result for stale-fallback (regime_stale=1, multiplier=1.0)
    # and for genuinely-neutral readings. These rows are INCLUDED in
    # the two-track but their delta is 0 by construction — distinguish
    # via the apply_regime_multiplier + regime_stale flags carried
    # alongside.

    async def get_dual_pnl_trades(
        self,
        account_id: int = 1,
        from_ms: int = 0,
        to_ms: int = 9_999_999_999_000,
    ) -> List[Dict[str, Any]]:
        """Per-trade dual-P&L over closed positions joined to plan-time
        regime decisions. Returns rows sorted exit_time_ms ASC.

        Each row carries the actual P&L, the inferred x1-counterfactual
        P&L (= actual / regime_multiplier under linear-scaling), the
        delta (actual - x1), and the regime flags so analytics can
        bucket / filter without re-querying.
        """
        rows: List[Dict[str, Any]] = []
        async with self._conn.execute(
            """
            SELECT
                cp.calc_id,
                cp.account_id,
                cp.symbol,
                cp.exit_time_ms,
                cp.net_pnl                       AS actual_pnl,
                pt.regime_label,
                pt.regime_multiplier,
                pt.regime_mode,
                pt.apply_regime_multiplier,
                pt.regime_stale
            FROM closed_positions cp
            INNER JOIN pre_trade_log pt
              ON pt.calc_id = cp.calc_id
            WHERE cp.account_id = ?
              AND cp.exit_time_ms BETWEEN ? AND ?
              AND cp.calc_id IS NOT NULL
              AND cp.calc_id != ''
              AND pt.regime_multiplier IS NOT NULL
              AND pt.regime_multiplier > 0
            ORDER BY cp.exit_time_ms ASC
            """,
            (account_id, from_ms, to_ms),
        ) as cur:
            for r in await cur.fetchall():
                actual = float(r[4])
                mult = float(r[6])
                x1 = actual / mult
                rows.append({
                    "calc_id":                  r[0],
                    "account_id":               r[1],
                    "symbol":                   r[2],
                    "exit_time_ms":             r[3],
                    "actual_pnl":               actual,
                    "regime_label":             r[5],
                    "regime_multiplier":        mult,
                    "regime_mode":              r[7],
                    "apply_regime_multiplier":  r[8],
                    "regime_stale":             r[9],
                    "x1_pnl":                   x1,
                    "delta":                    actual - x1,
                })
        return rows

    async def get_dual_pnl_summary(
        self,
        account_id: int = 1,
        from_ms: int = 0,
        to_ms: int = 9_999_999_999_000,
    ) -> Dict[str, Any]:
        """Aggregate the per-trade dual-P&L into a forward-two-track
        summary. Returns:
            n_trades              — eligible trades in window
            actual_total          — sum of actual_pnl
            x1_total              — sum of x1_pnl
            delta_total           — actual_total - x1_total (positive
                                    = regime sizing helped overall)
            n_regime_active       — rows with apply_regime_multiplier=1
                                    AND regime_multiplier != 1.0
            n_neutral_or_off      — rows where actual == x1 by
                                    construction (1.0 / toggle / stale)

        Excludes the same rows the per-trade query excludes (NULL or
        non-positive multiplier; missing calc_id link).
        """
        trades = await self.get_dual_pnl_trades(account_id, from_ms, to_ms)
        if not trades:
            return {
                "n_trades":         0,
                "actual_total":     0.0,
                "x1_total":         0.0,
                "delta_total":      0.0,
                "n_regime_active":  0,
                "n_neutral_or_off": 0,
            }
        actual_total = sum(t["actual_pnl"] for t in trades)
        x1_total     = sum(t["x1_pnl"]     for t in trades)
        n_regime_active = sum(
            1 for t in trades
            if t["apply_regime_multiplier"] == 1
            and t["regime_multiplier"] != 1.0
            and not t["regime_stale"]
        )
        return {
            "n_trades":         len(trades),
            "actual_total":     actual_total,
            "x1_total":         x1_total,
            "delta_total":      actual_total - x1_total,
            "n_regime_active":  n_regime_active,
            "n_neutral_or_off": len(trades) - n_regime_active,
        }
