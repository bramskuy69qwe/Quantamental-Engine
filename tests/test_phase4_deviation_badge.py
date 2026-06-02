"""
Phase 4 Task 3 (P4.T3) tests — live position deviation badge.

Verifies the combined badge (spec §10.2 semantic + plan §4.4 thresholds):
  - ``core.state.deviation_badge_level`` — the pure level function:
      red    = no calc (UNPLANNED) OR |size_delta_pct| >= red_pct
      yellow = amended (amendment_count > 0) OR |size_delta_pct| >= yellow_pct
      green  = linked, on-plan, no amendments
  - ``Database.count_amendments_by_calcs`` — grouped {calc_id: count}.
  - ``OrderManager._enrich_positions_calc_id`` stamps ``amendment_count`` +
    ``deviation_badge`` onto each live PositionInfo (no-junction → "red").
  - ``templates/primitives/deviation_badge.html`` + the live positions row
    render (compile-render, per CLAUDE.md Jinja discipline).

Run: pytest tests/test_phase4_deviation_badge.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
from types import SimpleNamespace

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
_REPO = os.path.dirname(os.path.dirname(__file__))

ACCOUNT_ID = 1


# ── 1. pure level function ──────────────────────────────────────────────


class TestDeviationBadgeLevel:
    def _lvl(self, **kw):
        from core.state import deviation_badge_level
        base = dict(has_calc=True, size_delta_pct=0.0, amendment_count=0,
                    yellow_pct=5.0, red_pct=15.0)
        base.update(kw)
        return deviation_badge_level(**base)

    def test_no_calc_is_red(self):
        assert self._lvl(has_calc=False) == "red"
        # no-calc beats everything (even on-plan size)
        assert self._lvl(has_calc=False, size_delta_pct=0.0) == "red"

    def test_on_plan_no_amendments_is_green(self):
        assert self._lvl(size_delta_pct=2.0, amendment_count=0) == "green"
        assert self._lvl(size_delta_pct=-4.9, amendment_count=0) == "green"

    def test_amended_is_yellow(self):
        assert self._lvl(size_delta_pct=0.0, amendment_count=1) == "yellow"

    def test_size_past_yellow_is_yellow(self):
        assert self._lvl(size_delta_pct=5.0) == "yellow"
        assert self._lvl(size_delta_pct=-9.9) == "yellow"

    def test_size_past_red_is_red(self):
        assert self._lvl(size_delta_pct=15.0) == "red"
        assert self._lvl(size_delta_pct=-30.0) == "red"

    def test_red_beats_amended(self):
        # large size deviation outranks the amended-yellow
        assert self._lvl(size_delta_pct=20.0, amendment_count=3) == "red"


# ── DB + enrich fixtures ────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database = DatabaseManager(path=tmp.name)
    await database.initialize()
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


@pytest_asyncio.fixture
async def om(db):
    from core.order_manager import OrderManager
    return OrderManager(db)


async def _seed_junction(db, position_id, calc_id, qty, planned_size,
                         ts=1000, account_id=ACCOUNT_ID):
    await db._conn.execute(
        "INSERT INTO positions_calcs (position_id, calc_id, order_id, account_id, "
        " contributed_qty, first_fill_ts, last_fill_ts, planned_size) "
        "VALUES (?, ?, 1, ?, ?, ?, ?, ?)",
        (position_id, calc_id, account_id, qty, ts, ts, planned_size),
    )
    await db._conn.commit()


async def _amend(db, calc_id, field="entry_price", old=50000.0, new=50100.0, ts=1100):
    await db.insert_order_amendment({
        "order_id": 1, "calc_id": calc_id, "field": field,
        "old_value": old, "new_value": new, "ts_ms": ts,
        "operator_id": None, "deviation_pct": 0.2, "lifecycle_id": None,
    })


def _pos(position_id="POS-1", ticker="BTCUSDT", direction="LONG"):
    from core.state import PositionInfo
    return PositionInfo(position_id=position_id, ticker=ticker, direction=direction)


# ── 2. grouped count helper ─────────────────────────────────────────────


class TestCountAmendmentsByCalcs:
    @pytest.mark.asyncio
    async def test_groups_by_calc(self, db):
        await _amend(db, "C1", ts=100)
        await _amend(db, "C1", field="sl_price", ts=200)
        await _amend(db, "C2", ts=300)
        m = await db.count_amendments_by_calcs(["C1", "C2", "C3"])
        assert m == {"C1": 2, "C2": 1}  # C3 absent → not in dict

    @pytest.mark.asyncio
    async def test_empty_is_empty_dict(self, db):
        assert await db.count_amendments_by_calcs([]) == {}
        assert await db.count_amendments_by_calcs([None, ""]) == {}


# ── 3. enrich stamps the badge ──────────────────────────────────────────


class TestEnrichBadge:
    @pytest.mark.asyncio
    async def test_on_plan_no_amendments_green(self, db, om):
        await _seed_junction(db, "POS-1", "C1", qty=10.0, planned_size=10.0)
        pos = _pos()
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.calc_id == "C1"
        assert pos.amendment_count == 0
        assert pos.size_delta_pct == pytest.approx(0.0)
        assert pos.deviation_badge == "green"

    @pytest.mark.asyncio
    async def test_amended_yellow(self, db, om):
        await _seed_junction(db, "POS-1", "C1", qty=10.0, planned_size=10.0)
        await _amend(db, "C1")
        await _amend(db, "C1", field="sl_price")
        pos = _pos()
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.amendment_count == 2
        assert pos.deviation_badge == "yellow"

    @pytest.mark.asyncio
    async def test_size_past_red_threshold_red(self, db, om):
        # contributed 13 vs planned 10 → +30% > default red_pct (15) → red.
        await _seed_junction(db, "POS-1", "C1", qty=13.0, planned_size=10.0)
        pos = _pos()
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.size_delta_pct == pytest.approx(30.0)
        assert pos.deviation_badge == "red"

    @pytest.mark.asyncio
    async def test_no_junction_is_red_no_calc(self, db, om):
        # Position has a position_id but no junction row → UNPLANNED → red.
        pos = _pos(position_id="POS-UNPLANNED")
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.calc_id == ""
        assert pos.amendment_count == 0
        assert pos.deviation_badge == "red"

    @pytest.mark.asyncio
    async def test_amendment_query_failure_degrades_to_defaults(self, db, om, monkeypatch):
        # Audit P4T3-MED regression: if count_amendments_by_calcs raises (e.g.
        # a transient DB lock), thresholds must DEFAULT (not strand at 0.0,
        # which would paint an on-plan position red). Config read happens first
        # + thresholds default → an on-plan position stays green, not red.
        await _seed_junction(db, "POS-1", "C1", qty=10.0, planned_size=10.0)

        async def _boom(*a, **k):
            raise RuntimeError("database is locked")
        monkeypatch.setattr(db, "count_amendments_by_calcs", _boom)

        pos = _pos()
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.deviation_badge == "green"   # NOT a false "red"
        assert pos.amendment_count == 0

    @pytest.mark.asyncio
    async def test_amendment_query_failure_with_real_amendments_warns(
        self, db, om, monkeypatch, caplog
    ):
        # P4 audit (P4T3-001 / TEST-INTEGRITY-002): when REAL amendments exist
        # but the count query fails, the badge can't see them THIS refresh (an
        # unavoidable transient miss that self-heals next poll). The fix makes
        # it DIAGNOSABLE — a WARNING (not a silent debug) — and decoupled from
        # the config read (a config failure no longer skips the count).
        await _seed_junction(db, "POS-1", "C1", qty=10.0, planned_size=10.0)
        await _amend(db, "C1", field="entry_price")   # a REAL amendment exists

        async def _boom(*a, **k):
            raise RuntimeError("database is locked")
        monkeypatch.setattr(db, "count_amendments_by_calcs", _boom)

        pos = _pos()
        with caplog.at_level("WARNING"):
            await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        # transient miss (documented): masked this refresh...
        assert pos.amendment_count == 0
        # ...but now VISIBLE in the logs (was a silent debug before the fix).
        assert any("amendment count failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_empty_position_id_skipped_no_badge(self, db, om):
        # binance one-way (no position_id) is skipped → badge stays default "".
        pos = _pos(position_id="")
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.deviation_badge == ""

    @pytest.mark.asyncio
    async def test_amendment_count_sums_scale_in_calcs(self, db, om):
        # Scale-in: two calcs contribute to one position; the count sums both.
        # Primary C1 planned the full 10 (so total==primary planned → size
        # on-plan), isolating the amendment-driven yellow.
        await _seed_junction(db, "POS-1", "C1", qty=6.0, planned_size=10.0, ts=1000)
        await _seed_junction(db, "POS-1", "C2", qty=4.0, planned_size=4.0, ts=2000)
        await _amend(db, "C1")
        await _amend(db, "C2")
        await _amend(db, "C2", field="sl_price")
        pos = _pos()
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.amendment_count == 3        # summed across C1 + C2
        assert pos.size_delta_pct == pytest.approx(0.0)
        assert pos.deviation_badge == "yellow"


# ── 4. compile-render (Jinja discipline) ────────────────────────────────


class TestBadgeTemplates:
    def _env(self):
        import jinja2
        return jinja2.Environment(
            loader=jinja2.FileSystemLoader(os.path.join(_REPO, "templates")))

    def test_macro_renders_each_level(self):
        env = self._env()
        t = env.from_string(
            '{% from "primitives/deviation_badge.html" import deviation_badge %}'
            '{{ deviation_badge(level, sd, n) }}')
        green = t.render(level="green", sd=2.0, n=0)
        assert "badge-green" in green and "on-plan" in green
        yellow = t.render(level="yellow", sd=-7.5, n=2)
        assert "badge-yellow" in yellow and "amended" in yellow
        assert "2 amendments" in yellow
        red = t.render(level="red", sd=20.0, n=0)
        assert "badge-red" in red and "off-plan" in red
        # empty level → no badge markup
        assert env.from_string(
            '{% from "primitives/deviation_badge.html" import deviation_badge %}'
            '{{ deviation_badge("") }}').render().strip() == ""

    def test_singular_amendment_label(self):
        env = self._env()
        t = env.from_string(
            '{% from "primitives/deviation_badge.html" import deviation_badge %}'
            '{{ deviation_badge("yellow", 0.0, 1) }}')
        out = t.render()
        assert "1 amendment" in out and "1 amendments" not in out

    def test_positions_row_renders_badge(self):
        env = self._env()
        env.globals["fmt"] = lambda v, n=2: f"{float(v):.{n}f}"
        env.globals["hold_time"] = lambda ts: "1h"
        tmpl = env.get_template("fragments/dashboard_positions_rows.html")
        pos = SimpleNamespace(
            ticker="BTCUSDT", direction="LONG", entry_timestamp="x",
            average=50000, fair_price=51000, contract_amount=1.0,
            position_value_usdt=50000, individual_unrealized=100,
            individual_fees=1.0, session_mfe=10, session_mae=-5,
            individual_tp_price=55000, individual_sl_price=48000,
            deviation_badge="yellow", size_delta_pct=-7.5, amendment_count=2)
        out = tmpl.render(open_positions=[pos])
        assert "badge-yellow" in out and "amended" in out
        assert "BTCUSDT" in out
