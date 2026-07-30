"""
Task 104a regression tests for HIGH-027 backend.

HIGH-027 backend scope:
- Add per-account link_window_seconds (default 6h = 21600s) to accounts table.
- Add per-pretrade link_window_seconds_override (nullable) to pre_trade_log.
- compute_exec_match accepts fill_ts_ms + pretrade_ts_ms + account window;
  hard-rejects (returns None) candidates past the effective window.
- Effective window: pretrade.link_window_seconds_override (if set, non-NULL)
  else account_link_window_seconds.
- get_exec_link_status threads the new args through and reports
  past-window matches as 'unlinked'.
- Caller updates in api/routes_orders.py (2 sites).

Frontend (settings UI, per-calc override input, live countdown) is
deferred to Task 104b. HIGH-027 stays OPEN until 104b lands.

Run: pytest tests/test_task104a_exec_link_window.py -v
"""
from __future__ import annotations

import asyncio
import inspect
import sqlite3

import pytest


# ── compute_exec_match window logic ──────────────────────────────────────────

class TestComputeExecMatchWindow:
    """Direct unit tests on the new window check in compute_exec_match."""

    def _pair(self, match_price: float = 100.0):
        """Build a fill/pretrade pair where the price matches under
        EXEC_LINK_PRICE_TOL. Returns (fill, pretrade)."""
        fill = {"price": match_price, "calc_id": "c1"}
        pretrade = {"id": 1, "average": match_price, "effective_entry": match_price}
        return fill, pretrade

    def test_match_within_window_succeeds(self):
        """Sanity: fill 1 h after pretrade, 6 h window → match."""
        from core.exec_link import compute_exec_match
        fill, pretrade = self._pair()
        pretrade_ts_ms = 1_700_000_000_000
        fill_ts_ms = pretrade_ts_ms + 3600 * 1000  # +1 h
        r = compute_exec_match(
            fill, pretrade, order_type="LIMIT",
            fill_ts_ms=fill_ts_ms, pretrade_ts_ms=pretrade_ts_ms,
            account_link_window_seconds=21600,
        )
        assert r is not None, "match within window should not be rejected"
        assert r.auto_link is True

    def test_match_past_window_rejected(self):
        """Load-bearing: fill 8 h after pretrade, 6 h window → None."""
        from core.exec_link import compute_exec_match
        fill, pretrade = self._pair()
        pretrade_ts_ms = 1_700_000_000_000
        fill_ts_ms = pretrade_ts_ms + 8 * 3600 * 1000  # +8 h
        r = compute_exec_match(
            fill, pretrade, order_type="LIMIT",
            fill_ts_ms=fill_ts_ms, pretrade_ts_ms=pretrade_ts_ms,
            account_link_window_seconds=21600,
        )
        assert r is None, (
            "HIGH-027 regression: 8h-stale pretrade should be hard-rejected. "
            f"Got {r!r}"
        )

    def test_per_calc_override_takes_precedence(self):
        """Override 24 h beats account default 6 h: a 12 h fill matches when
        override is set and rejects when it isn't."""
        from core.exec_link import compute_exec_match
        fill, _ = self._pair()
        pretrade_ts_ms = 1_700_000_000_000
        fill_ts_ms = pretrade_ts_ms + 12 * 3600 * 1000  # +12 h

        # Without override: rejected (12h > 6h)
        pre_no_override = {"id": 1, "average": 100.0, "effective_entry": 100.0,
                           "link_window_seconds_override": None}
        r1 = compute_exec_match(
            fill, pre_no_override, order_type="LIMIT",
            fill_ts_ms=fill_ts_ms, pretrade_ts_ms=pretrade_ts_ms,
            account_link_window_seconds=21600,
        )
        assert r1 is None, "without override 12h > 6h should reject"

        # With 24h override: accepted
        pre_override = {"id": 1, "average": 100.0, "effective_entry": 100.0,
                        "link_window_seconds_override": 86400}
        r2 = compute_exec_match(
            fill, pre_override, order_type="LIMIT",
            fill_ts_ms=fill_ts_ms, pretrade_ts_ms=pretrade_ts_ms,
            account_link_window_seconds=21600,
        )
        assert r2 is not None, "override 24h should allow 12h fill"
        assert r2.auto_link is True

    def test_zero_window_rejects_all_past_fills(self):
        """Boundary: zero window means any non-zero elapsed rejects. Defense
        against a misconfigured zero default that would otherwise behave
        like 'always match' under naive code."""
        from core.exec_link import compute_exec_match
        fill, pretrade = self._pair()
        pretrade_ts_ms = 1_700_000_000_000
        fill_ts_ms = pretrade_ts_ms + 1  # +1 ms
        r = compute_exec_match(
            fill, pretrade, order_type="LIMIT",
            fill_ts_ms=fill_ts_ms, pretrade_ts_ms=pretrade_ts_ms,
            account_link_window_seconds=0,
        )
        assert r is None

    def test_zero_elapsed_at_window_boundary_accepts(self):
        """Boundary: elapsed exactly == window means NOT past-window
        (the test is `elapsed > window`, strict)."""
        from core.exec_link import compute_exec_match
        fill, pretrade = self._pair()
        pretrade_ts_ms = 1_700_000_000_000
        fill_ts_ms = pretrade_ts_ms + 21600 * 1000  # +6h exactly
        r = compute_exec_match(
            fill, pretrade, order_type="LIMIT",
            fill_ts_ms=fill_ts_ms, pretrade_ts_ms=pretrade_ts_ms,
            account_link_window_seconds=21600,
        )
        assert r is not None, "elapsed == window should still match (strict >)"

    def test_missing_timestamps_skips_window_check(self):
        """Backwards-compat: callers that don't pass timestamps must still
        get the pre-fix behavior (no reject)."""
        from core.exec_link import compute_exec_match
        fill, pretrade = self._pair()
        r = compute_exec_match(fill, pretrade, order_type="LIMIT")
        assert r is not None, "without timestamps, window check should not fire"
        assert r.auto_link is True

    def test_only_fill_ts_provided_skips_check(self):
        """Partial-args case: providing only one of the two timestamps
        must still skip the window check (both required)."""
        from core.exec_link import compute_exec_match
        fill, pretrade = self._pair()
        r = compute_exec_match(
            fill, pretrade, order_type="LIMIT",
            fill_ts_ms=1_700_000_000_000,
            # pretrade_ts_ms intentionally omitted
            account_link_window_seconds=21600,
        )
        assert r is not None

    def test_default_window_constant_is_21600(self):
        """Pin the DEFAULT_LINK_WINDOW_SECONDS constant. Surfaces to UI in
        Task 104b and to the schema migration in this task — drift between
        the three would be confusing."""
        from core.exec_link import DEFAULT_LINK_WINDOW_SECONDS
        assert DEFAULT_LINK_WINDOW_SECONDS == 21600  # 6 hours


