"""
Model-library routes (v2.7 Phase 3).

Co-locates the JSON API (/api/models — pre-v2.7 contract, extended),
the server-rendered fragments (/fragments/models/*), the Form-post
mutations, the backtest-report upload, and the calculator prefill —
mirroring the routes_backtest.py co-location precedent.

The GET /models PAGE route ships in Phase 4, not here (executed
deviation, plan 3.2): it needs model_library.html + the nav/page_meta
entries — all Phase-4 artifacts — and would 500 template-less today.
Conversely the five fragment TEMPLATES (plan 4.2-4.5) shipped WITH
their routes in this phase.

Response conventions:
- GET fragments: TemplateResponse + _ctx (house idiom).
- Form POST / DELETE mutations: 200 + a status span for the form's
  status target, PLUS an hx-swap-oob re-render of the affected
  fragment(s) (routes_config.py's 200-error-span precedent, extended
  with out-of-band swaps so the list/detail panes refresh in the same
  response — htmx swallows non-2xx bodies).
- Upload errors: 200 + the backtest-list fragment carrying an error
  banner (the list stays rendered). Catches the BASE ValueError — an
  unknown app_id raises plain ValueError from the registry while parse
  raises BacktestAdapterError; both must render, not 500 (P2 audit).

v3.0 P7 additions (the React /v3 Models page):
- JSON doors: `?format=json` on the backtest upload (errors become
  JSON {"error"} with real status codes — a new lane, no htmx
  constraint), plus GET /api/models/overview (G-M3), /{id}/runs,
  /{id}/runs/{run_id}/report (G-M1), /{id}/usage (G-M6), and the
  combined POST /api/models/import (G-M5; `?dry_run=1` = parse-preview,
  no writes). All JSON exits ride _json_safe (F2 both-doors rule).
- Every successful import now also stores the VERBATIM workbook capture
  (G-M2) in report_json, stamps the source filename into
  summary_json["source_file"] (G-M7), and auto-seeds the model's empty
  source binding from the parsed Settings sheet (G-M4/§6-3b) — the
  Jinja upload lane gets all three for free (shared path).
"""
from __future__ import annotations

import asyncio
import json as _pyjson
import logging
import math
from dataclasses import asdict
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from api.helpers import templates, _ctx
from core.backtest_adapters import get_backtest_adapter, list_backtest_adapters
from core.database import db

log = logging.getLogger("routes.models")
router = APIRouter()

VALID_TYPES = ("macro", "micro", "both")

# v2.7 3.4: the upload lands fully in memory before parsing — cap it.
# Single-tenant localhost; the cap guards accidents, not adversaries.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# Raw JSON columns are internal storage — API/fragment consumers get the
# decoded dicts only (P1 audit NIT-3).
_RAW_JSON_KEYS = ("config_json", "risk_preset_json", "strategy_json",
                  "source_json", "tags_json")


def _json_safe_resp(payload, status_code: int = 200) -> JSONResponse:
    """JSONResponse through the house _json_safe non-finite guard (F2
    both-doors discipline; local import mirrors routes_analytics)."""
    from api.routes_calculator import _json_safe
    return JSONResponse(_json_safe(payload), status_code=status_code)


def _clean(model: Dict[str, Any]) -> Dict[str, Any]:
    for key in _RAW_JSON_KEYS:
        model.pop(key, None)
    return model


# ── JSON API (pre-v2.7 contract, extended with the new fields) ──────────────

@router.get("/api/models", response_class=JSONResponse)
async def api_list_models():
    models = await db.list_potential_models()
    return JSONResponse([_clean(m) for m in models])


# NB: declared BEFORE /api/models/{model_id} — FastAPI matches in
# declaration order and the untyped path segment would otherwise
# swallow "overview" into a 422.
@router.get("/api/models/overview", response_class=JSONResponse)
async def api_models_overview():
    """G-M3: the library/overview feed — every model + latest-run
    summary + equity sparkline + runs_count, batched (no N+1)."""
    models = await db.list_models_overview()
    return _json_safe_resp({"models": [_clean(m) for m in models]})


