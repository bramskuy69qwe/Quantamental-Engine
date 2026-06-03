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
        # The funding key must be the TEXT terminal_position_id, not the shipped
        # INTEGER. The real INTEGER-affinity hazard is COLLISION, not a zero-read:
        # distinct numeric tpids collapse (leading-zero "00123"==123; >int64
        # overflow), leaking another position's funding into the SUM. Matching
        # the sibling TEXT key (positions_calcs/closed_positions) is unambiguous.
        cols = await _table_columns(db, "funding_events")
        assert cols["position_id"] == "TEXT"

    @pytest.mark.asyncio
    async def test_text_tpid_round_trips_through_sum(self, db):
        # A non-numeric TEXT tpid stores + sums back exactly under TEXT. (Under
        # INTEGER affinity it would also store fine — affinity can't coerce it —
        # so this pins the round-trip; the numeric-collision hazard is the actual
        # reason for the TEXT migration, asserted by the schema-type test.)
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

    @pytest.mark.asyncio
    async def test_migration_fails_loud_if_not_text(self, monkeypatch):
        # FAIL-LOUD guard (audit): if the recreate does NOT flip the column to
        # TEXT, initialize() must RAISE (abort startup) rather than boot with a
        # mis-keyed funding column. Sabotage = no-op the recreate executescript
        # so position_id stays INTEGER; the post-migration PRAGMA verify must
        # then raise. Pins that a future edit can't silently swallow the failure.
        import aiosqlite
        from core.database import DatabaseManager
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            conn = await aiosqlite.connect(tmp.name)
            await conn.execute(
                "CREATE TABLE funding_events (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " position_id INTEGER NOT NULL, calc_id TEXT, account_id INTEGER"
                " NOT NULL, symbol TEXT NOT NULL, amount REAL NOT NULL DEFAULT 0,"
                " mark_price REAL, funding_rate REAL, ts_ms INTEGER NOT NULL,"
                " venue_event_id TEXT NOT NULL, lifecycle_id TEXT,"
                " UNIQUE(venue_event_id))")
            await conn.commit()
            await conn.close()

            real_es = aiosqlite.Connection.executescript

            async def _sabotage(self, sql):
                if "_funding_events_int" in sql:   # the recreate script only
                    return                          # no-op → stays INTEGER
                return await real_es(self, sql)

            monkeypatch.setattr(aiosqlite.Connection, "executescript", _sabotage)
            dbm = DatabaseManager(path=tmp.name)
            with pytest.raises(RuntimeError, match="migration did not take"):
                await dbm.initialize()
            try:
                await dbm.close()
            except Exception:
                pass
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
        assert res == {"written": 1, "deduped": 0, "orphan": 0, "reconciled": 0}
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
        assert second == {"written": 0, "deduped": 2, "orphan": 0, "reconciled": 0}
        assert await db.sum_position_funding("pos-1") == pytest.approx(-0.09)

    @pytest.mark.asyncio
    async def test_orphan_when_no_open_position(self, db):
        # Funding for a symbol with no open position (e.g. settled post-close).
        res = await handle_funding_incomes(
            account_id=1, incomes=[_income("XRPUSDT", -0.01, 1000)],
            positions=[PositionInfo(position_id="pos-1", ticker="BTCUSDT")],
            db=db, primary_calc_resolver=_resolver_ab,
        )
        assert res == {"written": 0, "deduped": 0, "orphan": 1, "reconciled": 0}
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

    @pytest.mark.asyncio
    async def test_orphan_writes_no_funding_row(self, db):
        # An orphan must be SKIPPED, not written under an empty/sentinel key —
        # else the empty-key row would later be picked up by funding_by_pos.get("")
        # or a COUNT. Assert the table stays empty (audit Rule-8 gap: prior
        # orphan tests only checked sum("pos-1")==0, not row absence).
        res = await handle_funding_incomes(
            account_id=1, incomes=[_income("XRPUSDT", -0.01, 1000)],
            positions=[PositionInfo(position_id="", ticker="XRPUSDT")],
            db=db, primary_calc_resolver=_resolver_ab,
        )
        assert res["orphan"] == 1 and res["written"] == 0
        async with db._conn.execute("SELECT COUNT(*) FROM funding_events") as cur:
            assert (await cur.fetchone())[0] == 0


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
    async def test_positive_funding_received_increases_net(self, db, om):
        # Funding RECEIVED (positive — short side of a negative-rate symbol):
        # net must INCREASE. Guards the sign on the funding-received path; every
        # other funded test uses negative funding, so an abs()/sign-flip slip
        # would otherwise survive (audit Rule-8 gap).
        await _seed_junction_cp(db, "POS-1", "C1", qty=1.0)
        await _seed_order_cp(db, "EO", "limit", "BUY")
        await _seed_fill_cp(db, "FO", "EO", "POS-1", 1.0, False, 1000, fee=0.5)
        await _seed_funding_cp(db, "POS-1", 0.10, 1200, "fe-pos")
        await _seed_order_cp(db, "XO", "market", "SELL")
        await _seed_fill_cp(db, "FX", "XO", "POS-1", 1.0, True, 2000,
                            fee=0.5, realized_pnl=20.0)
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill_cp("XO", "POS-1", 2000))
        row = await _closed_row_cp(db, "POS-1", 2000)
        assert row["funding_fees"] == pytest.approx(0.10)
        # net = realized(20) - fees(1.0) + funding(+0.10) = 19.10
        assert row["net_pnl"] == pytest.approx(19.10)

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


