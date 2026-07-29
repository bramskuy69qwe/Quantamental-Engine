"""
Canonical "fills → position records" helper (Phase 0.0.1, T182).

Establishes a single source of truth for grouping fills into closed
position rows. Replaces three duplicated grouping paths that diverged:

1. ``order_manager._build_close_row_for_fill`` (live close-row builder,
   uses the broken ``get_position_fills`` ``(symbol, direction)``
   fallback when ``terminal_position_id`` is empty)
2. ``db_orders.exchange_history_backfill`` (ad-hoc
   ``(symbol, direction, open_time)`` grouping + synthetic fill
   duplication — T178 Layers 1 & 3)
3. One-off rebuild scripts (the T177 dryrun draft and the future
   ``scripts/rebuild_closed_positions.py``)

T178 audit reference:
``docs/audits/2026-05-25-t178-fills-data-quality.md`` — five corruption
layers identified in the existing fills + closed_positions data.

Grouping rule (no pos_id required):
  Walk fills chronologically, per-``(account_id, symbol, direction)``.
  Track net open quantity. A logical position OPENS on the first
  non-close fill when net qty was 0. Subsequent fills ADD
  (``is_close=0``) or REDUCE (``is_close=1``) the qty. When qty
  returns to 0 (within ``_QTY_EPS``), the position is CLOSED and a
  ``PositionRecord`` is emitted. A new position can then open on the
  next non-close fill.

Why this is correct: fills represent actual order executions in
chronological order. A position's lifecycle is fully defined by its
fills — opens add, closes subtract, until qty hits 0. Cross-position
contamination is impossible because each position's fills are
contiguous in the qty-tracked stream (a new position can't open
while qty > 0 for the same symbol/direction in one-way mode).

Caveats:
  - Hedge mode (LONG + SHORT positions simultaneously on the same
    symbol) is handled because we key on (account_id, symbol,
    direction). The LONG and SHORT positions have independent qty
    tracks.
  - If qty goes NEGATIVE (overfill — close qty > open qty), we
    flush the current position at qty=0 and log a warning. The
    reversal-split fix (Phase 0.0.4) will pre-process such events
    into two separate fill rows before they reach this helper, so
    this branch is a defensive fallback for pre-0.0.4 historical
    data.
  - Fills MUST be sorted chronologically AND deduplicated by the
    ``is_same_fill`` rule before being fed in. Duplicate fills
    (e.g., WS + REST or backfill-synthetic reporting the same trade)
    would double-count qty. Phase 0.0.2 stops new dups at the write
    path; Phase 0.0.3's ``scripts/dedup_fills.py`` cleans historical
    dups.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple, TypedDict

# R4 (LB-D4): the close-row calc rule delegates to the identity owner's
# §3.2 selection helper (single source of truth — the same rule the live
# builder, close-fill stamp, and live enrichment converge on).
from core.position_identity import _most_contributing_calc_id

log = logging.getLogger("position_grouping")

# Floating-point tolerance for "qty has returned to zero". Crypto futures
# typically use 3-8 decimal qty precision; 1e-6 is safely below.
_QTY_EPS = 1e-6

# ── Fill-dedup tolerance constants ──────────────────────────────────────
#
# Used by ``is_same_fill`` (and downstream Phase 0.0.2 dedup guard +
# Phase 0.0.3 dedup script) to decide whether two fill rows describe the
# same physical trade execution.
#
# Why 2 seconds: synthetic fills produced by ``exchange_history_backfill``
# carry a slightly different timestamp than the real WS/REST fill for the
# same trade (the synthetic is reconstructed from REALIZED_PNL accounting,
# which may use the order's close timestamp rather than the fill's). T178
# observed real Binance matching-engine splits (single client order →
# multiple matching-engine fills) using IDENTICAL timestamps, so 2s is
# wide enough to catch dual-write skew without collapsing legitimate
# multi-fill orders.
#
# Why price tolerance is exact (0.0): both sources should report
# identical prices since they come from the same trade execution. Any
# divergence indicates the fills are genuinely different.
FILL_DEDUP_TOLERANCE_MS = 2000
FILL_DEDUP_PRICE_TOLERANCE_PCT = 0.0


class PositionRecord(TypedDict, total=False):
    """Closed-position row shape emitted by ``group_fills_into_positions``.

    Matches the keys read by ``db_orders.insert_closed_position`` via
    its ``row.get(...)`` calls. ``total=False`` so callers can pass a
    subset and let ``insert_closed_position``'s ``.get`` defaults fill
    the rest — but in practice this helper populates every field with
    a deterministic value.

    Keep in sync with the ``closed_positions`` schema in
    ``core/database.py`` and the INSERT column list in
    ``core/db_orders.py:insert_closed_position``.

    MFE/MAE are intentionally left at 0.0 here — the reconciler runs
    after rebuild (``backfill_completed=0`` triggers it) and computes
    those with T175's gross-PnL floor applied. Don't try to re-derive
    MFE/MAE inside this helper; the reconciler is the canonical owner.
    """
    account_id: int
    exchange_position_id: str
    terminal_position_id: str
    symbol: str
    direction: str
    quantity: float
    entry_price: float
    exit_price: float
    entry_time_ms: int
    exit_time_ms: int
    realized_pnl: float
    total_fees: float
    net_pnl: float
    funding_fees: float
    hold_time_ms: int
    exit_reason: str
    model_name: str
    source: str
    calc_id: str
    mfe: float                  # 0.0 placeholder until the reconciler runs —
    mae: float                  # backfill_completed is the "measured?" bit (P5-R4)
    backfill_completed: int


def is_same_fill(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Return True if two fill rows describe the same physical trade execution.

    Matches by:
      - ``symbol``, ``side``, ``is_close``, ``quantity``, ``direction``: exact
      - ``timestamp_ms``: within ``FILL_DEDUP_TOLERANCE_MS``
      - ``price``: within ``FILL_DEDUP_PRICE_TOLERANCE_PCT`` (currently exact)

    Note: ``side`` (BUY/SELL) and ``direction`` (LONG/SHORT) are both
    compared because the close of a SHORT position is a BUY-side fill;
    matching on side alone would let a SHORT close collide with a LONG
    open at the same price/time/qty. Belt-and-braces.

    Quantity comparison uses ``_QTY_EPS`` to absorb floating-point
    representation drift from the dual-write JSON round-trip — Binance's
    REST and WS payloads encode quantities as decimal strings, and the
    json parser's float conversion can produce values that differ by
    one ULP.
    """
    if a.get("symbol", "") != b.get("symbol", ""):
        return False
    if (a.get("side", "") or "").upper() != (b.get("side", "") or "").upper():
        return False
    if (a.get("direction", "") or "").upper() != (b.get("direction", "") or "").upper():
        return False
    if bool(a.get("is_close", 0)) != bool(b.get("is_close", 0)):
        return False

    qty_a = float(a.get("quantity", 0) or 0)
    qty_b = float(b.get("quantity", 0) or 0)
    if abs(qty_a - qty_b) > _QTY_EPS:
        return False

    ts_a = int(a.get("timestamp_ms", 0) or 0)
    ts_b = int(b.get("timestamp_ms", 0) or 0)
    if abs(ts_a - ts_b) > FILL_DEDUP_TOLERANCE_MS:
        return False

    price_a = float(a.get("price", 0) or 0)
    price_b = float(b.get("price", 0) or 0)
    if FILL_DEDUP_PRICE_TOLERANCE_PCT <= 0.0:
        if price_a != price_b:
            return False
    else:
        denom = price_b if price_b else (price_a if price_a else 1.0)
        if abs(price_a - price_b) / abs(denom) > FILL_DEDUP_PRICE_TOLERANCE_PCT:
            return False

    return True


