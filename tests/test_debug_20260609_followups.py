"""Regression tests for the 2026-06-08/09 live calc-linkage debug follow-ups.

Covers the behaviours fixed during the live Binance-direct debug session:

  #1  deviation badge label — yellow reads "amended" ONLY for a real amendment
      (order-ledger OR a live TP/SL drift), else "off-size" (a size deviation).
      A market-fill size rounding must NOT read as "amended".
  #2  ``reconcile_filled_orders`` — truth-based (filled_qty >= quantity) promotion
      of orders stuck in new/partially_filled to 'filled'. Must NEVER touch a
      genuinely-working order (filled_qty < quantity). The time-based staleness
      loop is plugin-gated, so this is the Binance-direct cleanup path.
  #3  ``query_trade_events(symbol=...)`` — payload-symbol filter used by the
      per-position drilldown to attribute order-lifecycle events (which on the
      observe-only path carry no calc_id) by symbol+time-window.
  #3/#4  close-recording — ``_build_close_row_for_fill`` builds the close row
      (and backfills the OPENING fills' tpid) when the closing fill carries the
      minted tpid but the opening fills were written empty (the ⑨ regression).
  #5b ``check_correlated_limit`` — excludes the operator's EXISTING
      same-(symbol,side) position from the sector net so re-calcing a held
      symbol doesn't double-count it.

Run: pytest tests/test_debug_20260609_followups.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
_REPO = os.path.dirname(os.path.dirname(__file__))

ACCOUNT_ID = 1


@pytest_asyncio.fixture
async def db():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database = DatabaseManager(path=tmp.name)
    await database.initialize()
    yield database
    await database.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


@pytest_asyncio.fixture
async def om(db):
    from core.order_manager import OrderManager
    return OrderManager(db)


# ── #1 — off-size vs amended label ──────────────────────────────────────────


class TestTpslAmendedLevel:
    def _lvl(self, **kw):
        from core.state import deviation_badge_level
        base = dict(has_calc=True, size_delta_pct=0.0, amendment_count=0,
                    yellow_pct=5.0, red_pct=15.0)
        base.update(kw)
        return deviation_badge_level(**base)

    def test_tpsl_amended_forces_yellow(self):
        # on-plan size + no ledger amendment, but a live TP/SL drift → yellow.
        assert self._lvl(tpsl_amended=True) == "yellow"

    def test_tpsl_amended_default_false_keeps_green(self):
        # the new kw-only param defaults False → unchanged behaviour.
        assert self._lvl() == "green"

    def test_red_still_beats_tpsl_amended(self):
        assert self._lvl(size_delta_pct=20.0, tpsl_amended=True) == "red"


class TestBadgeMacroLabel:
    """The macro must DISTINGUISH a real amendment from a size-only deviation —
    the operator's bug was a market-fill size rounding reading as 'amended'."""

    def _render(self, level, size_delta_pct=0.0, amendment_count=0,
                tpsl_amended=False):
        from jinja2 import Environment, FileSystemLoader
        env = Environment(loader=FileSystemLoader(os.path.join(_REPO, "templates")))
        tmpl = env.from_string(
            "{% from 'primitives/deviation_badge.html' import deviation_badge %}"
            "{{ deviation_badge(level, sd, ac, tp) }}"
        )
        return tmpl.render(level=level, sd=size_delta_pct, ac=amendment_count,
                           tp=tpsl_amended)

    def test_size_only_yellow_reads_off_size(self):
        out = self._render("yellow", size_delta_pct=-8.18,
                           amendment_count=0, tpsl_amended=False)
        assert "off-size" in out
        assert "amended" not in out

    def test_ledger_amendment_reads_amended(self):
        out = self._render("yellow", amendment_count=2, tpsl_amended=False)
        assert "amended" in out
        assert "off-size" not in out

    def test_tpsl_drift_reads_amended(self):
        out = self._render("yellow", amendment_count=0, tpsl_amended=True)
        assert "amended" in out
        assert "off-size" not in out
        assert "TP/SL amended" in out  # title detail

    def test_green_and_red_unaffected(self):
        assert "on-plan" in self._render("green")
        assert "off-plan" in self._render("red", size_delta_pct=20.0)


# ── #1 — live TP/SL-drift detection in _enrich_positions_calc_id ────────────


async def _seed_junction_tpsl(db, position_id, calc_id, *, qty, planned_size,
                              planned_tp, planned_sl, account_id=ACCOUNT_ID):
    await db._conn.execute(
        "INSERT INTO positions_calcs (position_id, calc_id, order_id, account_id, "
        " contributed_qty, first_fill_ts, last_fill_ts, planned_size, "
        " planned_tp, planned_sl) VALUES (?, ?, 1, ?, ?, 1000, 1000, ?, ?, ?)",
        (position_id, calc_id, account_id, qty, planned_size, planned_tp, planned_sl),
    )
    await db._conn.commit()


