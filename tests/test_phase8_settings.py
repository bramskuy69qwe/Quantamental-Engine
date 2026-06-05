"""
Phase 8 Task 8 (P8.T8) — per-account config_json settings editor.

A "Calc-Linkage" tab in /config (NOT a separate /settings page — /config IS
the settings surface) edits accounts.config_json: window, clock-skew, entry/
snapshot tolerances, deviation thresholds, size-deviation threshold, webhook
URL + flags. Reuses the T4a write_account_config / merge_config_json writer.

Intent (Rule 8):
  - the save endpoint validates every knob (range + numeric + yellow<red +
    webhook-url shape), writes the full snapshot (top-level + nested
    deviation_thresholds/feature_flags), and the read path resolves it;
  - it PRESERVES unrelated config_json keys (top-level merge);
  - checkboxes map to strict JSON bools (absent -> False);
  - the form pre-fills from the resolved AccountConfig;
  - the tab + routes are wired.

Run: pytest tests/test_phase8_settings.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from types import SimpleNamespace

import jinja2
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.account_config import read_account_config_async, AccountConfig  # noqa: E402


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


async def _blob(d, account_id=1):
    async with d._conn.execute(
        "SELECT config_json FROM accounts WHERE id=?", (account_id,)) as cur:
        r = await cur.fetchone()
    return r[0] if r else None


def _wire(rc, monkeypatch, d):
    monkeypatch.setattr(rc, "db", d)
    monkeypatch.setattr(rc, "app_state", SimpleNamespace(active_account_id=1))


_GOOD = dict(
    window_seconds="900", clock_skew_tolerance_sec="20",
    entry_tolerance_pct="0.30", snapshot_drift_tolerance_pct="0.6",
    yellow_pct="6", red_pct="18", size_deviation_threshold_pct="12",
    webhook_url="https://hook.example/x", webhook_enabled="on",
    snapshot_wins_drift="",
)


class TestSaveAccountConfig:
    @pytest.mark.asyncio
    async def test_valid_save_round_trips(self, db, monkeypatch):
        import api.routes_config as rc
        _wire(rc, monkeypatch, db)
        resp = await rc.save_account_config(**_GOOD)
        assert b"saved" in resp.body
        cfg = await read_account_config_async(db, 1)
        assert cfg.window_seconds == 900
        assert cfg.clock_skew_tolerance_sec == 20
        assert cfg.entry_tolerance_pct == 0.30
        assert cfg.snapshot_drift_tolerance_pct == 0.6
        assert cfg.yellow_deviation_pct == 6.0
        assert cfg.red_deviation_pct == 18.0
        assert cfg.size_deviation_threshold_pct == 12.0
        assert cfg.webhook_url == "https://hook.example/x"
        assert cfg.webhook_enabled is True            # checkbox "on"
        assert cfg.snapshot_wins_drift is False       # absent

    @pytest.mark.asyncio
    async def test_nested_groups_written(self, db, monkeypatch):
        import api.routes_config as rc
        _wire(rc, monkeypatch, db)
        await rc.save_account_config(**{**_GOOD, "snapshot_wins_drift": "on"})
        blob = json.loads(await _blob(db))
        assert blob["deviation_thresholds"] == {"yellow_pct": 6.0, "red_pct": 18.0}
        assert blob["feature_flags"] == {"snapshot_wins_drift": True, "webhook_enabled": True}

    @pytest.mark.asyncio
    async def test_preserves_unrelated_keys(self, db, monkeypatch):
        import api.routes_config as rc
        _wire(rc, monkeypatch, db)
        await db._conn.execute(
            "UPDATE accounts SET config_json=? WHERE id=1",
            (json.dumps({"some_future_key": 42}),))
        await db._conn.commit()
        await rc.save_account_config(**_GOOD)
        blob = json.loads(await _blob(db))
        assert blob["some_future_key"] == 42          # NOT dropped by the merge
        assert blob["window_seconds"] == 900

    @pytest.mark.asyncio
    async def test_blank_webhook_url_stores_none(self, db, monkeypatch):
        import api.routes_config as rc
        _wire(rc, monkeypatch, db)
        await rc.save_account_config(**{**_GOOD, "webhook_url": "  "})
        assert (await read_account_config_async(db, 1)).webhook_url is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("over,frag", [
        ({"window_seconds": "0"}, "Match window"),
        ({"window_seconds": "999999999"}, "Match window"),
        ({"window_seconds": "abc"}, "Match window"),
        ({"entry_tolerance_pct": "-1"}, "Entry tolerance"),
        ({"entry_tolerance_pct": "nan"}, "finite"),            # NaN bypassed range
        ({"red_pct": "Infinity"}, "finite"),
        ({"yellow_pct": "20", "red_pct": "10"}, "yellow"),     # yellow >= red
        ({"webhook_url": "ftp://nope"}, "webhook"),
    ])
    async def test_invalid_rejected_no_write(self, db, monkeypatch, over, frag):
        import api.routes_config as rc
        _wire(rc, monkeypatch, db)
        resp = await rc.save_account_config(**{**_GOOD, **over})
        assert frag.encode() in resp.body or b"text-red" in resp.body
        assert await _blob(db) is None                 # nothing persisted


# ── fragment render (pre-fill) ────────────────────────────────────────────────


def _render_cfg(cfg):
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    return env.get_template("fragments/account_config.html").render(cfg=cfg)


class TestFragmentRender:
    def test_prefills_values_and_flags(self):
        cfg = AccountConfig(window_seconds=900, clock_skew_tolerance_sec=20,
                            webhook_url="https://x", webhook_enabled=True,
                            snapshot_wins_drift=False)
        html = _render_cfg(cfg)
        assert 'name="window_seconds"' in html and 'value="900"' in html
        assert 'name="webhook_url"' in html and 'value="https://x"' in html
        assert 'name="webhook_enabled"' in html and 'name="snapshot_wins_drift"' in html
        assert 'hx-post="/config/account_config"' in html
        assert html.count(" checked") == 1            # only webhook_enabled (True)

    def test_checkbox_states(self):
        # both False -> 0 checked; both True -> 2 checked (pins the if/endif logic)
        assert _render_cfg(AccountConfig(webhook_enabled=False, snapshot_wins_drift=False)).count(" checked") == 0
        assert _render_cfg(AccountConfig(webhook_enabled=True, snapshot_wins_drift=True)).count(" checked") == 2

    def test_template_compiles(self):
        jinja2.Environment(loader=jinja2.FileSystemLoader("templates")).get_template("config.html")


class TestWiring:
    def test_config_tab_present(self):
        with open("templates/config.html", encoding="utf-8") as fh:
            src = fh.read()
        assert "switchConfigTab('calc-linkage')" in src
        assert 'id="tab-calc-linkage"' in src
        assert 'hx-get="/fragments/account_config"' in src
        assert "['accounts','connections','calc-linkage']" in src

    def test_routes_registered(self):
        import api.routes_config as rc

        def _has(path, method):
            return any(
                getattr(r, "path", None) == path and method in getattr(r, "methods", set())
                for r in rc.router.routes
            )
        assert _has("/fragments/account_config", "GET")
        assert _has("/config/account_config", "POST")
