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

import jinja2
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


def _env():
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    env.globals["fmt"] = lambda v, n=2: f"{float(v):.{n}f}" if isinstance(v, (int, float)) else str(v)
    env.globals["fmt_size"] = lambda v: f"{float(v):.4f}" if isinstance(v, (int, float)) else str(v)
    env.globals["fmt_price"] = lambda v, *a: str(v)
    return env


def _full_calc(**over):
    """A complete calc dict (all fields calc_result.html dereferences)."""
    c = {
        "calc_id": "C1", "eligible": True, "ticker": "BTCUSDT", "side": "long",
        "order_type": "market", "average": 50000.0,
        "weekly_pnl_state": "ok", "dd_state": "ok", "equity_stale": False,
        "total_equity": 1000.0, "at_max_positions": False,
        "at_max_exposure": False, "exceeds_corr_limit": False,
        "ineligible_reason": "",
        "regime_stale": False, "regime_label": "neutral",
        "regime_multiplier": 1.0, "apply_regime_multiplier": True,
        "atr_c": 0.5, "atr_category": "normal", "atr100": 100.0, "atr14": 50.0,
        "risk_usdt": 10.0, "base_size": 500.0, "est_fill_price": 50000.0,
        "one_percent_depth": 1000.0, "best_bid": 49990.0, "best_ask": 50010.0,
        "size": 10.0, "size_raw": 10.0, "notional": 500000.0,
        "tp_usdt": 50.0, "sl_usdt": 20.0,
        "size_overridden": False, "planned_size": 10.0,
        "est_slippage": 0.001, "est_slippage_usdt": 0.5, "est_profit": 45.0,
        "est_loss": 25.0, "est_r": 1.8, "est_exposure": 0.5, "fee_rate": 0.0004,
        "correlated_exposure": {}, "new_sector_exposure": 100.0,
        "tp_price": 55000.0, "sl_price": 48000.0,
        "would_be_notional": 500000.0, "would_be_size": 10.0,
    }
    c.update(over)
    return c


_PARAMS = {"max_position_count": 10, "max_exposure": 3.0, "max_correlated_exposure": 0.5}


def _render_result(calc):
    return _env().get_template("fragments/calc_result.html").render(calc=calc, params=_PARAMS)


class TestCalcResultOverrideDisplay:
    def test_overridden_shows_recommended(self):
        html = _render_result(_full_calc(size_overridden=True, size=8.0, planned_size=10.0))
        # specific: "10.0000" alone is a substring of best_ask 50010.0000
        assert "override · recommended 10.0000" in html   # the engine recommendation
        assert "8.0000" in html                            # the override (displayed size)

    def test_not_overridden_no_recommended_line(self):
        html = _render_result(_full_calc(size_overridden=False))
        assert "override · recommended" not in html

    def test_override_suppresses_regime_subtext(self):
        # regime multiplier != 1 normally shows a "without regime" subtext;
        # when overridden it must be suppressed (size_raw is moot).
        html = _render_result(_full_calc(
            size_overridden=True, size=8.0, planned_size=12.0,
            regime_multiplier=1.5, apply_regime_multiplier=True, size_raw=8.0,
        ))
        assert "without regime" not in html
        assert "override · recommended" in html

    def test_regime_subtext_when_not_overridden(self):
        html = _render_result(_full_calc(
            size_overridden=False, regime_multiplier=1.5,
            apply_regime_multiplier=True, size_raw=8.0,
        ))
        assert "without regime" in html


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
