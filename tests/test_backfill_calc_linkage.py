"""
Phase 0 Task 5 (P0.T5) tests — calc-linkage backfill script.

End-to-end behavior against a tempfile DB covering:

  1. exit_reason re-map: each legacy value ('manual', 'tp', 'sl', NULL,
     '') → spec §3.4 enum; already-new-enum values left unchanged
  2. lifecycle_id generation: cp rows without lifecycle_id get a
     UUID; fills with matching tpid get the same UUID stamped
  3. positions_calcs junction backfill: fills grouped by
     (calc_id, exchange_order_id) → one junction row per group with
     summed contributed_qty; fills without calc_id skipped; fills
     whose order_id doesn't resolve skipped
  4. Dry-run reads + reports + writes nothing
  5. Idempotence: re-running --apply plans 0 work after first
  6. Scope: --account-id and --symbol filter correctly

Run: pytest tests/test_backfill_calc_linkage.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scripts.backfill_calc_linkage import run_backfill


@pytest_asyncio.fixture
async def db_path():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    await db.close()
    yield tmp.name
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


# ── Seed helpers ───────────────────────────────────────────────────────


async def _seed_cp(
    db_path: str, *,
    tpid: str, symbol: str = "BTCUSDT", direction: str = "LONG",
    exit_reason: str = "",   # NOT NULL DEFAULT '' on the column
    account_id: int = 1,
    entry_time_ms: int = 1000, exit_time_ms: int = 2000,
    entry_price: float = 80000.0, exit_price: float = 81000.0,
    quantity: float = 1.0, realized_pnl: float = 1000.0,
):
    from core.database import DatabaseManager
    db = DatabaseManager(path=db_path)
    await db.initialize()
    try:
        await db._conn.execute(
            "INSERT INTO closed_positions "
            "(account_id, terminal_position_id, symbol, direction, "
            " quantity, entry_price, exit_price, entry_time_ms, "
            " exit_time_ms, realized_pnl, source, exit_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, tpid, symbol, direction, quantity,
             entry_price, exit_price, entry_time_ms, exit_time_ms,
             realized_pnl, "test_seed", exit_reason),
        )
        await db._conn.commit()
        async with db._conn.execute(
            "SELECT id FROM closed_positions WHERE terminal_position_id = ?",
            (tpid,),
        ) as cur:
            row = await cur.fetchone()
        return int(row["id"])
    finally:
        await db.close()


async def _seed_order(
    db_path: str, *,
    exchange_order_id: str, symbol: str = "BTCUSDT",
    side: str = "BUY", quantity: float = 1.0,
    account_id: int = 1, calc_id: str = "",
):
    from core.database import DatabaseManager
    db = DatabaseManager(path=db_path)
    await db.initialize()
    try:
        await db._conn.execute(
            "INSERT INTO orders "
            "(account_id, exchange_order_id, symbol, side, order_type, "
            " status, quantity, created_at_ms, updated_at_ms, calc_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, exchange_order_id, symbol, side,
             "limit", "filled", quantity, 1000, 2000, calc_id),
        )
        await db._conn.commit()
        async with db._conn.execute(
            "SELECT id FROM orders WHERE exchange_order_id = ?",
            (exchange_order_id,),
        ) as cur:
            row = await cur.fetchone()
        return int(row["id"])
    finally:
        await db.close()


async def _seed_fill(
    db_path: str, *,
    exchange_fill_id: str, tpid: str,
    calc_id: str = None,
    exchange_order_id: str = "",
    quantity: float = 1.0, account_id: int = 1,
    timestamp_ms: int = 1500, is_close: int = 0,
    symbol: str = "BTCUSDT", direction: str = "LONG",
    side: str = "BUY", price: float = 80000.0,
):
    from core.database import DatabaseManager
    db = DatabaseManager(path=db_path)
    await db.initialize()
    try:
        await db._conn.execute(
            "INSERT INTO fills "
            "(account_id, exchange_fill_id, exchange_order_id, symbol, "
            " side, direction, price, quantity, is_close, "
            " terminal_position_id, calc_id, timestamp_ms, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, exchange_fill_id, exchange_order_id, symbol,
             side, direction, price, quantity, is_close,
             tpid, calc_id, timestamp_ms, "test_seed"),
        )
        await db._conn.commit()
    finally:
        await db.close()


async def _read_cp(db_path, cp_id):
    from core.database import DatabaseManager
    db = DatabaseManager(path=db_path)
    await db.initialize()
    try:
        async with db._conn.execute(
            "SELECT * FROM closed_positions WHERE id = ?", (cp_id,),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def _read_junction(db_path, cp_id):
    from core.database import DatabaseManager
    db = DatabaseManager(path=db_path)
    await db.initialize()
    try:
        async with db._conn.execute(
            "SELECT * FROM positions_calcs WHERE position_id = ? "
            "ORDER BY id ASC", (cp_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


# ── 1. exit_reason re-map ──────────────────────────────────────────────


class TestExitReasonRemap:
    @pytest.mark.parametrize("legacy, expected", [
        ("manual", "MANUAL_OTHER"),
        ("tp",     "TP_PLANNED"),
        ("sl",     "SL_PLANNED"),
        ("",       "MANUAL_OTHER"),
        # NULL is in EXIT_REASON_REMAP defensively but unreachable in
        # practice — closed_positions.exit_reason is NOT NULL DEFAULT
        # ''. Task 76 idempotent migration also patches any pre-existing
        # NULLs to 'manual' on startup.
    ])
    @pytest.mark.asyncio
    async def test_each_legacy_value_remaps(self, db_path, legacy, expected):
        cp_id = await _seed_cp(db_path, tpid="tpid-A", exit_reason=legacy)
        result = await run_backfill(db_path=db_path, apply=True, verbose=False)
        assert result["exit_remap_planned"] == 1
        assert result["exit_remap_applied"] == 1
        cp = await _read_cp(db_path, cp_id)
        assert cp["exit_reason"] == expected

    @pytest.mark.asyncio
    async def test_new_enum_value_unchanged(self, db_path):
        # Already-migrated value should NOT be re-mapped.
        cp_id = await _seed_cp(db_path, tpid="tpid-B", exit_reason="TP_AMENDED")
        result = await run_backfill(db_path=db_path, apply=True, verbose=False)
        assert result["exit_remap_planned"] == 0
        cp = await _read_cp(db_path, cp_id)
        assert cp["exit_reason"] == "TP_AMENDED"

    @pytest.mark.asyncio
    async def test_dry_run_does_not_write(self, db_path):
        cp_id = await _seed_cp(db_path, tpid="tpid-C", exit_reason="manual")
        await run_backfill(db_path=db_path, apply=False, verbose=False)
        cp = await _read_cp(db_path, cp_id)
        assert cp["exit_reason"] == "manual"   # unchanged


# ── 2. lifecycle_id generation + stamping ──────────────────────────────


class TestLifecycleGeneration:
    @pytest.mark.asyncio
    async def test_cp_without_lifecycle_gets_uuid(self, db_path):
        cp_id = await _seed_cp(db_path, tpid="tpid-life-1")
        result = await run_backfill(db_path=db_path, apply=True, verbose=False)
        assert result["lifecycle_gen_planned"] == 1
        assert result["lifecycle_gen_applied"] == 1
        cp = await _read_cp(db_path, cp_id)
        assert cp["lifecycle_id"] is not None
        # UUID v4 format: 8-4-4-4-12 hex chars.
        assert len(cp["lifecycle_id"]) == 36
        assert cp["lifecycle_id"].count("-") == 4

    @pytest.mark.asyncio
    async def test_fills_stamped_with_same_uuid(self, db_path):
        cp_id = await _seed_cp(db_path, tpid="tpid-life-2")
        await _seed_fill(db_path, exchange_fill_id="f1", tpid="tpid-life-2")
        await _seed_fill(db_path, exchange_fill_id="f2", tpid="tpid-life-2")
        result = await run_backfill(db_path=db_path, apply=True, verbose=False)
        assert result["fill_stamps_planned"] == 2
        assert result["fill_stamps_applied"] == 2

        cp = await _read_cp(db_path, cp_id)
        from core.database import DatabaseManager
        db = DatabaseManager(path=db_path)
        await db.initialize()
        try:
            async with db._conn.execute(
                "SELECT lifecycle_id FROM fills WHERE terminal_position_id = ?",
                ("tpid-life-2",),
            ) as cur:
                fill_uuids = {row["lifecycle_id"] for row in await cur.fetchall()}
        finally:
            await db.close()
        assert fill_uuids == {cp["lifecycle_id"]}

    @pytest.mark.asyncio
    async def test_cp_with_existing_lifecycle_not_regenerated(self, db_path):
        cp_id = await _seed_cp(db_path, tpid="tpid-life-3")
        from core.database import DatabaseManager
        db = DatabaseManager(path=db_path)
        await db.initialize()
        try:
            await db._conn.execute(
                "UPDATE closed_positions SET lifecycle_id = ? WHERE id = ?",
                ("pre-existing-uuid", cp_id),
            )
            await db._conn.commit()
        finally:
            await db.close()

        result = await run_backfill(db_path=db_path, apply=True, verbose=False)
        assert result["lifecycle_gen_planned"] == 0
        cp = await _read_cp(db_path, cp_id)
        assert cp["lifecycle_id"] == "pre-existing-uuid"   # untouched


# ── 3. positions_calcs junction backfill ───────────────────────────────


class TestJunctionBackfill:
    @pytest.mark.asyncio
    async def test_single_calc_single_order_one_junction_row(self, db_path):
        cp_id = await _seed_cp(db_path, tpid="tpid-J1")
        order_id = await _seed_order(
            db_path, exchange_order_id="ord-1", calc_id="calc-a",
        )
        await _seed_fill(
            db_path, exchange_fill_id="f1", tpid="tpid-J1",
            calc_id="calc-a", exchange_order_id="ord-1", quantity=0.5,
        )
        await _seed_fill(
            db_path, exchange_fill_id="f2", tpid="tpid-J1",
            calc_id="calc-a", exchange_order_id="ord-1", quantity=0.5,
        )

        result = await run_backfill(db_path=db_path, apply=True, verbose=False)
        assert result["junction_rows_planned"] == 1
        assert result["junction_rows_applied"] == 1

        rows = await _read_junction(db_path, cp_id)
        assert len(rows) == 1
        assert rows[0]["calc_id"] == "calc-a"
        assert rows[0]["order_id"] == order_id
        assert rows[0]["contributed_qty"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_scale_in_two_calcs_two_junction_rows(self, db_path):
        cp_id = await _seed_cp(db_path, tpid="tpid-J2")
        o1 = await _seed_order(db_path, exchange_order_id="ord-A", calc_id="calc-a")
        o2 = await _seed_order(db_path, exchange_order_id="ord-B", calc_id="calc-b")
        await _seed_fill(
            db_path, exchange_fill_id="f1", tpid="tpid-J2",
            calc_id="calc-a", exchange_order_id="ord-A", quantity=0.3,
        )
        await _seed_fill(
            db_path, exchange_fill_id="f2", tpid="tpid-J2",
            calc_id="calc-b", exchange_order_id="ord-B", quantity=0.7,
        )
        result = await run_backfill(db_path=db_path, apply=True, verbose=False)
        assert result["junction_rows_applied"] == 2

        rows = await _read_junction(db_path, cp_id)
        assert len(rows) == 2
        by_calc = {r["calc_id"]: r for r in rows}
        assert by_calc["calc-a"]["order_id"] == o1
        assert by_calc["calc-a"]["contributed_qty"] == pytest.approx(0.3)
        assert by_calc["calc-b"]["order_id"] == o2
        assert by_calc["calc-b"]["contributed_qty"] == pytest.approx(0.7)
        # Same lifecycle_id stamped on both.
        assert by_calc["calc-a"]["lifecycle_id"] == by_calc["calc-b"]["lifecycle_id"]
        assert by_calc["calc-a"]["lifecycle_id"] is not None

    @pytest.mark.asyncio
    async def test_fill_without_calc_id_skipped(self, db_path):
        await _seed_cp(db_path, tpid="tpid-J3")
        await _seed_order(db_path, exchange_order_id="ord-x", calc_id="calc-x")
        await _seed_fill(
            db_path, exchange_fill_id="f-orphan", tpid="tpid-J3",
            calc_id=None,   # no calc_id — skipped
            exchange_order_id="ord-x", quantity=1.0,
        )
        result = await run_backfill(db_path=db_path, apply=True, verbose=False)
        assert result["junction_rows_planned"] == 0
        assert result["junction_skip_no_calc"] >= 1

    @pytest.mark.asyncio
    async def test_fill_with_unresolvable_order_skipped(self, db_path):
        await _seed_cp(db_path, tpid="tpid-J4")
        # No seed_order for "ord-missing" — fill should be skipped.
        await _seed_fill(
            db_path, exchange_fill_id="f1", tpid="tpid-J4",
            calc_id="calc-a", exchange_order_id="ord-missing",
            quantity=1.0,
        )
        result = await run_backfill(db_path=db_path, apply=True, verbose=False)
        assert result["junction_rows_planned"] == 0
        assert result["junction_skip_no_order"] >= 1

    @pytest.mark.asyncio
    async def test_already_populated_position_skipped(self, db_path):
        # First run populates; second run skips because junction has rows.
        cp_id = await _seed_cp(db_path, tpid="tpid-J5")
        await _seed_order(db_path, exchange_order_id="ord-y", calc_id="calc-y")
        await _seed_fill(
            db_path, exchange_fill_id="f1", tpid="tpid-J5",
            calc_id="calc-y", exchange_order_id="ord-y", quantity=1.0,
        )
        r1 = await run_backfill(db_path=db_path, apply=True, verbose=False)
        assert r1["junction_rows_applied"] == 1
        r2 = await run_backfill(db_path=db_path, apply=False, verbose=False)
        assert r2["junction_rows_planned"] == 0
        assert r2["junction_skip_already_populated"] >= 1


# ── 4. Dry-run + idempotence ──────────────────────────────────────────


class TestDryRunAndIdempotence:
    @pytest.mark.asyncio
    async def test_dry_run_makes_no_writes(self, db_path):
        cp_id = await _seed_cp(db_path, tpid="tpid-DR", exit_reason="manual")
        await _seed_order(db_path, exchange_order_id="ord-1", calc_id="c1")
        await _seed_fill(
            db_path, exchange_fill_id="f1", tpid="tpid-DR",
            calc_id="c1", exchange_order_id="ord-1", quantity=1.0,
        )
        await run_backfill(db_path=db_path, apply=False, verbose=False)
        cp = await _read_cp(db_path, cp_id)
        # Unchanged because dry-run.
        assert cp["exit_reason"] == "manual"
        assert cp["lifecycle_id"] is None
        rows = await _read_junction(db_path, cp_id)
        assert rows == []

    @pytest.mark.asyncio
    async def test_re_apply_is_noop(self, db_path):
        # All three operations should plan 0 work on second --apply.
        cp_id = await _seed_cp(db_path, tpid="tpid-IDEMP", exit_reason="manual")
        await _seed_order(db_path, exchange_order_id="ord-i", calc_id="c1")
        await _seed_fill(
            db_path, exchange_fill_id="f1", tpid="tpid-IDEMP",
            calc_id="c1", exchange_order_id="ord-i", quantity=1.0,
        )
        await run_backfill(db_path=db_path, apply=True, verbose=False)
        r2 = await run_backfill(db_path=db_path, apply=False, verbose=False)
        assert r2["exit_remap_planned"] == 0
        assert r2["lifecycle_gen_planned"] == 0
        assert r2["fill_stamps_planned"] == 0
        assert r2["junction_rows_planned"] == 0


# ── 5b. T207 audit follow-up: pre_trade_log + orders lifecycle stamps ──


async def _seed_pretrade(
    db_path: str, *,
    calc_id: str, account_id: int = 1, ticker: str = "BTCUSDT",
):
    """Seed a pre_trade_log row that the backfill can chain via calc_id."""
    from core.database import DatabaseManager
    db = DatabaseManager(path=db_path)
    await db.initialize()
    try:
        await db._conn.execute(
            "INSERT INTO pre_trade_log "
            "(timestamp, ticker, account_id, calc_id) VALUES (?, ?, ?, ?)",
            ("2026-05-26T12:00:00Z", ticker, account_id, calc_id),
        )
        await db._conn.commit()
        async with db._conn.execute(
            "SELECT id FROM pre_trade_log WHERE calc_id = ?", (calc_id,),
        ) as cur:
            return int((await cur.fetchone())["id"])
    finally:
        await db.close()


class TestPretradeLifecycleStamp:
    @pytest.mark.asyncio
    async def test_pretrade_stamped_with_cp_lifecycle(self, db_path):
        # Setup: cp with fills carrying calc_id; pre_trade_log row
        # with same calc_id should receive the cp's lifecycle_id.
        cp_id = await _seed_cp(db_path, tpid="tpid-PT1")
        ptl_id = await _seed_pretrade(db_path, calc_id="calc-pt-1")
        await _seed_order(
            db_path, exchange_order_id="ord-pt", calc_id="calc-pt-1",
        )
        await _seed_fill(
            db_path, exchange_fill_id="f-pt", tpid="tpid-PT1",
            calc_id="calc-pt-1", exchange_order_id="ord-pt", quantity=1.0,
        )
        result = await run_backfill(db_path=db_path, apply=True, verbose=False)
        assert result["pretrade_stamps_planned"] == 1
        assert result["pretrade_stamps_applied"] == 1

        from core.database import DatabaseManager
        db = DatabaseManager(path=db_path)
        await db.initialize()
        try:
            async with db._conn.execute(
                "SELECT lifecycle_id FROM pre_trade_log WHERE id = ?",
                (ptl_id,),
            ) as cur:
                ptl_lifecycle = (await cur.fetchone())["lifecycle_id"]
            cp = await _read_cp(db_path, cp_id)
        finally:
            await db.close()
        assert ptl_lifecycle is not None
        assert ptl_lifecycle == cp["lifecycle_id"]

    @pytest.mark.asyncio
    async def test_pretrade_without_fill_chain_unaffected(self, db_path):
        # pre_trade_log row exists but no fill references its calc_id.
        # Should NOT be stamped.
        await _seed_pretrade(db_path, calc_id="calc-orphan")
        result = await run_backfill(db_path=db_path, apply=True, verbose=False)
        assert result["pretrade_stamps_planned"] == 0


class TestOrderLifecycleStamp:
    @pytest.mark.asyncio
    async def test_order_stamped_with_cp_lifecycle(self, db_path):
        # Setup: cp with fills carrying exchange_order_id; orders row
        # with same exchange_order_id should receive the cp's lifecycle.
        cp_id = await _seed_cp(db_path, tpid="tpid-O1")
        order_id = await _seed_order(
            db_path, exchange_order_id="ord-stamp",
        )
        await _seed_fill(
            db_path, exchange_fill_id="f-stamp", tpid="tpid-O1",
            exchange_order_id="ord-stamp", quantity=1.0,
            # Note: NO calc_id on fill — order_stamp path works
            # independently of the junction backfill path.
        )
        result = await run_backfill(db_path=db_path, apply=True, verbose=False)
        assert result["order_stamps_planned"] == 1
        assert result["order_stamps_applied"] == 1

        from core.database import DatabaseManager
        db = DatabaseManager(path=db_path)
        await db.initialize()
        try:
            async with db._conn.execute(
                "SELECT lifecycle_id FROM orders WHERE id = ?",
                (order_id,),
            ) as cur:
                order_lifecycle = (await cur.fetchone())["lifecycle_id"]
            cp = await _read_cp(db_path, cp_id)
        finally:
            await db.close()
        assert order_lifecycle is not None
        assert order_lifecycle == cp["lifecycle_id"]

    @pytest.mark.asyncio
    async def test_order_with_existing_lifecycle_not_overwritten(self, db_path):
        cp_id = await _seed_cp(db_path, tpid="tpid-O2")
        order_id = await _seed_order(
            db_path, exchange_order_id="ord-existing",
        )
        await _seed_fill(
            db_path, exchange_fill_id="f-x", tpid="tpid-O2",
            exchange_order_id="ord-existing", quantity=1.0,
        )
        # Pre-stamp the order with a different lifecycle_id (simulates
        # Phase 2.1 having already written it). Backfill should leave
        # the existing value untouched.
        from core.database import DatabaseManager
        db = DatabaseManager(path=db_path)
        await db.initialize()
        try:
            await db._conn.execute(
                "UPDATE orders SET lifecycle_id = ? WHERE id = ?",
                ("pre-existing-lifecycle", order_id),
            )
            await db._conn.commit()
        finally:
            await db.close()

        result = await run_backfill(db_path=db_path, apply=True, verbose=False)
        # Plan should exclude this order (WHERE lifecycle_id IS NULL
        # in the SELECT).
        assert result["order_stamps_planned"] == 0

        db = DatabaseManager(path=db_path)
        await db.initialize()
        try:
            async with db._conn.execute(
                "SELECT lifecycle_id FROM orders WHERE id = ?",
                (order_id,),
            ) as cur:
                still = (await cur.fetchone())["lifecycle_id"]
        finally:
            await db.close()
        assert still == "pre-existing-lifecycle"


class TestUnmappedExitReasonWarning:
    @pytest.mark.asyncio
    async def test_unmapped_value_surfaced_not_remapped(self, db_path):
        # A legacy value that's NOT in EXIT_REASON_REMAP and NOT in
        # the spec enum should be surfaced as "unmapped" and left
        # untouched by --apply.
        cp_id = await _seed_cp(db_path, tpid="tpid-UM", exit_reason="forced")
        result = await run_backfill(db_path=db_path, apply=True, verbose=False)
        assert result["unmapped_exit_reasons"] == 1
        assert result["exit_remap_planned"] == 0
        cp = await _read_cp(db_path, cp_id)
        assert cp["exit_reason"] == "forced"   # unchanged

    @pytest.mark.asyncio
    async def test_known_new_enum_not_flagged_as_unmapped(self, db_path):
        # Spec-enum values that already exist on the row should NOT
        # surface as unmapped warnings.
        await _seed_cp(db_path, tpid="tpid-UM2", exit_reason="LIQUIDATION")
        result = await run_backfill(db_path=db_path, apply=True, verbose=False)
        assert result["unmapped_exit_reasons"] == 0


# ── 6. Scope filters ──────────────────────────────────────────────────


class TestScopeFilters:
    @pytest.mark.asyncio
    async def test_symbol_filter(self, db_path):
        await _seed_cp(db_path, tpid="tpid-BTC", symbol="BTCUSDT", exit_reason="manual")
        await _seed_cp(db_path, tpid="tpid-ETH", symbol="ETHUSDT", exit_reason="manual")
        result = await run_backfill(
            db_path=db_path, apply=True, symbol="BTCUSDT", verbose=False,
        )
        assert result["cps_in_scope"] == 1
        assert result["exit_remap_applied"] == 1

    @pytest.mark.asyncio
    async def test_account_id_filter(self, db_path):
        await _seed_cp(db_path, tpid="tpid-A1", account_id=1, exit_reason="manual")
        await _seed_cp(db_path, tpid="tpid-A2", account_id=2, exit_reason="manual")
        result = await run_backfill(
            db_path=db_path, apply=True, account_id=1, verbose=False,
        )
        assert result["cps_in_scope"] == 1
        assert result["exit_remap_applied"] == 1
