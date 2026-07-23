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
    "/api/models/overview",  # v3.0 P7 G-M3: overview feed smoke
    # v3.0 P1 backend gaps (JSON contract smoke):
    "/api/state",
    "/api/dashboard/snapshot",
    "/api/engine/log",
    "/api/regime/signals/latest",
    "/notifications/poll",
    # v3.0 P2 Config backend gaps (JSON contract smoke):
    "/api/system",
    "/api/connections",
    "/api/config/account/1",
    "/api/config/presets",
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
    # v3.0 P1: journal_stats now renders via the shared _journal_stats_context
    # builder (also feeding /api/dashboard/snapshot) — parity smoke.
    "/fragments/dashboard/journal_stats",
]


@pytest.mark.parametrize("path", FRAGMENT_ROUTES)
def test_fragment_returns_200(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, f"{path} returned {resp.status_code}"
    assert "text/html" in resp.headers.get("content-type", "")


# ── v3.0 P1 backend-gap JSON contracts ──────────────────────────────────────

def test_api_state_has_halt_surface(client):
    """G-O2: /api/state exposes the DD-gate-derived halt surface (corrected —
    halt is DD-enforced-only; weekly_pnl is advisory)."""
    data = client.get("/api/state").json()
    for k in ("halted", "blocked", "halt_reason", "dd_enforcement_mode",
              "weekly_pnl_enforcement_mode", "dd_manually_unblocked"):
        assert k in data, f"/api/state missing {k}"
    assert isinstance(data["halted"], bool)
    assert isinstance(data["blocked"], bool)


def test_dashboard_snapshot_shape(client):
    """G-O12: /api/dashboard/snapshot aggregates the tile sections."""
    data = client.get("/api/dashboard/snapshot").json()
    for k in ("equity", "risk", "positions", "journal", "regime"):
        assert k in data, f"snapshot missing {k}"
    assert isinstance(data["positions"], list)
    assert "total_equity" in data["equity"]
    assert "dd_state" in data["risk"]
    assert "month_label" in data["journal"]  # shared builder wired


def test_engine_log_shape(client):
    """G-O1: engine-log tail returns {lines, latest_id}."""
    data = client.get("/api/engine/log").json()
    assert isinstance(data.get("lines"), list)
    assert "latest_id" in data


def test_macro_signals_latest_shape(client):
    """G-O5: the 6 real regime signals in tile shape (values may be None)."""
    data = client.get("/api/regime/signals/latest").json()
    assert isinstance(data.get("signals"), list)
    keys = {s["key"] for s in data["signals"]}
    assert {"VIX", "10Y", "BTC.OI", "FUND·BTC"}.issubset(keys)


def test_notifications_poll_shape(client):
    """G-O3: poll returns {notifications, latest_id} (init cursor form)."""
    data = client.get("/notifications/poll?since=-1").json()
    assert isinstance(data.get("notifications"), list)
    assert "latest_id" in data


# ── v3.0 P2 Config backend gaps ──────────────────────────────────────────────

def test_system_shape(client):
    """G-O8: /api/system exposes engine identity + runtime facts."""
    data = client.get("/api/system").json()
    for k in ("name", "version", "bus_backend", "uptime_s", "cadences"):
        assert k in data, f"/api/system missing {k}"
    assert data["version"] == config.PROJECT_VERSION_  # config-wired, not a literal


def test_connections_shape(client):
    """P2: JSON connections mirror merges configured + known providers."""
    data = client.get("/api/connections").json()
    conns = data.get("connections")
    assert isinstance(conns, list) and conns
    assert {"provider", "label", "has_key"} <= set(conns[0])


def test_config_account_shape(client):
    """P2: account detail exposes the two risk stores (read-only)."""
    data = client.get("/api/config/account/1").json()
    assert isinstance(data.get("params"), dict)
    assert "settings" in data

# NB: apply-preset is a WRITE that the account_settings writer resolves against
# config.DATA_DIR (the LIVE per-account DB) — the TestClient's temp-DB rebind does
# NOT isolate it (the F5 gap). So it is NOT exercised here; its composition is
# unit-tested with stubbed writers in tests/test_p2_config.py (no live write).


# ── PWA static assets ───────────────────────────────────────────────────────

def test_manifest_is_valid_json(client):
    resp = client.get("/manifest.json")
    assert resp.status_code == 200
    data = resp.json()
    # Compare against config, not a literal — the manifest identity is
    # config-wired (naming-hygiene task), so a product rename must not
    # turn this test into a stale pin.
    assert data["short_name"] == config.PROJECT_SHORT_NAME
    assert data["name"] == config.PROJECT_NAME
    assert "icons" in data


def test_manifest_reflects_config_identity(client, monkeypatch):
    """End-to-end wiring pin (naming-hygiene audit fold): the equality
    assert above is tautological when a hardcoded literal happens to
    EQUAL config — force divergence to prove the route reads config at
    request time."""
    monkeypatch.setattr(config, "PROJECT_SHORT_NAME", "PINCHK")
    resp = client.get("/manifest.json")
    assert resp.status_code == 200
    assert resp.json()["short_name"] == "PINCHK"


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