# ── get_exec_link_status integration ────────────────────────────────────────

class TestGetExecLinkStatusWindow:
    """The status helper forwards window args; a past-window match comes
    back from compute_exec_match as None and gets reported as 'unlinked'."""

    def test_past_window_reports_unlinked(self):
        from core.exec_link import get_exec_link_status
        fill = {"price": 100.0, "calc_id": "c1"}
        pretrade = {"id": 1, "average": 100.0, "effective_entry": 100.0}
        pretrade_ts_ms = 1_700_000_000_000
        fill_ts_ms = pretrade_ts_ms + 8 * 3600 * 1000

        status, count = get_exec_link_status(
            fill, pretrade, order_type="LIMIT",
            fill_ts_ms=fill_ts_ms, pretrade_ts_ms=pretrade_ts_ms,
            account_link_window_seconds=21600,
        )
        assert status == "unlinked"
        assert count == 0

    def test_confirmed_fill_bypasses_window_check(self):
        """An operator-confirmed link is authoritative — the window check
        should NOT override a confirmation. Important: ops can manually
        link a fill to an old pretrade and have that stick."""
        from core.exec_link import get_exec_link_status
        fill = {"price": 100.0, "calc_id": "c1", "exec_link_confirmed": 1}
        pretrade = {"id": 1, "average": 100.0, "effective_entry": 100.0}
        pretrade_ts_ms = 1_700_000_000_000
        fill_ts_ms = pretrade_ts_ms + 24 * 3600 * 1000  # 24h stale

        status, count = get_exec_link_status(
            fill, pretrade, order_type="LIMIT",
            fill_ts_ms=fill_ts_ms, pretrade_ts_ms=pretrade_ts_ms,
            account_link_window_seconds=21600,
        )
        assert status == "linked"
        assert count == 1

    def test_within_window_reports_linked(self):
        from core.exec_link import get_exec_link_status
        fill = {"price": 100.0, "calc_id": "c1"}
        pretrade = {"id": 1, "average": 100.0, "effective_entry": 100.0}
        pretrade_ts_ms = 1_700_000_000_000
        fill_ts_ms = pretrade_ts_ms + 60 * 1000  # +1 min

        status, count = get_exec_link_status(
            fill, pretrade, order_type="LIMIT",
            fill_ts_ms=fill_ts_ms, pretrade_ts_ms=pretrade_ts_ms,
            account_link_window_seconds=21600,
        )
        assert status == "linked"
        assert count == 1


# ── Schema pins ──────────────────────────────────────────────────────────────

