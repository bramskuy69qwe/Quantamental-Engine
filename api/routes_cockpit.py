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

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from core.state import app_state
from core.database import db
from api.helpers import templates, _ctx, _table_ctx

log = logging.getLogger("routes.cockpit")
router = APIRouter()

# Per-pane caps — the cockpit panes are summaries, not full tables (the
# full tables live on the dashboard / history / needs-link pages).
_CALCS_LIMIT = 50
_CLOSES_LIMIT = 15
_NEEDS_LINK_PREVIEW = 8


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
    return templates.TemplateResponse(
        request, "fragments/cockpit/closes.html",
        _table_ctx(request, rows=rows),
    )
