"""Reverse-query graph assembly (Phase 7.1, spec §11.1).

Assembles the full causal graph for one calc or one trade lifecycle so a
downstream model (or the audit UI) can fetch the whole chain in one call:

    calc → orders → fills → amendments → junction → position → funding →
    events → match_audit (the per-criterion matcher decision trace)

**Cross-DB (spec §12.7).** The calc-linkage tables (pre_trade_log, orders,
fills, closed_positions, positions_calcs, order_amendments, funding_events)
live in ``config.DB_PATH`` (the ``db`` singleton, async aiosqlite). But
``trade_events`` live in the PER-ACCOUNT DB (``core.trade_event_log``, sync
sqlite3). The two are joined HERE in Python by ``calc_id`` — never SQL across
files. The sync ``query_trade_events`` read is dispatched via
``asyncio.to_thread`` so it never blocks the event loop, and is best-effort
(a cross-DB fault yields ``events: []`` rather than failing the whole graph).

``db`` is passed in (not the module singleton) so the assembly is unit-testable
against an in-memory ``DatabaseManager`` without touching global state; the
endpoints pass ``core.database.db``.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from core.state import app_state

log = logging.getLogger("context_query")


def json_safe(obj: Any) -> Any:
    """Recursively replace non-finite floats (``inf`` / ``-inf`` / ``nan``) with
    ``None`` so the JSON layer can't 500. Starlette's ``JSONResponse`` renders
    with ``allow_nan=False``, and SQLite round-trips a ``REAL`` ``inf`` as a
    Python ``inf`` — so a single adapter-ingested ``inf`` in any ``SELECT *``
    column (price, mark_price, fee, …) would otherwise raise ``ValueError`` and
    turn that calc/lifecycle into a permanent 500. (NaN written to a REAL is
    stored as NULL by SQLite, so it's already benign; we cover it anyway.)
    Finite floats and all non-float values pass through unchanged, so the
    assembled values are untouched in the normal case."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj

# The "deviations" object (spec §11.1: "computed from amendments and planned vs
# actual") is the set of close-time deltas already computed + persisted on the
# closed_positions row (T2.5 / P4.T2 / P4.T5) — surfaced, NOT recomputed here.
_DEVIATION_COLS: Tuple[str, ...] = (
    "entry_px_delta_pct", "size_delta_pct", "tp_drift_pct", "sl_drift_pct",
    "exit_vs_target_pct", "realized_r", "planned_r", "cumulative_amendment_count",
)
# Live deviation surface for an OPEN position (T2.12 / P4.T3 store these on
# PositionInfo): the size delta + amendment count + computed badge.
_OPEN_DEVIATION_FIELDS: Tuple[str, ...] = (
    "size_delta_pct", "amendment_count", "deviation_badge",
)


def _ordered_unique(values: List[Optional[str]]) -> List[str]:
    """Order-preserving de-dup, dropping falsy entries."""
    seen: set = set()
    out: List[str] = []
    for v in values:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _open_position_dict(position_id: str) -> Optional[Dict[str, Any]]:
    """Serialize the live ``PositionInfo`` for ``position_id`` (the in-memory
    open position), or ``None`` if no open position matches. ``PositionInfo`` is
    a plain dataclass of primitives + ``List[str]`` → JSON-safe via ``asdict``.
    """
    if not position_id:
        return None
    for p in app_state.positions:
        if getattr(p, "position_id", None) == position_id:
            try:
                return dataclasses.asdict(p)
            except TypeError:
                return {k: v for k, v in vars(p).items()}
    return None


def _primary_position_id(junction: List[Dict[str, Any]]) -> Optional[str]:
    """The position this calc/lifecycle most contributed to, by SUM(contributed_qty)
    per position_id (tie-break: earliest first_fill_ts) — the §3.2 most-contributing
    basis, mirroring core.order_manager._most_contributing_calc_id but pivoted on
    position_id. Used to resolve the single ``position`` field; the full junction
    is returned separately for multi-position calcs."""
    sums: Dict[str, float] = {}
    earliest: Dict[str, int] = {}
    for j in junction:
        pid = j.get("position_id")
        if not pid:
            continue
        sums[pid] = sums.get(pid, 0.0) + float(j.get("contributed_qty") or 0.0)
        ff = int(j.get("first_fill_ts") or 0)
        if pid not in earliest or ff < earliest[pid]:
            earliest[pid] = ff
    if not sums:
        return None
    # Higher summed qty wins; tie → earlier first_fill_ts (smaller ts).
    return max(sums, key=lambda pid: (sums[pid], -earliest[pid]))


def _deviations(state: Optional[str], position: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not position:
        return {}
    if state == "closed":
        return {c: position.get(c) for c in _DEVIATION_COLS if c in position}
    if state == "open":
        return {f: position[f] for f in _OPEN_DEVIATION_FIELDS if f in position}
    return {}


async def _resolve_position(
    db: Any, position_id: Optional[str], *, prefer_open: bool = True,
) -> Tuple[Optional[str], Optional[Dict[str, Any]], Dict[str, Any]]:
    """Resolve a position_id to (state, position_dict, deviations).

    ``prefer_open=True`` (the live /context default) prefers a LIVE open
    PositionInfo (from in-memory app_state); else the most-recent closed row;
    else (None, None, {}).

    ``prefer_open=False`` (the SIGNED audit export, P7 holistic-audit fix) SKIPS
    the live app_state lookup and resolves only the sealed closed row — so a
    compliance artifact is DB-reproducible (its signature can be recomputed from
    the DB alone, not app_state-at-export-time) and never reflects the live,
    mutating state of a still-partially-open position (a multi-TP partial close
    writes a closed_positions row WHILE the position is still open)."""
    if not position_id:
        return None, None, {}
    if prefer_open:
        op = _open_position_dict(position_id)
        if op is not None:
            return "open", op, _deviations("open", op)
    closed = await db.get_closed_positions_by_position_id(position_id)
    if closed:
        return "closed", closed[0], _deviations("closed", closed[0])
    return None, None, {}


def _fetch_trade_events_sync(
    account_id: int, calc_ids: List[str],
) -> List[Dict[str, Any]]:
    """Per-account ``trade_events`` for the given calc_ids, merged + sorted by
    timestamp ascending. Best-effort: a cross-DB read fault is swallowed.
    SYNC — the caller dispatches this via ``asyncio.to_thread``."""
    from core.trade_event_log import query_trade_events

    out: List[Dict[str, Any]] = []
    for cid in calc_ids:
        try:
            rows, _ = query_trade_events(account_id=account_id, calc_id=cid, limit=1000)
            out.extend(rows)
        except Exception:
            log.debug("trade_events read failed for calc_id=%s", cid, exc_info=True)
    out.sort(key=lambda r: r.get("timestamp") or "")
    return out


async def _events_for(account_id: Optional[int], calc_ids: List[str]) -> List[Dict[str, Any]]:
    if account_id is None or not calc_ids:
        return []
    return await asyncio.to_thread(_fetch_trade_events_sync, int(account_id), calc_ids)


def _first(rows: List[Dict[str, Any]], key: str) -> Any:
    """First non-None value of ``key`` across ``rows`` (insertion order), else None."""
    for r in rows:
        v = r.get(key)
        if v is not None:
            return v
    return None


async def _aggregate_tail(
    db: Any, *, calc_ids: List[str], position_ids: List[str],
    primary_position_id: Optional[str], account_id: Optional[int],
    prefer_open: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str],
           Optional[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]],
           List[Dict[str, Any]]]:
    """Shared tail for the lifecycle + position aggregate graphs: amendments
    (per contributing calc, merged + time-sorted), funding (per position), the
    resolved primary position + its deviations, the cross-DB events, and the
    per-criterion matcher decision trace (match_audit, per contributing calc,
    merged + deterministically ordered). ``prefer_open`` is threaded to
    :func:`_resolve_position` (False for the signed export → sealed,
    DB-reproducible). Returns ``(amendments, funding, position_state, position,
    deviations, events, match_audit)``."""
    amendments: List[Dict[str, Any]] = []
    for cid in calc_ids:
        amendments.extend(await db.get_calc_amendments(cid))
    amendments.sort(key=lambda a: (a.get("ts_ms") or 0, a.get("id") or 0))

    funding: List[Dict[str, Any]] = []
    for pid in position_ids:
        funding.extend(await db.get_position_funding_events(pid))

    # P7 follow-up #1: match_audit per contributing calc (scale-in → >1 calc),
    # merged + ordered (order_id, calc_id, id) for a stable cross-calc trace.
    match_audit: List[Dict[str, Any]] = []
    for cid in calc_ids:
        match_audit.extend(await db.get_calc_match_audit(cid))
    match_audit.sort(key=lambda m: (m.get("order_id") or 0, m.get("calc_id") or "", m.get("id") or 0))

    state, position, deviations = await _resolve_position(
        db, primary_position_id, prefer_open=prefer_open)
    events = await _events_for(account_id, calc_ids)
    return amendments, funding, state, position, deviations, events, match_audit


