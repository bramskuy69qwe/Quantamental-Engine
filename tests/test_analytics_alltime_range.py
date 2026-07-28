"""E2E-P2-001 regression pins — period=all_time 500 on the analytics doors.

Mechanism (investigated, not assumed): resolve_period('all_time') returns
start=datetime.min (year 1, tz-aware). _analytics_range converted that to
from_ms = -62_135_620_924_000; core/db_analytics.get_r_multiples then ran
datetime.utcfromtimestamp(from_ms/1000), which on Windows raises OSError
(outside the platform gmtime() range) — get_r_multiples is called OUTSIDE
the route's return_exceptions gather, so the whole fragment 500'd. The
gathered stats calls (db_analytics.py:64/124 use the same conversion)
failed too but degraded SILENTLY to {} — empty All-Time stats.

The legacy all=1 path always used from_ms=0; only the v3 React
PeriodSelector sends period=all_time, which is why this survived until the
Phase-2 sweep. Fix: clamp both bounds at the producer (_analytics_range).

Found by the Playwright Phase-2 sweep (run 2-20260728-0422, CRIT http-5xx
@ Analytics period:all), reproduced live with a direct GET before fixing.
"""
from datetime import datetime, timezone

from api.routes_analytics import _analytics_range


class TestAllTimeRangeClamp:
    def test_all_time_from_ms_is_epoch_zero(self):
        from_ms, to_ms, label, period_s = _analytics_range(period="all_time", offset=0)
        assert from_ms == 0, (
            "all_time lower bound must clamp to epoch 0 — a negative epoch "
            "kills utcfromtimestamp on Windows (OSError) in get_r_multiples "
            "and silently empties the gathered journal stats"
        )
        assert to_ms > 0
        assert label == "All Time"
        assert period_s == "all_time"

    def test_all_time_bounds_convert_cleanly(self):
        """The exact downstream conversion that raised pre-fix."""
        from_ms, to_ms, _, _ = _analytics_range(period="all_time", offset=0)
        for ms in (from_ms, to_ms):
            # tz-aware conversion — same range constraints, no deprecation.
            dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
            assert dt.year >= 1970

    def test_legacy_all_param_unchanged(self):
        from_ms, _, label, _ = _analytics_range(all="1")
        assert from_ms == 0
        assert label == "All Time"

    def test_other_periods_untouched_by_clamp(self):
        from_ms, to_ms, _, _ = _analytics_range(period="monthly", offset=0)
        assert 0 < from_ms < to_ms
