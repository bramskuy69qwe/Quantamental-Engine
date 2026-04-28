"""
Macro Backtester — signal-scan mode.

Architecture:
  - Runs as a separate Python process (subprocess), never in the FastAPI event loop.
  - Fetches historical OHLCV from ohlcv_cache (pre-populated by ohlcv_fetcher.py).
  - Generates hypothetical entries from a rule-based strategy config.
  - Applies the same sizing logic as risk_engine.py (ATR coefficient, slippage model).
  - Optionally filters entries using macro signals from regime_signals table (when available).
  - Outputs equity curve, trade log, and regime-sliced stats to DB.

Strategy config schema (dict):
    {
      "name":        str,           # session label
      "symbols":     [str],         # e.g. ["BTCUSDT", "ETHUSDT"]
      "timeframe":   str,           # e.g. "4h"
      "date_from":   "YYYY-MM-DD",
      "date_to":     "YYYY-MM-DD",
      "initial_equity": float,      # starting capital in USDT

      # Entry signal rules (all must be True to generate a long/short entry)
      "signals": {
        "trend_ema_fast":  int,     # fast EMA period (e.g. 20)
        "trend_ema_slow":  int,     # slow EMA period (e.g. 50)
        "atr_sl_mult":     float,   # SL = entry ± atr_sl_mult × ATR14 (e.g. 1.5)
        "atr_tp_mult":     float,   # TP = entry ± atr_tp_mult × ATR14 (e.g. 3.0)
        "min_atr_c":       float,   # minimum atr_c (volatility filter, e.g. 0.2)
        "allow_long":      bool,
        "allow_short":     bool,
      },

      # Risk parameters (mirrors live engine params)
      "risk": {
        "individual_risk_per_trade": float,  # e.g. 0.01 (1%)
        "max_position_count":        int,    # e.g. 5
        "max_exposure":              float,  # e.g. 3.0 (300%)
        "maker_fee":                 float,  # e.g. 0.0002
        "taker_fee":                 float,  # e.g. 0.0005
      },

      # Optional macro filters (disabled if empty)
      "macro_filters": [
        # Each filter: {"signal": str, "op": "<"|">"|"<="|">=", "value": float}
        # e.g. {"signal": "vix_close", "op": "<", "value": 25}
      ],

      # Regime multipliers (applied when regime_signals table exists)
      "regime_multipliers": {
        "risk_on_trending":   1.2,
        "risk_on_choppy":     1.0,
        "neutral":            1.0,
        "risk_off_defensive": 0.7,
        "risk_off_panic":     0.4,
      },
    }
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from core.database import db
from core.analytics import daily_returns, sharpe, sortino, r_multiple_stats
from core.regime_classifier import classify_regime, ALL_SIGNALS

log = logging.getLogger("backtest_runner")


# ── Pure math helpers (no I/O, testable in isolation) ────────────────────────

def _ema(values: List[float], period: int) -> List[float]:
    """Exponential moving average. Returns list of same length; first period-1 values are nan."""
    n = len(values)
    if n < period:
        return [float("nan")] * n
    k = 2.0 / (period + 1)
    out = [float("nan")] * n
    seed_idx = period - 1
    out[seed_idx] = sum(values[:period]) / period
    for i in range(seed_idx + 1, n):
        out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out


def _wilder_atr(candles: List[List], period: int) -> List[float]:
    """
    Wilder's smoothed ATR over the full candle list.
    candles = [[ts, o, h, l, c, vol], ...].
    Returns list of same length; first `period` values are nan.
    """
    n = len(candles)
    if n < period + 1:
        return [float("nan")] * n

    trs: List[float] = [float("nan")]  # no TR for first bar
    for i in range(1, n):
        h  = float(candles[i][2])
        lo = float(candles[i][3])
        pc = float(candles[i - 1][4])
        trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))

    atr_vals = [float("nan")] * n
    seed = sum(trs[1: period + 1]) / period
    atr_vals[period] = seed
    alpha = 1.0 / period
    for i in range(period + 1, n):
        atr_vals[i] = atr_vals[i - 1] * (1 - alpha) + trs[i] * alpha
    return atr_vals


def _atr_coefficient(atr14: float, atr100: float) -> Tuple[float, str]:
    """Returns (atr_c capped at 1.0, category) matching live risk_engine.py logic."""
    if atr14 == 0:
        return 0.0, "unknown"
    raw  = atr100 / atr14
    atr_c = min(raw, 1.0)
    if atr_c < 0.2:
        cat = "too_volatile"
    elif atr_c < 0.6:
        cat = "volatile"
    elif raw >= 1.0:
        cat = "not_volatile"
    else:
        cat = "normal"
    return atr_c, cat


def _simulate_slippage(notional_usdt: float, avg_volume_usdt: float, fee_rate: float) -> float:
    """
    Slippage model for historical data (no live orderbook).
    Linear model: 0.01% per 0.1% of average daily volume consumed. Capped at 0.5%.
    """
    if avg_volume_usdt <= 0:
        return fee_rate
    return min(notional_usdt / avg_volume_usdt * 0.001, 0.005)


def _size_position(
    entry_price: float,
    sl_price: float,
    equity: float,
    atr_c: float,
    risk_pct: float,
    avg_volume_usdt: float,
    fee_rate: float,
    regime_mult: float = 1.0,
) -> Tuple[float, float, float]:
    """
    PRD-compliant sizing.
    Returns (est_size_usdt, slippage_frac, risk_usdt).
    """
    if entry_price <= 0 or sl_price <= 0 or equity <= 0:
        return 0.0, 0.0, 0.0
    sl_pct = abs(sl_price - entry_price) / entry_price
    if sl_pct == 0:
        return 0.0, 0.0, 0.0
    risk_usdt = risk_pct * equity * regime_mult
    base_size = (atr_c * risk_usdt) / sl_pct
    slippage  = _simulate_slippage(base_size, avg_volume_usdt, fee_rate)
    est_size  = base_size * (1.0 - slippage)
    return est_size, slippage, risk_usdt


def _build_equity_curve(
    trades: List[Dict[str, Any]], initial_equity: float
) -> List[Dict[str, Any]]:
    """Build equity curve with running drawdown. Returns [{dt, equity, drawdown}, ...]."""
    equity = initial_equity
    peak   = initial_equity
    curve: List[Dict[str, Any]] = [{"dt": "", "equity": equity, "drawdown": 0.0}]
    for t in sorted(trades, key=lambda x: x["exit_dt"]):
        equity += t["pnl_usdt"]
        peak    = max(peak, equity)
        dd      = (peak - equity) / peak if peak > 0 else 0.0
        curve.append({"dt": t["exit_dt"], "equity": round(equity, 4), "drawdown": round(dd, 6)})
    return curve


def _regime_slice(trades: List[Dict[str, Any]]) -> Dict[str, Dict]:
    """Group trades by regime_label and compute per-regime R-multiple stats."""
    groups: Dict[str, List[float]] = {}
    for t in trades:
        label = t.get("regime_label") or "unlabelled"
        groups.setdefault(label, []).append(t["r_multiple"])
    return {label: r_multiple_stats(rs) for label, rs in groups.items()}


def _max_drawdown(curve: List[Dict[str, Any]]) -> float:
    if not curve:
        return 0.0
    return max(p["drawdown"] for p in curve)


# ── BacktestRunner ─────────────────────────────────────────────────────────────

class BacktestRunner:
    """
    Signal-scan backtester. Instantiate once per run, then call run().
    All heavy indicator computation is done upfront (O(n)) before the event loop,
    not inside the loop (which would be O(n²)).
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        self.cfg         = config
        self.signals_cfg = config.get("signals", {})
        self.risk_cfg    = config.get("risk", {})
        self.macro_filters = config.get("macro_filters", [])
        self.regime_mults  = config.get("regime_multipliers", {})

    async def run(self, session_id: int, progress_cb=None) -> Dict[str, Any]:
        """
        Full backtest run. Writes results to DB and returns summary dict.
        progress_cb: optional async callable(pct: float, msg: str)
        """
        symbols    = self.cfg.get("symbols", [])
        timeframe  = self.cfg.get("timeframe", "4h")
        date_from  = self.cfg.get("date_from", "")
        date_to    = self.cfg.get("date_to", "")
        initial_eq = float(self.cfg.get("initial_equity", 10_000))

        since_ms = _date_to_ms(date_from) if date_from else 0
        until_ms = _date_to_ms(date_to, end_of_day=True) if date_to else int(time.time() * 1000)

        await _progress(progress_cb, 5, f"Loading OHLCV for {len(symbols)} symbols…")

        # ── Load candles ──────────────────────────────────────────────────────
        candle_map: Dict[str, List[List]] = {}
        for sym in symbols:
            candles = await db.get_ohlcv(sym, timeframe, since_ms=since_ms, until_ms=until_ms)
            if len(candles) < 110:
                log.warning("Insufficient OHLCV for %s (%d candles) — skipping", sym, len(candles))
                continue
            candle_map[sym] = candles

        if not candle_map:
            await db.finish_backtest_session(session_id, "failed", {"error": "No OHLCV data available"})
            return {"error": "No OHLCV data available"}

        # ── Load macro signals ────────────────────────────────────────────────
        macro_data: Dict[str, List[Dict]] = {}
        if self.macro_filters or self.regime_mults:
            await _progress(progress_cb, 10, "Loading macro signals…")
            macro_data = await self._load_macro_signals(since_ms, until_ms)

        # ── Precompute all indicators per symbol (O(n) each, done once) ───────
        # This avoids the O(n²) cost of recomputing EMA/ATR inside the event loop.
        await _progress(progress_cb, 12, "Precomputing indicators…")

        fast_p = int(self.signals_cfg.get("trend_ema_fast", 20))
        slow_p = int(self.signals_cfg.get("trend_ema_slow", 50))

        ind: Dict[str, Dict[str, List[float]]] = {}
        for sym, candles in candle_map.items():
            closes = [float(c[4]) for c in candles]
            ind[sym] = {
                "ema_fast": _ema(closes, fast_p),
                "ema_slow": _ema(closes, slow_p),
                "atr14":    _wilder_atr(candles, 14),
                "atr100":   _wilder_atr(candles, 100),
                # Rolling 20-bar avg volume (USDT) — precomputed once
                "avg_vol":  _rolling_avg_vol(candles, 20),
            }

        await _progress(progress_cb, 15, "Running signal scan…")

        all_trades: List[Dict[str, Any]] = []
        open_positions: Dict[str, Dict] = {}   # symbol → open trade
        equity = initial_eq

        # ── Unified timeline: (ts_ms, symbol, bar_idx) sorted by time ─────────
        events = []
        for sym, candles in candle_map.items():
            for i, c in enumerate(candles):
                events.append((int(c[0]), sym, i))
        events.sort(key=lambda x: x[0])

        total_events = len(events)

        for ev_idx, (ts_ms, sym, bar_idx) in enumerate(events):
            candles = candle_map[sym]
            sym_ind = ind[sym]

            # Need enough warm-up for all indicators
            if bar_idx < max(slow_p + 2, 101):
                continue

            if ev_idx % 500 == 0:
                pct = 15 + (ev_idx / max(total_events, 1)) * 70
                await _progress(progress_cb, pct, f"Bar {ev_idx}/{total_events} — {sym}")

            bar      = candles[bar_idx]
            bar_high = float(bar[2])
            bar_low  = float(bar[3])
            bar_ts   = datetime.utcfromtimestamp(ts_ms / 1000).isoformat()

            # ── Check TP / SL for open position ───────────────────────────────
            if sym in open_positions:
                pos   = open_positions[sym]
                sl    = pos["sl_price"]
                tp    = pos["tp_price"]
                side  = pos["side"]
                ep    = pos["entry_price"]
                szu   = pos["size_usdt"]
                rusd  = pos["risk_usdt"]
                frate = float(self.risk_cfg.get("taker_fee", 0.0005))

                hit_sl = (side == "long" and bar_low  <= sl) or (side == "short" and bar_high >= sl)
                hit_tp = (side == "long" and bar_high >= tp) or (side == "short" and bar_low  <= tp)

                if hit_sl or hit_tp:
                    # When both hit on same bar, prefer TP for longs on up-bars, SL otherwise
                    if hit_sl and hit_tp:
                        bar_close = float(bar[4])
                        bar_open  = float(bar[1])
                        exit_price  = tp if (side == "long" and bar_close >= bar_open) else sl
                        exit_reason = "tp" if exit_price == tp else "sl"
                    else:
                        exit_price  = tp if hit_tp else sl
                        exit_reason = "tp" if hit_tp else "sl"

                    if ep > 0:
                        gross_pnl = ((exit_price - ep) / ep * szu if side == "long"
                                     else (ep - exit_price) / ep * szu)
                    else:
                        gross_pnl = 0.0
                    fees    = 2 * frate * szu
                    net_pnl = gross_pnl - fees
                    r_mult  = net_pnl / abs(rusd) if rusd != 0 else 0.0

                    all_trades.append({
                        "symbol":       sym,
                        "side":         side,
                        "entry_dt":     pos["entry_dt"],
                        "exit_dt":      bar_ts,
                        "entry_price":  ep,
                        "exit_price":   exit_price,
                        "size_usdt":    szu,
                        "r_multiple":   round(r_mult, 4),
                        "pnl_usdt":     round(net_pnl, 4),
                        "regime_label": pos.get("regime_label", ""),
                        "exit_reason":  exit_reason,
                    })
                    equity += net_pnl
                    del open_positions[sym]

            # ── Check for new entry signal ─────────────────────────────────────
            if sym in open_positions:
                continue
            if len(open_positions) >= int(self.risk_cfg.get("max_position_count", 5)):
                continue

            signal = self._check_entry_signal_fast(sym_ind, bar_idx)
            if not signal:
                continue

            side = signal["side"]
            if side == "long"  and not self.signals_cfg.get("allow_long",  True):
                continue
            if side == "short" and not self.signals_cfg.get("allow_short", True):
                continue

            if self.macro_filters and not self._check_macro_filters(ts_ms, macro_data):
                continue

            # ATR values — already computed, just index
            atr14  = sym_ind["atr14"][bar_idx]
            atr100 = sym_ind["atr100"][bar_idx]
            if math.isnan(atr14) or math.isnan(atr100) or atr14 == 0:
                continue

            atr_c, atr_cat = _atr_coefficient(atr14, atr100)
            if atr_c < float(self.signals_cfg.get("min_atr_c", 0.0)):
                continue

            bar_close   = float(bar[4])
            atr_sl_mult = float(self.signals_cfg.get("atr_sl_mult", 1.5))
            atr_tp_mult = float(self.signals_cfg.get("atr_tp_mult", 3.0))

            if side == "long":
                sl_price = bar_close - atr_sl_mult * atr14
                tp_price = bar_close + atr_tp_mult * atr14
            else:
                sl_price = bar_close + atr_sl_mult * atr14
                tp_price = bar_close - atr_tp_mult * atr14

            avg_vol  = sym_ind["avg_vol"][bar_idx]
            if math.isnan(avg_vol) or avg_vol <= 0:
                continue
            fee_rate = float(self.risk_cfg.get("taker_fee", 0.0005))
            risk_pct = float(self.risk_cfg.get("individual_risk_per_trade", 0.01))

            regime_label = ""
            regime_mult  = 1.0
            if self.regime_mults:
                regime_label = self._get_regime_label(ts_ms, macro_data)
                regime_mult  = self.regime_mults.get(regime_label, 1.0)

            size_usdt, _slip, risk_usdt = _size_position(
                bar_close, sl_price, equity, atr_c,
                risk_pct, avg_vol, fee_rate, regime_mult,
            )
            if size_usdt <= 0:
                continue

            # Guard: skip if equity is depleted
            if equity <= 0:
                continue

            current_exp = sum(p["size_usdt"] for p in open_positions.values())
            max_exp     = float(self.risk_cfg.get("max_exposure", 3.0))
            if (current_exp + size_usdt) / equity > max_exp:
                continue

            open_positions[sym] = {
                "side":         side,
                "entry_price":  bar_close,
                "sl_price":     sl_price,
                "tp_price":     tp_price,
                "size_usdt":    size_usdt,
                "risk_usdt":    risk_usdt,
                "entry_dt":     bar_ts,
                "regime_label": regime_label,
            }

        # ── Force-close remaining open positions at last price ─────────────────
        for sym, pos in open_positions.items():
            candles     = candle_map[sym]
            last_bar    = candles[-1]
            exit_price  = float(last_bar[4])
            exit_dt     = datetime.utcfromtimestamp(last_bar[0] / 1000).isoformat()
            side        = pos["side"]
            szu         = pos["size_usdt"]
            rusd        = pos["risk_usdt"]
            ep          = pos["entry_price"]
            fee_rate    = float(self.risk_cfg.get("taker_fee", 0.0005))

            if ep > 0:
                gross_pnl = ((exit_price - ep) / ep * szu if side == "long"
                             else (ep - exit_price) / ep * szu)
            else:
                gross_pnl = 0.0
            fees    = 2 * fee_rate * szu
            net_pnl = gross_pnl - fees
            r_mult  = net_pnl / abs(rusd) if rusd != 0 else 0.0

            all_trades.append({
                "symbol":       sym,
                "side":         side,
                "entry_dt":     pos["entry_dt"],
                "exit_dt":      exit_dt,
                "entry_price":  ep,
                "exit_price":   exit_price,
                "size_usdt":    szu,
                "r_multiple":   round(r_mult, 4),
                "pnl_usdt":     round(net_pnl, 4),
                "regime_label": pos.get("regime_label", ""),
                "exit_reason":  "end_of_data",
            })

        await _progress(progress_cb, 87, "Building equity curve…")

        equity_curve  = _build_equity_curve(all_trades, initial_eq)
        r_multiples   = [t["r_multiple"] for t in all_trades]
        r_stats       = r_multiple_stats(r_multiples)
        equity_series = [p["equity"] for p in equity_curve]
        rets          = daily_returns(equity_series)
        final_equity  = equity_series[-1] if equity_series else initial_eq
        total_ret_pct = (final_equity - initial_eq) / initial_eq if initial_eq else 0.0

        summary = {
            "total_trades":     len(all_trades),
            "initial_equity":   initial_eq,
            "final_equity":     round(final_equity, 2),
            "total_return_pct": round(total_ret_pct, 6),
            "max_drawdown":     round(_max_drawdown(equity_curve), 6),
            "sharpe":           round(sharpe(rets), 4),
            "sortino":          round(sortino(rets), 4),
            "r_stats":          r_stats,
            "regime_breakdown": _regime_slice(all_trades),
            "symbols_traded":   list(candle_map.keys()),
        }

        await _progress(progress_cb, 92, "Writing results to DB…")
        await db.insert_backtest_trades(session_id, all_trades)
        await db.insert_backtest_equity(session_id, equity_curve[1:])  # skip seed row
        await db.finish_backtest_session(session_id, "completed", summary)

        await _progress(progress_cb, 100, "Done.")
        log.info(
            "Backtest session %d complete: %d trades, %.2f%% return, %.4f Sharpe",
            session_id, len(all_trades), total_ret_pct * 100, summary["sharpe"],
        )
        return summary

    # ── Entry signal (uses precomputed indicator arrays) ──────────────────────

    def _check_entry_signal_fast(
        self, sym_ind: Dict[str, List[float]], bar_idx: int
    ) -> Optional[Dict[str, str]]:
        """
        EMA crossover. Long: fast crosses above slow. Short: fast crosses below slow.
        Uses precomputed arrays — O(1) per bar.
        """
        ema_fast = sym_ind["ema_fast"]
        ema_slow = sym_ind["ema_slow"]

        if bar_idx < 1 or bar_idx >= len(ema_fast):
            return None

        f_now  = ema_fast[bar_idx]
        f_prev = ema_fast[bar_idx - 1]
        s_now  = ema_slow[bar_idx]
        s_prev = ema_slow[bar_idx - 1]

        if any(math.isnan(v) for v in (f_now, f_prev, s_now, s_prev)):
            return None

        if f_prev <= s_prev and f_now > s_now:
            return {"side": "long"}
        if f_prev >= s_prev and f_now < s_now:
            return {"side": "short"}
        return None

    # ── Macro filter ──────────────────────────────────────────────────────────

    def _check_macro_filters(self, ts_ms: int, macro_data: Dict[str, List[Dict]]) -> bool:
        ops = {"<": float.__lt__, ">": float.__gt__, "<=": float.__le__, ">=": float.__ge__}
        bar_date = datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")

        for f in self.macro_filters:
            signal_name = f.get("signal", "")
            op_fn       = ops.get(f.get("op", "<"))
            threshold   = float(f.get("value", 0))
            val         = _lookup_signal(macro_data.get(signal_name, []), bar_date)
            if val is None:
                continue  # missing data → pass through
            if op_fn and not op_fn(val, threshold):
                return False
        return True

    def _get_regime_label(self, ts_ms: int, macro_data: Dict[str, List[Dict]]) -> str:
        """Classify regime for a given bar timestamp using stored macro signals."""
        bar_date = datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
        signals: Dict[str, float] = {}
        for sig_name, series in macro_data.items():
            val = _lookup_signal(series, bar_date)
            if val is not None:
                signals[sig_name] = val

        # BTC dominance rate-of-change: look back 7 days
        if "btc_dominance" in macro_data:
            prev_date = (datetime.utcfromtimestamp(ts_ms / 1000) - timedelta(days=7)).strftime("%Y-%m-%d")
            prev_val = _lookup_signal(macro_data["btc_dominance"], prev_date)
            if prev_val is not None:
                signals["btc_dominance_prev"] = prev_val

        has_crypto = "agg_oi_change" in signals or "avg_funding" in signals
        mode = "full" if has_crypto else "macro_only"
        return classify_regime(signals, mode=mode)

    # ── Macro data loader ─────────────────────────────────────────────────────

    async def _load_macro_signals(
        self, since_ms: int, until_ms: int
    ) -> Dict[str, List[Dict]]:
        """Load all regime signals from DB for the given time range."""
        try:
            from_date = datetime.utcfromtimestamp(since_ms / 1000).strftime("%Y-%m-%d")
            to_date   = datetime.utcfromtimestamp(until_ms / 1000).strftime("%Y-%m-%d")
            return await db.get_regime_signals(ALL_SIGNALS, from_date, to_date)
        except Exception:
            return {}


