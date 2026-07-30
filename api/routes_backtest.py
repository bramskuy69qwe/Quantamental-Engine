from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.state import app_state
from core.tz import now_in_account_tz
from core.database import db
from core.backtest_runner import BacktestRunner
from core.ohlcv_fetcher import OHLCVFetcher

log = logging.getLogger("routes.backtest")
router = APIRouter()

# In-memory job state — lives for the process lifetime
_backtest_tasks: Dict[int, asyncio.Task] = {}
_fetch_jobs: Dict[int, Dict[str, Any]] = {}
_fetch_job_counter = 0

# HIGH-022 (Task 97): cap on backtest date range. 1 year of crypto-futures
# OHLCV at 1-minute granularity = ~525k bars per symbol; multi-year crafted
# requests can exhaust memory before BacktestRunner aborts. Cap matches
# typical strategy-research horizons; can be raised via env if needed.
MAX_BACKTEST_DURATION_DAYS = 365
MIN_BACKTEST_DURATION_DAYS = 1


def _validate_date_range(date_from: str, date_to: str) -> Optional[str]:
    """HIGH-022 validation helper. Returns None if valid, else an error string.

    Accepts ISO-8601 date strings (`YYYY-MM-DD`). Empty strings short-circuit
    to None (caller decides whether empty is acceptable — backtest submission
    requires both fields; the retired Quantower importer treated them as
    metadata, which is why the empty lane exists).
    """
    if not date_from or not date_to:
        return None
    try:
        d_from = datetime.fromisoformat(date_from).date()
        d_to = datetime.fromisoformat(date_to).date()
    except (TypeError, ValueError):
        return f"invalid date format (expected YYYY-MM-DD): from={date_from!r}, to={date_to!r}"
    if d_to < d_from:
        return f"date_to ({date_to}) must be >= date_from ({date_from})"
    span = d_to - d_from
    if span < timedelta(days=MIN_BACKTEST_DURATION_DAYS):
        return (
            f"date range must span at least {MIN_BACKTEST_DURATION_DAYS} day "
            f"(got {span.days})"
        )
    if span > timedelta(days=MAX_BACKTEST_DURATION_DAYS):
        return (
            f"date range exceeds maximum {MAX_BACKTEST_DURATION_DAYS} days "
            f"(got {span.days})"
        )
    return None


# (Jinja retirement 2026-07-30: GET /backtest + backtest.html retired — the
# React Models workbench carries backtests. Fragments slim-down 2026-07-30:
# the two /fragments/backtest/* doors are DELETED — nothing consumed them.
# The /api/backtest/* JSON routes below SURVIVE.)


@router.post("/api/backtest/fetch-ohlcv", response_class=JSONResponse)
async def api_fetch_ohlcv(request: Request):
    """Trigger background OHLCV ingestion. Body: {symbols, timeframe, days}. Returns {job_id}."""
    global _fetch_job_counter

    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    # Task D fold (F16-residual class sweep): a valid-JSON non-dict body
    # (list/string/number) previously 500'd at body.get below.
    if not isinstance(body, dict):
        return JSONResponse(
            {"error": "Body must be a JSON object"}, status_code=400)

    symbols   = body.get("symbols", [])
    timeframe = body.get("timeframe", "4h")
    days      = int(body.get("days", 365))

    if not symbols:
        return JSONResponse({"error": "No symbols provided"}, status_code=400)

    _fetch_job_counter += 1
    job_id = _fetch_job_counter
    job: Dict[str, Any] = {
        "status": "running", "symbols": symbols, "timeframe": timeframe,
        "days": days, "detail": f"Starting fetch for {len(symbols)} symbol(s)…", "results": {},
    }
    _fetch_jobs[job_id] = job

    async def _run():
        from core.exchange import _get_adapter
        fetcher = OHLCVFetcher(adapter=_get_adapter())
        try:
            for i, sym in enumerate(symbols):
                job["detail"] = f"Fetching {sym} ({i + 1}/{len(symbols)})…"
                count = await fetcher.fetch_and_store(sym, timeframe, days)
                job["results"][sym] = count
            job["status"] = "completed"
            total = sum(job["results"].values())
            job["detail"] = f"Done — {total} candles across {len(symbols)} symbol(s)"
        except Exception as exc:
            job["status"] = "failed"
            job["detail"] = str(exc)

    asyncio.create_task(_run())
    return JSONResponse({"status": "started", "job_id": job_id, "symbols": symbols,
                         "timeframe": timeframe, "days": days})


