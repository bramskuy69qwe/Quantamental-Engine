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
    build_batch_export,
    render_batch_zip,
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
        assert "match_audit" in b          # P7 follow-up #1 (matcher trace section)

    @pytest.mark.asyncio
    async def test_bundle_includes_match_audit(self, db, monkeypatch):
        # P7 follow-up #1: the per-criterion matcher decision trace rides the
        # SIGNED export bundle (the assembler section flows through unchanged).
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        cid = await _seed(db)
        await db._conn.execute(
            "INSERT INTO calc_match_audit (order_id, calc_id, criterion, calc_value, "
            "order_value, tolerance_used, matched, ts_ms, winning) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "C1", "entry", "64000", "64010", 0.25, 1, 1000, 1))
        await db._conn.commit()
        env = await build_closed_position_export(db, cid)
        ma = env["bundle"]["match_audit"]
        assert len(ma) == 1
        assert ma[0]["calc_id"] == "C1" and ma[0]["criterion"] == "entry"
        assert ma[0]["matched"] == 1 and ma[0]["winning"] == 1
        # JSON/PDF parity: the matcher trace also renders in the PDF text.
        from core.audit_export import _export_text_lines
        txt = "\n".join(_export_text_lines(env))
        assert "MATCH AUDIT" in txt and "criterion=entry" in txt

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
    async def test_header_tamper_changes_signature(self, db, monkeypatch):
        # The signature covers the HEADER too — tampering a header field (not
        # just the bundle) must be detected.
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        cid = await _seed(db)
        env = await build_closed_position_export(db, cid)
        header = _header_without_sig(env["export"])
        header["account_id"] = 999          # tamper a HEADER field
        _, sig2 = _sign(_canonical({"header": header, "bundle": env["bundle"]}))
        assert sig2 != env["export"]["signature"]

    @pytest.mark.asyncio
    async def test_json_safe_in_signed_bundle(self, db, monkeypatch):
        # A non-finite REAL column must be coerced to null IN THE EXPORTED bundle,
        # and the signature must be over the coerced content (so a verifier of the
        # served bundle recomputes the same signature).
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        c = db._conn
        cur = await c.execute(
            "INSERT INTO closed_positions (account_id, terminal_position_id, symbol, "
            "exit_time_ms, entry_px_delta_pct) VALUES (?, ?, ?, ?, ?)",
            (ACCOUNT_ID, "POSI", "BTCUSDT", 7000, float("inf")))
        await c.commit()
        env = await build_closed_position_export(db, cur.lastrowid)
        cp = env["bundle"]["closed_positions"][0]
        assert cp["entry_px_delta_pct"] is None       # inf → null in the bundle
        header = _header_without_sig(env["export"])
        _, sig = _sign(_canonical({"header": header, "bundle": env["bundle"]}))
        assert sig == env["export"]["signature"]      # signed over the coerced content

    @pytest.mark.asyncio
    async def test_lifecycle_fallback_bundle(self, db, monkeypatch):
        # A closed row with EMPTY tpid but a real lifecycle_id (+ a junction under
        # that lifecycle) routes to the lifecycle assembler → bundle_kind=lifecycle.
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        c = db._conn
        await c.execute(
            "INSERT INTO pre_trade_log (account_id, timestamp, ticker, calc_id, lifecycle_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (ACCOUNT_ID, "2026-06-01T00:00:00Z", "ETHUSDT", "CL", "LX"))
        await c.execute(
            "INSERT INTO positions_calcs (position_id, calc_id, order_id, account_id, "
            "contributed_qty, first_fill_ts, lifecycle_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("POSL", "CL", 1, ACCOUNT_ID, 1.0, 1100, "LX"))
        cur = await c.execute(
            "INSERT INTO closed_positions (account_id, terminal_position_id, symbol, "
            "exit_time_ms, lifecycle_id) VALUES (?, ?, ?, ?, ?)",
            (ACCOUNT_ID, "", "ETHUSDT", 6000, "LX"))   # empty tpid, lifecycle set
        await c.commit()
        env = await build_closed_position_export(db, cur.lastrowid)
        assert env["export"]["bundle_kind"] == "lifecycle"
        assert env["export"]["position_id"] is None
        assert env["export"]["lifecycle_id"] == "LX"
        assert [c2["calc_id"] for c2 in env["bundle"]["calcs"]] == ["CL"]

    @pytest.mark.asyncio
    async def test_multi_partial_closed_rows_in_bundle(self, db, monkeypatch):
        # Export by ONE partial's id → the bundle carries ALL the position's
        # closed rows (export = whole position, §10.6).
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        cid = await _seed(db)   # closed row for POS1 @ exit 2000
        c = db._conn
        await c.execute(
            "INSERT INTO closed_positions (account_id, terminal_position_id, symbol, "
            "exit_time_ms, calc_id, lifecycle_id) VALUES (?, ?, ?, ?, ?, ?)",
            (ACCOUNT_ID, "POS1", "BTCUSDT", 3000, "C1", "L1"))   # 2nd partial, same tpid
        await c.commit()
        env = await build_closed_position_export(db, cid)
        assert len(env["bundle"]["closed_positions"]) == 2

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

        resp = await rx.export_closed_position(cid, fmt="json")
        assert resp.status_code == 200
        body = json.loads(bytes(resp.body))
        assert body["export"]["closed_position_id"] == cid
        assert body["bundle"]["position_id"] == "POS1"
        assert body["export"]["signature"]

        nf = await rx.export_closed_position(999999, fmt="json")
        assert nf.status_code == 404
        assert "error" in json.loads(bytes(nf.body))


# ── PDF writer (P7.T5) ───────────────────────────────────────────────────────


class TestPdfWriter:
    def test_valid_pdf_structure(self):
        from core.pdf_writer import text_pdf
        pdf = text_pdf(["hello world", "second line"])
        assert pdf.startswith(b"%PDF-1.4")
        assert pdf.rstrip().endswith(b"%%EOF")
        assert b"xref" in pdf and b"trailer" in pdf and b"startxref" in pdf
        assert b"/BaseFont /Courier" in pdf
        assert b"(hello world)" in pdf and b"(second line)" in pdf   # uncompressed text

    def test_startxref_points_to_xref_table(self):
        from core.pdf_writer import text_pdf
        pdf = text_pdf(["x"])
        off = int(pdf.rsplit(b"startxref", 1)[1].split(b"%%EOF")[0].strip())
        assert pdf[off:off + 4] == b"xref"     # the offset actually indexes the xref keyword

    def test_string_special_chars_escaped(self):
        from core.pdf_writer import text_pdf
        pdf = text_pdf(["a (b) \\ c"])
        assert b"a \\(b\\) \\\\ c" in pdf       # ( ) \ backslash-escaped in the stream

    def test_pagination_multipage(self):
        import re
        from core.pdf_writer import text_pdf
        pdf = text_pdf([f"line {i}" for i in range(200)])   # > 65/page → several pages
        m = re.search(rb"/Count (\d+)", pdf)
        assert m and int(m.group(1)) >= 3
        assert b"(line 0)" in pdf and b"(line 199)" in pdf

    def test_empty_input_is_valid(self):
        from core.pdf_writer import text_pdf
        pdf = text_pdf([])
        assert pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF")

    def test_xref_entries_point_to_objects(self):
        # Every xref entry's byte offset must index its `N 0 obj` — a random-access
        # reader relies on this. Multi-page input exercises the LATER offsets too
        # (the ones that drift silently on a pagination regression).
        import re
        from core.pdf_writer import text_pdf
        pdf = text_pdf([f"line {i}" for i in range(150)])
        off = int(pdf.rsplit(b"startxref", 1)[1].split(b"%%EOF")[0].strip())
        xref = pdf[off:]
        n = int(re.search(rb"xref\n0 (\d+)", xref).group(1))
        entries = re.findall(rb"(\d{10}) 00000 n", xref)
        assert len(entries) == n - 1                       # object 0 is the free head
        for i, e in enumerate(entries, start=1):
            o = int(e)
            assert pdf[o:].startswith(b"%d 0 obj" % i), f"xref entry {i} offset {o} wrong"

    def test_content_stream_length_exact(self):
        # /Length must equal the exact byte span between `stream\n` and
        # `\nendstream` (the classic off-by-one a strict reader rejects).
        import re
        from core.pdf_writer import text_pdf
        pdf = text_pdf(["alpha", "beta gamma", "delta"])
        found = 0
        for m in re.finditer(rb"/Length (\d+) >>\nstream\n", pdf):
            length = int(m.group(1))
            start = m.end()
            tail = b"\nendstream"
            assert pdf[start + length:start + length + len(tail)] == tail
            found += 1
        assert found >= 1


class TestExportPdf:
    @pytest.mark.asyncio
    async def test_render_export_pdf_contains_key_fields(self, db, monkeypatch):
        from core.audit_export import render_export_pdf
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        cid = await _seed(db)
        env = await build_closed_position_export(db, cid)
        pdf = render_export_pdf(env)
        assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
        assert b"CLOSED-POSITION AUDIT EXPORT" in pdf
        assert b"POS1" in pdf                                # the position id (header)
        assert env["export"]["signature"].encode() in pdf   # SAME signature, in the footer
        # body content from the BUNDLE sections — a header-only regression (e.g.
        # dropping the _PDF_SECTIONS loop) would fail these, not just b"POS1".
        # (Section labels asserted WITHOUT the "(" — it's PDF-escaped to "\(".)
        assert b"ORDERS" in pdf and b"FILLS" in pdf and b"FUNDING" in pdf
        assert b"EO1" in pdf and b"F1" in pdf                # seeded order/fill ids (rows)

    @pytest.mark.asyncio
    async def test_route_format_pdf(self, db, monkeypatch):
        import api.routes_export as rx
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        monkeypatch.setattr(rx, "db", db)
        cid = await _seed(db)

        resp = await rx.export_closed_position(cid, fmt="pdf")
        assert resp.status_code == 200
        assert resp.media_type == "application/pdf"
        assert bytes(resp.body).startswith(b"%PDF")
        assert "attachment" in resp.headers.get("content-disposition", "")

        jr = await rx.export_closed_position(cid, fmt="json")
        assert jr.status_code == 200
        assert json.loads(bytes(jr.body))["bundle"]["position_id"] == "POS1"
        # Phase-8 #2: the JSON path MUST carry attachment disposition too, else
        # the native-form download button (position_events.html) navigates the
        # SPA to a raw JSON page instead of downloading. Advisory header — the
        # json.loads above still works, so programmatic callers are unaffected.
        assert "attachment" in jr.headers.get("content-disposition", "")

        # case-insensitive: ?format=PDF must also yield a PDF
        up = await rx.export_closed_position(cid, fmt="PDF")
        assert up.media_type == "application/pdf"
        assert bytes(up.body).startswith(b"%PDF")

        nf = await rx.export_closed_position(999999, fmt="pdf")
        assert nf.status_code == 404

    @pytest.mark.asyncio
    async def test_render_pdf_lifecycle_shape(self, db, monkeypatch):
        # The lifecycle-fallback bundle (no top-level position) must render.
        from core.audit_export import render_export_pdf
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        c = db._conn
        await c.execute(
            "INSERT INTO pre_trade_log (account_id, timestamp, ticker, calc_id, lifecycle_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (ACCOUNT_ID, "2026-06-01T00:00:00Z", "ETHUSDT", "CL", "LX"))
        await c.execute(
            "INSERT INTO positions_calcs (position_id, calc_id, order_id, account_id, "
            "contributed_qty, first_fill_ts, lifecycle_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("POSL", "CL", 1, ACCOUNT_ID, 1.0, 1100, "LX"))
        cur = await c.execute(
            "INSERT INTO closed_positions (account_id, terminal_position_id, symbol, "
            "exit_time_ms, lifecycle_id) VALUES (?, ?, ?, ?, ?)",
            (ACCOUNT_ID, "", "ETHUSDT", 6000, "LX"))
        await c.commit()
        env = await build_closed_position_export(db, cur.lastrowid)
        assert env["export"]["bundle_kind"] == "lifecycle"
        pdf = render_export_pdf(env)
        assert pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF")
        assert b"lifecycle" in pdf and b"CL" in pdf

    @pytest.mark.asyncio
    async def test_render_pdf_closed_row_only_shape(self, db, monkeypatch):
        # The degenerate closed-row-only bundle (no graph) must render.
        from core.audit_export import render_export_pdf
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        c = db._conn
        cur = await c.execute(
            "INSERT INTO closed_positions (account_id, terminal_position_id, symbol, "
            "exit_time_ms) VALUES (?, ?, ?, ?)",
            (ACCOUNT_ID, "", "BTCUSDT", 5000))
        await c.commit()
        env = await build_closed_position_export(db, cur.lastrowid)
        assert env["export"]["bundle_kind"] == "closed_row_only"
        pdf = render_export_pdf(env)
        assert pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF")
        assert b"closed_row_only" in pdf


# ── Batch / date-range export (P7.T6) ────────────────────────────────────────


async def _seed_batch(db):
    """POS1 (full graph + 2 partial closed rows, exits 2000+3000) + POS2 (one
    closed row, exit 4000). All account 1."""
    await _seed(db)            # POS1: graph + 1 closed row @ exit 2000
    c = db._conn
    await c.execute(
        "INSERT INTO closed_positions (account_id, terminal_position_id, symbol, "
        "exit_time_ms, calc_id, lifecycle_id) VALUES (?, ?, ?, ?, ?, ?)",
        (ACCOUNT_ID, "POS1", "BTCUSDT", 3000, "C1", "L1"))     # 2nd partial, same tpid
    await c.execute(
        "INSERT INTO closed_positions (account_id, terminal_position_id, symbol, "
        "exit_time_ms) VALUES (?, ?, ?, ?)",
        (ACCOUNT_ID, "POS2", "ETHUSDT", 4000))                 # a distinct position
    await c.execute(
        "INSERT INTO closed_positions (account_id, terminal_position_id, symbol, "
        "exit_time_ms) VALUES (?, ?, ?, ?)",
        (2, "POS_ACCT2", "SOLUSDT", 3500))    # a DIFFERENT account — must never leak
    await c.commit()


class TestBatchExport:
    @pytest.mark.asyncio
    async def test_range_helper(self, db):
        await _seed_batch(db)
        rows = await db.get_closed_positions_in_range(ACCOUNT_ID, 0, 10 ** 15)
        assert [r["exit_time_ms"] for r in rows] == [2000, 3000, 4000]   # oldest first
        assert await db.get_closed_positions_in_range(ACCOUNT_ID, 0, 100) == []   # range filter

    @pytest.mark.asyncio
    async def test_batch_dedups_multipartial_and_signs(self, db, monkeypatch):
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        await _seed_batch(db)
        batch = await build_batch_export(db, ACCOUNT_ID, 0, 10 ** 15)
        m = batch["manifest"]
        assert m["kind"] == "closed_positions_batch"
        assert m["count"] == 2                              # POS1 (deduped) + POS2
        assert set(m["position_ids"]) == {"POS1", "POS2"}
        assert len(batch["exports"]) == 2
        assert len(m["member_signatures"]) == 2
        # the POS1 member's bundle carries BOTH partials (export = whole position)
        pos1 = next(e for e in batch["exports"] if e["export"]["position_id"] == "POS1")
        assert len(pos1["bundle"]["closed_positions"]) == 2
        # manifest signature recomputes
        sig, algo = m.pop("signature"), m.pop("signature_algo")
        a2, s2 = _sign(_canonical(m))
        assert (a2, s2) == (algo, sig)

    @pytest.mark.asyncio
    async def test_batch_is_account_scoped(self, db, monkeypatch):
        # The lone WHERE account_id=? invariant: account 2's closed position must
        # NEVER appear in account 1's batch, and vice-versa.
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        await _seed_batch(db)
        b1 = await build_batch_export(db, ACCOUNT_ID, 0, 10 ** 15)
        assert "POS_ACCT2" not in b1["manifest"]["position_ids"]
        assert b1["manifest"]["count"] == 2                     # POS1 + POS2 only
        b2 = await build_batch_export(db, 2, 0, 10 ** 15)
        assert b2["manifest"]["position_ids"] == ["POS_ACCT2"]  # account 2's own

    @pytest.mark.asyncio
    async def test_manifest_tamper_changes_signature(self, db, monkeypatch):
        # Mutating a member signature (or the range) must change the batch
        # signature — the manifest is tamper-evident as a whole.
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        await _seed_batch(db)
        m = (await build_batch_export(db, ACCOUNT_ID, 0, 10 ** 15))["manifest"]
        orig = m["signature"]
        del m["signature"], m["signature_algo"]
        m["member_signatures"][0] = "0" * 64                   # tamper a member sig
        _, s2 = _sign(_canonical(m))
        assert s2 != orig

    @pytest.mark.asyncio
    async def test_batch_includes_empty_tpid_member(self, db, monkeypatch):
        # An observe-only (empty-tpid) closed row is its OWN batch member, packed
        # as the closed_row_only degenerate bundle (position_id None).
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        c = db._conn
        await c.execute(
            "INSERT INTO closed_positions (account_id, terminal_position_id, symbol, "
            "exit_time_ms) VALUES (?, ?, ?, ?)",
            (ACCOUNT_ID, "", "BTCUSDT", 9000))
        await c.commit()
        b = await build_batch_export(db, ACCOUNT_ID, 0, 10 ** 15)
        assert b["manifest"]["count"] == 1
        assert b["exports"][0]["export"]["bundle_kind"] == "closed_row_only"
        assert None in b["manifest"]["position_ids"]

    @pytest.mark.asyncio
    async def test_range_boundary_inclusive(self, db):
        await _seed_batch(db)                                  # account-1 exits 2000/3000/4000
        rows = await db.get_closed_positions_in_range(ACCOUNT_ID, 2000, 4000)
        assert [r["exit_time_ms"] for r in rows] == [2000, 3000, 4000]   # both ends inclusive

    @pytest.mark.asyncio
    async def test_batch_empty_range(self, db, monkeypatch):
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        await _seed_batch(db)
        batch = await build_batch_export(db, ACCOUNT_ID, 0, 100)   # before any exit
        assert batch["manifest"]["count"] == 0
        assert batch["exports"] == []
        assert batch["manifest"]["truncated"] is False

    @pytest.mark.asyncio
    async def test_batch_truncation_flagged_not_silent(self, db, monkeypatch):
        import core.audit_export as ae
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        monkeypatch.setattr(ae, "MAX_BATCH_POSITIONS", 1)
        await _seed_batch(db)                                 # 2 positions
        batch = await ae.build_batch_export(db, ACCOUNT_ID, 0, 10 ** 15)
        assert batch["manifest"]["truncated"] is True        # surfaced, not silent
        assert batch["manifest"]["count"] == 1               # capped
        assert batch["manifest"]["cap"] == 1

    @pytest.mark.asyncio
    async def test_render_batch_zip_json(self, db, monkeypatch):
        import io
        import zipfile
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        await _seed_batch(db)
        batch = await build_batch_export(db, ACCOUNT_ID, 0, 10 ** 15)
        z = zipfile.ZipFile(io.BytesIO(render_batch_zip(batch, "json")))
        names = z.namelist()
        assert "manifest.json" in names
        members = [n for n in names if n.startswith("closed_position_") and n.endswith(".json")]
        assert len(members) == 2
        env = json.loads(z.read(members[0]))
        assert env["export"]["signature"]                    # a signed envelope per member
        man = json.loads(z.read("manifest.json"))
        assert man["count"] == 2 and man["signature"]

    @pytest.mark.asyncio
    async def test_render_batch_zip_pdf(self, db, monkeypatch):
        import io
        import zipfile
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        await _seed_batch(db)
        batch = await build_batch_export(db, ACCOUNT_ID, 0, 10 ** 15)
        z = zipfile.ZipFile(io.BytesIO(render_batch_zip(batch, "pdf")))
        pdfs = [n for n in z.namelist() if n.endswith(".pdf")]
        assert len(pdfs) == 2
        assert z.read(pdfs[0]).startswith(b"%PDF")

    @pytest.mark.asyncio
    async def test_batch_route_zip_and_active_account_default(self, db, monkeypatch):
        import io
        import types
        import zipfile
        import api.routes_export as rx
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        monkeypatch.setattr(rx, "db", db)
        # active_account_id is a read-through property (no setter) → patch the
        # route module's app_state reference to a stub for the default-account path.
        monkeypatch.setattr(rx, "app_state", types.SimpleNamespace(active_account_id=ACCOUNT_ID))
        await _seed_batch(db)

        resp = await rx.export_closed_positions_batch(
            account_id=ACCOUNT_ID, from_ms=0, to_ms=10 ** 15, fmt="json")
        assert resp.status_code == 200
        assert resp.media_type == "application/zip"
        z = zipfile.ZipFile(io.BytesIO(bytes(resp.body)))
        assert "manifest.json" in z.namelist()

        # explicit account is honored AND reported in the manifest
        man0 = json.loads(z.read("manifest.json"))
        assert man0["account_id"] == ACCOUNT_ID

        # account_id=None → falls back to the active account
        resp2 = await rx.export_closed_positions_batch(
            account_id=None, from_ms=0, to_ms=10 ** 15, fmt="json")
        man = json.loads(zipfile.ZipFile(io.BytesIO(bytes(resp2.body))).read("manifest.json"))
        assert man["account_id"] == ACCOUNT_ID

    @pytest.mark.asyncio
    async def test_batch_route_pdf_format(self, db, monkeypatch):
        import io
        import zipfile
        import api.routes_export as rx
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        monkeypatch.setattr(rx, "db", db)
        await _seed_batch(db)
        resp = await rx.export_closed_positions_batch(
            account_id=ACCOUNT_ID, from_ms=0, to_ms=10 ** 15, fmt="pdf")
        assert resp.status_code == 200 and resp.media_type == "application/zip"
        z = zipfile.ZipFile(io.BytesIO(bytes(resp.body)))
        assert any(n.endswith(".pdf") for n in z.namelist())   # the route's pdf plumbing


# ── Cross-task integration (Phase 7 holistic audit, Task 286) ─────────────────


class TestContextExportEquivalence:
    """The export bundle and the /context graph come from the SAME assembler;
    these pin that the two entrypoints stay in lock-step AND that the signed
    export is sealed to the DB (the holistic-audit MED reproducibility fix)."""

    @pytest.mark.asyncio
    async def test_export_bundle_equals_context_graph_fully_closed(self, db, monkeypatch):
        # A fully-closed position with no live open: the signed export's bundle
        # must be byte-for-byte the /context/position graph (export = signed
        # /context — the two assembler entrypoints must not drift).
        from core.context_query import assemble_position_context, json_safe
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        cid = await _seed(db)                              # POS1 fully closed
        env = await build_closed_position_export(db, cid)
        ctx = json_safe(await assemble_position_context(db, "POS1"))   # /context path
        assert env["export"]["bundle_kind"] == "position"
        assert env["bundle"] == ctx                        # same graph, both json_safe'd

    @pytest.mark.asyncio
    async def test_export_seals_closed_even_with_live_open_same_tpid(self, db, monkeypatch):
        # The MED reproducibility fix (prefer_open=False): a signed export is
        # sealed to the PERSISTED closed row even if the same tpid is live OPEN in
        # app_state (a re-open under the same id). /context surfaces the live OPEN
        # snapshot; the export must stay CLOSED so its bundle is DB-reproducible.
        from core.context_query import assemble_position_context
        from core.state import app_state, PositionInfo
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        cid = await _seed(db)                              # POS1 closed row persisted
        monkeypatch.setattr(app_state, "positions",
                            [PositionInfo(position_id="POS1", size_delta_pct=9.0,
                                          amendment_count=2)])   # live re-open, same tpid
        # /context (prefer_open=True) surfaces the live OPEN snapshot …
        ctx = await assemble_position_context(db, "POS1")
        assert ctx["position_state"] == "open"
        # … but the signed export seals to the CLOSED row.
        env = await build_closed_position_export(db, cid)
        assert env["bundle"]["position_state"] == "closed"
        assert env["bundle"]["position"]["terminal_position_id"] == "POS1"
        # reproducible: a second export yields the IDENTICAL bundle regardless of
        # live state (the envelope's generated_at differs by design; the sealed
        # bundle does not — that's what makes the signature recomputable).
        env2 = await build_closed_position_export(db, cid)
        assert env2["bundle"] == env["bundle"]

    @pytest.mark.asyncio
    async def test_batch_mixed_bundle_kinds(self, db, monkeypatch):
        # One batch carrying all THREE member shapes at once: a full position
        # graph ("position"), an empty-tpid+lifecycle row ("lifecycle"), and an
        # empty-tpid no-lifecycle row ("closed_row_only"). Empty-tpid rows are
        # each their own member (dedup only collapses non-empty tpids).
        monkeypatch.setattr(config, "EXPORT_SIGNING_KEY", "")
        await _seed(db)                                   # POS1 full graph → "position"
        c = db._conn
        await c.execute(
            "INSERT INTO pre_trade_log (account_id, timestamp, ticker, calc_id, lifecycle_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (ACCOUNT_ID, "2026-06-01T00:00:00Z", "ETHUSDT", "CL", "LX"))
        await c.execute(
            "INSERT INTO positions_calcs (position_id, calc_id, order_id, account_id, "
            "contributed_qty, first_fill_ts, lifecycle_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("POSL", "CL", 1, ACCOUNT_ID, 1.0, 1100, "LX"))
        await c.execute(                                  # empty tpid + lifecycle → "lifecycle"
            "INSERT INTO closed_positions (account_id, terminal_position_id, symbol, "
            "exit_time_ms, lifecycle_id) VALUES (?, ?, ?, ?, ?)",
            (ACCOUNT_ID, "", "ETHUSDT", 6000, "LX"))
        await c.execute(                                  # empty tpid + no lifecycle → "closed_row_only"
            "INSERT INTO closed_positions (account_id, terminal_position_id, symbol, "
            "exit_time_ms) VALUES (?, ?, ?, ?)",
            (ACCOUNT_ID, "", "SOLUSDT", 7000))
        await c.commit()
        batch = await build_batch_export(db, ACCOUNT_ID, 0, 10 ** 15)
        assert batch["manifest"]["count"] == 3
        assert sorted(e["export"]["bundle_kind"] for e in batch["exports"]) == \
            ["closed_row_only", "lifecycle", "position"]
        # every member is independently signed (tamper-evidence per member)
        assert all(e["export"]["signature"] for e in batch["exports"])


class TestRouteAliasWiring:
    """The ``?format=`` query alias must bind to the ``fmt`` handler param. The
    handler tests call the functions directly (passing ``fmt=`` themselves),
    BYPASSING alias resolution — so a regression dropping ``alias="format"``
    would slip past them. Inspect the route's resolved query params instead
    (no TestClient — the suite's TestClient-in-a-fresh-file gotcha hangs)."""

    def _aliases(self, path):
        from fastapi.routing import APIRoute
        import api.routes_export as rx
        for r in rx.router.routes:
            if isinstance(r, APIRoute) and r.path == path:
                out = {}
                for qp in r.dependant.query_params:
                    out[qp.name] = getattr(qp, "alias", None) or getattr(
                        getattr(qp, "field_info", None), "alias", None)
                return out
        raise AssertionError(f"route {path} not found")

    def test_single_export_format_alias(self):
        a = self._aliases("/export/closed_position/{closed_position_id}")
        assert a["fmt"] == "format"          # ?format=pdf binds to fmt

    def test_batch_export_format_alias(self):
        a = self._aliases("/export/closed_positions")
        assert a["fmt"] == "format"
