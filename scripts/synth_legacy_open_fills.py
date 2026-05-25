"""
Phase 0.0.7 (T197): operator-controlled synthesis of OPEN fills for
legacy orphan ``closed_positions``.

Background:
-----------
After Phase 0.0 cleanup, 92 ``closed_positions`` rows remained as
"orphan" rows — ``source='exchange_history_backfill'`` with
``terminal_position_id`` of the form ``bf:SYMBOL:DIR:open_time_ms``.
They originate from a pre-Phase-0.0.2 backfill code path that
reconstructed ``closed_positions`` directly from ``exchange_history``
REALIZED_PNL row fields without persisting any OPEN fills to the
``fills`` table. CLOSE fills for ~14 of the 19 affected symbols WERE
written (the loop at db_orders.py:1037+ inserts a CLOSE fill per RPNL
row), but OPEN fills are synthesized in-memory only during
``backfill_fills_from_exchange_history`` — never persisted.

The orphan rows are correct values (T178 Layer 3 confirms single-
position reconstructions, no cross-position-VWAP). They are just
invisible to any feature that walks fills→position
(``get_position_fills``, the Phase 0.1+ ``positions_calcs`` junction
migration, deviation badges, etc.).

This script closes the gap for positions whose upstream ``exchange_
history`` RPNL row still exists with ``entry_price > 0`` and
``open_time > 0`` — synthesizing one OPEN fill per logical position
and re-deriving the corresponding ``closed_positions`` row via
``core.position_grouping.group_fills_into_positions`` (the same
canonical path Phase 0.0.6's rebuild uses). Recovered rows get
``source='rebuilt_from_fills'`` and the reconciler re-runs MFE/MAE
with T175's gross-PnL floor invariant.

What "no upstream data" means:
------------------------------
Binance's income/REALIZED_PNL API has a historical window (~3 months).
Trades older than that window or trades from a now-wiped earlier
``exchange_history`` populate cannot be re-derived. ~26 of the 92
orphans fall into this bucket (5 symbols are fully zero-data:
CUSDT, DUSKUSDT, MUSDT, TRUMPUSDT, ETCUSDT; the rest are partial-
coverage symbols where some positions are recoverable and others
are not). The unrecoverable orphans stay PRESERVED — they remain
visible in Position History with their original stored values
(which are correct per T178 Layer 3), just without a fills-backed
provenance.

Operator workflow:
------------------
  1. Back up the DB:
     ``cp data/risk_engine.db data/risk_engine.db.pre_synth_legacy.bak``
  2. Run ``python scripts/synth_legacy_open_fills.py`` (dry-run).
     Read the plan carefully — verify per-symbol counts, preserved-
     orphan symbols, and any data-shape surprises.
  3. Run ``python scripts/synth_legacy_open_fills.py --apply`` to
     insert synth OPENs + re-derive closed_positions rows.
  4. The reconciler picks up the new ``rebuilt_from_fills`` rows
     (``backfill_completed=0``) and re-runs MFE/MAE on next sweep.

USAGE:
    # Default: DRY-RUN. Prints per-symbol plan. No DB writes.
    python scripts/synth_legacy_open_fills.py

    # APPLY: insert synth OPENs + replace recoverable orphans with
    # rebuilt rows. BACKUP THE DB FIRST.
    python scripts/synth_legacy_open_fills.py --apply

    # Scope to one account / one symbol for rehearsal.
    python scripts/synth_legacy_open_fills.py --account-id 1 --symbol SIRENUSDT
    python scripts/synth_legacy_open_fills.py --symbol BILLUSDT --apply

    # Rehearse against a backup before touching the live DB.
    python scripts/synth_legacy_open_fills.py --db /path/to/backup.db --apply

WHAT --apply DOES (per recoverable position, all in one transaction):
  1. UPSERT a synth OPEN fill into ``fills``:
        exchange_fill_id = ``synth_open:<rpnl.trade_key>``
        source           = ``synth_legacy_open``
        is_close         = 0
        price            = RPNL.entry_price
        quantity         = RPNL.qty (summed across multi-RPNL groups)
        timestamp_ms     = RPNL.open_time
  2. For each affected symbol, run group_fills_into_positions on all
     fills for that symbol; for each output PositionRecord, find the
     matching ``bf:SYMBOL:DIR:open_time`` orphan and:
       - DELETE the orphan row
       - INSERT the rebuilt row (``source='rebuilt_from_fills'``,
         ``backfill_completed=0``)
  3. Orphan rows with NO matching rebuilt record (unrecoverable
     positions) are PRESERVED untouched.

WHAT DRY-RUN DOES:
  - Reads orphans + upstream RPNL + existing fills.
  - Builds the plan: per-symbol counts of recoverable / preserved
    positions, sample of the first synthesized OPEN per symbol.
  - Emits a per-symbol summary plus a totals line.
  - NO DB writes.

IMPORTANT:
  - NOT auto-run on engine startup. Operator-controlled only.
  - BACKUP REQUIRED before --apply.
  - Idempotent — ``upsert_fill`` on ``synth_open:<trade_key>``
    re-runs as UPDATEs; the per-position DELETE+INSERT is also
    idempotent for the same input.
  - Synth OPEN fills carry ``fee=0`` (Binance RPNL rows record the
    closing fee, not the opening fee — opening-fee data is not
    recoverable from RPNL).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.position_grouping import group_fills_into_positions  # noqa: E402

DEFAULT_DB_PATH = os.path.join(ROOT, "data", "risk_engine.db")

SYNTH_SOURCE = "synth_legacy_open"
ORPHAN_TPID_PREFIX = "bf:"
ORPHAN_SOURCE = "exchange_history_backfill"


# ── Read helpers ───────────────────────────────────────────────────────


async def _read_orphan_signatures(
    db: Any,
    account_id: Optional[int],
    symbol: Optional[str],
) -> List[Dict[str, Any]]:
    """Return existing orphan closed_positions rows in scope.

    Orphan = ``source='exchange_history_backfill'`` AND
    ``terminal_position_id LIKE 'bf:%'``. (The legacy pre-Phase-0.0.2
    backfill convention.)
    """
    sql = (
        "SELECT id, account_id, symbol, direction, entry_time_ms, "
        "exit_time_ms, terminal_position_id, entry_price, exit_price, "
        "quantity, realized_pnl "
        "FROM closed_positions "
        "WHERE source = ? AND terminal_position_id LIKE ?"
    )
    params: List = [ORPHAN_SOURCE, f"{ORPHAN_TPID_PREFIX}%"]
    if account_id is not None:
        sql += " AND account_id = ?"
        params.append(account_id)
    if symbol:
        sql += " AND symbol = ?"
        params.append(symbol)
    sql += " ORDER BY symbol, direction, entry_time_ms"
    async with db._conn.execute(sql, params) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def _read_rpnl_rows(
    db: Any,
    account_id: Optional[int],
    symbol: Optional[str],
) -> List[Dict[str, Any]]:
    """Read all usable REALIZED_PNL exchange_history rows in scope.

    Usable = ``entry_price > 0`` AND ``open_time > 0`` AND ``qty > 0``.
    """
    sql = (
        "SELECT trade_key, time, symbol, income_type, income, direction, "
        "entry_price, exit_price, qty, open_time, fee, asset, account_id "
        "FROM exchange_history "
        "WHERE income_type = 'REALIZED_PNL' "
        "AND entry_price > 0 AND open_time > 0 AND qty > 0"
    )
    params: List = []
    if account_id is not None:
        sql += " AND account_id = ?"
        params.append(account_id)
    if symbol:
        sql += " AND symbol = ?"
        params.append(symbol)
    sql += " ORDER BY symbol, direction, open_time, time"
    async with db._conn.execute(sql, params) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def _read_fills_for_symbols(
    db: Any,
    account_id: Optional[int],
    symbols: List[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """Read all fills (chronologically) grouped by symbol.

    Used after synth OPENs are inserted to re-derive closed_positions
    via the canonical helper.
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    if not symbols:
        return out
    placeholders = ",".join("?" * len(symbols))
    sql = (
        f"SELECT * FROM fills "
        f"WHERE COALESCE(exchange_fill_id, '') != '' "
        f"AND symbol IN ({placeholders})"
    )
    params: List = list(symbols)
    if account_id is not None:
        sql += " AND account_id = ?"
        params.append(account_id)
    sql += " ORDER BY symbol, timestamp_ms ASC, id ASC"
    async with db._conn.execute(sql, params) as cur:
        rows = await cur.fetchall()
    for r in rows:
        d = dict(r)
        out.setdefault(d["symbol"], []).append(d)
    return out


