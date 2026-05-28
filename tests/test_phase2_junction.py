"""
Phase 2 Task 1 (P2.T1) tests — position↔calc junction + lifecycle_id.

Verifies the forward path
``OrderManager._link_position_calc_on_open`` (wired into
``_process_single_fill`` on every opening fill):

  1. First opening fill of a position writes a ``positions_calcs`` row
     keyed by ``terminal_position_id`` (TEXT) and mints a UUID v4
     ``lifecycle_id``, back-filled onto the contributing
     ``pre_trade_log`` + ``orders`` rows (spec §3.5).
  2. ``position_id`` is the ``terminal_position_id`` STRING, not an
     integer surrogate (spec §3.1, P2.T1 schema decision).
  3. Multiple fills of the same order accumulate ``contributed_qty``
     and reuse the position's lifecycle_id.
  4. Scale-in (second calc/order on the same position) appends a junction
     row sharing the SAME lifecycle_id.
  5. Skips (no attribution) for closing fills, empty
     terminal_position_id, missing calc_id, and unknown orders.

Two layers of coverage:
  - Unit (``Test*`` classes below): drive ``_link_position_calc_on_open``
    directly for fine-grained contract cases (skip conditions, scale-in,
    idempotency). Self-contained on ``self._db._conn``.
  - Integration (``TestRealFillPathWiring``): drive the REAL
    ``_process_single_fill`` entry point with ``config.DB_PATH`` patched
    to the tmpfile DB (the test_phase1_lifecycle_e2e pattern). This is the
    Rule-8 intent test — it would FAIL if the ``await
    _link_position_calc_on_open`` call were dropped from
    ``_process_single_fill`` or mis-ordered before enrichment sets
    ``orders.calc_id``.

Run: pytest tests/test_phase2_junction.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

ACCOUNT_ID = 1


@pytest_asyncio.fixture
async def db():
    """Tempfile DB initialized with the full schema."""
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


@pytest_asyncio.fixture
async def om(db):
    from core.order_manager import OrderManager
    return OrderManager(db)


# ── seed helpers ───────────────────────────────────────────────────────


async def _seed_order(db, eoid, calc_id=None, lifecycle_id=None,
                      symbol="BTCUSDT", side="BUY") -> int:
    cur = await db._conn.execute(
        "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
        " calc_id, lifecycle_id) VALUES (?, ?, ?, ?, ?, ?)",
        (ACCOUNT_ID, eoid, symbol, side, calc_id, lifecycle_id),
    )
    await db._conn.commit()
    return cur.lastrowid


async def _seed_calc(db, calc_id, lifecycle_id=None,
                     ticker="BTCUSDT") -> None:
    await db._conn.execute(
        "INSERT INTO pre_trade_log (timestamp, ticker, calc_id, lifecycle_id) "
        "VALUES (?, ?, ?, ?)",
        ("2026-05-29T00:00:00Z", ticker, calc_id, lifecycle_id),
    )
    await db._conn.commit()


def _fill(eoid, tpid, qty, ts=1000, is_close=0, symbol="BTCUSDT", fid="F-1"):
    return {
        "account_id": ACCOUNT_ID,
        "exchange_fill_id": fid,
        "exchange_order_id": eoid,
        "terminal_position_id": tpid,
        "symbol": symbol,
        "quantity": qty,
        "timestamp_ms": ts,
        "is_close": is_close,
    }


async def _junction(db, position_id=None):
    sql = "SELECT * FROM positions_calcs"
    params = ()
    if position_id is not None:
        sql += " WHERE position_id = ?"
        params = (position_id,)
    sql += " ORDER BY id ASC"
    async with db._conn.execute(sql, params) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def _calc_lifecycle(db, calc_id):
    async with db._conn.execute(
        "SELECT lifecycle_id FROM pre_trade_log WHERE calc_id = ?", (calc_id,),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


async def _order_lifecycle(db, order_id):
    async with db._conn.execute(
        "SELECT lifecycle_id FROM orders WHERE id = ?", (order_id,),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


# ── 1. first opening fill: junction + lifecycle ────────────────────────


class TestFirstOpeningFill:
    @pytest.mark.asyncio
    async def test_junction_row_written(self, db, om):
        oid = await _seed_order(db, "O-1", calc_id="calc-a")
        await _seed_calc(db, "calc-a")

        await om._link_position_calc_on_open(ACCOUNT_ID, _fill("O-1", "POS-1", 5.0))

        rows = await _junction(db)
        assert len(rows) == 1
        r = rows[0]
        assert r["position_id"] == "POS-1"
        assert r["calc_id"] == "calc-a"
        assert r["order_id"] == oid
        assert r["account_id"] == ACCOUNT_ID
        assert r["contributed_qty"] == pytest.approx(5.0)
        assert r["first_fill_ts"] == 1000
        assert r["last_fill_ts"] == 1000

    @pytest.mark.asyncio
    async def test_position_id_is_text_terminal_position_id(self, db, om):
        # The junction key is the terminal_position_id STRING, not an
        # integer surrogate (spec §3.1 / P2.T1).
        await _seed_order(db, "O-1", calc_id="calc-a")
        await _seed_calc(db, "calc-a")
        await om._link_position_calc_on_open(
            ACCOUNT_ID, _fill("O-1", "binance:BTCUSDT:LONG", 2.0),
        )
        rows = await _junction(db)
        assert rows[0]["position_id"] == "binance:BTCUSDT:LONG"
        assert isinstance(rows[0]["position_id"], str)

    @pytest.mark.asyncio
    async def test_lifecycle_is_uuid_v4_and_backfilled(self, db, om):
        oid = await _seed_order(db, "O-1", calc_id="calc-a")
        await _seed_calc(db, "calc-a")

        await om._link_position_calc_on_open(ACCOUNT_ID, _fill("O-1", "POS-1", 5.0))

        rows = await _junction(db)
        lc = rows[0]["lifecycle_id"]
        # UUID v4 shape: 8-4-4-4-12 hex.
        assert lc is not None
        assert len(lc) == 36
        assert lc.count("-") == 4
        # Back-filled onto contributing calc + order with the SAME value.
        assert await _calc_lifecycle(db, "calc-a") == lc
        assert await _order_lifecycle(db, oid) == lc


# ── 2. multi-fill same order: accumulate + stable lifecycle ─────────────


class TestMultiFillSameOrder:
    @pytest.mark.asyncio
    async def test_qty_accumulates_lifecycle_stable(self, db, om):
        await _seed_order(db, "O-1", calc_id="calc-a")
        await _seed_calc(db, "calc-a")

        await om._link_position_calc_on_open(
            ACCOUNT_ID, _fill("O-1", "POS-1", 3.0, ts=1000),
        )
        await om._link_position_calc_on_open(
            ACCOUNT_ID, _fill("O-1", "POS-1", 4.0, ts=2000),
        )

        rows = await _junction(db)
        assert len(rows) == 1
        assert rows[0]["contributed_qty"] == pytest.approx(7.0)
        assert rows[0]["first_fill_ts"] == 1000   # preserved
        assert rows[0]["last_fill_ts"] == 2000    # advanced
        # lifecycle minted once, reused (not regenerated on the 2nd fill).
        lc = rows[0]["lifecycle_id"]
        assert lc is not None
        assert await _calc_lifecycle(db, "calc-a") == lc


# ── 3. scale-in: second calc/order on same position ─────────────────────


class TestScaleIn:
    @pytest.mark.asyncio
    async def test_second_order_appends_row_sharing_lifecycle(self, db, om):
        oid1 = await _seed_order(db, "O-1", calc_id="calc-a")
        oid2 = await _seed_order(db, "O-2", calc_id="calc-b")
        await _seed_calc(db, "calc-a")
        await _seed_calc(db, "calc-b")

        await om._link_position_calc_on_open(
            ACCOUNT_ID, _fill("O-1", "POS-1", 5.0, ts=1000),
        )
        await om._link_position_calc_on_open(
            ACCOUNT_ID, _fill("O-2", "POS-1", 3.0, ts=2000),
        )

        rows = await _junction(db, "POS-1")
        assert len(rows) == 2
        assert {r["calc_id"] for r in rows} == {"calc-a", "calc-b"}
        # One shared lifecycle_id across both junction rows...
        lcs = {r["lifecycle_id"] for r in rows}
        assert len(lcs) == 1
        lc = lcs.pop()
        # ...and back-filled onto BOTH contributing calcs (spec §3.5).
        assert await _calc_lifecycle(db, "calc-a") == lc
        assert await _calc_lifecycle(db, "calc-b") == lc
        assert await _order_lifecycle(db, oid1) == lc
        assert await _order_lifecycle(db, oid2) == lc

    @pytest.mark.asyncio
    async def test_distinct_positions_get_distinct_lifecycles(self, db, om):
        # Two DIFFERENT positions must NOT share a lifecycle_id (the reuse
        # lookup is scoped WHERE position_id=?; dropping that scope would
        # collapse all positions onto one lifecycle).
        await _seed_order(db, "O-1", calc_id="calc-a")
        await _seed_order(db, "O-2", calc_id="calc-b")
        await _seed_calc(db, "calc-a")
        await _seed_calc(db, "calc-b")
        await om._link_position_calc_on_open(
            ACCOUNT_ID, _fill("O-1", "POS-1", 5.0, fid="F1"),
        )
        await om._link_position_calc_on_open(
            ACCOUNT_ID, _fill("O-2", "POS-2", 5.0, fid="F2"),
        )
        rows = await _junction(db)
        assert {r["position_id"] for r in rows} == {"POS-1", "POS-2"}
        assert len({r["lifecycle_id"] for r in rows}) == 2


# ── 4. skip conditions (no attribution possible) ───────────────────────


class TestSkips:
    @pytest.mark.asyncio
    async def test_closing_fill_skips(self, db, om):
        await _seed_order(db, "O-1", calc_id="calc-a")
        await _seed_calc(db, "calc-a")
        await om._link_position_calc_on_open(
            ACCOUNT_ID, _fill("O-1", "POS-1", 5.0, is_close=1),
        )
        assert await _junction(db) == []

    @pytest.mark.asyncio
    async def test_empty_terminal_position_id_skips(self, db, om):
        await _seed_order(db, "O-1", calc_id="calc-a")
        await _seed_calc(db, "calc-a")
        await om._link_position_calc_on_open(ACCOUNT_ID, _fill("O-1", "", 5.0))
        assert await _junction(db) == []

    @pytest.mark.asyncio
    async def test_order_without_calc_id_skips(self, db, om):
        # UNPLANNED / unlinked entry — nothing to attribute.
        oid = await _seed_order(db, "O-1", calc_id=None)
        await om._link_position_calc_on_open(ACCOUNT_ID, _fill("O-1", "POS-1", 5.0))
        assert await _junction(db) == []
        assert await _order_lifecycle(db, oid) is None

    @pytest.mark.asyncio
    async def test_unknown_order_skips(self, db, om):
        # Fill references an order not present in the DB.
        await om._link_position_calc_on_open(ACCOUNT_ID, _fill("O-NOPE", "POS-1", 5.0))
        assert await _junction(db) == []

    @pytest.mark.asyncio
    async def test_missing_exchange_order_id_skips(self, db, om):
        await om._link_position_calc_on_open(ACCOUNT_ID, _fill("", "POS-1", 5.0))
        assert await _junction(db) == []


# ── 5. idempotent back-fill (pre-stamped rows preserved) ───────────────


class TestLifecycleBackfillIdempotency:
    @pytest.mark.asyncio
    async def test_existing_calc_lifecycle_not_overwritten(self, db, om):
        # If a contributing calc already carries a lifecycle_id, the
        # back-fill's WHERE lifecycle_id IS NULL guard leaves it intact.
        await _seed_order(db, "O-1", calc_id="calc-a")
        await _seed_calc(db, "calc-a", lifecycle_id="preset-uuid")
        await om._link_position_calc_on_open(ACCOUNT_ID, _fill("O-1", "POS-1", 5.0))
        # pre_trade_log keeps its preset value (not clobbered).
        assert await _calc_lifecycle(db, "calc-a") == "preset-uuid"


# ── 6. integration: REAL _process_single_fill path (Rule-8 wiring test) ─


@pytest_asyncio.fixture
async def real(monkeypatch):
    """OrderManager driven through the real `_process_single_fill` path.

    Enrichment helpers use `config.DB_PATH` (raw sqlite3) while the
    junction uses `self._db._conn`; both are pointed at ONE tmpfile DB
    (the test_phase1_lifecycle_e2e pattern), so a fill exercises the
    whole opening-fill chain end-to-end.
    """
    import config
    from core.database import DatabaseManager
    from core.order_manager import OrderManager

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database = DatabaseManager(path=tmp.name)
    await database.initialize()
    await database._conn.execute(
        "INSERT OR IGNORE INTO accounts (id, name, config_json) "
        "VALUES (1, 'Test', ?)",
        ('{"window_seconds": 300}',),
    )
    await database._conn.commit()
    monkeypatch.setattr(config, "DB_PATH", tmp.name)
    yield OrderManager(database), database
    await database.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


async def _seed_linked_order_and_calc(db, eoid="O-1", calc_id="calc-a",
                                      reduce_only=0):
    # Order is already calc-linked (calc_id set) so the post-fill matcher
    # re-fire is an idempotent no-op — isolates the junction wiring.
    await db._conn.execute(
        "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
        " order_type, status, price, calc_id, reduce_only) "
        "VALUES (1, ?, 'BTCUSDT', 'BUY', 'limit', 'new', 50000, ?, ?)",
        (eoid, calc_id, reduce_only),
    )
    await db._conn.execute(
        "INSERT INTO pre_trade_log (timestamp, ticker, calc_id) "
        "VALUES ('2026-05-29T00:00:00Z', 'BTCUSDT', ?)",
        (calc_id,),
    )
    await db._conn.commit()


class TestRealFillPathWiring:
    @pytest.mark.asyncio
    async def test_opening_fill_creates_junction_via_real_path(self, real):
        # Drives the actual _process_single_fill: upsert fill → matcher
        # re-fire → enrich_fill → _link_position_calc_on_open. Proves the
        # call is wired + awaited (would fail if the call were dropped).
        om, db = real
        await _seed_linked_order_and_calc(db)

        await om._process_single_fill(ACCOUNT_ID, _fill("O-1", "POS-1", 0.01))

        async with db._conn.execute("SELECT * FROM positions_calcs") as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        assert len(rows) == 1
        assert rows[0]["position_id"] == "POS-1"
        assert rows[0]["calc_id"] == "calc-a"
        assert rows[0]["contributed_qty"] == pytest.approx(0.01)
        lc = rows[0]["lifecycle_id"]
        assert lc and len(lc) == 36
        # lifecycle_id back-filled onto the calc through the real path.
        async with db._conn.execute(
            "SELECT lifecycle_id FROM pre_trade_log WHERE calc_id = 'calc-a'",
        ) as cur:
            assert (await cur.fetchone())[0] == lc

    @pytest.mark.asyncio
    async def test_closing_fill_no_junction_via_real_path(self, real):
        om, db = real
        await _seed_linked_order_and_calc(db, reduce_only=1)

        await om._process_single_fill(
            ACCOUNT_ID, _fill("O-1", "POS-1", 0.01, is_close=1),
        )

        async with db._conn.execute(
            "SELECT COUNT(*) FROM positions_calcs",
        ) as cur:
            assert (await cur.fetchone())[0] == 0


# ── 7. T2.2 — closing-fill attribution from position primary ───────────


async def _seed_junction(db, position_id, calc_id, order_id, qty, ts,
                         lifecycle_id):
    await db.upsert_position_calc_link({
        "position_id": position_id, "calc_id": calc_id, "order_id": order_id,
        "account_id": ACCOUNT_ID, "contributed_qty": qty,
        "first_fill_ts": ts, "last_fill_ts": ts, "lifecycle_id": lifecycle_id,
    })


async def _seed_fill_row(db, fid, tpid="POS-1", is_close=1,
                         calc_id=None, lifecycle_id=None):
    await db._conn.execute(
        "INSERT INTO fills (account_id, exchange_fill_id, symbol, side, "
        " terminal_position_id, is_close, calc_id, lifecycle_id) "
        "VALUES (1, ?, 'BTCUSDT', 'SELL', ?, ?, ?, ?)",
        (fid, tpid, is_close, calc_id, lifecycle_id),
    )
    await db._conn.commit()


async def _fill_attribution(db, fid):
    async with db._conn.execute(
        "SELECT calc_id, lifecycle_id FROM fills WHERE exchange_fill_id = ?",
        (fid,),
    ) as cur:
        row = await cur.fetchone()
    return (row[0], row[1]) if row else (None, None)


class TestClosingFillAttribution:
    @pytest.mark.asyncio
    async def test_single_calc_close_stamped(self, db, om):
        await _seed_junction(db, "POS-1", "calc-a", 100, 5.0, 1000, "uuid-1")
        await _seed_fill_row(db, "FC-1", tpid="POS-1")

        await om._stamp_closing_fill_attribution(
            ACCOUNT_ID, _fill("O-C", "POS-1", 5.0, is_close=1, fid="FC-1"),
        )

        assert await _fill_attribution(db, "FC-1") == ("calc-a", "uuid-1")

    @pytest.mark.asyncio
    async def test_scale_in_close_uses_most_contributing(self, db, om):
        # calc-b contributed more → it is the primary.
        await _seed_junction(db, "POS-1", "calc-a", 100, 2.0, 1000, "uuid-1")
        await _seed_junction(db, "POS-1", "calc-b", 101, 8.0, 2000, "uuid-1")
        await _seed_fill_row(db, "FC-1", tpid="POS-1")

        await om._stamp_closing_fill_attribution(
            ACCOUNT_ID, _fill("O-C", "POS-1", 10.0, is_close=1, fid="FC-1"),
        )

        calc_id, lc = await _fill_attribution(db, "FC-1")
        assert calc_id == "calc-b"   # most-contributing
        assert lc == "uuid-1"

    @pytest.mark.asyncio
    async def test_most_contributing_when_bigger_came_first(self, db, om):
        # Discrimination: the bigger contributor is the EARLIER entry, so
        # "max qty" and "latest ts" point at DIFFERENT rows. Proves the
        # primary is chosen by contributed_qty, not by recency.
        await _seed_junction(db, "POS-1", "calc-big", 100, 8.0, 1000, "uuid-1")
        await _seed_junction(db, "POS-1", "calc-small", 101, 2.0, 2000, "uuid-1")
        await _seed_fill_row(db, "FC-1", tpid="POS-1")
        await om._stamp_closing_fill_attribution(
            ACCOUNT_ID, _fill("O-C", "POS-1", 10.0, is_close=1, fid="FC-1"),
        )
        calc_id, _ = await _fill_attribution(db, "FC-1")
        assert calc_id == "calc-big"

    @pytest.mark.asyncio
    async def test_tie_break_prefers_first_entry(self, db, om):
        # Equal contributed_qty → earliest first_fill_ts wins (spec §3.2).
        await _seed_junction(db, "POS-1", "calc-early", 100, 5.0, 1000, "uuid-1")
        await _seed_junction(db, "POS-1", "calc-late", 101, 5.0, 2000, "uuid-1")
        await _seed_fill_row(db, "FC-1", tpid="POS-1")

        await om._stamp_closing_fill_attribution(
            ACCOUNT_ID, _fill("O-C", "POS-1", 5.0, is_close=1, fid="FC-1"),
        )

        calc_id, _ = await _fill_attribution(db, "FC-1")
        assert calc_id == "calc-early"

    @pytest.mark.asyncio
    async def test_primary_overrides_close_orders_own_calc(self, db, om):
        # A close fill that already carries its own calc_id (e.g. a
        # standalone TP that matched calc-tp) is OVERRIDDEN with the
        # position's primary — position attribution is authoritative.
        await _seed_junction(db, "POS-1", "calc-entry", 100, 5.0, 1000, "uuid-1")
        await _seed_fill_row(db, "FC-1", tpid="POS-1",
                             calc_id="calc-tp", lifecycle_id=None)

        await om._stamp_closing_fill_attribution(
            ACCOUNT_ID, _fill("O-C", "POS-1", 5.0, is_close=1, fid="FC-1"),
        )

        assert await _fill_attribution(db, "FC-1") == ("calc-entry", "uuid-1")

    @pytest.mark.asyncio
    async def test_no_junction_leaves_fill_untouched(self, db, om):
        # No junction for this position → existing fill attribution kept.
        await _seed_fill_row(db, "FC-1", tpid="POS-NONE",
                             calc_id="preexisting", lifecycle_id="lc-x")
        await om._stamp_closing_fill_attribution(
            ACCOUNT_ID, _fill("O-C", "POS-NONE", 5.0, is_close=1, fid="FC-1"),
        )
        assert await _fill_attribution(db, "FC-1") == ("preexisting", "lc-x")

    @pytest.mark.asyncio
    async def test_opening_fill_is_noop(self, db, om):
        await _seed_junction(db, "POS-1", "calc-a", 100, 5.0, 1000, "uuid-1")
        await _seed_fill_row(db, "FO-1", tpid="POS-1", is_close=0)
        # is_close=0 → method returns early, no stamp.
        await om._stamp_closing_fill_attribution(
            ACCOUNT_ID, _fill("O-1", "POS-1", 5.0, is_close=0, fid="FO-1"),
        )
        assert await _fill_attribution(db, "FO-1") == (None, None)

    @pytest.mark.asyncio
    async def test_empty_tpid_close_is_noop(self, db, om):
        await _seed_fill_row(db, "FC-1", tpid="", is_close=1)
        await om._stamp_closing_fill_attribution(
            ACCOUNT_ID, _fill("O-C", "", 5.0, is_close=1, fid="FC-1"),
        )
        assert await _fill_attribution(db, "FC-1") == (None, None)

    @pytest.mark.asyncio
    async def test_close_fill_stamped_via_real_path(self, real):
        # End-to-end: open (junction created), then close through the real
        # _process_single_fill → closing fill stamped from the primary.
        om, db = real
        await _seed_linked_order_and_calc(db, eoid="O-1", calc_id="calc-a")
        await om._process_single_fill(
            ACCOUNT_ID, _fill("O-1", "POS-1", 0.01, fid="F-OPEN"),
        )
        # Seed a reduce-only close order (no calc_id of its own).
        await db._conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
            " order_type, status, price, reduce_only) "
            "VALUES (1, 'O-CLOSE', 'BTCUSDT', 'SELL', 'take_profit', 'new', 55000, 1)",
        )
        await db._conn.commit()

        await om._process_single_fill(
            ACCOUNT_ID, _fill("O-CLOSE", "POS-1", 0.01, is_close=1, fid="F-CLOSE"),
        )

        # The opening fill's lifecycle is what the close should inherit.
        async with db._conn.execute(
            "SELECT lifecycle_id FROM positions_calcs WHERE position_id='POS-1'",
        ) as cur:
            pos_lc = (await cur.fetchone())[0]
        assert await _fill_attribution(db, "F-CLOSE") == ("calc-a", pos_lc)


# ── 8. T2.3 — PositionInfo.calc_id enrichment from junction primary ─────


def _pos(position_id, calc_id=""):
    from core.state import PositionInfo
    return PositionInfo(position_id=position_id, ticker="BTCUSDT",
                        direction="LONG", calc_id=calc_id)


class TestPositionInfoCalcId:
    @pytest.mark.asyncio
    async def test_field_defaults_empty(self):
        from core.state import PositionInfo
        assert PositionInfo().calc_id == ""

    @pytest.mark.asyncio
    async def test_calc_id_in_preserve_fields(self):
        from core.data_cache import _PRESERVE_FIELDS
        assert "calc_id" in _PRESERVE_FIELDS

    @pytest.mark.asyncio
    async def test_calc_id_survives_snapshot_rebuild(self):
        # Behavioral: _preserve_metadata must carry calc_id from the old
        # position object onto the rebuilt one, so a snapshot rebuild
        # between refreshes doesn't blank the live display.
        from core.data_cache import DataCache
        from core.state import PositionInfo
        old = PositionInfo(position_id="POS-1", ticker="BTCUSDT",
                           direction="LONG", calc_id="calc-a")
        new = PositionInfo(position_id="POS-1", ticker="BTCUSDT",
                           direction="LONG")
        DataCache._preserve_metadata(new, old)
        assert new.calc_id == "calc-a"

    @pytest.mark.asyncio
    async def test_enrich_sets_primary(self, db, om):
        await _seed_junction(db, "POS-1", "calc-a", 100, 5.0, 1000, "uuid-1")
        positions = [_pos("POS-1")]
        await om._enrich_positions_calc_id(ACCOUNT_ID, positions)
        assert positions[0].calc_id == "calc-a"

    @pytest.mark.asyncio
    async def test_enrich_uses_most_contributing(self, db, om):
        await _seed_junction(db, "POS-1", "calc-a", 100, 2.0, 1000, "uuid-1")
        await _seed_junction(db, "POS-1", "calc-b", 101, 8.0, 2000, "uuid-1")
        positions = [_pos("POS-1")]
        await om._enrich_positions_calc_id(ACCOUNT_ID, positions)
        assert positions[0].calc_id == "calc-b"

    @pytest.mark.asyncio
    async def test_enrich_tie_break_first_entry(self, db, om):
        await _seed_junction(db, "POS-1", "calc-early", 100, 5.0, 1000, "uuid-1")
        await _seed_junction(db, "POS-1", "calc-late", 101, 5.0, 2000, "uuid-1")
        positions = [_pos("POS-1")]
        await om._enrich_positions_calc_id(ACCOUNT_ID, positions)
        assert positions[0].calc_id == "calc-early"

    @pytest.mark.asyncio
    async def test_enrich_most_contributing_when_bigger_came_first(self, db, om):
        # qty and ts disagree: bigger contributor entered first.
        await _seed_junction(db, "POS-1", "calc-big", 100, 8.0, 1000, "uuid-1")
        await _seed_junction(db, "POS-1", "calc-small", 101, 2.0, 2000, "uuid-1")
        positions = [_pos("POS-1")]
        await om._enrich_positions_calc_id(ACCOUNT_ID, positions)
        assert positions[0].calc_id == "calc-big"

    @pytest.mark.asyncio
    async def test_enrich_multiple_positions_each_gets_own_primary(self, db, om):
        # Batched grouping must assign each position ITS OWN primary —
        # no cross-position bleed in the grouping dict.
        await _seed_junction(db, "POS-1", "calc-a", 100, 5.0, 1000, "uuid-1")
        await _seed_junction(db, "POS-2", "calc-b", 200, 9.0, 1500, "uuid-2")
        positions = [_pos("POS-1"), _pos("POS-2")]
        await om._enrich_positions_calc_id(ACCOUNT_ID, positions)
        assert positions[0].calc_id == "calc-a"
        assert positions[1].calc_id == "calc-b"

    @pytest.mark.asyncio
    async def test_enrich_rehydrate_without_fill(self, db, om):
        # Restart rehydrate: junction persists; a bare PositionInfo
        # (rebuilt with calc_id="") is repopulated from the DB alone, no
        # fill processed in this session.
        await _seed_junction(db, "POS-1", "calc-a", 100, 5.0, 1000, "uuid-1")
        positions = [_pos("POS-1")]
        await om._enrich_positions_calc_id(ACCOUNT_ID, positions)
        assert positions[0].calc_id == "calc-a"

    @pytest.mark.asyncio
    async def test_enrich_clears_stale_calc_id_when_no_junction(self, db, om):
        # R2 (T226 holistic audit): a same-(symbol,direction) reopen can
        # inherit a stale calc_id via _PRESERVE_FIELDS. With no junction
        # for its tpid, enrichment CLEARS it (no stale-attribution bleed).
        positions = [_pos("POS-REOPEN", calc_id="stale-calc")]
        await om._enrich_positions_calc_id(ACCOUNT_ID, positions)
        assert positions[0].calc_id == ""

    @pytest.mark.asyncio
    async def test_no_junction_leaves_empty(self, db, om):
        positions = [_pos("POS-NONE")]
        await om._enrich_positions_calc_id(ACCOUNT_ID, positions)
        assert positions[0].calc_id == ""

    @pytest.mark.asyncio
    async def test_empty_position_id_skipped(self, db, om):
        positions = [_pos("")]
        await om._enrich_positions_calc_id(ACCOUNT_ID, positions)
        assert positions[0].calc_id == ""

    @pytest.mark.asyncio
    async def test_refresh_cache_populates_calc_id(self, real, monkeypatch):
        # End-to-end: opening fill creates the junction via the real path;
        # refresh_cache then enriches the live PositionInfo.calc_id.
        om, db = real
        from core.state import app_state
        await _seed_linked_order_and_calc(db, eoid="O-1", calc_id="calc-a")
        await om._process_single_fill(
            ACCOUNT_ID, _fill("O-1", "POS-1", 0.01, fid="F-OPEN"),
        )
        pos = _pos("POS-1")
        monkeypatch.setattr(app_state, "positions", [pos])
        await om.refresh_cache(ACCOUNT_ID)
        assert pos.calc_id == "calc-a"
