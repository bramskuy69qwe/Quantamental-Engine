"""
Task 166 regression tests — hysteresis counts distinct signal readings,
not classification calls.

The bug T166 fixes: T165's HysteresisWrapper.step() advanced its
pending counter on every call. compute_current_regime fires every
10 minutes, but the underlying signals are daily (VIX/FRED) / 8h
(funding). So within a single day, every 10-min tick saw the same
signal values; for a re-risk transition with N_rerisk=2, the second
tick re-confirming an identical reading hit N quickly:

    tick 1 (t=0)    raw=risk_on  → pending=1
    tick 2 (t=+10m) raw=risk_on  → pending=2 → FLIP

i.e. ~20 minutes to "earn the way back up" on a single improved
daily reading — undermining the asymmetric protection. MED-029's
daily flap suppression failed for the same shape (each day has many
more than N ticks; a defensive→neutral→defensive day-to-day pattern
flipped each day).

The fix:

  step(raw, reading_id=X) — the wrapper only mutates state on
  calls where reading_id changes from the last accepted call.
  reading_id is a hashable that names the source data the call
  observed; compute_current_regime uses "db:{date}" for the
  backfilled-label path and "live:{max-signal-date}" for the live
  fallback path.

Backwards-compat: step(raw) without reading_id falls into T165
behaviour (every call counts). All 33 T165 tests pass unchanged.
classify(signals) also stays T165-compat — single-source-data
single-call shapes don't need reading_id.

What this file pins:

  - step(raw, reading_id=X) repeated with the same X does not
    advance pending; intra-reading raw label differences return
    held current.
  - Distinct reading_ids drive the counter as expected:
      * de-risk flips on 1 new reading (N_derisk=1 default)
      * re-risk requires 2 distinct readings (N_rerisk=2 default)
  - Daily flap: defensive → neutral → defensive single-reading
    sequence keeps defensive throughout (re-risk holds; defensive
    re-confirmation resets pending).
  - Equal-multiplier bypass still applies under reading-id mode.
  - reset() clears _last_reading_id (otherwise tests + per-backtest
    resets leak the gate state).
  - compute_current_regime passes the right reading_id (source pin).
  - Back-compat: step(raw) without reading_id behaves like T165.

Run: pytest tests/test_task166_hysteresis_reading_unit.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class _Stub:
    """Sentinel classifier — step() bypasses the wrapped classify()."""

    def classify(self, _signals):
        raise RuntimeError(
            "step() must not invoke the wrapped classifier — T165 pin"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Intra-reading re-ticks don't advance state (the core T166 fix)
# ─────────────────────────────────────────────────────────────────────────────


class TestIntraReadingNoOp:
    """The pre-T166 bug: re-running step() on the same source data
    advanced the pending counter. After T166, same reading_id = no-op."""

    def test_same_reading_id_holds_current_through_many_calls(self):
        from core.regime import HysteresisWrapper, RegimeResult

        h = HysteresisWrapper(_Stub(), confirmations_derisk=1, confirmations_rerisk=2)

        # Seed with neutral on day-1's reading
        seed = h.step(RegimeResult("neutral", 1.0), reading_id="2026-05-23")
        assert seed.label == "neutral"

        # Fifty intra-day re-ticks with the IMPROVED label. Pre-T166
        # would have flipped to risk_on_trending on the 2nd call
        # (re-risk N=2). T166 must hold neutral throughout.
        for _ in range(50):
            held = h.step(
                RegimeResult("risk_on_trending", 1.2),
                reading_id="2026-05-23",
            )
            assert held.label == "neutral", (
                "Task 166 regression: intra-reading re-tick advanced "
                "the hysteresis counter — should no-op on same reading_id."
            )

        # Pending state must remain unchanged.
        assert h._pending_label is None
        assert h._pending_count == 0
        assert h._last_reading_id == "2026-05-23"

    def test_same_reading_id_holds_when_pending_is_active(self):
        """If pending was accumulating across distinct readings, an
        intra-reading re-tick of the pending label must NOT increment
        pending_count or trigger the flip."""
        from core.regime import HysteresisWrapper, RegimeResult

        h = HysteresisWrapper(_Stub(), confirmations_derisk=1, confirmations_rerisk=2)

        h.step(RegimeResult("neutral", 1.0), reading_id="r1")
        # New reading → pending begins
        h.step(RegimeResult("risk_on_trending", 1.2), reading_id="r2")
        assert h._pending_label == "risk_on_trending"
        assert h._pending_count == 1

        # Intra-reading re-ticks on r2 — pending must not advance.
        for _ in range(10):
            out = h.step(RegimeResult("risk_on_trending", 1.2), reading_id="r2")
            assert out.label == "neutral"
            assert h._pending_count == 1, (
                "Task 166 regression: pending_count incremented during "
                "an intra-reading re-tick — must only advance on new readings."
            )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Asymmetric thresholds under reading-id mode
# ─────────────────────────────────────────────────────────────────────────────


class TestAsymmetricOverReadings:
    """T165's per-direction confirmation logic still holds, but now
    counts over distinct readings."""

    def test_derisk_flips_on_one_new_reading(self):
        """N_derisk=1: de-risk should flip on the first distinct
        reading after current → even though we've held current
        through many intra-reading re-ticks."""
        from core.regime import HysteresisWrapper, RegimeResult

        h = HysteresisWrapper(_Stub(), confirmations_derisk=1, confirmations_rerisk=2)

        h.step(RegimeResult("neutral", 1.0), reading_id="r1")
        # Several intra-reading ticks on r1 with same label — no-op.
        for _ in range(5):
            h.step(RegimeResult("neutral", 1.0), reading_id="r1")
        # New reading with de-risk label → flip immediately (N_derisk=1).
        out = h.step(RegimeResult("risk_off_defensive", 0.7), reading_id="r2")
        assert out.label == "risk_off_defensive"
        assert out.multiplier == pytest.approx(0.7)

    def test_rerisk_requires_two_distinct_readings(self):
        """N_rerisk=2: even with one intra-day reading repeated 100×,
        re-risk only flips after a SECOND distinct improving reading."""
        from core.regime import HysteresisWrapper, RegimeResult

        h = HysteresisWrapper(_Stub(), confirmations_derisk=1, confirmations_rerisk=2)

        h.step(RegimeResult("risk_off_defensive", 0.7), reading_id="r1")

        # Reading r2: first improving reading → pending=1, hold defensive.
        held = h.step(RegimeResult("risk_on_trending", 1.2), reading_id="r2")
        assert held.label == "risk_off_defensive"

        # Intra-reading hammering on r2 — pending must not advance.
        for _ in range(100):
            h.step(RegimeResult("risk_on_trending", 1.2), reading_id="r2")
        assert h._pending_count == 1
        assert h.current.label == "risk_off_defensive"

        # Reading r3: second distinct improving reading → flip.
        out = h.step(RegimeResult("risk_on_trending", 1.2), reading_id="r3")
        assert out.label == "risk_on_trending"

    def test_single_improved_reading_does_not_size_back_up(self):
        """The spec's load-bearing example: 'a single improved reading
        does NOT size back up.' Daily VIX drops below 20 for one day
        → the calc result must still come back as defensive."""
        from core.regime import HysteresisWrapper, RegimeResult

        h = HysteresisWrapper(_Stub(), confirmations_derisk=1, confirmations_rerisk=2)

        h.step(RegimeResult("risk_off_defensive", 0.7), reading_id="2026-05-20")
        out = h.step(RegimeResult("risk_on_trending", 1.2), reading_id="2026-05-21")
        assert out.label == "risk_off_defensive", (
            "Task 166: a single improved daily reading sized up — "
            "re-risk must require 2 distinct readings."
        )
        assert out.multiplier == pytest.approx(0.7)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Day-to-day flap suppression (MED-029's stated goal)
# ─────────────────────────────────────────────────────────────────────────────


class TestDayToDayFlap:
    """defensive → neutral → defensive over three days. Re-risk's
    2-reading requirement holds defensive throughout."""

    def test_defensive_neutral_defensive_holds_defensive(self):
        from core.regime import HysteresisWrapper, RegimeResult

        h = HysteresisWrapper(_Stub(), confirmations_derisk=1, confirmations_rerisk=2)

        d1 = h.step(RegimeResult("risk_off_defensive", 0.7), reading_id="2026-05-20")
        d2 = h.step(RegimeResult("neutral",            1.0), reading_id="2026-05-21")
        d3 = h.step(RegimeResult("risk_off_defensive", 0.7), reading_id="2026-05-22")

        assert d1.label == "risk_off_defensive"
        assert d2.label == "risk_off_defensive", (
            "Single neutral reading must NOT flip current — re-risk "
            "needs 2 distinct improving readings."
        )
        assert d3.label == "risk_off_defensive"
        # Pending state should have reset on d3 (re-confirmation of current).
        assert h._pending_label is None
        assert h._pending_count == 0

    def test_two_consecutive_improving_readings_finally_flip(self):
        """Mirror of the flap test, but with two consecutive improving
        readings → re-risk completes."""
        from core.regime import HysteresisWrapper, RegimeResult

        h = HysteresisWrapper(_Stub(), confirmations_derisk=1, confirmations_rerisk=2)

        h.step(RegimeResult("risk_off_defensive", 0.7), reading_id="d1")
        h.step(RegimeResult("neutral",            1.0), reading_id="d2")    # pending=1
        out = h.step(RegimeResult("neutral",      1.0), reading_id="d3")    # pending=2 → flip
        assert out.label == "neutral"
        assert out.multiplier == pytest.approx(1.0)

    def test_pending_label_change_resets_count_across_readings(self):
        """If reading r2 says risk_on_trending (pending) and reading
        r3 says neutral (different pending label), the count resets to
        1 — confirmation is for the SAME pending label across
        consecutive distinct readings."""
        from core.regime import HysteresisWrapper, RegimeResult

        h = HysteresisWrapper(_Stub(), confirmations_derisk=1, confirmations_rerisk=3)

        h.step(RegimeResult("risk_off_defensive", 0.7), reading_id="r1")
        h.step(RegimeResult("risk_on_trending",   1.2), reading_id="r2")  # pending=trending,1
        h.step(RegimeResult("neutral",            1.0), reading_id="r3")  # pending=neutral,1
        assert h._pending_label == "neutral"
        assert h._pending_count == 1
        assert h.current.label == "risk_off_defensive"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Equal-multiplier bypass still works under reading-id mode
# ─────────────────────────────────────────────────────────────────────────────


class TestEqualMultiplierBypassPreserved:
    def test_equal_multiplier_flips_on_first_new_reading(self):
        """T165's equal-mult immediate-flip rule still applies under
        reading-id mode — but only when reading_id advances."""
        from core.regime import HysteresisWrapper, RegimeResult

        h = HysteresisWrapper(_Stub(), confirmations_derisk=5, confirmations_rerisk=5)

        h.step(RegimeResult("neutral", 1.0), reading_id="r1")
        # Intra-reading equal-mult flip attempt: must NOT advance.
        for _ in range(3):
            held = h.step(RegimeResult("risk_on_choppy", 1.0), reading_id="r1")
            assert held.label == "neutral"
        # New reading: equal-mult bypass fires.
        out = h.step(RegimeResult("risk_on_choppy", 1.0), reading_id="r2")
        assert out.label == "risk_on_choppy"


# ─────────────────────────────────────────────────────────────────────────────
# 5. reset() clears _last_reading_id (gate state must not leak)
# ─────────────────────────────────────────────────────────────────────────────


class TestResetClearsReadingId:
    def test_reset_clears_last_reading_id(self):
        from core.regime import HysteresisWrapper, RegimeResult

        h = HysteresisWrapper(_Stub(), confirmations_derisk=1, confirmations_rerisk=2)
        h.step(RegimeResult("neutral", 1.0), reading_id="r1")
        assert h._last_reading_id == "r1"

        h.reset()
        assert h._last_reading_id is None, (
            "Task 166 regression: reset() must clear _last_reading_id "
            "alongside current/pending — otherwise per-backtest reruns "
            "would treat the first re-seeded call as 'same reading'."
        )

        # After reset, a step() with the same reading_id should run
        # the state machine (it's the first call post-reset).
        out = h.step(RegimeResult("risk_off_defensive", 0.7), reading_id="r1")
        assert out.label == "risk_off_defensive"
        assert h._last_reading_id == "r1"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Back-compat — step() without reading_id behaves like T165
# ─────────────────────────────────────────────────────────────────────────────


class TestBackCompatNoReadingId:
    def test_no_reading_id_counts_per_call_like_t165(self):
        """The 33 T165 tests pass step(raw) without reading_id. That
        path must remain the per-call counting model."""
        from core.regime import HysteresisWrapper, RegimeResult

        h = HysteresisWrapper(_Stub(), confirmations_derisk=1, confirmations_rerisk=2)

        # T165 re-risk shape: 1 hold, then flip.
        h.step(RegimeResult("risk_off_defensive", 0.7))
        held = h.step(RegimeResult("risk_on_trending", 1.2))
        assert held.label == "risk_off_defensive"
        flipped = h.step(RegimeResult("risk_on_trending", 1.2))
        assert flipped.label == "risk_on_trending"

    def test_classify_method_unchanged(self):
        """classify(signals) — the original Classifier-Protocol entry —
        is not threaded with reading_id (single-source single-call
        shape). Existing test_task163_regime_1a.py uses classify() and
        must still pass."""
        from core.regime import HysteresisWrapper, JsonRuleClassifier, RegimeResult
        from pathlib import Path
        rules = (
            Path(__file__).parent.parent
            / "core" / "regime" / "v1_rules.json"
        )
        cls = JsonRuleClassifier.from_file(rules)
        h = HysteresisWrapper(cls, confirmations_derisk=1, confirmations_rerisk=2)
        # First call sees panic → seeds. Second call sees neutral →
        # T165 per-call counts apply, no reading_id involved.
        out1 = h.classify({"vix_close": 50.0, "hy_spread": 6.0, "mode": "macro_only"})
        assert out1.label == "risk_off_panic"
        out2 = h.classify({"vix_close": 15.0, "hy_spread": 3.0, "mode": "macro_only"})
        # Re-risk needs 2 per-call confirmations under back-compat — held.
        assert out2.label == "risk_off_panic"


# ─────────────────────────────────────────────────────────────────────────────
# 7. compute_current_regime source pin: reading_id is passed
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeCurrentRegimeReadingId:
    def test_reading_id_passed_to_step(self):
        """Source pin: compute_current_regime must pass reading_id
        to _LIVE_HYSTERESIS.step() — without it, the wrapper falls
        back to per-tick counting and T166's whole point is lost."""
        src = Path(__file__).parent.parent / "core" / "regime_classifier.py"
        text = src.read_text(encoding="utf-8")
        executing = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("#")
        )
        assert "reading_id=reading_id" in executing, (
            "Task 166 regression: compute_current_regime must call "
            "_LIVE_HYSTERESIS.step(..., reading_id=...)."
        )

    def test_db_path_uses_db_label_date_for_reading_id(self):
        src = Path(__file__).parent.parent / "core" / "regime_classifier.py"
        text = src.read_text(encoding="utf-8")
        executing = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("#")
        )
        # The DB path builds reading_id from recent_db["date"].
        assert 'reading_id = f"db:{recent_db' in executing

    def test_live_path_uses_max_signal_date_for_reading_id(self):
        src = Path(__file__).parent.parent / "core" / "regime_classifier.py"
        text = src.read_text(encoding="utf-8")
        executing = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("#")
        )
        # The live fallback path picks max(latest_dates).
        assert 'max(latest_dates)' in executing
        assert 'reading_id = f"live:' in executing


# ─────────────────────────────────────────────────────────────────────────────
# 8. T166 source anchors
# ─────────────────────────────────────────────────────────────────────────────


class TestT166Anchors:
    def test_hysteresis_anchor(self):
        text = (
            Path(__file__).parent.parent / "core" / "regime" / "hysteresis.py"
        ).read_text(encoding="utf-8")
        assert "Task 166" in text or "T166" in text

    def test_regime_classifier_anchor(self):
        text = (
            Path(__file__).parent.parent / "core" / "regime_classifier.py"
        ).read_text(encoding="utf-8")
        assert "Task 166" in text or "T166" in text
