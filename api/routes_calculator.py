from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from core.state import app_state
from core.risk_engine import run_risk_calculator
from core.event_bus import event_bus
from core.exchange import fetch_orderbook, fetch_ohlcv
from core import ws_manager
from api.helpers import templates, _ctx

log = logging.getLogger("routes.calculator")
router = APIRouter()


@router.get("/calculator", response_class=HTMLResponse)
async def calculator_page(request: Request):
    return templates.TemplateResponse(request, "calculator.html", _ctx(request, calc=None))


@router.post("/calculator/calculate", response_class=HTMLResponse)
async def calculate_risk(
    request:                 Request,
    ticker:                  str   = Form(...),
    average:                 float = Form(...),
    sl_price:                float = Form(...),
    tp_price:                float = Form(0.0),
    tp_amount_pct:           float = Form(100.0),
    sl_amount_pct:           float = Form(100.0),
    model_name:              str   = Form(""),
    model_desc:              str   = Form(""),
    order_type:              str   = Form("market"),
    auto_refresh:            str   = Form("0"),
    apply_regime_multiplier: str   = Form("1"),
):
    ticker = ticker.upper().strip()
    ws_manager.set_calculator_symbol(ticker)

    try:
        await fetch_orderbook(ticker)
        if ticker not in app_state.ohlcv_cache:
            await fetch_ohlcv(ticker)
    except Exception as e:
        return HTMLResponse(f'<div class="alert alert-error">Data fetch error: {e}</div>')

    calc = run_risk_calculator(
        ticker=ticker, average=average, sl_price=sl_price,
        tp_price=tp_price, tp_amount_pct=tp_amount_pct,
        sl_amount_pct=sl_amount_pct, model_name=model_name, model_desc=model_desc,
        order_type=order_type,
        apply_regime_multiplier=(apply_regime_multiplier == "1"),
    )

    if auto_refresh != "1":
        await event_bus.publish("risk:risk_calculated", calc)

    return templates.TemplateResponse(
        request, "fragments/calc_result.html",
        _ctx(request, calc=calc),
    )


@router.get("/calculator/refresh/{ticker}", response_class=HTMLResponse)
async def calculator_refresh(request: Request, ticker: str):
    ticker = ticker.upper()
    try:
        await fetch_orderbook(ticker)
    except Exception:
        pass

    ob   = app_state.orderbook_cache.get(ticker, {})
    bids = ob.get("bids", [])[:5]
    asks = ob.get("asks", [])[:5]
    return templates.TemplateResponse(
        request, "fragments/orderbook.html",
        {"ticker": ticker, "bids": bids, "asks": asks},
    )
