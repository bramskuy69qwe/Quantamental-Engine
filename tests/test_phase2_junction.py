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
                      symbol="BTCUSDT", side="BUY", account_id=ACCOUNT_ID) -> int:
    cur = await db._conn.execute(
        "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
        " calc_id, lifecycle_id) VALUES (?, ?, ?, ?, ?, ?)",
        (account_id, eoid, symbol, side, calc_id, lifecycle_id),
    )
    await db._conn.commit()
    return cur.lastrowid


async def _seed_calc(db, calc_id, lifecycle_id=None, ticker="BTCUSDT",
                     *, account_id=ACCOUNT_ID, size=0.0, tp_price=0.0,
                     sl_price=0.0, overridden_size=None, planned_size=None,
                     overridden_tp=None, planned_tp=None,
                     overridden_sl=None, planned_sl=None,
                     effective_entry=0.0, average=0.0, est_r=0.0) -> None:
    # Legacy size/tp_price/sl_price (NOT NULL DEFAULT 0) are what the
    # calculator writes today; overridden_*/planned_* (P0.T3, NULL on
    # every live calc) are the spec-named source the T2.4 snapshot
    # prefers if a future calculator ever populates them. effective_entry/
    # average/est_r back the T2.5 close-time deltas (planned_entry, planned_r).
    await db._conn.execute(
        "INSERT INTO pre_trade_log (account_id, timestamp, ticker, calc_id, "
        " lifecycle_id, size, tp_price, sl_price, overridden_size, planned_size, "
        " overridden_tp, planned_tp, overridden_sl, planned_sl, "
        " effective_entry, average, est_r) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (account_id, "2026-05-29T00:00:00Z", ticker, calc_id, lifecycle_id,
         size, tp_price, sl_price, overridden_size, planned_size,
         overridden_tp, planned_tp, overridden_sl, planned_sl,
         effective_entry, average, est_r),
    )
    await db._conn.commit()


