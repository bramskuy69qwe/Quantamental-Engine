"""
Config page router — serves the tabbed config page (Accounts + Connections
+ P8.T8 Calc-Linkage).
"""
from __future__ import annotations

import logging
import math

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse

from core.state import app_state
from core.database import db
from api.helpers import templates, _ctx

log = logging.getLogger("routes.config")
router = APIRouter(tags=["config"])


@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    return templates.TemplateResponse(request, "config.html", _ctx(request))


# ── v3.0 P2: JSON config surface for the React Config page ────────────────
@router.get("/api/config/account/{account_id}")
async def api_config_account(account_id: int):
    """Risk params + DD/weekly settings for the React Config detail form (v3.0
    P2). Account display fields come from GET /accounts; this adds the two risk
    stores (account_params sizing + account_settings DD/weekly posture)."""
    from core.account_registry import account_registry
    from core.db_account_settings import get_account_settings
    params = account_registry.get_account_params(account_id)
    try:
        s = get_account_settings(account_id)
        # M2a/M2b (dead-settings batch, 2026-08-04): the three weekly_pnl_*
        # fields are no longer served. They are DEAD as inputs — the weekly
        # state machine derives from account_params ratios (core/data_cache)
        # and no gate consumes the enforcement mode (advisory-only by
        # design) — and the ONE consumer of this endpoint used to render
        # them as if live. Columns + data stay in the DB; /api/state still
        # reports the stored enforcement mode.
        settings = {f: getattr(s, f) for f in (
            "dd_rolling_window_days", "dd_warning_threshold", "dd_limit_threshold",
            "dd_recovery_threshold", "dd_enforcement_mode",
            "strategy_preset",
            # config-3 (Meridian audit): every timestamp the operator reads is
            # rendered against this, and it was surfaced NOWHERE in v3 — a wrong
            # timezone stayed invisible until timestamps looked off. Real
            # per-account setting, ZoneInfo-validated by the same
            # POST /accounts/{id}/update the Config form already posts to.
            "timezone",
        )}
    except Exception:
        settings = {}
    return JSONResponse({"account_id": account_id, "params": params, "settings": settings})


@router.post("/api/config/apply-preset")
async def api_config_apply_preset(request: Request):
    """Apply a strategy preset to an account (v3.0 P2 — FULL scope): write BOTH
    the DD posture (account_settings via strategy_presets.apply_preset) AND the
    sizing envelope (account_params via the validated param-save path).
    EXCLUDES the enforcement-mode flip (that keeps its own confirm gate).

    config-2 (2026-07-25 Meridian audit): the target is now the OPTIONAL body
    field `account_id`, defaulting to the active account. It used to be
    hard-wired to `app_state.active_account_id`, which meant an account that had
    never been activated could not be given a preset at all — while every other
    read and write on that tab is per-selected-account via
    /api/config/account/{id}. Configuring a second account before switching to
    it is a normal workflow.

    The live-state coupling is the sharp edge here and is handled below: the
    in-memory `app_state.params` mirror and the `risk:params_updated` event
    describe the ACTIVE account only. Writing another account's row must not
    touch either, or the running account would start sizing off a preset the
    operator applied to a different one.
    """
    from core.strategy_presets import apply_preset, STRATEGY_PRESETS, PRESET_PARAMS
    from core.account_registry import account_registry
    from core.state import validate_params
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "Body must be a JSON object"}, status_code=400)
    preset = str(body.get("preset", "")).strip().lower()
    if preset not in STRATEGY_PRESETS:
        return JSONResponse(
            {"error": f"Unknown preset {preset!r}", "valid": sorted(STRATEGY_PRESETS)},
            status_code=400)
    active_id = app_state.active_account_id
    raw_aid = body.get("account_id", None)
    if raw_aid is None:
        aid = active_id
    else:
        try:
            aid = int(raw_aid)
        except (TypeError, ValueError):
            return JSONResponse({"error": f"account_id must be an integer, got {raw_aid!r}"},
                                status_code=400)
        # Never write a row for an account that does not exist — an unknown id
        # would otherwise silently create/park settings nothing ever reads.
        # list_accounts() is ASYNC (account_registry.py:320) — iterating it
        # unawaited raised TypeError: 'coroutine' object is not iterable, which
        # escaped this route's try/except and returned an EMPTY 500. The branch
        # runs whenever account_id is supplied, and the v3 UI always supplies it
        # (pages-config.jsx:690), so Apply Preset failed for every preset and
        # every target. `await` matches the sibling route (routes_accounts.py:158).
        known = {a["id"] for a in await account_registry.list_accounts()}
        if aid not in known:
            return JSONResponse({"error": f"Unknown account_id {aid}",
                                 "valid": sorted(known)}, status_code=404)
    is_active = (aid == active_id)
    # 1) DD posture -> account_settings (reuse the tested writer)
    try:
        apply_preset(aid, preset)
    except Exception as e:
        log.warning("[apply-preset] settings write failed: %s", e)
        return JSONResponse({"error": f"settings write failed: {e}"}, status_code=500)
    # 2) sizing envelope -> account_params (validated; publishes risk:params_updated)
    sizing = {k: float(v) for k, v in PRESET_PARAMS.get(preset, {}).items()}
    applied_params = {}
    if sizing:
        errors = validate_params(sizing)
        if errors:
            return JSONResponse({"error": "; ".join(errors)}, status_code=400)
        existing = account_registry.get_account_params(aid)
        existing.update(sizing)
        await account_registry.update_account_params(aid, existing)
        applied_params = sizing
        # config-2: app_state.params is the ACTIVE account's live sizing mirror
        # and risk:params_updated tells the engine to re-read it. Both are
        # active-scoped — touching them while writing a DIFFERENT account's row
        # would make the running account size off the other one's preset.
        if is_active:
            app_state.params.update(sizing)
            from core.event_bus import event_bus
            await event_bus.publish("risk:params_updated", {"ts": "preset_apply"})
    return JSONResponse({
        "status":     "ok",
        "preset":     preset,
        "account_id": aid,          # echoed so the UI can prove what it wrote
        "is_active":  is_active,
        "settings":   STRATEGY_PRESETS.get(preset, {}),
        "params":     applied_params,
    })