# ── Plan building ──────────────────────────────────────────────────────


def _build_synth_opens(
    rpnl_rows: List[Dict[str, Any]],
    orphan_signatures: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Tuple[Tuple[int, str, str, int], int]]]:
    """Build the list of synth OPEN fills to insert.

    Multi-RPNL same-(symbol, direction, open_time) groups (rare —
    one logical position closed via multiple RPNL events) collapse
    into ONE synth OPEN with summed qty.

    Duplicate orphan rows sharing the same
    (account_id, symbol, direction, entry_time_ms) but different
    exit_time_ms (a known data oddity from earlier double-write
    backfill passes) ALL get queued for deletion on --apply when
    the key is recoverable — the rebuilt row is one per logical
    open_time, so the duplicates collapse into a single clean row.

    Returns ``(synth_opens, recoverable_orphans, preserved_orphans,
    duplicate_keys)``. ``recoverable_orphans`` includes EVERY orphan
    row whose key matches an RPNL group (counting duplicates).
    ``duplicate_keys`` is a list of ``(key, count)`` tuples for
    diagnostic display.
    """
    # Index orphans by (account_id, symbol, direction, entry_time_ms) —
    # multi-valued so duplicate-key orphans are tracked together.
    orphan_index: Dict[Tuple[int, str, str, int], List[Dict[str, Any]]] = defaultdict(list)
    for o in orphan_signatures:
        key = (
            int(o["account_id"]),
            str(o["symbol"]),
            str(o["direction"]),
            int(o["entry_time_ms"] or 0),
        )
        orphan_index[key].append(o)

    duplicate_keys = [
        (key, len(rows)) for key, rows in orphan_index.items() if len(rows) > 1
    ]

    # Group RPNL rows by (account_id, symbol, direction, open_time)
    rpnl_groups: Dict[Tuple[int, str, str, int], List[Dict[str, Any]]] = defaultdict(list)
    for r in rpnl_rows:
        key = (
            int(r["account_id"]),
            str(r["symbol"]),
            str(r["direction"]),
            int(r["open_time"] or 0),
        )
        rpnl_groups[key].append(r)

    synth_opens: List[Dict[str, Any]] = []
    recoverable: List[Dict[str, Any]] = []
    matched_orphan_keys: set = set()

    for key, group in rpnl_groups.items():
        if key not in orphan_index:
            # RPNL exists but no matching orphan — could be a position
            # already rebuilt, or one whose orphan was wiped by a prior
            # rebuild --wipe-orphans run. Skip.
            continue
        account_id, symbol, direction, open_time = key
        # All rows in group share entry_price (same logical position open).
        # qty is summed across the close events that make up the position
        # close (one for singleton, N for multi-close).
        entry_price = float(group[0]["entry_price"])
        total_qty = sum(float(r["qty"] or 0) for r in group)
        # Trade key for the synth fill id: use the earliest close's
        # trade_key for determinism (groups are typically size 1).
        trade_key = sorted(group, key=lambda r: int(r["time"] or 0))[0]["trade_key"]

        synth_opens.append({
            "account_id":           account_id,
            "exchange_fill_id":     f"synth_open:{trade_key}",
            "terminal_fill_id":     "",
            "exchange_order_id":    "",
            "symbol":               symbol,
            "side":                 "BUY" if direction == "LONG" else "SELL",
            "direction":            direction,
            "price":                entry_price,
            "quantity":             total_qty,
            "fee":                  0.0,
            "fee_asset":            "USDT",
            "exchange_position_id": "",
            "terminal_position_id": "",
            "is_close":             0,
            "realized_pnl":         0.0,
            "role":                 "",
            "source":               SYNTH_SOURCE,
            "timestamp_ms":         open_time,
        })
        # Mark ALL orphans with this key as recoverable (collapses
        # duplicate-key orphans into the one rebuilt row).
        recoverable.extend(orphan_index[key])
        matched_orphan_keys.add(key)

    preserved = [
        o for o in orphan_signatures
        if (
            int(o["account_id"]),
            str(o["symbol"]),
            str(o["direction"]),
            int(o["entry_time_ms"] or 0),
        ) not in matched_orphan_keys
    ]

    return synth_opens, recoverable, preserved, duplicate_keys


