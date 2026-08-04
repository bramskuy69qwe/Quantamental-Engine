"""
Event handlers registered with event_bus.

Each handler is an async callback with signature:
    async def handle_X(payload: dict) -> None

Handlers are the single place where event bus messages translate into
state mutations and DB writes. They are registered in main.py lifespan.

Import graph (no circular deps):
    handlers → core.state (app_state)
    handlers → core.database (db)
    handlers do NOT import from event_bus or ws_manager
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from core.state import app_state
from core.tz import now_in_account_tz
from core.database import db

log = logging.getLogger("handlers")


def _build_account_snapshot(trigger_channel: str) -> Dict[str, Any]:
    """Build an account_snapshots row dict from current app_state."""
    acc = app_state.account_state
    pf  = app_state.portfolio
    return {
        "account_id":           app_state.active_account_id,
        "snapshot_ts":          datetime.now(timezone.utc).isoformat(),
        "total_equity":         acc.total_equity,
        "balance_usdt":         acc.balance_usdt,
        "available_margin":     acc.available_margin,
        "total_unrealized":     acc.total_unrealized,
        "total_realized":       acc.total_realized,
        "total_position_value": acc.total_position_value,
        "total_margin_used":    acc.total_margin_used,
        "total_margin_ratio":   acc.total_margin_ratio,
        "daily_pnl":            acc.daily_pnl,
        "daily_pnl_percent":    acc.daily_pnl_percent,
        "bod_equity":           acc.bod_equity,
        "sow_equity":           acc.sow_equity,
        "max_total_equity":     acc.max_total_equity,
        "min_total_equity":     acc.min_total_equity,
        "total_exposure":       pf.total_exposure,
        "drawdown":             pf.drawdown,
        "total_weekly_pnl":     pf.total_weekly_pnl,
        "weekly_pnl_state":     pf.weekly_pnl_state,
        "dd_state":             pf.dd_state,
        "open_positions":       len(app_state.positions),
        "trigger_channel":      trigger_channel,
    }


async def handle_account_updated(payload: Dict[str, Any]) -> None:
    """
    Triggered by: risk:account_updated
    Source: ws_manager._handle_user_event (WS ACCOUNT_UPDATE event)

    1. Recalculate portfolio metrics
    2. Persist account snapshot to DB
    """
    # recalculate_portfolio() now called inside DataCache after position mutations.
    # For account_updated events (WS), DataCache already recalculated.
    snap = _build_account_snapshot("risk:account_updated")
    try:
        await db.insert_account_snapshot(snap)
    except Exception as exc:
        log.error("handle_account_updated DB write failed: %s", exc)

    # v2.4 Phase 5: publish equity update to Redis
    # Task 162: narrow the silent swallow. publish() can fail on
    # legitimate operational conditions (redis down, network blip, bus
    # backend swap mid-call). Those deserve a warning so the operator
    # sees pub/sub degradation. Programming errors in the bus shim must
    # propagate. ConnectionError + TimeoutError + OSError cover network/
    # backend infra; ImportError covers module-not-loaded.
    try:
        from core.pubsub.bus import get_bus
        from core.pubsub.channels import equity_channel
        await get_bus().publish(equity_channel(app_state.active_account_id), {
            "total_equity": snap.get("total_equity", 0),
            "available_margin": snap.get("available_margin", 0),
            "unrealized_pnl": snap.get("total_unrealized", 0),
            "ts": snap.get("snapshot_ts", ""),
        })
    except (ImportError, ConnectionError, TimeoutError, OSError) as exc:
        log.warning("handle_account_updated: equity publish failed: %r", exc)

    log.debug(
        "account_updated",
        extra={
            "event": payload.get("event"),
            "equity": app_state.account_state.total_equity,
            "drawdown": app_state.portfolio.drawdown,
        },
    )


async def handle_positions_refreshed(payload: Dict[str, Any]) -> None:
    """
    Triggered by: risk:positions_refreshed
    Sources:
      - ws_manager._refresh_positions_after_fill  (trigger="fill")
      - main._account_refresh_loop                (trigger="periodic")

    1. Rebuild market WS streams if the position symbol set changed
    2. Persist account snapshot (position refresh changes portfolio state)

    (Portfolio recalculation happens UPSTREAM — DataCache.apply_position_
    snapshot() runs it before publishing this event, see the comment
    below; the "persist all open positions to position_changes" step was
    retired 2026-08-04 — dead-settings batch M4, note at the write site.)
    """
    # recalculate_portfolio() now called inside DataCache.apply_position_snapshot()
    # before this event is published — portfolio is already up-to-date.

    # Rebuild market WS streams if position symbols changed (new open/close)
    current_syms = {p.ticker for p in app_state.positions}
    if not hasattr(handle_positions_refreshed, "_prev_syms"):
        handle_positions_refreshed._prev_syms = set()
    if current_syms != handle_positions_refreshed._prev_syms:
        handle_positions_refreshed._prev_syms = current_syms
        try:
            from core import ws_manager
            await ws_manager.restart_market_streams()
        except (ImportError, ConnectionError, TimeoutError, OSError) as exc:
            # Task 162: narrow the silent swallow. WS restart failure is
            # operationally important — operator should see when a
            # subscription rebuild doesn't happen on symbol-set change
            # (positions will use stale market data until next restart).
            log.warning(
                "handle_positions_refreshed: market-stream restart "
                "failed (symbol-set change to %s): %r",
                sorted(current_syms), exc,
            )

    trigger = payload.get("trigger", "unknown")

    # M4 (dead-settings batch, 2026-08-04): the per-position write to
    # position_changes is RETIRED. It ran on every refresh since its v2.x
    # introduction (19,151 live rows) and no prod code ever read the table.
    # The table, its historical rows and db.insert_position_changes all
    # STAY (forensic time-series + the kept table-level-API convention,
    # same reasoning as insert_trade_history in the ninth-block retirement)
    # — only this, its ONLY caller, stops. `trigger` still feeds the log
    # line below.

    try:
        await db.insert_account_snapshot(_build_account_snapshot("risk:positions_refreshed"))
    except Exception as exc:
        log.error("handle_positions_refreshed DB write failed: %s", exc)

    log.debug(
        "positions_refreshed",
        extra={"trigger": trigger, "count": len(app_state.positions)},
    )


async def _supersede_prior_active_calcs(
    account_id: int,
    ticker: str,
    side: str,
    new_calc_id: str,
) -> None:
    """T214 (P1.T3): supersede any prior live calc for the same
    ``(account_id, ticker, side)`` before a new calc lands.

    Spec §2 / §5 calc-revision flow: when the operator clicks Calculate
    again for the same symbol+direction, the prior calc transitions
    ``→ superseded`` and the new one takes its place. The link between
    them is preserved via ``pre_trade_log.superseded_by_calc_id``.

    T217 (audit follow-up): "prior live calc" = status IN
    ('active', 'released'), not just 'active'. A recalc is a fresh
    intent that supersedes ALL prior live calcs for the key — including
    a ``released`` calc whose order was cancelled (spec §5 has the
    RELEASED → SUPERSEDED edge). This prevents a stale released calc
    coexisting with the new active calc as a second matcher candidate.
    The T216 re-match workflow (re-place the SAME order without
    recomputing) is unaffected — that path has no recalc, so the
    released calc survives until a replacement order re-matches it.

    Side normalization uses :func:`core.calc_correlation.norm_side` so
    a prior calc with ``side='long'`` is still found when the new calc
    arrives with ``side='LONG'``/``'BUY'`` (defensive — the calculator
    currently always writes lowercase, but the consistency saves us if
    that changes).

    The UPDATE is scoped ``WHERE ... AND status = <the row's status>``
    (T211 M3 pattern): if a concurrent caller already flipped the prior
    calc out of that status (matcher link, expire-sweeper) the UPDATE
    affects 0 rows and the transition skips event emission silently.

    Best-effort: per-calc failures log but don't abort the new calc's
    insert. The caller (``handle_risk_calculated``) wraps this in its
    own try/except.
    """
    if not new_calc_id or not ticker or not side:
        return

    from core.calc_correlation import norm_side
    from core.calc_state import CalcStatus, CalcTransitionRaceLost, transition

    side_canonical = norm_side(side)

    # Find candidate prior calcs by (account, ticker, status IN
    # ('active','released')). Side normalization happens in Python
    # because the column stores raw values (matching the matcher's
    # same-shape filter from T211 H1). We carry each row's actual
    # status so the transition + TOCTOU-guarded UPDATE use the right
    # source state (active→superseded OR released→superseded).
    async with db._conn.execute(
        "SELECT calc_id, side, status FROM pre_trade_log "
        "WHERE account_id = ? "
        "  AND ticker = ? "
        "  AND status IN ('active', 'released') "
        "  AND calc_id IS NOT NULL "
        "  AND calc_id != ?",
        (account_id, ticker, new_calc_id),
    ) as cur:
        rows = await cur.fetchall()

    for old_calc_id, old_side, old_status in rows:
        if norm_side(old_side) != side_canonical:
            continue  # different direction — not a supersede target

        # T215 M3: no default-arg capture needed — transition() awaits
        # apply_fn fully before the loop advances, so old_calc_id /
        # old_status can't change under a still-pending closure.
        async def _apply_supersede() -> None:
            cur2 = await db._conn.execute(
                "UPDATE pre_trade_log "
                "SET status = ?, superseded_by_calc_id = ? "
                "WHERE calc_id = ? AND status = ?",
                (CalcStatus.SUPERSEDED.value, new_calc_id,
                 old_calc_id, old_status),
            )
            await db._conn.commit()
            if cur2.rowcount == 0:
                # Race: prior caller moved this calc out of old_status
                # between SELECT and UPDATE. Raise the shared sentinel
                # (T215 M2b) so transition() skips the event; caught below.
                raise CalcTransitionRaceLost(
                    old_calc_id,
                    old_status,
                    CalcStatus.SUPERSEDED.value,
                )

        try:
            await transition(
                calc_id=old_calc_id,
                current_status=old_status,
                target_status=CalcStatus.SUPERSEDED.value,
                apply_fn=_apply_supersede,
                account_id=account_id,
                event_payload={"new_calc_id": new_calc_id},
                reason="operator_recalc",
            )
        except CalcTransitionRaceLost as exc:
            log.info("%s", exc)
        except Exception:
            log.warning(
                "supersede transition failed for calc_id=%s (new=%s)",
                old_calc_id, new_calc_id, exc_info=True,
            )


async def sweep_expired_calcs(
    account_id: int, now_ms: Optional[int] = None,
) -> int:
    """T224 (Phase 1.8 — audit follow-up): expire window-lapsed calcs.

    Transitions ``active | released → expired`` via
    :func:`core.calc_state.transition` (emits ``calc:expired``) for every
    calc whose window has elapsed. Before this, the only producer of
    ``expired`` was the one-shot NULL backfill (which bypasses the
    choke-point), so ``calc:expired`` never fired live and unmatched
    calcs lingered as matcher / supersede / manual-link candidates
    indefinitely. The Phase-1 holistic audit (H1/H2/L2) flagged this.

    Expiry threshold matches the matcher's in-window gate (spec §4.2):
    a calc expires when ``age > window_seconds + clock_skew_tolerance_sec``
    — i.e. exactly when it's no longer matchable. Per-calc frozen
    ``window_seconds`` (T2) is honored; NULL falls back to the account
    default.

    Spec §9 ``calc:expired`` payload carries ``age_seconds`` + ticker /
    direction / model_name (fetched here). TOCTOU-guarded (T211 M3):
    UPDATE scoped ``WHERE status = <read>`` → CalcTransitionRaceLost →
    event skipped if a concurrent transition won the race.

    Returns the count expired. Best-effort per calc; called from the
    periodic ``_calc_expiry_loop`` in ``core/schedulers.py`` (sweeps the
    active account — multi-account sweep is a future refinement).
    """
    import time as _time
    from datetime import datetime, timezone

    from core.account_config import read_account_config_async
    from core.calc_state import (
        CalcStatus,
        CalcTransitionRaceLost,
        transition,
    )

    if now_ms is None:
        now_ms = int(_time.time() * 1000)

    cfg = await read_account_config_async(db, account_id)

    try:
        async with db._conn.execute(
            "SELECT calc_id, status, timestamp, window_seconds, "
            "       ticker, side, model_name "
            "FROM pre_trade_log "
            "WHERE account_id = ? "
            "  AND status IN ('active', 'released') "
            "  AND calc_id IS NOT NULL",
            (account_id,),
        ) as cur:
            rows = await cur.fetchall()
    except Exception:
        log.warning(
            "sweep_expired_calcs: candidate query failed for account=%s",
            account_id, exc_info=True,
        )
        return 0

    expired = 0
    for calc_id, status, timestamp, window_seconds, ticker, side, model_name in rows:
        calc_window = window_seconds or cfg.window_seconds
        bound_ms = (calc_window + cfg.clock_skew_tolerance_sec) * 1000
        try:
            dt = datetime.fromisoformat((timestamp or "").replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            calc_ts_ms = int(dt.timestamp() * 1000)
        except Exception:
            continue  # malformed timestamp — skip (can't age it)
        age_ms = now_ms - calc_ts_ms
        if age_ms <= bound_ms:
            continue  # still in window — not expired

        # T215 M3: no default-arg capture — transition() awaits apply_fn
        # before the loop advances, so calc_id/status can't rebind under
        # a pending closure.
        async def _apply_expire() -> None:
            cur2 = await db._conn.execute(
                "UPDATE pre_trade_log SET status = ? "
                "WHERE calc_id = ? AND status = ?",
                (CalcStatus.EXPIRED.value, calc_id, status),
            )
            await db._conn.commit()
            if cur2.rowcount == 0:
                raise CalcTransitionRaceLost(
                    calc_id, status, CalcStatus.EXPIRED.value,
                )

        try:
            await transition(
                calc_id=calc_id,
                current_status=status,
                target_status=CalcStatus.EXPIRED.value,
                apply_fn=_apply_expire,
                account_id=account_id,
                event_payload={
                    "age_seconds": age_ms // 1000,
                    "ticker": ticker,
                    "direction": side,
                    "model_name": model_name,
                },
            )
            expired += 1
        except CalcTransitionRaceLost as exc:
            log.info("%s", exc)
        except Exception:
            log.warning(
                "sweep_expired_calcs: expire failed for calc_id=%s",
                calc_id, exc_info=True,
            )

    if expired:
        log.info("Expired %d window-lapsed calc(s) for account %s",
                 expired, account_id)
    return expired


async def cancel_calc_by_operator(
    account_id: int, calc_id: str, reason: str = "",
) -> str:
    """T219 (P1.T4 / plan §1 task 1.6): operator cancels a live calc.

    Spec §2 [A] / §5 / §9: the operator clicks "Cancel calc"; the calc
    transitions ``→ cancelled_by_operator`` with an optional reason note,
    and a ``calc:cancelled`` event fires (carrying ``reason``/``reason_note``).

    Only LIVE calcs are cancellable — status IN ('active', 'released')
    (both have CANCELLED_BY_OPERATOR as a valid outgoing edge in
    ``core/calc_state.CALC_TRANSITIONS``). A ``matched`` calc is linked
    to a working order; cancel the ORDER (which releases the calc, T216)
    rather than the calc directly. Terminal states (expired, superseded,
    completed_via_position, already-cancelled) are not cancellable.

    The UPDATE is TOCTOU-guarded ``WHERE ... AND status = <read status>``
    (T211 M3): if a concurrent transition flipped the calc out from
    under us between the read and the UPDATE, rowcount=0 → the shared
    sentinel skips event emission.

    Returns a status string for the caller to map to an HTTP response:
      'cancelled' | 'not_found' | 'not_cancellable' | 'race_lost' | 'error'
    """
    if not calc_id:
        return "not_found"

    from core.calc_state import (
        CalcStatus,
        CalcTransitionRaceLost,
        transition,
    )

    try:
        async with db._conn.execute(
            "SELECT status FROM pre_trade_log "
            "WHERE account_id = ? AND calc_id = ?",
            (account_id, calc_id),
        ) as cur:
            row = await cur.fetchone()
    except Exception:
        log.warning(
            "cancel_calc_by_operator: status read failed for calc_id=%s",
            calc_id, exc_info=True,
        )
        return "error"

    if not row:
        return "not_found"
    current_status = row[0]

    if current_status not in (CalcStatus.ACTIVE.value, CalcStatus.RELEASED.value):
        # matched / superseded / expired / completed_via_position /
        # already cancelled — not a valid cancel source.
        return "not_cancellable"

    reason_value = reason.strip() or None

    async def _apply_cancel() -> None:
        cur2 = await db._conn.execute(
            "UPDATE pre_trade_log "
            "SET status = ?, cancelled_reason = ? "
            "WHERE calc_id = ? AND status = ?",
            (CalcStatus.CANCELLED_BY_OPERATOR.value, reason_value,
             calc_id, current_status),
        )
        await db._conn.commit()
        if cur2.rowcount == 0:
            raise CalcTransitionRaceLost(
                calc_id, current_status,
                CalcStatus.CANCELLED_BY_OPERATOR.value,
            )

    try:
        await transition(
            calc_id=calc_id,
            current_status=current_status,
            target_status=CalcStatus.CANCELLED_BY_OPERATOR.value,
            apply_fn=_apply_cancel,
            account_id=account_id,
            reason=reason_value,
        )
        return "cancelled"
    except CalcTransitionRaceLost as exc:
        log.info("%s", exc)
        return "race_lost"
    except Exception:
        log.warning(
            "cancel_calc_by_operator: transition failed for calc_id=%s",
            calc_id, exc_info=True,
        )
        return "error"


async def handle_risk_calculated(payload: Dict[str, Any]) -> None:
    """
    Triggered by: risk:risk_calculated
    Source: api/routes.calculate_risk (after run_risk_calculator())

    1. Read per-account config (window_seconds is frozen onto the calc)
    2. Supersede any prior ``active`` calc for (account, ticker, side)
    3. Write calc result to pre_trade_log DB table
    4. Update in-memory cache (app_state.pre_trade_log, last 200 rows) —
       preserves the contract that /fragments/history and UI depend on
    """
    account_id = app_state.active_account_id
    # T213 (P1.T2 / plan §1 task 1.3): freeze per-account window onto
    # the calc at creation time. Spec §3.2: "window_seconds | INTEGER
    # | frozen from accounts.config_json at creation" — so an operator
    # changing accounts.config_json.window_seconds mid-flight doesn't
    # affect in-flight calcs. The matcher reads this column per-calc
    # (spec §4.3) and falls back to the account default only when NULL.
    try:
        from core.account_config import read_account_config_async
        account_config = await read_account_config_async(db, account_id)
    except Exception:
        log.warning(
            "handle_risk_calculated: account config read failed; "
            "calc will land with window_seconds=NULL and matcher will "
            "fall back to spec default", exc_info=True,
        )
        from core.account_config import AccountConfig
        account_config = AccountConfig()

    # P9.T3: stamp who created this calc (the active operator session's
    # seat). DB-resolved — correct even when the WS cache is cold (right
    # after a restart, before any browser registers) — because "who
    # created this calc" is the high-value attribution and calc creation
    # is not a hot path. Best-effort None on no active session / fault.
    from core.auth_state import current_operator_id
    operator_id = await current_operator_id(db, account_id)

    # T215 H2: insert new calc FIRST, then supersede priors. Reverse
    # of the T214 order — closes the orphan-risk window where supersede
    # succeeded but insert failed, leaving the old calc 'superseded'
    # with superseded_by_calc_id pointing at a non-existent new calc.
    # The brief overlap (two active calcs for the same key) between
    # insert and supersede is safe: the matcher's most-recent tie-break
    # (spec §4.3) picks the new calc on any concurrent order arrival.
    insert_ok = False
    try:
        await db.insert_pre_trade_log({
            **payload,
            "account_id": account_id,
            "window_seconds": account_config.window_seconds,
            "operator_id": operator_id,
        })
        insert_ok = True
    except Exception as exc:
        log.error("handle_risk_calculated DB write failed: %s", exc)

    # T214 (P1.T3 / plan §1 task 1.5): supersede prior active calc(s)
    # for the same (account, ticker, side). Spec §2 / §5 calc-revision
    # flow. Best-effort: a failure here leaves prior calc(s) active and
    # the new calc also active; matcher's most-recent tie-break covers
    # the gap. Only runs when the insert succeeded — otherwise the
    # new_calc_id we'd cite in superseded_by_calc_id wouldn't exist.
    if insert_ok:
        try:
            await _supersede_prior_active_calcs(
                account_id=account_id,
                ticker=payload.get("ticker", ""),
                side=payload.get("side", ""),
                new_calc_id=payload.get("calc_id", ""),
            )
        except Exception:
            log.warning(
                "handle_risk_calculated: supersede pass failed for "
                "ticker=%s side=%s; new calc is in DB but priors may "
                "remain active (matcher tie-break still picks newest)",
                payload.get("ticker"), payload.get("side"), exc_info=True,
            )

    # v2.4: emit calc_created trade event
    # Task 162: narrow + upgrade from log.debug → log.warning. The
    # pre-T162 form (`except Exception: log.debug(..., exc_info=True)`)
    # silently swallowed every failure at a log level the operator
    # almost never sees. trade_event_log is the forensic trail the
    # regime build's leaderboard will consume; missed events are real
    # operational concerns. Narrow to infra-failure shapes; programming
    # errors propagate.
    try:
        from core.trade_event_log import log_trade_event
        calc_id = payload.get("calc_id")
        if calc_id and payload.get("eligible"):
            log_trade_event(app_state.active_account_id, calc_id, "calc_created", {
                "ticker": payload.get("ticker", ""),
                "side": payload.get("side", ""),
                "entry": payload.get("effective_entry", 0),
                "tp": payload.get("tp_price", 0),
                "sl": payload.get("sl_price", 0),
                "size": payload.get("size", 0),
                "atr_category": payload.get("atr_category", ""),
                "est_slippage": payload.get("est_slippage", 0),
                "est_r": payload.get("est_r", 0),
            }, source="risk_engine")
    except (ImportError, sqlite3.Error, OSError) as exc:
        log.warning(
            "handle_risk_calculated: calc_created trade event not "
            "recorded (event_log infrastructure failed): %r", exc,
        )

    # P6 (calc:created event_bus topic, spec §9): mirror the calc_created trade
    # event onto the per-account topic engine:account:{id}:calc:created. Same
    # gate as the trade event (an eligible calc with an id). Best-effort —
    # publish_engine is enqueue-only; never block the calc write on it.
    try:
        from core.event_bus import event_bus, DOMAIN_CALC
        created_calc_id = payload.get("calc_id")
        if created_calc_id and payload.get("eligible"):
            await event_bus.publish_engine(account_id, DOMAIN_CALC, "created", {
                "calc_id":        created_calc_id,
                "ticker":         payload.get("ticker", ""),
                "direction":      payload.get("side", ""),
                "window_seconds": account_config.window_seconds,
                "model_name":     payload.get("model_name", ""),
                # v2.7 5.2 (optional plan item): the model-library FK rides
                # the event too — additive for consumers.
                "model_id":       payload.get("model_id"),
                "tags":           payload.get("tags"),
                "operator_id":    operator_id,  # P9.T3 (active session seat)
            })
    except Exception:
        log.warning(
            "handle_risk_calculated: calc:created event_bus publish failed",
            exc_info=True,
        )

    # Maintain in-memory cache (same shape as the old CSV-backed list)
    row = {
        "timestamp":         payload.get("timestamp", now_in_account_tz(app_state.active_account_id).isoformat()),
        "ticker":            payload.get("ticker", ""),
        "average":           payload.get("average", 0),
        "side":              payload.get("side", ""),
        "one_percent_depth": payload.get("one_percent_depth", 0),
        "individual_risk":   payload.get("individual_risk_pct", payload.get("individual_risk", 0)),
        "tp_price":          payload.get("tp_price", 0),
        "tp_amount_pct":     payload.get("tp_amount_pct", 0),
        "tp_usdt":           payload.get("tp_usdt", 0),
        "sl_price":          payload.get("sl_price", 0),
        "sl_amount_pct":     payload.get("sl_amount_pct", 0),
        "sl_usdt":           payload.get("sl_usdt", 0),
        "model_name":        payload.get("model_name", ""),
        "model_desc":        payload.get("model_desc", ""),
        "risk_usdt":         payload.get("risk_usdt", 0),
        "atr_c":             payload.get("atr_c", ""),
        "atr_category":      payload.get("atr_category", ""),
        "est_slippage":      payload.get("est_slippage", 0),
        "effective_entry":   payload.get("effective_entry", 0),
        "size":              payload.get("size", 0),
        "notional":          payload.get("notional", 0),
        "est_profit":        payload.get("est_profit", 0),
        "est_loss":          payload.get("est_loss", 0),
        "est_r":             payload.get("est_r", 0),
        "est_exposure":      payload.get("est_exposure", 0),
        "eligible":          payload.get("eligible", False),
    }
    app_state.pre_trade_log.append(row)
    app_state.pre_trade_log = app_state.pre_trade_log[-200:]

    log.debug(
        "risk_calculated",
        extra={"ticker": payload.get("ticker"), "eligible": payload.get("eligible")},
    )


async def handle_params_updated(payload: Dict[str, Any]) -> None:
    """
    Triggered by: risk:params_updated
    Source: api/routes.update_params (after app_state.save_params())

    Recalculate portfolio so all metrics reflect new parameters immediately.
    """
    # SR-3/F4: route through DataCache (sole recalculation path)
    if app_state._data_cache is not None:
        app_state._data_cache._recalculate_portfolio()
    log.debug("params_updated", extra={"ts": payload.get("ts")})
