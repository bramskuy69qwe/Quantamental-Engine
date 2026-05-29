"""Phase 2.12 — restart rehydrate: contributing_calc_ids + live size deviation.

T2.3 already rehydrates ``PositionInfo.calc_id`` (primary) from the
positions_calcs junction at startup (via ``refresh_cache`` →
``_enrich_positions_calc_id``). T2.12 EXTENDS that same authoritative,
already-startup-running method to also populate:

  - ``contributing_calc_ids`` — all junction calcs for the position,
    primary-first then by contributed_qty desc;
  - ``size_delta_pct`` — live size deviation vs the primary calc's planned
    size: (Σ contributed_qty − primary planned_size) / planned_size × 100.

All three are AUTHORITATIVE (mirror the junction each refresh; cleared when
no junction). Tests drive ``_enrich_positions_calc_id`` directly on the
DatabaseManager — the same call refresh_cache makes at restart.

Run: pytest tests/test_phase2_rehydrate.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

ACCOUNT_ID = 1


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


async def _seed_junction(db, position_id, calc_id, order_id, qty, first_fill_ts,
                         planned_size=None, account_id=ACCOUNT_ID):
    await db._conn.execute(
        "INSERT INTO positions_calcs (position_id, calc_id, order_id, "
        " account_id, contributed_qty, first_fill_ts, last_fill_ts, "
        " planned_size) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (position_id, calc_id, order_id, account_id, qty, first_fill_ts,
         first_fill_ts, planned_size),
    )
    await db._conn.commit()


def _pos(position_id, ticker="BTCUSDT", direction="LONG"):
    from core.state import PositionInfo
    return PositionInfo(position_id=position_id, ticker=ticker, direction=direction)


class TestRehydrateContributingCalcs:
    @pytest.mark.asyncio
    async def test_single_calc(self, db, om):
        await _seed_junction(db, "POS-1", "C1", 1, 1.0, 1000, planned_size=1.0)
        pos = _pos("POS-1")
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.calc_id == "C1"
        assert pos.contributing_calc_ids == ["C1"]
        assert pos.size_delta_pct == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_scale_in_primary_and_ordering(self, db, om):
        # C-A first (qty 3), C-B later (qty 7) → primary = C-B (max qty),
        # contributing ordered by qty desc: [C-B, C-A].
        await _seed_junction(db, "POS-1", "C-A", 1, 3.0, 1000, planned_size=3.0)
        await _seed_junction(db, "POS-1", "C-B", 2, 7.0, 2000, planned_size=7.0)
        pos = _pos("POS-1")
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.calc_id == "C-B"
        assert pos.contributing_calc_ids == ["C-B", "C-A"]
        # actual = 3+7 = 10; primary (C-B) planned = 7 → (10-7)/7*100 ≈ 42.857
        assert pos.size_delta_pct == pytest.approx((10.0 - 7.0) / 7.0 * 100.0)

    @pytest.mark.asyncio
    async def test_tie_break_earliest_first_fill_is_primary(self, db, om):
        # Equal qty → earliest first_fill_ts is primary AND first in the list.
        await _seed_junction(db, "POS-1", "C-EARLY", 1, 5.0, 1000, planned_size=5.0)
        await _seed_junction(db, "POS-1", "C-LATE", 2, 5.0, 2000, planned_size=5.0)
        pos = _pos("POS-1")
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.calc_id == "C-EARLY"
        assert pos.contributing_calc_ids == ["C-EARLY", "C-LATE"]

    @pytest.mark.asyncio
    async def test_multiple_orders_same_calc_sum_qty(self, db, om):
        # One calc placing TWO orders on the position → two junction rows;
        # contributed_qty summed, single entry in contributing_calc_ids.
        await _seed_junction(db, "POS-1", "C1", 1, 2.0, 1000, planned_size=5.0)
        await _seed_junction(db, "POS-1", "C1", 2, 3.0, 1500, planned_size=5.0)
        pos = _pos("POS-1")
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.calc_id == "C1"
        assert pos.contributing_calc_ids == ["C1"]
        # actual = 2+3 = 5; planned = 5 → 0%
        assert pos.size_delta_pct == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_no_junction_clears_authoritatively(self, db, om):
        # Pre-populate as if stale (preserved via _PRESERVE_FIELDS), then a
        # position with NO junction must be cleared.
        pos = _pos("POS-NONE")
        pos.calc_id = "STALE"
        pos.contributing_calc_ids = ["STALE"]
        pos.size_delta_pct = 99.0
        # need ≥1 position with a real junction so the method doesn't early-return
        await _seed_junction(db, "POS-OTHER", "C9", 1, 1.0, 1000, planned_size=1.0)
        other = _pos("POS-OTHER")
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos, other])
        assert pos.calc_id == ""
        assert pos.contributing_calc_ids == []
        assert pos.size_delta_pct == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_negative_size_delta_underfill(self, db, om):
        # Opened less than planned → negative size_delta_pct.
        await _seed_junction(db, "POS-1", "C1", 1, 0.6, 1000, planned_size=1.0)
        pos = _pos("POS-1")
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.size_delta_pct == pytest.approx((0.6 - 1.0) / 1.0 * 100.0)

    @pytest.mark.asyncio
    async def test_no_planned_size_delta_is_zero(self, db, om):
        # planned_size NULL on the primary → can't compute → 0.0.
        await _seed_junction(db, "POS-1", "C1", 1, 1.0, 1000, planned_size=None)
        pos = _pos("POS-1")
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.calc_id == "C1"
        assert pos.size_delta_pct == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_empty_position_id_skipped(self, db, om):
        # binance one-way (no terminal_position_id) — no junction key.
        await _seed_junction(db, "POS-1", "C1", 1, 1.0, 1000, planned_size=1.0)
        empty = _pos("")
        await om._enrich_positions_calc_id(ACCOUNT_ID, [empty])
        # untouched defaults (no raise)
        assert empty.calc_id == ""
        assert empty.contributing_calc_ids == []

    @pytest.mark.asyncio
    async def test_multiple_positions_each_own_linkage(self, db, om):
        await _seed_junction(db, "POS-1", "C1", 1, 1.0, 1000, planned_size=1.0)
        await _seed_junction(db, "POS-2", "C2", 2, 2.0, 1000, planned_size=4.0)
        p1, p2 = _pos("POS-1"), _pos("POS-2")
        await om._enrich_positions_calc_id(ACCOUNT_ID, [p1, p2])
        assert p1.calc_id == "C1" and p1.contributing_calc_ids == ["C1"]
        assert p2.calc_id == "C2" and p2.contributing_calc_ids == ["C2"]
        assert p2.size_delta_pct == pytest.approx((2.0 - 4.0) / 4.0 * 100.0)


class TestPrimaryConvergence:
    @pytest.mark.asyncio
    async def test_multi_order_calc_aggregates_and_converges(self, db, om):
        # T240 review (HIGH): C-A places TWO orders (3+3=6 summed); C-B one
        # order (5). Spec §3.2/§12.4 most-contributing CALC = C-A (6 > 5) even
        # though C-B's single row (5) is larger than either C-A row (3). Both
        # the live surface (_enrich_positions_calc_id) and the close-path
        # surface (_position_primary_calc) must agree on C-A via the shared
        # _most_contributing_calc_id selector (R1 convergence). Pre-fix,
        # _position_primary_calc took the max single ROW → C-B → divergence.
        await _seed_junction(db, "POS-1", "C-A", 1, 3.0, 1000, planned_size=3.0)
        await _seed_junction(db, "POS-1", "C-A", 2, 3.0, 1100, planned_size=3.0)
        await _seed_junction(db, "POS-1", "C-B", 3, 5.0, 1200, planned_size=5.0)

        pos = _pos("POS-1")
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        close_primary, _lc = await om._position_primary_calc(ACCOUNT_ID, "POS-1")

        assert pos.calc_id == "C-A"           # live surface: summed wins
        assert close_primary == "C-A"         # close path agrees (the fix)
        assert pos.calc_id == close_primary   # R1 convergence
        assert pos.contributing_calc_ids == ["C-A", "C-B"]
        # actual = 3+3+5 = 11; primary C-A planned = 3 (spec §3.2 total-vs-primary)
        assert pos.size_delta_pct == pytest.approx((11.0 - 3.0) / 3.0 * 100.0)

    @pytest.mark.asyncio
    async def test_single_order_per_calc_unchanged(self, db, om):
        # Regression guard: the common one-order-per-calc case is identical
        # under summed vs max-row, so both surfaces still pick the bigger calc.
        await _seed_junction(db, "POS-1", "C-A", 1, 3.0, 1000, planned_size=3.0)
        await _seed_junction(db, "POS-1", "C-B", 2, 7.0, 2000, planned_size=7.0)
        pos = _pos("POS-1")
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        close_primary, _lc = await om._position_primary_calc(ACCOUNT_ID, "POS-1")
        assert pos.calc_id == "C-B" == close_primary


class TestRehydratePreserveFields:
    def test_new_fields_in_preserve_set(self):
        # T2.12 fields must survive snapshot rebuilds like calc_id does.
        from core.data_cache import _PRESERVE_FIELDS
        assert "contributing_calc_ids" in _PRESERVE_FIELDS
        assert "size_delta_pct" in _PRESERVE_FIELDS
        assert "calc_id" in _PRESERVE_FIELDS

    def test_positioninfo_defaults(self):
        from core.state import PositionInfo
        p = PositionInfo()
        assert p.contributing_calc_ids == []
        assert p.size_delta_pct == 0.0
        # distinct list instances per dataclass instance (default_factory)
        q = PositionInfo()
        p.contributing_calc_ids.append("X")
        assert q.contributing_calc_ids == []
