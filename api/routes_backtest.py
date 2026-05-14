from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from core.state import app_state
from core.tz import now_in_account_tz
from core.database import db
from core.backtest_runner import BacktestRunner
from core.ohlcv_fetcher import OHLCVFetcher
from core import analytics as _an
from api.helpers import templates, _ctx

log = logging.getLogger("routes.backtest")
router = APIRouter()

# In-memory job state — lives for the process lifetime
_backtest_tasks: Dict[int, asyncio.Task] = {}
_fetch_jobs: Dict[int, Dict[str, Any]] = {}
_fetch_job_counter = 0


@router.get("/backtest", response_class=HTMLResponse)
async def backtest_page(request: Request):
    return templates.TemplateResponse(
        request, "backtest.html", _ctx(request, active_page="backtest")
    )


@router.get("/fragments/backtest/sessions", response_class=HTMLResponse)
async def frag_backtest_sessions(request: Request):
    sessions = await db.list_backtest_sessions(limit=30)
    return templates.TemplateResponse(
        request, "fragments/backtest/sessions_list.html",
        _ctx(request, sessions=sessions),
    )


@router.get("/fragments/backtest/results/{session_id}", response_class=HTMLResponse)
async def frag_backtest_results(request: Request, session_id: int):
    session = await db.get_backtest_session(session_id)
    if not session:
        return HTMLResponse("<p class='text-red'>Session not found.</p>", status_code=404)
    trades = await db.get_backtest_trades(session_id)
    equity = await db.get_backtest_equity(session_id)
    return templates.TemplateResponse(
        request, "fragments/backtest/results.html",
        _ctx(request, session=session, trades=trades, equity=equity),
    )


@router.post("/api/backtest/fetch-ohlcv", response_class=JSONResponse)
async def api_fetch_ohlcv(request: Request):
    """Trigger background OHLCV ingestion. Body: {symbols, timeframe, days}. Returns {job_id}."""
    global _fetch_job_counter

    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

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

    name       = cfg.get("name", f"Backtest {now_in_account_tz(app_state.active_account_id).strftime('%Y-%m-%d %H:%M')}")
    date_from  = cfg.get("date_from", "")
    date_to    = cfg.get("date_to", "")
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


@router.post("/api/backtest/qt-import", response_class=JSONResponse)
async def api_qt_import(request: Request):
    """Import Quantower microstructure backtest results."""
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    session_name = body.get("session_name", "Quantower Import")
    date_from    = body.get("date_from", "")
    date_to      = body.get("date_to", "")
    raw_trades   = body.get("trades", [])
    qt_summary   = body.get("summary", {})

    session_id = await db.create_backtest_session(
        name=session_name, session_type="microstructure",
        date_from=date_from, date_to=date_to,
        config={"source": "quantower", "strategy": body.get("strategy", "")},
    )

    trades = [
        {
            "symbol":      t.get("symbol", ""),
            "side":        t.get("side", ""),
            "entry_dt":    t.get("entry_dt", ""),
            "exit_dt":     t.get("exit_dt", ""),
            "entry_price": float(t.get("entry_price", 0)),
            "exit_price":  float(t.get("exit_price", 0)),
            "size_usdt":   float(t.get("size_usdt", 0)),
            "r_multiple":  float(t.get("pnl_r", 0)),
            "pnl_usdt":    float(t.get("pnl_usdt", t.get("size_usdt", 0) * t.get("pnl_r", 0))),
            "regime_label": "",
            "exit_reason": t.get("exit_reason", ""),
        }
        for t in raw_trades
    ]

    r_vals  = [t["r_multiple"] for t in trades]
    r_stats = _an.r_multiple_stats(r_vals)

    summary = {
        "source":           "quantower",
        "total_trades":     len(trades),
        "win_rate":         float(qt_summary.get("win_rate", r_stats.get("win_rate", 0))),
        "total_r":          float(qt_summary.get("total_r", sum(r_vals))),
        "avg_slippage_bps": float(qt_summary.get("avg_slippage_bps", 0)),
        "r_stats":          r_stats,
    }

    await db.insert_backtest_trades(session_id, trades)
    await db.finish_backtest_session(session_id, "completed", summary)
    return JSONResponse({"session_id": session_id, "status": "imported", "trade_count": len(trades)})
