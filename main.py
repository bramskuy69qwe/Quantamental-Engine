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
import sys
import time
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

# Attach rotating JSON file handler to root logger so all modules write to it.
# MED-045 (Task 103.5): use ConcurrentRotatingFileHandler instead of the stdlib
# RotatingFileHandler. The stdlib version uses os.rename for rotation, which
# fails on Windows with PermissionError [WinError 32] whenever another process
# (e.g., a uvicorn worker subprocess) holds the file open. ConcurrentRotatingFileHandler
# is a drop-in replacement that coordinates via OS-level file locks
# (msvcrt on Windows, fcntl on Unix). maxBytes / backupCount / encoding match
# the prior configuration verbatim.
# F5 (v2.7 holistic audit, Task E): under pytest this module-import side
# effect appended every suite run's log lines to the LIVE
# data/logs/risk_engine.jsonl (and held a Windows file lock on it). The
# handler OBJECT still exists — MED-045 pins isinstance on
# main._json_handler — but under pytest it targets a throwaway temp file
# and is NOT attached to the root logger (caplog is unaffected either way).
_TESTING = "pytest" in sys.modules
if _TESTING:
    import tempfile
    _log_target = os.path.join(
        tempfile.mkdtemp(prefix="qre-test-logs-"), "risk_engine.jsonl")
else:
    os.makedirs(config.LOGS_DIR, exist_ok=True)
    _log_target = config.LOG_FILE
from concurrent_log_handler import ConcurrentRotatingFileHandler
from core.log_formatter import JsonFormatter
_json_handler = ConcurrentRotatingFileHandler(
    _log_target,
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
    use_gzip=False,  # match prior behavior — flip later if rotated-log size becomes a concern
)
_json_handler.setFormatter(JsonFormatter())
if not _TESTING:
    logging.getLogger().addHandler(_json_handler)

# Credential hygiene (phase-3/5 ledger observation, fixed 2026-07-30):
# httpx logs every request URL at INFO — including Finnhub's token QUERY
# PARAM — and the root JSON handler shipped those lines to
# data/logs/risk_engine.jsonl in cleartext. WARNING silences the per-request
# echo (the standard httpx production setting); real transport errors still
# surface. httpcore's DEBUG chatter is capped for the same reason. NB log
# files written BEFORE this change still carry tokens until rotation ages
# them out — rotating the key is the operator-side complement.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# F5: set True by the lifespan when the pytest gates actually fire —
# tests/test_routes.py pins this (a deleted gate turns the pin red).
TEST_LIFESPAN_GATED = False

log = logging.getLogger("main")


# ── Startup singleton guard (E2E-program carry-forward, 2026-07-30) ──────────
# Nothing used to stop a second engine instance sharing this data dir: two
# instances mean doubled schedulers with real API keys, SQLite write
# contention, and a split fill pipeline (OBS-001's "dual instance" theory was
# disproven, but only because the second boot happened to fail). The file
# lives under config.DATA_DIR, so a sandbox worktree (own data dir) never
# collides with the live engine. Liveness is os.kill(pid, 0) — PID reuse can
# in principle false-positive, so the refusal message names the file and the
# override (delete it); a stale file from a crash clears itself.

_PID_FILE = os.path.join(config.DATA_DIR, "engine.pid")


