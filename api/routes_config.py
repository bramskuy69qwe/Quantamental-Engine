"""
Config page router — serves the tabbed config page (Accounts + Connections
+ P8.T8 Calc-Linkage).
"""
from __future__ import annotations

import logging
import math

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from core.state import app_state
from core.database import db
from api.helpers import templates, _ctx

log = logging.getLogger("routes.config")
router = APIRouter(tags=["config"])


@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    return templates.TemplateResponse(request, "config.html", _ctx(request))


# ── P8.T8 (plan §8.9 / spec §3.3): per-account config_json editor ────────────
# A "Calc-Linkage" tab in /config (NOT a separate /settings page — /config IS
# the settings surface; a second config page would be redundant). Reuses the
# T4a write_account_config / merge_config_json writer. notification_subscriptions
# (§8.9) are deferred to P8.T7 (the notification system that defines them).


def _bounded(raw, lo, hi, label, *, is_int=False):
    """Parse a numeric form field within [lo, hi]; raise ValueError (mapped to
    an inline error) on a bad / out-of-range value."""
    try:
        v = int(raw) if is_int else float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number")
    # float('nan')/float('inf') parse, and NaN fails BOTH range comparisons
    # (nan<lo and nan>hi are False), so it would slip the bound check and
    # persist as INVALID JSON (json.dumps emits a bare NaN token) AND silently
    # disable the matcher (a nan tolerance makes every drift comparison False).
    if not is_int and not math.isfinite(v):
        raise ValueError(f"{label} must be a finite number")
    if v < lo or v > hi:
        raise ValueError(f"{label} must be between {lo} and {hi}")
    return v


@router.get("/fragments/account_config", response_class=HTMLResponse)
async def frag_account_config(request: Request):
    """The Calc-Linkage config form, pre-filled from the active account's
    resolved AccountConfig (spec §3.3 defaults fill anything absent)."""
    from core.account_config import read_account_config_async
    cfg = await read_account_config_async(db, app_state.active_account_id)
    return templates.TemplateResponse(
        request, "fragments/account_config.html", _ctx(request, cfg=cfg),
    )


@router.post("/config/account_config", response_class=HTMLResponse)
async def save_account_config(
    window_seconds: str = Form(...),
    clock_skew_tolerance_sec: str = Form(...),
    entry_tolerance_pct: str = Form(...),
    snapshot_drift_tolerance_pct: str = Form(...),
    yellow_pct: str = Form(...),
    red_pct: str = Form(...),
    size_deviation_threshold_pct: str = Form(...),
    webhook_url: str = Form(""),
    webhook_enabled: str = Form(""),
    snapshot_wins_drift: str = Form(""),
):
    """Validate + persist the per-account config_json knobs. All responses are
    200 + an inline span (htmx swallows non-2xx bodies). The form is the full
    snapshot of deviation_thresholds + feature_flags, so a top-level merge
    correctly replaces those nested groups (every current nested key has a
    field — a future key must be added to the form too)."""
    from core.exec_link import MAX_LINK_WINDOW_SECONDS
    try:
        ws  = _bounded(window_seconds, 1, MAX_LINK_WINDOW_SECONDS, "Match window", is_int=True)
        cs  = _bounded(clock_skew_tolerance_sec, 0, 3600, "Clock-skew tolerance", is_int=True)
        et  = _bounded(entry_tolerance_pct, 0, 100, "Entry tolerance")
        sd  = _bounded(snapshot_drift_tolerance_pct, 0, 100, "Snapshot-drift tolerance")
        yp  = _bounded(yellow_pct, 0, 100, "Deviation yellow")
        rp  = _bounded(red_pct, 0, 100, "Deviation red")
        szd = _bounded(size_deviation_threshold_pct, 0, 1000, "Size-deviation threshold")
    except ValueError as exc:
        return HTMLResponse(f'<span class="text-red">{exc}</span>')
    if yp >= rp:
        return HTMLResponse(
            '<span class="text-red">yellow threshold must be &lt; red threshold</span>'
        )
    url = webhook_url.strip()
    if url and not url.startswith(("http://", "https://")):
        return HTMLResponse(
            '<span class="text-red">webhook URL must start with http:// or https://</span>'
        )

    updates = {
        "window_seconds":               ws,
        "clock_skew_tolerance_sec":     cs,
        "entry_tolerance_pct":          et,
        "snapshot_drift_tolerance_pct": sd,
        "size_deviation_threshold_pct": szd,
        "deviation_thresholds":         {"yellow_pct": yp, "red_pct": rp},
        # STRICT JSON bools — an unchecked checkbox is absent (-> "" -> False).
        "feature_flags": {
            "snapshot_wins_drift": bool(snapshot_wins_drift),
            "webhook_enabled":     bool(webhook_enabled),
        },
        "webhook_url": url or None,
    }
    from core.account_config import write_account_config
    try:
        await write_account_config(db, app_state.active_account_id, updates)
    except Exception:
        log.exception("save_account_config failed")
        return HTMLResponse('<span class="text-red">save failed</span>')
    return HTMLResponse('<span class="text-green">saved ✓</span>')
