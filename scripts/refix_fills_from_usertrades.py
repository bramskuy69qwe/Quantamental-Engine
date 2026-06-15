"""
Operator-controlled re-fix of OFFLINE-recovered fills from Binance ``userTrades``.

WHY THIS EXISTS
---------------
When the engine is OFFLINE during trading, the observe-only design sees no
live fills, so the fallback recovery rebuilt ``fills`` from the Binance
REALIZED_PNL *income* feed (``fetch_exchange_trade_history`` ->
``backfill_fills_from_exchange_history``). That feed contains only the
CLOSE side of each trade, so the recovery:

  (a) re-summed each position's opening commission onto EVERY partial close
      that shared one open_time  ->  fees inflated 8-70x; and
  (b) synthesized ONE undersized opening fill (sized at the first tiny
      close)  ->  the grouper over-closed immediately and shattered
      hundreds of fills into a few garbled ``closed_positions``.

This script rebuilds those fills from ``userTrades`` -- the real per-fill
record: genuine opens AND closes, each with its OWN commission and a
hedge-aware ``is_close`` -- so the downstream rebuild yields correct
positions + fees.

WORKFLOW (every step is DRY-RUN by default)
-------------------------------------------
  1. Back up the DB.
  2. python scripts/refix_fills_from_usertrades.py --symbol SPCXUSDT
        DRY-RUN: fetches userTrades (read-only API), prints the TRUE fills,
        the would-be positions, and the current (bad) state. No DB writes.
  3. python scripts/refix_fills_from_usertrades.py --symbol SPCXUSDT --apply
        DELETEs the synthetic ``source='exchange_history_backfill'`` fills
        for the symbol(s) and INSERTs the userTrades fills. Does NOT touch
        ``closed_positions``.
  4. python scripts/rebuild_closed_positions.py --symbol SPCXUSDT --apply
        Rebuilds ``closed_positions`` from the now-correct fills (existing,
        trusted script -- also dry-run by default).

USAGE
-----
  --symbol SYMS       restrict to symbol(s); comma-separated. Default: all
                      symbols that currently have exchange_history_backfill
                      fills.
  --account-id N      restrict to one account (default: the active account).
  --days N            narrow the userTrades look-back to N days; default 0 =
                      full symbol history (recommended -- captures every open
                      so no position is dropped as an orphan close). The
                      DELETE of old backfill rows is scoped to the same window.
  --since / --until   explicit ISO bounds (UTC), override --days.
  --apply             commit (default: dry-run only).

IMPORTANT
---------
  - NOT auto-run on startup. Operator-controlled only. BACKUP before --apply.
  - Operates on the live DB (config.DB_PATH). DRY-RUN is your rehearsal --
    it reads + previews without writing.
  - Makes a READ-ONLY Binance userTrades call (no orders placed/changed).
  - Only deletes synthetic ``exchange_history_backfill`` fills; real
    WS/REST fills are preserved. For a symbol traded BOTH online and
    offline, run ``scripts/dedup_fills.py`` after rebuilding.

BACKGROUND: 2026-06-14/15 live debug session; see the
``project_spcx_offline_backfill_bug`` memory + the income-reconstruction
bug sites core/exchange_income.py:389 and core/db_orders.py:1543.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.db_orders import SYNTHETIC_FILL_SOURCES  # noqa: E402

# Prior synthetic-recovery fill sources userTrades supersedes (income backfill
# + legacy synth-open). DELETE these + never collision-preserve them, else
# doubled opens break the rebuild (2026-06-15 regression fix).
_SYNTH_IN = "(" + ",".join("?" * len(SYNTHETIC_FILL_SOURCES)) + ")"


def _fmt_ms(v: Any) -> str:
    try:
        return datetime.fromtimestamp(int(v) / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(v)


def preview_from_trades(trades: List[Any], account_id: int) -> Dict[str, Any]:
    """Pure: NormalizedTrade list -> fill dicts + grouped positions + summary.

    No DB / no network -- testable in isolation. This is EXACTLY what
    ``--apply`` writes (fills) and what the subsequent rebuild produces
    (positions), so the dry-run preview is faithful.
    """
    from core.exchange_income import user_trade_to_fill_dict
    from core.position_grouping import group_fills_into_positions

    fills = [
        user_trade_to_fill_dict(t, account_id)
        for t in trades
        if float(getattr(t, "quantity", 0) or 0) > 0
    ]
    fills.sort(key=lambda f: int(f.get("timestamp_ms", 0) or 0))
    positions = [dict(p) for p in group_fills_into_positions(fills)]

    opens = [f for f in fills if not f.get("is_close")]
    closes = [f for f in fills if f.get("is_close")]
    summary = {
        "n_fills": len(fills),
        "n_opens": len(opens),
        "n_closes": len(closes),
        "commission": round(sum(float(f.get("fee", 0) or 0) for f in fills), 6),
        "gross_realized": round(sum(float(f.get("realized_pnl", 0) or 0) for f in fills), 6),
        "n_positions": len(positions),
        "ts_first": min((int(f["timestamp_ms"]) for f in fills), default=0),
        "ts_last": max((int(f["timestamp_ms"]) for f in fills), default=0),
    }
    summary["net_after_commission"] = round(summary["gross_realized"] - summary["commission"], 6)
    # Orphan-clip guard: per direction, if close qty exceeds open qty then
    # opening fills predate the window (clipped) and group_fills_into_positions
    # silently drops the orphan closes -- the operator must widen --since/--days.
    oq: Dict[str, float] = {}
    cq: Dict[str, float] = {}
    for f in fills:
        d = f.get("direction", "")
        acc = cq if f.get("is_close") else oq
        acc[d] = acc.get(d, 0.0) + float(f.get("quantity", 0) or 0)
    summary["clipped_open_qty"] = {
        d: round(cq.get(d, 0.0) - oq.get(d, 0.0), 6)
        for d in set(list(oq) + list(cq))
        if cq.get(d, 0.0) - oq.get(d, 0.0) > 1e-6
    }
    return {"fills": fills, "positions": positions, "summary": summary}


async def _count(db, sql: str, params: tuple) -> int:
    cur = await db._conn.execute(sql, params)
    try:
        row = await cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        await cur.close()


async def _current_state(db, account_id: int, symbol: str) -> Dict[str, int]:
    return {
        "backfill_fills": await _count(
            db, f"SELECT count(*) FROM fills WHERE account_id=? AND symbol=? AND source IN {_SYNTH_IN}",
            (account_id, symbol, *SYNTHETIC_FILL_SOURCES)),
        "other_fills": await _count(
            db, f"SELECT count(*) FROM fills WHERE account_id=? AND symbol=? AND source NOT IN {_SYNTH_IN}",
            (account_id, symbol, *SYNTHETIC_FILL_SOURCES)),
        "closed_positions": await _count(
            db, "SELECT count(*) FROM closed_positions WHERE account_id=? AND symbol=?",
            (account_id, symbol)),
    }


async def _resolve_symbols(db, account_id: int) -> List[str]:
    cur = await db._conn.execute(
        f"SELECT DISTINCT symbol FROM fills WHERE account_id=? AND source IN {_SYNTH_IN} ORDER BY symbol",
        (account_id, *SYNTHETIC_FILL_SOURCES),
    )
    try:
        return [r[0] for r in await cur.fetchall()]
    finally:
        await cur.close()


def _print_positions(positions: List[Dict[str, Any]]) -> None:
    if not positions:
        print("    (no closed positions reconstructed)")
        return
    print(f"    {'dir':<6} {'qty':>10} {'entry':>11} {'exit':>11} "
          f"{'realized':>11} {'fees':>9} {'net':>11}  open -> close")
    for p in positions:
        print(
            f"    {str(p.get('direction','?')):<6} "
            f"{float(p.get('quantity',0) or 0):>10.4f} "
            f"{float(p.get('entry_price',0) or 0):>11.5f} "
            f"{float(p.get('exit_price',0) or 0):>11.5f} "
            f"{float(p.get('realized_pnl',0) or 0):>11.4f} "
            f"{float(p.get('total_fees',0) or 0):>9.4f} "
            f"{float(p.get('net_pnl',0) or 0):>11.4f}  "
            f"{_fmt_ms(p.get('entry_time_ms'))} -> {_fmt_ms(p.get('exit_time_ms'))}"
        )


async def run_refix(
    *,
    db,
    account_id: int,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    fetch_fn,
    symbols: Optional[List[str]] = None,
    apply: bool = False,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Core entrypoint (CLI + tests). Caller owns the ``db`` lifecycle.

    ``fetch_fn(symbol, start_ms, end_ms) -> List[NormalizedTrade]`` is
    ``exchange_income.fetch_all_user_trades`` in production; tests inject a
    stub returning synthetic trades.
    """
    syms = symbols if symbols is not None else await _resolve_symbols(db, account_id)
    if verbose:
        win_lo = _fmt_ms(start_ms) if start_ms else "(all history)"
        win_hi = _fmt_ms(end_ms) if end_ms else "now"
        print(f"account_id={account_id}  window={win_lo} .. {win_hi}")
        print(f"symbols: {', '.join(syms) if syms else '(none -- nothing to re-fix)'}")
        print("=" * 78)

    result: Dict[str, Any] = {"applied": apply, "account_id": account_id, "per_symbol": {}}

    for sym in syms:
        trades = await fetch_fn(sym, start_ms, end_ms)
        prev = preview_from_trades(trades, account_id)
        s = prev["summary"]
        cur = await _current_state(db, account_id, sym)

        if verbose:
            print(f"\n### {sym}")
            print(f"  userTrades fetched: {s['n_fills']} "
                  f"(opens={s['n_opens']}, closes={s['n_closes']})  "
                  f"span {_fmt_ms(s['ts_first'])} .. {_fmt_ms(s['ts_last'])}")
            print(f"  TRUE totals: gross_realized={s['gross_realized']}  "
                  f"commission={s['commission']}  net={s['net_after_commission']}")
            print(f"  would-be closed_positions: {s['n_positions']}")
            _print_positions(prev["positions"])
            print(f"  CURRENT (to be replaced): {cur['backfill_fills']} backfill fills, "
                  f"{cur['closed_positions']} closed_positions"
                  + (f"  [+{cur['other_fills']} real WS/REST fills PRESERVED]"
                     if cur["other_fills"] else ""))
            if s.get("clipped_open_qty"):
                print(f"  WARNING: close qty exceeds open qty for {s['clipped_open_qty']} "
                      f"- opening fills predate the window; widen --since/--days "
                      f"(else those positions are dropped as orphan closes).")

        sym_res = {
            "fetched": s["n_fills"], "positions": s["n_positions"],
            "gross_realized": s["gross_realized"], "commission": s["commission"],
            "net": s["net_after_commission"], "current": cur,
            "deleted": 0, "inserted": 0, "preserved": 0,
        }

        if apply:
            # Preserve real WS/REST fills: a userTrades fill that shares a
            # tradeId (exchange_fill_id) with an existing NON-backfill row is
            # already authoritative -- SKIP it (don't overwrite via upsert)
            # and count it. Also makes re-runs idempotent: a prior run's
            # exchange_usertrades rows are non-backfill -> skipped. (HIGH-2)
            ecur = await db._conn.execute(
                f"SELECT exchange_fill_id FROM fills WHERE account_id=? AND symbol=? "
                f"AND source NOT IN {_SYNTH_IN}",
                (account_id, sym, *SYNTHETIC_FILL_SOURCES),
            )
            existing_real = {r[0] for r in await ecur.fetchall()}
            await ecur.close()
            # Order: INSERT before DELETE so a mid-run crash leaves a
            # recoverable over-complete state (old + new), never a data-loss
            # gap (old deleted, new missing). (MED-1)
            inserted = 0
            preserved = 0
            for fd in prev["fills"]:
                if fd["exchange_fill_id"] in existing_real:
                    preserved += 1
                    continue
                await db.upsert_fill(fd)
                inserted += 1
            # Scope the DELETE to the SAME window as the fetch so we never
            # delete a backfill row we won't re-insert (data-loss guard). With
            # the default full-history window both bounds are None -> all
            # backfill rows for the symbol are replaced.
            del_sql = f"DELETE FROM fills WHERE account_id=? AND symbol=? AND source IN {_SYNTH_IN}"
            del_params: List[Any] = [account_id, sym, *SYNTHETIC_FILL_SOURCES]
            if start_ms is not None:
                del_sql += " AND timestamp_ms >= ?"
                del_params.append(start_ms)
            if end_ms is not None:
                del_sql += " AND timestamp_ms <= ?"
                del_params.append(end_ms)
            delcur = await db._conn.execute(del_sql, tuple(del_params))
            deleted = delcur.rowcount
            await delcur.close()
            await db._conn.commit()
            sym_res["deleted"] = deleted
            sym_res["inserted"] = inserted
            sym_res["preserved"] = preserved
            if verbose:
                msg = (f"  APPLIED: inserted {inserted} userTrades fills, "
                       f"deleted {deleted} backfill fills")
                if preserved:
                    msg += (f", preserved {preserved} existing real/prior fills "
                            f"(tradeId collision -> not overwritten)")
                print(msg + ".")

        result["per_symbol"][sym] = sym_res

    if verbose:
        print("\n" + "=" * 78)
        if apply:
            print("APPLIED fills. NEXT: rebuild closed_positions from the corrected fills:")
            tgt = f" --symbol {syms[0]}" if len(syms) == 1 else ""
            print(f"  python scripts/rebuild_closed_positions.py{tgt} --apply")
        else:
            print("[DRY-RUN] No changes made. Re-run with --apply (after a DB backup) to commit.")
            print("Then: python scripts/rebuild_closed_positions.py --apply  (also dry-run by default)")

    return result