@router.get("/api/models/{model_id}", response_class=JSONResponse)
async def api_get_model(model_id: int):
    model = await db.get_potential_model(model_id)
    if not model:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(_clean(model))


def _has_non_finite(value: Any) -> bool:
    """True when a NaN/Infinity float hides anywhere in a JSON-shaped value.

    v2.7 holistic-audit F2: Python's json.loads accepts NaN/Infinity tokens
    and parses 1e400 to inf, json.dumps stores them — but starlette's
    JSONResponse renders with allow_nan=False, so ONE poisoned model 500s
    GET /api/models for the ENTIRE list (both pickers silently empty).
    Reject at the door instead.
    """
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_has_non_finite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_non_finite(v) for v in value)
    return False


def _validate_model_body(body: Dict[str, Any]) -> Optional[str]:
    """Shared create/update validation. Returns an error string or None."""
    name = body.get("name", "")
    # F16 fold: {"name": null} previously PASSED (str(None)="None") then
    # 500'd at .strip() in the route — reject non-strings here instead.
    if not isinstance(name, str) or not name.strip():
        return "Name is required"
    if not isinstance(body.get("description", ""), str):
        return "Description must be a string"
    if body.get("type", "both") not in VALID_TYPES:
        return "Type must be macro, micro, or both"
    for key in ("risk_preset", "strategy", "config", "source"):
        if key in body and body[key] is not None:
            if not isinstance(body[key], dict):
                return f"{key} must be an object"
            if _has_non_finite(body[key]):
                return f"{key} must not contain NaN or Infinity values"
    if "tags" in body and body["tags"] is not None:
        tags = body["tags"]
        if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
            return "tags must be a list of strings"
        if len(tags) > 32 or any(len(t) > 48 for t in tags):
            return "tags: at most 32 tags of at most 48 chars each"
    return None


def _norm_tags(tags) -> "list | None":
    """None passes through (update = leave untouched); a list is
    trimmed + de-blanked."""
    if tags is None:
        return None
    return [t.strip() for t in tags if t.strip()]


async def _json_object_body(request: Request) -> "Dict[str, Any] | None":
    """The request body as a dict, or None when it isn't one.

    Task D fold of the F16 residual: a valid-JSON-but-non-dict body
    (list/string/number) previously reached _validate_model_body and
    500'd at body.get(...); malformed JSON 500'd at request.json().
    Both are caller errors — 400 at the door.
    """
    try:
        body = await request.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


@router.post("/api/models", response_class=JSONResponse)
async def api_create_model(request: Request):
    body = await _json_object_body(request)
    if body is None:
        return JSONResponse(
            {"error": "Body must be a JSON object"}, status_code=400)
    err = _validate_model_body(body)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    model_id = await db.create_potential_model(
        body.get("name", "").strip(),
        body.get("type", "both"),
        body.get("description", "").strip(),
        body.get("config", {}) or {},
        risk_preset=body.get("risk_preset"),
        strategy=body.get("strategy"),
        source=body.get("source"),
        tags=_norm_tags(body.get("tags")),
    )
    return JSONResponse({"model_id": model_id, "status": "created"})


@router.put("/api/models/{model_id}", response_class=JSONResponse)
async def api_update_model(request: Request, model_id: int):
    body = await _json_object_body(request)
    if body is None:
        return JSONResponse(
            {"error": "Body must be a JSON object"}, status_code=400)
    # v2.7 3.1 fold: update now validates type (was a pre-existing hole —
    # PUT could persist arbitrary type values) and 404s on unknown ids.
    err = _validate_model_body(body)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    if not await db.get_potential_model(model_id):
        return JSONResponse({"error": "Not found"}, status_code=404)
    await db.update_potential_model(
        model_id,
        body.get("name", "").strip(),
        body.get("type", "both"),
        body.get("description", "").strip(),
        body.get("config", {}) or {},
        risk_preset=body.get("risk_preset"),
        strategy=body.get("strategy"),
        source=body.get("source"),
        tags=_norm_tags(body.get("tags")),
    )
    return JSONResponse({"status": "updated"})


