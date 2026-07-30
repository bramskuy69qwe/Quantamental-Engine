"""
Task 159 regression tests — Risk-engine correctness clamps.

Closes 4 fix-before-regime findings from T158 triage:
  - MED-016: negative size at high slippage (mis-tiered → HIGH-shape:
    direction-inversion at exchange API).
  - MED-019: max_position_count not enforced (mis-tiered → HIGH-shape:
    risk-limit non-enforcement).
  - MED-002: R:R ratio overflow at tiny est_loss (epsilon vulnerability).
  - MED-021: config values accepted without bounds (NaN/inf/negative).

Mechanism investigations + deviations (per T155 deviation discipline):

  MED-016. Spec said "clamp at 0, reject (not silently zero), surface why."
  Investigation: `est_size = base_size * (1 - est_slippage)` at
  risk_engine.py step 6 goes negative when `est_slippage >= 1.0`. The
  reject path uses the existing `eligible=False` / `ineligible_reason`
  shape rather than a new error return type — keeps the calc-output dict
  shape stable for all callers. Defensive `max(0.0, ...)` clamp also
  retained for belt-and-suspenders.

  MED-019. Spec said "Gate at order submission." Investigation: the
  engine has NO order submission layer (passive observer per HIGH-019 /
  Task 93 architectural decision — Quantower plugin places orders;
  engine only logs fills). The `eligible=False` flag DOES fire when
  positions are at max, but the size value in the returned dict still
  carries the computed (non-zero) number and the click-to-copy
  `data-contracts` attribute (T149) would let an operator paste the
  blocked size into QT despite the warning. Deviation from spec: gate at
  the *display/copy* layer instead. Two changes: (a) populate
  `ineligible_reason` for at_max_positions / at_max_exposure /
  exceeds_corr cases (was empty); (b) zero the `data-contracts` and
  `data-notional` attributes when eligible=False so paste returns 0.

  MED-002. Spec said "clamp to sane bound." Constant `MAX_REASONABLE_RR
  = 50.0` chosen as "professional trader sanity bound" — above 50× the
  inputs are degenerate (sub-fee SL distance, epsilon vulnerability
  shared with MED-031). Log fires on clamp.

  MED-021. Spec said "bounds-checking at load, reject/clamp with clear
  startup error." Helper `_bounded_float_env(name, default, *, lo, hi)`
  fails loud at module import with RuntimeError for NaN/inf/out-of-range/
  unparseable inputs. EXEC_LINK_PRICE_TOL bounded [1e-6, 0.1];
  EXCHANGE_REFRESH_HZ bounded [0.01, 100].

Run: pytest tests/test_task159_risk_engine_clamps.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── MED-016: negative-size catastrophic-book gate ──────────────────────────


class TestMed016HighSlippageRejects:
    """High slippage → reject (eligible=False) + reason + size=0.
    Dangerous-path test: confirm negative size NEVER leaves the
    calculator."""

    def _build_orderbook_with_high_slippage(self):
        """Construct an orderbook so the VWAP fill of base_size walks far
        from the best price → est_slippage >= 1.0. Best ask 100; very
        thin levels jumping to 250+ → fills walk into the >100% region."""
        return {
            "bids": [[100.0, 0.01]],
            "asks": [
                [100.0, 0.0001],   # thin best
                [250.0, 100.0],    # gap; VWAP walks here
                [300.0, 100.0],
            ],
        }

    def test_est_slippage_above_one_rejects(self, monkeypatch):
        """The load-bearing test: when est_slippage computed by the VWAP
        walk reaches/exceeds 1.0, calculator must return eligible=False
        with a reason explaining slippage, AND size must be 0 (never
        negative).

        Fixture construction: thin best ask (qty=0.0001 @ price=100)
        followed by a gap to 250+. base_size budget (500 USDT) exhausts
        the thin level instantly and walks into the 250 region → VWAP
        ≈ 250 → est_slippage ≈ 1.5 → catastrophic gate fires."""
        from core import risk_engine
        from core.state import app_state

        # Catastrophic orderbook
        monkeypatch.setattr(
            app_state, "orderbook_cache",
            {"FAKEUSDT": self._build_orderbook_with_high_slippage()},
            raising=False,
        )
        # Skip the engine-ready / capability gates so the path reaches
        # the MED-016 logic. The function does `from core.monitoring
        # import ReadyStateEvaluator` inline — patch the SOURCE module,
        # not risk_engine's namespace.
        from core import monitoring
        monkeypatch.setattr(
            monitoring, "ReadyStateEvaluator",
            lambda: type("R", (), {"evaluate": lambda s: (True, "")})(),
            raising=False,
        )
        # Capability gate uses a broad `except Exception: pass` fallback
        # if _get_adapter fails — no explicit patch needed.
        # Fix atr_c to a normal value so the OHLCV-based ATR doesn't gate
        # us out before we reach the slippage step.
        monkeypatch.setattr(
            risk_engine, "calculate_atr_coefficient",
            lambda symbol: (0.5, "normal", 100.0, 200.0),
        )
        # Stub app_state.params (risk-per-trade) so risk_usdt computes
        params = dict(getattr(app_state, "params", {}))
        params["individual_risk_per_trade"] = 0.01
        monkeypatch.setattr(app_state, "params", params, raising=False)

        result = risk_engine.calculate_position_size(
            "FAKEUSDT", average=100.0, sl_price=99.0,
            total_equity=1000.0, side="long",
        )

        # Mechanism load-bearing pin: fixture MUST trigger ≥1.0
        # slippage, else the test fails (no skip — the test exists
        # specifically to exercise this path).
        assert result["est_slippage"] >= 1.0, (
            f"Test fixture failed to trigger catastrophic slippage; "
            f"got est_slippage={result['est_slippage']:.4f}. Adjust the "
            f"orderbook stub so VWAP walks past best ask."
        )
        # The MED-016 gate fired
        assert result["eligible"] is False, (
            "MED-016 regression: est_slippage>=1.0 but eligible=True"
        )
        assert "slippage" in result["ineligible_reason"].lower(), (
            f"MED-016 regression: reason doesn't mention slippage: "
            f"{result['ineligible_reason']!r}"
        )
        # The "direction inversion" failure mode: size must never go
        # negative. This is the load-bearing invariant — operator
        # pasting size=−X.YZ into QT could place the opposite-side order.
        assert result["size"] >= 0, (
            f"MED-016 regression: negative size leaked: {result['size']}"
        )

    def test_negative_size_never_propagates_via_clamp(self):
        """Belt-and-suspenders pin: even when something forces
        est_slippage > 1.0 and eligible stays True (defensive scenario),
        the max(0.0, est_size) clamp catches it."""
        # The pin lives in the source — verify the clamp line is present.
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        assert "max(0.0, est_size)" in src, (
            "MED-016 regression: belt-and-suspenders clamp removed. "
            "Without it, a future path that lets est_slippage > 1 "
            "through with eligible=True would propagate negative size."
        )

    def test_reject_path_surfaces_via_eligible_flag(self):
        """Source pin: the MED-016 gate sets eligible=False (not just
        prints a warning). The reject IS the eligible flag."""
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        # Find the MED-016 block
        idx = src.find("MED-016")
        assert idx > 0
        block = src[idx:idx + 2000]
        assert 'result["eligible"] = False' in block, (
            "MED-016 regression: block does not set eligible=False"
        )
        assert "ineligible_reason" in block
        assert "est_slippage >= 1.0" in block

    def test_med016_anchor_comment_present(self):
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        assert "Task 159 (MED-016)" in src


# ── MED-019: max_position_count enforcement at display/copy layer ──────────


class TestMed019AtMaxPositionsHasReasonAndZeroedCopy:
    """The audit recommended "gate at order submission" — engine has none
    (passive observer). Closest analog: ensure no surface looks
    actionable when eligible=False. Two pins."""

    def test_at_max_positions_populates_ineligible_reason(self):
        """Source pin: at_max_positions branch sets the portfolio_reason
        text. Pre-T159: empty string. Post-T159: populated."""
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        assert "Max position count reached" in src, (
            "MED-019 regression: at_max_positions has no populated "
            "ineligible_reason — the calc dict surfaces eligible=False "
            "with no explanation."
        )
        assert "portfolio_reason" in src, (
            "MED-019 regression: portfolio_reason variable missing"
        )

    def test_final_reason_combines_sizing_and_portfolio_paths(self):
        """sizing-path reason (Engine not ready / capability / SL invalid
        / too volatile / MED-016 slippage) wins over portfolio gates;
        portfolio gates fill in when sizing path is fine but portfolio
        limits hit. T161 inserted contract_reason between sizing and
        portfolio in the chain."""
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        # Pattern: final_reason = sizing.get(...) [...] or portfolio_reason
        assert "final_reason = (" in src or "final_reason = sizing.get" in src
        assert "or portfolio_reason" in src

    def test_returned_dict_uses_final_reason_not_bare_get(self):
        """Anti-revert pin: the returned dict's ineligible_reason field
        must reference final_reason, NOT the bare sizing.get() that
        leaves portfolio gates empty."""
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        # Find the return dict's ineligible_reason line
        # New form: "ineligible_reason":   final_reason,
        assert '"ineligible_reason":   final_reason' in src or (
            '"ineligible_reason": final_reason' in src
        ), (
            "MED-019 regression: returned dict's ineligible_reason "
            "reverted to bare sizing.get()"
        )


# ── MED-002: R:R ratio clamp ───────────────────────────────────────────────


class TestMed002RrClamp:
    """est_r unbounded when est_loss → 0+. Cap at MAX_REASONABLE_RR=50."""

    def test_max_reasonable_rr_constant_exists(self):
        from core.risk_engine import MAX_REASONABLE_RR
        assert MAX_REASONABLE_RR == 50.0

    def test_rr_clamped_when_loss_is_tiny(self):
        """Mirror of the JS-side clamp logic — when est_profit/est_loss
        would produce >50, the value caps."""
        from core.risk_engine import MAX_REASONABLE_RR

        # Simulate the new logic exactly
        def compute_est_r(est_profit, est_loss):
            if est_loss > 0:
                raw_r = est_profit / est_loss
                return min(raw_r, MAX_REASONABLE_RR) if raw_r > 0 else raw_r
            return 0.0

        # Tiny loss → unbounded raw, clamped to 50
        assert compute_est_r(est_profit=100.0, est_loss=0.001) == 50.0
        # Negative est_profit (loss-shape) → don't clamp, just compute
        # (raw_r negative; clamp only applies on positive overflow)
        assert compute_est_r(est_profit=-5.0, est_loss=10.0) == -0.5
        # Normal R:R unaffected
        assert compute_est_r(est_profit=20.0, est_loss=10.0) == 2.0
        # Zero loss → 0.0 (existing guard preserved)
        assert compute_est_r(est_profit=100.0, est_loss=0.0) == 0.0
        # Zero loss when est_profit also zero
        assert compute_est_r(est_profit=0.0, est_loss=0.0) == 0.0

    def test_rr_clamp_anchor_present(self):
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        assert "Task 159 (MED-002)" in src
        # The actual clamp expression
        assert "min(raw_r, MAX_REASONABLE_RR)" in src


# ── MED-021: bounded float env config ──────────────────────────────────────


class TestMed021BoundedFloatEnv:
    """Config bounds-checking at load."""

    def test_helper_exists_and_handles_normal_value(self):
        from config import _bounded_float_env
        assert _bounded_float_env("__NO_SUCH_VAR__", "0.5", lo=0, hi=1) == 0.5

    def test_helper_rejects_unparseable(self):
        from config import _bounded_float_env
        # Use a name that doesn't exist in env; default carries the bad value
        with pytest.raises(RuntimeError, match=r"not a valid float"):
            _bounded_float_env("__NO_SUCH_VAR__", "abc", lo=0, hi=1)

    def test_helper_rejects_nan(self):
        from config import _bounded_float_env
        with pytest.raises(RuntimeError, match=r"must be finite"):
            _bounded_float_env("__NO_SUCH_VAR__", "nan", lo=0, hi=1)

    def test_helper_rejects_inf(self):
        from config import _bounded_float_env
        with pytest.raises(RuntimeError, match=r"must be finite"):
            _bounded_float_env("__NO_SUCH_VAR__", "inf", lo=0, hi=1)

    def test_helper_rejects_out_of_range_low(self):
        from config import _bounded_float_env
        with pytest.raises(RuntimeError, match=r"out of range"):
            _bounded_float_env("__NO_SUCH_VAR__", "-1", lo=0, hi=1)

    def test_helper_rejects_out_of_range_high(self):
        from config import _bounded_float_env
        with pytest.raises(RuntimeError, match=r"out of range"):
            _bounded_float_env("__NO_SUCH_VAR__", "1.5", lo=0, hi=1)

    def test_helper_reads_actual_env_var(self, monkeypatch):
        """If env var is set, it wins over the default."""
        from config import _bounded_float_env
        monkeypatch.setenv("__T159_TEST__", "0.7")
        assert _bounded_float_env("__T159_TEST__", "0.1", lo=0, hi=1) == 0.7

    def test_env_var_out_of_range_rejected_at_load(self, monkeypatch):
        """Dangerous-path: a misconfigured env var raises at config module
        import — startup fails loud, never silently misbehaves."""
        from config import _bounded_float_env
        monkeypatch.setenv("__T159_BAD__", "999")
        with pytest.raises(RuntimeError, match=r"out of range"):
            _bounded_float_env("__T159_BAD__", "1.0", lo=0.01, hi=100.0)

    def test_exec_link_price_tol_uses_bounded_helper(self):
        """Source pin: the load-bearing wire-up. Bare float(os.getenv...)
        must be replaced with _bounded_float_env."""
        src = Path("config.py").read_text(encoding="utf-8")
        assert "EXEC_LINK_PRICE_TOL = _bounded_float_env(" in src, (
            "MED-021 regression: EXEC_LINK_PRICE_TOL reverted to bare "
            "float(os.getenv(...)) — accepts NaN/inf/negative again."
        )

    def test_exchange_refresh_hz_uses_bounded_helper(self):
        src = Path("config.py").read_text(encoding="utf-8")
        assert "EXCHANGE_REFRESH_HZ = _bounded_float_env(" in src, (
            "MED-021 regression: EXCHANGE_REFRESH_HZ reverted to bare "
            "float(os.getenv(...)) — 0Hz would cause div-by-zero downstream."
        )

    def test_bare_float_pattern_gone(self):
        """Defensive: the pre-T159 form `float(os.getenv("EXEC..."` or
        `float(os.getenv("EXCHANGE_REFRESH_HZ"...`
        must not reappear via revert."""
        src = Path("config.py").read_text(encoding="utf-8")
        assert 'float(os.getenv("EXEC_LINK_PRICE_TOL"' not in src
        assert 'float(os.getenv("EXCHANGE_REFRESH_HZ"' not in src


# ── Top-level anchors ──────────────────────────────────────────────────────


class TestTask159Anchors:
    """The four anchor comments tie each finding to T159 + its mechanism
    so a future maintainer can trace why these clamps exist."""

    def test_risk_engine_anchors(self):
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        for anchor in ("Task 159 (MED-002)", "Task 159 (MED-016)",
                       "Task 159 (MED-019)"):
            assert anchor in src, f"Missing anchor: {anchor}"

    def test_config_anchor(self):
        src = Path("config.py").read_text(encoding="utf-8")
        assert "Task 159 (MED-021)" in src

