"""
Task 163 regression tests — Regime 1a (interface + JSON interpreter +
v1 parity migration + MED-029 hysteresis + MED-030 FRED validation).

Coverage split:

  - **Interpreter unit tests** (JsonRuleClassifier): each operator,
    AND semantics, missing-signal handling, first-match precedence,
    no-match → default, string ==-RHS, parse errors.

  - **Parity golden-master**: across a representative grid of
    (vix, hy, rvol, oi_change, funding, mode) tuples, the new
    `classify_regime` (which delegates to JsonRuleClassifier) and
    the preserved `_legacy_classify_regime` (the original cascade)
    must agree EXCEPT on the documented intended deviation:
      - When hy_spread is MISSING (None) and VIX/rvol qualify for
        risk-on, the legacy code's `hy is None or hy < 3.5` allowed
        risk-on; v1's strict-AND `hy < 3.5` fails on None and falls
        to neutral. Safer-direction; rare-path (FRED feed normally
        has hy daily). Asserted EXPLICITLY in
        TestIntendedDeviations, not silent.

  - **MED-029 hysteresis**: a single border-crossing reading must
    not flip the label. The wrapper holds the current label until
    N consecutive observations of a NEW different label.

  - **MED-030 FRED validation**: a FRED response missing
    `observations` (the error-envelope shape) must log + return 0,
    not silently swallow with `data.get("observations", [])`.

Run: pytest tests/test_task163_regime_1a.py -v
"""
from __future__ import annotations

import itertools
import json
import logging
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Interpreter unit tests ─────────────────────────────────────────────────


class TestJsonInterpreterOperators:
    """Each comparison operator + string-equality + missing-signal +
    no-match-default. Pure functional; no side-effects."""

    @staticmethod
    def _single_rule_cls(when_value, regime="match", multiplier=2.0):
        """Build a single-rule classifier so each operator test
        exercises ONE rule against ONE input without ordering-overlap
        confounds."""
        from core.regime import JsonRuleClassifier
        return JsonRuleClassifier({
            "rules": [{"regime": regime, "when": {"x": when_value},
                       "multiplier": multiplier}],
            "default": {"regime": "fallback", "multiplier": 1.0},
        })

    def test_greater_than(self):
        cls = self._single_rule_cls("> 10")
        r = cls.classify({"x": 15})
        assert r.label == "match"
        assert r.multiplier == 2.0
        assert cls.classify({"x": 10}).label == "fallback"   # strict
        assert cls.classify({"x": 5}).label == "fallback"

    def test_less_than(self):
        cls = self._single_rule_cls("< 5")
        assert cls.classify({"x": 4}).label == "match"
        assert cls.classify({"x": 5}).label == "fallback"   # strict

    def test_greater_or_equal_boundary(self):
        cls = self._single_rule_cls(">= 100")
        assert cls.classify({"x": 100}).label == "match"    # boundary included
        assert cls.classify({"x": 99}).label == "fallback"

    def test_less_or_equal_boundary(self):
        cls = self._single_rule_cls("<= -5")
        assert cls.classify({"x": -5}).label == "match"     # boundary included
        assert cls.classify({"x": -4}).label == "fallback"

    def test_numeric_equality(self):
        cls = self._single_rule_cls("== 7")
        assert cls.classify({"x": 7}).label == "match"
        assert cls.classify({"x": 7.000001}).label == "fallback"

    def test_string_equality(self):
        from core.regime import JsonRuleClassifier
        cls = JsonRuleClassifier({
            "rules": [{"regime": "match", "when": {"mode": "== full"}}],
            "default": {"regime": "fallback"},
        })
        assert cls.classify({"mode": "full"}).label == "match"
        assert cls.classify({"mode": "macro_only"}).label == "fallback"

    def test_missing_signal_fails_rule(self):
        """Signal not in input dict → numeric condition fails → rule
        does not match. Drops to default."""
        cls = self._single_rule_cls("> 10")
        assert cls.classify({}).label == "fallback"

    def test_none_value_fails_rule(self):
        """Signal present but value is None → same as missing."""
        cls = self._single_rule_cls("> 10")
        assert cls.classify({"x": None}).label == "fallback"

    def test_string_eq_fails_on_none(self):
        from core.regime import JsonRuleClassifier
        cls = JsonRuleClassifier({
            "rules": [{"regime": "match", "when": {"mode": "== full"}}],
            "default": {"regime": "fallback"},
        })
        assert cls.classify({"mode": None}).label == "fallback"


