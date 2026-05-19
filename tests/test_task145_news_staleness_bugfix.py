"""
Task 145 regression tests — FE-LOW-027 (News-staleness dead-code
bugfix + audit calibration).

Bug: `core/monitoring.py:331` (pre-Task-144) queried `FROM news` —
a table that does not exist. The schema defines `news_items`
(`core/database.py:316`). The inline try/except silently swallowed
the resulting OperationalError, making the news-feed-staleness
health check dead code since whenever the typo was introduced.

Task 144 (Phase 6 db._conn refactor) preserved the typo byte-for-
byte to keep refactor + bugfix orthogonal, and recorded the bug as
a latent observation.

Task 145 (this) fixes the typo + narrows the try/except:
  - SQL: `FROM news` → `FROM news_items`
  - except: now logs warning instead of silently returning None.

The narrowing-to-log preserves the "don't crash monitoring on a
flaky DB" property of the original swallow, but breaks the "fail
silent forever" property. Future regressions surface in logs.

Run: pytest tests/test_task145_news_staleness_bugfix.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
import aiosqlite


# ── Source pins ─────────────────────────────────────────────────────────────

class TestHelperUsesCorrectTableName:
    """The helper must reference `news_items`, not `news`. Pin the
    SQL string so a future copy-paste regression is caught."""

    def test_helper_queries_news_items(self):
        """Pin the SQL string in executing code. Scope by selecting
        only the line that calls `self._conn.execute(` — avoids
        false-positive matches against docstring text that mentions
        the historical bug."""
        src = Path("core/db_news.py").read_text(encoding="utf-8")
        idx = src.find("async def get_latest_news_timestamp")
        assert idx > 0
        end = src.find("\n    async def ", idx + 10)
        body = src[idx:end] if end > 0 else src[idx:idx + 2000]
        # Find the executing SQL line — the string-literal arg to
        # self._conn.execute(...). Look for the FROM clause on a
        # line that doesn't start with """ (skips docstring).
        exec_idx = body.find("self._conn.execute(")
        assert exec_idx > 0, "execute call not found in helper"
        # The next ~200 chars contain the SQL string literal
        sql_window = body[exec_idx:exec_idx + 400]
        assert "FROM news_items" in sql_window, (
            f"FE-LOW-027 regression: helper SQL does not target "
            f"news_items. Window: {sql_window!r}"
        )
        # Defensive: ensure no bare `FROM news"` (closing quote)
        # appears in the executing SQL — would indicate the typo
        # was reintroduced.
        assert "FROM news\"" not in sql_window and "FROM news'" not in sql_window

    def test_helper_does_not_swallow_silently(self):
        """The pre-Task-145 `except Exception: return None` silently
        swallowed errors. Task 145 narrows to log-and-return. Pin
        that a log call lives in the except branch."""
        src = Path("core/db_news.py").read_text(encoding="utf-8")
        idx = src.find("async def get_latest_news_timestamp")
        end = src.find("\n    async def ", idx + 10)
        body = src[idx:end] if end > 0 else src[idx:idx + 2000]
        # Should call log.warning (or log.error) in the except branch
        assert "log.warning(" in body or "log.error(" in body, (
            "FE-LOW-027: get_latest_news_timestamp must log on "
            "exception instead of silently swallowing. Silent catch "
            "hid the FROM-news typo for an unknown duration."
        )

    def test_fe_low_027_anchor_present(self):
        for path in ("core/db_news.py", "core/monitoring.py"):
            src = Path(path).read_text(encoding="utf-8")
            assert "FE-LOW-027" in src or "Task 145" in src, (
                f"FE-LOW-027 / Task 145 anchor missing in {path}"
            )


# ── Behavior-identical test against in-memory news_items table ──────────────

@pytest_asyncio.fixture
async def db_with_news():
    """Minimal harness — NewsMixin against an in-memory DB with the
    schema-correct news_items table."""
    from core.db_news import NewsMixin

    class _TestDB(NewsMixin):
        def __init__(self, conn):
            self._conn = conn

    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    # Match the actual schema from core/database.py:316
    await conn.executescript(
        """
        CREATE TABLE news_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            external_id TEXT NOT NULL,
            headline TEXT NOT NULL,
            published_at TEXT NOT NULL,
            UNIQUE(source, external_id)
        );
        """
    )
    await conn.commit()
    yield _TestDB(conn)
    await conn.close()


