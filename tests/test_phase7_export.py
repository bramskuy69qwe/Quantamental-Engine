"""Phase 7.4 — closed-position audit export (POST /export/closed_position/{id}).

Covers: the new get_closed_position_by_id helper, the signed-envelope build
(reusing the P7.2 position assembler), signature recompute + tamper-evidence,
the HMAC-vs-SHA256 signing modes, the degenerate empty-tpid bundle, and the
route handler (200/404).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from core.audit_export import (
    build_closed_position_export,
    _canonical,
    _sign,
    EXPORT_SCHEMA_VERSION,
)

ACCOUNT_ID = 1


@pytest_asyncio.fixture
async def db():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database = DatabaseManager(path=tmp.name)
    await database.initialize()
    yield database
    await database.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


async def _seed(db, *, tpid="POS1", lifecycle="L1") -> int:
    """Seed a closed position + its causal graph. Returns the closed_positions id."""
    c = db._conn
    await c.execute(
        "INSERT INTO pre_trade_log (account_id, timestamp, ticker, calc_id, lifecycle_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (ACCOUNT_ID, "2026-06-01T00:00:00Z", "BTCUSDT", "C1", lifecycle))
    await c.execute(
        "INSERT INTO orders (account_id, exchange_order_id, symbol, side, calc_id, "
        "lifecycle_id, terminal_position_id, created_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ACCOUNT_ID, "EO1", "BTCUSDT", "BUY", "C1", lifecycle, tpid, 1000))
    await c.execute(
        "INSERT INTO fills (account_id, exchange_fill_id, exchange_order_id, symbol, side, "
        "terminal_position_id, calc_id, lifecycle_id, timestamp_ms, is_close) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ACCOUNT_ID, "F1", "EO1", "BTCUSDT", "BUY", tpid, "C1", lifecycle, 1100, 0))
    await c.execute(
        "INSERT INTO positions_calcs (position_id, calc_id, order_id, account_id, "
        "contributed_qty, first_fill_ts, lifecycle_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (tpid, "C1", 1, ACCOUNT_ID, 1.0, 1100, lifecycle))
    await c.execute(
        "INSERT INTO funding_events (position_id, calc_id, account_id, symbol, amount, "
        "ts_ms, venue_event_id, lifecycle_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (tpid, "C1", ACCOUNT_ID, "BTCUSDT", -1.2, 1500, "binance:fe1", lifecycle))
    cur = await c.execute(
        "INSERT INTO closed_positions (account_id, terminal_position_id, symbol, "
        "exit_time_ms, calc_id, lifecycle_id, entry_px_delta_pct, size_delta_pct) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ACCOUNT_ID, tpid, "BTCUSDT", 2000, "C1", lifecycle, 0.5, -10.0))
    await c.commit()
    return cur.lastrowid


@pytest.fixture(autouse=True)
def _no_open_pos_no_live_events(monkeypatch):
    # assemble_position_context reads app_state.positions + (cross-DB) trade_events.
    from core.state import app_state
    monkeypatch.setattr(app_state, "positions", [])
    monkeypatch.setattr("core.trade_event_log.query_trade_events", lambda **kw: ([], 0))


# ── _sign / _canonical units ─────────────────────────────────────────────────


class TestSignHelpers:
    def test_sha256_default(self, monkeypatch):
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        algo, sig = _sign("hello")
        assert algo == "sha256"
        assert sig == hashlib.sha256(b"hello").hexdigest()

    def test_hmac_when_key(self, monkeypatch):
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "k")
        algo, sig = _sign("hello")
        assert algo == "hmac-sha256"
        assert sig == hmac.new(b"k", b"hello", hashlib.sha256).hexdigest()

    def test_canonical_deterministic_sorted(self):
        assert _canonical({"b": 1, "a": 2}) == _canonical({"a": 2, "b": 1}) == '{"a":2,"b":1}'


# ── helper ───────────────────────────────────────────────────────────────────


class TestGetClosedPositionById:
    @pytest.mark.asyncio
    async def test_returns_full_row_or_none(self, db):
        cid = await _seed(db)
        row = await db.get_closed_position_by_id(cid)
        assert row["terminal_position_id"] == "POS1"
        assert row["calc_id"] == "C1"
        assert row["entry_px_delta_pct"] == 0.5
        assert await db.get_closed_position_by_id(999999) is None


# ── envelope build ───────────────────────────────────────────────────────────


def _header_without_sig(export: dict) -> dict:
    return {k: v for k, v in export.items() if k not in ("signature", "signature_algo")}


class TestBuildExport:
    @pytest.mark.asyncio
    async def test_envelope_shape_and_bundle(self, db, monkeypatch):
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        cid = await _seed(db)
        env = await build_closed_position_export(db, cid)
        exp = env["export"]
        assert exp["kind"] == "closed_position_audit"
        assert exp["schema_version"] == EXPORT_SCHEMA_VERSION
        assert exp["closed_position_id"] == cid
        assert exp["position_id"] == "POS1"
        assert exp["account_id"] == ACCOUNT_ID
        assert exp["bundle_kind"] == "position"
        assert exp["signature_algo"] == "sha256"
        assert exp["generated_at"]            # ISO timestamp present
        # bundle is the full position graph (P7.2 assembler)
        b = env["bundle"]
        assert b["position_id"] == "POS1"
        assert b["contributing_calc_ids"] == ["C1"]
        assert b["closed_positions"][0]["entry_px_delta_pct"] == 0.5
        assert b["funding_events"][0]["amount"] == -1.2

    @pytest.mark.asyncio
    async def test_signature_recomputes(self, db, monkeypatch):
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        cid = await _seed(db)
        env = await build_closed_position_export(db, cid)
        header = _header_without_sig(env["export"])
        algo, sig = _sign(_canonical({"header": header, "bundle": env["bundle"]}))
        assert algo == env["export"]["signature_algo"]
        assert sig == env["export"]["signature"]     # signature is correct + recomputable

    @pytest.mark.asyncio
    async def test_tamper_changes_signature(self, db, monkeypatch):
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        cid = await _seed(db)
        env = await build_closed_position_export(db, cid)
        header = _header_without_sig(env["export"])
        tampered = json.loads(json.dumps(env["bundle"]))   # deep copy
        tampered["position_id"] = "HACKED"
        _, sig2 = _sign(_canonical({"header": header, "bundle": tampered}))
        assert sig2 != env["export"]["signature"]          # tamper-evident

    @pytest.mark.asyncio
    async def test_hmac_mode_when_key_configured(self, db, monkeypatch):
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "topsecret")
        cid = await _seed(db)
        env = await build_closed_position_export(db, cid)
        assert env["export"]["signature_algo"] == "hmac-sha256"
        header = _header_without_sig(env["export"])
        canon = _canonical({"header": header, "bundle": env["bundle"]})
        # HMAC matches the configured key …
        assert env["export"]["signature"] == hmac.new(
            b"topsecret", canon.encode(), hashlib.sha256).hexdigest()
        # … and is NOT the unkeyed digest of the same content.
        assert env["export"]["signature"] != hashlib.sha256(canon.encode()).hexdigest()

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self, db):
        assert await build_closed_position_export(db, 424242) is None

    @pytest.mark.asyncio
    async def test_degenerate_empty_tpid_bundle(self, db, monkeypatch):
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        # A closed row with empty terminal_position_id AND no lifecycle (binance
        # observe-only path) → the graph is unassemblable → closed-row-only bundle.
        c = db._conn
        cur = await c.execute(
            "INSERT INTO closed_positions (account_id, terminal_position_id, symbol, "
            "exit_time_ms) VALUES (?, ?, ?, ?)",
            (ACCOUNT_ID, "", "BTCUSDT", 5000))
        await c.commit()
        cid = cur.lastrowid
        env = await build_closed_position_export(db, cid)
        assert env["export"]["bundle_kind"] == "closed_row_only"
        assert env["export"]["position_id"] is None
        assert env["bundle"]["closed_positions"][0]["id"] == cid
        assert "note" in env["bundle"]
        # still signed
        assert env["export"]["signature"]


# ── route handler ────────────────────────────────────────────────────────────


class TestRoute:
    @pytest.mark.asyncio
    async def test_export_route_200_and_404(self, db, monkeypatch):
        import api.routes_export as rx
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        monkeypatch.setattr(rx, "db", db)
        cid = await _seed(db)

        resp = await rx.export_closed_position(cid)
        assert resp.status_code == 200
        body = json.loads(bytes(resp.body))
        assert body["export"]["closed_position_id"] == cid
        assert body["bundle"]["position_id"] == "POS1"
        assert body["export"]["signature"]

        nf = await rx.export_closed_position(999999)
        assert nf.status_code == 404
        assert "error" in json.loads(bytes(nf.body))
