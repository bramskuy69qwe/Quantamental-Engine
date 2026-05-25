"""
Phase 0.0.5 (T188) tests — close-row builder uses position_grouping
instead of the broken (symbol, direction) fallback.

Closes T178 Layer 3 in the live close-row build path. Two changes:

  1. ``core/db_orders.py::get_position_fills`` is now STRICT. Empty
     ``pos_id`` returns [] instead of falling back to the
     ``(COALESCE(terminal_position_id, '') = '' AND symbol=? AND
     direction=?)`` arm that returned opens from MULTIPLE distinct
     positions over time.

  2. ``core/order_manager.py::_build_close_row_for_fill`` uses
     ``core.position_grouping.find_opens_for_position_close_at`` to
     resolve opens when ``pos_id`` is empty (Binance one-way path).
     The helper walks fills chronologically per
     (account, symbol, direction) and returns the opens for the
     position closing at the given timestamp.

Run: pytest tests/test_phase0_0_5_close_row_grouping.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.position_grouping import find_opens_for_position_close_at


BASE_MS = 1778025600000   # 2026-05-01 UTC


def _fill(
    *, id: int, ts: int, is_close: int = 0,
    symbol: str = "BTCUSDT", direction: str = "LONG",
    price: float = 100.0, quantity: float = 1.0,
    account_id: int = 1, side: str = "BUY",
    exchange_fill_id: str = "",
):
    return {
        "id":               id,
        "account_id":       account_id,
        "exchange_fill_id": exchange_fill_id or f"fid-{id}",
        "symbol":           symbol,
        "side":             side,
        "direction":        direction,
        "price":            price,
        "quantity":         quantity,
        "is_close":         is_close,
        "timestamp_ms":     ts,
    }


# ── 1. find_opens_for_position_close_at ─────────────────────────────────


class TestFindOpensSinglePosition:
    def test_single_open_then_close_returns_one_open(self):
        fills = [
            _fill(id=1, ts=BASE_MS,        is_close=0, quantity=2.0, price=100.0),
            _fill(id=2, ts=BASE_MS+60_000, is_close=1, quantity=2.0, price=110.0,
                  side="SELL"),
        ]
        opens = find_opens_for_position_close_at(
            fills, account_id=1, symbol="BTCUSDT", direction="LONG",
            close_ts_ms=BASE_MS + 60_000,
        )
        assert len(opens) == 1
        assert opens[0]["id"] == 1

    def test_scale_in_opens_all_returned(self):
        # 2 opens (scale-in) then 1 full close. Both opens returned.
        fills = [
            _fill(id=1, ts=BASE_MS,         is_close=0, quantity=1.0, price=100.0),
            _fill(id=2, ts=BASE_MS+10_000,  is_close=0, quantity=3.0, price=110.0),
            _fill(id=3, ts=BASE_MS+60_000,  is_close=1, quantity=4.0, price=120.0,
                  side="SELL"),
        ]
        opens = find_opens_for_position_close_at(
            fills, account_id=1, symbol="BTCUSDT", direction="LONG",
            close_ts_ms=BASE_MS + 60_000,
        )
        assert [o["id"] for o in opens] == [1, 2]


class TestFindOpensPartialCloseStillReturnsActiveOpens:
    """When the target close is a PARTIAL close (qty not fully reduced),
    the position is still open. Helper returns the active opens — they
    haven't been retired yet."""

    def test_partial_close_returns_current_opens(self):
        # Open 4, partial-close 1. Target is the partial close.
        fills = [
            _fill(id=1, ts=BASE_MS,         is_close=0, quantity=4.0, price=100.0),
            _fill(id=2, ts=BASE_MS+30_000,  is_close=1, quantity=1.0, price=110.0,
                  side="SELL"),
        ]
        opens = find_opens_for_position_close_at(
            fills, account_id=1, symbol="BTCUSDT", direction="LONG",
            close_ts_ms=BASE_MS + 30_000,
        )
        # Position still has 3 qty open — the active opens are the one open
        # fill (the qty has been reduced but not retired).
        assert [o["id"] for o in opens] == [1]


