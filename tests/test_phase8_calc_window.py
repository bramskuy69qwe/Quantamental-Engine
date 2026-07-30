"""
Phase 8 Task 4a (P8.T4a) — calculator account-level match-window dropdown.

The dropdown writes ``accounts.config_json.window_seconds`` (the default the
matcher freezes onto each new calc, P1.T2/T3) via a new reusable config
writer (which P8.T8's settings page will also use).

Intent (Rule 8):
  - merge_config_json applies updates at the top level WITHOUT dropping any
    other config key (webhook_url, feature_flags, …) and tolerates a
    missing / malformed / non-dict blob;
  - write_account_config round-trips through the DB and the read path sees
    the new value while preserving siblings;
  - the endpoint validates the range (out-of-range / non-positive rejected
    with a 200 error span — htmx swallows non-2xx) and writes on success;
  - the calculator page surfaces the current window selected, the dropdown
    POSTs to /calculator/window, and both routes are registered.

Run: pytest tests/test_phase8_calc_window.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

import jinja2
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.account_config import (  # noqa: E402
    merge_config_json,
    write_account_config,
    read_account_config_async,
    DEFAULT_WINDOW_SECONDS,
)


# ── merge_config_json (pure) ──────────────────────────────────────────────────


class TestMergeConfigJson:
    def test_empty_blob_creates_dict(self):
        assert json.loads(merge_config_json(None, {"window_seconds": 60})) == {"window_seconds": 60}
        assert json.loads(merge_config_json("", {"window_seconds": 60})) == {"window_seconds": 60}

    def test_preserves_other_keys(self):
        blob = json.dumps({"webhook_url": "http://x", "window_seconds": 300,
                           "feature_flags": {"webhook_enabled": True}})
        out = json.loads(merge_config_json(blob, {"window_seconds": 900}))
        assert out["window_seconds"] == 900          # updated
        assert out["webhook_url"] == "http://x"      # preserved
        assert out["feature_flags"] == {"webhook_enabled": True}  # nested preserved

    def test_overwrites_existing_key(self):
        out = json.loads(merge_config_json('{"window_seconds": 60}', {"window_seconds": 900}))
        assert out["window_seconds"] == 900

    def test_malformed_blob_treated_as_empty(self):
        assert json.loads(merge_config_json("{not json", {"window_seconds": 60})) == {"window_seconds": 60}

    def test_non_dict_blob_treated_as_empty(self):
        assert json.loads(merge_config_json("[1, 2, 3]", {"window_seconds": 60})) == {"window_seconds": 60}

    def test_multi_key_update(self):
        out = json.loads(merge_config_json('{"a": 1}', {"window_seconds": 60, "b": 2}))
        assert out == {"a": 1, "window_seconds": 60, "b": 2}


# ── DB fixture ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    d = DatabaseManager(path=tmp.name)
    await d.initialize()
    await d._conn.execute("INSERT OR IGNORE INTO accounts (id, name) VALUES (1, 'Test')")
    await d._conn.commit()
    yield d
    await d.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


async def _config_blob(d, account_id=1):
    async with d._conn.execute(
        "SELECT config_json FROM accounts WHERE id = ?", (account_id,),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


# ── write_account_config (DB round-trip) ──────────────────────────────────────


class TestWriteAccountConfig:
    @pytest.mark.asyncio
    async def test_writes_and_read_path_sees_it(self, db):
        await write_account_config(db, 1, {"window_seconds": 900})
        cfg = await read_account_config_async(db, 1)
        assert cfg.window_seconds == 900

    @pytest.mark.asyncio
    async def test_preserves_existing_keys(self, db):
        # seed a config with an unrelated key
        await db._conn.execute(
            "UPDATE accounts SET config_json = ? WHERE id = 1",
            (json.dumps({"webhook_url": "http://hook", "window_seconds": 300}),),
        )
        await db._conn.commit()
        await write_account_config(db, 1, {"window_seconds": 60})
        blob = json.loads(await _config_blob(db))
        assert blob["window_seconds"] == 60
        assert blob["webhook_url"] == "http://hook"   # NOT dropped
        # and the read path resolves it
        assert (await read_account_config_async(db, 1)).webhook_url == "http://hook"

    @pytest.mark.asyncio
    async def test_null_config_json_creates_fresh(self, db):
        assert await _config_blob(db) is None  # fixture leaves it NULL
        await write_account_config(db, 1, {"window_seconds": 900})
        assert json.loads(await _config_blob(db)) == {"window_seconds": 900}


# ── endpoint: POST /calculator/window ─────────────────────────────────────────


class TestSetAccountWindowEndpoint:
    @pytest.mark.asyncio
    async def test_valid_writes(self, db, monkeypatch):
        import api.routes_calculator as rc
        from types import SimpleNamespace
        monkeypatch.setattr(rc, "db", db)
        monkeypatch.setattr(rc, "app_state", SimpleNamespace(active_account_id=1))
        resp = await rc.set_account_window(window_seconds=900)
        assert resp.status_code == 200
        assert b"saved" in resp.body
        assert (await read_account_config_async(db, 1)).window_seconds == 900

    @pytest.mark.asyncio
    async def test_out_of_range_rejected_no_write(self, db, monkeypatch):
        import api.routes_calculator as rc
        from core.exec_link import MAX_LINK_WINDOW_SECONDS
        from types import SimpleNamespace
        monkeypatch.setattr(rc, "db", db)
        monkeypatch.setattr(rc, "app_state", SimpleNamespace(active_account_id=1))
        resp = await rc.set_account_window(window_seconds=MAX_LINK_WINDOW_SECONDS + 1)
        assert resp.status_code == 200          # 200 so htmx swaps the body
        assert b"invalid" in resp.body
        # nothing written -> read path returns the default, config_json still NULL
        assert await _config_blob(db) is None
        assert (await read_account_config_async(db, 1)).window_seconds == DEFAULT_WINDOW_SECONDS

    @pytest.mark.asyncio
    async def test_non_positive_rejected(self, db, monkeypatch):
        import api.routes_calculator as rc
        from types import SimpleNamespace
        monkeypatch.setattr(rc, "db", db)
        monkeypatch.setattr(rc, "app_state", SimpleNamespace(active_account_id=1))
        resp = await rc.set_account_window(window_seconds=0)
        assert b"invalid" in resp.body
        assert await _config_blob(db) is None


# ── template + route wiring (no TestClient — gotcha #9) ───────────────────────


