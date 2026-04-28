from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.database import db

log = logging.getLogger("routes.models")
router = APIRouter()


@router.get("/api/models", response_class=JSONResponse)
async def api_list_models():
    models = await db.list_potential_models()
    for m in models:
        m.pop("config_json", None)
    return JSONResponse(models)


@router.get("/api/models/{model_id}", response_class=JSONResponse)
async def api_get_model(model_id: int):
    model = await db.get_potential_model(model_id)
    if not model:
        return JSONResponse({"error": "Not found"}, status_code=404)
    model.pop("config_json", None)
    return JSONResponse(model)


@router.post("/api/models", response_class=JSONResponse)
async def api_create_model(request: Request):
    body = await request.json()
    name        = body.get("name", "").strip()
    model_type  = body.get("type", "both")
    description = body.get("description", "").strip()
    config      = body.get("config", {})

    if not name:
        return JSONResponse({"error": "Name is required"}, status_code=400)
    if model_type not in ("macro", "micro", "both"):
        return JSONResponse({"error": "Type must be macro, micro, or both"}, status_code=400)

    model_id = await db.create_potential_model(name, model_type, description, config)
    return JSONResponse({"model_id": model_id, "status": "created"})


@router.put("/api/models/{model_id}", response_class=JSONResponse)
async def api_update_model(request: Request, model_id: int):
    body = await request.json()
    name        = body.get("name", "").strip()
    model_type  = body.get("type", "both")
    description = body.get("description", "").strip()
    config      = body.get("config", {})

    if not name:
        return JSONResponse({"error": "Name is required"}, status_code=400)

    await db.update_potential_model(model_id, name, model_type, description, config)
    return JSONResponse({"status": "updated"})


@router.delete("/api/models/{model_id}", response_class=JSONResponse)
async def api_delete_model(model_id: int):
    await db.delete_potential_model(model_id)
    return JSONResponse({"status": "deleted"})
