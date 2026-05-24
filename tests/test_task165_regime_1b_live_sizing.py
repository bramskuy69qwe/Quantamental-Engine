"""
Task 165 regression tests — regime build 1b (live sizing).

Re-investigation finding (per CLAUDE.md re-investigation discipline):
  The T165 spec described the multiplier as "never scaled a trade today".
  Investigation shows T157 already wired `size = size_raw * regime_mult`
  into core/risk_engine.py:run_risk_calculator at line ~433. What was
  actually missing — and is fixed in T165 — is FOUR things:

  1. HysteresisWrapper was imported in regime_classifier.py but never
     INSTANTIATED in production. compute_current_regime called
     classify_regime() raw on each tick → no flap suppression in live
     sizing path.

  2. HysteresisWrapper was SYMMETRIC (single confirmations=N applied in
     both directions). T165 makes it ASYMMETRIC + multiplier-keyed:
     de-risk fast (N_derisk=1), re-risk slow (N_rerisk=2), equal-mult
     immediate.

  3. regime_stale was emitted in the calc dict (risk_engine.py:655) but
     NEVER PERSISTED to pre_trade_log. Forward analytics had to re-derive
     staleness from RegimeState + now-mutable REGIME_STALE_MINUTES — not
     reliable. T165 adds the column (migration 013 + CREATE TABLE + db_
     trades insert).

  4. MED-017 mark-price freshness: data_cache.apply_mark_price stored
     mark prices without timestamps. Risk-engine sized off equity that
     could be silently outdated after a WS outage. T165 adds a parallel
     timestamps dict + risk_engine surfaces a mark_price_stale flag +
     log.warning at calc time.

What this file pins:

  - HysteresisWrapper asymmetric API: confirmations_derisk +
    confirmations_rerisk per-direction; equal-multiplier immediate
    flip; multiplier-keyed (not label-keyed).
  - HysteresisWrapper.step(raw_result) public entry point.
  - compute_current_regime routes its raw label through the
    module-singleton hysteresis (state persists across ticks).
  - regime_stale persisted to pre_trade_log via insert_pre_trade_log.
  - Fresh-install + upgrade-shadow-migration paths both yield the
    regime_stale column.
  - MED-017: mark_price_cache writes timestamp the entry; risk_engine
    surfaces mark_price_stale + mark_price_age on the calc dict; warns
    when stale; "never received" is treated as stale.
  - The pre-existing multiplier wiring (T157) remains correct:
    multiplier-then-gate ordering, toggle OFF → 1.0, stale → 1.0,
    would_be_size preserved for x1 recoverability.

Run: pytest tests/test_task165_regime_1b_live_sizing.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import time as _time
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def test_db():
    """Temp file-backed DatabaseManager — mirrors T157 fixture."""
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


def _minimal_calc(**overrides) -> dict:
    """Minimal pre_trade_log calc dict — mirrors T157 helper."""
    base = {
        "ticker": "BTCUSDT",
        "average": 80000.0,
        "side": "long",
        "size": 0.01,
        "notional": 800.0,
        "tp_price": 82000.0,
        "sl_price": 79000.0,
        "eligible": True,
        "calc_id": "task165-calc-1",
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# 1. HysteresisWrapper asymmetric per-direction (multiplier-keyed)
# ─────────────────────────────────────────────────────────────────────────────


class _ScriptedClassifier:
    """Returns a pre-scripted sequence of RegimeResults regardless of signals."""

    def __init__(self, sequence):
        self._seq = list(sequence)
        self._i = 0

    def classify(self, signals):  # noqa: ARG002
        if self._i >= len(self._seq):
            return self._seq[-1]
        out = self._seq[self._i]
        self._i += 1
        return out


class TestHysteresisAsymmetric:
    """Asymmetric per-direction confirmations keyed on the pending result's
    multiplier vs the current's multiplier.
    """

    def test_derisk_flips_at_n1_default(self):
        """De-risk: pending.multiplier < current.multiplier. Default
        config N_derisk=1 → flip on first sighting of the lower-mult
        label."""
        from core.regime import HysteresisWrapper, RegimeResult

        seq = [
            RegimeResult("neutral", 1.0),
            RegimeResult("risk_off_defensive", 0.7),  # de-risk; one tick
        ]
        cls = _ScriptedClassifier(seq)
        hyst = HysteresisWrapper(cls, confirmations_derisk=1, confirmations_rerisk=3)

        assert hyst.classify({}).label == "neutral"
        out = hyst.classify({})
        assert out.label == "risk_off_defensive"
        assert out.multiplier == pytest.approx(0.7)

    def test_rerisk_requires_n2(self):
        """Re-risk: pending.multiplier > current.multiplier. With
        confirmations_rerisk=2, single tick of the higher-mult label
        does NOT flip; second confirming tick does."""
        from core.regime import HysteresisWrapper, RegimeResult

        seq = [
            RegimeResult("risk_off_defensive", 0.7),
            RegimeResult("risk_on_trending", 1.2),    # tick 1 — pending
            RegimeResult("risk_on_trending", 1.2),    # tick 2 — confirm → flip
        ]
        cls = _ScriptedClassifier(seq)
        hyst = HysteresisWrapper(cls, confirmations_derisk=1, confirmations_rerisk=2)

        assert hyst.classify({}).label == "risk_off_defensive"
        # First risk-on tick: held → still defensive
        held = hyst.classify({})
        assert held.label == "risk_off_defensive"
        assert held.multiplier == pytest.approx(0.7)
        # Second risk-on tick: flip confirmed
        flipped = hyst.classify({})
        assert flipped.label == "risk_on_trending"
        assert flipped.multiplier == pytest.approx(1.2)

    def test_equal_multiplier_flips_immediately(self):
        """Equal-multiplier label change (e.g. neutral 1.0× ↔ risk_on_
        choppy 1.0×) bypasses hysteresis — no sizing delta to suppress.
        Even with both directions at N≥5, an equal-mult change flips
        on the first tick."""
        from core.regime import HysteresisWrapper, RegimeResult

        seq = [
            RegimeResult("neutral", 1.0),
            RegimeResult("risk_on_choppy", 1.0),     # equal mult → instant
        ]
        cls = _ScriptedClassifier(seq)
        hyst = HysteresisWrapper(cls, confirmations_derisk=5, confirmations_rerisk=5)

        assert hyst.classify({}).label == "neutral"
        flipped = hyst.classify({})
        assert flipped.label == "risk_on_choppy"
        assert flipped.multiplier == pytest.approx(1.0)

    def test_multiplier_keyed_not_label_keyed(self):
        """Direction is keyed on the MULTIPLIER comparison, not label
        membership. A new label at multiplier 0.5× (less than current
        0.7×) is still de-risk and uses N_derisk."""
        from core.regime import HysteresisWrapper, RegimeResult

        seq = [
            RegimeResult("risk_off_defensive", 0.7),
            RegimeResult("risk_off_severe_imaginary", 0.5),  # de-risk
        ]
        cls = _ScriptedClassifier(seq)
        hyst = HysteresisWrapper(cls, confirmations_derisk=1, confirmations_rerisk=2)

        assert hyst.classify({}).label == "risk_off_defensive"
        out = hyst.classify({})
        assert out.label == "risk_off_severe_imaginary"
        assert out.multiplier == pytest.approx(0.5)

    def test_pending_resets_when_raw_returns_to_current(self):
        """If raw flaps back to current mid-pending, the pending count
        resets — protection against borderline flap that re-confirms
        current."""
        from core.regime import HysteresisWrapper, RegimeResult

        seq = [
            RegimeResult("neutral", 1.0),
            RegimeResult("risk_on_trending", 1.2),   # tick 1 pending re-risk
            RegimeResult("neutral", 1.0),            # back to current — reset
            RegimeResult("risk_on_trending", 1.2),   # tick 1 again (count=1)
        ]
        cls = _ScriptedClassifier(seq)
        hyst = HysteresisWrapper(cls, confirmations_derisk=1, confirmations_rerisk=2)

        assert hyst.classify({}).label == "neutral"
        assert hyst.classify({}).label == "neutral"           # held
        assert hyst.classify({}).label == "neutral"           # back to current
        assert hyst.classify({}).label == "neutral"           # 1 again, still held

    def test_backwards_compat_with_single_confirmations(self):
        """T163's `confirmations=N` constructor still works — applies N
        to both directions (the pre-T165 behaviour). A test in
        test_task163_regime_1a.py exercises this; we mirror it here so
        any T165 change that breaks the old API is caught locally."""
        from core.regime import HysteresisWrapper, RegimeResult

        seq = [
            RegimeResult("neutral", 1.0),
            RegimeResult("risk_off_defensive", 0.7),  # tick 1
            RegimeResult("risk_off_defensive", 0.7),  # tick 2 → confirms
        ]
        cls = _ScriptedClassifier(seq)
        hyst = HysteresisWrapper(cls, confirmations=2)

        assert hyst.classify({}).label == "neutral"
        assert hyst.classify({}).label == "neutral"            # held (1/2)
        assert hyst.classify({}).label == "risk_off_defensive" # flipped (2/2)


class TestHysteresisStepEntryPoint:
    """The new `step(raw_result)` entry point allows callers that already
    have a RegimeResult to apply hysteresis without a redundant
    classifier invocation. compute_current_regime uses this for both
    DB-fed and live-classified source paths."""

    def test_step_applies_same_state_machine_as_classify(self):
        from core.regime import HysteresisWrapper, RegimeResult

        cls = _ScriptedClassifier([RegimeResult("neutral", 1.0)])
        hyst = HysteresisWrapper(cls, confirmations_derisk=1, confirmations_rerisk=2)

        # Seed via step
        out0 = hyst.step(RegimeResult("neutral", 1.0))
        assert out0.label == "neutral"

        # Re-risk requires 2 confirmations via step too
        held = hyst.step(RegimeResult("risk_on_trending", 1.2))
        assert held.label == "neutral"
        flipped = hyst.step(RegimeResult("risk_on_trending", 1.2))
        assert flipped.label == "risk_on_trending"

    def test_step_does_not_invoke_inner_classifier(self):
        """step() must NOT call self._classifier.classify(). If it did,
        the wrapper would re-derive the label from synthetic signals
        and ignore the caller's pre-built result."""
        from core.regime import HysteresisWrapper, RegimeResult

        class _Sentinel:
            calls = 0
            def classify(self, _signals):
                _Sentinel.calls += 1
                return RegimeResult("DERIVED-LABEL", 9.99)

        hyst = HysteresisWrapper(_Sentinel(), confirmations_derisk=1, confirmations_rerisk=1)
        out = hyst.step(RegimeResult("PROVIDED-LABEL", 0.5))
        assert out.label == "PROVIDED-LABEL"
        assert out.multiplier == pytest.approx(0.5)
        assert _Sentinel.calls == 0