# ── 6. P5.T7: live unrealized-funding view ───────────────────────────────────

import jinja2  # noqa: E402
from types import SimpleNamespace  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(__file__))


class TestSumFundingByPositions:
    @pytest.mark.asyncio
    async def test_groups_by_position(self, db):
        await _seed_funding_cp(db, "P1", -0.05, 1000, "e1")
        await _seed_funding_cp(db, "P1", -0.04, 2000, "e2")
        await _seed_funding_cp(db, "P2", 0.02, 1500, "e3")
        out = await db.sum_funding_by_positions(["P1", "P2", "P3"])
        assert out["P1"] == pytest.approx(-0.09)
        assert out["P2"] == pytest.approx(0.02)
        assert "P3" not in out          # no funding → absent (caller defaults 0)

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self, db):
        assert await db.sum_funding_by_positions([]) == {}


class TestLiveFundingEnrichment:
    @pytest.mark.asyncio
    async def test_funded_position_stamped(self, db, om):
        await _seed_funding_cp(db, "POS-1", -0.05, 1000, "e1")
        await _seed_funding_cp(db, "POS-1", -0.03, 2000, "e2")
        positions = [PositionInfo(position_id="POS-1", ticker="BTCUSDT")]
        await om._enrich_positions_calc_id(ACCOUNT_ID, positions)
        assert positions[0].individual_funding_fees == pytest.approx(-0.08)

    @pytest.mark.asyncio
    async def test_position_without_funding_zero(self, db, om):
        positions = [PositionInfo(position_id="POS-9", ticker="ETHUSDT")]
        await om._enrich_positions_calc_id(ACCOUNT_ID, positions)
        assert positions[0].individual_funding_fees == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_empty_tpid_zero_funded_neighbor_summed(self, db, om):
        # binance one-way empty-tpid stays 0 (not attributable); a funded
        # tpid'd neighbor in the same refresh still gets its SUM.
        await _seed_funding_cp(db, "POS-1", -0.05, 1000, "e1")
        positions = [
            PositionInfo(position_id="", ticker="XRPUSDT"),
            PositionInfo(position_id="POS-1", ticker="BTCUSDT"),
        ]
        await om._enrich_positions_calc_id(ACCOUNT_ID, positions)
        assert positions[0].individual_funding_fees == pytest.approx(0.0)
        assert positions[1].individual_funding_fees == pytest.approx(-0.05)

    @pytest.mark.asyncio
    async def test_junctioned_position_funding_and_calc_coexist(self, db, om):
        # A PLANNED position (has a positions_calcs junction) must get BOTH
        # calc_id (junction logic) AND individual_funding_fees stamped — funding
        # enrichment must not be skipped when the junction/badge branch runs
        # (audit Rule-8 gap: the other enrichment tests have no junction, so
        # per_pos is empty and the junction branch never executes).
        await db.upsert_position_calc_link({
            "position_id": "POS-1", "calc_id": "calc-z", "order_id": 1,
            "account_id": ACCOUNT_ID, "contributed_qty": 5.0,
            "first_fill_ts": 1000, "last_fill_ts": 1000,
            "lifecycle_id": "lc-z", "planned_size": 5.0,
            "planned_tp": None, "planned_sl": None,
        })
        await _seed_funding_cp(db, "POS-1", -0.07, 1000, "fe-j")
        positions = [PositionInfo(position_id="POS-1", ticker="BTCUSDT")]
        await om._enrich_positions_calc_id(ACCOUNT_ID, positions)
        assert positions[0].individual_funding_fees == pytest.approx(-0.07)
        assert positions[0].calc_id == "calc-z"   # junction logic still ran


class TestFundingResolverIntegration:
    @pytest.mark.asyncio
    async def test_real_primary_calc_resolver_denormalizes(self, db, om):
        # Drive the handler with the REAL OrderManager._position_primary_calc
        # (not the _resolver_ab fake), so a resolver-contract drift (return
        # shape / (calc_id, lifecycle_id) order) is caught through the funding
        # path — the loop wires this real method but every other test fakes it
        # (audit Rule-8 gap: TestFundingLoopWiring is only a source-grep smoke).
        await db.upsert_position_calc_link({
            "position_id": "POS-1", "calc_id": "calc-z", "order_id": 1,
            "account_id": ACCOUNT_ID, "contributed_qty": 5.0,
            "first_fill_ts": 1000, "last_fill_ts": 1000,
            "lifecycle_id": "lc-z", "planned_size": 5.0,
            "planned_tp": None, "planned_sl": None,
        })
        res = await handle_funding_incomes(
            account_id=ACCOUNT_ID,
            incomes=[_income("BTCUSDT", -0.05, 1000)],
            positions=[PositionInfo(position_id="POS-1", ticker="BTCUSDT")],
            db=db, primary_calc_resolver=om._position_primary_calc,
        )
        assert res["written"] == 1
        rows = await db.get_position_funding_events("POS-1")
        assert rows[0]["calc_id"] == "calc-z"        # (calc_id, lifecycle_id)
        assert rows[0]["lifecycle_id"] == "lc-z"     # order correct


