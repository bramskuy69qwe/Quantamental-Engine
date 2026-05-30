"""
OrdersMixin — write, read, and utility methods for orders / fills / closed_positions.

All queries operate on the 3 tables created in v2.2.2.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("database")


# P2.T5 close-time delta columns persisted on closed_positions. Computed
# in OrderManager._compute_close_deltas and written here; preserved across
# INSERT OR REPLACE recompute (T176/T232 wipe pattern). tp_drift_pct /
# sl_drift_pct (Phase 4.6), cumulative_amendment_count (Phase 4.3), and
# hold_time_planned_ms (no source) are intentionally NOT in this set —
# their owning tasks add them later.
_CLOSED_POS_DELTA_COLS = (
    "entry_px_delta_pct", "size_delta_pct", "exit_vs_target_pct",
    "realized_r", "planned_r", "hold_time_actual_ms",
)


def _escape_like(value: str) -> str:
    """MED-022 (Task 147): escape SQL LIKE wildcards (`%`, `_`) so a
    user-supplied prefix/search string is matched literally rather
    than as a pattern.

    Order matters: backslash MUST be doubled first; otherwise the
    backslashes we add for `%` and `_` get caught by the backslash
    pass and become double-escaped. Used with `LIKE ? ESCAPE '\\'`
    in the SQL clause.

    Module-local rather than a shared util — only one consumer
    (mark_stale_orders_canceled) so far. Promote to a shared module
    when a second consumer needs it. Per Task 142 convention
    (single-consumer helper extensions are over-engineering).
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class OrdersMixin:
    """Domain methods for the orders, fills, and closed_positions tables."""

    # ── Allowed sort columns (whitelist to prevent SQL injection) ────────────

    _ORDERS_SORT_COLS = {
        "updated_at_ms", "created_at_ms", "symbol", "side", "order_type",
        "quantity", "price", "stop_price", "status", "filled_qty",
    }
    _FILLS_SORT_COLS = {
        "timestamp_ms", "symbol", "side", "price", "quantity", "fee",
        "realized_pnl", "role", "direction", "slippage_actual",
    }
    _CLOSED_POS_SORT_COLS = {
        "exit_time_ms", "entry_time_ms", "symbol", "direction", "quantity",
        "entry_price", "exit_price", "realized_pnl", "net_pnl", "total_fees",
        "hold_time_ms", "exit_reason", "mfe", "mae", "tp_price", "sl_price",
    }

    # ── Write methods ───────────────────────────────────────────────────────

    async def upsert_order_batch(self, rows: List[Dict[str, Any]]) -> None:
        """Batch upsert orders in a single transaction."""
        if not rows:
            return
        now_ms = int(time.time() * 1000)
        sql = """
            INSERT INTO orders (
                account_id, exchange_order_id, terminal_order_id, client_order_id,
                symbol, side, order_type, status, price, stop_price,
                quantity, filled_qty, avg_fill_price, reduce_only,
                time_in_force, position_side, exchange_position_id,
                terminal_position_id, source, created_at_ms, updated_at_ms,
                last_seen_ms
            ) VALUES (
                :account_id, :exchange_order_id, :terminal_order_id, :client_order_id,
                :symbol, :side, :order_type, :status, :price, :stop_price,
                :quantity, :filled_qty, :avg_fill_price, :reduce_only,
                :time_in_force, :position_side, :exchange_position_id,
                :terminal_position_id, :source, :created_at_ms, :updated_at_ms,
                :last_seen_ms
            )
            ON CONFLICT(account_id, exchange_order_id) DO UPDATE SET
                terminal_order_id   = excluded.terminal_order_id,
                client_order_id     = excluded.client_order_id,
                status              = excluded.status,
                price               = excluded.price,
                stop_price          = excluded.stop_price,
                quantity            = excluded.quantity,
                filled_qty          = excluded.filled_qty,
                avg_fill_price      = excluded.avg_fill_price,
                order_type          = excluded.order_type,
                reduce_only         = excluded.reduce_only,
                time_in_force       = excluded.time_in_force,
                position_side       = excluded.position_side,
                exchange_position_id = excluded.exchange_position_id,
                updated_at_ms       = excluded.updated_at_ms,
                last_seen_ms        = excluded.last_seen_ms
            WHERE excluded.updated_at_ms >= orders.updated_at_ms
               OR orders.updated_at_ms IS NULL
        """
        try:
            async with self._conn.cursor() as cur:
                for row in rows:
                    await cur.execute(sql, {
                        "account_id":           row.get("account_id", 1),
                        "exchange_order_id":    row.get("exchange_order_id"),
                        "terminal_order_id":    row.get("terminal_order_id", ""),
                        "client_order_id":      row.get("client_order_id", ""),
                        "symbol":               row.get("symbol", ""),
                        "side":                 row.get("side", ""),
                        "order_type":           row.get("order_type", ""),
                        "status":               row.get("status", "new"),
                        "price":                row.get("price", 0),
                        "stop_price":           row.get("stop_price", 0),
                        "quantity":             row.get("quantity", 0),
                        "filled_qty":           row.get("filled_qty", 0),
                        "avg_fill_price":       row.get("avg_fill_price", 0),
                        # `or 0` coerces a present-but-None reduce_only to 0:
                        # int(None) would raise and (inside this batch loop's
                        # try/except) silently swallow the ENTIRE order batch.
                        # MEXC's NormalizedOrder leaves reduce_only=None (its
                        # fetch_open_orders never sets it), so a MEXC snapshot
                        # would otherwise lose every order (T236 review).
                        "reduce_only":          int(row.get("reduce_only") or 0),
                        "time_in_force":        row.get("time_in_force", ""),
                        "position_side":        row.get("position_side", ""),
                        "exchange_position_id": row.get("exchange_position_id", ""),
                        "terminal_position_id": row.get("terminal_position_id", ""),
                        "source":               row.get("source", ""),
                        "created_at_ms":        row.get("created_at_ms", 0),
                        "updated_at_ms":        row.get("updated_at_ms", now_ms),
                        "last_seen_ms":         now_ms,
                    })
            await self._conn.commit()
        except Exception:
            log.exception("upsert_order_batch failed")

    async def upsert_fill(self, row: Dict[str, Any]) -> None:
        """Insert or update a single fill (deduped by exchange_fill_id)."""
        sql = """
            INSERT INTO fills (
                account_id, exchange_fill_id, terminal_fill_id, exchange_order_id,
                symbol, side, direction, price, quantity, fee, fee_asset,
                exchange_position_id, terminal_position_id, is_close,
                realized_pnl, role, source, timestamp_ms
            ) VALUES (
                :account_id, :exchange_fill_id, :terminal_fill_id, :exchange_order_id,
                :symbol, :side, :direction, :price, :quantity, :fee, :fee_asset,
                :exchange_position_id, :terminal_position_id, :is_close,
                :realized_pnl, :role, :source, :timestamp_ms
            )
            ON CONFLICT(account_id, exchange_fill_id) DO UPDATE SET
                terminal_fill_id     = excluded.terminal_fill_id,
                terminal_position_id = excluded.terminal_position_id,
                price                = excluded.price,
                quantity             = excluded.quantity,
                fee                  = excluded.fee,
                fee_asset            = excluded.fee_asset,
                role                 = excluded.role,
                realized_pnl         = excluded.realized_pnl,
                timestamp_ms         = excluded.timestamp_ms
        """
        try:
            await self._conn.execute(sql, {
                "account_id":           row.get("account_id", 1),
                "exchange_fill_id":     row.get("exchange_fill_id"),
                "terminal_fill_id":     row.get("terminal_fill_id", ""),
                "exchange_order_id":    row.get("exchange_order_id", ""),
                "symbol":               row.get("symbol", ""),
                "side":                 row.get("side", ""),
                "direction":            row.get("direction", ""),
                "price":                row.get("price", 0),
                "quantity":             row.get("quantity", 0),
                "fee":                  row.get("fee", 0),
                "fee_asset":            row.get("fee_asset", "USDT"),
                "exchange_position_id": row.get("exchange_position_id", ""),
                "terminal_position_id": row.get("terminal_position_id", ""),
                "is_close":             int(row.get("is_close", False)),
                "realized_pnl":         row.get("realized_pnl", 0),
                "role":                 row.get("role", ""),
                "source":               row.get("source", ""),
                "timestamp_ms":         row.get("timestamp_ms", 0),
            })
            await self._conn.commit()
        except Exception:
            log.exception("upsert_fill failed")

    async def insert_closed_position(
        self, row: Dict[str, Any], commit: bool = True,
    ) -> None:
        """Insert a closed_positions row (deduped by position_id + exit_time).

        Uses REPLACE so a re-computed close row (e.g. after late fill) wins
        over the earlier version rather than being silently dropped.

        If tp_price/sl_price are not provided but calc_id is, resolves them
        from pre_trade_log automatically (v2.4 Task 69).

        ``commit`` (T191 / Phase 0.0.6 audit B1): default True for
        backward compat with all existing callers (real-time close-row
        builder, exchange_history_backfill, etc.) — each insert commits
        per-call. Set ``False`` when the caller is batching multiple
        inserts inside a single explicit transaction (e.g.
        ``scripts/rebuild_closed_positions.py`` wraps DELETE +
        INSERT-loop in one transaction so a mid-script kill rolls
        back to a consistent state instead of leaving the DB wiped).
        The caller is then responsible for the final commit / rollback.
        """
        # Task 168 (FE-MED-017 defense-in-depth): reject pollution-shaped
        # writes — entry_price <= 0 while quantity > 0 AND exit_price > 0
        # is the exact shape of the 278 pre-prod BTCUSDT test-fixture
        # rows the audit flagged. A real fill never produces this shape:
        # entry_price comes from the position's average-fill computation
        # upstream and is always positive for any executed quantity.
        # The T167 dual-P&L replay set excludes pollution by construction
        # (calc_id + regime_multiplier guards), but adding the write-time
        # guard at the canonical insert path means future pollution
        # paths can't reach EITHER surface even if they bypass calc_id.
        # log.warning surfaces the rejected write so the operator sees
        # the drop (vs silent).
        entry = float(row.get("entry_price", 0) or 0)
        qty = float(row.get("quantity", 0) or 0)
        exit_p = float(row.get("exit_price", 0) or 0)
        if entry <= 0 and qty > 0 and exit_p > 0:
            log.warning(
                "T168 FE-MED-017 reject: closed_position has pollution "
                "shape (entry_price=%r, quantity=%r, exit_price=%r, "
                "symbol=%r) — refusing write; a real fill never produces "
                "this combination",
                entry, qty, exit_p, row.get("symbol", ""),
            )
            return

        # Resolve tp_price/sl_price from pre_trade_log if not explicitly provided.
        # T234 note: calc_id is bound UNCONDITIONALLY below (not carried
        # forward across REPLACE like lifecycle_id / mfe / mae / the delta
        # columns). That asymmetry is intentional — every close path derives
        # calc_id deterministically and always supplies it (the live builder
        # → junction primary or earliest-fill fallback; backfill/rebuild →
        # earliest-fill), so there is no "caller omitted it" case to carry
        # forward, and cross-path REPLACEs use non-colliding 'rebuilt:' tpids.
        # tp_price/sl_price auto-resolve keys off this same calc_id (so they
        # follow the primary post-T2.6, by design).
        calc_id = row.get("calc_id")
        tp_price = row.get("tp_price")
        sl_price = row.get("sl_price")
        if calc_id and tp_price is None and sl_price is None:
            try:
                async with self._conn.execute(
                    "SELECT tp_price, sl_price FROM pre_trade_log WHERE calc_id = ? LIMIT 1",
                    (calc_id,),
                ) as cur:
                    ptl = await cur.fetchone()
                    if ptl:
                        tp_price = ptl["tp_price"] if ptl["tp_price"] else None
                        sl_price = ptl["sl_price"] if ptl["sl_price"] else None
            except Exception:
                pass  # non-critical — columns stay NULL

        # T176: preserve reconciler-owned columns across INSERT OR REPLACE.
        # SQLite's REPLACE = DELETE-THEN-INSERT — any column omitted from
        # the INSERT-VALUES list resets to its schema default. Previously
        # `backfill_completed` was omitted entirely → every REPLACE wiped
        # the reconciler's flag back to 0, and any caller (like real-time
        # close-row builder) that passed mfe=0/mae=0 also wiped the
        # reconciler's computed values. Result: multi-fill closes that
        # triggered the close-row builder twice could race the reconciler
        # — first run computed MFE over a partial window, REPLACE then
        # wiped it, second run computed over the full window... but only
        # if the reconciler's get_uncalculated_closed_positions caught
        # the wiped row before the next REPLACE. Net effect on operator's
        # screen: MFE values below the math-required floor of |gross_pnl|.
        # Fix: read existing row's reconciler columns; preserve them
        # explicitly in the new INSERT if backfill was already done.
        # Caller-supplied mfe/mae still win when reconciler hasn't run
        # (exchange_history backfill path passes computed values for
        # rows it owns; those get preserved if a later REPLACE has
        # mfe=0/mae=0/backfill=0 defaults).
        preserved_mfe = row.get("mfe", 0)
        preserved_mae = row.get("mae", 0)
        preserved_backfill = 0
        # T232 (T176-class): lifecycle_id is omitted from the INSERT below,
        # so an INSERT OR REPLACE recompute (DELETE+INSERT on the UNIQUE
        # natural key) would reset a previously-stamped lifecycle_id to
        # DEFAULT NULL — the same data-loss shape T176 fixed for mfe/mae.
        # The Phase-2 backfill stamps closed_positions.lifecycle_id on
        # historical rows TODAY, so re-running exchange_history_backfill
        # would wipe it without this preservation. Carry forward a
        # caller-supplied value if present, else an existing stamped one.
        preserved_lifecycle = row.get("lifecycle_id")
        # T232/T2.5 (T176-class): the P2.T5 close-time delta columns are
        # likewise omitted-then-wiped by an INSERT OR REPLACE recompute
        # that doesn't recompute them (e.g. exchange_history_backfill
        # REPLACEing a live-built row). _build_close_row_for_fill supplies
        # them deterministically; carry forward an existing value when a
        # caller doesn't (caller-wins).
        preserved_deltas = {c: row.get(c) for c in _CLOSED_POS_DELTA_COLS}
        try:
            async with self._conn.execute(
                "SELECT mfe, mae, backfill_completed, lifecycle_id, "
                + ", ".join(_CLOSED_POS_DELTA_COLS)
                + " FROM closed_positions "
                "WHERE account_id = ? AND terminal_position_id = ? "
                "AND exit_time_ms = ? LIMIT 1",
                (row.get("account_id", 1),
                 row.get("terminal_position_id", ""),
                 row.get("exit_time_ms", 0)),
            ) as cur:
                existing = await cur.fetchone()
                if existing and existing["backfill_completed"]:
                    # Reconciler ran — its values are authoritative.
                    preserved_mfe = existing["mfe"]
                    preserved_mae = existing["mae"]
                    preserved_backfill = existing["backfill_completed"]
                # Preserve a stamped lifecycle_id unless the caller is
                # supplying one (caller wins on first insert / forward seal).
                if existing and existing["lifecycle_id"] and not preserved_lifecycle:
                    preserved_lifecycle = existing["lifecycle_id"]
                # Same caller-wins-else-carry-forward for the delta columns.
                if existing:
                    for c in _CLOSED_POS_DELTA_COLS:
                        if preserved_deltas[c] is None and existing[c] is not None:
                            preserved_deltas[c] = existing[c]
        except Exception:
            pass  # if the read fails, fall through to caller-supplied values

        sql = """
            INSERT OR REPLACE INTO closed_positions (
                account_id, exchange_position_id, terminal_position_id,
                symbol, direction, quantity, entry_price, exit_price,
                entry_time_ms, exit_time_ms, realized_pnl, total_fees,
                net_pnl, funding_fees, mfe, mae, backfill_completed, hold_time_ms,
                exit_reason, model_name, notes,
                shortfall_entry, shortfall_exit, source, calc_id,
                tp_price, sl_price, lifecycle_id,
                entry_px_delta_pct, size_delta_pct, exit_vs_target_pct,
                realized_r, planned_r, hold_time_actual_ms
            ) VALUES (
                :account_id, :exchange_position_id, :terminal_position_id,
                :symbol, :direction, :quantity, :entry_price, :exit_price,
                :entry_time_ms, :exit_time_ms, :realized_pnl, :total_fees,
                :net_pnl, :funding_fees, :mfe, :mae, :backfill_completed, :hold_time_ms,
                :exit_reason, :model_name, :notes,
                :shortfall_entry, :shortfall_exit, :source, :calc_id,
                :tp_price, :sl_price, :lifecycle_id,
                :entry_px_delta_pct, :size_delta_pct, :exit_vs_target_pct,
                :realized_r, :planned_r, :hold_time_actual_ms
            )
        """
        try:
            await self._conn.execute(sql, {
                "account_id":           row.get("account_id", 1),
                "exchange_position_id": row.get("exchange_position_id", ""),
                "terminal_position_id": row.get("terminal_position_id", ""),
                "symbol":               row.get("symbol", ""),
                "direction":            row.get("direction", ""),
                "quantity":             row.get("quantity", 0),
                "entry_price":          row.get("entry_price", 0),
                "exit_price":           row.get("exit_price", 0),
                "entry_time_ms":        row.get("entry_time_ms", 0),
                "exit_time_ms":         row.get("exit_time_ms", 0),
                "realized_pnl":         row.get("realized_pnl", 0),
                "total_fees":           row.get("total_fees", 0),
                "net_pnl":              row.get("net_pnl", 0),
                "funding_fees":         row.get("funding_fees", 0),
                "mfe":                  preserved_mfe,
                "mae":                  preserved_mae,
                "backfill_completed":   preserved_backfill,
                "hold_time_ms":         row.get("hold_time_ms", 0),
                "exit_reason":          row.get("exit_reason", ""),
                "model_name":           row.get("model_name", ""),
                "notes":                row.get("notes", ""),
                "shortfall_entry":      row.get("shortfall_entry", 0),
                "shortfall_exit":       row.get("shortfall_exit", 0),
                "source":               row.get("source", ""),
                "calc_id":              calc_id,
                "tp_price":             tp_price,
                "sl_price":             sl_price,
                "lifecycle_id":         preserved_lifecycle,
                **preserved_deltas,
            })
            if commit:
                await self._conn.commit()
        except Exception:
            log.exception("insert_closed_position failed")
            # T191 audit B1: batched-transaction callers (commit=False)
            # need failures to PROPAGATE so the outer transaction can
            # roll back. Default-commit callers retain the historical
            # fail-silent behavior — a real-time close-row write that
            # fails doesn't crash the WS event loop.
            if not commit:
                raise

    async def update_order_from_fill(
        self, exchange_order_id: str, fill: Dict[str, Any]
    ) -> None:
        """Best-effort update of parent order's filled_qty/avg_fill_price from a fill."""
        if not exchange_order_id:
            return
        now_ms = int(time.time() * 1000)
        try:
            # avg_fill_price must be computed BEFORE filled_qty is incremented,
            # so we compute it first and set filled_qty second.
            await self._conn.execute(
                """UPDATE orders SET
                    avg_fill_price = CASE
                        WHEN filled_qty = 0 THEN :price
                        ELSE (avg_fill_price * filled_qty + :price * :qty)
                             / (filled_qty + :qty)
                    END,
                    filled_qty     = filled_qty + :qty,
                    updated_at_ms  = :now_ms
                WHERE exchange_order_id = :oid AND account_id = :aid""",
                {
                    "qty":    fill.get("quantity", 0),
                    "price":  fill.get("price", 0),
                    "now_ms": now_ms,
                    "oid":    exchange_order_id,
                    "aid":    fill.get("account_id", 1),
                },
            )
            await self._conn.commit()
        except Exception:
            log.warning("update_order_from_fill: order %s not found", exchange_order_id)

    async def upsert_fill_and_update_order(
        self, row: Dict[str, Any], exchange_order_id: str = "",
    ) -> None:
        """Upsert fill + update parent order in a SINGLE commit.

        Replaces the old pattern of upsert_fill() + update_order_from_fill()
        which did 2 separate commits per fill event.

        Phase 0.0.4 callers may pass a synthetic ``exchange_fill_id`` of
        the form ``synth:{tradeId}:open`` for the open portion of a
        reversal-split. The UNIQUE constraint on
        ``(account_id, exchange_fill_id)`` treats these as distinct
        rows (the ``synth:`` prefix can never collide with Binance's
        numeric tradeIds), and the parent-order qty/avg-price update
        sums correctly across the two portions since both share the
        same ``exchange_order_id``.
        """
        fill_sql = """
            INSERT INTO fills (
                account_id, exchange_fill_id, terminal_fill_id, exchange_order_id,
                symbol, side, direction, price, quantity, fee, fee_asset,
                exchange_position_id, terminal_position_id, is_close,
                realized_pnl, role, source, timestamp_ms
            ) VALUES (
                :account_id, :exchange_fill_id, :terminal_fill_id, :exchange_order_id,
                :symbol, :side, :direction, :price, :quantity, :fee, :fee_asset,
                :exchange_position_id, :terminal_position_id, :is_close,
                :realized_pnl, :role, :source, :timestamp_ms
            )
            ON CONFLICT(account_id, exchange_fill_id) DO UPDATE SET
                terminal_fill_id     = excluded.terminal_fill_id,
                terminal_position_id = excluded.terminal_position_id,
                price                = excluded.price,
                quantity             = excluded.quantity,
                fee                  = excluded.fee,
                fee_asset            = excluded.fee_asset,
                role                 = excluded.role,
                realized_pnl         = excluded.realized_pnl,
                timestamp_ms         = excluded.timestamp_ms
        """
        try:
            await self._conn.execute(fill_sql, {
                "account_id":           row.get("account_id", 1),
                "exchange_fill_id":     row.get("exchange_fill_id"),
                "terminal_fill_id":     row.get("terminal_fill_id", ""),
                "exchange_order_id":    row.get("exchange_order_id", ""),
                "symbol":               row.get("symbol", ""),
                "side":                 row.get("side", ""),
                "direction":            row.get("direction", ""),
                "price":                row.get("price", 0),
                "quantity":             row.get("quantity", 0),
                "fee":                  row.get("fee", 0),
                "fee_asset":            row.get("fee_asset", "USDT"),
                "exchange_position_id": row.get("exchange_position_id", ""),
                "terminal_position_id": row.get("terminal_position_id", ""),
                "is_close":             int(row.get("is_close", False)),
                "realized_pnl":         row.get("realized_pnl", 0),
                "role":                 row.get("role", ""),
                "source":               row.get("source", ""),
                "timestamp_ms":         row.get("timestamp_ms", 0),
            })
            if exchange_order_id:
                now_ms = int(time.time() * 1000)
                await self._conn.execute(
                    """UPDATE orders SET
                        avg_fill_price = CASE
                            WHEN filled_qty = 0 THEN :price
                            ELSE (avg_fill_price * filled_qty + :price * :qty)
                                 / (filled_qty + :qty)
                        END,
                        filled_qty     = filled_qty + :qty,
                        updated_at_ms  = :now_ms
                    WHERE exchange_order_id = :oid AND account_id = :aid""",
                    {
                        "qty":    row.get("quantity", 0),
                        "price":  row.get("price", 0),
                        "now_ms": now_ms,
                        "oid":    exchange_order_id,
                        "aid":    row.get("account_id", 1),
                    },
                )
            await self._conn.commit()
        except Exception:
            log.exception("upsert_fill_and_update_order failed")

    async def mark_stale_orders_canceled(
        self, account_id: int, active_ids: List[str],
        *, allow_cancel_all: bool = False,
        exclude_prefix: str = "",
        only_prefix: str = "",
    ) -> int:
        """Mark active orders NOT in snapshot as canceled. Returns count affected.

        If active_ids is empty and allow_cancel_all is False, skip cancellation
        to avoid mass-cancel on empty/broken snapshots.

        exclude_prefix: skip orders whose exchange_order_id starts with this prefix
            (e.g., 'algo:' to protect algo orders during basic snapshot processing)
        only_prefix: only affect orders whose exchange_order_id starts with this prefix
            (e.g., 'algo:' to scope stale-cancel to algo orders only)
        """
        now_ms = int(time.time() * 1000)
        # MED-022 (Task 101): build the LIKE clause via ? placeholder rather
        # than f-string interpolation. The old form wrapped exclude_prefix in
        # single-quote SQL literals via f-string substitution, making any
        # quote in the prefix terminate the literal early and inject arbitrary SQL.
        # Callers today pass only hardcoded prefixes ("algo:"), so no current
        # exploit — defense-in-depth against future user-supplied prefixes.
        #
        # MED-022 (Task 147): close the second half — wildcard escape.
        # Task 101 left `%` and `_` in the prefix UNESCAPED (acting as
        # LIKE wildcards). For a hardcoded "algo:" prefix this is fine;
        # for any future user-supplied prefix, `%foo` or `_bar` would
        # match unintended rows. Now escaped via `_escape_like()` +
        # `ESCAPE '\'` clause — the prefix is matched literally; the
        # trailing `%` (appended after escaping) remains the
        # legitimate prefix-match wildcard.
        scope_clause = ""
        scope_params: list = []
        if exclude_prefix:
            scope_clause = " AND exchange_order_id NOT LIKE ? ESCAPE '\\'"
            scope_params.append(f"{_escape_like(exclude_prefix)}%")
        elif only_prefix:
            scope_clause = " AND exchange_order_id LIKE ? ESCAPE '\\'"
            scope_params.append(f"{_escape_like(only_prefix)}%")

        if not active_ids:
            if not allow_cancel_all:
                log.debug("mark_stale_orders_canceled: empty active_ids, skipping")
                return 0
            cur = await self._conn.execute(
                "UPDATE orders SET status='canceled', updated_at_ms=? "
                f"WHERE account_id=? AND status IN ('new','partially_filled'){scope_clause}",
                [now_ms, account_id] + scope_params,
            )
            await self._conn.commit()
            return cur.rowcount

        placeholders = ",".join("?" for _ in active_ids)
        cur = await self._conn.execute(
            f"UPDATE orders SET status='canceled', updated_at_ms=? "
            f"WHERE account_id=? AND status IN ('new','partially_filled') "
            f"AND exchange_order_id NOT IN ({placeholders}){scope_clause}",
            [now_ms, account_id] + active_ids + scope_params,
        )
        await self._conn.commit()
        return cur.rowcount

    async def mark_stale_orders(
        self, account_id: int, stale_threshold_ms: int = 300_000
    ) -> int:
        """Mark active orders not seen in stale_threshold_ms as canceled."""
        now_ms = int(time.time() * 1000)
        cutoff = now_ms - stale_threshold_ms
        cur = await self._conn.execute(
            "UPDATE orders SET status='canceled', updated_at_ms=? "
            "WHERE account_id=? AND status IN ('new','partially_filled') "
            "AND last_seen_ms < ? AND last_seen_ms > 0",
            (now_ms, account_id, cutoff),
        )
        await self._conn.commit()
        return cur.rowcount

    # ── Read methods (paginated) ────────────────────────────────────────────

    _ALLOWED_TABLES = {"orders", "fills", "closed_positions"}

    async def _paginated_order_query(
        self,
        table: str,
        ts_col: str,
        allowed_sort: set,
        account_id: int,
        page: int = 1,
        per_page: int = 25,
        sort_by: str = "",
        sort_dir: str = "DESC",
        search: str = "",
        date_from_ms: Optional[int] = None,
        date_to_ms: Optional[int] = None,
        extra_where: str = "",
        extra_params: Optional[list] = None,
    ) -> Tuple[List[Dict], int]:
        """Paginated query for order-domain tables (ms-based timestamps)."""
        if table not in self._ALLOWED_TABLES:
            raise ValueError(f"Invalid table: {table}")
        clauses: list = ["account_id = ?"]
        params: list = [account_id]

        if extra_where:
            clauses.append(extra_where)
            if extra_params:
                params.extend(extra_params)

        if date_from_ms is not None:
            clauses.append(f"{ts_col} >= ?")
            params.append(date_from_ms)
        if date_to_ms is not None:
            clauses.append(f"{ts_col} <= ?")
            params.append(date_to_ms)
        if search:
            clauses.append("(symbol LIKE ?)")
            params.append(f"%{search}%")

        where = " WHERE " + " AND ".join(clauses)

        if sort_by not in allowed_sort:
            sort_by = ts_col
        if sort_dir not in ("ASC", "DESC"):
            sort_dir = "DESC"

        async with self._conn.execute(
            f"SELECT COUNT(*) FROM {table}{where}", params
        ) as cur:
            total = (await cur.fetchone())[0]

        offset = (max(page, 1) - 1) * per_page
        async with self._conn.execute(
            f"SELECT * FROM {table}{where} ORDER BY {sort_by} {sort_dir} LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows], total

    async def query_open_orders(
        self, account_id: int, page: int = 1, per_page: int = 25,
        sort_by: str = "created_at_ms", sort_dir: str = "DESC", search: str = "",
    ) -> Tuple[List[Dict], int]:
        """Open Orders tab — active orders only."""
        return await self._paginated_order_query(
            "orders", "created_at_ms", self._ORDERS_SORT_COLS,
            account_id, page, per_page, sort_by, sort_dir, search,
            extra_where="status IN ('new','partially_filled')",
        )

    async def query_order_history(
        self, account_id: int, page: int = 1, per_page: int = 25,
        sort_by: str = "updated_at_ms", sort_dir: str = "DESC", search: str = "",
        date_from_ms: Optional[int] = None, date_to_ms: Optional[int] = None,
    ) -> Tuple[List[Dict], int]:
        """Order History tab — all statuses."""
        return await self._paginated_order_query(
            "orders", "updated_at_ms", self._ORDERS_SORT_COLS,
            account_id, page, per_page, sort_by, sort_dir, search,
            date_from_ms, date_to_ms,
        )

    async def count_needs_link(self, account_id: int) -> int:
        """P3.T4 (plan §3 row 3.8): count orders in the manual-link review
        queue — link_status in (NEEDS_MANUAL_REVIEW, UNLINKED) — for the
        Needs-Link nav badge counter. Cheap COUNT (indexed-ish, no row build)."""
        async with self._conn.execute(
            "SELECT COUNT(*) FROM orders "
            "WHERE account_id=? AND link_status IN ('NEEDS_MANUAL_REVIEW', 'UNLINKED')",
            (account_id,),
        ) as cur:
            return (await cur.fetchone())[0]

    async def query_fills(
        self, account_id: int, page: int = 1, per_page: int = 25,
        sort_by: str = "timestamp_ms", sort_dir: str = "DESC", search: str = "",
        date_from_ms: Optional[int] = None, date_to_ms: Optional[int] = None,
    ) -> Tuple[List[Dict], int]:
        """Trade History (fills) tab."""
        return await self._paginated_order_query(
            "fills", "timestamp_ms", self._FILLS_SORT_COLS,
            account_id, page, per_page, sort_by, sort_dir, search,
            date_from_ms, date_to_ms,
        )

    async def query_closed_positions(
        self, account_id: int, page: int = 1, per_page: int = 25,
        sort_by: str = "exit_time_ms", sort_dir: str = "DESC", search: str = "",
        date_from_ms: Optional[int] = None, date_to_ms: Optional[int] = None,
    ) -> Tuple[List[Dict], int]:
        """Position History tab."""
        return await self._paginated_order_query(
            "closed_positions", "exit_time_ms", self._CLOSED_POS_SORT_COLS,
            account_id, page, per_page, sort_by, sort_dir, search,
            date_from_ms, date_to_ms,
        )

    # ── Utility methods ─────────────────────────────────────────────────────

    async def get_active_orders_map(self, account_id: int) -> Dict[str, Dict]:
        """Return {exchange_order_id: row} for all active orders."""
        async with self._conn.execute(
            "SELECT * FROM orders WHERE account_id=? "
            "AND status IN ('new','partially_filled')",
            (account_id,),
        ) as cur:
            rows = await cur.fetchall()
            return {r["exchange_order_id"]: dict(r) for r in rows if r["exchange_order_id"]}

    async def query_open_orders_all(self, account_id: int) -> List[Dict]:
        """Unpaginated list of all active orders (for cache rebuild)."""
        async with self._conn.execute(
            "SELECT * FROM orders WHERE account_id=? "
            "AND status IN ('new','partially_filled') "
            "ORDER BY created_at_ms DESC",
            (account_id,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_position_fees(self, account_id: int, terminal_position_id: str) -> float:
        """SUM(fee) for all fills of a position. Never accumulate in cache."""
        async with self._conn.execute(
            "SELECT COALESCE(SUM(fee), 0) FROM fills "
            "WHERE account_id=? AND terminal_position_id=?",
            (account_id, terminal_position_id),
        ) as cur:
            row = await cur.fetchone()
            return float(row[0]) if row else 0.0

    async def get_position_fills(
        self, account_id: int, pos_id: str, symbol: str,
        direction: str, is_close: Optional[bool] = None,
    ) -> List[Dict]:
        """Get fills for a position by strict ``terminal_position_id`` match.

        Phase 0.0.5 (T188 / T178 Layer 3): the previous
        ``(COALESCE(terminal_position_id, '') = '' AND symbol=? AND
        direction=?)`` fallback arm returned fills from MULTIPLE
        distinct positions over time when pos_id was empty (the
        Binance-only case where the engine's own WS path never
        populates terminal_position_id). That cross-position
        contamination produced nonsense entry_price + entry_time on
        live-built closed_positions rows.

        Empty ``pos_id`` now returns ``[]``. Callers that need to
        resolve opens without a pos_id should use
        ``core.position_grouping.find_opens_for_position_close_at``,
        which walks fills chronologically per (account, symbol,
        direction) and tracks the actual lifecycle of each logical
        position.

        ``symbol`` and ``direction`` parameters are retained in the
        signature for backward compatibility with existing callers
        but are no longer used by the SQL.
        """
        if not pos_id:
            return []
        sql = "SELECT * FROM fills WHERE account_id=? AND terminal_position_id=?"
        params: list = [account_id, pos_id]
        if is_close is not None:
            sql += " AND is_close=?"
            params.append(int(is_close))
        sql += " ORDER BY timestamp_ms ASC"
        async with self._conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_fills_for_symbol_direction(
        self, account_id: int, symbol: str, direction: str,
        since_ms: Optional[int] = None,
    ) -> List[Dict]:
        """Get all fills for ``(account_id, symbol, direction)`` chronologically.

        Phase 0.0.5 helper: feeds
        ``core.position_grouping.find_opens_for_position_close_at``
        when the caller needs to resolve opens without a
        ``terminal_position_id`` (Binance one-way path).

        ``since_ms`` is an optional lower bound to cap the scan window
        (callers that know the position is recent can pass e.g.
        ``close_ts_ms - 90*86400*1000``).

        Performance note (T189 audit M1): no covering index exists for
        ``(account_id, symbol, direction, timestamp_ms)``. SQLite uses
        ``idx_fills_ts (account_id, timestamp_ms)`` to narrow by
        account + time, then filters symbol+direction in-memory. For
        an account with thousands of fills per (symbol, direction)
        this becomes O(N) per call. Fine for current scale (live DB
        has ~350 fills total). Migrate to a covering index when an
        account approaches 10k+ fills per symbol — e.g.
        ``CREATE INDEX idx_fills_acct_sym_dir
            ON fills(account_id, symbol, direction, timestamp_ms)``.
        """
        sql = (
            "SELECT * FROM fills WHERE account_id=? AND symbol=? AND direction=?"
        )
        params: list = [account_id, symbol, direction]
        if since_ms is not None:
            sql += " AND timestamp_ms >= ?"
            params.append(since_ms)
        sql += " ORDER BY timestamp_ms ASC, id ASC"
        async with self._conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_fills_by_order(
        self, account_id: int, exchange_order_id: str
    ) -> List[Dict]:
        """Get all fills for a specific order."""
        async with self._conn.execute(
            "SELECT * FROM fills WHERE account_id=? AND exchange_order_id=? "
            "ORDER BY timestamp_ms ASC",
            (account_id, exchange_order_id),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_unrecorded_closing_fills(
        self, account_id: int, pos_id: str, symbol: str, direction: str
    ) -> List[Dict]:
        """Find closing fills that don't yet have a closed_positions row.

        A closed_positions row covers a time *range* (entry→exit).  We check
        whether the fill's timestamp falls within any existing row's window
        for the same position, which handles batched partial fills correctly.
        """
        async with self._conn.execute(
            """SELECT f.* FROM fills f
            WHERE f.account_id=? AND f.is_close=1
              AND (f.terminal_position_id=? OR
                   (COALESCE(f.terminal_position_id, '') = '' AND f.symbol=? AND f.direction=?))
              AND NOT EXISTS (
                  SELECT 1 FROM closed_positions cp
                  WHERE cp.account_id = f.account_id
                    AND cp.terminal_position_id = f.terminal_position_id
                    AND f.timestamp_ms BETWEEN cp.entry_time_ms AND cp.exit_time_ms
              )
            ORDER BY f.timestamp_ms ASC""",
            (account_id, pos_id, symbol, direction),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_order_by_exchange_id(
        self, account_id: int, exchange_order_id: str
    ) -> Optional[Dict]:
        """Look up a single order by exchange_order_id (for exit_reason)."""
        if not exchange_order_id:
            return None
        async with self._conn.execute(
            "SELECT * FROM orders WHERE account_id=? AND exchange_order_id=?",
            (account_id, exchange_order_id),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None  # get_order_by_exchange_id

    async def get_closed_position_terminal_key(
        self, closed_pos_id: int,
    ) -> Optional[Dict]:
        """HIGH-002 (Task 142, Phase 6 routes): minimal lookup for the
        closed_positions row's terminal_position_id + symbol + direction
        composite key. Used by the position-fills drawer to resolve
        which fills belong to a closed_positions row.

        Returns {terminal_position_id, symbol, direction} or None if
        the row is missing.
        """
        async with self._conn.execute(
            "SELECT terminal_position_id, symbol, direction "
            "FROM closed_positions WHERE id=?",
            (closed_pos_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_fill_by_id(
        self, fill_id: int, account_id: int,
    ) -> Optional[Dict]:
        """HIGH-002 (Task 142, Phase 6 routes): single-fill lookup
        scoped to the active account. Used by the exec-link comparison
        panel for one row at a time."""
        async with self._conn.execute(
            "SELECT * FROM fills WHERE id=? AND account_id=?",
            (fill_id, account_id),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_pretrade_log_by_calc_id(
        self, calc_id: str,
    ) -> Optional[Dict]:
        """HIGH-002 (Task 142, Phase 6 routes): singular variant of
        `get_pretrade_logs_by_calc_ids`. LIMIT 1 semantics — when
        multiple rows share a calc_id (duplicate-write race), the
        DB's natural order picks one; not deterministic but matches
        the previous direct-query behavior."""
        if not calc_id:
            return None
        async with self._conn.execute(
            "SELECT * FROM pre_trade_log WHERE calc_id=? LIMIT 1",
            (calc_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def confirm_fill_exec_link(self, fill_id: int) -> None:
        """HIGH-002 (Task 142, Phase 6 routes): persist user-confirmed
        exec link on a fill. Sets `exec_link_confirmed=1`,
        `exec_link_confirmed_at=now()`, `exec_link_confirmed_by='user'`
        and commits. No-op if fill_id is 0/falsy — caller may pass
        Form(0) on missing input."""
        if not fill_id:
            return
        await self._conn.execute(
            "UPDATE fills SET exec_link_confirmed=1, "
            "exec_link_confirmed_at=datetime('now'), "
            "exec_link_confirmed_by='user' "
            "WHERE id=?",
            (fill_id,),
        )
        await self._conn.commit()

    # ── HIGH-002 (Task 144, Phase 6 monitoring/reconciler) ──────────────────
    # Helpers below replace `db._conn` direct access in
    # `api/routes_calculator.py::calculator_link_window_status` (the
    # link-window countdown polling endpoint).

    async def get_pretrade_timestamp_for_link_window(
        self, *, calc_id: str, account_id: int,
    ) -> Optional[Dict]:
        """Minimal pre_trade_log lookup for the link-window countdown:
        returns `{timestamp, link_window_seconds_override}` for the
        matching row, or None.

        Distinct from `get_pretrade_log_by_calc_id` (Task 142): that
        helper returns the FULL row; this one returns only the two
        columns the countdown endpoint reads. Narrower because the
        full pre_trade_log row is wide and pulling it all over the
        wire per 1Hz poll is wasteful.
        """
        if not calc_id:
            return None
        async with self._conn.execute(
            "SELECT timestamp, link_window_seconds_override "
            "FROM pre_trade_log WHERE calc_id=? AND account_id=? LIMIT 1",
            (calc_id, account_id),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def has_confirmed_fill_for_calc(
        self, *, calc_id: str, account_id: int,
    ) -> bool:
        """Return True if any fill exists for `calc_id` within the
        account that has `exec_link_confirmed=1`. Used by the link-
        window countdown to surface LINKED_CONFIRMED state.

        Returns False (not None) — boolean shape matches the caller's
        intent of "did we find one or not".
        """
        if not calc_id:
            return False
        async with self._conn.execute(
            "SELECT 1 FROM fills WHERE calc_id=? AND account_id=? "
            "AND exec_link_confirmed=1 LIMIT 1",
            (calc_id, account_id),
        ) as cur:
            row = await cur.fetchone()
            return row is not None

    async def get_pretrade_logs_by_calc_ids(
        self, calc_ids: List[str]
    ) -> Dict[str, Dict]:
        """Batch-fetch pre_trade_log rows by calc_id.

        Returns {calc_id: row_dict}. Missing calc_ids are absent from the result.
        Eliminates the N+1 pattern when enriching a list of fills (CRIT-001).
        """
        if not calc_ids:
            return {}
        # Dedupe while preserving order. SQLite default param limit is 32766
        # (since 3.32, 2020); a position with that many distinct calc_ids is
        # implausible. No chunking.
        unique_ids = list(dict.fromkeys(calc_ids))
        placeholders = ",".join("?" * len(unique_ids))
        async with self._conn.execute(
            f"SELECT * FROM pre_trade_log WHERE calc_id IN ({placeholders})",
            unique_ids,
        ) as cur:
            rows = await cur.fetchall()
            # Last row wins on duplicate calc_id (matches LIMIT 1 semantics
            # of the per-fill query that this replaces).
            return {r["calc_id"]: dict(r) for r in rows}

    async def get_order_types_by_ids(
        self, account_id: int, exchange_order_ids: List[str]
    ) -> Dict[str, str]:
        """Batch-fetch order_type column by exchange_order_id for one account.

        Returns {exchange_order_id: order_type}. Missing IDs absent from result.
        Eliminates the N+1 pattern when enriching a list of fills (CRIT-001).
        """
        if not exchange_order_ids:
            return {}
        unique_ids = list(dict.fromkeys(exchange_order_ids))
        placeholders = ",".join("?" * len(unique_ids))
        async with self._conn.execute(
            f"SELECT exchange_order_id, order_type FROM orders "
            f"WHERE account_id=? AND exchange_order_id IN ({placeholders})",
            [account_id, *unique_ids],
        ) as cur:
            rows = await cur.fetchall()
            return {r["exchange_order_id"]: (r["order_type"] or "") for r in rows}

    async def get_pre_trade_for_shortfall(
        self, account_id: int, symbol: str, entry_time_ms: int,
        window_ms: int = 300_000,
    ) -> Optional[Dict]:
        """Find the most recent pre_trade_log entry for symbol within window before entry.

        pre_trade_log.timestamp is ISO-8601 text; entry_time_ms is epoch-ms.
        We convert the window bounds to ISO for comparison.
        """
        from datetime import datetime, timezone, timedelta

        entry_dt = datetime.fromtimestamp(entry_time_ms / 1000, tz=timezone.utc)
        window_start = (entry_dt - timedelta(milliseconds=window_ms)).isoformat()
        window_end   = (entry_dt + timedelta(seconds=30)).isoformat()  # small grace

        async with self._conn.execute(
            "SELECT * FROM pre_trade_log "
            "WHERE account_id=? AND ticker=? AND timestamp BETWEEN ? AND ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (account_id, symbol, window_start, window_end),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None  # get_pre_trade_for_shortfall

    # ── Backfill from exchange_history ──────────────────────────────────────

    async def backfill_fills_from_exchange_history(
        self, account_id: int = 1, days: int = 30,
    ) -> Dict[str, int]:
        """One-time migration: copy exchange_history rows into fills + closed_positions.

        OPEN → is_close=0, REALIZED_PNL → is_close=1.

        Phase 0.0.2 (T183 / T178 Layers 1+3 fix):

          - Dedup uses ``position_grouping.is_same_fill`` instead of the
            old SQL-only ``(symbol, side, qty, ±1000ms ts)`` check. The
            new rule widens timestamp tolerance to
            ``FILL_DEDUP_TOLERANCE_MS = 2000`` (to absorb dual-write
            clock skew between this synthetic source and the real
            WS/REST recorders) and ALSO tightens by requiring exact
            match on ``direction``, ``is_close``, and ``price``. Catches
            the synthetic-dup case (Layer 1: backfill writes alongside
            real WS/REST fills for the same trade) without collapsing
            legitimate same-symbol same-time-bucket distinct fills.

          - ``closed_positions`` construction routes through
            ``position_grouping.group_fills_into_positions``, replacing
            the ad-hoc ``(symbol, direction, open_time)`` grouping that
            could collide cross-position when open_time was reused
            (Layer 3 / 5). The helper's chronological-walk grouping
            handles scale-in / partial close / hedge mode correctly.

          - ``mfe``/``mae`` are no longer carried from exchange_history
            row values; the reconciler recomputes them with T175's
            gross-PnL floor applied (helper emits
            ``backfill_completed=0`` to trigger this).

        Returns ``{"fills_inserted": N, "closed_inserted": M}``.
        """
        from core.position_grouping import (
            FILL_DEDUP_TOLERANCE_MS,
            group_fills_into_positions,
            is_same_fill,
        )
        cutoff_ms = int((time.time() - days * 86400) * 1000)

        async with self._conn.execute(
            "SELECT * FROM exchange_history "
            "WHERE time >= ? AND account_id = ? "
            "ORDER BY time ASC",
            (cutoff_ms, account_id),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]

        accepted_fills: List[Dict[str, Any]] = []
        fills_inserted = 0
        for r in rows:
            is_close = r.get("income_type") == "REALIZED_PNL"
            fill = {
                "account_id":           account_id,
                "exchange_fill_id":     r.get("trade_key", ""),
                "terminal_fill_id":     "",
                "exchange_order_id":    "",
                "symbol":               r.get("symbol", ""),
                "side":                 "SELL" if (
                    (r.get("direction") == "LONG" and is_close)
                    or (r.get("direction") == "SHORT" and not is_close)
                ) else "BUY",
                "direction":            r.get("direction", ""),
                "price":                r.get("exit_price") if is_close else r.get("entry_price", 0),
                "quantity":             r.get("qty", 0),
                "fee":                  r.get("fee", 0),
                "fee_asset":            r.get("asset", "USDT"),
                "exchange_position_id": "",
                "terminal_position_id": "",
                "is_close":             int(is_close),
                "realized_pnl":         r.get("income", 0) if is_close else 0,
                "role":                 "",
                "source":               "exchange_history_backfill",
                "timestamp_ms":         r.get("time", 0),
            }
            # Phase 0.0.2 dedup: SQL narrows by (account, symbol, ts window)
            # for performance; in-Python is_same_fill applies the full rule
            # (symbol, side, direction, is_close, qty within _QTY_EPS,
            # ts within FILL_DEDUP_TOLERANCE_MS, price exact).
            # T184 (audit M3): LIMIT 100 caps worst-case scan when an
            # account has many fills clustered in the same 2s window
            # (e.g., multi-fill partial-close storms). 100 is far above
            # any realistic legitimate cluster.
            is_dup = False
            try:
                async with self._conn.execute(
                    "SELECT account_id, exchange_fill_id, symbol, side, direction, "
                    "price, quantity, is_close, timestamp_ms "
                    "FROM fills WHERE account_id=? AND symbol=? "
                    "AND ABS(timestamp_ms - ?) <= ? "
                    "LIMIT 100",
                    (account_id, fill["symbol"], fill["timestamp_ms"],
                     FILL_DEDUP_TOLERANCE_MS),
                ) as cur:
                    async for candidate in cur:
                        if is_same_fill(dict(candidate), fill):
                            is_dup = True
                            break
            except Exception:
                pass  # If check fails, proceed with insert (safe: upsert is idempotent)
            if is_dup:
                continue
            try:
                await self.upsert_fill(fill)
                accepted_fills.append(fill)
                fills_inserted += 1
            except Exception:
                pass

        # Phase 0.0.2 + T184 audit fix (B1): closed_positions reconstruction.
        #
        # The helper requires both opens and closes in the fill stream. In
        # the Binance-only path (Quantower plugin NOT connected),
        # `exchange_history` only contains REALIZED_PNL events — no OPEN
        # rows (those come from platform_bridge / Quantower). The OLD
        # backfill reconstructed closed_positions from REALIZED_PNL rows'
        # embedded `entry_price` + `open_time` metadata directly. To
        # preserve that behavior under the new chronological-walk grouping,
        # we synthesize an in-memory OPEN fill for each REALIZED_PNL row
        # whose corresponding OPEN is NOT already in the accepted batch.
        # The synthetic OPENs are PURELY for grouping — NOT inserted into
        # the fills table — so they don't pollute the fills universe or
        # become a new Layer-1 dup source.
        grouping_input = list(accepted_fills)
        opens_present = {
            (f["symbol"], f["direction"], int(f.get("timestamp_ms", 0) or 0))
            for f in accepted_fills
            if not int(f.get("is_close", 0))
        }
        closes_dropped_no_open_time = 0
        for r in rows:
            if r.get("income_type") != "REALIZED_PNL":
                continue
            open_time = int(r.get("open_time", 0) or 0)
            if open_time == 0:
                # PA-1b couldn't match an open — orphan close. Skip
                # rather than fabricate an entry timestamp. Counted in
                # the return dict for operator visibility.
                closes_dropped_no_open_time += 1
                continue
            symbol = r.get("symbol", "")
            direction = r.get("direction", "")
            if not symbol or not direction:
                continue
            key = (symbol, direction, open_time)
            if key in opens_present:
                continue   # real OPEN already in grouping stream
            entry_price = float(r.get("entry_price", 0) or 0)
            qty = float(r.get("qty", 0) or 0)
            if entry_price <= 0 or qty <= 0:
                continue
            grouping_input.append({
                "account_id":           account_id,
                # in-memory synthetic ID — NOT written to fills, marker
                # only for in-process traceability if someone logs the
                # grouping input
                "exchange_fill_id":     f"bf:open:{r.get('trade_key', '')}",
                "symbol":               symbol,
                "side":                 "BUY" if direction == "LONG" else "SELL",
                "direction":            direction,
                "price":                entry_price,
                "quantity":             qty,
                "is_close":             0,
                "timestamp_ms":         open_time,
                "source":               "exchange_history_backfill_inmemory_open",
            })
            opens_present.add(key)

        grouping_input.sort(key=lambda f: int(f.get("timestamp_ms", 0) or 0))
        position_records = group_fills_into_positions(grouping_input)

        closed_inserted = 0
        for pr in position_records:
            try:
                # Override source so operators can still filter by
                # `source='exchange_history_backfill'`; helper's default
                # `rebuilt_from_fills` marker is reserved for the
                # Phase 0.0.6 rebuild script.
                record = dict(pr)
                record["source"] = "exchange_history_backfill"
                await self.insert_closed_position(record)
                closed_inserted += 1
            except Exception:
                pass

        if closes_dropped_no_open_time:
            log.info(
                "Backfill: %d REALIZED_PNL rows had open_time=0 (orphan "
                "closes — PA-1b couldn't match a prior open). Skipped "
                "during closed_positions reconstruction.",
                closes_dropped_no_open_time,
            )
        log.info(
            "Backfill complete: %d fills, %d closed_positions from exchange_history",
            fills_inserted, closed_inserted,
        )
        return {
            "fills_inserted":              fills_inserted,
            "closed_inserted":             closed_inserted,
            "closes_dropped_no_open_time": closes_dropped_no_open_time,
        }

    # ── MFE/MAE for closed_positions ───────────────────────────────────────

    async def get_uncalculated_closed_positions(
        self, account_id: int,
    ) -> List[Dict]:
        """Return closed_positions rows where backfill has not completed."""
        async with self._conn.execute(
            "SELECT * FROM closed_positions "
            "WHERE account_id=? AND NOT backfill_completed "
            "AND entry_time_ms > 0 AND exit_time_ms > 0 "
            "ORDER BY exit_time_ms DESC LIMIT 200",
            (account_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def update_closed_position_mfe_mae(
        self, row_id: int, mfe: float, mae: float,
    ) -> None:
        """Update MFE/MAE on a specific closed_positions row."""
        await self._conn.execute(
            "UPDATE closed_positions SET mfe=?, mae=?, backfill_completed=1 WHERE id=?",
            (mfe, mae, row_id),
        )
        await self._conn.commit()

    # ── Data consistency ───────────────────────────────────────────────────

    async def validate_order_data_consistency(
        self, account_id: int,
    ) -> Dict[str, Any]:
        """Check for orphan fills, qty mismatches, stale orders, unclosed positions."""
        result: Dict[str, Any] = {}

        # Orphan fills (reference non-existent orders)
        async with self._conn.execute(
            "SELECT COUNT(*) FROM fills f "
            "WHERE f.account_id=? AND f.exchange_order_id != '' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM orders o WHERE o.exchange_order_id = f.exchange_order_id"
            ")",
            (account_id,),
        ) as cur:
            result["orphan_fills"] = (await cur.fetchone())[0]

        # Stale active orders (not seen in 24h+)
        cutoff = int(time.time() * 1000) - 86_400_000
        async with self._conn.execute(
            "SELECT COUNT(*) FROM orders "
            "WHERE account_id=? AND status IN ('new','partially_filled') "
            "AND last_seen_ms < ? AND last_seen_ms > 0",
            (account_id, cutoff),
        ) as cur:
            result["stale_orders_24h"] = (await cur.fetchone())[0]

        # Closed positions missing MFE/MAE
        async with self._conn.execute(
            "SELECT COUNT(*) FROM closed_positions "
            "WHERE account_id=? AND NOT backfill_completed "
            "AND entry_time_ms > 0 AND exit_time_ms > 0",
            (account_id,),
        ) as cur:
            result["closed_missing_mfe_mae"] = (await cur.fetchone())[0]

        # Row counts
        for table in ("orders", "fills", "closed_positions"):
            async with self._conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE account_id=?",
                (account_id,),
            ) as cur:
                result[f"{table}_count"] = (await cur.fetchone())[0]

        return result

    # ── Phase 0 (P0.T1): calc-linkage CRUD helpers ─────────────────────
    #
    # CRUD for the four new tables introduced in P0.T1
    # (positions_calcs, order_amendments, funding_events,
    # calc_match_audit). Schema in core/database.py _CREATE_STATEMENTS
    # under the "Phase 0 (P0.T1)" comment block; column reference in
    # docs/design/calc_linkage_spec.md §3.1.
    #
    # No callers in production yet — wired by Phase 1+ (matcher),
    # Phase 2 (junction attribution), Phase 4 (amendments), Phase 5
    # (funding), and Phase 7 (reverse-query). Helpers ship in P0.T1
    # so downstream phases can land thin behavior changes against an
    # already-established API.

    # ── positions_calcs ────────────────────────────────────────────────

    async def upsert_position_calc_link(self, row: Dict[str, Any]) -> None:
        """UPSERT a junction row for (position_id, calc_id, order_id).

        ``position_id`` is the engine's ``terminal_position_id`` string
        (TEXT) — the universal position identity used across orders/
        fills/closed_positions — NOT an integer (see spec §3.1, P2.T1).

        Phase 2.1 calls this on every opening fill. Per-fill cumulative
        ``contributed_qty`` is summed via the UPSERT (UNIQUE constraint
        on the triple + ON CONFLICT DO UPDATE adds the new fill's qty
        and refreshes last_fill_ts). ``first_fill_ts`` is preserved on
        update by being omitted from the DO UPDATE SET (it keeps the
        value written on first insert).
        """
        sql = """
            INSERT INTO positions_calcs (
                position_id, calc_id, order_id, account_id,
                contributed_qty, first_fill_ts, last_fill_ts,
                planned_size, size_delta_pct, planned_tp, planned_sl,
                lifecycle_id
            ) VALUES (
                :position_id, :calc_id, :order_id, :account_id,
                :contributed_qty, :first_fill_ts, :last_fill_ts,
                :planned_size, :size_delta_pct, :planned_tp, :planned_sl,
                :lifecycle_id
            )
            ON CONFLICT(position_id, calc_id, order_id) DO UPDATE SET
                contributed_qty = positions_calcs.contributed_qty + excluded.contributed_qty,
                last_fill_ts    = MAX(positions_calcs.last_fill_ts, excluded.last_fill_ts),
                lifecycle_id    = COALESCE(positions_calcs.lifecycle_id, excluded.lifecycle_id)
                -- size_delta_pct + planned_size/tp/sl are OMITTED from DO
                -- UPDATE SET deliberately: planned_* are a contribution-time
                -- snapshot (first-write-wins, T2.4) and size_delta_pct is a
                -- CLOSE-time quantity (T2.5) that needs the cumulative
                -- contributed_qty. T232: size_delta_pct used to be
                -- `= excluded.size_delta_pct` here, which would have
                -- clobbered a T2.5 close-computed value to NULL on any
                -- later fill of the same triple. T2.5 must write
                -- size_delta_pct via a dedicated close-time UPDATE, not
                -- through this per-fill UPSERT.
        """
        try:
            await self._conn.execute(sql, {
                "position_id":     row.get("position_id"),
                "calc_id":         row.get("calc_id", ""),
                "order_id":        row.get("order_id"),
                "account_id":      row.get("account_id", 1),
                "contributed_qty": row.get("contributed_qty", 0),
                "first_fill_ts":   row.get("first_fill_ts", 0),
                "last_fill_ts":    row.get("last_fill_ts", 0),
                "planned_size":    row.get("planned_size"),
                "size_delta_pct":  row.get("size_delta_pct"),
                "planned_tp":      row.get("planned_tp"),
                "planned_sl":      row.get("planned_sl"),
                "lifecycle_id":    row.get("lifecycle_id"),
            })
            await self._conn.commit()
        except Exception:
            log.exception("upsert_position_calc_link failed")

    async def get_position_calc_links(self, position_id: str) -> List[Dict]:
        """Return all junction rows for one position, ordered by first_fill_ts.

        ``position_id`` is the ``terminal_position_id`` string (P2.T1).

        Phase 2.5/2.6 uses this to compute the most-contributing calc
        for delta basis (spec §3.2) and to surface the per-calc
        breakdown of a scale-in position.
        """
        async with self._conn.execute(
            "SELECT * FROM positions_calcs WHERE position_id = ? "
            "ORDER BY first_fill_ts ASC, id ASC",
            (position_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_calc_position_links(self, calc_id: str) -> List[Dict]:
        """Return all junction rows for one calc. Used by reverse-query
        (Phase 7.1 ``GET /context/calc/{id}``) to assemble the calc's
        contribution history across positions."""
        async with self._conn.execute(
            "SELECT * FROM positions_calcs WHERE calc_id = ? "
            "ORDER BY first_fill_ts ASC, id ASC",
            (calc_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_lifecycle_links(self, lifecycle_id: str) -> List[Dict]:
        """Return all junction rows for one lifecycle. Backs the
        single-key audit query (Phase 7.1 ``GET /context/lifecycle/{id}``)."""
        if not lifecycle_id:
            return []
        async with self._conn.execute(
            "SELECT * FROM positions_calcs WHERE lifecycle_id = ? "
            "ORDER BY first_fill_ts ASC, id ASC",
            (lifecycle_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ── order_amendments ───────────────────────────────────────────────

    async def insert_order_amendment(self, row: Dict[str, Any]) -> None:
        """INSERT an immutable amendment audit row.

        Phase 4.1 calls this from the WS handler on every detected
        change to ``entry_price`` / ``tp_price`` / ``sl_price`` /
        ``size`` / ``leverage``. No upsert — each amendment event is
        its own row. ``deviation_pct`` is signed:
        ``(new - old) / old * 100``.
        """
        sql = """
            INSERT INTO order_amendments (
                order_id, calc_id, field, old_value, new_value,
                ts_ms, operator_id, deviation_pct, lifecycle_id
            ) VALUES (
                :order_id, :calc_id, :field, :old_value, :new_value,
                :ts_ms, :operator_id, :deviation_pct, :lifecycle_id
            )
        """
        try:
            await self._conn.execute(sql, {
                "order_id":      row.get("order_id"),
                "calc_id":       row.get("calc_id"),
                "field":         row.get("field", ""),
                "old_value":     row.get("old_value"),
                "new_value":     row.get("new_value"),
                "ts_ms":         row.get("ts_ms", 0),
                "operator_id":   row.get("operator_id"),
                "deviation_pct": row.get("deviation_pct"),
                "lifecycle_id":  row.get("lifecycle_id"),
            })
            await self._conn.commit()
        except Exception:
            log.exception("insert_order_amendment failed")

    async def get_order_amendments(self, order_id: int) -> List[Dict]:
        """Return all amendments for one order, oldest first."""
        async with self._conn.execute(
            "SELECT * FROM order_amendments WHERE order_id = ? "
            "ORDER BY ts_ms ASC, id ASC",
            (order_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_calc_amendments(
        self, calc_id: str, since_ms: Optional[int] = None,
    ) -> List[Dict]:
        """Return all amendments for one calc, oldest first.

        ``since_ms`` filters to amendments after a timestamp (used by
        Phase 4.3's live deviation badge to compute incremental drift
        since the last refresh).
        """
        if since_ms is not None:
            sql = ("SELECT * FROM order_amendments WHERE calc_id = ? "
                   "AND ts_ms >= ? ORDER BY ts_ms ASC, id ASC")
            params: Tuple[Any, ...] = (calc_id, since_ms)
        else:
            sql = ("SELECT * FROM order_amendments WHERE calc_id = ? "
                   "ORDER BY ts_ms ASC, id ASC")
            params = (calc_id,)
        async with self._conn.execute(sql, params) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ── funding_events ─────────────────────────────────────────────────

    async def insert_funding_event(self, row: Dict[str, Any]) -> bool:
        """INSERT a funding event with dedup on ``venue_event_id``.

        Phase 5.2/5.3 calls this on every funding WS event for an
        open position. Returns ``True`` if a new row was inserted,
        ``False`` if the venue_event_id was already present (WS
        replay scenario). Uses INSERT OR IGNORE — idempotent.
        """
        sql = """
            INSERT OR IGNORE INTO funding_events (
                position_id, calc_id, account_id, symbol,
                amount, mark_price, funding_rate, ts_ms,
                venue_event_id, lifecycle_id
            ) VALUES (
                :position_id, :calc_id, :account_id, :symbol,
                :amount, :mark_price, :funding_rate, :ts_ms,
                :venue_event_id, :lifecycle_id
            )
        """
        try:
            cur = await self._conn.execute(sql, {
                "position_id":    row.get("position_id"),
                "calc_id":        row.get("calc_id"),
                "account_id":     row.get("account_id", 1),
                "symbol":         row.get("symbol", ""),
                "amount":         row.get("amount", 0),
                "mark_price":     row.get("mark_price"),
                "funding_rate":   row.get("funding_rate"),
                "ts_ms":          row.get("ts_ms", 0),
                "venue_event_id": row.get("venue_event_id", ""),
                "lifecycle_id":   row.get("lifecycle_id"),
            })
            await self._conn.commit()
            return (cur.rowcount or 0) > 0
        except Exception:
            log.exception("insert_funding_event failed")
            return False

    async def get_position_funding_events(self, position_id: int) -> List[Dict]:
        """Return all funding events for one position, oldest first."""
        async with self._conn.execute(
            "SELECT * FROM funding_events WHERE position_id = ? "
            "ORDER BY ts_ms ASC, id ASC",
            (position_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def sum_position_funding(self, position_id: int) -> float:
        """Return SUM(amount) of funding events for one position.

        Phase 5.4 uses this at position close to populate
        ``closed_positions.funding_fees``. Phase 5.7's live unrealized
        funding helper uses this on open positions.
        """
        async with self._conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM funding_events "
            "WHERE position_id = ?",
            (position_id,),
        ) as cur:
            row = await cur.fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0

    # ── calc_match_audit ───────────────────────────────────────────────

    async def insert_calc_match_audit_batch(
        self, rows: List[Dict[str, Any]],
    ) -> int:
        """INSERT a batch of per-criterion audit rows in one transaction.

        Phase 1.4 calls this per matcher decision with N rows (one per
        criterion per candidate calc — typically 5/5 for limit, 6/6
        for market across each candidate). Batched to amortize the
        commit cost on hot-path matcher decisions. Returns the count
        of rows inserted.
        """
        if not rows:
            return 0
        sql = """
            INSERT INTO calc_match_audit (
                order_id, calc_id, criterion, calc_value, order_value,
                tolerance_used, matched, ts_ms, winning
            ) VALUES (
                :order_id, :calc_id, :criterion, :calc_value, :order_value,
                :tolerance_used, :matched, :ts_ms, :winning
            )
        """
        params = [{
            "order_id":       r.get("order_id"),
            "calc_id":        r.get("calc_id", ""),
            "criterion":      r.get("criterion", ""),
            "calc_value":     r.get("calc_value"),
            "order_value":    r.get("order_value"),
            "tolerance_used": r.get("tolerance_used"),
            "matched":        int(bool(r.get("matched", 0))),
            "ts_ms":          r.get("ts_ms", 0),
            "winning":        int(bool(r.get("winning", 0))),
        } for r in rows]
        try:
            await self._conn.executemany(sql, params)
            await self._conn.commit()
            return len(rows)
        except Exception:
            log.exception("insert_calc_match_audit_batch failed")
            return 0

    async def get_order_match_audit(self, order_id: int) -> List[Dict]:
        """Return all per-criterion audit rows for one order.

        Phase 3.5's needs-link diff panel reads this to render the
        side-by-side per-criterion match/miss visualization.
        """
        async with self._conn.execute(
            "SELECT * FROM calc_match_audit WHERE order_id = ? "
            "ORDER BY calc_id ASC, criterion ASC, id ASC",
            (order_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_calc_match_audit(
        self, calc_id: str, order_id: Optional[int] = None,
    ) -> List[Dict]:
        """Return audit rows for one calc, optionally filtered to one order."""
        if order_id is not None:
            sql = ("SELECT * FROM calc_match_audit WHERE calc_id = ? "
                   "AND order_id = ? ORDER BY criterion ASC, id ASC")
            params: Tuple[Any, ...] = (calc_id, order_id)
        else:
            sql = ("SELECT * FROM calc_match_audit WHERE calc_id = ? "
                   "ORDER BY order_id ASC, criterion ASC, id ASC")
            params = (calc_id,)
        async with self._conn.execute(sql, params) as cur:
            return [dict(r) for r in await cur.fetchall()]