class TestSchemaPins:
    """The two new columns must exist with correct defaults on a fresh
    DB AND must be added by the migration list on a legacy DB."""

    @pytest.fixture
    def fresh_db(self, tmp_path):
        """Run the full initialize() against a tmp DB and yield the path."""
        from core.database import DatabaseManager

        db_path = str(tmp_path / "fresh.db")
        mgr = DatabaseManager(path=db_path)
        asyncio.run(mgr.initialize())
        asyncio.run(mgr._conn.close())
        return db_path

    def test_accounts_has_link_window_seconds_with_default_21600(self, fresh_db):
        conn = sqlite3.connect(fresh_db)
        try:
            cols = conn.execute("PRAGMA table_info(accounts)").fetchall()
            # cols: list of (cid, name, type, notnull, dflt_value, pk)
            link_col = [c for c in cols if c[1] == "link_window_seconds"]
            assert link_col, (
                f"HIGH-027 schema regression: accounts.link_window_seconds "
                f"column missing. Columns: {[c[1] for c in cols]}"
            )
            (cid, name, ctype, notnull, dflt, pk) = link_col[0]
            assert ctype.upper() == "INTEGER"
            assert notnull == 1, "must be NOT NULL"
            assert int(str(dflt)) == 21600, (
                f"Default must be 21600 (6h); got {dflt!r}"
            )
        finally:
            conn.close()

    def test_pre_trade_log_has_link_window_seconds_override_nullable(self, fresh_db):
        conn = sqlite3.connect(fresh_db)
        try:
            cols = conn.execute("PRAGMA table_info(pre_trade_log)").fetchall()
            override_col = [c for c in cols
                            if c[1] == "link_window_seconds_override"]
            assert override_col, (
                "HIGH-027 schema regression: "
                "pre_trade_log.link_window_seconds_override column missing."
            )
            (cid, name, ctype, notnull, dflt, pk) = override_col[0]
            assert ctype.upper() == "INTEGER"
            assert notnull == 0, "must be nullable (default NULL)"
            # dflt is "NULL" string or actual None depending on sqlite version;
            # accept either
            assert dflt is None or str(dflt).upper() == "NULL"
        finally:
            conn.close()

    def test_legacy_db_migration_adds_columns(self, tmp_path):
        """Drop a legacy-shape DB (accounts + pre_trade_log without the new
        columns), run initialize(), verify the ALTER migrations added them."""
        db_path = str(tmp_path / "legacy.db")
        # Construct a minimal legacy DB matching the pre-104a CREATE TABLE
        # for the two affected tables.
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                exchange TEXT NOT NULL DEFAULT 'binance',
                market_type TEXT NOT NULL DEFAULT 'future',
                api_key_enc TEXT NOT NULL DEFAULT '',
                api_secret_enc TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                broker_account_id TEXT
            );
            CREATE TABLE pre_trade_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                ticker TEXT NOT NULL,
                average REAL NOT NULL DEFAULT 0
            );
            INSERT INTO accounts (name) VALUES ('legacy-acct');
            INSERT INTO pre_trade_log (timestamp, ticker) VALUES ('2026-01-01T00:00:00+00:00', 'BTCUSDT');
        """)
        conn.commit()
        conn.close()

        from core.database import DatabaseManager
        mgr = DatabaseManager(path=db_path)
        asyncio.run(mgr.initialize())
        asyncio.run(mgr._conn.close())

        # Verify columns now exist with correct defaults on the pre-existing rows
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT link_window_seconds FROM accounts WHERE name='legacy-acct'"
            ).fetchone()
            assert row is not None
            assert row[0] == 21600, (
                f"Legacy account should inherit default 21600; got {row[0]}"
            )

            row = conn.execute(
                "SELECT link_window_seconds_override FROM pre_trade_log "
                "WHERE ticker='BTCUSDT'"
            ).fetchone()
            assert row is not None
            assert row[0] is None, (
                f"Legacy pretrade override should be NULL; got {row[0]!r}"
            )
        finally:
            conn.close()


# ── Caller wiring pins ──────────────────────────────────────────────────────

class TestCallerWiring:
    """Source pins: routes_orders.py calls compute_exec_match and
    get_exec_link_status with the new timestamp + window kwargs."""

    def test_routes_orders_passes_window_kwargs(self):
        # (Fragments slim-down 2026-07-30: the exec_link comparison panel
        # retired with its template, so compute_exec_match no longer has a
        # routes_orders call site — get_exec_link_status in the
        # position_fills drawer is the surviving one.)
        from api import routes_orders
        src = inspect.getsource(routes_orders)
        assert src.count("fill_ts_ms=") >= 1, (
            "HIGH-027 wiring regression: expected fill_ts_ms kwarg passed "
            "at the get_exec_link_status call site."
        )
        assert src.count("pretrade_ts_ms=") >= 1
        assert src.count("account_link_window_seconds=") >= 1

    def test_routes_orders_defines_account_link_window_helper(self):
        from api import routes_orders
        assert hasattr(routes_orders, "_account_link_window_seconds")
        assert hasattr(routes_orders, "_pretrade_ts_to_ms")
