"""Phase 7.1 reverse-query tests — GET /context/calc + /context/lifecycle.

Three layers:
  1. Assembly logic (FakeDB stub): the cross-DB orchestration + payload shape,
     primary-position resolution (open vs closed), deviations extraction,
     funding merge across positions, and lifecycle aggregation — WITHOUT schema
     coupling. These are the Rule-8 intent tests.
  2. DB helpers (real tmp DatabaseManager): the 6 new keyed SELECTs return the
     right rows in the right order (would FAIL on a wrong column name).
  3. End-to-end: assemble against a real seeded DB including the cross-DB
     trade_events join (events come from the per-account DB).

Run: pytest tests/test_phase7_context.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.context_query import (
    assemble_calc_context,
    assemble_lifecycle_context,
    assemble_position_context,
    json_safe,
    _primary_position_id,
    _ordered_unique,
    _deviations,
)

ACCOUNT_ID = 1


# ── Layer 1: FakeDB stub of the OrdersMixin reads the assembler uses ──────────


class FakeDB:
    """In-memory canned-row stub matching the db read helpers
    ``core.context_query`` calls. Each method filters the seeded rows by the
    same key the real SQL helper does."""

    def __init__(self, *, calcs=None, orders=None, fills=None, amendments=None,
                 junction=None, funding=None, closed=None):
        self.calcs = {c["calc_id"]: c for c in (calcs or [])}
        self.orders = orders or []
        self.fills = fills or []
        self.amendments = amendments or []
        self.junction = junction or []
        self.funding = funding or []
        self.closed = closed or []

    async def get_pretrade_log_by_calc_id(self, calc_id):
        return self.calcs.get(calc_id)

    async def get_pretrade_logs_by_calc_ids(self, calc_ids):
        return {c: self.calcs[c] for c in calc_ids if c in self.calcs}

    async def get_orders_by_calc_id(self, calc_id):
        return [o for o in self.orders if o.get("calc_id") == calc_id]

    async def get_orders_by_lifecycle_id(self, lifecycle_id):
        return [o for o in self.orders if o.get("lifecycle_id") == lifecycle_id]

    async def get_fills_by_calc_id(self, calc_id):
        return [f for f in self.fills if f.get("calc_id") == calc_id]

    async def get_fills_by_lifecycle_id(self, lifecycle_id):
        return [f for f in self.fills if f.get("lifecycle_id") == lifecycle_id]

    async def get_calc_amendments(self, calc_id, since_ms=None):
        return [a for a in self.amendments if a.get("calc_id") == calc_id]

    async def get_calc_position_links(self, calc_id):
        return [j for j in self.junction if j.get("calc_id") == calc_id]

    async def get_lifecycle_links(self, lifecycle_id):
        return [j for j in self.junction if j.get("lifecycle_id") == lifecycle_id]

    async def get_position_funding_events(self, position_id):
        return [f for f in self.funding if f.get("position_id") == position_id]

    async def get_closed_positions_by_position_id(self, position_id):
        return [c for c in self.closed if c.get("terminal_position_id") == position_id]

    async def get_closed_positions_by_lifecycle_id(self, lifecycle_id):
        return [c for c in self.closed if c.get("lifecycle_id") == lifecycle_id]

    async def get_position_calc_links(self, position_id):
        return [j for j in self.junction if j.get("position_id") == position_id]

    async def get_orders_by_position_id(self, position_id):
        return [o for o in self.orders if o.get("terminal_position_id") == position_id]

    async def get_fills_by_position_id(self, position_id):
        return [f for f in self.fills if f.get("terminal_position_id") == position_id]


def _calc(cid="C1", *, account_id=ACCOUNT_ID, lifecycle_id="L1"):
    return {"calc_id": cid, "account_id": account_id, "ticker": "BTCUSDT",
            "lifecycle_id": lifecycle_id}


def _jrow(cid="C1", pid="POS1", *, qty=1.0, ts=1000, lifecycle_id="L1"):
    return {"calc_id": cid, "position_id": pid, "order_id": 1, "account_id": ACCOUNT_ID,
            "contributed_qty": qty, "first_fill_ts": ts, "lifecycle_id": lifecycle_id}


def _closed(pid="POS1", *, lifecycle_id="L1", exit_time_ms=2000, **deltas):
    row = {"terminal_position_id": pid, "lifecycle_id": lifecycle_id,
           "account_id": ACCOUNT_ID, "symbol": "BTCUSDT", "exit_time_ms": exit_time_ms,
           "entry_px_delta_pct": 0.31, "size_delta_pct": -20.0, "realized_r": 1.85,
           "cumulative_amendment_count": 1}
    row.update(deltas)
    return row


class TestAssembleCalcContext:
    @pytest.mark.asyncio
    async def test_full_graph_closed_position(self, monkeypatch):
        # No open position → resolves to the closed row; deviations from its
        # delta columns; funding merged for the position; amendments scoped to
        # THIS calc only.
        from core.state import app_state
        monkeypatch.setattr(app_state, "positions", [])
        db = FakeDB(
            calcs=[_calc("C1")],
            orders=[{"calc_id": "C1", "id": 10, "lifecycle_id": "L1"}],
            fills=[{"calc_id": "C1", "id": 20, "lifecycle_id": "L1"}],
            amendments=[{"calc_id": "C1", "field": "sl_price", "id": 1},
                        {"calc_id": "OTHER", "field": "tp_price", "id": 2}],
            junction=[_jrow("C1", "POS1")],
            funding=[{"position_id": "POS1", "amount": -1.2, "id": 1},
                     {"position_id": "POS1", "amount": -0.8, "id": 2}],
            closed=[_closed("POS1")],
        )
        g = await assemble_calc_context(db, "C1")
        assert set(g) == {"calc", "orders", "fills", "amendments", "positions_calcs",
                          "position", "position_state", "funding_events",
                          "deviations", "events"}
        assert g["calc"]["calc_id"] == "C1"
        assert len(g["orders"]) == 1 and len(g["fills"]) == 1
        assert [a["calc_id"] for a in g["amendments"]] == ["C1"]   # scoped, not OTHER
        assert g["positions_calcs"] == db.junction
        assert g["position_state"] == "closed"
        assert g["position"]["terminal_position_id"] == "POS1"
        assert g["deviations"]["entry_px_delta_pct"] == 0.31
        assert "exit_time_ms" not in g["deviations"]              # only delta cols
        assert len(g["funding_events"]) == 2                      # merged for POS1

    @pytest.mark.asyncio
    async def test_open_position_takes_precedence(self, monkeypatch):
        # A live open PositionInfo for the junction's position wins over any
        # closed row; deviations come from the live size-delta surface.
        from core.state import app_state, PositionInfo
        pos = PositionInfo(position_id="POS1", size_delta_pct=12.5,
                           amendment_count=3, deviation_badge="yellow")
        monkeypatch.setattr(app_state, "positions", [pos])
        db = FakeDB(calcs=[_calc("C1")], junction=[_jrow("C1", "POS1")],
                    closed=[_closed("POS1")])  # closed row exists but open wins
        g = await assemble_calc_context(db, "C1")
        assert g["position_state"] == "open"
        assert g["position"]["position_id"] == "POS1"
        assert g["deviations"] == {"size_delta_pct": 12.5,
                                   "amendment_count": 3, "deviation_badge": "yellow"}

    @pytest.mark.asyncio
    async def test_no_position_yet(self, monkeypatch):
        from core.state import app_state
        monkeypatch.setattr(app_state, "positions", [])
        db = FakeDB(calcs=[_calc("C1")])  # calc never filled → no junction
        g = await assemble_calc_context(db, "C1")
        assert g["position_state"] is None
        assert g["position"] is None
        assert g["deviations"] == {}
        assert g["funding_events"] == []

    @pytest.mark.asyncio
    async def test_multi_position_resolves_most_contributing(self, monkeypatch):
        # Calc spans two positions; `position` resolves the larger-contributed
        # one (§3.2), funding merges BOTH, junction keeps both.
        from core.state import app_state
        monkeypatch.setattr(app_state, "positions", [])
        db = FakeDB(
            calcs=[_calc("C1")],
            junction=[_jrow("C1", "POSA", qty=3.0, ts=1000),
                      _jrow("C1", "POSB", qty=7.0, ts=2000)],
            funding=[{"position_id": "POSA", "amount": -1.0, "id": 1},
                     {"position_id": "POSB", "amount": -2.0, "id": 2}],
            closed=[_closed("POSA", exit_time_ms=1500),
                    _closed("POSB", exit_time_ms=2500)],
        )
        g = await assemble_calc_context(db, "C1")
        assert g["position"]["terminal_position_id"] == "POSB"   # 7 > 3
        assert len(g["positions_calcs"]) == 2
        assert len(g["funding_events"]) == 2

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self):
        db = FakeDB(calcs=[])
        assert await assemble_calc_context(db, "MISSING") is None

    @pytest.mark.asyncio
    async def test_events_merged_and_time_sorted(self, monkeypatch):
        from core.state import app_state
        monkeypatch.setattr(app_state, "positions", [])
        # query_trade_events is patched (newest-first per the real API); the
        # assembler re-sorts ascending by timestamp.
        def _fake_query(*, account_id, calc_id, limit=100, **kw):
            return ([{"event_type": "position_closed", "timestamp": "2026-06-04T10:05:00", "calc_id": calc_id},
                     {"event_type": "order_filled", "timestamp": "2026-06-04T10:01:00", "calc_id": calc_id}], 2)
        monkeypatch.setattr("core.trade_event_log.query_trade_events", _fake_query)
        db = FakeDB(calcs=[_calc("C1", account_id=7)])
        g = await assemble_calc_context(db, "C1")
        ts = [e["timestamp"] for e in g["events"]]
        assert ts == sorted(ts)                       # ascending
        assert ts[0].endswith("10:01:00")

    @pytest.mark.asyncio
    async def test_events_empty_when_no_account(self, monkeypatch):
        from core.state import app_state
        monkeypatch.setattr(app_state, "positions", [])
        # A guard so a None account_id never reaches the per-account read.
        def _boom(**kw):  # pragma: no cover - must not be called
            raise AssertionError("query_trade_events should not run without account_id")
        monkeypatch.setattr("core.trade_event_log.query_trade_events", _boom)
        db = FakeDB(calcs=[{"calc_id": "C1", "account_id": None}])
        g = await assemble_calc_context(db, "C1")
        assert g["events"] == []


class TestAssembleLifecycleContext:
    @pytest.mark.asyncio
    async def test_aggregates_contributing_calcs(self, monkeypatch):
        # A scale-in lifecycle: two calcs (C1, C2) → one position; calcs plural,
        # amendments merged across both calcs + time-sorted, closed rows present.
        from core.state import app_state
        monkeypatch.setattr(app_state, "positions", [])
        monkeypatch.setattr("core.trade_event_log.query_trade_events",
                            lambda **kw: ([], 0))
        db = FakeDB(
            calcs=[_calc("C1", lifecycle_id="L1"), _calc("C2", lifecycle_id="L1")],
            orders=[{"calc_id": "C1", "lifecycle_id": "L1", "id": 1}],
            fills=[{"calc_id": "C1", "lifecycle_id": "L1", "id": 1}],
            amendments=[{"calc_id": "C2", "field": "sl_price", "ts_ms": 50, "id": 2},
                        {"calc_id": "C1", "field": "tp_price", "ts_ms": 10, "id": 1}],
            junction=[_jrow("C1", "POS1", lifecycle_id="L1"),
                      _jrow("C2", "POS1", lifecycle_id="L1")],
            closed=[_closed("POS1", lifecycle_id="L1")],
        )
        g = await assemble_lifecycle_context(db, "L1")
        assert g["lifecycle_id"] == "L1"
        assert [c["calc_id"] for c in g["calcs"]] == ["C1", "C2"]
        # amendments merged across calcs, ascending by ts_ms (C1.ts=10 before C2.ts=50)
        assert [a["ts_ms"] for a in g["amendments"]] == [10, 50]
        assert g["position_state"] == "closed"
        assert len(g["closed_positions"]) == 1
        assert len(g["positions_calcs"]) == 2

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self):
        db = FakeDB(junction=[])
        assert await assemble_lifecycle_context(db, "NOPE") is None


class TestAssemblePositionContext:
    @pytest.mark.asyncio
    async def test_junction_bearing_position_aggregates(self, monkeypatch):
        # Scale-in position: two calcs → one position; keyed on position_id.
        # `position` resolves THIS position (the query key), not a contributing
        # pick. A confounding junction row for a DIFFERENT position (C9/POSOTHER)
        # must NOT leak into contributing_calc_ids (pins the position_id filter).
        from core.state import app_state
        monkeypatch.setattr(app_state, "positions", [])
        monkeypatch.setattr("core.trade_event_log.query_trade_events", lambda **kw: ([], 0))
        db = FakeDB(
            calcs=[_calc("C1"), _calc("C2"), _calc("C9")],
            orders=[{"terminal_position_id": "POS1", "calc_id": "C1", "id": 1}],
            fills=[{"terminal_position_id": "POS1", "calc_id": "C1", "id": 1}],
            amendments=[{"calc_id": "C1", "field": "sl_price", "ts_ms": 10, "id": 1}],
            junction=[_jrow("C1", "POS1"), _jrow("C2", "POS1"),
                      _jrow("C9", "POSOTHER")],   # confound: a DIFFERENT position
            funding=[{"position_id": "POS1", "amount": -1.0, "id": 1}],
            closed=[_closed("POS1")],
        )
        g = await assemble_position_context(db, "POS1")
        assert g["position_id"] == "POS1"
        assert g["contributing_calc_ids"] == ["C1", "C2"]   # NOT C9 (other position)
        assert g["lifecycle_id"] == "L1"
        assert [c["calc_id"] for c in g["calcs"]] == ["C1", "C2"]
        assert g["position_state"] == "closed"
        assert g["position"]["terminal_position_id"] == "POS1"
        assert g["deviations"]["entry_px_delta_pct"] == 0.31
        assert len(g["orders"]) == 1 and len(g["fills"]) == 1
        assert len(g["funding_events"]) == 1
        assert g["amendments"][0]["field"] == "sl_price"

    @pytest.mark.asyncio
    async def test_junction_bearing_open_position(self, monkeypatch):
        # Live scale-in: an OPEN position WITH junction calcs — `position` is the
        # live PositionInfo (open wins) yet contributing_calc_ids stays populated.
        from core.state import app_state, PositionInfo
        pos = PositionInfo(position_id="POS1", size_delta_pct=4.0, amendment_count=1)
        monkeypatch.setattr(app_state, "positions", [pos])
        monkeypatch.setattr("core.trade_event_log.query_trade_events", lambda **kw: ([], 0))
        db = FakeDB(
            calcs=[_calc("C1"), _calc("C2")],
            junction=[_jrow("C1", "POS1"), _jrow("C2", "POS1")],
            closed=[_closed("POS1")],   # closed row exists but open wins
        )
        g = await assemble_position_context(db, "POS1")
        assert g["position_state"] == "open"
        assert g["position"]["position_id"] == "POS1"
        assert g["contributing_calc_ids"] == ["C1", "C2"]
        assert g["deviations"]["size_delta_pct"] == 4.0

    @pytest.mark.asyncio
    async def test_junction_less_unplanned_position(self, monkeypatch):
        # An UNPLANNED position (no calc, no junction) still returns a graph from
        # its position-keyed orders/fills/closed; calcs/amendments/events empty.
        # lifecycle_id falls back to the closed row (junction arm empty).
        from core.state import app_state
        monkeypatch.setattr(app_state, "positions", [])
        # query_trade_events must NOT run (no calc_ids → no account events)
        monkeypatch.setattr(
            "core.trade_event_log.query_trade_events",
            lambda **kw: (_ for _ in ()).throw(AssertionError("no calc → no events read")))
        db = FakeDB(
            orders=[{"terminal_position_id": "POSU", "id": 9}],
            fills=[{"terminal_position_id": "POSU", "id": 9}],
            closed=[_closed("POSU", lifecycle_id="LU")],
            junction=[],   # UNPLANNED → no junction
        )
        g = await assemble_position_context(db, "POSU")
        assert g is not None
        assert g["contributing_calc_ids"] == []
        assert g["calcs"] == []
        assert g["amendments"] == []
        assert g["events"] == []
        assert g["lifecycle_id"] == "LU"     # fell back to the closed row
        assert g["position_state"] == "closed"
        assert len(g["orders"]) == 1 and len(g["fills"]) == 1

    @pytest.mark.asyncio
    async def test_open_position_keyed_directly(self, monkeypatch):
        # `position` resolves the QUERIED position open-or-closed — for an open
        # position it's the live PositionInfo, even with no junction.
        from core.state import app_state, PositionInfo
        pos = PositionInfo(position_id="POSO", size_delta_pct=3.0, amendment_count=1)
        monkeypatch.setattr(app_state, "positions", [pos])
        monkeypatch.setattr("core.trade_event_log.query_trade_events", lambda **kw: ([], 0))
        db = FakeDB(orders=[{"terminal_position_id": "POSO", "id": 1}])
        g = await assemble_position_context(db, "POSO")
        assert g["position_state"] == "open"
        assert g["position"]["position_id"] == "POSO"

    @pytest.mark.asyncio
    async def test_no_trace_returns_none(self, monkeypatch):
        from core.state import app_state
        monkeypatch.setattr(app_state, "positions", [])
        db = FakeDB()  # nothing seeded
        assert await assemble_position_context(db, "GHOST") is None


class TestPureHelpers:
    def test_ordered_unique_drops_falsy_and_dups(self):
        assert _ordered_unique(["a", "b", "a", None, "", "c", "b"]) == ["a", "b", "c"]

    def test_primary_position_id_by_summed_qty(self):
        j = [_jrow("C1", "A", qty=2.0, ts=1000), _jrow("C1", "A", qty=2.0, ts=1000),
             _jrow("C1", "B", qty=3.0, ts=2000)]
        assert _primary_position_id(j) == "A"   # 2+2=4 > 3

    def test_primary_position_id_tie_breaks_earliest(self):
        j = [_jrow("C1", "A", qty=5.0, ts=2000), _jrow("C1", "B", qty=5.0, ts=1000)]
        assert _primary_position_id(j) == "B"   # tie → earliest first_fill_ts

    def test_primary_position_id_empty(self):
        assert _primary_position_id([]) is None

    def test_deviations_closed_only_delta_cols(self):
        row = {"entry_px_delta_pct": 1.0, "size_delta_pct": 2.0, "exit_time_ms": 99,
               "realized_r": 1.5}
        d = _deviations("closed", row)
        assert d == {"entry_px_delta_pct": 1.0, "size_delta_pct": 2.0, "realized_r": 1.5}

    def test_deviations_open_fields(self):
        info = {"size_delta_pct": 5.0, "amendment_count": 2, "deviation_badge": "red",
                "position_id": "X"}
        assert _deviations("open", info) == {"size_delta_pct": 5.0,
                                             "amendment_count": 2, "deviation_badge": "red"}

    def test_deviations_none(self):
        assert _deviations(None, None) == {}


class TestJsonSafe:
    """json_safe defends the JSON boundary: Starlette renders with
    allow_nan=False, and SQLite round-trips a REAL inf as Python inf, so an
    un-sanitized graph could 500 on a stray adapter-ingested inf."""

    def test_non_finite_floats_become_none(self):
        out = json_safe({"a": float("inf"), "b": float("-inf"), "c": float("nan"),
                         "d": 1.5, "e": [float("inf"), 2.0], "f": {"g": float("nan")}})
        assert out == {"a": None, "b": None, "c": None, "d": 1.5,
                       "e": [None, 2.0], "f": {"g": None}}

    def test_finite_and_non_floats_pass_through(self):
        payload = {"i": 7, "s": "x", "n": None, "b": True, "lst": ["a", 1, 2.5]}
        assert json_safe(payload) == payload

    def test_rendered_payload_has_no_nan_inf_token(self):
        import json
        rendered = json.dumps(json_safe({"x": float("inf")}))  # default allow_nan=True
        assert "Infinity" not in rendered and "NaN" not in rendered


# ── Layer 2: real-DB helper smoke tests (verify the SQL columns/keys/order) ───


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


async def _seed_full_graph(db):
    """Seed one calc → order → fill → junction → closed → funding → amendment,
    all keyed calc=C1 / lifecycle=L1 / position=POS1 / account=1."""
    c = db._conn
    await c.execute(
        "INSERT INTO pre_trade_log (account_id, timestamp, ticker, calc_id, lifecycle_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (ACCOUNT_ID, "2026-06-01T00:00:00Z", "BTCUSDT", "C1", "L1"))
    await c.execute(
        "INSERT INTO orders (account_id, exchange_order_id, symbol, side, calc_id, "
        "lifecycle_id, terminal_position_id, created_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ACCOUNT_ID, "EO1", "BTCUSDT", "BUY", "C1", "L1", "POS1", 1000))
    await c.execute(
        "INSERT INTO fills (account_id, exchange_fill_id, exchange_order_id, symbol, "
        "side, terminal_position_id, calc_id, lifecycle_id, timestamp_ms, is_close) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ACCOUNT_ID, "F1", "EO1", "BTCUSDT", "BUY", "POS1", "C1", "L1", 1100, 0))
    await c.execute(
        "INSERT INTO positions_calcs (position_id, calc_id, order_id, account_id, "
        "contributed_qty, first_fill_ts, lifecycle_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("POS1", "C1", 1, ACCOUNT_ID, 1.0, 1100, "L1"))
    await c.execute(
        "INSERT INTO closed_positions (account_id, terminal_position_id, symbol, "
        "exit_time_ms, calc_id, lifecycle_id, entry_px_delta_pct, size_delta_pct) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ACCOUNT_ID, "POS1", "BTCUSDT", 2000, "C1", "L1", 0.5, -10.0))
    await c.execute(
        "INSERT INTO funding_events (position_id, calc_id, account_id, symbol, amount, "
        "ts_ms, venue_event_id, lifecycle_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("POS1", "C1", ACCOUNT_ID, "BTCUSDT", -1.2, 1500, "binance:fe1", "L1"))
    await c.execute(
        "INSERT INTO order_amendments (order_id, calc_id, field, old_value, new_value, "
        "ts_ms, lifecycle_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "C1", "sl_price", 49000.0, 49500.0, 1300, "L1"))
    await c.commit()


class TestNewReadHelpers:
    @pytest.mark.asyncio
    async def test_orders_by_calc_and_lifecycle(self, db):
        await _seed_full_graph(db)
        assert (await db.get_orders_by_calc_id("C1"))[0]["exchange_order_id"] == "EO1"
        assert (await db.get_orders_by_lifecycle_id("L1"))[0]["exchange_order_id"] == "EO1"
        assert await db.get_orders_by_calc_id("NONE") == []
        assert await db.get_orders_by_calc_id("") == []     # falsy guard

    @pytest.mark.asyncio
    async def test_fills_by_calc_and_lifecycle(self, db):
        await _seed_full_graph(db)
        assert (await db.get_fills_by_calc_id("C1"))[0]["exchange_fill_id"] == "F1"
        assert (await db.get_fills_by_lifecycle_id("L1"))[0]["exchange_fill_id"] == "F1"

    @pytest.mark.asyncio
    async def test_orders_and_fills_by_position_id(self, db):
        await _seed_full_graph(db)   # order + fill both carry terminal_position_id=POS1
        assert (await db.get_orders_by_position_id("POS1"))[0]["exchange_order_id"] == "EO1"
        assert (await db.get_fills_by_position_id("POS1"))[0]["exchange_fill_id"] == "F1"
        assert await db.get_orders_by_position_id("NONE") == []
        assert await db.get_fills_by_position_id("") == []   # falsy guard

    @pytest.mark.asyncio
    async def test_closed_positions_by_position_and_lifecycle(self, db):
        await _seed_full_graph(db)
        by_pos = await db.get_closed_positions_by_position_id("POS1")
        by_life = await db.get_closed_positions_by_lifecycle_id("L1")
        assert by_pos[0]["entry_px_delta_pct"] == 0.5
        assert by_life[0]["terminal_position_id"] == "POS1"

    @pytest.mark.asyncio
    async def test_multi_partial_closed_rows_newest_exit_first(self, db, monkeypatch):
        # Multi-TP preserves a closed_positions row per partial (T2.11). The
        # helper must return them newest-exit-first, and the calc graph's
        # singular `position` must be the NEWEST (row[0]) — pins the
        # `ORDER BY exit_time_ms DESC` selection.
        from core.state import app_state
        monkeypatch.setattr(app_state, "positions", [])
        monkeypatch.setattr("core.trade_event_log.query_trade_events",
                            lambda **kw: ([], 0))
        c = db._conn
        await c.execute(
            "INSERT INTO pre_trade_log (account_id, timestamp, ticker, calc_id, lifecycle_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (ACCOUNT_ID, "2026-06-01T00:00:00Z", "BTCUSDT", "CM", "LM"))
        await c.execute(
            "INSERT INTO positions_calcs (position_id, calc_id, order_id, account_id, "
            "contributed_qty, first_fill_ts, lifecycle_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("POSM", "CM", 1, ACCOUNT_ID, 1.0, 1100, "LM"))
        for exit_ms, dpct in ((2000, 1.0), (3000, 9.9)):   # newer row carries 9.9
            await c.execute(
                "INSERT INTO closed_positions (account_id, terminal_position_id, symbol, "
                "exit_time_ms, calc_id, lifecycle_id, entry_px_delta_pct) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ACCOUNT_ID, "POSM", "BTCUSDT", exit_ms, "CM", "LM", dpct))
        await c.commit()
        rows = await db.get_closed_positions_by_position_id("POSM")
        assert [r["exit_time_ms"] for r in rows] == [3000, 2000]   # newest first
        g = await assemble_calc_context(db, "CM")
        assert g["position"]["exit_time_ms"] == 3000               # row[0] = newest
        assert g["deviations"]["entry_px_delta_pct"] == 9.9


# ── Layer 3: end-to-end assemble against a real seeded DB (+ cross-DB events) ──


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_calc_context_e2e(self, db, monkeypatch):
        from core.state import app_state
        from core.trade_event_log import log_trade_event
        monkeypatch.setattr(app_state, "positions", [])  # no open → closed path
        await _seed_full_graph(db)
        # A trade event in the per-account DB (the conftest guard redirects this
        # un-isolated write to the throwaway iso DB; the assembler's read is the
        # same un-isolated path → it reads the same iso DB → consistent). Use a
        # UNIQUE source sentinel the live DB cannot contain, so this proves the
        # cross-DB join (and a guard regression → reading live → would NOT find
        # the sentinel → fails) rather than passing on live-DB-contents luck.
        log_trade_event(ACCOUNT_ID, "C1", "order_filled",
                        {"symbol": "BTCUSDT"}, source="phase7-e2e-sentinel")

        g = await assemble_calc_context(db, "C1")
        assert g is not None
        assert g["calc"]["calc_id"] == "C1"
        assert g["orders"][0]["calc_id"] == "C1"
        assert g["fills"][0]["calc_id"] == "C1"
        assert g["positions_calcs"][0]["position_id"] == "POS1"
        assert g["position_state"] == "closed"
        assert g["deviations"]["entry_px_delta_pct"] == 0.5
        assert g["funding_events"][0]["amount"] == -1.2
        assert g["amendments"][0]["field"] == "sl_price"
        assert len(g["events"]) >= 1                      # cross-DB read non-empty
        assert any(e.get("source") == "phase7-e2e-sentinel" for e in g["events"])

    @pytest.mark.asyncio
    async def test_lifecycle_context_e2e(self, db, monkeypatch):
        from core.state import app_state
        monkeypatch.setattr(app_state, "positions", [])
        monkeypatch.setattr("core.trade_event_log.query_trade_events",
                            lambda **kw: ([], 0))
        await _seed_full_graph(db)
        g = await assemble_lifecycle_context(db, "L1")
        assert g is not None
        assert [c["calc_id"] for c in g["calcs"]] == ["C1"]
        assert g["orders"][0]["calc_id"] == "C1"
        assert g["closed_positions"][0]["terminal_position_id"] == "POS1"
        assert g["funding_events"][0]["amount"] == -1.2

    @pytest.mark.asyncio
    async def test_lifecycle_not_found_e2e(self, db):
        await _seed_full_graph(db)
        assert await assemble_lifecycle_context(db, "NOPE") is None

    @pytest.mark.asyncio
    async def test_position_context_e2e(self, db, monkeypatch):
        from core.state import app_state
        monkeypatch.setattr(app_state, "positions", [])
        monkeypatch.setattr("core.trade_event_log.query_trade_events", lambda **kw: ([], 0))
        await _seed_full_graph(db)
        g = await assemble_position_context(db, "POS1")
        assert g is not None
        assert g["position_id"] == "POS1"
        assert g["contributing_calc_ids"] == ["C1"]
        assert g["lifecycle_id"] == "L1"
        assert g["orders"][0]["exchange_order_id"] == "EO1"   # by terminal_position_id
        assert g["fills"][0]["exchange_fill_id"] == "F1"
        assert g["position_state"] == "closed"
        assert g["closed_positions"][0]["entry_px_delta_pct"] == 0.5
        assert g["funding_events"][0]["amount"] == -1.2

    @pytest.mark.asyncio
    async def test_position_not_found_e2e(self, db):
        await _seed_full_graph(db)
        assert await assemble_position_context(db, "GHOST") is None


# ── Layer 4: route handlers (direct-call; no TestClient — Lesson 9 hang) ──────


def _json_body(resp):
    import json
    return json.loads(bytes(resp.body))


class TestRouteHandlers:
    """Drive the FastAPI handlers directly (the codebase TestClient-in-a-fresh-
    file gotcha hangs the suite). Pins the 200 + JSONResponse render and the
    None → 404 mapping the assembler tests don't cover."""

    @pytest.mark.asyncio
    async def test_context_calc_200_and_404(self, db, monkeypatch):
        import api.routes_context as rc
        from core.state import app_state
        monkeypatch.setattr(rc, "db", db)               # route uses the module singleton
        monkeypatch.setattr(app_state, "positions", [])
        monkeypatch.setattr("core.trade_event_log.query_trade_events", lambda **kw: ([], 0))
        await _seed_full_graph(db)

        resp = await rc.context_calc("C1")
        assert resp.status_code == 200
        body = _json_body(resp)                          # would raise if not JSON-renderable
        assert body["calc"]["calc_id"] == "C1"
        assert body["position_state"] == "closed"

        nf = await rc.context_calc("MISSING")
        assert nf.status_code == 404
        assert "error" in _json_body(nf)

    @pytest.mark.asyncio
    async def test_context_lifecycle_200_and_404(self, db, monkeypatch):
        import api.routes_context as rc
        from core.state import app_state
        monkeypatch.setattr(rc, "db", db)
        monkeypatch.setattr(app_state, "positions", [])
        monkeypatch.setattr("core.trade_event_log.query_trade_events", lambda **kw: ([], 0))
        await _seed_full_graph(db)

        resp = await rc.context_lifecycle("L1")
        assert resp.status_code == 200
        assert _json_body(resp)["lifecycle_id"] == "L1"

        nf = await rc.context_lifecycle("NOPE")
        assert nf.status_code == 404
        assert "error" in _json_body(nf)

    @pytest.mark.asyncio
    async def test_context_position_200_and_404(self, db, monkeypatch):
        import api.routes_context as rc
        from core.state import app_state
        monkeypatch.setattr(rc, "db", db)
        monkeypatch.setattr(app_state, "positions", [])
        monkeypatch.setattr("core.trade_event_log.query_trade_events", lambda **kw: ([], 0))
        await _seed_full_graph(db)

        resp = await rc.context_position("POS1")
        assert resp.status_code == 200
        body = _json_body(resp)
        assert body["position_id"] == "POS1"
        assert body["contributing_calc_ids"] == ["C1"]

        nf = await rc.context_position("GHOST")
        assert nf.status_code == 404
        assert "error" in _json_body(nf)

    @pytest.mark.asyncio
    async def test_inf_in_real_column_renders_without_500(self, db, monkeypatch):
        # A stray non-finite REAL (e.g. a bad adapter mark_price) must NOT 500
        # the endpoint — json_safe coerces it to null (Starlette renders with
        # allow_nan=False, and SQLite round-trips inf as Python inf).
        import api.routes_context as rc
        from core.state import app_state
        monkeypatch.setattr(rc, "db", db)
        monkeypatch.setattr(app_state, "positions", [])
        monkeypatch.setattr("core.trade_event_log.query_trade_events", lambda **kw: ([], 0))
        c = db._conn
        await c.execute(
            "INSERT INTO pre_trade_log (account_id, timestamp, ticker, calc_id, lifecycle_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (ACCOUNT_ID, "2026-06-01T00:00:00Z", "BTCUSDT", "CINF", "LINF"))
        await c.execute(
            "INSERT INTO positions_calcs (position_id, calc_id, order_id, account_id, "
            "contributed_qty, first_fill_ts, lifecycle_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("POSINF", "CINF", 1, ACCOUNT_ID, 1.0, 1100, "LINF"))
        await c.execute(
            "INSERT INTO closed_positions (account_id, terminal_position_id, symbol, "
            "exit_time_ms, calc_id, lifecycle_id, entry_px_delta_pct) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ACCOUNT_ID, "POSINF", "BTCUSDT", 2000, "CINF", "LINF", float("inf")))
        await c.commit()

        resp = await rc.context_calc("CINF")
        assert resp.status_code == 200                   # did NOT 500
        body = _json_body(resp)                          # parses (no Infinity token)
        assert body["deviations"]["entry_px_delta_pct"] is None   # inf → null
