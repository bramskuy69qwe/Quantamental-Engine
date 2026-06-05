"""
Phase 8 Task 5 (P8.T5) — replacement-decision REFRAME.

The spec §10.4 pre-submission replacement modal is architecturally impossible
(observe-only engine; no place_order hook — Lesson 4 / Phase-1 reframe). The
achievable equivalent is POST-arrival: when a replacement order near-matches a
RELEASED calc (its prior order was cancelled), surface that in the needs-link
queue so the operator's manual link IS the replacement decision.

This pins the reframe:
  - find_candidate_calcs now filters to live calcs (status IN active/released),
    which (a) drops expired/cancelled/superseded leakage AND (b) FIXES a latent
    bug — the old "exclude any calc_id present in orders" guard wrongly excluded
    released calcs (their cancelled order still carries calc_id), so a released
    calc never surfaced as a manual-link candidate;
  - released candidates carry status + the cancelled order they replace;
  - the needs-link UI shows a REPLACEMENT badge + "replaces order X" + a
    "Link (replace)" action.

Run: pytest tests/test_phase8_replacement.py -v
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

import jinja2
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.calc_correlation import (  # noqa: E402
    find_candidate_calcs,
    _cancelled_order_for_calc,
)


# ── _cancelled_order_for_calc (direct, minimal orders table) ──────────────────


class TestCancelledOrderLookup:
    def _conn(self):
        c = sqlite3.connect(":memory:")
        c.execute(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, account_id INTEGER, "
            "calc_id TEXT, status TEXT, exchange_order_id TEXT, cancel_ts_ms INTEGER)"
        )
        return c

    def test_returns_most_recent_cancelled(self):
        c = self._conn()
        c.execute("INSERT INTO orders (account_id, calc_id, status, exchange_order_id, cancel_ts_ms) VALUES "
                  "(1, 'R1', 'canceled', 'O-OLD', 1000), "
                  "(1, 'R1', 'canceled', 'O-NEW', 5000), "
                  "(1, 'R1', 'filled', 'O-FILLED', 9000), "
                  "(2, 'R1', 'canceled', 'O-ACCT2', 9999)")     # newer but other account
        c.commit()
        assert _cancelled_order_for_calc(c, "R1", 1) == {"exchange_order_id": "O-NEW", "cancel_ts_ms": 5000}

    def test_account_scoped(self):
        # Phase 8 audit: the lookup must not leak another account's cancelled
        # order even when it's more recent (combined-DB fallback safety).
        c = self._conn()
        c.execute("INSERT INTO orders (account_id, calc_id, status, exchange_order_id, cancel_ts_ms) VALUES "
                  "(2, 'R1', 'canceled', 'O-ACCT2', 9999)")
        c.commit()
        assert _cancelled_order_for_calc(c, "R1", 1) is None     # account 1 sees nothing

    def test_none_when_no_cancelled(self):
        c = self._conn()
        c.execute("INSERT INTO orders (account_id, calc_id, status, exchange_order_id) VALUES (1, 'R2', 'new', 'O-1')")
        c.commit()
        assert _cancelled_order_for_calc(c, "R2", 1) is None

    def test_none_on_bad_table(self):
        c = sqlite3.connect(":memory:")  # no orders table
        assert _cancelled_order_for_calc(c, "X", 1) is None


# ── find_candidate_calcs status filter + replacement context ──────────────────


@pytest_asyncio.fixture
async def db():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    d = DatabaseManager(path=tmp.name)
    await d.initialize()
    await d._conn.execute("INSERT OR IGNORE INTO accounts (id, name) VALUES (1, 'Test')")
    await d._conn.commit()
    yield d, tmp.name
    await d.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


async def _calc(d, calc_id, status):
    await d.insert_pre_trade_log({
        "account_id": 1, "ticker": "BTCUSDT", "side": "long",
        "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
        "calc_id": calc_id, "status": status,
    })


_ORDER = {"symbol": "BTCUSDT", "side": "BUY", "price": 50000.0,
          "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.0, "account_id": 1}


class TestCandidateStatusFilter:
    @pytest.mark.asyncio
    async def test_only_active_and_released_are_candidates(self, db):
        d, path = db
        await _calc(d, "A1", "active")
        await _calc(d, "R1", "released")
        await _calc(d, "M1", "matched")
        await _calc(d, "E1", "expired")
        await _calc(d, "C1", "cancelled_by_operator")
        await _calc(d, "S1", "superseded")
        cands = find_candidate_calcs(_ORDER, db_path=path)
        assert {c.calc_id for c in cands} == {"A1", "R1"}

    @pytest.mark.asyncio
    async def test_released_calc_now_surfaces_despite_cancelled_order(self, db):
        # the bug fix: a released calc whose cancelled order still carries its
        # calc_id MUST still appear as a candidate (old `linked` guard dropped it)
        d, path = db
        await _calc(d, "R1", "released")
        await d._conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, calc_id, status, cancel_ts_ms) "
            "VALUES (1, 'O-OLD', 'BTCUSDT', 'BUY', 'R1', 'canceled', 1700000000000)"
        )
        await d._conn.commit()
        cands = find_candidate_calcs(_ORDER, db_path=path)
        r1 = next((c for c in cands if c.calc_id == "R1"), None)
        assert r1 is not None
        assert r1.status == "released"
        assert r1.replaced_order == {"exchange_order_id": "O-OLD", "cancel_ts_ms": 1700000000000}

    @pytest.mark.asyncio
    async def test_active_candidate_has_no_replacement_context(self, db):
        d, path = db
        await _calc(d, "A1", "active")
        cands = find_candidate_calcs(_ORDER, db_path=path)
        a1 = next(c for c in cands if c.calc_id == "A1")
        assert a1.status == "active"
        assert a1.replaced_order is None

    @pytest.mark.asyncio
    async def test_released_without_cancelled_order_has_none_context(self, db):
        d, path = db
        await _calc(d, "R1", "released")  # no orders rows seeded
        cands = find_candidate_calcs(_ORDER, db_path=path)
        r1 = next(c for c in cands if c.calc_id == "R1")
        assert r1.status == "released" and r1.replaced_order is None


# ── needs_link_queue.html replacement UI (compile-render) ─────────────────────


def _env():
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    env.globals["fmt"] = lambda v, n=2: f"{float(v):.{n}f}" if isinstance(v, (int, float)) else str(v)
    env.globals["ms_to_local"] = lambda ms: "2026-06-05 14:02:00" if ms else "—"
    return env


def _cand(calc_id="C-AAAAAAAAAAAA", status="active", replaced=None):
    return {
        "calc_id": calc_id, "ticker": "BTCUSDT", "side": "long",
        "effective_entry": 50000.0, "entry_drift_pct": 0.001, "entry_match": True,
        "tp_price": 55000.0, "tp_drift_pct": 0.002, "tp_match": True,
        "sl_price": 48000.0, "sl_drift_pct": 0.003, "sl_match": False,
        "timestamp": "2026-06-05T00:00:00+00:00", "age_hours": 1.5,
        "status": status, "replaced_order": replaced,
    }


def _order(candidates):
    return {"id": 7, "symbol": "BTCUSDT", "side": "long", "order_type": "limit",
            "price": 50000.0, "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.0,
            "link_status": "NEEDS_MANUAL_REVIEW", "candidates": candidates}


def _render(orders):
    return _env().get_template("fragments/needs_link_queue.html").render(orders=orders)


class TestReplacementUI:
    def test_released_candidate_shows_replacement(self):
        html = _render([_order([_cand(
            status="released",
            replaced={"exchange_order_id": "O-OLD", "cancel_ts_ms": 1700000000000},
        )])])
        assert "REPLACEMENT" in html
        assert "replaces O-OLD" in html
        assert "2026-06-05 14:02:00" in html        # cancel time via ms_to_local
        assert "Link (replace)" in html             # action label

    def test_released_without_context_still_badges(self):
        html = _render([_order([_cand(status="released", replaced=None)])])
        assert "REPLACEMENT" in html
        assert "replaces" not in html               # no cancelled-order line
        assert "Link (replace)" in html

    def test_active_candidate_no_replacement(self):
        html = _render([_order([_cand(status="active")])])
        assert "REPLACEMENT" not in html
        assert "Link (replace)" not in html
        assert ">\n          Link\n" in html or ">Link<" in html or "Link\n" in html
