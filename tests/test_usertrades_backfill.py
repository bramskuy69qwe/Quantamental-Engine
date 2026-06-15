"""
userTrades offline-recovery fix (2026-06-15 live debug session).

When the engine is offline during trades, fills were rebuilt from the
REALIZED_PNL *income* feed (close-only) which re-summed opening commissions
per partial close (8-70x fee inflation) and synthesized undersized opens
(position collapse). The fix rebuilds fills from Binance ``userTrades`` —
real opens AND closes with per-fill commission.

These tests pin:
  - user_trade_to_fill_dict mapping (core/exchange_income.py)
  - the SPCX-shape correctness: real opens+closes -> correct positions +
    NON-inflated per-position fees (the whole point)
  - fetch_all_user_trades pagination/dedup/window
  - backfill_fills_from_user_trades (builder, idempotent)
  - scripts/refix_fills_from_usertrades.run_refix dry-run vs apply
    (deletes synthetic backfill fills, preserves real WS fills,
    leaves closed_positions untouched)

Run: pytest tests/test_usertrades_backfill.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
from types import SimpleNamespace

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.exchange_income import (  # noqa: E402
    user_trade_to_fill_dict,
    fetch_all_user_trades,
    backfill_fills_from_user_trades,
    recover_offline_trades,
)
from scripts.refix_fills_from_usertrades import preview_from_trades, run_refix  # noqa: E402


BASE = 1781279232000  # SPCX session anchor (2026-06-12 UTC), ms


def _trade(tid, side, direction, price, qty, fee, is_close, rpnl=0.0, ts=BASE, symbol="SPCXUSDT"):
    """Duck-typed NormalizedTrade (the code reads via getattr)."""
    return SimpleNamespace(
        trade_id=str(tid), exchange_fill_id=str(tid), exchange_order_id="o" + str(tid),
        symbol=symbol, side=side, direction=direction, price=price, quantity=qty,
        fee=fee, fee_asset="USDT", role="taker", is_close=is_close,
        realized_pnl=rpnl, timestamp_ms=ts,
    )


def _spcx_shape(symbol="SPCXUSDT"):
    """A LONG round-trip (1 open + 2 partial closes) + a SHORT round-trip
    (1 open + 1 close) — the hedge-mode partial-close shape the income path
    mangled. Opening commission appears ONCE (on the open fill)."""
    return [
        _trade(1, "BUY",  "LONG",  100.0, 10.0, 0.40, False, 0.0,   BASE + 0,    symbol),
        _trade(2, "SELL", "LONG",  110.0, 4.0,  0.44, True,  40.0,  BASE + 1000, symbol),
        _trade(3, "SELL", "LONG",  120.0, 6.0,  0.72, True,  120.0, BASE + 2000, symbol),
        _trade(4, "SELL", "SHORT", 200.0, 5.0,  1.00, False, 0.0,   BASE + 500,  symbol),
        _trade(5, "BUY",  "SHORT", 190.0, 5.0,  0.95, True,  50.0,  BASE + 1500, symbol),
    ]


async def _insert_exchange_history(db, *, trade_key, time_ms, symbol, account_id=1,
                                   income_type="REALIZED_PNL"):
    """Insert one exchange_history (income ledger) row for gap-detection tests."""
    await db._conn.execute(
        "INSERT INTO exchange_history (trade_key, time, symbol, income_type, income, "
        "direction, account_id) VALUES (?, ?, ?, ?, 0, 'LONG', ?)",
        (trade_key, time_ms, symbol, income_type, account_id),
    )
    await db._conn.commit()


async def _seed_backfill_fill(db, symbol, *, eid="bf1", account_id=1, ts=BASE):
    await db.upsert_fill({
        "account_id": account_id, "exchange_fill_id": eid, "symbol": symbol,
        "side": "SELL", "direction": "LONG", "price": 110.0, "quantity": 3.0,
        "fee": 9.0, "is_close": 1, "timestamp_ms": ts,
        "source": "exchange_history_backfill",
    })


# ── fixtures ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def test_db():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    yield db
    await db.close()
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(tmp.name + ext)
        except OSError:
            pass


class _FakeAdapter:
    """Mimics Binance fetch_user_trades: ascending by id, honours
    fromId / startTime, caps at ``limit``."""
    def __init__(self, trades):
        self.trades = sorted(trades, key=lambda t: int(t.trade_id))
        self.calls = []

    def set_priority(self, _p):  # paginator calls this
        pass

    async def fetch_user_trades(self, symbol, limit=1000, start_ms=None, end_ms=None, from_id=None):
        self.calls.append({"start_ms": start_ms, "end_ms": end_ms, "from_id": from_id, "limit": limit})
        ts = self.trades
        if from_id is not None:
            ts = [t for t in ts if int(t.trade_id) >= from_id]
        elif start_ms is not None:
            ts = [t for t in ts if t.timestamp_ms >= start_ms]
        return ts[:limit]


# ── user_trade_to_fill_dict ─────────────────────────────────────────────

class TestUserTradeToFillDict:
    def test_maps_fields_and_normalizes(self):
        t = _trade(42, "SELL", "LONG", 110.5, 4.0, -0.44, True, 40.0, BASE)
        fd = user_trade_to_fill_dict(t, account_id=7)
        assert fd["account_id"] == 7
        assert fd["exchange_fill_id"] == "42"          # = tradeId (dedup key)
        assert fd["exchange_order_id"] == "o42"
        assert fd["symbol"] == "SPCXUSDT"
        assert fd["side"] == "SELL"
        assert fd["direction"] == "LONG"               # = positionSide
        assert fd["is_close"] == 1                      # bool -> int
        assert fd["fee"] == 0.44                        # abs()
        assert fd["realized_pnl"] == 40.0
        assert fd["source"] == "exchange_usertrades"
        assert fd["timestamp_ms"] == BASE

    def test_open_fill_is_close_zero(self):
        fd = user_trade_to_fill_dict(_trade(1, "BUY", "LONG", 100, 10, 0.4, False), account_id=1)
        assert fd["is_close"] == 0


# ── SPCX-shape correctness (the whole point) ────────────────────────────

class TestPreviewCorrectness:
    def test_real_opens_and_closes_yield_correct_positions(self):
        prev = preview_from_trades(_spcx_shape(), account_id=1)
        s = prev["summary"]
        assert s["n_opens"] == 2 and s["n_closes"] == 3
        assert s["n_positions"] == 2          # NOT collapsed/shattered
        positions = {p["direction"]: p for p in prev["positions"]}
        assert set(positions) == {"LONG", "SHORT"}

        lng = positions["LONG"]
        # total_fees = THIS position's fills only: 0.40 + 0.44 + 0.72.
        # The opening fee (0.40) is counted ONCE across the 2 closes — the
        # income path's bug counted it per-close (would be >= 1.96).
        assert lng["total_fees"] == pytest.approx(1.56)
        assert lng["realized_pnl"] == pytest.approx(160.0)
        assert lng["net_pnl"] == pytest.approx(158.44)
        assert lng["quantity"] == pytest.approx(10.0)

        sht = positions["SHORT"]
        assert sht["total_fees"] == pytest.approx(1.95)
        assert sht["realized_pnl"] == pytest.approx(50.0)
        assert sht["net_pnl"] == pytest.approx(48.05)
        assert sht["quantity"] == pytest.approx(5.0)

    def test_fees_not_inflated_vs_income_path(self):
        # Regression guard: the bug produced fees many multiples of the true
        # per-fill sum. Assert the LONG fee is exactly the 3-fill sum.
        prev = preview_from_trades(_spcx_shape(), account_id=1)
        lng = next(p for p in prev["positions"] if p["direction"] == "LONG")
        assert lng["total_fees"] < 2.0   # true 1.56; inflated would be >=3

    def test_zero_qty_fill_skipped(self):
        trades = _spcx_shape() + [_trade(9, "BUY", "LONG", 100, 0.0, 0.0, False)]
        prev = preview_from_trades(trades, account_id=1)
        assert prev["summary"]["n_fills"] == 5   # the 0-qty fill dropped

    def test_clipped_opens_flagged(self):
        # Only closes (opens predate the window -> clipped). The grouper drops
        # the orphan closes; the preview must FLAG the imbalance (MED-2).
        trades = [
            _trade(1, "SELL", "LONG", 110, 4, 0.44, True, 40.0, BASE + 1000),
            _trade(2, "SELL", "LONG", 120, 6, 0.72, True, 120.0, BASE + 2000),
        ]
        prev = preview_from_trades(trades, account_id=1)
        assert prev["summary"]["clipped_open_qty"].get("LONG", 0) == pytest.approx(10.0)
        assert prev["summary"]["n_positions"] == 0   # orphan closes dropped

    def test_balanced_shape_has_no_clip_flag(self):
        prev = preview_from_trades(_spcx_shape(), account_id=1)
        assert prev["summary"]["clipped_open_qty"] == {}


# ── pagination ──────────────────────────────────────────────────────────

class TestFetchAllUserTradesPagination:
    @pytest.mark.asyncio
    async def test_paginates_dedups_and_windows(self, monkeypatch):
        # ids 1..6 ascending; #6 is AFTER end_ms (must be filtered out).
        trades = [
            _trade(1, "BUY",  "LONG", 100, 1, 0.0, False, ts=BASE + 10),
            _trade(2, "SELL", "LONG", 101, 1, 0.0, True,  ts=BASE + 20),
            _trade(3, "BUY",  "LONG", 102, 1, 0.0, False, ts=BASE + 30),
            _trade(4, "SELL", "LONG", 103, 1, 0.0, True,  ts=BASE + 40),
            _trade(5, "BUY",  "LONG", 104, 1, 0.0, False, ts=BASE + 50),
            _trade(6, "SELL", "LONG", 105, 1, 0.0, True,  ts=BASE + 9_000_000),
        ]
        fake = _FakeAdapter(trades)
        monkeypatch.setattr("core.exchange_income._get_adapter", lambda: fake)

        out = await fetch_all_user_trades(
            "SPCXUSDT", start_ms=BASE, end_ms=BASE + 100, page_limit=2,
        )
        ids = [int(t.trade_id) for t in out]
        assert ids == [1, 2, 3, 4, 5]                 # #6 dropped (> end_ms), sorted asc
        # fromId paging from the start; startTime is NEVER sent (avoids the
        # Binance 7-day startTime/endTime window cap).
        assert fake.calls[0]["from_id"] == 1
        assert all(c["start_ms"] is None for c in fake.calls)
        assert len(fake.calls) >= 3                    # multiple pages walked

    @pytest.mark.asyncio
    async def test_no_trades_returns_empty(self, monkeypatch):
        monkeypatch.setattr("core.exchange_income._get_adapter", lambda: _FakeAdapter([]))
        out = await fetch_all_user_trades("SPCXUSDT", start_ms=BASE, page_limit=2)
        assert out == []


# ── builder ─────────────────────────────────────────────────────────────

class TestBackfillBuilder:
    @pytest.mark.asyncio
    async def test_inserts_true_fills_and_is_idempotent(self, monkeypatch, test_db):
        async def _stub(symbol, start_ms, end_ms=None):
            return _spcx_shape()
        monkeypatch.setattr("core.exchange_income.db", test_db)
        monkeypatch.setattr("core.exchange_income.fetch_all_user_trades", _stub)

        res = await backfill_fills_from_user_trades(["SPCXUSDT"], BASE - 1000, account_id=1)
        assert res["fills_upserted"] == 5
        async with test_db._conn.execute(
            "SELECT side, direction, is_close, fee, source FROM fills "
            "WHERE account_id=1 AND symbol='SPCXUSDT' ORDER BY timestamp_ms"
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        assert len(rows) == 5
        assert sum(1 for r in rows if r["is_close"] == 0) == 2   # real opens exist
        assert all(r["source"] == "exchange_usertrades" for r in rows)

        # idempotent: dedup on (account_id, exchange_fill_id)
        await backfill_fills_from_user_trades(["SPCXUSDT"], BASE - 1000, account_id=1)
        n = await _count_fills(test_db)
        assert n == 5


async def _count_fills(db, account_id=1):
    async with db._conn.execute(
        "SELECT count(*) FROM fills WHERE account_id=?", (account_id,)
    ) as cur:
        return (await cur.fetchone())[0]


# ── run_refix (script) ──────────────────────────────────────────────────

class TestRunRefix:
    async def _seed(self, db):
        # synthetic close-only backfill fills (the bad rows) for SPCX
        for i in range(3):
            await db.upsert_fill({
                "account_id": 1, "exchange_fill_id": f"bad{i}", "symbol": "SPCXUSDT",
                "side": "SELL", "direction": "LONG", "price": 110.0, "quantity": 3.0,
                "fee": 9.0, "is_close": 1, "timestamp_ms": BASE + i,
                "source": "exchange_history_backfill",
            })
        # a REAL ws fill that must be preserved
        await db.upsert_fill({
            "account_id": 1, "exchange_fill_id": "ws1", "symbol": "SPCXUSDT",
            "side": "BUY", "direction": "LONG", "price": 100.0, "quantity": 1.0,
            "fee": 0.04, "is_close": 0, "timestamp_ms": BASE - 50,
            "source": "binance_ws",
        })
        # a closed_position that run_refix must NOT touch
        await db._conn.execute(
            "INSERT INTO closed_positions "
            "(account_id, symbol, terminal_position_id, direction, quantity, "
            " entry_price, exit_price, realized_pnl, total_fees, net_pnl, source) "
            "VALUES (1,'SPCXUSDT','rebuilt:x','LONG',9,100,110,90,27,63,'exchange_history_backfill')"
        )
        await db._conn.commit()

    async def _stub(self, symbol, start_ms, end_ms=None):
        return _spcx_shape()

    @pytest.mark.asyncio
    async def test_dry_run_writes_nothing(self, test_db):
        await self._seed(test_db)
        res = await run_refix(
            db=test_db, account_id=1, start_ms=BASE - 1000, fetch_fn=self._stub,
            symbols=["SPCXUSDT"], apply=False, verbose=False,
        )
        sym = res["per_symbol"]["SPCXUSDT"]
        assert sym["positions"] == 2 and sym["deleted"] == 0 and sym["inserted"] == 0
        # bad fills still present (no writes)
        async with test_db._conn.execute(
            "SELECT count(*) FROM fills WHERE source='exchange_history_backfill'"
        ) as cur:
            assert (await cur.fetchone())[0] == 3

    @pytest.mark.asyncio
    async def test_apply_replaces_bad_fills_preserves_real_and_closed(self, test_db):
        await self._seed(test_db)
        res = await run_refix(
            db=test_db, account_id=1, start_ms=BASE - 1000, fetch_fn=self._stub,
            symbols=["SPCXUSDT"], apply=True, verbose=False,
        )
        sym = res["per_symbol"]["SPCXUSDT"]
        assert sym["deleted"] == 3 and sym["inserted"] == 5

        async def _cnt(where):
            async with test_db._conn.execute(
                f"SELECT count(*) FROM fills WHERE {where}"
            ) as cur:
                return (await cur.fetchone())[0]

        assert await _cnt("source='exchange_history_backfill'") == 0     # bad gone
        assert await _cnt("source='exchange_usertrades'") == 5           # true fills in
        assert await _cnt("source='binance_ws'") == 1                    # real WS preserved
        # closed_positions untouched by this script
        async with test_db._conn.execute("SELECT count(*) FROM closed_positions") as cur:
            assert (await cur.fetchone())[0] == 1

    @pytest.mark.asyncio
    async def test_collision_preserves_real_ws_fill(self, test_db):
        # A real WS fill shares tradeId "2" with a userTrades close: on --apply
        # it must be PRESERVED (not overwritten via upsert) + counted (HIGH-2).
        await test_db.upsert_fill({
            "account_id": 1, "exchange_fill_id": "2", "symbol": "SPCXUSDT",
            "side": "SELL", "direction": "LONG", "price": 110.0, "quantity": 4.0,
            "fee": 0.44, "is_close": 1, "timestamp_ms": BASE + 1000,
            "source": "binance_ws",
        })
        res = await run_refix(
            db=test_db, account_id=1, start_ms=BASE - 1000, fetch_fn=self._stub,
            symbols=["SPCXUSDT"], apply=True, verbose=False,
        )
        sym = res["per_symbol"]["SPCXUSDT"]
        assert sym["preserved"] == 1 and sym["inserted"] == 4
        async with test_db._conn.execute(
            "SELECT source FROM fills WHERE exchange_fill_id='2'"
        ) as cur:
            rows = [r[0] for r in await cur.fetchall()]
        assert rows == ["binance_ws"]   # one row, still WS (not overwritten/duped)

    @pytest.mark.asyncio
    async def test_apply_is_idempotent(self, test_db):
        await self._seed(test_db)
        await run_refix(db=test_db, account_id=1, start_ms=BASE - 1000,
                        fetch_fn=self._stub, symbols=["SPCXUSDT"], apply=True, verbose=False)
        # second run: prior userTrades rows are non-backfill -> all preserved
        res2 = await run_refix(db=test_db, account_id=1, start_ms=BASE - 1000,
                               fetch_fn=self._stub, symbols=["SPCXUSDT"], apply=True, verbose=False)
        sym = res2["per_symbol"]["SPCXUSDT"]
        assert sym["inserted"] == 0 and sym["preserved"] == 5 and sym["deleted"] == 0
        async with test_db._conn.execute(
            "SELECT count(*) FROM fills WHERE source='exchange_usertrades'"
        ) as cur:
            assert (await cur.fetchone())[0] == 5   # no duplication on re-run


# ── Task 2: gap detection + per-symbol rebuild + auto-recovery on startup ────

class TestGapSymbols:
    @pytest.mark.asyncio
    async def test_backfill_marker_selected(self, test_db):
        await _seed_backfill_fill(test_db, "AAAUSDT")
        assert "AAAUSDT" in await test_db.get_offline_gap_symbols(1, 0)

    @pytest.mark.asyncio
    async def test_exchange_history_newer_than_fills_selected(self, test_db):
        await test_db.upsert_fill({
            "account_id": 1, "exchange_fill_id": "b1", "symbol": "BBBUSDT",
            "side": "BUY", "direction": "LONG", "price": 1.0, "quantity": 1.0,
            "is_close": 0, "timestamp_ms": BASE, "source": "binance_ws",
        })
        await _insert_exchange_history(test_db, trade_key="b-eh", time_ms=BASE + 60000, symbol="BBBUSDT")
        assert "BBBUSDT" in await test_db.get_offline_gap_symbols(1, 0)

    @pytest.mark.asyncio
    async def test_online_symbol_not_selected(self, test_db):
        # exchange_history OLDER than the recorded fill, no backfill -> no gap
        await _insert_exchange_history(test_db, trade_key="c-eh", time_ms=BASE, symbol="CCCUSDT")
        await test_db.upsert_fill({
            "account_id": 1, "exchange_fill_id": "c1", "symbol": "CCCUSDT",
            "side": "BUY", "direction": "LONG", "price": 1.0, "quantity": 1.0,
            "is_close": 0, "timestamp_ms": BASE + 60000, "source": "binance_ws",
        })
        assert "CCCUSDT" not in await test_db.get_offline_gap_symbols(1, 0)

    @pytest.mark.asyncio
    async def test_cutoff_excludes_old_exchange_history(self, test_db):
        await _insert_exchange_history(test_db, trade_key="d-eh", time_ms=BASE, symbol="DDDUSDT")
        # cutoff AFTER the row -> excluded from the gap branch (and no backfill marker)
        assert "DDDUSDT" not in await test_db.get_offline_gap_symbols(1, BASE + 1_000_000)

    async def _seed_closed(self, db, symbol, *, source, calc_id=""):
        await db._conn.execute(
            "INSERT INTO closed_positions (account_id,symbol,terminal_position_id,direction,"
            "quantity,entry_price,exit_price,realized_pnl,total_fees,net_pnl,source,calc_id) "
            "VALUES (1,?,?,'LONG',1,1,1,0,0,0,?,?)",
            (symbol, f"tp-{symbol}", source, calc_id),
        )
        await db._conn.commit()

    @pytest.mark.asyncio
    async def test_protected_real_position_excluded(self, test_db):
        # gapped (backfill fill) BUT has a real WS closed_position -> EXCLUDED (H1/H2)
        await _seed_backfill_fill(test_db, "GGGUSDT")
        await self._seed_closed(test_db, "GGGUSDT", source="binance_ws")
        assert "GGGUSDT" not in await test_db.get_offline_gap_symbols(1, 0)

    @pytest.mark.asyncio
    async def test_protected_calc_linked_excluded(self, test_db):
        # gapped BUT has a calc-linked closed_position -> EXCLUDED (protect linkage)
        await _seed_backfill_fill(test_db, "HHHUSDT")
        await self._seed_closed(test_db, "HHHUSDT", source="rebuilt_from_fills", calc_id="CALC-1")
        assert "HHHUSDT" not in await test_db.get_offline_gap_symbols(1, 0)

    @pytest.mark.asyncio
    async def test_synthetic_only_symbol_still_selected(self, test_db):
        # gapped + only synthetic, unlinked closed_positions -> still recoverable
        await _seed_backfill_fill(test_db, "IIIUSDT")
        await self._seed_closed(test_db, "IIIUSDT", source="exchange_history_backfill")
        assert "IIIUSDT" in await test_db.get_offline_gap_symbols(1, 0)

    @pytest.mark.asyncio
    async def test_synth_legacy_open_marker_selected(self, test_db):
        # REGRESSION 2026-06-15: synth_legacy_open is ALSO a synthetic-recovery
        # marker -> the symbol must be selected (so userTrades supersedes it).
        await test_db.upsert_fill({
            "account_id": 1, "exchange_fill_id": "sl1", "symbol": "KKKUSDT",
            "side": "BUY", "direction": "LONG", "price": 1.0, "quantity": 1.0,
            "is_close": 0, "timestamp_ms": BASE, "source": "synth_legacy_open",
        })
        assert "KKKUSDT" in await test_db.get_offline_gap_symbols(1, 0)


class TestRebuildForSymbol:
    @pytest.mark.asyncio
    async def test_rebuilds_and_backlinks(self, test_db):
        for t in _spcx_shape("EEEUSDT"):
            await test_db.upsert_fill(user_trade_to_fill_dict(t, 1))
        await test_db._conn.execute(
            "INSERT INTO closed_positions (account_id,symbol,terminal_position_id,direction,"
            "quantity,entry_price,exit_price,realized_pnl,total_fees,net_pnl,source) "
            "VALUES (1,'EEEUSDT','stale','LONG',1,1,1,0,0,0,'exchange_history_backfill')"
        )
        await test_db._conn.commit()
        res = await test_db.rebuild_closed_positions_for_symbol(1, "EEEUSDT")
        assert res["deleted"] == 1 and res["rebuilt"] == 2
        async with test_db._conn.execute(
            "SELECT count(*) FROM closed_positions WHERE symbol='EEEUSDT' AND source='rebuilt_from_fills'"
        ) as cur:
            assert (await cur.fetchone())[0] == 2
        async with test_db._conn.execute(
            "SELECT count(*) FROM fills WHERE symbol='EEEUSDT' AND terminal_position_id<>''"
        ) as cur:
            assert (await cur.fetchone())[0] == 5   # all contributing fills back-linked

    @pytest.mark.asyncio
    async def test_preserves_operator_columns_on_rebuild(self, test_db):
        # H1: a re-rebuild must NOT drop operator/reconciler columns. The
        # synthetic tpid is deterministic, so they re-supply by tpid.
        for t in _spcx_shape("JJJUSDT"):
            await test_db.upsert_fill(user_trade_to_fill_dict(t, 1))
        await test_db.rebuild_closed_positions_for_symbol(1, "JJJUSDT")
        async with test_db._conn.execute(
            "SELECT terminal_position_id FROM closed_positions WHERE symbol='JJJUSDT' LIMIT 1"
        ) as cur:
            tpid = (await cur.fetchone())[0]
        await test_db._conn.execute(
            "UPDATE closed_positions SET close_note='op note', "
            "exit_reason='MANUAL_DISCIPLINE_BREAK', lifecycle_id='LC-1' "
            "WHERE terminal_position_id=?", (tpid,),
        )
        await test_db._conn.commit()
        await test_db.rebuild_closed_positions_for_symbol(1, "JJJUSDT")   # re-rebuild
        async with test_db._conn.execute(
            "SELECT close_note, exit_reason, lifecycle_id FROM closed_positions "
            "WHERE terminal_position_id=?", (tpid,),
        ) as cur:
            assert tuple(await cur.fetchone()) == ("op note", "MANUAL_DISCIPLINE_BREAK", "LC-1")


class TestRecoverOfflineTrades:
    @staticmethod
    def _stub(by_symbol):
        async def _f(symbol, start_ms=None, end_ms=None):
            if isinstance(by_symbol, Exception):
                raise by_symbol
            return by_symbol.get(symbol, [])
        return _f

    @pytest.mark.asyncio
    async def test_recovers_gapped_symbol(self, monkeypatch, test_db):
        await _seed_backfill_fill(test_db, "EEEUSDT")
        monkeypatch.setattr("core.exchange_income.db", test_db)
        monkeypatch.setattr("core.exchange_income.fetch_all_user_trades",
                            self._stub({"EEEUSDT": _spcx_shape("EEEUSDT")}))
        res = await recover_offline_trades(account_id=1, days=3650)
        assert res["symbols"] == 1 and res["errors"] == {}
        r = res["recovered"]["EEEUSDT"]
        assert r["fills_inserted"] == 5 and r["backfill_fills_deleted"] == 1 and r["positions_rebuilt"] == 2

        async def _cnt(where):
            async with test_db._conn.execute(f"SELECT count(*) FROM fills WHERE {where}") as cur:
                return (await cur.fetchone())[0]
        assert await _cnt("source='exchange_history_backfill'") == 0
        assert await _cnt("source='exchange_usertrades'") == 5
        async with test_db._conn.execute(
            "SELECT count(*) FROM closed_positions WHERE symbol='EEEUSDT'") as cur:
            assert (await cur.fetchone())[0] == 2

    @pytest.mark.asyncio
    async def test_idempotent_second_run(self, monkeypatch, test_db):
        await _seed_backfill_fill(test_db, "EEEUSDT")
        monkeypatch.setattr("core.exchange_income.db", test_db)
        monkeypatch.setattr("core.exchange_income.fetch_all_user_trades",
                            self._stub({"EEEUSDT": _spcx_shape("EEEUSDT")}))
        await recover_offline_trades(account_id=1, days=3650)
        res2 = await recover_offline_trades(account_id=1, days=3650)
        assert res2["symbols"] == 0   # no longer gapped -> not re-recovered

    @pytest.mark.asyncio
    async def test_collision_preserves_ws_fill(self, monkeypatch, test_db):
        await _seed_backfill_fill(test_db, "EEEUSDT")
        await test_db.upsert_fill({
            "account_id": 1, "exchange_fill_id": "2", "symbol": "EEEUSDT",
            "side": "SELL", "direction": "LONG", "price": 110.0, "quantity": 4.0,
            "fee": 0.44, "is_close": 1, "timestamp_ms": BASE + 1000, "source": "binance_ws",
        })
        monkeypatch.setattr("core.exchange_income.db", test_db)
        monkeypatch.setattr("core.exchange_income.fetch_all_user_trades",
                            self._stub({"EEEUSDT": _spcx_shape("EEEUSDT")}))
        res = await recover_offline_trades(account_id=1, days=3650)
        r = res["recovered"]["EEEUSDT"]
        assert r["fills_preserved"] == 1 and r["fills_inserted"] == 4
        async with test_db._conn.execute("SELECT source FROM fills WHERE exchange_fill_id='2'") as cur:
            assert [x[0] for x in await cur.fetchall()] == ["binance_ws"]   # not overwritten

    @pytest.mark.asyncio
    async def test_error_isolation(self, monkeypatch, test_db):
        await _seed_backfill_fill(test_db, "EEEUSDT", eid="bf-e")
        await _seed_backfill_fill(test_db, "FFFUSDT", eid="bf-f")

        async def _f(symbol, start_ms=None, end_ms=None):
            if symbol == "FFFUSDT":
                raise RuntimeError("boom")
            return _spcx_shape(symbol)
        monkeypatch.setattr("core.exchange_income.db", test_db)
        monkeypatch.setattr("core.exchange_income.fetch_all_user_trades", _f)
        res = await recover_offline_trades(account_id=1, days=3650)
        assert res["symbols"] == 2
        assert "EEEUSDT" in res["recovered"] and "FFFUSDT" in res["errors"]
        # the failed symbol's backfill fills are left intact (no partial damage)
        async with test_db._conn.execute(
            "SELECT count(*) FROM fills WHERE symbol='FFFUSDT' AND source='exchange_history_backfill'"
        ) as cur:
            assert (await cur.fetchone())[0] == 1

    @pytest.mark.asyncio
    async def test_empty_fetch_skips_delete_and_rebuild(self, monkeypatch, test_db):
        # H3: an empty/failed userTrades fetch must NOT delete backfill fills
        # (nothing to replace them with) nor rebuild — avoids data loss + thrash.
        await _seed_backfill_fill(test_db, "EEEUSDT")
        monkeypatch.setattr("core.exchange_income.db", test_db)
        monkeypatch.setattr("core.exchange_income.fetch_all_user_trades", self._stub({"EEEUSDT": []}))
        res = await recover_offline_trades(account_id=1, days=3650)
        r = res["recovered"]["EEEUSDT"]
        assert r.get("skipped_empty") is True and r["backfill_fills_deleted"] == 0
        async with test_db._conn.execute(
            "SELECT count(*) FROM fills WHERE symbol='EEEUSDT' AND source='exchange_history_backfill'"
        ) as cur:
            assert (await cur.fetchone())[0] == 1   # backfill fills left intact

    @pytest.mark.asyncio
    async def test_supersedes_synth_legacy_open(self, monkeypatch, test_db):
        # REGRESSION 2026-06-15: a prior synth_legacy_open OPEN must be
        # SUPERSEDED by userTrades, never collision-preserved (which doubled
        # opens -> broken rebuild -> 0 positions for STO/ON/JCT/...).
        await test_db.upsert_fill({
            "account_id": 1, "exchange_fill_id": "synth-1", "symbol": "EEEUSDT",
            "side": "BUY", "direction": "LONG", "price": 100.0, "quantity": 10.0,
            "is_close": 0, "timestamp_ms": BASE - 5, "source": "synth_legacy_open",
        })
        monkeypatch.setattr("core.exchange_income.db", test_db)
        monkeypatch.setattr("core.exchange_income.fetch_all_user_trades",
                            self._stub({"EEEUSDT": _spcx_shape("EEEUSDT")}))
        res = await recover_offline_trades(account_id=1, days=3650)
        r = res["recovered"]["EEEUSDT"]
        assert r["fills_preserved"] == 0          # synth open is NOT "real"
        assert r["backfill_fills_deleted"] == 1   # the synth_legacy_open fill deleted
        assert r["positions_rebuilt"] == 2        # correct (not 0 from doubled opens)

        async def _cnt(where):
            async with test_db._conn.execute(f"SELECT count(*) FROM fills WHERE {where}") as cur:
                return (await cur.fetchone())[0]
        assert await _cnt("symbol='EEEUSDT' AND source='synth_legacy_open'") == 0
        assert await _cnt("symbol='EEEUSDT' AND source='exchange_usertrades'") == 5