# ── Simulation-based validation (T199 audit fix) ───────────────────────


def _simulate_helper_emitted_keys(
    fills_by_symbol: Dict[str, List[Dict[str, Any]]],
    synth_opens: List[Dict[str, Any]],
) -> Dict[str, set]:
    """For each affected symbol, simulate the helper run with existing
    fills + planned synth OPENs combined; return the set of
    (direction, entry_time_ms) keys the helper actually emits.

    Used to validate that each planned synth WOULD produce a rebuilt
    record at apply time. Catches two classes of conflict the naive
    "RPNL exists → recoverable" path misses:

      - **Real-OPEN conflict**: a real (non-synth) OPEN fill already
        exists at the same timestamp+price, so the orphan represents
        a partial close of a larger position. Adding the synth would
        inflate the open side; the helper still doesn't emit a record
        because the position remains partially open. Pre-cleanup state
        had BILLUSDT + FOLKSUSDT in this shape.

      - **Lifecycle-absorption**: a residual qty from a prior position
        in the same (symbol, direction) lifecycle prevents qty from
        returning to zero. The helper consumes the synth + close into
        a single longer lifecycle record attributed to the FIRST
        entry_time_ms — leaving subsequent orphan keys unmatched.
        Pre-cleanup state had ONUSDT SHORT at 1774634668929 in this
        shape.

    Pure (no DB I/O). Caller is responsible for pre-loading fills.
    """
    emitted: Dict[str, set] = {}
    for sym, existing_fills in fills_by_symbol.items():
        combined = list(existing_fills)
        combined.extend(s for s in synth_opens if s["symbol"] == sym)
        combined.sort(key=lambda f: (
            int(f.get("timestamp_ms", 0) or 0),
            int(f.get("id", 0) or 0),
        ))
        records = group_fills_into_positions(combined)
        emitted[sym] = {(r["direction"], int(r["entry_time_ms"] or 0)) for r in records}
    return emitted


