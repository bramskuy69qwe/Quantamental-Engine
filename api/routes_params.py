from __future__ import annotations

import logging
import os
from datetime import datetime

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, FileResponse

from core.state import app_state, TZ_LOCAL
from core.event_bus import event_bus
from core.data_logger import export_all_to_excel
from api.helpers import templates, _ctx

log = logging.getLogger("routes.params")
router = APIRouter()


@router.get("/params", response_class=HTMLResponse)
async def params_page(request: Request):
    return templates.TemplateResponse(request, "params.html", _ctx(request))


@router.post("/params/update", response_class=HTMLResponse)
async def update_params(
    request:                   Request,
    individual_risk_per_trade: float = Form(...),
    max_w_loss_percent:        float = Form(...),
    max_dd_percent:            float = Form(...),
    max_exposure:              float = Form(...),
    max_position_count:        int   = Form(...),
    max_correlated_exposure:   float = Form(...),
    auto_export_hours:         int   = Form(24),
    weekly_loss_warning_pct:   float = Form(0.80),
    weekly_loss_limit_pct:     float = Form(0.95),
    max_dd_warning_pct:        float = Form(0.80),
    max_dd_limit_pct:          float = Form(0.95),
):
    app_state.params.update({
        "individual_risk_per_trade": individual_risk_per_trade,
        "max_w_loss_percent":        max_w_loss_percent,
        "max_dd_percent":            max_dd_percent,
        "max_exposure":              max_exposure,
        "max_position_count":        max_position_count,
        "max_correlated_exposure":   max_correlated_exposure,
        "auto_export_hours":         auto_export_hours,
        "weekly_loss_warning_pct":   weekly_loss_warning_pct,
        "weekly_loss_limit_pct":     weekly_loss_limit_pct,
        "max_dd_warning_pct":        max_dd_warning_pct,
        "max_dd_limit_pct":          max_dd_limit_pct,
    })
    await app_state.save_params_async()
    await event_bus.publish(
        "risk:params_updated",
        {"ts": datetime.now(TZ_LOCAL).isoformat()},
    )
    return HTMLResponse('<div class="alert-success p-2 rounded">Parameters saved.</div>')


@router.get("/export")
async def manual_export():
    path = await export_all_to_excel()
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=os.path.basename(path),
    )