@router.delete("/api/models/{model_id}", response_class=JSONResponse)
async def api_delete_model(model_id: int):
    await db.delete_potential_model(model_id)
    return JSONResponse({"status": "deleted"})


# ── v3.0 P7 JSON doors (runs list · verbatim report · usage feed) ───────────

@router.get("/api/models/{model_id}/runs", response_class=JSONResponse)
async def api_model_runs(model_id: int):
    """Imported-run list for a model (summary-only — the verbatim
    capture rides the per-run report endpoint, never the list)."""
    if not await db.get_potential_model(model_id):
        return JSONResponse({"error": "Not found"}, status_code=404)
    runs = await db.list_model_backtests(model_id)
    for r in runs:
        r.pop("config_json", None)
        r.pop("summary_json", None)
    return _json_safe_resp({"runs": runs})


@router.get("/api/models/{model_id}/runs/{run_id}/report",
            response_class=JSONResponse)
async def api_model_run_report(model_id: int, run_id: int):
    """G-M1: one run with its verbatim workbook capture + equity +
    normalized trades. `report` is null for engine-run / pre-P7 rows
    (the UI falls back to the derived summary/trades)."""
    data = await db.get_model_backtest_report(model_id, run_id)
    if data is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return _json_safe_resp(data)


@router.get("/api/models/{model_id}/usage", response_class=JSONResponse)
async def api_model_usage(model_id: int):
    """G-M6: reverse attribution — closed positions + pre-trade plans
    tagged with this model (open positions surface once closed; named
    P7 deviation — no durable open-position model_id source)."""
    if not await db.get_potential_model(model_id):
        return JSONResponse({"error": "Not found"}, status_code=404)
    usage = await db.get_model_usage(model_id)
    return _json_safe_resp(usage)


# ── Page (v2.7 Phase 4 — moved here from 3.2 once the template existed) ─────

@router.get("/models", response_class=HTMLResponse)
async def models_page(request: Request):
    return templates.TemplateResponse(
        request, "model_library.html", _ctx(request, active_page="models")
    )


# ── Fragments (GET — TemplateResponse + _ctx house idiom) ────────────────────

@router.get("/fragments/models/list", response_class=HTMLResponse)
async def frag_model_list(request: Request):
    models = await db.list_potential_models()
    return templates.TemplateResponse(
        request, "fragments/model_list.html", _ctx(request, models=models)
    )


@router.get("/fragments/models/detail/{model_id}", response_class=HTMLResponse)
async def frag_model_detail(request: Request, model_id: int):
    model = await db.get_potential_model(model_id)
    if not model:
        return HTMLResponse("<p class='text-red'>Model not found.</p>")
    runs = await db.list_model_backtests(model_id)
    return templates.TemplateResponse(
        request, "fragments/model_detail.html",
        _ctx(request, model=model, runs=runs,
             adapters=list_backtest_adapters()),
    )


@router.get("/fragments/models/form", response_class=HTMLResponse)
async def frag_model_form_blank(request: Request):
    return templates.TemplateResponse(
        request, "fragments/model_form.html", _ctx(request, model=None)
    )


@router.get("/fragments/models/form/{model_id}", response_class=HTMLResponse)
async def frag_model_form_edit(request: Request, model_id: int):
    model = await db.get_potential_model(model_id)
    if not model:
        return HTMLResponse("<p class='text-red'>Model not found.</p>")
    return templates.TemplateResponse(
        request, "fragments/model_form.html", _ctx(request, model=model)
    )


