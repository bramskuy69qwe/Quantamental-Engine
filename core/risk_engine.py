"""
Risk calculation engine.

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
import logging
import math
import sqlite3
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import config
from core.state import app_state

log = logging.getLogger(__name__)


# Task 159 (MED-002): cap est_r so tiny est_loss doesn't display as
# "amazing setup" R:R. 50× = "professional trader sanity bound" — above
# this the inputs are degenerate (sub-fee SL distance, or other
# epsilon-vulnerability per MED-002's family with MED-031 / MED-007).
# Display value caps at MAX_REASONABLE_RR; log fires when clamp hits so
# operator can investigate inputs.
MAX_REASONABLE_RR = 50.0


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
            log.warning(
                "estimate_vwap_fill: skipping invalid orderbook level "
                "(price=%s, qty=%s) — non-positive price",
                price, qty,
            )
            continue
        if qty <= 0:
            log.warning(
                "estimate_vwap_fill: skipping invalid orderbook level "
                "(price=%s, qty=%s) — non-positive qty",
                price, qty,
            )
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
    if best_price <= 0:
        return 0.0, entry_price
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
        "effective_entry": 0.0,   # slippage-adjusted entry price (defect-4 fix; was 1−slippage)
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
    # Task 162: narrow the "adapter unavailable" swallow. ReadyStateEvaluator
    # above gates engine_ready; reaching here means the engine should
    # have an adapter. Catch the "infrastructure not loaded" shapes:
    # ImportError (module-load failure), AttributeError (adapter chain
    # absent), KeyError (missing config), RuntimeError (the explicit
    # `_get_adapter` raises `RuntimeError("No active account
    # credentials available")` for the no-active-account case —
    # legitimate in test envs + during account-switch transitions).
    # Programming errors (NameError, TypeError) propagate so a future
    # regression here surfaces immediately. The pre-T162 broad
    # `except Exception: pass` was the same anti-pattern as the T161
    # NameError swallow.
    except (ImportError, AttributeError, KeyError, RuntimeError) as exc:
        log.debug(
            "risk_engine T162: capability gate skipped — adapter "
            "infrastructure unavailable: %r", exc,
        )

    # Phase 8 audit (HIGH): finite guard MUST precede the <= 0 checks. NaN/Inf
    # parse via float() but fail BOTH `<= 0` comparisons (nan<=0 and inf<=0 are
    # decided the wrong way), so a non-finite average/sl_price would slip this
    # gate and poison every downstream field (sl_pct→size→notional all NaN)
    # while the eligibility gates (`> max_exposure`, etc.) silently return False
    # on NaN — persisting an eligible calc with NaN size into pre_trade_log,
    # which the matcher + deviation analytics then read. math.isfinite closes it.
    if not (math.isfinite(average) and math.isfinite(sl_price)) or average <= 0 or sl_price <= 0:
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
    # Debug 2026-06-08 (defect 4): effective_entry is the slippage-adjusted ENTRY
    # PRICE — what calc_correlation (the calc<->order matcher) and exec_link read
    # it as. It previously stored the `1 - est_slippage` FACTOR (~1.0 for any
    # real-priced asset), so the matcher's entry criterion compared the real fill
    # price (e.g. 0.236) against ~1.0 and could NEVER match -> zero auto-links on
    # the live path. The factor was never consumed AS a factor (est_size below
    # uses est_slippage directly), so this is a pure value fix.
    result["effective_entry"] = est_fill_price
    result["est_fill_price"]  = est_fill_price

    # Task 159 (MED-016): catastrophic-book gate. If slippage estimate reaches
    # or exceeds 100%, the VWAP fill is so far from entry that the size
    # formula `base_size * (1 - est_slippage)` would go ≤ 0. A negative
    # size at the exchange API can be interpreted as an opposite-side order
    # — direction inversion is the HIGH-shape failure mode the audit
    # under-rated. Reject the sizing path (eligible=False) and surface the
    # mechanism instead of silently zeroing. Defensive clamp on the size
    # field still applies below in case downstream callers ignore eligible.
    if est_slippage >= 1.0:
        result["eligible"] = False
        result["ineligible_reason"] = (
            f"Orderbook too thin: est_slippage={est_slippage:.2%} ≥ 100% — "
            "refusing to size against catastrophic book conditions."
        )
        log.warning(
            "risk_engine MED-016 reject: symbol=%s est_slippage=%.4f base_size=%.2f",
            symbol, est_slippage, base_size,
        )

    # Step 6–8: est_size = base_size × (1 − est_slippage); _size = est_size / average
    if result["eligible"]:
        est_size = base_size * (1.0 - est_slippage)
        # Belt-and-suspenders clamp: even if a future path lets est_slippage
        # > 1 through with eligible=True, we never propagate a negative size.
        est_size = max(0.0, est_size)
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
    # #5b (debug 2026-06-08): exclude the operator's EXISTING same-(symbol,side)
    # position from the sector net. Re-calcing a symbol you already hold would
    # otherwise DOUBLE-COUNT it — the open position is summed into existing_net
    # AND the new calc's notional is added on top — blocking a legitimate
    # re-calc / linkage of a position you're already in. The calc represents the
    # intended position, not an addition to it. (A genuine scale-in is then
    # slightly under-counted on the correlated gate; the per-trade size + the
    # portfolio max_exposure gate still bound it. Operator-confirmed.)
    norm_dir = "LONG" if side == "long" else "SHORT"
    for p in app_state.positions:
        # getattr-guarded: a position without a ticker can't be the symbol being
        # calc'd, so it's simply not excluded (graceful fall-back to the
        # pre-#5b count). Real PositionInfo always carries ticker.
        if getattr(p, "ticker", None) == symbol and getattr(p, "direction", None) == norm_dir:
            sign = 1.0 if p.direction == "LONG" else -1.0
            existing_net -= sign * p.position_value_usdt
    new_notional = size * average * (1.0 if side == "long" else -1.0)
    new_net_abs  = abs(existing_net + new_notional)
    return (new_net_abs > max_corr), new_net_abs


# ── Full risk calculator output ───────────────────────────────────────────────

def _resolve_size_override(computed_size: float, size_override):
    """P8.T4b (spec §10.1): resolve the operator size override.

    Returns ``(effective_size, planned_size, overridden_size, was_overridden)``:
    - ``planned_size`` is ALWAYS the engine-recommended (computed) size;
    - ``overridden_size`` == ``planned_size`` when there is no override (spec
      line 264: "operator's final size (== planned if not overridden)");
    - a None / non-numeric / non-positive override is treated as "no override".

    The caller substitutes ``effective_size`` for ``size`` BEFORE the
    downstream notional / profit / loss / exposure / eligibility computation,
    so the whole calc reflects the operator's size (not just a scaled display).
    """
    planned = float(computed_size)
    if size_override is not None:
        try:
            ov = float(size_override)
        except (TypeError, ValueError):
            ov = 0.0
        if ov > 0:
            return ov, planned, ov, True
    return planned, planned, planned, False


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
    # P8.T4b (spec §10.1): operator size override (contracts). None → use the
    # engine-recommended size. When set (>0), it replaces the computed size
    # for ALL downstream metrics + eligibility, and planned_size / overridden_
    # size are both recorded onto the calc (pre_trade_log) for deviation track.
    size_override:          "float | None" = None,
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

    # Task 165 (MED-017): surface mark-price staleness at calc time.
    # The base size scales with total_equity, which in turn depends on
    # per-position mark prices (data_cache.apply_mark_price recomputes
    # acc.total_unrealized → equity). If the WS feed for `ticker` has
    # gone quiet beyond MARK_PRICE_STALE_SECONDS, the equity number
    # the calc is sizing off may be silently outdated. Not a hard
    # block — the operator may still want to size a manually-priced
    # entry — but the flag fires on the calc result so the surface
    # exists. A missing timestamp (symbol never received a mark) is
    # treated as stale: we have nothing to claim freshness from.
    mark_ts = app_state.mark_price_timestamps.get(ticker)
    if mark_ts is None:
        mark_price_stale = True
        mark_price_age = None
    else:
        mark_price_age = time.monotonic() - mark_ts
        mark_price_stale = mark_price_age > config.MARK_PRICE_STALE_SECONDS
    if mark_price_stale:
        log.warning(
            "risk_engine MED-017: mark-price stale for %s (age=%s s, "
            "threshold=%s s) — base_size derived from possibly outdated "
            "equity; calc proceeds with stale flag set",
            ticker,
            f"{mark_price_age:.1f}" if mark_price_age is not None else "never-received",
            config.MARK_PRICE_STALE_SECONDS,
        )

    side   = "short" if sl_price > average else "long"
    sizing = calculate_position_size(ticker, average, sl_price, total_equity, side)

    # Regime multiplier
    regime        = app_state.current_regime
    regime_stale  = regime.is_stale if regime else True
    regime_label  = regime.label      if regime else "neutral"
    # Task 157: thread mode through to the calc dict so insert_pre_trade_log
    # can persist it (full / macro_only marks which signal-set the live
    # classifier saw at decision time; matters for forward-validation
    # comparisons of macro-only vs full-mode reasoning).
    regime_mode   = regime.mode       if regime else "macro_only"
    # Stale regime → fall back to 1.0 (safer than applying a stale label)
    if regime and not regime_stale:
        regime_mult = regime.multiplier
    else:
        regime_mult = 1.0
    if not apply_regime_multiplier:
        regime_mult = 1.0

    # _size (contracts) and est_size (USDT notional, post-slippage)
    calc_id   = sizing["calc_id"]       # uuid4 from calculate_position_size
    size_raw  = sizing["size"]          # pre-regime
    size      = size_raw * regime_mult  # post-regime
    base_size = sizing["base_size"]

    # v2.4 Priority 2b: validate against exchange contract constraints
    # Task 161: the prior implementation referenced `result["eligible"]`
    # and `result["ineligible_reason"]` inside this block — but
    # `result` is a local var name from `calculate_position_size`, NOT
    # defined in run_risk_calculator's scope. The reference raised
    # NameError on every contract-validation-failure path, which the
    # broad `except Exception: pass` outside silently swallowed. Net
    # effect: contract validation rejection was DEAD CODE — invalid
    # sizes proceeded as eligible with their un-snapped value. T161
    # routes the eligibility flag through local `contract_invalid` /
    # `contract_reason` vars that feed into the existing final_eligible
    # / final_reason computation below.
    contract_notes   = ""
    contract_invalid = False
    contract_reason  = ""
    try:
        from core.contract_validation import validate_and_snap_size
        vr = validate_and_snap_size(size, ticker, sizing["est_fill_price"])
        if vr.valid and vr.snapped_size is not None:
            snapped = float(vr.snapped_size)
            if snapped != size:
                contract_notes = f"Size snapped: {size:.8f} -> {snapped:.8f} (lot_step)"
                size = snapped
        elif not vr.valid:
            # Task 161: distinguish "validation infra unavailable"
            # (don't block — same intent as the pre-T161 comment "don't
            # block calculator") from "contract spec says invalid"
            # (block). validate_and_snap_size returns
            # `exchange_info_unavailable` when get_contract_spec(symbol)
            # is None — no grounds to block a trade just because the
            # spec hasn't loaded for this ticker yet. Other reasons
            # (below_min_qty / below_min_notional / invalid_numeric_input)
            # are real rejects — block.
            if vr.reason == "exchange_info_unavailable":
                log.warning(
                    "risk_engine T161: contract validation skipped for %s — "
                    "no contract spec loaded; calc proceeds without contract "
                    "constraints",
                    ticker,
                )
            else:
                contract_invalid = True
                contract_reason  = f"Contract spec: {vr.reason}"
                if vr.suggested_size:
                    contract_notes = f"Suggested size: {vr.suggested_size}"
                # Task 162: narrow the event-log swallow (T161 latent #1).
                # log_event can legitimately fail on DB / FS / import-time
                # issues — those are operational concerns the operator
                # should see. Programming errors in log_event (e.g.
                # signature mismatch on a future refactor) must NOT be
                # silently swallowed. ImportError covers module-not-loaded;
                # sqlite3.Error / OSError cover DB+FS infra failures.
                # Narrower than T161's `except (ImportError, AttributeError)`
                # because the event_log write path uses sqlite3 + file I/O.
                try:
                    from core.event_log import log_event
                    log_event(app_state.active_account_id, "calc_blocked_contract", {
                        "ticker": ticker,
                        "original_size": str(vr.original_size),
                        "reason": vr.reason,
                        "suggested_size": str(vr.suggested_size) if vr.suggested_size else None,
                    }, source="risk_engine")
                except (ImportError, sqlite3.Error, OSError) as exc:
                    log.warning(
                        "risk_engine T162: calc_blocked_contract event "
                        "not recorded (event_log infrastructure failed): %r",
                        exc,
                    )
    # Task 161: narrow the swallow to the "validation infrastructure
    # unavailable" case ONLY. The prior `except Exception: pass` hid
    # the NameError that made the rejection branch dead. Programming
    # errors (NameError, TypeError, KeyError, etc.) must propagate —
    # let them surface as test/runtime failures rather than silently
    # disabling a safety check. ImportError covers module-not-loaded;
    # AttributeError covers contract_validation API drift (vr missing
    # an attr). Validation-infrastructure unavailability is logged at
    # warning level so the operator at least sees that contract
    # checking is silently no-op for this calc cycle.
    except (ImportError, AttributeError) as exc:
        log.warning(
            "risk_engine T161: contract validation skipped for %s — "
            "validation infrastructure unavailable: %r",
            ticker, exc,
        )

    # P8.T4b (spec §10.1): apply the operator size override BEFORE any
    # size-dependent computation so notional / profit / loss / est_exposure /
    # eligibility all reflect the operator's size (not a post-hoc scale —
    # est_exposure is portfolio-level and would NOT scale linearly). planned_
    # size is the engine recommendation (post regime + contract snap), captured
    # here before the substitution; both are returned for deviation tracking.
    size, planned_size, overridden_size, size_overridden = _resolve_size_override(
        size, size_override,
    )

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
    # Task 159 (MED-002): zero-denominator guard preserved; additional clamp
    # at MAX_REASONABLE_RR catches the epsilon-vulnerability case (est_loss
    # > 0 but ≪ est_profit → R:R unbounded). Trader scanning for "great
    # setups" should not see 500× displayed as if it were a real number.
    if est_loss > 0:
        raw_r = est_profit / est_loss
        est_r = min(raw_r, MAX_REASONABLE_RR) if raw_r > 0 else raw_r
        if raw_r > MAX_REASONABLE_RR:
            log.warning(
                "risk_engine MED-002 R:R clamp: symbol=%s raw_r=%.2f "
                "(profit=%.4f loss=%.6f) → clamped to %.1f",
                ticker, raw_r, est_profit, est_loss, MAX_REASONABLE_RR,
            )
    else:
        est_r = 0.0

    # PRD step 12: est_exposure = (total_notional + est_size) / total_equity
    total_notional = sum(abs(p.position_value_usdt) for p in app_state.positions)
    est_exposure   = (total_notional + est_size) / total_equity if total_equity > 0 else 0.0

    exceeds_corr, new_sect_exp = check_correlated_limit(
        ticker, size, average, side, total_equity
    )

    at_max_positions = len(app_state.positions) >= prm["max_position_count"]
    at_max_exposure  = est_exposure > prm["max_exposure"]

    # Task 159 (MED-019): populate ineligible_reason for the three
    # portfolio-level gates so a single uniform error surface exists. The
    # template (calc_result.html) renders specific banners per-gate, but
    # downstream consumers (event_log, regime analytics, anything reading
    # the calc dict) needed a populated reason field. Order priority:
    # at_max_positions > at_max_exposure > exceeds_corr — matches the
    # template's elif chain. sizing["ineligible_reason"] (sizing-path
    # rejects from calculate_position_size — Engine not ready, capability
    # gate, invalid SL, too volatile, MED-016 slippage) takes precedence
    # because it's earlier in the pipeline.
    portfolio_reason = ""
    if at_max_positions:
        portfolio_reason = (
            f"Max position count reached ({prm['max_position_count']}). "
            "Close a position first."
        )
    elif at_max_exposure:
        portfolio_reason = (
            f"Estimated exposure {est_exposure:.2f}× exceeds max "
            f"{prm['max_exposure']:.2f}×."
        )
    elif exceeds_corr:
        portfolio_reason = "Sector correlated exposure limit exceeded."
    # Task 161: contract-validation reject feeds the same chain. Reason
    # precedence: sizing-path reject (earliest) > contract-validation
    # reject (priced at sizing time, before portfolio assembly) >
    # portfolio reject. First-non-empty wins so the operator sees the
    # most specific cause.
    final_reason = (
        sizing.get("ineligible_reason", "")
        or contract_reason
        or portfolio_reason
    )

    # Task 160: dict-level size enforcement. T159 zeroed size only at the
    # template data-* attrs; downstream consumers (regime leaderboard,
    # API, logs, T157 pre_trade_log regime row) still saw the breaching
    # size in the calc dict. Move enforcement to the source so no caller
    # needs to re-check `eligible`. Compute final_eligible first, snapshot
    # the computed values into `would_be_*` for forensic display, then
    # zero the actionable fields when not eligible.
    # Task 161: contract_invalid joins the final_eligible AND — the
    # contract-spec safety check that was silently dead now actually
    # blocks the trade.
    final_eligible = (
        sizing["eligible"]
        and not at_max_positions
        and not at_max_exposure
        and not exceeds_corr
        and not contract_invalid
    )
    would_be_size     = size          # contracts as computed (after regime + contract validation)
    would_be_notional = est_size      # USDT notional as computed
    if not final_eligible:
        size = 0.0
        est_size = 0.0

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
        # Task 157: persisted by insert_pre_trade_log so the forward
        # two-track's "actual" arm can replay decisions at full fidelity.
        "regime_mode":               regime_mode,
        # Task 165 (MED-017): mark-price freshness at calc time.
        # `mark_price_stale` is True if the WS-driven mark for `ticker`
        # is older than MARK_PRICE_STALE_SECONDS (or has never been
        # received). `mark_price_age` is the actual age in seconds, or
        # None if no mark was ever received. Not a hard-block — just
        # a flag the operator + downstream analytics can act on.
        "mark_price_stale":          mark_price_stale,
        "mark_price_age":            mark_price_age,
        "size_raw":                  size_raw,       # contracts, without regime multiplier
        # Sizing chain
        "base_size":           base_size,           # USDT notional, pre-slippage
        "est_fill_price":      sizing["est_fill_price"],
        "est_slippage":        sizing["est_slippage"],
        "effective_entry":     sizing["effective_entry"],
        "size":                size,                # _size in contracts (0 if ineligible per T160)
        "notional":            est_size,            # est_size in USDT (0 if ineligible per T160)
        # P8.T4b (spec §10.1 + §3.2): plan-vs-override capture. planned_size =
        # engine recommendation (always, even if size was overridden/zeroed);
        # overridden_size = operator's final size (== planned when not
        # overridden); size_overridden flags the UI. Persisted by
        # insert_pre_trade_log; the P2.T4 junction prefers overridden_size as
        # the deviation baseline. planned_tp/sl = the entered TP/SL (the plan;
        # the calculator overrides SIZE only per §10.1).
        "planned_size":        planned_size,
        "overridden_size":     overridden_size,
        "size_overridden":     size_overridden,
        "planned_tp":          tp_price,
        "planned_sl":          sl_price,
        # Task 160: forensic counterparts — what the size/notional WOULD
        # have been if the eligibility gate hadn't fired. Surfaces "you'd
        # have placed 0.05 BTC but you're at max positions" via downstream
        # analytics / regime leaderboard without re-running the calc.
        # Sizing-stage rejects (engine-not-ready, capability, invalid SL,
        # too_volatile, MED-016 slippage>=1) set these to 0 too because
        # calculate_position_size returns size=0 — no computation was
        # possible, so "would have been" is genuinely 0.
        "would_be_size":       would_be_size,
        "would_be_notional":   would_be_notional,
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
        # Task 160: use precomputed final_eligible (same logic as
        # before, just hoisted so size/notional zeroing can branch on it).
        "eligible":            final_eligible,
        # Task 159 (MED-019): non-empty reason for every ineligible path —
        # was sizing.get("ineligible_reason", "") which left at_max_*/
        # exceeds_corr cases with empty reason despite eligible=False.
        "ineligible_reason":   final_reason,
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
