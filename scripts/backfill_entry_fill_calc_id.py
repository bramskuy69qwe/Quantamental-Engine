#!/usr/bin/env python
"""One-time backfill: attribute calc_id + lifecycle_id onto fills of calc-linked
positions that the link-timing race left unattributed.

On the observe-only path the ENTRY fill is recorded BEFORE the matcher links the
order, so every fill-time calc_id propagation no-ops (the order had no calc_id
yet) and is never re-run -> the entry fill of every linked position lacks
calc_id + lifecycle_id (the close fill gets both via the close-fill stamp).
Symptoms: the per-fill Exec-Link drawer shows "-" on entry fills, and
/context/calc omits the entry fill from its fills list.

The code fix (order_enrichment link-time fill backfill + the close-time
open-fill catch-all in OrderManager._backfill_open_fill_tpids) prevents this
going forward; this script repairs the EXISTING rows.

Source of truth = positions_calcs, the spec-3.2 PRIMARY calc (most
contributed_qty, tie-break earliest first_fill_ts). Idempotent: only fills a
currently-empty column (COALESCE/NULLIF). Dry-run by default; --apply backs up
the DB first, then writes.

Usage:
  python scripts/backfill_entry_fill_calc_id.py            # dry-run (no writes)
  python scripts/backfill_entry_fill_calc_id.py --apply    # backup + write
"""
import argparse
import os
import sqlite3
import time

DEFAULT_DB = os.environ.get("RISK_ENGINE_DB", "data/risk_engine.db")


def _primary_calc(conn, account_id, pos_id):
    row = conn.execute(
        "SELECT calc_id, lifecycle_id FROM positions_calcs "
        "WHERE account_id = ? AND position_id = ? "
        "ORDER BY contributed_qty DESC, first_fill_ts ASC LIMIT 1",
        (account_id, pos_id),
    ).fetchone()
    return (row[0], row[1]) if row else (None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write the changes (default: dry-run only)")
    ap.add_argument("--db", default=DEFAULT_DB)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db, timeout=30)
    conn.row_factory = sqlite3.Row

    # Fills whose position has a junction (linked) but which are missing calc_id
    # and/or lifecycle_id.
    rows = conn.execute(
        "SELECT f.id, f.account_id, f.exchange_fill_id, f.symbol, f.is_close, "
        "       f.terminal_position_id AS tpid, f.calc_id, f.lifecycle_id "
        "FROM fills f "
        "WHERE COALESCE(f.terminal_position_id, '') <> '' "
        "  AND (COALESCE(f.calc_id, '') = '' OR COALESCE(f.lifecycle_id, '') = '') "
        "  AND EXISTS (SELECT 1 FROM positions_calcs j "
        "              WHERE j.account_id = f.account_id "
        "                AND j.position_id = f.terminal_position_id) "
        "ORDER BY f.symbol, f.timestamp_ms"
    ).fetchall()

    plan = []
    cache = {}
    for r in rows:
        key = (r["account_id"], r["tpid"])
        if key not in cache:
            cache[key] = _primary_calc(conn, r["account_id"], r["tpid"])
        calc_id, lifecycle_id = cache[key]
        new_calc = calc_id if not (r["calc_id"] or "") else None
        new_lc = lifecycle_id if not (r["lifecycle_id"] or "") else None
        if new_calc or new_lc:
            plan.append((r["id"], r["exchange_fill_id"], r["symbol"],
                         r["is_close"], r["tpid"], new_calc, new_lc))

    print(f"DB: {args.db}")
    print(f"under-attributed fills on linked positions: {len(plan)}")
    for fid, xfid, sym, isc, tpid, nc, nl in plan:
        kind = "CLOSE" if isc else "ENTRY"
        print(f"  id={fid:>6} {sym:>10} {kind} fill={xfid} "
              f"tpid=...{(tpid or '')[-13:]} -> calc={nc} lifecycle={nl}")

    if not args.apply:
        print("\nDRY-RUN (no writes). Re-run with --apply to write "
              "(backs up the DB first).")
        conn.close()
        return

    if not plan:
        print("nothing to apply.")
        conn.close()
        return

    bdir = "data/backups"
    os.makedirs(bdir, exist_ok=True)
    bpath = os.path.join(
        bdir, f"risk_engine_pre_entryfill_calcid_{time.strftime('%Y%m%d_%H%M%S')}.db")
    bk = sqlite3.connect(bpath)
    with bk:
        conn.backup(bk)
    bk.close()
    print(f"\nBACKUP -> {bpath}  ({os.path.getsize(bpath):,} bytes)")

    n = 0
    for fid, xfid, sym, isc, tpid, nc, nl in plan:
        conn.execute(
            "UPDATE fills SET "
            "  calc_id = COALESCE(NULLIF(calc_id, ''), ?), "
            "  lifecycle_id = COALESCE(NULLIF(lifecycle_id, ''), ?) "
            "WHERE id = ?",
            (nc, nl, fid),
        )
        n += 1
    conn.commit()
    print(f"applied: {n} fills updated.")
    conn.close()


if __name__ == "__main__":
    main()
