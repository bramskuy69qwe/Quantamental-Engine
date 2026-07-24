"""
Null over-attributed MFE/MAE in exchange_history (v3.0 operator-bug #8 residue).

WHAT THIS CLEANS
----------------
exchange_history stores MFE/MAE PER income-row (per partial close), and the
reconciler computes ONE high/low over the whole position's window and assigns
it to EVERY partial scaled by qty. A scale-in/out position therefore
over-attributes the full-position excursion to each row — SPCX read MAE -284
(true -111), SAGA 61% / LAB 46% adverse (liquidation territory). The Analytics
excursion scatter no longer reads these (commit 7617b73 re-sourced it to
closed_positions), so this is DB HYGIENE: null the garbage values so they can
never be mis-used and the table tells the truth.

THE DETECTOR (verifiable, conservative)
---------------------------------------
A row's excursion is flagged over-attributed when the adverse OR favorable
excursion exceeds MIN_PCT of its own notional:

    |mae| / notional > MIN_PCT   OR   mfe / notional > MIN_PCT

An excursion worth >8% of notional (the default) is implausible for the
operator's real trading — a leveraged futures position that actually swung
that far would have been liquidated or closed — and is the over-attribution
symptom. The shared-open_time COUNT (how many income rows share this row's
open_time window) is printed alongside as the mechanism confirmation, not as a
filter: raise MIN_PCT to be stricter, lower it (→ 0) to null the whole
shared-window class. Rows with notional<=0 are skipped (can't judge).

THE FIX
-------
Flagged rows get mfe=0, mae=0, backfill_completed=1 — zeroed so any excursion
query (filter `mfe!=0 OR mae!=0`) skips them, and marked reconciler-DONE so the
zeroes STAY.

Why backfill_completed=1 and NOT 0 (the never-computed sentinel): 0 is the
reconciler's WORK-QUEUE flag, not an inert "unknown" marker.
``ReconcilerWorker.backfill_all()`` — spawned unconditionally at every engine
start (``core/schedulers.py``) — selects
``WHERE NOT backfill_completed AND open_time>0 AND trade_key NOT LIKE 'qt:%'``
(``core/db_exchange.py``) and recomputes MFE/MAE through the very
full-position-window ``calc_mfe_mae`` call that over-attributed them in the
first place. Writing 0 here re-queues 62 of the 67 live rows and restores the
exact garbage on the next restart — a self-undoing cleanup.

The ``core.database`` reset migrations (v1-v4) DO leave the flag alone, but
their intent is the OPPOSITE of this tool's: they zero the columns so the
reconciler RECOMPUTES with a corrected formula. Nothing is corrected here — a
per-partial excursion is not recoverable from a full-position window — so these
rows must stay OUT of the queue permanently.

income / notional / prices are LEFT INTACT — only the excursion columns were
wrong. Nothing reads exchange_history's mfe/mae for display any more (commit
7617b73 re-sourced the Analytics excursion scatter to ``closed_positions``;
``get_trade_distribution_series`` reads this table for PnL/hold-time only), so
the flag flip changes no rendered number. Reversible from the backup, or by
``UPDATE exchange_history SET backfill_completed=0 WHERE ...`` if a future
reconciler fix ever makes per-partial excursions well-defined.

SAFETY (CLAUDE.md § "Live-DB dry-run before any destructive --apply")
---------------------------------------------------------------------
  * DRY-RUN IS THE DEFAULT. --apply is explicit opt-in.
  * Dry-run prints the flagged rows verbatim (grouped by symbol + a sample).
  * --apply writes a timestamped .bak_pre_excursion_clean_* copy first and
    REFUSES if a non-empty -wal is present (engine running).
  * STOP THE ENGINE before --apply.

Usage:
    python scripts/clean_overattributed_excursions.py                 # dry-run
    python scripts/clean_overattributed_excursions.py --min-pct 8     # dry-run, threshold
    python scripts/clean_overattributed_excursions.py --apply         # writes (engine stopped)
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(ROOT, "data", "risk_engine.db")
DEFAULT_MIN_PCT = 8.0   # excursion > this % of notional ⇒ flagged over-attributed


def _flagged(row: Dict[str, Any], min_pct: float) -> bool:
    """True iff the row's MFE or MAE exceeds min_pct of its notional."""
    notional = row.get("notional") or 0.0
    if notional <= 0:
        return False
    mae = row.get("mae") or 0.0
    mfe = row.get("mfe") or 0.0
    thr = (min_pct / 100.0) * notional
    return abs(mae) > thr or abs(mfe) > thr


