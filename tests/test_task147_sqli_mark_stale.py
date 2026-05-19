r"""
Task 147 regression tests — MED-022 SQL injection / wildcard escape
in `mark_stale_orders_canceled` LIKE clause.

History:
  - Pre-Task-101: LIKE clause built via f-string interpolation
    (`f" AND exchange_order_id NOT LIKE '{exclude_prefix}%'"`).
    Vulnerable to classic SQL injection if prefix is ever user-
    controlled.
  - Task 101: SQL injection portion fixed by replacing f-string
    with `?` placeholder. LIKE wildcards (`%`, `_`) in input were
    LEFT UNESCAPED; comment explicitly deferred the wildcard
    escape "out of scope for this fix" until a real consumer
    needed literal-match.
  - Task 147 (this): close the deferred wildcard-escape portion.
    Defense-in-depth — current callers pass hardcoded "algo:"
    only; the helper protects against future user-supplied
    prefixes containing `%` or `_`.

Fix: module-local `_escape_like(value)` helper + `ESCAPE '\\'`
clause on the LIKE WHERE-condition. Escapes `\`, `%`, `_` in that
order (backslash first prevents double-escape).

Run: pytest tests/test_task147_sqli_mark_stale.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
import aiosqlite


# ── Helper unit tests ───────────────────────────────────────────────────────

class TestEscapeLikeHelper:
    """The escape helper is module-local. Test its behavior directly."""

    def test_passthrough_for_safe_input(self):
        from core.db_orders import _escape_like
        assert _escape_like("algo:") == "algo:"
        assert _escape_like("plain") == "plain"

    def test_escapes_percent(self):
        from core.db_orders import _escape_like
        assert _escape_like("a%b") == "a\\%b"

    def test_escapes_underscore(self):
        from core.db_orders import _escape_like
        assert _escape_like("a_b") == "a\\_b"

    def test_escapes_backslash(self):
        from core.db_orders import _escape_like
        assert _escape_like("a\\b") == "a\\\\b"

    def test_backslash_processed_before_wildcards(self):
        r"""Order matters: if `%` were escaped first then `\`, we'd get
        `\\\\%` (double-escaped). Backslash first gives `\\\\\\%`
        which renders as `\\%` (correctly escaped, single level)."""
        from core.db_orders import _escape_like
        # Input: '%' → should become '\%', NOT '\\%' (which would be
        # "literal backslash + literal percent" in SQL LIKE).
        assert _escape_like("%") == "\\%"
        # Input: '\' → should become '\\' (single-level escape).
        assert _escape_like("\\") == "\\\\"

    def test_no_sql_injection_chars_special_treatment(self):
        """Quotes, semicolons, etc. are NOT LIKE wildcards — helper
        leaves them alone. (SQL injection via these chars is the
        Task 101 concern, addressed via `?` placeholder; this helper
        is wildcard-escape only.)"""
        from core.db_orders import _escape_like
        assert _escape_like("'; DROP TABLE--") == "'; DROP TABLE--"


# ── Source-pins ─────────────────────────────────────────────────────────────

class TestMarkStaleSourceShape:
    def test_escape_clause_present_in_both_branches(self):
        src = Path("core/db_orders.py").read_text(encoding="utf-8")
        idx = src.find("async def mark_stale_orders_canceled")
        end = src.find("\n    async def ", idx + 10)
        body = src[idx:end] if end > 0 else src[idx:idx + 4000]
        # Both LIKE branches must include the ESCAPE clause
        assert body.count("ESCAPE '\\\\'") >= 2, (
            f"MED-022 (T147): expected ESCAPE clause in both NOT LIKE "
            f"and LIKE branches. Found {body.count(chr(92)*2)} times."
        )

    def test_uses_escape_like_helper(self):
        src = Path("core/db_orders.py").read_text(encoding="utf-8")
        idx = src.find("async def mark_stale_orders_canceled")
        end = src.find("\n    async def ", idx + 10)
        body = src[idx:end] if end > 0 else src[idx:idx + 4000]
        assert "_escape_like(" in body, (
            "MED-022 (T147): _escape_like helper must be called on "
            "both exclude_prefix and only_prefix paths."
        )
        assert body.count("_escape_like(") >= 2

    def test_anchor_comment_references_task_147(self):
        src = Path("core/db_orders.py").read_text(encoding="utf-8")
        assert "Task 147" in src and "MED-022" in src


# ── Behavior-identical fixtures ─────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_with_orders():
    """Minimal harness — OrdersMixin against an in-memory DB with the
    orders table."""
    from core.db_orders import OrdersMixin

    class _TestDB(OrdersMixin):
        def __init__(self, conn):
            self._conn = conn

    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            exchange_order_id TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at_ms INTEGER DEFAULT 0
        );
        """
    )
    await conn.commit()
    yield _TestDB(conn)
    await conn.close()


# ── Wildcard-escape behavior tests ──────────────────────────────────────────

class TestWildcardLiteralMatching:
    """The fix's user-facing payoff: `%` and `_` in prefix match
    literally, not as wildcards."""

    @pytest.mark.asyncio
    async def test_percent_in_prefix_does_not_match_unintended_rows(
        self, db_with_orders,
    ):
        """Pre-T147: only_prefix='a%' would match ANY id starting
        with 'a' (because `%` after Python f-string concat acted as
        LIKE wildcard for any chars). Post-T147: matches only ids
        starting with the literal `a%`."""
        db = db_with_orders
        await db._conn.executemany(
            "INSERT INTO orders (account_id, exchange_order_id, status) "
            "VALUES (1, ?, 'new')",
            [
                ("algo:btc_001",),   # literally starts with "algo:"
                ("a%special",),      # literally starts with "a%"
                ("abc",),            # would have matched 'a%' as wildcard
                ("a_underscore",),   # also would match 'a_' as wildcard
            ],
        )
        await db._conn.commit()
        # only_prefix='a%' should now match ONLY 'a%special'
        canceled = await db.mark_stale_orders_canceled(
            account_id=1, active_ids=["non-existent"], only_prefix="a%",
        )
        assert canceled == 1, (
            f"only_prefix='a%' must literal-match only 'a%special'; "
            f"canceled {canceled} rows."
        )
        # Confirm exactly which row was canceled
        async with db._conn.execute(
            "SELECT exchange_order_id FROM orders WHERE status='canceled'"
        ) as cur:
            rows = [r[0] for r in await cur.fetchall()]
        assert rows == ["a%special"]

    @pytest.mark.asyncio
    async def test_underscore_in_prefix_does_not_match_unintended_rows(
        self, db_with_orders,
    ):
        """`_` is the LIKE single-char wildcard. Pre-T147 unescaped;
        post-T147 escaped via `\\_` + ESCAPE clause."""
        db = db_with_orders
        await db._conn.executemany(
            "INSERT INTO orders (account_id, exchange_order_id, status) "
            "VALUES (1, ?, 'new')",
            [
                ("x_y",),    # literally starts with "x_"
                ("xay",),    # would match 'x_' as wildcard
                ("xby",),    # would match 'x_' as wildcard
            ],
        )
        await db._conn.commit()
        canceled = await db.mark_stale_orders_canceled(
            account_id=1, active_ids=["non-existent"], only_prefix="x_",
        )
        assert canceled == 1
        async with db._conn.execute(
            "SELECT exchange_order_id FROM orders WHERE status='canceled'"
        ) as cur:
            rows = [r[0] for r in await cur.fetchall()]
        assert rows == ["x_y"]


# ── Functionality-preservation tests ────────────────────────────────────────

class TestNormalPrefixBehaviorPreserved:
    """The fix must not regress the 'algo:' callsite behavior — that's
    the only current real caller."""

    @pytest.mark.asyncio
    async def test_algo_prefix_only_matches(self, db_with_orders):
        db = db_with_orders
        await db._conn.executemany(
            "INSERT INTO orders (account_id, exchange_order_id, status) "
            "VALUES (1, ?, 'new')",
            [
                ("algo:btc_001",),
                ("algo:eth_002",),
                ("regular:btc_003",),
            ],
        )
        await db._conn.commit()
        canceled = await db.mark_stale_orders_canceled(
            account_id=1, active_ids=["regular:btc_003"], only_prefix="algo:",
        )
        # Both algo: orders canceled; regular:btc_003 is in active_ids so spared
        assert canceled == 2

    @pytest.mark.asyncio
    async def test_exclude_prefix_protects_algo(self, db_with_orders):
        db = db_with_orders
        await db._conn.executemany(
            "INSERT INTO orders (account_id, exchange_order_id, status) "
            "VALUES (1, ?, 'new')",
            [
                ("algo:btc_001",),
                ("regular:btc_003",),
            ],
        )
        await db._conn.commit()
        # Snapshot has neither order → would cancel all without scope.
        # exclude_prefix='algo:' protects the algo order.
        canceled = await db.mark_stale_orders_canceled(
            account_id=1, active_ids=["never-seen"], exclude_prefix="algo:",
        )
        assert canceled == 1
        async with db._conn.execute(
            "SELECT exchange_order_id FROM orders WHERE status='canceled'"
        ) as cur:
            rows = [r[0] for r in await cur.fetchall()]
        assert rows == ["regular:btc_003"]


# ── FBF intent: malicious-string handling ───────────────────────────────────

class TestMaliciousInputNoEffect:
    """The MED-022 finding's classic SQL-injection concern was closed
    in Task 101 via the `?` placeholder. T147 doesn't change that;
    this test pins it as still-fixed. A prefix containing SQL meta-
    chars (`'`, `;`, `--`) is treated as a literal opaque string —
    the `?` binding prevents it from being interpreted as SQL."""

    @pytest.mark.asyncio
    async def test_quote_injection_attempt_treated_literally(
        self, db_with_orders,
    ):
        """`'; DROP TABLE orders; --` as prefix → no injection.
        Table still exists; no rows match the literal prefix."""
        db = db_with_orders
        await db._conn.executemany(
            "INSERT INTO orders (account_id, exchange_order_id, status) "
            "VALUES (1, ?, 'new')",
            [("algo:safe",)],
        )
        await db._conn.commit()
        await db.mark_stale_orders_canceled(
            account_id=1, active_ids=["never-seen"],
            only_prefix="'; DROP TABLE orders; --",
        )
        # Table still exists + the existing row is untouched (no literal
        # prefix match)
        async with db._conn.execute("SELECT COUNT(*) FROM orders") as cur:
            assert (await cur.fetchone())[0] == 1