# ─────────────────────────────────────────────────────────────────────────────
# 2. compute_current_regime wires HysteresisWrapper (production path)
# ─────────────────────────────────────────────────────────────────────────────


class TestLiveHysteresisWiring:
    """The module-level _LIVE_HYSTERESIS singleton is constructed and
    wired into compute_current_regime. State persists across ticks."""

    def test_live_singleton_exists_with_asymmetric_config(self):
        from core.regime_classifier import _LIVE_HYSTERESIS
        import config

        # SLF001 fine in tests — we're verifying construction.
        assert _LIVE_HYSTERESIS._n_derisk == config.REGIME_CONFIRMATIONS_DERISK
        assert _LIVE_HYSTERESIS._n_rerisk == config.REGIME_CONFIRMATIONS_RERISK

    def test_default_config_is_derisk_fast_rerisk_slow(self):
        import config
        assert config.REGIME_CONFIRMATIONS_DERISK == 1, (
            "Task 165 spec: default derisk N=1 (de-risk fast — capital "
            "protection on first signal of worsening regime)"
        )
        assert config.REGIME_CONFIRMATIONS_RERISK == 2, (
            "Task 165 spec: default rerisk N=2 (re-risk slow — don't "
            "lift exposure on a single benign tick)"
        )

    def test_compute_current_regime_source_pin_uses_hysteresis(self):
        """Source pin: compute_current_regime calls _LIVE_HYSTERESIS.step()."""
        from pathlib import Path
        src = Path(__file__).parent.parent / "core" / "regime_classifier.py"
        text = src.read_text(encoding="utf-8")
        # Strip comment lines (T161 anti-false-positive trick).
        executing = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("#")
        )
        assert "_LIVE_HYSTERESIS.step(" in executing, (
            "Task 165 regression: compute_current_regime must funnel its "
            "raw label through the live hysteresis singleton."
        )

    def test_classify_regime_pure_does_NOT_use_hysteresis(self):
        """classify_regime() (the pure-function entry point) stays raw —
        tests and callers wanting a stateless label-from-signals function
        must not be entangled in module-singleton state."""
        from core.regime_classifier import classify_regime, _LIVE_HYSTERESIS
        _LIVE_HYSTERESIS.reset()

        # A panic-screen call should return raw panic even though the
        # singleton has never seen a prior tick.
        out = classify_regime({"vix_close": 50.0, "hy_spread": 6.0}, mode="macro_only")
        assert out == "risk_off_panic"
        # Singleton remains at initial state because classify_regime
        # bypassed it.
        assert _LIVE_HYSTERESIS.current is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. regime_stale persisted to pre_trade_log (T157 follow-up)