def _parse_iso(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


async def _main_async(args) -> int:
    from core.database import db
    from core.account_registry import account_registry
    from core.exchange_income import fetch_all_user_trades

    await db.initialize()
    try:
        await account_registry.load_all()
        aid = args.account_id if args.account_id is not None else account_registry.active_id

        # The standalone script does NOT run the engine's startup clock-sync,
        # so enable ccxt's own time-difference adjustment to avoid Binance
        # -1021 ("timestamp ahead of server") if the local clock has drifted.
        try:
            from core.exchange import _get_adapter
            _ex = _get_adapter().get_ccxt_instance()
            _ex.options["adjustForTimeDifference"] = True
            await asyncio.to_thread(_ex.load_time_difference)
        except Exception as e:
            print(f"  (clock-sync warning: {e!r})")

        start_ms = _parse_iso(args.since)
        if start_ms is None and args.days and args.days > 0:
            start_ms = int((time.time() - args.days * 86400) * 1000)
        # else: start_ms stays None = full symbol history (default)
        end_ms = _parse_iso(args.until)
        symbols = [s.strip().upper() for s in args.symbol.split(",")] if args.symbol else None

        await run_refix(
            db=db, account_id=aid, start_ms=start_ms, end_ms=end_ms,
            fetch_fn=fetch_all_user_trades, symbols=symbols, apply=args.apply,
        )
    finally:
        await db.close()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--symbol", default=None,
                        help="comma-separated symbol(s); default: all backfill symbols")
    parser.add_argument("--account-id", type=int, default=None)
    parser.add_argument("--days", type=int, default=0,
                        help="narrow userTrades look-back to N days; 0 (default) = full history")
    parser.add_argument("--since", default=None, help="ISO UTC lower bound (overrides --days)")
    parser.add_argument("--until", default=None, help="ISO UTC upper bound")
    parser.add_argument("--apply", action="store_true", help="commit (default: dry-run)")
    args = parser.parse_args(argv)

    if args.apply:
        print("=" * 70)
        print("WARNING: --apply WILL DELETE + REWRITE fill rows in the live DB.")
        print("  This is destructive. Back up the DB first.")
        print("  Press Ctrl+C within 3 seconds to abort.")
        print("=" * 70)
        for s in (3, 2, 1):
            print(f"  proceeding in {s}...", end="\r")
            time.sleep(1)
        print("  proceeding now.            \n")

    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    sys.exit(main())
