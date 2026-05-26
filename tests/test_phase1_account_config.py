"""
Phase 1 Task 2 (P1.T2) — per-account config helper tests.

Verifies:

1. AccountConfig parsing from various ``config_json`` shapes:
   full, partial (defaults fill gaps), missing column, empty blob,
   malformed JSON, JSON that isn't a dict.

2. Both reader flavors return the same AccountConfig:
   - read_account_config_sync (matcher path)
   - read_account_config_async (handlers path)

3. handle_risk_calculated freezes window_seconds onto the new calc
   from the account's config_json (spec §3.2 — "frozen from
   accounts.config_json at creation").

4. The matcher honors a frozen pre_trade_log.window_seconds (so
   operator-changed account config doesn't break in-flight calcs).

Run: pytest tests/test_phase1_account_config.py -v
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.account_config import (
    AccountConfig,
    DEFAULT_CLOCK_SKEW_TOLERANCE_SEC,
    DEFAULT_ENTRY_TOLERANCE_PCT,
    DEFAULT_RED_DEVIATION_PCT,
    DEFAULT_SIZE_DEVIATION_THRESHOLD_PCT,
    DEFAULT_SNAPSHOT_DRIFT_TOLERANCE_PCT,
    DEFAULT_WINDOW_SECONDS,
    DEFAULT_YELLOW_DEVIATION_PCT,
    _parse_config_json,
    read_account_config_async,
    read_account_config_sync,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db():
    """Tempfile DB initialized with the full schema (P0.T1-T4 + P1.T1)."""
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    yield db, tmp.name
    await db.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


async def _set_config_json(db, account_id: int, blob: str | None) -> None:
    await db._conn.execute(
        "INSERT OR REPLACE INTO accounts (id, name, config_json) "
        "VALUES (?, ?, ?)",
        (account_id, "Test", blob),
    )
    await db._conn.commit()


# ── 1. _parse_config_json — pure parser ──────────────────────────────


class TestParseConfigJson:
    """The parser is pure: testable without a DB. Pin every spec
    §3.3 fallback path.
    """

    def test_full_config_round_trip(self):
        """All spec §3.3 fields supplied — config matches verbatim."""
        blob = json.dumps({
            "window_seconds": 60,
            "clock_skew_tolerance_sec": 5,
            "entry_tolerance_pct": 0.5,
            "snapshot_drift_tolerance_pct": 1.0,
            "deviation_thresholds": {"yellow_pct": 3, "red_pct": 9},
            "size_deviation_threshold_pct": 7,
        })
        cfg = _parse_config_json(blob)
        assert cfg.window_seconds == 60
        assert cfg.clock_skew_tolerance_sec == 5
        assert cfg.entry_tolerance_pct == 0.5
        assert cfg.snapshot_drift_tolerance_pct == 1.0
        assert cfg.yellow_deviation_pct == 3.0
        assert cfg.red_deviation_pct == 9.0
        assert cfg.size_deviation_threshold_pct == 7.0

    def test_partial_config_fills_with_defaults(self):
        """Only some fields supplied — missing ones fall back to spec §3.3.

        Why this matters: real operators rarely set every field. The
        spec promises defaults for unset values; a partial JSON blob
        must not break this contract.
        """
        blob = json.dumps({"window_seconds": 900})  # only one field
        cfg = _parse_config_json(blob)
        assert cfg.window_seconds == 900  # set
        assert cfg.clock_skew_tolerance_sec == DEFAULT_CLOCK_SKEW_TOLERANCE_SEC
        assert cfg.entry_tolerance_pct == DEFAULT_ENTRY_TOLERANCE_PCT
        assert cfg.yellow_deviation_pct == DEFAULT_YELLOW_DEVIATION_PCT
        assert cfg.red_deviation_pct == DEFAULT_RED_DEVIATION_PCT

    def test_partial_deviation_thresholds_fill_with_defaults(self):
        """deviation_thresholds dict supplies only yellow_pct — red_pct defaults."""
        blob = json.dumps({"deviation_thresholds": {"yellow_pct": 2}})
        cfg = _parse_config_json(blob)
        assert cfg.yellow_deviation_pct == 2.0
        assert cfg.red_deviation_pct == DEFAULT_RED_DEVIATION_PCT

    def test_none_blob_returns_full_defaults(self):
        cfg = _parse_config_json(None)
        assert cfg == AccountConfig()  # everything default

    def test_empty_string_returns_full_defaults(self):
        cfg = _parse_config_json("")
        assert cfg == AccountConfig()

    def test_malformed_json_returns_full_defaults(self):
        """Operator-edited config_json with a typo should not break the
        engine. Fail loud in logs (Rule 10), but defaults keep the
        system running.
        """
        cfg = _parse_config_json('{"window_seconds": 60,')  # trailing comma → bad JSON
        assert cfg == AccountConfig()

    def test_non_dict_json_returns_full_defaults(self):
        """JSON that parses but isn't a dict — list, string, number."""
        cfg = _parse_config_json('["window_seconds", 60]')
        assert cfg == AccountConfig()

    def test_non_numeric_field_falls_back_to_default(self):
        """A field with a string value where a number is expected — fall
        back to that field's default rather than raise.
        """
        blob = json.dumps({
            "window_seconds": "not a number",
            "clock_skew_tolerance_sec": 7,
        })
        cfg = _parse_config_json(blob)
        assert cfg.window_seconds == DEFAULT_WINDOW_SECONDS  # fallback
        assert cfg.clock_skew_tolerance_sec == 7  # parsed normally


