"""
Quantamental Engine — FastAPI entry point.

Run with:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

WSL2 (uvloop):
    uvicorn main:app --host 0.0.0.0 --port 8000 --loop uvloop
"""
from __future__ import annotations

# ── uvloop: install before any event loop is created (Linux/WSL2 only) ────────
try:
    import uvloop
    uvloop.install()
except ImportError:
    pass  # Windows dev — standard asyncio

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse

import config

# Anchor all relative paths to this file's directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)   # ensure CWD is always the project root

from core.state import app_state
from core.database import db
from core.account_registry import account_registry
from core.event_bus import event_bus
from core.schedulers import start_background_tasks
from api.router import router

# ── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Attach rotating JSON file handler to root logger so all modules write to it
os.makedirs(config.LOGS_DIR, exist_ok=True)
from logging.handlers import RotatingFileHandler
from core.log_formatter import JsonFormatter
_json_handler = RotatingFileHandler(
    config.LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_json_handler.setFormatter(JsonFormatter())
logging.getLogger().addHandler(_json_handler)

log = logging.getLogger("main")


# ── Application lifespan ─────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(f"Starting {config.PROJECT_NAME} ...")
    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.SNAPSHOTS_DIR, exist_ok=True)
    os.makedirs(config.LOGS_DIR, exist_ok=True)

    # ── SQLite init (fast — local file) ──────────────────────────────────────
    await db.initialize()

    # ── SQL migrations (post-split only — no-op if marker absent) ────────────
    from core.migrations.runner import run_all as _run_migrations
    _run_migrations()

    # ── Data migrations (threshold conversion from legacy account_params) ────
    from core.migrations.convert_thresholds import convert_thresholds as _convert_thresholds
    _convert_thresholds()

    # ── Load account registry (fast — local DB) ──────────────────────────────
    await account_registry.load_all()
    # SR-2: app_state.active_account_id is now a read-through property
    # backed by account_registry.active_id — no manual sync needed.

    # ── Load connections manager (3rd-party API keys) ────────────────────────
    from core.connections import connections_manager
    await connections_manager.load_all()

    # ── Load active platform from settings ────────────────────────────────────
    platform = await db.get_setting("active_platform")
    app_state.active_platform = platform or "standalone"

    # ── Load persisted parameters (per-account from DB) ──────────────────────
    app_state.load_params()

    # ── Initialize DataCache (single-writer state manager) ──────────────────
    from core.data_cache import DataCache
    app_state._data_cache = DataCache(event_bus)

    # ── Crash recovery: restore last known account state from DB (fast) ──────
    last_snap = await db.get_last_account_state(account_id=app_state.active_account_id)
    if last_snap:
        app_state.restore_from_snapshot(last_snap)
        log.info(f"Crash recovery: restored equity={app_state.account_state.total_equity:.2f} USDT from last DB snapshot")

    # ── Background tasks (Binance REST/WS, schedulers, monitoring) ───────────
    start_background_tasks()

    log.info(f"{config.PROJECT_NAME} accepting connections at http://localhost:8000")
    yield

    log.info(f"Shutting down {config.PROJECT_NAME}...")
    await event_bus.close()
    await db.close()


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=config.PROJECT_NAME,
    version="2.1.0",
    lifespan=lifespan,
)

# Static files (CSS, JS — served from /static)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(router)


@app.get("/manifest.json", include_in_schema=False)
async def pwa_manifest():
    return JSONResponse(
        {
            "name": config.PROJECT_NAME,
            "short_name": "QRE",
            "description": "Pre-trade gatekeeper for discretionary crypto futures trading",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#07080f",
            "theme_color": "#07080f",
            "orientation": "any",
            "icons": [
                {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
                {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
            ],
        },
        media_type="application/manifest+json",
    )


@app.get("/service-worker.js", include_in_schema=False)
async def pwa_service_worker():
    return FileResponse(
        "static/service-worker.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    if os.path.exists("static/icon-192.png"):
        return FileResponse("static/icon-192.png", media_type="image/png")
    return RedirectResponse(url="/")