def _fill(eoid, tpid, qty, ts=1000, is_close=0, symbol="BTCUSDT", fid="F-1",
          account_id=ACCOUNT_ID, price=0.0):
    return {
        "account_id": account_id,
        "exchange_fill_id": fid,
        "exchange_order_id": eoid,
        "terminal_position_id": tpid,
        "symbol": symbol,
        "quantity": qty,
        "price": price,
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

        # Two DISTINCT fills of the same order (distinct exchange_fill_id)
        # genuinely accumulate. (T232: previously both used the default
        # fid='F-1', which looked like — but did not test — redelivery
        # safety; the helper accumulates regardless of fill identity, so
        # distinct fids reflect honest two-fill accumulation. The
        # same-fid redelivery double-count is the separately-documented
        # deferred finding — see HANDOFF "junction contributed_qty
        # redelivery double-count".)
        await om._link_position_calc_on_open(
            ACCOUNT_ID, _fill("O-1", "POS-1", 3.0, ts=1000, fid="F-1"),
        )
        await om._link_position_calc_on_open(
            ACCOUNT_ID, _fill("O-1", "POS-1", 4.0, ts=2000, fid="F-2"),
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


# ── 3b. T2.4 — planned_* snapshot at contribution time ─────────────────


class TestPlannedSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_from_legacy_columns(self, db, om):
        # Live reality: only legacy size/tp_price/sl_price are populated.
        await _seed_order(db, "O-1", calc_id="calc-a")
        await _seed_calc(db, "calc-a", size=3.0, tp_price=55000.0, sl_price=48000.0)
        await om._link_position_calc_on_open(ACCOUNT_ID, _fill("O-1", "POS-1", 3.0))
        row = (await _junction(db, "POS-1"))[0]
        assert row["planned_size"] == pytest.approx(3.0)
        assert row["planned_tp"] == pytest.approx(55000.0)
        assert row["planned_sl"] == pytest.approx(48000.0)

    @pytest.mark.asyncio
    async def test_prefers_overridden_spec_columns(self, db, om):
        # Forward-compat: if a future calculator populates overridden_*,
        # the snapshot prefers them over the legacy columns.
        await _seed_order(db, "O-1", calc_id="calc-a")
        await _seed_calc(db, "calc-a", size=3.0, tp_price=55000.0, sl_price=48000.0,
                         overridden_size=9.0, overridden_tp=60000.0,
                         overridden_sl=47000.0)
        await om._link_position_calc_on_open(ACCOUNT_ID, _fill("O-1", "POS-1", 9.0))
        row = (await _junction(db, "POS-1"))[0]
        assert row["planned_size"] == pytest.approx(9.0)
        assert row["planned_tp"] == pytest.approx(60000.0)
        assert row["planned_sl"] == pytest.approx(47000.0)

    @pytest.mark.asyncio
    async def test_falls_back_to_planned_col_when_no_override(self, db, om):
        # Middle tier: planned_* used when overridden_* is NULL; falls to
        # legacy only when both spec columns are NULL.
        await _seed_order(db, "O-1", calc_id="calc-a")
        await _seed_calc(db, "calc-a", size=3.0, tp_price=55000.0, sl_price=48000.0,
                         planned_tp=58000.0)   # overridden_tp NULL
        await om._link_position_calc_on_open(ACCOUNT_ID, _fill("O-1", "POS-1", 3.0))
        row = (await _junction(db, "POS-1"))[0]
        assert row["planned_tp"] == pytest.approx(58000.0)  # planned_tp beats legacy
        assert row["planned_sl"] == pytest.approx(48000.0)  # falls to legacy sl_price

    @pytest.mark.asyncio
    async def test_absent_tpsl_snapshots_null(self, db, om):
        # tp_price/sl_price == 0.0 means "no level" → snapshot NULL,
        # not a literal 0 (HANDOFF lesson 7 / T1.7).
        await _seed_order(db, "O-1", calc_id="calc-a")
        await _seed_calc(db, "calc-a", size=3.0, tp_price=0.0, sl_price=0.0)
        await om._link_position_calc_on_open(ACCOUNT_ID, _fill("O-1", "POS-1", 3.0))
        row = (await _junction(db, "POS-1"))[0]
        assert row["planned_size"] == pytest.approx(3.0)
        assert row["planned_tp"] is None
        assert row["planned_sl"] is None

    @pytest.mark.asyncio
    async def test_scale_in_per_calc_independent_snapshots(self, db, om):
        # Each (position, calc, order) row snapshots ITS OWN calc's plan —
        # the core T2.4 scale-in deliverable.
        await _seed_order(db, "O-A", calc_id="calc-a")
        await _seed_order(db, "O-B", calc_id="calc-b")
        await _seed_calc(db, "calc-a", size=3.0, tp_price=55000.0, sl_price=48000.0)
        await _seed_calc(db, "calc-b", size=7.0, tp_price=60000.0, sl_price=47000.0)
        await om._link_position_calc_on_open(
            ACCOUNT_ID, _fill("O-A", "POS-1", 3.0, fid="F1"))
        await om._link_position_calc_on_open(
            ACCOUNT_ID, _fill("O-B", "POS-1", 7.0, fid="F2"))
        rows = {r["calc_id"]: r for r in await _junction(db, "POS-1")}
        assert rows["calc-a"]["planned_size"] == pytest.approx(3.0)
        assert rows["calc-a"]["planned_tp"] == pytest.approx(55000.0)
        assert rows["calc-b"]["planned_size"] == pytest.approx(7.0)
        assert rows["calc-b"]["planned_tp"] == pytest.approx(60000.0)

    @pytest.mark.asyncio
    async def test_snapshot_stable_across_multi_fill(self, db, om):
        # Snapshot is taken at FIRST contribution; later fills of the same
        # triple preserve it (UPSERT omits planned_* from DO UPDATE SET)
        # even if the calc row mutates. size_delta_pct stays NULL (T2.5).
        await _seed_order(db, "O-1", calc_id="calc-a")
        await _seed_calc(db, "calc-a", size=3.0, tp_price=55000.0, sl_price=48000.0)
        await om._link_position_calc_on_open(
            ACCOUNT_ID, _fill("O-1", "POS-1", 3.0, ts=1000, fid="F1"))
        await db._conn.execute(
            "UPDATE pre_trade_log SET tp_price = 99999.0 WHERE calc_id = 'calc-a'")
        await db._conn.commit()
        await om._link_position_calc_on_open(
            ACCOUNT_ID, _fill("O-1", "POS-1", 2.0, ts=2000, fid="F2"))
        row = (await _junction(db, "POS-1"))[0]
        assert row["contributed_qty"] == pytest.approx(5.0)   # accumulated
        assert row["planned_tp"] == pytest.approx(55000.0)    # snapshot preserved
        assert row["size_delta_pct"] is None                  # deferred to T2.5

    @pytest.mark.asyncio
    async def test_planned_snapshot_via_real_path(self, real):
        # Rule 8: the snapshot must wire through the real
        # _process_single_fill, not just the helper.
        om, db = real
        await _seed_linked_order_and_calc(db, eoid="O-1", calc_id="calc-a")
        await db._conn.execute(
            "UPDATE pre_trade_log SET size=4.0, tp_price=55000.0, sl_price=48000.0 "
            "WHERE calc_id='calc-a'")
        await db._conn.commit()
        await om._process_single_fill(
            ACCOUNT_ID, _fill("O-1", "POS-1", 4.0, fid="F-OPEN"))
        row = (await _junction(db, "POS-1"))[0]
        assert row["planned_size"] == pytest.approx(4.0)
        assert row["planned_tp"] == pytest.approx(55000.0)
        assert row["planned_sl"] == pytest.approx(48000.0)

    @pytest.mark.asyncio
    async def test_account_id_predicate_discrimination(self, db, om):
        # The snapshot SELECT is scoped WHERE calc_id=? AND account_id=?.
        # Seed the SAME calc_id under account 2 FIRST (lower id) with a
        # decoy, then account 1 with the real values. With ORDER BY id
        # LIMIT 1, dropping the account_id predicate would pick account 2's
        # decoy — so this fails if the predicate regresses. (T231 audit:
        # calc_id is non-unique in pre_trade_log; the predicate is the
        # only thing scoping the read to the right account.)
        await _seed_calc(db, "calc-a", account_id=2, size=99.0, tp_price=11.0)
        await _seed_calc(db, "calc-a", account_id=1, size=3.0, tp_price=55000.0)
        await _seed_order(db, "O-1", calc_id="calc-a", account_id=1)
        await om._link_position_calc_on_open(
            1, _fill("O-1", "POS-1", 3.0, account_id=1))
        row = (await _junction(db, "POS-1"))[0]
        assert row["planned_size"] == pytest.approx(3.0)     # acct 1, not decoy 99
        assert row["planned_tp"] == pytest.approx(55000.0)

    @pytest.mark.asyncio
    async def test_intra_triple_overridden_beats_planned(self, db, om):
        # Within one field's triple the priority is overridden_* > planned_*
        # > legacy. Distinct sentinel magnitudes per tier lock the ordering
        # (T231 audit: the only intra-triple priority not otherwise pinned).
        await _seed_order(db, "O-1", calc_id="calc-a")
        await _seed_calc(db, "calc-a",
                         size=1.0, overridden_size=9.0, planned_size=5.0,
                         tp_price=55000.0, planned_tp=58000.0,  # overridden_tp NULL
                         sl_price=48000.0)                       # both spec cols NULL
        await om._link_position_calc_on_open(ACCOUNT_ID, _fill("O-1", "POS-1", 9.0))
        row = (await _junction(db, "POS-1"))[0]
        assert row["planned_size"] == pytest.approx(9.0)    # overridden > planned(5) > legacy(1)
        assert row["planned_tp"] == pytest.approx(58000.0)  # planned > legacy(55000)
        assert row["planned_sl"] == pytest.approx(48000.0)  # legacy (both spec NULL)

    @pytest.mark.asyncio
    async def test_scale_in_per_calc_snapshots_via_real_path(self, real):
        # Rule 8: per-calc independence through the REAL
        # _process_single_fill scale-in path (two orders/calcs on one
        # position), not just the helper.
        om, db = real
        await _seed_linked_order_and_calc(db, eoid="O-A", calc_id="calc-a")
        await _seed_linked_order_and_calc(db, eoid="O-B", calc_id="calc-b")
        await db._conn.execute(
            "UPDATE pre_trade_log SET size=3.0, tp_price=55000.0 WHERE calc_id='calc-a'")
        await db._conn.execute(
            "UPDATE pre_trade_log SET size=7.0, tp_price=60000.0 WHERE calc_id='calc-b'")
        await db._conn.commit()
        await om._process_single_fill(ACCOUNT_ID, _fill("O-A", "POS-1", 3.0, fid="F-A"))
        await om._process_single_fill(ACCOUNT_ID, _fill("O-B", "POS-1", 7.0, fid="F-B"))
        rows = {r["calc_id"]: r for r in await _junction(db, "POS-1")}
        assert rows["calc-a"]["planned_size"] == pytest.approx(3.0)
        assert rows["calc-a"]["planned_tp"] == pytest.approx(55000.0)
        assert rows["calc-b"]["planned_size"] == pytest.approx(7.0)
        assert rows["calc-b"]["planned_tp"] == pytest.approx(60000.0)


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
        # T232: the OPENING fill itself is stamped with the same lifecycle
        # (spec §3.5 lists fills among the stamping targets; previously
        # only closing fills got it). Closes the Phase-7 single-key
        # /context/lifecycle/{id} fills-join gap for new positions.
        async with db._conn.execute(
            "SELECT lifecycle_id FROM fills WHERE exchange_fill_id = 'F-1'",
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
                         lifecycle_id, *, planned_size=None,
                         planned_tp=None, planned_sl=None):
    await db.upsert_position_calc_link({
        "position_id": position_id, "calc_id": calc_id, "order_id": order_id,
        "account_id": ACCOUNT_ID, "contributed_qty": qty,
        "first_fill_ts": ts, "last_fill_ts": ts, "lifecycle_id": lifecycle_id,
        "planned_size": planned_size, "planned_tp": planned_tp,
        "planned_sl": planned_sl,
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
    async def test_enrich_clears_stale_in_mixed_batch(self, db, om):
        # T232 (holistic-audit R2 discrimination): the clear must be
        # PER-POSITION, not "only when the junction table is empty". One
        # position HAS a junction (non-empty `primary` dict); the stale
        # reopen does NOT — it must still be cleared. A regression that
        # only cleared on an empty table would pass the empty-table test
        # but fail HERE.
        await _seed_junction(db, "POS-A", "calc-a", 100, 5.0, 1000, "uuid-a")
        positions = [_pos("POS-A"), _pos("POS-REOPEN-STALE", calc_id="stale")]
        await om._enrich_positions_calc_id(ACCOUNT_ID, positions)
        assert positions[0].calc_id == "calc-a"   # keeps its primary
        assert positions[1].calc_id == ""         # stale cleared despite non-empty batch

    @pytest.mark.asyncio
    async def test_enrich_self_heals_after_junction_appears(self, db, om):
        # Clear-then-repopulate the SAME tpid: first no junction → cleared;
        # then the new position's first opening fill writes its junction →
        # next enrich picks up the new primary (the R2 self-heal claim).
        stale = _pos("POS-REOPEN", calc_id="stale")
        await om._enrich_positions_calc_id(ACCOUNT_ID, [stale])
        assert stale.calc_id == ""
        await _seed_junction(db, "POS-REOPEN", "calc-new", 100, 5.0, 3000, "uuid-new")
        await om._enrich_positions_calc_id(ACCOUNT_ID, [stale])
        assert stale.calc_id == "calc-new"

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


# ── 9. T2.5 — close-time deltas vs most-contributing calc ──────────────


async def _closed_pos(db, tpid):
    async with db._conn.execute(
        "SELECT * FROM closed_positions WHERE terminal_position_id = ? "
        "ORDER BY id DESC LIMIT 1", (tpid,),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


class TestCloseDeltas:
    """T2.5: _compute_close_deltas against the most-contributing calc."""

    @pytest.mark.asyncio
    async def test_all_six_deltas_computed(self, db, om):
        await _seed_calc(db, "calc-a", effective_entry=50000.0, est_r=2.0)
        await _seed_junction(db, "POS-1", "calc-a", 100, 10.0, 1000, "lc-1",
                             planned_size=10.0, planned_tp=55000.0, planned_sl=48000.0)
        out = await om._compute_close_deltas(
            ACCOUNT_ID, "POS-1",
            entry_price=50500.0, actual_size=11.0, exit_price=54000.0,
            entry_time=1000, exit_time=4000,
        )
        assert out["entry_px_delta_pct"] == pytest.approx(1.0)       # (50500-50000)/50000*100
        assert out["size_delta_pct"] == pytest.approx(10.0)         # (11-10)/10*100
        # exit 54000 is closer to planned_tp 55000 than planned_sl 48000:
        assert out["exit_vs_target_pct"] == pytest.approx((54000-55000)/55000*100, abs=1e-3)
        assert out["realized_r"] == pytest.approx(1.75)             # (54000-50500)/(50000-48000)
        assert out["planned_r"] == pytest.approx(2.0)
        assert out["hold_time_actual_ms"] == 3000

    @pytest.mark.asyncio
    async def test_basis_is_most_contributing_calc(self, db, om):
        # calc-b contributes more → its plan is the basis (not calc-a).
        await _seed_calc(db, "calc-a", effective_entry=50000.0, est_r=1.0)
        await _seed_calc(db, "calc-b", effective_entry=51000.0, est_r=3.0)
        await _seed_junction(db, "POS-1", "calc-a", 100, 2.0, 1000, "lc-1",
                             planned_size=2.0, planned_tp=55000.0, planned_sl=49000.0)
        await _seed_junction(db, "POS-1", "calc-b", 101, 8.0, 2000, "lc-1",
                             planned_size=8.0, planned_tp=60000.0, planned_sl=48000.0)
        out = await om._compute_close_deltas(
            ACCOUNT_ID, "POS-1",
            entry_price=51000.0, actual_size=10.0, exit_price=59000.0,
            entry_time=1000, exit_time=5000,
        )
        # planned_entry = calc-b's 51000 → entry_px_delta_pct = 0
        assert out["entry_px_delta_pct"] == pytest.approx(0.0)
        # planned_r = calc-b's est_r 3.0
        assert out["planned_r"] == pytest.approx(3.0)
        # realized_r uses calc-b's planned_sl 48000: (59000-51000)/(51000-48000)
        assert out["realized_r"] == pytest.approx(8000/3000, abs=1e-3)

    @pytest.mark.asyncio
    async def test_realized_r_short_direction_agnostic(self, db, om):
        # SHORT: entry 100, stop ABOVE at 110, exit 90 (a win). The spec
        # formula (exit-entry)/(planned_entry-planned_sl) flips both
        # numerator and denominator → +1 R without any sign handling.
        await _seed_calc(db, "calc-s", effective_entry=100.0)
        await _seed_junction(db, "POS-S", "calc-s", 100, 5.0, 1000, "lc-s",
                             planned_size=5.0, planned_tp=90.0, planned_sl=110.0)
        out = await om._compute_close_deltas(
            ACCOUNT_ID, "POS-S",
            entry_price=100.0, actual_size=5.0, exit_price=90.0,
            entry_time=1000, exit_time=2000,
        )
        assert out["realized_r"] == pytest.approx(1.0)   # (90-100)/(100-110)

    @pytest.mark.asyncio
    async def test_null_guard_missing_planned_entry(self, db, om):
        # No effective_entry/average on the calc → planned_entry falsy →
        # entry_px_delta_pct and realized_r omitted; size_delta_pct still set.
        await _seed_calc(db, "calc-a")   # effective_entry/average default 0
        await _seed_junction(db, "POS-1", "calc-a", 100, 10.0, 1000, "lc-1",
                             planned_size=10.0, planned_tp=55000.0, planned_sl=48000.0)
        out = await om._compute_close_deltas(
            ACCOUNT_ID, "POS-1",
            entry_price=50500.0, actual_size=10.0, exit_price=54000.0,
            entry_time=1000, exit_time=2000,
        )
        assert "entry_px_delta_pct" not in out
        assert "realized_r" not in out
        assert out["size_delta_pct"] == pytest.approx(0.0)   # planned_size present

    @pytest.mark.asyncio
    async def test_no_junction_returns_empty(self, db, om):
        out = await om._compute_close_deltas(
            ACCOUNT_ID, "POS-NONE",
            entry_price=50000.0, actual_size=1.0, exit_price=51000.0,
            entry_time=1000, exit_time=2000,
        )
        assert out == {}

    @pytest.mark.asyncio
    async def test_actual_size_zero_omits_size_delta(self, db, om):
        # Opens-unresolvable fallback passes actual_size=0; size_delta_pct
        # must be OMITTED (NULL), not a spurious -100% (T233 review fix).
        await _seed_calc(db, "calc-a", effective_entry=50000.0)
        await _seed_junction(db, "POS-1", "calc-a", 100, 10.0, 1000, "lc-1",
                             planned_size=10.0, planned_tp=55000.0, planned_sl=48000.0)
        out = await om._compute_close_deltas(
            ACCOUNT_ID, "POS-1",
            entry_price=50500.0, actual_size=0.0, exit_price=54000.0,
            entry_time=1000, exit_time=2000,
        )
        assert "size_delta_pct" not in out

    @pytest.mark.asyncio
    async def test_planned_size_none_omits_size_delta(self, db, om):
        # No planned_size on the junction (NULL) → size_delta_pct omitted.
        await _seed_calc(db, "calc-a", effective_entry=50000.0)
        await _seed_junction(db, "POS-1", "calc-a", 100, 10.0, 1000, "lc-1",
                             planned_size=None, planned_tp=55000.0, planned_sl=48000.0)
        out = await om._compute_close_deltas(
            ACCOUNT_ID, "POS-1",
            entry_price=50500.0, actual_size=10.0, exit_price=54000.0,
            entry_time=1000, exit_time=2000,
        )
        assert "size_delta_pct" not in out

    @pytest.mark.asyncio
    async def test_zero_planned_r_omitted(self, db, om):
        # est_r==0 ("no R estimate") → planned_r omitted (NULL), not stored
        # as a literal 0 — consistent with the absent-value→NULL convention.
        await _seed_calc(db, "calc-a", effective_entry=50000.0, est_r=0.0)
        await _seed_junction(db, "POS-1", "calc-a", 100, 10.0, 1000, "lc-1",
                             planned_size=10.0, planned_tp=55000.0, planned_sl=48000.0)
        out = await om._compute_close_deltas(
            ACCOUNT_ID, "POS-1",
            entry_price=50500.0, actual_size=10.0, exit_price=54000.0,
            entry_time=1000, exit_time=2000,
        )
        assert "planned_r" not in out

    @pytest.mark.asyncio
    async def test_columns_not_emitted_without_amendments(self, db, om):
        # No amendments seeded → tp_drift_pct/sl_drift_pct omitted (P4.T5
        # computes them only when the primary calc's TP/SL leg was amended —
        # see test_phase4_drift). cumulative_amendment_count is computed in
        # _build_close_row_for_fill, NOT this dict; hold_time_planned_ms has
        # no source — both stay out here regardless.
        await _seed_calc(db, "calc-a", effective_entry=50000.0, est_r=2.0)
        await _seed_junction(db, "POS-1", "calc-a", 100, 10.0, 1000, "lc-1",
                             planned_size=10.0, planned_tp=55000.0, planned_sl=48000.0)
        out = await om._compute_close_deltas(
            ACCOUNT_ID, "POS-1",
            entry_price=50500.0, actual_size=10.0, exit_price=54000.0,
            entry_time=1000, exit_time=2000,
        )
        for omitted in ("tp_drift_pct", "sl_drift_pct",
                        "cumulative_amendment_count", "hold_time_planned_ms"):
            assert omitted not in out

    @pytest.mark.asyncio
    async def test_deltas_persisted_via_real_close_path(self, real):
        # Rule 8: deltas flow through _build_close_row_for_fill →
        # insert_closed_position → closed_positions columns. Drives the
        # real open (junction planned_* snapshot via T2.4) then close.
        om, db = real
        await _seed_linked_order_and_calc(db, eoid="O-1", calc_id="calc-a")
        await db._conn.execute(
            "UPDATE pre_trade_log SET size=10.0, tp_price=55000.0, sl_price=48000.0, "
            "effective_entry=50000.0, est_r=2.0 WHERE calc_id='calc-a'")
        await db._conn.commit()
        # Opening fill @ 50500 → junction + planned_* snapshot.
        await om._process_single_fill(
            ACCOUNT_ID, _fill("O-1", "POS-1", 10.0, fid="F-OPEN", price=50500.0, ts=1000))
        # Reduce-only close order + closing fill @ 54000.
        await db._conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
            " order_type, status, price, reduce_only) "
            "VALUES (1, 'O-C', 'BTCUSDT', 'SELL', 'take_profit', 'new', 54000, 1)")
        await db._conn.commit()
        close = _fill("O-C", "POS-1", 10.0, is_close=1, fid="F-CLOSE",
                      price=54000.0, ts=4000)
        await om._process_single_fill(ACCOUNT_ID, close)
        await om._build_close_row_for_fill(ACCOUNT_ID, close)

        cp = await _closed_pos(db, "POS-1")
        assert cp is not None
        assert cp["entry_px_delta_pct"] == pytest.approx(1.0)
        assert cp["size_delta_pct"] == pytest.approx(0.0)
        assert cp["realized_r"] == pytest.approx(1.75)
        assert cp["planned_r"] == pytest.approx(2.0)
        assert cp["hold_time_actual_ms"] == 3000
        # tp/sl drift stay NULL here — no amendment seeded (P4.T5 computes
        # them only for an AMENDED stop; see test_phase4_drift for the
        # amended path). hold_time_planned_ms remains NULL (no source).
        assert cp["tp_drift_pct"] is None              # no amendment
        assert cp["sl_drift_pct"] is None              # no amendment
        # P4.T2 LANDED: cumulative_amendment_count now computed at close from
        # order_amendments; 0 here (this fixture seeds no amendments).
        assert cp["cumulative_amendment_count"] == 0   # P4.3 / P4.T2
        assert cp["hold_time_planned_ms"] is None       # no source column


# ── 10. T2.6 — closed_positions.calc_id + lifecycle_id = junction primary ─


async def _seed_open_fill_no_junction(db, fid, eoid, calc_id, tpid, price, qty, ts):
    # Persist an OPENING fill directly (with calc_id), WITHOUT seeding a
    # junction row — simulates the no-junction path (UNPLANNED / binance
    # empty-tpid) so the close-row builder must fall back to earliest-fill.
    await db._conn.execute(
        "INSERT INTO fills (account_id, exchange_fill_id, exchange_order_id, "
        " symbol, side, direction, price, quantity, terminal_position_id, "
        " is_close, calc_id, timestamp_ms) "
        "VALUES (1, ?, ?, 'BTCUSDT', 'BUY', 'long', ?, ?, ?, 0, ?, ?)",
        (fid, eoid, price, qty, tpid, calc_id, ts),
    )
    await db._conn.commit()


class TestClosedPositionPrimaryCalc:
    """T2.6: closed_positions.calc_id + lifecycle_id sealed from the
    most-contributing junction calc, closing the R1 divergence."""

    @pytest.mark.asyncio
    async def test_closed_calc_and_lifecycle_from_primary_and_converge(self, real):
        # Scale-in where the BIGGER calc (calc-B, qty 7) is NOT first
        # (calc-A, qty 3, opened first). Pre-T2.6 the closed row would carry
        # calc-A (earliest) + NULL lifecycle; now it must carry calc-B
        # (most-contributing) + the sealed lifecycle, AND agree with
        # fills(close).calc_id (T2.2) and the junction lifecycle.
        om, db = real
        await _seed_linked_order_and_calc(db, eoid="O-A", calc_id="calc-A")
        await _seed_linked_order_and_calc(db, eoid="O-B", calc_id="calc-B")
        # Distinct tp/sl per calc so the tp_price/sl_price auto-resolve
        # (insert_closed_position resolves by calc_id) is pinned to the
        # PRIMARY (calc-B), not the earliest (calc-A) — a real T2.6 side effect.
        await db._conn.execute(
            "UPDATE pre_trade_log SET size=3.0, effective_entry=50000.0, "
            "tp_price=55000.0, sl_price=48000.0 WHERE calc_id='calc-A'")
        await db._conn.execute(
            "UPDATE pre_trade_log SET size=7.0, effective_entry=51000.0, "
            "tp_price=60000.0, sl_price=47000.0 WHERE calc_id='calc-B'")
        await db._conn.commit()
        await om._process_single_fill(
            ACCOUNT_ID, _fill("O-A", "POS-1", 3.0, fid="FA", price=50000.0, ts=1000))
        await om._process_single_fill(
            ACCOUNT_ID, _fill("O-B", "POS-1", 7.0, fid="FB", price=51000.0, ts=2000))
        await db._conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
            " order_type, status, price, reduce_only) "
            "VALUES (1, 'O-C', 'BTCUSDT', 'SELL', 'take_profit', 'new', 54000, 1)")
        await db._conn.commit()
        close = _fill("O-C", "POS-1", 10.0, is_close=1, fid="FC", price=54000.0, ts=4000)
        await om._process_single_fill(ACCOUNT_ID, close)
        await om._build_close_row_for_fill(ACCOUNT_ID, close)

        cp = await _closed_pos(db, "POS-1")
        assert cp["calc_id"] == "calc-B"        # most-contributing, NOT earliest calc-A
        assert cp["lifecycle_id"] is not None   # sealed (was NULL pre-T2.6)
        # R1 convergence: all attribution surfaces agree.
        async with db._conn.execute(
            "SELECT calc_id, lifecycle_id FROM fills WHERE exchange_fill_id='FC'") as cur:
            fc = await cur.fetchone()
        async with db._conn.execute(
            "SELECT lifecycle_id FROM positions_calcs WHERE position_id='POS-1' LIMIT 1") as cur:
            jlc = (await cur.fetchone())[0]
        assert fc["calc_id"] == "calc-B"
        assert cp["lifecycle_id"] == fc["lifecycle_id"] == jlc
        # tp/sl auto-resolved from the PRIMARY (calc-B), not earliest calc-A.
        assert cp["tp_price"] == pytest.approx(60000.0)
        assert cp["sl_price"] == pytest.approx(47000.0)

    @pytest.mark.asyncio
    async def test_no_junction_falls_back_to_earliest_calc(self, real):
        # No junction (UNPLANNED / binance empty-tpid shape): the close row
        # keeps the Phase-1 earliest-opening-fill calc_id, lifecycle NULL.
        om, db = real
        await _seed_linked_order_and_calc(db, eoid="O-A", calc_id="calc-early")
        # Opening fill persisted directly, NO junction seeded.
        await _seed_open_fill_no_junction(
            db, "FA", "O-A", "calc-early", "POS-NJ", 50000.0, 5.0, 1000)
        await db._conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
            " order_type, status, price, reduce_only) "
            "VALUES (1, 'O-C', 'BTCUSDT', 'SELL', 'take_profit', 'new', 54000, 1)")
        await db._conn.commit()
        close = _fill("O-C", "POS-NJ", 5.0, is_close=1, fid="FC", price=54000.0, ts=4000)
        # Persist the closing fill so get_fills_by_order resolves it.
        await om._process_single_fill(ACCOUNT_ID, close)
        await om._build_close_row_for_fill(ACCOUNT_ID, close)

        cp = await _closed_pos(db, "POS-NJ")
        assert cp is not None
        assert cp["calc_id"] == "calc-early"   # earliest-fill fallback
        assert cp["lifecycle_id"] is None      # no junction → no lifecycle

    @pytest.mark.asyncio
    async def test_empty_tpid_has_no_primary(self, db, om):
        # binance one-way empty-tpid: _position_primary_calc short-circuits
        # on the empty position_id guard → (None, None), so the close-row
        # builder takes the earliest-fill fallback (no junction to consult).
        assert await om._position_primary_calc(ACCOUNT_ID, "") == (None, None)

    @pytest.mark.asyncio
    async def test_single_calc_seal(self, real):
        # Common case: one calc → closed row carries that calc + its lifecycle.
        om, db = real
        await _seed_linked_order_and_calc(db, eoid="O-1", calc_id="calc-solo")
        await db._conn.execute(
            "UPDATE pre_trade_log SET size=5.0, effective_entry=50000.0 WHERE calc_id='calc-solo'")
        await db._conn.commit()
        await om._process_single_fill(
            ACCOUNT_ID, _fill("O-1", "POS-1", 5.0, fid="FO", price=50000.0, ts=1000))
        await db._conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
            " order_type, status, price, reduce_only) "
            "VALUES (1, 'O-C', 'BTCUSDT', 'SELL', 'take_profit', 'new', 53000, 1)")
        await db._conn.commit()
        close = _fill("O-C", "POS-1", 5.0, is_close=1, fid="FC", price=53000.0, ts=3000)
        await om._process_single_fill(ACCOUNT_ID, close)
        await om._build_close_row_for_fill(ACCOUNT_ID, close)
        cp = await _closed_pos(db, "POS-1")
        assert cp["calc_id"] == "calc-solo"
        assert cp["lifecycle_id"] is not None

    @pytest.mark.asyncio
    async def test_tie_break_first_entry_at_close(self, real):
        # Equal contributed_qty across two calcs → §3.2 tie-break picks the
        # EARLIER first_fill_ts (calc-early) for closed_positions.calc_id.
        om, db = real
        await _seed_linked_order_and_calc(db, eoid="O-E", calc_id="calc-early")
        await _seed_linked_order_and_calc(db, eoid="O-L", calc_id="calc-late")
        await db._conn.execute(
            "UPDATE pre_trade_log SET size=5.0, effective_entry=50000.0 "
            "WHERE calc_id IN ('calc-early','calc-late')")
        await db._conn.commit()
        await om._process_single_fill(
            ACCOUNT_ID, _fill("O-E", "POS-1", 5.0, fid="FE", price=50000.0, ts=1000))
        await om._process_single_fill(
            ACCOUNT_ID, _fill("O-L", "POS-1", 5.0, fid="FL", price=50000.0, ts=2000))
        await db._conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
            " order_type, status, price, reduce_only) "
            "VALUES (1, 'O-C', 'BTCUSDT', 'SELL', 'take_profit', 'new', 53000, 1)")
        await db._conn.commit()
        close = _fill("O-C", "POS-1", 10.0, is_close=1, fid="FC", price=53000.0, ts=4000)
        await om._process_single_fill(ACCOUNT_ID, close)
        await om._build_close_row_for_fill(ACCOUNT_ID, close)
        cp = await _closed_pos(db, "POS-1")
        assert cp["calc_id"] == "calc-early"   # tie → earliest first_fill_ts


