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
  symbol with no attributable open position — settled just before close, or a
  position the engine can't key (empty ``terminal_position_id`` on the binance
  one-way path) — is counted/logged as an orphan and skipped, per spec §11[F]'s
  "optional orphan funding log". This is the same key-availability limitation the
  ``positions_calcs`` junction already carries.

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
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

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
    time, ...}``). Returns ``{"written", "deduped", "orphan"}`` counts.
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

    for row in incomes:
        if str(row.get("incomeType", "")).upper() != "FUNDING_FEE":
            continue
        symbol = row.get("symbol", "") or ""
        tpid = sym_to_tpid.get(symbol, "")
        if not tpid:
            orphan += 1
            log.debug(
                "Orphan funding (no open position for %s, acct %s): amount=%s",
                symbol, account_id, row.get("income"),
            )
            continue
        if tpid not in resolved:
            try:
                resolved[tpid] = await primary_calc_resolver(account_id, tpid)
            except Exception:
                # Best-effort denormalization — a resolver fault must not drop
                # the funding row (the close-time SUM keys on position_id only).
                resolved[tpid] = (None, None)
        calc_id, lifecycle_id = resolved[tpid]
        ts_ms = int(row.get("time", 0) or 0)
        inserted = await db.insert_funding_event({
            "position_id":    tpid,
            "calc_id":        calc_id,
            "account_id":     account_id,
            "symbol":         symbol,
            "amount":         float(row.get("income", 0) or 0),
            "mark_price":     None,    # not on the income feed
            "funding_rate":   None,    # not on the income feed
            "ts_ms":          ts_ms,
            "venue_event_id": synthetic_venue_event_id(account_id, symbol, ts_ms),
            "lifecycle_id":   lifecycle_id,
        })
        if inserted:
            written += 1
        else:
            deduped += 1

    return {"written": written, "deduped": deduped, "orphan": orphan}
