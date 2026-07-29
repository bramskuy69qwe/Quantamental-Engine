"""
Phase 0.0.6 (T190) tests for ``scripts/rebuild_closed_positions.py``.

End-to-end behavior against a tempfile DB:

  1. Dry-run reads + reports + returns counts; NO writes.
  2. Apply DELETEs existing in scope + INSERTs rebuilt rows from
     ``position_grouping.group_fills_into_positions``.
  3. Idempotent — running --apply twice produces the same final state.
  4. Scope filtering (--account-id, --symbol) is respected.
  5. Existing rows whose source is NOT 'rebuilt_from_fills' (the
     corrupted T178 rows) are removed and replaced.

Run: pytest tests/test_rebuild_closed_positions.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scripts.rebuild_closed_positions import run_rebuild


BASE_MS = 1778025600000   # 2026-05-01 UTC


@pytest_asyncio.fixture
async def db_path():
    """Tempfile DB initialized with the project schema. Yields the path
    so the script under test can open its own DatabaseManager against
    it (matches how an operator invokes the script)."""
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


# ── Test data helpers ──────────────────────────────────────────────────


async def _seed_fill(
    db_path: str, *,
    exchange_fill_id: str,
    symbol: str,
    side: str,
    direction: str,
    quantity: float,
    price: float,
    is_close: bool,
    timestamp_ms: int,
    terminal_position_id: str = "",
    realized_pnl: float = 0.0,
    fee: float = 0.0,
    account_id: int = 1,
):
    from core.database import DatabaseManager
    db = DatabaseManager(path=db_path)
    await db.initialize()
    try:
        await db.upsert_fill({
            "account_id":           account_id,
            "exchange_fill_id":     exchange_fill_id,
            "symbol":               symbol,
            "side":                 side,
            "direction":            direction,
            "price":                price,
            "quantity":             quantity,
            "fee":                  fee,
            "is_close":             int(is_close),
            "realized_pnl":         realized_pnl,
            "timestamp_ms":         timestamp_ms,
            "terminal_position_id": terminal_position_id,
        })
    finally:
        await db.close()


async def _seed_existing_closed(
    db_path: str, *,
    terminal_position_id: str,
    symbol: str,
    direction: str,
    quantity: float,
    entry_price: float,
    exit_price: float,
    entry_time_ms: int,
    exit_time_ms: int,
    realized_pnl: float = 0.0,
    source: str = "exchange_history_backfill",
    account_id: int = 1,
):
    """Seed an existing (corrupted, pre-rebuild) closed_positions row."""
    from core.database import DatabaseManager
    db = DatabaseManager(path=db_path)
    await db.initialize()
    try:
        await db.insert_closed_position({
            "account_id":           account_id,
            "terminal_position_id": terminal_position_id,
            "symbol":               symbol,
            "direction":            direction,
            "quantity":             quantity,
            "entry_price":          entry_price,
            "exit_price":           exit_price,
            "entry_time_ms":        entry_time_ms,
            "exit_time_ms":         exit_time_ms,
            "realized_pnl":         realized_pnl,
            "source":               source,
        })
    finally:
        await db.close()


async def _all_closed(db_path: str, account_id: int = 1):
    from core.database import DatabaseManager
    db = DatabaseManager(path=db_path)
    await db.initialize()
    try:
        async with db._conn.execute(
            "SELECT * FROM closed_positions WHERE account_id=? ORDER BY id ASC",
            (account_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


# ── 1. Dry-run reads but writes nothing ────────────────────────────────


class TestDryRunReadsOnly:
    @pytest.mark.asyncio
    async def test_dry_run_makes_no_writes(self, db_path):
        # Seed an existing corrupted row + the underlying fills.
        await _seed_existing_closed(
            db_path,
            terminal_position_id="bf:BTCUSDT:LONG:1000",
            symbol="BTCUSDT", direction="LONG",
            quantity=1.0, entry_price=99999.0,   # corrupted entry
            exit_price=81000.0,
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
            source="exchange_history_backfill",
        )
        await _seed_fill(
            db_path, exchange_fill_id="open-1",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=1.0, price=80000.0, is_close=False,
            timestamp_ms=BASE_MS,
        )
        await _seed_fill(
            db_path, exchange_fill_id="close-1",
            symbol="BTCUSDT", side="SELL", direction="LONG",
            quantity=1.0, price=81000.0, is_close=True,
            timestamp_ms=BASE_MS + 60_000, realized_pnl=1000.0,
        )

        before = await _all_closed(db_path)
        result = await run_rebuild(
            db_path=db_path, apply=False, verbose=False,
        )
        after = await _all_closed(db_path)

        assert result["applied"] is False
        assert result["rebuilt_count"] == 1
        assert result["existing_count"] == 1
        assert result["deleted_count"] == 0
        assert result["inserted_count"] == 0
        # No changes to closed_positions in dry-run.
        assert before == after


# ── 2. Apply deletes-then-inserts ──────────────────────────────────────


class TestApplyDeletesAndInserts:
    @pytest.mark.asyncio
    async def test_apply_replaces_corrupted_row_with_rebuilt(self, db_path):
        # Existing corrupted row: entry_price is nonsense (from T178
        # Layer 3 fallback contamination).
        await _seed_existing_closed(
            db_path,
            terminal_position_id="bf:BTCUSDT:LONG:1000",
            symbol="BTCUSDT", direction="LONG",
            quantity=1.0, entry_price=99999.0,
            exit_price=81000.0,
            entry_time_ms=BASE_MS - 1000, exit_time_ms=BASE_MS + 60_000,
            source="exchange_history_backfill",
        )
        # Clean fills underlying the same trade.
        await _seed_fill(
            db_path, exchange_fill_id="open-1",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=1.0, price=80000.0, is_close=False,
            timestamp_ms=BASE_MS,
        )
        await _seed_fill(
            db_path, exchange_fill_id="close-1",
            symbol="BTCUSDT", side="SELL", direction="LONG",
            quantity=1.0, price=81000.0, is_close=True,
            timestamp_ms=BASE_MS + 60_000, realized_pnl=1000.0,
        )

        result = await run_rebuild(
            db_path=db_path, apply=True, verbose=False,
        )
        assert result["applied"] is True
        assert result["deleted_count"] == 1
        assert result["inserted_count"] == 1

        rows = await _all_closed(db_path)
        assert len(rows) == 1
        r = rows[0]
        # Old corrupted entry_price=99999.0 wiped; rebuilt from fills.
        assert r["entry_price"] == pytest.approx(80000.0)
        assert r["exit_price"] == pytest.approx(81000.0)
        assert r["quantity"] == pytest.approx(1.0)
        # Synthetic deterministic ID from the helper.
        assert r["terminal_position_id"] == f"rebuilt:BTCUSDT:LONG:{BASE_MS}"
        assert r["source"] == "rebuilt_from_fills"
        # backfill_completed = 0 so the reconciler picks it up + applies
        # the T175 MFE/MAE floor.
        assert r["backfill_completed"] == 0

    @pytest.mark.asyncio
    async def test_apply_backfills_fill_tpids(self, db_path):
        # T198: --apply should UPDATE fills.terminal_position_id to
        # match the rebuilt closed_positions row's tpid (so the strict
        # get_position_fills lookup returns the fills on the Position
        # History drawer).
        await _seed_fill(
            db_path, exchange_fill_id="open-tpid",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=1.0, price=80000.0, is_close=False,
            timestamp_ms=BASE_MS,
        )
        await _seed_fill(
            db_path, exchange_fill_id="close-tpid",
            symbol="BTCUSDT", side="SELL", direction="LONG",
            quantity=1.0, price=81000.0, is_close=True,
            timestamp_ms=BASE_MS + 60_000, realized_pnl=1000.0,
        )

        result = await run_rebuild(
            db_path=db_path, apply=True, verbose=False,
        )
        assert result["fill_tpids_updated"] == 2

        # Both fills should now carry the rebuilt tpid.
        from core.database import DatabaseManager
        db = DatabaseManager(path=db_path)
        await db.initialize()
        try:
            async with db._conn.execute(
                "SELECT exchange_fill_id, terminal_position_id "
                "FROM fills WHERE symbol='BTCUSDT' ORDER BY timestamp_ms"
            ) as cur:
                rows = [dict(r) for r in await cur.fetchall()]
        finally:
            await db.close()
        assert len(rows) == 2
        expected_tpid = f"rebuilt:BTCUSDT:LONG:{BASE_MS}"
        assert rows[0]["terminal_position_id"] == expected_tpid
        assert rows[1]["terminal_position_id"] == expected_tpid

    @pytest.mark.asyncio
    async def test_apply_preserves_existing_non_empty_tpid_on_fills(self, db_path):
        # Quantower-plugin fills arrive with terminal_position_id
        # populated by the plugin. The tpid backfill must NOT overwrite
        # those — it only fills in empty tpids.
        await _seed_fill(
            db_path, exchange_fill_id="open-qt",
            symbol="ETHUSDT", side="BUY", direction="LONG",
            quantity=1.0, price=3000.0, is_close=False,
            timestamp_ms=BASE_MS,
            terminal_position_id="qt-pos-12345",
        )
        await _seed_fill(
            db_path, exchange_fill_id="close-qt",
            symbol="ETHUSDT", side="SELL", direction="LONG",
            quantity=1.0, price=3100.0, is_close=True,
            timestamp_ms=BASE_MS + 60_000,
            terminal_position_id="qt-pos-12345",
        )

        await run_rebuild(db_path=db_path, apply=True, verbose=False)

        from core.database import DatabaseManager
        db = DatabaseManager(path=db_path)
        await db.initialize()
        try:
            async with db._conn.execute(
                "SELECT terminal_position_id FROM fills WHERE symbol='ETHUSDT'"
            ) as cur:
                rows = [dict(r) for r in await cur.fetchall()]
        finally:
            await db.close()
        for r in rows:
            assert r["terminal_position_id"] == "qt-pos-12345"

    @pytest.mark.asyncio
    async def test_tpid_backfill_only_skips_delete_and_insert(self, db_path):
        # T198: --tpid-backfill-only should update fills' tpids without
        # touching closed_positions.
        await _seed_fill(
            db_path, exchange_fill_id="open-only",
            symbol="SOLUSDT", side="BUY", direction="LONG",
            quantity=1.0, price=140.0, is_close=False,
            timestamp_ms=BASE_MS,
        )
        await _seed_fill(
            db_path, exchange_fill_id="close-only",
            symbol="SOLUSDT", side="SELL", direction="LONG",
            quantity=1.0, price=141.0, is_close=True,
            timestamp_ms=BASE_MS + 60_000, realized_pnl=1.0,
        )
        # Seed an existing rebuilt closed_position (as if a prior
        # --apply ran before tpid-backfill was wired). Its source +
        # tpid match what the helper would produce.
        await _seed_existing_closed(
            db_path,
            terminal_position_id=f"rebuilt:SOLUSDT:LONG:{BASE_MS}",
            symbol="SOLUSDT", direction="LONG",
            quantity=1.0, entry_price=140.0, exit_price=141.0,
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
            source="rebuilt_from_fills",
        )

        before_closed = await _all_closed(db_path)
        result = await run_rebuild(
            db_path=db_path, apply=True, tpid_backfill_only=True,
            verbose=False,
        )
        after_closed = await _all_closed(db_path)

        assert result["fill_tpids_updated"] == 2
        # closed_positions untouched.
        assert result["deleted_count"] == 0
        assert result["inserted_count"] == 0
        assert before_closed == after_closed

        # Fills now carry the tpid.
        from core.database import DatabaseManager
        db = DatabaseManager(path=db_path)
        await db.initialize()
        try:
            async with db._conn.execute(
                "SELECT terminal_position_id FROM fills WHERE symbol='SOLUSDT'"
            ) as cur:
                rows = [dict(r) for r in await cur.fetchall()]
        finally:
            await db.close()
        expected_tpid = f"rebuilt:SOLUSDT:LONG:{BASE_MS}"
        for r in rows:
            assert r["terminal_position_id"] == expected_tpid

    @pytest.mark.asyncio
    async def test_tpid_backfill_only_idempotent(self, db_path):
        # Re-running --tpid-backfill-only should be a no-op (all fills
        # already have non-empty tpid).
        await _seed_fill(
            db_path, exchange_fill_id="op1",
            symbol="ADAUSDT", side="BUY", direction="LONG",
            quantity=10.0, price=1.0, is_close=False,
            timestamp_ms=BASE_MS,
        )
        await _seed_fill(
            db_path, exchange_fill_id="cl1",
            symbol="ADAUSDT", side="SELL", direction="LONG",
            quantity=10.0, price=1.05, is_close=True,
            timestamp_ms=BASE_MS + 60_000,
        )
        await _seed_existing_closed(
            db_path,
            terminal_position_id=f"rebuilt:ADAUSDT:LONG:{BASE_MS}",
            symbol="ADAUSDT", direction="LONG",
            quantity=10.0, entry_price=1.0, exit_price=1.05,
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
            source="rebuilt_from_fills",
        )

        r1 = await run_rebuild(
            db_path=db_path, apply=True, tpid_backfill_only=True,
            verbose=False,
        )
        r2 = await run_rebuild(
            db_path=db_path, apply=True, tpid_backfill_only=True,
            verbose=False,
        )
        assert r1["fill_tpids_updated"] == 2
        assert r2["fill_tpids_updated"] == 0   # idempotent

    @pytest.mark.asyncio
    async def test_apply_with_no_existing_just_inserts(self, db_path):
        # No prior closed_positions, only fills.
        await _seed_fill(
            db_path, exchange_fill_id="open-1",
            symbol="ETHUSDT", side="BUY", direction="LONG",
            quantity=2.0, price=3000.0, is_close=False,
            timestamp_ms=BASE_MS,
        )
        await _seed_fill(
            db_path, exchange_fill_id="close-1",
            symbol="ETHUSDT", side="SELL", direction="LONG",
            quantity=2.0, price=3100.0, is_close=True,
            timestamp_ms=BASE_MS + 60_000, realized_pnl=200.0,
        )

        result = await run_rebuild(
            db_path=db_path, apply=True, verbose=False,
        )
        assert result["deleted_count"] == 0
        assert result["inserted_count"] == 1
        rows = await _all_closed(db_path)
        assert len(rows) == 1
        assert rows[0]["symbol"] == "ETHUSDT"


# ── 3. Idempotency ─────────────────────────────────────────────────────


class TestIdempotent:
    @pytest.mark.asyncio
    async def test_apply_twice_produces_same_final_state(self, db_path):
        await _seed_fill(
            db_path, exchange_fill_id="o-1",
            symbol="BNBUSDT", side="BUY", direction="LONG",
            quantity=3.0, price=500.0, is_close=False,
            timestamp_ms=BASE_MS,
        )
        await _seed_fill(
            db_path, exchange_fill_id="c-1",
            symbol="BNBUSDT", side="SELL", direction="LONG",
            quantity=3.0, price=510.0, is_close=True,
            timestamp_ms=BASE_MS + 60_000, realized_pnl=30.0,
        )

        await run_rebuild(db_path=db_path, apply=True, verbose=False)
        rows_first = await _all_closed(db_path)
        await run_rebuild(db_path=db_path, apply=True, verbose=False)
        rows_second = await _all_closed(db_path)

        assert len(rows_first) == 1
        assert len(rows_second) == 1
        # Deterministic synthetic ID across runs.
        assert rows_first[0]["terminal_position_id"] == rows_second[0]["terminal_position_id"]
        assert rows_first[0]["entry_price"] == rows_second[0]["entry_price"]
        assert rows_first[0]["exit_price"] == rows_second[0]["exit_price"]


# ── 4. Scope filtering ─────────────────────────────────────────────────


class TestScopeFilters:
    @pytest.mark.asyncio
    async def test_symbol_filter_only_touches_that_symbol(self, db_path):
        # Seed fills for two symbols.
        for sym, qty, price in [("BTCUSDT", 1.0, 80000.0), ("ETHUSDT", 2.0, 3000.0)]:
            await _seed_fill(
                db_path, exchange_fill_id=f"open-{sym}",
                symbol=sym, side="BUY", direction="LONG",
                quantity=qty, price=price, is_close=False,
                timestamp_ms=BASE_MS,
            )
            await _seed_fill(
                db_path, exchange_fill_id=f"close-{sym}",
                symbol=sym, side="SELL", direction="LONG",
                quantity=qty, price=price * 1.01, is_close=True,
                timestamp_ms=BASE_MS + 60_000,
                realized_pnl=qty * price * 0.01,
            )
        # Seed existing rows for both.
        for sym in ("BTCUSDT", "ETHUSDT"):
            await _seed_existing_closed(
                db_path,
                terminal_position_id=f"bf:{sym}:LONG:1",
                symbol=sym, direction="LONG",
                quantity=1.0, entry_price=99999.0, exit_price=99999.0,
                entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
            )

        # Run with --symbol=BTCUSDT only.
        result = await run_rebuild(
            db_path=db_path, apply=True, symbol="BTCUSDT", verbose=False,
        )
        assert result["deleted_count"] == 1
        assert result["inserted_count"] == 1

        rows = await _all_closed(db_path)
        # ETHUSDT existing row should be untouched.
        eth_rows = [r for r in rows if r["symbol"] == "ETHUSDT"]
        btc_rows = [r for r in rows if r["symbol"] == "BTCUSDT"]
        assert len(eth_rows) == 1
        assert eth_rows[0]["terminal_position_id"] == "bf:ETHUSDT:LONG:1"
        assert eth_rows[0]["entry_price"] == 99999.0   # untouched corrupted
        assert len(btc_rows) == 1
        # BTCUSDT row was rebuilt with correct entry_price.
        assert btc_rows[0]["entry_price"] == pytest.approx(80000.0)
        assert btc_rows[0]["source"] == "rebuilt_from_fills"

    @pytest.mark.asyncio
    async def test_account_id_filter_restricts_scope(self, db_path):
        for acct in (1, 2):
            await _seed_fill(
                db_path, exchange_fill_id=f"o-{acct}",
                symbol="ADAUSDT", side="BUY", direction="LONG",
                quantity=10.0, price=1.0, is_close=False,
                timestamp_ms=BASE_MS, account_id=acct,
            )
            await _seed_fill(
                db_path, exchange_fill_id=f"c-{acct}",
                symbol="ADAUSDT", side="SELL", direction="LONG",
                quantity=10.0, price=1.1, is_close=True,
                timestamp_ms=BASE_MS + 60_000,
                realized_pnl=1.0, account_id=acct,
            )
            await _seed_existing_closed(
                db_path,
                terminal_position_id=f"bf:acct-{acct}",
                symbol="ADAUSDT", direction="LONG",
                quantity=10.0, entry_price=99.0, exit_price=99.0,
                entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
                account_id=acct,
            )

        result = await run_rebuild(
            db_path=db_path, apply=True, account_id=1, verbose=False,
        )
        # Only account 1's row was rebuilt.
        assert result["inserted_count"] == 1
        rows_1 = await _all_closed(db_path, account_id=1)
        rows_2 = await _all_closed(db_path, account_id=2)
        assert len(rows_1) == 1
        assert rows_1[0]["source"] == "rebuilt_from_fills"
        # Account 2's corrupted row untouched.
        assert len(rows_2) == 1
        assert rows_2[0]["terminal_position_id"] == "bf:acct-2"
        assert rows_2[0]["entry_price"] == 99.0


# ── 5. Cross-position contamination guard ──────────────────────────────


class TestOrphanSymbolPreservation:
    """T194 fix: existing closed_positions rows for symbols that have
    no usable fills (pre-Phase-0.0.2 backfill artifacts) MUST be
    preserved by default. Only when --wipe-orphans is set do they get
    deleted."""

    @pytest.mark.asyncio
    async def test_orphan_symbol_rows_preserved_by_default(self, db_path):
        # Symbol BTCUSDT: has clean fills + a rebuilt position.
        await _seed_fill(
            db_path, exchange_fill_id="btc-open",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=1.0, price=80000.0, is_close=False,
            timestamp_ms=BASE_MS,
        )
        await _seed_fill(
            db_path, exchange_fill_id="btc-close",
            symbol="BTCUSDT", side="SELL", direction="LONG",
            quantity=1.0, price=81000.0, is_close=True,
            timestamp_ms=BASE_MS + 60_000,
        )
        await _seed_existing_closed(
            db_path,
            terminal_position_id="bf:BTCUSDT:LONG:1",
            symbol="BTCUSDT", direction="LONG",
            quantity=1.0, entry_price=99999.0, exit_price=99999.0,
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
        )
        # Symbol ORPHANUSDT: closed_positions row but NO fills.
        await _seed_existing_closed(
            db_path,
            terminal_position_id="bf:ORPHANUSDT:LONG:1",
            symbol="ORPHANUSDT", direction="LONG",
            quantity=10.0, entry_price=1.0, exit_price=1.1,
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
        )

        result = await run_rebuild(
            db_path=db_path, apply=True, verbose=False,
        )

        # BTCUSDT was rebuilt; ORPHANUSDT was preserved.
        assert result["rebuilt_count"] == 1
        assert result["inserted_count"] == 1
        assert result["orphan_symbols"] == ["ORPHANUSDT"]
        assert result["orphan_rows_preserved"] == 1

        rows = await _all_closed(db_path)
        symbols = {r["symbol"] for r in rows}
        assert symbols == {"BTCUSDT", "ORPHANUSDT"}, (
            "ORPHANUSDT must be preserved by default — no rebuilt "
            "equivalent doesn't mean wipe."
        )
        # BTCUSDT was actually rebuilt (entry_price changed).
        btc_row = next(r for r in rows if r["symbol"] == "BTCUSDT")
        assert btc_row["entry_price"] == pytest.approx(80000.0)
        # ORPHANUSDT untouched (corrupted entry preserved as-is).
        orphan_row = next(r for r in rows if r["symbol"] == "ORPHANUSDT")
        assert orphan_row["entry_price"] == pytest.approx(1.0)
        assert orphan_row["terminal_position_id"] == "bf:ORPHANUSDT:LONG:1"

    @pytest.mark.asyncio
    async def test_wipe_orphans_flag_deletes_orphan_rows(self, db_path):
        # Same setup as the preservation test, but --wipe-orphans.
        await _seed_fill(
            db_path, exchange_fill_id="btc-open",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=1.0, price=80000.0, is_close=False,
            timestamp_ms=BASE_MS,
        )
        await _seed_fill(
            db_path, exchange_fill_id="btc-close",
            symbol="BTCUSDT", side="SELL", direction="LONG",
            quantity=1.0, price=81000.0, is_close=True,
            timestamp_ms=BASE_MS + 60_000,
        )
        await _seed_existing_closed(
            db_path,
            terminal_position_id="bf:ORPHANUSDT:LONG:1",
            symbol="ORPHANUSDT", direction="LONG",
            quantity=10.0, entry_price=1.0, exit_price=1.1,
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
        )

        result = await run_rebuild(
            db_path=db_path, apply=True, wipe_orphans=True, verbose=False,
        )
        # orphan_rows_preserved == 0 — they were wiped.
        assert result["orphan_rows_preserved"] == 0
        rows = await _all_closed(db_path)
        symbols = {r["symbol"] for r in rows}
        assert symbols == {"BTCUSDT"}, (
            "--wipe-orphans must delete the orphan rows."
        )

    @pytest.mark.asyncio
    async def test_dry_run_reports_orphans_without_writing(self, db_path):
        await _seed_existing_closed(
            db_path,
            terminal_position_id="bf:ORPHAN:LONG:1",
            symbol="ORPHAN", direction="LONG",
            quantity=10.0, entry_price=1.0, exit_price=1.1,
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
        )
        result = await run_rebuild(
            db_path=db_path, apply=False, verbose=False,
        )
        assert result["applied"] is False
        assert result["orphan_symbols"] == ["ORPHAN"]
        # Dry-run preserves count is 0 (no actual preservation yet).
        assert result["orphan_rows_preserved"] == 0
        # Existing row untouched.
        rows = await _all_closed(db_path)
        assert len(rows) == 1


class TestReversalSplitFlowsThroughRebuild:
    """T191 audit M1: Phase 0.0.4 reversal-split emits 2 fills (a
    close-of-old with the original tradeId + an open-of-new with
    ``synth:{tradeId}:open``). The rebuild script feeds ALL fills to
    ``group_fills_into_positions``; verify that the helper attributes
    the synth-open correctly so the new direction's position is
    rebuilt with the right entry data."""

    @pytest.mark.asyncio
    async def test_reversal_split_produces_two_rebuilt_rows(self, db_path):
        # Original LONG position open.
        long_open_ts = BASE_MS
        reversal_ts = BASE_MS + 60_000
        short_close_ts = BASE_MS + 120_000

        await _seed_fill(
            db_path, exchange_fill_id="long-open",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=5.0, price=79000.0, is_close=False,
            timestamp_ms=long_open_ts,
        )
        # Reversal: a single SELL 12 crosses zero. Phase 0.0.4 splits it
        # into close-of-LONG and open-of-SHORT.
        await _seed_fill(
            db_path, exchange_fill_id="tid-100",
            symbol="BTCUSDT", side="SELL", direction="LONG",
            quantity=5.0, price=80000.0, is_close=True,
            timestamp_ms=reversal_ts, realized_pnl=5000.0,
        )
        await _seed_fill(
            db_path, exchange_fill_id="synth:tid-100:open",
            symbol="BTCUSDT", side="SELL", direction="SHORT",
            quantity=7.0, price=80000.0, is_close=False,
            timestamp_ms=reversal_ts,
        )
        # Later, the SHORT closes for a profit.
        await _seed_fill(
            db_path, exchange_fill_id="tid-200",
            symbol="BTCUSDT", side="BUY", direction="SHORT",
            quantity=7.0, price=78000.0, is_close=True,
            timestamp_ms=short_close_ts, realized_pnl=14000.0,
        )

        await run_rebuild(db_path=db_path, apply=True, verbose=False)
        rows = await _all_closed(db_path)
        rows_by_dir = {r["direction"]: r for r in rows}
        assert set(rows_by_dir) == {"LONG", "SHORT"}

        long_row = rows_by_dir["LONG"]
        assert long_row["entry_price"] == pytest.approx(79000.0)
        assert long_row["exit_price"] == pytest.approx(80000.0)
        assert long_row["quantity"] == pytest.approx(5.0)
        assert long_row["entry_time_ms"] == long_open_ts
        assert long_row["exit_time_ms"] == reversal_ts

        short_row = rows_by_dir["SHORT"]
        # Entry from the synth open at the reversal.
        assert short_row["entry_price"] == pytest.approx(80000.0)
        assert short_row["entry_time_ms"] == reversal_ts
        # Exit from the follow-up close.
        assert short_row["exit_price"] == pytest.approx(78000.0)
        assert short_row["exit_time_ms"] == short_close_ts
        assert short_row["quantity"] == pytest.approx(7.0)


class TestTpSlResolutionViaCalcId:
    """T191 audit M2: ``insert_closed_position`` auto-resolves
    ``tp_price``/``sl_price`` from ``pre_trade_log`` when ``calc_id``
    is supplied (v2.4 Task 69). Verify that rebuilt rows whose opens
    carry calc_id pick up the corresponding tp/sl_price."""

    @pytest.mark.asyncio
    async def test_calc_id_propagates_tp_sl_prices(self, db_path):
        from core.database import DatabaseManager
        from datetime import datetime, timezone

        # Seed a pre_trade_log row with tp/sl_price.
        db = DatabaseManager(path=db_path)
        await db.initialize()
        try:
            await db.insert_pre_trade_log({
                "account_id":   1,
                "timestamp":    datetime.now(timezone.utc).isoformat(),
                "ticker":       "BTCUSDT",
                "side":         "BUY",
                "average":      80000.0,
                "calc_id":      "calc-rebuild-1",
                "tp_price":     85000.0,
                "sl_price":     75000.0,
            })
        finally:
            await db.close()

        # Seed fills with the matching calc_id on the open.
        await _seed_fill(
            db_path, exchange_fill_id="open-1",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=1.0, price=80000.0, is_close=False,
            timestamp_ms=BASE_MS,
        )
        await _seed_fill(
            db_path, exchange_fill_id="close-1",
            symbol="BTCUSDT", side="SELL", direction="LONG",
            quantity=1.0, price=81000.0, is_close=True,
            timestamp_ms=BASE_MS + 60_000, realized_pnl=1000.0,
        )
        # Set calc_id directly on the open fill (upsert_fill doesn't
        # populate calc_id — it's normally written via enrich_fill).
        db = DatabaseManager(path=db_path)
        await db.initialize()
        try:
            await db._conn.execute(
                "UPDATE fills SET calc_id = ? WHERE exchange_fill_id = ?",
                ("calc-rebuild-1", "open-1"),
            )
            await db._conn.commit()
        finally:
            await db.close()

        await run_rebuild(db_path=db_path, apply=True, verbose=False)
        rows = await _all_closed(db_path)
        assert len(rows) == 1
        r = rows[0]
        # tp_price/sl_price auto-resolved from pre_trade_log via calc_id.
        assert r["calc_id"] == "calc-rebuild-1"
        assert r["tp_price"] == pytest.approx(85000.0)
        assert r["sl_price"] == pytest.approx(75000.0)


class TestAtomicityOnFailure:
    """T191 audit B1 fix: DELETE + INSERTs run in a single transaction.
    If any step fails mid-way, the transaction rolls back to pre-script
    state instead of leaving the DB with closed_positions wiped but
    rebuilt rows incomplete."""

    @pytest.mark.asyncio
    async def test_rollback_on_insert_failure_preserves_pre_script_state(
        self, db_path,
    ):
        from unittest.mock import patch
        from core.database import DatabaseManager

        # Seed an existing row + the underlying fills.
        await _seed_existing_closed(
            db_path,
            terminal_position_id="bf:original",
            symbol="BTCUSDT", direction="LONG",
            quantity=1.0, entry_price=99999.0, exit_price=99999.0,
            entry_time_ms=BASE_MS, exit_time_ms=BASE_MS + 60_000,
        )
        await _seed_fill(
            db_path, exchange_fill_id="open-1",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=1.0, price=80000.0, is_close=False,
            timestamp_ms=BASE_MS,
        )
        await _seed_fill(
            db_path, exchange_fill_id="close-1",
            symbol="BTCUSDT", side="SELL", direction="LONG",
            quantity=1.0, price=81000.0, is_close=True,
            timestamp_ms=BASE_MS + 60_000,
        )

        # Force a mid-transaction failure by patching
        # insert_closed_position to raise on the rebuild call.
        original_insert = DatabaseManager.insert_closed_position

        async def boom(self, row, commit=True):
            raise RuntimeError("simulated insert failure")

        with patch.object(DatabaseManager, "insert_closed_position", boom):
            with pytest.raises(RuntimeError, match="simulated insert failure"):
                await run_rebuild(
                    db_path=db_path, apply=True, verbose=False,
                )

        # Restore the original method (the patch context manager already
        # does this, but be explicit).
        DatabaseManager.insert_closed_position = original_insert

        # The DELETE rolled back — pre-script row should still be there.
        rows = await _all_closed(db_path)
        assert len(rows) == 1
        assert rows[0]["terminal_position_id"] == "bf:original", (
            "Transaction failed to roll back — DELETE persisted "
            "while INSERT failed, leaving DB in inconsistent state. "
            "T191 audit B1 fix regressed."
        )


class TestCrossPositionRebuild:
    """T178 Layer 3 closed at the rebuild boundary: multiple sequential
    positions in the same (symbol, direction) must produce multiple
    distinct closed_positions rows with correct per-position
    attribution (not cross-VWAP'd)."""

    @pytest.mark.asyncio
    async def test_two_sequential_long_positions_emit_two_rows(self, db_path):
        # Position A
        await _seed_fill(
            db_path, exchange_fill_id="A-open",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=2.0, price=80000.0, is_close=False,
            timestamp_ms=BASE_MS,
        )
        await _seed_fill(
            db_path, exchange_fill_id="A-close",
            symbol="BTCUSDT", side="SELL", direction="LONG",
            quantity=2.0, price=82000.0, is_close=True,
            timestamp_ms=BASE_MS + 60_000, realized_pnl=4000.0,
        )
        # Position B (later, same direction)
        await _seed_fill(
            db_path, exchange_fill_id="B-open",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=1.0, price=85000.0, is_close=False,
            timestamp_ms=BASE_MS + 120_000,
        )
        await _seed_fill(
            db_path, exchange_fill_id="B-close",
            symbol="BTCUSDT", side="SELL", direction="LONG",
            quantity=1.0, price=86000.0, is_close=True,
            timestamp_ms=BASE_MS + 180_000, realized_pnl=1000.0,
        )

        await run_rebuild(db_path=db_path, apply=True, verbose=False)
        rows = await _all_closed(db_path)
        rows_sorted = sorted(rows, key=lambda r: r["exit_time_ms"])
        assert len(rows_sorted) == 2

        a, b = rows_sorted
        # Position A: entry=80000 (NOT a VWAP across A+B opens)
        assert a["entry_price"] == pytest.approx(80000.0)
        assert a["exit_price"] == pytest.approx(82000.0)
        assert a["quantity"] == pytest.approx(2.0)
        # Position B: entry=85000 (NOT contaminated by A's entry)
        assert b["entry_price"] == pytest.approx(85000.0)
        assert b["exit_price"] == pytest.approx(86000.0)
        assert b["quantity"] == pytest.approx(1.0)

        # Each gets a distinct deterministic ID.
        assert a["terminal_position_id"] != b["terminal_position_id"]
        assert a["terminal_position_id"].startswith("rebuilt:")
        assert b["terminal_position_id"].startswith("rebuilt:")


# -- P5-R4: rebuilt rows carry NULL excursions until the reconciler runs --


class TestP5R4NullExcursions:
    @pytest.mark.asyncio
    async def test_pending_row_emits_null_mfe_mae_measured_row_does_not(self, db_path):
        """P5-R4 (phase-5 ledger): the mfe/mae COLUMNS are NOT NULL DEFAULT 0,
        so storage carries a 0.0 placeholder until the reconciler runs — but a
        0.0 emitted to a consumer renders as a MEASURED zero-width excursion
        (v3 truthfulness rule: both null -> em-dash, never a zero bar; the 26
        recovered SNXX/SNDK rows showed 0.0/0.0 for hours while the
        rate-limited reconciler drained). query_closed_positions — the door
        History and the cockpit recent-closes read — must mask the pair to
        None while backfill_completed=0 and pass real values through once the
        reconciler has stamped the row."""
        await _seed_fill(
            db_path, exchange_fill_id="p5r4-open",
            symbol="SOLUSDT", side="BUY", direction="LONG",
            quantity=1.0, price=70.0, is_close=False,
            timestamp_ms=BASE_MS,
        )
        await _seed_fill(
            db_path, exchange_fill_id="p5r4-close",
            symbol="SOLUSDT", side="SELL", direction="LONG",
            quantity=1.0, price=71.0, is_close=True,
            timestamp_ms=BASE_MS + 60_000, realized_pnl=1.0,
        )
        await run_rebuild(db_path=db_path, apply=True, verbose=False)

        # Storage: the schema-constrained placeholder + the work-queue flag.
        raw = await _all_closed(db_path)
        assert len(raw) == 1
        assert raw[0]["mfe"] == 0.0
        assert raw[0]["mae"] == 0.0
        assert raw[0]["backfill_completed"] == 0

        from core.database import DatabaseManager
        db = DatabaseManager(path=db_path)
        await db.initialize()
        try:
            # Emission while PENDING: masked to None (renders as em-dash).
            rows, total = await db.query_closed_positions(account_id=1)
            assert total == 1
            assert rows[0]["mfe"] is None
            assert rows[0]["mae"] is None

            # Reconciler stamps the row -> real values pass through.
            await db.update_closed_position_mfe_mae(raw[0]["id"], 2.5, -1.25)
            rows, _ = await db.query_closed_positions(account_id=1)
            assert rows[0]["mfe"] == 2.5
            assert rows[0]["mae"] == -1.25
            assert rows[0]["backfill_completed"] == 1
        finally:
            await db.close()
