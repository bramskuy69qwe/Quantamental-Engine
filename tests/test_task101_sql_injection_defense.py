"""
Task 101 regression tests for HIGH-011 + MED-003 + MED-022.

HIGH-011 — core/db_trades.py _paginated_query: filter column names must be
  whitelisted before being f-string-interpolated into the WHERE clause.
MED-003 — route handlers must validate sort_by + sort_dir before forwarding
  to the DB layer. Visible 400 on invalid input rather than silent fallback.
MED-022 — core/db_orders.py mark_stale_orders_canceled: LIKE prefix must be
  parameterized via ? placeholder rather than f-string-interpolated with
  single-quote literal wrapping.

Pattern: tests include CONCRETE INJECTION PAYLOADS that would have
exploited the pre-fix code. Failure-before-fix is demonstrated by
asserting the validator rejects payloads that the unsafe pre-fix code
would have executed.

Run: pytest tests/test_task101_sql_injection_defense.py -v
"""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── validate_sort_params unit tests ──────────────────────────────────────────

class TestValidateSortParams:
    """MED-003: route-level helper rejects invalid sort_by / sort_dir."""

    def test_valid_column_and_dir_passes(self):
        from core.sql_safety import validate_sort_params
        cols = frozenset({"created_at_ms", "symbol"})
        result = validate_sort_params("created_at_ms", "DESC", cols)
        assert result == ("created_at_ms", "DESC")

    def test_lowercase_sort_dir_uppercased(self):
        from core.sql_safety import validate_sort_params
        cols = frozenset({"created_at_ms"})
        result = validate_sort_params("created_at_ms", "asc", cols)
        assert result == ("created_at_ms", "ASC")

    def test_unknown_column_raises_400(self):
        from core.sql_safety import validate_sort_params
        from fastapi import HTTPException
        cols = frozenset({"created_at_ms"})
        with pytest.raises(HTTPException) as ei:
            validate_sort_params("not_a_real_col", "DESC", cols)
        assert ei.value.status_code == 400
        assert "invalid sort column" in ei.value.detail.lower()

    def test_invalid_sort_dir_raises_400(self):
        from core.sql_safety import validate_sort_params
        from fastapi import HTTPException
        cols = frozenset({"created_at_ms"})
        with pytest.raises(HTTPException) as ei:
            validate_sort_params("created_at_ms", "SIDEWAYS", cols)
        assert ei.value.status_code == 400
        assert "invalid sort direction" in ei.value.detail.lower()

    def test_injection_payload_as_sort_column_rejected(self):
        """Concrete exploitation attempt: sort_by carries a SQL injection
        payload. Must be rejected with 400 before reaching the DB layer."""
        from core.sql_safety import validate_sort_params
        from fastapi import HTTPException
        cols = frozenset({"created_at_ms"})
        payload = "created_at_ms; DROP TABLE orders--"
        with pytest.raises(HTTPException) as ei:
            validate_sort_params(payload, "DESC", cols)
        assert ei.value.status_code == 400
        # Make sure the literal payload appears in the error detail so the
        # operator sees what was rejected (security-log-friendly).
        assert "DROP" in ei.value.detail or "drop" in ei.value.detail.lower() or \
               payload[:20] in ei.value.detail

    def test_injection_payload_as_sort_dir_rejected(self):
        """Even if sort_by is valid, a poisoned sort_dir must be rejected."""
        from core.sql_safety import validate_sort_params
        from fastapi import HTTPException
        cols = frozenset({"created_at_ms"})
        with pytest.raises(HTTPException) as ei:
            validate_sort_params("created_at_ms", "DESC; DELETE FROM orders--", cols)
        assert ei.value.status_code == 400

    def test_empty_string_sort_dir_rejected(self):
        """Anti-over-correction: empty string must NOT be treated as a default
        (raises 400 instead of silently picking DESC)."""
        from core.sql_safety import validate_sort_params
        from fastapi import HTTPException
        cols = frozenset({"created_at_ms"})
        with pytest.raises(HTTPException):
            validate_sort_params("created_at_ms", "", cols)


# ── HIGH-011: _paginated_query filter whitelist ──────────────────────────────

