"""v3.0 P5 (Analytics) backend pins.

Handler-direct + F5-safe: no TestClient anywhere in this file — the shared
TestClient's lifespan touches live data (F5) and write-endpoints through it
mutate the operator's DBs. Handlers are awaited directly with every
query-param default supplied explicitly (FastAPI defaults are sentinels at
the Python level); DB readers are monkeypatched on the `db` singleton, and
the two new AnalyticsMixin queries are pinned against a throwaway aiosqlite
DB built from a mini-schema (test_slippage_actual pattern) — never the
DatabaseManager constructor (fresh-DB init runs the credential seeds).

Covers:
- G-O4 /api/analytics/execution: row shaping (slippage_cost side
  normalization, time_to_fill, link status parity with the P4 drawer rule)
  + summary aggregates + the _json_safe non-finite guard.
- G-O4 /api/analytics/distributions: account-tz hour/dow bucketing,
  hold_min None on unknown open_time, r_histogram ride-along.
- The 8 ?format=json doors on the existing analytics fragments.
- The _json_safe wrap added to /api/analytics/equity_ohlc (F2 fold).
- AnalyticsMixin.get_execution_quality: JOIN correctness (ptl_calc_id NULL
  discrimination, orders join, window + limit).
- AnalyticsMixin.get_trade_distribution_series: funding/transfer exclusion,
  NO mfe/mae filter (the get_mfe_mae_series contrast).
"""
from __future__ import annotations

import asyncio
import json as _jsonlib
import math
from datetime import datetime, timedelta, timezone

import pytest

import api.routes_analytics as ra
from core.database import db
from core.state import app_state


def _body(resp):
    return _jsonlib.loads(resp.body)


def _run(coro):
    return asyncio.run(coro)


# Fixed clock anchors (no wall-clock coupling in assertions).
_PT_ISO = "2026-01-01T00:00:00+00:00"          # pre_trade timestamp
_PT_MS = 1_767_225_600_000                       # the same instant in epoch ms
_FILL_MS = _PT_MS + 60_000                       # fill 60 s later (inside window)


def _exec_row(**over):
    """A raw get_execution_quality row (post-JOIN dict), entry-fill default."""
    row = {
        "fill_id": 1, "exchange_fill_id": "X1", "timestamp_ms": _FILL_MS,
        "symbol": "BTCUSDT", "side": "BUY", "direction": "LONG",
        "price": 100.0, "quantity": 1.0, "fee": 0.01, "fee_asset": "USDT",
        "role": "maker", "is_close": 0, "calc_id": "C1",
        "fill_type": "entry", "slippage_actual": 0.001,
        "exec_link_confirmed": 0,
        "ptl_calc_id": "C1", "est_entry": 100.0, "est_average": 100.0,
        "est_slippage": 0.0005, "plan_tp": 110.0, "plan_sl": 95.0,
        "pretrade_ts": _PT_ISO, "link_window_override": None,
        "order_type": "MARKET", "order_created_ms": _FILL_MS - 500,
    }
    row.update(over)
    return row


