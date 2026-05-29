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
     The forward path stamps fills.lifecycle_id on BOTH opening fills
     (P2.T1 junction link, T232) and closing fills (P2.T2 primary
     inherit), so this backfill only catches legacy/historical rows.

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


# Legacy → spec §3.4 enum mapping. Anything not in this dict that
# IS in SPEC_EXIT_REASON_ENUM is treated as already-migrated and
# left untouched. Anything not in EITHER set surfaces as a warning
# in the dry-run output (task 207 audit follow-up).
EXIT_REASON_REMAP: Dict[Optional[str], str] = {
    None:      "MANUAL_OTHER",
    "":        "MANUAL_OTHER",
    "manual":  "MANUAL_OTHER",
    "tp":      "TP_PLANNED",
    "sl":      "SL_PLANNED",
}


# Spec §3.4 enum — the canonical post-T206 exit_reason values.
# Used by the warn-on-unmapped guard added in task 207 (audit
# follow-up): values that are neither in the remap nor in this set
# get surfaced as a warning so a future legacy DB with a
# non-spec-enum value (e.g., 'forced', 'auto_close') doesn't get
# silently left as-is.
SPEC_EXIT_REASON_ENUM: frozenset = frozenset({
    "TP_PLANNED", "TP_AMENDED", "SL_PLANNED", "SL_AMENDED",
    "TP_LADDER_COMPLETE", "MIXED",
    "MANUAL_INTERVENTION", "MANUAL_DISCIPLINE_BREAK",
    "MANUAL_NEW_OPPORTUNITY", "MANUAL_OTHER",
    "LIQUIDATION", "ADL", "EXPIRED",
})


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
    position_id: str,
) -> int:
    async with db._conn.execute(
        "SELECT COUNT(*) FROM positions_calcs WHERE position_id = ?",
        (position_id,),
    ) as cur:
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def _read_pretrade_lifecycle_stamps(
    db: Any,
    account_id: Optional[int],
    symbol: Optional[str],
    cp_lifecycle_map: Dict[int, str],
) -> List[Tuple[int, str]]:
    """Find pre_trade_log rows whose ``calc_id`` is referenced by a
    fill of a closed_position carrying (or about-to-carry)
    ``lifecycle_id``.

    Per spec §3.5: ``pre_trade_log.lifecycle_id`` is "back-filled
    when calc first contributes to a position; multi-calc scale-ins
    share same lifecycle_id across all their pre_trade_log rows."

    ``cp_lifecycle_map`` is the planning-time {cp_id → lifecycle_id}
    union of (a) cps with existing lifecycle_id already in the DB,
    plus (b) cps for which the current planning pass generated a
    fresh UUID via ``lifecycle_gen``. The query intentionally does
    NOT filter on ``cp.lifecycle_id IS NOT NULL`` because at dry-run
    + within-transaction planning time the fresh UUIDs haven't been
    written yet.

    Live-DB legacy fills currently have no calc_id, so this query
    will return 0 rows for the current state — but the helper exists
    so a future DB with calc-attributed legacy fills migrates cleanly.

    Returns ``[(pretrade_id, lifecycle_id_uuid), ...]``.
    """
    if not cp_lifecycle_map:
        return []
    sql = (
        "SELECT DISTINCT p.id AS pretrade_id, cp.id AS cp_id "
        "FROM pre_trade_log p "
        "JOIN fills f ON f.calc_id = p.calc_id "
        "JOIN closed_positions cp ON cp.terminal_position_id = f.terminal_position_id "
        "WHERE p.lifecycle_id IS NULL "
        "AND COALESCE(p.calc_id, '') != ''"
    )
    params: List = []
    if account_id is not None:
        sql += " AND p.account_id = ? AND cp.account_id = ?"
        params.extend([account_id, account_id])
    if symbol:
        sql += " AND cp.symbol = ?"
        params.append(symbol)
    async with db._conn.execute(sql, params) as cur:
        rows = await cur.fetchall()
    out: List[Tuple[int, str]] = []
    for r in rows:
        cp_id = int(r["cp_id"])
        if cp_id in cp_lifecycle_map:
            out.append((int(r["pretrade_id"]), cp_lifecycle_map[cp_id]))
    return out


