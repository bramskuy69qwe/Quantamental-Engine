"""
Task 142 regression tests — HIGH-002 Phase 6 Routes layer refactor (1/3).

Replaces 7 `db._conn.execute(...)` direct-access locations in
`api/routes_orders.py` with public helper methods on DatabaseManager.

5 new helpers + 1 reuse cover the 7 sites:

  Site (route L#) | Query                              | Helper
  ----------------+------------------------------------+----------------
  L155 (helper)   | accounts.link_window_seconds       | (new) SettingsMixin.get_account_link_window_seconds
  L191 (drawer)   | closed_positions terminal key      | (new) OrdersMixin.get_closed_position_terminal_key
  L254 (exec)     | fills WHERE id=? AND account_id=?  | (new) OrdersMixin.get_fill_by_id
  L262 (exec)     | pre_trade_log WHERE calc_id=?      | (new) OrdersMixin.get_pretrade_log_by_calc_id
  L271 (exec)     | orders.order_type by exchange_id   | (reuse) OrdersMixin.get_order_by_exchange_id
  L321+L327       | UPDATE fills SET exec_link_*       | (new) OrdersMixin.confirm_fill_exec_link

Behavior-identical pin (per helper): run helper against a synthetic
in-memory schema with known rows; assert returned shape matches what
the original `_conn.execute` would have produced.

Source-pin: `db._conn.execute(` / `db._conn.commit(` no longer appear
in executing code in `api/routes_orders.py` (anchor comments
referencing the old pattern are allowed).

Run: pytest tests/test_task142_phase6_routes.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import pytest_asyncio
import aiosqlite


# ── Source-pin: db._conn removed from executing code ────────────────────────

class TestNoDbConnInExecutingCode:
    """HIGH-002 (Phase 6 routes): `db._conn` direct access must be
    gone from executing JS/Python in `api/routes_orders.py`. Anchor
    comments referencing the old pattern are allowed (they're
    documentation, not executing code)."""

    def test_no_db_conn_execute_in_executing_code(self):
        src = Path("api/routes_orders.py").read_text(encoding="utf-8")
        bad_lines = []
        for ln, line in enumerate(src.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            if "db._conn.execute(" in line or "db._conn.commit(" in line:
                bad_lines.append((ln, line.strip()))
        assert not bad_lines, (
            f"HIGH-002 regression: db._conn direct access back in "
            f"routes_orders.py at {bad_lines!r}. Use public helpers."
        )

    def test_anchor_comments_reference_high_002(self):
        """Anchor comments at the 4 sites refer to HIGH-002 / Task 142
        so future maintainers know why the indirection exists."""
        src = Path("api/routes_orders.py").read_text(encoding="utf-8")
        assert "HIGH-002" in src and "Task 142" in src


# ── Helpers added to mixins (source-pin) ────────────────────────────────────

class TestHelpersAddedToMixins:
    """Source-pin that the 5 new helper methods exist on the right
    mixins. Verifies the refactor's static surface."""

    def test_settings_mixin_has_account_link_window_helper(self):
        src = Path("core/db_settings.py").read_text(encoding="utf-8")
        assert "async def get_account_link_window_seconds" in src
        # Anchor present
        idx = src.find("async def get_account_link_window_seconds")
        end = src.find("\n    async def ", idx + 10)
        body = src[idx:end] if end > 0 else src[idx:idx + 1500]
        assert "HIGH-002" in body or "Task 142" in body

    def test_orders_mixin_has_4_new_helpers(self):
        src = Path("core/db_orders.py").read_text(encoding="utf-8")
        for name in (
            "get_closed_position_terminal_key",
            "get_fill_by_id",
            "get_pretrade_log_by_calc_id",
            "confirm_fill_exec_link",
        ):
            assert f"async def {name}" in src, f"missing helper: {name}"

    def test_order_by_exchange_id_still_exists(self):
        """The L271 site reuses existing `get_order_by_exchange_id`.
        Pin its existence so a future cleanup doesn't accidentally
        delete it under the assumption it's unused."""
        src = Path("core/db_orders.py").read_text(encoding="utf-8")
        assert "async def get_order_by_exchange_id" in src


# ── Behavior-identical fixtures: in-memory DB with the actual mixins ────────

@pytest_asyncio.fixture
async def db_with_schema():
    """Build a DatabaseManager-shaped object against an in-memory
    aiosqlite DB with the minimal schema needed for these helpers."""
    from core.db_settings import SettingsMixin
    from core.db_orders import OrdersMixin

    class _TestDB(OrdersMixin, SettingsMixin):
        def __init__(self, conn):
            self._conn = conn

    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row

    await conn.executescript(
        """
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY,
            name TEXT,
            link_window_seconds INTEGER
        );
        CREATE TABLE closed_positions (
            id INTEGER PRIMARY KEY,
            account_id INTEGER,
            terminal_position_id TEXT,
            symbol TEXT,
            direction TEXT
        );
        CREATE TABLE fills (
            id INTEGER PRIMARY KEY,
            account_id INTEGER,
            calc_id TEXT,
            exchange_order_id TEXT,
            exec_link_confirmed INTEGER DEFAULT 0,
            exec_link_confirmed_at TEXT,
            exec_link_confirmed_by TEXT
        );
        CREATE TABLE pre_trade_log (
            calc_id TEXT,
            ticker TEXT,
            timestamp TEXT
        );
        CREATE TABLE orders (
            account_id INTEGER,
            exchange_order_id TEXT,
            order_type TEXT
        );
        """
    )
    await conn.commit()

    yield _TestDB(conn)

    await conn.close()


