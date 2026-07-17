"""
Route smoke tests — every page and fragment endpoint returns 200.

Uses FastAPI's TestClient (synchronous) so no running server needed.

ISOLATION (v2.7 holistic-audit F5 — HARDENED in Task E): the client
fixture rebinds the `db` SINGLETON's `path` attribute to the temp DB
before the lifespan enters (immune to import order — the config.DB_PATH
patch below only covers solo runs, because in full-suite runs an
alphabetically-earlier test file has already constructed the singleton
against the real path), and main.py's lifespan gates skip the SQL/data
migrations and background schedulers under pytest (they resolve
config.DATA_DIR at runtime and would touch the LIVE split DBs / start
15 live schedulers with real API keys). The TestF5IsolationPins class
below pins all three mechanisms.
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Point DB at a temp file BEFORE importing anything that touches config/database
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ.setdefault("QRE_DB_PATH", _tmp_db.name)

# Patch config.DB_PATH before any module reads it
import config
config.DB_PATH = _tmp_db.name


@pytest.fixture(scope="module")
def client():
    """Create a TestClient that initializes the app with a temp DB.

    F5 (Task E): the singleton's ``path`` is rebound HERE, at fixture
    time — the module-top config.DB_PATH patch is void whenever an
    earlier test file already constructed the singleton (it bakes
    config.DB_PATH in __init__). The attribute rebind works in both solo
    and full-suite runs; teardown restores the original binding so the
    post-module world is unchanged for any later singleton user.
    """
    from fastapi.testclient import TestClient
    from core.database import db as _db_singleton
    from main import app
    _orig_path = _db_singleton.path
    _db_singleton.path = _tmp_db.name
    try:
        with TestClient(app) as c:
            yield c
    finally:
        _db_singleton.path = _orig_path
    # Cleanup temp DB
    try:
        os.unlink(_tmp_db.name)
        for ext in ("-wal", "-shm"):
            p = _tmp_db.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


# ── HTML pages (should return 200 with HTML content) ────────────────────────

PAGE_ROUTES = [
    "/",
    "/calculator",
    "/history",
    "/params",
    "/analytics",
    "/backtest",
    "/models",  # v2.7 P4: model-library page
    "/regime",
]


@pytest.mark.parametrize("path", PAGE_ROUTES)
def test_page_returns_200(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, f"{path} returned {resp.status_code}"
    assert "text/html" in resp.headers.get("content-type", "")


# ── API endpoints (JSON or HTML fragments) ──────────────────────────────────

API_ROUTES = [
    "/api/ready",
    "/manifest.json",
    "/service-worker.js",
    "/api/models",  # v2.7 P3: JSON contract smoke
]


@pytest.mark.parametrize("path", API_ROUTES)
def test_api_returns_200(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, f"{path} returned {resp.status_code}"


# ── Fragment endpoints (HTMX partials) ──────────────────────────────────────

FRAGMENT_ROUTES = [
    "/fragments/ws_status",
    "/fragments/dashboard/exchange_info",
    # v2.7 P3: model-library fragments (id-less GETs only — the
    # id-parameterized ones are handler-tested in test_v27_phase3_*)
    "/fragments/models/list",
    "/fragments/models/form",
]


@pytest.mark.parametrize("path", FRAGMENT_ROUTES)
def test_fragment_returns_200(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, f"{path} returned {resp.status_code}"
    assert "text/html" in resp.headers.get("content-type", "")


# ── PWA static assets ───────────────────────────────────────────────────────

def test_manifest_is_valid_json(client):
    resp = client.get("/manifest.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["short_name"] == "QRE"
    assert "icons" in data


def test_service_worker_has_correct_header(client):
    resp = client.get("/service-worker.js")
    assert resp.status_code == 200
    assert resp.headers.get("service-worker-allowed") == "/"


# ── F5 isolation pins (v2.7 holistic audit, Task E) ─────────────────────────
# This module owns the process's ONE TestClient lifespan (LOW-023), so it
# is the only place the three F5 mechanisms can be pinned against the
# REAL lifespan rather than a mock.

class TestF5IsolationPins:
    def test_lifespan_test_gates_fired(self, client):
        """Deleting the pytest gate in main.lifespan turns this red: the
        flag flips True only when the gate branch actually executes —
        i.e. the migration runner + convert_thresholds + the 15 live
        schedulers were all SKIPPED for this lifespan."""
        import main
        assert main.TEST_LIFESPAN_GATED is True, (
            "F5 regression: main.lifespan ran WITHOUT the pytest gates — "
            "the migration runner and live schedulers just executed "
            "against the operator's environment"
        )

    def test_db_singleton_bound_to_temp_db(self, client):
        """The lifespan must have initialized the TEMP DB, not the live
        data/risk_engine.db — the fixture's attribute rebind is what
        makes this true in FULL-SUITE runs (the config.DB_PATH patch
        alone is void once an earlier file constructed the singleton)."""
        from core.database import db as _db_singleton
        assert os.path.abspath(_db_singleton.path) == os.path.abspath(_tmp_db.name)
        assert os.path.basename(_db_singleton.path) != "risk_engine.db"

    def test_root_logger_has_no_rotating_file_handler(self, client):
        """Under pytest, main.py must not attach its rotating JSON
        handler to the root logger (it targeted the LIVE
        data/logs/risk_engine.jsonl and held a Windows lock on it).
        The handler OBJECT still exists — MED-045 pins its class — it
        is just unattached and pointed at a temp file."""
        import logging as _logging
        from concurrent_log_handler import ConcurrentRotatingFileHandler
        root_handlers = _logging.getLogger().handlers
        assert not any(
            isinstance(h, ConcurrentRotatingFileHandler) for h in root_handlers
        ), "F5 regression: the rotating file handler is attached to root under pytest"
        import main
        assert isinstance(main._json_handler, ConcurrentRotatingFileHandler)
        assert "risk_engine.jsonl" in str(main._json_handler.baseFilename)
        assert os.path.abspath(config.LOG_FILE) != os.path.abspath(
            main._json_handler.baseFilename
        ), "F5 regression: the test-mode handler targets the live LOG_FILE"
