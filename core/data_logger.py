"""
CSV logging, periodic snapshots, and manual exports.

Files:
  data/pre_trade_log.csv       – every risk-calculator calculation
  data/execution_log.csv       – filled trades (manually logged via UI)
  data/live_trades_log.csv     – live positions tracking
  data/trade_history.csv       – closed trades
  data/snapshots/YYYY-MM-DD_bod.csv – daily snapshot
  data/snapshots/YYYY-MM_monthly.csv – monthly snapshot
"""
from __future__ import annotations
import csv
import os
import json
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional

import pandas as pd

import config
from core.state import app_state, TZ_LOCAL


# ── Ensure data dirs exist ────────────────────────────────────────────────────

def _ensure_dirs():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.SNAPSHOTS_DIR, exist_ok=True)


# ── Generic CSV append ────────────────────────────────────────────────────────

def _append_csv(path: str, row: Dict[str, Any], fieldnames: List[str]) -> None:
    _ensure_dirs()
    exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow(row)


# ── Pre-trade log ─────────────────────────────────────────────────────────────

PRE_TRADE_FIELDS = [
    "timestamp", "ticker", "average", "side",
    "one_percent_depth", "individual_risk",
    "tp_price", "tp_amount_pct", "tp_usdt",
    "sl_price", "sl_amount_pct", "sl_usdt",
    "model_name", "model_desc",
    "risk_usdt", "atr_c", "atr_category",
    "est_slippage", "effective_entry", "size", "notional",
    "est_profit", "est_loss", "est_r",
    "est_exposure", "eligible",
]


def log_pre_trade(calc_result: Dict) -> None:
    # Replaced by redis_bus.publish("risk:risk_calculated", calc) in api/routes.py.
    # DB write + in-memory cache update are handled by handle_risk_calculated in core/handlers.py.
    # Stub kept so legacy import references don't raise AttributeError.
    pass


# ── Execution log ─────────────────────────────────────────────────────────────

EXEC_FIELDS = [
    "entry_timestamp", "ticker", "side",
    "entry_price_actual", "size_filled", "slippage",
    "order_type", "maker_fee", "taker_fee",
    "latency_snapshot", "orderbook_depth_snapshot",
]


def log_execution(row: Dict) -> None:
    row.setdefault("entry_timestamp", datetime.now(TZ_LOCAL).isoformat())
    _append_csv(config.EXECUTION_LOG, row, EXEC_FIELDS)


# ── Live trades log ───────────────────────────────────────────────────────────

LIVE_FIELDS = [
    "ticker", "entry_timestamp", "direction",
    "max_profit", "max_loss", "hold_time",
    "stop_adjustments",
]


def update_live_trade(row: Dict) -> None:
    _append_csv(config.LIVE_TRADES, row, LIVE_FIELDS)


# ── Trade history ─────────────────────────────────────────────────────────────

HISTORY_FIELDS = [
    "exit_timestamp", "ticker", "direction",
    "entry_price", "exit_price",
    "individual_realized", "individual_realized_r",
    "total_funding_fees", "total_fees",
    "slippage_exit", "holding_time", "notes",
]


def log_trade_close(row: Dict) -> None:
    row.setdefault("exit_timestamp", datetime.now(TZ_LOCAL).isoformat())
    _append_csv(config.TRADE_HISTORY, row, HISTORY_FIELDS)


# ── Dashboard snapshot ────────────────────────────────────────────────────────

