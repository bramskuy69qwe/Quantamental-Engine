"""
DataCache — single-writer state manager (Nautilus-style).

ALL mutable position state flows through this class. No other module
may write to positions directly. This eliminates the TOCTOU race in
fetch_positions() and the unlocked appends in ws_manager.

Data sources call apply_* methods → DataCache acquires lock, resolves
conflicts, mutates state, then publishes events AFTER mutation.

Readers access state via properties (no lock needed — asyncio is
single-threaded, reads between awaits are atomic).

Phase 1: positions only.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

import config
from core.state import PositionInfo

log = logging.getLogger("data_cache")


# ── Update source & versioning ───────────────────────────────────────────────

class UpdateSource(Enum):
    WS_USER   = "ws_user"
    WS_MARKET = "ws_market"
    REST      = "rest"
    PLATFORM  = "platform"
    INTERNAL  = "internal"


@dataclass
class VersionedState:
    """Tracks the provenance and recency of the last accepted mutation."""
    sequence:     int          = 0
    source:       UpdateSource = UpdateSource.INTERNAL
    timestamp_ms: int          = 0
    applied_at:   float        = 0.0   # time.monotonic()


# ── Result types returned to callers ─────────────────────────────────────────

@dataclass
class PositionUpdateResult:
    """Returned by apply_* methods so callers can trigger side effects."""
    accepted:    bool      = True
    closed_syms: Set[str]  = field(default_factory=set)
    new_syms:    Set[str]  = field(default_factory=set)
    changed:     bool      = False


# Metadata fields that only live in engine state (never from REST/WS)
_PRESERVE_FIELDS = (
    "model_name", "individual_tpsl",
    "individual_tp_price", "individual_sl_price",
    "individual_tp_amount", "individual_sl_amount",
    "order_timestamp", "entry_timestamp",
    "session_mfe", "session_mae", "individual_fees",
)

# How long (ms) a WS/Platform update protects state from being overwritten by REST
_WS_PRIORITY_WINDOW_MS = 5000


def _fetch_rolling_peak_equity(
    account_id: int, window_days: int, current_equity: float
) -> float:
    """Query MAX(total_equity) from account_snapshots within the rolling window.

    Uses sync sqlite3 via the same path-resolution pattern as
    db_account_settings.  Returns *current_equity* if no snapshots exist
    in the window (defensive — DD = 0).
    """
    import sqlite3
    from datetime import timedelta

    try:
        from core.db_account_settings import _resolve_db_path
        db_path = _resolve_db_path(account_id)
    except KeyError:
        return current_equity

    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT MAX(total_equity) FROM account_snapshots "
            "WHERE account_id = ? AND snapshot_ts >= ?",
            (account_id, cutoff),
        ).fetchone()
        conn.close()
        db_peak = row[0] if row and row[0] is not None else 0.0
    except Exception:
        db_peak = 0.0

    return max(db_peak, current_equity)


def _check_dd_window_gaps(account_id: int, window_days: int) -> bool:
    """Return True if any gaps exist in the rolling DD window.

    Uses the equity gap detector to check for data holes.
    Returns False (no degradation) on any error.
    """
    try:
        from core.equity_gap_detector import detect_gaps
        from datetime import timedelta
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        since_ms = now_ms - window_days * 24 * 3600 * 1000
        gaps = detect_gaps(account_id, since_ms, now_ms)
        return len(gaps) > 0
    except Exception:
        return False


class DataCache:
    """Single-writer cache for all mutable trading state.

    Phase 1 scope: positions only.
    Later phases add: account_state, portfolio, market data caches.

    Lock model (asyncio single-threaded):
        self._lock guards position list mutations. Simple attribute writes
        (e.g. account_state.balance_usdt) between awaits are atomic in
        asyncio's cooperative model — no concurrent access possible.
        app_state._lock is being phased out; it must NEVER be acquired
        while self._lock is held (lock ordering: DataCache first).
    """

    def __init__(self, event_bus) -> None:
        self._lock = asyncio.Lock()
        self._event_bus = event_bus

        # ── Positions ────────────────────────────────────────────────────────
        self._positions: List[PositionInfo] = []
        self._positions_version = VersionedState()

        # ── Account state (Phase 4) ─────────────────────────────────────────
        self._account_version = VersionedState()

    # ── Read-only properties ─────────────────────────────────────────────────

    @property
    def positions(self) -> List[PositionInfo]:
        return self._positions

    # ── Conflict resolution ──────────────────────────────────────────────────

    def _should_accept_position_update(
        self, incoming_source: UpdateSource, incoming_ts_ms: int
    ) -> bool:
        """Decide whether an incoming update should overwrite current state.

        Rule: if the current state was set by WS or Platform within the
        priority window, reject REST updates (they're likely stale).
        Platform always wins (broker truth). WS always wins over REST.
        """
        cur = self._positions_version

        # Same source or first update — always accept
        if cur.source == UpdateSource.INTERNAL or cur.source == incoming_source:
            return True

        # Platform (broker truth) always accepted
        if incoming_source == UpdateSource.PLATFORM:
            return True

        # WS always accepted
        if incoming_source == UpdateSource.WS_USER:
            return True

        # REST trying to overwrite WS/Platform within priority window
        if incoming_source == UpdateSource.REST:
            if cur.source in (UpdateSource.WS_USER, UpdateSource.PLATFORM):
                age_ms = incoming_ts_ms - cur.timestamp_ms
                if age_ms < _WS_PRIORITY_WINDOW_MS:
                    log.debug(
                        "DataCache: rejecting REST position update — "
                        "WS/Platform updated %dms ago (window=%dms)",
                        age_ms, _WS_PRIORITY_WINDOW_MS,
                    )
                    return False

        return True

    def _advance_version(self, source: UpdateSource, ts_ms: int) -> None:
        v = self._positions_version
        v.sequence += 1
        v.source = source
        v.timestamp_ms = ts_ms
        v.applied_at = time.monotonic()

    # ── Position metadata preservation ───────────────────────────────────────

    @staticmethod
    def _preserve_metadata(new_pos: PositionInfo, old_pos: PositionInfo) -> None:
        """Copy engine-local metadata from old position to new one."""
        for attr in _PRESERVE_FIELDS:
            setattr(new_pos, attr, getattr(old_pos, attr))
        # Preserve plugin-sourced position_id (REST may not provide it)
        if old_pos.position_id and not new_pos.position_id:
            new_pos.position_id = old_pos.position_id
        # Preserve WS-sourced unrealized PnL if it is more recent than REST
        if old_pos.individual_unrealized != 0.0:
            new_pos.individual_unrealized = old_pos.individual_unrealized

    # ── Apply: full snapshot (REST / Platform) ───────────────────────────────

    async def apply_position_snapshot(
        self,
        source: UpdateSource,
        incoming: List[PositionInfo],
        ts_ms: int = 0,
        force: bool = False,
    ) -> Optional[PositionUpdateResult]:
        """Replace the full position list (used by REST fetch_positions and
        Platform bridge). Returns None if rejected by conflict resolution.

        Set force=True for fill-triggered refreshes that must always be
        accepted (e.g. _refresh_positions_after_fill).

        Metadata preservation, closure detection, and event publishing all
        happen inside a single lock acquisition — no TOCTOU race.
        """
        if ts_ms == 0:
            ts_ms = int(time.time() * 1000)

        async with self._lock:
            if not force and not self._should_accept_position_update(source, ts_ms):
                return None

            existing = {(p.ticker, p.direction): p for p in self._positions}
            new_keys = {(p.ticker, p.direction) for p in incoming}

            # Preserve engine-local metadata from existing positions
            for p in incoming:
                key = (p.ticker, p.direction)
                if key in existing:
                    self._preserve_metadata(p, existing[key])
                elif not p.entry_timestamp:
                    p.entry_timestamp = datetime.now(timezone.utc).isoformat()

            # Detect closed positions
            closed_syms: Set[str] = set()
            closed_positions: List[Dict[str, Any]] = []
            for (ticker, direction), old_pos in existing.items():
                if (ticker, direction) not in new_keys:
                    closed_syms.add(ticker)
                    closed_positions.append({
                        "ticker":          ticker,
                        "direction":       old_pos.direction,
                        "approx_close_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
                    })

            # Atomic replacement
            self._positions = sorted(incoming, key=lambda p: p.entry_timestamp or "")
            self._advance_version(source, ts_ms)
            self._recalculate_portfolio()

            result = PositionUpdateResult(
                accepted=True,
                closed_syms=closed_syms,
                new_syms={p.ticker for p in incoming
                          if (p.ticker, p.direction) not in existing},
                changed=True,
            )

        # Outside lock: publish events (publish is just Queue.put — O(1))
        from core.event_bus import CH_TRADE_CLOSED
        for cp in closed_positions:
            await self._event_bus.publish(CH_TRADE_CLOSED, cp)

        await self._event_bus.publish(
            "risk:positions_refreshed",
            {"trigger": source.value, "ts": datetime.now(timezone.utc).isoformat()},
        )

        # v2.4 Phase 5: dual-publish to Redis for SSE consumers
        try:
            from core.pubsub.bus import get_bus
            from core.pubsub.channels import position_channel
            from core.state import app_state as _as
            await get_bus().publish(position_channel(_as.active_account_id), {
                "trigger": source.value,
                "positions": [
                    {"symbol": p.ticker, "side": p.direction,
                     "size": p.contract_amount, "upnl": p.individual_unrealized}
                    for p in self._positions
                ],
                "ts": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass  # Redis unavailable — dual-publish is best-effort

        log.debug(
            "DataCache: snapshot applied (source=%s, count=%d, closed=%d, new=%d)",
            source.value, len(incoming), len(closed_syms), len(result.new_syms),
        )

        return result

    # ── Apply: incremental WS update ─────────────────────────────────────────

    async def apply_position_update_incremental(
        self,
        source: UpdateSource,
        norm_positions: list,
        balances: dict,
        ts_ms: int = 0,
    ) -> PositionUpdateResult:
        """Apply incremental position changes from a WS ACCOUNT_UPDATE.

        `norm_positions` are adapter-normalized position objects with fields:
            symbol, side, size, entry_price, unrealized_pnl

        `balances` dict may contain: wallet_balance, cross_wallet

        Always accepted (WS is authoritative for real-time updates).
        """
        from core.state import app_state

        if ts_ms == 0:
            ts_ms = int(time.time() * 1000)

        closed_syms: Set[str] = set()
        new_syms: Set[str] = set()
        closed_positions: List[Dict[str, Any]] = []

        async with self._lock:
            # Apply balance updates + advance account version so REST
            # won't overwrite fresher WS balance data within priority window
            if balances:
                app_state.account_state.balance_usdt = balances.get("wallet_balance", 0)
                # FE-9: total_equity NOT set here — cross_wallet is balance-only
                # (missing unrealized PnL). Sole equity authority is apply_mark_price()
                # which computes balance_usdt + total_unrealized correctly.
                self._advance_account_version(source, ts_ms)

            if norm_positions:
                existing = {(p.ticker, p.direction): p for p in self._positions}

                for np in norm_positions:
                    sym = np.symbol
                    key = (sym, np.side)

                    if np.size == 0:
                        # Position closed
                        if key in existing:
                            closed_syms.add(sym)
                            closed_positions.append({
                                "ticker":          sym,
                                "direction":       np.side,
                                "approx_close_ms": ts_ms,
                            })
                            # Remove from list
                            self._positions = [
                                p for p in self._positions
                                if (p.ticker, p.direction) != key
                            ]
                        continue

                    if key in existing:
                        # Update existing position in-place
                        pos = existing[key]
                        pos.individual_unrealized = np.unrealized_pnl
                        pos.contract_amount = np.size
                        pos.direction = np.side
                        if np.entry_price > 0:
                            pos.average = np.entry_price
                        mark = app_state.mark_price_cache.get(sym, 0)
                        if mark:
                            pos.position_value_usdt = np.size * mark
                    else:
                        # New position
                        mark = app_state.mark_price_cache.get(sym, np.entry_price) or np.entry_price
                        self._positions.append(PositionInfo(
                            ticker=sym,
                            direction=np.side,
                            contract_amount=np.size,
                            average=np.entry_price,
                            fair_price=mark,
                            individual_unrealized=np.unrealized_pnl,
                            position_value_usdt=np.size * mark,
                            entry_timestamp=datetime.now(timezone.utc).isoformat(),
                            sector=config.get_sector(sym),
                        ))
                        new_syms.add(sym)

            # Recalculate total unrealized from all positions
            app_state.account_state.total_unrealized = sum(
                p.individual_unrealized for p in self._positions
            )

            self._advance_version(source, ts_ms)
            self._recalculate_portfolio()

        # Outside lock: publish events
        from core.event_bus import CH_TRADE_CLOSED
        for cp in closed_positions:
            await self._event_bus.publish(CH_TRADE_CLOSED, cp)

        return PositionUpdateResult(
            accepted=True,
            closed_syms=closed_syms,
            new_syms=new_syms,
            changed=bool(norm_positions or balances),
        )

    # ── Portfolio recalculation ────────────────────────────────────────────────

    def _recalculate_portfolio(self) -> None:
        """Recalculate portfolio metrics from current positions + account state.

        Called inside apply_* methods after every state mutation so portfolio
        is always consistent with the positions list. Replaces the 7+ scattered
        calls to app_state.recalculate_portfolio() with a single call site.

        Never raises — logs errors so callers don't need try/except.
        """
        from core.state import app_state

        try:
            self._do_recalculate_portfolio(app_state)
        except Exception as exc:
            log.error("DataCache._recalculate_portfolio failed: %s", exc)

    def _do_recalculate_portfolio(self, app_state) -> None:
        """Inner portfolio recalculation (separated for error isolation)."""
        acc = app_state.account_state
        pos = self._positions
        prm = app_state.params
        pf  = app_state.portfolio

        total_equity = acc.total_equity

        # Total exposure = sum of all notional / equity
        if total_equity > 0:
            pf.total_exposure = sum(abs(p.position_value_usdt) for p in pos) / total_equity
        else:
            pf.total_exposure = 0.0

        # Correlated exposure per sector
        sector_net: Dict[str, float] = {}
        for p in pos:
            net = p.position_value_usdt if p.direction == "LONG" else -p.position_value_usdt
            sector_net[p.sector] = sector_net.get(p.sector, 0.0) + net
        pf.total_correlated_exposure = sector_net

        # Total TP / SL usdt
        acc.total_tp_usdt = sum(p.individual_tp_usdt for p in pos)
        acc.total_sl_usdt = sum(p.individual_sl_usdt for p in pos)

        # Daily PnL (current equity vs BOD equity)
        bod_eq = acc.bod_equity if acc.bod_equity > 0 else total_equity
        acc.daily_pnl         = acc.total_equity - bod_eq
        acc.daily_pnl_percent = acc.daily_pnl / bod_eq if bod_eq > 0 else 0.0

        # Weekly PnL
        sow_eq = acc.sow_equity if acc.sow_equity > 0 else total_equity
        pf.total_weekly_pnl = acc.total_equity - sow_eq
        pf.total_weekly_pnl_percent = pf.total_weekly_pnl / sow_eq if sow_eq > 0 else 0.0

        # Drawdown from BOD baseline
        max_eq = max(acc.max_total_equity, total_equity)
        acc.max_total_equity = max_eq
        if acc.min_total_equity > 0:
            acc.min_total_equity = min(acc.min_total_equity, total_equity)
        else:
            acc.min_total_equity = total_equity
        pf.drawdown = (max_eq - total_equity) / max_eq if max_eq > 0 else 0.0

        # Warnings / limits
        weekly_loss_pct = -pf.total_weekly_pnl_percent
        w_ratio = weekly_loss_pct / prm["max_w_loss_percent"] if prm["max_w_loss_percent"] > 0 else 0
        if weekly_loss_pct > 0 and w_ratio >= prm["weekly_loss_limit_pct"]:
            pf.weekly_pnl_state = "limit"
        elif weekly_loss_pct > 0 and w_ratio >= prm["weekly_loss_warning_pct"]:
            pf.weekly_pnl_state = "warning"
        else:
            pf.weekly_pnl_state = "ok"

        # ── Rolling DD (v2.4) ────────────────────────────────────────────────
        # Uses per-account thresholds from account_settings + rolling-window
        # peak from account_snapshots. Falls back to legacy intraday logic
        # if account_settings unavailable.
        try:
            from core.dd_state import dd_state_with_recovery
            from core.db_account_settings import get_account_settings
            aid = app_state.active_account_id

            settings = get_account_settings(aid)
            warn_t = settings.dd_warning_threshold
            limit_t = settings.dd_limit_threshold
            recov_t = settings.dd_recovery_threshold

            if warn_t is not None and limit_t is not None:
                # Check for data gaps in the rolling window
                pf.dd_degraded = _check_dd_window_gaps(aid, settings.dd_rolling_window_days)

                # Query true rolling-window peak from account_snapshots
                rolling_peak = _fetch_rolling_peak_equity(
                    aid, settings.dd_rolling_window_days, total_equity,
                )

                # Compute rolling drawdown
                rolling_dd = (rolling_peak - total_equity) / rolling_peak if rolling_peak > 0 else 0.0
                rolling_dd = max(rolling_dd, 0.0)
                pf.drawdown = rolling_dd

                # Evaluate state with recovery
                prev_state = app_state.dd_previous_states.get(aid, "ok")
                ep_peak = app_state.dd_episode_peaks.get(aid, rolling_dd)

                new_state, new_ep_peak = dd_state_with_recovery(
                    prev_state, rolling_dd, ep_peak, warn_t, limit_t, recov_t,
                )
                pf.dd_state = new_state
                app_state.dd_episode_peaks[aid] = new_ep_peak

                # Transition detection + event logging
                if new_state != prev_state:
                    app_state.dd_previous_states[aid] = new_state
                    # Reset shadow-event dedup + manual override when leaving limit
                    if prev_state == "limit" and new_state != "limit":
                        app_state.dd_would_have_blocked_logged.discard(aid)
                        app_state.dd_manually_unblocked.discard(aid)
                    try:
                        from core.event_log import log_event
                        log_event(aid, "dd_state_transition", {
                            "from": prev_state, "to": new_state,
                            "drawdown": round(rolling_dd, 6),
                            "peak_equity": round(rolling_peak, 2),
                            "window_days": settings.dd_rolling_window_days,
                        }, source="data_cache")
                    except Exception:
                        log.warning("dd_state_transition log failed", exc_info=True)
                    # v2.4 Phase 5: publish DD state change to Redis
                    try:
                        import asyncio as _aio
                        from core.pubsub.bus import get_bus
                        from core.pubsub.channels import dd_state_channel
                        _aio.get_event_loop().create_task(get_bus().publish(
                            dd_state_channel(aid), {
                                "from": prev_state, "to": new_state,
                                "drawdown": round(rolling_dd, 6),
                                "degraded": pf.dd_degraded,
                                "ts": datetime.now(timezone.utc).isoformat(),
                            }
                        ))
                    except Exception:
                        pass
                else:
                    app_state.dd_previous_states[aid] = new_state
            else:
                # Thresholds not configured — keep drawdown computed above, state ok
                pf.dd_state = "ok"
        except Exception:
            # Fallback: legacy intraday logic
            dd_ratio = pf.drawdown / prm["max_dd_percent"] if prm["max_dd_percent"] > 0 else 0
            if dd_ratio >= prm["max_dd_limit_pct"]:
                pf.dd_state = "limit"
            elif dd_ratio >= prm["max_dd_warning_pct"]:
                pf.dd_state = "warning"
            else:
                pf.dd_state = "ok"

        # v2.4 Phase 5: publish position_update on every recalc cycle
        # (covers continuous PnL drift from mark-price ticks between fills)
        try:
            import asyncio as _aio2
            from core.pubsub.bus import get_bus
            from core.pubsub.channels import position_channel
            _aio2.get_event_loop().create_task(get_bus().publish(
                position_channel(app_state.active_account_id), {
                    "trigger": "recalc_cycle",
                    "positions": [
                        {"symbol": p.ticker, "side": p.direction,
                         "size": p.contract_amount, "upnl": p.individual_unrealized}
                        for p in self._positions
                    ],
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            ))
        except Exception:
            pass  # best-effort — never break recalc

    # ── Account state: conflict resolution ──────────────────────────────────

    def _should_accept_account_update(
        self, incoming_source: UpdateSource, incoming_ts_ms: int
    ) -> bool:
        """Same rules as position updates — WS/Platform trump REST within window."""
        cur = self._account_version
        if cur.source == UpdateSource.INTERNAL or cur.source == incoming_source:
            return True
        if incoming_source in (UpdateSource.PLATFORM, UpdateSource.WS_USER):
            return True
        if incoming_source == UpdateSource.REST:
            if cur.source in (UpdateSource.WS_USER, UpdateSource.PLATFORM):
                age_ms = incoming_ts_ms - cur.timestamp_ms
                if age_ms < _WS_PRIORITY_WINDOW_MS:
                    log.debug(
                        "DataCache: rejecting REST account update — "
                        "WS/Platform updated %dms ago",
                        age_ms,
                    )
                    return False
        return True

    def _advance_account_version(self, source: UpdateSource, ts_ms: int) -> None:
        v = self._account_version
        v.sequence += 1
        v.source = source
        v.timestamp_ms = ts_ms
        v.applied_at = time.monotonic()

    # ── Account state: apply methods ─────────────────────────────────────────

    async def apply_account_update_rest(
        self,
        na,  # NormalizedAccount from adapter
        ts_ms: int = 0,
    ) -> bool:
        """Apply REST account balance snapshot. Returns False if rejected."""
        from core.state import app_state

        if ts_ms == 0:
            ts_ms = int(time.time() * 1000)

        async with self._lock:
            if not self._should_accept_account_update(UpdateSource.REST, ts_ms):
                return False

            acc = app_state.account_state
            acc.total_equity       = na.total_equity
            acc.available_margin   = na.available_margin
            acc.total_unrealized   = na.unrealized_pnl
            acc.total_margin_used  = na.initial_margin
            acc.total_margin_ratio = na.maint_margin
            acc.balance_usdt       = na.total_equity

            # Set BOD / SOW equity on first fetch if not set
            if acc.bod_equity == 0.0:
                acc.bod_equity       = acc.total_equity
                acc.max_total_equity = acc.total_equity
                acc.min_total_equity = acc.total_equity
                app_state.portfolio.dd_baseline_equity = acc.total_equity
            if acc.sow_equity == 0.0:
                acc.sow_equity = acc.total_equity

            self._advance_account_version(UpdateSource.REST, ts_ms)
            self._recalculate_portfolio()

        return True

    async def apply_account_update_platform(
        self,
        balance: float,
        total_equity: float,
        unrealized_pnl: float,
        available_margin: float,
        margin_ratio: float,
        ts_ms: int = 0,
    ) -> None:
        """Apply platform (Quantower) account state — broker truth, always accepted."""
        from core.state import app_state

        if ts_ms == 0:
            ts_ms = int(time.time() * 1000)

        async with self._lock:
            acc = app_state.account_state
            acc.balance_usdt       = balance
            acc.total_equity       = total_equity
            acc.total_unrealized   = unrealized_pnl
            acc.available_margin   = available_margin
            acc.total_margin_used  = max(0.0, total_equity - available_margin)
            acc.total_margin_ratio = margin_ratio

            self._advance_account_version(UpdateSource.PLATFORM, ts_ms)
            self._recalculate_portfolio()

    async def apply_bod_sow_equity(
        self,
        bod_equity: Optional[float] = None,
        bod_timestamp: Optional[str] = None,
        sow_equity: Optional[float] = None,
        sow_timestamp: Optional[str] = None,
    ) -> None:
        """Apply BOD/SOW equity derived from income history."""
        from core.state import app_state

        async with self._lock:
            acc = app_state.account_state
            if bod_equity is not None:
                acc.bod_equity = bod_equity
            if bod_timestamp is not None and acc.bod_timestamp == "":
                acc.bod_timestamp = bod_timestamp
            if sow_equity is not None:
                acc.sow_equity = sow_equity
            if sow_timestamp is not None and acc.sow_timestamp == "":
                acc.sow_timestamp = sow_timestamp

            self._recalculate_portfolio()

    # ── Market data: synchronous methods (Phase 5) ─────────────────────────
    #
    # No async lock needed — asyncio is single-threaded, sync functions run
    # to completion without yielding. These are called from WS message
    # handlers at high frequency (~1/sec per symbol for mark price).

    def apply_mark_price(self, symbol: str, mark: float) -> None:
        """Update mark price, recalculate PnL for matching positions,
        update account aggregates, and recalculate portfolio."""
        from core.state import app_state

        app_state.mark_price_cache[symbol] = mark

        for pos in self._positions:
            if pos.ticker != symbol:
                continue
            pos.fair_price = mark
            pos.position_value_usdt = abs(mark * pos.contract_amount * pos.contract_size)
            pos.position_value_asset = abs(pos.contract_amount * pos.contract_size)
            if pos.average > 0:
                if pos.direction == "LONG":
                    pos.individual_unrealized = (mark - pos.average) * pos.contract_amount
                else:
                    pos.individual_unrealized = (pos.average - mark) * pos.contract_amount
                unreal = pos.individual_unrealized
                if unreal > pos.session_mfe:
                    pos.session_mfe = round(unreal, 2)
                if pos.session_mae == 0.0 or unreal < pos.session_mae:
                    pos.session_mae = round(unreal, 2)

        acc = app_state.account_state
        acc.total_unrealized = sum(p.individual_unrealized for p in self._positions)
        acc.total_position_value = sum(p.position_value_usdt for p in self._positions)
        acc.total_margin_used = sum(p.individual_margin_used for p in self._positions)
        if acc.balance_usdt > 0:
            acc.total_equity = acc.balance_usdt + acc.total_unrealized
            acc.available_margin = acc.total_equity - acc.total_margin_used

        self._recalculate_portfolio()

    def apply_kline(self, symbol: str, candle: list) -> None:
        """Update OHLCV cache with a closed kline candle."""
        from core.state import app_state

        cache = app_state.ohlcv_cache.get(symbol, [])
        if cache and cache[-1][0] == candle[0]:
            cache[-1] = candle          # replace in-progress bar
        else:
            cache.append(candle)
            if len(cache) > config.ATR_FETCH_LIMIT + 10:
                cache = cache[-(config.ATR_FETCH_LIMIT + 10):]
        app_state.ohlcv_cache[symbol] = cache

    def apply_depth(self, symbol: str, bids: list, asks: list) -> None:
        """Update orderbook cache with a depth snapshot."""
        from core.state import app_state
        app_state.orderbook_cache[symbol] = {"bids": bids, "asks": asks}

    def evict_symbol_caches(self, active_tickers: set) -> None:
        """Remove cache entries for symbols no longer in any active position."""
        from core.state import app_state
        for sym in list(app_state.ohlcv_cache.keys()):
            if sym not in active_tickers:
                del app_state.ohlcv_cache[sym]
        for sym in list(app_state.orderbook_cache.keys()):
            if sym not in active_tickers:
                del app_state.orderbook_cache[sym]
        for sym in list(app_state.mark_price_cache.keys()):
            if sym not in active_tickers:
                del app_state.mark_price_cache[sym]

    # ── Utilities ────────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Reset all state (used on account switch).

        Safe to call synchronously — asyncio is cooperative, so no other
        coroutine can be mid-mutation between awaits. The lock only guards
        against concurrent async operations, which can't happen here.
        """
        self._positions = []
        self._positions_version = VersionedState()
        self._account_version = VersionedState()

    @property
    def last_update_monotonic(self) -> float:
        """Monotonic timestamp of last accepted position update."""
        return self._positions_version.applied_at
