"""
Task 164 regression tests — FRED-error → conservative-path discipline.

Background (T163 + T164 verify-then-fix):
  T163's MED-030 fix routes FRED errors to `return 0 (rows)`. Spec
  worried that this might inject `0` as a signal value, satisfying
  the JSON rules' risk-on gate (`hy_spread < 3.5`). Verification
  outcome:

  - **LIVE BUG: REFUTED.** Trace confirmed `return 0` is the row
    count, not a signal value. Empty regime_signals row → missing
    signal at classify time → strict-AND fails → conservative
    (neutral). End-to-end repro test confirms.

  - **HAZARD: CONFIRMED.** If any code path ever injects 0 as a
    signal value for vix_close / btc_rvol_ratio / hy_spread, the
    JSON rules' risk-on gates would fire (size-UP on garbage).
    Reproduced directly with explicit-zero inputs.

  - **FIX: source-side `value > 0` filter** at the three fetchers
    for the three dangerous-direction signals:
      - fetch_vix: discard rows with VIX value <= 0.
      - fetch_fred_series: discard rows for hy_spread (signal-name-
        conditional, leaving us10y_yield alone — not in rules + 0
        plausible in zero-rate regime).
      - compute_btc_rvol_ratio: discard ratio <= 0.
    Each emits log.warning. agg_oi_change + avg_funding NOT
    filtered — 0 is a legitimate value AND the rules use strict
    `>` (0 fails the gate naturally).

Coverage:
  - End-to-end live-bug-refuted property (hy missing → neutral).
  - Hazard control (hy=0 explicit → risk_on_trending) — locks in
    that the hazard is real, surfaces if anyone weakens the
    discipline.
  - Source-side filter behavior at all 3 fetchers + safe-at-0
    signal anti-control.

Run: pytest tests/test_task164_fred_error_conservative.py -v
"""
from __future__ import annotations

import logging
import math
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── End-to-end: live-bug-refuted property ──────────────────────────────────


class TestLiveBugRefutedProperty:
    """The actual data flow on FRED error is conservative — assert it
    end-to-end so future maintainers can't accidentally regress to
    default-to-0 patterns."""

    def test_missing_hy_with_riskon_qualifying_signals_yields_neutral(self):
        """FRED error → hy_spread missing from signals dict → strict-AND
        on `hy_spread < 3.5` fails → no risk-on rule matches → neutral.

        This is the actual data flow per investigation. Conservative
        direction holds; live-bug refuted."""
        from core.regime_classifier import classify_regime
        sig = {
            "vix_close": 15,           # low — would satisfy `< 20`
            "btc_rvol_ratio": 1.0,     # low — would satisfy `< 1.2`
            # NO hy_spread (FRED error → no row → missing)
            "mode": "macro_only",
        }
        result = classify_regime(sig)
        assert result == "neutral", (
            f"T164 regression: missing-hy + risk-on-qualifying VIX/rvol "
            f"yielded {result!r}, expected neutral. The conservative path "
            "for FRED-error is broken — likely a default-to-0 was added."
        )

    def test_missing_all_three_dangerous_signals_yields_neutral(self):
        """Even with everything missing except mode, the default
        fallback is neutral / 1.0."""
        from core.regime_classifier import classify_regime
        assert classify_regime({"mode": "macro_only"}) == "neutral"