async def assemble_calc_context(db: Any, calc_id: str) -> Optional[Dict[str, Any]]:
    """Full causal graph for one calc (spec §11.1). Returns ``None`` if the
    calc does not exist (the endpoint maps that to 404).

    ``position`` is the calc's PRIMARY position (most-contributing, §3.2)
    resolved open-or-closed; the full per-position contribution detail is in
    ``positions_calcs`` (so a calc spanning >1 position loses nothing).
    """
    calc = await db.get_pretrade_log_by_calc_id(calc_id)
    if calc is None:
        return None

    account_id = calc.get("account_id")
    orders = await db.get_orders_by_calc_id(calc_id)
    fills = await db.get_fills_by_calc_id(calc_id)
    amendments = await db.get_calc_amendments(calc_id)
    junction = await db.get_calc_position_links(calc_id)
    # P7 follow-up #1: the per-criterion matcher decision trace ("why did
    # this calc match — or fail to match — which order"). Already ordered
    # (order_id, criterion, id). Empty for a calc no order was scored against.
    match_audit = await db.get_calc_match_audit(calc_id)

    position_ids = _ordered_unique([j.get("position_id") for j in junction])
    funding: List[Dict[str, Any]] = []
    for pid in position_ids:
        funding.extend(await db.get_position_funding_events(pid))

    state, position, deviations = await _resolve_position(db, _primary_position_id(junction))
    events = await _events_for(account_id, [calc_id])

    return {
        "calc": calc,
        "orders": orders,
        "fills": fills,
        "amendments": amendments,
        "positions_calcs": junction,
        "match_audit": match_audit,
        "position": position,
        "position_state": state,          # "open" | "closed" | None
        "funding_events": funding,
        "deviations": deviations,
        "events": events,
    }


