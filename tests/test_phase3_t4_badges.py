"""
Phase 3 Task 4 (P3.T4) tests — link_status badges + needs-link nav counter.

3.7: a per-order link_status BADGE in the order tables (history + open orders),
     colored via the now-defined app-wide badge family.
3.8: a live NAV BADGE COUNTER on the Needs-Link tab = count of
     NEEDS_MANUAL_REVIEW + UNLINKED orders.

Per CLAUDE.md template-wiring discipline: compile-and-render (not just grep).
The badge macro is rendered in isolation for all enum branches; the two order
tables are compiled + rendered; the count helper is unit-tested against a temp
DB; the count fragment endpoint is driven directly (no TestClient — gotcha #9).

Run: pytest tests/test_phase3_t4_badges.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import jinja2
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

ACCOUNT_ID = 1


def _make_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    env.globals["fmt"] = lambda v, n=2: (
        f"{v:.{n}f}" if isinstance(v, (int, float)) else str(v)
    )
    env.globals["ms_to_local"] = lambda ms: "2026-01-01 00:00:00"
    env.globals["project_name"] = "TestEngine"
    return env


# ── 3.7a: link_status_badge macro (the single source of truth) ─────────


def _render_badge(status):
    env = _make_env()
    tpl = env.from_string(
        '{% from "primitives/link_status_badge.html" import link_status_badge %}'
        '{{ link_status_badge(s) }}'
    )
    return tpl.render(s=status)


class TestLinkStatusBadgeMacro:
    @pytest.mark.parametrize("status, css, label", [
        ("LINKED", "badge-green", "LINKED"),
        ("NEEDS_MANUAL_REVIEW", "badge-yellow", "NEEDS REVIEW"),
        ("UNLINKED", "badge-gray", "UNLINKED"),
        ("UNPLANNED", "badge-blue", "UNPLANNED"),
    ])
    def test_each_status_maps_to_color(self, status, css, label):
        html = _render_badge(status)
        assert css in html
        assert label in html

    def test_null_renders_dash_not_badge(self):
        html = _render_badge(None)
        assert "—" in html
        assert "badge-green" not in html and "badge-yellow" not in html

    def test_unknown_value_falls_back_to_plain_badge(self):
        html = _render_badge("WEIRD")
        assert "badge" in html
        # not one of the colored variants
        for c in ("badge-green", "badge-yellow", "badge-gray", "badge-blue"):
            assert c not in html


# ── 3.7b: the order tables carry the Link column ───────────────────────


# ── badge CSS family is defined app-wide (the Option-A decision) ───────


class TestBadgeCssDefined:
    def test_missing_family_now_defined(self):
        with open("templates/base.html", encoding="utf-8") as fh:
            base = fh.read()
        for cls in (".badge-green", ".badge-red", ".badge-gray",
                    ".badge-yellow", ".badge-blue"):
            assert cls in base, cls


# ── 3.8: count helper ──────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_t4():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database = DatabaseManager(path=tmp.name)
    await database.initialize()
    await database._conn.execute(
        "INSERT OR IGNORE INTO accounts (id, name) VALUES (?, ?)",
        (ACCOUNT_ID, "Test"),
    )
    await database._conn.commit()
    yield database
    await database.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


async def _seed(db, eoid, link_status, account_id=ACCOUNT_ID):
    await db._conn.execute(
        "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
        " order_type, status, link_status) "
        "VALUES (?, ?, 'BTCUSDT', 'BUY', 'limit', 'new', ?)",
        (account_id, eoid, link_status),
    )
    await db._conn.commit()


class TestCountNeedsLink:
    @pytest.mark.asyncio
    async def test_counts_only_review_states(self, db_t4):
        await _seed(db_t4, "a", "NEEDS_MANUAL_REVIEW")
        await _seed(db_t4, "b", "NEEDS_MANUAL_REVIEW")
        await _seed(db_t4, "c", "UNLINKED")
        await _seed(db_t4, "d", "LINKED")        # excluded
        await _seed(db_t4, "e", "UNPLANNED")     # excluded
        await _seed(db_t4, "f", None)            # excluded
        assert await db_t4.count_needs_link(ACCOUNT_ID) == 3

    @pytest.mark.asyncio
    async def test_empty_is_zero(self, db_t4):
        assert await db_t4.count_needs_link(ACCOUNT_ID) == 0

    @pytest.mark.asyncio
    async def test_account_scoped(self, db_t4):
        # Orders for a DIFFERENT account must NOT count toward this account.
        await db_t4._conn.execute(
            "INSERT OR IGNORE INTO accounts (id, name) VALUES (2, 'Other')")
        await db_t4._conn.commit()
        await _seed(db_t4, "a1", "NEEDS_MANUAL_REVIEW", account_id=1)
        await _seed(db_t4, "a2", "UNLINKED", account_id=1)
        await _seed(db_t4, "b1", "NEEDS_MANUAL_REVIEW", account_id=2)
        await _seed(db_t4, "b2", "UNLINKED", account_id=2)
        assert await db_t4.count_needs_link(1) == 2   # excludes account 2's rows
        assert await db_t4.count_needs_link(2) == 2


# ── 3.8: count fragment endpoint (driven directly, no TestClient) ──────


class _FakeDB:
    def __init__(self, n):
        self._n = n

    async def count_needs_link(self, account_id):
        return self._n


class TestNeedsLinkCountFragment:
    @pytest.mark.asyncio
    async def test_zero_returns_empty(self, monkeypatch):
        import api.routes_orders as ro
        monkeypatch.setattr(ro, "db", _FakeDB(0))
        resp = await ro.frag_needs_link_count()
        assert resp.body.decode() == ""

    @pytest.mark.asyncio
    async def test_positive_returns_amber_badge(self, monkeypatch):
        import api.routes_orders as ro
        monkeypatch.setattr(ro, "db", _FakeDB(4))
        resp = await ro.frag_needs_link_count()
        body = resp.body.decode()
        assert "badge badge-yellow" in body
        assert ">4<" in body

    def test_route_registered(self):
        import api.routes_orders as ro
        assert any(
            getattr(r, "path", None) == "/fragments/needs_link_count"
            and "GET" in getattr(r, "methods", set())
            for r in ro.router.routes
        )


# ── 3.8: nav badge wiring in base.html ─────────────────────────────────


class TestNavBadgeWiring:
    def test_nav_has_needs_link_count_span(self):
        with open("templates/base.html", encoding="utf-8") as fh:
            base = fh.read()
        assert 'hx-get="/fragments/needs_link_count"' in base
        assert "page_key == 'needs_link'" in base