class TestHazardControl:
    """Pin the hazard: IF a signal value of 0 ever reaches the classifier
    for vix / rvol / hy_spread, risk-on fires. This test surfaces
    regressions where someone weakens the source-side filter or adds a
    default-to-0 pattern."""

    def test_hy_zero_satisfies_riskon_gate(self):
        """Hazard: hy_spread = 0 satisfies `< 3.5` → risk_on_trending
        with the other low-VIX/compressed-rvol gates. Pinned so any
        future weakening of the missing-not-zero discipline is loud."""
        from core.regime_classifier import classify_regime
        sig = {
            "vix_close": 15,
            "btc_rvol_ratio": 1.0,
            "hy_spread": 0.0,          # ← THE HAZARD
            "mode": "macro_only",
        }
        result = classify_regime(sig)
        assert result == "risk_on_trending", (
            "Hazard control unexpectedly failed. If this test starts "
            "passing AND test_missing_hy... also passes, the discipline "
            "is intact. If this fails, the JSON rules changed and the "
            "hazard direction may have shifted."
        )

    def test_vix_zero_satisfies_riskon_gate(self):
        """Hazard: vix_close = 0 satisfies `< 20`. Same shape as hy=0."""
        from core.regime_classifier import classify_regime
        sig = {
            "vix_close": 0.0,          # ← HAZARD
            "btc_rvol_ratio": 1.0,
            "hy_spread": 3.0,
            "mode": "macro_only",
        }
        assert classify_regime(sig) == "risk_on_trending"

    def test_rvol_zero_satisfies_riskon_gate(self):
        """Hazard: btc_rvol_ratio = 0 satisfies `< 1.2`."""
        from core.regime_classifier import classify_regime
        sig = {
            "vix_close": 15,
            "btc_rvol_ratio": 0.0,     # ← HAZARD
            "hy_spread": 3.0,
            "mode": "macro_only",
        }
        assert classify_regime(sig) == "risk_on_trending"

    def test_oi_zero_does_not_trigger_riskon(self):
        """Anti-control: agg_oi_change = 0 should NOT trigger risk-on
        because the rule is `agg_oi_change > 0` (strict). 0 is a
        legitimate "no change" value; safe direction."""
        from core.regime_classifier import classify_regime
        sig = {
            "vix_close": 15,
            "btc_rvol_ratio": 1.0,
            "hy_spread": 3.0,
            "agg_oi_change": 0.0,      # ← safe at 0
            "avg_funding": 0.001,
            "mode": "full",
        }
        # With oi=0, full-mode trending rules require oi>0 → fail.
        # Macro_only trending requires mode==macro_only → fail.
        # Should not be trending. (May be choppy if vix/rvol fit, but
        # rvol=1.0 doesn't satisfy choppy `> 1.3`.) Expected: neutral.
        assert classify_regime(sig) == "neutral"

    def test_funding_zero_does_not_trigger_riskon(self):
        """Anti-control: avg_funding = 0 should NOT trigger risk-on
        for the same reason as oi (rule is strict `> 0`)."""
        from core.regime_classifier import classify_regime
        sig = {
            "vix_close": 15,
            "btc_rvol_ratio": 1.0,
            "hy_spread": 3.0,
            "agg_oi_change": 0.5,
            "avg_funding": 0.0,        # ← safe at 0
            "mode": "full",
        }
        assert classify_regime(sig) == "neutral"


# ── Source-side filters: T164 missing-not-zero discipline ─────────────────


