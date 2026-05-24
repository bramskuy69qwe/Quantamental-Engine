"""
Task 169 regression tests — v1 historical counterfactual replay.

Verify-first per CLAUDE.md re-investigation discipline.

Verified state (T168/T167 carry-forward):
  • T167's get_dual_pnl_trades computes actual-vs-x1 for trades WITH
    a logged regime_multiplier (regime-active era). INNER JOIN
    excludes pre-T157 trades — that's by design for the FORWARD
    two-track.
  • T169's counterfactual is broader: replay live v1 rules across
    EVERY past trade (including pre-regime ones) by date-joining
    closed_positions to regime_signals + running classify_regime
    at each trade's entry_date. T156 established date-join feasibility.
  • Pieces re-used: classify_regime + _lookup_nearest + db.get_regime_
    signals + config.REGIME_MULTIPLIERS. The orchestrator (per-trade
    replay loop + linear-scaling re-size + per-mode segmentation) is
    the genuinely new code.

Linear-scaling re-size (T167 acceptance):
  x1_pnl = actual_pnl / actual_applied_mult
  v1_pnl = x1_pnl × v1_multiplier
        = actual × (v1_multiplier / actual_applied_mult)
  where actual_applied_mult falls back to 1.0 for pre-T157 / toggle-
  OFF / stale-fallback rows (NO regime scaling occurred → actual is
  the x1 baseline).

What this file pins:
  • Per-trade math: hand-computed v1_pnl matches output to 6 sig-figs.
  • Pre-T157 trade (no logged regime_multiplier): actual_applied_mult
    falls to 1.0 — so x1_pnl = actual; v1_pnl = actual × v1_mult.
    Load-bearing: this is what makes T169 broader than T167.
  • Per-mode segmentation: trade with crypto signals available
    replays mode="full"; trade without replays mode="macro_only".
    Both kept separate in summary.by_mode; never silently mixed.
  • Per-trade v1_mode is the COUNTERFACTUAL mode (determined by
    signal availability at trade_date), NOT the live-engine mode
    that was recorded at trade time. Confirmation of T168's
    "counterfactual mode is replay-derived" verdict.
  • Screening framing: output["framing"] carries the screening
    warning + linear-scaling caveat. Promotion language explicit.
  • Edge guards: no entry_time_ms / no signal coverage / pollution
    shape / invalid mult — all excluded with non-zero excluded counts.
  • Date join correctness: trade on 2024-06-15 uses the most-recent
    signal value AT OR BEFORE that date (not after — anti-future-
    leak).
  • Account-id filter + date-range filter.
  • Sort order: entry_time_ms ASC (chronological timeline).

Run: pytest tests/test_task169_counterfactual_replay.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures + helpers
# ─────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def test_db_swapped():
    """Temp DB plus monkey-swap of the module-level `db` reference used
    by regime_counterfactual + regime_classifier."""
    from core.database import DatabaseManager
    import core.database as db_mod
    import core.regime_counterfactual as rc_mod
    import core.regime_classifier as rc_mod_clf

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    test_db = DatabaseManager(path=tmp.name)
    await test_db.initialize()

    saved_db = db_mod.db
    db_mod.db = test_db
    rc_mod.db = test_db
    rc_mod_clf.db = test_db
    try:
        yield test_db
    finally:
        db_mod.db = saved_db
        rc_mod.db = saved_db
        rc_mod_clf.db = saved_db
        await test_db.close()
        try:
            os.unlink(tmp.name)
            for ext in ("-wal", "-shm"):
                p = tmp.name + ext
                if os.path.exists(p):
                    os.unlink(p)
        except OSError:
            pass


def _ms(date_iso: str, hour: int = 14) -> int:
    """YYYY-MM-DD → ms-epoch at the given UTC hour. Default 14:00 UTC
    keeps the timezone-edge worry off the test data."""
    dt = datetime.fromisoformat(date_iso + f"T{hour:02d}:00:00+00:00")
    return int(dt.timestamp() * 1000)


async def _insert_real_close(
    db, *, calc_id, symbol="BTCUSDT", entry_date, exit_date=None,
    net_pnl=100.0, entry_price=80000.0, exit_price=81000.0, quantity=0.01,
    account_id=1,
):
    """Insert a real (non-pollution-shape) closed_position row."""
    exit_date = exit_date or entry_date
    await db._conn.execute(
        """
        INSERT INTO closed_positions
            (account_id, symbol, entry_time_ms, exit_time_ms, net_pnl,
             entry_price, exit_price, quantity, calc_id,
             terminal_position_id, direction, realized_pnl, total_fees)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'LONG', ?, 0)
        """,
        (account_id, symbol, _ms(entry_date), _ms(exit_date),
         net_pnl, entry_price, exit_price, quantity, calc_id,
         f"term-{calc_id}", net_pnl),
    )
    await db._conn.commit()


async def _insert_pretrade(
    db, *, calc_id, regime_multiplier=None, regime_label=None,
    regime_mode=None, apply_regime_multiplier=None, regime_stale=None,
    account_id=1,
):
    await db.insert_pre_trade_log({
        "account_id":               account_id,
        "ticker":                   "BTCUSDT",
        "average":                  80000.0,
        "side":                     "long",
        "size":                     0.01,
        "notional":                 800.0,
        "tp_price":                 82000.0,
        "sl_price":                 79000.0,
        "eligible":                 True,
        "calc_id":                  calc_id,
        "regime_label":             regime_label,
        "regime_multiplier":        regime_multiplier,
        "regime_mode":              regime_mode,
        "apply_regime_multiplier":  apply_regime_multiplier,
        "regime_stale":             regime_stale,
    })


async def _seed_panic_signals(db, date_iso: str = "2024-06-15"):
    """Signal values that classify_regime maps to risk_off_panic
    under macro_only mode (vix > 30 AND hy > 5.0). Multiplier = 0.4."""
    await db.upsert_regime_signals("vix_close", [{"date": date_iso, "value": 50.0}])
    await db.upsert_regime_signals("us10y_yield", [{"date": date_iso, "value": 4.0}])
    await db.upsert_regime_signals("hy_spread", [{"date": date_iso, "value": 6.0}])


async def _seed_trending_signals_full(db, date_iso: str = "2024-06-15"):
    """Signal values that classify_regime maps to risk_on_trending
    under full mode. Multiplier = 1.2."""
    await db.upsert_regime_signals("vix_close",      [{"date": date_iso, "value": 15.0}])
    await db.upsert_regime_signals("us10y_yield",    [{"date": date_iso, "value": 4.0}])
    await db.upsert_regime_signals("hy_spread",      [{"date": date_iso, "value": 3.0}])
    await db.upsert_regime_signals("btc_rvol_ratio", [{"date": date_iso, "value": 1.0}])
    await db.upsert_regime_signals("agg_oi_change",  [{"date": date_iso, "value": 0.05}])
    await db.upsert_regime_signals("avg_funding",    [{"date": date_iso, "value": 0.001}])


# ─────────────────────────────────────────────────────────────────────────────
# 1. Per-trade math correctness (the load-bearing assertion)
# ─────────────────────────────────────────────────────────────────────────────


class TestPerTradeMath:
    @pytest.mark.asyncio
    async def test_pre_regime_trade_replayed_with_x1_baseline(self, test_db_swapped):
        """Pre-T157 trade has no logged regime_multiplier → actual_
        applied_mult = 1.0 → x1_pnl = actual. v1 regime is panic
        (signals stored at trade date) → v1_mult = 0.4 → v1_pnl =
        actual × 0.4. Load-bearing: proves T169 reaches trades T167
        excludes."""
        from core.regime_counterfactual import replay_v1_counterfactual

        await _seed_panic_signals(test_db_swapped, "2024-06-15")
        await _insert_real_close(
            test_db_swapped, calc_id="t169-no-regime",
            entry_date="2024-06-15", net_pnl=100.0,
        )
        # NOTE: no _insert_pretrade — pre-T157 shape.

        out = await replay_v1_counterfactual(account_id=1)
        assert len(out["trades"]) == 1
        r = out["trades"][0]
        assert r["actual_pnl"]          == pytest.approx(100.0)
        assert r["actual_applied_mult"] == pytest.approx(1.0)  # no regime row → 1.0
        assert r["x1_pnl"]              == pytest.approx(100.0)
        assert r["v1_label"]            == "risk_off_panic"
        assert r["v1_multiplier"]       == pytest.approx(0.4)
        assert r["v1_pnl"]              == pytest.approx(40.0)
        assert r["delta_v1_vs_actual"]  == pytest.approx(-60.0)
        assert r["delta_v1_vs_x1"]      == pytest.approx(-60.0)

    @pytest.mark.asyncio
    async def test_regime_active_trade_replayed_consistent_with_t167(self, test_db_swapped):
        """Trade WITH logged regime_multiplier=0.7 → x1 = actual / 0.7
        (T167 shape). v1 says panic at this date → v1 = x1 × 0.4."""
        from core.regime_counterfactual import replay_v1_counterfactual

        await _seed_panic_signals(test_db_swapped, "2024-06-15")
        await _insert_real_close(
            test_db_swapped, calc_id="t169-active",
            entry_date="2024-06-15", net_pnl=70.0,
        )
        await _insert_pretrade(
            test_db_swapped, calc_id="t169-active",
            regime_label="risk_off_defensive", regime_multiplier=0.7,
            regime_mode="full", apply_regime_multiplier=True, regime_stale=False,
        )

        out = await replay_v1_counterfactual(account_id=1)
        r = out["trades"][0]
        assert r["actual_pnl"]          == pytest.approx(70.0)
        assert r["actual_applied_mult"] == pytest.approx(0.7)
        assert r["x1_pnl"]              == pytest.approx(100.0)
        assert r["v1_multiplier"]       == pytest.approx(0.4)
        assert r["v1_pnl"]              == pytest.approx(40.0)
        # Live label preserved alongside counterfactual label.
        assert r["live_label"] == "risk_off_defensive"

    @pytest.mark.asyncio
    async def test_negative_pnl_scales_same_way(self, test_db_swapped):
        """Losing trade — counterfactual should report the de-risk
        SAVINGS as a positive delta."""
        from core.regime_counterfactual import replay_v1_counterfactual

        await _seed_panic_signals(test_db_swapped, "2024-06-15")
        # actual_applied_mult = 1.0 (no pre_trade_log row), actual = -100
        await _insert_real_close(
            test_db_swapped, calc_id="t169-loss",
            entry_date="2024-06-15", net_pnl=-100.0,
        )
        out = await replay_v1_counterfactual(account_id=1)
        r = out["trades"][0]
        assert r["x1_pnl"]             == pytest.approx(-100.0)
        assert r["v1_pnl"]             == pytest.approx(-40.0)
        assert r["delta_v1_vs_actual"] == pytest.approx(60.0)  # saved 60


# ─────────────────────────────────────────────────────────────────────────────
# 2. Per-mode segmentation (T168 carry-forward)
# ─────────────────────────────────────────────────────────────────────────────


class TestPerModeSegmentation:
    @pytest.mark.asyncio
    async def test_macro_only_when_crypto_signals_absent(self, test_db_swapped):
        """Pre-Binance-window trade — only macro signals available →
        replay assigns mode=macro_only."""
        from core.regime_counterfactual import replay_v1_counterfactual

        await _seed_panic_signals(test_db_swapped, "2020-01-15")
        await _insert_real_close(
            test_db_swapped, calc_id="t169-old", entry_date="2020-01-15",
            net_pnl=50.0,
        )

        out = await replay_v1_counterfactual(account_id=1)
        r = out["trades"][0]
        assert r["v1_mode"] == "macro_only", (
            "Task 169 regression: trade with only macro signals "
            "available should replay macro_only; got {!r}".format(r["v1_mode"])
        )

    @pytest.mark.asyncio
    async def test_full_mode_when_crypto_signals_present(self, test_db_swapped):
        from core.regime_counterfactual import replay_v1_counterfactual

        await _seed_trending_signals_full(test_db_swapped, "2024-06-15")
        await _insert_real_close(
            test_db_swapped, calc_id="t169-recent",
            entry_date="2024-06-15", net_pnl=100.0,
        )

        out = await replay_v1_counterfactual(account_id=1)
        r = out["trades"][0]
        assert r["v1_mode"] == "full"
        assert r["v1_label"] == "risk_on_trending"
        assert r["v1_multiplier"] == pytest.approx(1.2)

    @pytest.mark.asyncio
    async def test_summary_by_mode_keeps_full_and_macro_only_separate(self, test_db_swapped):
        """Mixed window — one pre-Binance macro_only trade + one
        recent full-mode trade → summary.by_mode aggregates per-mode
        independently."""
        from core.regime_counterfactual import replay_v1_counterfactual

        await _seed_panic_signals(test_db_swapped, "2020-01-15")            # macro_only
        await _seed_trending_signals_full(test_db_swapped, "2024-06-15")    # full

        await _insert_real_close(
            test_db_swapped, calc_id="old-1", entry_date="2020-01-15",
            net_pnl=50.0,
        )
        await _insert_real_close(
            test_db_swapped, calc_id="recent-1", entry_date="2024-06-15",
            net_pnl=100.0,
        )

        out = await replay_v1_counterfactual(account_id=1)
        s = out["summary"]
        assert s["n_trades_total"] == 2
        assert s["by_mode"]["macro_only"]["n"] == 1
        assert s["by_mode"]["full"]["n"]       == 1
        # Per-mode actual totals stay separate (no silent mixing)
        assert s["by_mode"]["macro_only"]["actual"] == pytest.approx(50.0)
        assert s["by_mode"]["full"]["actual"]       == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_v1_mode_is_counterfactual_not_live(self, test_db_swapped):
        """T168 confirmed: counterfactual mode is determined by signal
        availability AT REPLAY TIME, not by what live engine recorded.
        Trade with live_mode='full' but no crypto signals at its
        date → counterfactual mode = macro_only."""
        from core.regime_counterfactual import replay_v1_counterfactual

        await _seed_panic_signals(test_db_swapped, "2020-01-15")  # macro only
        await _insert_real_close(
            test_db_swapped, calc_id="t169-mode-divergence",
            entry_date="2020-01-15", net_pnl=50.0,
        )
        # Live recording claimed full mode (artificial — but proves
        # the counterfactual ignores it).
        await _insert_pretrade(
            test_db_swapped, calc_id="t169-mode-divergence",
            regime_label="neutral", regime_multiplier=1.0,
            regime_mode="full",  # ← claimed full
            apply_regime_multiplier=True, regime_stale=False,
        )
        out = await replay_v1_counterfactual(account_id=1)
        r = out["trades"][0]
        assert r["live_mode"] == "full"             # preserved for cross-check
        assert r["v1_mode"]   == "macro_only"        # but replay says macro_only


# ─────────────────────────────────────────────────────────────────────────────
# 3. Edge guards (silent exclusion with counts)
# ─────────────────────────────────────────────────────────────────────────────


class TestEdgeGuards:
    @pytest.mark.asyncio
    async def test_no_entry_time_ms_excluded(self, test_db_swapped):
        """entry_time_ms = 0 (DEFAULT) → trade excluded under
        excluded.no_entry_ms count + non-crashing."""
        from core.regime_counterfactual import replay_v1_counterfactual

        await _seed_panic_signals(test_db_swapped, "2024-06-15")
        # Bypass helper — insert with entry_time_ms=0
        await test_db_swapped._conn.execute(
            """
            INSERT INTO closed_positions
                (account_id, symbol, entry_time_ms, exit_time_ms, net_pnl,
                 entry_price, exit_price, quantity, calc_id,
                 terminal_position_id, direction, realized_pnl, total_fees)
            VALUES (1, 'BTCUSDT', 0, ?, 100.0, 80000, 81000, 0.01,
                    'no-entry', 'term-no-entry', 'LONG', 100.0, 0)
            """,
            (_ms("2024-06-15"),),
        )
        await test_db_swapped._conn.commit()

        out = await replay_v1_counterfactual(account_id=1)
        assert out["trades"] == []
        assert out["summary"]["excluded"]["no_entry_ms"] == 1

    @pytest.mark.asyncio
    async def test_no_signal_coverage_excluded(self, test_db_swapped):
        """Trade at a date with NO signal coverage (empty
        regime_signals before-or-at-date) → excluded under
        no_signal_coverage."""
        from core.regime_counterfactual import replay_v1_counterfactual

        # Signals exist but only AFTER trade date — _lookup_nearest
        # returns None for all of them.
        await _seed_panic_signals(test_db_swapped, "2024-12-31")
        await _insert_real_close(
            test_db_swapped, calc_id="t169-no-cov",
            entry_date="2024-06-15", net_pnl=100.0,
        )

        out = await replay_v1_counterfactual(account_id=1)
        assert out["trades"] == []
        assert out["summary"]["excluded"]["no_signal_coverage"] == 1

    @pytest.mark.asyncio
    async def test_pollution_shape_excluded_at_read_time(self, test_db_swapped):
        """Defense-in-depth: even if a pollution-shape row reached
        closed_positions (pre-T168 or via a non-canonical path),
        the counterfactual must exclude it."""
        from core.regime_counterfactual import replay_v1_counterfactual

        await _seed_panic_signals(test_db_swapped, "2024-06-15")
        await test_db_swapped._conn.execute(
            """
            INSERT INTO closed_positions
                (account_id, symbol, entry_time_ms, exit_time_ms, net_pnl,
                 entry_price, exit_price, quantity, calc_id,
                 terminal_position_id, direction, realized_pnl, total_fees)
            VALUES (1, 'BTCUSDT', ?, ?, -0.5, 0.0, 110.0, 0.01,
                    'pollute', 'term-pollute', 'LONG', -0.5, 0)
            """,
            (_ms("2024-06-15"), _ms("2024-06-15")),
        )
        await test_db_swapped._conn.commit()

        out = await replay_v1_counterfactual(account_id=1)
        assert out["trades"] == []
        assert out["summary"]["excluded"]["pollution_shape"] == 1

    @pytest.mark.asyncio
    async def test_zero_multiplier_handled_by_coalesce(self, test_db_swapped):
        """pre_trade_log.regime_multiplier=0 should be SQL-replaced
        with 1.0 by COALESCE/NULLIF → trade still replayed (not
        excluded), actual_applied_mult=1.0."""
        from core.regime_counterfactual import replay_v1_counterfactual

        await _seed_panic_signals(test_db_swapped, "2024-06-15")
        await _insert_real_close(
            test_db_swapped, calc_id="t169-zero-mult",
            entry_date="2024-06-15", net_pnl=100.0,
        )
        await _insert_pretrade(
            test_db_swapped, calc_id="t169-zero-mult",
            regime_multiplier=0.0,    # invalid — should COALESCE to 1.0
            apply_regime_multiplier=True,
        )
        out = await replay_v1_counterfactual(account_id=1)
        assert len(out["trades"]) == 1
        assert out["trades"][0]["actual_applied_mult"] == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Screening framing (promotion-discipline guard)
# ─────────────────────────────────────────────────────────────────────────────


class TestScreeningFraming:
    @pytest.mark.asyncio
    async def test_framing_carries_screening_label(self, test_db_swapped):
        from core.regime_counterfactual import replay_v1_counterfactual

        out = await replay_v1_counterfactual(account_id=1)
        f = out["framing"]
        assert f["type"] == "screening"
        # Load-bearing language — promotion is explicit
        assert "SCREENING" in f["warning"]
        assert "promotion" in f["warning"].lower() or "promote" in f["warning"].lower()
        assert "forward two-track" in f["warning"]

    @pytest.mark.asyncio
    async def test_framing_carries_linear_scaling_caveat(self, test_db_swapped):
        from core.regime_counterfactual import replay_v1_counterfactual

        out = await replay_v1_counterfactual(account_id=1)
        f = out["framing"]
        assert "linear_scaling_caveat" in f
        assert "slippage" in f["linear_scaling_caveat"].lower()
        assert "under-credits" in f["linear_scaling_caveat"].lower()

    @pytest.mark.asyncio
    async def test_framing_carries_hysteresis_bypass_caveat(self, test_db_swapped):
        """T169 follow-up: replay uses raw classify_regime per trade —
        no hysteresis. Deployed v1 has T165/T166 asymmetric hysteresis.
        Caveat must call this out so the screen isn't read as
        deployed-model performance."""
        from core.regime_counterfactual import replay_v1_counterfactual

        out = await replay_v1_counterfactual(account_id=1)
        f = out["framing"]
        assert "hysteresis_bypass_caveat" in f
        c = f["hysteresis_bypass_caveat"].lower()
        assert "hysteresis" in c
        assert "raw" in c or "classify_regime" in c
        # Load-bearing language — operator must not read this as deployed-model perf
        assert "deployed" in c or "live" in c


# ─────────────────────────────────────────────────────────────────────────────
# 5. Signal-date join correctness (no future leak)
# ─────────────────────────────────────────────────────────────────────────────


class TestDateJoinNoFutureLeak:
    @pytest.mark.asyncio
    async def test_uses_most_recent_at_or_before(self, test_db_swapped):
        """Signals on 2024-06-10 (panic) AND 2024-06-20 (trending).
        Trade on 2024-06-15 must use the 2024-06-10 panic values, NOT
        the 2024-06-20 trending values. Anti-future-leak."""
        from core.regime_counterfactual import replay_v1_counterfactual

        await test_db_swapped.upsert_regime_signals(
            "vix_close",
            [{"date": "2024-06-10", "value": 50.0},   # panic (before)
             {"date": "2024-06-20", "value": 15.0}],  # trending (after — must NOT leak)
        )
        await test_db_swapped.upsert_regime_signals(
            "hy_spread",
            [{"date": "2024-06-10", "value": 6.0},
             {"date": "2024-06-20", "value": 3.0}],
        )
        await test_db_swapped.upsert_regime_signals(
            "us10y_yield",
            [{"date": "2024-06-10", "value": 4.0}],
        )
        await _insert_real_close(
            test_db_swapped, calc_id="t169-date-join",
            entry_date="2024-06-15", net_pnl=100.0,
        )

        out = await replay_v1_counterfactual(account_id=1)
        r = out["trades"][0]
        # Used the BEFORE-date panic values → label = panic
        assert r["v1_label"] == "risk_off_panic", (
            "Task 169 regression: counterfactual leaked a future "
            "signal value (got {} — should be panic from 2024-06-10 "
            "values)".format(r["v1_label"])
        )

    @pytest.mark.asyncio
    async def test_uses_entry_date_not_exit_date(self, test_db_swapped):
        """Sizing decision happens at ENTRY, not exit. Trade entered
        2024-06-10 (panic signals available), exited 2024-06-20 (when
        signals had improved). Replay must use entry-date signals."""
        from core.regime_counterfactual import replay_v1_counterfactual

        # 2024-06-10 panic; 2024-06-20 calm
        await test_db_swapped.upsert_regime_signals(
            "vix_close",
            [{"date": "2024-06-10", "value": 50.0},
             {"date": "2024-06-20", "value": 15.0}],
        )
        await test_db_swapped.upsert_regime_signals(
            "hy_spread",
            [{"date": "2024-06-10", "value": 6.0},
             {"date": "2024-06-20", "value": 3.0}],
        )
        await test_db_swapped.upsert_regime_signals(
            "us10y_yield", [{"date": "2024-06-10", "value": 4.0}],
        )
        await _insert_real_close(
            test_db_swapped, calc_id="t169-entry-vs-exit",
            entry_date="2024-06-10", exit_date="2024-06-20", net_pnl=100.0,
        )

        out = await replay_v1_counterfactual(account_id=1)
        r = out["trades"][0]
        assert r["v1_label"] == "risk_off_panic"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Filters + sort
# ─────────────────────────────────────────────────────────────────────────────


class TestFiltersAndSort:
    @pytest.mark.asyncio
    async def test_account_id_filter(self, test_db_swapped):
        from core.regime_counterfactual import replay_v1_counterfactual

        await _seed_panic_signals(test_db_swapped, "2024-06-15")
        await _insert_real_close(
            test_db_swapped, calc_id="acc1", account_id=1,
            entry_date="2024-06-15", net_pnl=50.0,
        )
        await _insert_real_close(
            test_db_swapped, calc_id="acc2", account_id=2,
            entry_date="2024-06-15", net_pnl=50.0,
        )

        out1 = await replay_v1_counterfactual(account_id=1)
        out2 = await replay_v1_counterfactual(account_id=2)
        assert len(out1["trades"]) == 1 and out1["trades"][0]["calc_id"] == "acc1"
        assert len(out2["trades"]) == 1 and out2["trades"][0]["calc_id"] == "acc2"

    @pytest.mark.asyncio
    async def test_date_range_filter(self, test_db_swapped):
        from core.regime_counterfactual import replay_v1_counterfactual

        await _seed_panic_signals(test_db_swapped, "2024-06-15")
        await _insert_real_close(
            test_db_swapped, calc_id="early", entry_date="2024-01-01",
            exit_date="2024-01-02", net_pnl=50.0,
        )
        await _insert_real_close(
            test_db_swapped, calc_id="late", entry_date="2024-06-15",
            exit_date="2024-06-16", net_pnl=50.0,
        )

        # Window covers only the late trade (filter on exit_time_ms)
        out = await replay_v1_counterfactual(
            account_id=1,
            from_ms=_ms("2024-06-01"),
            to_ms=_ms("2024-12-31"),
        )
        assert len(out["trades"]) == 1
        assert out["trades"][0]["calc_id"] == "late"

    @pytest.mark.asyncio
    async def test_sort_by_entry_time_asc(self, test_db_swapped):
        from core.regime_counterfactual import replay_v1_counterfactual

        await _seed_panic_signals(test_db_swapped, "2024-06-15")
        for cid, d in [("c", "2024-06-17"), ("a", "2024-06-15"), ("b", "2024-06-16")]:
            await _insert_real_close(
                test_db_swapped, calc_id=cid, entry_date=d, net_pnl=10.0,
            )
        out = await replay_v1_counterfactual(account_id=1)
        assert [t["calc_id"] for t in out["trades"]] == ["a", "b", "c"]


# ─────────────────────────────────────────────────────────────────────────────
# 7. Summary aggregator math
# ─────────────────────────────────────────────────────────────────────────────


class TestSummaryAggregator:
    @pytest.mark.asyncio
    async def test_summary_aggregates_match_per_trade(self, test_db_swapped):
        """Two trades, panic regime: actual=50+100, v1_mult=0.4
        → v1=20+40, x1=50+100; v1_minus_actual = -90."""
        from core.regime_counterfactual import replay_v1_counterfactual

        await _seed_panic_signals(test_db_swapped, "2024-06-15")
        await _insert_real_close(test_db_swapped, calc_id="a",
                                 entry_date="2024-06-15", net_pnl=50.0)
        await _insert_real_close(test_db_swapped, calc_id="b",
                                 entry_date="2024-06-15", net_pnl=100.0)

        out = await replay_v1_counterfactual(account_id=1)
        s = out["summary"]
        assert s["n_trades_total"]  == 2
        assert s["actual_total"]    == pytest.approx(150.0)
        assert s["x1_total"]        == pytest.approx(150.0)   # mult=1 each
        assert s["v1_total"]        == pytest.approx(60.0)    # 0.4 × 150
        assert s["v1_minus_actual"] == pytest.approx(-90.0)
        assert s["v1_minus_x1"]     == pytest.approx(-90.0)

    @pytest.mark.asyncio
    async def test_excluded_counts_surface_in_summary(self, test_db_swapped):
        """All 4 excluded counts must appear in summary so consumers
        see why the trade count diverges from the raw closed_positions
        count."""
        from core.regime_counterfactual import replay_v1_counterfactual

        out = await replay_v1_counterfactual(account_id=1)
        ex = out["summary"]["excluded"]
        assert set(ex.keys()) == {
            "no_entry_ms", "no_signal_coverage",
            "pollution_shape", "invalid_actual_mult",
        }


# ─────────────────────────────────────────────────────────────────────────────
# 8. T169 source anchors
# ─────────────────────────────────────────────────────────────────────────────


class TestT169SourceAnchors:
    def test_counterfactual_module_has_task_169_anchor(self):
        text = (
            Path(__file__).parent.parent / "core" / "regime_counterfactual.py"
        ).read_text(encoding="utf-8")
        assert "Task 169" in text or "T169" in text

    def test_counterfactual_module_documents_screening_framing(self):
        text = (
            Path(__file__).parent.parent / "core" / "regime_counterfactual.py"
        ).read_text(encoding="utf-8")
        assert "SCREENING" in text or "screening" in text.lower()
        assert "promotion" in text.lower()

    def test_module_documents_linear_scaling_caveat(self):
        text = (
            Path(__file__).parent.parent / "core" / "regime_counterfactual.py"
        ).read_text(encoding="utf-8")
        assert "linear" in text.lower() and "scaling" in text.lower()
        assert "slippage" in text.lower()

    def test_uses_entry_time_ms_not_exit_time_ms_for_date(self):
        """Source pin: trade_date derives from entry_time_ms (sizing
        is decided at entry), not exit_time_ms. A refactor that
        switches the wrong way would re-introduce future-leak risk."""
        text = (
            Path(__file__).parent.parent / "core" / "regime_counterfactual.py"
        ).read_text(encoding="utf-8")
        executing = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("#")
        )
        assert "_trade_date_iso(t[\"entry_time_ms\"])" in executing or \
               "_trade_date_iso(t['entry_time_ms'])" in executing

    def test_left_join_used_not_inner(self):
        """Source pin: LEFT JOIN keeps pre-T157 trades. INNER would
        regress to T167's narrower scope."""
        text = (
            Path(__file__).parent.parent / "core" / "regime_counterfactual.py"
        ).read_text(encoding="utf-8")
        assert "LEFT JOIN pre_trade_log" in text

    def test_coalesce_actual_applied_mult_to_one(self):
        """Source pin: actual_applied_mult falls back to 1.0 for
        pre-T157 / toggle-OFF / stale rows. COALESCE + NULLIF combo
        handles NULL and 0."""
        text = (
            Path(__file__).parent.parent / "core" / "regime_counterfactual.py"
        ).read_text(encoding="utf-8")
        assert "COALESCE(NULLIF(pt.regime_multiplier, 0), 1.0)" in text