# ── 11. T2.7 — exit_reason spec §3.4 enum (forward path) ───────────────


async def _seed_order_with_type(db, eoid, order_type):
    await db._conn.execute(
        "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
        " order_type, status, price, reduce_only) "
        "VALUES (1, ?, 'BTCUSDT', 'SELL', ?, 'filled', 50000, 1)",
        (eoid, order_type),
    )
    await db._conn.commit()


class TestExitReasonEnum:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("order_type,expected", [
        ("take_profit", "TP_PLANNED"),
        ("take_profit_market", "TP_PLANNED"),
        ("stop_loss", "SL_PLANNED"),
        ("stop_market", "SL_PLANNED"),
        ("trailing_stop", "SL_PLANNED"),   # trailing collapses to SL (deviation)
        ("market", "MANUAL_OTHER"),
        ("limit", "MANUAL_OTHER"),
        ("", "MANUAL_OTHER"),
    ])
    async def test_order_type_maps_to_enum(self, db, om, order_type, expected):
        await _seed_order_with_type(db, "O-X", order_type)
        assert await om._determine_exit_reason(ACCOUNT_ID, "O-X") == expected

    @pytest.mark.asyncio
    async def test_empty_eoid_and_missing_order_are_manual_other(self, db, om):
        assert await om._determine_exit_reason(ACCOUNT_ID, "") == "MANUAL_OTHER"
        assert await om._determine_exit_reason(ACCOUNT_ID, "O-NONE") == "MANUAL_OTHER"

    @pytest.mark.asyncio
    async def test_never_emits_amended_or_legacy(self, db, om):
        # T2.7 emits only *_PLANNED / MANUAL_OTHER; *_AMENDED is Phase-4,
        # and the legacy strings (tp_hit/sl_hit/manual/limit_close) are gone.
        results = set()
        for ot in ("take_profit", "stop_loss", "trailing_stop", "market", "limit"):
            await db._conn.execute("DELETE FROM orders WHERE exchange_order_id='O-X'")
            await db._conn.commit()
            await _seed_order_with_type(db, "O-X", ot)
            results.add(await om._determine_exit_reason(ACCOUNT_ID, "O-X"))
        assert results <= {"TP_PLANNED", "SL_PLANNED", "MANUAL_OTHER"}
        assert not (results & {"tp_hit", "sl_hit", "manual", "limit_close",
                               "trailing_stop", "TP_AMENDED", "SL_AMENDED"})

    @pytest.mark.asyncio
    async def test_exit_reason_enum_via_real_close_path(self, real):
        # The forward close row persists the §3.4 enum, not a legacy string.
        om, db = real
        await _seed_linked_order_and_calc(db, eoid="O-1", calc_id="calc-a")
        await db._conn.execute(
            "UPDATE pre_trade_log SET effective_entry=50000.0 WHERE calc_id='calc-a'")
        await db._conn.commit()
        await om._process_single_fill(
            ACCOUNT_ID, _fill("O-1", "POS-1", 5.0, fid="FO", price=50000.0, ts=1000))
        await db._conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
            " order_type, status, price, reduce_only) "
            "VALUES (1, 'O-TP', 'BTCUSDT', 'SELL', 'take_profit', 'new', 55000, 1)")
        await db._conn.commit()
        close = _fill("O-TP", "POS-1", 5.0, is_close=1, fid="FC", price=55000.0, ts=3000)
        await om._process_single_fill(ACCOUNT_ID, close)
        await om._build_close_row_for_fill(ACCOUNT_ID, close)
        cp = await _closed_pos(db, "POS-1")
        assert cp["exit_reason"] == "TP_PLANNED"   # not legacy "tp_hit"