def _classify_conflict(
    orphan: Dict[str, Any],
    existing_fills: List[Dict[str, Any]],
) -> str:
    """Categorize a recoverable-but-no-rebuilt-record orphan.

    Returns one of ``real_open_conflict`` / ``lifecycle_absorbed``.
    """
    sym = orphan["symbol"]
    dirn = orphan["direction"]
    entry_t = int(orphan["entry_time_ms"] or 0)
    for f in existing_fills:
        if f.get("symbol") != sym or f.get("direction") != dirn:
            continue
        if int(f.get("is_close", 0)):
            continue
        # Synth fills count as "synth", not as real OPENs.
        if f.get("source") == SYNTH_SOURCE:
            continue
        ts = int(f.get("timestamp_ms", 0) or 0)
        if abs(ts - entry_t) <= 2000:   # FILL_DEDUP_TOLERANCE_MS
            return "real_open_conflict"
    return "lifecycle_absorbed"


# ── Output helpers ─────────────────────────────────────────────────────


def _iso(ms: int) -> str:
    if not ms:
        return "--"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _print_plan(
    synth_opens: List[Dict[str, Any]],
    recoverable: List[Dict[str, Any]],
    preserved: List[Dict[str, Any]],
    orphans_total: int,
    duplicate_keys: Optional[List[Tuple[Tuple[int, str, str, int], int]]] = None,
    conflicts: Optional[List[Dict[str, Any]]] = None,
) -> None:
    syms_recover: Dict[str, int] = defaultdict(int)
    for r in recoverable:
        syms_recover[r["symbol"]] += 1
    syms_preserve: Dict[str, int] = defaultdict(int)
    for p in preserved:
        syms_preserve[p["symbol"]] += 1

    all_syms = sorted(set(syms_recover.keys()) | set(syms_preserve.keys()))

    if duplicate_keys:
        print()
        print("=" * 70)
        print("DUPLICATE-KEY ORPHANS — multiple rows sharing (symbol, dir, entry_time)")
        print("=" * 70)
        print(
            "  These collapse into a single rebuilt row on --apply (the helper "
            "emits one PositionRecord per logical open_time). ALL matching "
            "orphan rows for each duplicate key are deleted."
        )
        for (acct, sym, dirn, entry_t), count in duplicate_keys:
            print(f"  acct={acct} {sym} {dirn} entry_t={entry_t} dupes={count}")

    if conflicts:
        print()
        print("=" * 70)
        print("RECLASSIFIED CONFLICTS — orphans with RPNL match but no rebuilt record")
        print("=" * 70)
        print(
            "  Detected via helper simulation. These orphans match upstream "
            "RPNL by (symbol, direction, open_time) but the helper would NOT "
            "emit a PositionRecord at apply time. Preserved-not-recoverable; "
            "no synth queued."
        )
        for c in conflicts:
            print(
                f"  {c['symbol']:<12} {c['direction']:<5} "
                f"entry_t={c['entry_time_ms']}  "
                f"reason={c.get('_conflict_reason', 'unknown')}"
            )

    print()
    print("=" * 70)
    print("PLAN — per orphan symbol")
    print("=" * 70)
    print(f"  {'symbol':<12} {'orphans':>7} {'recover':>7} {'preserve':>8}")
    for s in all_syms:
        total = syms_recover[s] + syms_preserve[s]
        print(
            f"  {s:<12} {total:>7} {syms_recover[s]:>7} {syms_preserve[s]:>8}"
            + ("" if syms_preserve[s] == 0 else "  (partial / no upstream)")
        )

    print()
    print("=" * 70)
    print("SYNTH OPEN FILLS — first 5 by symbol-time")
    print("=" * 70)
    print(
        f"  {'symbol':<12} {'dir':<5} {'qty':>10} {'entry':>10} "
        f"{'open_ts_iso':<20} {'exchange_fill_id':<40}"
    )
    for f in synth_opens[:5]:
        print(
            f"  {f['symbol']:<12} {f['direction']:<5} "
            f"{f['quantity']:>10.4f} {f['price']:>10.6f} "
            f"{_iso(f['timestamp_ms']):<20} {f['exchange_fill_id']:<40}"
        )
    if len(synth_opens) > 5:
        print(f"  ... and {len(synth_opens) - 5} more")

    n_conflicts = len(conflicts) if conflicts else 0
    n_no_upstream = len(preserved) - n_conflicts

    print()
    print("=" * 70)
    print("TOTALS")
    print("=" * 70)
    print(f"  Orphan rows in scope:                  {orphans_total}")
    print(f"  Recoverable (will be rebuilt):         {len(recoverable)}")
    print(f"  Preserved — no upstream RPNL:          {n_no_upstream}")
    print(f"  Preserved — fill-stream conflict:      {n_conflicts}")
    print(f"  Synth OPEN fills to insert:            {len(synth_opens)}")
    print(
        f"  Symbols with full recovery:            "
        f"{len([s for s in all_syms if syms_preserve[s] == 0])}"
    )
    print(
        f"  Symbols with partial recovery:         "
        f"{len([s for s in all_syms if syms_recover[s] and syms_preserve[s]])}"
    )
    print(
        f"  Symbols fully unrecoverable:           "
        f"{len([s for s in all_syms if syms_recover[s] == 0])}"
    )