class TestFundingUiSurfacing:
    def test_in_preserve_fields(self):
        from core.data_cache import _PRESERVE_FIELDS
        assert "individual_funding_fees" in _PRESERVE_FIELDS

    def _env(self):
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(os.path.join(_REPO, "templates")))
        env.globals["fmt"] = lambda v, n=2: f"{float(v):.{n}f}"
        env.globals["hold_time"] = lambda ts: "1h"
        return env

    def test_rows_fragment_renders_funding_and_net(self):
        env = self._env()
        tmpl = env.get_template("fragments/dashboard_positions_rows.html")
        pos = SimpleNamespace(
            ticker="BTCUSDT", direction="LONG", entry_timestamp="x",
            average=50000, fair_price=51000, contract_amount=1.0,
            position_value_usdt=50000, individual_unrealized=100.0,
            individual_fees=1.0, individual_funding_fees=-0.5,
            session_mfe=10, session_mae=-5,
            individual_tp_price=55000, individual_sl_price=48000,
            deviation_badge="green", size_delta_pct=0.0, amendment_count=0)
        out = tmpl.render(open_positions=[pos])
        assert "-0.5000" in out                 # funding cell
        assert "98.50" in out                    # net = 100 - 1.0 + (-0.5)

    def test_other_open_position_templates_compile(self):
        # Compile (parse) the other two open-position templates touched by P5.T7
        # so a Jinja-syntax error in the added Funding column/cell is caught
        # (CLAUDE.md: source-grep is insufficient; compile-render catches it).
        env = self._env()
        env.get_template("fragments/dashboard_body.html")
        env.get_template("fragments/history/open_positions.html")


# ── 7. P6 deferred-funding reconcile (was a filed P5 gap) ─────────────────────
#
# CORRECTED MECHANISM (re-investigation): the filed gap said the late funding
# row is "written but never folded into closed_positions". It is NOT — the live
# attribution map is built from OPEN positions only, so a closed position's
# late funding ORPHANED (never written). The fix is two-part: late attribution
# to the closed lifecycle whose [entry, exit] window contains the settlement ts
# (find_closed_position_for_funding), then recompute funding_fees/net_pnl on
# that row (reconcile_closed_position_funding). Both halves are exercised below.


async def _insert_closed_cp(
    db, tpid, *, symbol="BTCUSDT", entry=1000, exit_=2000,
    realized=100.0, fees=2.0, funding=0.0, calc_id="C-sealed",
    lifecycle="lc-sealed", direction="LONG",
):
    """Seed a closed_positions row directly (for the lookup/reconcile units)."""
    await db.insert_closed_position({
        "account_id": ACCOUNT_ID, "terminal_position_id": tpid, "symbol": symbol,
        "direction": direction, "quantity": 1.0, "entry_price": 50000.0,
        "exit_price": 51000.0, "entry_time_ms": entry, "exit_time_ms": exit_,
        "realized_pnl": realized, "total_fees": fees,
        "net_pnl": realized - fees + funding, "funding_fees": funding,
        "exit_reason": "TP_PLANNED", "calc_id": calc_id, "lifecycle_id": lifecycle,
    })


class TestFindClosedPositionForFunding:
    @pytest.mark.asyncio
    async def test_window_match_returns_sealed_calc_lifecycle(self, db):
        # A settlement ts INSIDE a closed lifecycle's [entry, exit] window
        # attributes to that closed tpid; calc_id/lifecycle come from the sealed
        # row (== junction primary at close, T2.6).
        await _insert_closed_cp(db, "POS-OLD", entry=1000, exit_=2000,
                                calc_id="C-sealed", lifecycle="lc-sealed")
        hit = await db.find_closed_position_for_funding(ACCOUNT_ID, "BTCUSDT", 1500)
        assert hit == {"position_id": "POS-OLD",
                       "calc_id": "C-sealed", "lifecycle_id": "lc-sealed"}

    @pytest.mark.asyncio
    async def test_ts_outside_window_no_match(self, db):
        # A settlement after the close (the position can't have been open at
        # settlement) — and one before the open — must NOT match. This is the
        # self-bounding property: only RECENTLY-closed positions can match.
        await _insert_closed_cp(db, "POS-OLD", entry=1000, exit_=2000)
        assert await db.find_closed_position_for_funding(ACCOUNT_ID, "BTCUSDT", 2500) is None
        assert await db.find_closed_position_for_funding(ACCOUNT_ID, "BTCUSDT", 500) is None

    @pytest.mark.asyncio
    async def test_empty_tpid_excluded(self, db):
        # binance one-way empty-tpid closed rows can't be keyed → excluded so
        # their funding stays an orphan (matches the open-path empty-tpid skip).
        await _insert_closed_cp(db, "", symbol="DOGEUSDT", entry=1000, exit_=2000)
        assert await db.find_closed_position_for_funding(ACCOUNT_ID, "DOGEUSDT", 1500) is None

    @pytest.mark.asyncio
    async def test_multi_partial_picks_final_row(self, db):
        # Multi-TP: per-partial rows share one tpid; MAX(exit_time_ms) resolves
        # to the final/primary-sealed row (whichever calc/lifecycle it sealed).
        await _insert_closed_cp(db, "POS-M", entry=1000, exit_=2000,
                                calc_id="C-partial", lifecycle="lc-partial")
        await _insert_closed_cp(db, "POS-M", entry=1000, exit_=3000,
                                calc_id="C-final", lifecycle="lc-final")
        hit = await db.find_closed_position_for_funding(ACCOUNT_ID, "BTCUSDT", 1500)
        assert hit["position_id"] == "POS-M"
        assert hit["calc_id"] == "C-final"        # the MAX-exit (final) row
        assert hit["lifecycle_id"] == "lc-final"

    @pytest.mark.asyncio
    async def test_account_scoped(self, db):
        # Another account's closed position must not leak into the lookup.
        await db.insert_closed_position({
            "account_id": 999, "terminal_position_id": "POS-OTHER",
            "symbol": "BTCUSDT", "direction": "LONG", "quantity": 1.0,
            "entry_price": 50000.0, "exit_price": 51000.0,
            "entry_time_ms": 1000, "exit_time_ms": 2000, "realized_pnl": 1.0,
            "total_fees": 0.0, "net_pnl": 1.0, "funding_fees": 0.0,
            "exit_reason": "TP_PLANNED", "calc_id": "x", "lifecycle_id": "y",
        })
        assert await db.find_closed_position_for_funding(ACCOUNT_ID, "BTCUSDT", 1500) is None