class TestFindOpensCrossPositionExclusion:
    """T178 Layer 3 regression guard: opens from an EARLIER position
    that already closed must NOT contaminate the result for a LATER
    position."""

    def test_prior_position_opens_excluded(self):
        # Position A: open at t=0, close at t=60k.
        # Position B: open at t=120k, close at t=180k.
        # Query target: B's close. Only B's open should be returned.
        fills = [
            _fill(id=1, ts=BASE_MS,          is_close=0, quantity=2.0, price=100.0),  # A open
            _fill(id=2, ts=BASE_MS+60_000,   is_close=1, quantity=2.0, price=110.0,
                  side="SELL"),                                                       # A close
            _fill(id=3, ts=BASE_MS+120_000,  is_close=0, quantity=1.0, price=120.0),  # B open
            _fill(id=4, ts=BASE_MS+180_000,  is_close=1, quantity=1.0, price=130.0,
                  side="SELL"),                                                       # B close
        ]
        opens = find_opens_for_position_close_at(
            fills, account_id=1, symbol="BTCUSDT", direction="LONG",
            close_ts_ms=BASE_MS + 180_000,
        )
        # Only B's open (id=3) returned. Pre-T188 fallback would have
        # mixed both opens, producing nonsense VWAP entry_price.
        assert [o["id"] for o in opens] == [3]


class TestFindOpensFilterScope:
    def test_other_symbols_ignored(self):
        fills = [
            _fill(id=1, ts=BASE_MS, is_close=0, symbol="ETHUSDT"),
            _fill(id=2, ts=BASE_MS, is_close=0, symbol="BTCUSDT"),
        ]
        opens = find_opens_for_position_close_at(
            fills, account_id=1, symbol="BTCUSDT", direction="LONG",
            close_ts_ms=BASE_MS + 1000,
        )
        # Only BTCUSDT open returned — the active LONG that hasn't closed.
        assert [o["id"] for o in opens] == [2]

    def test_other_directions_ignored(self):
        fills = [
            _fill(id=1, ts=BASE_MS, is_close=0, direction="SHORT", side="SELL"),
            _fill(id=2, ts=BASE_MS, is_close=0, direction="LONG", side="BUY"),
        ]
        opens = find_opens_for_position_close_at(
            fills, account_id=1, symbol="BTCUSDT", direction="LONG",
            close_ts_ms=BASE_MS + 1000,
        )
        assert [o["id"] for o in opens] == [2]

    def test_other_accounts_ignored(self):
        fills = [
            _fill(id=1, ts=BASE_MS, is_close=0, account_id=2),
            _fill(id=2, ts=BASE_MS, is_close=0, account_id=1),
        ]
        opens = find_opens_for_position_close_at(
            fills, account_id=1, symbol="BTCUSDT", direction="LONG",
            close_ts_ms=BASE_MS + 1000,
        )
        assert [o["id"] for o in opens] == [2]

    def test_fills_after_close_ts_excluded(self):
        # A later open shouldn't affect the result.
        fills = [
            _fill(id=1, ts=BASE_MS,         is_close=0, quantity=1.0),
            _fill(id=2, ts=BASE_MS+30_000,  is_close=1, quantity=1.0, side="SELL"),
            _fill(id=3, ts=BASE_MS+60_000,  is_close=0, quantity=2.0),   # later open
        ]
        opens = find_opens_for_position_close_at(
            fills, account_id=1, symbol="BTCUSDT", direction="LONG",
            close_ts_ms=BASE_MS + 30_000,
        )
        # The target close at BASE_MS+30_000 retires the position with
        # open id=1. id=3 is past the close ts → excluded.
        assert [o["id"] for o in opens] == [1]


class TestFindOpensEmptyCases:
    def test_empty_fills_returns_empty(self):
        opens = find_opens_for_position_close_at(
            [], account_id=1, symbol="BTCUSDT", direction="LONG",
            close_ts_ms=BASE_MS,
        )
        assert opens == []

    def test_only_close_no_prior_open_returns_empty(self):
        fills = [
            _fill(id=1, ts=BASE_MS, is_close=1, quantity=1.0, side="SELL"),
        ]
        opens = find_opens_for_position_close_at(
            fills, account_id=1, symbol="BTCUSDT", direction="LONG",
            close_ts_ms=BASE_MS,
        )
        # No prior open → no opens to return.
        assert opens == []