def group_fills_into_positions(
    fills: Iterable[Dict[str, Any]],
    fee_rate_fallback: float = 0.0,
    attribution_out: Optional[Dict[str, List[int]]] = None,
) -> List[PositionRecord]:
    """Group chronologically-sorted, deduplicated fills into ``PositionRecord``s.

    Open-but-not-closed positions at the end of the input stream are
    NOT emitted (they're still live; ``closed_positions`` tracks closed
    positions only).

    Caller is responsible for:
      - sorting ``fills`` chronologically (``timestamp_ms ASC, id ASC``)
      - deduplicating via ``is_same_fill`` BEFORE passing in (this helper
        does not dedup — it walks the stream as authoritative)

    Args:
        fills: iterable of fill row dicts (column-name keys, matching
            the ``fills`` table schema in ``core/database.py``).
        fee_rate_fallback: if a position's fills all have ``fee=0``,
            estimate ``total_fees`` as ``fee_rate_fallback * notional *
            2`` (both sides). Set to 0.0 to disable. Used by the rebuild
            script when historical fills predate fee-recording.
        attribution_out (Phase 0.0.6 follow-up): if a mutable dict is
            provided, the helper writes a mapping of each emitted
            PositionRecord's ``terminal_position_id`` → list of
            contributing fill ``id`` values (sqlite row ids from the
            input fill dicts). Used by ``rebuild_closed_positions.py``
            and ``synth_legacy_open_fills.py`` to UPDATE fills'
            ``terminal_position_id`` so the strict ``get_position_fills``
            lookup (api/routes_orders.py:204) returns the fills on the
            Position History drawer. Fills missing an ``id`` key are
            skipped silently (synth in-memory fills that aren't yet in
            the DB have no id — they get a real id once persisted).

    Returns:
        List of ``PositionRecord``s, one per closed logical position,
        in close-time order.
    """
    rows: List[PositionRecord] = []
    # state per (account_id, symbol, direction): accumulating opens + closes
    state: Dict[Tuple[int, str, str], Dict[str, Any]] = {}

    for f in fills:
        account_id = f.get("account_id", 1)
        symbol = f.get("symbol", "")
        direction = f.get("direction", "")
        if not symbol or not direction:
            log.warning(
                "position_grouping: skipping fill missing symbol/direction: %r",
                f.get("exchange_fill_id", "<no-id>"),
            )
            continue
        key = (account_id, symbol, direction)
        st = state.get(key)
        is_close = bool(f.get("is_close", 0))
        qty = float(f.get("quantity", 0) or 0)

        if qty <= 0:
            continue   # ignore zero-qty fills (rare data anomaly)

        if st is None:
            # New position opens (regardless of is_close — defensive: if
            # the first fill we see is a close, the prior opens are
            # missing from the input, so treat this as a noise event).
            if is_close:
                log.debug(
                    "position_grouping: closing fill with no prior open "
                    "(symbol=%s, dir=%s, qty=%s) — likely fills outside "
                    "input window; skipping",
                    symbol, direction, qty,
                )
                continue
            state[key] = {
                "account_id": account_id,
                "open_qty": qty,
                "opens": [f],
                "closes": [],
            }
            continue

        if is_close:
            st["closes"].append(f)
            st["open_qty"] -= qty
            if st["open_qty"] <= _QTY_EPS:
                # Position closed (or over-closed). Emit row.
                record = _build_row(key, st, fee_rate_fallback)
                rows.append(record)
                if attribution_out is not None:
                    fill_ids = [
                        int(of["id"]) for of in st["opens"]
                        if of.get("id") is not None
                    ] + [
                        int(cf["id"]) for cf in st["closes"]
                        if cf.get("id") is not None
                    ]
                    attribution_out[record["terminal_position_id"]] = fill_ids
                if st["open_qty"] < -_QTY_EPS:
                    # Over-closed: residual qty would conceptually open an
                    # opposite-direction position. In one-way mode this
                    # shouldn't happen; in hedge mode the opposite
                    # direction has its own state key. The reversal-split
                    # fix (Phase 0.0.4) will pre-process such events into
                    # two fill rows. Log + reset here as a defensive
                    # fallback for pre-0.0.4 historical data.
                    log.warning(
                        "position_grouping: over-close on %s %s — "
                        "residual qty %.6f after close; resetting state. "
                        "This typically means a fill was missed or the "
                        "data is duplicated. Review fills around %s.",
                        symbol, direction, st["open_qty"],
                        f.get("timestamp_ms"),
                    )
                del state[key]
        else:
            # Additional open (averaging in)
            st["opens"].append(f)
            st["open_qty"] += qty

    return rows