# ── 13. P6.T4 — position:opened / scale_in / partial_close on the event_bus ──


def _drain_bus():
    from core.event_bus import event_bus
    out = []
    while not event_bus._queue.empty():
        out.append(event_bus._queue.get_nowait())
    return out


class TestPositionOpenedScaleInEvents:
    """P6.T4 (spec §9): _link_position_calc_on_open emits position:opened on a
    position's FIRST open (lifecycle mint) and position:scale_in when a calc
    NEW to the position contributes (lifecycle reuse) — the §9-correct
    position-level split (distinct from the per-calc position_opened trade event).
    """

    @pytest.mark.asyncio
    async def test_first_open_emits_position_opened(self, om, db):
        await _seed_calc(db, "C1")
        await _seed_order(db, "EO", calc_id="C1")
        _drain_bus()
        f = _fill("EO", "POS-1", 2.0, ts=1000, fid="F1", price=50000.0)
        f["direction"] = "LONG"
        await om._link_position_calc_on_open(ACCOUNT_ID, f)
        events = _drain_bus()
        opened = [(c, p) for c, p in events if c == "engine:account:1:position:opened"]
        assert len(opened) == 1, f"expected 1 position:opened, got {events!r}"
        _, p = opened[0]
        assert p["position_id"] == "POS-1"
        assert p["calc_ids"] == ["C1"]
        assert p["symbol"] == "BTCUSDT"
        assert p["direction"] == "LONG"
        assert p["entry_px"] == pytest.approx(50000.0)
        assert p["size"] == pytest.approx(2.0)
        assert not any(c.endswith(":position:scale_in") for c, _ in events)

    @pytest.mark.asyncio
    async def test_scale_in_emits_scale_in_not_opened(self, om, db):
        await _seed_calc(db, "C1")
        await _seed_calc(db, "C2")
        await _seed_order(db, "EO1", calc_id="C1")
        await _seed_order(db, "EO2", calc_id="C2")
        await om._link_position_calc_on_open(
            ACCOUNT_ID, _fill("EO1", "POS-1", 2.0, ts=1000, fid="F1"))
        _drain_bus()  # discard the position:opened from the first fill
        await om._link_position_calc_on_open(
            ACCOUNT_ID, _fill("EO2", "POS-1", 1.0, ts=2000, fid="F2"))
        events = _drain_bus()
        scale = [(c, p) for c, p in events if c == "engine:account:1:position:scale_in"]
        assert len(scale) == 1, f"expected 1 position:scale_in, got {events!r}"
        _, p = scale[0]
        assert p["new_calc_id"] == "C2"
        assert p["added_qty"] == pytest.approx(1.0)
        # A scale-in must NOT also re-emit position:opened.
        assert not any(c.endswith(":position:opened") for c, _ in events)

    @pytest.mark.asyncio
    async def test_same_calc_additional_fill_emits_neither(self, om, db):
        # Another fill of the SAME (position, calc) is neither an open nor a
        # scale-in — no lifecycle event (Rule 8: pins the membership check).
        await _seed_calc(db, "C1")
        await _seed_order(db, "EO1", calc_id="C1")
        await om._link_position_calc_on_open(
            ACCOUNT_ID, _fill("EO1", "POS-1", 2.0, ts=1000, fid="F1"))
        _drain_bus()
        await om._link_position_calc_on_open(
            ACCOUNT_ID, _fill("EO1", "POS-1", 1.0, ts=1500, fid="F2"))
        events = _drain_bus()
        assert not any(
            c.endswith(":position:opened") or c.endswith(":position:scale_in")
            for c, _ in events
        )

    @pytest.mark.asyncio
    async def test_opened_on_owning_account_topic(self, om, db):
        # P6 holistic-audit [9]: pin the per-account topic for a position:* emit
        # site with a NON-default account (7 != app_state's default 1) so a
        # wrong/transposed/hardcoded account_id at the emit can't coincide with 1.
        await _seed_calc(db, "C7", account_id=7)
        await _seed_order(db, "EO7", calc_id="C7", account_id=7)
        _drain_bus()
        f = _fill("EO7", "POS-7", 2.0, ts=1000, fid="F7", price=50000.0, account_id=7)
        f["direction"] = "LONG"
        await om._link_position_calc_on_open(7, f)
        topics = [c for c, _ in _drain_bus()]
        assert "engine:account:7:position:opened" in topics