def _pos_tpsl(tp, sl, position_id="POS-T", ticker="BTCUSDT", direction="LONG"):
    from core.state import PositionInfo
    p = PositionInfo(position_id=position_id, ticker=ticker, direction=direction)
    p.individual_tp_price = tp
    p.individual_sl_price = sl
    return p


class TestTpslDriftEnrich:
    @pytest.mark.asyncio
    async def test_tp_drift_sets_amended_and_yellow(self, db, om):
        # planned tp 110 / sl 90; live tp 120 (>0.1% drift) → amended (the
        # observe-only Binance cancel+create amendment, invisible to the ledger).
        await _seed_junction_tpsl(db, "POS-T", "C1", qty=10.0, planned_size=10.0,
                                  planned_tp=110.0, planned_sl=90.0)
        pos = _pos_tpsl(tp=120.0, sl=90.0)
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.calc_id == "C1"
        assert pos.tpsl_amended is True
        assert pos.deviation_badge == "yellow"

    @pytest.mark.asyncio
    async def test_sl_drift_sets_amended(self, db, om):
        await _seed_junction_tpsl(db, "POS-T", "C1", qty=10.0, planned_size=10.0,
                                  planned_tp=110.0, planned_sl=90.0)
        pos = _pos_tpsl(tp=110.0, sl=85.0)  # SL moved
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.tpsl_amended is True

    @pytest.mark.asyncio
    async def test_on_plan_tpsl_not_amended(self, db, om):
        # live tp/sl match the plan → green, NOT amended (the false-positive the
        # operator hit was a SIZE deviation, not a TP/SL change).
        await _seed_junction_tpsl(db, "POS-T", "C1", qty=10.0, planned_size=10.0,
                                  planned_tp=110.0, planned_sl=90.0)
        pos = _pos_tpsl(tp=110.0, sl=90.0)
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.tpsl_amended is False
        assert pos.deviation_badge == "green"

    @pytest.mark.asyncio
    async def test_missing_live_tpsl_not_amended(self, db, om):
        # fresh open — NEITHER bracket order observed yet (both 0.0) → not amended
        # (the gate that prevents the fresh-open false positive).
        await _seed_junction_tpsl(db, "POS-T", "C1", qty=10.0, planned_size=10.0,
                                  planned_tp=110.0, planned_sl=90.0)
        pos = _pos_tpsl(tp=0.0, sl=0.0)
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.tpsl_amended is False
        assert pos.deviation_badge == "green"

    @pytest.mark.asyncio
    async def test_sl_removed_while_tp_live_is_red(self, db, om):
        # #1b + 2026-06-20 severity: calc planned an SL but the open position has
        # NO live SL while the TP is still live → the operator REMOVED the stop →
        # unprotected. A removed stop is the most dangerous deviation ("fatal"),
        # so it now paints RED (was yellow) — distinct from a benign TP/SL move.
        await _seed_junction_tpsl(db, "POS-T", "C1", qty=10.0, planned_size=10.0,
                                  planned_tp=110.0, planned_sl=90.0)
        pos = _pos_tpsl(tp=110.0, sl=0.0)
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.tpsl_amended is True
        assert pos.deviation_badge == "red"
        # the sticky stash captures the SL-removal at severity 2 (→ red history).
        assert om._tpsl_amended_seen.get(pos.position_id) == 2

    @pytest.mark.asyncio
    async def test_tp_removed_while_sl_live_is_amended(self, db, om):
        # removing the TAKE-PROFIT (stop still live) is "amended" (yellow), NOT
        # red — the position is still protected. Severity level 1.
        await _seed_junction_tpsl(db, "POS-T", "C1", qty=10.0, planned_size=10.0,
                                  planned_tp=110.0, planned_sl=90.0)
        pos = _pos_tpsl(tp=0.0, sl=90.0)
        await om._enrich_positions_calc_id(ACCOUNT_ID, [pos])
        assert pos.tpsl_amended is True
        assert pos.deviation_badge == "yellow"
        assert om._tpsl_amended_seen.get(pos.position_id) == 1


# ── #2 — reconcile_filled_orders (truth-based) ──────────────────────────────


async def _seed_order(db, eoid, *, status, quantity, filled_qty,
                      symbol="VELVETUSDT", side="BUY", order_type="market",
                      account_id=ACCOUNT_ID):
    await db._conn.execute(
        "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
        " order_type, status, quantity, filled_qty) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (account_id, eoid, symbol, side, order_type, status, quantity, filled_qty),
    )
    await db._conn.commit()


