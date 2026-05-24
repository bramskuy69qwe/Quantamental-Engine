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