# ── Apply ─────────────────────────────────────────────────────────────


async def _apply_synth_and_rebuild(
    db: Any,
    synth_opens: List[Dict[str, Any]],
    account_id: Optional[int],
    verbose: bool,
) -> Dict[str, int]:
    """Insert synth OPEN fills, then per-symbol re-derive closed_positions.

    All operations wrapped in a single transaction. On failure
    (KeyboardInterrupt or Exception), rolls back to pre-script state.
    """
    if not synth_opens:
        return {
            "fills_synthed":    0,
            "positions_rebuilt": 0,
            "orphans_deleted":   0,
            "orphans_preserved": 0,
        }

    fills_synthed = 0
    positions_rebuilt = 0
    orphans_deleted = 0

    try:
        # 1. UPSERT synth OPEN fills.
        for f in synth_opens:
            await db.upsert_fill(f)
            fills_synthed += 1

        # 2. Per affected symbol: re-derive closed_positions via canonical
        # helper. For each output record, find matching bf: orphan and
        # replace it.
        affected_symbols = sorted({f["symbol"] for f in synth_opens})
        fills_by_symbol = await _read_fills_for_symbols(
            db, account_id, affected_symbols,
        )

        # T198: per-symbol attribution map collected across all rebuilt
        # records that actually replaced an orphan. After the loop, the
        # contributing fills get their terminal_position_id back-linked.
        per_record_attribution: Dict[str, List[int]] = {}

        for sym in affected_symbols:
            fills = fills_by_symbol.get(sym, [])
            sym_attribution: Dict[str, List[int]] = {}
            records = group_fills_into_positions(
                fills, attribution_out=sym_attribution,
            )
            for rec in records:
                # Find ALL matching bf: orphans by (account_id, symbol,
                # direction, entry_time_ms). Duplicate-key orphans
                # (multiple rows sharing the same entry_time_ms,
                # differing only by exit_time_ms — earlier double-write
                # backfill artifact) all collapse into the one rebuilt
                # row.
                async with db._conn.execute(
                    "SELECT id "
                    "FROM closed_positions "
                    "WHERE account_id = ? AND symbol = ? AND direction = ? "
                    "AND entry_time_ms = ? "
                    "AND terminal_position_id LIKE ? "
                    "AND source = ?",
                    (
                        rec["account_id"], rec["symbol"], rec["direction"],
                        rec["entry_time_ms"],
                        f"{ORPHAN_TPID_PREFIX}%", ORPHAN_SOURCE,
                    ),
                ) as cur:
                    rows = await cur.fetchall()
                if not rows:
                    # No matching bf: orphan — this position was either
                    # already rebuilt or didn't originate from the orphan
                    # set. Skip to avoid creating duplicate rebuilt rows.
                    continue
                # DELETE all matching orphan rows.
                for row in rows:
                    await db._conn.execute(
                        "DELETE FROM closed_positions WHERE id = ?",
                        (row["id"],),
                    )
                    orphans_deleted += 1
                # INSERT the rebuilt row (helper's source='rebuilt_from_fills',
                # backfill_completed=0). commit=False — outer try owns commit.
                await db.insert_closed_position(rec, commit=False)
                positions_rebuilt += 1
                # Record this record's fill attribution for the
                # post-loop tpid-backfill UPDATE pass.
                tpid = rec["terminal_position_id"]
                per_record_attribution[tpid] = sym_attribution.get(tpid, [])

        # T198: back-link fills' terminal_position_id to the rebuilt
        # rows inside the same transaction so closed_positions + fills
        # tpid linkage land atomically. Without this, the Position
        # History fills drawer renders empty for rebuilt rows because
        # get_position_fills (api/routes_orders.py:204) does a strict
        # tpid match and the fills have empty tpid.
        fills_tpid_updated = 0
        for tpid, fill_ids in per_record_attribution.items():
            if not fill_ids:
                continue
            placeholders = ",".join("?" * len(fill_ids))
            cur = await db._conn.execute(
                f"UPDATE fills SET terminal_position_id = ? "
                f"WHERE id IN ({placeholders}) "
                f"AND COALESCE(terminal_position_id, '') = ''",
                (tpid, *fill_ids),
            )
            fills_tpid_updated += cur.rowcount

        await db._conn.commit()
    except BaseException:
        try:
            await db._conn.rollback()
        except Exception:
            pass
        raise

    if verbose:
        print()
        print(f"Inserted {fills_synthed} synth OPEN fill(s).")
        print(
            f"Replaced {orphans_deleted} orphan row(s) with "
            f"{positions_rebuilt} rebuilt row(s)."
        )
        print(
            f"Back-linked {fills_tpid_updated} fill(s) to rebuilt tpids."
        )
        print(
            "Reconciler will pick up the new rebuilt rows (backfill_completed=0) "
            "and re-run MFE/MAE with T175's gross-PnL floor on next sweep."
        )

    return {
        "fills_synthed":       fills_synthed,
        "positions_rebuilt":   positions_rebuilt,
        "orphans_deleted":     orphans_deleted,
        "fills_tpid_updated":  fills_tpid_updated,
    }