# ── Module-level helpers ──────────────────────────────────────────────────────

def _rolling_avg_vol(candles: List[List], window: int) -> List[float]:
    """
    Precomputed rolling average USDT volume (close × volume) over `window` bars.
    Returns list of same length as candles; first window bars use partial average.
    """
    n   = len(candles)
    out = [0.0] * n
    for i in range(n):
        lo = max(0, i - window)
        bars = candles[lo:i]
        if bars:
            out[i] = sum(float(c[4]) * float(c[5]) for c in bars) / len(bars)
    return out


def _date_to_ms(date_str: str, end_of_day: bool = False) -> int:
    """Convert 'YYYY-MM-DD' to epoch milliseconds (UTC)."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if end_of_day:
            dt = dt + timedelta(hours=23, minutes=59, seconds=59)
        return int(dt.timestamp() * 1000)
    except (ValueError, OverflowError, OSError):
        return 0


def _lookup_signal(series: List[Dict], date_str: str) -> Optional[float]:
    """Binary-search the closest signal value at or before the given date."""
    if not series:
        return None
    lo, hi, result = 0, len(series) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if series[mid]["date"] <= date_str:
            result = series[mid]["value"]
            lo = mid + 1
        else:
            hi = mid - 1
    return result


async def _progress(cb, pct: float, msg: str) -> None:
    if cb:
        try:
            await cb(pct, msg)
        except Exception:
            pass
