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
"""
from __future__ import annotations

import logging
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
_RAW_JSON_KEYS = ("config_json", "risk_preset_json", "strategy_json")


def _clean(model: Dict[str, Any]) -> Dict[str, Any]:
    for key in _RAW_JSON_KEYS:
        model.pop(key, None)
    return model


# ── JSON API (pre-v2.7 contract, extended with the new fields) ──────────────

@router.get("/api/models", response_class=JSONResponse)
async def api_list_models():
    models = await db.list_potential_models()
    return JSONResponse([_clean(m) for m in models])


@router.get("/api/models/{model_id}", response_class=JSONResponse)
async def api_get_model(model_id: int):
    model = await db.get_potential_model(model_id)
    if not model:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(_clean(model))


def _validate_model_body(body: Dict[str, Any]) -> Optional[str]:
    """Shared create/update validation. Returns an error string or None."""
    if not str(body.get("name", "")).strip():
        return "Name is required"
    if body.get("type", "both") not in VALID_TYPES:
        return "Type must be macro, micro, or both"
    for key in ("risk_preset", "strategy", "config"):
        if key in body and body[key] is not None and not isinstance(body[key], dict):
            return f"{key} must be an object"
    return None


@router.post("/api/models", response_class=JSONResponse)
async def api_create_model(request: Request):
    body = await request.json()
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
    )
    return JSONResponse({"model_id": model_id, "status": "created"})


@router.put("/api/models/{model_id}", response_class=JSONResponse)
async def api_update_model(request: Request, model_id: int):
    body = await request.json()
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
    )
    return JSONResponse({"status": "updated"})


@router.delete("/api/models/{model_id}", response_class=JSONResponse)
async def api_delete_model(model_id: int):
    await db.delete_potential_model(model_id)
    return JSONResponse({"status": "deleted"})


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
            if sval <= 0:
                return "Size override must be > 0", {}, {}, {}
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

@router.post("/models/{model_id}/backtest-upload", response_class=HTMLResponse)
async def upload_model_backtest(
    request: Request,
    model_id: int,
    file: UploadFile = File(...),
    app_id: str = Form("multicharts"),
):
    """Parse an external report and attach it to the model as an imported
    run. Every response is 200 + the backtest-list fragment (with an error
    banner on failure) so the list container swaps cleanly either way."""
    async def _list_response(error: str = "") -> HTMLResponse:
        runs = await db.list_model_backtests(model_id)
        return HTMLResponse(_render_fragment(
            "fragments/model_backtest_list.html", runs=runs, error=error,
        ))

    if not await db.get_potential_model(model_id):
        return await _list_response("Model not found.")
    raw = await file.read()
    if not raw:
        return await _list_response("Empty file.")
    if len(raw) > MAX_UPLOAD_BYTES:
        return await _list_response(
            f"File too large ({len(raw) // (1024 * 1024)} MB > "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB)."
        )
    try:
        adapter = get_backtest_adapter(app_id)  # unknown app_id: ValueError
        result = adapter.parse(raw, file.filename or "")
    except ValueError as exc:  # includes BacktestAdapterError
        return await _list_response(str(exc))

    payload = asdict(result)
    # §6-3b: persist the Settings-sheet params so the run detail can show
    # them read-only — they ride summary_json (free-form).
    payload["summary"]["settings"] = payload.pop("settings", {})
    try:
        await db.create_model_backtest(model_id, adapter.app_id, payload)
    except Exception:
        # create_model_backtest is atomic (deletes its session on failure),
        # so nothing was saved.
        log.exception("backtest import failed post-parse (model %s)", model_id)
        return await _list_response("Import failed after parse — nothing saved.")
    return await _list_response()


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