@router.get("/fragments/models/backtests/{model_id}", response_class=HTMLResponse)
async def frag_model_backtests(request: Request, model_id: int):
    """Standalone refresh hook for the detail pane's run list (Phase-4
    lazy-load target). The upload POST re-renders the same fragment
    directly; this GET exists so the list is independently refreshable."""
    runs = await db.list_model_backtests(model_id)
    return templates.TemplateResponse(
        request, "fragments/model_backtest_list.html",
        _ctx(request, runs=runs, error=""),
    )


# ── Form mutations (200 status span + hx-swap-oob refresh) ──────────────────

def _render_fragment(name: str, **ctx) -> str:
    """Render a fragment WITHOUT a request (for oob composition in POST
    responses). The model fragments are request-independent by design —
    they read only the vars passed here."""
    return templates.env.get_template(name).render(**ctx)


async def _oob_list() -> str:
    models = await db.list_potential_models()
    inner = _render_fragment("fragments/model_list.html", models=models)
    return f'<div id="model-list" hx-swap-oob="innerHTML">{inner}</div>'


def _err_span(msg: str) -> HTMLResponse:
    return HTMLResponse(f'<span class="text-red">{msg}</span>')


def _parse_model_form(
    name: str, model_type: str, description: str,
    risk_pct: str, sizing_rule: str, window_seconds: str,
    tp_methodology: str, sl_methodology: str,
    apply_regime_multiplier: str, size_override_default: str,
    entry_logic: str, exit_logic: str, target_universe: str,
    regime_config: str, notes: str,
) -> Tuple[Optional[str], Dict[str, Any], Dict[str, Any], Dict[str, str]]:
    """Validate + shape the model form. Returns (error, base, preset, strategy).

    Numeric preset fields are stored only when set; the regime toggle is a
    checkbox (absent -> "" -> False, the config-form full-snapshot idiom).
    The form is a FULL-SNAPSHOT editor of the known preset/strategy keys —
    extra keys set via the JSON API are dropped on a UI edit save (the
    JSON API stays the power path for arbitrary keys).
    """
    if not name.strip():
        return "Name is required", {}, {}, {}
    if model_type not in VALID_TYPES:
        return "Type must be macro, micro, or both", {}, {}, {}
    preset: Dict[str, Any] = {
        "apply_regime_multiplier": bool(apply_regime_multiplier),
    }
    try:
        if risk_pct.strip():
            val = float(risk_pct)
            if not 0 < val <= 100:
                return "Risk % must be in (0, 100]", {}, {}, {}
            preset["risk_pct"] = val
        if window_seconds.strip():
            wval = int(window_seconds)
            if wval <= 0:
                return "Window seconds must be > 0", {}, {}, {}
            preset["window_seconds"] = wval
        if size_override_default.strip():
            sval = float(size_override_default)
            # v2.7 holistic-audit F2: nan/inf pass `<= 0` (NaN comparisons
            # are False; inf > 0) — the exact trap routes_calculator guards
            # with math.isfinite. A stored non-finite poisons every JSON
            # endpoint reading this model (F2 blast radius).
            if not math.isfinite(sval) or sval <= 0:
                return "Size override must be a finite number > 0", {}, {}, {}
            preset["size_override_default"] = sval
    except ValueError:
        return "Risk %, window seconds and size override must be numeric", {}, {}, {}
    for key, raw in (("sizing_rule", sizing_rule),
                     ("tp_methodology", tp_methodology),
                     ("sl_methodology", sl_methodology)):
        if raw.strip():
            preset[key] = raw.strip()
    strategy = {
        "entry_logic": entry_logic.strip(),
        "exit_logic": exit_logic.strip(),
        "target_universe": target_universe.strip(),
        "regime_config": regime_config.strip(),
        "notes": notes.strip(),
    }
    base = {"name": name.strip(), "type": model_type,
            "description": description.strip()}
    return None, base, preset, strategy