class TestJsonInterpreterAndSemantics:
    """Multi-condition `when` blocks are ANDed."""

    @pytest.fixture
    def cls(self):
        from core.regime import JsonRuleClassifier
        return JsonRuleClassifier({
            "rules": [
                {
                    "regime": "both",
                    "when": {"a": "> 10", "b": "< 5"},
                },
            ],
        })

    def test_all_conditions_satisfied(self, cls):
        assert cls.classify({"a": 11, "b": 4}).label == "both"

    def test_one_fails(self, cls):
        assert cls.classify({"a": 11, "b": 10}).label == "neutral"
        assert cls.classify({"a": 5, "b": 4}).label == "neutral"

    def test_one_missing(self, cls):
        """AND with a missing signal → rule fails."""
        assert cls.classify({"a": 11}).label == "neutral"


class TestJsonInterpreterFirstMatchPrecedence:
    """Rule list order matters — earlier rules win even if a later
    rule would also match."""

    def test_first_matching_rule_wins(self):
        from core.regime import JsonRuleClassifier
        cls = JsonRuleClassifier({
            "rules": [
                {"regime": "first", "when": {"x": "> 0"}},
                {"regime": "second", "when": {"x": "> 0"}},  # also matches
            ],
        })
        assert cls.classify({"x": 1}).label == "first"

    def test_only_matches_after_first(self):
        from core.regime import JsonRuleClassifier
        cls = JsonRuleClassifier({
            "rules": [
                {"regime": "specific", "when": {"x": "> 100"}},
                {"regime": "general", "when": {"x": "> 0"}},
            ],
        })
        assert cls.classify({"x": 50}).label == "general"
        assert cls.classify({"x": 200}).label == "specific"


class TestJsonInterpreterNoMatch:
    def test_default_used_when_no_rule_matches(self):
        from core.regime import JsonRuleClassifier
        cls = JsonRuleClassifier({
            "rules": [{"regime": "high", "when": {"x": "> 100"}}],
            "default": {"regime": "low", "multiplier": 0.5},
        })
        r = cls.classify({"x": 0})
        assert r.label == "low"
        assert r.multiplier == 0.5

    def test_implicit_neutral_default(self):
        """Rule set with no `default` block → neutral / 1.0."""
        from core.regime import JsonRuleClassifier
        cls = JsonRuleClassifier({"rules": []})
        r = cls.classify({})
        assert r.label == "neutral"
        assert r.multiplier == 1.0


class TestJsonInterpreterParseErrors:
    """Bad rule sets fail fast at construction, not silently at
    classification time."""

    def test_missing_regime_key(self):
        from core.regime import JsonRuleClassifier
        with pytest.raises(ValueError, match="missing 'regime'"):
            JsonRuleClassifier({"rules": [{"when": {"x": "> 0"}}]})

    def test_missing_when_key(self):
        from core.regime import JsonRuleClassifier
        with pytest.raises(ValueError, match="missing 'when'"):
            JsonRuleClassifier({"rules": [{"regime": "x"}]})

    def test_invalid_operator(self):
        from core.regime import JsonRuleClassifier
        with pytest.raises(ValueError, match="missing operator"):
            JsonRuleClassifier({"rules": [{"regime": "x", "when": {"a": "30"}}]})

    def test_non_numeric_rhs_with_non_eq_op(self):
        from core.regime import JsonRuleClassifier
        with pytest.raises(ValueError, match="non-numeric"):
            JsonRuleClassifier({"rules": [{"regime": "x", "when": {"a": "> abc"}}]})


# ── Parity golden-master ────────────────────────────────────────────────────