async def _status(db, eoid):
    async with db._conn.execute(
        "SELECT status FROM orders WHERE exchange_order_id=?", (eoid,),
    ) as cur:
        row = await cur.fetchone()
        return row[0]


class TestReconcileFilledOrders:
    @pytest.mark.asyncio
    async def test_fully_filled_new_promoted(self, db):
        await _seed_order(db, "O-new", status="new", quantity=71.0, filled_qty=71.0)
        n = await db.reconcile_filled_orders(ACCOUNT_ID)
        assert n == 1
        assert await _status(db, "O-new") == "filled"

    @pytest.mark.asyncio
    async def test_fully_filled_partial_promoted(self, db):
        await _seed_order(db, "O-pf", status="partially_filled",
                          quantity=153.0, filled_qty=153.0)
        await db.reconcile_filled_orders(ACCOUNT_ID)
        assert await _status(db, "O-pf") == "filled"

    @pytest.mark.asyncio
    async def test_working_order_untouched(self, db):
        # filled_qty < quantity → a genuinely-working order — must NOT be touched.
        await _seed_order(db, "O-work", status="partially_filled",
                          quantity=100.0, filled_qty=40.0)
        await _seed_order(db, "O-open", status="new",
                          quantity=100.0, filled_qty=0.0)
        n = await db.reconcile_filled_orders(ACCOUNT_ID)
        assert n == 0
        assert await _status(db, "O-work") == "partially_filled"
        assert await _status(db, "O-open") == "new"

    @pytest.mark.asyncio
    async def test_zero_quantity_skipped(self, db):
        # quantity == 0 (e.g. some algo placeholders) → never auto-filled.
        await _seed_order(db, "O-zero", status="new", quantity=0.0, filled_qty=0.0)
        n = await db.reconcile_filled_orders(ACCOUNT_ID)
        assert n == 0
        assert await _status(db, "O-zero") == "new"

    @pytest.mark.asyncio
    async def test_already_terminal_untouched(self, db):
        await _seed_order(db, "O-canc", status="canceled",
                          quantity=10.0, filled_qty=10.0)
        n = await db.reconcile_filled_orders(ACCOUNT_ID)
        assert n == 0
        assert await _status(db, "O-canc") == "canceled"


# ── #3 — query_trade_events symbol filter ───────────────────────────────────


class TestQueryTradeEventsSymbolFilter:
    def _emit(self, calc_id, event_type, ts, symbol):
        from core.trade_event_log import log_trade_event
        log_trade_event(ACCOUNT_ID, calc_id, event_type,
                        {"symbol": symbol}, "test", timestamp=ts)

    def test_symbol_filters_by_payload(self):
        from core.trade_event_log import query_trade_events
        # order-lifecycle events with NO calc_id (the observe-only reality) but a
        # symbol in the payload — the drilldown finds them by symbol.
        self._emit(None, "order_filled", "2026-06-09T00:00:01", "BEATUSDT")
        self._emit(None, "order_canceled", "2026-06-09T00:00:02", "BEATUSDT")
        self._emit(None, "order_filled", "2026-06-09T00:00:03", "XAUUSDT")
        rows, total = query_trade_events(account_id=ACCOUNT_ID, symbol="BEATUSDT")
        assert total == 2
        assert {r["event_type"] for r in rows} == {"order_filled", "order_canceled"}
        assert all('"symbol": "BEATUSDT"' in r["payload_json"] for r in rows)

    def test_symbol_plus_window(self):
        from core.trade_event_log import query_trade_events
        self._emit(None, "order_placed", "2026-06-09T01:00:00", "SOLUSDT")
        self._emit(None, "order_filled", "2026-06-09T02:00:00", "SOLUSDT")
        self._emit(None, "order_canceled", "2026-06-09T09:00:00", "SOLUSDT")
        rows, total = query_trade_events(
            account_id=ACCOUNT_ID, symbol="SOLUSDT",
            since="2026-06-09T00:30:00", until="2026-06-09T03:00:00",
        )
        # the 09:00 cancel is outside the window.
        assert total == 2
        assert {r["event_type"] for r in rows} == {"order_placed", "order_filled"}


# ── #3/#4 — close-recording with empty-tpid opening fills ───────────────────