class TestReconcileClosedPositionFunding:
    @pytest.mark.asyncio
    async def test_recomputes_funding_and_net(self, db):
        await _insert_closed_cp(db, "POS-1", realized=100.0, fees=2.0, funding=0.0)
        await _seed_funding_cp(db, "POS-1", -0.05, 1200, "fe-1")
        await _seed_funding_cp(db, "POS-1", -0.04, 1400, "fe-2")
        assert await db.reconcile_closed_position_funding(ACCOUNT_ID, "POS-1") is True
        row = await _closed_row_cp(db, "POS-1", 2000)
        assert row["funding_fees"] == pytest.approx(-0.09)
        # net = realized(100) - fees(2) + funding(-0.09) — the close-builder
        # convention recomputed from the row's stored realized/fees.
        assert row["net_pnl"] == pytest.approx(97.91)

    @pytest.mark.asyncio
    async def test_idempotent_noop_when_unchanged(self, db):
        await _insert_closed_cp(db, "POS-1", realized=100.0, fees=2.0)
        await _seed_funding_cp(db, "POS-1", -0.05, 1200, "fe-1")
        # First reconcile changes the row (0 → -0.05) → True.
        assert await db.reconcile_closed_position_funding(ACCOUNT_ID, "POS-1") is True
        # Re-run with no new funding → already correct → NO-OP, returns False
        # (the self-heal retries / per-close backstop calls must not churn).
        assert await db.reconcile_closed_position_funding(ACCOUNT_ID, "POS-1") is False
        row = await _closed_row_cp(db, "POS-1", 2000)
        assert row["funding_fees"] == pytest.approx(-0.05)
        assert row["net_pnl"] == pytest.approx(97.95)   # 100 - 2 - 0.05

    @pytest.mark.asyncio
    async def test_picks_up_new_funding_after_first_reconcile(self, db):
        # A SECOND late settlement arriving after the first reconcile must be
        # folded in (returns True; not skipped as "unchanged").
        await _insert_closed_cp(db, "POS-1", realized=100.0, fees=2.0)
        await _seed_funding_cp(db, "POS-1", -0.05, 1200, "fe-1")
        assert await db.reconcile_closed_position_funding(ACCOUNT_ID, "POS-1") is True
        await _seed_funding_cp(db, "POS-1", -0.03, 1400, "fe-2")
        assert await db.reconcile_closed_position_funding(ACCOUNT_ID, "POS-1") is True
        row = await _closed_row_cp(db, "POS-1", 2000)
        assert row["funding_fees"] == pytest.approx(-0.08)
        assert row["net_pnl"] == pytest.approx(97.92)   # 100 - 2 - 0.08

    @pytest.mark.asyncio
    async def test_no_row_returns_false(self, db):
        assert await db.reconcile_closed_position_funding(ACCOUNT_ID, "NOPE") is False

    @pytest.mark.asyncio
    async def test_empty_tpid_returns_false(self, db):
        # Empty position_id (binance one-way) can't key a SUM → no-op False even
        # if empty-tpid funding_events somehow existed.
        assert await db.reconcile_closed_position_funding(ACCOUNT_ID, "") is False

    @pytest.mark.asyncio
    async def test_targets_final_row_only(self, db):
        # Multi-TP: reconcile must touch ONLY the final (MAX exit_time) row so
        # the across-rows funding sum still counts funding exactly once (the
        # per-partial row stays 0, as the is_final stamp left it).
        await _insert_closed_cp(db, "POS-T", exit_=2000, realized=40.0, fees=0.3, funding=0.0)
        await _insert_closed_cp(db, "POS-T", exit_=3000, realized=50.0, fees=1.0, funding=0.0)
        await _seed_funding_cp(db, "POS-T", -0.06, 1500, "fe-1")
        assert await db.reconcile_closed_position_funding(ACCOUNT_ID, "POS-T") is True
        partial = await _closed_row_cp(db, "POS-T", 2000)
        final = await _closed_row_cp(db, "POS-T", 3000)
        assert partial["funding_fees"] == pytest.approx(0.0)      # untouched
        assert final["funding_fees"] == pytest.approx(-0.06)      # full SUM
        assert final["net_pnl"] == pytest.approx(50.0 - 1.0 - 0.06)
        # Summed across rows, funding counted exactly once.
        assert (partial["funding_fees"] + final["funding_fees"]) == pytest.approx(-0.06)