class TestPaginatedQueryFilterWhitelist:
    """HIGH-011: _paginated_query must reject any filter column not in
    TradesMixin._ALLOWED_FILTER_COLS."""

    def test_allowed_filter_cols_constant_exists(self):
        from core.db_trades import TradesMixin
        assert hasattr(TradesMixin, "_ALLOWED_FILTER_COLS"), (
            "HIGH-011 regression: _ALLOWED_FILTER_COLS constant missing."
        )
        # Current callers depend on these three keys
        for required in ("ticker", "side", "direction"):
            assert required in TradesMixin._ALLOWED_FILTER_COLS, (
                f"HIGH-011 regression: {required!r} dropped from _ALLOWED_FILTER_COLS — "
                "existing callers (query_pre_trade_log / query_execution_log / "
                "query_trade_history) will break."
            )

    @pytest.mark.asyncio
    async def test_unsafe_filter_col_raises_value_error(self):
        """Concrete payload: filter dict key carries SQL injection. Must
        raise ValueError before f-string-interpolation."""
        from core.db_trades import TradesMixin

        # Build a minimal subject — give it a mocked _conn so the
        # validator path runs before any DB call.
        mixin = TradesMixin.__new__(TradesMixin)
        mixin._conn = MagicMock()

        injection_key = "ticker; DROP TABLE pre_trade_log--"
        with pytest.raises(ValueError) as ei:
            await mixin._paginated_query(
                table="pre_trade_log",
                ts_col="timestamp",
                allowed_sort=TradesMixin._PRE_TRADE_SORT_COLS,
                date_from=None, date_to=None, search=None,
                filters={injection_key: "BTCUSDT"},
                sort_by="timestamp", sort_dir="DESC",
                page=1, per_page=20, account_id=1,
            )
        msg = str(ei.value)
        assert "unsafe filter column" in msg
        assert injection_key in msg

    @pytest.mark.asyncio
    async def test_known_safe_filter_col_passes_validation(self):
        """Functionality preservation: ticker filter still works."""
        from core.db_trades import TradesMixin

        mixin = TradesMixin.__new__(TradesMixin)
        # Mock _conn so we can capture the SQL without a real DB
        cur = AsyncMock()
        cur.fetchone = AsyncMock(return_value=(0,))
        cur.fetchall = AsyncMock(return_value=[])
        # _conn.execute returns an async context manager
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=cur)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mixin._conn = MagicMock()
        mixin._conn.execute = MagicMock(return_value=ctx)

        # Should NOT raise; should execute two SQL statements (count + data)
        rows, total = await mixin._paginated_query(
            table="pre_trade_log",
            ts_col="timestamp",
            allowed_sort=TradesMixin._PRE_TRADE_SORT_COLS,
            date_from=None, date_to=None, search=None,
            filters={"ticker": "BTCUSDT", "side": "LONG"},
            sort_by="timestamp", sort_dir="DESC",
            page=1, per_page=20, account_id=1,
        )
        assert rows == []
        assert total == 0
        # Two execute calls (count + data SQL)
        assert mixin._conn.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_filter_value_skipped_without_validation(self):
        """Anti-regression: empty filter values (None or '') short-circuit
        the `if val` guard, never reach the whitelist check. Important so
        that filters={"ticker": None} doesn't trigger spurious raise."""
        from core.db_trades import TradesMixin

        mixin = TradesMixin.__new__(TradesMixin)
        cur = AsyncMock()
        cur.fetchone = AsyncMock(return_value=(0,))
        cur.fetchall = AsyncMock(return_value=[])
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=cur)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mixin._conn = MagicMock()
        mixin._conn.execute = MagicMock(return_value=ctx)

        # Even though "unsafe_col" is not in the whitelist, val=None skips it
        await mixin._paginated_query(
            table="pre_trade_log",
            ts_col="timestamp",
            allowed_sort=TradesMixin._PRE_TRADE_SORT_COLS,
            date_from=None, date_to=None, search=None,
            filters={"unsafe_col_but_no_value": None, "ticker": "BTC"},
            sort_by="timestamp", sort_dir="DESC",
            page=1, per_page=20, account_id=1,
        )
        # No raise = success