def _build_row(
    key: Tuple[int, str, str],
    st: Dict[str, Any],
    fee_rate_fallback: float,
) -> PositionRecord:
    """Build a ``PositionRecord`` from accumulated opens + closes."""
    account_id, symbol, direction = key
    opens: List[Dict[str, Any]] = st["opens"]
    closes: List[Dict[str, Any]] = st["closes"]

    total_open_qty = sum(float(f.get("quantity", 0) or 0) for f in opens)
    total_close_qty = sum(float(f.get("quantity", 0) or 0) for f in closes)

    entry_price = (
        sum(float(f["price"]) * float(f["quantity"]) for f in opens) / total_open_qty
        if total_open_qty else 0.0
    )
    exit_price = (
        sum(float(f["price"]) * float(f["quantity"]) for f in closes) / total_close_qty
        if total_close_qty else 0.0
    )
    entry_time_ms = min(int(f.get("timestamp_ms", 0) or 0) for f in opens)
    exit_time_ms = max(int(f.get("timestamp_ms", 0) or 0) for f in closes) if closes else 0

    # Fees from the fill records (each fill carries its own fee)
    total_fees = (
        sum(float(f.get("fee", 0) or 0) for f in opens)
        + sum(float(f.get("fee", 0) or 0) for f in closes)
    )
    # If any fill is missing fee, fall back to fee_rate_fallback × notional
    if total_fees == 0 and fee_rate_fallback > 0:
        notional = total_close_qty * exit_price
        total_fees = fee_rate_fallback * notional * 2  # both sides

    # Realized PnL from close fills (each carries its own realized_pnl when
    # the WS/REST recorder set it). Fall back to math if not provided.
    realized_pnl = sum(float(f.get("realized_pnl", 0) or 0) for f in closes)
    if realized_pnl == 0 and total_close_qty > 0 and entry_price > 0:
        # Gross PnL math fallback
        if direction == "LONG":
            realized_pnl = (exit_price - entry_price) * total_close_qty
        else:  # SHORT
            realized_pnl = (entry_price - exit_price) * total_close_qty

    net_pnl = realized_pnl - total_fees

    # calc_id via the identity owner's §3.2 rule (R4 / LB-D4): the
    # most-contributing calc across the opening fills — per-calc SUMMED
    # qty, tie-break earliest fill — the SAME selection rule the live
    # close-row builder applies to junction rows (T2.6). Pre-R4 this
    # grouper used "earliest opening fill with a calc_id" (the T234
    # reconstruction approximation), so rebuilding a scale-in whose
    # larger calc wasn't first flipped calc_id back to earliest — a
    # consumer re-deriving identity with a DIFFERENT rule (LB-D4). The
    # EVIDENCE still differs by construction (fills here vs junction
    # rows live — this offline grouper has no positions_calcs access),
    # but junction contributed_qty IS SUM(fill qty) per calc, so the two
    # converge whenever the opening fills carry their calc stamps.
    # lifecycle_id remains NULL on rebuilt rows (attribution-only drift;
    # PnL/qty/prices are recomputed correctly from fills) — the rebuild
    # lane's preserve pass re-supplies it for same-tpid re-rebuilds.
    # ``opens`` is in chronological walk order, satisfying the helper's
    # first_fill_ts-ASC precondition (ties → earliest calc).
    calc_id = _most_contributing_calc_id(
        [(f.get("calc_id") or "", float(f.get("quantity", 0) or 0))
         for f in opens]
    ) or ""

    return {
        "account_id":           account_id,
        "exchange_position_id": "",  # not populated from fills alone
        "terminal_position_id": _synthetic_pos_id(symbol, direction, entry_time_ms),
        "symbol":               symbol,
        "direction":            direction,
        "quantity":             total_close_qty,
        "entry_price":          entry_price,
        "exit_price":           exit_price,
        "entry_time_ms":        entry_time_ms,
        "exit_time_ms":         exit_time_ms,
        "realized_pnl":         realized_pnl,
        "total_fees":           total_fees,
        "net_pnl":              net_pnl,
        "funding_fees":         0.0,
        "hold_time_ms":         max(0, exit_time_ms - entry_time_ms),
        # T2.7: spec §3.4 enum. Fills-only rebuild has no order-type metadata
        # to distinguish TP/SL, so it defaults to MANUAL_OTHER (was legacy
        # "manual") — consistent with the live close path's enum + the P0.T5
        # backfill (manual→MANUAL_OTHER).
        "exit_reason":          "MANUAL_OTHER",
        # v2.7 5.4: left empty HERE (this builder is pure, no DB access) —
        # insert_closed_position resolves model_id + model_name from
        # calc_id at write time (the choke-point enrichment), so rebuilt
        # rows carry model attribution when their calc is tagged.
        "model_name":           "",
        "source":               "rebuilt_from_fills",
        "calc_id":              calc_id,
        # MFE/MAE left to reconciler (T175 floor applies there).
        # backfill_completed=0 so the reconciler picks up rebuilt rows.
        # P5-R4: 0.0 here is a SCHEMA-CONSTRAINED placeholder (the columns
        # are NOT NULL DEFAULT 0) — "measured or not" travels on
        # backfill_completed, and the JSON emitters null the pair out for
        # unmeasured rows so the display renders an em-dash, never a
        # fabricated zero-width bar.
        "mfe":                  0.0,
        "mae":                  0.0,
        "backfill_completed":   0,
    }