class TestDeferredFundingLateAttribution:
    @pytest.mark.asyncio
    async def test_late_funding_attributes_and_reconciles(self, db):
        # The headline fix: funding for a CLOSED position (no open position in
        # the cache) is attributed to the closed lifecycle by window and the
        # closed row's funding rollup is reconciled — NOT orphaned.
        await _insert_closed_cp(db, "POS-C", entry=1000, exit_=2000,
                                realized=100.0, fees=2.0, funding=0.0,
                                calc_id="C-sealed", lifecycle="lc-sealed")
        res = await handle_funding_incomes(
            account_id=ACCOUNT_ID, incomes=[_income("BTCUSDT", -0.05, 1500)],
            positions=[], db=db, primary_calc_resolver=_resolver_ab,
        )
        assert res == {"written": 1, "deduped": 0, "orphan": 0, "reconciled": 1}
        # funding_events row keyed to the closed tpid, sealed calc/lifecycle.
        rows = await db.get_position_funding_events("POS-C")
        assert len(rows) == 1
        assert rows[0]["calc_id"] == "C-sealed"
        assert rows[0]["lifecycle_id"] == "lc-sealed"
        # closed row reconciled.
        row = await _closed_row_cp(db, "POS-C", 2000)
        assert row["funding_fees"] == pytest.approx(-0.05)
        assert row["net_pnl"] == pytest.approx(97.95)   # 100 - 2 - 0.05

    @pytest.mark.asyncio
    async def test_no_open_no_closed_still_orphans(self, db):
        # A symbol with neither an open position nor a containing closed window
        # is a TRUE orphan (e.g. funding for a never-traded symbol).
        await _insert_closed_cp(db, "POS-C", symbol="BTCUSDT", entry=1000, exit_=2000)
        res = await handle_funding_incomes(
            account_id=ACCOUNT_ID, incomes=[_income("XRPUSDT", -0.01, 1500)],
            positions=[], db=db, primary_calc_resolver=_resolver_ab,
        )
        assert res == {"written": 0, "deduped": 0, "orphan": 1, "reconciled": 0}

    @pytest.mark.asyncio
    async def test_empty_tpid_closed_orphans(self, db):
        # A closed row with empty tpid can't be keyed → the late funding stays
        # an orphan (not attributed to the empty key).
        await _insert_closed_cp(db, "", symbol="DOGEUSDT", entry=1000, exit_=2000)
        res = await handle_funding_incomes(
            account_id=ACCOUNT_ID, incomes=[_income("DOGEUSDT", -0.02, 1500)],
            positions=[], db=db, primary_calc_resolver=_resolver_ab,
        )
        assert res["orphan"] == 1 and res["written"] == 0 and res["reconciled"] == 0
        async with db._conn.execute("SELECT COUNT(*) FROM funding_events") as cur:
            assert (await cur.fetchone())[0] == 0

    @pytest.mark.asyncio
    async def test_late_funding_repoll_is_idempotent(self, db):
        # Re-polling the same window after a late attribution dedups (synthetic
        # venue_event_id) and does NOT re-reconcile — the closed row is stable.
        await _insert_closed_cp(db, "POS-C", realized=100.0, fees=2.0)
        first = await handle_funding_incomes(
            account_id=ACCOUNT_ID, incomes=[_income("BTCUSDT", -0.05, 1500)],
            positions=[], db=db, primary_calc_resolver=_resolver_ab,
        )
        assert first == {"written": 1, "deduped": 0, "orphan": 0, "reconciled": 1}
        second = await handle_funding_incomes(
            account_id=ACCOUNT_ID, incomes=[_income("BTCUSDT", -0.05, 1500)],
            positions=[], db=db, primary_calc_resolver=_resolver_ab,
        )
        assert second == {"written": 0, "deduped": 1, "orphan": 0, "reconciled": 0}
        row = await _closed_row_cp(db, "POS-C", 2000)
        assert row["funding_fees"] == pytest.approx(-0.05)   # unchanged

    @pytest.mark.asyncio
    async def test_mixed_open_and_closed_late_in_one_batch(self, db):
        # One income for an OPEN position + one for a CLOSED position in the same
        # poll: both attributed (open via resolver, closed via window+reconcile).
        await _insert_closed_cp(db, "POS-C", symbol="BTCUSDT", realized=100.0, fees=2.0)
        res = await handle_funding_incomes(
            account_id=ACCOUNT_ID,
            incomes=[_income("ETHUSDT", -0.03, 1500),     # open
                     _income("BTCUSDT", -0.05, 1500)],    # closed-late
            positions=[PositionInfo(position_id="POS-OPEN", ticker="ETHUSDT")],
            db=db, primary_calc_resolver=_resolver_ab,
        )
        assert res == {"written": 2, "deduped": 0, "orphan": 0, "reconciled": 1}
        assert await db.sum_position_funding("POS-OPEN") == pytest.approx(-0.03)
        assert await db.sum_position_funding("POS-C") == pytest.approx(-0.05)
        assert (await _closed_row_cp(db, "POS-C", 2000))["funding_fees"] == pytest.approx(-0.05)

    @pytest.mark.asyncio
    async def test_swallowed_reconcile_fault_self_heals_next_poll(self, db, monkeypatch):
        # Rule-8 (audit MED): the funding row is committed independently of the
        # reconcile. If the reconcile RAISES (e.g. transient SQLite lock — the
        # aiosqlite conn has no busy_timeout), poll 1 swallows it and the closed
        # row stays stale. Poll 2 must SELF-HEAL: the income dedups but the
        # closed tpid is still collected for reconcile (the add() is NOT gated on
        # `inserted`), so the rollup folds in. A regression that re-gates on
        # `inserted` would leave the row permanently stale and FAIL this test.
        await _insert_closed_cp(db, "POS-C", realized=100.0, fees=2.0, funding=0.0)
        real = db.reconcile_closed_position_funding
        calls = {"n": 0}

        async def _flaky(account_id, position_id):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient lock on first reconcile")
            return await real(account_id, position_id)

        monkeypatch.setattr(db, "reconcile_closed_position_funding", _flaky)

        # Poll 1: row written, reconcile faults (swallowed) → reconciled 0, stale.
        res1 = await handle_funding_incomes(
            account_id=ACCOUNT_ID, incomes=[_income("BTCUSDT", -0.05, 1500)],
            positions=[], db=db, primary_calc_resolver=_resolver_ab,
        )
        assert res1 == {"written": 1, "deduped": 0, "orphan": 0, "reconciled": 0}
        assert (await _closed_row_cp(db, "POS-C", 2000))["funding_fees"] == pytest.approx(0.0)

        # Poll 2: same income dedups, but the closed tpid is STILL reconciled →
        # the rollup self-heals from the persisted funding_events SUM.
        res2 = await handle_funding_incomes(
            account_id=ACCOUNT_ID, incomes=[_income("BTCUSDT", -0.05, 1500)],
            positions=[], db=db, primary_calc_resolver=_resolver_ab,
        )
        assert res2 == {"written": 0, "deduped": 1, "orphan": 0, "reconciled": 1}
        row = await _closed_row_cp(db, "POS-C", 2000)
        assert row["funding_fees"] == pytest.approx(-0.05)
        assert row["net_pnl"] == pytest.approx(97.95)   # 100 - 2 - 0.05


