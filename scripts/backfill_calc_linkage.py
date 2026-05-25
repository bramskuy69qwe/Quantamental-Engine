"""
Phase 0 Task 5 (P0.T5): one-shot calc-linkage data backfill.

Three operations, all idempotent + safe to re-run, per plan tasks
0.11 + 0.12 + spec §3.5:

  1. Re-map closed_positions.exit_reason legacy → spec §3.4 enum:
       'manual' → 'MANUAL_OTHER'
       'tp'     → 'TP_PLANNED'
       'sl'     → 'SL_PLANNED'
       NULL     → 'MANUAL_OTHER'
       ''       → 'MANUAL_OTHER'
     Already-new-enum values (TP_PLANNED, SL_AMENDED, LIQUIDATION,
     etc.) are left unchanged.

  2. Generate lifecycle_id (UUID v4) for each closed_positions row
     that has ``lifecycle_id IS NULL``. Stamp onto:
       - closed_positions.lifecycle_id
       - All fills with matching terminal_position_id
         (fills.lifecycle_id)
     Forward fills (Phase 2.1) generate lifecycle_id at the first
     opening fill, so this only catches legacy rows.

  3. Backfill positions_calcs junction from fills WHERE calc_id IS
     NOT NULL. Per (closed_position.id, calc_id, orders.id) tuple,
     sum contributed_qty. Fills whose exchange_order_id doesn't
     resolve to an orders.id (rare orphan-fill case) are skipped
     + counted. Junction rows already present for a closed_position
     are NOT re-populated — re-running the script is a no-op.

USAGE:
    # Default: DRY-RUN. Prints per-operation counts + sample.
    python scripts/backfill_calc_linkage.py

    # APPLY: write the changes in one atomic transaction.
    python scripts/backfill_calc_linkage.py --apply

    # Scope: restrict to one account or one symbol.
    python scripts/backfill_calc_linkage.py --account-id 1
    python scripts/backfill_calc_linkage.py --symbol BSBUSDT --apply

IMPORTANT:
  - BACKUP the DB before --apply (standard discipline; the script
    itself is idempotent + transaction-wrapped, but the backup is
    the safety net of last resort).
  - The script does NOT auto-run on engine startup — operator
    triggers manually after Phase 0.T1–T4 schema is in place.

PLAN REFERENCE: docs/design/calc_linkage_implementation_plan.md
§14.3 P0.T5 (line ~839). Spec sections: §3.2 (exit_reason enum),
§3.4 (full enum list), §3.5 (lifecycle_id semantics).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DEFAULT_DB_PATH = os.path.join(ROOT, "data", "risk_engine.db")


# Legacy → spec §3.4 enum mapping. Anything not in this dict is left
# untouched (treated as already-migrated). Empty-string and None both
# default to MANUAL_OTHER per plan task 0.12.
EXIT_REASON_REMAP: Dict[Optional[str], str] = {
    None:      "MANUAL_OTHER",
    "":        "MANUAL_OTHER",
    "manual":  "MANUAL_OTHER",
    "tp":      "TP_PLANNED",
    "sl":      "SL_PLANNED",
}


# ── Read helpers ───────────────────────────────────────────────────────


async def _read_closed_positions(
    db: Any,
    account_id: Optional[int],
    symbol: Optional[str],
) -> List[Dict[str, Any]]:
    sql = ("SELECT id, account_id, terminal_position_id, symbol, "
           "direction, exit_reason, lifecycle_id "
           "FROM closed_positions WHERE 1=1")
    params: List = []
    if account_id is not None:
        sql += " AND account_id = ?"
        params.append(account_id)
    if symbol:
        sql += " AND symbol = ?"
        params.append(symbol)
    sql += " ORDER BY id ASC"
    async with db._conn.execute(sql, params) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def _read_fills_for_position(
    db: Any,
    account_id: int,
    terminal_position_id: str,
) -> List[Dict[str, Any]]:
    """Read fills linked to one closed_position via tpid."""
    if not terminal_position_id:
        return []
    async with db._conn.execute(
        "SELECT id, account_id, exchange_fill_id, exchange_order_id, "
        "calc_id, quantity, timestamp_ms, lifecycle_id "
        "FROM fills WHERE account_id = ? AND terminal_position_id = ?",
        (account_id, terminal_position_id),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def _resolve_order_id(
    db: Any,
    account_id: int,
    exchange_order_id: str,
) -> Optional[int]:
    """Resolve fills.exchange_order_id → orders.id. None if not found."""
    if not exchange_order_id:
        return None
    async with db._conn.execute(
        "SELECT id FROM orders WHERE account_id = ? AND exchange_order_id = ? "
        "LIMIT 1",
        (account_id, exchange_order_id),
    ) as cur:
        row = await cur.fetchone()
    return int(row["id"]) if row else None


async def _existing_junction_count(
    db: Any,
    position_id: int,
) -> int:
    async with db._conn.execute(
        "SELECT COUNT(*) FROM positions_calcs WHERE position_id = ?",
        (position_id,),
    ) as cur:
        row = await cur.fetchone()
    return int(row[0]) if row else 0


# ── Planning (pure-async; no writes) ───────────────────────────────────


async def _build_plan(
    db: Any,
    account_id: Optional[int],
    symbol: Optional[str],
) -> Dict[str, Any]:
    """Inspect existing state and return a dict of planned changes.

    Returns ``{
        'cps_in_scope': int,
        'exit_remap': List[(cp_id, old, new)],
        'lifecycle_gen': List[(cp_id, tpid, new_uuid)],
        'fill_stamps': List[(fill_id, new_uuid)],
        'junction_rows': List[Dict],            # ready for upsert
        'junction_skip_no_calc': int,
        'junction_skip_no_order': int,
        'junction_skip_already_populated': int,
    }``.
    """
    cps = await _read_closed_positions(db, account_id, symbol)

    exit_remap: List[Tuple[int, Optional[str], str]] = []
    for cp in cps:
        old = cp.get("exit_reason")
        if old in EXIT_REASON_REMAP:
            new = EXIT_REASON_REMAP[old]
            if new != old:
                exit_remap.append((cp["id"], old, new))

    lifecycle_gen: List[Tuple[int, str, str]] = []
    fill_stamps: List[Tuple[int, str]] = []
    junction_rows: List[Dict[str, Any]] = []
    skip_no_calc = 0
    skip_no_order = 0
    skip_already_populated = 0

    for cp in cps:
        cp_id = int(cp["id"])
        tpid = cp.get("terminal_position_id") or ""
        # 2. Lifecycle generation — only if NULL
        if cp.get("lifecycle_id") is None:
            new_uuid = str(uuid.uuid4())
            lifecycle_gen.append((cp_id, tpid, new_uuid))
            # Stamp on matching fills that don't already carry a
            # lifecycle_id.
            if tpid:
                fills = await _read_fills_for_position(
                    db, int(cp["account_id"]), tpid,
                )
                for f in fills:
                    if f.get("lifecycle_id") is None:
                        fill_stamps.append((int(f["id"]), new_uuid))
        else:
            new_uuid = str(cp["lifecycle_id"])

        # 3. Junction backfill — only if no junction rows yet for this
        # closed_position.
        existing_junction = await _existing_junction_count(db, cp_id)
        if existing_junction > 0:
            skip_already_populated += 1
            continue
        if not tpid:
            continue

        fills = await _read_fills_for_position(
            db, int(cp["account_id"]), tpid,
        )
        # Group fills by (calc_id, exchange_order_id); skip fills
        # without calc_id (no attribution possible).
        groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for f in fills:
            cid = f.get("calc_id") or ""
            if not cid:
                skip_no_calc += 1
                continue
            xoid = f.get("exchange_order_id") or ""
            groups[(cid, xoid)].append(f)

        for (cid, xoid), fs in groups.items():
            order_id = await _resolve_order_id(
                db, int(cp["account_id"]), xoid,
            )
            if order_id is None:
                skip_no_order += len(fs)
                continue
            total_qty = sum(float(f.get("quantity", 0) or 0) for f in fs)
            first_ts = min(int(f.get("timestamp_ms", 0) or 0) for f in fs)
            last_ts = max(int(f.get("timestamp_ms", 0) or 0) for f in fs)
            junction_rows.append({
                "position_id":     cp_id,
                "calc_id":         cid,
                "order_id":        order_id,
                "account_id":      int(cp["account_id"]),
                "contributed_qty": total_qty,
                "first_fill_ts":   first_ts,
                "last_fill_ts":    last_ts,
                "lifecycle_id":    new_uuid,
            })

    return {
        "cps_in_scope":                  len(cps),
        "exit_remap":                    exit_remap,
        "lifecycle_gen":                 lifecycle_gen,
        "fill_stamps":                   fill_stamps,
        "junction_rows":                 junction_rows,
        "junction_skip_no_calc":         skip_no_calc,
        "junction_skip_no_order":        skip_no_order,
        "junction_skip_already_populated": skip_already_populated,
    }


# ── Application ────────────────────────────────────────────────────────


async def _apply_plan(
    db: Any,
    plan: Dict[str, Any],
    verbose: bool,
) -> Dict[str, int]:
    """Write the planned changes in a single transaction.

    Returns counts of writes performed.
    """
    exit_remap = plan["exit_remap"]
    lifecycle_gen = plan["lifecycle_gen"]
    fill_stamps = plan["fill_stamps"]
    junction_rows = plan["junction_rows"]

    n_exit = 0
    n_lifecycle = 0
    n_fill_stamp = 0
    n_junction = 0
    try:
        for cp_id, _, new_value in exit_remap:
            await db._conn.execute(
                "UPDATE closed_positions SET exit_reason = ? WHERE id = ?",
                (new_value, cp_id),
            )
            n_exit += 1

        for cp_id, _, new_uuid in lifecycle_gen:
            await db._conn.execute(
                "UPDATE closed_positions SET lifecycle_id = ? WHERE id = ?",
                (new_uuid, cp_id),
            )
            n_lifecycle += 1

        for fill_id, new_uuid in fill_stamps:
            await db._conn.execute(
                "UPDATE fills SET lifecycle_id = ? "
                "WHERE id = ? AND lifecycle_id IS NULL",
                (new_uuid, fill_id),
            )
            n_fill_stamp += 1

        for jr in junction_rows:
            # Use the canonical helper so the upsert semantics match
            # what Phase 2.1's forward-path writer will use.
            await db.upsert_position_calc_link(jr)
            n_junction += 1

        await db._conn.commit()
    except BaseException:
        try:
            await db._conn.rollback()
        except Exception:
            pass
        raise

    if verbose:
        print()
        print(f"Updated exit_reason: {n_exit} row(s)")
        print(f"Generated lifecycle_id: {n_lifecycle} row(s)")
        print(f"Stamped lifecycle_id onto fills: {n_fill_stamp} row(s)")
        print(f"Inserted positions_calcs: {n_junction} row(s)")

    return {
        "exit_remap_applied":     n_exit,
        "lifecycle_gen_applied":  n_lifecycle,
        "fill_stamps_applied":    n_fill_stamp,
        "junction_rows_applied":  n_junction,
    }


# ── Output ────────────────────────────────────────────────────────────


def _print_plan(plan: Dict[str, Any]) -> None:
    n_remap = len(plan["exit_remap"])
    n_life = len(plan["lifecycle_gen"])
    n_stamp = len(plan["fill_stamps"])
    n_junction = len(plan["junction_rows"])

    print()
    print("=" * 70)
    print("PLAN — calc-linkage backfill")
    print("=" * 70)
    print(f"  closed_positions in scope:              {plan['cps_in_scope']}")
    print(f"  exit_reason re-map (legacy → enum):     {n_remap}")
    print(f"  lifecycle_id generated (cp rows):       {n_life}")
    print(f"  fills stamped with lifecycle_id:        {n_stamp}")
    print(f"  positions_calcs rows to insert:         {n_junction}")
    print(f"  junction skipped (no calc_id on fill):  {plan['junction_skip_no_calc']}")
    print(f"  junction skipped (order_id unresolved): {plan['junction_skip_no_order']}")
    print(f"  junction skipped (cp already populated):{plan['junction_skip_already_populated']}")

    if n_remap:
        print()
        print("Sample exit_reason re-maps (first 5):")
        for cp_id, old, new in plan["exit_remap"][:5]:
            print(f"  cp_id={cp_id}: {old!r} → {new!r}")
        if n_remap > 5:
            print(f"  ... and {n_remap - 5} more")

    if n_junction:
        print()
        print("Sample junction rows (first 5):")
        for jr in plan["junction_rows"][:5]:
            print(
                f"  position_id={jr['position_id']} calc_id={jr['calc_id']!r} "
                f"order_id={jr['order_id']} qty={jr['contributed_qty']:.4f}"
            )
        if n_junction > 5:
            print(f"  ... and {n_junction - 5} more")


# ── Programmable entrypoint ────────────────────────────────────────────


async def run_backfill(
    db_path: str = DEFAULT_DB_PATH,
    *,
    apply: bool = False,
    account_id: Optional[int] = None,
    symbol: Optional[str] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Programmable entrypoint (used by main + tests)."""
    from core.database import DatabaseManager
    db = DatabaseManager(path=db_path)
    await db.initialize()
    try:
        plan = await _build_plan(db, account_id, symbol)
        if verbose:
            print(f"Read {plan['cps_in_scope']} closed_positions from {db_path}")
            if account_id is not None:
                print(f"  Filter: account_id={account_id}")
            if symbol:
                print(f"  Filter: symbol={symbol}")
            _print_plan(plan)

        result = {
            "cps_in_scope":         plan["cps_in_scope"],
            "exit_remap_planned":   len(plan["exit_remap"]),
            "lifecycle_gen_planned": len(plan["lifecycle_gen"]),
            "fill_stamps_planned":  len(plan["fill_stamps"]),
            "junction_rows_planned": len(plan["junction_rows"]),
            "junction_skip_no_calc": plan["junction_skip_no_calc"],
            "junction_skip_no_order": plan["junction_skip_no_order"],
            "junction_skip_already_populated": plan["junction_skip_already_populated"],
            "applied":              False,
        }

        if not apply:
            if verbose:
                print()
                print("[DRY-RUN] No changes made.")
                print(
                    "Re-run with --apply after backing up the DB. "
                    "Script wraps writes in a single transaction and "
                    "is idempotent — re-running plans 0 work after "
                    "first --apply."
                )
            return result

        if verbose:
            print()
            print("Applying (atomic — single transaction)...")
        applied = await _apply_plan(db, plan, verbose)
        result.update(applied)
        result["applied"] = True
        return result
    finally:
        await db.close()


# ── CLI ────────────────────────────────────────────────────────────────


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Write the planned changes (default: dry-run).",
    )
    parser.add_argument(
        "--account-id", type=int, default=None,
        help="Restrict to one account_id (default: all).",
    )
    parser.add_argument(
        "--symbol", default=None,
        help="Restrict to one symbol.",
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
        print("WARNING: --apply WILL UPDATE closed_positions + fills + INSERT")
        print(f"  positions_calcs in {args.db}")
        print()
        print("  Idempotent + transaction-wrapped, but back up first.")
        print("=" * 70)

    result = asyncio.run(run_backfill(
        db_path=args.db,
        apply=args.apply,
        account_id=args.account_id,
        symbol=args.symbol,
    ))
    return 0 if result is not None else 1


if __name__ == "__main__":
    sys.exit(main())