def _form_fields() -> Dict[str, Any]:
    """Fresh Form() FieldInfo instances per route signature — FastAPI can
    mutate FieldInfo during param analysis, so sharing one set across two
    routes is fragile (P3 audit NIT-5)."""
    return dict(
        name=Form(""), model_type=Form("both", alias="type"),
        description=Form(""),
        risk_pct=Form(""), sizing_rule=Form(""), window_seconds=Form(""),
        tp_methodology=Form(""), sl_methodology=Form(""),
        apply_regime_multiplier=Form(""), size_override_default=Form(""),
        entry_logic=Form(""), exit_logic=Form(""), target_universe=Form(""),
        regime_config=Form(""), notes=Form(""),
    )


_CREATE_FIELDS = _form_fields()
_UPDATE_FIELDS = _form_fields()


@router.post("/models", response_class=HTMLResponse)
async def create_model_form(
    request: Request,
    name: str = _CREATE_FIELDS["name"],
    model_type: str = _CREATE_FIELDS["model_type"],
    description: str = _CREATE_FIELDS["description"],
    risk_pct: str = _CREATE_FIELDS["risk_pct"],
    sizing_rule: str = _CREATE_FIELDS["sizing_rule"],
    window_seconds: str = _CREATE_FIELDS["window_seconds"],
    tp_methodology: str = _CREATE_FIELDS["tp_methodology"],
    sl_methodology: str = _CREATE_FIELDS["sl_methodology"],
    apply_regime_multiplier: str = _CREATE_FIELDS["apply_regime_multiplier"],
    size_override_default: str = _CREATE_FIELDS["size_override_default"],
    entry_logic: str = _CREATE_FIELDS["entry_logic"],
    exit_logic: str = _CREATE_FIELDS["exit_logic"],
    target_universe: str = _CREATE_FIELDS["target_universe"],
    regime_config: str = _CREATE_FIELDS["regime_config"],
    notes: str = _CREATE_FIELDS["notes"],
):
    err, base, preset, strategy = _parse_model_form(
        name, model_type, description, risk_pct, sizing_rule, window_seconds,
        tp_methodology, sl_methodology, apply_regime_multiplier,
        size_override_default, entry_logic, exit_logic, target_universe,
        regime_config, notes,
    )
    if err:
        return _err_span(err)
    model_id = await db.create_potential_model(
        base["name"], base["type"], base["description"], {},
        risk_preset=preset, strategy=strategy,
    )
    oob = await _oob_list()
    return HTMLResponse(
        f'<span class="text-green">saved ✓ (#{model_id})</span>{oob}'
    )


@router.post("/models/{model_id}/update", response_class=HTMLResponse)
async def update_model_form(
    request: Request,
    model_id: int,
    name: str = _UPDATE_FIELDS["name"],
    model_type: str = _UPDATE_FIELDS["model_type"],
    description: str = _UPDATE_FIELDS["description"],
    risk_pct: str = _UPDATE_FIELDS["risk_pct"],
    sizing_rule: str = _UPDATE_FIELDS["sizing_rule"],
    window_seconds: str = _UPDATE_FIELDS["window_seconds"],
    tp_methodology: str = _UPDATE_FIELDS["tp_methodology"],
    sl_methodology: str = _UPDATE_FIELDS["sl_methodology"],
    apply_regime_multiplier: str = _UPDATE_FIELDS["apply_regime_multiplier"],
    size_override_default: str = _UPDATE_FIELDS["size_override_default"],
    entry_logic: str = _UPDATE_FIELDS["entry_logic"],
    exit_logic: str = _UPDATE_FIELDS["exit_logic"],
    target_universe: str = _UPDATE_FIELDS["target_universe"],
    regime_config: str = _UPDATE_FIELDS["regime_config"],
    notes: str = _UPDATE_FIELDS["notes"],
):
    existing = await db.get_potential_model(model_id)
    if not existing:
        return _err_span("Model not found")
    err, base, preset, strategy = _parse_model_form(
        name, model_type, description, risk_pct, sizing_rule, window_seconds,
        tp_methodology, sl_methodology, apply_regime_multiplier,
        size_override_default, entry_logic, exit_logic, target_universe,
        regime_config, notes,
    )
    if err:
        return _err_span(err)
    # The new form has no config editor — pass the STORED config through
    # (P3 audit MED-1): legacy models built in backtest.html's old panel
    # carry config.signals/risk/regime that its JS still reads during the
    # two-editors coexistence window (until Phase 6 retires it); an
    # unconditional {} here silently destroyed it.
    await db.update_potential_model(
        model_id, base["name"], base["type"], base["description"],
        existing["config"],
        risk_preset=preset, strategy=strategy,
    )
    oob = await _oob_list()
    return HTMLResponse(f'<span class="text-green">updated ✓</span>{oob}')


