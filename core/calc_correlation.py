"""
Calculator-to-order correlation — strict matcher per spec §4.

Both LIMIT and MARKET orders evaluate the SAME 6/6 criteria (ticker,
side, in-window, entry-loose, TP, SL — all must match). The only
difference is the entry comparison source: LIMIT uses the order's limit
price, MARKET uses avg_fill_price (a market order carries no limit
price). Earlier drafts labeled LIMIT "5/5" by not counting entry; the
matcher gates entry for both.

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

from core import correlation_log

log = logging.getLogger("calc_correlation")


# Spec §3.3 defaults — used by the caller if accounts.config_json hasn't
# been populated. Kept here so the matcher's tests can drive defaults
# without round-tripping through the config layer (which T2 builds).
SPEC_DEFAULT_WINDOW_SECONDS         = 300
SPEC_DEFAULT_CLOCK_SKEW_TOLERANCE   = 10
SPEC_DEFAULT_ENTRY_TOLERANCE_PCT    = 0.25  # percent, not ratio (0.25 == 0.25%)


# link_status values per spec §3.4 (orders.link_status enum).
#
# Spec ambiguity (T212 L6): spec §3.4 lists four states — LINKED,
# NEEDS_MANUAL_REVIEW, UNLINKED, UNPLANNED — but the matcher pseudocode
# in §4.3 + the state diagram in §6 only have the matcher emit three:
# LINKED, NEEDS_MANUAL_REVIEW, UNPLANNED.
#
# UNLINKED appears in §3.4 (enum) and §6 (operator-action transitions:
# UNLINKED → UNPLANNED, UNLINKED → LINKED via manual link) but is NEVER
# produced by the matcher itself. The state exists for OPERATOR action
# only — Phase 3 endpoints (POST /orders/{id}/mark_unplanned,
# /manual_link, etc.) will set/clear it. Our matcher therefore emits
# NEEDS_MANUAL_REVIEW in the "candidates exist, none full-match" case
# (per §4.3 pseudocode, matching §6 diagram), and never UNLINKED.
#
# Resolution per Rule 6: pin NEEDS_MANUAL_REVIEW as the matcher's
# output for partial-match candidates; UNLINKED remains a valid enum
# value reserved for operator-driven state transitions (covered by
# core/link_state.py's transition tables). Worth confirming with the
# operator if a use case for UNLINKED-as-matcher-output emerges later.
LINK_STATUS_LINKED              = "LINKED"
LINK_STATUS_NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"
LINK_STATUS_UNPLANNED           = "UNPLANNED"
LINK_STATUS_UNLINKED            = "UNLINKED"  # operator-set only, never matcher-emitted


# Side-vocabulary normalization. The calculator writes "long"/"short"
# into pre_trade_log.side (core/risk_engine.py); WS adapters write
# "BUY"/"SELL" into orders.side (core/adapters/{binance,bybit}/ws_adapter.py).
# Without normalization, the matcher's SQL `WHERE side = ?` never matches.
# T211 fix: collapse both vocabularies to canonical 'long'/'short' at
# comparison time. Returns the input unchanged when the value isn't
# recognized — defensive against future adapters introducing new
# strings; mismatch then fails the criterion explicitly rather than
# silently aliasing.
_BUY_TOKENS:  frozenset = frozenset({"long", "buy", "LONG", "BUY", "Long", "Buy"})
_SELL_TOKENS: frozenset = frozenset({"short", "sell", "SHORT", "SELL", "Short", "Sell"})


def norm_side(value: Optional[str]) -> str:
    """Normalize a side string to canonical 'long' / 'short'.

    Public — used across the matcher (this module), supersede pass
    (``core/handlers.py``), and manual-link candidate finder (this
    module). Promoted from ``_norm_side`` in T215 (audit M2) so
    external callers no longer reach into a private helper.

    Unknown values are returned lowercased (so two unrecognized
    strings of the same shape still match each other, but a
    'BUY' would not match a 'sneeze').
    """
    if not value:
        return ""
    if value in _BUY_TOKENS:
        return "long"
    if value in _SELL_TOKENS:
        return "short"
    return value.lower()


# T215 M2a: keep the underscore alias for the matcher's in-module
# callsites (no functional change). Future cleanup can drop the alias
# once all internal references migrate to the public name.
_norm_side = norm_side


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
    """Strict 6/6 matcher (LIMIT + MARKET) per spec §4.

    Both order types gate the same six criteria; only the entry
    comparison source differs (LIMIT → limit price, MARKET → avg fill
    price). See the module docstring.

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

    corr-tap: attr_match_attempt (CL.T3b-entry, spec §5.6). This public
    entry is a thin wrapper around ``_correlate_order_to_calc_impl`` so
    that EVERY invocation — every decision, every defensive early
    return, every exception — emits exactly one envelope (mandate 1:
    no silent exits), structurally guaranteed by the ``finally``.
    Emission is the only side effect; the matcher stays pure w.r.t.
    engine state.
    """
    _trace: Dict[str, Any] = {}
    _t0 = time.perf_counter()
    _err: Optional[str] = None
    result: Optional[MatchResult] = None
    try:
        result = _correlate_order_to_calc_impl(
            order,
            order_id=order_id,
            tick_size=tick_size,
            entry_tolerance_pct=entry_tolerance_pct,
            window_seconds=window_seconds,
            clock_skew_tolerance_sec=clock_skew_tolerance_sec,
            now_ts_ms=now_ts_ms,
            db_path=db_path,
            data_dir=data_dir,
            _trace=_trace,
        )
        return result
    except Exception as e:
        _err = type(e).__name__
        raise
    finally:
        if _err is not None:
            outcome, reason = "ERROR", None
        elif _trace.get("skip"):
            outcome, reason = "SKIPPED", _trace["skip"]
        elif result is not None and result.link_status == LINK_STATUS_LINKED:
            outcome, reason = "LINKED", None
        elif (result is not None
              and result.link_status == LINK_STATUS_NEEDS_MANUAL_REVIEW):
            outcome, reason = "NEEDS_MANUAL_REVIEW", "no_full_match"
        else:
            outcome, reason = "UNPLANNED", "no_candidates_in_window"
        # Per-candidate failed-criteria summary, derived from the audit
        # rows (one line must read "calc X failed [tp, sl]" — the
        # per-criterion trace the manual-review queue persists in full).
        cands: List[Dict[str, Any]] = []
        if result is not None and result.audit_rows:
            failed_by_calc: Dict[str, List[str]] = {}
            for r in result.audit_rows:
                failed_by_calc.setdefault(r["calc_id"], [])
                if not r["matched"]:
                    failed_by_calc[r["calc_id"]].append(r["criterion"])
            cands = [{"calc_id": c, "failed": f}
                     for c, f in failed_by_calc.items()]
        eid = str(order.get("exchange_order_id") or "")
        payload: Dict[str, Any] = {
            "outcome": outcome,
            # identity tuple VERBATIM incl. "" (mandate 2)
            "calc_id": (result.calc_id if result and result.calc_id else ""),
            "exchange_order_id": eid,
            "terminal_position_id": str(order.get("terminal_position_id") or ""),
            "lifecycle_id": str(order.get("lifecycle_id") or ""),
            "order_id": order_id,
            "candidates": cands[:20],
            "n_candidates": len(cands),
            "n_prefilter_rows": _trace.get("n_prefilter_rows"),
            "tolerances": {
                "entry_pct": entry_tolerance_pct,
                "tick_size": tick_size,
                "window_s": window_seconds,
                "skew_s": clock_skew_tolerance_sec,
            },
            "is_market": (order.get("order_type") or "").lower() == "market",
            "duration_ms": round((time.perf_counter() - _t0) * 1000, 2),
        }
        if reason:
            payload["reason"] = reason
        if _err is not None:
            payload["error_type"] = _err
        if len(cands) > 20:
            payload["n_candidates_omitted"] = len(cands) - 20
        if eid:
            # dedup_key of the triggering order (mandate 3) — same
            # NORMALIZED convention as order_status_applied (T3a): a
            # re-run on the SAME order state (the double-process bug) is
            # a one-grep find; a legitimate re-run after a state change
            # gets a fresh key.
            payload["dedup_key"] = (
                f"{eid}:{order.get('status') or ''}:{order.get('quantity') or ''}"
            )
        correlation_log.emit(
            "calc_correlation", "internal", "internal",
            correlation_log.CAT_ATTR_MATCH_ATTEMPT, payload,
            account_id=order.get("account_id", 1),
            symbol=order.get("symbol") or None,
        )


def _correlate_order_to_calc_impl(
    order: Dict[str, Any],
    *,
    order_id: int,
    tick_size: float,
    entry_tolerance_pct: float,
    window_seconds: int,
    clock_skew_tolerance_sec: int,
    now_ts_ms: Optional[int],
    db_path: Optional[str],
    data_dir: Optional[str],
    _trace: Dict[str, Any],
) -> MatchResult:
    """The matcher body (see :func:`correlate_order_to_calc` for the full
    contract). ``_trace`` collects the skip reason / prefilter stats the
    wrapper's attr_match_attempt envelope reports — every defensive
    early return below sets ``_trace["skip"]`` so the envelope can
    distinguish "decided UNPLANNED on zero candidates" from "could not
    evaluate" (the two were indistinguishable from the returned
    MatchResult alone — both UNPLANNED with no audit rows)."""
    ticker = order.get("symbol", "")
    side_raw = order.get("side", "")
    if not ticker or not side_raw:
        _trace["skip"] = "no_ticker_or_side"
        return MatchResult(None, LINK_STATUS_UNPLANNED)
    side_canonical = _norm_side(side_raw)

    order_type = (order.get("order_type") or "").lower()
    is_market = order_type == "market"

    tp_price = order.get("tp_trigger_price")
    sl_price = order.get("sl_trigger_price")
    if not tp_price or not sl_price:
        # Caller (``_try_correlate``) already gates on this; defensive
        # belt-and-suspenders. Returning UNPLANNED with no audit rows
        # signals "matcher hasn't run yet" rather than "matcher decided
        # zero candidates".
        _trace["skip"] = "no_tp_sl_on_order"
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
        _trace["skip"] = "no_entry_source"
        return MatchResult(None, LINK_STATUS_UNPLANNED)

    # Resolve DB path
    if db_path is None:
        try:
            from core.db_account_settings import _resolve_db_path
            account_id = order.get("account_id", 1)
            db_path = _resolve_db_path(account_id, data_dir)
        except Exception:
            _trace["skip"] = "db_path_unresolved"
            return MatchResult(None, LINK_STATUS_UNPLANNED)

    account_id = order.get("account_id", 1)

    if now_ts_ms is None:
        now_ts_ms = int(time.time() * 1000)
    raw_created_ms = order.get("created_at_ms")
    if not raw_created_ms:
        # T212 L5: silent fallback to "now" makes the in-window check
        # pass when it shouldn't (a stale order with created_at_ms=0
        # would always be evaluated as "just placed"). Real adapters
        # populate this; warn so we notice when production hits it.
        log.warning(
            "matcher saw order_id=%s with no created_at_ms; falling back "
            "to now() for the in-window check — adapter ingest may have "
            "missed the timestamp",
            order_id,
        )
        order_ts_ms = now_ts_ms
    else:
        order_ts_ms = int(raw_created_ms)

    # Pre-filter candidates by account / status / ticker (spec §4.3).
    # The side and in-window checks happen in Python because:
    #   - side requires vocabulary normalization (BUY/SELL ↔ long/short),
    #     pushing that into SQL would require a verbose IN-list or a
    #     denormalized side column. Python is simpler and the per-symbol
    #     candidate set is small in practice.
    #   - each calc can carry its own ``window_seconds`` override
    #     (NULL → account default).
    # Index `idx_pretrade_matcher` covers (account_id, status, ticker).
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT calc_id, timestamp, side, effective_entry, tp_price, "
            "       sl_price, status, window_seconds "
            "FROM pre_trade_log "
            "WHERE account_id = ? "
            "  AND status IN ('active', 'released') "
            "  AND ticker = ? "
            "  AND calc_id IS NOT NULL "
            "ORDER BY timestamp DESC",
            (account_id, ticker),
        ).fetchall()
        conn.close()
    except Exception:
        log.warning("calc correlation query failed", exc_info=True)
        _trace["skip"] = "query_failed"
        return MatchResult(None, LINK_STATUS_UNPLANNED)
    _trace["n_prefilter_rows"] = len(rows)

    # Per-criterion evaluation — for every candidate that passes the
    # in-window gate, record one audit row per criterion. Tolerances
    # per spec §4.2.
    in_window_candidates: List[Tuple[Dict[str, Any], List[Dict[str, Any]], bool]] = []
    #   ↑ (candidate-row-dict, criterion-rows, all-matched-bool)

    entry_tol_ratio = entry_tolerance_pct / 100.0  # 0.25 → 0.0025

    for row in rows:
        calc_id = row["calc_id"]
        calc_side_canonical = _norm_side(row["side"])
        if calc_side_canonical != side_canonical:
            continue  # side mismatch — not a candidate (T211 H1 fix)
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

        # Malformed-calc skip (T211 M5, narrowed in T7 P1.T7): a calc
        # with no effective_entry can't be evaluated — entry is the
        # price anchor for the loose-entry criterion AND its drift
        # denominator. Skip such a calc as a non-candidate.
        #
        # NOTE (T7): null/0 TP or SL is NOT skipped here. Per spec Q27
        # ("Allow nullable TP/SL but auto-route to manual-link") + §13,
        # a calc may legitimately carry a null TP or SL (operator chose
        # not to set one). Such a calc MUST surface to manual review —
        # not be silently excluded. The TP/SL criterion below evaluates
        # null → matched=False (bool() guard), so the candidate can't
        # auto-link and the order routes to NEEDS_MANUAL_REVIEW. T211
        # originally over-skipped TP/SL too; T7 narrows it to entry-only.
        calc_entry = row["effective_entry"] or 0.0
        if not calc_entry:
            log.debug("skipping calc %s — no effective_entry (anchor)", calc_id)
            continue

        # Per-criterion checks
        criteria: List[Dict[str, Any]] = []

        # ticker (exact — already pre-filtered, but audit it for completeness)
        criteria.append(_audit_row(
            order_id, calc_id, "ticker", ticker, ticker, 0.0,
            matched=True, ts_ms=now_ts_ms,
        ))
        # direction / side — pre-filtered by _norm_side equivalence above.
        # Audit records the RAW values (not canonicalized) so the operator
        # can see the actual vocabulary divergence in the manual-link diff.
        criteria.append(_audit_row(
            order_id, calc_id, "direction", row["side"], side_raw, 0.0,
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
        entry_drift = abs(entry_source - calc_entry) / calc_entry
        entry_ok = entry_drift <= entry_tol_ratio
        criteria.append(_audit_row(
            order_id, calc_id, "entry",
            calc_entry, entry_source, entry_tol_ratio,
            matched=entry_ok, ts_ms=now_ts_ms,
        ))
        # TP (spec §4.2: |order_tp - calc_tp| ≤ N * tick_size, N=1).
        # T7: an absent calc TP can't be confirmed → matched=False (the
        # bool() short-circuit also avoids a None-subtraction). The
        # candidate then can't be a full match → order → manual-link.
        #
        # "Absent" = falsy: the pre_trade_log.tp_price/sl_price columns
        # are NOT NULL DEFAULT 0, so an operator who omits a TP/SL
        # stores 0.0 (not SQL NULL). Both 0.0 and a hypothetical NULL
        # are treated as "no TP/SL". The audit records calc_value=None
        # for an absent value (clearer "calc had no TP" signal in the
        # manual-review diff than "0.0").
        calc_tp = row["tp_price"]
        tp_ok = bool(calc_tp) and abs(tp_price - calc_tp) <= tick_size
        criteria.append(_audit_row(
            order_id, calc_id, "tp",
            calc_tp if calc_tp else None, tp_price, tick_size,
            matched=tp_ok, ts_ms=now_ts_ms,
        ))
        # SL — same absent-value handling (T7)
        calc_sl = row["sl_price"]
        sl_ok = bool(calc_sl) and abs(sl_price - calc_sl) <= tick_size
        criteria.append(_audit_row(
            order_id, calc_id, "sl",
            calc_sl if calc_sl else None, sl_price, tick_size,
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
    # P8.T5 (reframe of the impossible §10.4 pre-submission modal): the calc's
    # status ('active' | 'released'). A 'released' candidate means this order
    # may be a REPLACEMENT for a cancelled order — replaced_order carries that
    # cancelled order's context (exchange_order_id + cancel_ts_ms) so the
    # needs-link UI can surface "replacement for order X @ time".
    status: str = "active"
    replaced_order: Optional[Dict[str, Any]] = None


def _cancelled_order_for_calc(conn, calc_id: str, account_id: int) -> Optional[Dict[str, Any]]:
    """P8.T5: the most-recent CANCELLED order for *calc_id* — the order this
    released calc's replacement would stand in for. Best-effort: returns
    ``{exchange_order_id, cancel_ts_ms}`` or None (older DBs may lack the
    cancel_ts_ms column / have no cancelled order). Account-scoped (Phase 8
    audit) — consistent with the strict matcher; matters on the combined-DB
    fallback path where one file holds multiple accounts."""
    try:
        r = conn.execute(
            "SELECT exchange_order_id, cancel_ts_ms FROM orders "
            "WHERE calc_id = ? AND account_id = ? AND status = 'canceled' "
            "ORDER BY COALESCE(cancel_ts_ms, 0) DESC LIMIT 1",
            (calc_id, account_id),
        ).fetchone()
    except Exception:
        return None
    if not r:
        return None
    return {"exchange_order_id": r[0], "cancel_ts_ms": r[1]}


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
    account_id = order.get("account_id", 1)

    if not ticker or not entry_price:
        return []

    if db_path is None:
        try:
            from core.db_account_settings import _resolve_db_path
            db_path = _resolve_db_path(account_id, data_dir)
        except Exception:
            return []

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=within_hours)).isoformat()
    now = datetime.now(timezone.utc)

    # T212 L2: apply side normalization (same fix as the strict matcher
    # — see _norm_side comment). Pre-T212 this was case-sensitive and
    # didn't bridge BUY/long vocabularies, so the Phase 3 manual-link UI
    # would silently return [] for the production cross-vocabulary case.
    # The query selects by ticker only and filters side in Python.
    # Loose-tolerance behavior (5% drift / 168h window) is unchanged —
    # manual-link UI intentionally shows near-misses.
    side_canonical = _norm_side(side)

    # P8.T5: candidates are LIVE calcs only — status IN ('active','released'),
    # matching the strict matcher's own candidate rule (spec §4.3). This drops
    # expired/cancelled/superseded leakage AND fixes a latent bug: the old
    # "exclude any calc_id present in orders" guard wrongly EXCLUDED released
    # calcs (whose CANCELLED order still carries calc_id), so a replacement
    # order's near-match to a released calc never surfaced in the manual-link
    # queue. A linked (matched) calc is excluded by the status filter instead
    # (linking flips active|released -> matched, so a live candidate can't be
    # linked to a working order).
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except Exception:
        return []
    try:
        rows = conn.execute(
            "SELECT calc_id, side, effective_entry, tp_price, sl_price, timestamp, status "
            "FROM pre_trade_log "
            "WHERE ticker = ? AND timestamp >= ? AND account_id = ? "
            "AND calc_id IS NOT NULL AND status IN ('active', 'released') "
            "ORDER BY timestamp DESC",
            (ticker, cutoff, account_id),
        ).fetchall()
    except Exception:
        conn.close()
        return []

    candidates: List[CandidateCalc] = []
    for row in rows:
        cid = row["calc_id"]
        if not cid:
            continue
        if _norm_side(row["side"]) != side_canonical:
            continue  # side mismatch — not a candidate

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

        # P8.T5: surface the calc's status; a 'released' candidate is a
        # replacement scenario — look up the cancelled order it replaces.
        cstatus = row["status"] or "active"
        replaced = _cancelled_order_for_calc(conn, cid, account_id) if cstatus == "released" else None
        candidates.append(CandidateCalc(
            calc_id=cid, ticker=ticker, side=side,
            effective_entry=eff, entry_drift_pct=round(e_drift, 6), entry_match=e_match,
            tp_price=tp, tp_drift_pct=round(t_drift, 6), tp_match=t_match,
            sl_price=sl, sl_drift_pct=round(s_drift, 6), sl_match=s_match,
            timestamp=row["timestamp"], age_hours=round(age_h, 1),
            status=cstatus, replaced_order=replaced,
        ))

    conn.close()
    candidates.sort(key=lambda c: (
        -(int(c.entry_match) + int(c.tp_match) + int(c.sl_match)),
        c.entry_drift_pct + c.tp_drift_pct + c.sl_drift_pct,
        c.timestamp,
    ))
    return candidates
