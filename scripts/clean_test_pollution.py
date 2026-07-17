"""
Operator-controlled cleanup of TEST-pollution rows in the live
per-account ``trade_events`` + ``engine_events`` logs +
``position_fill_snapshots``.

Years of un-isolated tests (fixed forward 2026-06-04 by
``tests/conftest.py::_isolate_live_per_account_logs``) wrote synthetic
fixture rows into the LIVE per-account DB because the fill/close/calc
paths call ``log_trade_event`` / ``log_event`` without a ``data_dir``,
so the resolver picked ``config.DATA_DIR`` -> the live DB for account 1.
This script removes those OLD rows. NEW pollution is already blocked.

  See: project memory ``project_live_db_test_pollution`` +
       HANDOFF "Live-DB test pollution".

────────────────────────────────────────────────────────────────────────
WHAT IS DELETED vs KEPT  (conservative: delete ONLY on a positive test
signature; anything ambiguous is KEPT and surfaced as UNKNOWN)
────────────────────────────────────────────────────────────────────────
REAL calc_ids are ``uuid.uuid4().hex`` -> 32-char lowercase hex
(core/risk_engine.py:230). ``pre_trade_log`` (the real calc registry in
the CLEAN risk_engine.db) holds ZERO non-hex non-null calc_ids, so a
non-null calc_id that is NOT 32-hex is definitively a test fixture.

trade_events:
  KEEP (REAL):
    - calc_id matches ^[0-9a-f]{32}$            (real operator calc_created)
    - calc_id IS NULL and exchange_order_id is  (real venue order:
      purely numeric OR ``algo:<digits>``)       order_placed/canceled)
  DELETE (TEST):
    - calc_id is non-null and NOT 32-hex        (named fixtures: calc-a,
                                                  C1, lc-1.., cr-1, ...)
    - calc_id IS NULL and exchange_order_id      (synthetic ids: O-C,
      starts with O-/ord-/OID-/binance-order-/POS-)  O-CLOSE, ord-1, ...)
    - calc_id IS NULL and event_type in
      (position_closed, partial_close) and       (test closes w/ fixture
      exchange_order_id is empty                  prices 100/110, 50000..)
  SAFETY NET: a row that matched a TEST signature but whose payload
    ``symbol`` is a genuinely-traded real symbol (anything other than
    ''/BTCUSDT/ETHUSDT, the only symbols present in test rows) is
    DOWNGRADED to UNKNOWN (kept + flagged). Real trades never emitted
    trade_events anyway (they were backfilled), but this makes accidental
    real-symbol deletion impossible by construction.

position_fill_snapshots (added v2.7 Task E — the leak the F5 session
tripwire surfaced; ``OrderManager._snapshot_and_fix_isclose`` persisted
fixture fills to the LIVE per-account DB via the un-guarded third
``_resolve_db_path``):
  KEEP (REAL):
    - fill_id purely numeric                     (real Binance tradeId,
                                                  8-10 digits observed)
  DELETE (TEST):
    - fill_id starts with ``tid-`` or            (reversal-split fixture;
      ``binance-trade-``                          both grep-verified
                                                  test-only — core/ never
                                                  emits them) OR any of the
                                                  trade_events synthetic
                                                  prefixes (O-/ord-/OID-/
                                                  binance-order-/POS-)
  NOT a delete signature: ``synth:<id>:open`` — PRODUCTION emits this for
    real reversal open-legs (position_snapshot.py:196), so it is KEPT
    (UNKNOWN); there are zero such snapshot rows today.
  SAFETY NET: a test-prefixed row whose symbol is a genuinely-traded real
    symbol (not ''/BTCUSDT/ETHUSDT) is DOWNGRADED to UNKNOWN — real
    per-symbol snapshots (SPCXUSDT/VELVET/… numeric ids) can never be
    deleted by construction.

engine_events:
  DELETE (TEST):
    - dd_state_transition with peak_equity > 200 (test fixtures use
      10500 / 1000; the REAL account equity is ~$82, verified via the
      account snapshot + equity_delta_warning rows)
    - close_row_build_failed with terminal_position_id ``POS-*`` or
      exchange_order_id ``OID-*``/``O-*``        (synthetic test ids)
  KEEP (REAL):
    - dd_state_transition with peak_equity <= 200 (real ~$82 account DD)
    - equity_delta_warning                        (real engine startup)
    - calc_blocked_contract                       (real operator Calculate
                                                   blocks; emitted by both
                                                   prod + tests -> kept to
                                                   never drop a real one)
    - any other / unknown event_type              (kept + flagged)

────────────────────────────────────────────────────────────────────────
USAGE
────────────────────────────────────────────────────────────────────────
    # Default: DRY-RUN. Prints the full plan. No DB writes.
    python scripts/clean_test_pollution.py

    # Apply: BACK UP THE DB FIRST. Deletes the TEST rows.
    python scripts/clean_test_pollution.py --apply

    # Restrict to one table.
    python scripts/clean_test_pollution.py --table trade_events
    python scripts/clean_test_pollution.py --table engine_events --apply

    # Rehearse against a backup copy first.
    python scripts/clean_test_pollution.py --db /path/to/backup.db --apply

IMPORTANT
    - NOT auto-run on startup. Operator-controlled only.
    - Default ``--db`` is the live binance-futures per-account DB.
    - ALWAYS read the dry-run output before ``--apply`` (CLAUDE.md
      live-DB-dry-run discipline). Inspect the per-bucket counts and the
      UNKNOWN list; a non-empty UNKNOWN list = stop and investigate.
    - Idempotent: a second run with no new pollution deletes 0 rows.
    - DELETE runs in a single transaction per table (rolls back on error).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from typing import Callable, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_DB_PATH = os.path.join(
    ROOT, "data", "per_account", "quantower__binancefutures__binance.db"
)

# Real calc_id format: uuid.uuid4().hex (risk_engine.py:230).
# \Z (not $) so a trailing newline can't sneak a string past the exact-match
# guard (re `$` matches before a final \n; these are exact-format checks).
HEX32 = re.compile(r"^[0-9a-f]{32}\Z")
NUMERIC_OID = re.compile(r"^\d+\Z")
ALGO_OID = re.compile(r"^algo:\d+\Z")
SYNTH_OID_PREFIXES = ("O-", "ord-", "OID-", "binance-order-", "POS-")

# position_fill_snapshots test fill_id prefixes: the two reversal-split
# fixture shapes (grep-verified test-only in core/) PLUS the shared
# synthetic-order prefixes. NB ``synth:`` is DELIBERATELY excluded —
# production emits ``synth:<tradeId>:open`` for real reversal legs
# (position_snapshot.py:196), so it is not a delete signature.
SNAPSHOT_TEST_PREFIXES = ("tid-", "binance-trade-") + SYNTH_OID_PREFIXES

# The real account is a tiny (~$82) Binance-Futures account. Test fixtures
# use peak_equity 1000 / 10500. 200 cleanly separates them with margin.
REAL_EQUITY_MAX = 200.0

# The only payload symbols ever present on test rows (verified). Anything
# else is a genuinely-traded real symbol and must never be deleted.
TEST_OR_EMPTY_SYMBOLS = ("", "BTCUSDT", "ETHUSDT")

# For documentation / cross-check (the exhaustive set of non-hex non-null
# calc_ids found in the live trade_events at authoring time, 2026-06-05).
# The classifier does NOT depend on this list (it uses the general
# "non-null non-hex -> TEST" rule); it exists so the dry-run can assert no
# surprise calc_id slipped through.
KNOWN_TEST_CALC_IDS = frozenset({
    "calc-a", "calc-b", "calc-A", "calc-B", "calc-early", "calc-late",
    "calc-solo", "C1", "C2", "C3", "C4", "CG",
    "lc-1", "lc-2", "lc-3", "lc-4a", "lc-4b", "lc-5", "lc-6", "cr-1",
})

Decision = str  # "TEST" | "REAL" | "UNKNOWN"


def _load_payload(raw: Optional[str]) -> Dict:
    try:
        p = json.loads(raw or "{}")
        return p if isinstance(p, dict) else {}
    except Exception:
        return {}


def classify_trade_event(
    calc_id: Optional[str], event_type: str, payload: Dict
) -> Decision:
    """Classify one trade_events row. Pure function (unit-tested)."""
    oid = str(payload.get("exchange_order_id") or "")
    sym = str(payload.get("symbol") or "")

    # ── REAL signals win first ──
    if calc_id and HEX32.match(calc_id):
        return "REAL"
    if calc_id is None and (NUMERIC_OID.match(oid) or ALGO_OID.match(oid)):
        return "REAL"

    # ── TEST signals ──
    decision: Optional[Decision] = None
    if calc_id is not None and not HEX32.match(calc_id):
        # uuid4().hex is the ONLY real calc_id format; a short/named one is
        # always a fixture.
        decision = "TEST"
    elif calc_id is None and oid.startswith(SYNTH_OID_PREFIXES):
        decision = "TEST"
    elif calc_id is None and event_type in ("position_closed", "partial_close") and oid == "":
        decision = "TEST"

    if decision is None:
        return "UNKNOWN"

    # ── safety net: never delete a row on a genuinely-traded real symbol ──
    if sym not in TEST_OR_EMPTY_SYMBOLS:
        return "UNKNOWN"
    return decision


def classify_engine_event(event_type: str, payload: Dict) -> Decision:
    """Classify one engine_events row. Pure function (unit-tested)."""
    if event_type == "dd_state_transition":
        try:
            pk = float(payload.get("peak_equity") or 0)
        except (TypeError, ValueError):
            return "UNKNOWN"
        return "TEST" if pk > REAL_EQUITY_MAX else "REAL"

    if event_type == "close_row_build_failed":
        tpid = str(payload.get("terminal_position_id") or "")
        oid = str(payload.get("exchange_order_id") or "")
        if tpid.startswith("POS-") or oid.startswith(("OID-", "O-")):
            return "TEST"
        return "UNKNOWN"  # a real close failure -> keep + flag

    # equity_delta_warning, calc_blocked_contract, and any future type:
    # keep (conservative — under-cleaning is safe).
    return "REAL"


def classify_position_fill_snapshot(
    fill_id: Optional[str], symbol: Optional[str]
) -> Decision:
    """Classify one position_fill_snapshots row. Pure function (unit-tested).

    Numeric fill_id = real Binance tradeId (KEEP). A verified test-only
    prefix on a test/empty symbol = TEST. Anything else — incl. the
    production ``synth:<id>:open`` reversal open-leg — is KEPT as UNKNOWN.
    """
    fid = str(fill_id or "")
    sym = str(symbol or "")

    # ── REAL wins first ──
    if NUMERIC_OID.match(fid):
        return "REAL"

    # ── TEST signature ──
    if fid.startswith(SNAPSHOT_TEST_PREFIXES):
        # safety net: never delete a snapshot on a genuinely-traded symbol
        if sym not in TEST_OR_EMPTY_SYMBOLS:
            return "UNKNOWN"
        return "TEST"

    # synth:<id>:open (production), empty, or any other shape → keep + flag
    return "UNKNOWN"


# ── Table scan ───────────────────────────────────────────────────────────────


def _scan_trade_events(conn: sqlite3.Connection) -> Dict:
    rows = conn.execute(
        "SELECT id, calc_id, event_type, payload_json FROM trade_events"
    ).fetchall()
    test_ids: List[int] = []
    real = 0
    unknown_rows: List[Tuple] = []
    del_calc_ids: Dict[str, int] = {}
    del_buckets: Dict[Tuple, int] = {}
    for r in rows:
        p = _load_payload(r["payload_json"])
        d = classify_trade_event(r["calc_id"], r["event_type"], p)
        if d == "TEST":
            test_ids.append(int(r["id"]))
            ck = r["calc_id"] if r["calc_id"] is not None else "<NULL>"
            del_calc_ids[ck] = del_calc_ids.get(ck, 0) + 1
            oid = str(p.get("exchange_order_id") or "")
            shape = (
                "numeric" if NUMERIC_OID.match(oid) else
                "algo" if ALGO_OID.match(oid) else
                "synthetic" if oid.startswith(SYNTH_OID_PREFIXES) else
                "empty" if oid == "" else "other"
            )
            bk = (r["event_type"], shape, str(p.get("symbol") or "<none>"))
            del_buckets[bk] = del_buckets.get(bk, 0) + 1
        elif d == "REAL":
            real += 1
        else:
            unknown_rows.append(
                (int(r["id"]), r["calc_id"], r["event_type"],
                 (r["payload_json"] or "")[:120])
            )
    return {
        "total": len(rows), "test_ids": test_ids, "real": real,
        "unknown_rows": unknown_rows, "del_calc_ids": del_calc_ids,
        "del_buckets": del_buckets,
    }


def _scan_engine_events(conn: sqlite3.Connection) -> Dict:
    rows = conn.execute(
        "SELECT id, event_type, payload_json FROM engine_events"
    ).fetchall()
    test_ids: List[int] = []
    real = 0
    unknown_rows: List[Tuple] = []
    del_buckets: Dict[Tuple, int] = {}
    for r in rows:
        p = _load_payload(r["payload_json"])
        d = classify_engine_event(r["event_type"], p)
        if d == "TEST":
            test_ids.append(int(r["id"]))
            extra = ""
            if r["event_type"] == "dd_state_transition":
                extra = f"peak={p.get('peak_equity')}"
            elif r["event_type"] == "close_row_build_failed":
                extra = f"tpid={p.get('terminal_position_id')}"
            bk = (r["event_type"], extra)
            del_buckets[bk] = del_buckets.get(bk, 0) + 1
        elif d == "REAL":
            real += 1
        else:
            unknown_rows.append(
                (int(r["id"]), r["event_type"], (r["payload_json"] or "")[:120])
            )
    return {
        "total": len(rows), "test_ids": test_ids, "real": real,
        "unknown_rows": unknown_rows, "del_buckets": del_buckets,
    }


def _scan_position_fill_snapshots(conn: sqlite3.Connection) -> Dict:
    rows = conn.execute(
        "SELECT id, fill_id, symbol FROM position_fill_snapshots"
    ).fetchall()
    test_ids: List[int] = []
    real = 0
    unknown_rows: List[Tuple] = []
    del_buckets: Dict[Tuple, int] = {}
    for r in rows:
        d = classify_position_fill_snapshot(r["fill_id"], r["symbol"])
        if d == "TEST":
            test_ids.append(int(r["id"]))
            fid = str(r["fill_id"] or "")
            prefix = next((p for p in SNAPSHOT_TEST_PREFIXES if fid.startswith(p)), "?")
            bk = (prefix, str(r["symbol"] or "<none>"))
            del_buckets[bk] = del_buckets.get(bk, 0) + 1
        elif d == "REAL":
            real += 1
        else:
            unknown_rows.append(
                (int(r["id"]), r["fill_id"], str(r["symbol"] or ""))
            )
    return {
        "total": len(rows), "test_ids": test_ids, "real": real,
        "unknown_rows": unknown_rows, "del_buckets": del_buckets,
    }


def delete_ids(conn: sqlite3.Connection, table: str, ids: List[int]) -> int:
    """Delete rows by id (single transaction, batched for the param limit)."""
    if not ids:
        return 0
    BATCH = 500
    total = 0
    for start in range(0, len(ids), BATCH):
        chunk = ids[start:start + BATCH]
        ph = ",".join("?" * len(chunk))
        cur = conn.execute(f"DELETE FROM {table} WHERE id IN ({ph})", chunk)
        total += cur.rowcount
    conn.commit()
    return total


# ── Reporting ────────────────────────────────────────────────────────────────


def _report_trade_events(s: Dict) -> None:
    print("\n" + "=" * 72)
    print("trade_events")
    print("=" * 72)
    print(f"  total={s['total']}  DELETE(test)={len(s['test_ids'])}  "
          f"KEEP(real)={s['real']}  UNKNOWN(kept)={len(s['unknown_rows'])}")
    print("\n  -- DELETE by calc_id --")
    for cid, c in sorted(s["del_calc_ids"].items(), key=lambda x: -x[1]):
        flag = "" if (cid == "<NULL>" or cid in KNOWN_TEST_CALC_IDS) else "  <-- UNEXPECTED calc_id"
        print(f"    {cid:<28} {c}{flag}")
    print("\n  -- DELETE by (event_type, order-id shape, symbol) --")
    for bk, c in sorted(s["del_buckets"].items(), key=lambda x: -x[1]):
        print(f"    {bk[0]:<16} {bk[1]:<10} {bk[2]:<10} {c}")


def _report_engine_events(s: Dict) -> None:
    print("\n" + "=" * 72)
    print("engine_events")
    print("=" * 72)
    print(f"  total={s['total']}  DELETE(test)={len(s['test_ids'])}  "
          f"KEEP(real)={s['real']}  UNKNOWN(kept)={len(s['unknown_rows'])}")
    print("\n  -- DELETE by (event_type, detail) --")
    for bk, c in sorted(s["del_buckets"].items(), key=lambda x: -x[1]):
        print(f"    {bk[0]:<24} {bk[1]:<20} {c}")


def _report_position_fill_snapshots(s: Dict) -> None:
    print("\n" + "=" * 72)
    print("position_fill_snapshots")
    print("=" * 72)
    print(f"  total={s['total']}  DELETE(test)={len(s['test_ids'])}  "
          f"KEEP(real)={s['real']}  UNKNOWN(kept)={len(s['unknown_rows'])}")
    print("\n  -- DELETE by (fill_id prefix, symbol) --")
    for bk, c in sorted(s["del_buckets"].items(), key=lambda x: -x[1]):
        print(f"    {bk[0]:<18} {bk[1]:<10} {c}")


def _report_unknown(name: str, unknown_rows: List[Tuple]) -> None:
    if not unknown_rows:
        return
    print(f"\n  !! {len(unknown_rows)} UNKNOWN {name} rows (KEPT — review):")
    for row in unknown_rows[:25]:
        print(f"     {row}")
    if len(unknown_rows) > 25:
        print(f"     ... and {len(unknown_rows) - 25} more")


# ── Entry point ──────────────────────────────────────────────────────────────


def run_clean(
    db_path: str = DEFAULT_DB_PATH,
    *,
    apply: bool = False,
    tables: Optional[List[str]] = None,
    verbose: bool = True,
) -> Dict:
    """Programmable entrypoint (called by main + tests)."""
    tables = tables or ["trade_events", "engine_events", "position_fill_snapshots"]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    summary: Dict = {"db": db_path, "applied": apply, "tables": {}}

    scanners: Dict[str, Tuple[Callable, Callable]] = {
        "trade_events": (_scan_trade_events, _report_trade_events),
        "engine_events": (_scan_engine_events, _report_engine_events),
        "position_fill_snapshots": (
            _scan_position_fill_snapshots, _report_position_fill_snapshots),
    }

    if verbose:
        print(f"Scanning {db_path}")

    for table in tables:
        scan, report = scanners[table]
        try:
            s = scan(conn)
        except sqlite3.OperationalError as e:
            if verbose:
                print(f"  {table}: skipped ({e})")
            continue
        if verbose:
            report(s)
            _report_unknown(table, s["unknown_rows"])
        deleted = 0
        if apply:
            deleted = delete_ids(conn, table, s["test_ids"])
            if verbose:
                print(f"\n  [APPLIED] deleted {deleted} {table} rows.")
        summary["tables"][table] = {
            "total": s["total"],
            "test": len(s["test_ids"]),
            "real": s["real"],
            "unknown": len(s["unknown_rows"]),
            "deleted": deleted,
            "test_ids": s["test_ids"],
        }

    conn.close()

    if verbose:
        print("\n" + "=" * 72)
        tot_test = sum(t["test"] for t in summary["tables"].values())
        tot_unknown = sum(t["unknown"] for t in summary["tables"].values())
        if apply:
            tot_del = sum(t["deleted"] for t in summary["tables"].values())
            print(f"APPLIED. Deleted {tot_del} test rows total "
                  f"({tot_unknown} unknown rows kept).")
        else:
            print(f"[DRY-RUN] Would delete {tot_test} test rows total "
                  f"({tot_unknown} unknown rows kept). No changes made.")
            print("Re-run with --apply after backing up the DB to commit.")
        print("=" * 72)

    return summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true",
                        help="Delete test rows (default: dry-run, no writes).")
    parser.add_argument(
        "--table",
        choices=["trade_events", "engine_events", "position_fill_snapshots"],
        default=None, help="Restrict to one table.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH,
                        help=f"DB path (default: {DEFAULT_DB_PATH}).")
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"ERROR: DB not found at {args.db}", file=sys.stderr)
        return 1

    if args.apply:
        print("=" * 72)
        print("WARNING: --apply WILL DELETE rows from")
        print(f"  {args.db}")
        print("  This is destructive. Back up the DB first.")
        print("  Press Ctrl+C in the next 3 seconds to abort.")
        print("=" * 72)
        import time
        for s in (3, 2, 1):
            print(f"  proceeding in {s}...", end="\r")
            time.sleep(1)
        print("  proceeding now.            \n")

    tables = [args.table] if args.table else None
    run_clean(db_path=args.db, apply=args.apply, tables=tables)
    return 0


if __name__ == "__main__":
    sys.exit(main())