# ── 2. get_position_fills strict mode ───────────────────────────────────


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


async def _seed_fill_via_db(
    db, *, exchange_fill_id, symbol, direction, side,
    quantity, price, is_close, timestamp_ms,
    terminal_position_id="", account_id=1,
):
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
        "terminal_position_id": terminal_position_id,
    })


class TestGetPositionFillsStrict:
    @pytest.mark.asyncio
    async def test_empty_pos_id_returns_empty(self, test_db):
        # Pre-T188 this returned all fills for (symbol, direction).
        await _seed_fill_via_db(
            test_db,
            exchange_fill_id="fid-1",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=1.0, price=100.0, is_close=False,
            timestamp_ms=BASE_MS,
            terminal_position_id="",
        )
        result = await test_db.get_position_fills(
            1, "", "BTCUSDT", "LONG",
        )
        assert result == [], (
            "Phase 0.0.5: empty pos_id must return [] — no fallback "
            "to (symbol, direction). T178 Layer 3 cross-position "
            "contamination is closed."
        )

    @pytest.mark.asyncio
    async def test_non_empty_pos_id_matches_strictly(self, test_db):
        # Two fills with different terminal_position_ids on the same
        # (symbol, direction). The strict match returns only the one
        # whose pos_id was queried.
        await _seed_fill_via_db(
            test_db,
            exchange_fill_id="fid-1",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=1.0, price=100.0, is_close=False,
            timestamp_ms=BASE_MS,
            terminal_position_id="pos-A",
        )
        await _seed_fill_via_db(
            test_db,
            exchange_fill_id="fid-2",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=2.0, price=110.0, is_close=False,
            timestamp_ms=BASE_MS + 1_000,
            terminal_position_id="pos-B",
        )
        result_a = await test_db.get_position_fills(
            1, "pos-A", "BTCUSDT", "LONG",
        )
        assert [f["exchange_fill_id"] for f in result_a] == ["fid-1"]

        result_b = await test_db.get_position_fills(
            1, "pos-B", "BTCUSDT", "LONG",
        )
        assert [f["exchange_fill_id"] for f in result_b] == ["fid-2"]

    @pytest.mark.asyncio
    async def test_is_close_filter_still_applied(self, test_db):
        await _seed_fill_via_db(
            test_db,
            exchange_fill_id="open-1",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=1.0, price=100.0, is_close=False,
            timestamp_ms=BASE_MS,
            terminal_position_id="pos-1",
        )
        await _seed_fill_via_db(
            test_db,
            exchange_fill_id="close-1",
            symbol="BTCUSDT", side="SELL", direction="LONG",
            quantity=1.0, price=110.0, is_close=True,
            timestamp_ms=BASE_MS + 1_000,
            terminal_position_id="pos-1",
        )
        opens = await test_db.get_position_fills(
            1, "pos-1", "BTCUSDT", "LONG", is_close=False,
        )
        assert [f["exchange_fill_id"] for f in opens] == ["open-1"]
        closes = await test_db.get_position_fills(
            1, "pos-1", "BTCUSDT", "LONG", is_close=True,
        )
        assert [f["exchange_fill_id"] for f in closes] == ["close-1"]


# ── 3. get_fills_for_symbol_direction ───────────────────────────────────


