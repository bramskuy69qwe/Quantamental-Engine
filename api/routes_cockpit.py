"""Cockpit — the calc-linkage operator dashboard (Phase 8, plan §8).

P8.T1 ships the LAYOUT + state-passing scaffold: a 2x2 grid of four panes
(open positions · active calcs · needs-link · recent closes) on a dedicated
``/cockpit`` page, each lazy-loading its own fragment. Subsequent Phase-8
tasks enrich each pane in place:
  - positions  -> P8.T2 (MFE/MAE, uPnL refresh)
  - active calcs -> P8.T3 (frozen-window countdown timers + per-calc cancel)
  - needs-link -> the manual-link queue (P3.T6 surfaced compactly here)
  - recent closes -> Export-Audit button wiring (P7.T4/T5)

All panes read the ACTIVE account (``app_state.active_account_id``), like
the rest of the app. The page is additive — the existing ``/`` overview
dashboard is unchanged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from core.state import app_state
from core.database import db
from api.helpers import templates, _ctx, _table_ctx
# v3.0 P4: the shared non-finite JSON guard (F2 both-doors discipline).
from api.routes_calculator import _json_safe

log = logging.getLogger("routes.cockpit")
router = APIRouter()

# Per-pane caps — the cockpit panes are summaries, not full tables (the
# full tables live on the dashboard / history / needs-link pages).
_CALCS_LIMIT = 50
_CLOSES_LIMIT = 15
_NEEDS_LINK_PREVIEW = 8


def _calc_expiry_ms(timestamp_iso, window_seconds):
    """Frozen-window expiry as epoch-ms: created_ts + window_seconds (P8.T3).

    ``window_seconds`` is frozen onto pre_trade_log at calc creation (P1.T3);
    the match window runs from the calc's creation ``timestamp``. Returns None
    when either input is missing (older calcs may have NULL window_seconds) —
    the pane then renders no countdown for that row. UTC epoch-ms so the
    client-side tick compares directly against Date.now() regardless of tz.
    """
    if not timestamp_iso or not window_seconds:
        return None
    try:
        dt = datetime.fromisoformat(timestamp_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000) + int(window_seconds) * 1000
    except (ValueError, TypeError):
        return None


@router.get("/cockpit", response_class=HTMLResponse)
async def cockpit_page(request: Request):
    """The 4-pane cockpit page. Thin shell — each pane lazy-loads its
    fragment (GET /fragments/cockpit/*)."""
    return templates.TemplateResponse(
        request, "cockpit.html", _ctx(request, active_page="cockpit"),
    )


@router.get("/fragments/cockpit/positions", response_class=HTMLResponse)
async def frag_cockpit_positions(request: Request):
    """Open-positions pane: live PositionInfo list with the P4.T3 deviation
    badge. Reads app_state (the single source of truth for live positions)."""
    return templates.TemplateResponse(
        request, "fragments/cockpit/positions.html",
        _table_ctx(request, positions=app_state.positions),
    )


@router.get("/fragments/cockpit/calcs", response_class=HTMLResponse)
async def frag_cockpit_calcs(request: Request):
    """Active-calcs pane: live (active|released) calcs for the account."""
    try:
        calcs = await db.get_active_calcs(app_state.active_account_id, limit=_CALCS_LIMIT)
    except Exception:
        log.exception("cockpit active-calcs read failed")
        calcs = []
    # P8.T3: derive the frozen-window expiry per calc for the client-side
    # countdown (the JS tick reads data-calc-expiry; see cockpit.html).
    for c in calcs:
        c["expiry_ms"] = _calc_expiry_ms(c.get("timestamp"), c.get("window_seconds"))
    return templates.TemplateResponse(
        request, "fragments/cockpit/calcs.html",
        _table_ctx(request, calcs=calcs),
    )


@router.get("/fragments/cockpit/needs_link", response_class=HTMLResponse)
async def frag_cockpit_needs_link(request: Request):
    """Needs-link pane: compact preview of the manual-link queue
    (NEEDS_MANUAL_REVIEW + UNLINKED), reusing core.link_actions."""
    from core.link_actions import list_needs_review
    try:
        orders = await list_needs_review(app_state.active_account_id)
    except Exception:
        log.exception("cockpit needs-link read failed")
        orders = []
    total = len(orders)
    return templates.TemplateResponse(
        request, "fragments/cockpit/needs_link.html",
        _table_ctx(request, orders=orders[:_NEEDS_LINK_PREVIEW], total=total),
    )


@router.get("/fragments/cockpit/closes", response_class=HTMLResponse)
async def frag_cockpit_closes(request: Request):
    """Recent-closes pane: latest closed positions (newest exit first)."""
    try:
        rows, _ = await db.query_closed_positions(
            app_state.active_account_id, page=1, per_page=_CLOSES_LIMIT,
            sort_by="exit_time_ms", sort_dir="DESC",
        )
    except Exception:
        log.exception("cockpit recent-closes read failed")
        rows = []
    # #2 (debug 2026-06-08): same calc-linkage "Plan" badge as Position History,
    # so the cockpit's open-positions and recent-closes panes read consistently.
    # Linked-only (no-calc rows stay "—"); thresholds read ONCE.
    try:
        from core.state import stamp_close_deviation_badges
        from core.account_config import read_account_config_async
        _cfg = await read_account_config_async(db, app_state.active_account_id)
        stamp_close_deviation_badges(
            rows, yellow_pct=_cfg.yellow_deviation_pct, red_pct=_cfg.red_deviation_pct)
    except Exception:
        log.debug("cockpit recent-closes badge stamping failed", exc_info=True)
    return templates.TemplateResponse(
        request, "fragments/cockpit/closes.html",
        _table_ctx(request, rows=rows),
    )


# ── v3.0 P4: JSON mirrors for the React Linkage page ─────────────────────
# Same data assembly as the fragments above; JSON out. Writes stay on the
# existing choke-pointed endpoints (manual_link / mark_unplanned /
# close_reason / cancel) — these mirrors are READ-ONLY.

def _position_row(p) -> dict:
    """Serialize a live PositionInfo for the Linkage/History position row —
    incl. the G-O7 planned/drift quartet stamped by _enrich_positions_calc_id."""
    return {
        "position_id":       p.position_id,
        "symbol":            p.ticker,
        "direction":         p.direction,
        "size":              p.contract_amount,
        "entry":             p.average,
        "mark":              p.fair_price,
        "notional":          p.position_value_usdt,
        "upnl":              p.individual_unrealized,
        "fees":              p.individual_fees,
        "funding_cum":       p.individual_funding_fees,
        "mfe":               p.session_mfe,
        "mae":               p.session_mae,
        "tp_live":           p.individual_tp_price,
        "sl_live":           p.individual_sl_price,
        "tp_plan":           p.planned_tp,
        "sl_plan":           p.planned_sl,
        "tp_drift_pct":      p.tp_drift_pct,
        "sl_drift_pct":      p.sl_drift_pct,
        "size_delta_pct":    p.size_delta_pct,
        "amendment_count":   p.amendment_count,
        "deviation_badge":   p.deviation_badge,
        "tpsl_amended":      p.tpsl_amended,
        "calc_id":           p.calc_id,
        "contributing_calc_ids": list(p.contributing_calc_ids or []),
        # a live position is LINKED iff the junction gave it a primary calc
        "link_status":       "LINKED" if p.calc_id else "UNPLANNED",
    }


@router.get("/api/linkage/positions")
async def api_linkage_positions():
    """Live positions with the lifecycle fields (G-O7). The full amendment
    timeline stays lazy-loaded per row via GET /context/position/{id} (the
    plan's sanctioned option)."""
    return JSONResponse(_json_safe(
        {"positions": [_position_row(p) for p in app_state.positions]}
    ))


@router.get("/api/linkage/calcs")
async def api_linkage_calcs():
    """Active (active|released) calcs incl. expiry_ms — the JSON twin of the
    calcs fragment. SELECT * carries model_id / est_r / operator_id / tags for
    the richer React row."""
    try:
        calcs = await db.get_active_calcs(app_state.active_account_id, limit=_CALCS_LIMIT)
    except Exception:
        log.exception("linkage calcs read failed")
        calcs = []
    for c in calcs:
        c["expiry_ms"] = _calc_expiry_ms(c.get("timestamp"), c.get("window_seconds"))
    return JSONResponse(_json_safe({"calcs": calcs}))


@router.get("/api/linkage/closes")
async def api_linkage_closes(limit: int = 15):
    """Recent closes incl. the stamped deviation badge. `pending_reason` is
    DERIVED (named deviation): the engine defaults a detected manual close to
    MANUAL_OTHER; an un-annotated MANUAL_OTHER row is the design's
    'categorize me' nudge."""
    limit = max(1, min(int(limit or 15), 50))
    try:
        rows, _ = await db.query_closed_positions(
            app_state.active_account_id, page=1, per_page=limit,
            sort_by="exit_time_ms", sort_dir="DESC",
        )
    except Exception:
        log.exception("linkage closes read failed")
        rows = []
    try:
        from core.state import stamp_close_deviation_badges
        from core.account_config import read_account_config_async
        _cfg = await read_account_config_async(db, app_state.active_account_id)
        stamp_close_deviation_badges(
            rows, yellow_pct=_cfg.yellow_deviation_pct, red_pct=_cfg.red_deviation_pct)
    except Exception:
        log.debug("linkage closes badge stamping failed", exc_info=True)
    for r in rows:
        r["pending_reason"] = bool(
            r.get("exit_reason") == "MANUAL_OTHER" and not r.get("close_note")
        )
    return JSONResponse(_json_safe({"closes": rows}))


@router.get("/api/linkage/funding")
async def api_linkage_funding():
    """G-O6 — the funding book: per-position rate / est-next / cumulative +
    the settlement countdown. Pure composition of existing inputs
    (fetch_funding_rates + compute_funding_exposure +
    PositionInfo.individual_funding_fees); the adverse rule mirrors
    routes_analytics.frag_analytics_funding."""
    import time as _time
    from core.analytics import compute_funding_exposure

    positions = list(app_state.positions)
    rates: dict = {}
    if positions:
        try:
            from core.exchange import fetch_funding_rates
            rates = await fetch_funding_rates([p.ticker for p in positions]) or {}
        except Exception:
            log.debug("linkage funding rate fetch failed", exc_info=True)
    rows = []
    net_next = 0.0
    net_cum = 0.0
    next_ts = None
    for p in positions:
        fd = rates.get(p.ticker) or {}
        rate = fd.get("funding_rate")
        # adapter-degraded rows carry the 0 sentinel (rest_adapter fallback) —
        # normalize to None so a JSON client can't render a Jan-1970
        # settlement [P4 audit L1]
        nft = fd.get("next_funding_time") or None
        notional = abs(p.position_value_usdt)
        exp = compute_funding_exposure(notional, rate or 0.0)
        adverse = ((rate or 0.0) > 0) if p.direction == "LONG" else ((rate or 0.0) < 0)
        est_next = -exp["per_8h"] if adverse else exp["per_8h"]
        rows.append({
            "position_id": p.position_id,
            "symbol":      p.ticker,
            "direction":   p.direction,
            "size":        p.contract_amount,
            "notional":    notional,
            "rate":        rate,
            "pays":        "you" if adverse else "venue",
            "est_next":    est_next,
            "per_day":     exp["per_day"],
            "per_week":    exp["per_week"],
            "cum":         p.individual_funding_fees,
            "next_funding_time": nft,
        })
        net_next += est_next
        net_cum += p.individual_funding_fees or 0.0
        if nft and (next_ts is None or nft < next_ts):
            next_ts = nft
    countdown_s = (
        max(0, int((next_ts - _time.time() * 1000) / 1000)) if next_ts else None
    )
    return JSONResponse(_json_safe({
        "rows":        rows,
        "net_next":    net_next,
        "net_cum":     net_cum,
        "next_funding_time_ms": next_ts,
        "countdown_s": countdown_s,
        # Binance perp settlement schedule (UTC) — display copy, mirrors the
        # funding_tracker fragment.
        "schedule":    ["00:00", "08:00", "16:00"],
    }))
