"""
Phase 5 (funding + fees) — ingestion path tests.

Covers deliverable 1: funding events get fetched, attributed to the open
position for their symbol, and written to ``funding_events`` (the
``position_id``-keyed SUM basis for ``closed_positions.funding_fees`` at close).

Verifies the load-bearing verify-first findings:

  1. ``funding_events.position_id`` is TEXT (reconciled from the shipped
     INTEGER) so it joins the engine's universal ``terminal_position_id`` key
     — and a TEXT tpid round-trips through insert → sum.
  2. The INTEGER→TEXT recreate migration preserves any existing rows.
  3. ``funding_handler.handle_funding_incomes`` attributes to the open
     position, dedups on the synthetic ``venue_event_id``, and orphans funding
     with no attributable open position (spec §11[F]).

Run: pytest tests/test_phase5_funding.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.funding_handler import (  # noqa: E402
    handle_funding_incomes,
    synthetic_venue_event_id,
)
from core.state import PositionInfo  # noqa: E402


@pytest_asyncio.fixture
async def db():
    """Tempfile DB initialized with the full schema (runs P5 migration)."""
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    dbm = DatabaseManager(path=tmp.name)
    await dbm.initialize()
    yield dbm
    await dbm.close()
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(tmp.name + ext)
        except OSError:
            pass


async def _table_columns(db, table: str) -> dict:
    async with db._conn.execute(f"PRAGMA table_info({table})") as cur:
        return {row[1]: row[2] for row in await cur.fetchall()}


async def _table_indexes(db, table: str) -> set:
    async with db._conn.execute(f"PRAGMA index_list({table})") as cur:
        return {row[1] for row in await cur.fetchall()}


async def _table_exists(db, table: str) -> bool:
    async with db._conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ) as cur:
        return (await cur.fetchone()) is not None


def _income(symbol: str, amount: float, ts: int, itype: str = "FUNDING_FEE") -> dict:
    """Shape returned by exchange_income.fetch_income_history."""
    return {"symbol": symbol, "incomeType": itype, "income": amount,
            "time": ts, "tradeId": ""}


async def _resolver_ab(_account_id, _tpid):
    return ("calc-a", "life-1")


# ── 1. position_id key: TEXT, round-trips, migrates ──────────────────────────


class TestFundingPositionIdKey:
    @pytest.mark.asyncio
    async def test_schema_position_id_is_text(self, db):
        # The whole point of P5's verify-first fix: the funding key must be the
        # TEXT terminal_position_id, not the shipped INTEGER (else the close SUM
        # would join an INTEGER-coerced key against a TEXT tpid and read 0).
        cols = await _table_columns(db, "funding_events")
        assert cols["position_id"] == "TEXT"

    @pytest.mark.asyncio
    async def test_text_tpid_round_trips_through_sum(self, db):
        # A non-numeric TEXT tpid (the shape Quantower can emit) must store and
        # sum back exactly — the failure mode INTEGER affinity would cause.
        tpid = "pos-abc-123"
        for i, amt in enumerate([-0.05, -0.04, 0.02], start=1):
            ok = await db.insert_funding_event({
                "position_id": tpid, "calc_id": "calc-a", "account_id": 1,
                "symbol": "BTCUSDT", "amount": amt, "ts_ms": 1000 * i,
                "venue_event_id": f"evt-{i}",
            })
            assert ok is True
        total = await db.sum_position_funding(tpid)
        assert total == pytest.approx(-0.07)
        # Isolation: a different tpid sums independently.
        assert await db.sum_position_funding("other") == 0.0

    @pytest.mark.asyncio
    async def test_migration_recreates_integer_as_text(self):
        # Faithfully simulate the live-DB upgrade: an OLD funding_events with
        # INTEGER position_id + a row, then initialize() over it. The guarded
        # recreate must flip the column to TEXT and PRESERVE the row (CAST).
        import aiosqlite
        from core.database import DatabaseManager
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            conn = await aiosqlite.connect(tmp.name)
            await conn.executescript(
                """
                CREATE TABLE funding_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id INTEGER NOT NULL,
                    calc_id TEXT, account_id INTEGER NOT NULL, symbol TEXT NOT NULL,
                    amount REAL NOT NULL DEFAULT 0, mark_price REAL, funding_rate REAL,
                    ts_ms INTEGER NOT NULL, venue_event_id TEXT NOT NULL,
                    lifecycle_id TEXT, UNIQUE(venue_event_id));
                CREATE INDEX idx_fe_position ON funding_events (position_id);
                CREATE INDEX idx_fe_account_ts ON funding_events (account_id, ts_ms);
                CREATE INDEX idx_fe_lifecycle ON funding_events (lifecycle_id);
                """
            )
            await conn.execute(
                "INSERT INTO funding_events "
                "(position_id, account_id, symbol, amount, ts_ms, venue_event_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (123, 1, "BTCUSDT", -0.05, 1000, "evt-old"),
            )
            await conn.commit()
            await conn.close()

            dbm = DatabaseManager(path=tmp.name)
            await dbm.initialize()
            cols = await _table_columns(dbm, "funding_events")
            assert cols["position_id"] == "TEXT"
            # Indexes rebuilt on the new table (the DROP-before-CREATE-INDEX
            # ordering must free the old names first, else the recreate would
            # silently land an index-less table).
            idx = await _table_indexes(dbm, "funding_events")
            assert {"idx_fe_position", "idx_fe_account_ts", "idx_fe_lifecycle"} <= idx
            # The temp rename target is dropped — no orphan left behind.
            assert not await _table_exists(dbm, "_funding_events_int")
            # Row preserved; INTEGER 123 cast to TEXT "123".
            rows = await dbm.get_position_funding_events("123")
            assert len(rows) == 1
            assert rows[0]["venue_event_id"] == "evt-old"
            # Idempotent: re-initialize is a no-op (already TEXT).
            await dbm.close()
            dbm2 = DatabaseManager(path=tmp.name)
            await dbm2.initialize()
            assert (await _table_columns(dbm2, "funding_events"))["position_id"] == "TEXT"
            await dbm2.close()
        finally:
            for ext in ("", "-wal", "-shm"):
                try:
                    os.unlink(tmp.name + ext)
                except OSError:
                    pass


# ── 2. synthetic venue_event_id ──────────────────────────────────────────────


class TestSyntheticVenueEventId:
    def test_deterministic_and_scoped(self):
        a = synthetic_venue_event_id(1, "BTCUSDT", 1700000000000)
        b = synthetic_venue_event_id(1, "BTCUSDT", 1700000000000)
        assert a == b == "binance:funding:1:BTCUSDT:1700000000000"
        # Distinct per account / symbol / settlement ts.
        assert a != synthetic_venue_event_id(2, "BTCUSDT", 1700000000000)
        assert a != synthetic_venue_event_id(1, "ETHUSDT", 1700000000000)
        assert a != synthetic_venue_event_id(1, "BTCUSDT", 1700000028800)


# ── 3. handle_funding_incomes: attribution / dedup / orphan ──────────────────


class TestHandleFundingIncomes:
    @pytest.mark.asyncio
    async def test_attributes_to_open_position(self, db):
        positions = [PositionInfo(position_id="pos-1", ticker="BTCUSDT")]
        res = await handle_funding_incomes(
            account_id=1,
            incomes=[_income("BTCUSDT", -0.05, 1000)],
            positions=positions, db=db, primary_calc_resolver=_resolver_ab,
        )
        assert res == {"written": 1, "deduped": 0, "orphan": 0}
        rows = await db.get_position_funding_events("pos-1")
        assert len(rows) == 1
        r = rows[0]
        assert r["symbol"] == "BTCUSDT"
        assert r["amount"] == pytest.approx(-0.05)
        # calc_id + lifecycle_id denormalized from the shared primary resolver.
        assert r["calc_id"] == "calc-a"
        assert r["lifecycle_id"] == "life-1"
        assert r["venue_event_id"] == "binance:funding:1:BTCUSDT:1000"

    @pytest.mark.asyncio
    async def test_dedup_same_window_reposted(self, db):
        positions = [PositionInfo(position_id="pos-1", ticker="BTCUSDT")]
        incomes = [_income("BTCUSDT", -0.05, 1000), _income("BTCUSDT", -0.04, 2000)]
        first = await handle_funding_incomes(
            account_id=1, incomes=incomes, positions=positions, db=db,
            primary_calc_resolver=_resolver_ab,
        )
        assert first["written"] == 2
        # Re-poll the SAME window — synthetic id makes every row a no-op insert.
        second = await handle_funding_incomes(
            account_id=1, incomes=incomes, positions=positions, db=db,
            primary_calc_resolver=_resolver_ab,
        )
        assert second == {"written": 0, "deduped": 2, "orphan": 0}
        assert await db.sum_position_funding("pos-1") == pytest.approx(-0.09)

    @pytest.mark.asyncio
    async def test_orphan_when_no_open_position(self, db):
        # Funding for a symbol with no open position (e.g. settled post-close).
        res = await handle_funding_incomes(
            account_id=1, incomes=[_income("XRPUSDT", -0.01, 1000)],
            positions=[PositionInfo(position_id="pos-1", ticker="BTCUSDT")],
            db=db, primary_calc_resolver=_resolver_ab,
        )
        assert res == {"written": 0, "deduped": 0, "orphan": 1}
        assert await db.sum_position_funding("pos-1") == 0.0

    @pytest.mark.asyncio
    async def test_orphan_when_empty_tpid(self, db):
        # binance one-way leaves position_id empty -> not attributable.
        res = await handle_funding_incomes(
            account_id=1, incomes=[_income("BTCUSDT", -0.01, 1000)],
            positions=[PositionInfo(position_id="", ticker="BTCUSDT")],
            db=db, primary_calc_resolver=_resolver_ab,
        )
        assert res["orphan"] == 1 and res["written"] == 0

    @pytest.mark.asyncio
    async def test_ignores_non_funding_rows(self, db):
        res = await handle_funding_incomes(
            account_id=1,
            incomes=[
                _income("BTCUSDT", 5.0, 1000, itype="REALIZED_PNL"),
                _income("BTCUSDT", -0.05, 2000),
            ],
            positions=[PositionInfo(position_id="pos-1", ticker="BTCUSDT")],
            db=db, primary_calc_resolver=_resolver_ab,
        )
        assert res["written"] == 1  # only the FUNDING_FEE row
        assert await db.sum_position_funding("pos-1") == pytest.approx(-0.05)

    @pytest.mark.asyncio
    async def test_resolver_fault_still_writes_row(self, db):
        # A denormalization (resolver) fault must NOT drop the funding row —
        # the close-time SUM keys on position_id only.
        async def _boom(_a, _t):
            raise RuntimeError("junction read failed")

        res = await handle_funding_incomes(
            account_id=1, incomes=[_income("BTCUSDT", -0.05, 1000)],
            positions=[PositionInfo(position_id="pos-1", ticker="BTCUSDT")],
            db=db, primary_calc_resolver=_boom,
        )
        assert res["written"] == 1
        rows = await db.get_position_funding_events("pos-1")
        assert rows[0]["calc_id"] is None
        assert rows[0]["lifecycle_id"] is None

    @pytest.mark.asyncio
    async def test_per_position_isolation(self, db):
        positions = [
            PositionInfo(position_id="pos-btc", ticker="BTCUSDT"),
            PositionInfo(position_id="pos-eth", ticker="ETHUSDT"),
        ]
        res = await handle_funding_incomes(
            account_id=1,
            incomes=[_income("BTCUSDT", -0.05, 1000), _income("ETHUSDT", -0.03, 1000)],
            positions=positions, db=db, primary_calc_resolver=_resolver_ab,
        )
        assert res["written"] == 2
        assert await db.sum_position_funding("pos-btc") == pytest.approx(-0.05)
        assert await db.sum_position_funding("pos-eth") == pytest.approx(-0.03)


# ── 4. loop wiring smoke ─────────────────────────────────────────────────────


class TestFundingLoopWiring:
    def test_loop_is_coroutine_and_registered(self):
        import inspect
        from core import schedulers
        assert inspect.iscoroutinefunction(schedulers._funding_refresh_loop)
        # Registered in the background-task startup (source-level guard so a
        # silent de-registration is caught).
        src = inspect.getsource(schedulers.start_background_tasks)
        assert "_funding_refresh_loop()" in src


# ── 5. P5.T4/T5: funding_fees + net_pnl at close ─────────────────────────────

ACCOUNT_ID = 1


@pytest.fixture(autouse=True)
def _no_live_trade_events(monkeypatch):
    """Shield the live per-account DB from close-path trade-event writes.

    ``_build_close_row_for_fill`` emits a ``position_closed`` trade event via
    a lazy ``from core.trade_event_log import log_trade_event`` — which resolves
    ``config.DATA_DIR`` (where account 1 exists live). Patching the module
    attribute binds the fake at call time. Autouse so the close-path tests
    below can't pollute; a no-op for the handler/schema tests above.
    """
    monkeypatch.setattr(
        "core.trade_event_log.log_trade_event",
        lambda *a, **k: None,
    )


@pytest_asyncio.fixture
async def om(db):
    from core.order_manager import OrderManager
    return OrderManager(db)


async def _seed_junction_cp(db, pos_id, calc_id, *, order_id=1, qty=2.0, ts=1000):
    await db.upsert_position_calc_link({
        "position_id": pos_id, "calc_id": calc_id, "order_id": order_id,
        "account_id": ACCOUNT_ID, "contributed_qty": qty,
        "first_fill_ts": ts, "last_fill_ts": ts, "lifecycle_id": "lc-1",
        "planned_size": qty, "planned_tp": None, "planned_sl": None,
    })


async def _seed_order_cp(db, eoid, order_type, side, status="filled"):
    await db._conn.execute(
        "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
        " order_type, status) VALUES (?, ?, 'BTCUSDT', ?, ?, ?)",
        (ACCOUNT_ID, eoid, side, order_type, status),
    )
    await db._conn.commit()


async def _seed_fill_cp(db, fid, eoid, tpid, qty, is_close, ts, *,
                        fee=0.0, realized_pnl=0.0, price=50000.0, calc_id="C1"):
    await db._conn.execute(
        "INSERT INTO fills (account_id, exchange_fill_id, exchange_order_id, "
        " terminal_position_id, symbol, side, direction, price, quantity, fee, "
        " is_close, realized_pnl, timestamp_ms, calc_id) "
        "VALUES (?, ?, ?, ?, 'BTCUSDT', ?, 'LONG', ?, ?, ?, ?, ?, ?, ?)",
        (ACCOUNT_ID, fid, eoid, tpid, "SELL" if is_close else "BUY",
         price, qty, fee, int(is_close), realized_pnl, ts, calc_id),
    )
    await db._conn.commit()


async def _seed_funding_cp(db, tpid, amount, ts, evt):
    await db.insert_funding_event({
        "position_id": tpid, "calc_id": "C1", "account_id": ACCOUNT_ID,
        "symbol": "BTCUSDT", "amount": amount, "ts_ms": ts,
        "venue_event_id": evt,
    })


def _close_fill_cp(eoid, tpid, ts):
    return {
        "terminal_position_id": tpid, "symbol": "BTCUSDT", "direction": "LONG",
        "exchange_order_id": eoid, "timestamp_ms": ts,
        "exchange_position_id": "", "source": "",
    }


async def _closed_row_cp(db, tpid, exit_time):
    async with db._conn.execute(
        "SELECT * FROM closed_positions WHERE account_id=? "
        "AND terminal_position_id=? AND exit_time_ms=?",
        (ACCOUNT_ID, tpid, exit_time),
    ) as cur:
        r = await cur.fetchone()
    return dict(r) if r else None


class TestFundingAtClose:
    @pytest.mark.asyncio
    async def test_funding_summed_into_final_close(self, db, om):
        # Full close: funding_fees = SUM(funding_events), net_pnl includes it.
        await _seed_junction_cp(db, "POS-1", "C1", qty=2.0)
        await _seed_order_cp(db, "EO", "limit", "BUY")
        await _seed_fill_cp(db, "FO", "EO", "POS-1", 2.0, False, 1000, fee=0.5)
        await _seed_funding_cp(db, "POS-1", -0.05, 1200, "fe-1")
        await _seed_funding_cp(db, "POS-1", -0.04, 1400, "fe-2")
        await _seed_order_cp(db, "XO", "market", "SELL")
        await _seed_fill_cp(db, "FX", "XO", "POS-1", 2.0, True, 2000,
                            fee=1.5, realized_pnl=100.0, price=51000.0)
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill_cp("XO", "POS-1", 2000))

        row = await _closed_row_cp(db, "POS-1", 2000)
        assert row is not None
        assert row["funding_fees"] == pytest.approx(-0.09)
        # total_fees = close_fees(1.5) + prop_entry(0.5*2/2=0.5) = 2.0
        assert row["total_fees"] == pytest.approx(2.0)
        # net_pnl = realized(100) - fees(2.0) + funding(-0.09) = 97.91
        assert row["net_pnl"] == pytest.approx(97.91)

    @pytest.mark.asyncio
    async def test_no_funding_events_zero(self, db, om):
        await _seed_junction_cp(db, "POS-1", "C1", qty=1.0)
        await _seed_order_cp(db, "EO", "limit", "BUY")
        await _seed_fill_cp(db, "FO", "EO", "POS-1", 1.0, False, 1000, fee=0.5)
        await _seed_order_cp(db, "XO", "market", "SELL")
        await _seed_fill_cp(db, "FX", "XO", "POS-1", 1.0, True, 2000,
                            fee=0.5, realized_pnl=10.0)
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill_cp("XO", "POS-1", 2000))

        row = await _closed_row_cp(db, "POS-1", 2000)
        assert row["funding_fees"] == pytest.approx(0.0)
        # net_pnl = 10 - (0.5 + 0.5) + 0 = 9.0
        assert row["net_pnl"] == pytest.approx(9.0)

    @pytest.mark.asyncio
    async def test_partial_carries_zero_final_carries_full(self, db, om):
        # Multi-TP: per-partial rows preserved (T2.11). Funding lands ONLY on
        # the final row — the partial row must be 0 so the position total isn't
        # double-counted across rows.
        await _seed_junction_cp(db, "POS-1", "C1", qty=2.0)
        await _seed_order_cp(db, "EO", "limit", "BUY")
        await _seed_fill_cp(db, "FO", "EO", "POS-1", 2.0, False, 1000, fee=0.4)
        await _seed_funding_cp(db, "POS-1", -0.06, 1500, "fe-1")

        # Partial close (1 of 2) — NOT final.
        await _seed_order_cp(db, "XO1", "take_profit", "SELL")
        await _seed_fill_cp(db, "FX1", "XO1", "POS-1", 1.0, True, 2000,
                            fee=0.3, realized_pnl=40.0, price=52000.0)
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill_cp("XO1", "POS-1", 2000))

        # Final close (the remaining 1).
        await _seed_order_cp(db, "XO2", "take_profit", "SELL")
        await _seed_fill_cp(db, "FX2", "XO2", "POS-1", 1.0, True, 3000,
                            fee=0.3, realized_pnl=50.0, price=53000.0)
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill_cp("XO2", "POS-1", 3000))

        partial = await _closed_row_cp(db, "POS-1", 2000)
        final = await _closed_row_cp(db, "POS-1", 3000)
        assert partial["funding_fees"] == pytest.approx(0.0)   # not final
        assert final["funding_fees"] == pytest.approx(-0.06)   # full position SUM
        # Summed across the per-partial rows, funding is counted exactly once.
        assert (partial["funding_fees"] + final["funding_fees"]) == pytest.approx(-0.06)

    @pytest.mark.asyncio
    async def test_empty_tpid_carries_zero_funding(self, db, om):
        # binance one-way empty-tpid: is_final is forced True but the `and
        # pos_id` guard keeps funding 0 (nothing to key the SUM on).
        await _seed_order_cp(db, "EO", "limit", "BUY")
        await _seed_fill_cp(db, "FO", "EO", "", 1.0, False, 1000, fee=0.2)
        await _seed_order_cp(db, "XO", "market", "SELL")
        await _seed_fill_cp(db, "FX", "XO", "", 1.0, True, 2000,
                            fee=0.2, realized_pnl=5.0)
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill_cp("XO", "", 2000))

        row = await _closed_row_cp(db, "", 2000)
        assert row is not None
        assert row["funding_fees"] == pytest.approx(0.0)

    def test_funding_fees_not_in_delta_preserve_set(self):
        # Documented deviation: funding_fees is NOT NULL DEFAULT 0, so it does
        # NOT use the None-sentinel _CLOSED_POS_DELTA_COLS preserve (which would
        # spread None over the default). The live builder is the sole real-tpid
        # writer and recomputes the SUM each final build.
        from core.db_orders import _CLOSED_POS_DELTA_COLS
        assert "funding_fees" not in _CLOSED_POS_DELTA_COLS
        assert "net_pnl" not in _CLOSED_POS_DELTA_COLS