# ─────────────────────────────────────────────────────────────────────────────


class TestRegimeStaleColumn:
    """Migration 013 + CREATE TABLE + insert_pre_trade_log persist
    regime_stale alongside the four T157 columns."""

    @pytest.mark.asyncio
    async def test_regime_stale_column_present(self, test_db):
        async with test_db._conn.execute("PRAGMA table_info(pre_trade_log)") as cur:
            cols = {row[1]: row for row in await cur.fetchall()}
        assert "regime_stale" in cols, (
            "Task 165 regression: pre_trade_log missing regime_stale "
            "column after initialize()."
        )
        notnull, dflt = cols["regime_stale"][3], cols["regime_stale"][4]
        assert notnull == 0, "regime_stale must be nullable (NULL = pre-T165 row)"
        assert dflt is None, "regime_stale must default NULL — same discipline as T157"

    @pytest.mark.asyncio
    async def test_regime_stale_true_persists_as_1(self, test_db):
        calc = _minimal_calc(
            calc_id="task165-stale-true",
            regime_label="neutral",
            regime_multiplier=1.0,
            regime_mode="full",
            apply_regime_multiplier=True,
            regime_stale=True,
        )
        await test_db.insert_pre_trade_log(calc)
        async with test_db._conn.execute(
            "SELECT regime_stale FROM pre_trade_log "
            "WHERE calc_id = 'task165-stale-true'"
        ) as cur:
            row = await cur.fetchone()
        assert row[0] == 1

    @pytest.mark.asyncio
    async def test_regime_stale_false_persists_as_0(self, test_db):
        calc = _minimal_calc(
            calc_id="task165-stale-false",
            regime_label="risk_on_trending",
            regime_multiplier=1.2,
            regime_mode="full",
            apply_regime_multiplier=True,
            regime_stale=False,
        )
        await test_db.insert_pre_trade_log(calc)
        async with test_db._conn.execute(
            "SELECT regime_stale FROM pre_trade_log "
            "WHERE calc_id = 'task165-stale-false'"
        ) as cur:
            row = await cur.fetchone()
        assert row[0] == 0

    @pytest.mark.asyncio
    async def test_regime_stale_missing_lands_null(self, test_db):
        """Calc dict without regime_stale key → NULL. Distinguishes
        pre-T165 rows from rows where the engine explicitly recorded
        True/False."""
        calc = _minimal_calc(calc_id="task165-stale-missing")
        assert "regime_stale" not in calc
        await test_db.insert_pre_trade_log(calc)
        async with test_db._conn.execute(
            "SELECT regime_stale FROM pre_trade_log "
            "WHERE calc_id = 'task165-stale-missing'"
        ) as cur:
            row = await cur.fetchone()
        assert row[0] is None

    @pytest.mark.asyncio
    async def test_distinguishes_stale_x1_from_toggle_off_x1(self, test_db):
        """Two rows both with multiplier=1.0 must be distinguishable
        by analytics: stale → fallback to 1.0; toggle-OFF → forced 1.0.
        T157 already let analytics tell apart toggle-OFF; T165 adds the
        stale dimension."""
        await test_db.insert_pre_trade_log(_minimal_calc(
            calc_id="task165-stale-x1",
            regime_label="risk_off_panic",
            regime_multiplier=1.0,
            apply_regime_multiplier=True,
            regime_stale=True,
        ))
        await test_db.insert_pre_trade_log(_minimal_calc(
            calc_id="task165-toggle-x1",
            regime_label="risk_off_panic",
            regime_multiplier=1.0,
            apply_regime_multiplier=False,
            regime_stale=False,
        ))
        async with test_db._conn.execute(
            "SELECT calc_id, regime_multiplier, apply_regime_multiplier, regime_stale "
            "FROM pre_trade_log WHERE calc_id LIKE 'task165-%-x1' ORDER BY calc_id"
        ) as cur:
            rows = list(await cur.fetchall())
        stale_row = next(r for r in rows if r[0] == "task165-stale-x1")
        toggle_row = next(r for r in rows if r[0] == "task165-toggle-x1")
        assert stale_row[1] == pytest.approx(1.0) and stale_row[2] == 1 and stale_row[3] == 1
        assert toggle_row[1] == pytest.approx(1.0) and toggle_row[2] == 0 and toggle_row[3] == 0


