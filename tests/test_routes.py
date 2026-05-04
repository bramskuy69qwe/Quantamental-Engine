"""
Route smoke tests — every page and fragment endpoint returns 200.

Uses FastAPI's TestClient (synchronous) so no running server needed.
The app initializes against a temporary SQLite DB to avoid touching production data.
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
    """Create a TestClient that initializes the app with a temp DB."""
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        yield c
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
]


@pytest.mark.parametrize("path", API_ROUTES)
def test_api_returns_200(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, f"{path} returned {resp.status_code}"


# ── Fragment endpoints (HTMX partials) ──────────────────────────────────────

FRAGMENT_ROUTES = [
    "/fragments/ws_status",
    "/fragments/dashboard/exchange_info",
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