@router.delete("/models/{model_id}", response_class=HTMLResponse)
async def delete_model_form(model_id: int):
    """Deletes the model + its imported runs; the detail pane is replaced
    (this response is the hx-target) and the list refreshes out-of-band."""
    await db.delete_potential_model(model_id)
    oob = await _oob_list()
    return HTMLResponse(
        f'<p style="color:var(--muted);font-size:.72rem;">Model deleted.</p>{oob}'
    )


# ── Backtest-report upload (the codebase's first multipart route) ───────────

def _upload_size_error(file: UploadFile, raw: "bytes | None") -> Optional[str]:
    """The v2.7 Task C (F14) size discipline, shared by both import
    routes: reject on the parser-measured UploadFile.size BEFORE read()
    materializes it into RAM; the post-read check stays as the belt
    (size can be None). Call once pre-read (raw=None), once post-read."""
    n = len(raw) if raw is not None else (file.size or 0)
    if n > MAX_UPLOAD_BYTES:
        return (f"File too large ({n // (1024 * 1024)} MB > "
                f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
    if raw is not None and not raw:
        return "Empty file."
    return None


async def _parse_and_capture(app_id: str, raw: bytes, filename: str):
    """Adapter parse (off-loop — v2.7 F8) + the G-M2 verbatim capture.
    Returns (adapter, result, capture, warnings). Parse errors raise
    ValueError (the caller renders); a capture failure AFTER a
    successful parse degrades to capture=None with a warning — the
    derived import still lands."""
    adapter = get_backtest_adapter(app_id)  # unknown app_id: ValueError
    result = await asyncio.to_thread(adapter.parse, raw, filename)
    capture = None
    if hasattr(adapter, "capture"):
        try:
            capture = await asyncio.to_thread(adapter.capture, raw, filename)
        except ValueError as exc:
            log.warning("[p7] capture failed after successful parse "
                        "(app=%s file=%r): %s", app_id, filename, exc)
    warnings = []
    if not result.trades:
        warnings.append("no trades parsed from the trade list")
    if capture is None:
        warnings.append("verbatim capture unavailable — run stores "
                        "summary/trades only")
    else:
        # ANCHOR (P7 audit NIT): the sheet/setting names below are
        # MultiCharts-specific inside an adapter-generic helper — fine
        # while MC is the only capture-capable adapter; when adapter #2
        # lands, move these expectations onto the adapter (e.g. an
        # `expected_sheets` attr) instead of growing this if-ladder.
        names = {s.get("name") for s in capture.get("sheets", [])}
        if "Strategy Analysis" not in names:
            warnings.append("'Strategy Analysis' sheet missing — summary "
                            "derived from trades")
    pv = _mc_to_float(result.settings.get("Point Value"))
    if pv is None or pv <= 0:
        warnings.append("Settings 'Point Value' missing/invalid — "
                        "size_usdt uses point value 1.0")
    return adapter, result, capture, warnings


def _preview_payload(adapter, result, capture, warnings, filename: str) -> Dict[str, Any]:
    """The shared dry-run preview shape (both import routes serve it —
    one builder, no shape drift; P7 audit NIT fold)."""
    return {
        "preview": True,
        "file": filename,
        "source_app": adapter.app_id,
        "session_name": result.session_name,
        "summary": asdict(result.summary),
        "settings": result.settings,
        "trades_count": len(result.trades),
        "sheets": [s.get("name") for s in (capture or {}).get("sheets", [])],
        "warnings": warnings,
        "source_suggestion": _source_from_settings(result.settings, adapter),
    }


def _mc_to_float(value):
    """Deferred import of the MultiCharts tolerant coercer ($/,/% aware)
    — reused for Settings-derived numbers, single source of truth."""
    from core.backtest_adapters.multicharts import _to_float
    return _to_float(value)


def _source_from_settings(settings: Dict[str, str], adapter) -> Dict[str, Any]:
    """G-M4/§6-3b: the model source binding derived from a parsed
    Settings sheet. Only keys the sheet actually carries; {} when the
    sheet yields nothing bindable (callers skip the seed)."""
    if not settings:
        return {}
    out: Dict[str, Any] = {}
    for key, setting in (("symbol", "Symbol Name"), ("resolution", "Compression"),
                         ("currency", "Symbol Currency"),
                         ("commission", "Commission"), ("slippage", "Slippage")):
        v = (settings.get(setting) or "").strip()
        if v:
            out[key] = v
    for key, setting in (("point_value", "Point Value"),
                         ("initial_capital", "Initial Capital")):
        v = _mc_to_float(settings.get(setting))
        if v is not None and math.isfinite(v) and v > 0:
            out[key] = v
    if not out:
        return {}
    out["app"] = getattr(adapter, "display_name", "") or adapter.app_id
    return out


@router.post("/models/{model_id}/backtest-upload")
async def upload_model_backtest(
    request: Request,
    model_id: int,
    file: UploadFile = File(...),
    app_id: str = Form("multicharts"),
    format: str = "",
    dry_run: str = "",
):
    """Parse an external report and attach it to the model as an imported
    run. Default (htmx) lane: every response is 200 + the backtest-list
    fragment (with an error banner on failure) so the list container
    swaps cleanly either way. `?format=json` (v3.0 P7): JSON responses
    with real status codes; `&dry_run=1` = parse-preview, NO writes."""
    is_json = format == "json"
    want_dry = dry_run in ("1", "true", "yes")

    async def _list_response(error: str = "", status: int = 400):
        if is_json:
            return JSONResponse({"error": error}, status_code=status)
        runs = await db.list_model_backtests(model_id)
        return HTMLResponse(_render_fragment(
            "fragments/model_backtest_list.html", runs=runs, error=error,
        ))

    # P7 audit LOW-1 fold: the htmx lane has no preview UI, so a dry_run
    # request outside the JSON lane must FAIL LOUD, never silently commit
    # a real import (the sibling /api/models/import honors bare dry_run).
    if want_dry and not is_json:
        return JSONResponse(
            {"error": "dry_run requires format=json"}, status_code=400)
    if not await db.get_potential_model(model_id):
        return await _list_response("Model not found.", status=404)
    err = _upload_size_error(file, None)
    if err:
        return await _list_response(err)
    raw = await file.read()
    err = _upload_size_error(file, raw)
    if err:
        return await _list_response(err)
    filename = file.filename or ""
    try:
        adapter, result, capture, warnings = await _parse_and_capture(
            app_id, raw, filename)
    except ValueError as exc:  # includes BacktestAdapterError
        return await _list_response(str(exc))

    if want_dry:
        return _json_safe_resp(
            _preview_payload(adapter, result, capture, warnings, filename))

    payload = asdict(result)
    # §6-3b: persist the Settings-sheet params read-only — they ride
    # summary_json (free-form). Rendered as a collapsed <details> row in
    # the run LIST (model_backtest_list.html; Task D/F12 — there is no
    # separate run-detail view in the minimal v2.7 UI).
    payload["summary"]["settings"] = payload.pop("settings", {})
    payload["summary"]["source_file"] = filename  # G-M7
    try:
        session_id = await db.create_model_backtest(
            model_id, adapter.app_id, payload, report=capture)
    except Exception:
        # create_model_backtest is atomic (deletes its session on failure),
        # so nothing was saved.
        log.exception("backtest import failed post-parse (model %s)", model_id)
        return await _list_response(
            "Import failed after parse — nothing saved.", status=500)
    seeded = await db.seed_model_source_if_empty(
        model_id, _source_from_settings(result.settings, adapter))
    if is_json:
        return _json_safe_resp({
            "run_id": session_id,
            "model_id": model_id,
            "file": filename,
            "summary": payload["summary"],
            "warnings": warnings,
            "source_seeded": seeded,
        })
    return await _list_response()


@router.post("/api/models/import", response_class=JSONResponse)
async def api_create_model_and_import(
    file: UploadFile = File(...),
    app_id: str = Form("multicharts"),
    payload: str = Form(""),
    dry_run: str = "",
):
    """G-M5: combined create-model-and-import (JSON, multipart).
    `payload` = the JSON model body (same shape as POST /api/models).
    `?dry_run=1` = parse-preview only — no model, no run, no payload
    needed (the create-form's autofill lane). On an import failure the
    just-created model is rolled back — the operation is all-or-nothing."""
    err = _upload_size_error(file, None)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    raw = await file.read()
    err = _upload_size_error(file, raw)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    filename = file.filename or ""
    try:
        adapter, result, capture, warnings = await _parse_and_capture(
            app_id, raw, filename)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    source_suggestion = _source_from_settings(result.settings, adapter)
    if dry_run in ("1", "true", "yes"):
        return _json_safe_resp(
            _preview_payload(adapter, result, capture, warnings, filename))

    try:
        body = _pyjson.loads(payload) if payload else None
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(
            {"error": "payload must be a JSON object (the model body)"},
            status_code=400)
    verr = _validate_model_body(body)
    if verr:
        return JSONResponse({"error": verr}, status_code=400)
    model_id = await db.create_potential_model(
        body.get("name", "").strip(),
        body.get("type", "both"),
        body.get("description", "").strip(),
        body.get("config", {}) or {},
        risk_preset=body.get("risk_preset"),
        strategy=body.get("strategy"),
        # An explicit source wins; otherwise bind the import's Settings.
        source=body.get("source") or source_suggestion or None,
        tags=_norm_tags(body.get("tags")),
    )
    imp = asdict(result)
    imp["summary"]["settings"] = imp.pop("settings", {})
    imp["summary"]["source_file"] = filename  # G-M7
    try:
        run_id = await db.create_model_backtest(
            model_id, adapter.app_id, imp, report=capture)
    except Exception:
        log.exception("create+import: import failed post-create "
                      "(model %s rolled back)", model_id)
        await db.delete_potential_model(model_id)
        return JSONResponse(
            {"error": "Import failed after parse — model not created."},
            status_code=500)
    return _json_safe_resp({
        "model_id": model_id,
        "run_id": run_id,
        "file": filename,
        "summary": imp["summary"],
        "warnings": warnings,
    })


# ── Calculator prefill (3.5 — consumed by the Phase-5 picker) ────────────────

@router.get("/calculator/prefill/{model_id}", response_class=JSONResponse)
async def calculator_prefill(model_id: int):
    model = await db.get_potential_model(model_id)
    if not model:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse({
        "model_id": model_id,
        "name": model["name"],
        "risk_preset": model["risk_preset"],
    })
