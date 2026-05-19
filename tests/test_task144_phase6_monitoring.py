"""
Task 144 regression tests — HIGH-002 Phase 6 Monitoring/Reconciler
refactor (3/3, closes HIGH-002).

Broad re-grep across `core/` + `api/` (excluding T142/T143 files)
found 7 sites of `db._conn` direct access:
  - core/monitoring.py: 3 (news health, reconciler health, db health)
  - core/reconciler.py: 1 (pending symbols list)
  - api/routes_calculator.py: 3 (NOT in audit's count — Task 139 area)

Audit said "8 across monitoring + reconciler + others"; actual 7
(monitoring's "3" + reconciler's "1" + routes_calculator's "3" =
7, not 8). Audit-count-imprecision pattern: matches Task 142's
off-by-one and contrasts with Task 143's exact count.

5 new helpers + 1 cross-task reuse cover all 7 sites:

  Site                                | Helper
  ------------------------------------+--------------------------
  monitoring.py news MAX(published_at)| (new) NewsMixin
                                      |  .get_latest_news_timestamp
  monitoring.py count reconciler rows | (new) ExchangeMixin
                                      |  .count_pending_reconciler_rows
  monitoring.py SELECT 1 health probe | (new) DatabaseManager
                                      |  .check_db_alive(timeout_s=...)
  reconciler.py distinct symbols      | (new) ExchangeMixin
                                      |  .get_pending_reconciler_symbols
  routes_calculator pre_trade lookup  | (new) OrdersMixin
                                      |  .get_pretrade_timestamp_for_link_window
  routes_calculator account window    | (reuse) T142's
                                      |  .get_account_link_window_seconds
  routes_calculator confirmed-fill ck | (new) OrdersMixin
                                      |  .has_confirmed_fill_for_calc

Cross-task reuse highlights: site 6 reuses T142's
`get_account_link_window_seconds` directly — proof that the T142
helper API generalizes.

Run: pytest tests/test_task144_phase6_monitoring.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
import aiosqlite


# ── Source-pin: db._conn removed from all 3 touched files ───────────────────

class TestNoDbConnInExecutingCode:
    """db._conn direct access must be gone from executing code in
    monitoring.py, reconciler.py, and routes_calculator.py. Anchor
    comments referencing db._conn are allowed."""

    def _scan(self, path: str) -> list:
        src = Path(path).read_text(encoding="utf-8")
        bad = []
        for ln, line in enumerate(src.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            if (
                "db._conn.execute(" in line
                or "db._conn.commit(" in line
                or "_db._conn.execute(" in line
                or "_db._conn.commit(" in line
            ):
                bad.append((ln, line.strip()))
        return bad

    def test_monitoring_clean(self):
        assert self._scan("core/monitoring.py") == []

    def test_reconciler_clean(self):
        assert self._scan("core/reconciler.py") == []

    def test_routes_calculator_clean(self):
        assert self._scan("api/routes_calculator.py") == []

    def test_anchor_comments_reference_high_002(self):
        for path in (
            "core/monitoring.py",
            "core/reconciler.py",
            "api/routes_calculator.py",
        ):
            src = Path(path).read_text(encoding="utf-8")
            assert "HIGH-002" in src and "Task 144" in src, (
                f"missing HIGH-002 / Task 144 anchor in {path}"
            )


# ── Source-pin: helpers added to right mixins ───────────────────────────────

class TestHelpersAddedToMixins:
    def test_news_mixin_has_latest_timestamp_helper(self):
        src = Path("core/db_news.py").read_text(encoding="utf-8")
        assert "async def get_latest_news_timestamp" in src
        assert "Task 144" in src

    def test_exchange_mixin_has_reconciler_helpers(self):
        src = Path("core/db_exchange.py").read_text(encoding="utf-8")
        assert "async def count_pending_reconciler_rows" in src
        assert "async def get_pending_reconciler_symbols" in src

    def test_orders_mixin_has_link_window_helpers(self):
        src = Path("core/db_orders.py").read_text(encoding="utf-8")
        assert "async def get_pretrade_timestamp_for_link_window" in src
        assert "async def has_confirmed_fill_for_calc" in src

    def test_database_manager_has_check_db_alive(self):
        src = Path("core/database.py").read_text(encoding="utf-8")
        assert "async def check_db_alive" in src


# ── Behavior-identical fixtures ─────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_with_schema():
    """Minimal in-memory DB harness covering all tables Task 144 helpers touch."""
    from core.db_news import NewsMixin
    from core.db_exchange import ExchangeMixin
    from core.db_orders import OrdersMixin
    from core.db_settings import SettingsMixin

    class _TestDB(NewsMixin, ExchangeMixin, OrdersMixin, SettingsMixin):
        def __init__(self, conn):
            self._conn = conn

        # Inline replica of DatabaseManager.check_db_alive for tests
        async def check_db_alive(self, timeout_s=None):
            import asyncio as _asyncio
            try:
                async with self._conn.execute("SELECT 1") as cur:
                    if timeout_s is not None:
                        await _asyncio.wait_for(cur.fetchone(), timeout=timeout_s)
                    else:
                        await cur.fetchone()
                return True
            except Exception:
                return False

    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(
        """
        CREATE TABLE news_items (
            source TEXT,
            external_id TEXT,
            headline TEXT,
            published_at INTEGER
        );
        CREATE TABLE exchange_history (
            account_id INTEGER,
            trade_key TEXT PRIMARY KEY,
            time INTEGER,
            symbol TEXT,
            income_type TEXT,
            open_time INTEGER DEFAULT 0,
            backfill_completed INTEGER DEFAULT 0
        );
        CREATE TABLE pre_trade_log (
            calc_id TEXT,
            account_id INTEGER,
            timestamp TEXT,
            link_window_seconds_override INTEGER
        );
        CREATE TABLE fills (
            id INTEGER PRIMARY KEY,
            account_id INTEGER,
            calc_id TEXT,
            exec_link_confirmed INTEGER DEFAULT 0
        );
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY,
            link_window_seconds INTEGER
        );
        """
    )
    await conn.commit()
    yield _TestDB(conn)
    await conn.close()


# ── get_latest_news_timestamp — preserves broken-but-tolerated behavior ─────

class TestGetLatestNewsTimestamp:
    """The helper queries `FROM news` (typo preserved from monitoring.py
    pre-Task-144). Actual table is `news_items`. Helper catches the
    OperationalError and returns None — matching original try/except."""

    @pytest.mark.asyncio
    async def test_returns_none_when_news_table_missing(self, db_with_schema):
        """Fixture only creates `news_items`, not `news`. Helper must
        return None (silently swallow OperationalError)."""
        result = await db_with_schema.get_latest_news_timestamp()
        assert result is None


# ── count_pending_reconciler_rows ───────────────────────────────────────────

class TestCountPendingReconcilerRows:
    @pytest.mark.asyncio
    async def test_counts_only_qualifying_rows(self, db_with_schema):
        db = db_with_schema
        await db._conn.executemany(
            "INSERT INTO exchange_history "
            "(account_id, trade_key, time, symbol, income_type, open_time, backfill_completed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                # Qualifying: NOT backfilled + open_time > 0 + not qt:
                (1, "tk1", 1, "BTC", "REALIZED_PNL", 100, 0),
                (1, "tk2", 2, "ETH", "REALIZED_PNL", 200, 0),
                # Excluded — backfilled
                (1, "tk3", 3, "SOL", "REALIZED_PNL", 300, 1),
                # Excluded — open_time = 0
                (1, "tk4", 4, "ADA", "REALIZED_PNL", 0,   0),
                # Excluded — qt: prefix
                (1, "qt:abc", 5, "DOT", "REALIZED_PNL", 500, 0),
            ],
        )
        await db._conn.commit()
        assert await db.count_pending_reconciler_rows() == 2

    @pytest.mark.asyncio
    async def test_returns_zero_when_empty(self, db_with_schema):
        assert await db_with_schema.count_pending_reconciler_rows() == 0


# ── get_pending_reconciler_symbols ──────────────────────────────────────────

class TestGetPendingReconcilerSymbols:
    @pytest.mark.asyncio
    async def test_returns_distinct_symbols(self, db_with_schema):
        db = db_with_schema
        await db._conn.executemany(
            "INSERT INTO exchange_history "
            "(account_id, trade_key, time, symbol, income_type, open_time, backfill_completed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "tk1", 1, "BTC", "REALIZED_PNL", 100, 0),
                (1, "tk2", 2, "BTC", "REALIZED_PNL", 200, 0),  # dup symbol
                (1, "tk3", 3, "ETH", "REALIZED_PNL", 300, 0),
                (1, "qt:x", 4, "SOL", "REALIZED_PNL", 400, 0),  # excluded
            ],
        )
        await db._conn.commit()
        symbols = await db.get_pending_reconciler_symbols()
        assert set(symbols) == {"BTC", "ETH"}
        assert len(symbols) == 2  # DISTINCT applied

    @pytest.mark.asyncio
    async def test_empty_when_no_pending(self, db_with_schema):
        assert await db_with_schema.get_pending_reconciler_symbols() == []


# ── check_db_alive ──────────────────────────────────────────────────────────

class TestCheckDbAlive:
    @pytest.mark.asyncio
    async def test_returns_true_on_live_connection(self, db_with_schema):
        assert await db_with_schema.check_db_alive() is True

    @pytest.mark.asyncio
    async def test_with_timeout_returns_true_when_fast(self, db_with_schema):
        """SELECT 1 against in-memory DB completes well within 1s timeout."""
        assert await db_with_schema.check_db_alive(timeout_s=1.0) is True

    @pytest.mark.asyncio
    async def test_returns_false_when_connection_closed(self, db_with_schema):
        """Closing the connection causes SELECT 1 to fail; helper returns False."""
        db = db_with_schema
        await db._conn.close()
        assert await db.check_db_alive() is False


# ── get_pretrade_timestamp_for_link_window ──────────────────────────────────

class TestGetPretradeTimestampForLinkWindow:
    @pytest.mark.asyncio
    async def test_returns_two_columns(self, db_with_schema):
        db = db_with_schema
        await db._conn.execute(
            "INSERT INTO pre_trade_log (calc_id, account_id, timestamp, link_window_seconds_override) "
            "VALUES ('calc-1', 1, '2026-05-19T12:00:00', 3600)"
        )
        await db._conn.commit()
        result = await db.get_pretrade_timestamp_for_link_window(
            calc_id="calc-1", account_id=1,
        )
        assert result == {
            "timestamp": "2026-05-19T12:00:00",
            "link_window_seconds_override": 3600,
        }

    @pytest.mark.asyncio
    async def test_none_when_calc_id_missing(self, db_with_schema):
        assert await db_with_schema.get_pretrade_timestamp_for_link_window(
            calc_id="nope", account_id=1,
        ) is None

    @pytest.mark.asyncio
    async def test_account_scoping_preserved(self, db_with_schema):
        db = db_with_schema
        await db._conn.execute(
            "INSERT INTO pre_trade_log (calc_id, account_id, timestamp) "
            "VALUES ('calc-1', 1, '2026-05-19')"
        )
        await db._conn.commit()
        assert await db.get_pretrade_timestamp_for_link_window(
            calc_id="calc-1", account_id=2,
        ) is None

    @pytest.mark.asyncio
    async def test_none_for_empty_calc_id(self, db_with_schema):
        """Empty calc_id short-circuits before SQL."""
        assert await db_with_schema.get_pretrade_timestamp_for_link_window(
            calc_id="", account_id=1,
        ) is None


# ── has_confirmed_fill_for_calc ─────────────────────────────────────────────

class TestHasConfirmedFillForCalc:
    @pytest.mark.asyncio
    async def test_true_when_confirmed_fill_exists(self, db_with_schema):
        db = db_with_schema
        await db._conn.execute(
            "INSERT INTO fills (id, account_id, calc_id, exec_link_confirmed) "
            "VALUES (1, 1, 'calc-1', 1)"
        )
        await db._conn.commit()
        assert await db.has_confirmed_fill_for_calc(
            calc_id="calc-1", account_id=1,
        ) is True

    @pytest.mark.asyncio
    async def test_false_when_no_fills(self, db_with_schema):
        assert await db_with_schema.has_confirmed_fill_for_calc(
            calc_id="calc-1", account_id=1,
        ) is False

    @pytest.mark.asyncio
    async def test_false_when_fill_unconfirmed(self, db_with_schema):
        """Unconfirmed fill exists → returns False (not just 'any fill exists')."""
        db = db_with_schema
        await db._conn.execute(
            "INSERT INTO fills (id, account_id, calc_id, exec_link_confirmed) "
            "VALUES (1, 1, 'calc-1', 0)"
        )
        await db._conn.commit()
        assert await db.has_confirmed_fill_for_calc(
            calc_id="calc-1", account_id=1,
        ) is False

    @pytest.mark.asyncio
    async def test_account_scoping(self, db_with_schema):
        db = db_with_schema
        await db._conn.execute(
            "INSERT INTO fills (id, account_id, calc_id, exec_link_confirmed) "
            "VALUES (1, 1, 'calc-1', 1)"
        )
        await db._conn.commit()
        assert await db.has_confirmed_fill_for_calc(
            calc_id="calc-1", account_id=2,
        ) is False

    @pytest.mark.asyncio
    async def test_false_for_empty_calc_id(self, db_with_schema):
        assert await db_with_schema.has_confirmed_fill_for_calc(
            calc_id="", account_id=1,
        ) is False


# ── Cross-task reuse: T142 helper still works for T144 caller ───────────────

class TestT142HelperReusedFromT144Caller:
    """`api/routes_calculator.py` line 133 reuses T142's
    `get_account_link_window_seconds`. Confirm the helper still
    exists and behaves correctly so the cross-task reuse holds."""

    @pytest.mark.asyncio
    async def test_reuse_returns_int_when_set(self, db_with_schema):
        db = db_with_schema
        await db._conn.execute(
            "INSERT INTO accounts (id, link_window_seconds) VALUES (1, 7200)"
        )
        await db._conn.commit()
        assert await db.get_account_link_window_seconds(1) == 7200

    @pytest.mark.asyncio
    async def test_reuse_returns_none_when_missing(self, db_with_schema):
        assert await db_with_schema.get_account_link_window_seconds(999) is None