async def _seed_fill(db, fid, *, is_close, tpid, ts, qty, price,
                     order_id, symbol="DOGEUSDT", direction="LONG",
                     side=None, account_id=ACCOUNT_ID):
    side = side or ("SELL" if is_close else "BUY")
    await db._conn.execute(
        "INSERT INTO fills (account_id, exchange_fill_id, exchange_order_id, "
        " symbol, side, direction, price, quantity, is_close, "
        " terminal_position_id, timestamp_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (account_id, fid, order_id, symbol, side, direction, price, qty,
         int(is_close), tpid, ts),
    )
    await db._conn.commit()


class TestCloseRecordingEmptyOpenTpid:
    @pytest.mark.asyncio
    async def test_close_row_built_and_opens_backfilled(self, db, om):
        TPID = "binance:DOGEUSDT:LONG:1000"
        # OPENING fill: empty tpid (observe-only path writes it before mint).
        await _seed_fill(db, "F-open", is_close=False, tpid="", ts=1000,
                         qty=100.0, price=0.10, order_id="O-entry")
        # CLOSING fill: carries the minted tpid (⑨ resolved it).
        await _seed_fill(db, "F-close", is_close=True, tpid=TPID, ts=2000,
                         qty=100.0, price=0.12, order_id="O-close")

        closing = {
            "exchange_fill_id": "F-close", "exchange_order_id": "O-close",
            "symbol": "DOGEUSDT", "direction": "LONG",
            "terminal_position_id": TPID, "is_close": 1,
            "quantity": 100.0, "price": 0.12, "timestamp_ms": 2000,
            "realized_pnl": 2.0, "fee": 0.0,
        }
        await om._build_close_row_for_fill(ACCOUNT_ID, closing, force_final=True)

        # 1) a closed_positions row was built (pre-fix: strict tpid open-lookup
        #    missed the empty-tpid opens → no entry VWAP → NO row).
        async with db._conn.execute(
            "SELECT entry_price, exit_price, quantity, terminal_position_id "
            "FROM closed_positions WHERE account_id=? AND terminal_position_id=?",
            (ACCOUNT_ID, TPID),
        ) as cur:
            row = await cur.fetchone()
        assert row is not None, "close row must be built via the walk fallback"
        assert abs(row[0] - 0.10) < 1e-9   # entry VWAP from the opening fill
        assert abs(row[1] - 0.12) < 1e-9   # exit VWAP from the closing fill

        # 2) the opening fill's tpid was backfilled (so the drilldown's
        #    fills-by-tpid is complete).
        async with db._conn.execute(
            "SELECT terminal_position_id FROM fills WHERE exchange_fill_id=?",
            ("F-open",),
        ) as cur:
            assert (await cur.fetchone())[0] == TPID

    @pytest.mark.asyncio
    async def test_sticky_tpsl_amended_persisted_to_close_row_and_pruned(self, db, om):
        # 2026-06-15: a position whose TP/SL was amended during life (sticky
        # stash set by drift_check) must write tpsl_amended=1 onto the close
        # row — pos.tpsl_amended has already reset by close, so the stash is the
        # only surviving signal. And the stash is pruned on the final close.
        TPID = "binance:DOGEUSDT:LONG:2000"
        await _seed_fill(db, "F-open2", is_close=False, tpid="", ts=1000,
                         qty=100.0, price=0.10, order_id="O-entry2")
        await _seed_fill(db, "F-close2", is_close=True, tpid=TPID, ts=2000,
                         qty=100.0, price=0.12, order_id="O-close2")
        om._tpsl_amended_seen[TPID] = 1   # drift_check saw an amendment (level 1)
        closing = {
            "exchange_fill_id": "F-close2", "exchange_order_id": "O-close2",
            "symbol": "DOGEUSDT", "direction": "LONG",
            "terminal_position_id": TPID, "is_close": 1,
            "quantity": 100.0, "price": 0.12, "timestamp_ms": 2000,
            "realized_pnl": 2.0, "fee": 0.0,
        }
        await om._build_close_row_for_fill(ACCOUNT_ID, closing, force_final=True)
        async with db._conn.execute(
            "SELECT tpsl_amended FROM closed_positions WHERE terminal_position_id=?",
            (TPID,),
        ) as cur:
            assert (await cur.fetchone())[0] == 1
        assert TPID not in om._tpsl_amended_seen   # pruned on final close

    @pytest.mark.asyncio
    async def test_never_amended_close_row_tpsl_amended_null(self, db, om):
        # contrast: a position never amended → tpsl_amended NULL (reads on-plan).
        TPID = "binance:DOGEUSDT:LONG:3000"
        await _seed_fill(db, "F-open3", is_close=False, tpid="", ts=1000,
                         qty=100.0, price=0.10, order_id="O-entry3")
        await _seed_fill(db, "F-close3", is_close=True, tpid=TPID, ts=2000,
                         qty=100.0, price=0.12, order_id="O-close3")
        closing = {
            "exchange_fill_id": "F-close3", "exchange_order_id": "O-close3",
            "symbol": "DOGEUSDT", "direction": "LONG",
            "terminal_position_id": TPID, "is_close": 1,
            "quantity": 100.0, "price": 0.12, "timestamp_ms": 2000,
            "realized_pnl": 2.0, "fee": 0.0,
        }
        await om._build_close_row_for_fill(ACCOUNT_ID, closing, force_final=True)
        async with db._conn.execute(
            "SELECT tpsl_amended FROM closed_positions WHERE terminal_position_id=?",
            (TPID,),
        ) as cur:
            assert (await cur.fetchone())[0] is None

    @pytest.mark.asyncio
    async def test_sticky_sl_removed_persists_level_2_to_close_row(self, db, om):
        # 2026-06-20 severity: a position whose STOP was removed during life
        # (stash level 2) must write tpsl_amended=2 onto the close row, so
        # Position History reads RED "unprotected", not yellow "amended".
        TPID = "binance:DOGEUSDT:LONG:4000"
        await _seed_fill(db, "F-open4", is_close=False, tpid="", ts=1000,
                         qty=100.0, price=0.10, order_id="O-entry4")
        await _seed_fill(db, "F-close4", is_close=True, tpid=TPID, ts=2000,
                         qty=100.0, price=0.12, order_id="O-close4")
        om._tpsl_amended_seen[TPID] = 2   # drift_check saw an SL removal
        closing = {
            "exchange_fill_id": "F-close4", "exchange_order_id": "O-close4",
            "symbol": "DOGEUSDT", "direction": "LONG",
            "terminal_position_id": TPID, "is_close": 1,
            "quantity": 100.0, "price": 0.12, "timestamp_ms": 2000,
            "realized_pnl": 2.0, "fee": 0.0,
        }
        await om._build_close_row_for_fill(ACCOUNT_ID, closing, force_final=True)
        async with db._conn.execute(
            "SELECT tpsl_amended FROM closed_positions WHERE terminal_position_id=?",
            (TPID,),
        ) as cur:
            assert (await cur.fetchone())[0] == 2
        assert TPID not in om._tpsl_amended_seen   # pruned on final close