# ── 2. Sync + async readers agree ────────────────────────────────────


class TestSyncAsyncParity:
    """Both flavors must return identical AccountConfig for the same DB
    state. The matcher uses sync; handlers use async. Drift between
    them would silently produce different decisions on the same calc.
    """

    @pytest.mark.asyncio
    async def test_sync_async_agree_on_full_config(self, db):
        d, db_path = db
        blob = json.dumps({"window_seconds": 600, "entry_tolerance_pct": 0.5})
        await _set_config_json(d, 1, blob)

        cfg_async = await read_account_config_async(d, 1)
        cfg_sync = read_account_config_sync(db_path, 1)
        assert cfg_async == cfg_sync
        assert cfg_async.window_seconds == 600
        assert cfg_async.entry_tolerance_pct == 0.5

    @pytest.mark.asyncio
    async def test_sync_async_agree_on_missing_account(self, db):
        """No row at account_id=99 → both return full defaults."""
        d, db_path = db
        cfg_async = await read_account_config_async(d, 99)
        cfg_sync = read_account_config_sync(db_path, 99)
        assert cfg_async == cfg_sync == AccountConfig()

    @pytest.mark.asyncio
    async def test_sync_async_agree_on_null_config(self, db):
        """Account row exists but config_json is NULL — both return defaults."""
        d, db_path = db
        await _set_config_json(d, 1, None)
        cfg_async = await read_account_config_async(d, 1)
        cfg_sync = read_account_config_sync(db_path, 1)
        assert cfg_async == cfg_sync == AccountConfig()


# ── 3. handle_risk_calculated freezes window_seconds ─────────────────