# ── Behavior-identical tests per helper ─────────────────────────────────────

class TestGetAccountLinkWindowSeconds:
    @pytest.mark.asyncio
    async def test_returns_int_when_set(self, db_with_schema):
        db = db_with_schema
        await db._conn.execute(
            "INSERT INTO accounts (id, name, link_window_seconds) VALUES (1, 'A', 7200)"
        )
        await db._conn.commit()
        assert await db.get_account_link_window_seconds(1) == 7200

    @pytest.mark.asyncio
    async def test_returns_none_when_row_missing(self, db_with_schema):
        db = db_with_schema
        assert await db.get_account_link_window_seconds(999) is None

    @pytest.mark.asyncio
    async def test_returns_none_when_column_null(self, db_with_schema):
        db = db_with_schema
        await db._conn.execute(
            "INSERT INTO accounts (id, name, link_window_seconds) VALUES (2, 'B', NULL)"
        )
        await db._conn.commit()
        assert await db.get_account_link_window_seconds(2) is None


class TestGetClosedPositionTerminalKey:
    @pytest.mark.asyncio
    async def test_returns_composite_key(self, db_with_schema):
        db = db_with_schema
        await db._conn.execute(
            "INSERT INTO closed_positions (id, account_id, terminal_position_id, "
            "symbol, direction) VALUES (10, 1, 'tpid-xyz', 'BTCUSDT', 'long')"
        )
        await db._conn.commit()
        result = await db.get_closed_position_terminal_key(10)
        assert result == {
            "terminal_position_id": "tpid-xyz",
            "symbol": "BTCUSDT",
            "direction": "long",
        }

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self, db_with_schema):
        assert await db_with_schema.get_closed_position_terminal_key(999) is None


class TestGetFillById:
    @pytest.mark.asyncio
    async def test_returns_full_row(self, db_with_schema):
        db = db_with_schema
        await db._conn.execute(
            "INSERT INTO fills (id, account_id, calc_id) VALUES (5, 1, 'calc-abc')"
        )
        await db._conn.commit()
        result = await db.get_fill_by_id(5, 1)
        assert result is not None
        assert result["id"] == 5
        assert result["account_id"] == 1
        assert result["calc_id"] == "calc-abc"

    @pytest.mark.asyncio
    async def test_returns_none_for_wrong_account(self, db_with_schema):
        """Account-scoping is preserved — fill belongs to acct 1,
        querying as acct 2 returns None."""
        db = db_with_schema
        await db._conn.execute(
            "INSERT INTO fills (id, account_id, calc_id) VALUES (5, 1, 'calc-abc')"
        )
        await db._conn.commit()
        assert await db.get_fill_by_id(5, 2) is None


class TestGetPretradeLogByCalcId:
    @pytest.mark.asyncio
    async def test_returns_row(self, db_with_schema):
        db = db_with_schema
        await db._conn.execute(
            "INSERT INTO pre_trade_log (calc_id, ticker, timestamp) "
            "VALUES ('calc-xyz', 'ETHUSDT', '2026-05-19T12:00:00')"
        )
        await db._conn.commit()
        result = await db.get_pretrade_log_by_calc_id("calc-xyz")
        assert result is not None
        assert result["ticker"] == "ETHUSDT"

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_calc_id(self, db_with_schema):
        assert await db_with_schema.get_pretrade_log_by_calc_id("nope") is None

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_calc_id(self, db_with_schema):
        """Empty/falsy calc_id short-circuits (avoid spurious SQL)."""
        assert await db_with_schema.get_pretrade_log_by_calc_id("") is None


class TestConfirmFillExecLink:
    @pytest.mark.asyncio
    async def test_sets_confirmed_fields(self, db_with_schema):
        db = db_with_schema
        await db._conn.execute(
            "INSERT INTO fills (id, account_id, calc_id) VALUES (8, 1, 'calc')"
        )
        await db._conn.commit()
        await db.confirm_fill_exec_link(8)
        async with db._conn.execute(
            "SELECT exec_link_confirmed, exec_link_confirmed_by FROM fills WHERE id=?",
            (8,),
        ) as cur:
            row = await cur.fetchone()
        assert row["exec_link_confirmed"] == 1
        assert row["exec_link_confirmed_by"] == "user"

    @pytest.mark.asyncio
    async def test_noop_on_falsy_fill_id(self, db_with_schema):
        """fill_id=0 is the Form(0) default — should silently no-op
        rather than UPDATE all rows (which would be catastrophic)."""
        db = db_with_schema
        await db._conn.execute(
            "INSERT INTO fills (id, account_id) VALUES (1, 1), (2, 1)"
        )
        await db._conn.commit()
        await db.confirm_fill_exec_link(0)
        # Neither row should be marked confirmed
        async with db._conn.execute(
            "SELECT id FROM fills WHERE exec_link_confirmed=1"
        ) as cur:
            rows = await cur.fetchall()
        assert rows == []