async def assemble_lifecycle_context(
    db: Any, lifecycle_id: str, *, prefer_open: bool = True,
) -> Optional[Dict[str, Any]]:
    """Single-key audit graph for one trade lifecycle (spec §3.5 / §11.1).
    Returns ``None`` if no junction rows carry this lifecycle_id (404).

    A lifecycle aggregates all contributing calcs (scale-in), so the payload
    carries ``calcs`` (plural) + ``closed_positions`` (the per-partial rows);
    otherwise it mirrors the calc graph. orders/fills/closed are keyed directly
    on ``lifecycle_id`` (the single-key audit query); amendments + events are
    gathered per contributing calc (those tables carry calc_id, and trade_events
    has no lifecycle_id column — spec §3.5).

    ``prefer_open=False`` seals ``position`` to the persisted closed row (the
    signed-export path → DB-reproducible); the default True path (the /context
    endpoint) prefers the live open position when one exists."""
    junction = await db.get_lifecycle_links(lifecycle_id)
    if not junction:
        return None

    calc_ids = _ordered_unique([j.get("calc_id") for j in junction])
    calcs_map = await db.get_pretrade_logs_by_calc_ids(calc_ids)
    calcs = [calcs_map[c] for c in calc_ids if c in calcs_map]
    account_id = next(
        (c.get("account_id") for c in calcs if c.get("account_id") is not None), None,
    )

    orders = await db.get_orders_by_lifecycle_id(lifecycle_id)
    fills = await db.get_fills_by_lifecycle_id(lifecycle_id)
    closed_positions = await db.get_closed_positions_by_lifecycle_id(lifecycle_id)

    position_ids = _ordered_unique([j.get("position_id") for j in junction])
    amendments, funding, state, position, deviations, events, match_audit = await _aggregate_tail(
        db, calc_ids=calc_ids, position_ids=position_ids,
        primary_position_id=_primary_position_id(junction), account_id=account_id,
        prefer_open=prefer_open,
    )

    return {
        "lifecycle_id": lifecycle_id,
        "calcs": calcs,
        "orders": orders,
        "fills": fills,
        "amendments": amendments,
        "positions_calcs": junction,
        "match_audit": match_audit,
        "position": position,
        "position_state": state,          # "open" | "closed" | None
        "closed_positions": closed_positions,
        "funding_events": funding,
        "deviations": deviations,
        "events": events,
    }


