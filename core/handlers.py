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
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

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
    3. Push risk state to any connected Quantower plugin clients
    """
    # recalculate_portfolio() now called inside DataCache after position mutations.
    # For account_updated events (WS), DataCache already recalculated.
    snap = _build_account_snapshot("risk:account_updated")
    try:
        await db.insert_account_snapshot(snap)
    except Exception as exc:
        log.error("handle_account_updated DB write failed: %s", exc)

    # Push to Quantower plugin (no-op when standalone or no clients connected)
    if app_state.active_platform == "quantower":
        try:
            from core.platform_bridge import platform_bridge
            await platform_bridge.push_risk_state()
        except Exception as exc:
            log.warning("push_risk_state failed: %s", exc)

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

    1. Recalculate portfolio metrics
    2. Persist all open positions snapshot to DB
    3. Persist account snapshot (position refresh changes portfolio state)
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
        except Exception:
            pass

    trigger = payload.get("trigger", "unknown")

    # Snapshot all current positions
    position_records = [
        {
            "ticker":                 p.ticker,
            "direction":              p.direction,
            "contract_amount":        p.contract_amount,
            "average":                p.average,
            "fair_price":             p.fair_price,
            "position_value_usdt":    p.position_value_usdt,
            "individual_unrealized":  p.individual_unrealized,
            "individual_margin_used": p.individual_margin_used,
            "sector":                 p.sector,
        }
        for p in app_state.positions
    ]

    try:
        await db.insert_position_changes(
            position_records,
            trigger=f"risk:positions_refreshed:{trigger}",
            account_id=app_state.active_account_id,
        )
        await db.insert_account_snapshot(_build_account_snapshot("risk:positions_refreshed"))
    except Exception as exc:
        log.error("handle_positions_refreshed DB write failed: %s", exc)

    log.debug(
        "positions_refreshed",
        extra={"trigger": trigger, "count": len(app_state.positions)},
    )


async def handle_risk_calculated(payload: Dict[str, Any]) -> None:
    """
    Triggered by: risk:risk_calculated
    Source: api/routes.calculate_risk (after run_risk_calculator())

    1. Write calc result to pre_trade_log DB table
    2. Update in-memory cache (app_state.pre_trade_log, last 200 rows) —
       preserves the contract that /fragments/history and UI depend on
    """
    try:
        await db.insert_pre_trade_log({**payload, "account_id": app_state.active_account_id})
    except Exception as exc:
        log.error("handle_risk_calculated DB write failed: %s", exc)

    # v2.4: emit calc_created trade event
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
    except Exception:
        log.debug("calc_created trade event failed", exc_info=True)

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
