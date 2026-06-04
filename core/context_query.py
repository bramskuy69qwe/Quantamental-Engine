"""Reverse-query graph assembly (Phase 7.1, spec §11.1).

Assembles the full causal graph for one calc or one trade lifecycle so a
downstream model (or the audit UI) can fetch the whole chain in one call:

    calc → orders → fills → amendments → junction → position → funding → events

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
    db: Any, position_id: Optional[str],
) -> Tuple[Optional[str], Optional[Dict[str, Any]], Dict[str, Any]]:
    """Resolve a position_id to (state, position_dict, deviations). Prefers a
    LIVE open position (in-memory PositionInfo); else the most-recent closed
    row; else (None, None, {})."""
    if not position_id:
        return None, None, {}
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
        "position": position,
        "position_state": state,          # "open" | "closed" | None
        "funding_events": funding,
        "deviations": deviations,
        "events": events,
    }


async def assemble_lifecycle_context(
    db: Any, lifecycle_id: str,
) -> Optional[Dict[str, Any]]:
    """Single-key audit graph for one trade lifecycle (spec §3.5 / §11.1).
    Returns ``None`` if no junction rows carry this lifecycle_id (404).

    A lifecycle aggregates all contributing calcs (scale-in), so the payload
    carries ``calcs`` (plural) + ``closed_positions`` (the per-partial rows);
    otherwise it mirrors the calc graph. orders/fills/closed are keyed directly
    on ``lifecycle_id`` (the single-key audit query); amendments + events are
    gathered per contributing calc (those tables carry calc_id, and trade_events
    has no lifecycle_id column — spec §3.5)."""
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

    amendments: List[Dict[str, Any]] = []
    for cid in calc_ids:
        amendments.extend(await db.get_calc_amendments(cid))
    amendments.sort(key=lambda a: (a.get("ts_ms") or 0, a.get("id") or 0))

    position_ids = _ordered_unique([j.get("position_id") for j in junction])
    funding: List[Dict[str, Any]] = []
    for pid in position_ids:
        funding.extend(await db.get_position_funding_events(pid))

    state, position, deviations = await _resolve_position(db, _primary_position_id(junction))
    events = await _events_for(account_id, calc_ids)

    return {
        "lifecycle_id": lifecycle_id,
        "calcs": calcs,
        "orders": orders,
        "fills": fills,
        "amendments": amendments,
        "positions_calcs": junction,
        "position": position,
        "position_state": state,          # "open" | "closed" | None
        "closed_positions": closed_positions,
        "funding_events": funding,
        "deviations": deviations,
        "events": events,
    }
