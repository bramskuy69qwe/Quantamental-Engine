"""
Phase 0.0.3 (T185) tests for ``scripts/dedup_fills.py``.

Verifies:

1. ``source_rank``: known sources ordered correctly; unknowns get
   ``UNKNOWN_PRIORITY``.

2. ``pick_keeper``: source priority decides, id-ascending tiebreak
   within a priority class.

3. ``group_fills_for_dedup``: walks the fill stream and emits only
   genuine duplicate groups (size >= 2) per ``is_same_fill``.

4. ``run_dedup`` end-to-end against a tempfile DB:
   - dry-run mode lists planned deletes but writes nothing
   - apply mode commits the deletes
   - idempotent — a second apply has nothing to delete
   - filters (account_id, symbol) restrict the scope correctly
   - unknown-source groups are flagged via ``unknown_source_groups``

Run: pytest tests/test_dedup_fills.py -v
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scripts.dedup_fills import (
    SOURCE_PRIORITY,
    UNKNOWN_PRIORITY,
    group_fills_for_dedup,
    pick_keeper,
    run_dedup,
    source_rank,
)


# Anchor timestamps inside any reasonable cutoff window. 2026-05-01 UTC.
BASE_MS = 1778025600000


# ── 1. source_rank ──────────────────────────────────────────────────────


class TestSourceRank:
    def test_binance_ws_is_highest_priority(self):
        assert source_rank("binance_ws") == 0

    def test_binance_rest_is_middle(self):
        assert source_rank("binance_rest") == 1

    def test_exchange_history_backfill_is_lowest_known(self):
        assert source_rank("exchange_history_backfill") == 2

    def test_unknown_source_is_deprioritized(self):
        assert source_rank("some_new_adapter") == UNKNOWN_PRIORITY

    def test_empty_source_treated_as_unknown(self):
        assert source_rank("") == UNKNOWN_PRIORITY

    def test_priority_order_holds_pairwise(self):
        # WS < REST < backfill < unknown — strict ordering invariant.
        assert (
            source_rank("binance_ws")
            < source_rank("binance_rest")
            < source_rank("exchange_history_backfill")
            < source_rank("unknown_xyz")
        )

    def test_quantower_ranked_with_ws_class(self):
        # Plugin events are real-time direct, equivalent fidelity to WS.
        assert source_rank("quantower") == source_rank("binance_ws")


# ── 2. pick_keeper ──────────────────────────────────────────────────────


def _fill_row(
    *, id: int, source: str, ts: int = BASE_MS,
    symbol: str = "BTCUSDT", side: str = "BUY",
    direction: str = "LONG", price: float = 80000.0,
    quantity: float = 0.5, is_close: int = 0,
    exchange_fill_id: str = "",
):
    return {
        "id":               id,
        "source":           source,
        "symbol":           symbol,
        "side":             side,
        "direction":        direction,
        "price":            price,
        "quantity":         quantity,
        "is_close":         is_close,
        "timestamp_ms":     ts,
        "exchange_fill_id": exchange_fill_id or f"fid-{id}",
    }


class TestPickKeeper:
    def test_higher_priority_source_wins(self):
        group = [
            _fill_row(id=1, source="exchange_history_backfill"),
            _fill_row(id=2, source="binance_ws"),
            _fill_row(id=3, source="binance_rest"),
        ]
        assert pick_keeper(group)["id"] == 2

    def test_id_ascending_tiebreak_within_priority_class(self):
        # All same priority — oldest id wins.
        group = [
            _fill_row(id=5, source="binance_ws"),
            _fill_row(id=2, source="binance_ws"),
            _fill_row(id=8, source="binance_ws"),
        ]
        assert pick_keeper(group)["id"] == 2

    def test_unknown_source_loses_to_known(self):
        group = [
            _fill_row(id=1, source="some_future_adapter"),
            _fill_row(id=2, source="exchange_history_backfill"),
        ]
        assert pick_keeper(group)["id"] == 2

    def test_all_unknown_falls_back_to_oldest_id(self):
        group = [
            _fill_row(id=7, source="src_a"),
            _fill_row(id=3, source="src_b"),
            _fill_row(id=11, source="src_c"),
        ]
        assert pick_keeper(group)["id"] == 3


# ── 3. group_fills_for_dedup ────────────────────────────────────────────


class TestGroupFillsForDedup:
    def test_no_duplicates_returns_empty(self):
        fills = [
            _fill_row(id=1, ts=BASE_MS,           source="binance_ws"),
            _fill_row(id=2, ts=BASE_MS + 10_000,  source="binance_ws",
                      exchange_fill_id="other"),
        ]
        # Different timestamps far apart — not duplicates.
        assert group_fills_for_dedup(fills) == []

    def test_two_matching_fills_form_one_group(self):
        fills = [
            _fill_row(id=1, ts=BASE_MS,        source="binance_ws"),
            _fill_row(id=2, ts=BASE_MS + 500,  source="exchange_history_backfill"),
        ]
        groups = group_fills_for_dedup(fills)
        assert len(groups) == 1
        assert len(groups[0]) == 2
        assert {f["id"] for f in groups[0]} == {1, 2}

    def test_three_matching_fills_form_one_group_of_three(self):
        fills = [
            _fill_row(id=1, ts=BASE_MS,        source="binance_ws"),
            _fill_row(id=2, ts=BASE_MS + 500,  source="binance_rest"),
            _fill_row(id=3, ts=BASE_MS + 1500, source="exchange_history_backfill"),
        ]
        groups = group_fills_for_dedup(fills)
        assert len(groups) == 1
        assert len(groups[0]) == 3

    def test_skew_beyond_tolerance_splits_into_separate_groups(self):
        # ts skew exceeds FILL_DEDUP_TOLERANCE_MS=2000 → distinct fills.
        fills = [
            _fill_row(id=1, ts=BASE_MS,         source="binance_ws"),
            _fill_row(id=2, ts=BASE_MS + 2001,  source="exchange_history_backfill"),
        ]
        assert group_fills_for_dedup(fills) == []

    def test_distinct_symbols_never_group(self):
        fills = [
            _fill_row(id=1, ts=BASE_MS, source="binance_ws", symbol="BTCUSDT"),
            _fill_row(id=2, ts=BASE_MS, source="binance_ws", symbol="ETHUSDT"),
        ]
        assert group_fills_for_dedup(fills) == []

    def test_singletons_are_not_returned(self):
        # 2 distinct pairs + 1 singleton. Only the pairs return.
        fills = [
            # Group A
            _fill_row(id=1, ts=BASE_MS,        source="binance_ws"),
            _fill_row(id=2, ts=BASE_MS + 500,  source="exchange_history_backfill"),
            # Singleton (different symbol)
            _fill_row(id=3, ts=BASE_MS + 1000, source="binance_ws",
                      symbol="ETHUSDT", price=3000.0),
            # Group B (later in time, different from A's window)
            _fill_row(id=4, ts=BASE_MS + 60_000,
                      source="binance_ws",  symbol="SOLUSDT", price=150.0),
            _fill_row(id=5, ts=BASE_MS + 60_500,
                      source="exchange_history_backfill",
                      symbol="SOLUSDT", price=150.0),
        ]
        groups = group_fills_for_dedup(fills)
        assert len(groups) == 2
        sizes = sorted(len(g) for g in groups)
        assert sizes == [2, 2]
        ids = sorted(f["id"] for g in groups for f in g)
        assert ids == [1, 2, 4, 5]   # singleton id=3 excluded


# ── 4. run_dedup against tempfile DB ────────────────────────────────────


@pytest_asyncio.fixture
async def temp_db_path():
    """Provision a tempfile DB initialized with the project schema."""
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


def _seed_fill(
    db_path: str, *, id: int, source: str, ts: int,
    symbol: str = "BTCUSDT", side: str = "BUY", direction: str = "LONG",
    price: float = 80000.0, quantity: float = 0.5, is_close: int = 0,
    account_id: int = 1, exchange_fill_id: str = "",
):
    """Insert a fill row directly via sqlite3 (sync) for setup."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO fills (id, account_id, exchange_fill_id, symbol, side, "
        "direction, price, quantity, is_close, timestamp_ms, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (id, account_id, exchange_fill_id or f"fid-{id}", symbol, side,
         direction, price, quantity, is_close, ts, source),
    )
    conn.commit()
    conn.close()