@router.get("/api/config/exchanges")
async def api_config_exchanges():
    """Adapter catalog for the React Add-Account dialog (2026-07-30).

    Same source the Jinja modal's dropdown used via `_ctx`'s
    `available_exchanges` — non-canonical adapters carry an `is_beta` flag and
    a "(Beta)" label suffix, so the operator can see that Bybit / MEXC are
    adapter-supported but not operator-verified for production trading.
    Without this door React had no way to build the dropdown, which is why
    Add Account shipped disabled.
    """
    from core.adapters.registry import (
        list_rest_exchanges, get_supported_market_types,
    )
    return JSONResponse({
        "exchanges": list_rest_exchanges(),
        "market_types": get_supported_market_types(),
    })


@router.get("/api/config/presets")
async def api_config_presets():
    """The strategy-preset catalog for the React Config Presets tab (v3.0 P2):
    the DD posture (STRATEGY_PRESETS) + the sizing envelope (PRESET_PARAMS) per
    preset. Static config metadata; Apply is POST /api/config/apply-preset."""
    from core.strategy_presets import STRATEGY_PRESETS, PRESET_PARAMS
    presets = [
        {"name": name, "dd": STRATEGY_PRESETS.get(name, {}), "sizing": PRESET_PARAMS.get(name, {})}
        for name in ("scalping", "day_trading", "swing", "position")
    ]
    return JSONResponse({"presets": presets})


# ── P8.T8 (plan §8.9 / spec §3.3): per-account config_json editor ────────────
# A "Calc-Linkage" tab in /config (NOT a separate /settings page — /config IS
# the settings surface; a second config page would be redundant). Reuses the
# T4a write_account_config / merge_config_json writer. notification_subscriptions
# (§8.9 / §12.5) wired in P8.T7 — the form snapshots every type (full replace).


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
    # P8.T7: notification subscription checkboxes (absent -> "" -> False).
    notif_calc_expired: str = Form(""),
    notif_position_liquidated: str = Form(""),
    notif_position_size_drift: str = Form(""),
    notif_duplicate_order_detected: str = Form(""),
    notif_near_replacement_match: str = Form(""),
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
        # P8.T7: notification subscriptions (full snapshot — every type has a
        # checkbox, so a top-level replace loses nothing).
        "notification_subscriptions": {
            "calc_expired":             bool(notif_calc_expired),
            "position_liquidated":      bool(notif_position_liquidated),
            "position_size_drift":      bool(notif_position_size_drift),
            "duplicate_order_detected": bool(notif_duplicate_order_detected),
            "near_replacement_match":   bool(notif_near_replacement_match),
        },
    }
    from core.account_config import write_account_config
    try:
        await write_account_config(db, app_state.active_account_id, updates)
    except Exception:
        log.exception("save_account_config failed")
        return HTMLResponse('<span class="text-red">save failed</span>')
    return HTMLResponse('<span class="text-green">saved ✓</span>')
