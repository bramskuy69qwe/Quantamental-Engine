"""
Task 143 regression tests — HIGH-002 Phase 6 Platform Bridge refactor (2/3).

Replaces 8 `db._conn.execute(...)` direct-access locations in
`core/platform_bridge.py::handle_historical_fill` with 5 public helper
methods on ExchangeMixin. (Audit's "8 locations" was accurate this
time — Task 142's count was off-by-one, but Task 143 matches exactly.)

5 helpers covering 8 sites (commits folded into mutation helpers):

  Site | Op                                  | Helper
  -----+-------------------------------------+--------------------------
  L300 | SELECT REALIZED_PNL row for merge   | find_realized_pnl_for_merge
  L313 | UPDATE merge aggregate              | merge_realized_pnl_into
  L322 | commit                              | (folded into helper above)
  L335 | SELECT MAX(time) nearest before     | find_nearest_open_time_before
  L343 | UPDATE open_time                    | set_close_fill_open_time
  L351 | SELECT MIN(time) fallback           | find_earliest_open_time
  L358 | UPDATE open_time (fallback)         | set_close_fill_open_time (reuse)
  L363 | commit                              | (folded into helper above)

Behavior-identical: each helper exercised against an in-memory
aiosqlite DB with the minimal exchange_history schema. Round-trip
behavior preserved against the original SQL byte-for-byte (including
the WHERE `(open_time=0 OR open_time=?)` guard on set_close_fill_open_time).

Source-pin: `db._conn.execute(`/`commit(` no longer in executing code
in `core/platform_bridge.py` (anchor comments allowed).

Run: pytest tests/test_task143_phase6_bridge.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
import aiosqlite


# ── Source-pin: db._conn removed from executing code ────────────────────────

class TestNoDbConnInExecutingCode:
    def test_no_db_conn_execute_in_executing_code(self):
        src = Path("core/platform_bridge.py").read_text(encoding="utf-8")
        bad_lines = []
        for ln, line in enumerate(src.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            if "db._conn.execute(" in line or "db._conn.commit(" in line:
                bad_lines.append((ln, line.strip()))
        assert not bad_lines, (
            f"HIGH-002 regression: db._conn direct access back in "
            f"core/platform_bridge.py at {bad_lines!r}."
        )

    def test_anchor_comments_reference_high_002(self):
        src = Path("core/platform_bridge.py").read_text(encoding="utf-8")
        assert "HIGH-002" in src and "Task 143" in src


# ── Helpers added to ExchangeMixin (source-pin) ─────────────────────────────

class TestHelpersAddedToExchangeMixin:
    def test_all_5_helpers_present(self):
        src = Path("core/db_exchange.py").read_text(encoding="utf-8")
        for name in (
            "find_realized_pnl_for_merge",
            "merge_realized_pnl_into",
            "find_nearest_open_time_before",
            "find_earliest_open_time",
            "set_close_fill_open_time",
        ):
            assert f"async def {name}" in src, f"missing helper: {name}"

    def test_anchor_block_present(self):
        """Block-level anchor comment groups the 5 new helpers so a
        future maintainer browsing the mixin sees their shared
        provenance + purpose."""
        src = Path("core/db_exchange.py").read_text(encoding="utf-8")
        assert "Task 143" in src
        assert "platform_bridge" in src


# ── Behavior-identical fixtures: in-memory exchange_history ─────────────────

@pytest_asyncio.fixture
async def db_with_exchange_history():
    """Build a minimal ExchangeMixin-bearing object against aiosqlite."""
    from core.db_exchange import ExchangeMixin

    class _TestDB(ExchangeMixin):
        def __init__(self, conn):
            self._conn = conn

    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row

    await conn.executescript(
        """
        CREATE TABLE exchange_history (
            account_id INTEGER NOT NULL,
            trade_key TEXT PRIMARY KEY,
            time INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            income_type TEXT NOT NULL,
            income REAL DEFAULT 0,
            direction TEXT DEFAULT '',
            entry_price REAL DEFAULT 0,
            exit_price REAL DEFAULT 0,
            qty REAL DEFAULT 0,
            notional REAL DEFAULT 0,
            open_time INTEGER DEFAULT 0,
            fee REAL DEFAULT 0,
            asset TEXT DEFAULT '',
            mfe REAL DEFAULT 0,
            mae REAL DEFAULT 0,
            backfill_completed INTEGER DEFAULT 0
        );
        """
    )
    await conn.commit()
    yield _TestDB(conn)
    await conn.close()


# ── find_realized_pnl_for_merge ─────────────────────────────────────────────

class TestFindRealizedPnlForMerge:
    @pytest.mark.asyncio
    async def test_finds_matching_row(self, db_with_exchange_history):
        db = db_with_exchange_history
        await db._conn.execute(
            "INSERT INTO exchange_history "
            "(account_id, trade_key, time, symbol, income_type, income, direction, qty, fee, exit_price, notional) "
            "VALUES (1, 'tk1', 1234, 'BTCUSDT', 'REALIZED_PNL', 5.0, 'long', 0.1, 0.01, 60000, 6000)"
        )
        await db._conn.commit()
        row = await db.find_realized_pnl_for_merge(
            time_ms=1234, symbol="BTCUSDT", direction="long", account_id=1,
        )
        assert row is not None
        assert row["trade_key"] == "tk1"
        assert row["qty"] == 0.1

    @pytest.mark.asyncio
    async def test_returns_none_when_no_match(self, db_with_exchange_history):
        row = await db_with_exchange_history.find_realized_pnl_for_merge(
            time_ms=9999, symbol="ETHUSDT", direction="short", account_id=1,
        )
        assert row is None

    @pytest.mark.asyncio
    async def test_account_scoping_preserved(self, db_with_exchange_history):
        """Row exists for account 1; query as account 2 returns None."""
        db = db_with_exchange_history
        await db._conn.execute(
            "INSERT INTO exchange_history "
            "(account_id, trade_key, time, symbol, income_type, direction) "
            "VALUES (1, 'tk1', 1234, 'BTC', 'REALIZED_PNL', 'long')"
        )
        await db._conn.commit()
        row = await db.find_realized_pnl_for_merge(
            time_ms=1234, symbol="BTC", direction="long", account_id=2,
        )
        assert row is None

    @pytest.mark.asyncio
    async def test_only_realized_pnl_type(self, db_with_exchange_history):
        """OPEN-type rows must NOT match — filter pins to REALIZED_PNL."""
        db = db_with_exchange_history
        await db._conn.execute(
            "INSERT INTO exchange_history "
            "(account_id, trade_key, time, symbol, income_type, direction) "
            "VALUES (1, 'tk1', 1234, 'BTC', 'OPEN', 'long')"
        )
        await db._conn.commit()
        row = await db.find_realized_pnl_for_merge(
            time_ms=1234, symbol="BTC", direction="long", account_id=1,
        )
        assert row is None


# ── merge_realized_pnl_into ─────────────────────────────────────────────────

class TestMergeRealizedPnlInto:
    @pytest.mark.asyncio
    async def test_aggregates_deltas_correctly(self, db_with_exchange_history):
        db = db_with_exchange_history
        await db._conn.execute(
            "INSERT INTO exchange_history "
            "(account_id, trade_key, time, symbol, income_type, income, qty, fee, exit_price, notional) "
            "VALUES (1, 'tk1', 1, 'BTC', 'REALIZED_PNL', 10.0, 0.5, 0.05, 60000, 30000)"
        )
        await db._conn.commit()
        await db.merge_realized_pnl_into(
            trade_key="tk1",
            income_delta=2.0,
            new_total_qty=0.7,         # 0.5 + 0.2
            fee_delta=0.02,
            wavg_exit=60100.0,
            notional_delta=12020.0,    # 60100 * 0.2
        )
        async with db._conn.execute(
            "SELECT income, qty, fee, exit_price, notional FROM exchange_history WHERE trade_key=?",
            ("tk1",),
        ) as cur:
            row = await cur.fetchone()
        # income/fee/notional: additive deltas; qty/exit_price: replacements
        assert row["income"] == pytest.approx(12.0)   # 10.0 + 2.0
        assert row["qty"] == pytest.approx(0.7)       # replaced
        assert row["fee"] == pytest.approx(0.07)      # 0.05 + 0.02
        assert row["exit_price"] == pytest.approx(60100.0)  # replaced
        assert row["notional"] == pytest.approx(42020.0)    # 30000 + 12020


# ── find_nearest_open_time_before ───────────────────────────────────────────

class TestFindNearestOpenTimeBefore:
    @pytest.mark.asyncio
    async def test_returns_max_within_window(self, db_with_exchange_history):
        db = db_with_exchange_history
        # Three OPEN rows; one inside window, one outside (older), one after `before_ms`
        now = 1_000_000
        seven_days = 604_800_000
        await db._conn.executemany(
            "INSERT INTO exchange_history (account_id, trade_key, time, symbol, income_type) VALUES (?, ?, ?, 'BTC', 'OPEN')",
            [
                (1, "tk_old",  now - seven_days - 1, ),  # outside window
                (1, "tk_in1",  now - 1000, ),            # in window
                (1, "tk_in2",  now - 500,  ),            # in window — newest before now
                (1, "tk_after", now + 100, ),            # after `before_ms` — excluded
            ],
        )
        await db._conn.commit()
        result = await db.find_nearest_open_time_before(
            symbol="BTC", account_id=1, before_ms=now,
        )
        assert result == now - 500  # newest qualifying

    @pytest.mark.asyncio
    async def test_returns_none_when_nothing_qualifies(self, db_with_exchange_history):
        db = db_with_exchange_history
        result = await db.find_nearest_open_time_before(
            symbol="BTC", account_id=1, before_ms=1_000_000,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_excludes_other_accounts(self, db_with_exchange_history):
        db = db_with_exchange_history
        await db._conn.execute(
            "INSERT INTO exchange_history (account_id, trade_key, time, symbol, income_type) "
            "VALUES (2, 'tk_other', 999, 'BTC', 'OPEN')"
        )
        await db._conn.commit()
        result = await db.find_nearest_open_time_before(
            symbol="BTC", account_id=1, before_ms=1_000_000,
        )
        assert result is None


# ── find_earliest_open_time ─────────────────────────────────────────────────

class TestFindEarliestOpenTime:
    @pytest.mark.asyncio
    async def test_returns_min_open_time(self, db_with_exchange_history):
        db = db_with_exchange_history
        await db._conn.executemany(
            "INSERT INTO exchange_history (account_id, trade_key, time, symbol, income_type) VALUES (?, ?, ?, 'BTC', 'OPEN')",
            [(1, "tk1", 500, ), (1, "tk2", 100, ), (1, "tk3", 1000, )],
        )
        await db._conn.commit()
        assert await db.find_earliest_open_time(symbol="BTC", account_id=1) == 100

    @pytest.mark.asyncio
    async def test_returns_none_when_no_open_fills(self, db_with_exchange_history):
        assert await db_with_exchange_history.find_earliest_open_time(
            symbol="BTC", account_id=1,
        ) is None


# ── set_close_fill_open_time ────────────────────────────────────────────────

class TestSetCloseFillOpenTime:
    @pytest.mark.asyncio
    async def test_sets_open_time_when_zero(self, db_with_exchange_history):
        db = db_with_exchange_history
        await db._conn.execute(
            "INSERT INTO exchange_history "
            "(account_id, trade_key, time, symbol, income_type, open_time) "
            "VALUES (1, 'tk1', 2000, 'BTC', 'REALIZED_PNL', 0)"
        )
        await db._conn.commit()
        await db.set_close_fill_open_time(
            trade_key="tk1", open_time=1500, current_close_ts=2000,
        )
        async with db._conn.execute(
            "SELECT open_time FROM exchange_history WHERE trade_key=?", ("tk1",),
        ) as cur:
            row = await cur.fetchone()
        assert row["open_time"] == 1500

    @pytest.mark.asyncio
    async def test_replaces_placeholder_equal_to_close_ts(self, db_with_exchange_history):
        """The guard `(open_time=0 OR open_time=?)` with second-arg=current_close_ts
        means a row whose open_time was placeholder-set to the close ts gets replaced."""
        db = db_with_exchange_history
        await db._conn.execute(
            "INSERT INTO exchange_history "
            "(account_id, trade_key, time, symbol, income_type, open_time) "
            "VALUES (1, 'tk1', 2000, 'BTC', 'REALIZED_PNL', 2000)"
        )
        await db._conn.commit()
        await db.set_close_fill_open_time(
            trade_key="tk1", open_time=1500, current_close_ts=2000,
        )
        async with db._conn.execute(
            "SELECT open_time FROM exchange_history WHERE trade_key=?", ("tk1",),
        ) as cur:
            row = await cur.fetchone()
        assert row["open_time"] == 1500

    @pytest.mark.asyncio
    async def test_does_not_overwrite_real_open_time(self, db_with_exchange_history):
        """If open_time is non-zero AND not equal to current_close_ts, it's a
        previously-resolved real value — must NOT be overwritten."""
        db = db_with_exchange_history
        await db._conn.execute(
            "INSERT INTO exchange_history "
            "(account_id, trade_key, time, symbol, income_type, open_time) "
            "VALUES (1, 'tk1', 2000, 'BTC', 'REALIZED_PNL', 1800)"
        )
        await db._conn.commit()
        await db.set_close_fill_open_time(
            trade_key="tk1", open_time=1500, current_close_ts=2000,
        )
        async with db._conn.execute(
            "SELECT open_time FROM exchange_history WHERE trade_key=?", ("tk1",),
        ) as cur:
            row = await cur.fetchone()
        # Should still be 1800 (the previously-resolved real value)
        assert row["open_time"] == 1800
