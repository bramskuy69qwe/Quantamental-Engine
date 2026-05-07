"""
Background task registry and schedulers for the Quantamental Engine.

All long-running loops (BOD, regime, news, account refresh, etc.) live here.
main.py calls start_background_tasks() during lifespan startup.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Set

import config
from core.state import app_state, TZ_LOCAL
from core.exchange import (
    fetch_exchange_info, fetch_account, fetch_positions,
    fetch_ohlcv, create_listen_key,
    fetch_bod_sow_equity, fetch_exchange_trade_history,
    populate_open_position_metadata,
)
from core import ws_manager
from core.data_logger import take_daily_snapshot, take_monthly_snapshot, export_all_to_excel
from core.event_bus import event_bus, CH_TRADE_CLOSED
from core.platform_bridge import platform_bridge
from core.handlers import (
    handle_account_updated, handle_positions_refreshed,
    handle_risk_calculated, handle_params_updated,
)
from core.reconciler import ReconcilerWorker
from core.regime_classifier import compute_current_regime
from core.regime_fetcher import RegimeFetcher
from core.news_fetcher import FinnhubFetcher, BweWsConsumer
from core.monitoring import MonitoringService
# _last_ws_position_update guard removed — DataCache handles conflict resolution

log = logging.getLogger("main")

# ── Background task registry ─────────────────────────────────────────────────
# Keeps strong references so tasks aren't garbage-collected, and logs crashes.
_bg_tasks: Set[asyncio.Task] = set()


def _spawn(coro, *, name: str) -> asyncio.Task:
    """Create a tracked background task that logs exceptions on exit."""
    task = asyncio.create_task(coro, name=name)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)

    def _on_done(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception() is not None:
            log.error("Background task '%s' crashed: %r", name, t.exception())

    task.add_done_callback(_on_done)
    return task


# ── BOD scheduler ────────────────────────────────────────────────────────────

async def _bod_scheduler():
    """Wake at midnight UTC+7 to run BOD resets and snapshots."""
    while True:
        now = datetime.now(TZ_LOCAL)
        # Sleep until next midnight local
        midnight = now.replace(hour=0, minute=0, second=5, microsecond=0)
        if now >= midnight:
            midnight = midnight.replace(day=midnight.day + 1)
        sleep_secs = (midnight - now).total_seconds()
        log.info(f"BOD scheduler: sleeping {sleep_secs/3600:.2f}h until {midnight}")
        await asyncio.sleep(sleep_secs)

        log.info("Running BOD reset...")
        app_state.perform_bod_reset()
        take_daily_snapshot()
        # Monthly on the 1st
        if datetime.now(TZ_LOCAL).day == 1:
            take_monthly_snapshot()
        app_state.ws_status.add_log("BOD reset completed.")


# ── Auto-export scheduler ────────────────────────────────────────────────────

async def _auto_export_scheduler():
    """Periodic DB->XLSX export."""
    while True:
        hours = app_state.params.get("auto_export_hours", 24)
        await asyncio.sleep(hours * 3600)
        try:
            path = await export_all_to_excel()
            log.info(f"Auto-export saved to {path}")
            app_state.ws_status.add_log(f"Auto-export: {os.path.basename(path)}")
        except Exception as e:
            log.error(f"Auto-export failed: {e}")


# ── Periodic account refresh (belt-and-suspenders alongside WS) ─────────────

_account_refresh_in_flight = False


async def _account_refresh_loop():
    """Refresh account + positions via REST.
    Skipped when the Quantower plugin is connected — plugin provides live data.
    Guards against overlap if a single refresh takes longer than the interval."""
    global _account_refresh_in_flight
    while True:
        # WS handles real-time position/mark price updates.
        # REST is just a safety net: 30s when WS healthy, 5s when WS down.
        interval = 30 if app_state.ws_status.connected else 5
        await asyncio.sleep(interval)
        if platform_bridge.is_connected or _account_refresh_in_flight:
            continue
        # WS freshness guard removed — DataCache now handles conflict resolution
        # (rejects stale REST position/account updates when WS is fresher)
        _account_refresh_in_flight = True
        try:
            await fetch_account()
            await fetch_positions()
            # Note: risk:positions_refreshed now fires inside
            # DataCache.apply_position_snapshot() — no duplicate needed.
            # Also sync orders from REST when plugin is disconnected
            try:
                from core.exchange import _get_adapter
                adapter = _get_adapter()
                normalized_orders = await adapter.fetch_open_orders()
                order_dicts = [
                    {
                        "account_id":         app_state.active_account_id,
                        "exchange_order_id":  o.exchange_order_id,
                        "terminal_order_id":  "",
                        "client_order_id":    o.client_order_id,
                        "symbol":             o.symbol,
                        "side":               o.side,
                        "order_type":         o.order_type,
                        "status":             o.status,
                        "price":              o.price,
                        "stop_price":         o.stop_price,
                        "quantity":           o.quantity,
                        "filled_qty":         o.filled_qty,
                        "avg_fill_price":     o.avg_fill_price,
                        "reduce_only":        o.reduce_only,
                        "time_in_force":      o.time_in_force,
                        "position_side":        o.position_side,
                        "exchange_position_id": "",
                        "terminal_position_id": "",
                        "source":               f"{config.EXCHANGE_NAME.lower()}_rest",
                        "created_at_ms":        o.created_at_ms,
                        "updated_at_ms":        o.updated_at_ms,
                    }
                    for o in normalized_orders
                ]
                await platform_bridge.order_manager.process_order_snapshot(
                    app_state.active_account_id, order_dicts,
                )
            except Exception as e:
                log.debug("REST order sync skipped: %s", e)
            # Also sync fills for open position symbols
            try:
                from core.database import db as _db
                for pos in app_state.positions:
                    try:
                        recent = await adapter.fetch_user_trades(pos.ticker, limit=50)
                        for t in recent:
                            await _db.upsert_fill({
                                "account_id":           app_state.active_account_id,
                                "exchange_fill_id":     t.exchange_fill_id,
                                "terminal_fill_id":     t.terminal_fill_id,
                                "exchange_order_id":    t.exchange_order_id,
                                "symbol":               t.symbol,
                                "side":                 t.side,
                                "direction":            t.direction,
                                "price":                t.price,
                                "quantity":             t.quantity,
                                "fee":                  t.fee,
                                "fee_asset":            t.fee_asset,
                                "exchange_position_id": "",
                                "terminal_position_id": t.terminal_position_id,
                                "is_close":             int(t.is_close),
                                "realized_pnl":         t.realized_pnl,
                                "role":                 t.role,
                                "source":               f"{config.EXCHANGE_NAME.lower()}_rest",
                                "timestamp_ms":         t.timestamp_ms,
                            })
                    except Exception:
                        pass
            except Exception as e:
                log.debug("REST fill sync skipped: %s", e)
        except Exception as e:
            log.warning(f"Periodic account refresh failed: {e}")
        finally:
            _account_refresh_in_flight = False


# ── Latency ping loop ───────────────────────────────────────────────────────

async def _ping_loop():
    """Measure REST round-trip latency every 1 second.
    Skipped when the Quantower plugin is connected — avoids hammering Binance REST."""
    while True:
        await asyncio.sleep(1)
        if platform_bridge.is_connected:
            continue
        try:
            await fetch_exchange_info()
        except Exception as e:
            log.debug(f"Ping failed: {e}")


# ── BOD/SOW + exchange history refresh ───────────────────────────────────────

async def _history_refresh_loop():
    """Refresh BOD/SOW equity and exchange trade history every 5 minutes.
    Skipped when the Quantower plugin is connected."""
    while True:
        await asyncio.sleep(300)
        if platform_bridge.is_connected:
            continue
        try:
            await fetch_bod_sow_equity()
        except Exception as e:
            log.warning(f"BOD/SOW refresh failed: {e}")
        try:
            await fetch_exchange_trade_history()
        except Exception as e:
            log.warning(f"Exchange trade history refresh failed: {e}")


# ── Background startup fetch ────────────────────────────────────────────────

async def _startup_fetch():
    """
    Slow startup tasks (Binance REST + WS setup) run as a background task so
    the server accepts connections immediately.  Sets app_state.is_initializing
    = False when done — the /api/ready endpoint watches this flag.
    """
    try:
        await event_bus.connect()
        event_bus.subscribe("risk:account_updated",     handle_account_updated)
        event_bus.subscribe("risk:positions_refreshed", handle_positions_refreshed)
        event_bus.subscribe("risk:risk_calculated",     handle_risk_calculated)
        event_bus.subscribe("risk:params_updated",      handle_params_updated)

        _reconciler = ReconcilerWorker()
        event_bus.subscribe(CH_TRADE_CLOSED, _reconciler.on_trade_closed)
        event_bus.subscribe("risk:position_closed", _reconciler.on_position_closed)
        _spawn(_reconciler.backfill_all(), name="reconciler_backfill")

        _spawn(event_bus.run(), name="event_bus")
    except Exception as e:
        log.error(f"EventBus startup failed: {e}")
        app_state.ws_status.add_log(f"EVENT BUS ERROR: {e}")

    # Each fetch is independent — one failure must not block the others.
    # Previously all were in a single try block, so fetch_account failure
    # would prevent fetch_positions from ever running (0 positions on startup).
    for fetch_fn, label in [
        (fetch_exchange_info, "exchange_info"),
        (fetch_account,       "account"),
        (fetch_positions,     "positions"),
    ]:
        try:
            await fetch_fn()
        except Exception as e:
            log.error(f"Initial {label} fetch failed: {e}")
            app_state.ws_status.add_log(f"INIT ERROR ({label}): {e}")

    try:
        await populate_open_position_metadata()
    except Exception as e:
        log.warning(f"Position metadata population failed: {e}")

    if app_state.account_state.total_equity > 0:
        log.info(f"Connected — equity: {app_state.account_state.total_equity:.2f} USDT")

    try:
        await fetch_bod_sow_equity()
    except Exception as e:
        log.warning(f"BOD/SOW initial fetch failed: {e}")

    try:
        await fetch_exchange_trade_history()
    except Exception as e:
        log.warning(f"Exchange trade history initial fetch failed: {e}")

    # Auto-backfill fills + closed_positions from exchange_history (idempotent)
    try:
        from core.database import db as _db
        aid = app_state.active_account_id
        result = await _db.backfill_fills_from_exchange_history(account_id=aid, days=90)
        if result["fills_inserted"] or result["closed_inserted"]:
            log.info(
                "Startup backfill: %d fills, %d closed_positions from exchange_history",
                result["fills_inserted"], result["closed_inserted"],
            )
            app_state.ws_status.add_log(
                f"Backfill: {result['fills_inserted']} fills, "
                f"{result['closed_inserted']} closed positions"
            )
    except Exception as e:
        log.warning(f"Startup backfill failed: {e}")

    for pos in app_state.positions:
        try:
            await fetch_ohlcv(pos.ticker)
        except Exception as e:
            log.warning(f"OHLCV fetch failed for {pos.ticker}: {e}")

    app_state.recalculate_portfolio()

    try:
        listen_key = await create_listen_key()
        await ws_manager.start(listen_key)
    except Exception as e:
        log.error(f"WS startup failed: {e}")
        app_state.ws_status.add_log(f"WS STARTUP ERROR: {e}")

    # Compute initial regime from whatever is already in the DB so that the
    # first calculator run is never stuck with a 1.0 fallback multiplier.
    try:
        app_state.current_regime = await compute_current_regime()
        r = app_state.current_regime
        log.info("Initial regime: %s x%.1f", r.label, r.multiplier)
        app_state.ws_status.add_log(f"Regime (startup): {r.label} x{r.multiplier}")
    except Exception as e:
        log.warning("Initial regime computation failed: %s", e)

    app_state.is_initializing = False
    app_state.ws_status.add_log(f"{config.PROJECT_NAME} fully initialized.")
    log.info(f"Background startup complete — {config.PROJECT_NAME} fully ready.")


# ── Regime refresh loop ──────────────────────────────────────────────────────

async def _regime_refresh_loop():
    """
    Background loop that keeps app_state.current_regime up to date.

    Schedule:
      - Re-classify every 10 minutes (reads latest DB signals — fast).
      - Re-fetch TradFi signals (VIX, FRED, rvol) once per hour (slow I/O).
      - Re-fetch Binance crypto signals (OI, funding) every 4 hours (slow I/O).

    Signal fetches run AFTER the first classification so they never block the
    initial regime computation (which is done in _startup_fetch instead).
    """
    _state = {"last_tradfi": 0.0, "last_crypto": 0.0}

    while True:
        await asyncio.sleep(10 * 60)  # re-classify every 10 minutes

        now = datetime.now(timezone.utc).timestamp()

        # ── TradFi signal refresh (hourly) ────────────────────────────────────
        if now - _state["last_tradfi"] >= 3600:
            try:
                today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                # 10-day lookback: covers weekends, public holidays, and FRED reporting lags
                lookback  = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
                fetcher   = RegimeFetcher()
                await fetcher.fetch_vix(lookback, today)
                await fetcher.fetch_us10y_yield(lookback, today)
                await fetcher.fetch_hy_spread(lookback, today)
                await fetcher.compute_btc_rvol_ratio(lookback, today)
                await fetcher.close()
                _state["last_tradfi"] = now
                log.info("Regime: TradFi signals refreshed")
            except Exception as e:
                log.warning("Regime TradFi signal refresh failed: %s", e)

        # ── Binance crypto signal refresh (every 4 hours) ─────────────────────
        if now - _state["last_crypto"] >= 4 * 3600:
            try:
                today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                lookback  = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
                fetcher   = RegimeFetcher()
                await fetcher.fetch_binance_oi(lookback, today)
                await fetcher.fetch_binance_funding(lookback, today)
                await fetcher.close()
                _state["last_crypto"] = now
                log.info("Regime: Binance crypto signals refreshed")
            except Exception as e:
                log.warning("Regime Binance signal refresh failed: %s", e)

        # ── Re-classify current regime ────────────────────────────────────────
        try:
            regime = await compute_current_regime()
            app_state.current_regime = regime
            log.info(
                "Regime updated: %s x%.1f confidence=%s stability=%dd",
                regime.label, regime.multiplier, regime.confidence, regime.stability_bars,
            )
            app_state.ws_status.add_log(
                f"Regime: {regime.label} x{regime.multiplier} ({regime.confidence})"
            )
        except Exception as e:
            log.warning("Regime computation failed: %s", e)


# ── News + Economic Calendar refresh loops ───────────────────────────────────

async def _news_refresh_loop():
    """
    Pull Finnhub news every 15s and economic calendar every 10 min.
    Non-fatal on errors — just log and continue, like _history_refresh_loop.
    """
    fetcher = FinnhubFetcher()
    last_calendar_ts = 0.0

    while True:
        try:
            await fetcher.fetch_news(category="general")
        except Exception as e:
            log.warning("Finnhub news refresh failed: %s", e)

        now_ts = datetime.now(timezone.utc).timestamp()
        if now_ts - last_calendar_ts >= 10 * 60:
            try:
                minus30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
                plus30 = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
                await fetcher.fetch_calendar(minus30, plus30)
                last_calendar_ts = now_ts
            except Exception as e:
                log.warning("Finnhub calendar refresh failed: %s", e)

        await asyncio.sleep(15)


async def _bwe_ws_consumer():
    """Long-running BWE News websocket subscriber. Reconnects on failure."""
    consumer = BweWsConsumer()
    await consumer.run()


# ── Order staleness detection ────────────────────────────────────────────────

async def _order_staleness_loop():
    """Every 60s: mark active orders not seen in 5+ minutes as canceled.
    Only meaningful when the plugin is connected (providing order snapshots)."""
    from core.database import db

    while True:
        await asyncio.sleep(60)
        if not platform_bridge.is_connected:
            continue
        try:
            count = await db.mark_stale_orders(
                account_id=app_state.active_account_id,
                stale_threshold_ms=5 * 60 * 1000,
            )
            if count:
                log.warning("Marked %d stale orders as canceled", count)
                # Rebuild cache from DB (mark_stale only updates DB, not cache)
                om = platform_bridge.order_manager
                om._open_orders = await db.query_open_orders_all(
                    app_state.active_account_id,
                )
                om.enrich_positions_tpsl(app_state.positions)
        except Exception as e:
            log.warning("Order staleness loop error: %s", e)


# ── Public API ───────────────────────────────────────────────────────────────

def start_background_tasks() -> None:
    """Spawn all background schedulers. Call from lifespan startup."""
    _spawn(_startup_fetch(),        name="startup_fetch")
    _spawn(_bod_scheduler(),         name="bod_scheduler")
    _spawn(_auto_export_scheduler(), name="auto_export")
    _spawn(_account_refresh_loop(),  name="account_refresh")
    _spawn(_ping_loop(),             name="ping")
    _spawn(_history_refresh_loop(),  name="history_refresh")
    _spawn(_regime_refresh_loop(),   name="regime_refresh")
    _spawn(_news_refresh_loop(),     name="news_refresh")
    _spawn(_bwe_ws_consumer(),       name="bwe_ws")
    _spawn(MonitoringService().run(), name="monitoring")
    _spawn(_order_staleness_loop(),  name="order_staleness")
