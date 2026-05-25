"""
Phase 0.0.6 (T190): operator-controlled rebuild of ``closed_positions``
from cleaned fills.

Operator workflow:

  1. Back up the DB.
  2. Run ``python scripts/dedup_fills.py --apply`` (Phase 0.0.3) to
     clean ``fills`` of synthetic backfill duplicates.
  3. Run ``python scripts/rebuild_closed_positions.py --apply`` (this
     script) to wipe and rebuild ``closed_positions`` from the cleaned
     ``fills`` via ``core.position_grouping.group_fills_into_positions``.
  4. The reconciler picks up rebuilt rows (``backfill_completed=0``)
     and re-runs MFE/MAE with T175's gross-PnL floor invariant in
     place.

USAGE:

    # Default: DRY-RUN. Prints a diff (would-be-rebuilt vs existing).
    # No DB writes.
    python scripts/rebuild_closed_positions.py

    # APPLY: deletes existing closed_positions in scope and inserts
    # fresh rebuilt rows. BACKUP THE DB FIRST.
    python scripts/rebuild_closed_positions.py --apply

    # Restrict to one account / one symbol for rehearsal.
    python scripts/rebuild_closed_positions.py --account-id 1
    python scripts/rebuild_closed_positions.py --symbol BSBUSDT
    python scripts/rebuild_closed_positions.py --account-id 1 --symbol BSBUSDT --apply

    # Rehearse against a backup before touching the live DB.
    python scripts/rebuild_closed_positions.py --db /path/to/backup.db --apply

WHAT --apply DOES:

  - DELETEs existing ``closed_positions`` rows whose symbol HAS a
    rebuilt equivalent in the current run (i.e., the symbol's fills
    produce at least one closed-position record via
    ``group_fills_into_positions``). Rows for "orphan symbols" --
    symbols that have existing closed_positions but no usable fills
    to rebuild from (pre-Phase-0.0.2 backfill artifacts) -- are
    PRESERVED untouched.
  - INSERTs fresh rows from ``group_fills_into_positions(fills)``.
    Each new row has ``source='rebuilt_from_fills'``,
    ``terminal_position_id='rebuilt:{symbol}:{direction}:{entry_ms}'``
    (deterministic), and ``backfill_completed=0`` so the reconciler
    re-runs MFE/MAE.

  Pass ``--wipe-orphans`` to also DELETE orphan-symbol rows on
  --apply (the T190 default, retained for explicit override).

WHAT DRY-RUN DOES:

  - Reads fills, runs grouping, reads existing rows, prints a
    per-symbol diff (rebuilt count vs existing count), a detail
    block for the most-affected symbol (or ``--symbol`` if set),
    AND an "orphan symbols" summary listing symbols whose rows
    will be preserved on --apply.
  - NO DB writes.

IMPORTANT:

  - NOT auto-run on engine startup. Operator-controlled only.
  - BACKUP REQUIRED before --apply. The DELETE-then-INSERT runs in
    one transaction; if anything fails mid-script, the transaction
    rolls back. A pre-script backup is the safety net of last
    resort.
  - This script is **destructive** on existing closed_positions
    rows whose symbol has a rebuilt equivalent (including any
    manually-edited rows for those symbols). If you have manual
    notes that must survive, narrow the scope with ``--symbol``
    or restore from backup after.
  - Orphan-symbol rows are PRESERVED by default (see WHAT --apply
    DOES above). The ``--wipe-orphans`` flag is the explicit
    override.
  - Idempotent — rerunning with the same scope produces the same
    final state (``group_fills_into_positions`` is deterministic).

PLAN REFERENCE: docs/design/calc_linkage_implementation_plan.md
Phase 0.0.6 row in the Tasks table.
T178 background: docs/audits/2026-05-25-t178-fills-data-quality.md
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.position_grouping import group_fills_into_positions  # noqa: E402


DEFAULT_DB_PATH = os.path.join(ROOT, "data", "risk_engine.db")


# ── Helpers (read/group/diff/write) ────────────────────────────────────


async def _read_fills(
    db: Any,
    account_id: Optional[int],
    symbol: Optional[str],
) -> List[Dict[str, Any]]:
    """Read fills in scope, chronologically. Dedup by exchange_fill_id
    (the upstream Phase 0.0.3 dedup_fills.py is the canonical dedup;
    this redundant fallback covers re-runs against a non-deduped DB)."""
    sql = "SELECT * FROM fills WHERE COALESCE(exchange_fill_id, '') != ''"
    params: List = []
    if account_id is not None:
        sql += " AND account_id = ?"
        params.append(account_id)
    if symbol:
        sql += " AND symbol = ?"
        params.append(symbol)
    sql += " ORDER BY timestamp_ms ASC, id ASC"

    async with db._conn.execute(sql, params) as cur:
        rows = await cur.fetchall()

    seen_ids: set = set()
    deduped: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        key = (d.get("account_id"), d.get("exchange_fill_id"))
        if key in seen_ids:
            continue
        seen_ids.add(key)
        deduped.append(d)
    return deduped


async def _read_existing_closed(
    db: Any,
    account_id: Optional[int],
    symbol: Optional[str],
) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM closed_positions WHERE 1=1"
    params: List = []
    if account_id is not None:
        sql += " AND account_id = ?"
        params.append(account_id)
    if symbol:
        sql += " AND symbol = ?"
        params.append(symbol)
    sql += " ORDER BY exit_time_ms ASC, id ASC"
    async with db._conn.execute(sql, params) as cur:
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def _delete_existing_in_scope(
    db: Any,
    account_id: Optional[int],
    symbol: Optional[str],
    restrict_to_symbols: Optional[set] = None,
) -> int:
    """DELETE existing closed_positions in scope. Does NOT commit -- the
    caller (run_rebuild's --apply path) wraps DELETE + INSERTs in a
    single transaction and commits once at the end so a mid-script
    kill rolls back to consistent state (T191 audit B1 fix).

    ``restrict_to_symbols`` (T194 fix): when provided, only DELETE rows
    whose symbol is in the set. Used by the default --apply path to
    PRESERVE existing closed_positions for "orphan symbols" — symbols
    that have closed_positions rows but no usable fills to rebuild
    from. The orphan rows are reconstructions from the pre-Phase-0.0.2
    backfill (which built closed_positions directly from exchange_history
    REALIZED_PNL rows). Wiping them without a rebuilt replacement would
    silently lose data; preserving them lets the operator investigate
    or re-backfill those symbols later.
    """
    sql = "DELETE FROM closed_positions WHERE 1=1"
    params: List = []
    if account_id is not None:
        sql += " AND account_id = ?"
        params.append(account_id)
    if symbol:
        sql += " AND symbol = ?"
        params.append(symbol)
    if restrict_to_symbols is not None:
        if not restrict_to_symbols:
            # Empty set -> nothing to delete. Skip the query entirely.
            return 0
        placeholders = ",".join("?" * len(restrict_to_symbols))
        sql += f" AND symbol IN ({placeholders})"
        params.extend(sorted(restrict_to_symbols))
    cur = await db._conn.execute(sql, params)
    return cur.rowcount


def _iso(ms: int) -> str:
    if not ms:
        return "--"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _print_diff(
    rebuilt: List[Dict[str, Any]],
    existing: List[Dict[str, Any]],
    detail_symbol: Optional[str] = None,
) -> None:
    rebuilt_by_sym: Dict[str, List[Dict]] = defaultdict(list)
    for r in rebuilt:
        rebuilt_by_sym[r["symbol"]].append(r)
    existing_by_sym: Dict[str, List[Dict]] = defaultdict(list)
    for r in existing:
        existing_by_sym[r["symbol"]].append(r)

    syms = sorted(set(rebuilt_by_sym.keys()) | set(existing_by_sym.keys()))
    print()
    print("=== Per-symbol counts ===")
    print(f"{'symbol':<15} {'rebuilt':>8} {'existing':>9} {'diff':>5}")
    for sym in syms:
        rb = len(rebuilt_by_sym[sym])
        ex = len(existing_by_sym[sym])
        diff = rb - ex
        marker = "" if diff == 0 else " <--"
        print(f"{sym:<15} {rb:>8} {ex:>9} {diff:>+5}{marker}")

    if not detail_symbol:
        # Pick the symbol with the largest absolute diff for detail.
        if syms:
            detail_symbol = max(
                syms,
                key=lambda s: abs(
                    len(rebuilt_by_sym[s]) - len(existing_by_sym[s])
                ),
            )

    if not detail_symbol:
        return

    print()
    print(f"=== Detail for {detail_symbol} ===")
    header = (
        f"{'side':>5} {'qty':>10} {'entry':>10} {'exit':>10} "
        f"{'pnl':>8} {'entry_iso':<20} {'exit_iso':<20} source"
    )
    print(header)

    print("--- REBUILT ---")
    for r in rebuilt_by_sym.get(detail_symbol, []):
        print(
            f"{r['direction']:>5} {r.get('quantity', 0):>10.4f} "
            f"{r.get('entry_price', 0):>10.4f} {r.get('exit_price', 0):>10.4f} "
            f"{r.get('net_pnl', 0):>8.2f} "
            f"{_iso(r.get('entry_time_ms', 0)):<20} "
            f"{_iso(r.get('exit_time_ms', 0)):<20} "
            f"{r.get('source', '')}"
        )

    print("--- EXISTING (would be wiped on --apply) ---")
    for r in existing_by_sym.get(detail_symbol, []):
        print(
            f"{r['direction']:>5} {r.get('quantity', 0):>10.4f} "
            f"{r.get('entry_price', 0):>10.4f} {r.get('exit_price', 0):>10.4f} "
            f"{r.get('net_pnl', 0):>8.2f} "
            f"{_iso(r.get('entry_time_ms', 0)):<20} "
            f"{_iso(r.get('exit_time_ms', 0)):<20} "
            f"{r.get('source', '')}"
        )


# ── Programmable entrypoint ────────────────────────────────────────────


async def run_rebuild(
    db_path: str = DEFAULT_DB_PATH,
    *,
    apply: bool = False,
    account_id: Optional[int] = None,
    symbol: Optional[str] = None,
    wipe_orphans: bool = False,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Programmable entrypoint (used by main + tests).

    Returns a summary dict with ``fills_read``, ``rebuilt_count``,
    ``existing_count``, ``deleted_count``, ``inserted_count``,
    ``orphan_symbols``, ``orphan_rows_preserved``, ``applied``.

    ``wipe_orphans`` (T194 fix): default ``False`` preserves existing
    closed_positions rows for "orphan symbols" — symbols that have
    closed_positions data but no usable fills to rebuild from (legacy
    pre-Phase-0.0.2 backfill artifacts). Set ``True`` to also wipe
    those rows.
    """
    from core.database import DatabaseManager

    db = DatabaseManager(path=db_path)
    await db.initialize()

    try:
        fills = await _read_fills(db, account_id, symbol)
        if verbose:
            print(f"Read {len(fills)} fills from {db_path}")
            if account_id is not None:
                print(f"  Filter: account_id={account_id}")
            if symbol:
                print(f"  Filter: symbol={symbol}")

        rebuilt = group_fills_into_positions(fills)
        if verbose:
            print(f"Grouped into {len(rebuilt)} closed positions")

        existing = await _read_existing_closed(db, account_id, symbol)
        if verbose:
            print(f"Existing closed_positions in scope: {len(existing)}")

        # T194: identify orphan symbols (existing rows with no rebuilt
        # equivalent — usually pre-Phase-0.0.2 backfill artifacts where
        # closed_positions was reconstructed from exchange_history
        # REALIZED_PNL rows without writing OPEN fills, leaving the
        # rebuild script with no input to reconstruct from).
        rebuilt_symbols = {r["symbol"] for r in rebuilt}
        existing_symbols = {r["symbol"] for r in existing}
        orphan_symbols = sorted(existing_symbols - rebuilt_symbols)
        orphan_rows = [r for r in existing if r["symbol"] in orphan_symbols]

        if verbose:
            _print_diff(rebuilt, existing, detail_symbol=symbol)
            if orphan_symbols:
                print()
                print(
                    f"Orphan symbols (existing closed_positions but NO "
                    f"rebuilt equivalent): {len(orphan_symbols)} symbols, "
                    f"{len(orphan_rows)} rows"
                )
                for s in orphan_symbols[:20]:
                    n = sum(1 for r in orphan_rows if r["symbol"] == s)
                    print(f"  {s}: {n} row(s)")
                if len(orphan_symbols) > 20:
                    print(f"  ... and {len(orphan_symbols) - 20} more")
                if not wipe_orphans:
                    print(
                        "  (preserved by default — pass --wipe-orphans "
                        "to also delete these on --apply)"
                    )

        if not apply:
            if verbose:
                print()
                print("[DRY-RUN] No changes made.")
                msg = (
                    "Re-run with --apply after backing up the DB to "
                    "DELETE existing rows in scope and INSERT rebuilt "
                    "rows. T178 Layer 3 corruption in the existing "
                    "data will be replaced by clean chronological-walk "
                    "attribution."
                )
                if orphan_symbols and not wipe_orphans:
                    msg += (
                        f" Orphan-symbol rows ({len(orphan_rows)} "
                        f"across {len(orphan_symbols)} symbols) will be "
                        f"PRESERVED."
                    )
                print(msg)
            return {
                "fills_read":            len(fills),
                "rebuilt_count":         len(rebuilt),
                "existing_count":        len(existing),
                "deleted_count":         0,
                "inserted_count":        0,
                "orphan_symbols":        orphan_symbols,
                "orphan_rows_preserved": 0,
                "applied":               False,
            }

        if verbose:
            print()
            print("Applying rebuild (atomic — single transaction)...")
        # T191 audit B1 fix: wrap DELETE + INSERT-loop in a SINGLE
        # transaction so a mid-script kill (Ctrl+C, OOM, machine crash)
        # rolls back to the pre-script state instead of leaving the DB
        # with closed_positions wiped but rebuilt rows incomplete. The
        # pre-script operator backup remains the safety net of last
        # resort but is no longer the FIRST line of defense.
        deleted = 0
        inserted = 0
        orphan_rows_preserved = 0
        try:
            # T194: default --apply preserves orphan-symbol rows by
            # restricting the DELETE to symbols that have rebuilt
            # replacements. Pass --wipe-orphans to wipe everything in
            # scope (the original T190 behavior).
            if wipe_orphans:
                restrict_set = None
                orphan_rows_preserved = 0
            else:
                restrict_set = rebuilt_symbols
                orphan_rows_preserved = len(orphan_rows)
            deleted = await _delete_existing_in_scope(
                db, account_id, symbol,
                restrict_to_symbols=restrict_set,
            )
            for r in rebuilt:
                # commit=False defers commit to the outer try-block.
                # insert_closed_position(commit=False) re-raises on
                # failure (T191 audit B1) so the outer try-except
                # rolls back the entire DELETE + partial INSERTs
                # instead of leaving the DB in inconsistent state.
                # T176 REPLACE preservation + T168 pollution guard
                # still apply per-row.
                await db.insert_closed_position(r, commit=False)
                inserted += 1
            await db._conn.commit()
        except BaseException:
            # KeyboardInterrupt + Exception both roll back. Reraise
            # so the caller / shell sees the original error and the
            # exit code propagates.
            try:
                await db._conn.rollback()
            except Exception:
                pass
            raise

        if verbose:
            print(f"Deleted {deleted} existing rows.")
            print(f"Inserted {inserted} rebuilt rows.")
            if orphan_rows_preserved:
                print(
                    f"Preserved {orphan_rows_preserved} orphan-symbol rows "
                    f"({len(orphan_symbols)} symbols) — no rebuilt "
                    f"equivalent. Pass --wipe-orphans to delete these "
                    f"too on next --apply."
                )
            print(
                "Reconciler will pick up the new rows (backfill_completed=0) "
                "and re-run MFE/MAE with T175's gross-PnL floor on next sweep."
            )

        return {
            "fills_read":            len(fills),
            "rebuilt_count":         len(rebuilt),
            "existing_count":        len(existing),
            "deleted_count":         deleted,
            "inserted_count":        inserted,
            "orphan_symbols":        orphan_symbols,
            "orphan_rows_preserved": orphan_rows_preserved,
            "applied":               True,
        }
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
        help="DELETE existing closed_positions in scope + INSERT rebuilt "
             "(default: dry-run, no writes).",
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
    parser.add_argument(
        "--wipe-orphans", action="store_true",
        help="Also DELETE existing closed_positions rows for orphan "
             "symbols (existing rows with no rebuilt equivalent). "
             "Default: preserve orphan-symbol rows (legacy backfill "
             "artifacts that can't be reconstructed from fills).",
    )
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"ERROR: DB not found at {args.db}", file=sys.stderr)
        return 1

    if args.apply:
        print("=" * 70)
        print("WARNING: --apply WILL DELETE + REBUILD closed_positions rows in")
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

    summary = asyncio.run(run_rebuild(
        db_path=args.db,
        apply=args.apply,
        account_id=args.account_id,
        symbol=args.symbol,
        wipe_orphans=args.wipe_orphans,
    ))
    print()
    print("Summary:")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