class TestPartialCloseEvent:
    @pytest.mark.asyncio
    async def test_partial_close_emits_event(self, om, monkeypatch):
        # P6.T4 (spec §9 position:partial_close): _emit_fill_events emits it for
        # a reduce-only fill while the position still has remaining qty. Patch
        # log_trade_event so the sync trade-event sink can't touch the live DB;
        # the closing fill carries calc_id (skips the config.DB_PATH lookup).
        from core.state import app_state
        monkeypatch.setattr("core.trade_event_log.log_trade_event", lambda *a, **k: None)
        pos = _pos("POS-1")
        # DISTINCT from the fill qty so the two payload fields can't be confused:
        # remaining_qty (position size after the rung) = 3.0, qty_reduced (this
        # fill's size) = 1.0 — a source-expression swap would now FAIL.
        pos.contract_amount = 3.0   # remaining > 0 → partial, not final
        monkeypatch.setattr(app_state, "positions", [pos])
        _drain_bus()
        fill = _fill("XO", "POS-1", 1.0, is_close=1, fid="FX", price=52000.0)
        fill["calc_id"] = "C1"
        fill["realized_pnl"] = 40.0
        om._emit_fill_events(ACCOUNT_ID, fill)
        events = _drain_bus()
        pc = [(c, p) for c, p in events if c == "engine:account:1:position:partial_close"]
        assert len(pc) == 1, f"expected 1 position:partial_close, got {events!r}"
        _, p = pc[0]
        assert p["position_id"] == "POS-1"
        assert p["qty_reduced"] == pytest.approx(1.0)     # this fill's size
        assert p["remaining_qty"] == pytest.approx(3.0)   # position size after
        assert p["realized_pnl_partial"] == pytest.approx(40.0)


