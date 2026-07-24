"""
Regression tests for scripts/clean_overattributed_excursions.py
(v3.0 operator-bug #8 residue cleanup — null over-attributed exchange_history
MFE/MAE).
"""
from __future__ import annotations

import sqlite3

import pytest

from scripts.clean_overattributed_excursions import _flagged, scan, run


class TestFlagged:
    def test_spcx_over_attributed_is_flagged(self):
        # mae -284 on notional 2951 = 9.6% adverse > 8%
        assert _flagged({"mae": -284.26, "mfe": 92.1, "notional": 2951.12}, 8.0)

    def test_saga_61pct_flagged(self):
        assert _flagged({"mae": -19.4, "mfe": 1.0, "notional": 31.8}, 8.0)

    def test_normal_row_not_flagged(self):
        # mae -0.10 on notional 204 = 0.05% adverse
        assert not _flagged({"mae": -0.10, "mfe": 0.52, "notional": 204.0}, 8.0)

    def test_large_favorable_also_flagged(self):
        # over-attribution inflates MFE too
        assert _flagged({"mae": -1.0, "mfe": 300.0, "notional": 1000.0}, 8.0)

    def test_zero_notional_skipped(self):
        assert not _flagged({"mae": -999.0, "mfe": 0.0, "notional": 0.0}, 8.0)

    def test_threshold_respected(self):
        row = {"mae": -30.0, "mfe": 0.0, "notional": 300.0}  # 10% adverse
        assert _flagged(row, 8.0)
        assert not _flagged(row, 12.0)


_COLS = ("trade_key", "account_id", "symbol", "direction", "income", "notional",
         "mfe", "mae", "entry_price", "qty", "open_time", "time", "backfill_completed")


def _make_db(tmp_path):
    db = str(tmp_path / "eh.db")
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE exchange_history (
        trade_key TEXT PRIMARY KEY, account_id INTEGER, symbol TEXT, direction TEXT,
        income REAL, notional REAL, mfe REAL, mae REAL, entry_price REAL, qty REAL,
        open_time INTEGER, time INTEGER, backfill_completed INTEGER DEFAULT 1)""")
    rows = [
        # over-attributed SPCX (2 share open_time), flagged
        ("s1", 1, "SPCXUSDT", "SHORT", -6.96, 2951.12, 92.1, -284.26, 161.06, 18.28, 1000, 2000, 1),
        ("s2", 1, "SPCXUSDT", "SHORT", -6.61, 2805.83, 87.6, -270.27, 161.06, 17.38, 1000, 2000, 1),
        # normal row, NOT flagged
        ("n1", 1, "BTCUSDT",  "LONG",   5.25,  204.0,   0.52,  -0.10, 68000.0, 0.003, 500, 1500, 1),
        # SAGA 61% adverse, flagged, single (no sibling)
        ("g1", 1, "SAGAUSDT", "SHORT", -0.5,   31.8,    1.0,  -19.4,  2.0,     15.9,  3000, 3500, 1),
    ]
    conn.executemany(
        f"INSERT INTO exchange_history ({','.join(_COLS)}) "
        f"VALUES ({','.join('?' * len(_COLS))})", rows)
    conn.commit(); conn.close()
    return db


def _fetch(db, tk):
    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM exchange_history WHERE trade_key=?", (tk,)).fetchone()
    conn.close()
    return dict(r) if r else None


class TestScan:
    def test_flags_over_attributed_only(self, tmp_path):
        db = _make_db(tmp_path)
        conn = sqlite3.connect(db)
        flagged = scan(conn, 8.0)
        conn.close()
        keys = {r["trade_key"] for r in flagged}
        assert keys == {"s1", "s2", "g1"}      # not n1
        # sibling count surfaced for the shared-open_time SPCX pair
        s1 = next(r for r in flagged if r["trade_key"] == "s1")
        assert s1["_siblings"] == 2
        g1 = next(r for r in flagged if r["trade_key"] == "g1")
        assert g1["_siblings"] == 1


class TestDryRunAndApply:
    def test_dry_run_makes_no_changes(self, tmp_path):
        db = _make_db(tmp_path)
        before = {tk: _fetch(db, tk) for tk in ("s1", "s2", "n1", "g1")}
        res = run(db_path=db, apply=False, verbose=False)
        after = {tk: _fetch(db, tk) for tk in ("s1", "s2", "n1", "g1")}
        assert res["applied"] is False and res["flagged"] == 3
        assert before == after

    def test_apply_nulls_flagged_leaves_rest(self, tmp_path):
        db = _make_db(tmp_path)
        res = run(db_path=db, apply=True, verbose=False)
        assert res["applied"] is True and res["affected"] == 3
        # flagged rows nulled + backfill reset
        for tk in ("s1", "s2", "g1"):
            r = _fetch(db, tk)
            assert r["mfe"] == 0 and r["mae"] == 0 and r["backfill_completed"] == 0
        # normal row untouched
        n1 = _fetch(db, "n1")
        assert n1["mae"] == pytest.approx(-0.10) and n1["mfe"] == pytest.approx(0.52)

    def test_apply_preserves_income_and_prices(self, tmp_path):
        """Only the excursion columns were wrong — income/notional/prices stay."""
        db = _make_db(tmp_path)
        run(db_path=db, apply=True, verbose=False)
        s1 = _fetch(db, "s1")
        assert s1["income"] == pytest.approx(-6.96)
        assert s1["notional"] == pytest.approx(2951.12)
        assert s1["entry_price"] == pytest.approx(161.06)

    def test_idempotent(self, tmp_path):
        db = _make_db(tmp_path)
        run(db_path=db, apply=True, verbose=False)
        res2 = run(db_path=db, apply=True, verbose=False)
        assert res2["flagged"] == 0      # nulled rows no longer match (mfe!=0 OR mae!=0)

    def test_threshold_widens_selection(self, tmp_path):
        db = _make_db(tmp_path)
        # min-pct 12 still flags SPCX (9.6%? no) — check the count changes sanely
        res_hi = run(db_path=db, min_pct=50.0, apply=False, verbose=False)
        # only SAGA (61%) exceeds 50%
        assert res_hi["flagged"] == 1