class TestGetFillsForSymbolDirection:
    @pytest.mark.asyncio
    async def test_returns_chronological(self, test_db):
        for ts in (BASE_MS + 2_000, BASE_MS, BASE_MS + 1_000):
            await _seed_fill_via_db(
                test_db,
                exchange_fill_id=f"fid-{ts}",
                symbol="BTCUSDT", side="BUY", direction="LONG",
                quantity=1.0, price=100.0, is_close=False,
                timestamp_ms=ts,
            )
        rows = await test_db.get_fills_for_symbol_direction(
            1, "BTCUSDT", "LONG",
        )
        assert [r["timestamp_ms"] for r in rows] == [
            BASE_MS, BASE_MS + 1_000, BASE_MS + 2_000,
        ]

    @pytest.mark.asyncio
    async def test_filters_by_symbol(self, test_db):
        await _seed_fill_via_db(
            test_db,
            exchange_fill_id="btc-1",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=1.0, price=100.0, is_close=False,
            timestamp_ms=BASE_MS,
        )
        await _seed_fill_via_db(
            test_db,
            exchange_fill_id="eth-1",
            symbol="ETHUSDT", side="BUY", direction="LONG",
            quantity=1.0, price=3000.0, is_close=False,
            timestamp_ms=BASE_MS,
        )
        rows = await test_db.get_fills_for_symbol_direction(
            1, "BTCUSDT", "LONG",
        )
        assert [r["exchange_fill_id"] for r in rows] == ["btc-1"]

    @pytest.mark.asyncio
    async def test_since_ms_filter(self, test_db):
        for offset in (0, 60_000, 120_000):
            await _seed_fill_via_db(
                test_db,
                exchange_fill_id=f"fid-{offset}",
                symbol="BTCUSDT", side="BUY", direction="LONG",
                quantity=1.0, price=100.0, is_close=False,
                timestamp_ms=BASE_MS + offset,
            )
        rows = await test_db.get_fills_for_symbol_direction(
            1, "BTCUSDT", "LONG", since_ms=BASE_MS + 30_000,
        )
        # Only the 60_000 and 120_000 fills.
        assert [r["timestamp_ms"] for r in rows] == [
            BASE_MS + 60_000, BASE_MS + 120_000,
        ]


# ── 4. End-to-end _build_close_row_for_fill (T189 audit L2 + L3) ────────