# ── 14. P6.T5 — order:duplicate_detected ──────────────────────────────────────


async def _seed_dup_order(db, eoid, *, symbol="BTCUSDT", side="BUY",
                          order_type="limit", price=50000.0, stop_price=0.0,
                          quantity=1.0, created_at_ms=1000, account_id=ACCOUNT_ID):
    cur = await db._conn.execute(
        "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
        " order_type, status, price, stop_price, quantity, created_at_ms) "
        "VALUES (?, ?, ?, ?, ?, 'new', ?, ?, ?, ?)",
        (account_id, eoid, symbol, side, order_type, price, stop_price,
         quantity, created_at_ms),
    )
    await db._conn.commit()
    return cur.lastrowid


def _arriving(eoid, *, symbol="BTCUSDT", side="BUY", order_type="limit",
              price=50000.0, stop_price=0.0, quantity=1.0, created_at_ms=1000):
    return {
        "account_id": ACCOUNT_ID, "exchange_order_id": eoid, "symbol": symbol,
        "side": side, "order_type": order_type, "price": price,
        "stop_price": stop_price, "quantity": quantity, "created_at_ms": created_at_ms,
    }


class TestDuplicateOrderDetection:
    """P6.T5 (spec §9 order:duplicate_detected): 2+ IDENTICAL-shape orders within
    DUP_WINDOW_MS → emit order_ids[] + dup_window_ms. New arrivals only."""

    @pytest.mark.asyncio
    async def test_two_identical_within_window_emit(self, om, db):
        id1 = await _seed_dup_order(db, "O-A", created_at_ms=1000)
        id2 = await _seed_dup_order(db, "O-B", created_at_ms=1500)  # +500ms
        _drain_bus()
        await om._detect_duplicate_orders(
            ACCOUNT_ID, _arriving("O-B", created_at_ms=1500), None)
        events = _drain_bus()
        dup = [(c, p) for c, p in events if c == "engine:account:1:order:duplicate_detected"]
        assert len(dup) == 1, f"expected 1 order:duplicate_detected, got {events!r}"
        _, p = dup[0]
        assert sorted(p["order_ids"]) == sorted([id1, id2])
        assert p["dup_window_ms"] == 2000

    @pytest.mark.asyncio
    async def test_single_order_no_emit(self, om, db):
        await _seed_dup_order(db, "O-A", created_at_ms=1000)
        _drain_bus()
        await om._detect_duplicate_orders(
            ACCOUNT_ID, _arriving("O-A", created_at_ms=1000), None)
        assert not any(c.endswith(":order:duplicate_detected") for c, _ in _drain_bus())

    @pytest.mark.asyncio
    async def test_different_price_no_emit(self, om, db):
        await _seed_dup_order(db, "O-A", price=50000.0, created_at_ms=1000)
        await _seed_dup_order(db, "O-B", price=50100.0, created_at_ms=1500)
        _drain_bus()
        await om._detect_duplicate_orders(
            ACCOUNT_ID, _arriving("O-B", price=50100.0, created_at_ms=1500), None)
        assert not any(c.endswith(":order:duplicate_detected") for c, _ in _drain_bus())

    @pytest.mark.asyncio
    async def test_different_stop_price_not_dup(self, om, db):
        # Multi-TP rungs: identical except the trigger (stop_price) — NOT dups.
        await _seed_dup_order(db, "O-A", order_type="take_profit", price=0.0,
                              stop_price=55000.0, created_at_ms=1000)
        await _seed_dup_order(db, "O-B", order_type="take_profit", price=0.0,
                              stop_price=56000.0, created_at_ms=1500)
        _drain_bus()
        await om._detect_duplicate_orders(
            ACCOUNT_ID, _arriving("O-B", order_type="take_profit", price=0.0,
                                  stop_price=56000.0, created_at_ms=1500), None)
        assert not any(c.endswith(":order:duplicate_detected") for c, _ in _drain_bus())

    @pytest.mark.asyncio
    async def test_outside_window_no_emit(self, om, db):
        await _seed_dup_order(db, "O-A", created_at_ms=1000)
        await _seed_dup_order(db, "O-B", created_at_ms=5000)  # +4s > 2s window
        _drain_bus()
        await om._detect_duplicate_orders(
            ACCOUNT_ID, _arriving("O-B", created_at_ms=5000), None)
        assert not any(c.endswith(":order:duplicate_detected") for c, _ in _drain_bus())

    @pytest.mark.asyncio
    async def test_update_of_existing_order_no_emit(self, om, db):
        # prev_order is not None → an UPDATE, not a new submission → skip.
        await _seed_dup_order(db, "O-A", created_at_ms=1000)
        await _seed_dup_order(db, "O-B", created_at_ms=1500)
        _drain_bus()
        await om._detect_duplicate_orders(
            ACCOUNT_ID, _arriving("O-B", created_at_ms=1500), {"status": "new"})
        assert not any(c.endswith(":order:duplicate_detected") for c, _ in _drain_bus())

    @pytest.mark.asyncio
    async def test_zero_created_at_skips(self, om, db):
        # No reliable arrival time (e.g. MEXC WS gap) → can't window → skip.
        await _seed_dup_order(db, "O-A", created_at_ms=0)
        await _seed_dup_order(db, "O-B", created_at_ms=0)
        _drain_bus()
        await om._detect_duplicate_orders(
            ACCOUNT_ID, _arriving("O-B", created_at_ms=0), None)
        assert not any(c.endswith(":order:duplicate_detected") for c, _ in _drain_bus())

    @pytest.mark.asyncio
    async def test_wired_into_process_order_update(self, real, monkeypatch):
        # Rule-8 wiring: two identical orders through the REAL process_order_update
        # path emit the event once (when the 2nd arrives). Patch log_trade_event so
        # _emit_order_events doesn't write the live per-account DB.
        monkeypatch.setattr("core.trade_event_log.log_trade_event", lambda *a, **k: None)
        om, db = real
        _drain_bus()
        await om.process_order_update(ACCOUNT_ID, _arriving("DUP-1", created_at_ms=1000))
        await om.process_order_update(ACCOUNT_ID, _arriving("DUP-2", created_at_ms=1200))
        events = _drain_bus()
        dup = [(c, p) for c, p in events if c == "engine:account:1:order:duplicate_detected"]
        assert len(dup) == 1, f"expected 1 (on the 2nd arrival), got {[c for c, _ in events]!r}"
        assert len(dup[0][1]["order_ids"]) == 2

    @pytest.mark.asyncio
    async def test_duplicate_detected_on_owning_account_topic(self, om, db):
        # P6 holistic-audit [9]: account scope for order:duplicate_detected with a
        # NON-default account (7) — the query + topic must both use the passed
        # account, not the default 1.
        await _seed_dup_order(db, "DA", created_at_ms=1000, account_id=7)
        await _seed_dup_order(db, "DB", created_at_ms=1500, account_id=7)
        _drain_bus()
        await om._detect_duplicate_orders(7, _arriving("DB", created_at_ms=1500), None)
        topics = [c for c, _ in _drain_bus()]
        assert "engine:account:7:order:duplicate_detected" in topics
