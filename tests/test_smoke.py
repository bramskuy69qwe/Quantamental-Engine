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
