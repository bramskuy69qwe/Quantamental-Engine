"""
Task 161 regression tests — contract-validation NameError + broad-except
swallow in risk_engine.run_risk_calculator.

Latent correctness bug surfaced during T160 investigation (not an audit
finding). Pre-T161 code at risk_engine.py:431-432 referenced
`result["eligible"] = False` / `result["ineligible_reason"] = ...` inside
the contract-validation-failure branch — but `result` is the local var
name from `calculate_position_size`, NOT defined in
`run_risk_calculator`'s scope. Every contract-validation-failure call
raised NameError; the broad `except Exception: pass` at line ~445
silently swallowed it; size remained un-snapped; eligible stayed True.
The "block on contract-spec violation" safety check was DEAD CODE.

Fix shape:
  - Replace the wrong `result[...]` refs with local flags
    `contract_invalid` + `contract_reason`.
  - Feed those into the existing T159 final_reason chain + T160
    final_eligible AND (chain: sizing-path > contract > portfolio).
  - Narrow `except Exception` to `except (ImportError, AttributeError)`
    so programming errors (NameError, TypeError, KeyError) propagate
    and surface. ImportError covers "validation infra unavailable"
    (the original intent of the comment); AttributeError covers API
    drift on the ValidationResult dataclass.
  - log.warning when the narrow-swallow path fires — operator sees
    contract validation went no-op rather than failing silently.

Deviations from spec:
  - The spec said "fix shape: make eligible=False + a clear reason
    actually land, consistent with the other reject paths (T159/T160
    shape: eligible=False + reason + size=0 + would_be_size handled)."
    T160's dict-level enforcement already handles size=0 + would_be_size
    automatically when final_eligible flips False — the contract_invalid
    feeds final_eligible, so the T160 mechanism covers the size zeroing
    without per-path duplication. Verified in test below.
  - The spec asked to "list other errors the narrowed except surfaces."
    Investigation: validate_and_snap_size's internal flow catches
    InvalidOperation + ValueError itself (returns ValidationResult with
    valid=False), so those don't propagate to our handler. Real bugs
    that the narrow except would now surface: any KeyError from
    `sizing["est_fill_price"]`, TypeError from a corrupted vr object,
    NameError from future maintainer regression like this one. None
    are currently triggered in production paths — the narrowing is
    purely a guardrail.

Run: pytest tests/test_task161_contract_validation_nameerror.py -v
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Fixture: stub app_state enough to drive run_risk_calculator ────────────


@pytest.fixture
def stub_app_state(monkeypatch):
    """Stub minimal app_state for risk_engine.run_risk_calculator without
    a real engine setup. Mirrors T160's pattern — clear _data_cache,
    write via _positions_legacy."""
    from core.state import app_state
    from core import monitoring, risk_engine

    monkeypatch.setattr(
        monitoring, "ReadyStateEvaluator",
        lambda: type("R", (), {"evaluate": lambda s: (True, "")})(),
        raising=False,
    )
    monkeypatch.setattr(app_state, "exchange_info",
                        SimpleNamespace(maker_fee=0.0002, taker_fee=0.0005),
                        raising=False)
    monkeypatch.setattr(app_state, "ws_status",
                        SimpleNamespace(is_stale=False), raising=False)
    monkeypatch.setattr(app_state, "account_state",
                        SimpleNamespace(total_equity=10000.0), raising=False)
    monkeypatch.setattr(app_state, "portfolio",
                        SimpleNamespace(weekly_pnl_state="ok", dd_state="ok"),
                        raising=False)
    params = dict(getattr(app_state, "params", {}))
    params.update({
        "individual_risk_per_trade": 0.01,
        "max_position_count": 10,
        "max_exposure": 5.0,
        "max_correlated_exposure": 5.0,
    })
    monkeypatch.setattr(app_state, "params", params, raising=False)
    monkeypatch.setattr(app_state, "orderbook_cache",
                        {"BTCUSDT": {"bids": [[80000.0, 10.0]],
                                      "asks": [[80000.0, 10.0]]}},
                        raising=False)
    # Clear DataCache + write empty positions via legacy slot (T160 lesson)
    monkeypatch.setattr(app_state, "_data_cache", None, raising=False)
    monkeypatch.setattr(app_state, "_positions_legacy", [], raising=False)
    monkeypatch.setattr(app_state, "ohlcv_cache", {}, raising=False)
    monkeypatch.setattr(app_state, "current_regime", None, raising=False)
    monkeypatch.setattr(app_state, "is_initializing", False, raising=False)

    monkeypatch.setattr(
        risk_engine, "calculate_atr_coefficient",
        lambda symbol: (0.5, "normal", 100.0, 200.0),
    )
    return app_state


# ── Pre-fix behavior pin: confirm the NameError shape was reachable ────────


class TestPreFixWasNameError:
    """Document what the pre-T161 code did. The narrowed except now lets
    a similar NameError propagate; if it ever fires again, tests catch it
    immediately instead of the production calculator continuing as if
    eligible."""

    @staticmethod
    def _strip_comments(body: str) -> str:
        """Remove `#`-prefixed line comments so source-pin checks scope
        to executing code only (the T161 anchor comment intentionally
        documents the buggy form for future maintainers — would trip
        naive substring checks)."""
        out = []
        for line in body.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            out.append(line)
        return "\n".join(out)

    def test_pre_t161_source_no_longer_references_undefined_result(self):
        """Source pin: the bug was `result["eligible"] = False` inside
        run_risk_calculator. Must not return."""
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        # Find run_risk_calculator's body
        idx = src.find("def run_risk_calculator(")
        assert idx > 0
        end = src.find("\ndef ", idx + 10)
        body = src[idx:end] if end > 0 else src[idx:]
        body = self._strip_comments(body)
        # The exact pre-T161 buggy lines:
        assert 'result["eligible"] = False' not in body, (
            "T161 regression: undefined `result` reference is back inside "
            "run_risk_calculator — the contract-validation reject branch "
            "will NameError + swallow again, silently disabling the safety "
            "check."
        )
        assert 'result["ineligible_reason"]' not in body, (
            "T161 regression: undefined `result` reference is back."
        )

    def test_t161_anchor_present(self):
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        assert "Task 161" in src
        # Anchor mentions the dead-code mechanism so future maintainers
        # understand why the local-flag pattern exists
        assert "DEAD CODE" in src or "dead code" in src.lower()


# ── Fix 1: contract-invalid → eligible=False with clear reason ─────────────


class TestContractRejectActuallyBlocks:
    """The DANGEROUS-PATH test. Mock validate_and_snap_size to return
    `valid=False` and confirm the calc dict reflects eligible=False +
    populated reason + size=0 (the T160 dict-level zeroing handles
    size automatically once final_eligible is False)."""

    def test_contract_invalid_lands_as_eligible_false(self, stub_app_state, monkeypatch):
        """Pre-T161: contract-invalid → NameError → swallowed → calc
        proceeds as eligible. Post-T161: eligible=False + reason set."""
        from core import risk_engine

        # Mock the contract_validation module so its result says
        # "valid=False, reason=below_min_qty". This is the path that
        # used to trigger the NameError pre-T161.
        from core import contract_validation
        fake_invalid = contract_validation.ValidationResult(
            valid=False,
            snapped_size=Decimal("0.001"),
            original_size=Decimal("0.0005"),
            reason="below_min_qty (0.0005 < 0.001)",
            suggested_size=Decimal("0.001"),
        )
        monkeypatch.setattr(
            contract_validation, "validate_and_snap_size",
            lambda size, symbol, price: fake_invalid,
        )

        result = risk_engine.run_risk_calculator(
            ticker="BTCUSDT", average=80000.0, sl_price=79000.0,
            tp_price=82000.0, tp_amount_pct=100, sl_amount_pct=100,
        )

        # Load-bearing assertion: the contract-spec safety check fires
        assert result["eligible"] is False, (
            "T161 regression: contract-validation-invalid did not flip "
            "eligible to False — the safety check is silently dead "
            "(NameError swallow returned)."
        )
        # Reason populated with the contract-spec detail
        assert "Contract spec" in result["ineligible_reason"], (
            f"T161 regression: ineligible_reason not populated with "
            f"contract detail; got {result['ineligible_reason']!r}"
        )
        assert "below_min_qty" in result["ineligible_reason"]
        # T160 dict-level enforcement: size = 0 once final_eligible flips
        assert result["size"] == 0.0, (
            "T161+T160 integration: size should be zeroed when contract-"
            "invalid blocks the trade."
        )
        # would_be_size carries the pre-zero computed value (T160)
        assert result["would_be_size"] > 0, (
            "T160 integration: would_be_size should carry the pre-zero "
            "computed size for forensic display."
        )

    def test_contract_valid_with_snap_still_works(self, stub_app_state, monkeypatch):
        """Anti-regression: when contract validation returns valid=True
        with a smaller snapped_size, the calculator must accept the
        snap and proceed eligible. Verifies T161 didn't break the
        happy-path snap behavior."""
        from core import risk_engine
        from core import contract_validation

        # Return valid=True with a snapped size 1% smaller than input —
        # the snap branch should fire and size update.
        # Compute the pre-snap "raw" size from the engine's formula so
        # we can construct a credible snap target.
        result_unsnapped = risk_engine.run_risk_calculator(
            ticker="BTCUSDT", average=80000.0, sl_price=79000.0,
            tp_price=82000.0, tp_amount_pct=100, sl_amount_pct=100,
        )
        raw_size = result_unsnapped["would_be_size"]
        # Snap to 99% of the raw
        snapped_target = raw_size * 0.99

        fake_valid = contract_validation.ValidationResult(
            valid=True,
            snapped_size=Decimal(str(snapped_target)),
            original_size=Decimal(str(raw_size)),
        )
        monkeypatch.setattr(
            contract_validation, "validate_and_snap_size",
            lambda size, symbol, price: fake_valid,
        )

        result = risk_engine.run_risk_calculator(
            ticker="BTCUSDT", average=80000.0, sl_price=79000.0,
            tp_price=82000.0, tp_amount_pct=100, sl_amount_pct=100,
        )
        assert result["eligible"] is True
        # Size has been snapped down (very approximate — float == compare
        # would be brittle; check it's close to the snap target)
        assert abs(result["size"] - snapped_target) < 1e-6


# ── Fix 2: narrowed except — programming errors propagate ──────────────────


class TestBroadExceptNarrowed:
    """Pre-T161 had `except Exception: pass`. Post-T161 catches only
    ImportError + AttributeError (the "validation infra unavailable"
    cases). Other exceptions must propagate."""

    def test_except_clause_narrowed_in_source(self):
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        # The pre-T161 swallow was right after the contract-validation
        # try block (line ~445).
        idx = src.find("validate_and_snap_size")
        assert idx > 0
        window = src[idx:idx + 4000]
        # Scope to executing code — strip `#` line comments so the
        # T161 anchor's pre-fix-form documentation doesn't count.
        executing = "\n".join(
            line for line in window.splitlines()
            if not line.lstrip().startswith("#")
        )
        # Narrow form present
        assert "except (ImportError, AttributeError)" in executing, (
            "T161 regression: contract-validation except clause widened "
            "back to bare `Exception` — programming errors will be "
            "silently swallowed again."
        )
        # In executing code: at most 1 bare `except Exception:` (the
        # inner event_log one), at least 1 narrow (the outer contract
        # validation).
        count_bare = executing.count("except Exception:")
        count_narrow = executing.count("except (ImportError, AttributeError)")
        assert count_narrow >= 1
        assert count_bare <= 1, (
            f"T161 regression: too many bare `except Exception:` in "
            f"executing code of the contract-validation block "
            f"({count_bare} found, max 1 for the inner event_log)"
        )

    def test_warning_logged_on_validation_unavailable(self, stub_app_state, monkeypatch, caplog):
        """When ImportError fires (validate_and_snap_size import fails),
        the narrow except logs a warning so the operator sees that
        contract validation went no-op for this cycle. Pre-T161 was
        silent `pass`."""
        from core import risk_engine
        import logging

        # Force an ImportError by monkeypatching the module reference
        # the function imports. The function does
        # `from core.contract_validation import validate_and_snap_size`
        # inline — patch the module's attribute so the import resolves
        # but the name doesn't exist → ImportError.
        import core.contract_validation
        monkeypatch.delattr(core.contract_validation, "validate_and_snap_size")

        caplog.set_level(logging.WARNING)
        result = risk_engine.run_risk_calculator(
            ticker="BTCUSDT", average=80000.0, sl_price=79000.0,
            tp_price=82000.0, tp_amount_pct=100, sl_amount_pct=100,
        )
        # The calc still proceeds (validation went no-op — don't block
        # on infra unavailability)
        assert result["eligible"] is True
        # But a warning fired so the no-op is visible
        warnings = [r for r in caplog.records
                    if "contract validation skipped" in r.message.lower()]
        assert warnings, (
            "T161 regression: validation-unavailable path no longer "
            "logs warning — silent no-op is back."
        )


# ── End-to-end integration with T159 + T160 ───────────────────────────────


class TestT159T160Integration:
    """Confirm the contract-invalid path now plays cleanly with the
    T159 final_reason chain + T160 dict-level enforcement."""

    def test_contract_reason_priority_below_sizing(self, stub_app_state, monkeypatch):
        """Reason priority: sizing-path reject (earliest) > contract
        reject > portfolio reject. If BOTH a sizing-path and contract
        problem exist, sizing wins."""
        from core import risk_engine
        from core import contract_validation

        # Mock contract to return invalid
        fake_invalid = contract_validation.ValidationResult(
            valid=False, snapped_size=Decimal("0.001"),
            original_size=Decimal("0.0005"),
            reason="below_min_qty",
        )
        monkeypatch.setattr(
            contract_validation, "validate_and_snap_size",
            lambda *a, **kw: fake_invalid,
        )

        # Trigger a sizing-path reject (sl_price == average → "zero risk
        # distance"). Sizing should win the reason.
        result = risk_engine.run_risk_calculator(
            ticker="BTCUSDT", average=80000.0, sl_price=80000.0,
            tp_price=82000.0, tp_amount_pct=100, sl_amount_pct=100,
        )
        assert result["eligible"] is False
        # Sizing-path reason wins
        assert ("zero risk distance" in result["ineligible_reason"].lower()
                or "invalid" in result["ineligible_reason"].lower())
        # Contract reason is suppressed because sizing fired first
        assert "Contract spec" not in result["ineligible_reason"]

    def test_contract_reason_priority_above_portfolio(self, stub_app_state, monkeypatch):
        """Contract reject beats portfolio reject (contract is priced
        at sizing time; portfolio assembly is later in the pipeline)."""
        from core import risk_engine
        from core import contract_validation

        # 10 positions → at_max_positions
        fake_positions = [
            SimpleNamespace(position_value_usdt=100.0, direction="LONG",
                             sector="big_two_crypto")
            for _ in range(10)
        ]
        monkeypatch.setattr(
            risk_engine.app_state, "_positions_legacy", fake_positions,
            raising=False,
        )
        fake_invalid = contract_validation.ValidationResult(
            valid=False, snapped_size=Decimal("0.001"),
            original_size=Decimal("0.0005"),
            reason="below_min_qty",
        )
        monkeypatch.setattr(
            contract_validation, "validate_and_snap_size",
            lambda *a, **kw: fake_invalid,
        )

        result = risk_engine.run_risk_calculator(
            ticker="BTCUSDT", average=80000.0, sl_price=79000.0,
            tp_price=82000.0, tp_amount_pct=100, sl_amount_pct=100,
        )
        assert result["eligible"] is False
        # Contract reason wins over the portfolio reason
        assert "Contract spec" in result["ineligible_reason"], (
            f"T161 regression: contract reject lost to portfolio reason; "
            f"got {result['ineligible_reason']!r}"
        )
        # at_max_positions IS true, but contract precedes it
        assert result["at_max_positions"] is True
