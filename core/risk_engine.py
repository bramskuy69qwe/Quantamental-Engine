"""
Risk calculation engine — Quantamental Engine v2.1.

PRD step-by-step chain:
  1. atr_c       = ATR(100,4h) / ATR(14,4h), capped at 1.0
  2. risk_usdt   = individual_risk × total_equity
  3. base_size   = risk_usdt × atr_c / sl_pct              [USDT notional, pre-slippage]
  4. est_fill_price = VWAP walk on orderbook (base_size as USDT budget)
  5. est_slippage   = |est_fill_price − average| / average
  6. est_slippage_usdt = est_slippage × est_size
  7. est_size    = base_size × (1 − est_slippage)          [USDT notional, post-slippage]
  8. _size       = est_size / average                       [contracts, displayed]
  9. est_profit  = tp_usdt − 2×maker_fee − 2×est_slippage_usdt
  10. est_loss   = sl_usdt − 2×maker_fee − 2×est_slippage_usdt
  11. est_rr     = est_profit / est_loss
  12. est_exposure = (total_notional + est_size) / total_equity
"""
from __future__ import annotations
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import config
from core.state import app_state


# ── ATR ───────────────────────────────────────────────────────────────────────

def _wilder_atr(ohlcv: List, period: int) -> Optional[float]:
    """Wilder's smoothed ATR from [ts, open, high, low, close, vol] candles."""
    if len(ohlcv) < period + 1:
        return None

    highs  = np.array([c[2] for c in ohlcv], dtype=float)
    lows   = np.array([c[3] for c in ohlcv], dtype=float)
    closes = np.array([c[4] for c in ohlcv], dtype=float)

    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:]  - closes[:-1]),
        )
    )

    atr   = float(np.mean(tr[:period]))
    alpha = 1.0 / period
    for t in tr[period:]:
        atr = atr * (1.0 - alpha) + float(t) * alpha
    return atr


def calculate_atr_coefficient(
    symbol: str,
) -> Tuple[Optional[float], str, Optional[float], Optional[float]]:
    """
    Returns (atr_c, category, atr14, atr100).

    PRD categories:
      atr_c < 0.2          → too_volatile  (red,   ineligible)
      0.2 ≤ atr_c < 0.6    → volatile      (yellow)
      0.6 ≤ atr_c < 1.0    → normal        (green)
      atr_c ≥ 1.0 (capped) → not_volatile  (green)
    """
    ohlcv = app_state.ohlcv_cache.get(symbol, [])
    if not ohlcv or len(ohlcv) < config.ATR_LONG_PERIOD + 1:
        return None, "unknown", None, None

    atr14  = _wilder_atr(ohlcv, config.ATR_SHORT_PERIOD)
    atr100 = _wilder_atr(ohlcv, config.ATR_LONG_PERIOD)

    if atr14 is None or atr100 is None or atr14 == 0:
        return None, "unknown", None, None

    raw_ratio = atr100 / atr14
    atr_c     = min(raw_ratio, 1.0)

    if atr_c < 0.2:
        category = "too_volatile"
    elif atr_c < 0.6:
        category = "volatile"
    elif raw_ratio >= 1.0:
        category = "not_volatile"
    else:
        category = "normal"

    return atr_c, category, atr14, atr100


# ── VWAP / slippage ───────────────────────────────────────────────────────────