class TestHelperReturnsMaxFromNewsItems:
    """The bug fix: with `news_items` populated, helper returns
    MAX(published_at). Pre-fix this returned None unconditionally
    (silent OperationalError on missing `news` table)."""

    @pytest.mark.asyncio
    async def test_returns_max_published_at(self, db_with_news):
        db = db_with_news
        await db._conn.executemany(
            "INSERT INTO news_items (source, external_id, headline, published_at) "
            "VALUES (?, ?, ?, ?)",
            [
                ("fh", "1", "h1", "2026-05-19T10:00:00"),
                ("fh", "2", "h2", "2026-05-19T15:30:00"),  # MAX
                ("fh", "3", "h3", "2026-05-19T12:15:00"),
            ],
        )
        await db._conn.commit()
        result = await db.get_latest_news_timestamp()
        assert result == "2026-05-19T15:30:00", (
            "FE-LOW-027 fix verification: helper must return MAX "
            "published_at from news_items. Pre-fix returned None due "
            "to FROM-news typo + silent except."
        )

    @pytest.mark.asyncio
    async def test_returns_none_when_news_items_empty(self, db_with_news):
        """Empty table → MAX() returns NULL → helper returns None.
        Distinct from the pre-fix 'always None due to typo' shape."""
        assert await db_with_news.get_latest_news_timestamp() is None


# ── Loud-on-failure behavior ────────────────────────────────────────────────

class TestHelperLogsOnFailure:
    """If a future regression breaks the query (e.g., schema drift),
    the helper logs a warning instead of returning None silently."""

    @pytest.mark.asyncio
    async def test_logs_warning_when_table_missing(self, caplog):
        """Reproduce the pre-fix failure mode (missing table) and
        confirm it now produces a log entry."""
        from core.db_news import NewsMixin
        import logging as _logging

        class _TestDB(NewsMixin):
            def __init__(self, conn):
                self._conn = conn

        conn = await aiosqlite.connect(":memory:")
        # Deliberately do NOT create news_items — repro the pre-fix
        # "table missing" failure
        db = _TestDB(conn)
        try:
            with caplog.at_level(_logging.WARNING, logger="database"):
                result = await db.get_latest_news_timestamp()
            assert result is None, (
                "Returns None on failure (preserves don't-crash-"
                "monitoring property)"
            )
            # The log must mention the helper name OR the failure shape
            warning_messages = [
                r.getMessage() for r in caplog.records
                if r.levelno >= _logging.WARNING
            ]
            assert any(
                "get_latest_news_timestamp" in msg or "news-staleness" in msg
                for msg in warning_messages
            ), (
                f"FE-LOW-027: helper must log on failure. Captured "
                f"warnings: {warning_messages!r}"
            )
        finally:
            await conn.close()


# ── End-to-end: the monitoring check transitions from dead → live ──────────

class TestMonitoringCheckNoLongerDeadCode:
    """The whole point of FE-LOW-027: with the helper fixed, the
    news-feed-staleness MonitoringEvent can actually fire for stale
    feeds. Pin the integration shape — `_check_news_feed_health` is
    now reachable code (not silently early-returning on missing-
    table OperationalError)."""

    def test_news_feed_health_calls_helper(self):
        src = Path("core/monitoring.py").read_text(encoding="utf-8")
        idx = src.find("async def _check_news_feed_health")
        end = src.find("\n    async def ", idx + 10)
        body = src[idx:end] if end > 0 else src[idx:idx + 2000]
        # The check must route through the helper
        assert "db.get_latest_news_timestamp()" in body

    def test_news_feed_health_no_inline_select(self):
        """Anti-regression — don't reintroduce the inline SELECT MAX
        path that originally had the typo."""
        src = Path("core/monitoring.py").read_text(encoding="utf-8")
        idx = src.find("async def _check_news_feed_health")
        end = src.find("\n    async def ", idx + 10)
        body = src[idx:end] if end > 0 else src[idx:idx + 2000]
        assert "SELECT MAX" not in body, (
            "Inline SELECT MAX shouldn't reappear — go through the "
            "helper (which now has the correct table name + logging)."
        )
        assert "db._conn.execute(" not in body
