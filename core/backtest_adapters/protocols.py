"""
Normalized result shapes for 3rd-party backtest imports (v2.7 Phase 2).

``BacktestTrade`` / ``EquityPoint`` are field-compatible with the
``backtest_trades`` / ``backtest_equity`` columns (verified exact vs
core/database.py — asdict keys == the insert helpers' expected keys), so
``asdict(result)`` feeds ``db.create_model_backtest(model_id, app_id,
asdict(result))`` unchanged.

Every field is defaulted: adapters are tolerant by contract, and a
defaulted dataclass guarantees ``asdict()`` always carries every key —
load-bearing for ``insert_backtest_equity``, which subscripts its keys
directly (non-tolerant). Keep these dataclasses; do not "optimize" them
into raw dicts.

Unit conventions (v2.7 plan §2.1 / §6-3):
- ``win_rate`` / ``max_drawdown_pct``: fractions 0-1.
- ``max_drawdown`` and per-point ``EquityPoint.drawdown``: POSITIVE
  dollar magnitudes (MultiCharts reports drawdowns signed-negative —
  adapters must abs() them).
- ``profit_factor``: unsigned (gross_profit / abs(gross_loss)).
- ``entry_dt`` / ``exit_dt`` / ``dt`` / ``period_*``: ISO-8601 strings.
- ``size_usdt``: dollar notional (Price x Contracts x Point Value —
  §6-3a decision).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class BacktestTrade:
    symbol: str = ""
    side: str = ""            # "long" | "short"
    entry_dt: str = ""
    exit_dt: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    size_usdt: float = 0.0
    # v3.0 P7 (G-M7): the raw contract count alongside the dollar
    # notional — size_usdt = entry_price × contracts × point_value, so
    # contracts is otherwise unrecoverable without the Settings sheet.
    contracts: float = 0.0
    r_multiple: float = 0.0   # not in MC reports — stays 0
    pnl_usdt: float = 0.0
    regime_label: str = ""    # n/a for external apps — stays ""
    exit_reason: str = ""     # normalized: take_profit / stop_loss / raw


@dataclass
class EquityPoint:
    dt: str = ""
    equity: float = 0.0
    drawdown: float = 0.0     # positive $ magnitude


@dataclass
class BacktestSummary:
    net_profit: float = 0.0
    win_rate: float = 0.0            # fraction 0-1
    profit_factor: float = 0.0       # unsigned
    max_drawdown: float = 0.0        # positive $ (abs of MC's negative)
    max_drawdown_pct: float = 0.0    # positive fraction (§6-3: store both)
    sharpe: float = 0.0
    total_trades: int = 0
    period_start: str = ""
    period_end: str = ""


@dataclass
class NormalizedBacktestResult:
    summary: BacktestSummary = field(default_factory=BacktestSummary)
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[EquityPoint] = field(default_factory=list)
    source_app: str = ""
    session_name: str = ""
    # Settings-sheet params (all values stringified for JSON safety).
    # NOT in the plan's 2.1 field list — added BECAUSE §6-3b decided the
    # params render read-only in the run detail; create_model_backtest
    # ignores unknown keys, so Phase 3 decides persistence (e.g. merge
    # into summary_json["settings"] at the upload route).
    settings: Dict[str, str] = field(default_factory=dict)