class TestExecutionEndpoint:
    def _call(self, monkeypatch, raw, window=None):
        async def fake_exec(*a, **k):
            return raw

        async def fake_window(_aid):
            return window

        monkeypatch.setattr(db, "get_execution_quality", fake_exec)
        monkeypatch.setattr(db, "get_account_link_window_seconds", fake_window)
        return _body(_run(ra.api_analytics_execution(limit=500)))

    def test_entry_buy_row_shape_and_link(self, monkeypatch):
        out = self._call(monkeypatch, [_exec_row()])
        row = out["rows"][0]
        # BUY keeps the raw sign: +0.001 actual → +0.001 cost (worse than plan)
        assert row["slippage_cost"] == pytest.approx(0.001)
        assert row["est_slippage"] == pytest.approx(0.0005)
        assert row["time_to_fill_ms"] == 500
        # MARKET entry inside the window → auto-linked
        assert row["link_status"] == "linked"
        assert row["link_confirmed"] is False
        assert out["summary"]["linked"] == 1
        assert out["summary"]["calc_backed"] == 1

    def test_sell_side_flips_slippage_cost(self, monkeypatch):
        out = self._call(monkeypatch, [
            _exec_row(side="SELL", direction="SHORT", slippage_actual=0.002),
        ])
        # SELL: fill printing ABOVE expected (+raw) is price improvement → −cost
        assert out["rows"][0]["slippage_cost"] == pytest.approx(-0.002)

    def test_close_and_unlinked_fills_blank_status(self, monkeypatch):
        out = self._call(monkeypatch, [
            _exec_row(fill_id=1, is_close=1),
            _exec_row(fill_id=2, calc_id=None, ptl_calc_id=None,
                      fill_type=None, slippage_actual=None),
        ])
        r1, r2 = out["rows"]
        assert r1["link_status"] == "" and r2["link_status"] == ""
        # no pre_trade row → est is None, not the NOT-NULL-DEFAULT-0 artifact
        assert r2["est_slippage"] is None
        assert r2["slippage_cost"] is None
        assert out["summary"]["by_fill_type"]["unclassified"] == 1

    def test_negative_ttf_guard_and_missing_order(self, monkeypatch):
        out = self._call(monkeypatch, [
            _exec_row(fill_id=1, order_created_ms=_FILL_MS + 999),  # clock skew
            _exec_row(fill_id=2, order_created_ms=None, order_type=None),
        ])
        assert out["rows"][0]["time_to_fill_ms"] is None
        assert out["rows"][1]["time_to_fill_ms"] is None
        assert out["summary"]["by_order_type"]["unknown"] == 1

    def test_bias_math_entry_only(self, monkeypatch):
        out = self._call(monkeypatch, [
            _exec_row(fill_id=1, est_slippage=0.0010, slippage_actual=0.0020),
            _exec_row(fill_id=2, est_slippage=0.0020, slippage_actual=0.0010),
            # tp fill is excluded from the bias sample AND carries no est
            # (audit L-2: entry impact estimate never pairs with an exit)
            _exec_row(fill_id=3, fill_type="tp", est_slippage=0.5,
                      slippage_actual=0.5),
        ])
        s = out["summary"]
        assert s["entry_n"] == 2
        assert s["avg_est_bp"] == pytest.approx(15.0)
        assert s["avg_cost_bp"] == pytest.approx(15.0)
        # Audit H-1: slippage_actual is a RESIDUAL vs the impact-adjusted
        # prediction (effective_entry), so bias == avg residual — NOT
        # avg_cost − avg_est (a perfect model must read 0, not −avg_est).
        assert s["bias_bp"] == pytest.approx(15.0)
        tp_row = [r for r in out["rows"] if r["fill_type"] == "tp"][0]
        assert tp_row["est_slippage"] is None

    def test_non_finite_slippage_nulled(self, monkeypatch):
        out = self._call(monkeypatch, [
            _exec_row(slippage_actual=float("nan"), est_slippage=float("inf")),
        ])
        row = out["rows"][0]
        assert row["slippage_actual"] is None
        assert row["est_slippage"] is None

    def test_window_reject_reports_unlinked(self, monkeypatch):
        # LIMIT order (price-matched) 100 days after the plan → hard reject.
        stale = _exec_row(order_type="LIMIT",
                          timestamp_ms=_PT_MS + 100 * 86_400_000)
        out = self._call(monkeypatch, [stale], window=60)
        assert out["rows"][0]["link_status"] == "unlinked"


class TestDistributionsEndpoint:
    def _call(self, monkeypatch, series, r_values):
        async def fake_series(*a, **k):
            return series

        async def fake_r(*a, **k):
            return r_values

        monkeypatch.setattr(db, "get_trade_distribution_series", fake_series)
        monkeypatch.setattr(db, "get_r_multiples", fake_r)
        monkeypatch.setattr(ra, "get_account_tz",
                            lambda _aid: timezone(timedelta(hours=7)))
        return _body(_run(ra.api_analytics_distributions(
            month="", all="1", period="", offset=0)))

    def test_tz_bucketing_hold_and_histogram(self, monkeypatch):
        # 2026-01-01 23:30 UTC = 2026-01-02 06:30 +07 (Friday, weekday 4)
        close_ms = int(datetime(2026, 1, 1, 23, 30,
                                tzinfo=timezone.utc).timestamp() * 1000)
        series = [
            {"trade_key": "t1", "symbol": "BTCUSDT", "direction": "LONG",
             "income": 5.0, "time": close_ms, "open_time": close_ms - 90 * 60_000},
            {"trade_key": "t2", "symbol": "ETHUSDT", "direction": "SHORT",
             "income": -2.0, "time": close_ms, "open_time": 0},
        ]
        out = self._call(monkeypatch, series, [1.5, -1.0])
        t1, t2 = out["trades"]
        assert t1["hour"] == 6 and t1["dow"] == 4
        assert t1["hold_min"] == pytest.approx(90.0)
        assert t2["hold_min"] is None          # unknown open_time
        assert out["count"] == 2
        assert len(out["r_histogram"]) == 8    # the shared 8-bin shape
        assert out["r_values"] == [1.5, -1.0]
        assert out["period_label"] == "All Time"


