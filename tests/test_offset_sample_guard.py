"""Pins — throttle-immune clock-offset sampling + Finnhub token redaction.

1. OFFSET SAMPLE GUARD (post-restart false CLOCK criticals, 2026-07-30):
   fetch_exchange_info computed offset = server_time − midpoint(wall_before,
   wall_after), but fetch_server_time runs through the adapter's _run(),
   where the weight tracker can SLEEP seconds before the HTTP call during a
   boot burst. The sleep shifts the real exchange away from the midpoint by
   half its length — a 3,465 ms throttle turned a true −27 ms offset into a
   reported −1747 ms CRITICAL minutes after the OS clock was verified in
   sync. Samples slower than _OFFSET_SAMPLE_MAX_ELAPSED_MS are discarded;
   the last good offset stands.

2. FINNHUB TOKEN REDACTION (the SECOND leak path): capping httpx at WARNING
   silenced its INFO request echo, but httpx.HTTPStatusError embeds the full
   URL — token included — in its message, and news_fetcher's error handlers
   logged that verbatim (observed live in the 403 line). All four Finnhub
   error sites now scrub through _redact.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _ScriptedClock:
    """time-module stand-in with scripted wall-clock reads."""

    def __init__(self, walls_s):
        self._walls = list(walls_s)

    def time(self):
        return self._walls.pop(0) if self._walls else 1_000_000.0

    def monotonic(self):
        return 0.0


def _adapter(server_ms, exchange_id):
    async def fetch_server_time():
        return server_ms
    return SimpleNamespace(
        fetch_server_time=fetch_server_time, exchange_id=exchange_id)


async def _run_fetch(monkeypatch, *, exchange_id, server_ms, walls_s):
    import core.exchange as ex
    monkeypatch.setattr(ex, "_get_adapter",
                        lambda: _adapter(server_ms, exchange_id))
    monkeypatch.setattr(ex, "time", _ScriptedClock(walls_s))
    try:
        await ex.fetch_exchange_info()
    except Exception:
        # The tail of fetch_exchange_info touches the account registry —
        # irrelevant here; the offset update happens before it.
        pass


class TestOffsetSampleGuard:
    @pytest.mark.asyncio
    async def test_fast_sample_updates_offset(self, monkeypatch):
        from core import time_sync
        # walls: before=1000.0s, after=1000.4s (400ms elapsed);
        # server stamped 1000.2s + 50ms true offset.
        await _run_fetch(
            monkeypatch, exchange_id="tsg-fast",
            server_ms=1_000_200 + 50, walls_s=[1_000.0, 1_000.4])
        assert time_sync.get_offset_ms("tsg-fast") == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_throttled_sample_is_discarded(self, monkeypatch):
        from core import time_sync
        time_sync.update("tsg-slow", 10.0)   # last good offset
        # 4,000 ms wall-to-wall (a 3.5s throttle sleep + rtt): the midpoint
        # is ~1.75s away from the real exchange — the corrupted sample would
        # have read ~ −1750ms and fired a false CRITICAL.
        await _run_fetch(
            monkeypatch, exchange_id="tsg-slow",
            server_ms=1_000_250, walls_s=[1_000.0, 1_004.0])
        assert time_sync.get_offset_ms("tsg-slow") == pytest.approx(10.0), (
            "a throttled/stalled sample must be discarded, not trusted — "
            "it fabricates multi-second drift on a healthy clock"
        )
        assert time_sync.get_status("tsg-slow").severity == "ok"

    @pytest.mark.asyncio
    async def test_boundary_sample_still_accepted(self, monkeypatch):
        from core import time_sync
        import core.exchange as ex
        lim_s = ex._OFFSET_SAMPLE_MAX_ELAPSED_MS / 1000.0
        await _run_fetch(
            monkeypatch, exchange_id="tsg-edge",
            server_ms=int((1_000.0 + lim_s / 2) * 1000) + 5,
            walls_s=[1_000.0, 1_000.0 + lim_s])
        assert time_sync.get_offset_ms("tsg-edge") == pytest.approx(5.0)


class TestFinnhubTokenRedaction:
    def test_redact_scrubs_token_param(self):
        from core.news_fetcher import _redact
        msg = ("Client error '403 Forbidden' for url 'https://finnhub.io/api/"
               "v1/calendar/economic?from=2026-06-29&token=d7mf1i9r01qsecret'")
        out = _redact(RuntimeError(msg))
        assert "d7mf1i9r01qsecret" not in out
        assert "token=***" in out
        assert "403 Forbidden" in out          # diagnostic content survives

    def test_every_finnhub_error_site_redacts(self):
        src = open(os.path.join(_ROOT, "core", "news_fetcher.py"),
                   encoding="utf-8").read()
        import re as _re
        sites = _re.findall(r'log\.error\("Finnhub[^\n]+', src)
        assert len(sites) >= 4
        for line in sites:
            assert "_redact(" in line, (
                f"Finnhub error site logs raw exception text (token leak): {line}"
            )