class TestDeferredFundingBackstop:
    @pytest.mark.asyncio
    async def test_backstop_reconciles_ws_gap_row(self, db, om, monkeypatch):
        # WS-gap shape: opens sum to 2.0 but only 1.0 of closing fills is
        # recorded → is_final never fires → the built close row stamps funding 0
        # despite funding_events existing. The disappearance backstop
        # (build_final_close_row) must reconcile that final row from the SUM.
        from core.state import app_state
        # active_account_id is a read-through property → patch it on the class
        # so the backstop (which reads app_state.active_account_id) resolves to
        # this test's account regardless of registry/test order.
        monkeypatch.setattr(
            type(app_state), "active_account_id",
            property(lambda self: ACCOUNT_ID),
        )
        await _seed_junction_cp(db, "POS-1", "C1", qty=2.0)
        await _seed_order_cp(db, "EO", "limit", "BUY")
        await _seed_fill_cp(db, "FO", "EO", "POS-1", 2.0, False, 1000, fee=0.4)
        await _seed_funding_cp(db, "POS-1", -0.06, 1500, "fe-1")
        await _seed_order_cp(db, "XO", "take_profit", "SELL")
        await _seed_fill_cp(db, "FX", "XO", "POS-1", 1.0, True, 2000,
                            fee=0.3, realized_pnl=40.0, price=52000.0)
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill_cp("XO", "POS-1", 2000))

        pre = await _closed_row_cp(db, "POS-1", 2000)
        assert pre is not None
        assert pre["funding_fees"] == pytest.approx(0.0)   # not final → 0

        prev = PositionInfo(position_id="POS-1", ticker="BTCUSDT", direction="LONG")
        await om.build_final_close_row(prev)

        post = await _closed_row_cp(db, "POS-1", 2000)
        assert post["funding_fees"] == pytest.approx(-0.06)
        # net recomputed from the row's stored realized/fees + funding.
        assert post["net_pnl"] == pytest.approx(
            post["realized_pnl"] - post["total_fees"] - 0.06)


# ── 8. P6.T2: position:closed FULL §9 payload on the event_bus ────────────────


