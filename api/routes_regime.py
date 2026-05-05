from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

import config
from core.state import app_state
from core.database import db
from core.regime_fetcher import RegimeFetcher
from core.regime_classifier import classify_range
from api.helpers import templates, _ctx

log = logging.getLogger("routes.regime")
router = APIRouter()

_regime_jobs: Dict[int, Dict[str, Any]] = {}
_regime_job_counter = 0


@router.get("/regime", response_class=HTMLResponse)
async def regime_page(request: Request):
    return templates.TemplateResponse(
        request, "regime.html", _ctx(request, active_page="regime")
    )


@router.get("/api/regime/current", response_class=JSONResponse)
async def api_regime_current():
    regime = app_state.current_regime
    if regime:
        return JSONResponse({
            "label":          regime.label,
            "multiplier":     regime.multiplier,
            "confidence":     regime.confidence,
            "stability_bars": regime.stability_bars,
            "mode":           regime.mode,
            "computed_at":    regime.computed_at.isoformat() if regime.computed_at else None,
            "signals":        regime.signals,
            "source":         "live",
        })
    label = await db.get_latest_regime_label()
    if not label:
        return JSONResponse({"label": None, "multiplier": 1.0, "source": "none"})
    return JSONResponse({
        **label,
        "multiplier": config.REGIME_MULTIPLIERS.get(label["label"], 1.0),
        "source": "db",
    })


@router.get("/api/regime/transitions", response_class=JSONResponse)
async def api_regime_transitions():
    """5×5 regime transition probability matrix from the full regime_labels history."""
    rows = await db.get_all_regime_labels()
    REGIMES = [
        "risk_on_trending", "risk_on_choppy", "neutral",
        "risk_off_defensive", "risk_off_panic",
    ]
    counts: dict = {r: {r2: 0 for r2 in REGIMES} for r in REGIMES}
    for i in range(1, len(rows)):
        frm = rows[i - 1]["label"]
        to  = rows[i]["label"]
        if frm in counts and to in counts[frm]:
            counts[frm][to] += 1
    matrix: dict = {}
    for frm in REGIMES:
        total = sum(counts[frm].values())
        matrix[frm] = {
            to: round(counts[frm][to] / total * 100, 1) if total else 0.0
            for to in REGIMES
        }
    return JSONResponse({"regimes": REGIMES, "matrix": matrix, "total_days": len(rows)})


@router.post("/api/regime/backfill", response_class=JSONResponse)
async def api_regime_backfill(request: Request):
    global _regime_job_counter
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    since_date = body.get("since_date", "2020-01-01")
    until_date = body.get("until_date", datetime.now().strftime("%Y-%m-%d"))
    mode       = body.get("mode", "macro_only")

    _regime_job_counter += 1
    job_id = _regime_job_counter
    job: Dict[str, Any] = {"status": "running", "detail": "Starting backfill...", "pct": 0, "results": {}}
    _regime_jobs[job_id] = job

    async def _run():
        try:
            fetcher = RegimeFetcher()

            async def progress(pct, msg):
                job["pct"] = pct * 0.8
                job["detail"] = msg

            results = await fetcher.fetch_all(since_date, until_date, mode=mode, progress_cb=progress)
            job["results"] = results
            await fetcher.close()

            job["detail"] = "Classifying regimes..."
            job["pct"] = 82

            async def classify_progress(p, m):
                job["pct"] = 82 + p * 0.18
                job["detail"] = m

            count = await classify_range(since_date, until_date, progress_cb=classify_progress)
            job["results"]["labels_classified"] = count
            job["status"] = "completed"
            job["detail"] = f"Done — {count} dates classified"
            job["pct"] = 100
        except Exception as e:
            log.error("Regime backfill failed: %s", e)
            job["status"] = "failed"
            job["detail"] = str(e)

    asyncio.create_task(_run())
    return JSONResponse({"job_id": job_id, "status": "running"})


@router.get("/api/regime/backfill-status/{job_id}", response_class=JSONResponse)
async def api_regime_backfill_status(job_id: int):
    job = _regime_jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return JSONResponse({
        "job_id": job_id, "status": job["status"],
        "detail": job["detail"], "pct": round(job.get("pct", 0), 1),
        "results": job.get("results", {}),
    })


@router.get("/api/regime/timeline", response_class=JSONResponse)
async def api_regime_timeline(from_date: str = "", to_date: str = ""):
    labels = await db.get_regime_labels(from_date, to_date)
    return JSONResponse(labels)


@router.get("/api/regime/signals", response_class=JSONResponse)
async def api_regime_signals(signal_name: str = "", from_date: str = "", to_date: str = ""):
    if not signal_name:
        return JSONResponse({"error": "signal_name required"}, status_code=400)
    data = await db.get_regime_signals([signal_name], from_date, to_date)
    return JSONResponse(data.get(signal_name, []))


@router.get("/api/regime/coverage", response_class=JSONResponse)
async def api_regime_coverage():
    coverage = await db.get_all_signal_coverage()
    return JSONResponse(coverage)


@router.post("/api/regime/reclassify", response_class=JSONResponse)
async def api_regime_reclassify(request: Request):
    try:
        body = await request.json()
    except ValueError:
        body = {}
    from_date = body.get("from_date", "")
    to_date   = body.get("to_date", "")

    if from_date or to_date:
        await db.delete_regime_labels(from_date, to_date)

    count = await classify_range(from_date, to_date)
    return JSONResponse({"status": "completed", "labels_classified": count})


@router.get("/api/regime/thresholds", response_class=JSONResponse)
async def api_regime_thresholds():
    return JSONResponse(config.REGIME_THRESHOLDS)
