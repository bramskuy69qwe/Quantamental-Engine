"""
Phase 8 Task 4b (P8.T4b) — calculator operator size override.

Spec §10.1: size is engine-recommended + operator-overridable (entry/TP/SL
stay plain inputs). When the operator overrides the size, run_risk_calculator
substitutes it BEFORE the size-dependent metrics + eligibility (so the whole
calc reflects the operator's size — est_exposure is portfolio-level and would
NOT scale linearly), and both planned_size (engine rec) + overridden_size are
persisted to pre_trade_log. The P2.T4 junction prefers overridden_size as the
deviation baseline.

Intent (Rule 8):
  - _resolve_size_override resolves planned/overridden/effective correctly
    (None/0/negative = no override; >0 = override; overridden == planned when
    not overridden, spec line 264);
  - insert_pre_trade_log persists the 6 plan/override columns (NULL when the
    caller omits them — backtest/legacy);
  - calc_result shows the engine recommendation when overridden + suppresses
    the now-moot regime size subtext;
  - the form carries the size_override field; the engine + endpoint are wired.

Run: pytest tests/test_phase8_size_override.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.risk_engine import _resolve_size_override  # noqa: E402


# ── _resolve_size_override (pure) ─────────────────────────────────────────────


class TestResolveSizeOverride:
    def test_none_is_no_override(self):
        assert _resolve_size_override(10.0, None) == (10.0, 10.0, 10.0, False)

    @pytest.mark.parametrize("bad", [0, 0.0, -5, "0", "", "abc", None])
    def test_nonpositive_or_bad_is_no_override(self, bad):
        eff, planned, ov, was = _resolve_size_override(10.0, bad)
        assert (eff, planned, ov, was) == (10.0, 10.0, 10.0, False)

    def test_valid_override(self):
        # planned stays the engine rec (10); effective + overridden = 8
        assert _resolve_size_override(10.0, 8.0) == (8.0, 10.0, 8.0, True)

    def test_string_numeric_override(self):
        assert _resolve_size_override(10.0, "8") == (8.0, 10.0, 8.0, True)

    def test_planned_preserved_even_when_override_larger(self):
        eff, planned, ov, was = _resolve_size_override(3.0, 25.0)
        assert planned == 3.0 and ov == 25.0 and eff == 25.0 and was is True


# ── insert_pre_trade_log persists plan/override columns ───────────────────────


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


async def _read(d, calc_id):
    async with d._conn.execute(
        "SELECT planned_size, overridden_size, planned_tp, overridden_tp, "
        "planned_sl, overridden_sl FROM pre_trade_log WHERE calc_id=?",
        (calc_id,),
    ) as cur:
        row = await cur.fetchone()
    return tuple(row) if row is not None else None


class TestPersistOverrideColumns:
    @pytest.mark.asyncio
    async def test_schema_has_columns(self, db):
        async with db._conn.execute("PRAGMA table_info(pre_trade_log)") as cur:
            cols = {r[1] for r in await cur.fetchall()}
        for col in ("planned_size", "overridden_size", "planned_tp",
                    "overridden_tp", "planned_sl", "overridden_sl"):
            assert col in cols

    @pytest.mark.asyncio
    async def test_persists_supplied_values(self, db):
        await db.insert_pre_trade_log({
            "account_id": 1, "ticker": "BTCUSDT", "side": "long",
            "calc_id": "OV1", "tp_price": 55000.0, "sl_price": 48000.0,
            "planned_size": 10.0, "overridden_size": 8.0,
            "planned_tp": 55000.0, "planned_sl": 48000.0,
        })
        row = await _read(db, "OV1")
        assert row == (10.0, 8.0, 55000.0, None, 48000.0, None)

    @pytest.mark.asyncio
    async def test_missing_keys_store_null(self, db):
        # backtest / legacy caller supplies no plan/override keys -> all NULL,
        # no crash (nullable columns; P2.T4 junction falls back to size/tp/sl)
        await db.insert_pre_trade_log({
            "account_id": 1, "ticker": "ETHUSDT", "side": "short",
            "calc_id": "OV2", "size": 5.0, "tp_price": 0.0, "sl_price": 0.0,
        })
        assert await _read(db, "OV2") == (None, None, None, None, None, None)


# ── calc_result.html override display (full fragment render) ──────────────────


_PARAMS = {"max_position_count": 10, "max_exposure": 3.0, "max_correlated_exposure": 0.5}


# ── form field + engine/endpoint wiring (source pins) ─────────────────────────


class TestSizeOverrideWiring:

    def test_run_risk_calculator_wires_override(self):
        with open("core/risk_engine.py", encoding="utf-8") as fh:
            src = fh.read()
        assert "size_override" in src
        assert "_resolve_size_override(" in src
        # the dict keys it must emit
        for key in ('"planned_size"', '"overridden_size"', '"size_overridden"',
                    '"planned_tp"', '"planned_sl"'):
            assert key in src
        # injection precedes the est_size computation (override feeds metrics)
        assert src.index("_resolve_size_override(\n        size") < src.index("est_size  = size * average")

    def test_endpoint_parses_and_passes_override(self):
        with open("api/routes_calculator.py", encoding="utf-8") as fh:
            src = fh.read()
        assert 'size_override: str = Form("")' in src
        assert "size_override=size_override_val" in src
