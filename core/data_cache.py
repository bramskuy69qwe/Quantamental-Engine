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
                app_state.account_state.total_equity = balances.get("cross_wallet", 0)
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

        dd_ratio = pf.drawdown / prm["max_dd_percent"] if prm["max_dd_percent"] > 0 else 0
        if dd_ratio >= prm["max_dd_limit_pct"]:
            pf.dd_state = "limit"
        elif dd_ratio >= prm["max_dd_warning_pct"]:
            pf.dd_state = "warning"
        else:
            pf.dd_state = "ok"

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