def estimate_vwap_fill(symbol: str, side: str, notional_usdt: float,
                       entry_price: float) -> float:
    """
    PRD: est_fill_price = Σ(Si × Pi) / S_total
      Si = contracts filled at level i  (= fill_usdt_i / Pi)
      Pi = price at level i
      S_total = total contracts filled
    Walk the orderbook spending `notional_usdt` USDT budget.
    side = "long" → consume asks; "short" → consume bids
    """
    ob = app_state.orderbook_cache.get(symbol)
    if not ob:
        return entry_price

    orders = ob.get("asks", []) if side == "long" else ob.get("bids", [])
    if not orders:
        return entry_price

    remaining_usdt = notional_usdt
    total_cost     = 0.0   # Σ(Si × Pi)
    total_qty      = 0.0   # S_total

    for price, qty in orders:
        price      = float(price)
        qty        = float(qty)
        if price <= 0:
            continue
        avail_usdt = price * qty
        fill_usdt  = min(remaining_usdt, avail_usdt)
        fill_qty   = fill_usdt / price      # Si
        total_cost += fill_usdt             # Si × Pi
        total_qty  += fill_qty              # S_total
        remaining_usdt -= fill_usdt
        if remaining_usdt <= 0:
            break

    if total_qty == 0:
        return entry_price
    return total_cost / total_qty           # est_fill_price


def calculate_slippage(
    symbol: str, side: str, notional_usdt: float, entry_price: float,
) -> Tuple[float, float]:
    """
    Returns (est_slippage, est_fill_price).

    Slippage = market impact = how far the VWAP fill deviates from the
    best bid/ask (top of book), NOT from the user's entry price.

    Reference: best_ask (long) or best_bid (short).
      - Order fits within first level → est_fill == best_price → slippage = 0
      - Order sweeps multiple levels → est_fill deviates → slippage > 0
    """
    ob = app_state.orderbook_cache.get(symbol)
    if not ob or entry_price <= 0:
        return 0.0, entry_price

    orders = ob.get("asks", []) if side == "long" else ob.get("bids", [])
    if not orders:
        return 0.0, entry_price

    best_price     = float(orders[0][0])            # best ask or best bid
    est_fill_price = estimate_vwap_fill(symbol, side, notional_usdt, entry_price)

    # Market impact: VWAP deviation from top-of-book reference
    if side == "long":
        est_slippage = max(0.0, (est_fill_price - best_price) / best_price)
    else:
        est_slippage = max(0.0, (best_price - est_fill_price) / best_price)

    return est_slippage, est_fill_price


def calculate_one_percent_depth(symbol: str, entry_price: float) -> float:
    """Total liquidity (USDT) within ±1% of entry price."""
    ob = app_state.orderbook_cache.get(symbol)
    if not ob or entry_price <= 0:
        return 0.0

    lo = entry_price * 0.99
    hi = entry_price * 1.01
    depth = 0.0

    for price, qty in ob.get("asks", []):
        p = float(price)
        if lo <= p <= hi:
            depth += float(price) * float(qty)

    for price, qty in ob.get("bids", []):
        p = float(price)
        if lo <= p <= hi:
            depth += float(price) * float(qty)

    return depth


# ── Position sizing ───────────────────────────────────────────────────────────