class _Snap:
    """Swap app_state.positions (and optionally total_equity) temporarily."""

    def __init__(self, positions=None, total_equity=None):
        self._positions = positions
        self._equity = total_equity

    def __enter__(self):
        self._old_pos = app_state.positions
        if self._positions is not None:
            app_state.positions = self._positions
        if self._equity is not None:
            self._old_eq = app_state.account_state.total_equity
            app_state.account_state.total_equity = self._equity
        return self

    def __exit__(self, *exc):
        app_state.positions = self._old_pos
        if self._equity is not None:
            app_state.account_state.total_equity = self._old_eq
        return False


class TestFragmentDoors:
    """The 8 ?format=json doors return the fragment's context as JSON."""

    @pytest.fixture(autouse=True)
    def _tz(self, monkeypatch):
        monkeypatch.setattr(ra, "get_account_tz",
                            lambda _aid: timezone(timedelta(hours=7)))

    def test_overview_door(self, monkeypatch):
        async def stats(*a, **k):
            return {"total_trades": 3, "total_pnl": 1.5}

        async def bounds(*a, **k):
            return {"initial_equity": 100.0, "final_equity": 101.5,
                    "max_drawdown": 0.02}

        async def pairs(*a, **k):
            return ["BTCUSDT"]

        async def cum(*a, **k):
            return {"total_pnl": 1.5}

        async def daily(*a, **k):
            return [{"day": "2026-01-01", "total_equity": 101.5,
                     "daily_pnl": 1.5, "daily_pnl_percent": 1.5,
                     "drawdown": 0.0}]

        async def mfe(*a, **k):
            return []

        async def rvals(*a, **k):
            return [1.0]

        monkeypatch.setattr(db, "get_journal_stats", stats)
        monkeypatch.setattr(db, "get_equity_period_boundaries", bounds)
        monkeypatch.setattr(db, "get_most_traded_pairs", pairs)
        monkeypatch.setattr(db, "get_cumulative_pnl", cum)
        monkeypatch.setattr(db, "get_daily_equity_series", daily)
        monkeypatch.setattr(db, "get_mfe_mae_series", mfe)
        monkeypatch.setattr(db, "get_r_multiples", rvals)
        out = _body(_run(ra.frag_analytics_overview(
            request=None, month="", all="1", period="", offset=0,
            format="json")))
        assert out["stats"]["total_trades"] == 3
        assert out["boundaries"]["max_drawdown"] == 0.02
        assert out["daily_equity"][0]["total_equity"] == 101.5
        assert set(out) >= {"stats", "boundaries", "top_pairs", "cumulative",
                            "ratios", "trading_days", "period_label", "month",
                            "daily_equity"}

    def test_calendar_door(self, monkeypatch):
        async def daily(*a, **k):
            return [{"day": "2026-01-05", "total_equity": 100.0,
                     "daily_pnl": 2.5, "daily_pnl_percent": 2.5,
                     "drawdown": 0.0}]

        async def dstats(*a, **k):
            return {"2026-01-05": {"trades": 2, "volume": 100.0,
                                   "win_rate": 0.5}}

        monkeypatch.setattr(db, "get_daily_equity_series", daily)
        monkeypatch.setattr(db, "get_daily_trade_stats", dstats)
        out = _body(_run(ra.frag_analytics_calendar(
            request=None, month="2026-01", all="", format="json")))
        assert out["month_label"] == "January 2026"
        assert out["prev_month"] == "2025-12" and out["next_month"] == "2026-02"
        assert out["trading_days"] == 1
        assert out["best_day"] == 2.5
        # grid cells carry the JSON-safe date string
        flat = [c for wk in out["calendar_grid"] for c in wk if c["day"]]
        assert any(c["date"] == "2026-01-05" and c["pnl"] == 2.5 for c in flat)

    def test_pairs_door(self, monkeypatch):
        async def rows(*a, **k):
            return [{"symbol": "BTCUSDT", "total": 5, "pnl_total": 2.0},
                    {"symbol": "ETHUSDT", "total": 9, "pnl_total": -1.0}]

        monkeypatch.setattr(db, "get_traded_pairs_stats", rows)
        out = _body(_run(ra.frag_analytics_pairs(
            request=None, month="", all="1", sort_by="total",
            sort_dir="DESC", period="", offset=0, format="json")))
        assert [r["symbol"] for r in out["rows"]] == ["ETHUSDT", "BTCUSDT"]
        assert out["sort_by"] == "total" and out["sort_dir"] == "DESC"

    def test_excursions_door(self, monkeypatch):
        async def trades(*a, **k):
            return [{"trade_key": "t", "symbol": "BTCUSDT",
                     "direction": "LONG", "income": 3.0, "notional": 100.0,
                     "mfe": 4.0, "mae": -1.0, "entry_price": 10.0,
                     "qty": 1.0, "hold_ms": 60000}]

        monkeypatch.setattr(db, "get_mfe_mae_series", trades)
        out = _body(_run(ra.frag_analytics_excursions(
            request=None, month="", all="1", dir="all", period="",
            offset=0, format="json")))
        assert out["avg_mfe"] == 4.0 and out["avg_mae_abs"] == 1.0
        assert out["pct_favorable"] == 100.0
        assert out["scatter_data"][0] == {"x": 4.0, "y": -1.0, "z": 3.0,
                                          "sym": "BTCUSDT"}

    def test_r_multiples_door(self, monkeypatch):
        async def rvals(*a, **k):
            return [2.0, -1.0, 0.5]

        monkeypatch.setattr(db, "get_r_multiples", rvals)
        out = _body(_run(ra.frag_analytics_r_multiples(
            request=None, month="", all="1", period="", offset=0,
            format="json")))
        assert out["r_values"] == [2.0, -1.0, 0.5]
        assert out["r_stats"]["count"] == 3
        assert len(out["histogram"]) == 8

    def test_var_door_has_data_gate(self, monkeypatch):
        async def daily(*a, **k):
            return [{"day": f"2026-01-{i:02d}", "total_equity": 100.0 + i,
                     "daily_pnl": 0, "daily_pnl_percent": 0, "drawdown": 0}
                    for i in range(1, 11)]  # 10 pts → 9 returns → below gate

        monkeypatch.setattr(db, "get_daily_equity_series", daily)
        with _Snap(total_equity=110.0):
            out = _body(_run(ra.frag_analytics_var(
                request=None, month="", all="1", period="", offset=0,
                format="json")))
        assert out["has_data"] is False       # ≥20-returns VaR guard mirrored
        assert out["cur_equity"] == 110.0
        assert len(out["returns"]) == 9

    def test_funding_door_empty_positions(self):
        with _Snap(positions=[]):
            out = _body(_run(ra.frag_analytics_funding(
                request=None, format="json")))
        # superset pin — additive fields must not go red (audit NIT)
        assert out["rows"] == []
        assert out["total_8h"] == 0 and out["total_day"] == 0

    def test_beta_door_empty_positions(self):
        with _Snap(positions=[]):
            out = _body(_run(ra.frag_analytics_beta(
                request=None, format="json")))
        assert out["rows"] == [] and out["port_beta"] == 0.0
        assert out["sector_totals"] == {}


