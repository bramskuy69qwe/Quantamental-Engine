"""
Phase 0.0.3 (T185): operator-controlled fills-table dedup.

Identifies and removes duplicate fill rows using the canonical
``position_grouping.is_same_fill`` rule. Source priority for which to
keep:

    binance_ws / binance_algo_ws / quantower / mexc_ws   (WS-class)   >
        binance_rest / binance_algo_rest                 (REST-class) >
            exchange_history_backfill                    (synthesized)

Ties within a priority class are broken by the smallest ``id`` (oldest
insertion). Fills with unknown sources are deprioritized to 99 -- if a
duplicate group contains an unknown source, a WARNING is printed but
the script still operates (the unknown row gets deleted unless it's
the only one). Review the dry-run output before ``--apply`` to confirm.

USAGE:

    # Default: dry-run, prints what WOULD be deleted, no DB writes.
    python scripts/dedup_fills.py

    # Apply: BACK UP THE DB FIRST.
    python scripts/dedup_fills.py --apply

    # Restrict to a single account / symbol for testing.
    python scripts/dedup_fills.py --account-id 1
    python scripts/dedup_fills.py --symbol BSBUSDT
    python scripts/dedup_fills.py --account-id 1 --symbol BSBUSDT --apply

    # Run against an alternate DB path (e.g., the freshly-backed-up
    # copy for safe rehearsal).
    python scripts/dedup_fills.py --db /path/to/backup.db --apply

IMPORTANT:

    - NOT auto-run on engine startup. Operator-controlled only.
    - BACKUP REQUIRED before --apply. The DELETE is committed in a
      single transaction; if anything goes wrong mid-script, the
      transaction rolls back, but a pre-script backup is the safety
      net of last resort.
    - Designed to be idempotent -- running it twice with no new fills
      between runs produces zero deletes on the second run.

PLAN REFERENCE: docs/design/calc_linkage_implementation_plan.md
Phase 0.0.3 row in the Tasks table.
T178 background: docs/audits/2026-05-25-t178-fills-data-quality.md
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.position_grouping import (  # noqa: E402
    FILL_DEDUP_TOLERANCE_MS,
    is_same_fill,
)


DEFAULT_DB_PATH = os.path.join(ROOT, "data", "risk_engine.db")


# Lower number = higher priority (kept). Sources not listed get
# UNKNOWN_PRIORITY (deprioritized; the script prints a WARN per group
# that touches an unknown source so the operator can review).
SOURCE_PRIORITY: Dict[str, int] = {
    # Real-time WS-class (highest fidelity -- direct event from exchange/plugin)
    "binance_ws":        0,
    "binance_algo_ws":   0,
    "mexc_ws":           0,
    # v2.6 removed the live Quantower plugin, but "quantower" stays here as
    # legacy/historical only: old source='quantower' fills + qt: trade_keys
    # are kept as-is (operator decision), and dedup must still rank them
    # WS-class. Removing this entry would re-rank + change keep/delete on
    # those historical rows (L4).
    "quantower":         0,
    # REST-poll-class (slight latency but reliable)
    "binance_rest":      1,
    "binance_algo_rest": 1,
    # Synthesized from income-API (lowest of the known sources)
    "exchange_history_backfill": 2,
}
UNKNOWN_PRIORITY = 99


def source_rank(source: str) -> int:
    """Lower rank = higher priority. Unknown sources rank 99."""
    return SOURCE_PRIORITY.get(source or "", UNKNOWN_PRIORITY)


def pick_keeper(group: List[Dict]) -> Dict:
    """Return the canonical fill from a duplicate group.

    Priority: lowest ``source_rank``, then smallest ``id`` (oldest
    insertion). Deterministic -- same input always yields the same
    keeper, which is what makes the apply mode idempotent.
    """
    return min(
        group,
        key=lambda f: (source_rank(f.get("source", "")), int(f.get("id", 0) or 0)),
    )


def group_fills_for_dedup(fills: List[Dict]) -> List[List[Dict]]:
    """Find duplicate-fill groups via ``is_same_fill``.

    Algorithm: walk fills in chronological order. For each fill that
    isn't already assigned to a group, scan forward until the
    timestamp gap exceeds ``FILL_DEDUP_TOLERANCE_MS`` and gather any
    matches into a new group.

    Returns only groups of size >= 2 (singletons aren't duplicates),
    AND excludes groups where every fill shares the same ``source``
    (T193 fix): T178 audit observed Binance matching-engine splits
    where a single client order matches against multiple counterparties
    at the SAME microsecond -- the exchange records each as a distinct
    fill with sequential tradeIds (e.g., 178459194 + 178459195), same
    price/qty/side/direction/is_close/timestamp. ``is_same_fill``
    returns True for these by construction, but they are NOT
    duplicates: both are real exchange-recorded fills that must be
    preserved. The same-source filter catches this -- synthetic-dup
    cases always cross sources (e.g., ``exchange_history_backfill``
    vs ``binance_ws``), while matching-engine splits share the source
    that recorded both halves.

    The ``id`` field on each input dict is preserved so the caller
    can issue ``DELETE`` by id.
    """
    sorted_fills = sorted(
        fills, key=lambda f: int(f.get("timestamp_ms", 0) or 0),
    )

    assigned: set = set()
    groups: List[List[Dict]] = []

    for i, fill in enumerate(sorted_fills):
        fid = int(fill.get("id", -1))
        if fid in assigned:
            continue
        group = [fill]
        assigned.add(fid)
        ts_i = int(fill.get("timestamp_ms", 0) or 0)
        for j in range(i + 1, len(sorted_fills)):
            candidate = sorted_fills[j]
            cid = int(candidate.get("id", -1))
            if cid in assigned:
                continue
            ts_j = int(candidate.get("timestamp_ms", 0) or 0)
            if ts_j - ts_i > FILL_DEDUP_TOLERANCE_MS:
                # Once outside the window, all subsequent fills are
                # too -- they're sorted by ts.
                break
            if is_same_fill(candidate, fill):
                group.append(candidate)
                assigned.add(cid)
        if len(group) < 2:
            continue
        # T193: same-source groups are Binance matching-engine splits,
        # not synthetic duplicates. Preserve them by NOT returning the
        # group from the dedup grouper. Synthetic dups always cross
        # sources (synth row from exchange_history_backfill paired
        # against a real binance_ws/_rest row).
        sources = {f.get("source", "") for f in group}
        if len(sources) == 1:
            continue
        groups.append(group)
    return groups


def read_fills(
    conn: sqlite3.Connection,
    account_id: Optional[int] = None,
    symbol: Optional[str] = None,
) -> List[Dict]:
    """Read fills from the DB with optional filters."""
    sql = "SELECT * FROM fills WHERE 1=1"
    params: List = []
    if account_id is not None:
        sql += " AND account_id=?"
        params.append(account_id)
    if symbol:
        sql += " AND symbol=?"
        params.append(symbol)
    sql += " ORDER BY timestamp_ms ASC, id ASC"
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def delete_fill_ids(
    conn: sqlite3.Connection, ids: List[int],
) -> int:
    """Delete fills by id list. Returns rows affected.

    Commits in a single transaction. If any id is invalid, the
    DELETE silently no-ops for that id (SQLite behavior).
    """
    if not ids:
        return 0
    # Chunk into batches of 500 to avoid SQLite's parameter limit.
    BATCH = 500
    total = 0
    for start in range(0, len(ids), BATCH):
        chunk = ids[start:start + BATCH]
        placeholders = ",".join("?" * len(chunk))
        cur = conn.execute(
            f"DELETE FROM fills WHERE id IN ({placeholders})", chunk
        )
        total += cur.rowcount
    conn.commit()
    return total


def _print_group(grp_i: int, group: List[Dict], keeper_id: int) -> None:
    print(
        f"--- Group {grp_i}: {len(group)} fills, "
        f"keep id={keeper_id} "
        f"(src={next(f.get('source', '?') for f in group if f['id'] == keeper_id)}) ---"
    )
    print(
        f"{'mark':<4} {'id':>6} {'source':<32} {'symbol':<10} "
        f"{'side':<5} {'dir':<6} {'qty':>10} {'price':>12} "
        f"{'ts_ms':>14} {'cls':>3} {'fill_id':<20}"
    )
    for f in group:
        mark = "KEEP" if int(f["id"]) == keeper_id else "DEL"
        print(
            f"{mark:<4} {int(f['id']):>6} {f.get('source', '?'):<32} "
            f"{f.get('symbol', ''):<10} {f.get('side', ''):<5} "
            f"{f.get('direction', ''):<6} "
            f"{float(f.get('quantity', 0) or 0):>10.4f} "
            f"{float(f.get('price', 0) or 0):>12.4f} "
            f"{int(f.get('timestamp_ms', 0) or 0):>14d} "
            f"{int(f.get('is_close', 0) or 0):>3d} "
            f"{(f.get('exchange_fill_id') or ''):<20}"
        )


def run_dedup(
    db_path: str = DEFAULT_DB_PATH,
    *,
    apply: bool = False,
    account_id: Optional[int] = None,
    symbol: Optional[str] = None,
    verbose: bool = True,
) -> Dict[str, int]:
    """Programmable entrypoint (called by main + tests).

    Returns a summary dict: ``{
        "fills_read": N,
        "groups": G,
        "deleted_ids": [...],   # actually deleted in apply, planned in dry-run
        "applied": bool,
        "unknown_source_groups": K,  # groups touching a source not in SOURCE_PRIORITY
    }``
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    fills = read_fills(conn, account_id=account_id, symbol=symbol)
    if verbose:
        print(f"Read {len(fills)} fills from {db_path}")
        if account_id is not None:
            print(f"  Filter: account_id={account_id}")
        if symbol:
            print(f"  Filter: symbol={symbol}")
        print()

    dup_groups = group_fills_for_dedup(fills)
    unknown_source_groups = 0
    ids_to_delete: List[int] = []

    if not dup_groups:
        if verbose:
            print("No duplicate fills detected.")
        conn.close()
        return {
            "fills_read":           len(fills),
            "groups":               0,
            "deleted_ids":          [],
            "applied":              False,
            "unknown_source_groups": 0,
        }

    if verbose:
        print(f"=== {len(dup_groups)} duplicate groups detected ===")
        print()

    for grp_i, group in enumerate(dup_groups, start=1):
        # Flag groups touching unknown sources.
        has_unknown = any(
            source_rank(f.get("source", "")) == UNKNOWN_PRIORITY for f in group
        )
        if has_unknown:
            unknown_source_groups += 1
            if verbose:
                unk = sorted({
                    f.get("source", "") for f in group
                    if source_rank(f.get("source", "")) == UNKNOWN_PRIORITY
                })
                print(
                    f"WARN: Group {grp_i} contains unknown source(s) {unk!r} -- "
                    f"these will be ranked at priority {UNKNOWN_PRIORITY} "
                    f"(deprioritized). Review before --apply."
                )
        keeper = pick_keeper(group)
        keeper_id = int(keeper["id"])
        for f in group:
            if int(f["id"]) != keeper_id:
                ids_to_delete.append(int(f["id"]))
        if verbose:
            _print_group(grp_i, group, keeper_id)
            print()

    if verbose:
        print("=" * 70)
        print(
            f"Summary: {len(dup_groups)} dup groups, "
            f"{len(ids_to_delete)} fills to delete "
            f"({unknown_source_groups} groups touch an unknown source)"
        )
        print("=" * 70)

    if not apply:
        if verbose:
            print()
            print("[DRY-RUN] No changes made.")
            print("Re-run with --apply after backing up the DB to commit deletes.")
        conn.close()
        return {
            "fills_read":           len(fills),
            "groups":               len(dup_groups),
            "deleted_ids":          ids_to_delete,
            "applied":              False,
            "unknown_source_groups": unknown_source_groups,
        }

    if verbose:
        print()
        print("Applying deletions...")
    affected = delete_fill_ids(conn, ids_to_delete)
    if verbose:
        print(f"Deleted {affected} fills.")
    conn.close()
    return {
        "fills_read":           len(fills),
        "groups":               len(dup_groups),
        "deleted_ids":          ids_to_delete,
        "applied":              True,
        "unknown_source_groups": unknown_source_groups,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually delete dups (default: dry-run only, no DB writes).",
    )
    parser.add_argument(
        "--account-id", type=int, default=None,
        help="Restrict to one account_id.",
    )
    parser.add_argument(
        "--symbol", default=None,
        help="Restrict to one symbol (e.g., BSBUSDT).",
    )
    parser.add_argument(
        "--db", default=DEFAULT_DB_PATH,
        help=f"Path to DB (default: {DEFAULT_DB_PATH}).",
    )
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"ERROR: DB not found at {args.db}", file=sys.stderr)
        return 1

    if args.apply:
        print("=" * 70)
        print("WARNING: --apply WILL DELETE FILL ROWS FROM")
        print(f"  {args.db}")
        print()
        print("  This is destructive. Back up the DB first.")
        print("  Press Ctrl+C in the next 3 seconds to abort.")
        print("=" * 70)
        print()
        import time
        for s in (3, 2, 1):
            print(f"  proceeding in {s}...", end="\r")
            time.sleep(1)
        print("  proceeding now.            ")
        print()

    run_dedup(
        db_path=args.db,
        apply=args.apply,
        account_id=args.account_id,
        symbol=args.symbol,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