def calculate_position_size(
    symbol:       str,
    average:      float,
    sl_price:     float,
    total_equity: float,
    side:         str,      # "long" | "short"
) -> Dict:
    """
    Implements the full PRD sizing chain.
    Returns dict including base_size, est_fill_price, atr14, atr100.
    """
    import uuid
    calc_id = uuid.uuid4().hex

    result: Dict = {
        "calc_id":         calc_id,
        "atr_c":           None,
        "atr_category":    "unknown",
        "atr14":           None,
        "atr100":          None,
        "risk_usdt":       0.0,
        "base_size":       0.0,   # USDT notional, pre-slippage
        "est_fill_price":  0.0,
        "est_slippage":    0.0,
        "effective_entry": 1.0,   # = 1 − est_slippage
        "size":            0.0,   # contracts = est_size / average
        "eligible":        True,
        "ineligible_reason": "",
    }

    # SC-2: engine_ready gate — refuse sizing when critical data missing
    from core.monitoring import ReadyStateEvaluator
    engine_ready, ready_reason = ReadyStateEvaluator().evaluate()
    if not engine_ready:
        result["eligible"] = False
        result["ineligible_reason"] = f"Engine not ready: {ready_reason}"
        return result

    # 0d: capability gate — refuse sizing if adapter doesn't support orders
    try:
        from core.exchange import _get_adapter
        from core.adapters.protocols import require_capability, AdapterCapabilityError
        adapter = _get_adapter()
        require_capability(adapter, "orders")
    except AdapterCapabilityError as exc:
        result["eligible"] = False
        result["ineligible_reason"] = str(exc)
        return result
    except Exception:
        pass  # adapter unavailable — ReadyStateEvaluator already handles this

    if average <= 0 or sl_price <= 0:
        result["eligible"] = False
        result["ineligible_reason"] = "Invalid entry or SL price."
        return result

    sl_pct = abs(sl_price - average) / average
    if sl_pct == 0:
        result["eligible"] = False
        result["ineligible_reason"] = "SL price equals entry — zero risk distance."
        return result

    # Step 1: ATR coefficient + raw values
    atr_c, category, atr14, atr100 = calculate_atr_coefficient(symbol)
    result["atr_c"]        = atr_c
    result["atr_category"] = category
    result["atr14"]        = atr14
    result["atr100"]       = atr100

    if category == "too_volatile":
        result["eligible"]          = False
        result["ineligible_reason"] = "Volatility exceeds maximum threshold (atr_c < 0.2)."
        atr_c = 0.0

    if atr_c is None:
        atr_c = 1.0     # fallback when OHLCV data not yet loaded

    # Step 2: risk_usdt = individual_risk × total_equity
    risk_usdt = app_state.params["individual_risk_per_trade"] * total_equity
    result["risk_usdt"] = risk_usdt

    # Step 3: base_size = risk_usdt × atr_c / sl_pct  [USDT notional, pre-slippage]
    base_size = (atr_c * risk_usdt) / sl_pct
    result["base_size"] = base_size

    # Step 4: est_fill_price via VWAP walk using base_size as USDT budget
    # Step 5: est_slippage = |est_fill_price − average| / average
    est_slippage, est_fill_price = calculate_slippage(symbol, side, base_size, average)
    result["est_slippage"]    = est_slippage
    result["effective_entry"] = 1.0 - est_slippage
    result["est_fill_price"]  = est_fill_price

    # Step 6–8: est_size = base_size × (1 − est_slippage); _size = est_size / average
    if result["eligible"]:
        est_size = base_size * (1.0 - est_slippage)
        result["size"] = est_size / average if average > 0 else 0.0
    # else size stays 0.0

    return result


# ── Correlated exposure ───────────────────────────────────────────────────────

def get_correlated_exposure() -> Dict[str, float]:
    """Net notional per sector (long = positive, short = negative)."""
    sector_net: Dict[str, float] = {}
    for p in app_state.positions:
        sign = 1.0 if p.direction == "LONG" else -1.0
        sector_net[p.sector] = sector_net.get(p.sector, 0.0) + sign * p.position_value_usdt
    return sector_net


def check_correlated_limit(
    symbol: str, size: float, average: float, side: str, total_equity: float,
) -> Tuple[bool, float]:
    """Returns (exceeds_limit, new_sector_exposure_abs)."""
    max_corr     = app_state.params["max_correlated_exposure"] * total_equity
    sector       = config.get_sector(symbol)
    existing     = get_correlated_exposure()
    existing_net = existing.get(sector, 0.0)
    new_notional = size * average * (1.0 if side == "long" else -1.0)
    new_net_abs  = abs(existing_net + new_notional)
    return (new_net_abs > max_corr), new_net_abs


# ── Full risk calculator output ───────────────────────────────────────────────

