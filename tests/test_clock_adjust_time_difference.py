"""
v3.0 clock-drift auto-fix — CCXT adjustForTimeDifference (operator opt-in).

Makes the engine resilient to an unsynced OS clock: CCXT offsets every SIGNED
request's timestamp by the measured server-time difference, so a local clock
>1000ms AHEAD stops tripping Binance -1021 and account/funding/positions reads
keep working. Safe under the observe-only architecture (every signed request
is a READ; the engine places no orders).

ccxt constructors make no network calls, so we construct real instances and
inspect their `options` directly — no mocking, no HTTP.
"""
from __future__ import annotations

from core.exchange_factory import _make_ccxt_instance


class TestAdjustForTimeDifferenceEnabled:
    def test_binance_future_enables_adjust(self):
        ex = _make_ccxt_instance("k", "s", "binance", "future")
        assert ex.options.get("adjustForTimeDifference") is True

    def test_binance_spot_enables_adjust(self):
        ex = _make_ccxt_instance("k", "s", "binance", "spot")
        assert ex.options.get("adjustForTimeDifference") is True

    def test_option_does_not_disturb_existing_options(self):
        """The pre-existing options that keep load_markets reachable behind the
        fapi-only proxy must survive alongside the new one."""
        ex = _make_ccxt_instance("k", "s", "binance", "future")
        assert ex.options.get("fetchCurrencies") is False
        assert ex.options.get("defaultType") == "future"

    def test_source_pin_names_observe_only_safety(self):
        """The safety rationale (read-only signed requests) must stay in the
        source so a future editor doesn't strip it as 'unused'."""
        import inspect
        from core import exchange_factory
        src = inspect.getsource(exchange_factory._make_ccxt_instance)
        assert "adjustForTimeDifference" in src
        assert "observe-only" in src.lower()
        assert "-1021" in src
