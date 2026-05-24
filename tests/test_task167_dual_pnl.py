"""
Task 167 regression tests — dual-P&L (forward two-track).

Re-investigation finding (per CLAUDE.md re-investigation discipline +
T167 re-sync step 0): the regime-plan's "log per-trade regime state +
dual P&L" was already half-done before T167. Per-trade regime state
landed in T157 (regime_label / regime_multiplier / regime_mode /
apply_regime_multiplier) + T165 (regime_stale). The remaining half —
dual-P&L as a forward-two-track readable surface — is a DERIVED
QUERY over already-logged data, not new per-trade logging. T167 ships
that query (RegimeMixin.get_dual_pnl_trades + get_dual_pnl_summary).

Why derived works:

  closed_positions.calc_id  ←—JOIN—→  pre_trade_log.calc_id

  pre_trade_log.regime_multiplier is the AS-APPLIED effective value
  (post-toggle, post-stale) — risk_engine.run_risk_calculator sets
  regime_mult = 1.0 when apply_regime_multiplier=False OR when
  regime_stale, then persists THAT value into pre_trade_log. So:

      x1_pnl = closed_positions.net_pnl / pre_trade_log.regime_multiplier

  yields the correct counterfactual under the plan-doc's linear-
  scaling assumption (P&L ∝ size at retail volume; fees linear in
  notional; slippage super-linear is a small second-order caveat).

Excluded from the two-track (would corrupt the comparison):
  • regime_multiplier IS NULL (pre-T157 row — decision unrecorded)
  • regime_multiplier <= 0  (invalid — multiplier should never be
                              0 or negative; defensive guard)
  • calc_id IS NULL/empty   (trade not linked to a calc — manual
                              entry, pre-T87 row, etc.)

Included with delta=0 by construction (no scaling occurred):
  • apply_regime_multiplier=0  (toggle OFF — mult forced 1.0)
  • regime_stale=1             (stale fallback — mult forced 1.0)
  • neutral / risk_on_choppy   (regime chose 1.0)

These rows are kept in the two-track stream + flagged so analytics
can tell apart "regime active but ineffective" from "regime not
applied".

What this file pins:
  • get_dual_pnl_trades + get_dual_pnl_summary methods exist on the
    database manager.
  • Active de-risk row (mult=0.7): actual=70 → x1=100, delta=-30.
  • Active re-risk row (mult=1.2): actual=120 → x1=100, delta=+20.
  • Toggle-OFF row (mult=1.0, apply=0): x1=actual, delta=0,
    classified n_neutral_or_off in summary.
  • Stale-fallback (mult=1.0, stale=1): x1=actual, delta=0,
    classified n_neutral_or_off.
  • Multiplier NULL: row excluded entirely.
  • Multiplier 0: row excluded (division guard).
  • Empty calc_id: row excluded.
  • Trade with no matching pre_trade_log row: excluded (INNER JOIN).
  • Summary aggregates: actual_total, x1_total, delta_total,
    n_regime_active vs n_neutral_or_off — load-bearing distinction.
  • Linear-scaling math: x1 = actual / mult exactly (asserted on
    constructed numbers).
  • Date-range filter honoured.

Run: pytest tests/test_task167_dual_pnl.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def test_db():
    from core.database import DatabaseManager

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    yield db
    await db.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


async def _insert_pretrade(
    db,
    calc_id: str,
    *,
    regime_label=None,
    regime_multiplier=None,
    regime_mode=None,
    apply_regime_multiplier=None,
    regime_stale=None,
    account_id: int = 1,
) -> None:
    """Helper — minimal insert via the public insert_pre_trade_log path
    so we exercise the T157+T165 coercion logic too."""
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


async def _insert_closed_position(
    db,
    calc_id: str,
    *,
    net_pnl: float,
    exit_time_ms: int,
    account_id: int = 1,
    symbol: str = "BTCUSDT",
) -> None:
    """Insert a minimal closed_positions row with a calc_id link."""
    await db._conn.execute(
        """
        INSERT INTO closed_positions
            (account_id, symbol, exit_time_ms, net_pnl, calc_id,
             terminal_position_id, direction, quantity, entry_price,
             exit_price, entry_time_ms, realized_pnl, total_fees)
        VALUES (?, ?, ?, ?, ?, ?, 'LONG', 0.01, 80000, 80000, 0, ?, 0)
        """,
        (account_id, symbol, exit_time_ms, net_pnl, calc_id,
         f"term-{calc_id}", net_pnl),
    )
    await db._conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Linear-scaling math correctness (the core assertion)
# ─────────────────────────────────────────────────────────────────────────────


class TestLinearScalingMath:
    """x1 = actual / multiplier under linear-scaling. Verify on
    constructed multipliers spanning de-risk + re-risk."""

    @pytest.mark.asyncio
    async def test_defensive_de_risk_actual_70_x1_100(self, test_db):
        """Defensive regime (mult=0.7): actual=70 USDT → x1=100,
        delta=-30 (regime sizing COST 30 vs what x1 would have made)."""
        await _insert_pretrade(
            test_db, calc_id="t167-def",
            regime_label="risk_off_defensive",
            regime_multiplier=0.7,
            regime_mode="full",
            apply_regime_multiplier=True,
            regime_stale=False,
        )
        await _insert_closed_position(
            test_db, calc_id="t167-def",
            net_pnl=70.0, exit_time_ms=1716000000000,
        )

        rows = await test_db.get_dual_pnl_trades(account_id=1)
        assert len(rows) == 1
        r = rows[0]
        assert r["actual_pnl"] == pytest.approx(70.0)
        assert r["regime_multiplier"] == pytest.approx(0.7)
        assert r["x1_pnl"] == pytest.approx(100.0)
        assert r["delta"] == pytest.approx(-30.0)

    @pytest.mark.asyncio
    async def test_trending_re_risk_actual_120_x1_100(self, test_db):
        """Trending regime (mult=1.2): actual=120 → x1=100,
        delta=+20 (regime sizing HELPED by 20 vs x1)."""
        await _insert_pretrade(
            test_db, calc_id="t167-trend",
            regime_label="risk_on_trending",
            regime_multiplier=1.2,
            regime_mode="full",
            apply_regime_multiplier=True,
            regime_stale=False,
        )
        await _insert_closed_position(
            test_db, calc_id="t167-trend",
            net_pnl=120.0, exit_time_ms=1716000000000,
        )

        rows = await test_db.get_dual_pnl_trades(account_id=1)
        assert len(rows) == 1
        r = rows[0]
        assert r["x1_pnl"] == pytest.approx(100.0)
        assert r["delta"] == pytest.approx(20.0)

    @pytest.mark.asyncio
    async def test_negative_pnl_scales_same_way(self, test_db):
        """A losing trade under defensive (mult=0.5): actual=-50
        loss → x1=-100 loss → delta=+50 (regime sizing SAVED 50)."""
        await _insert_pretrade(
            test_db, calc_id="t167-loss",
            regime_label="risk_off_defensive",
            regime_multiplier=0.5,
            regime_mode="full",
            apply_regime_multiplier=True,
            regime_stale=False,
        )
        await _insert_closed_position(
            test_db, calc_id="t167-loss",
            net_pnl=-50.0, exit_time_ms=1716000000000,
        )

        rows = await test_db.get_dual_pnl_trades(account_id=1)
        r = rows[0]
        assert r["x1_pnl"] == pytest.approx(-100.0)
        # Delta positive: regime de-sizing avoided 50 USDT of loss.
        assert r["delta"] == pytest.approx(50.0)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Inclusion-with-delta-0 rows (toggle-OFF + stale + neutral)
# ─────────────────────────────────────────────────────────────────────────────


class TestZeroDeltaRowsIncluded:
    """Rows where actual == x1 by construction are KEPT in the
    stream + flagged so analytics can tell apart 'regime ineffective'
    from 'regime not active'."""

    @pytest.mark.asyncio
    async def test_toggle_off_row_included_delta_zero(self, test_db):
        await _insert_pretrade(
            test_db, calc_id="t167-toggle-off",
            regime_label="risk_off_panic",          # regime said panic
            regime_multiplier=1.0,                  # but toggle forced 1.0
            regime_mode="full",
            apply_regime_multiplier=False,
            regime_stale=False,
        )
        await _insert_closed_position(
            test_db, calc_id="t167-toggle-off",
            net_pnl=50.0, exit_time_ms=1716000000000,
        )

        rows = await test_db.get_dual_pnl_trades(account_id=1)
        assert len(rows) == 1
        r = rows[0]
        assert r["x1_pnl"] == pytest.approx(50.0)
        assert r["delta"] == pytest.approx(0.0)
        # Flag preserved so analytics can bucket this as toggle-OFF.
        assert r["apply_regime_multiplier"] == 0

    @pytest.mark.asyncio
    async def test_stale_fallback_row_included_delta_zero(self, test_db):
        await _insert_pretrade(
            test_db, calc_id="t167-stale",
            regime_label="risk_off_defensive",      # regime SAID defensive
            regime_multiplier=1.0,                  # but stale → forced 1.0
            regime_mode="full",
            apply_regime_multiplier=True,
            regime_stale=True,
        )
        await _insert_closed_position(
            test_db, calc_id="t167-stale",
            net_pnl=30.0, exit_time_ms=1716000000000,
        )

        rows = await test_db.get_dual_pnl_trades(account_id=1)
        assert len(rows) == 1
        r = rows[0]
        assert r["delta"] == pytest.approx(0.0)
        assert r["regime_stale"] == 1

    @pytest.mark.asyncio
    async def test_neutral_label_row_included_delta_zero(self, test_db):
        """neutral regime → mult 1.0 by config → actual==x1."""
        await _insert_pretrade(
            test_db, calc_id="t167-neutral",
            regime_label="neutral",
            regime_multiplier=1.0,
            regime_mode="macro_only",
            apply_regime_multiplier=True,
            regime_stale=False,
        )
        await _insert_closed_position(
            test_db, calc_id="t167-neutral",
            net_pnl=15.0, exit_time_ms=1716000000000,
        )

        rows = await test_db.get_dual_pnl_trades(account_id=1)
        assert len(rows) == 1
        assert rows[0]["delta"] == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Excluded rows (division guards + missing data)
# ─────────────────────────────────────────────────────────────────────────────


class TestExclusions:
    @pytest.mark.asyncio
    async def test_null_multiplier_row_excluded(self, test_db):
        """Pre-T157 row carries NULL multiplier → exclude (can't
        compute x1 without it; including would imply x1=actual which
        is wrong — we don't KNOW what the regime would have done)."""
        await _insert_pretrade(test_db, calc_id="t167-null-mult")
        # No regime_multiplier passed → NULL in DB.
        await _insert_closed_position(
            test_db, calc_id="t167-null-mult",
            net_pnl=50.0, exit_time_ms=1716000000000,
        )
        rows = await test_db.get_dual_pnl_trades(account_id=1)
        assert rows == [], (
            "Task 167 regression: NULL regime_multiplier row was "
            "included in dual-P&L stream — must be excluded so the "
            "two-track doesn't conflate 'unknown' with 'neutral'."
        )

    @pytest.mark.asyncio
    async def test_zero_multiplier_row_excluded_division_guard(self, test_db):
        """multiplier <= 0 → exclude (division guard; multiplier
        should never legitimately be 0)."""
        await _insert_pretrade(
            test_db, calc_id="t167-zero-mult",
            regime_multiplier=0.0,
            apply_regime_multiplier=True,
        )
        await _insert_closed_position(
            test_db, calc_id="t167-zero-mult",
            net_pnl=50.0, exit_time_ms=1716000000000,
        )
        rows = await test_db.get_dual_pnl_trades(account_id=1)
        assert rows == [], (
            "Task 167 regression: zero multiplier reached the dual-"
            "P&L query — division guard failed."
        )

    @pytest.mark.asyncio
    async def test_no_pretrade_row_excluded_inner_join(self, test_db):
        """Closed trade with no matching pre_trade_log row (e.g.
        manual fill before T87 wired calc_id) → INNER JOIN drops it."""
        await _insert_closed_position(
            test_db, calc_id="t167-orphan",
            net_pnl=50.0, exit_time_ms=1716000000000,
        )
        rows = await test_db.get_dual_pnl_trades(account_id=1)
        assert rows == []

    @pytest.mark.asyncio
    async def test_empty_calc_id_excluded(self, test_db):
        """Pre-T87 / manual trade with empty calc_id → exclude."""
        await _insert_pretrade(
            test_db, calc_id="",
            regime_multiplier=0.7,
            apply_regime_multiplier=True,
        )
        # Insert closed_position with empty calc_id directly.
        await test_db._conn.execute(
            """
            INSERT INTO closed_positions
                (account_id, symbol, exit_time_ms, net_pnl, calc_id,
                 terminal_position_id, direction, quantity, entry_price,
                 exit_price, entry_time_ms, realized_pnl, total_fees)
            VALUES (1, 'BTCUSDT', 1716000000000, 50.0, '',
                    'term-empty', 'LONG', 0.01, 80000, 80000, 0, 50.0, 0)
            """,
        )
        await test_db._conn.commit()
        rows = await test_db.get_dual_pnl_trades(account_id=1)
        assert rows == []


# ─────────────────────────────────────────────────────────────────────────────
# 4. Summary aggregator
# ─────────────────────────────────────────────────────────────────────────────


class TestSummary:
    @pytest.mark.asyncio
    async def test_empty_summary(self, test_db):
        s = await test_db.get_dual_pnl_summary(account_id=1)
        assert s["n_trades"] == 0
        assert s["actual_total"] == 0.0
        assert s["x1_total"] == 0.0
        assert s["delta_total"] == 0.0
        assert s["n_regime_active"] == 0
        assert s["n_neutral_or_off"] == 0

    @pytest.mark.asyncio
    async def test_summary_aggregates_actual_x1_delta(self, test_db):
        """3 trades: defensive 0.7/+70, trending 1.2/+120, neutral 1.0/+15.
        Expect actual_total=205, x1_total=215 (100+100+15), delta=-10.
        Active count = 2 (defensive + trending); neutral_or_off = 1."""
        await _insert_pretrade(
            test_db, calc_id="s1",
            regime_label="risk_off_defensive", regime_multiplier=0.7,
            regime_mode="full", apply_regime_multiplier=True, regime_stale=False,
        )
        await _insert_pretrade(
            test_db, calc_id="s2",
            regime_label="risk_on_trending", regime_multiplier=1.2,
            regime_mode="full", apply_regime_multiplier=True, regime_stale=False,
        )
        await _insert_pretrade(
            test_db, calc_id="s3",
            regime_label="neutral", regime_multiplier=1.0,
            regime_mode="macro_only", apply_regime_multiplier=True, regime_stale=False,
        )
        await _insert_closed_position(test_db, calc_id="s1", net_pnl=70.0,  exit_time_ms=1716000001000)
        await _insert_closed_position(test_db, calc_id="s2", net_pnl=120.0, exit_time_ms=1716000002000)
        await _insert_closed_position(test_db, calc_id="s3", net_pnl=15.0,  exit_time_ms=1716000003000)

        s = await test_db.get_dual_pnl_summary(account_id=1)
        assert s["n_trades"] == 3
        assert s["actual_total"] == pytest.approx(205.0)
        assert s["x1_total"]     == pytest.approx(215.0)   # 100 + 100 + 15
        assert s["delta_total"]  == pytest.approx(-10.0)
        assert s["n_regime_active"]  == 2
        assert s["n_neutral_or_off"] == 1

    @pytest.mark.asyncio
    async def test_stale_row_classified_as_neutral_or_off_not_active(self, test_db):
        """The load-bearing distinction: a row with apply=1 + mult!=1
        is 'regime_active'; apply=0 OR mult==1.0 OR stale=1 is
        'neutral_or_off'. Test the stale-flag branch — apply=1 but
        stale forced mult=1.0."""
        await _insert_pretrade(
            test_db, calc_id="s-stale",
            regime_label="risk_off_defensive",
            regime_multiplier=1.0,        # stale forced 1.0
            apply_regime_multiplier=True,
            regime_stale=True,
        )
        await _insert_closed_position(
            test_db, calc_id="s-stale", net_pnl=50.0, exit_time_ms=1716000001000,
        )
        s = await test_db.get_dual_pnl_summary(account_id=1)
        assert s["n_regime_active"] == 0, (
            "Task 167 regression: stale-flag row was counted as "
            "regime_active — must be neutral_or_off since stale forces "
            "multiplier=1.0 and no scaling occurred."
        )
        assert s["n_neutral_or_off"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 5. Filters (account_id + date range)
# ─────────────────────────────────────────────────────────────────────────────


class TestFilters:
    @pytest.mark.asyncio
    async def test_account_id_filter(self, test_db):
        """Per-account isolation — account 2's trades don't leak into
        account 1's two-track."""
        await _insert_pretrade(
            test_db, calc_id="acc1", account_id=1,
            regime_multiplier=0.7, apply_regime_multiplier=True,
        )
        await _insert_pretrade(
            test_db, calc_id="acc2", account_id=2,
            regime_multiplier=0.7, apply_regime_multiplier=True,
        )
        await _insert_closed_position(test_db, calc_id="acc1", account_id=1,
                                      net_pnl=70.0, exit_time_ms=1716000001000)
        await _insert_closed_position(test_db, calc_id="acc2", account_id=2,
                                      net_pnl=70.0, exit_time_ms=1716000002000)

        rows1 = await test_db.get_dual_pnl_trades(account_id=1)
        rows2 = await test_db.get_dual_pnl_trades(account_id=2)
        assert len(rows1) == 1 and rows1[0]["account_id"] == 1
        assert len(rows2) == 1 and rows2[0]["account_id"] == 2

    @pytest.mark.asyncio
    async def test_date_range_filter(self, test_db):
        await _insert_pretrade(test_db, calc_id="early", regime_multiplier=0.7, apply_regime_multiplier=True)
        await _insert_pretrade(test_db, calc_id="late",  regime_multiplier=0.7, apply_regime_multiplier=True)
        await _insert_closed_position(test_db, calc_id="early", net_pnl=70.0, exit_time_ms=1_000_000_000_000)
        await _insert_closed_position(test_db, calc_id="late",  net_pnl=70.0, exit_time_ms=2_000_000_000_000)

        # Window covers only the late trade
        rows = await test_db.get_dual_pnl_trades(
            account_id=1, from_ms=1_500_000_000_000, to_ms=9_999_999_999_000,
        )
        assert len(rows) == 1
        assert rows[0]["calc_id"] == "late"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Sort ordering (exit_time_ms ASC — forward-two-track timeline)
# ─────────────────────────────────────────────────────────────────────────────


class TestSortOrder:
    @pytest.mark.asyncio
    async def test_rows_sorted_by_exit_time_asc(self, test_db):
        """Forward-two-track is a timeline — analytics will likely
        consume in order. Pin ASC sort."""
        for cid, t in [("c", 3000), ("a", 1000), ("b", 2000)]:
            await _insert_pretrade(
                test_db, calc_id=cid,
                regime_multiplier=0.7, apply_regime_multiplier=True,
            )
            await _insert_closed_position(
                test_db, calc_id=cid, net_pnl=70.0, exit_time_ms=t,
            )
        rows = await test_db.get_dual_pnl_trades(account_id=1)
        assert [r["calc_id"] for r in rows] == ["a", "b", "c"]


# ─────────────────────────────────────────────────────────────────────────────
# 7. Source pins
# ─────────────────────────────────────────────────────────────────────────────


class TestT167SourcePins:
    def test_db_regime_has_task_167_anchor(self):
        from pathlib import Path
        text = (
            Path(__file__).parent.parent / "core" / "db_regime.py"
        ).read_text(encoding="utf-8")
        assert "Task 167" in text or "T167" in text

    def test_query_uses_calc_id_inner_join(self):
        """Source pin: the join must be INNER on calc_id — LEFT JOIN
        would surface orphan closed_positions rows with NULL regime
        fields and pollute the comparison."""
        from pathlib import Path
        text = (
            Path(__file__).parent.parent / "core" / "db_regime.py"
        ).read_text(encoding="utf-8")
        executing = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("--")
        )
        assert "INNER JOIN pre_trade_log" in executing
        assert "pt.calc_id = cp.calc_id" in executing

    def test_query_excludes_null_and_nonpositive_multiplier(self):
        from pathlib import Path
        text = (
            Path(__file__).parent.parent / "core" / "db_regime.py"
        ).read_text(encoding="utf-8")
        assert "pt.regime_multiplier IS NOT NULL" in text
        assert "pt.regime_multiplier > 0" in text

    def test_method_signatures_present(self):
        """get_dual_pnl_trades + get_dual_pnl_summary must both exist
        on the database manager (RegimeMixin)."""
        from core.database import DatabaseManager
        assert hasattr(DatabaseManager, "get_dual_pnl_trades")
        assert hasattr(DatabaseManager, "get_dual_pnl_summary")

    def test_linear_scaling_caveat_documented(self):
        """Source pin: the linear-scaling assumption + slippage caveat
        must be documented in core/db_regime.py near the dual-P&L
        section so future readers see the caveat without spelunking
        the plan doc."""
        from pathlib import Path
        text = (
            Path(__file__).parent.parent / "core" / "db_regime.py"
        ).read_text(encoding="utf-8")
        assert "linear" in text.lower() and "scaling" in text.lower()
        assert "slippage" in text.lower()
