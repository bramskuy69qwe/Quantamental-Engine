"""P5-R1 pins — the final-close safety net is wired to the close signal.

Filed (phase-5 ledger): the REST reconcile fill path inserts fills but never
schedules the close-row build — it silently became the de-facto fill source
when the user-data WS died (zero closed_positions rows across two live-trading
days). Investigated mechanism: closed_positions rows were built EXCLUSIVELY by
the WS fill path (`process_fill` -> call_later -> `_build_close_row_for_fill`;
sole production caller `ws_manager.py`), while the purpose-built backstop
`OrderManager.build_final_close_row` — force_final-aware, deduped via
`get_unrecorded_closing_fills` — had NO production caller at all.

The fix wires it to the authoritative close signal (`CH_TRADE_CLOSED`,
published by DataCache on position disappearance for BOTH the REST snapshot
and the WS incremental paths), widened to carry `position_id`. The handler
also REST-fetches the closed symbol's recent fills first, because the refresh
loop's fill sync iterates OPEN positions only — a closed symbol's final fills
would otherwise never be fetched once the position leaves the snapshot.

All stubs — no live engine, no TestClient, no real adapter.
"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.data_cache import DataCache, UpdateSource  # noqa: E402
from core.event_bus import CH_TRADE_CLOSED, EventBus  # noqa: E402
from core.state import PositionInfo, app_state  # noqa: E402
from core.schedulers import _trade_closed_final_row_work  # noqa: E402


def _drain(dc):
    out = []
    while not dc._event_bus._queue.empty():
        out.append(dc._event_bus._queue.get_nowait()[:2])
    return out


# ── 1. The close signal carries the identity (both detection paths) ──────────


class TestCloseSignalCarriesIdentity:
    @pytest.mark.asyncio
    async def test_rest_snapshot_close_publishes_position_id(self, monkeypatch):
        dc = DataCache(EventBus())
        monkeypatch.setattr(dc, "_recalculate_portfolio", lambda: None)
        pos = PositionInfo(position_id="tp-777", ticker="SOLUSDT",
                           direction="LONG", contract_amount=1.0)
        await dc.apply_position_snapshot(UpdateSource.REST, [pos], ts_ms=1000)
        _drain(dc)  # discard the seed events

        await dc.apply_position_snapshot(
            UpdateSource.REST, [], ts_ms=200_000, force=True)
        events = _drain(dc)
        closed = [p for ch, p in events if ch == CH_TRADE_CLOSED]
        assert len(closed) == 1
        assert closed[0]["ticker"] == "SOLUSDT"
        assert closed[0]["direction"] == "LONG"
        assert closed[0]["position_id"] == "tp-777"

    @pytest.mark.asyncio
    async def test_empty_tpid_travels_verbatim(self, monkeypatch):
        # The stranded-identity shape (one-way mode): "" must ride, not vanish
        # — build_final_close_row's empty-tpid walk branch handles it.
        dc = DataCache(EventBus())
        monkeypatch.setattr(dc, "_recalculate_portfolio", lambda: None)
        pos = PositionInfo(position_id="", ticker="ETHUSDT",
                           direction="SHORT", contract_amount=0.5)
        await dc.apply_position_snapshot(UpdateSource.REST, [pos], ts_ms=1000)
        _drain(dc)
        await dc.apply_position_snapshot(
            UpdateSource.REST, [], ts_ms=200_000, force=True)
        closed = [p for ch, p in _drain(dc) if ch == CH_TRADE_CLOSED]
        assert closed and closed[0]["position_id"] == ""


# ── 2. The backstop work function ────────────────────────────────────────────


def _fake_trade(fid="f1", symbol="SOLUSDT"):
    return SimpleNamespace(
        exchange_fill_id=fid, terminal_fill_id="", exchange_order_id="o1",
        symbol=symbol, side="SELL", direction="LONG", price=71.0,
        quantity=1.0, fee=0.02, fee_asset="USDT", terminal_position_id="",
        is_close=True, realized_pnl=1.0, role="taker", timestamp_ms=123_456,
    )


class _Recorder:
    def __init__(self):
        self.upserts = []
        self.built = []

    async def upsert_fill(self, row):
        self.upserts.append(row)

    async def build_final_close_row(self, prev):
        self.built.append(prev)


@pytest.fixture
def wired(monkeypatch):
    rec = _Recorder()
    fake_adapter = SimpleNamespace(
        fetch_user_trades=lambda symbol, limit=50: _aret([_fake_trade(symbol=symbol)]),
    )
    import core.exchange as ex
    import core.database as cdb
    import core.order_manager_singleton as oms
    monkeypatch.setattr(ex, "_get_adapter", lambda: fake_adapter)
    monkeypatch.setattr(cdb.db, "upsert_fill", rec.upsert_fill)
    monkeypatch.setattr(
        oms, "order_manager",
        SimpleNamespace(build_final_close_row=rec.build_final_close_row))
    # not rate-limited (None; the property compares datetimes)
    monkeypatch.setattr(app_state.ws_status, "rate_limited_until", None)
    return rec


def _aret(value):
    f = asyncio.get_event_loop().create_future()
    f.set_result(value)
    return f


class TestBackstopWork:
    @pytest.mark.asyncio
    async def test_fetches_fills_then_builds(self, wired):
        await _trade_closed_final_row_work(
            {"ticker": "SOLUSDT", "direction": "LONG", "position_id": "tp-1"})
        assert len(wired.upserts) == 1
        u = wired.upserts[0]
        assert u["symbol"] == "SOLUSDT"
        assert u["source"].endswith("_rest")
        assert u["is_close"] == 1
        assert len(wired.built) == 1
        prev = wired.built[0]
        assert (prev.position_id, prev.ticker, prev.direction) == \
            ("tp-1", "SOLUSDT", "LONG")

    @pytest.mark.asyncio
    async def test_rate_limited_skips_fetch_but_still_builds(
            self, wired, monkeypatch):
        from datetime import datetime, timedelta, timezone
        monkeypatch.setattr(
            app_state.ws_status, "rate_limited_until",
            datetime.now(timezone.utc) + timedelta(minutes=10))
        await _trade_closed_final_row_work(
            {"ticker": "SOLUSDT", "direction": "LONG", "position_id": "tp-1"})
        assert wired.upserts == []          # no REST spend while limited
        assert len(wired.built) == 1        # the builder still runs

    @pytest.mark.asyncio
    async def test_fetch_failure_still_builds(self, wired, monkeypatch):
        import core.exchange as ex

        def _boom():
            raise RuntimeError("adapter down")

        monkeypatch.setattr(ex, "_get_adapter", _boom)
        await _trade_closed_final_row_work(
            {"ticker": "SOLUSDT", "direction": "LONG", "position_id": "tp-1"})
        assert wired.upserts == []
        assert len(wired.built) == 1        # fail-loud, never fail-silent

    @pytest.mark.asyncio
    async def test_blank_payload_is_a_noop(self, wired):
        await _trade_closed_final_row_work({"ticker": "", "direction": ""})
        assert wired.upserts == [] and wired.built == []


# ── 3. The subscription exists (source pin) ──────────────────────────────────


class TestSubscriptionWired:
    def test_backstop_subscribed_to_trade_closed(self):
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)),
                         "core", "schedulers.py"),
            encoding="utf-8",
        ).read()
        assert "event_bus.subscribe(CH_TRADE_CLOSED, _on_trade_closed_final_row)" in src, (
            "P5-R1 regressed: build_final_close_row's only trigger is the "
            "CH_TRADE_CLOSED subscription in start_background_tasks"
        )