# ── #5b — correlated-limit same-symbol exclusion ────────────────────────────


class TestCorrelatedSameSymbolExclusion:
    def _setup(self, monkeypatch, *, held):
        from core import state as state_mod
        from core.state import PositionInfo
        import core.risk_engine as risk
        # equity 100, cap 50% → 50 USDT per sector.
        monkeypatch.setattr(risk.app_state, "params",
                            {"max_correlated_exposure": 0.5}, raising=False)
        positions = []
        if held:
            p = PositionInfo(position_id="P", ticker="BNBUSDT", direction="LONG")
            p.position_value_usdt = 40.0
            p.sector = "top_twenty_alts"
            positions = [p]
        monkeypatch.setattr(risk.app_state, "positions", positions, raising=False)
        return risk

    def test_held_same_symbol_excluded(self, monkeypatch):
        risk = self._setup(monkeypatch, held=True)
        # new BNB calc, notional 30 (size 0.05 * avg 600). Held BNB = 40.
        # WITHOUT exclusion: 40 + 30 = 70 > 50 → would block.
        # WITH exclusion (held BNB removed): |0 + 30| = 30 < 50 → eligible.
        exceeds, new_abs = risk.check_correlated_limit(
            "BNBUSDT", 0.05, 600.0, "long", 100.0,
        )
        assert exceeds is False
        assert abs(new_abs - 30.0) < 1e-6

    def test_other_symbol_in_sector_still_counts(self, monkeypatch):
        # A DIFFERENT symbol in the same sector is NOT excluded — the gate still
        # guards genuine sector concentration.
        risk = self._setup(monkeypatch, held=True)
        # new SOL (also top_twenty_alts), notional 30. Held BNB 40 stays in net.
        exceeds, new_abs = risk.check_correlated_limit(
            "SOLUSDT", 0.2, 150.0, "long", 100.0,
        )
        assert abs(new_abs - 70.0) < 1e-6   # 40 (BNB) + 30 (SOL)
        assert exceeds is True               # 70 > 50

    def test_no_held_position_unchanged(self, monkeypatch):
        risk = self._setup(monkeypatch, held=False)
        exceeds, new_abs = risk.check_correlated_limit(
            "BNBUSDT", 0.05, 600.0, "long", 100.0,
        )
        assert abs(new_abs - 30.0) < 1e-6
        assert exceeds is False