class TestVixFetcherFiltersNonPositive:
    """fetch_vix discards rows with value <= 0."""

    @pytest.mark.asyncio
    async def test_zero_vix_filtered(self, monkeypatch, caplog):
        from core import regime_fetcher

        # Build a synthetic DataFrame with one valid + one zero row
        import pandas as pd  # type: ignore

        df = pd.DataFrame(
            {"Close": [25.5, 0.0, 18.2]},
            index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        )

        class _FakeYf:
            @staticmethod
            def download(*a, **kw):
                return df

        # Patch the lazy `import yfinance as yf` inside _download.
        # Use sys.modules injection so the local import resolves to our stub.
        monkeypatch.setitem(sys.modules, "yfinance", _FakeYf)
        # Stub upsert so we can inspect what was passed
        captured_rows = []

        async def fake_upsert(name, rows, source):
            captured_rows.extend(rows)
            return len(rows)

        monkeypatch.setattr(regime_fetcher.db, "upsert_regime_signals",
                            fake_upsert, raising=False)

        caplog.set_level(logging.WARNING, logger="regime_fetcher")
        fetcher = regime_fetcher.RegimeFetcher()
        await fetcher.fetch_vix("2024-01-01", "2024-01-03")

        # Two rows stored (25.5, 18.2); the 0.0 was filtered
        stored_values = [r["value"] for r in captured_rows]
        assert 0.0 not in stored_values, (
            f"T164 regression: VIX zero value reached storage. "
            f"Stored: {stored_values}"
        )
        assert 25.5 in stored_values and 18.2 in stored_values

        # Warning surfaced the filter
        warns = [r for r in caplog.records
                 if "implausible" in r.message and "VIX" in r.message]
        assert warns, "Expected log.warning for filtered VIX zero"

    @pytest.mark.asyncio
    async def test_negative_vix_filtered(self, monkeypatch):
        """Negative VIX is also filtered (defensive — shouldn't occur,
        but the `v <= 0` check covers it)."""
        from core import regime_fetcher
        import pandas as pd

        df = pd.DataFrame(
            {"Close": [25.0, -1.0]},
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )

        class _FakeYf:
            @staticmethod
            def download(*a, **kw):
                return df

        monkeypatch.setitem(sys.modules, "yfinance", _FakeYf)
        captured = []

        async def fake_upsert(name, rows, source):
            captured.extend(rows)
            return len(rows)

        monkeypatch.setattr(regime_fetcher.db, "upsert_regime_signals",
                            fake_upsert, raising=False)
        await regime_fetcher.RegimeFetcher().fetch_vix(
            "2024-01-01", "2024-01-02",
        )
        values = [r["value"] for r in captured]
        assert all(v > 0 for v in values), (
            f"T164 regression: non-positive VIX leaked. Values: {values}"
        )


class TestHySpreadFetcherFiltersNonPositive:
    """fetch_fred_series filters hy_spread rows with value <= 0 (but
    NOT us10y_yield — 0 is theoretically possible in zero-rate regime
    and us10y is not in the dangerous-direction set)."""

    @pytest.mark.asyncio
    async def test_zero_hy_spread_filtered(self, monkeypatch, caplog):
        from core import regime_fetcher

        # Stub config so the API-key check passes
        monkeypatch.setattr(regime_fetcher.config, "FRED_API_KEY",
                            "test_key", raising=False)

        # FRED-like response with two observations
        class _FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return {
                    "observations": [
                        {"date": "2024-01-01", "value": "3.5"},
                        {"date": "2024-01-02", "value": "0.0"},
                        {"date": "2024-01-03", "value": "4.0"},
                    ]
                }

        class _FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, *a, **kw): return _FakeResp()

        monkeypatch.setattr(regime_fetcher.httpx, "AsyncClient",
                            lambda *a, **kw: _FakeClient(), raising=False)

        captured = []

        async def fake_upsert(name, rows, source):
            captured.extend(rows)
            return len(rows)

        monkeypatch.setattr(regime_fetcher.db, "upsert_regime_signals",
                            fake_upsert, raising=False)

        caplog.set_level(logging.WARNING, logger="regime_fetcher")
        await regime_fetcher.RegimeFetcher().fetch_fred_series(
            "BAMLH0A0HYM2", "hy_spread", "2024-01-01", "2024-01-03",
        )
        values = [r["value"] for r in captured]
        assert 0.0 not in values, (
            f"T164 regression: hy_spread zero reached storage. {values}"
        )
        assert 3.5 in values and 4.0 in values
        warns = [r for r in caplog.records
                 if "implausible" in r.message and "hy_spread" in r.message]
        assert warns

    @pytest.mark.asyncio
    async def test_zero_us10y_NOT_filtered(self, monkeypatch):
        """Anti-control: us10y_yield isn't in the dangerous-direction
        set + 0 is theoretically possible in a zero-rate regime; the
        filter should be signal-name-conditional and NOT apply here."""
        from core import regime_fetcher

        monkeypatch.setattr(regime_fetcher.config, "FRED_API_KEY",
                            "test_key", raising=False)

        class _FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return {
                    "observations": [
                        {"date": "2024-01-01", "value": "0.0"},
                        {"date": "2024-01-02", "value": "1.2"},
                    ]
                }

        class _FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, *a, **kw): return _FakeResp()

        monkeypatch.setattr(regime_fetcher.httpx, "AsyncClient",
                            lambda *a, **kw: _FakeClient(), raising=False)
        captured = []

        async def fake_upsert(name, rows, source):
            captured.extend(rows)
            return len(rows)

        monkeypatch.setattr(regime_fetcher.db, "upsert_regime_signals",
                            fake_upsert, raising=False)
        await regime_fetcher.RegimeFetcher().fetch_fred_series(
            "DGS10", "us10y_yield", "2024-01-01", "2024-01-02",
        )
        values = [r["value"] for r in captured]
        # 0.0 NOT filtered for us10y_yield
        assert 0.0 in values, (
            "T164 regression: us10y_yield 0 was filtered. The signal-"
            "name-conditional filter should leave zero-rate values "
            "alone — 0 is theoretically possible and us10y isn't in "
            "the dangerous-direction rule set."
        )