class TestParityWithLegacyCascade:
    """Across a representative grid, classify_regime (new, JSON-backed)
    and _legacy_classify_regime (preserved original cascade) must agree.
    Intended deviations are isolated to TestIntendedDeviations."""

    @staticmethod
    def _representative_grid():
        """A small grid of (signals, mode) tuples that covers each
        cascade branch. NOT exhaustive — that's a fuzz test (below)."""
        # Each tuple: (vix, hy, rvol, oi_change, funding, mode_hint)
        # mode_hint chosen to disambiguate full vs macro_only.
        for vix in (15, 19, 21, 23, 27, 35):
            for hy in (3.0, 3.6, 4.2, 4.7, 5.5):
                for rvol in (1.0, 1.25, 1.4):
                    # full-mode case (crypto signals present)
                    for oi in (-0.3, 0.5):
                        for fund in (-0.02, -0.005, 0.0, 0.001):
                            yield {
                                "vix_close": vix, "hy_spread": hy,
                                "btc_rvol_ratio": rvol,
                                "agg_oi_change": oi, "avg_funding": fund,
                            }
                    # macro_only case (no oi/funding)
                    yield {
                        "vix_close": vix, "hy_spread": hy,
                        "btc_rvol_ratio": rvol,
                    }

    def test_parity_across_representative_grid(self):
        from core.regime_classifier import classify_regime, _legacy_classify_regime
        mismatches = []
        for sig in self._representative_grid():
            new = classify_regime(sig)
            old = _legacy_classify_regime(sig)
            if new != old:
                mismatches.append((sig, new, old))
        # No mismatches allowed in the present-hy grid (deviation only
        # fires when hy is None, which is in TestIntendedDeviations).
        assert not mismatches, (
            f"Parity broken on {len(mismatches)} grid points. "
            f"First 5: {mismatches[:5]}"
        )

    def test_parity_macro_only_specific_cases(self):
        """Pin a few specific macro-only points to make regressions
        diagnosable individually."""
        from core.regime_classifier import classify_regime, _legacy_classify_regime
        cases = [
            # Low-VIX risk-on (macro_only)
            ({"vix_close": 17, "hy_spread": 3.0, "btc_rvol_ratio": 1.1},
             "risk_on_trending"),
            # Defensive on elevated VIX
            ({"vix_close": 28, "hy_spread": 3.5, "btc_rvol_ratio": 1.1},
             "risk_off_defensive"),
            # Panic — high VIX + high HY
            ({"vix_close": 35, "hy_spread": 5.5, "btc_rvol_ratio": 1.5},
             "risk_off_panic"),
            # Neutral floor — hy in [4.0, 4.5)
            ({"vix_close": 18, "hy_spread": 4.2, "btc_rvol_ratio": 1.0},
             "neutral"),
        ]
        for sig, expected in cases:
            new = classify_regime(sig)
            old = _legacy_classify_regime(sig)
            assert new == old == expected, (
                f"sig={sig!r}: new={new!r} old={old!r} expected={expected!r}"
            )


class TestIntendedDeviations:
    """Document + assert the parity gaps so they're visible, not silent.
    A future operator running the parity test will see these flagged
    intentionally; any NEW divergence beyond these is a real regression."""

    def test_missing_hy_with_riskon_qualifying_signals(self):
        """Legacy `hy is None or hy < 3.5` allowed risk-on when hy was
        missing. v1 JSON's `hy_spread: < 3.5` fails on missing →
        falls to neutral (safer direction). Asserted explicitly."""
        from core.regime_classifier import classify_regime, _legacy_classify_regime
        sig = {
            "vix_close": 15,
            # hy_spread MISSING
            "btc_rvol_ratio": 1.0,
            "agg_oi_change": 0.5, "avg_funding": 0.002,
        }
        new = classify_regime(sig)
        old = _legacy_classify_regime(sig)
        # Documented divergence:
        assert old == "risk_on_trending"
        assert new == "neutral"

    def test_no_other_missing_hy_deviation(self):
        """Same setup but with hy PRESENT and low — both should agree
        on risk-on. This is the anti-control proving the deviation is
        specifically about missing-hy."""
        from core.regime_classifier import classify_regime, _legacy_classify_regime
        sig = {
            "vix_close": 15, "hy_spread": 2.5,
            "btc_rvol_ratio": 1.0,
            "agg_oi_change": 0.5, "avg_funding": 0.002,
        }
        new = classify_regime(sig)
        old = _legacy_classify_regime(sig)
        assert new == old == "risk_on_trending"


# ── MED-029 hysteresis ─────────────────────────────────────────────────────