def run_risk_calculator(
    ticker:                 str,
    average:                float,
    sl_price:               float,
    tp_price:               float,
    tp_amount_pct:          float,   # 0–100
    sl_amount_pct:          float,   # 0–100
    model_name:             str = "",
    model_desc:             str = "",
    order_type:             str = "market",   # "market" | "limit" | "stop"
    apply_regime_multiplier: bool = True,
) -> Dict:
    """Returns the full PRD-compliant risk calculator output dict."""
    acc          = app_state.account_state
    prm          = app_state.params
    pf           = app_state.portfolio
    total_equity = acc.total_equity if acc.total_equity > 0 else 1.0

    # RE-1: detect stale equity — sizing on outdated balance is dangerous
    equity_stale = True  # assume stale until proven fresh
    dc = getattr(app_state, "_data_cache", None)
    if dc is not None:
        applied = dc._account_version.applied_at
        if applied > 0 and (time.monotonic() - applied) < config.WS_FALLBACK_TIMEOUT:
            equity_stale = False
    elif not app_state.ws_status.is_stale:
        equity_stale = False  # no data_cache yet but WS is alive

    side   = "short" if sl_price > average else "long"
    sizing = calculate_position_size(ticker, average, sl_price, total_equity, side)

    # Regime multiplier
    regime        = app_state.current_regime
    regime_stale  = regime.is_stale if regime else True
    regime_label  = regime.label      if regime else "neutral"
    # Stale regime → fall back to 1.0 (safer than applying a stale label)
    if regime and not regime_stale:
        regime_mult = regime.multiplier
    else:
        regime_mult = 1.0
    if not apply_regime_multiplier:
        regime_mult = 1.0

    # _size (contracts) and est_size (USDT notional, post-slippage)
    size_raw  = sizing["size"]          # pre-regime
    size      = size_raw * regime_mult  # post-regime
    base_size = sizing["base_size"]

    # v2.4 Priority 2b: validate against exchange contract constraints
    contract_notes = ""
    try:
        from core.contract_validation import validate_and_snap_size
        vr = validate_and_snap_size(size, ticker, sizing["est_fill_price"])
        if vr.valid and vr.snapped_size is not None:
            snapped = float(vr.snapped_size)
            if snapped != size:
                contract_notes = f"Size snapped: {size:.8f} -> {snapped:.8f} (lot_step)"
                size = snapped
        elif not vr.valid:
            result["eligible"] = False
            result["ineligible_reason"] = f"Contract spec: {vr.reason}"
            if vr.suggested_size:
                contract_notes = f"Suggested size: {vr.suggested_size}"
            try:
                from core.event_log import log_event
                log_event(app_state.active_account_id, "calc_blocked_contract", {
                    "ticker": ticker,
                    "original_size": str(vr.original_size),
                    "reason": vr.reason,
                    "suggested_size": str(vr.suggested_size) if vr.suggested_size else None,
                }, source="risk_engine")
            except Exception:
                pass
    except Exception:
        pass  # validation unavailable — don't block calculator

    est_size  = size * average          # = base_size × regime_mult × (1 − est_slippage)

    # TP / SL USDT amounts (applied to the est_size portion being closed)
    tp_amount = est_size * (tp_amount_pct / 100.0)
    sl_amount = est_size * (sl_amount_pct / 100.0)

    if side == "long":
        tp_usdt = abs(tp_price - average) * (tp_amount / average) if (average > 0 and tp_price > 0) else 0.0
        sl_usdt = abs(average - sl_price) * (sl_amount / average) if average > 0 else 0.0
    else:
        tp_usdt = abs(average - tp_price) * (tp_amount / average) if (average > 0 and tp_price > 0) else 0.0
        sl_usdt = abs(sl_price - average) * (sl_amount / average) if average > 0 else 0.0

    # PRD step 6: est_slippage_usdt = est_slippage × est_size
    est_slip_usdt = sizing["est_slippage"] * est_size
    _maker, _taker = app_state.exchange_info.maker_fee, app_state.exchange_info.taker_fee
    fee_rate       = _taker if order_type in ("market", "stop") else _maker
    fee_cost      = 2 * fee_rate * est_size

    # PRD steps 9–11
    # est_profit: TP gain minus round-trip costs (fees + slippage reduce profit)
    # est_loss:   SL loss plus round-trip costs (fees + slippage increase loss)
    est_profit = tp_usdt - fee_cost - 2 * est_slip_usdt
    est_loss   = sl_usdt + fee_cost + 2 * est_slip_usdt
    est_r      = est_profit / est_loss if est_loss > 0 else 0.0

    # PRD step 12: est_exposure = (total_notional + est_size) / total_equity
    total_notional = sum(abs(p.position_value_usdt) for p in app_state.positions)
    est_exposure   = (total_notional + est_size) / total_equity if total_equity > 0 else 0.0

    exceeds_corr, new_sect_exp = check_correlated_limit(
        ticker, size, average, side, total_equity
    )

    at_max_positions = len(app_state.positions) >= prm["max_position_count"]
    at_max_exposure  = est_exposure > prm["max_exposure"]

    one_pct_depth = calculate_one_percent_depth(ticker, average)
    ob       = app_state.orderbook_cache.get(ticker, {})
    best_bid = ob.get("bids", [[0]])[0][0] if ob.get("bids") else 0
    best_ask = ob.get("asks", [[0]])[0][0] if ob.get("asks") else 0

    return {
        # Inputs / identifiers
        "ticker":              ticker,
        "average":             average,
        "side":                side,
        # Market info
        "one_percent_depth":   one_pct_depth,
        "best_bid":            best_bid,
        "best_ask":            best_ask,
        # Risk
        "individual_risk_pct": prm["individual_risk_per_trade"],
        "risk_usdt":           sizing["risk_usdt"],
        # ATR (raw values + coefficient + category)
        "atr14":               sizing["atr14"],
        "atr100":              sizing["atr100"],
        "atr_c":               sizing["atr_c"],
        "atr_category":        sizing["atr_category"],
        # Regime
        "regime_label":              regime_label,
        "regime_multiplier":         regime_mult,
        "apply_regime_multiplier":   apply_regime_multiplier,
        "regime_stale":              regime_stale,
        "size_raw":                  size_raw,       # contracts, without regime multiplier
        # Sizing chain
        "base_size":           base_size,           # USDT notional, pre-slippage
        "est_fill_price":      sizing["est_fill_price"],
        "est_slippage":        sizing["est_slippage"],
        "effective_entry":     sizing["effective_entry"],
        "size":                size,                # _size in contracts
        "notional":            est_size,            # est_size in USDT
        # TP / SL
        "tp_price":            tp_price,
        "tp_amount_pct":       tp_amount_pct,
        "tp_usdt":             tp_usdt,
        "sl_price":            sl_price,
        "sl_amount_pct":       sl_amount_pct,
        "sl_usdt":             sl_usdt,
        # Estimations
        "est_slippage_usdt":   est_slip_usdt,
        "est_profit":          est_profit,
        "est_loss":            est_loss,
        "est_r":               est_r,
        "est_exposure":        est_exposure,
        # Correlated
        "correlated_exposure": get_correlated_exposure(),
        "new_sector_exposure": new_sect_exp,
        "exceeds_corr_limit":  exceeds_corr,
        # Eligibility
        "at_max_positions":    at_max_positions,
        "at_max_exposure":     at_max_exposure,
        "eligible":            sizing["eligible"] and not at_max_positions
                               and not at_max_exposure and not exceeds_corr,
        "ineligible_reason":   sizing.get("ineligible_reason", ""),
        # Portfolio state
        "weekly_pnl_state":    pf.weekly_pnl_state,
        "dd_state":            pf.dd_state,
        # Equity freshness (RE-1)
        "equity_stale":        equity_stale,
        "total_equity":        total_equity,
        # Misc
        "calc_id":             calc_id,
        "model_name":          model_name,
        "model_desc":          model_desc,
        "order_type":          order_type,
        "fee_rate":            fee_rate,
        "maker_fee":           _maker,
        "taker_fee":           _taker,
    }
