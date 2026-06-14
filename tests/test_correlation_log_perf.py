"""CL.T5 (plan 5.2) — the falsifiable correlation-log performance gate.

Spec §7.7 / acceptance #5: enabling the log must not blow the hot-path
budget. This is a **wall-clock benchmark** — flaky-by-design and slow —
so it is behind the `perf` marker and EXCLUDED from the default suite
(pyproject `addopts = -m 'not perf'`). Run it deliberately:

    .venv/Scripts/python.exe -m pytest tests/test_correlation_log_perf.py -m perf

Two assertions, in increasing noise:

1. **Per-emit budget (primary, robust).** N=10k isolated `emit()` calls,
   `full` profile vs `CORR_LOG_ENABLED=0`: the enabled p95 must stay under
   the spec §7.7 budget (<50 µs) and the disabled path near-free (~the
   no-op cost). This is the stable, falsifiable signal — if someone moves
   serialization out of the writer thread, or adds heavy work to the emit
   pipeline, this fails. (Measured at authoring: enabled p95 ≈ 15 µs,
   disabled p95 ≈ 0.2 µs.)

2. **Frame→state-apply overhead < 5% (the spec headline).** The real
   `apply_position_snapshot` hot path, `full` vs disabled. Two NAMED
   deviations from the plan's literal "p95 over N=10k":
   - **p50, not p95**: a 10k-iteration wall-clock p95 is dominated by OS
     scheduler jitter on the tail (measured p95 delta swings ~8% while the
     systematic emit overhead is ~3.5%); the median isolates the real
     overhead. (X instead of Y because Z: p50 because the p95 tail is
     jitter, not emit cost.)
   - **N feasible under timeout(60), MEDIAN of rounds**: the real apply is
     ~9 ms/call (dominated by `_recalculate_portfolio`, NOT the log), so
     N=10k × 2 arms ≈ 180 s would blow `timeout(60)`. We run a smaller N
     across several rounds and take the MEDIAN round delta — robust to a
     single load spike either way WITHOUT the leniency of min-of-rounds
     (which would let a borderline regression pass on its one luckiest
     round; audit-flagged). (Measured median delta ≈ 3.5%.)

If this gate ever fails legitimately (not jitter): per spec 5.2, check
whether the writer thread's flush shows in the profile and adjust the
batch interval — the emit path itself should never touch disk.
"""

from __future__ import annotations

import asyncio
import statistics
import time

import pytest

import core.correlation_log as cl

pytestmark = pytest.mark.perf

EMIT_N = 10_000
EMIT_P95_BUDGET_US = 50.0      # spec §7.7
DISABLED_P95_BUDGET_US = 3.0   # the ~1 µs no-op + measurement overhead

APPLY_N = 400
APPLY_ROUNDS = 3              # median of 3; keeps total well under timeout(60)
APPLY_DELTA_BUDGET = 0.05      # spec acceptance #5: < 5%


def _pctile(xs, p):
    xs = sorted(xs)
    if not xs:
        return 0.0
    k = int(round((p / 100.0) * (len(xs) - 1)))
    return xs[k]


def _drain():
    while True:
        try:
            cl._queue.get_nowait()
        except Exception:
            break


@pytest.fixture(autouse=True)
def _pin(monkeypatch):
    # Run the emit pipeline fully (serialize + enqueue) but DON'T start the
    # writer thread: the queue accumulates and we drain it ourselves, so the
    # measurement is the pure emit cost (the hot-path concern) with zero
    # disk/drain interference — exactly what spec §7.7 budgets.
    _drain()
    monkeypatch.setattr(cl, "_profile", "full")
    monkeypatch.setattr(cl, "_emit_error_logged", set())
    yield
    _drain()


@pytest.mark.timeout(60)
def test_per_emit_budget(monkeypatch):
    payload = {"order_id": "E-12345", "status": "FILLED", "qty": 0.42,
               "price": 65000.0, "dedup_key": "E-12345:FILLED:0.42",
               "terminal_position_id": "POS-9", "calc_id": "CALC-1"}

    def measure(enabled):
        monkeypatch.setattr(cl, "_enabled", enabled)
        for _ in range(500):  # warm up
            cl.emit("order_manager", "binance", "in", cl.CAT_WS_ORDER_UPDATE,
                    dict(payload), account_id=1, symbol="BTCUSDT")
        _drain()
        durs = []
        for _ in range(EMIT_N):
            t0 = time.perf_counter()
            cl.emit("order_manager", "binance", "in", cl.CAT_WS_ORDER_UPDATE,
                    dict(payload), account_id=1, symbol="BTCUSDT")
            durs.append((time.perf_counter() - t0) * 1e6)
        _drain()
        return _pctile(durs, 95)

    enabled_p95 = measure(True)
    disabled_p95 = measure(False)
    assert enabled_p95 < EMIT_P95_BUDGET_US, (
        f"enabled emit p95 {enabled_p95:.1f}µs ≥ {EMIT_P95_BUDGET_US}µs budget")
    assert disabled_p95 < DISABLED_P95_BUDGET_US, (
        f"disabled emit p95 {disabled_p95:.2f}µs ≥ {DISABLED_P95_BUDGET_US}µs "
        f"— a disabled category must be ~a dict lookup")


class _StubBus:
    async def publish(self, *a, **k):
        pass

    async def publish_engine(self, *a, **k):
        pass

    def publish_engine_nowait(self, *a, **k):
        pass


@pytest.mark.timeout(60)
def test_frame_apply_overhead_under_5pct(monkeypatch):
    from core.data_cache import DataCache, UpdateSource
    from core.state import PositionInfo, app_state

    # restore app_state mutated by the applies
    acc_snap = dict(app_state.account_state.__dict__)
    pf_snap = dict(app_state.portfolio.__dict__)
    try:
        incoming = [
            PositionInfo(ticker=f"SYM{i}USDT", direction="LONG",
                         contract_amount=1.0, average=100.0, fair_price=101.0,
                         individual_unrealized=1.0, position_id=f"POS-{i}")
            for i in range(3)
        ]

        async def measure(enabled, n):
            monkeypatch.setattr(cl, "_enabled", enabled)
            cache = DataCache(_StubBus())
            for _ in range(100):  # warm up
                await cache.apply_position_snapshot(
                    UpdateSource.WS_USER, incoming, force=True)
            _drain()
            durs = []
            for _ in range(n):
                t0 = time.perf_counter()
                await cache.apply_position_snapshot(
                    UpdateSource.WS_USER, incoming, force=True)
                durs.append((time.perf_counter() - t0) * 1e6)
            _drain()
            return _pctile(durs, 50)

        # median-of-rounds: each round measures off then on close in time;
        # the median round delta is robust to a single load spike either
        # direction without the leniency of min-of-rounds.
        deltas = []
        for _ in range(APPLY_ROUNDS):
            p50_off = asyncio.run(measure(False, APPLY_N))
            p50_on = asyncio.run(measure(True, APPLY_N))
            deltas.append((p50_on - p50_off) / max(p50_off, 1e-9))
        med = statistics.median(deltas)
        assert med < APPLY_DELTA_BUDGET, (
            f"frame→state-apply p50 overhead {med * 100:.1f}% "
            f"≥ {APPLY_DELTA_BUDGET * 100:.0f}% budget (rounds={[f'{d*100:.1f}%' for d in deltas]})")
    finally:
        app_state.account_state.__dict__.update(acc_snap)
        app_state.portfolio.__dict__.update(pf_snap)