class TestMed029Hysteresis:
    """Border-crossing readings don't flap the regime under hysteresis."""

    def test_single_border_crossing_does_not_flip(self):
        """VIX hovering at the vix_defensive boundary (25). One reading
        above shouldn't flip from neutral → defensive immediately."""
        from core.regime import JsonRuleClassifier, HysteresisWrapper
        cls = JsonRuleClassifier.from_file(
            Path("core/regime/v1_rules.json")
        )
        hyst = HysteresisWrapper(cls, confirmations=2)

        # First reading: low VIX → neutral / 1.0 (default; needs hy_spread)
        # We need a signal set that classifies as neutral. Use hy=3.7
        # so risk-on rules fail (hy >= 3.5 blocks them) but no other
        # rule matches → default neutral.
        baseline = {"vix_close": 18, "hy_spread": 3.7, "mode": "macro_only"}
        r1 = hyst.classify(baseline)
        assert r1.label == "neutral"

        # Single VIX spike just above threshold (would be defensive
        # if applied immediately) — hysteresis must HOLD neutral.
        spike = {"vix_close": 25.5, "hy_spread": 3.7, "mode": "macro_only"}
        r2 = hyst.classify(spike)
        assert r2.label == "neutral", (
            f"MED-029 regression: single border-crossing reading "
            f"flipped the label to {r2.label!r} immediately"
        )

        # VIX returns to baseline — confirms the flap was illusory.
        r3 = hyst.classify(baseline)
        assert r3.label == "neutral"

    def test_two_consecutive_confirmations_flip(self):
        """Two consecutive defensive observations DO flip — the regime
        actually shifted, not a single bounce."""
        from core.regime import JsonRuleClassifier, HysteresisWrapper
        cls = JsonRuleClassifier.from_file(Path("core/regime/v1_rules.json"))
        hyst = HysteresisWrapper(cls, confirmations=2)

        # Seed neutral
        baseline = {"vix_close": 18, "hy_spread": 3.7, "mode": "macro_only"}
        hyst.classify(baseline)

        # Two consecutive defensive observations
        defensive = {"vix_close": 27, "hy_spread": 3.7, "mode": "macro_only"}
        r1 = hyst.classify(defensive)
        assert r1.label == "neutral"   # pending; still held
        r2 = hyst.classify(defensive)
        assert r2.label == "risk_off_defensive"   # flip confirmed

    def test_pending_resets_when_label_returns_to_current(self):
        """A → pending(B) → A → ... pending should reset, not commit B."""
        from core.regime import JsonRuleClassifier, HysteresisWrapper
        cls = JsonRuleClassifier.from_file(Path("core/regime/v1_rules.json"))
        hyst = HysteresisWrapper(cls, confirmations=2)

        baseline = {"vix_close": 18, "hy_spread": 3.7, "mode": "macro_only"}
        hyst.classify(baseline)
        defensive = {"vix_close": 27, "hy_spread": 3.7, "mode": "macro_only"}
        hyst.classify(defensive)        # pending=defensive, count=1
        hyst.classify(baseline)         # pending should reset
        # Next observation of defensive should be count=1 again (not 2)
        r = hyst.classify(defensive)
        assert r.label == "neutral"     # still held — pending re-counts

    def test_confirmations_1_disables_hysteresis(self):
        """N=1 means immediate flip (equivalent to no hysteresis).
        Useful for tests / synchronous-eval analytics paths."""
        from core.regime import JsonRuleClassifier, HysteresisWrapper
        cls = JsonRuleClassifier.from_file(Path("core/regime/v1_rules.json"))
        hyst = HysteresisWrapper(cls, confirmations=1)

        hyst.classify({"vix_close": 18, "hy_spread": 3.7, "mode": "macro_only"})
        r = hyst.classify({"vix_close": 27, "hy_spread": 3.7, "mode": "macro_only"})
        assert r.label == "risk_off_defensive"


# ── MED-030 FRED validation ────────────────────────────────────────────────


class TestMed030FredValidation:
    """FRED response missing `observations` (error-envelope) must log
    + return 0. Pre-T163: `data.get("observations", [])` silently
    swallowed."""

    @pytest.mark.asyncio
    async def test_error_envelope_logs_and_returns_zero(self, monkeypatch, caplog):
        """Patch httpx.AsyncClient to return a FRED error envelope
        (no 'observations' key). The fetcher should detect, log, and
        return 0 rows — NOT silently treat as 'no data'."""
        from core import regime_fetcher

        # Force FRED_API_KEY non-empty so the early-skip branch
        # doesn't pre-empt the test
        monkeypatch.setattr(regime_fetcher.config, "FRED_API_KEY", "test_key_123", raising=False)

        class _FakeResp:
            def raise_for_status(self): pass
            def json(self): return {
                "error_code": 400,
                "error_message": "Bad Request. The series does not exist.",
            }

        class _FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, *a, **kw): return _FakeResp()

        monkeypatch.setattr(regime_fetcher.httpx, "AsyncClient",
                            lambda *a, **kw: _FakeClient(), raising=False)

        fetcher = regime_fetcher.RegimeFetcher()
        caplog.set_level(logging.WARNING, logger="regime_fetcher")

        result = await fetcher.fetch_fred_series(
            "BOGUS", "us10y_yield", "2024-01-01", "2024-12-31",
        )
        assert result == 0, "Expected 0 rows on FRED error envelope"

        # Warning logged with error_code visible
        matches = [r for r in caplog.records
                   if "missing 'observations'" in r.message
                   and r.levelname == "WARNING"]
        assert matches, (
            "MED-030 regression: FRED error envelope did not log "
            "a warning surfacing the failure. Records: "
            + repr([(r.levelname, r.message[:80]) for r in caplog.records])
        )

    @pytest.mark.asyncio
    async def test_observations_not_a_list_logs(self, monkeypatch, caplog):
        """FRED schema drift safety: 'observations' present but wrong
        type → log + return 0."""
        from core import regime_fetcher

        monkeypatch.setattr(regime_fetcher.config, "FRED_API_KEY", "test_key_123", raising=False)

        class _FakeResp:
            def raise_for_status(self): pass
            def json(self): return {"observations": "not_a_list"}

        class _FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, *a, **kw): return _FakeResp()

        monkeypatch.setattr(regime_fetcher.httpx, "AsyncClient",
                            lambda *a, **kw: _FakeClient(), raising=False)

        fetcher = regime_fetcher.RegimeFetcher()
        caplog.set_level(logging.WARNING, logger="regime_fetcher")
        result = await fetcher.fetch_fred_series(
            "DGS10", "us10y_yield", "2024-01-01", "2024-12-31",
        )
        assert result == 0
        matches = [r for r in caplog.records if "Schema drift" in r.message]
        assert matches