class TestEquityOhlcJsonSafe:
    def test_nan_candle_nulled(self, monkeypatch):
        async def backfill(*a, **k):
            return None

        async def candles(*a, **k):
            return [{"x": 1, "o": float("nan"), "h": 2.0, "l": 1.0,
                     "c": 1.5, "cf": 0.0}]

        monkeypatch.setattr(ra, "_maybe_backfill_equity", backfill)
        monkeypatch.setattr(ra, "_inject_live_equity", lambda c: None)
        monkeypatch.setattr(db, "get_equity_ohlc", candles)
        out = _body(_run(ra.api_analytics_equity_ohlc(tf="1M")))
        assert out["candles"][0]["o"] is None      # F2: no bare NaN token
        assert out["candles"][0]["h"] == 2.0
        assert out["tf"] == "1M"


# ─── AnalyticsMixin pins against a throwaway aiosqlite DB ────────────────────

_MINI_SCHEMA = """
CREATE TABLE fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER, exchange_fill_id TEXT, exchange_order_id TEXT,
    symbol TEXT, side TEXT, direction TEXT, price REAL, quantity REAL,
    fee REAL, fee_asset TEXT, role TEXT, is_close INTEGER,
    realized_pnl REAL, source TEXT, timestamp_ms INTEGER,
    calc_id TEXT, fill_type TEXT, slippage_actual REAL,
    exec_link_confirmed INTEGER DEFAULT 0
);
CREATE TABLE pre_trade_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER, calc_id TEXT, timestamp TEXT, ticker TEXT,
    average REAL, effective_entry REAL, est_slippage REAL,
    tp_price REAL, sl_price REAL, link_window_seconds_override INTEGER
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER, exchange_order_id TEXT, order_type TEXT,
    created_at_ms INTEGER
);
CREATE TABLE exchange_history (
    trade_key TEXT PRIMARY KEY, account_id INTEGER, symbol TEXT,
    income_type TEXT, income REAL, direction TEXT,
    time INTEGER, open_time INTEGER, mfe REAL, mae REAL
);
"""


