"""
v3.0 React UI surface (P0 Foundation).

Serves the precompiled static React shell at ``/v3``, alongside the live
Jinja/HTMX UI (page-by-page migration — see
``docs/design/v3.0_ui_rebuild_plan.md``). The app bundle + vendored runtime
deps live under ``static/`` (built by ``frontend/build.mjs``, committed) and are
served by the existing ``/static`` mount; this route only serves the shell HTML.

It injects the content-hashed asset filenames from ``static/v3/manifest.json``
(so the cache-first service worker can never serve a stale bundle) and a small
``window.QE_BOOTSTRAP`` (product identity + active account id, the latter read by
the SSE client-adapter). If the bundle is not built, the shell renders a loud
in-page error instead of a 500.
"""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

import config
from api.helpers import templates, _ctx

router = APIRouter()

_MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "static", "v3", "manifest.json",
)


def _load_manifest() -> dict:
    """Read the build manifest (content-hashed asset names). Fails soft to an
    empty dict so a missing/corrupt build yields a clear in-page error (see
    ``templates/v3.html`` ``{% if v3.app %}``) rather than a 500."""
    try:
        with open(_MANIFEST_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


@router.get("/v3", response_class=HTMLResponse)
async def v3_shell(request: Request):
    return templates.TemplateResponse(
        request,
        "v3.html",
        _ctx(
            request,
            v3=_load_manifest(),
            project_short_name=config.PROJECT_SHORT_NAME,
        ),
    )