# ── Programmable entrypoint ───────────────────────────────────────────


async def run_synth(
    db_path: str = DEFAULT_DB_PATH,
    *,
    apply: bool = False,
    account_id: Optional[int] = None,
    symbol: Optional[str] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Programmable entrypoint (used by main + tests).

    Returns a summary dict with ``orphans_in_scope``, ``recoverable``,
    ``preserved``, ``synth_opens_planned`` plus, when ``apply=True``,
    ``fills_synthed``, ``positions_rebuilt``, ``orphans_deleted``.
    """
    from core.database import DatabaseManager
    db = DatabaseManager(path=db_path)
    await db.initialize()

    try:
        orphans = await _read_orphan_signatures(db, account_id, symbol)
        if verbose:
            print(f"Read {len(orphans)} orphan closed_positions from {db_path}")
            if account_id is not None:
                print(f"  Filter: account_id={account_id}")
            if symbol:
                print(f"  Filter: symbol={symbol}")

        if not orphans:
            if verbose:
                print("Nothing to do — no orphan rows in scope.")
            return {
                "orphans_in_scope":     0,
                "recoverable":          0,
                "preserved":            0,
                "synth_opens_planned":  0,
                "applied":              False,
            }

        rpnl_rows = await _read_rpnl_rows(db, account_id, symbol)
        if verbose:
            print(f"Read {len(rpnl_rows)} usable RPNL row(s) from exchange_history")

        synth_opens, recoverable, preserved_no_upstream, duplicate_keys = (
            _build_synth_opens(rpnl_rows, orphans)
        )

        # T199 (audit fix for F1+F2): SIMULATE the helper with planned
        # synths to detect orphans that would NOT produce a rebuilt
        # record at apply time (real-OPEN conflict + lifecycle-
        # absorption shapes). Reclassify those as preserved-with-reason
        # and drop their synth from the plan — makes the script truly
        # idempotent (re-running won't re-insert garbage that the
        # helper would reject again).
        affected_symbols = sorted({s["symbol"] for s in synth_opens})
        existing_fills_by_symbol = await _read_fills_for_symbols(
            db, account_id, affected_symbols,
        )
        emitted_keys = _simulate_helper_emitted_keys(
            existing_fills_by_symbol, synth_opens,
        )
        validated_recoverable: List[Dict[str, Any]] = []
        conflicts: List[Dict[str, Any]] = []
        for o in recoverable:
            sym = o["symbol"]
            key = (o["direction"], int(o["entry_time_ms"] or 0))
            if key in emitted_keys.get(sym, set()):
                validated_recoverable.append(o)
            else:
                reason = _classify_conflict(
                    o, existing_fills_by_symbol.get(sym, []),
                )
                o_copy = dict(o)
                o_copy["_conflict_reason"] = reason
                conflicts.append(o_copy)

        # Filter the synth_opens list to only those backing validated
        # recoverable orphans.
        validated_keys = {
            (
                int(o["account_id"]), str(o["symbol"]),
                str(o["direction"]), int(o["entry_time_ms"] or 0),
            )
            for o in validated_recoverable
        }
        validated_synth_opens = [
            s for s in synth_opens
            if (
                int(s["account_id"]), str(s["symbol"]),
                str(s["direction"]), int(s["timestamp_ms"] or 0),
            ) in validated_keys
        ]
        preserved = list(preserved_no_upstream) + conflicts

        if verbose:
            _print_plan(
                validated_synth_opens, validated_recoverable, preserved,
                len(orphans), duplicate_keys=duplicate_keys,
                conflicts=conflicts,
            )

        result = {
            "orphans_in_scope":    len(orphans),
            "recoverable":         len(validated_recoverable),
            "preserved":           len(preserved),
            "preserved_no_upstream": len(preserved_no_upstream),
            "preserved_conflict":  len(conflicts),
            "synth_opens_planned": len(validated_synth_opens),
            "applied":             False,
        }

        if not apply:
            if verbose:
                print()
                print("[DRY-RUN] No changes made.")
                print(
                    "Re-run with --apply after backing up the DB to "
                    "INSERT synth OPEN fills and replace recoverable orphan "
                    "rows with rebuilt_from_fills rows."
                )
            return result

        if verbose:
            print()
            print("Applying synth + per-symbol rebuild (atomic — single transaction)...")

        apply_result = await _apply_synth_and_rebuild(
            db, validated_synth_opens, account_id, verbose,
        )
        result.update(apply_result)
        result["orphans_preserved"] = len(preserved)
        result["applied"] = True
        return result
    finally:
        await db.close()


# ── CLI ───────────────────────────────────────────────────────────────


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="INSERT synth OPEN fills + replace recoverable orphan rows "
             "with rebuilt_from_fills rows (default: dry-run, no writes).",
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
        print("WARNING: --apply WILL INSERT fills + DELETE/INSERT closed_positions in")
        print(f"  {args.db}")
        print()
        print("  This is destructive (on the recoverable-orphan subset).")
        print("  Back up the DB first if you haven't already.")
        print("=" * 70)

    result = asyncio.run(run_synth(
        db_path=args.db,
        apply=args.apply,
        account_id=args.account_id,
        symbol=args.symbol,
    ))
    return 0 if result is not None else 1


if __name__ == "__main__":
    sys.exit(main())