@pytest.fixture()
def mini_db(tmp_path):
    """AnalyticsMixin host over a throwaway aiosqlite DB (mini-schema)."""
    aiosqlite = pytest.importorskip("aiosqlite")
    from core.db_analytics import AnalyticsMixin

    class _Host(AnalyticsMixin):
        def __init__(self):
            self._conn = None

    host = _Host()
    path = str(tmp_path / "p5_mini.db")

    async def _setup():
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        await conn.executescript(_MINI_SCHEMA)
        await conn.commit()
        return conn

    host._conn = asyncio.run(_setup())
    yield host
    asyncio.run(host._conn.close())


class TestExecutionQualityQuery:
    def _seed(self, host):
        async def go():
            c = host._conn
            await c.execute(
                "INSERT INTO pre_trade_log (account_id, calc_id, timestamp,"
                " ticker, average, effective_entry, est_slippage, tp_price,"
                " sl_price, link_window_seconds_override)"
                " VALUES (1,'C1',?, 'BTCUSDT', 100.0, 100.5, 0.0007,"
                " 110.0, 95.0, NULL)", (_PT_ISO,))
            await c.execute(
                "INSERT INTO orders (account_id, exchange_order_id,"
                " order_type, created_at_ms) VALUES (1,'O1','MARKET',?)",
                (_FILL_MS - 250,))
            # calc-backed fill w/ pre_trade + order
            await c.execute(
                "INSERT INTO fills (account_id, exchange_fill_id,"
                " exchange_order_id, symbol, side, direction, price,"
                " quantity, fee, fee_asset, role, is_close, timestamp_ms,"
                " calc_id, fill_type, slippage_actual)"
                " VALUES (1,'F1','O1','BTCUSDT','BUY','LONG',100.6,1.0,"
                " 0.01,'USDT','maker',0,?, 'C1','entry',0.001)", (_FILL_MS,))
            # orphan fill: no calc, no order row
            await c.execute(
                "INSERT INTO fills (account_id, exchange_fill_id,"
                " exchange_order_id, symbol, side, direction, price,"
                " quantity, fee, fee_asset, role, is_close, timestamp_ms,"
                " calc_id, fill_type, slippage_actual)"
                " VALUES (1,'F2','O_MISSING','ETHUSDT','SELL','SHORT',"
                " 50.0,2.0,0.02,'USDT','taker',1,?, NULL,NULL,NULL)",
                (_FILL_MS + 1,))
            # other account — must not leak
            await c.execute(
                "INSERT INTO fills (account_id, exchange_fill_id, symbol,"
                " side, direction, price, quantity, fee, fee_asset, role,"
                " is_close, timestamp_ms, calc_id)"
                " VALUES (2,'F3','X','BUY','LONG',1.0,1.0,0,'USDT','maker',"
                " 0,?, NULL)", (_FILL_MS,))
            await c.commit()
        asyncio.run(go())

    def test_join_and_null_discrimination(self, mini_db):
        self._seed(mini_db)
        rows = asyncio.run(mini_db.get_execution_quality(account_id=1))
        assert len(rows) == 2                      # account 2 excluded
        by_id = {r["exchange_fill_id"]: r for r in rows}
        linked = by_id["F1"]
        assert linked["ptl_calc_id"] == "C1"
        assert linked["est_entry"] == 100.5
        assert linked["est_slippage"] == 0.0007
        assert linked["order_type"] == "MARKET"
        assert linked["order_created_ms"] == _FILL_MS - 250
        orphan = by_id["F2"]
        assert orphan["ptl_calc_id"] is None       # no pre_trade row
        assert orphan["est_slippage"] is None
        assert orphan["order_type"] is None        # no orders row

    def test_window_and_limit(self, mini_db):
        self._seed(mini_db)
        rows = asyncio.run(mini_db.get_execution_quality(
            from_ms=_FILL_MS + 1, to_ms=_FILL_MS + 10, account_id=1))
        assert [r["exchange_fill_id"] for r in rows] == ["F2"]
        rows = asyncio.run(mini_db.get_execution_quality(
            account_id=1, limit=1))
        assert len(rows) == 1
        assert rows[0]["exchange_fill_id"] == "F2"  # newest-first

    def test_from_ms_only_means_since(self, mini_db):
        # Audit M-1: from_ms without to_ms must mean "since from_ms",
        # not the empty [from_ms, 0] window.
        self._seed(mini_db)
        rows = asyncio.run(mini_db.get_execution_quality(
            from_ms=_FILL_MS, account_id=1))
        assert len(rows) == 2

    def test_blank_order_id_never_joins(self, mini_db):
        # Audit L-3: a fills row with exchange_order_id='' must not inherit
        # order metadata from a hypothetical ''-keyed orders row.
        self._seed(mini_db)

        async def go():
            c = mini_db._conn
            await c.execute(
                "INSERT INTO orders (account_id, exchange_order_id,"
                " order_type, created_at_ms) VALUES (1,'','LIMIT',123)")
            await c.execute(
                "INSERT INTO fills (account_id, exchange_fill_id,"
                " exchange_order_id, symbol, side, direction, price,"
                " quantity, fee, fee_asset, role, is_close, timestamp_ms,"
                " calc_id) VALUES (1,'F4','','SOLUSDT','BUY','LONG',1.0,"
                " 1.0,0,'USDT','maker',0,?,NULL)", (_FILL_MS + 2,))
            await c.commit()
        asyncio.run(go())
        rows = asyncio.run(mini_db.get_execution_quality(account_id=1))
        f4 = {r["exchange_fill_id"]: r for r in rows}["F4"]
        assert f4["order_type"] is None
        assert f4["order_created_ms"] is None