def _state_to_snapshot_dict() -> Dict:
    acc = app_state.account_state
    pf  = app_state.portfolio
    ex  = app_state.exchange_info
    prm = app_state.params
    ws  = app_state.ws_status
    now = datetime.now(TZ_LOCAL).isoformat()

    snap = {
        "snapshot_time": now,
        # exchange_info
        "exchange_name": ex.name,
        "latency_ms":    ex.latency_ms,
        "server_time":   ex.server_time,
        "maker_fee":     ex.maker_fee,
        "taker_fee":     ex.taker_fee,
        # account_state
        "total_equity":        acc.total_equity,
        "balance_usdt":        acc.balance_usdt,
        "available_margin":    acc.available_margin,
        "total_unrealized":    acc.total_unrealized,
        "total_realized":      acc.total_realized,
        "total_position_value": acc.total_position_value,
        "total_margin_used":   acc.total_margin_used,
        "total_margin_ratio":  acc.total_margin_ratio,
        "total_tp_usdt":       acc.total_tp_usdt,
        "total_sl_usdt":       acc.total_sl_usdt,
        "daily_pnl":           acc.daily_pnl,
        "daily_pnl_percent":   acc.daily_pnl_percent,
        "bod_equity":          acc.bod_equity,
        "sow_equity":          acc.sow_equity,
        "max_total_equity":    acc.max_total_equity,
        "min_total_equity":    acc.min_total_equity,
        # portfolio stats
        "total_exposure":           pf.total_exposure,
        "total_weekly_pnl":         pf.total_weekly_pnl,
        "total_weekly_pnl_percent": pf.total_weekly_pnl_percent,
        "drawdown":                 pf.drawdown,
        "weekly_pnl_state":         pf.weekly_pnl_state,
        "dd_state":                 pf.dd_state,
        # params
        **{f"param_{k}": v for k, v in prm.items()},
        # position count
        "open_positions": len(app_state.positions),
    }

    # Flatten positions
    for i, p in enumerate(app_state.positions, start=1):
        snap[f"pos{i}_ticker"]     = p.ticker
        snap[f"pos{i}_direction"]  = p.direction
        snap[f"pos{i}_average"]    = p.average
        snap[f"pos{i}_size"]       = p.contract_amount
        snap[f"pos{i}_notional"]   = p.position_value_usdt
        snap[f"pos{i}_unrealized"] = p.individual_unrealized
        snap[f"pos{i}_model"]      = p.model_name

    return snap


def take_daily_snapshot() -> None:
    """Write BOD snapshot CSV."""
    _ensure_dirs()
    snap = _state_to_snapshot_dict()
    date_str = datetime.now(TZ_LOCAL).strftime("%Y-%m-%d")
    path = os.path.join(config.SNAPSHOTS_DIR, f"{date_str}_bod.csv")
    pd.DataFrame([snap]).to_csv(path, index=False)


def take_monthly_snapshot() -> None:
    """Overwrite monthly CSV with current state (reset on 1st of month)."""
    _ensure_dirs()
    snap = _state_to_snapshot_dict()
    month_str = datetime.now(TZ_LOCAL).strftime("%Y-%m")
    path = os.path.join(config.SNAPSHOTS_DIR, f"{month_str}_monthly.csv")

    if os.path.exists(path):
        df = pd.read_csv(path)
        df = pd.concat([df, pd.DataFrame([snap])], ignore_index=True)
    else:
        df = pd.DataFrame([snap])
    df.to_csv(path, index=False)


# ── Load last 30 days history ─────────────────────────────────────────────────

def load_recent_history(path: str, days: int = 30) -> List[Dict]:
    if not os.path.exists(path):
        return []
    try:
        df = pd.read_csv(path)
        if df.empty:
            return []
        # Try to filter last `days` days by first timestamp-like column
        ts_col = next((c for c in df.columns if "timestamp" in c.lower()), None)
        if ts_col:
            df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce", utc=True)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            df = df[df[ts_col] >= cutoff]
            # Convert Timestamp back to string so templates can slice with [:19]
            df[ts_col] = df[ts_col].astype(str)
        return df.fillna("").to_dict(orient="records")
    except Exception:
        return []


# ── Manual / auto export to XLSX ─────────────────────────────────────────────

async def export_all_to_excel(path: Optional[str] = None) -> str:
    """Export all log tables from SQLite to a multi-sheet XLSX file."""
    from core.db_router import db_router
    _ensure_dirs()
    if path is None:
        ts = datetime.now(TZ_LOCAL).strftime("%Y%m%d_%H%M%S")
        path = os.path.join(config.DATA_DIR, f"risk_engine_export_{ts}.xlsx")

    per = db_router.account_read
    pre_trade_df = pd.DataFrame(await per.get_all_pre_trade_log(days=365))
    execution_df = pd.DataFrame(await per.get_all_execution_log(days=365))
    history_df   = pd.DataFrame(await per.get_all_trade_history(days=365))
    # live_trades still on CSV (no DB table in Phase 1)
    live_df = pd.read_csv(config.LIVE_TRADES) if os.path.exists(config.LIVE_TRADES) else pd.DataFrame()

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, df in [
            ("pre_trade_log", pre_trade_df),
            ("execution_log", execution_df),
            ("trade_history", history_df),
            ("live_trades",   live_df),
        ]:
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    return path