class TestHandleRiskCalculatedFreeze:
    """Plan §1 task 1.3: window_seconds must be frozen onto the
    pre_trade_log row at creation time so operator-side changes to
    accounts.config_json don't affect in-flight calcs (spec §3.2).
    """

    @pytest.mark.asyncio
    async def test_freezes_from_account_config(self, db, monkeypatch):
        d, db_path = db
        # Account config says window_seconds=900
        await _set_config_json(d, 1, json.dumps({"window_seconds": 900}))

        # Wire handlers' `db` import to our fixture. active_account_id
        # defaults to 1 in test contexts (account_registry initializes
        # to 1 before any settings load) — matches our test DB seed.
        from core import handlers
        monkeypatch.setattr(handlers, "db", d)

        # Invoke the handler
        await handlers.handle_risk_calculated({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": "BTCUSDT",
            "side": "long",
            "effective_entry": 50000.0,
            "tp_price": 55000.0,
            "sl_price": 48000.0,
            "calc_id": "freeze-test-1",
        })

        # Verify the row was inserted with the frozen window
        async with d._conn.execute(
            "SELECT window_seconds, status FROM pre_trade_log WHERE calc_id = ?",
            ("freeze-test-1",),
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        assert row[0] == 900  # frozen at handle_risk_calculated time
        assert row[1] == "active"  # status default kept from T211 H2

    @pytest.mark.asyncio
    async def test_freezes_spec_default_when_config_missing(self, db, monkeypatch):
        """No config_json set → calc lands with the spec default 300."""
        d, db_path = db
        # No accounts row → AccountConfig() with defaults

        from core import handlers
        monkeypatch.setattr(handlers, "db", d)

        await handlers.handle_risk_calculated({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": "ETHUSDT",
            "side": "short",
            "effective_entry": 3000.0,
            "tp_price": 2800.0,
            "sl_price": 3100.0,
            "calc_id": "freeze-test-2",
        })

        async with d._conn.execute(
            "SELECT window_seconds FROM pre_trade_log WHERE calc_id = ?",
            ("freeze-test-2",),
        ) as cur:
            row = await cur.fetchone()
        assert row[0] == DEFAULT_WINDOW_SECONDS  # spec §3.3 default

    @pytest.mark.asyncio
    async def test_in_flight_calc_immune_to_config_change(self, db, monkeypatch):
        """Spec §3.2: 'frozen from accounts.config_json at creation'.

        Why this matters: operator might change window mid-day. Calcs
        that were placed earlier with a 5-min window should still
        evaluate with 5 min — not jump to a new 15-min window mid-stream.
        Without freezing, the matcher would silently apply the new
        window to old calcs.
        """
        d, db_path = db
        await _set_config_json(d, 1, json.dumps({"window_seconds": 300}))

        from core import handlers
        monkeypatch.setattr(handlers, "db", d)

        # Calc #1 created when window=300
        await handlers.handle_risk_calculated({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": "BTCUSDT", "side": "long",
            "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
            "calc_id": "in-flight-1",
        })

        # Operator changes config to window=900 (15 min)
        await _set_config_json(d, 1, json.dumps({"window_seconds": 900}))

        # Calc #2 created post-change
        await handlers.handle_risk_calculated({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": "BTCUSDT", "side": "long",
            "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
            "calc_id": "in-flight-2",
        })

        # Calc #1's frozen window should still be 300
        async with d._conn.execute(
            "SELECT window_seconds FROM pre_trade_log WHERE calc_id = ?",
            ("in-flight-1",),
        ) as cur:
            row1 = await cur.fetchone()
        async with d._conn.execute(
            "SELECT window_seconds FROM pre_trade_log WHERE calc_id = ?",
            ("in-flight-2",),
        ) as cur:
            row2 = await cur.fetchone()
        assert row1[0] == 300, (
            f"in-flight calc lost its frozen window: got {row1[0]}"
        )
        assert row2[0] == 900


# ── 4. Matcher honors frozen window ──────────────────────────────────


class TestMatcherHonorsFrozenWindow:
    """Spec §4.3: the matcher uses ``pre_trade_log.window_seconds`` per-calc.
    If the calc was frozen with a custom window, that's what's evaluated —
    not the account's current value.

    Why this matters: if the matcher silently fell back to the account's
    CURRENT window every time, a stale calc could be made eligible (or
    excluded) by a mid-flight config change. The freeze + per-calc
    lookup together preserve the operator's original intent.
    """

    @pytest.mark.asyncio
    async def test_matcher_uses_frozen_window_not_account_current(self, db):
        """Insert a calc with window_seconds=60 (frozen narrow), then
        verify a 100-second-old calc fails in-window check even though
        the account default is 300.
        """
        from core.calc_correlation import (
            LINK_STATUS_LINKED,
            LINK_STATUS_UNPLANNED,
            correlate_order_to_calc,
        )
        d, db_path = db
        # Account default 300, but this calc was frozen with 60.
        await _set_config_json(d, 1, json.dumps({"window_seconds": 300}))
        # Manually insert calc with frozen window=60 and timestamp 100s ago
        old_ts = (datetime.now(timezone.utc) - timedelta(seconds=100)).isoformat()
        await d._conn.execute(
            "INSERT INTO pre_trade_log "
            "(account_id, timestamp, ticker, side, effective_entry, "
            " tp_price, sl_price, average, calc_id, status, window_seconds) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, old_ts, "BTCUSDT", "long", 50000.0, 55000.0, 48000.0,
             50000.0, "frozen-narrow", "active", 60),
        )
        await d._conn.commit()

        # Order arrives now — 100s is OUT of the calc's frozen 60s window
        # (+ default 10s clock skew = 70s allowed). Account's CURRENT
        # 300s window would have allowed it; per-calc freeze blocks it.
        result = correlate_order_to_calc(
            {"account_id": 1, "symbol": "BTCUSDT", "side": "BUY",
             "order_type": "limit", "price": 50000.0,
             "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.0,
             "created_at_ms": int(time.time() * 1000)},
            order_id=1,
            tick_size=0.1,
            window_seconds=300,  # account default — IGNORED because per-calc set
            clock_skew_tolerance_sec=10,
            db_path=db_path,
        )
        assert result.calc_id is None, (
            "matcher should have honored per-calc frozen window=60 "
            "over the account default 300; calc was 100s old, "
            "outside the frozen 60+10=70 second bound"
        )
        assert result.link_status == LINK_STATUS_UNPLANNED
