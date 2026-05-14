"""
Deterministic clock for state-machine testing.

Provides a controllable time source so tests can advance time in fixed
steps without wall-clock dependency.  Production code never imports
this module — it exists solely for the test harness.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


class TestClock:
    """Controllable clock that starts at a given instant (default: epoch UTC)."""

    __test__ = False  # prevent pytest collection

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        """Return the current synthetic time."""
        return self._now

    def advance(self, seconds: float) -> datetime:
        """Move the clock forward by *seconds* and return the new time."""
        self._now += timedelta(seconds=seconds)
        return self._now

    def set(self, dt: datetime) -> None:
        """Jump the clock to an absolute instant."""
        self._now = dt