def find_opens_for_position_close_at(
    fills: Iterable[Dict[str, Any]],
    *,
    account_id: int,
    symbol: str,
    direction: str,
    close_ts_ms: int,
) -> List[Dict[str, Any]]:
    """Walk fills chronologically and return the opens for the position
    that is open AT (or closes AT) ``close_ts_ms`` for the given
    ``(account_id, symbol, direction)``.

    Used by ``order_manager._build_close_row_for_fill`` (Phase 0.0.5) when
    ``terminal_position_id`` is empty — replaces the broken
    ``get_position_fills`` ``(COALESCE='' AND symbol=? AND direction=?)``
    fallback that returned opens from MULTIPLE distinct positions over
    time (T178 Layer 3 cross-position contamination).

    Algorithm: per-(account, symbol, direction) chronological walk.
    Track net open qty. Snapshot opens whenever the position closes
    (qty returns to zero). Return:
      - the CURRENT opens if the position is still partially open at
        ``close_ts_ms`` (partial-close scenario where qty hasn't yet
        reached zero); OR
      - the LAST snapshot's opens if the position just closed (qty
        reached zero) at or before ``close_ts_ms``.

    The caller's close fill should be in ``fills``. Walks all fills with
    ``timestamp_ms <= close_ts_ms`` so partial-close intermediate
    closes are accounted for.

    Args:
        fills: all fills (need not be sorted; helper sorts internally).
        account_id, symbol, direction: position scope.
        close_ts_ms: the target close fill's timestamp.

    Returns:
        List of opening-fill dicts (``is_close == 0``) belonging to the
        position whose close is at ``close_ts_ms``. Returns ``[]`` when
        no opens match (e.g., open fills are outside the input window).
    """
    sorted_fills = sorted(
        fills,
        key=lambda f: (
            int(f.get("timestamp_ms", 0) or 0),
            int(f.get("id", 0) or 0),
        ),
    )

    current_opens: List[Dict[str, Any]] = []
    last_closed_opens: List[Dict[str, Any]] = []
    qty = 0.0

    for f in sorted_fills:
        if (
            f.get("account_id") != account_id
            or f.get("symbol") != symbol
            or f.get("direction") != direction
        ):
            continue
        ts = int(f.get("timestamp_ms", 0) or 0)
        if ts > close_ts_ms:
            break
        q = float(f.get("quantity", 0) or 0)
        if q <= 0:
            continue
        if not bool(f.get("is_close", 0)):
            if qty <= _QTY_EPS:
                current_opens = [f]
            else:
                current_opens.append(f)
            qty += q
        else:
            qty -= q
            if qty <= _QTY_EPS:
                # Position closed — snapshot opens and reset.
                last_closed_opens = list(current_opens)
                current_opens = []
                qty = 0.0

    # If qty > 0 at end, the position is still open at close_ts_ms (a
    # partial close has fired but the position isn't fully closed yet).
    # Return the current accumulating opens — they're the right answer
    # for fee-allocation in the multi-fill partial-close scenario.
    if qty > _QTY_EPS:
        return current_opens
    return last_closed_opens


