"""Tests for core.period_resolver — analytics period boundary computation."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from core.period_resolver import VALID_PERIODS, resolve_period

TZ = ZoneInfo("Asia/Jakarta")  # UTC+7
NOW = datetime(2026, 5, 15, 10, 0, 0, tzinfo=TZ)  # Friday


class TestWeekly:
    def test_monday_start(self):
        start, end = resolve_period("weekly", TZ, now=NOW, week_start_dow=1)
        assert start.isoweekday() == 1  # Monday
        assert start == datetime(2026, 5, 11, 0, 0, 0, tzinfo=TZ)
        assert end == datetime(2026, 5, 17, 23, 59, 59, tzinfo=TZ)

    def test_sunday_start(self):
        start, end = resolve_period("weekly", TZ, now=NOW, week_start_dow=7)
        assert start.isoweekday() == 7  # Sunday
        assert start == datetime(2026, 5, 10, 0, 0, 0, tzinfo=TZ)
        assert end == datetime(2026, 5, 16, 23, 59, 59, tzinfo=TZ)


class TestMonthly:
    def test_boundaries(self):
        start, end = resolve_period("monthly", TZ, now=NOW)
        assert start == datetime(2026, 5, 1, 0, 0, 0, tzinfo=TZ)
        assert end == datetime(2026, 5, 31, 23, 59, 59, tzinfo=TZ)

    def test_february(self):
        feb = datetime(2026, 2, 15, 12, 0, tzinfo=TZ)
        start, end = resolve_period("monthly", TZ, now=feb)
        assert start.day == 1
        assert end.day == 28


class TestQuarterly:
    def test_q2(self):
        start, end = resolve_period("quarterly", TZ, now=NOW)
        assert start == datetime(2026, 4, 1, 0, 0, 0, tzinfo=TZ)
        assert end == datetime(2026, 6, 30, 23, 59, 59, tzinfo=TZ)

    def test_q1(self):
        jan = datetime(2026, 1, 20, 8, 0, tzinfo=TZ)
        start, end = resolve_period("quarterly", TZ, now=jan)
        assert start.month == 1
        assert end.month == 3
        assert end.day == 31


class TestYearly:
    def test_boundaries(self):
        start, end = resolve_period("yearly", TZ, now=NOW)
        assert start == datetime(2026, 1, 1, 0, 0, 0, tzinfo=TZ)
        assert end == datetime(2026, 12, 31, 23, 59, 59, tzinfo=TZ)


class TestRolling:
    def test_30d(self):
        start, end = resolve_period("rolling_30d", TZ, now=NOW)
        assert end == NOW
        assert (end - start).days == 30

    def test_90d(self):
        start, end = resolve_period("rolling_90d", TZ, now=NOW)
        assert end == NOW
        assert (end - start).days == 90


class TestAllTime:
    def test_starts_at_min(self):
        start, end = resolve_period("all_time", TZ, now=NOW)
        assert start.year == 1
        assert end == NOW


class TestValidation:
    def test_unknown_period_raises(self):
        with pytest.raises(ValueError, match="Unknown period"):
            resolve_period("biweekly", TZ, now=NOW)

    def test_all_valid_periods_accepted(self):
        for p in VALID_PERIODS:
            start, end = resolve_period(p, TZ, now=NOW)
            assert start <= end

    def test_naive_now_gets_tz(self):
        naive = datetime(2026, 5, 15, 10, 0, 0)
        start, end = resolve_period("monthly", TZ, now=naive)
        assert start.tzinfo is not None