async def assemble_position_context(
    db: Any, position_id: str, *, prefer_open: bool = True,
) -> Optional[Dict[str, Any]]:
    """Full graph for one position (spec §11.1, keyed on ``terminal_position_id``).
    Returns ``None`` if the position has NO trace anywhere (no junction, orders,
    fills, closed rows, or live open position) → the endpoint maps that to 404.

    Account-scoping / tpid-invariant: ``position_id`` IS ``terminal_position_id``,
    which is unique per position instance (spec §3.2 tpid-uniqueness — Quantower
    emits one id per object; Binance leaves it empty so an empty/None id never
    reaches here as a query key). All reads below are keyed on it, so the graph
    is single-position by construction; no account filter is applied because the
    tpid already pins one account's one position.

    Aggregates all contributing calcs (like the lifecycle graph: ``calcs`` plural
    + ``closed_positions`` + the per-position ``deviations``) but keyed DIRECTLY
    on ``position_id``, so it also works for a junction-less / UNPLANNED position
    (which has orders/fills/closed by position_id but no calc attribution → empty
    ``calcs``/``amendments``/``events``, since those are calc-keyed). The
    ``position`` field resolves THIS position open-or-closed (not a
    most-contributing pick — the position is the query key).

    ``prefer_open`` (default True) prefers the live in-memory open position when
    one exists with this tpid — a position that re-opens under the same tpid would
    surface its OPEN snapshot on /context. ``prefer_open=False`` (the signed
    export) seals ``position`` to the persisted closed row so the sealed graph is
    DB-reproducible regardless of live app_state."""
    junction = await db.get_position_calc_links(position_id)
    orders = await db.get_orders_by_position_id(position_id)
    fills = await db.get_fills_by_position_id(position_id)
    closed_positions = await db.get_closed_positions_by_position_id(position_id)
    open_pos = _open_position_dict(position_id)
    if not junction and not orders and not fills and not closed_positions and open_pos is None:
        return None

    calc_ids = _ordered_unique([j.get("calc_id") for j in junction])
    calcs_map = await db.get_pretrade_logs_by_calc_ids(calc_ids)
    calcs = [calcs_map[c] for c in calc_ids if c in calcs_map]
    lifecycle_id = _first(junction, "lifecycle_id") or _first(closed_positions, "lifecycle_id")
    account_id = _first(list(junction) + list(closed_positions) + list(orders), "account_id")

    amendments, funding, state, position, deviations, events, match_audit = await _aggregate_tail(
        db, calc_ids=calc_ids, position_ids=[position_id],
        primary_position_id=position_id, account_id=account_id,
        prefer_open=prefer_open,
    )

    return {
        "position_id": position_id,
        "contributing_calc_ids": calc_ids,
        "lifecycle_id": lifecycle_id,
        "calcs": calcs,
        "orders": orders,
        "fills": fills,
        "amendments": amendments,
        "positions_calcs": junction,
        "match_audit": match_audit,
        "position": position,
        "position_state": state,          # "open" | "closed" | None
        "closed_positions": closed_positions,
        "funding_events": funding,
        "deviations": deviations,
        "events": events,
    }
