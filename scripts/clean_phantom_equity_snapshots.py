"""
Clean phantom-equity rows from account_snapshots (v3.0 operator-bug #1 residue).

WHAT THIS FIXES
---------------
operator-bug #1 (commit 23d04de) fixed the Binance adapter that reported
`totalWalletBalance` (wallet-only, EXCLUDING open-position PnL) as
`total_equity`. Before that fix, every REST account poll wrote a snapshot
whose `total_equity` had collapsed onto the wallet balance — the phantom
dips the operator saw on the equity curve (L $278.41 while equity never
truly dropped below 300). The adapter fix stops NEW pollution; this script
cleans the rows already persisted.

THE DETECTOR (provable, not heuristic)
--------------------------------------
`apply_account_update_rest` set BOTH fields from the same wallet figure:

    acc.total_equity = na.total_equity      # wallet (the bug)
    acc.balance_usdt = na.total_equity       # wallet

so a phantom row has `total_equity == balance_usdt` to full float
precision, while `total_unrealized` still holds the real open PnL. A CORRECT
row instead has `total_equity = balance_usdt + total_unrealized` (computed
by apply_mark_price), so `total_equity == balance_usdt` there ONLY when
`total_unrealized == 0`.

    PHANTOM  iff  abs(total_equity - balance_usdt) <= EPS  AND
                  abs(total_unrealized)            >  UNREAL_EPS

Both operands of the correction are individually valid in the phantom row
(`balance_usdt` = the real wallet, `total_unrealized` = the real open PnL),
so their sum is exactly the equity the mark tick would have produced. This
is a reconstruction, not an estimate.

TWO MODES
---------
  correct  (recommended, DEFAULT): total_equity <- balance_usdt + unrealized,
           and the two derived-from-equity columns are recomputed with the
           ENGINE's own formulas (data_cache._recalculate_portfolio):
               daily_pnl         = total_equity - bod_eq
               daily_pnl_percent = daily_pnl / bod_eq        (fraction)
           where bod_eq = bod_equity if bod_equity > 0 else total_equity.
           Recovers the true value AND preserves curve density.
  delete   removes the phantom rows entirely (the operator's literal ask).
           The curve reconnects across the gaps; density drops ~50% in
           position-open stretches (phantoms alternate roughly every other
           row). Offered because it was requested; `correct` is strictly
           better here since the true value is recoverable.

DELIBERATELY NOT TOUCHED (named residue — do not silently widen scope)
----------------------------------------------------------------------
  * `drawdown` column — the rolling-window dd-GATE measure (≈0 at rolling
    high), path-dependent, and NOT the source of the analytics max-drawdown
    (get_equity_period_boundaries recomputes peak-to-trough from
    total_equity, which `correct` fixes). Rebuilding it needs a rolling-peak
    replay.
  * `min_total_equity` / `max_total_equity` — monotonic ratchet STATE, also
    path-dependent, and read only as the LIVE value (which clears at the
    next BOD reset), never historically by the analytics queries.
  * The ~436 "identity-violator" rows where total_equity != balance_usdt
    (old rows with balance_usdt=0 where total_equity is actually CORRECT,
    plus 1-2 transient $100 balance glitches that self-corrected). These are
    a DIFFERENT, mostly-cosmetic, mostly-ancient class — this script does
    not touch them. `--report-anomalies` lists them for a separate decision.

SAFETY (CLAUDE.md § "Live-DB dry-run before any destructive --apply")
---------------------------------------------------------------------
  * DRY-RUN IS THE DEFAULT. `--apply` is an explicit opt-in.
  * Dry-run prints planned changes verbatim (a sample + full magnitude
    stats) so the shape can be inspected before committing.
  * `--apply` writes a timestamped `.bak_pre_phantom_clean_*` copy first.
  * STOP THE ENGINE before `--apply` — it holds the DB open in WAL mode.

Usage:
    python scripts/clean_phantom_equity_snapshots.py                 # dry-run, correct
    python scripts/clean_phantom_equity_snapshots.py --mode delete   # dry-run, delete
    python scripts/clean_phantom_equity_snapshots.py --report-anomalies
    python scripts/clean_phantom_equity_snapshots.py --apply         # writes (engine stopped)
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(ROOT, "data", "risk_engine.db")

# unrealized considered "material" — below this there is no open PnL to have
# been dropped, so the row cannot be a phantom.
UNREAL_EPS = 1e-4
# Absolute gate: how far total_equity may sit from balance_usdt and still be
# read as "collapsed onto the wallet". At WRITE time the bug set both from the
# same float (exactly equal); the few live rows that drifted did so by ~1c
# because a later partial update nudged balance between the snapshot's field
# reads. 0.10 absorbs that with margin while excluding the $100 transfer-glitch
# rows (te-bal ~ 100).
PHANTOM_TOL = 0.10
# Absolute gate: how far total_equity may sit from (balance + unrealized) and
# still be read as a correct mark-tick row — pure inter-field capture jitter.
# Sized from live data: genuine jitter tops out ~$1 (on a ≤$600 account, marks
# moving between the sequential field reads); the real anomalies it must still
# flag (transient $100 balance-transfer glitches, old balance_usdt=0 rows) are
# 2+ orders of magnitude beyond it. This gate only affects the ok/anomaly
# REPORT split — neither class is ever auto-touched.
IDENTITY_TOL = 1.5


# ── classification ───────────────────────────────────────────────────────────

def classify(row: Dict[str, Any]) -> str:
    """One of: 'ok' | 'phantom' | 'anomaly'.

    The test is RELATIVE, not a fixed cent-tolerance: is total_equity closer to
    the WALLET (balance_usdt) or to the CORRECT value (balance_usdt +
    total_unrealized)? A phantom collapsed onto the wallet; a correct row sits
    at wallet+unrealized. Sequential-capture jitter of a few cents never flips
    which side te is on as long as the open PnL is larger than the jitter.

    phantom  — material open PnL AND total_equity hugs balance_usdt (wallet)
               rather than balance_usdt+unrealized. Correctable to bal+un.
    ok       — no material PnL and te==bal (flat), OR te sits at bal+un (a
               real mark-tick row, incl. genuine drawdowns).
    anomaly  — neither shape: identity violated some OTHER way (old rows with
               balance_usdt=0 where te is actually correct; transient $100
               balance-transfer glitches). Reported, never auto-touched.
    """
    te = row["total_equity"]
    bal = row["balance_usdt"]
    un = row["total_unrealized"]
    if te is None or bal is None or un is None:
        return "anomaly"

    if abs(un) <= UNREAL_EPS:
        # No open PnL to drop: te should equal bal. Within jitter => ok.
        return "ok" if abs(te - bal) <= IDENTITY_TOL else "anomaly"

    dist_wallet  = abs(te - bal)
    dist_correct = abs(te - (bal + un))
    if dist_wallet <= PHANTOM_TOL and dist_wallet <= dist_correct:
        return "phantom"
    if dist_correct <= IDENTITY_TOL:
        return "ok"
    return "anomaly"


def corrected_row(row: Dict[str, Any]) -> Tuple[float, float, float]:
    """Return (total_equity, daily_pnl, daily_pnl_percent) for a phantom row,
    using the engine's own formulas so a corrected day-boundary row stays
    consistent with what a live mark tick would have stored."""
    new_te = row["balance_usdt"] + row["total_unrealized"]
    bod = row["bod_equity"]
    bod_eq = bod if (bod is not None and bod > 0) else new_te
    daily_pnl = new_te - bod_eq
    daily_pct = (daily_pnl / bod_eq) if bod_eq > 0 else 0.0
    return new_te, daily_pnl, daily_pct


# ── scan ─────────────────────────────────────────────────────────────────────

def scan(conn: sqlite3.Connection, account_id: Optional[int] = None) -> Dict[str, List[Dict]]:
    conn.row_factory = sqlite3.Row
    where = "WHERE account_id = ?" if account_id is not None else ""
    params = (account_id,) if account_id is not None else ()
    rows = [dict(r) for r in conn.execute(
        f"""SELECT id, account_id, snapshot_ts, total_equity, balance_usdt,
                   total_unrealized, bod_equity, daily_pnl, daily_pnl_percent
            FROM account_snapshots {where} ORDER BY id ASC""", params
    ).fetchall()]
    out: Dict[str, List[Dict]] = {"ok": [], "phantom": [], "anomaly": []}
    for r in rows:
        out[classify(r)].append(r)
    return out


def _fmt_stats(phantom: List[Dict]) -> str:
    if not phantom:
        return "  (none)"
    corr = [abs(r["total_unrealized"]) for r in phantom]
    corr.sort()
    n = len(corr)
    median = corr[n // 2]
    lines = [
        f"  rows: {n}",
        f"  dropped-unrealized (= correction size): "
        f"min={corr[0]:.4f}  median={median:.4f}  max={corr[-1]:.4f}",
        f"  date range: {phantom[0]['snapshot_ts'][:10]} .. "
        f"{phantom[-1]['snapshot_ts'][:10]}",
    ]
    # magnitude buckets
    buckets = [("<$0.50", 0), ("$0.50-$2", 0), ("$2-$10", 0), ("$10-$50", 0), (">$50", 0)]
    counts = [0, 0, 0, 0, 0]
    for c in corr:
        counts[0 if c < 0.5 else 1 if c < 2 else 2 if c < 10 else 3 if c < 50 else 4] += 1
    lines.append("  by magnitude: " + "  ".join(
        f"{label}={cnt}" for (label, _), cnt in zip(buckets, counts)))
    return "\n".join(lines)


def _print_sample(phantom: List[Dict], mode: str, limit: int = 12) -> None:
    if not phantom:
        return
    print(f"  sample ({min(limit, len(phantom))} of {len(phantom)}, "
          f"largest corrections first):")
    for r in sorted(phantom, key=lambda x: -abs(x["total_unrealized"]))[:limit]:
        ts = r["snapshot_ts"][:19]
        if mode == "delete":
            print(f"    DELETE id={r['id']:>7} {ts}  te={r['total_equity']:.4f} "
                  f"(phantom; true={r['balance_usdt'] + r['total_unrealized']:.4f})")
        else:
            new_te, new_dp, _ = corrected_row(r)
            print(f"    FIX    id={r['id']:>7} {ts}  te {r['total_equity']:.4f} "
                  f"-> {new_te:.4f}   daily_pnl {r['daily_pnl']:.4f} -> {new_dp:.4f}")


# ── apply ────────────────────────────────────────────────────────────────────

def apply_correct(conn: sqlite3.Connection, phantom: List[Dict]) -> int:
    cur = conn.cursor()
    for r in phantom:
        new_te, new_dp, new_pct = corrected_row(r)
        cur.execute(
            "UPDATE account_snapshots SET total_equity=?, daily_pnl=?, "
            "daily_pnl_percent=? WHERE id=?",
            (new_te, new_dp, new_pct, r["id"]),
        )
    conn.commit()
    return len(phantom)


def apply_delete(conn: sqlite3.Connection, phantom: List[Dict]) -> int:
    cur = conn.cursor()
    ids = [r["id"] for r in phantom]
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        cur.execute(
            f"DELETE FROM account_snapshots WHERE id IN ({','.join('?' * len(chunk))})",
            chunk,
        )
    conn.commit()
    return len(ids)


def run(db_path: str = DEFAULT_DB_PATH, mode: str = "correct",
        account_id: Optional[int] = None, apply: bool = False,
        report_anomalies: bool = False, verbose: bool = True) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    try:
        groups = scan(conn, account_id)
        phantom, anomaly = groups["phantom"], groups["anomaly"]

        if verbose:
            print("=" * 72)
            print(f"account_snapshots phantom-equity scan  ({db_path})")
            print("=" * 72)
            print(f"  ok rows:      {len(groups['ok'])}")
            print(f"  phantom rows: {len(phantom)}   <- operator-bug #1 residue")
            print(f"  anomaly rows: {len(anomaly)}   (NOT touched; see --report-anomalies)")
            print()
            print(f"mode = {mode}")
            print(_fmt_stats(phantom))
            print()
            _print_sample(phantom, mode)
            print()

        if report_anomalies and verbose:
            print("-" * 72)
            print(f"ANOMALIES ({len(anomaly)}) — identity total_equity == "
                  "balance+unrealized violated in a NON-phantom way.")
            print("These are NOT auto-touched (total_equity is usually correct; "
                  "the miss is an unpopulated/jittery balance_usdt in old rows).")
            for r in anomaly[:40]:
                te, bal, un = r["total_equity"], r["balance_usdt"], r["total_unrealized"]
                gap = (bal + un - te) if (bal is not None and un is not None) else None
                print(f"    id={r['id']:>7} {r['snapshot_ts'][:19]}  te={te}  "
                      f"bal={bal}  un={un}  gap={gap}")
            if len(anomaly) > 40:
                print(f"    ... and {len(anomaly) - 40} more")
            print()

        if not apply:
            if verbose:
                print("[DRY-RUN] No changes made.")
                print("Stop the engine, then re-run with --apply to commit.")
            return {"phantom": len(phantom), "anomaly": len(anomaly),
                    "applied": False, "mode": mode,
                    "phantom_ids": [r["id"] for r in phantom]}

        if mode == "correct":
            n = apply_correct(conn, phantom)
        elif mode == "delete":
            n = apply_delete(conn, phantom)
        else:
            raise ValueError(f"unknown mode {mode!r}")
        if verbose:
            print(f"Applied {mode}: {n} rows.")
        return {"phantom": len(phantom), "anomaly": len(anomaly),
                "applied": True, "mode": mode, "affected": n,
                "phantom_ids": [r["id"] for r in phantom]}
    finally:
        conn.close()


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true",
                   help="Commit changes (default: dry-run, no writes).")
    p.add_argument("--mode", choices=["correct", "delete"], default="correct",
                   help="correct (recommended, default) | delete.")
    p.add_argument("--account-id", type=int, default=None,
                   help="Restrict to one account_id.")
    p.add_argument("--report-anomalies", action="store_true",
                   help="Also list the non-phantom identity-violator rows.")
    p.add_argument("--db", default=DEFAULT_DB_PATH,
                   help=f"DB path (default: {DEFAULT_DB_PATH}).")
    args = p.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"ERROR: DB not found at {args.db}", file=sys.stderr)
        return 1

    if args.apply:
        # WAL-safety: refuse if the engine is plausibly holding the DB open.
        if os.path.exists(args.db + "-wal") and os.path.getsize(args.db + "-wal") > 0:
            print("=" * 72)
            print("REFUSING --apply: a non-empty -wal file is present, which "
                  "usually means the engine is RUNNING and holds the DB open.")
            print("Stop the engine first, then re-run --apply.")
            print("=" * 72)
            return 2
        import time
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup = f"{args.db}.bak_pre_phantom_clean_{stamp}"
        print("=" * 72)
        print(f"WARNING: --apply WILL {args.mode.upper()} phantom rows IN")
        print(f"  {args.db}")
        print(f"  A backup will be written to:")
        print(f"  {backup}")
        print("  Ctrl+C in the next 3 seconds to abort.")
        print("=" * 72)
        for s in (3, 2, 1):
            print(f"  proceeding in {s}...", end="\r")
            time.sleep(1)
        print("  proceeding now.            ")
        shutil.copy2(args.db, backup)
        print(f"  backup written: {backup}")
        print()

    run(db_path=args.db, mode=args.mode, account_id=args.account_id,
        apply=args.apply, report_anomalies=args.report_anomalies)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
