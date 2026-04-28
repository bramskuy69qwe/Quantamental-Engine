"""Import all core modules and assert no exceptions at module load time."""
import importlib
import pytest

MODULES = [
    "config",
    "core.state",
    "core.database",
    "core.risk_engine",
    "core.regime_classifier",
    "core.regime_fetcher",
    "core.news_fetcher",
    "core.event_bus",
    "core.db_router",
    "core.migrations.000_split_databases",
    "core.account_registry",
    "core.crypto",
    "core.data_logger",
    "core.exchange",
    "core.ws_manager",
    "core.platform_bridge",
    "core.reconciler",
    "core.handlers",
    "core.analytics",
    "core.backtest_runner",
    "core.monitoring",
]


@pytest.mark.parametrize("module", MODULES)
def test_import(module):
    importlib.import_module(module)


def test_db_router_pre_split_returns_legacy():
    """Pre-split, every db_router accessor returns the legacy combined DB."""
    from core.db_router import db_router, split_done
    from core.database import db as legacy
    if split_done():
        # Skip when split already executed — different invariants apply post-split.
        return
    assert db_router.global_db is legacy
    assert db_router.account_db() is legacy
    assert db_router.ohlcv_db("binancefutures") is legacy