class TestMigration013File:
    """Standalone migration 013 file exists for split-DB setups (not just
    the in-DatabaseManager shadow ALTER)."""

    def test_migration_013_file_exists(self):
        from pathlib import Path
        mig = (
            Path(__file__).parent.parent
            / "core" / "migrations"
            / "013_v2_5_pretrade_regime_stale.sql"
        )
        assert mig.exists(), (
            "Task 165 regression: 013_v2_5_pretrade_regime_stale.sql "
            "must exist as a standalone migration so split-DB account "
            "DBs receive the column on next runner pass."
        )

    def test_migration_013_correctly_headered(self):
        from pathlib import Path
        mig = (
            Path(__file__).parent.parent
            / "core" / "migrations"
            / "013_v2_5_pretrade_regime_stale.sql"
        )
        text = mig.read_text(encoding="utf-8")
        assert "migration: per_account" in text, (
            "Task 165 regression: migration 013 must be per_account "
            "(pre_trade_log is per-account in split-DB layout)."
        )
        assert "ADD COLUMN regime_stale INTEGER" in text


# ─────────────────────────────────────────────────────────────────────────────
# 4. MED-017 — mark-price freshness
# ─────────────────────────────────────────────────────────────────────────────


class TestMarkPriceFreshness:
    """data_cache.apply_mark_price now stamps the parallel timestamps
    dict; risk_engine surfaces mark_price_stale at calc time."""

    def test_apply_mark_price_stamps_timestamp(self):
        from core.state import app_state
        from core.data_cache import DataCache

        class _NullBus:
            def publish(self, *_args, **_kwargs): pass
            def subscribe(self, *_args, **_kwargs): pass
        cache = DataCache(_NullBus())
        app_state.mark_price_cache.clear()
        app_state.mark_price_timestamps.clear()

        before = _time.monotonic()
        cache.apply_mark_price("BTCUSDT", 80000.0)
        after = _time.monotonic()

        assert app_state.mark_price_cache["BTCUSDT"] == pytest.approx(80000.0)
        ts = app_state.mark_price_timestamps["BTCUSDT"]
        assert before <= ts <= after

    def test_missing_timestamp_treated_as_stale(self):
        """A symbol with no mark-price write ever → mark_price_stale=True,
        mark_price_age=None. 'never received' is treated as stale; we
        have nothing to claim freshness from."""
        # Source pin — the file's logic is the load-bearing assertion.
        from pathlib import Path
        src = Path(__file__).parent.parent / "core" / "risk_engine.py"
        text = src.read_text(encoding="utf-8")
        executing = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("#")
        )
        assert "mark_price_timestamps.get(ticker)" in executing
        assert "mark_price_stale = True" in executing
        assert "mark_price_age = None" in executing

    def test_calc_dict_carries_mark_price_flags(self):
        """Source pin: calc dict emits mark_price_stale + mark_price_age
        so the operator / forward analytics can act on it."""
        from pathlib import Path
        src = Path(__file__).parent.parent / "core" / "risk_engine.py"
        text = src.read_text(encoding="utf-8")
        assert '"mark_price_stale":' in text
        assert '"mark_price_age":' in text

    def test_stale_threshold_in_config(self):
        import config
        assert hasattr(config, "MARK_PRICE_STALE_SECONDS")
        assert config.MARK_PRICE_STALE_SECONDS > 0

    def test_cache_cleanup_prunes_timestamps_in_parallel(self):
        """When DataCache prunes stale symbols from mark_price_cache,
        the parallel timestamps dict must be pruned too — otherwise a
        re-added symbol with no fresh write would falsely look fresh
        from the old timestamp."""
        from pathlib import Path
        src = Path(__file__).parent.parent / "core" / "data_cache.py"
        text = src.read_text(encoding="utf-8")
        executing = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("#")
        )
        assert "mark_price_timestamps.pop(sym, None)" in executing, (
            "Task 165 regression: cache cleanup must prune timestamps "
            "alongside prices."
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. Multiplier wiring sanity (T157 pre-existing — pinned so a regression
#    that re-breaks this would surface)
# ─────────────────────────────────────────────────────────────────────────────


class TestMultiplierWiringPreserved:
    """T157 wired the multiplier (size = size_raw * regime_mult) at
    risk_engine.py. T165 must not regress this — pin the source so a
    refactor that drops the multiplication is caught."""

    def test_size_raw_multiplied_by_regime_mult(self):
        from pathlib import Path
        src = Path(__file__).parent.parent / "core" / "risk_engine.py"
        text = src.read_text(encoding="utf-8")
        executing = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("#")
        )
        assert "size      = size_raw * regime_mult" in executing or \
               "size = size_raw * regime_mult" in executing.replace("  ", " "), (
            "Task 165 regression: T157's multiplier wiring (size = size_raw "
            "* regime_mult) is missing from run_risk_calculator. T165 must "
            "not regress the live-sizing apply point."
        )

    def test_toggle_off_forces_one_x(self):
        from pathlib import Path
        src = Path(__file__).parent.parent / "core" / "risk_engine.py"
        text = src.read_text(encoding="utf-8")
        executing = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("#")
        )
        assert "if not apply_regime_multiplier:" in executing
        assert "regime_mult = 1.0" in executing

    def test_stale_regime_falls_to_one_x(self):
        from pathlib import Path
        src = Path(__file__).parent.parent / "core" / "risk_engine.py"
        text = src.read_text(encoding="utf-8")
        executing = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("#")
        )
        # The stale → 1.0 path is the else branch of the freshness check.
        assert "if regime and not regime_stale:" in executing

    def test_would_be_size_preserves_x1_recoverability(self):
        """T160's would_be_size holds the regime-scaled computed size.
        x1-equivalent is recoverable for downstream replay (1c): given
        regime_multiplier and would_be_size, x1 = would_be_size /
        regime_multiplier when multiplier > 0."""
        # Math sanity (not source-dependent).
        wbs, mult = 0.05, 0.7
        x1 = wbs / mult
        assert x1 == pytest.approx(0.05 / 0.7)
        # Source pin: would_be_size IS computed post-multiplier (i.e.
        # holds the regime-scaled size) so the division above is valid.
        from pathlib import Path
        src = Path(__file__).parent.parent / "core" / "risk_engine.py"
        text = src.read_text(encoding="utf-8")
        executing = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("#")
        )
        assert "would_be_size     = size" in executing or \
               "would_be_size = size" in executing.replace("  ", " "), (
            "Task 165: would_be_size must hold post-multiplier size so "
            "downstream replay can recover x1 via size / multiplier."
        )


