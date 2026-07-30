from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from starlette.responses import RedirectResponse

from core.data_logger import export_all_to_excel

log = logging.getLogger("routes.params")
router = APIRouter()


# (Retired 2026-07-30, operator call: `POST /params/update`. It was the Jinja
# params form's writer and had been UI-orphaned since the retirement deleted
# that page. Risk params are edited per-account through the React Config page,
# which posts /accounts/{id}/update and /api/config/apply-preset — both of
# which run the same `validate_params` guard, so no bounds validation was lost.
# The route's one UNIQUE behaviour — MED-036's runtime check refusing a
# `max_position_count` below the live open-position count — was REHOMED into
# /accounts/{id}/update rather than dropped, scoped to the active account
# because app_state.positions is active-account state.)


@router.get("/params")
async def params_page(request: Request):
    return RedirectResponse(url="/config", status_code=302)


@router.get("/export")
async def manual_export():
    path = await export_all_to_excel()
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=os.path.basename(path),
    )