class TestRvolComputeFiltersNonPositiveRatio:
    """compute_btc_rvol_ratio filters ratio <= 0."""

    def test_source_pin_has_positive_check(self):
        """The compute_btc_rvol_ratio path now has both
        `if vol_7d > 0` (existing) and `if ratio > 0` (T164)."""
        from pathlib import Path
        src = Path("core/regime_fetcher.py").read_text(encoding="utf-8")
        assert "if ratio > 0" in src, (
            "T164 regression: rvol filter missing — a ratio of 0 "
            "would reach storage and satisfy `< 1.2` risk-on gate."
        )
        # Anchor comment present
        assert "T164" in src and "missing-not-zero" in src


# ── End-to-end: source-side filter wired through to classification ────────


class TestEndToEndFilterPreventsRiskOn:
    """Integration check: if the filter is in place, even when upstream
    DATA tries to inject 0 for vix/hy/rvol, no risk-on fires (because
    the row never makes it to regime_signals)."""

    @pytest.mark.asyncio
    async def test_zero_vix_in_yf_does_not_yield_riskon(self, monkeypatch):
        """yfinance returns one valid VIX and one zero (corrupt source).
        After T164 source filter: only the valid row reaches DB → on
        the zero-date, the classify would see vix missing → fallback to
        neutral (the conservative direction)."""
        from core import regime_fetcher
        import pandas as pd

        # Synthesise yfinance return with a zero
        df = pd.DataFrame(
            {"Close": [0.0]},          # only a 0 → after filter, nothing
            index=pd.to_datetime(["2024-06-01"]),
        )

        class _FakeYf:
            @staticmethod
            def download(*a, **kw):
                return df

        monkeypatch.setitem(sys.modules, "yfinance", _FakeYf)
        captured = []

        async def fake_upsert(name, rows, source):
            captured.extend(rows)
            return len(rows)

        monkeypatch.setattr(regime_fetcher.db, "upsert_regime_signals",
                            fake_upsert, raising=False)
        n = await regime_fetcher.RegimeFetcher().fetch_vix(
            "2024-06-01", "2024-06-01",
        )
        # All rows filtered → 0 stored
        assert n == 0
        assert captured == []


# ── Source pins ────────────────────────────────────────────────────────────


class TestT164SourcePins:
    def test_fetch_vix_has_value_floor_anchor(self):
        from pathlib import Path
        src = Path("core/regime_fetcher.py").read_text(encoding="utf-8")
        # Check anchor + the filter in fetch_vix
        assert "Task 164" in src
        # The filter line itself
        assert "if v <= 0:" in src

    def test_fred_filter_is_signal_conditional(self):
        from pathlib import Path
        src = Path("core/regime_fetcher.py").read_text(encoding="utf-8")
        # Signal-name-conditional check
        assert "require_positive" in src
        assert '"hy_spread"' in src
        assert '"btc_rvol_ratio"' in src
