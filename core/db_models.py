from __future__ import annotations

import json as _json
import logging
from typing import Any, Dict, Iterable, List, Optional

log = logging.getLogger("database")


def _decode_model_row(row) -> Dict[str, Any]:
    """dict(row) with the JSON columns decoded (config/risk_preset/strategy
    + the v3.0 P7 source/tags)."""
    d = dict(row)
    d["config"] = _json.loads(d.get("config_json") or "{}")
    d["risk_preset"] = _json.loads(d.get("risk_preset_json") or "{}")
    d["strategy"] = _json.loads(d.get("strategy_json") or "{}")
    d["source"] = _json.loads(d.get("source_json") or "{}")
    d["tags"] = _json.loads(d.get("tags_json") or "[]")
    return d


class ModelsMixin:
    """potential_models domain methods (+ v2.7 model-library helpers)."""

    async def create_potential_model(
        self, name: str, model_type: str, description: str, config: Dict[str, Any],
        risk_preset: Optional[Dict[str, Any]] = None,
        strategy: Optional[Dict[str, Any]] = None,
        source: Optional[Dict[str, Any]] = None,
        tags: Optional[list] = None,
    ) -> int:
        """Insert a new potential_models row; return new id.

        risk_preset / strategy (v2.7) and source / tags (v3.0 P7 G-M4)
        are optional — omitted writes '{}'/'[]' so earlier callers are
        unchanged. updated_at stays NULL on create (NULL = never
        updated; update_potential_model stamps it).
        """
        async with self._conn.execute(
            """INSERT INTO potential_models
               (name, type, description, config_json, risk_preset_json,
                strategy_json, source_json, tags_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, model_type, description, _json.dumps(config),
             _json.dumps(risk_preset or {}), _json.dumps(strategy or {}),
             _json.dumps(source or {}), _json.dumps(tags or [])),
        ) as cur:
            new_id = cur.lastrowid
        await self._conn.commit()
        return new_id

    async def list_potential_models(self) -> List[Dict[str, Any]]:
        """Return all potential_models rows, newest first, with JSON decoded."""
        async with self._conn.execute(
            "SELECT * FROM potential_models ORDER BY id DESC"
        ) as cur:
            rows = await cur.fetchall()
        return [_decode_model_row(row) for row in rows]

    async def get_potential_model(self, model_id: int) -> Optional[Dict[str, Any]]:
        """Return a single potential_models row by id, or None."""
        async with self._conn.execute(
            "SELECT * FROM potential_models WHERE id=?", (model_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return _decode_model_row(row)

    async def update_potential_model(
        self, model_id: int, name: str, model_type: str,
        description: str, config: Dict[str, Any],
        risk_preset: Optional[Dict[str, Any]] = None,
        strategy: Optional[Dict[str, Any]] = None,
        source: Optional[Dict[str, Any]] = None,
        tags: Optional[list] = None,
    ) -> None:
        """Overwrite name/type/description/config; stamp updated_at.

        risk_preset / strategy / source / tags: None = leave the stored
        value untouched (earlier callers don't pass them); a value
        overwrites.
        """
        sets = ["name=?", "type=?", "description=?", "config_json=?",
                "updated_at=datetime('now')"]
        params: List[Any] = [name, model_type, description, _json.dumps(config)]
        if risk_preset is not None:
            sets.append("risk_preset_json=?")
            params.append(_json.dumps(risk_preset))
        if strategy is not None:
            sets.append("strategy_json=?")
            params.append(_json.dumps(strategy))
        if source is not None:
            sets.append("source_json=?")
            params.append(_json.dumps(source))
        if tags is not None:
            sets.append("tags_json=?")
            params.append(_json.dumps(tags))
        params.append(model_id)
        await self._conn.execute(
            f"UPDATE potential_models SET {', '.join(sets)} WHERE id=?",
            params,
        )
        await self._conn.commit()

    async def delete_potential_model(self, model_id: int) -> None:
        """Delete a model AND its imported backtest runs.

        The backtest_sessions delete relies on ON DELETE CASCADE to clear
        backtest_trades/backtest_equity children — true on this
        connection (PRAGMA foreign_keys=ON in initialize()); raw
        sqlite3.connect() scripts touching backtest_sessions must set the
        pragma themselves. pre_trade_log.model_id /
        closed_positions.model_id then dangle BY DESIGN (no REFERENCES —
        cross-file FK impossible); readers LEFT JOIN with a
        "(deleted model)" fallback (see get_model_for_calc).
        """
        await self._conn.execute(
            "DELETE FROM backtest_sessions WHERE model_id=?", (model_id,)
        )
        await self._conn.execute(
            "DELETE FROM potential_models WHERE id=?", (model_id,)
        )
        await self._conn.commit()

    # ── v2.7 Phase 1: imported backtest runs (reuse backtest_* tables) ──────

    async def create_model_backtest(
        self, model_id: int, source_app: str, normalized: Dict[str, Any],
        report: Optional[Dict[str, Any]] = None,
    ) -> int:
        """One-path import: session + trades + equity + finish.

        ``normalized`` is the adapter output (v2.7 plan §2.1 shape):
        {session_name, summary: dict, trades: [dict], equity_curve:
        [dict]}. date_from/date_to come from summary.period_start/_end.
        ``report`` (v3.0 P7 G-M1) is the verbatim workbook capture,
        stored in report_json; None leaves the '{}' default (legacy
        callers / apps without a capture lane).
        Returns the new backtest_sessions id (status 'completed').

        Transactional shape (v2.7 Task C, audit F9): the four steps
        commit INDEPENDENTLY on the shared conn — deliberate. An explicit
        BEGIN..COMMIT would risk nested-transaction errors the moment an
        interleaved writer commits (single shared aiosqlite conn, no
        isolation-level override). The failure lanes are covered instead:
        in-process failure → the except below deletes the session
        (CASCADE clears children); process DEATH mid-import → the
        initialize() boot sweep marks the orphaned 'running' session
        'failed' (rendered as FAILED in the run list).
        """
        summary = normalized.get("summary") or {}
        session_id = await self.create_backtest_session(
            name=normalized.get("session_name") or f"{source_app} import",
            session_type="imported",
            date_from=str(summary.get("period_start") or ""),
            date_to=str(summary.get("period_end") or ""),
            config={},
            model_id=model_id,
            source_app=source_app,
        )
        try:
            await self.insert_backtest_trades(
                session_id, normalized.get("trades") or []
            )
            await self.insert_backtest_equity(
                session_id, normalized.get("equity_curve") or []
            )
            if report is not None:
                await self._conn.execute(
                    "UPDATE backtest_sessions SET report_json=? WHERE id=?",
                    (_json.dumps(report), session_id),
                )
                await self._conn.commit()
            await self.finish_backtest_session(session_id, "completed", summary)
        except Exception:
            # No phantom 'running' rows: a mid-import failure (e.g. an
            # equity point missing dt/equity/drawdown — that insert is
            # non-tolerant) deletes the session (CASCADE clears partial
            # trades/equity) and re-raises for the caller's error surface
            # (Phase-3 upload route renders the error fragment).
            await self._conn.execute(
                "DELETE FROM backtest_sessions WHERE id=?", (session_id,)
            )
            await self._conn.commit()
            raise
        return session_id

    # Run-list / overview column set — deliberately EXCLUDES report_json:
    # the verbatim capture can be hundreds of KB and belongs only to the
    # single-run report fetch (get_model_backtest_report).
    _RUN_LIST_COLS = (
        "id, created_at, name, type, status, date_from, date_to, "
        "config_json, summary_json, model_id, source_app"
    )

    async def list_model_backtests(self, model_id: int) -> List[Dict[str, Any]]:
        """All imported runs for a model, newest first, JSON decoded
        (WITHOUT the verbatim report_json — see _RUN_LIST_COLS)."""
        async with self._conn.execute(
            f"SELECT {self._RUN_LIST_COLS} FROM backtest_sessions "
            "WHERE model_id=? ORDER BY id DESC",
            (model_id,),
        ) as cur:
            rows = await cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["config"] = _json.loads(d.get("config_json") or "{}")
            d["summary"] = _json.loads(d.get("summary_json") or "{}")
            result.append(d)
        return result

    # ── v3.0 P7: report fetch / overview feed / usage reverse feed ──────────

    async def get_model_backtest_report(
        self, model_id: int, run_id: int,
    ) -> Optional[Dict[str, Any]]:
        """One imported run WITH its verbatim capture + equity + trades
        (G-M1). None when the run doesn't exist or belongs to another
        model (the caller 404s — never leak a cross-model run)."""
        async with self._conn.execute(
            "SELECT * FROM backtest_sessions WHERE id=? AND model_id=?",
            (run_id, model_id),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["config"] = _json.loads(d.get("config_json") or "{}")
        d["summary"] = _json.loads(d.get("summary_json") or "{}")
        report = _json.loads(d.pop("report_json", None) or "{}")
        d.pop("config_json", None)
        d.pop("summary_json", None)
        equity = await self.get_backtest_equity(run_id)
        trades = await self.get_backtest_trades(run_id)
        return {
            "run": d,
            # '{}' (engine-run / pre-P7 import) → None: the UI keys its
            # "no verbatim capture" fallback on null, not shape-sniffing.
            # isinstance guard (P7 audit NIT): corrupt local state (a
            # non-dict report_json) degrades to null, never 500s.
            "report": report if isinstance(report, dict) and report.get("sheets") else None,
            "equity": equity,
            "trades": trades,
        }

    async def list_models_overview(self, spark_points: int = 48) -> List[Dict[str, Any]]:
        """The library/overview feed (G-M3): every model with its
        latest COMPLETED imported run's summary + a downsampled equity
        sparkline + runs_count — batched (4 queries total), no N+1.
        """
        models = await self.list_potential_models()
        if not models:
            return []
        # Latest completed run + total runs per model, one scan.
        async with self._conn.execute(
            "SELECT model_id, MAX(id) AS latest_id, COUNT(*) AS n "
            "FROM backtest_sessions "
            "WHERE model_id IS NOT NULL AND status='completed' "
            "GROUP BY model_id"
        ) as cur:
            agg = {r["model_id"]: (r["latest_id"], r["n"]) for r in await cur.fetchall()}
        latest_ids = [v[0] for v in agg.values()]
        runs: Dict[int, Dict[str, Any]] = {}
        if latest_ids:
            ph = ",".join("?" * len(latest_ids))
            async with self._conn.execute(
                f"SELECT {self._RUN_LIST_COLS} FROM backtest_sessions "
                f"WHERE id IN ({ph})",
                latest_ids,
            ) as cur:
                for r in await cur.fetchall():
                    d = dict(r)
                    d["summary"] = _json.loads(d.get("summary_json") or "{}")
                    d.pop("summary_json", None)
                    d.pop("config_json", None)
                    runs[d["id"]] = d
            # Equity for all latest runs in one scan; stride-downsample
            # per run to <= spark_points (keep first + last).
            eq: Dict[int, List[float]] = {}
            async with self._conn.execute(
                f"SELECT session_id, equity FROM backtest_equity "
                f"WHERE session_id IN ({ph}) ORDER BY session_id, dt ASC",
                latest_ids,
            ) as cur:
                for r in await cur.fetchall():
                    eq.setdefault(r["session_id"], []).append(r["equity"])
            for sid, series in eq.items():
                if len(series) > spark_points:
                    step = (len(series) - 1) / (spark_points - 1)
                    series = [series[round(i * step)] for i in range(spark_points)]
                if sid in runs:
                    runs[sid]["spark"] = series
        out = []
        for m in models:
            latest_id, n = agg.get(m["id"], (None, 0))
            run = runs.get(latest_id) if latest_id else None
            out.append({
                **m,
                "runs_count": n,
                "latest_run": run,
                "spark": (run or {}).pop("spark", []) if run else [],
            })
        return out

    async def get_model_usage(
        self, model_id: int, closed_limit: int = 100, plan_limit: int = 50,
    ) -> Dict[str, Any]:
        """Reverse attribution feed (G-M6): closed positions + pre-trade
        plans tagged with this model. Live/open positions are NOT
        queried server-side (no durable open-position model_id source;
        they appear here once closed — named P7 deviation)."""
        async with self._conn.execute(
            "SELECT id, terminal_position_id, symbol, direction, quantity, "
            "net_pnl, realized_pnl, entry_time_ms, exit_time_ms "
            "FROM closed_positions WHERE model_id=? "
            "ORDER BY exit_time_ms DESC LIMIT ?",
            (model_id, closed_limit),
        ) as cur:
            closed = [dict(r) for r in await cur.fetchall()]
        async with self._conn.execute(
            "SELECT id, calc_id, ticker, side, timestamp, status "
            "FROM pre_trade_log WHERE model_id=? "
            "ORDER BY id DESC LIMIT ?",
            (model_id, plan_limit),
        ) as cur:
            plans = [dict(r) for r in await cur.fetchall()]
        return {"closed": closed, "plans": plans}

    async def seed_model_source_if_empty(
        self, model_id: int, source: Dict[str, Any],
    ) -> bool:
        """§6-3b auto-seed: write the import-derived source binding ONLY
        when the model has none — an operator-entered source is never
        overwritten by an upload. True when the seed was applied."""
        if not source:
            return False
        async with self._conn.execute(
            "UPDATE potential_models SET source_json=? "
            "WHERE id=? AND (source_json IS NULL OR source_json='' "
            "OR source_json='{}')",
            (_json.dumps(source), model_id),
        ) as cur:
            seeded = bool(cur.rowcount)
        await self._conn.commit()
        return seeded

    async def get_model_names_by_ids(
        self, model_ids: Iterable[int],
    ) -> Dict[int, str]:
        """{model_id: name} batch lookup for FK renderers (v2.7 Task D/F11).

        Missing ids are simply absent — the FK policy is FK-in-name-only
        (ids dangle by design after a model delete), so callers render
        "(deleted model)" for ids not in the result. Empty input → {}.
        Non-coercible ids are skipped (audit fold: a type-corrupted
        model_id must degrade to the visible "(deleted model)" render,
        not 500 the whole fragment at int()).
        """
        ids = []
        for i in model_ids:
            if i is None:
                continue
            try:
                ids.append(int(i))
            except (TypeError, ValueError):
                continue
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        async with self._conn.execute(
            f"SELECT id, name FROM potential_models WHERE id IN ({placeholders})",
            ids,
        ) as cur:
            rows = await cur.fetchall()
        return {row["id"]: row["name"] for row in rows}

    async def get_model_stamp_for_calc(self, calc_id: str) -> Optional[Dict[str, Any]]:
        """(model_id, model_name) close-row stamp from a calc's
        pre_trade_log row (v2.7 plan 5.4).

        model_name resolution: the row's own free text wins (the operator
        typed it at plan time); when empty and the row carries model_id,
        fall back to the library name via get_model_for_calc (which
        handles the dangling-id "(deleted model)" case). Returns None
        when the calc is unknown / empty — callers keep their legacy
        fallback (the close path's shortfall heuristic).
        """
        if not calc_id:
            return None
        async with self._conn.execute(
            "SELECT model_id, model_name FROM pre_trade_log "
            "WHERE calc_id=? ORDER BY id DESC LIMIT 1",
            (calc_id,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        model_id, free_text = row[0], row[1] or ""
        name = free_text
        if not name and model_id is not None:
            res = await self.get_model_for_calc(calc_id)
            name = res["name"] if res else ""
        if model_id is None and not name:
            # Newest row is untagged AND unnamed — align with the sibling's
            # dedup rule (newest TAGGED row wins over a newer untagged one)
            # before giving up (P5 audit NIT-6).
            res = await self.get_model_for_calc(calc_id)
            if res:
                return {"model_id": res["model_id"], "model_name": res["name"]}
            return None
        return {"model_id": model_id, "model_name": name}

    async def get_model_for_calc(self, calc_id: str) -> Optional[Dict[str, Any]]:
        """Resolve the model tagged on a calc's pre_trade_log row.

        Plain lookup by calc_id — callers resolving a POSITION must pick
        the calc via PositionIdentity.position_primary_calc first (the
        summed-contribution / unsealed-first rule); do NOT join
        positions_calcs here (v2.7 plan §2: a naive junction join
        mis-attributes on scale-ins and reused tpids).

        Returns {"model_id", "name"} — name falls back to
        "(deleted model)" when the id dangles (FK-in-name-only, §2 FK
        policy) — or None when the calc has no row / no model tag.
        Duplicate calc_id rows: the newest TAGGED row wins (untagged
        rows are filtered out, so an older tagged row beats a newer
        untagged one).
        """
        if not calc_id:
            return None
        async with self._conn.execute(
            """SELECT p.model_id AS model_id, m.name AS model_name
               FROM pre_trade_log p
               LEFT JOIN potential_models m ON m.id = p.model_id
               WHERE p.calc_id=? AND p.model_id IS NOT NULL
               ORDER BY p.id DESC LIMIT 1""",
            (calc_id,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        name = row["model_name"]
        return {
            "model_id": row["model_id"],
            "name": name if name is not None else "(deleted model)",
        }
