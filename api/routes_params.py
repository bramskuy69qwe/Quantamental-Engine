from __future__ import annotations

import logging
import os
from datetime import datetime

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, FileResponse

from starlette.responses import RedirectResponse

from core.state import app_state, validate_params
from core.tz import now_in_account_tz
from core.event_bus import event_bus
from core.data_logger import export_all_to_excel
from api.helpers import templates, _ctx

log = logging.getLogger("routes.params")
router = APIRouter()


@router.get("/params")
async def params_page(request: Request):
    return RedirectResponse(url="/config", status_code=302)


@router.get("/fragments/ws_log", response_class=HTMLResponse)
async def frag_ws_log(request: Request):
    return templates.TemplateResponse(
        request, "fragments/ws_log.html",
        _ctx(request, ws_log=list(app_state.ws_status.logs)),
    )


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
    new_params = {
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
    }
    errors = validate_params(new_params)
    if errors:
        return HTMLResponse(
            f'<div class="alert alert-error">Validation error: {"; ".join(errors)}</div>'
        )
    app_state.params.update(new_params)
    await app_state.save_params_async()
    await event_bus.publish(
        "risk:params_updated",
        {"ts": now_in_account_tz(app_state.active_account_id).isoformat()},
    )
    return HTMLResponse('<div class="alert alert-success">Parameters saved.</div>')


@router.get("/export")
async def manual_export():
    path = await export_all_to_excel()
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=os.path.basename(path),
    )
