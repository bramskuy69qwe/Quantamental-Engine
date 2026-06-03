"""
Phase 6 (P6.T6) — position:size_drift + the snapshot-wins-drift inversion.

The RISKIEST Phase-6 change: it inverts data_cache's WS-fills-win-within-5s
position conflict policy. Gated behind config_json.feature_flags.snapshot_wins_drift
(default OFF) so flag-off is PROVABLY zero behaviour change.

Audit-driven design (P6.T6 review): the config is read OFF the lock and passed
into the SYNCHRONOUS decision helper `_apply_snapshot_wins_inversion`, so
self._lock is never held across a DB await (the DataCache single-writer invariant).

Three layers:
  - Unit (TestSnapshotWinsInversion): drive the isolated sync decision helper
    directly — the load-bearing risky logic (accept verdict + drift payloads).
  - Safe-default (TestReadDriftConfigSafeDefault): _read_drift_config defaults
    to flag-OFF on any read error.
  - E2E (TestApplySnapshotInversionE2E): drive the real apply_position_snapshot
    so a REST snapshot within the WS window is accepted (flag ON) / rejected
    (flag OFF) and position:size_drift fires accordingly.

Run: pytest tests/test_phase6_size_drift.py -v
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.data_cache import DataCache, UpdateSource  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.state import PositionInfo  # noqa: E402


@pytest.fixture
def dc():
    return DataCache(EventBus())


def _pos(ticker, direction, size, pid="P1"):
    return PositionInfo(position_id=pid, ticker=ticker, direction=direction,
                        contract_amount=size)


def _accfg(*, on, tol=0.5):
    """An AccountConfig with the snapshot-drift flag/tolerance (passed into the
    sync helper directly — the caller reads it off-lock in production)."""
    from core.account_config import AccountConfig
    return AccountConfig(snapshot_wins_drift=on, snapshot_drift_tolerance_pct=tol)


def _async_cfg(*, on, tol=0.5):
    """An async stub for monkeypatching _read_drift_config in the e2e tests."""
    async def _f():
        return _accfg(on=on, tol=tol)
    return _f


def _drain(dc):
    out = []
    while not dc._event_bus._queue.empty():
        out.append(dc._event_bus._queue.get_nowait())
    return out


# ── 1. The isolated inversion decision (sync; the risky logic) ────────────────


class TestSnapshotWinsInversion:
    def test_already_accepted_is_noop(self, dc):
        # base_accept True (WS/Platform/outside-window/force) → never touched.
        accept, drifts = dc._apply_snapshot_wins_inversion(
            UpdateSource.REST, [_pos("BTCUSDT", "LONG", 3.0)], True, _accfg(on=True))
        assert accept is True and drifts == []

    def test_non_rest_source_unchanged(self, dc):
        # Only REST rejections are inverted (the WS-fills-win-within-5s policy).
        accept, drifts = dc._apply_snapshot_wins_inversion(
            UpdateSource.WS_USER, [_pos("BTCUSDT", "LONG", 3.0)], False, _accfg(on=True))
        assert accept is False and drifts == []

    def test_flag_off_rest_stays_rejected(self, dc):
        # Default OFF → the rejected REST snapshot stays rejected, no drift.
        dc._positions = [_pos("BTCUSDT", "LONG", 2.0)]
        accept, drifts = dc._apply_snapshot_wins_inversion(
            UpdateSource.REST, [_pos("BTCUSDT", "LONG", 3.0)], False, _accfg(on=False))
        assert accept is False and drifts == []

    def test_no_cfg_rest_stays_rejected(self, dc):
        # cfg None (production passes None for non-REST/force) → unchanged.
        dc._positions = [_pos("BTCUSDT", "LONG", 2.0)]
        accept, drifts = dc._apply_snapshot_wins_inversion(
            UpdateSource.REST, [_pos("BTCUSDT", "LONG", 3.0)], False, None)
        assert accept is False and drifts == []

    def test_flag_on_inverts_and_reports_drift(self, dc):
        dc._positions = [_pos("BTCUSDT", "LONG", 2.0)]
        accept, drifts = dc._apply_snapshot_wins_inversion(
            UpdateSource.REST, [_pos("BTCUSDT", "LONG", 3.0)], False, _accfg(on=True, tol=0.5))
        assert accept is True                  # inversion: snapshot wins
        assert len(drifts) == 1
        d = drifts[0]
        assert d["position_id"] == "P1"
        assert d["fill_derived_size"] == 2.0
        assert d["snapshot_size"] == 3.0
        assert d["delta"] == pytest.approx(1.0)

    def test_flag_on_within_tolerance_accepts_but_no_drift(self, dc):
        # 2.0 → 2.005 = 0.25% < 0.5% tolerance: snapshot still wins (authoritative)
        # but NO drift event (the disagreement is below tolerance).
        dc._positions = [_pos("BTCUSDT", "LONG", 2.0)]
        accept, drifts = dc._apply_snapshot_wins_inversion(
            UpdateSource.REST, [_pos("BTCUSDT", "LONG", 2.005)], False, _accfg(on=True, tol=0.5))
        assert accept is True
        assert drifts == []

    def test_flag_on_new_position_no_drift(self, dc):
        # A snapshot position not currently held → no current size to compare.
        dc._positions = []
        accept, drifts = dc._apply_snapshot_wins_inversion(
            UpdateSource.REST, [_pos("BTCUSDT", "LONG", 3.0)], False, _accfg(on=True))
        assert accept is True and drifts == []

    def test_flag_on_multi_position_only_drifting_reported(self, dc):
        # Audit Finding D: with several held positions, ONLY the position(s)
        # exceeding tolerance produce a drift dict (the per-position loop).
        dc._positions = [_pos("BTCUSDT", "LONG", 2.0, "PB"),
                         _pos("ETHUSDT", "LONG", 10.0, "PE")]
        incoming = [_pos("BTCUSDT", "LONG", 3.0, "PB"),        # +50% → drift
                    _pos("ETHUSDT", "LONG", 10.005, "PE")]     # +0.05% < tol → no drift
        accept, drifts = dc._apply_snapshot_wins_inversion(
            UpdateSource.REST, incoming, False, _accfg(on=True, tol=0.5))
        assert accept is True
        assert len(drifts) == 1
        assert drifts[0]["position_id"] == "PB"
        assert drifts[0]["snapshot_size"] == 3.0


# ── 2. _read_drift_config safe default ────────────────────────────────────────


class TestReadDriftConfigSafeDefault:
    @pytest.mark.asyncio
    async def test_defaults_off_on_read_error(self, dc, monkeypatch):
        # Any read error (e.g. db unavailable) → flag OFF, so the inversion stays
        # safely disabled. _read_drift_config lazy-imports read_account_config_async,
        # so patching the module attribute binds the fake at call time.
        import core.account_config as ac

        async def _boom(db, account_id):
            raise RuntimeError("db down")

        monkeypatch.setattr(ac, "read_account_config_async", _boom)
        cfg = await dc._read_drift_config()
        assert cfg.snapshot_wins_drift is False


# ── 3. End-to-end through apply_position_snapshot ─────────────────────────────


class TestApplySnapshotInversionE2E:
    @pytest.mark.asyncio
    async def test_flag_off_rest_within_window_rejected_no_event(self, dc, monkeypatch):
        # Isolate the drift logic from portfolio recalc (orthogonal + needs app_state).
        monkeypatch.setattr(dc, "_recalculate_portfolio", lambda: None)
        # Seed current = WS at ts=1000 (size 2.0).
        await dc.apply_position_snapshot(
            UpdateSource.WS_USER, [_pos("BTCUSDT", "LONG", 2.0)], ts_ms=1000)
        _drain(dc)
        monkeypatch.setattr(dc, "_read_drift_config", _async_cfg(on=False))
        # REST within the 5s window (ts=1500), disagreeing size.
        res = await dc.apply_position_snapshot(
            UpdateSource.REST, [_pos("BTCUSDT", "LONG", 3.0)], ts_ms=1500)
        assert res is None                              # rejected (unchanged)
        assert dc.positions[0].contract_amount == 2.0   # WS size preserved
        assert not any(c.endswith(":position:size_drift") for c, _ in _drain(dc))

    @pytest.mark.asyncio
    async def test_flag_on_rest_within_window_accepted_and_emits(self, dc, monkeypatch):
        monkeypatch.setattr(dc, "_recalculate_portfolio", lambda: None)
        await dc.apply_position_snapshot(
            UpdateSource.WS_USER, [_pos("BTCUSDT", "LONG", 2.0)], ts_ms=1000)
        _drain(dc)
        monkeypatch.setattr(dc, "_read_drift_config", _async_cfg(on=True, tol=0.5))
        res = await dc.apply_position_snapshot(
            UpdateSource.REST, [_pos("BTCUSDT", "LONG", 3.0)], ts_ms=1500)
        assert res is not None                          # accepted (inversion)
        assert dc.positions[0].contract_amount == 3.0   # snapshot size won
        drift = [(c, p) for c, p in _drain(dc)
                 if c.endswith(":position:size_drift")]
        assert len(drift) == 1
        _, p = drift[0]
        assert p["fill_derived_size"] == 2.0
        assert p["snapshot_size"] == 3.0
        assert p["delta"] == pytest.approx(1.0)