def _count_fills(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
    conn.close()
    return n


def _fill_ids(db_path: str) -> set:
    conn = sqlite3.connect(db_path)
    ids = {row[0] for row in conn.execute("SELECT id FROM fills")}
    conn.close()
    return ids


class TestRunDedupDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_makes_no_writes(self, temp_db_path):
        _seed_fill(temp_db_path, id=1, source="binance_ws",
                   ts=BASE_MS)
        _seed_fill(temp_db_path, id=2, source="exchange_history_backfill",
                   ts=BASE_MS + 500)
        before = _count_fills(temp_db_path)
        result = run_dedup(
            db_path=temp_db_path, apply=False, verbose=False,
        )
        after = _count_fills(temp_db_path)
        assert before == after == 2
        assert result["applied"] is False
        assert result["groups"] == 1
        assert result["deleted_ids"] == [2]   # backfill loses to ws

    @pytest.mark.asyncio
    async def test_dry_run_no_dups_reports_empty(self, temp_db_path):
        _seed_fill(temp_db_path, id=1, source="binance_ws",
                   ts=BASE_MS, symbol="BTCUSDT")
        _seed_fill(temp_db_path, id=2, source="binance_ws",
                   ts=BASE_MS, symbol="ETHUSDT", price=3000.0)
        result = run_dedup(
            db_path=temp_db_path, apply=False, verbose=False,
        )
        assert result["groups"] == 0
        assert result["deleted_ids"] == []


class TestRunDedupApply:
    @pytest.mark.asyncio
    async def test_apply_deletes_non_keeper_rows(self, temp_db_path):
        _seed_fill(temp_db_path, id=1, source="binance_ws",
                   ts=BASE_MS)
        _seed_fill(temp_db_path, id=2, source="exchange_history_backfill",
                   ts=BASE_MS + 500)
        result = run_dedup(
            db_path=temp_db_path, apply=True, verbose=False,
        )
        assert result["applied"] is True
        assert result["deleted_ids"] == [2]
        remaining = _fill_ids(temp_db_path)
        assert remaining == {1}

    @pytest.mark.asyncio
    async def test_apply_keeps_highest_priority_across_three(self, temp_db_path):
        _seed_fill(temp_db_path, id=1, source="exchange_history_backfill",
                   ts=BASE_MS)
        _seed_fill(temp_db_path, id=2, source="binance_rest",
                   ts=BASE_MS + 500)
        _seed_fill(temp_db_path, id=3, source="binance_ws",
                   ts=BASE_MS + 1500)
        run_dedup(db_path=temp_db_path, apply=True, verbose=False)
        # Only the WS row (id=3) survives.
        assert _fill_ids(temp_db_path) == {3}

    @pytest.mark.asyncio
    async def test_apply_idempotent(self, temp_db_path):
        _seed_fill(temp_db_path, id=1, source="binance_ws",
                   ts=BASE_MS)
        _seed_fill(temp_db_path, id=2, source="exchange_history_backfill",
                   ts=BASE_MS + 500)
        run_dedup(db_path=temp_db_path, apply=True, verbose=False)
        # Second apply: nothing left to delete.
        result2 = run_dedup(db_path=temp_db_path, apply=True, verbose=False)
        assert result2["groups"] == 0
        assert result2["deleted_ids"] == []
        assert _fill_ids(temp_db_path) == {1}


class TestRunDedupFilters:
    @pytest.mark.asyncio
    async def test_account_id_filter_restricts_scope(self, temp_db_path):
        # Account 1 has a dup; account 2 also has a dup. Filter to 1.
        _seed_fill(temp_db_path, id=1, source="binance_ws",
                   ts=BASE_MS, account_id=1)
        _seed_fill(temp_db_path, id=2, source="exchange_history_backfill",
                   ts=BASE_MS + 500, account_id=1)
        _seed_fill(temp_db_path, id=3, source="binance_ws",
                   ts=BASE_MS, account_id=2)
        _seed_fill(temp_db_path, id=4, source="exchange_history_backfill",
                   ts=BASE_MS + 500, account_id=2)
        result = run_dedup(
            db_path=temp_db_path, apply=True, account_id=1,
            verbose=False,
        )
        # Only account 1's dup deleted.
        assert result["deleted_ids"] == [2]
        assert _fill_ids(temp_db_path) == {1, 3, 4}

    @pytest.mark.asyncio
    async def test_symbol_filter_restricts_scope(self, temp_db_path):
        _seed_fill(temp_db_path, id=1, source="binance_ws",
                   ts=BASE_MS, symbol="BTCUSDT")
        _seed_fill(temp_db_path, id=2, source="exchange_history_backfill",
                   ts=BASE_MS + 500, symbol="BTCUSDT")
        _seed_fill(temp_db_path, id=3, source="binance_ws",
                   ts=BASE_MS, symbol="ETHUSDT", price=3000.0)
        _seed_fill(temp_db_path, id=4, source="exchange_history_backfill",
                   ts=BASE_MS + 500, symbol="ETHUSDT", price=3000.0)
        result = run_dedup(
            db_path=temp_db_path, apply=True, symbol="BTCUSDT",
            verbose=False,
        )
        # Only the BTCUSDT dup deleted.
        assert result["deleted_ids"] == [2]
        assert _fill_ids(temp_db_path) == {1, 3, 4}


class TestRunDedupUnknownSource:
    @pytest.mark.asyncio
    async def test_unknown_source_group_flagged_in_summary(self, temp_db_path):
        _seed_fill(temp_db_path, id=1, source="future_exchange_adapter",
                   ts=BASE_MS)
        _seed_fill(temp_db_path, id=2, source="binance_ws",
                   ts=BASE_MS + 500)
        result = run_dedup(
            db_path=temp_db_path, apply=False, verbose=False,
        )
        assert result["unknown_source_groups"] == 1
        # Unknown source loses to ws; deletion would target id=1.
        assert result["deleted_ids"] == [1]


class TestSourcePriorityConstants:
    """Pin the constants — Phase 0.0.2's backfill writes
    ``exchange_history_backfill``; future callers may import these."""

    def test_known_sources_have_priorities(self):
        for src in ("binance_ws", "binance_rest", "exchange_history_backfill"):
            assert src in SOURCE_PRIORITY

    def test_unknown_priority_is_99(self):
        assert UNKNOWN_PRIORITY == 99