class TestPositionClosedEvent:
    @pytest.mark.asyncio
    async def test_final_close_emits_full_payload_and_keeps_flat(self, db, om):
        # P6.T2: the close path emits the FULL spec §9 position:closed payload on
        # the per-account topic, AND keeps the flat risk:position_closed (compat
        # shim for the reconciler subscriber). Both must appear on a final close.
        from core.event_bus import event_bus
        await _seed_junction_cp(db, "POS-1", "C1", qty=2.0)
        await _seed_order_cp(db, "EO", "limit", "BUY")
        await _seed_fill_cp(db, "FO", "EO", "POS-1", 2.0, False, 1000, fee=0.5)
        await _seed_order_cp(db, "XO", "market", "SELL")
        await _seed_fill_cp(db, "FX", "XO", "POS-1", 2.0, True, 2000,
                            fee=1.5, realized_pnl=100.0, price=51000.0)
        while not event_bus._queue.empty():
            event_bus._queue.get_nowait()

        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill_cp("XO", "POS-1", 2000))

        events = []
        while not event_bus._queue.empty():
            events.append(event_bus._queue.get_nowait())
        # compat shim: the flat event is still emitted for the reconciler.
        assert any(c == "risk:position_closed" for c, _ in events)
        closed = [(c, p) for c, p in events if c == "engine:account:1:position:closed"]
        assert len(closed) == 1, f"expected 1 position:closed, got {[c for c, _ in events]!r}"
        _, p = closed[0]
        assert p["position_id"] == "POS-1"
        assert p["primary_calc_id"] == "C1"
        assert p["contributing_calc_ids"] == ["C1"]
        assert p["realized_pnl"] == pytest.approx(100.0)
        # net_pnl self-consistent with the payload's own fee/funding fields.
        assert p["net_pnl"] == pytest.approx(
            p["realized_pnl"] - p["total_fees"] + p["funding_fees"])
        # §9 deltas sub-object: ONLY the 7 spec delta keys — hold_time_actual_ms
        # is a TOP-LEVEL §9 field (must not leak into the nested block from the
        # close-ROW delta dict). issubset tolerates a conditionally-absent delta
        # but FAILS on any extra key (e.g. a hold_time_actual_ms leak).
        assert isinstance(p["deltas"], dict)
        assert set(p["deltas"]).issubset({
            "entry_px_delta_pct", "size_delta_pct", "tp_drift_pct", "sl_drift_pct",
            "exit_vs_target_pct", "realized_r", "planned_r",
        }), p["deltas"].keys()
        assert "hold_time_actual_ms" not in p["deltas"]   # nested: excluded
        assert "hold_time_actual_ms" in p                 # top-level: present
        assert p["exit_reason"]                       # non-empty §3.4 enum
        assert p["mfe"] is None and p["mae"] is None  # reconciler-computed post-close

    @pytest.mark.asyncio
    async def test_partial_close_does_not_emit_position_closed(self, db, om):
        # FINAL-only: a non-final (multi-TP partial) close emits NO
        # position:closed (it would falsely signal the position is flat). The
        # flat risk:position_closed still fires (per-row, for the reconciler).
        from core.event_bus import event_bus
        await _seed_junction_cp(db, "POS-1", "C1", qty=2.0)
        await _seed_order_cp(db, "EO", "limit", "BUY")
        await _seed_fill_cp(db, "FO", "EO", "POS-1", 2.0, False, 1000, fee=0.4)
        await _seed_order_cp(db, "XO1", "take_profit", "SELL")
        await _seed_fill_cp(db, "FX1", "XO1", "POS-1", 1.0, True, 2000,
                            fee=0.3, realized_pnl=40.0, price=52000.0)
        while not event_bus._queue.empty():
            event_bus._queue.get_nowait()

        # Σclose(1) < Σopen(2) → NOT final.
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill_cp("XO1", "POS-1", 2000))

        events = []
        while not event_bus._queue.empty():
            events.append(event_bus._queue.get_nowait())
        assert not any(c.endswith(":position:closed") for c, _ in events)


# ── 9. P6.T7: position:liquidated (forced-liq detection + dedicated event) ────


