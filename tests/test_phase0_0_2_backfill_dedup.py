"""
Phase 0.0.2 (T183) behavior tests.

Verifies that ``DatabaseManager.backfill_fills_from_exchange_history``:

1. **Dedup**: skips inserting a synthetic backfill fill when a real
   WS/REST fill for the same physical trade already exists in the
   ``fills`` table (matched by ``position_grouping.is_same_fill``).
   This closes T178 Layer 1 (synthetic-fill duplication).

2. **Grouping**: builds ``closed_positions`` rows by walking the
   accepted fills chronologically via
   ``position_grouping.group_fills_into_positions``, rather than the
   old ad-hoc ``(symbol, direction, open_time)`` grouping that could
   pull cross-position fills when ``open_time`` collided (T178
   Layer 3 contributory factor).

3. **MFE/MAE deferral**: ``mfe`` and ``mae`` on rebuilt
   ``closed_positions`` rows are 0 with ``backfill_completed=0``, so
   the reconciler re-runs them with T175's gross-PnL floor.

4. **Synthetic terminal_position_id**: format is
   ``rebuilt:{symbol}:{direction}:{entry_time_ms}`` (the helper's
   convention), deterministic across re-runs.

Run: pytest tests/test_phase0_0_2_backfill_dedup.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# Anchor timestamps inside the 365-day cutoff window
# (backfill_fills_from_exchange_history filters on ``time >=
# (now - days * 86400 * 1000)``). 2026-05-01 UTC in ms epoch.
BASE_MS = 1778025600000


@pytest_asyncio.fixture
async def test_db():
    from core.database import DatabaseManager

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    yield db
    await db.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


# ── helpers ─────────────────────────────────────────────────────────────


async def _insert_exchange_history(
    db, *, trade_key, time_ms, symbol, income_type, direction,
    entry_price=0.0, exit_price=0.0, qty=0.0, fee=0.0, income=0.0,
    open_time=0, account_id=1,
):
    """Insert one exchange_history row directly via the open connection."""
    await db._conn.execute(
        "INSERT INTO exchange_history "
        "(trade_key, time, symbol, income_type, income, direction, "
        " entry_price, exit_price, qty, open_time, fee, account_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (trade_key, time_ms, symbol, income_type, income, direction,
         entry_price, exit_price, qty, open_time, fee, account_id),
    )
    await db._conn.commit()


async def _insert_fill(
    db, *, exchange_fill_id, symbol, side, direction, price, quantity,
    is_close, timestamp_ms, source, account_id=1,
):
    """Insert one fill via the canonical upsert_fill path."""
    await db.upsert_fill({
        "account_id":           account_id,
        "exchange_fill_id":     exchange_fill_id,
        "symbol":               symbol,
        "side":                 side,
        "direction":            direction,
        "price":                price,
        "quantity":             quantity,
        "is_close":             int(is_close),
        "timestamp_ms":         timestamp_ms,
        "source":               source,
    })


async def _all_fills(db, account_id=1):
    async with db._conn.execute(
        "SELECT * FROM fills WHERE account_id=? ORDER BY timestamp_ms ASC, id ASC",
        (account_id,),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def _all_closed(db, account_id=1):
    async with db._conn.execute(
        "SELECT * FROM closed_positions WHERE account_id=? ORDER BY exit_time_ms ASC, id ASC",
        (account_id,),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


# ── 1. Dedup: synthetic vs real-fill skip ───────────────────────────────


class TestBackfillSkipsSyntheticDup:
    """T178 Layer 1: backfill produces a synthetic fill for a trade that
    a real WS/REST fill already recorded. With the new is_same_fill
    dedup, the synthetic is skipped instead of doubling the qty."""

    @pytest.mark.asyncio
    async def test_synthetic_open_dup_within_2s_skipped(self, test_db):
        # Real WS open fill at BASE_MS; exchange_history row 1500ms later
        # describing the same trade (within FILL_DEDUP_TOLERANCE_MS=2000).
        await _insert_fill(
            test_db,
            exchange_fill_id="ws-tradeId-1",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            price=80000.0, quantity=0.5, is_close=False,
            timestamp_ms=BASE_MS, source="binance_ws",
        )
        await _insert_exchange_history(
            test_db,
            trade_key="hist-trade-1",
            time_ms=BASE_MS + 1500,
            symbol="BTCUSDT",
            income_type="",          # non-REALIZED_PNL → is_close=False
            direction="LONG",
            entry_price=80000.0,
            qty=0.5,
        )
        result = await test_db.backfill_fills_from_exchange_history(
            account_id=1, days=365,
        )

        assert result["fills_inserted"] == 0, (
            "Phase 0.0.2 dedup must skip the synthetic open that matches "
            "the existing real WS fill via is_same_fill"
        )
        fills = await _all_fills(test_db)
        assert len(fills) == 1
        assert fills[0]["source"] == "binance_ws"
        assert fills[0]["exchange_fill_id"] == "ws-tradeId-1"

    @pytest.mark.asyncio
    async def test_skew_beyond_2s_treated_as_distinct(self, test_db):
        # Skew >2s → not a duplicate; both fills preserved.
        await _insert_fill(
            test_db,
            exchange_fill_id="ws-tradeId-2",
            symbol="ETHUSDT", side="BUY", direction="LONG",
            price=3000.0, quantity=1.0, is_close=False,
            timestamp_ms=BASE_MS, source="binance_ws",
        )
        await _insert_exchange_history(
            test_db,
            trade_key="hist-trade-2",
            time_ms=BASE_MS + 2001,       # 2001ms skew — over the threshold
            symbol="ETHUSDT",
            income_type="",
            direction="LONG",
            entry_price=3000.0,
            qty=1.0,
        )
        result = await test_db.backfill_fills_from_exchange_history(
            account_id=1, days=365,
        )
        assert result["fills_inserted"] == 1, (
            "Skew >2s should NOT be treated as duplicate"
        )
        fills = await _all_fills(test_db)
        assert len(fills) == 2

    @pytest.mark.asyncio
    async def test_price_mismatch_treated_as_distinct(self, test_db):
        # Two trades at the same time on the same symbol but different
        # prices are legitimately distinct. FILL_DEDUP_PRICE_TOLERANCE_PCT=0.0
        # preserves both.
        await _insert_fill(
            test_db,
            exchange_fill_id="ws-tradeId-3a",
            symbol="SOLUSDT", side="BUY", direction="LONG",
            price=150.0, quantity=2.0, is_close=False,
            timestamp_ms=BASE_MS, source="binance_ws",
        )
        await _insert_exchange_history(
            test_db,
            trade_key="hist-trade-3b",
            time_ms=BASE_MS + 500,
            symbol="SOLUSDT",
            income_type="",
            direction="LONG",
            entry_price=150.01,      # different price
            qty=2.0,
        )
        result = await test_db.backfill_fills_from_exchange_history(
            account_id=1, days=365,
        )
        assert result["fills_inserted"] == 1
        fills = await _all_fills(test_db)
        assert len(fills) == 2


# ── 2. Grouping: closed_positions via canonical helper ─────────────────


class TestBackfillUsesGroupingHelper:
    """T178 Layer 3 fix: closed_positions construction routes through
    group_fills_into_positions instead of the old (symbol, direction,
    open_time) ad-hoc grouping."""

    @pytest.mark.asyncio
    async def test_single_position_emits_one_closed_row(self, test_db):
        # OPEN fill + REALIZED_PNL close in exchange_history → one
        # closed_positions row.
        open_ts = BASE_MS
        close_ts = BASE_MS + 60_000   # 60s hold
        await _insert_exchange_history(
            test_db,
            trade_key="open-1",
            time_ms=open_ts,
            symbol="BTCUSDT",
            income_type="",          # OPEN
            direction="LONG",
            entry_price=80000.0,
            qty=0.5,
        )
        await _insert_exchange_history(
            test_db,
            trade_key="close-1",
            time_ms=close_ts,
            symbol="BTCUSDT",
            income_type="REALIZED_PNL",
            direction="LONG",
            entry_price=80000.0,
            exit_price=81000.0,
            qty=0.5,
            open_time=open_ts,
            income=500.0,
        )
        result = await test_db.backfill_fills_from_exchange_history(
            account_id=1, days=365,
        )
        assert result["fills_inserted"] == 2
        assert result["closed_inserted"] == 1

        closed = await _all_closed(test_db)
        assert len(closed) == 1
        c = closed[0]
        assert c["symbol"] == "BTCUSDT"
        assert c["direction"] == "LONG"
        assert c["quantity"] == pytest.approx(0.5)
        assert c["entry_price"] == pytest.approx(80000.0)
        assert c["exit_price"] == pytest.approx(81000.0)
        assert c["entry_time_ms"] == open_ts
        assert c["exit_time_ms"] == close_ts
        assert c["source"] == "exchange_history_backfill"

    @pytest.mark.asyncio
    async def test_terminal_position_id_uses_rebuilt_prefix(self, test_db):
        # Phase 0.0.1 (T182) introduced the `rebuilt:` synthetic ID
        # convention. The old backfill used `bf:`; Phase 0.0.2 routes
        # through the helper so the prefix changes accordingly.
        open_ts = BASE_MS
        close_ts = BASE_MS + 60_000
        await _insert_exchange_history(
            test_db,
            trade_key="open-2",
            time_ms=open_ts,
            symbol="ETHUSDT",
            income_type="",
            direction="LONG",
            entry_price=3000.0,
            qty=1.0,
        )
        await _insert_exchange_history(
            test_db,
            trade_key="close-2",
            time_ms=close_ts,
            symbol="ETHUSDT",
            income_type="REALIZED_PNL",
            direction="LONG",
            entry_price=3000.0,
            exit_price=3100.0,
            qty=1.0,
            open_time=open_ts,
            income=100.0,
        )
        await test_db.backfill_fills_from_exchange_history(
            account_id=1, days=365,
        )
        closed = await _all_closed(test_db)
        assert len(closed) == 1
        assert closed[0]["terminal_position_id"] == f"rebuilt:ETHUSDT:LONG:{open_ts}"

    @pytest.mark.asyncio
    async def test_idempotent_across_reruns(self, test_db):
        # Running backfill twice over the same exchange_history rows
        # produces the same number of closed_positions (not double).
        open_ts = BASE_MS
        close_ts = BASE_MS + 60_000
        await _insert_exchange_history(
            test_db,
            trade_key="open-3",
            time_ms=open_ts,
            symbol="BNBUSDT",
            income_type="",
            direction="LONG",
            entry_price=500.0,
            qty=2.0,
        )
        await _insert_exchange_history(
            test_db,
            trade_key="close-3",
            time_ms=close_ts,
            symbol="BNBUSDT",
            income_type="REALIZED_PNL",
            direction="LONG",
            entry_price=500.0,
            exit_price=510.0,
            qty=2.0,
            open_time=open_ts,
            income=20.0,
        )
        await test_db.backfill_fills_from_exchange_history(
            account_id=1, days=365,
        )
        closed_first = await _all_closed(test_db)
        await test_db.backfill_fills_from_exchange_history(
            account_id=1, days=365,
        )
        closed_second = await _all_closed(test_db)
        assert len(closed_first) == 1
        assert len(closed_second) == 1, (
            "rerunning backfill must be idempotent — same logical position "
            "gets the same terminal_position_id (rebuilt:...) so the UNIQUE "
            "constraint dedups via REPLACE"
        )

    @pytest.mark.asyncio
    async def test_hedge_mode_emits_two_records(self, test_db):
        # Simultaneous LONG + SHORT on the same symbol must produce two
        # distinct closed_positions rows. The helper's per-direction
        # state tracking handles this correctly.
        open_long_ts = BASE_MS
        open_short_ts = BASE_MS + 500
        close_long_ts = BASE_MS + 60_000
        close_short_ts = BASE_MS + 60_500
        for trade_key, time_ms, side_dir, income_type, entry_p, exit_p, qty, open_t, income in [
            ("o-l", open_long_ts,   "LONG",  "",             100.0,   0.0, 1.0,        0,            0.0),
            ("o-s", open_short_ts,  "SHORT", "",             105.0,   0.0, 1.0,        0,            0.0),
            ("c-l", close_long_ts,  "LONG",  "REALIZED_PNL", 100.0, 110.0, 1.0, open_long_ts,        10.0),
            ("c-s", close_short_ts, "SHORT", "REALIZED_PNL", 105.0,  95.0, 1.0, open_short_ts,       10.0),
        ]:
            await _insert_exchange_history(
                test_db, trade_key=trade_key, time_ms=time_ms,
                symbol="HEDGUSDT", income_type=income_type, direction=side_dir,
                entry_price=entry_p, exit_price=exit_p, qty=qty,
                open_time=open_t, income=income,
            )
        await test_db.backfill_fills_from_exchange_history(
            account_id=1, days=365,
        )
        closed = await _all_closed(test_db)
        assert len(closed) == 2
        dirs = {c["direction"] for c in closed}
        assert dirs == {"LONG", "SHORT"}


# ── 3. MFE/MAE deferred to reconciler ──────────────────────────────────


class TestBackfillDefersMfeMaeToReconciler:
    """Phase 0.0.2 stops carrying mfe/mae from exchange_history rows.
    Helper emits 0.0/0.0 with backfill_completed=0 so the reconciler
    re-runs them with T175's gross-PnL floor."""

    @pytest.mark.asyncio
    async def test_backfill_inserts_with_zero_mfe_mae_and_unflagged(self, test_db):
        open_ts = BASE_MS
        close_ts = BASE_MS + 60_000
        await _insert_exchange_history(
            test_db,
            trade_key="open-mfe",
            time_ms=open_ts,
            symbol="ADAUSDT",
            income_type="",
            direction="LONG",
            entry_price=1.0,
            qty=100.0,
        )
        await _insert_exchange_history(
            test_db,
            trade_key="close-mfe",
            time_ms=close_ts,
            symbol="ADAUSDT",
            income_type="REALIZED_PNL",
            direction="LONG",
            entry_price=1.0,
            exit_price=1.10,
            qty=100.0,
            open_time=open_ts,
            income=10.0,
        )
        await test_db.backfill_fills_from_exchange_history(
            account_id=1, days=365,
        )
        closed = await _all_closed(test_db)
        assert len(closed) == 1
        c = closed[0]
        assert c["mfe"] == 0.0
        assert c["mae"] == 0.0
        assert c["backfill_completed"] == 0, (
            "Reconciler must re-run on rebuilt rows (T175 floor applies)"
        )
