"""
Regression tests for scripts/clean_phantom_equity_snapshots.py
(v3.0 operator-bug #1 residue cleanup).

Built off the exact live shapes the detector was designed against:
- phantom: total_equity == balance_usdt, unrealized dropped (correct = bal+un)
- ok flat: total_equity == balance_usdt, unrealized == 0 (no position)
- ok open: total_equity == balance_usdt + unrealized (mark-tick row)
- anomaly: identity violated some OTHER way (old balance_usdt=0 row where
  total_equity is actually correct; must NOT be touched)
"""
from __future__ import annotations

import sqlite3

import pytest

from scripts.clean_phantom_equity_snapshots import (
    classify, corrected_row, run,
)


# ── the classifier ───────────────────────────────────────────────────────────

class TestClassify:
    def test_phantom_row(self):
        # live shape: id 128158, te==bal==278.408, un=29.0679
        assert classify({
            "total_equity": 278.408, "balance_usdt": 278.408,
            "total_unrealized": 29.0679,
        }) == "phantom"

    def test_flat_open_pnl_zero_is_ok(self):
        """te==bal with NO open position is a correct flat row, not phantom."""
        assert classify({
            "total_equity": 300.0, "balance_usdt": 300.0,
            "total_unrealized": 0.0,
        }) == "ok"

    def test_correct_open_row_is_ok(self):
        # live shape: te = bal + un
        assert classify({
            "total_equity": 307.5415, "balance_usdt": 278.408,
            "total_unrealized": 29.1335,
        }) == "ok"

    def test_capture_jitter_is_ok_not_anomaly(self):
        """te ~ bal+un within a few cents (fields read microseconds apart)."""
        assert classify({
            "total_equity": 83.181, "balance_usdt": 80.4945,
            "total_unrealized": 2.6402,
        }) == "ok"

    def test_old_zero_balance_row_is_anomaly_not_phantom(self):
        """Old rows with balance_usdt=0 where total_equity is CORRECT — the
        identity fails but total_equity must not be rewritten."""
        assert classify({
            "total_equity": 84.4821, "balance_usdt": 0.0,
            "total_unrealized": 0.0,
        }) == "anomaly"

    def test_null_fields_are_anomaly(self):
        assert classify({
            "total_equity": 100.0, "balance_usdt": None,
            "total_unrealized": None,
        }) == "anomaly"

    def test_sub_cent_unrealized_still_phantom_but_tiny(self):
        r = {"total_equity": 100.0, "balance_usdt": 100.0, "total_unrealized": 0.02}
        assert classify(r) == "phantom"


# ── the correction formula (must match the engine) ───────────────────────────

class TestCorrectedRow:
    def test_recovers_true_equity(self):
        r = {"total_equity": 278.408, "balance_usdt": 278.408,
             "total_unrealized": 29.0679, "bod_equity": 307.0}
        new_te, _, _ = corrected_row(r)
        assert new_te == pytest.approx(307.4759)

    def test_daily_pnl_uses_engine_formula(self):
        # engine: daily_pnl = total_equity - bod_eq ; bod_eq = bod_equity(>0)
        r = {"total_equity": 278.408, "balance_usdt": 278.408,
             "total_unrealized": 29.0679, "bod_equity": 307.0}
        new_te, new_dp, new_pct = corrected_row(r)
        assert new_dp == pytest.approx(new_te - 307.0)
        assert new_pct == pytest.approx((new_te - 307.0) / 307.0)

    def test_bod_zero_falls_back_to_new_equity(self):
        r = {"total_equity": 50.0, "balance_usdt": 50.0,
             "total_unrealized": 5.0, "bod_equity": 0.0}
        new_te, new_dp, new_pct = corrected_row(r)
        assert new_te == pytest.approx(55.0)
        assert new_dp == pytest.approx(0.0)      # bod_eq defaults to new_te
        assert new_pct == pytest.approx(0.0)


# ── end-to-end against a synthetic DB ────────────────────────────────────────

_COLS = ("id", "account_id", "snapshot_ts", "total_equity", "balance_usdt",
         "total_unrealized", "bod_equity", "daily_pnl", "daily_pnl_percent")