async def _read_order_lifecycle_stamps(
    db: Any,
    account_id: Optional[int],
    symbol: Optional[str],
    cp_lifecycle_map: Dict[int, str],
) -> List[Tuple[int, str]]:
    """Find orders rows whose ``exchange_order_id`` is referenced by
    a fill of a closed_position carrying (or about-to-carry)
    ``lifecycle_id``.

    Per spec §3.5: ``orders.lifecycle_id`` is "denormalized; copied
    from junction when order links to position." Legacy orders that
    won't pass through Phase 2.1's forward path need this backfill
    so the single-key audit query (GET /context/lifecycle/{id})
    returns the historical order chain.

    See :func:`_read_pretrade_lifecycle_stamps` docstring for why
    the helper takes ``cp_lifecycle_map`` instead of joining on
    ``cp.lifecycle_id IS NOT NULL``.

    Returns ``[(order_id, lifecycle_id_uuid), ...]``.
    """
    if not cp_lifecycle_map:
        return []
    sql = (
        "SELECT DISTINCT o.id AS order_id, cp.id AS cp_id "
        "FROM orders o "
        "JOIN fills f ON f.exchange_order_id = o.exchange_order_id "
        "JOIN closed_positions cp ON cp.terminal_position_id = f.terminal_position_id "
        "WHERE o.lifecycle_id IS NULL "
        "AND COALESCE(o.exchange_order_id, '') != ''"
    )
    params: List = []
    if account_id is not None:
        sql += " AND o.account_id = ? AND cp.account_id = ?"
        params.extend([account_id, account_id])
    if symbol:
        sql += " AND cp.symbol = ?"
        params.append(symbol)
    async with db._conn.execute(sql, params) as cur:
        rows = await cur.fetchall()
    out: List[Tuple[int, str]] = []
    for r in rows:
        cp_id = int(r["cp_id"])
        if cp_id in cp_lifecycle_map:
            out.append((int(r["order_id"]), cp_lifecycle_map[cp_id]))
    return out


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
    unmapped_exit_reasons: List[Tuple[int, Optional[str]]] = []
    for cp in cps:
        old = cp.get("exit_reason")
        if old in EXIT_REASON_REMAP:
            new = EXIT_REASON_REMAP[old]
            if new != old:
                exit_remap.append((cp["id"], old, new))
        elif old not in SPEC_EXIT_REASON_ENUM:
            # Neither in remap nor already a spec-enum value — surface
            # so the operator can decide whether to extend the remap
            # dict + re-run, or accept the value as-is.
            unmapped_exit_reasons.append((cp["id"], old))

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
        # position. Keyed by terminal_position_id (TEXT) per P2.T1 — the
        # same key the forward path (order_manager) writes (spec §3.1),
        # NOT closed_positions.id. A cp without a tpid can't be mapped to
        # a position key, so it can't seed the junction → skip. When
        # several closed_positions share a tpid (partial-close history),
        # the first seeds the junction; the rest skip as already-populated.
        if not tpid:
            continue
        existing_junction = await _existing_junction_count(db, tpid)
        if existing_junction > 0:
            skip_already_populated += 1
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
                "position_id":     tpid,
                "calc_id":         cid,
                "order_id":        order_id,
                "account_id":      int(cp["account_id"]),
                "contributed_qty": total_qty,
                "first_fill_ts":   first_ts,
                "last_fill_ts":    last_ts,
                "lifecycle_id":    new_uuid,
            })

    # Task 207 audit follow-up: spec §3.5 mandates lifecycle_id on
    # pre_trade_log + orders (denormalized from the junction). Forward
    # path (Phase 2.1) handles new positions; this backfill closes the
    # gap for legacy rows.
    #
    # Build the planning-time {cp_id → lifecycle_id} map: existing
    # values from the DB (already-stamped cps) PLUS the freshly-
    # generated UUIDs from this pass. The stamp helpers can't query
    # cp.lifecycle_id directly because the fresh UUIDs aren't written
    # until _apply_plan runs.
    cp_lifecycle_map: Dict[int, str] = {}
    for cp in cps:
        if cp.get("lifecycle_id"):
            cp_lifecycle_map[int(cp["id"])] = str(cp["lifecycle_id"])
    for cp_id, _tpid, new_uuid in lifecycle_gen:
        cp_lifecycle_map[cp_id] = new_uuid

    pretrade_lifecycle_stamps = await _read_pretrade_lifecycle_stamps(
        db, account_id, symbol, cp_lifecycle_map,
    )
    order_lifecycle_stamps = await _read_order_lifecycle_stamps(
        db, account_id, symbol, cp_lifecycle_map,
    )

    return {
        "cps_in_scope":                  len(cps),
        "exit_remap":                    exit_remap,
        "unmapped_exit_reasons":         unmapped_exit_reasons,
        "lifecycle_gen":                 lifecycle_gen,
        "fill_stamps":                   fill_stamps,
        "pretrade_lifecycle_stamps":     pretrade_lifecycle_stamps,
        "order_lifecycle_stamps":        order_lifecycle_stamps,
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
    pretrade_stamps = plan["pretrade_lifecycle_stamps"]
    order_stamps = plan["order_lifecycle_stamps"]

    n_exit = 0
    n_lifecycle = 0
    n_fill_stamp = 0
    n_junction = 0
    n_pretrade_stamp = 0
    n_order_stamp = 0
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

        # Task 207: pre_trade_log + orders lifecycle_id back-stamp.
        # Only UPDATE rows whose lifecycle_id is currently NULL — the
        # WHERE guard makes this idempotent + safe against multi-cp
        # contention (a pre_trade_log row that already won an earlier
        # lifecycle stamp stays that way).
        for pretrade_id, lifecycle in pretrade_stamps:
            await db._conn.execute(
                "UPDATE pre_trade_log SET lifecycle_id = ? "
                "WHERE id = ? AND lifecycle_id IS NULL",
                (lifecycle, pretrade_id),
            )
            n_pretrade_stamp += 1
        for order_id, lifecycle in order_stamps:
            await db._conn.execute(
                "UPDATE orders SET lifecycle_id = ? "
                "WHERE id = ? AND lifecycle_id IS NULL",
                (lifecycle, order_id),
            )
            n_order_stamp += 1

        await db._conn.commit()
    except BaseException:
        try:
            await db._conn.rollback()
        except Exception:
            pass
        raise

    if verbose:
        print()
        print(f"Updated exit_reason:               {n_exit} row(s)")
        print(f"Generated lifecycle_id:            {n_lifecycle} row(s)")
        print(f"Stamped lifecycle_id onto fills:   {n_fill_stamp} row(s)")
        print(f"Stamped lifecycle_id onto pretrade:{n_pretrade_stamp} row(s)")
        print(f"Stamped lifecycle_id onto orders:  {n_order_stamp} row(s)")
        print(f"Inserted positions_calcs:          {n_junction} row(s)")

    return {
        "exit_remap_applied":           n_exit,
        "lifecycle_gen_applied":        n_lifecycle,
        "fill_stamps_applied":          n_fill_stamp,
        "pretrade_stamps_applied":      n_pretrade_stamp,
        "order_stamps_applied":         n_order_stamp,
        "junction_rows_applied":        n_junction,
    }


# ── Output ────────────────────────────────────────────────────────────


def _print_plan(plan: Dict[str, Any]) -> None:
    n_remap = len(plan["exit_remap"])
    n_life = len(plan["lifecycle_gen"])
    n_stamp = len(plan["fill_stamps"])
    n_pretrade = len(plan["pretrade_lifecycle_stamps"])
    n_orders = len(plan["order_lifecycle_stamps"])
    n_junction = len(plan["junction_rows"])
    n_unmapped = len(plan.get("unmapped_exit_reasons", []))

    # Task 207: surface unmapped exit_reason values up-front so the
    # operator notices BEFORE running --apply.
    if n_unmapped:
        print()
        print("=" * 70)
        print("WARNING — unmapped exit_reason values detected")
        print("=" * 70)
        print(
            "  These rows have an exit_reason that is neither in the "
            "legacy remap (manual/tp/sl/empty) nor in the spec §3.4 "
            "enum. They will be LEFT UNCHANGED on --apply. Extend "
            "EXIT_REASON_REMAP and re-run if these should be mapped."
        )
        for cp_id, val in plan["unmapped_exit_reasons"][:10]:
            print(f"  cp_id={cp_id}: exit_reason={val!r}")
        if n_unmapped > 10:
            print(f"  ... and {n_unmapped - 10} more")

    print()
    print("=" * 70)
    print("PLAN — calc-linkage backfill")
    print("=" * 70)
    print(f"  closed_positions in scope:                {plan['cps_in_scope']}")
    print(f"  exit_reason re-map (legacy → enum):       {n_remap}")
    print(f"  exit_reason unmapped (will be left as-is):{n_unmapped}")
    print(f"  lifecycle_id generated (cp rows):         {n_life}")
    print(f"  fills stamped with lifecycle_id:          {n_stamp}")
    print(f"  pre_trade_log stamped with lifecycle_id:  {n_pretrade}")
    print(f"  orders stamped with lifecycle_id:         {n_orders}")
    print(f"  positions_calcs rows to insert:           {n_junction}")
    print(f"  junction skipped (no calc_id on fill):    {plan['junction_skip_no_calc']}")
    print(f"  junction skipped (order_id unresolved):   {plan['junction_skip_no_order']}")
    print(f"  junction skipped (cp already populated):  {plan['junction_skip_already_populated']}")

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

    if n_orders:
        print()
        print("Sample orders lifecycle stamps (first 5):")
        for order_id, lifecycle in plan["order_lifecycle_stamps"][:5]:
            print(f"  order_id={order_id} ← lifecycle={lifecycle}")
        if n_orders > 5:
            print(f"  ... and {n_orders - 5} more")


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
            "cps_in_scope":             plan["cps_in_scope"],
            "exit_remap_planned":       len(plan["exit_remap"]),
            "unmapped_exit_reasons":    len(plan.get("unmapped_exit_reasons", [])),
            "lifecycle_gen_planned":    len(plan["lifecycle_gen"]),
            "fill_stamps_planned":      len(plan["fill_stamps"]),
            "pretrade_stamps_planned":  len(plan["pretrade_lifecycle_stamps"]),
            "order_stamps_planned":     len(plan["order_lifecycle_stamps"]),
            "junction_rows_planned":    len(plan["junction_rows"]),
            "junction_skip_no_calc":    plan["junction_skip_no_calc"],
            "junction_skip_no_order":   plan["junction_skip_no_order"],
            "junction_skip_already_populated": plan["junction_skip_already_populated"],
            "applied":                  False,
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