class TestPositionLiquidatedEvent:
    @pytest.mark.asyncio
    async def test_determine_exit_reason_liquidation(self, db, om):
        # Per-order: a "liquidation" order_type (Binance forced-liq fallback) →
        # exit_reason LIQUIDATION (highest priority).
        await _seed_order_cp(db, "LQ", "liquidation", "SELL")
        assert await om._determine_exit_reason(ACCOUNT_ID, "LQ") == "LIQUIDATION"

    @pytest.mark.asyncio
    async def test_liquidation_close_detects_emits_persists(self, db, om):
        from core.event_bus import event_bus
        await _seed_junction_cp(db, "POS-1", "C1", qty=2.0)
        await _seed_order_cp(db, "EO", "limit", "BUY")
        await _seed_fill_cp(db, "FO", "EO", "POS-1", 2.0, False, 1000, fee=0.5)
        await _seed_order_cp(db, "LQ", "liquidation", "SELL")
        await _seed_fill_cp(db, "FX", "LQ", "POS-1", 2.0, True, 2000,
                            fee=1.0, realized_pnl=-500.0, price=49000.0)
        while not event_bus._queue.empty():
            event_bus._queue.get_nowait()
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill_cp("LQ", "POS-1", 2000))

        # exit_reason classified LIQUIDATION; liquidation_px persisted (=exit px).
        row = await _closed_row_cp(db, "POS-1", 2000)
        assert row["exit_reason"] == "LIQUIDATION"
        assert row["liquidation_px"] == pytest.approx(49000.0)

        events = []
        while not event_bus._queue.empty():
            events.append(event_bus._queue.get_nowait())
        liq = [(c, p) for c, p in events if c == "engine:account:1:position:liquidated"]
        assert len(liq) == 1, f"expected 1 position:liquidated, got {[c for c, _ in events]!r}"
        _, p = liq[0]
        assert p["position_id"] == "POS-1"
        assert p["liquidation_px"] == pytest.approx(49000.0)
        assert p["bankruptcy_px"] is None         # no venue-event source
        assert p["insurance_fund_fee"] is None
        assert p["adl_indicator"] is None
        # position:closed ALSO fires on a liquidation close (both events).
        assert any(c == "engine:account:1:position:closed" for c, _ in events)

    @pytest.mark.asyncio
    async def test_non_liquidation_close_no_event_null_px(self, db, om):
        from core.event_bus import event_bus
        await _seed_junction_cp(db, "POS-2", "C1", qty=1.0)
        await _seed_order_cp(db, "EO", "limit", "BUY")
        await _seed_fill_cp(db, "FO", "EO", "POS-2", 1.0, False, 1000, fee=0.5)
        await _seed_order_cp(db, "XO", "market", "SELL")
        await _seed_fill_cp(db, "FX", "XO", "POS-2", 1.0, True, 2000,
                            fee=0.5, realized_pnl=10.0)
        while not event_bus._queue.empty():
            event_bus._queue.get_nowait()
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill_cp("XO", "POS-2", 2000))
        row = await _closed_row_cp(db, "POS-2", 2000)
        assert row["exit_reason"] != "LIQUIDATION"
        assert row["liquidation_px"] is None
        events = []
        while not event_bus._queue.empty():
            events.append(event_bus._queue.get_nowait())
        assert not any(c.endswith(":position:liquidated") for c, _ in events)

    @pytest.mark.asyncio
    async def test_liquidation_dominates_ladder(self, db, om):
        # A TP rung then a forced liquidation on the rest: the FINAL close reads
        # LIQUIDATION (it dominates the TP+liq mix — not MIXED).
        from core.event_bus import event_bus
        await _seed_junction_cp(db, "POS-3", "C1", qty=2.0)
        await _seed_order_cp(db, "EO", "limit", "BUY")
        await _seed_fill_cp(db, "FO", "EO", "POS-3", 2.0, False, 1000, fee=0.4)
        await _seed_order_cp(db, "TP", "take_profit", "SELL")
        await _seed_fill_cp(db, "FT", "TP", "POS-3", 1.0, True, 2000,
                            fee=0.3, realized_pnl=40.0, price=52000.0)
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill_cp("TP", "POS-3", 2000))
        await _seed_order_cp(db, "LQ", "liquidation", "SELL")
        await _seed_fill_cp(db, "FL", "LQ", "POS-3", 1.0, True, 3000,
                            fee=0.5, realized_pnl=-300.0, price=48000.0)
        while not event_bus._queue.empty():
            event_bus._queue.get_nowait()
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill_cp("LQ", "POS-3", 3000))

        # The partial TP row keeps its per-order reason; the FINAL row = LIQUIDATION.
        partial = await _closed_row_cp(db, "POS-3", 2000)
        final = await _closed_row_cp(db, "POS-3", 3000)
        assert partial["exit_reason"] == "TP_PLANNED"
        assert final["exit_reason"] == "LIQUIDATION"
        assert any(c == "engine:account:1:position:liquidated"
                   for c, _ in (event_bus._queue.get_nowait()
                                for _ in range(event_bus._queue.qsize())))

    @pytest.mark.asyncio
    async def test_partial_liquidation_emits_no_event(self, db, om):
        # Audit F2 (Rule-8 gate): Binance does PARTIAL liquidations. A partial
        # forced-liq close is exit_reason=LIQUIDATION but is_final=False → the
        # is_final conjunct must SUPPRESS position:liquidated (it fires only on
        # the final close). Dropping the is_final gate would fail this test.
        from core.event_bus import event_bus
        await _seed_junction_cp(db, "POS-4", "C1", qty=2.0)
        await _seed_order_cp(db, "EO", "limit", "BUY")
        await _seed_fill_cp(db, "FO", "EO", "POS-4", 2.0, False, 1000, fee=0.4)
        await _seed_order_cp(db, "LQ", "liquidation", "SELL")
        # partial liq: closes 1 of 2 → is_final False
        await _seed_fill_cp(db, "FL", "LQ", "POS-4", 1.0, True, 2000,
                            fee=0.5, realized_pnl=-200.0, price=49000.0)
        while not event_bus._queue.empty():
            event_bus._queue.get_nowait()
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill_cp("LQ", "POS-4", 2000))
        row = await _closed_row_cp(db, "POS-4", 2000)
        assert row["exit_reason"] == "LIQUIDATION"   # per-order classified
        events = []
        while not event_bus._queue.empty():
            events.append(event_bus._queue.get_nowait())
        assert not any(c.endswith(":position:liquidated") for c, _ in events)

    @pytest.mark.asyncio
    async def test_liquidation_px_is_liq_fill_not_final_order(self, db, om):
        # Audit F1: liquidation_px must be the LIQUIDATION fill's price even when
        # a NON-liquidation order completes the close AFTER a partial liquidation
        # (margin recovered). Source = the liq fill VWAP (49000), NOT the final
        # non-liq order's price (53000). Old code (=exit_price) would record 53000.
        from core.event_bus import event_bus
        await _seed_junction_cp(db, "POS-5", "C1", qty=2.0)
        await _seed_order_cp(db, "EO", "limit", "BUY")
        await _seed_fill_cp(db, "FO", "EO", "POS-5", 2.0, False, 1000, fee=0.4)
        # partial liquidation FIRST (1 of 2) at 49000
        await _seed_order_cp(db, "LQ", "liquidation", "SELL")
        await _seed_fill_cp(db, "FL", "LQ", "POS-5", 1.0, True, 2000,
                            fee=0.5, realized_pnl=-200.0, price=49000.0)
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill_cp("LQ", "POS-5", 2000))
        # non-liq close LAST (remaining 1) at 53000
        await _seed_order_cp(db, "MX", "market", "SELL")
        await _seed_fill_cp(db, "FM", "MX", "POS-5", 1.0, True, 3000,
                            fee=0.5, realized_pnl=20.0, price=53000.0)
        while not event_bus._queue.empty():
            event_bus._queue.get_nowait()
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill_cp("MX", "POS-5", 3000))
        final = await _closed_row_cp(db, "POS-5", 3000)
        assert final["exit_reason"] == "LIQUIDATION"          # liq dominates
        assert final["liquidation_px"] == pytest.approx(49000.0)  # liq fill, not 53000
        liq = [(c, p) for c, p in (event_bus._queue.get_nowait()
                                   for _ in range(event_bus._queue.qsize()))
               if c == "engine:account:1:position:liquidated"]
        assert len(liq) == 1
        assert liq[0][1]["liquidation_px"] == pytest.approx(49000.0)
