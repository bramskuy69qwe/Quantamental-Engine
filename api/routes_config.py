"""
Config page router — serves the tabbed config page (Accounts + Connections).
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from api.helpers import templates, _ctx

router = APIRouter(tags=["config"])


@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    return templates.TemplateResponse(request, "config.html", _ctx(request))