# ── MED-022: mark_stale_orders_canceled LIKE parameterization ────────────────

class TestStaleOrdersLikeParameterized:
    """MED-022: scope_clause must use ? placeholder. The pre-fix form
    interpolated the prefix with single-quote literal wrapping, so a single
    quote in the prefix terminated the literal and injected SQL."""

    def test_source_contains_no_fstring_like_interpolation(self):
        """Source pin: the f-string LIKE pattern must be gone."""
        from core.db_orders import OrdersMixin
        src = inspect.getsource(OrdersMixin.mark_stale_orders_canceled)
        # The original vulnerable form:
        #   f" AND exchange_order_id NOT LIKE '{exclude_prefix}%'"
        # Anything that contains both "LIKE '" and "{exclude_prefix}" together
        # would re-introduce the bug.
        assert "LIKE '{" not in src, (
            "MED-022 regression: scope_clause f-string-interpolates an "
            "identifier into the LIKE pattern; reintroduces the injection "
            "vector. Use ? placeholder instead."
        )
        # And confirm the placeholder form is in place
        assert "NOT LIKE ?" in src and "LIKE ?" in src, (
            "MED-022 regression: scope_clause no longer uses ? placeholder."
        )

    @pytest.mark.asyncio
    async def test_exclude_prefix_passed_as_param_not_interpolated(self):
        """Capture-execute-args test: invoke with a prefix containing a
        single quote and verify the SQL string has no quoted literal of
        the prefix; the prefix appears in the params list instead."""
        from core.db_orders import OrdersMixin

        mixin = OrdersMixin.__new__(OrdersMixin)
        # Mock _conn with execute() that captures the SQL + params
        captured = {}
        cur = AsyncMock()
        cur.rowcount = 0
        async def _exec(sql, params):
            captured["sql"] = sql
            captured["params"] = list(params)
            return cur
        mixin._conn = MagicMock()
        mixin._conn.execute = _exec
        mixin._conn.commit = AsyncMock()

        # Injection-shaped prefix: ' OR 1=1 --
        injection_prefix = "' OR 1=1 --"
        await mixin.mark_stale_orders_canceled(
            account_id=1, active_ids=[], allow_cancel_all=True,
            exclude_prefix=injection_prefix,
        )

        # Pre-fix the SQL would have contained the literal injection prefix
        # within single quotes. Post-fix the SQL has '?' placeholder only.
        assert injection_prefix not in captured["sql"], (
            "MED-022 regression: SQL string contains the raw prefix value; "
            "injection vector reintroduced."
        )
        # The prefix appears in params with the % suffix appended
        assert any(injection_prefix + "%" == p for p in captured["params"]), (
            f"prefix not in params list: {captured['params']!r}"
        )

    @pytest.mark.asyncio
    async def test_only_prefix_also_parameterized(self):
        """Same protection for the only_prefix branch."""
        from core.db_orders import OrdersMixin

        mixin = OrdersMixin.__new__(OrdersMixin)
        captured = {}
        cur = AsyncMock()
        cur.rowcount = 0
        async def _exec(sql, params):
            captured["sql"] = sql
            captured["params"] = list(params)
            return cur
        mixin._conn = MagicMock()
        mixin._conn.execute = _exec
        mixin._conn.commit = AsyncMock()

        injection_prefix = "' OR 1=1 --"
        await mixin.mark_stale_orders_canceled(
            account_id=1, active_ids=[], allow_cancel_all=True,
            only_prefix=injection_prefix,
        )
        assert injection_prefix not in captured["sql"]
        assert any(injection_prefix + "%" == p for p in captured["params"])

    @pytest.mark.asyncio
    async def test_normal_prefix_unchanged_behavior(self):
        """Functionality preservation: 'algo:' prefix (the actual caller
        usage) still works."""
        from core.db_orders import OrdersMixin

        mixin = OrdersMixin.__new__(OrdersMixin)
        captured = {}
        cur = AsyncMock()
        cur.rowcount = 0
        async def _exec(sql, params):
            captured["sql"] = sql
            captured["params"] = list(params)
            return cur
        mixin._conn = MagicMock()
        mixin._conn.execute = _exec
        mixin._conn.commit = AsyncMock()

        await mixin.mark_stale_orders_canceled(
            account_id=42, active_ids=["1", "2"], exclude_prefix="algo:",
        )
        # Params: [now_ms, account_id, "1", "2", "algo:%"]
        assert captured["params"][-1] == "algo:%"
        assert "NOT LIKE ?" in captured["sql"]


