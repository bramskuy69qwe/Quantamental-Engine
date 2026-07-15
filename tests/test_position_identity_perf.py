"""R2 fill-pipeline micro-benchmark (reconciler plan §6.2).

``perf``-marked → EXCLUDED from the default run (pyproject addopts
``-m 'not perf'``); run deliberately with ``-m perf``. Exists because the
corr-log perf gate (E29) measures emit/apply deltas only and structurally
CANNOT see identity-owner latency on the fill path — this is the
regression tripwire the reconciler acceptance #2 requires.

Budget calibration: the opening-fill path runs ~6-10 awaited SQL
statements + up to 3 commits on a tempfile sqlite (measured ~5-25 ms/call
on the dev box); the p50 budget of 150 ms is a LOOSE tripwire (≥5×
headroom) so OS jitter can't flake it — it exists to catch an
accidental O(N)/table-scan regression in canonical-key / migration /
retro-reconcile work (R2+), not to enforce a target.
"""
import os
import statistics
import sys
import time

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tests.linkage_battery_helpers import (  # noqa: E402
    ACCOUNT_ID,
    RECENT_MS,
    fill,
    make_real_db,
    seed_calc,
    seed_order,
)

N_FILLS = 120


@pytest_asyncio.fixture
async def real(monkeypatch):
    import config
    import core.link_actions as la
    import core.trade_event_log as tel
    from core.order_manager import OrderManager

    db, path, cleanup = await make_real_db()
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(la, "db", db)
    monkeypatch.setattr(tel, "log_trade_event", lambda *a, **k: None)
    yield OrderManager(db), db
    await cleanup()


@pytest.mark.perf
@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_process_single_fill_p50_budget(real):
    """p50 of the REAL opening-fill pipeline (matcher re-fire + enrich +
    identity owner: junction upsert, lifecycle backfills, migration scan)
    across N linked scale-in fills on one position."""
    om, db = real
    await seed_calc(db, "CALC-PERF", status="matched", window_seconds=300)
    await seed_order(db, "O-PERF", calc_id="CALC-PERF",
                     link_status="LINKED", quantity=float(N_FILLS))

    durations = []
    for i in range(N_FILLS):
        f = fill("O-PERF", "POS-PERF", 1.0, fid=f"F-PERF-{i}",
                 ts=RECENT_MS + 1000 + i)
        t0 = time.perf_counter()
        await om._process_single_fill(ACCOUNT_ID, f)
        durations.append(time.perf_counter() - t0)

    p50 = statistics.median(durations)
    # Sanity: the pipeline actually did the identity work.
    async with db._conn.execute(
        "SELECT contributed_qty FROM positions_calcs "
        "WHERE position_id = 'POS-PERF'",
    ) as cur:
        rows = await cur.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == pytest.approx(float(N_FILLS))

    assert p50 < 0.150, (
        f"fill-pipeline p50 {p50 * 1000:.1f} ms exceeds the 150 ms "
        "tripwire — an identity-owner change likely added a per-fill "
        "table scan or O(N) pass (reconciler acceptance #2)")
