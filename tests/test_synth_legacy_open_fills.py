"""
Phase 0.0.7 (T197) tests for ``scripts/synth_legacy_open_fills.py``.

End-to-end behavior against a tempfile DB covering:

  1. Dry-run reads + reports + returns counts; NO writes.
  2. Apply UPSERTs synth OPEN fills + replaces matching orphan
     closed_positions with rebuilt_from_fills rows.
  3. Partial-coverage preservation: orphan rows whose upstream RPNL
     is missing or unusable stay PRESERVED (not wiped).
  4. Zero-data-symbol case: an orphan symbol with no exchange_history
     RPNL at all stays fully preserved.
  5. Idempotent — running --apply twice produces the same final state.
  6. Multi-RPNL same-(symbol, direction, open_time) groups collapse
     into a single synth OPEN with summed qty.
  7. Scope filtering (--symbol) is respected.

Run: pytest tests/test_synth_legacy_open_fills.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scripts.synth_legacy_open_fills import run_synth


BASE_MS = 1778025600000   # 2026-05-01 UTC


@pytest_asyncio.fixture
async def db_path():
    """Tempfile DB initialized with the project schema."""
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


async def _seed_orphan(
    db_path: str, *,
    symbol: str,
    direction: str,
    entry_time_ms: int,
    exit_time_ms: int,
    entry_price: float,
    exit_price: float,
    quantity: float,
    realized_pnl: float = 0.0,
    account_id: int = 1,
):
    """Seed a legacy orphan closed_positions row (bf: tpid)."""
    from core.database import DatabaseManager
    db = DatabaseManager(path=db_path)
    await db.initialize()
    try:
        await db.insert_closed_position({
            "account_id":           account_id,
            "terminal_position_id": f"bf:{symbol}:{direction}:{entry_time_ms}",
            "symbol":               symbol,
            "direction":            direction,
            "quantity":             quantity,
            "entry_price":          entry_price,
            "exit_price":           exit_price,
            "entry_time_ms":        entry_time_ms,
            "exit_time_ms":         exit_time_ms,
            "realized_pnl":         realized_pnl,
            "source":               "exchange_history_backfill",
            "backfill_completed":   1,
            "mfe":                  0.5,
            "mae":                  -0.3,
        })
    finally:
        await db.close()


async def _seed_rpnl(
    db_path: str, *,
    trade_key: str,
    symbol: str,
    direction: str,
    entry_price: float,
    exit_price: float,
    qty: float,
    open_time: int,
    time: int,
    income: float = 0.0,
    account_id: int = 1,
):
    """Seed an exchange_history REALIZED_PNL row."""
    from core.database import DatabaseManager
    db = DatabaseManager(path=db_path)
    await db.initialize()
    try:
        await db.upsert_exchange_history(
            [{
                "trade_key":  trade_key,
                "time":       time,
                "symbol":     symbol,
                "incomeType": "REALIZED_PNL",
                "income":     income,
                "direction":  direction,
                "entry_price": entry_price,
                "exit_price":  exit_price,
                "qty":         qty,
                "notional":    entry_price * qty,
                "open_time":   open_time,
                "fee":         0.0,
                "asset":       "USDT",
            }],
            account_id=account_id,
        )
    finally:
        await db.close()


async def _seed_close_fill(
    db_path: str, *,
    exchange_fill_id: str,
    symbol: str,
    direction: str,
    quantity: float,
    price: float,
    timestamp_ms: int,
    realized_pnl: float = 0.0,
    account_id: int = 1,
):
    """Seed a CLOSE fill (the existing exchange_history_backfill
    artifact for orphan symbols)."""
    from core.database import DatabaseManager
    db = DatabaseManager(path=db_path)
    await db.initialize()
    try:
        await db.upsert_fill({
            "account_id":           account_id,
            "exchange_fill_id":     exchange_fill_id,
            "symbol":               symbol,
            "side":                 "SELL" if direction == "LONG" else "BUY",
            "direction":            direction,
            "price":                price,
            "quantity":             quantity,
            "is_close":             1,
            "realized_pnl":         realized_pnl,
            "timestamp_ms":         timestamp_ms,
            "source":               "exchange_history_backfill",
        })
    finally:
        await db.close()


async def _all_closed(db_path: str, account_id: int = 1):
    from core.database import DatabaseManager
    db = DatabaseManager(path=db_path)
    await db.initialize()
    try:
        async with db._conn.execute(
            "SELECT * FROM closed_positions WHERE account_id=? "
            "ORDER BY symbol, direction, entry_time_ms",
            (account_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def _all_fills(db_path: str, account_id: int = 1):
    from core.database import DatabaseManager
    db = DatabaseManager(path=db_path)
    await db.initialize()
    try:
        async with db._conn.execute(
            "SELECT * FROM fills WHERE account_id=? "
            "ORDER BY symbol, timestamp_ms, id",
            (account_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


# ── 1. Dry-run reads but writes nothing ────────────────────────────────


class TestDryRunReadsOnly:
    @pytest.mark.asyncio
    async def test_dry_run_makes_no_writes(self, db_path):
        await _seed_orphan(
            db_path, symbol="SIRENUSDT", direction="LONG",
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
            entry_price=0.76, exit_price=0.77, quantity=10.0,
        )
        await _seed_rpnl(
            db_path, trade_key="rpnl-1", symbol="SIRENUSDT",
            direction="LONG", entry_price=0.76, exit_price=0.77,
            qty=10.0, open_time=BASE_MS, time=BASE_MS + 60_000,
            income=0.10,
        )
        await _seed_close_fill(
            db_path, exchange_fill_id="close-1",
            symbol="SIRENUSDT", direction="LONG", quantity=10.0,
            price=0.77, timestamp_ms=BASE_MS + 60_000,
            realized_pnl=0.10,
        )

        before_closed = await _all_closed(db_path)
        before_fills = await _all_fills(db_path)

        result = await run_synth(db_path=db_path, apply=False, verbose=False)

        after_closed = await _all_closed(db_path)
        after_fills = await _all_fills(db_path)

        assert result["applied"] is False
        assert result["orphans_in_scope"] == 1
        assert result["recoverable"] == 1
        assert result["preserved"] == 0
        assert result["synth_opens_planned"] == 1
        assert before_closed == after_closed
        assert before_fills == after_fills


# ── 2. Apply inserts synth OPEN + rebuilds matching orphan ─────────────


class TestApplyRebuildsRecoverableOrphan:
    @pytest.mark.asyncio
    async def test_apply_replaces_orphan_with_rebuilt(self, db_path):
        await _seed_orphan(
            db_path, symbol="SIRENUSDT", direction="LONG",
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
            entry_price=0.76, exit_price=0.77, quantity=10.0,
            realized_pnl=0.10,
        )
        await _seed_rpnl(
            db_path, trade_key="rpnl-1", symbol="SIRENUSDT",
            direction="LONG", entry_price=0.76, exit_price=0.77,
            qty=10.0, open_time=BASE_MS, time=BASE_MS + 60_000,
            income=0.10,
        )
        await _seed_close_fill(
            db_path, exchange_fill_id="close-1",
            symbol="SIRENUSDT", direction="LONG", quantity=10.0,
            price=0.77, timestamp_ms=BASE_MS + 60_000,
            realized_pnl=0.10,
        )

        result = await run_synth(db_path=db_path, apply=True, verbose=False)

        assert result["applied"] is True
        assert result["fills_synthed"] == 1
        assert result["orphans_deleted"] == 1
        assert result["positions_rebuilt"] == 1

        closed = await _all_closed(db_path)
        assert len(closed) == 1
        r = closed[0]
        assert r["terminal_position_id"] == f"rebuilt:SIRENUSDT:LONG:{BASE_MS}"
        assert r["source"] == "rebuilt_from_fills"
        # Reconciler picks up backfill_completed=0 → re-runs MFE/MAE.
        assert r["backfill_completed"] == 0
        assert r["entry_price"] == pytest.approx(0.76)
        assert r["exit_price"] == pytest.approx(0.77)
        assert r["quantity"] == pytest.approx(10.0)

        fills = await _all_fills(db_path)
        # 1 synth OPEN + 1 existing CLOSE.
        assert len(fills) == 2
        opens = [f for f in fills if not f["is_close"]]
        assert len(opens) == 1
        assert opens[0]["exchange_fill_id"] == "synth_open:rpnl-1"
        assert opens[0]["source"] == "synth_legacy_open"
        assert opens[0]["price"] == pytest.approx(0.76)
        assert opens[0]["quantity"] == pytest.approx(10.0)
        assert opens[0]["timestamp_ms"] == BASE_MS


# ── 3. Partial coverage: unrecoverable orphans preserved ───────────────


class TestPartialCoveragePreservesUnrecoverable:
    @pytest.mark.asyncio
    async def test_recoverable_rebuilt_and_unrecoverable_preserved(self, db_path):
        # Two SIRENUSDT orphans. Only one has matching RPNL.
        await _seed_orphan(
            db_path, symbol="SIRENUSDT", direction="LONG",
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
            entry_price=0.76, exit_price=0.77, quantity=10.0,
        )
        await _seed_orphan(
            db_path, symbol="SIRENUSDT", direction="SHORT",
            entry_time_ms=BASE_MS + 100_000,
            exit_time_ms=BASE_MS + 200_000,
            entry_price=0.80, exit_price=0.79, quantity=5.0,
        )
        # Only the LONG one has upstream RPNL.
        await _seed_rpnl(
            db_path, trade_key="rpnl-1", symbol="SIRENUSDT",
            direction="LONG", entry_price=0.76, exit_price=0.77,
            qty=10.0, open_time=BASE_MS, time=BASE_MS + 60_000,
        )
        await _seed_close_fill(
            db_path, exchange_fill_id="close-1",
            symbol="SIRENUSDT", direction="LONG", quantity=10.0,
            price=0.77, timestamp_ms=BASE_MS + 60_000,
        )

        result = await run_synth(db_path=db_path, apply=True, verbose=False)

        assert result["recoverable"] == 1
        assert result["preserved"] == 1
        assert result["fills_synthed"] == 1
        assert result["orphans_deleted"] == 1
        assert result["positions_rebuilt"] == 1

        closed = await _all_closed(db_path)
        # LONG: rebuilt. SHORT: preserved as orphan.
        assert len(closed) == 2
        longs = [r for r in closed if r["direction"] == "LONG"]
        shorts = [r for r in closed if r["direction"] == "SHORT"]
        assert len(longs) == 1
        assert longs[0]["source"] == "rebuilt_from_fills"
        assert longs[0]["terminal_position_id"].startswith("rebuilt:")
        assert len(shorts) == 1
        assert shorts[0]["source"] == "exchange_history_backfill"
        assert shorts[0]["terminal_position_id"].startswith("bf:")


# ── 4. Zero-data symbol: fully preserved ───────────────────────────────


class TestZeroDataSymbolFullyPreserved:
    @pytest.mark.asyncio
    async def test_no_rpnl_means_orphan_untouched(self, db_path):
        await _seed_orphan(
            db_path, symbol="TRUMPUSDT", direction="SHORT",
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
            entry_price=3.78, exit_price=3.77, quantity=350.0,
        )
        # No RPNL row seeded — symbol fully unrecoverable.

        before = await _all_closed(db_path)
        result = await run_synth(db_path=db_path, apply=True, verbose=False)
        after = await _all_closed(db_path)

        assert result["recoverable"] == 0
        assert result["preserved"] == 1
        assert result["fills_synthed"] == 0
        assert result["orphans_deleted"] == 0
        assert before == after


# ── 5. Idempotence ─────────────────────────────────────────────────────


class TestIdempotence:
    @pytest.mark.asyncio
    async def test_apply_twice_no_further_change(self, db_path):
        await _seed_orphan(
            db_path, symbol="SIRENUSDT", direction="LONG",
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
            entry_price=0.76, exit_price=0.77, quantity=10.0,
        )
        await _seed_rpnl(
            db_path, trade_key="rpnl-1", symbol="SIRENUSDT",
            direction="LONG", entry_price=0.76, exit_price=0.77,
            qty=10.0, open_time=BASE_MS, time=BASE_MS + 60_000,
        )
        await _seed_close_fill(
            db_path, exchange_fill_id="close-1",
            symbol="SIRENUSDT", direction="LONG", quantity=10.0,
            price=0.77, timestamp_ms=BASE_MS + 60_000,
        )

        await run_synth(db_path=db_path, apply=True, verbose=False)
        after_1 = await _all_closed(db_path)
        fills_1 = await _all_fills(db_path)

        # 2nd apply: orphans_in_scope=0 (all bf: rows gone after 1st run),
        # nothing to do.
        result = await run_synth(db_path=db_path, apply=True, verbose=False)
        after_2 = await _all_closed(db_path)
        fills_2 = await _all_fills(db_path)

        assert result["orphans_in_scope"] == 0
        # Strip ids — auto-increment may shift.
        def _strip(r):
            return {k: v for k, v in r.items() if k != "id"}
        assert [_strip(r) for r in after_1] == [_strip(r) for r in after_2]
        assert [_strip(f) for f in fills_1] == [_strip(f) for f in fills_2]


# ── 6. Multi-RPNL same-(symbol, direction, open_time) groups ───────────


class TestMultiRpnlGrouping:
    @pytest.mark.asyncio
    async def test_two_rpnls_same_open_time_collapse_to_one_synth_open(self, db_path):
        # One logical SHORT position closed via two RPNL events at the
        # same open_time (multi-fill partial-close storm).
        await _seed_orphan(
            db_path, symbol="ONUSDT", direction="SHORT",
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
            entry_price=0.50, exit_price=0.49, quantity=20.0,
        )
        await _seed_rpnl(
            db_path, trade_key="rpnl-1a", symbol="ONUSDT",
            direction="SHORT", entry_price=0.50, exit_price=0.49,
            qty=12.0, open_time=BASE_MS, time=BASE_MS + 50_000,
        )
        await _seed_rpnl(
            db_path, trade_key="rpnl-1b", symbol="ONUSDT",
            direction="SHORT", entry_price=0.50, exit_price=0.49,
            qty=8.0, open_time=BASE_MS, time=BASE_MS + 60_000,
        )
        # Two CLOSE fills already exist for both RPNL events.
        await _seed_close_fill(
            db_path, exchange_fill_id="close-1a",
            symbol="ONUSDT", direction="SHORT", quantity=12.0,
            price=0.49, timestamp_ms=BASE_MS + 50_000,
        )
        await _seed_close_fill(
            db_path, exchange_fill_id="close-1b",
            symbol="ONUSDT", direction="SHORT", quantity=8.0,
            price=0.49, timestamp_ms=BASE_MS + 60_000,
        )

        result = await run_synth(db_path=db_path, apply=True, verbose=False)

        assert result["fills_synthed"] == 1   # one synth OPEN, not two
        assert result["positions_rebuilt"] == 1
        assert result["orphans_deleted"] == 1

        fills = await _all_fills(db_path)
        opens = [f for f in fills if not f["is_close"]]
        assert len(opens) == 1
        # Summed qty from both RPNL events.
        assert opens[0]["quantity"] == pytest.approx(20.0)
        assert opens[0]["price"] == pytest.approx(0.50)
        assert opens[0]["timestamp_ms"] == BASE_MS

        closed = await _all_closed(db_path)
        assert len(closed) == 1
        r = closed[0]
        assert r["quantity"] == pytest.approx(20.0)
        assert r["entry_price"] == pytest.approx(0.50)
        assert r["source"] == "rebuilt_from_fills"


# ── 7. Duplicate-key orphans collapse into one rebuilt row ─────────────


class TestDuplicateKeyOrphans:
    @pytest.mark.asyncio
    async def test_two_orphans_same_entry_time_both_deleted(self, db_path):
        # Two orphan rows share (symbol, direction, entry_time_ms) but
        # differ in exit_time_ms — earlier double-write backfill
        # artifact. Both should be DELETED when key is recoverable;
        # only ONE rebuilt row results (helper emits one per logical
        # open_time).
        await _seed_orphan(
            db_path, symbol="STOUSDT", direction="LONG",
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 70_000,
            entry_price=1.20, exit_price=1.21, quantity=5.0,
        )
        await _seed_orphan(
            db_path, symbol="STOUSDT", direction="LONG",
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 12_476_188,
            entry_price=1.20, exit_price=1.22, quantity=5.0,
        )
        await _seed_rpnl(
            db_path, trade_key="rpnl-1", symbol="STOUSDT",
            direction="LONG", entry_price=1.20, exit_price=1.21,
            qty=5.0, open_time=BASE_MS, time=BASE_MS + 70_000,
        )
        await _seed_close_fill(
            db_path, exchange_fill_id="close-1",
            symbol="STOUSDT", direction="LONG", quantity=5.0,
            price=1.21, timestamp_ms=BASE_MS + 70_000,
        )

        result = await run_synth(db_path=db_path, apply=True, verbose=False)

        # Both orphan rows counted as recoverable + both deleted.
        assert result["recoverable"] == 2
        assert result["preserved"] == 0
        # One synth OPEN, one rebuilt row, two orphans deleted.
        assert result["fills_synthed"] == 1
        assert result["positions_rebuilt"] == 1
        assert result["orphans_deleted"] == 2

        closed = await _all_closed(db_path)
        assert len(closed) == 1
        assert closed[0]["source"] == "rebuilt_from_fills"
        assert closed[0]["terminal_position_id"] == f"rebuilt:STOUSDT:LONG:{BASE_MS}"


# ── 8. T198: fill-tpid backfill ────────────────────────────────────────


class TestFillTpidBackfill:
    @pytest.mark.asyncio
    async def test_apply_backfills_fill_tpids_for_synth_and_close(self, db_path):
        # T198: after --apply, both the synth OPEN and the existing
        # CLOSE fill should carry the rebuilt tpid so the Position
        # History fills drawer renders them.
        await _seed_orphan(
            db_path, symbol="SIRENUSDT", direction="LONG",
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
            entry_price=0.76, exit_price=0.77, quantity=10.0,
        )
        await _seed_rpnl(
            db_path, trade_key="rpnl-tpid", symbol="SIRENUSDT",
            direction="LONG", entry_price=0.76, exit_price=0.77,
            qty=10.0, open_time=BASE_MS, time=BASE_MS + 60_000,
        )
        await _seed_close_fill(
            db_path, exchange_fill_id="close-tpid",
            symbol="SIRENUSDT", direction="LONG", quantity=10.0,
            price=0.77, timestamp_ms=BASE_MS + 60_000,
        )

        result = await run_synth(db_path=db_path, apply=True, verbose=False)

        assert result["fills_tpid_updated"] == 2

        # Both synth OPEN + existing CLOSE now carry the rebuilt tpid.
        fills = await _all_fills(db_path)
        expected_tpid = f"rebuilt:SIRENUSDT:LONG:{BASE_MS}"
        for f in fills:
            assert f["terminal_position_id"] == expected_tpid, (
                f"fill {f['exchange_fill_id']} has tpid={f['terminal_position_id']!r}"
            )


# ── 9. T199: simulation-based validation (real-OPEN conflict) ──────────


class TestRealOpenConflictReclassified:
    @pytest.mark.asyncio
    async def test_real_open_at_same_ts_reclassifies_as_conflict(self, db_path):
        # BILLUSDT-shape: a real binance_rest OPEN already exists at
        # the same timestamp + price as the orphan's entry. The orphan
        # represents a 140-qty partial close of a 218-qty position.
        # Helper would never emit a record for this lifecycle (open=
        # 218+140=358, close=140 → still 218 open). Script must
        # detect this in dry-run + classify as conflict, not as
        # recoverable.
        await _seed_orphan(
            db_path, symbol="BILLUSDT", direction="LONG",
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
            entry_price=0.13284, exit_price=0.13119, quantity=140.0,
        )
        await _seed_rpnl(
            db_path, trade_key="rpnl-real", symbol="BILLUSDT",
            direction="LONG", entry_price=0.13284, exit_price=0.13119,
            qty=140.0, open_time=BASE_MS, time=BASE_MS + 60_000,
        )
        # Real OPEN already in fills (qty=218 > orphan's 140 — partial-
        # close pattern).
        from core.database import DatabaseManager
        db = DatabaseManager(path=db_path)
        await db.initialize()
        try:
            await db.upsert_fill({
                "account_id": 1, "exchange_fill_id": "real-open-218",
                "symbol": "BILLUSDT", "side": "BUY", "direction": "LONG",
                "price": 0.13284, "quantity": 218.0, "is_close": 0,
                "timestamp_ms": BASE_MS, "source": "binance_rest",
            })
        finally:
            await db.close()
        await _seed_close_fill(
            db_path, exchange_fill_id="close-140",
            symbol="BILLUSDT", direction="LONG", quantity=140.0,
            price=0.13119, timestamp_ms=BASE_MS + 60_000,
        )

        result = await run_synth(db_path=db_path, apply=True, verbose=False)

        # Orphan reclassified as conflict-preserved; no synth queued.
        assert result["recoverable"] == 0
        assert result["preserved"] == 1
        assert result["preserved_conflict"] == 1
        assert result["preserved_no_upstream"] == 0
        assert result["synth_opens_planned"] == 0
        assert result["fills_synthed"] == 0
        assert result["orphans_deleted"] == 0

        # No new fills, no new closed_positions. Orphan unchanged.
        fills = await _all_fills(db_path)
        assert len(fills) == 2   # real OPEN + real CLOSE only
        assert not any(f["source"] == "synth_legacy_open" for f in fills)
        closed = await _all_closed(db_path)
        assert len(closed) == 1
        assert closed[0]["source"] == "exchange_history_backfill"
        assert closed[0]["terminal_position_id"].startswith("bf:")


class TestLifecycleAbsorbedReclassified:
    @pytest.mark.asyncio
    async def test_lifecycle_absorption_reclassifies_as_conflict(self, db_path):
        # ONUSDT-shape: a residual qty from a prior lifecycle prevents
        # qty from returning to zero between positions. Helper emits
        # ONE record covering BOTH "positions" attributed to the FIRST
        # entry_time_ms; the second orphan key has no matching record.
        #
        # Setup: 2 orphans at distinct entry_time_ms, both SHORT, with
        # an existing fill stream that creates a non-zero residual
        # (close qty 1 less than open qty) AFTER processing the first
        # orphan's synth+close, then second orphan's synth+close gets
        # consumed into the same lifecycle.

        # Orphan 1: entry at BASE_MS, exit 5s later.
        await _seed_orphan(
            db_path, symbol="ONUSDT", direction="SHORT",
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 5_000,
            entry_price=0.50, exit_price=0.49, quantity=139.0,
        )
        # Orphan 2: entry 60s later, exit 90s later.
        await _seed_orphan(
            db_path, symbol="ONUSDT", direction="SHORT",
            entry_time_ms=BASE_MS + 60_000,
            exit_time_ms=BASE_MS + 90_000,
            entry_price=0.51, exit_price=0.50, quantity=174.0,
        )
        # RPNL for both.
        await _seed_rpnl(
            db_path, trade_key="rpnl-onu-1", symbol="ONUSDT",
            direction="SHORT", entry_price=0.50, exit_price=0.49,
            qty=139.0, open_time=BASE_MS, time=BASE_MS + 5_000,
        )
        await _seed_rpnl(
            db_path, trade_key="rpnl-onu-2", symbol="ONUSDT",
            direction="SHORT", entry_price=0.51, exit_price=0.50,
            qty=174.0, open_time=BASE_MS + 60_000,
            time=BASE_MS + 90_000,
        )
        # Existing CLOSE fills: close 1 short of synth OPEN qty so a
        # residual remains and absorbs the next lifecycle.
        await _seed_close_fill(
            db_path, exchange_fill_id="close-onu-1",
            symbol="ONUSDT", direction="SHORT", quantity=138.0,
            price=0.49, timestamp_ms=BASE_MS + 5_000,
        )
        await _seed_close_fill(
            db_path, exchange_fill_id="close-onu-2",
            symbol="ONUSDT", direction="SHORT", quantity=174.0,
            price=0.50, timestamp_ms=BASE_MS + 90_000,
        )
        await _seed_close_fill(
            db_path, exchange_fill_id="close-onu-residual",
            symbol="ONUSDT", direction="SHORT", quantity=1.0,
            price=0.50, timestamp_ms=BASE_MS + 91_000,
        )

        result = await run_synth(db_path=db_path, apply=True, verbose=False)

        # Helper emits 1 record at entry_time_ms=BASE_MS (qty=313, close
        # 313+1=314 → over-close → snapshot at qty=0).
        # First orphan recovered. Second orphan reclassified (no record
        # at entry_time_ms=BASE_MS+60_000 — that synth got absorbed).
        assert result["recoverable"] == 1
        assert result["preserved"] == 1
        assert result["preserved_conflict"] == 1
        assert result["preserved_no_upstream"] == 0
        assert result["synth_opens_planned"] == 1
        assert result["fills_synthed"] == 1

        # Confirm the absorbed orphan's bf: row is preserved.
        closed = await _all_closed(db_path)
        absorbed = [
            c for c in closed
            if c["terminal_position_id"] == f"bf:ONUSDT:SHORT:{BASE_MS + 60_000}"
        ]
        assert len(absorbed) == 1


class TestPostFixIdempotence:
    @pytest.mark.asyncio
    async def test_apply_then_apply_again_truly_no_op(self, db_path):
        # T199 (post-fix): re-running --apply after a successful run
        # should plan ZERO new synths (true idempotence). Pre-fix,
        # fill-stream-conflict orphans were re-planned every run.
        await _seed_orphan(
            db_path, symbol="SIRENUSDT", direction="LONG",
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
            entry_price=0.76, exit_price=0.77, quantity=10.0,
        )
        await _seed_rpnl(
            db_path, trade_key="rpnl-idem", symbol="SIRENUSDT",
            direction="LONG", entry_price=0.76, exit_price=0.77,
            qty=10.0, open_time=BASE_MS, time=BASE_MS + 60_000,
        )
        await _seed_close_fill(
            db_path, exchange_fill_id="close-idem",
            symbol="SIRENUSDT", direction="LONG", quantity=10.0,
            price=0.77, timestamp_ms=BASE_MS + 60_000,
        )

        await run_synth(db_path=db_path, apply=True, verbose=False)
        r2 = await run_synth(db_path=db_path, apply=False, verbose=False)

        assert r2["orphans_in_scope"] == 0
        assert r2["synth_opens_planned"] == 0


# ── 10. Symbol scope filter ────────────────────────────────────────────


class TestSymbolScope:
    @pytest.mark.asyncio
    async def test_symbol_filter_isolates_scope(self, db_path):
        # Two symbols, both with recoverable RPNL. Scope by SIRENUSDT
        # only; STOUSDT orphan should be untouched.
        for sym in ("SIRENUSDT", "STOUSDT"):
            await _seed_orphan(
                db_path, symbol=sym, direction="LONG",
                entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
                entry_price=1.0, exit_price=1.01, quantity=10.0,
            )
            await _seed_rpnl(
                db_path, trade_key=f"rpnl-{sym}", symbol=sym,
                direction="LONG", entry_price=1.0, exit_price=1.01,
                qty=10.0, open_time=BASE_MS, time=BASE_MS + 60_000,
            )
            await _seed_close_fill(
                db_path, exchange_fill_id=f"close-{sym}",
                symbol=sym, direction="LONG", quantity=10.0,
                price=1.01, timestamp_ms=BASE_MS + 60_000,
            )

        result = await run_synth(
            db_path=db_path, apply=True, symbol="SIRENUSDT", verbose=False,
        )
        assert result["recoverable"] == 1
        assert result["positions_rebuilt"] == 1

        closed = await _all_closed(db_path)
        siren = [r for r in closed if r["symbol"] == "SIRENUSDT"]
        sto = [r for r in closed if r["symbol"] == "STOUSDT"]
        assert len(siren) == 1
        assert siren[0]["source"] == "rebuilt_from_fills"
        assert len(sto) == 1
        assert sto[0]["source"] == "exchange_history_backfill"
        assert sto[0]["terminal_position_id"].startswith("bf:")