def _pid_alive(pid: int) -> bool:
    """Liveness probe. NEVER os.kill(pid, 0) on Windows — any signal other
    than the two CTRL events routes to TerminateProcess, i.e. the 'probe'
    would KILL the other engine instead of detecting it."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        h = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            code = wintypes.DWORD()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(
                h, ctypes.byref(code))
            return bool(ok) and code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True     # exists, owned by someone else
    except OSError:
        return False
    return True


def _acquire_pid_lock() -> None:
    """Refuse to start when another live engine holds this data dir."""
    try:
        with open(_PID_FILE, encoding="ascii") as fh:
            other = int(fh.read().strip() or 0)
    except (OSError, ValueError):
        other = 0
    if other and other != os.getpid() and _pid_alive(other):
        raise RuntimeError(
            f"another engine instance (pid {other}) already holds "
            f"{config.DATA_DIR} — refusing to double-run schedulers against "
            f"the live account. If that pid is not an engine (stale reuse), "
            f"delete {_PID_FILE} and start again."
        )
    with open(_PID_FILE, "w", encoding="ascii") as fh:
        fh.write(str(os.getpid()))


def _release_pid_lock() -> None:
    """Remove the PID file iff it still names this process.

    Read first, CLOSE, then remove — on Windows os.remove fails with
    WinError 32 while the read handle is still open (and the defensive
    except would have swallowed exactly that, leaving the file behind)."""
    try:
        with open(_PID_FILE, encoding="ascii") as fh:
            holder = int(fh.read().strip() or 0)
        if holder == os.getpid():
            os.remove(_PID_FILE)
    except (OSError, ValueError):
        pass


# ── Application lifespan ─────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(f"Starting {config.PROJECT_NAME} ...")
    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.SNAPSHOTS_DIR, exist_ok=True)
    os.makedirs(config.LOGS_DIR, exist_ok=True)

    # Singleton guard — gated OFF under pytest like every other lifespan
    # step that touches the live data dir (F5).
    if not _TESTING:
        _acquire_pid_lock()

    # ── Correlation-log sink (CL.T0b, spec §6.5) ─────────────────────────────
    # Started FIRST: zero dependencies on DB/REST/bus, and the module-level
    # queue already buffers any emits from requests served before startup
    # completes. Guarded internally by CORR_LOG_ENABLED.
    from core import correlation_log
    correlation_log.start()

    # ── SQLite init (fast — local file) ──────────────────────────────────────
    await db.initialize()

    # ── SQL + data migrations — GATED OUT under pytest (F5, Task E) ──────────
    # Both resolve config.DATA_DIR at RUNTIME and open the LIVE split DBs
    # (runner: global.db + per_account/*.db; convert_thresholds: a WRITABLE
    # per-account connection). Under a TestClient lifespan they therefore
    # migrated/touched operator data on every full-suite run — the exact
    # F5 exposure. Tests that exercise the migrations do so directly
    # against their own temp dirs (test_threshold_conversion, the
    # migration test files); the ONE in-process TestClient lifespan
    # (test_routes, LOW-023) needs neither.
    global TEST_LIFESPAN_GATED
    if _TESTING:
        TEST_LIFESPAN_GATED = True
        log.warning(
            "pytest detected — F5 test-lifespan gates active: skipping "
            "SQL/data migrations and background schedulers (live-DB and "
            "live-mutation vectors stay untouched)"
        )
    else:
        from core.migrations.runner import run_all as _run_migrations
        _run_migrations()
        from core.migrations.convert_thresholds import convert_thresholds as _convert_thresholds
        _convert_thresholds()

    # ── Load account registry (fast — local DB) ──────────────────────────────
    await account_registry.load_all()
    # SR-2: app_state.active_account_id is now a read-through property
    # backed by account_registry.active_id — no manual sync needed.

    # ── Load connections manager (3rd-party API keys) ────────────────────────
    from core.connections import connections_manager
    await connections_manager.load_all()

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
    # F5 (Task E): NOT under pytest — this starts 15 live schedulers with
    # the operator's real API keys (calc-expiry / stale-order /
    # session-reaper are live-mutation vectors on the operator's account).
    if not _TESTING:
        start_background_tasks()

    log.info(f"{config.PROJECT_NAME} accepting connections at http://localhost:8000")
    yield

    log.info(f"Shutting down {config.PROJECT_NAME}...")
    await event_bus.close()
    await db.close()
    if not _TESTING:
        _release_pid_lock()
    # Last: flush + stop the correlation-log writer (the explicit call is
    # the only reliable flush trigger — teardown cancels no bg tasks).
    correlation_log.close()


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=config.PROJECT_NAME,
    # OpenAPI version tracks the product version (display "v" prefix stripped).
    version=config.PROJECT_VERSION_.lstrip("v"),
    lifespan=lifespan,
)


# ── Correlation-log HTTP entry point (CL.T1a, spec §3.2 + §5.1) ──────────────

async def _sse_close_tap(orig_iterator, cid: str, path: str, status: int, start: float):
    """SSE/streaming responses: http_response fires at stream CLOSE with the
    total duration (spec §5.1) — a multi-hour duration_ms on a /stream/*
    route is normal. The generator runs outside the middleware's scope, so
    the corr_id is re-bound explicitly."""
    from core import correlation_log
    try:
        async for chunk in orig_iterator:
            yield chunk
    finally:
        with correlation_log.correlation_scope(corr_id=cid):
            # corr-tap: http_response (streaming)
            correlation_log.emit(
                "http", "operator", "out", correlation_log.CAT_HTTP_RESPONSE,
                {"status": status, "path": path, "streaming": True,
                 "duration_ms": round((time.perf_counter() - start) * 1000, 2)},
            )


@app.middleware("http")
async def _corr_http_middleware(request, call_next):
    """Mint one corr_id per HTTP request; tap request-in + response-out.

    NB FastAPI HTTP middleware does NOT run for WebSocket scope — the
    platform WS entry point mints its own (spec §3.2, CL.T1b). /static
    asset fetches are skipped (UI noise, not an engine boundary)."""
    from core import correlation_log
    path = request.url.path
    if path.startswith("/static"):
        return await call_next(request)
    with correlation_log.correlation_scope("http") as cid:
        start = time.perf_counter()
        # corr-tap: http_request
        correlation_log.emit(
            "http", "operator", "in", correlation_log.CAT_HTTP_REQUEST,
            {"method": request.method, "path": path,
             "query": dict(request.query_params),
             "client": request.client.host if request.client else None,
             "content_length": request.headers.get("content-length")},
        )
        try:
            response = await call_next(request)
        except Exception as exc:
            # corr-tap: http_response (unhandled exception path)
            correlation_log.emit(
                "http", "operator", "out", correlation_log.CAT_HTTP_RESPONSE,
                {"status": 500, "path": path, "error_type": type(exc).__name__,
                 "duration_ms": round((time.perf_counter() - start) * 1000, 2)},
            )
            raise
        if "text/event-stream" in response.headers.get("content-type", ""):
            response.body_iterator = _sse_close_tap(
                response.body_iterator, cid, path, response.status_code, start)
            return response
        # corr-tap: http_response
        correlation_log.emit(
            "http", "operator", "out", correlation_log.CAT_HTTP_RESPONSE,
            {"status": response.status_code, "path": path,
             "duration_ms": round((time.perf_counter() - start) * 1000, 2),
             "content_length": response.headers.get("content-length")},
        )
        return response

# Static files (CSS, JS — served from /static)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(router)


@app.get("/manifest.json", include_in_schema=False)
async def pwa_manifest():
    return JSONResponse(
        {
            "name": config.PROJECT_NAME,
            "short_name": config.PROJECT_SHORT_NAME,
            "description": config.PROJECT_DESCRIPTION,
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