def scan(conn: sqlite3.Connection, min_pct: float,
         account_id: Optional[int] = None) -> List[Dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    where = "WHERE (mfe != 0 OR mae != 0)"
    params: list = []
    if account_id is not None:
        where += " AND account_id = ?"
        params.append(account_id)
    rows = [dict(r) for r in conn.execute(
        f"""SELECT trade_key, account_id, symbol, direction, income, notional,
                   mfe, mae, entry_price, qty, open_time, time
            FROM exchange_history {where}""", params).fetchall()]
    # shared-open_time count per (symbol, open_time) — mechanism confirmation
    counts: Dict[tuple, int] = {}
    for r in rows:
        if r.get("open_time"):
            counts[(r["symbol"], r["open_time"])] = counts.get((r["symbol"], r["open_time"]), 0) + 1
    flagged = []
    for r in rows:
        if _flagged(r, min_pct):
            r["_siblings"] = counts.get((r["symbol"], r.get("open_time")), 1)
            r["_adverse_pct"] = round(abs(r["mae"]) / r["notional"] * 100, 1) if r["notional"] else 0.0
            r["_fav_pct"] = round(abs(r["mfe"]) / r["notional"] * 100, 1) if r["notional"] else 0.0
            flagged.append(r)
    return flagged


def _report(flagged: List[Dict[str, Any]], min_pct: float) -> None:
    print(f"flagged rows (excursion > {min_pct}% of notional): {len(flagged)}")
    if not flagged:
        return
    by_sym: Dict[str, List[Dict]] = {}
    for r in flagged:
        by_sym.setdefault(r["symbol"], []).append(r)
    print("  by symbol (worst-adverse first):")
    for sym in sorted(by_sym, key=lambda s: min(x["mae"] for x in by_sym[s])):
        g = by_sym[sym]
        worst = min(g, key=lambda x: x["mae"])
        print(f"    {sym:14} rows={len(g):3}  worst_mae={worst['mae']:.1f} "
              f"({worst['_adverse_pct']}% adverse, {worst['_siblings']} share its open_time)")
    print("\n  sample (10 largest adverse):")
    for r in sorted(flagged, key=lambda x: x["mae"])[:10]:
        print(f"    {r['symbol']:12} {r['direction']:5} mae={r['mae']:8.1f} mfe={r['mfe']:7.1f} "
              f"notional={r['notional']:9.1f}  adverse={r['_adverse_pct']}%  "
              f"siblings={r['_siblings']}  income={r['income']:.2f}  -> mfe=0, mae=0")


def apply_null(conn: sqlite3.Connection, flagged: List[Dict[str, Any]]) -> int:
    # backfill_completed=1 (NOT 0) — see the module docstring's "THE FIX": 0 is
    # the reconciler's work-queue flag, so writing it would hand these rows
    # straight back to the over-attributing calc_mfe_mae at the next engine start.
    cur = conn.cursor()
    for r in flagged:
        cur.execute(
            "UPDATE exchange_history SET mfe=0, mae=0, backfill_completed=1 "
            "WHERE trade_key=?", (r["trade_key"],))
    conn.commit()
    return len(flagged)


def run(db_path: str = DEFAULT_DB_PATH, min_pct: float = DEFAULT_MIN_PCT,
        account_id: Optional[int] = None, apply: bool = False,
        verbose: bool = True) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    try:
        flagged = scan(conn, min_pct, account_id)
        if verbose:
            print("=" * 72)
            print(f"exchange_history over-attributed-excursion scan  ({db_path})")
            print("=" * 72)
            _report(flagged, min_pct)
            print()
        if not apply:
            if verbose:
                print("[DRY-RUN] No changes made.")
                print("Stop the engine, then re-run with --apply to null mfe/mae "
                      "on the flagged rows.")
            return {"flagged": len(flagged), "applied": False,
                    "trade_keys": [r["trade_key"] for r in flagged]}
        n = apply_null(conn, flagged)
        if verbose:
            print(f"Applied: nulled mfe/mae on {n} rows.")
        return {"flagged": len(flagged), "applied": True, "affected": n,
                "trade_keys": [r["trade_key"] for r in flagged]}
    finally:
        conn.close()


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true",
                   help="Commit (default: dry-run, no writes).")
    p.add_argument("--min-pct", type=float, default=DEFAULT_MIN_PCT,
                   help=f"Flag excursion > this %% of notional (default {DEFAULT_MIN_PCT}).")
    p.add_argument("--account-id", type=int, default=None)
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    args = p.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"ERROR: DB not found at {args.db}", file=sys.stderr)
        return 1

    if args.apply:
        if os.path.exists(args.db + "-wal") and os.path.getsize(args.db + "-wal") > 0:
            print("REFUSING --apply: non-empty -wal present (engine likely RUNNING). "
                  "Stop the engine first.")
            return 2
        import time
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup = f"{args.db}.bak_pre_excursion_clean_{stamp}"
        print("=" * 72)
        print(f"WARNING: --apply WILL null mfe/mae on flagged rows IN {args.db}")
        print(f"  backup -> {backup}")
        print("  Ctrl+C in the next 3 seconds to abort.")
        print("=" * 72)
        for s in (3, 2, 1):
            print(f"  proceeding in {s}...", end="\r")
            time.sleep(1)
        print("  proceeding now.            ")
        shutil.copy2(args.db, backup)
        print(f"  backup written: {backup}\n")

    run(db_path=args.db, min_pct=args.min_pct, account_id=args.account_id,
        apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