# ─────────────────────────────────────────────────────────────────────────────
# 6. T165 source anchors — proof the per-task changes shipped
# ─────────────────────────────────────────────────────────────────────────────


class TestT165SourceAnchors:
    def test_hysteresis_has_task_165_anchor(self):
        from pathlib import Path
        src = Path(__file__).parent.parent / "core" / "regime" / "hysteresis.py"
        text = src.read_text(encoding="utf-8")
        assert "Task 165" in text

    def test_regime_classifier_has_t165_anchor(self):
        from pathlib import Path
        src = Path(__file__).parent.parent / "core" / "regime_classifier.py"
        text = src.read_text(encoding="utf-8")
        assert "Task 165" in text

    def test_risk_engine_has_t165_anchor(self):
        from pathlib import Path
        src = Path(__file__).parent.parent / "core" / "risk_engine.py"
        text = src.read_text(encoding="utf-8")
        assert "Task 165" in text or "T165" in text

    def test_db_trades_has_t165_anchor(self):
        from pathlib import Path
        src = Path(__file__).parent.parent / "core" / "db_trades.py"
        text = src.read_text(encoding="utf-8")
        assert "Task 165" in text

    def test_data_cache_has_t165_anchor(self):
        from pathlib import Path
        src = Path(__file__).parent.parent / "core" / "data_cache.py"
        text = src.read_text(encoding="utf-8")
        assert "Task 165" in text or "MED-017" in text