class TestTradeDistributionQuery:
    def test_excludes_funding_keeps_flat_excursions(self, mini_db):
        async def go():
            c = mini_db._conn
            rows = [
                ("t1", 1, "BTCUSDT", "REALIZED_PNL", 5.0, "LONG",
                 _FILL_MS, _FILL_MS - 60_000, 0.0, 0.0),   # flat mfe/mae KEPT
                ("t2", 1, "BTCUSDT", "FUNDING_FEE", -0.1, "LONG",
                 _FILL_MS, 0, 0.0, 0.0),                    # excluded
                ("t3", 1, "ETHUSDT", "TRANSFER", 100.0, "",
                 _FILL_MS, 0, 0.0, 0.0),                    # excluded
                ("t4", 2, "BTCUSDT", "REALIZED_PNL", 1.0, "LONG",
                 _FILL_MS, 0, 0.0, 0.0),                    # other account
            ]
            await c.executemany(
                "INSERT INTO exchange_history (trade_key, account_id,"
                " symbol, income_type, income, direction, time, open_time,"
                " mfe, mae) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            await c.commit()
        asyncio.run(go())
        out = asyncio.run(mini_db.get_trade_distribution_series(
            0, _FILL_MS + 10, account_id=1))
        assert [r["trade_key"] for r in out] == ["t1"]
        assert out[0]["income"] == 5.0
        assert out[0]["open_time"] == _FILL_MS - 60_000
