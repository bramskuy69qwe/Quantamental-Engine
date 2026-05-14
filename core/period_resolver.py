"""
Analytics period resolver — computes (start, end) datetime boundaries.

Used by UI consumers to resolve the account's ``analytics_default_period``
(or a user-selected override) into a concrete time range.

Supports: weekly, monthly, quarterly, yearly, rolling_30d, rolling_90d, all_time.
"""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

VALID_PERIODS = frozenset({
    "weekly", "monthly", "quarterly", "yearly",
    "rolling_30d", "rolling_90d", "all_time",
})


def resolve_period(
    period: str,
    tz: ZoneInfo,
    *,
    now: datetime | None = None,
    week_start_dow: int = 1,
) -> tuple[datetime, datetime]:
    """Return ``(start, end)`` for *period* in timezone *tz*.

    Args:
        period: One of ``VALID_PERIODS``.
        tz: Account timezone for calendar-boundary calculations.
        now: Override for deterministic testing.  Defaults to ``datetime.now(tz)``.
        week_start_dow: ISO weekday for week start (1=Monday, 7=Sunday).

    Returns:
        Tuple of tz-aware datetimes ``(start_inclusive, end_inclusive)``.

    Raises:
        ValueError: Unknown *period*.
    """
    if period not in VALID_PERIODS:
        raise ValueError(
            f"Unknown period {period!r}. Valid: {sorted(VALID_PERIODS)}"
        )

    if now is None:
        now = datetime.now(tz)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=tz)

    if period == "weekly":
        # Days since the configured start-of-week
        current_dow = now.isoweekday()  # 1=Mon ... 7=Sun
        days_back = (current_dow - week_start_dow) % 7
        start = (now - timedelta(days=days_back)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end = start + timedelta(days=6, hours=23, minutes=59, seconds=59)
        return start, end

    if period == "monthly":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        _, last_day = calendar.monthrange(now.year, now.month)
        end = now.replace(
            day=last_day, hour=23, minute=59, second=59, microsecond=0
        )
        return start, end

    if period == "quarterly":
        q_start_month = ((now.month - 1) // 3) * 3 + 1
        start = now.replace(
            month=q_start_month, day=1,
            hour=0, minute=0, second=0, microsecond=0,
        )
        q_end_month = q_start_month + 2
        _, last_day = calendar.monthrange(now.year, q_end_month)
        end = now.replace(
            month=q_end_month, day=last_day,
            hour=23, minute=59, second=59, microsecond=0,
        )
        return start, end

    if period == "yearly":
        start = now.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        end = now.replace(
            month=12, day=31, hour=23, minute=59, second=59, microsecond=0
        )
        return start, end

    if period == "rolling_30d":
        end = now
        start = now - timedelta(days=30)
        return start, end

    if period == "rolling_90d":
        end = now
        start = now - timedelta(days=90)
        return start, end

    # all_time
    start = datetime.min.replace(tzinfo=tz)
    return start, now
