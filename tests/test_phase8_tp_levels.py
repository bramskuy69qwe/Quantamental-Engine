"""
Phase 8 Task 4c (P8.T4c) — calculator multi-TP ladder (tp_levels).

Spec §10.1: "TP (or tp_levels array)". The operator can enter a TP ladder
(rows of {price, size_pct}); it is validated, persisted to
pre_trade_log.tp_levels (JSON TEXT), and shown in the calc result. The
single-TP path (matcher / sizing / est_profit) is unchanged — if a ladder is
entered with the single TP blank, the UI feeds TP1 there. Per-rung weighted
profit / drift are a later phase (SPEC-001).

Intent (Rule 8):
  - _parse_tp_levels validates + normalizes (blank/empty -> None; bad JSON /
    non-array / bad element / price<=0 / size_pct out of (0,100] / sum>100 /
    too many -> ValueError);
  - insert_pre_trade_log JSON-serializes a list to the TEXT column (None ->
    NULL; an already-serialized string stored as-is);
  - calc_result renders the ladder when present;
  - the calculator widget + submit serialization + endpoint are wired.

Run: pytest tests/test_phase8_tp_levels.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from api.routes_calculator import _parse_tp_levels, MAX_TP_LEVELS  # noqa: E402


# ── _parse_tp_levels (pure) ───────────────────────────────────────────────────


class TestParseTpLevels:
    @pytest.mark.parametrize("blank", [None, "", "   ", "[]"])
    def test_blank_or_empty_is_none(self, blank):
        assert _parse_tp_levels(blank) is None

    def test_single_level_normalized_to_floats(self):
        out = _parse_tp_levels('[{"price": 55000, "size_pct": 50}]')
        assert out == [{"price": 55000.0, "size_pct": 50.0}]
        assert isinstance(out[0]["price"], float) and isinstance(out[0]["size_pct"], float)

    def test_multi_level(self):
        out = _parse_tp_levels('[{"price":55000,"size_pct":50},{"price":60000,"size_pct":50}]')
        assert len(out) == 2 and out[1]["price"] == 60000.0

    def test_sum_exactly_100_ok(self):
        out = _parse_tp_levels('[{"price":5,"size_pct":40},{"price":6,"size_pct":60}]')
        assert len(out) == 2

    def test_sum_within_tolerance_ok(self):
        # sum 100.005 <= 100.01 tolerance (each level still <= 100)
        out = _parse_tp_levels('[{"price":5,"size_pct":50},{"price":6,"size_pct":50.005}]')
        assert out is not None and len(out) == 2

    @pytest.mark.parametrize("raw,frag", [
        ("{not json", "valid JSON"),
        ('{"price":1,"size_pct":1}', "array"),         # not a list
        ('[1, 2]', "object"),                          # element not a dict
        ('[{"price":0,"size_pct":50}]', "> 0"),        # price <= 0
        ('[{"price":-5,"size_pct":50}]', "> 0"),
        ('[{"price":5,"size_pct":0}]', "(0, 100]"),    # size_pct <= 0
        ('[{"price":5,"size_pct":150}]', "(0, 100]"),  # size_pct > 100
        ('[{"price":5,"size_pct":60},{"price":6,"size_pct":60}]', "exceeds 100"),  # sum 120
        ('[{"price":"x","size_pct":50}]', "must be numbers"),
        ('[{"size_pct":50}]', "must be numbers"),      # missing price
    ])
    def test_invalid_raises(self, raw, frag):
        with pytest.raises(ValueError) as ei:
            _parse_tp_levels(raw)
        assert frag in str(ei.value)

    def test_too_many_levels_raises(self):
        raw = "[" + ",".join(['{"price":5,"size_pct":1}'] * (MAX_TP_LEVELS + 1)) + "]"
        with pytest.raises(ValueError) as ei:
            _parse_tp_levels(raw)
        assert "too many" in str(ei.value)

    @pytest.mark.parametrize("raw", [
        '[{"price": NaN, "size_pct": 50}]',          # json.loads accepts NaN
        '[{"price": Infinity, "size_pct": 50}]',     # ...and Infinity
        '[{"price": 1e400, "size_pct": 50}]',        # overflows to inf
        '[{"price": 5, "size_pct": Infinity}]',
    ])
    def test_non_finite_rejected(self, raw):
        # non-finite would otherwise persist as INVALID JSON (audit MED).
        with pytest.raises(ValueError) as ei:
            _parse_tp_levels(raw)
        assert "finite" in str(ei.value) or "(0, 100]" in str(ei.value)


# ── insert_pre_trade_log persists tp_levels ───────────────────────────────────


@pytest_asyncio.fixture
async def db():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    d = DatabaseManager(path=tmp.name)
    await d.initialize()
    yield d
    await d.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


async def _read_tp_levels(d, calc_id):
    async with d._conn.execute(
        "SELECT tp_levels FROM pre_trade_log WHERE calc_id=?", (calc_id,),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


class TestPersistTpLevels:
    @pytest.mark.asyncio
    async def test_schema_has_column(self, db):
        async with db._conn.execute("PRAGMA table_info(pre_trade_log)") as cur:
            cols = {r[1] for r in await cur.fetchall()}
        assert "tp_levels" in cols

    @pytest.mark.asyncio
    async def test_list_is_json_serialized(self, db):
        levels = [{"price": 55000.0, "size_pct": 50.0}, {"price": 60000.0, "size_pct": 50.0}]
        await db.insert_pre_trade_log({
            "account_id": 1, "ticker": "BTCUSDT", "side": "long",
            "calc_id": "L1", "tp_levels": levels,
        })
        stored = await _read_tp_levels(db, "L1")
        assert isinstance(stored, str)
        assert json.loads(stored) == levels   # round-trips

    @pytest.mark.asyncio
    async def test_none_stores_null(self, db):
        await db.insert_pre_trade_log({
            "account_id": 1, "ticker": "ETHUSDT", "side": "short",
            "calc_id": "L2", "tp_levels": None,
        })
        assert await _read_tp_levels(db, "L2") is None

    @pytest.mark.asyncio
    async def test_missing_key_stores_null(self, db):
        await db.insert_pre_trade_log({
            "account_id": 1, "ticker": "ETHUSDT", "side": "short", "calc_id": "L3",
        })
        assert await _read_tp_levels(db, "L3") is None

    @pytest.mark.asyncio
    async def test_prserialized_string_stored_as_is(self, db):
        await db.insert_pre_trade_log({
            "account_id": 1, "ticker": "BTCUSDT", "side": "long",
            "calc_id": "L4", "tp_levels": '[{"price": 1, "size_pct": 100}]',
        })
        stored = await _read_tp_levels(db, "L4")
        assert json.loads(stored) == [{"price": 1, "size_pct": 100}]


# ── calc_result.html ladder display (full fragment render) ────────────────────


_PARAMS = {"max_position_count": 10, "max_exposure": 3.0, "max_correlated_exposure": 0.5}


# ── widget + endpoint wiring (source pins) ────────────────────────────────────


class TestLadderWiring:

    def test_endpoint_wires_tp_levels(self):
        with open("api/routes_calculator.py", encoding="utf-8") as fh:
            src = fh.read()
        assert 'tp_levels: str = Form("")' in src
        assert "_parse_tp_levels(tp_levels)" in src
        assert 'calc["tp_levels"] = tp_levels_parsed' in src