@router.get("/api/backtest/fetch-status/{job_id}", response_class=JSONResponse)
async def api_fetch_status(job_id: int):
    job = _fetch_jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return JSONResponse({
        "job_id": job_id, "status": job["status"],
        "detail": job["detail"], "results": job["results"],
    })


@router.post("/api/backtest/run", response_class=JSONResponse)
async def api_backtest_run(request: Request):
    """Start a backtest session. Body: strategy config dict. Returns {session_id}."""
    try:
        cfg = await request.json()
    except ValueError:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    # Task D fold (F16-residual class sweep): non-dict body → 400, not a
    # 500 at cfg.get below.
    if not isinstance(cfg, dict):
        return JSONResponse(
            {"error": "Body must be a JSON object"}, status_code=400)

    name       = cfg.get("name", f"Backtest {now_in_account_tz(app_state.active_account_id).strftime('%Y-%m-%d %H:%M')}")
    date_from  = cfg.get("date_from", "")
    date_to    = cfg.get("date_to", "")
    # HIGH-022: bound the date range before scheduling the runner.
    err = _validate_date_range(date_from, date_to)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    session_id = await db.create_backtest_session(
        name=name, session_type="macro", date_from=date_from, date_to=date_to, config=cfg,
    )

    async def _run_backtest():
        runner = BacktestRunner(cfg)
        try:
            await runner.run(session_id)
        except Exception as exc:
            log.error("Backtest session %d failed: %s", session_id, exc)
            await db.finish_backtest_session(session_id, "failed", {"error": str(exc)})
        finally:
            _backtest_tasks.pop(session_id, None)

    task = asyncio.create_task(_run_backtest())
    _backtest_tasks[session_id] = task
    return JSONResponse({"session_id": session_id, "status": "running"})


@router.get("/api/backtest/sessions", response_class=JSONResponse)
async def api_backtest_sessions():
    sessions = await db.list_backtest_sessions(limit=50)
    for s in sessions:
        s.pop("config_json", None)
    return JSONResponse(sessions)


@router.get("/api/backtest/sessions/{session_id}", response_class=JSONResponse)
async def api_backtest_session_detail(session_id: int):
    session = await db.get_backtest_session(session_id)
    if not session:
        return JSONResponse({"error": "Not found"}, status_code=404)
    trades = await db.get_backtest_trades(session_id)
    equity = await db.get_backtest_equity(session_id)
    session.pop("config_json", None)
    return JSONResponse({"session": session, "trades": trades, "equity": equity})


@router.delete("/api/backtest/sessions/{session_id}", response_class=JSONResponse)
async def api_backtest_session_delete(session_id: int):
    task = _backtest_tasks.get(session_id)
    if task and not task.done():
        task.cancel()
        _backtest_tasks.pop(session_id, None)
    await db.delete_backtest_session(session_id)
    return JSONResponse({"status": "deleted"})


# v2.7 Phase 6 (task 6.1): the Quantower BACKTEST-RESULTS JSON importer
# route (landmine L5 — a JSON upload, NOT the v2.6-removed plugin) was
# retired here, superseded by the model library's per-app adapter upload
# (POST /models/{model_id}/backtest-upload). Historical sessions it created
# (type='microstructure', config/summary source 'quantower') remain in
# backtest_sessions, readable via the /api/backtest/* JSON routes (their
# Jinja renderer, fragments/backtest/results.html, retired with the
# fragments slim-down 2026-07-30).