# ── compute_current_regime + classify_range delegate path ─────────────────


class TestDelegationToInterpreter:
    """compute_current_regime + classify_range now route through
    classify_regime → JsonRuleClassifier. The T156-caveat-d divergence
    (fallback path vs persisted-label path producing different labels)
    is closed by having one source of truth."""

    def test_classify_regime_is_delegate_to_v1_classifier(self):
        """Direct callability + mode-inject behavior."""
        from core.regime_classifier import classify_regime

        # mode auto-detection branches: presence of oi/funding
        with_crypto = {"vix_close": 15, "hy_spread": 2.5,
                       "btc_rvol_ratio": 1.0,
                       "agg_oi_change": 0.5, "avg_funding": 0.001}
        without_crypto = {"vix_close": 15, "hy_spread": 2.5,
                           "btc_rvol_ratio": 1.0}
        # Both qualify for risk_on_trending in their respective modes
        assert classify_regime(with_crypto, mode="full") == "risk_on_trending"
        assert classify_regime(without_crypto, mode="macro_only") == "risk_on_trending"
        # Auto-detection matches:
        assert classify_regime(with_crypto, mode="auto") == "risk_on_trending"
        assert classify_regime(without_crypto, mode="auto") == "risk_on_trending"

    def test_thresholds_argument_is_no_op_post_t163(self):
        """T163 ignores `thresholds`. Document via behavior: passing
        an absurd thresholds dict should NOT change the outcome."""
        from core.regime_classifier import classify_regime
        # Realistic VIX-high case
        sig = {"vix_close": 27, "hy_spread": 3.5, "btc_rvol_ratio": 1.1,
               "mode": "macro_only"}
        baseline = classify_regime(sig, mode="macro_only")
        # Pass a thresholds dict that, if honored, would invert the
        # decision (lower vix_defensive to 10 → 27 is way past, but
        # baseline already classifies as defensive at 25; instead use
        # absurd 100 to see if the rule fires anyway)
        with_thresholds = classify_regime(
            sig, mode="macro_only",
            thresholds={"vix_defensive": 100},   # ignored
        )
        assert baseline == with_thresholds == "risk_off_defensive"


# ── Source pins for the consolidation + housekeeping ──────────────────────


class TestT163SourcePins:
    def test_v1_rule_set_file_present(self):
        assert Path("core/regime/v1_rules.json").exists()

    def test_v1_rule_set_parses_without_error(self):
        """Belt-and-suspenders: the rule set file must be a valid JSON
        rule set the JsonRuleClassifier accepts."""
        from core.regime import JsonRuleClassifier
        cls = JsonRuleClassifier.from_file(Path("core/regime/v1_rules.json"))
        assert cls is not None

    def test_legacy_cascade_preserved_for_parity_testing(self):
        """The original cascade must be retained as
        `_legacy_classify_regime` so the parity golden-master can run."""
        from core.regime_classifier import _legacy_classify_regime
        assert callable(_legacy_classify_regime)

    def test_classify_regime_delegates_to_v1_classifier(self):
        """Source pin: `classify_regime` references the v1 classifier
        + injects mode into the signals dict."""
        src = Path("core/regime_classifier.py").read_text(encoding="utf-8")
        # Anchor + delegate marker
        assert "_V1_CLASSIFIER" in src
        assert "Task 163" in src
        # mode injection
        assert '"mode": mode' in src or "mode=mode" in src