# ── MED-003: route handlers wire validate_sort_params ────────────────────────

class TestRouteWiring:
    """MED-003 wiring pins: source-pin pattern. Each affected route module
    must import validate_sort_params and call it in every sortable handler.
    """

    def test_routes_orders_imports_validator(self):
        from api import routes_orders
        src = inspect.getsource(routes_orders)
        assert "from core.sql_safety import validate_sort_params" in src

    def test_routes_history_imports_validator(self):
        from api import routes_history
        src = inspect.getsource(routes_history)
        assert "from core.sql_safety import validate_sort_params" in src

    def test_routes_orders_calls_validator_in_each_handler(self):
        """4 sortable handlers in routes_orders.py — all must call validator."""
        from api import routes_orders
        src = inspect.getsource(routes_orders)
        # The exact call shape we expect
        call_count = src.count("validate_sort_params(sort_by, sort_dir,")
        assert call_count == 4, (
            f"MED-003 wiring regression: expected 4 validate_sort_params calls "
            f"in routes_orders.py (frag_open_orders, frag_order_history, "
            f"frag_fills, frag_closed_positions); found {call_count}."
        )

    def test_routes_history_calls_validator_in_each_handler(self):
        """3 sortable handlers in routes_history.py — all must call validator."""
        from api import routes_history
        src = inspect.getsource(routes_history)
        call_count = src.count("validate_sort_params(sort_by, sort_dir,")
        assert call_count == 3, (
            f"MED-003 wiring regression: expected 3 validate_sort_params calls "
            f"in routes_history.py (frag_history_exchange, frag_history_pre_trade, "
            f"frag_history_trade_history); found {call_count}."
        )


# ── End-to-end via TestClient: injection payload returns 400 ─────────────────

class TestRoutesRejectInjection:
    """End-to-end: a HTTP request carrying a SQL injection payload in
    sort_by must produce 400, not 200 with a silently-defaulted sort."""

    @pytest.fixture(scope="class")
    def client(self):
        import os
        import sys
        import tempfile

        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

        _tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        _tmp_db.close()
        os.environ.setdefault("QRE_DB_PATH", _tmp_db.name)
        import config
        config.DB_PATH = _tmp_db.name

        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app) as c:
            yield c
        try:
            os.unlink(_tmp_db.name)
            for ext in ("-wal", "-shm"):
                p = _tmp_db.name + ext
                if os.path.exists(p):
                    os.unlink(p)
        except OSError:
            pass

    def test_injection_in_sort_by_returns_400(self, client):
        """Concrete exploitation attempt: sort_by carries a DROP TABLE
        payload. Pre-fix the route would have silently fallen back to the
        default sort and returned 200 (masking the abuse). Post-fix returns
        400 with a visible "invalid sort column" detail."""
        payload = "created_at_ms; DROP TABLE orders--"
        resp = client.get(f"/fragments/history/open_orders?sort_by={payload}")
        assert resp.status_code == 400, (
            f"Expected 400 for injection payload; got {resp.status_code}: "
            f"{resp.text[:200]}"
        )

    def test_injection_in_sort_dir_returns_400(self, client):
        """sort_dir injection — even with valid sort_by."""
        resp = client.get(
            "/fragments/history/open_orders"
            "?sort_by=created_at_ms&sort_dir=DESC; DELETE FROM orders--"
        )
        assert resp.status_code == 400

    def test_valid_sort_request_returns_200(self, client):
        """Functionality preservation: legitimate sort still works."""
        resp = client.get(
            "/fragments/history/open_orders?sort_by=created_at_ms&sort_dir=DESC"
        )
        assert resp.status_code == 200
