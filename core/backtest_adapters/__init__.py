"""
3rd-party backtest import adapters (v2.7 Phase 2).

Importing this package registers every adapter (the
``@register_backtest_adapter`` decorators fire at import time) —
mirror of core/adapters/__init__.
"""
from core.backtest_adapters.base import BacktestAdapter, BacktestAdapterError
from core.backtest_adapters.protocols import (
    BacktestSummary,
    BacktestTrade,
    EquityPoint,
    NormalizedBacktestResult,
)
from core.backtest_adapters.registry import (
    get_backtest_adapter,
    list_backtest_adapters,
    register_backtest_adapter,
)

from core.backtest_adapters import multicharts  # noqa: F401  (registers)

__all__ = [
    "BacktestAdapter",
    "BacktestAdapterError",
    "BacktestSummary",
    "BacktestTrade",
    "EquityPoint",
    "NormalizedBacktestResult",
    "get_backtest_adapter",
    "list_backtest_adapters",
    "register_backtest_adapter",
]
