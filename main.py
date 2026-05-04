"""
Quantamental Risk Engine v2.1 — FastAPI entry point.

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
from fastapi.responses import RedirectResponse

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
    log.info("Starting Quantamental Risk Engine v2.1 ...")
    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.SNAPSHOTS_DIR, exist_ok=True)
    os.makedirs(config.LOGS_DIR, exist_ok=True)

    # ── SQLite init (fast — local file) ──────────────────────────────────────
    await db.initialize()

    # ── Load account registry (fast — local DB) ──────────────────────────────
    await account_registry.load_all()
    app_state.active_account_id = account_registry.active_id

    # ── Load active platform from settings ────────────────────────────────────
    platform = await db.get_setting("active_platform")
    app_state.active_platform = platform or "standalone"

    # ── Load persisted parameters (fast — local file) ────────────────────────
    app_state.load_params()

    # ── Crash recovery: restore last known account state from DB (fast) ──────
    last_snap = await db.get_last_account_state(account_id=app_state.active_account_id)
    if last_snap:
        acc = app_state.account_state
        acc.total_equity     = last_snap.get("total_equity", 0.0)
        acc.bod_equity       = last_snap.get("bod_equity", 0.0)
        acc.sow_equity       = last_snap.get("sow_equity", 0.0)
        acc.max_total_equity = last_snap.get("max_total_equity", 0.0)
        log.info(f"Crash recovery: restored equity={acc.total_equity:.2f} USDT from last DB snapshot")

    # ── Background tasks (Binance REST/WS, schedulers, monitoring) ───────────
    start_background_tasks()

    log.info("Risk Engine accepting connections at http://localhost:8000")
    yield

    log.info("Shutting down Quantamental Risk Engine...")
    await event_bus.close()
    await db.close()


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Quantamental Risk Engine v2.1",
    version="2.1.0",
    lifespan=lifespan,
)

# Static files (CSS, JS — served from /static)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(router)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse(url="/static/favicon.ico") if os.path.exists("static/favicon.ico") \
        else RedirectResponse(url="/")
