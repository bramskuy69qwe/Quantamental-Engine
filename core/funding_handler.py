"""Funding attribution — Phase 5 (funding + fees), P5.T2/T3.

On each funding poll (``schedulers._funding_refresh_loop``), venue
``FUNDING_FEE`` income rows are matched to the open position for their
symbol and written to ``funding_events`` — the ``position_id``-keyed source
of ``closed_positions.funding_fees`` at close (spec §3.1, §11[F]).

Design notes (verified against the shipped plumbing):

- **Dedup (P5.T3)** is by a *deterministic synthetic* ``venue_event_id`` =
  ``binance:funding:{account}:{symbol}:{ts}``. Binance's truly-unique per-row
  ``tranId`` is not surfaced by ``NormalizedIncome`` (and the ``tradeId`` that
  IS surfaced is ``"0"`` for FUNDING_FEE rows — useless as a key), so we key on
  the natural tuple. On the live **one-way** deployment a symbol has at most one
  funded position per settlement, so the tuple is collision-free; re-polling an
  overlapping window yields identical ids and dedups via
  ``UNIQUE(venue_event_id)`` (``insert_funding_event`` = INSERT OR IGNORE).
  **Hedge-mode limitation** (deferred, out of scope for one-way live): if a
  LONG and a SHORT leg of one symbol are funded at the same settlement ts, their
  two FUNDING_FEE rows collapse to one ``venue_event_id`` and one is dropped —
  the same collision class ``exchange_income.py`` (~L403-410) already hit for
  REALIZED_PNL and fixed by threading ``tradeId``. The fix when hedge mode is
  enabled is to map ``tranId`` through ``NormalizedIncome`` and fold it into
  the key.

- **Primary calc / lifecycle** come from the injected ``primary_calc_resolver``
  (in production ``OrderManager._position_primary_calc``) — the SINGLE shared
  §3.2 most-contributing rule (T240/R1). It returns ``(calc_id, lifecycle_id)``
  from the junction, populating both denormalized fields authoritatively. The
  open-position cache supplies only the ``symbol → terminal_position_id``
  attribution ("which position is open for this symbol right now").

- **OBSERVE-ONLY**: the engine observes funding, never places it. Funding for a
  symbol the engine can't key to ANY position — a position with an empty
  ``terminal_position_id`` (binance one-way path), or a symbol never traded — is
  counted/logged as an orphan and skipped, per spec §11[F]'s "optional orphan
  funding log". This is the same key-availability limitation the
  ``positions_calcs`` junction already carries.

- **Deferred-funding attribution (P6 reconcile, spec §5/§12.3)**: funding settles
  ~3x/day but the poll runs every ~5min, so funding that settles while a position
  is OPEN but is first polled only AFTER that position closed has no open position
  in the cache. Rather than orphan it (which would under-count
  ``closed_positions.funding_fees``/``net_pnl`` — the gap that left plan §5's
  "within $0.01 of venue" criterion unmet), the open-cache miss falls back to a
  closed-position window lookup (``find_closed_position_for_funding``): the
  settlement ts must fall inside a closed lifecycle's ``[entry, exit]`` window. On
  a hit the funding row is keyed to the now-closed tpid and that closed row's
  funding rollup is reconciled (``reconcile_closed_position_funding``). The
  ``calc_id``/``lifecycle_id`` come from the SEALED closed row — equal to the
  §3.2 junction primary at close (T2.6), one fewer query than re-resolving, and
  guarantees ``funding_events.calc_id`` matches ``closed_positions.calc_id``.
  **Known residual edge**: if a NEW position on the same symbol opened (and was
  caught by the open cache) before the poll, the old settlement's funding
  mis-attributes to the new position — the open path doesn't validate the
  settlement ts against the new position's entry. Rare (close+reopen within the
  ≤5min orphan window) and bounded; a future refinement can ts-validate the open
  path against the window primitive added here.

- **Two-views, not two-totals (audit note)**: funding ALSO flows through the
  pre-existing equity pipeline — ``exchange_income`` folds ``FUNDING_FEE`` into
  ``exchange_history.fee`` (``abs()``, FIFO-windowed) for the wallet/equity-curve
  view. ``funding_events`` here is the SEPARATE position-attributed view (signed,
  lifecycle-windowed) feeding ``closed_positions.funding_fees``/``net_pnl``. They
  populate DIFFERENT tables — there is NO double-count today — but they are two
  views of the same venue charges with opposite sign + different windowing; a
  future report must NOT sum ``closed_positions.net_pnl`` together with an
  ``exchange_history``-derived total, or it will double-count funding.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from core import correlation_log

log = logging.getLogger("exchange")

# (account_id, terminal_position_id) -> (calc_id, lifecycle_id)
PrimaryCalcResolver = Callable[
    [int, str], Awaitable[Tuple[Optional[str], Optional[str]]]
]


def synthetic_venue_event_id(account_id: int, symbol: str, ts_ms: int) -> str:
    """Deterministic dedup key for one Binance funding settlement.

    ``(account, symbol, settlement-ts)`` is a stable natural key (funding
    settles at most once per symbol per settlement), so re-polling the same
    window stays idempotent under ``UNIQUE(venue_event_id)``.
    """
    return f"binance:funding:{account_id}:{symbol}:{ts_ms}"


async def handle_funding_incomes(
    *,
    account_id: int,
    incomes: List[Dict],
    positions: List,  # List[PositionInfo]; only .ticker / .position_id read
    db,
    primary_calc_resolver: PrimaryCalcResolver,
) -> Dict[str, int]:
    """Attribute ``FUNDING_FEE`` income rows to open positions; write rows.

    ``incomes`` are the dicts returned by
    ``exchange_income.fetch_income_history`` (``{symbol, incomeType, income,
    time, ...}``). Returns ``{"written", "deduped", "orphan", "reconciled"}``
    counts (``reconciled`` = closed rows whose funding rollup was recomputed
    after a late funding row landed).
    """
    # symbol -> terminal_position_id, for open positions that HAVE a key.
    # binance one-way leaves position_id empty -> not attributable. First
    # match wins (hedge-mode two-sided positions on one symbol is a documented
    # limitation: the income feed carries no position side).
    sym_to_tpid: Dict[str, str] = {}
    for p in positions:
        tpid = getattr(p, "position_id", "") or ""
        sym = getattr(p, "ticker", "") or ""
        if tpid and sym and sym not in sym_to_tpid:
            sym_to_tpid[sym] = tpid

    resolved: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
    written = deduped = orphan = 0
    # Closed tpids that received a late funding row → reconcile after the loop
    # (a set so multiple late rows for one closed position reconcile once).
    closed_tpids_to_reconcile: set = set()

    # corr-tap: attr_funding_assign (CL.T3c, spec §5.6 — the ninth and last
    # attribution category). One envelope per FUNDING_FEE row processed:
    # ASSIGNED (resolution_path open_position | closed_window) or ORPHAN —
    # the orphan is a decision line, not an absence. Non-funding income rows
    # are a domain filter (no envelope — same class as the reenrich
    # non-child filter). dedup_key = venue_event_id (the §4.1 mechanism:
    # a re-polled settlement re-emits with the SAME key, `inserted:false`).
    # NB `inserted:false` covers dedup AND a swallowed write failure — the
    # paired db_write twin on the same chain distinguishes them.
    _fault_tpids: set = set()
    _n_processed = 0
    try:
        for row in incomes:
            if str(row.get("incomeType", "")).upper() != "FUNDING_FEE":
                continue
            _n_processed += 1
            symbol = row.get("symbol", "") or ""
            ts_ms = int(row.get("time", 0) or 0)
            _veid = synthetic_venue_event_id(account_id, symbol, ts_ms)
            tpid = sym_to_tpid.get(symbol, "")
            calc_id: Optional[str] = None
            lifecycle_id: Optional[str] = None
            _path = "open_position"
            _reconcile_queued = False
            if tpid:
                # Open-position fast path — primary calc/lifecycle from the
                # shared §3.2 most-contributing resolver (the junction).
                if tpid not in resolved:
                    try:
                        resolved[tpid] = await primary_calc_resolver(
                            account_id, tpid)
                    except Exception:
                        # Best-effort denormalization — a resolver fault must
                        # not drop the funding row (the close SUM keys on
                        # position_id).
                        resolved[tpid] = (None, None)
                        _fault_tpids.add(tpid)
                calc_id, lifecycle_id = resolved[tpid]
            else:
                # No open position → deferred-funding fallback: a closed
                # lifecycle whose [entry, exit] window contains the settlement
                # ts. calc_id / lifecycle_id come from the SEALED closed row
                # (== junction primary at close). No match → true orphan
                # (empty-tpid / never-traded).
                closed = await db.find_closed_position_for_funding(
                    account_id, symbol, ts_ms,
                )
                if closed and closed.get("position_id"):
                    _path = "closed_window"
                    tpid = closed["position_id"]
                    calc_id = closed.get("calc_id")
                    lifecycle_id = closed.get("lifecycle_id")
                    # Reconcile this closed row whether the write below
                    # inserts OR dedups — NOT gated on `inserted`. Self-heal:
                    # if an earlier poll wrote the row but its reconcile
                    # faulted (swallowed), the row dedups now yet still needs
                    # the rollup folded in. The reconcile is a no-op when
                    # already correct, so re-attempting on every dedup is free
                    # until last_seen_ms advances past this ts.
                    closed_tpids_to_reconcile.add(tpid)
                    _reconcile_queued = True
                else:
                    orphan += 1
                    log.debug(
                        "Orphan funding (no open/closed position for %s, "
                        "acct %s): amount=%s",
                        symbol, account_id, row.get("income"),
                    )
                    correlation_log.emit(
                        "funding_handler", "internal", "internal",
                        correlation_log.CAT_ATTR_FUNDING_ASSIGN,
                        {"outcome": "ORPHAN",
                         "reason": "no_open_or_closed_position",
                         "resolution_path": "orphan",
                         "amount": float(row.get("income", 0) or 0),
                         "ts_ms": ts_ms,
                         # identity tuple VERBATIM incl. "" (mandate 2)
                         "terminal_position_id": "", "calc_id": "",
                         "lifecycle_id": "", "exchange_order_id": "",
                         "dedup_key": _veid, "venue_event_id": _veid},
                        account_id=account_id, symbol=symbol or None,
                    )
                    continue
            inserted = await db.insert_funding_event({
                "position_id":    tpid,
                "calc_id":        calc_id,
                "account_id":     account_id,
                "symbol":         symbol,
                "amount":         float(row.get("income", 0) or 0),
                "mark_price":     None,    # not on the income feed
                "funding_rate":   None,    # not on the income feed
                "ts_ms":          ts_ms,
                "venue_event_id": _veid,
                "lifecycle_id":   lifecycle_id,
            })
            if inserted:
                written += 1
            else:
                deduped += 1
            _fa: Dict[str, Any] = {
                "outcome": "ASSIGNED",
                "resolution_path": _path,
                "amount": float(row.get("income", 0) or 0),
                "ts_ms": ts_ms,
                "inserted": bool(inserted),
                "reconcile_queued": _reconcile_queued,
                "terminal_position_id": tpid,
                "calc_id": calc_id or "",
                "lifecycle_id": lifecycle_id or "",
                "exchange_order_id": "",
                "dedup_key": _veid, "venue_event_id": _veid,
            }
            if tpid in _fault_tpids:
                _fa["resolver_fault"] = True
            correlation_log.emit(
                "funding_handler", "internal", "internal",
                correlation_log.CAT_ATTR_FUNDING_ASSIGN, _fa,
                account_id=account_id, symbol=symbol or None,
            )
    except Exception as e:
        # corr-tap: attr_funding_assign — batch-abort twin (mandate 1: the
        # exception path is a line; behavior unchanged — re-raise to the
        # caller exactly as before)
        correlation_log.emit(
            "funding_handler", "internal", "internal",
            correlation_log.CAT_ATTR_FUNDING_ASSIGN,
            {"outcome": "ERROR", "reason": "batch_aborted",
             "error_type": type(e).__name__,
             "n_rows_processed": _n_processed,
             "terminal_position_id": "", "calc_id": "",
             "lifecycle_id": "", "exchange_order_id": ""},
            account_id=account_id,
        )
        raise

    reconciled = 0
    for tpid in closed_tpids_to_reconcile:
        try:
            if await db.reconcile_closed_position_funding(account_id, tpid):
                reconciled += 1
        except Exception:
            # Best-effort — a reconcile fault must not lose the funding row (it's
            # persisted). Recovery IS automatic: the next poll re-fetches this
            # settlement (inclusive last_seen_ms cursor), re-resolves the closed
            # tpid, and re-attempts reconcile even though the row dedups (the
            # add() above is NOT gated on `inserted`) — until last_seen_ms
            # advances past this ts (next settlement, ~8h). The reconcile is
            # idempotent + a no-op when already correct, so the retries are cheap.
            log.debug(
                "deferred-funding reconcile failed for %s (will retry next poll)",
                tpid, exc_info=True,
            )

    return {
        "written": written, "deduped": deduped,
        "orphan": orphan, "reconciled": reconciled,
    }