def _make_db(tmp_path):
    db = str(tmp_path / "snap.db")
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE account_snapshots (
        id INTEGER PRIMARY KEY, account_id INTEGER, snapshot_ts TEXT,
        total_equity REAL, balance_usdt REAL, total_unrealized REAL,
        bod_equity REAL, daily_pnl REAL, daily_pnl_percent REAL)""")
    rows = [
        # id, aid, ts,          te,      bal,     un,     bod,   dp,     dpp
        (1, 1, "2026-07-23T10:00:00", 307.54, 278.41, 29.13, 307.0,  0.54, 0.0017),  # ok open
        (2, 1, "2026-07-23T10:01:00", 278.41, 278.41, 29.07, 307.0, -28.59, -0.09),  # PHANTOM
        (3, 1, "2026-07-23T10:02:00", 300.00, 300.00,  0.0,  300.0,  0.0,   0.0),     # ok flat
        (4, 1, "2026-07-23T10:03:00", 278.41, 278.41, 28.99, 307.0, -28.59, -0.09),  # PHANTOM
        (5, 1, "2026-03-28T19:11:41",  84.48,   0.0,   0.0,   84.0,  0.48,  0.005),   # anomaly (old)
        (6, 2, "2026-07-23T10:00:00", 100.00, 100.00, 10.0,  100.0,  0.0,   0.0),     # PHANTOM acct 2
    ]
    conn.executemany(
        f"INSERT INTO account_snapshots ({','.join(_COLS)}) "
        f"VALUES ({','.join('?' * len(_COLS))})", rows)
    conn.commit()
    conn.close()
    return db


def _fetch(db, id_):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM account_snapshots WHERE id=?", (id_,)).fetchone()
    conn.close()
    return dict(r) if r else None


class TestDryRunMakesNoChanges:
    def test_dry_run_leaves_db_untouched(self, tmp_path):
        db = _make_db(tmp_path)
        before = [_fetch(db, i) for i in range(1, 7)]
        res = run(db_path=db, mode="correct", apply=False, verbose=False)
        after = [_fetch(db, i) for i in range(1, 7)]
        assert res["applied"] is False
        assert res["phantom"] == 3          # ids 2, 4, 6
        assert before == after


class TestCorrectMode:
    def test_corrects_only_phantom_rows(self, tmp_path):
        db = _make_db(tmp_path)
        res = run(db_path=db, mode="correct", apply=True, verbose=False)
        assert res["applied"] is True and res["affected"] == 3

        # phantom id=2 recovered to bal+un
        assert _fetch(db, 2)["total_equity"] == pytest.approx(278.41 + 29.07)
        # daily_pnl recomputed off bod 307
        assert _fetch(db, 2)["daily_pnl"] == pytest.approx((278.41 + 29.07) - 307.0)

    def test_leaves_ok_and_anomaly_rows_intact(self, tmp_path):
        db = _make_db(tmp_path)
        ok_before = _fetch(db, 1)
        anomaly_before = _fetch(db, 5)
        flat_before = _fetch(db, 3)
        run(db_path=db, mode="correct", apply=True, verbose=False)
        assert _fetch(db, 1) == ok_before
        assert _fetch(db, 5) == anomaly_before      # old zero-balance row untouched
        assert _fetch(db, 3) == flat_before

    def test_account_scope(self, tmp_path):
        db = _make_db(tmp_path)
        res = run(db_path=db, mode="correct", account_id=2, apply=True, verbose=False)
        assert res["affected"] == 1                 # only id=6
        assert _fetch(db, 6)["total_equity"] == pytest.approx(110.0)
        assert _fetch(db, 2)["total_equity"] == pytest.approx(278.41)  # acct1 untouched

    def test_correcting_is_idempotent(self, tmp_path):
        """A corrected row is no longer te==bal, so a second pass is a no-op."""
        db = _make_db(tmp_path)
        run(db_path=db, mode="correct", apply=True, verbose=False)
        res2 = run(db_path=db, mode="correct", apply=True, verbose=False)
        assert res2["phantom"] == 0


class TestDeleteMode:
    def test_deletes_only_phantom_rows(self, tmp_path):
        db = _make_db(tmp_path)
        res = run(db_path=db, mode="delete", apply=True, verbose=False)
        assert res["affected"] == 3
        assert _fetch(db, 2) is None and _fetch(db, 4) is None and _fetch(db, 6) is None
        # ok / flat / anomaly survive
        assert _fetch(db, 1) is not None
        assert _fetch(db, 3) is not None
        assert _fetch(db, 5) is not None


class TestNoDataLossOfRealDips:
    def test_a_genuine_low_equity_row_is_not_phantom(self, tmp_path):
        """A real drawdown row (te = bal + un, both moved down together) must
        survive both modes — only the te==bal collapse is corruption."""
        db = str(tmp_path / "d.db")
        conn = sqlite3.connect(db)
        conn.execute("""CREATE TABLE account_snapshots (
            id INTEGER PRIMARY KEY, account_id INTEGER, snapshot_ts TEXT,
            total_equity REAL, balance_usdt REAL, total_unrealized REAL,
            bod_equity REAL, daily_pnl REAL, daily_pnl_percent REAL)""")
        # genuine loss: equity 250 = balance 260 + unrealized -10
        conn.execute(f"INSERT INTO account_snapshots ({','.join(_COLS)}) VALUES "
                     f"({','.join('?' * len(_COLS))})",
                     (1, 1, "2026-07-23T10:00:00", 250.0, 260.0, -10.0, 300.0, -50.0, -0.16))
        conn.commit(); conn.close()

        res = run(db_path=db, mode="correct", apply=True, verbose=False)
        assert res["phantom"] == 0
        assert _fetch(db, 1)["total_equity"] == pytest.approx(250.0)