def _synthetic_pos_id(symbol: str, direction: str, entry_time_ms: int) -> str:
    """Deterministic synthetic position ID — same logical position
    always gets the same ID across reruns. Format mirrors the
    exchange-history backfill convention (``bf:...``; see
    synth_legacy_open_fills.ORPHAN_TPID_PREFIX — the db_orders line
    once cited here moved). Distinguishable as ``rebuilt:`` for
    traceability. Both namespaces are structurally FENCED from the
    identity owner's migration + lifecycle-sweep passes (R5)."""
    return f"rebuilt:{symbol}:{direction}:{entry_time_ms}"


def mint_terminal_position_id(
    *, source: str, symbol: str, direction: str, entry_ms: int
) -> str:
    """Deterministic, BROKER-AGNOSTIC terminal_position_id for a live
    position whose upstream feed supplies no venue position id (e.g. the
    Binance one-way observe-only WS path). Debug session 2026-06-07.

    Format ``{venue}:{symbol}:{direction}:{entry_ms}`` mirrors the
    ``rebuilt:`` / ``bf:`` conventions so a live-minted id sits in the same
    family and is distinguishable by prefix. The venue prefix is the first
    token of ``source`` lowercased (``"Binance"`` / ``"binance_ws"`` ->
    ``"binance"``; ``""`` -> ``"live"``) — NEVER a hardcoded literal, so any
    adapter without a venue id gets a coherent prefix for free.

    Deterministic: the same (source, symbol, direction, entry_ms) always
    yields the same id, so WS re-delivery / duplicate ACCOUNT_UPDATE events
    dedup to one id (NOT uuid4 — the tpid IS the position key). ``entry_ms``
    MUST be the position's first-open time (stable for the position's life,
    distinct across a close->reopen on the same slot) to preserve the
    one-tpid-per-position-instance invariant relied on by
    ``order_manager._link_position_calc_on_open``.

    SPLIT-BRAIN CAVEAT: the offline rebuild script synthesizes
    ``rebuilt:{symbol}:{direction}:{first_fill_ms}`` — a DIFFERENT prefix AND a
    different timestamp basis (first-fill vs ACCOUNT_UPDATE event time) than this
    live mint. They don't reconcile, but they don't collide either: the rebuild
    only fills EMPTY tpids (``COALESCE(...,'')=''``) so it skips live-minted rows.
    Don't re-run rebuild_closed_positions over symbols that already carry live ids
    expecting it to match them.
    """
    prefix = (source or "").strip().lower().replace(":", "_").split("_")[0] or "live"
    return f"{prefix}:{symbol}:{direction}:{entry_ms}"
