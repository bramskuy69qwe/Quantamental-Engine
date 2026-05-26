"""
Calculator-to-order correlation — strict matcher per spec §4.

LIMIT orders: 5/5 criteria (ticker, side, in-window, entry-loose, TP, SL).
MARKET orders: 6/6 (entry-loose compared against avg_fill_price).

Pure function — returns a :class:`MatchResult` carrying the decision plus
per-criterion audit rows. The caller (``core/order_enrichment.py``)
persists the audit rows, updates ``orders.link_status``, and routes the
calc-status flip through ``core/calc_state.transition()`` so the
event-bus fires and the choke-point holds (spec §3.6).

Side note: live DB column is ``side``; spec §3 wording uses
``direction``. This module uses ``side`` to match the schema; the spec
drift is purely terminological.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("calc_correlation")


# Spec §3.3 defaults — used by the caller if accounts.config_json hasn't
# been populated. Kept here so the matcher's tests can drive defaults
# without round-tripping through the config layer (which T2 builds).
SPEC_DEFAULT_WINDOW_SECONDS         = 300
SPEC_DEFAULT_CLOCK_SKEW_TOLERANCE   = 10
SPEC_DEFAULT_ENTRY_TOLERANCE_PCT    = 0.25  # percent, not ratio (0.25 == 0.25%)


# link_status values per spec §3.4 (orders.link_status enum)
LINK_STATUS_LINKED              = "LINKED"
LINK_STATUS_NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"
LINK_STATUS_UNPLANNED           = "UNPLANNED"


@dataclass
class MatchResult:
    """Outcome of one matcher invocation.

    Fields:
        calc_id: winning calc's identifier, or ``None`` if no full match.
        link_status: ``LINKED`` | ``NEEDS_MANUAL_REVIEW`` | ``UNPLANNED``
            per spec §3.4. Always set; caller writes it onto
            ``orders.link_status``.
        audit_rows: list of dicts ready for
            ``Database.insert_calc_match_audit_batch``. One row per
            candidate per criterion. The winning candidate's rows carry
            ``winning=True``.
        matched_from_status: the winning calc's pre-match status
            (``active`` or ``released``). The caller passes this into
            ``calc_state.transition(..., current_status=...)`` to drive
            the choke-point. ``None`` when no match.
    """
    calc_id: Optional[str]
    link_status: str
    audit_rows: List[Dict[str, Any]] = field(default_factory=list)
    matched_from_status: Optional[str] = None


def correlate_order_to_calc(
    order: Dict[str, Any],
    *,
    order_id: int,
    tick_size: float,
    entry_tolerance_pct: float = SPEC_DEFAULT_ENTRY_TOLERANCE_PCT,
    window_seconds: int = SPEC_DEFAULT_WINDOW_SECONDS,
    clock_skew_tolerance_sec: int = SPEC_DEFAULT_CLOCK_SKEW_TOLERANCE,
    now_ts_ms: Optional[int] = None,
    db_path: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> MatchResult:
    """Strict 5/5 (LIMIT) / 6/6 (MARKET) matcher per spec §4.

    Args:
        order: dict with keys ``account_id``, ``symbol``, ``side``,
            ``order_type``, ``price`` (limit), ``avg_fill_price``
            (market), ``tp_trigger_price``, ``sl_trigger_price``,
            ``created_at_ms`` (order placement time in ms; defaults to
            now if missing).
        order_id: ``orders.id`` for the audit row's ``order_id`` field.
        tick_size: per-symbol tick size; used as the tolerance bound for
            TP and SL criteria (spec §4.2: ``|order_X - calc_X| ≤
            N * tick_size``, N=1 default).
        entry_tolerance_pct: per-account loose-entry tolerance in
            **percent** (spec §3.3 default 0.25 == 0.25%). Caller
            resolves from ``accounts.config_json``.
        window_seconds: account-default window. Per-calc override comes
            from ``pre_trade_log.window_seconds`` (frozen at creation by
            T2). Spec §3.3 default 300.
        clock_skew_tolerance_sec: spec §4.2 padding on the time-window
            comparison. Spec §3.3 default 10.
        now_ts_ms: matcher's reference time in ms (testability hook).
            Defaults to ``time.time() * 1000``.
        db_path: explicit per-account DB path. If omitted, resolved via
            ``core.db_account_settings._resolve_db_path``.
        data_dir: data root used by the DB-path resolver fallback.

    Returns:
        :class:`MatchResult` carrying calc_id (if a single full match was
        found), link_status, and the audit rows for every candidate's
        per-criterion match record.

    Decision flow (spec §4.3):
        - 0 candidates in window  → ``UNPLANNED``
        - 1+ candidates, 1 full match → ``LINKED``
        - 1+ candidates, >1 full matches → most-recent wins; others
          marked losing in audit rows
        - 1+ candidates, 0 full matches → ``NEEDS_MANUAL_REVIEW``

    The matcher is a **pure** function — it does not write to the DB.
    The caller persists ``audit_rows`` via
    ``Database.insert_calc_match_audit_batch`` and triggers the calc
    transition through :func:`core.calc_state.transition`.
    """
    ticker = order.get("symbol", "")
    side = order.get("side", "")
    if not ticker or not side:
        return MatchResult(None, LINK_STATUS_UNPLANNED)

    order_type = (order.get("order_type") or "").lower()
    is_market = order_type == "market"

    tp_price = order.get("tp_trigger_price")
    sl_price = order.get("sl_trigger_price")
    if not tp_price or not sl_price:
        # Caller (``_try_correlate``) already gates on this; defensive
        # belt-and-suspenders. Returning UNPLANNED with no audit rows
        # signals "matcher hasn't run yet" rather than "matcher decided
        # zero candidates".
        return MatchResult(None, LINK_STATUS_UNPLANNED)

    # Entry source differs by order type (spec §4.1):
    #   LIMIT  → order.price (the intended limit price)
    #   MARKET → order.avg_fill_price (the actual fill price)
    if is_market:
        entry_source = order.get("avg_fill_price") or 0.0
    else:
        entry_source = order.get("price") or 0.0
    if not entry_source:
        # Defensive: a market order with no fill yet should be deferred
        # by the caller. If we got here, fail closed.
        return MatchResult(None, LINK_STATUS_UNPLANNED)

    # Resolve DB path
    if db_path is None:
        try:
            from core.db_account_settings import _resolve_db_path
            account_id = order.get("account_id", 1)
            db_path = _resolve_db_path(account_id, data_dir)
        except Exception:
            return MatchResult(None, LINK_STATUS_UNPLANNED)

    account_id = order.get("account_id", 1)

    if now_ts_ms is None:
        now_ts_ms = int(time.time() * 1000)
    order_ts_ms = int(order.get("created_at_ms") or now_ts_ms)

    # Pre-filter candidates by account / symbol / side / status (spec
    # §4.3 SQL). In-window check happens in Python because each calc
    # can carry its own ``window_seconds`` override (NULL → account
    # default).
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT calc_id, timestamp, effective_entry, tp_price, "
            "       sl_price, status, window_seconds "
            "FROM pre_trade_log "
            "WHERE account_id = ? "
            "  AND status IN ('active', 'released') "
            "  AND ticker = ? "
            "  AND side = ? "
            "  AND calc_id IS NOT NULL "
            "ORDER BY timestamp DESC",
            (account_id, ticker, side),
        ).fetchall()
        conn.close()
    except Exception:
        log.warning("calc correlation query failed", exc_info=True)
        return MatchResult(None, LINK_STATUS_UNPLANNED)

    # Per-criterion evaluation — for every candidate that passes the
    # in-window gate, record one audit row per criterion. Tolerances
    # per spec §4.2.
    in_window_candidates: List[Tuple[Dict[str, Any], List[Dict[str, Any]], bool]] = []
    #   ↑ (candidate-row-dict, criterion-rows, all-matched-bool)

    entry_tol_ratio = entry_tolerance_pct / 100.0  # 0.25 → 0.0025

    for row in rows:
        calc_id = row["calc_id"]
        calc_window = row["window_seconds"] or window_seconds

        # In-window check (spec §4.2): age compared to per-calc window
        # plus clock-skew padding.
        try:
            calc_ts = datetime.fromisoformat(
                (row["timestamp"] or "").replace("Z", "+00:00")
            )
            if calc_ts.tzinfo is None:
                calc_ts = calc_ts.replace(tzinfo=timezone.utc)
            calc_ts_ms = int(calc_ts.timestamp() * 1000)
        except Exception:
            continue  # malformed timestamp — not a candidate

        age_sec = abs(order_ts_ms - calc_ts_ms) / 1000.0
        window_bound = calc_window + clock_skew_tolerance_sec
        if age_sec > window_bound:
            continue  # out of window — not a candidate per spec §4.3

        # Per-criterion checks
        criteria: List[Dict[str, Any]] = []

        # ticker (exact — already pre-filtered, but audit it for completeness)
        criteria.append(_audit_row(
            order_id, calc_id, "ticker", ticker, ticker, 0.0,
            matched=True, ts_ms=now_ts_ms,
        ))
        # direction / side (exact — already pre-filtered)
        criteria.append(_audit_row(
            order_id, calc_id, "direction", side, side, 0.0,
            matched=True, ts_ms=now_ts_ms,
        ))
        # in-window (already pre-filtered to True at this point)
        criteria.append(_audit_row(
            order_id, calc_id, "window",
            str(calc_ts_ms), str(order_ts_ms),
            float(window_bound),
            matched=True, ts_ms=now_ts_ms,
        ))
        # entry-loose (spec §4.2: |order - calc| / calc ≤ entry_tolerance_pct)
        calc_entry = row["effective_entry"] or 0.0
        entry_drift = (
            abs(entry_source - calc_entry) / calc_entry if calc_entry else 1.0
        )
        entry_ok = entry_drift <= entry_tol_ratio
        criteria.append(_audit_row(
            order_id, calc_id, "entry",
            calc_entry, entry_source, entry_tol_ratio,
            matched=entry_ok, ts_ms=now_ts_ms,
        ))
        # TP (spec §4.2: |order_tp - calc_tp| ≤ N * tick_size, N=1)
        calc_tp = row["tp_price"] or 0.0
        tp_ok = abs(tp_price - calc_tp) <= tick_size
        criteria.append(_audit_row(
            order_id, calc_id, "tp",
            calc_tp, tp_price, tick_size,
            matched=tp_ok, ts_ms=now_ts_ms,
        ))
        # SL
        calc_sl = row["sl_price"] or 0.0
        sl_ok = abs(sl_price - calc_sl) <= tick_size
        criteria.append(_audit_row(
            order_id, calc_id, "sl",
            calc_sl, sl_price, tick_size,
            matched=sl_ok, ts_ms=now_ts_ms,
        ))

        all_matched = all(c["matched"] for c in criteria)
        in_window_candidates.append((dict(row), criteria, all_matched))

    if not in_window_candidates:
        # Spec §4.3: zero candidates in window → UNPLANNED, no audit
        # rows (nothing to audit; the order genuinely has no calcs to
        # compare against).
        return MatchResult(None, LINK_STATUS_UNPLANNED)

    full_matches = [c for c in in_window_candidates if c[2]]

    # Flatten all audit rows; we'll set winning=True on the winner's
    # rows below.
    all_audit_rows: List[Dict[str, Any]] = []
    for _row, criteria, _ok in in_window_candidates:
        all_audit_rows.extend(criteria)

    if not full_matches:
        # Candidates exist but none fully match → manual review.
        return MatchResult(
            calc_id=None,
            link_status=LINK_STATUS_NEEDS_MANUAL_REVIEW,
            audit_rows=all_audit_rows,
        )

    # Pick winner: most-recent calc (rows are already ORDER BY timestamp
    # DESC, so full_matches[0] is the newest).
    winner_row, winner_criteria, _ = full_matches[0]
    winner_calc_id = winner_row["calc_id"]
    winner_status = winner_row["status"]

    # Mark the winner's audit rows as winning=True (spec §3.1
    # calc_match_audit column).
    for c in winner_criteria:
        c["winning"] = True

    return MatchResult(
        calc_id=winner_calc_id,
        link_status=LINK_STATUS_LINKED,
        audit_rows=all_audit_rows,
        matched_from_status=winner_status,
    )


def _audit_row(
    order_id: int,
    calc_id: str,
    criterion: str,
    calc_value: Any,
    order_value: Any,
    tolerance_used: float,
    *,
    matched: bool,
    ts_ms: int,
) -> Dict[str, Any]:
    """Build one ``calc_match_audit`` row dict (winning=False by default).

    Caller flips ``winning=True`` on the winner's six rows after the
    decision lands. Schema mirrors
    :meth:`Database.insert_calc_match_audit_batch`.
    """
    return {
        "order_id":       order_id,
        "calc_id":        calc_id,
        "criterion":      criterion,
        "calc_value":     str(calc_value) if calc_value is not None else None,
        "order_value":    str(order_value) if order_value is not None else None,
        "tolerance_used": float(tolerance_used),
        "matched":        bool(matched),
        "ts_ms":          int(ts_ms),
        "winning":        False,
    }


# ── Manual link candidate finder ─────────────────────────────────────────────


@dataclass
class CandidateCalc:
    calc_id: str
    ticker: str
    side: str
    effective_entry: float
    entry_drift_pct: float
    entry_match: bool
    tp_price: float
    tp_drift_pct: float
    tp_match: bool
    sl_price: float
    sl_drift_pct: float
    sl_match: bool
    timestamp: str
    age_hours: float


def find_candidate_calcs(
    order: Dict[str, Any],
    *,
    max_drift_pct: float = 0.05,
    within_hours: int = 168,
    db_path: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> List[CandidateCalc]:
    """Find pre_trade_log entries that might match *order* within drift tolerance.

    Includes candidates where at least ONE leg matches within max_drift_pct.
    Sorted by: count-of-matching-legs DESC, drift sum ASC, timestamp DESC.
    """
    entry_price = order.get("price", 0)
    tp_price = order.get("tp_trigger_price", 0)
    sl_price = order.get("sl_trigger_price", 0)
    ticker = order.get("symbol", "")
    side = order.get("side", "")

    if not ticker or not entry_price:
        return []

    if db_path is None:
        try:
            from core.db_account_settings import _resolve_db_path
            db_path = _resolve_db_path(order.get("account_id", 1), data_dir)
        except Exception:
            return []

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=within_hours)).isoformat()
    now = datetime.now(timezone.utc)

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT calc_id, effective_entry, tp_price, sl_price, timestamp "
            "FROM pre_trade_log "
            "WHERE ticker = ? AND side = ? AND timestamp >= ? "
            "AND calc_id IS NOT NULL "
            "ORDER BY timestamp DESC",
            (ticker, side, cutoff),
        ).fetchall()
        conn.close()
    except Exception:
        return []

    # Filter out already-linked calc_ids
    linked: set = set()
    try:
        conn = sqlite3.connect(db_path)
        for r in conn.execute(
            "SELECT DISTINCT calc_id FROM orders WHERE calc_id IS NOT NULL"
        ).fetchall():
            linked.add(r[0])
        conn.close()
    except Exception:
        pass

    candidates: List[CandidateCalc] = []
    for row in rows:
        cid = row["calc_id"]
        if not cid or cid in linked:
            continue

        eff = row["effective_entry"] or 0
        tp = row["tp_price"] or 0
        sl = row["sl_price"] or 0

        e_drift = abs(entry_price - eff) / eff if eff else 1.0
        t_drift = abs(tp_price - tp) / tp if tp and tp_price else 1.0
        s_drift = abs(sl_price - sl) / sl if sl and sl_price else 1.0

        e_match = e_drift <= max_drift_pct
        t_match = t_drift <= max_drift_pct
        s_match = s_drift <= max_drift_pct

        if not (e_match or t_match or s_match):
            continue

        try:
            ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_h = (now - ts).total_seconds() / 3600
        except Exception:
            age_h = 0

        candidates.append(CandidateCalc(
            calc_id=cid, ticker=ticker, side=side,
            effective_entry=eff, entry_drift_pct=round(e_drift, 6), entry_match=e_match,
            tp_price=tp, tp_drift_pct=round(t_drift, 6), tp_match=t_match,
            sl_price=sl, sl_drift_pct=round(s_drift, 6), sl_match=s_match,
            timestamp=row["timestamp"], age_hours=round(age_h, 1),
        ))

    candidates.sort(key=lambda c: (
        -(int(c.entry_match) + int(c.tp_match) + int(c.sl_match)),
        c.entry_drift_pct + c.tp_drift_pct + c.sl_drift_pct,
        c.timestamp,
    ))
    return candidates
