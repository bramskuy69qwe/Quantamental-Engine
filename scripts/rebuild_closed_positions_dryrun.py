"""
T177 dry-run: rebuild closed_positions from fills using the corrected
chronological-walk grouping. WRITE-FREE — only reads the live DB and
prints a diff against the current (corrupted) closed_positions rows.

Usage:
    python scripts/rebuild_closed_positions_dryrun.py [symbol]

If [symbol] is given, only that symbol is shown. Otherwise all symbols.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from typing import Optional

# Make project root importable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.position_grouping import group_fills_into_positions  # noqa: E402

DB_PATH = os.path.join(ROOT, "data", "risk_engine.db")


def main(filter_symbol: Optional[str] = None) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Pull all fills, chronologically. Dedupe by exchange_fill_id (WS+REST
    # duplicates were observed in the DB).
    fills_q = """
        SELECT * FROM fills
        WHERE COALESCE(exchange_fill_id, '') != ''
        ORDER BY timestamp_ms ASC, id ASC
    """
    if filter_symbol:
        fills_q = fills_q.replace("WHERE", f"WHERE symbol='{filter_symbol}' AND")

    seen_fill_ids = set()
    deduped_fills = []
    raw_count = 0
    for row in conn.execute(fills_q).fetchall():
        raw_count += 1
        fid = row["exchange_fill_id"]
        if fid in seen_fill_ids:
            continue
        seen_fill_ids.add(fid)
        deduped_fills.append(dict(row))

    print(f"Read {raw_count} fills, deduped to {len(deduped_fills)}")

    # Group into positions
    rebuilt = group_fills_into_positions(deduped_fills)
    print(f"Rebuilt {len(rebuilt)} closed positions")

    # Read existing closed_positions for comparison
    existing_q = """
        SELECT * FROM closed_positions
        WHERE source != 'rebuilt_from_fills'
    """
    if filter_symbol:
        existing_q += f" AND symbol='{filter_symbol}'"
    existing_q += " ORDER BY exit_time_ms ASC, id ASC"
    existing = [dict(r) for r in conn.execute(existing_q).fetchall()]

    print(f"Existing (non-rebuilt) closed_positions: {len(existing)}")

    # Per-symbol summary diff
    from collections import defaultdict
    rebuilt_by_sym = defaultdict(list)
    for r in rebuilt:
        rebuilt_by_sym[r["symbol"]].append(r)
    existing_by_sym = defaultdict(list)
    for r in existing:
        existing_by_sym[r["symbol"]].append(r)

    print()
    print("=== Per-symbol counts ===")
    print(f"{'symbol':<15} {'rebuilt':>8} {'existing':>9} {'diff':>5}")
    for sym in sorted(set(rebuilt_by_sym.keys()) | set(existing_by_sym.keys())):
        rb = len(rebuilt_by_sym[sym])
        ex = len(existing_by_sym[sym])
        diff = rb - ex
        marker = "" if diff == 0 else " <—"
        print(f"{sym:<15} {rb:>8} {ex:>9} {diff:>+5}{marker}")

    # Detail for one symbol (filtered or BSBUSDT default)
    detail_sym = filter_symbol or "BSBUSDT"
    print()
    print(f"=== Detail for {detail_sym} ===")
    print(f"{'side':>5} {'qty':>8} {'entry':>10} {'exit':>10} {'pnl':>7} "
          f"{'entry_iso':<22} {'exit_iso':<22} source")
    from datetime import datetime, timezone

    def _iso(ms):
        if not ms:
            return "—"
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    print("--- REBUILT ---")
    for r in rebuilt_by_sym[detail_sym]:
        print(f"{r['direction']:>5} {r['quantity']:>8.2f} {r['entry_price']:>10.4f} "
              f"{r['exit_price']:>10.4f} {r['net_pnl']:>7.2f} "
              f"{_iso(r['entry_time_ms']):<22} {_iso(r['exit_time_ms']):<22} {r['source']}")

    print("--- EXISTING ---")
    for r in existing_by_sym[detail_sym]:
        print(f"{r['direction']:>5} {r['quantity']:>8.2f} {r['entry_price']:>10.4f} "
              f"{r['exit_price']:>10.4f} {r['net_pnl']:>7.2f} "
              f"{_iso(r['entry_time_ms']):<22} {_iso(r['exit_time_ms']):<22} {r['source']}")

    conn.close()


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else None
    main(sym)