async def _all_closed(db, account_id=1):
    async with db._conn.execute(
        "SELECT * FROM closed_positions WHERE account_id=? ORDER BY id ASC",
        (account_id,),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


class TestBuildCloseRowEmptyPosIdEndToEnd:
    """L2 audit fix: end-to-end verification that _build_close_row_for_fill
    correctly routes through find_opens_for_position_close_at for the
    empty-pos_id path and produces a closed_positions row with the right
    entry/exit attribution.

    Closes the equivalent of Phase 0.0.4's H1 gap — the dispatcher-level
    helper tests don't exercise the integration between the close-row
    builder and the helper. A regression in the wiring (e.g., a future
    refactor swapping the helper call) would slip past the 16
    isolation-mode tests above."""

    @pytest.mark.asyncio
    async def test_scale_in_then_close_with_empty_pos_id_builds_correct_row(
        self, test_db,
    ):
        from unittest.mock import patch
        from core.order_manager import OrderManager

        om = OrderManager(test_db)

        open_ts_1 = BASE_MS
        open_ts_2 = BASE_MS + 10_000
        close_ts = BASE_MS + 60_000

        # Scale-in opens (2 separate fills, different prices).
        await _seed_fill_via_db(
            test_db,
            exchange_fill_id="open-1",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=1.0, price=100.0, is_close=False,
            timestamp_ms=open_ts_1,
            terminal_position_id="",
        )
        await _seed_fill_via_db(
            test_db,
            exchange_fill_id="open-2",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=3.0, price=110.0, is_close=False,
            timestamp_ms=open_ts_2,
            terminal_position_id="",
        )
        # Close fill — already in the table when builder runs.
        await _seed_fill_via_db(
            test_db,
            exchange_fill_id="close-1",
            symbol="BTCUSDT", side="SELL", direction="LONG",
            quantity=4.0, price=120.0, is_close=True,
            timestamp_ms=close_ts,
            terminal_position_id="",
        )

        # The close fill dict as it would arrive at _build_close_row_for_fill.
        close_fill = {
            "account_id":           1,
            "exchange_fill_id":     "close-1",
            "exchange_order_id":    "",
            "symbol":               "BTCUSDT",
            "side":                 "SELL",
            "direction":            "LONG",
            "price":                120.0,
            "quantity":             4.0,
            "fee":                  0.1,
            "is_close":             1,
            "realized_pnl":         40.0,    # (120-VWAP_entry) * 4 = math fallback
            "timestamp_ms":         close_ts,
            "terminal_position_id": "",      # the Phase 0.0.5 path
            "source":               "binance_ws",
        }

        # app_state.positions is empty (no plugin tracking)
        with patch("core.order_manager.app_state") as mock_state:
            mock_state.positions = []
            mock_state.active_account_id = 1
            await om._build_close_row_for_fill(1, close_fill)

        closed = await _all_closed(test_db)
        assert len(closed) == 1, (
            "Empty-pos_id close-row builder must produce exactly 1 row "
            "via the Phase 0.0.5 grouping path. If 0 rows: the helper "
            "returned []. If 2+ rows: cross-position contamination "
            "regressed."
        )
        c = closed[0]
        assert c["symbol"] == "BTCUSDT"
        assert c["direction"] == "LONG"
        assert c["quantity"] == pytest.approx(4.0)
        # VWAP entry: (100*1 + 110*3) / 4 = 107.5
        assert c["entry_price"] == pytest.approx(107.5)
        # exit_price from VWAP of close_fills (single close at 120)
        assert c["exit_price"] == pytest.approx(120.0)
        # entry_time_ms = min of opens
        assert c["entry_time_ms"] == open_ts_1
        # exit_time_ms = max of closes
        assert c["exit_time_ms"] == close_ts
        # terminal_position_id from input fill (empty)
        assert c["terminal_position_id"] == ""

    @pytest.mark.asyncio
    async def test_empty_pos_id_prior_position_does_not_contaminate(
        self, test_db,
    ):
        """T178 Layer 3 regression guard at the integration level: a
        prior closed position's opens must NOT leak into the current
        close-row build."""
        from unittest.mock import patch
        from core.order_manager import OrderManager

        om = OrderManager(test_db)

        # Position A: open at T+0, close at T+60_000. Already retired.
        await _seed_fill_via_db(
            test_db, exchange_fill_id="A-open",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=2.0, price=80000.0, is_close=False,
            timestamp_ms=BASE_MS, terminal_position_id="",
        )
        await _seed_fill_via_db(
            test_db, exchange_fill_id="A-close",
            symbol="BTCUSDT", side="SELL", direction="LONG",
            quantity=2.0, price=82000.0, is_close=True,
            timestamp_ms=BASE_MS + 60_000, terminal_position_id="",
        )
        # Position B: open at T+120_000, close at T+180_000. Current.
        b_open_ts = BASE_MS + 120_000
        b_close_ts = BASE_MS + 180_000
        await _seed_fill_via_db(
            test_db, exchange_fill_id="B-open",
            symbol="BTCUSDT", side="BUY", direction="LONG",
            quantity=1.0, price=85000.0, is_close=False,
            timestamp_ms=b_open_ts, terminal_position_id="",
        )
        await _seed_fill_via_db(
            test_db, exchange_fill_id="B-close",
            symbol="BTCUSDT", side="SELL", direction="LONG",
            quantity=1.0, price=86000.0, is_close=True,
            timestamp_ms=b_close_ts, terminal_position_id="",
        )

        b_close_fill = {
            "account_id":           1,
            "exchange_fill_id":     "B-close",
            "exchange_order_id":    "",
            "symbol":               "BTCUSDT",
            "side":                 "SELL",
            "direction":            "LONG",
            "price":                86000.0,
            "quantity":             1.0,
            "fee":                  0.05,
            "is_close":             1,
            "realized_pnl":         1000.0,
            "timestamp_ms":         b_close_ts,
            "terminal_position_id": "",
            "source":               "binance_ws",
        }

        with patch("core.order_manager.app_state") as mock_state:
            mock_state.positions = []
            mock_state.active_account_id = 1
            await om._build_close_row_for_fill(1, b_close_fill)

        closed = await _all_closed(test_db)
        # Only B's close — A's close-row was never built in this test.
        # The critical check: B's entry_price reflects B's open (85000),
        # NOT a VWAP across A+B opens. Pre-Phase-0.0.5 fallback would
        # have produced (80000*2 + 85000*1) / 3 = 81666.67 — clearly wrong.
        assert len(closed) == 1
        c = closed[0]
        assert c["entry_price"] == pytest.approx(85000.0), (
            "T178 Layer 3: prior position A's open at 80000 must NOT "
            "contaminate position B's entry_price. Got {} — expected "
            "85000.0 (B's open alone).".format(c["entry_price"])
        )
        assert c["entry_time_ms"] == b_open_ts, (
            "entry_time_ms must reflect B's open, not A's earlier open"
        )
        assert c["quantity"] == pytest.approx(1.0)


class TestReversalSplitCloseRowFollowUp:
    """L3 audit fix: the Phase 0.0.4 reversal split produces a synth
    open with terminal_position_id="". When THAT open later closes,
    the close-row builder's empty-pos_id branch must correctly walk
    the fills and pin the synth open as the entry.

    Pins the Phase 0.0.4 + 0.0.5 cross-call invariant: reversal-split
    + chronological-walk grouping compose correctly."""

    @pytest.mark.asyncio
    async def test_synth_open_close_uses_synth_open_as_entry(
        self, test_db,
    ):
        from unittest.mock import patch
        from core.order_manager import OrderManager

        om = OrderManager(test_db)

        # Pre-state: a Phase 0.0.4 reversal already wrote 2 rows.
        # Close-of-old (LONG): qty=5 at $80k. (not exercised here — it
        # would have its own closed_positions row from the original
        # reversal trigger.)
        # Open-of-new (SHORT, synth): qty=7 at $80k, ts = T_reversal.
        t_reversal = BASE_MS
        t_followup_close = BASE_MS + 60_000

        await _seed_fill_via_db(
            test_db, exchange_fill_id="tid-100",
            symbol="BTCUSDT", side="SELL", direction="LONG",
            quantity=5.0, price=80000.0, is_close=True,
            timestamp_ms=t_reversal, terminal_position_id="pos-old",
        )
        await _seed_fill_via_db(
            test_db, exchange_fill_id="synth:tid-100:open",
            symbol="BTCUSDT", side="SELL", direction="SHORT",
            quantity=7.0, price=80000.0, is_close=False,
            timestamp_ms=t_reversal, terminal_position_id="",
        )
        # Follow-up close of the SHORT position. Different tradeId.
        await _seed_fill_via_db(
            test_db, exchange_fill_id="tid-200",
            symbol="BTCUSDT", side="BUY", direction="SHORT",
            quantity=7.0, price=78000.0, is_close=True,
            timestamp_ms=t_followup_close, terminal_position_id="",
        )

        followup_fill = {
            "account_id":           1,
            "exchange_fill_id":     "tid-200",
            "exchange_order_id":    "",
            "symbol":               "BTCUSDT",
            "side":                 "BUY",
            "direction":            "SHORT",
            "price":                78000.0,
            "quantity":             7.0,
            "fee":                  0.2,
            "is_close":             1,
            "realized_pnl":         14000.0,    # (80000 - 78000) * 7
            "timestamp_ms":         t_followup_close,
            "terminal_position_id": "",          # inherited from synth open
            "source":               "binance_ws",
        }

        with patch("core.order_manager.app_state") as mock_state:
            mock_state.positions = []
            mock_state.active_account_id = 1
            await om._build_close_row_for_fill(1, followup_fill)

        closed = await _all_closed(test_db)
        assert len(closed) == 1, (
            "Follow-up close of a synth-open SHORT must produce a "
            "closed_positions row — the empty-pos_id grouping path "
            "must find the synth open as the entry."
        )
        c = closed[0]
        assert c["direction"] == "SHORT"
        # entry from the synth open
        assert c["entry_price"] == pytest.approx(80000.0)
        assert c["entry_time_ms"] == t_reversal
        # exit from the follow-up close
        assert c["exit_price"] == pytest.approx(78000.0)
        assert c["exit_time_ms"] == t_followup_close
        assert c["quantity"] == pytest.approx(7.0)
        # The reversal-split's LONG close (tid-100) is on the LONG
        # direction track and must NOT participate in this SHORT
        # close-row build. Verified implicitly via direction filter
        # in find_opens_for_position_close_at.
