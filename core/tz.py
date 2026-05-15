"""
Per-account timezone resolution.

Reads the ``timezone`` column from ``account_settings`` (via the
accessor in ``core.db_account_settings``) and returns a ``ZoneInfo``
object suitable for ``datetime.now(tz)``.

Replaces the global ``state.TZ_LOCAL`` at risk-critical call sites.
Display-only sites are migrated separately.
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger("tz")

_UTC = ZoneInfo("UTC")


def get_account_tz(account_id: int) -> ZoneInfo:
    """Return the ``ZoneInfo`` for *account_id*'s configured timezone.

    Falls back to UTC (with a WARNING log) if:
    - the account doesn't exist in ``account_settings``
    - the stored timezone string is unparseable
    """
    try:
        from core.db_account_settings import get_account_settings

        settings = get_account_settings(account_id)
        return ZoneInfo(settings.timezone)
    except KeyError:
        log.warning("get_account_tz: unknown account_id=%d — defaulting to UTC", account_id)
        return _UTC
    except (ZoneInfoNotFoundError, KeyError) as exc:
        log.warning("get_account_tz: bad timezone for account %d (%s) — defaulting to UTC", account_id, exc)
        return _UTC


def now_in_account_tz(account_id: int) -> datetime:
    """Convenience: ``datetime.now`` in the account's configured timezone."""
    return datetime.now(get_account_tz(account_id))


def format_tz_display(account_id: int) -> str:
    """Return a display string like 'UTC+7' for the account's timezone.

    Computes the current UTC offset (DST-aware) from the IANA zone name.
    """
    tz = get_account_tz(account_id)
    offset = datetime.now(tz).utcoffset()
    if offset is None:
        return "UTC"
    total_seconds = int(offset.total_seconds())
    hours, remainder = divmod(abs(total_seconds), 3600)
    minutes = remainder // 60
    sign = "+" if total_seconds >= 0 else "-"
    if minutes:
        return f"UTC{sign}{hours}:{minutes:02d}"
    return f"UTC{sign}{hours}"
