"""Parametrized integration test runner — auto-discovers scenarios."""
import importlib
import os

import pytest

from tests.integration.driver import run_scenario_sync, assert_scenario_state

_SCENARIOS_DIR = os.path.join(os.path.dirname(__file__), "scenarios")


def _discover_scenarios():
    """Import all scenario modules and collect their .scenario attribute."""
    results = []
    for fname in sorted(os.listdir(_SCENARIOS_DIR)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        mod_name = f"tests.integration.scenarios.{fname[:-3]}"
        mod = importlib.import_module(mod_name)
        if hasattr(mod, "scenario"):
            results.append(mod.scenario)
    return results


_scenarios = _discover_scenarios()


@pytest.mark.parametrize("scenario", _scenarios, ids=[s.name for s in _scenarios])
def test_scenario(scenario, tmp_path):
    actual = run_scenario_sync(scenario, str(tmp_path))
    assert_scenario_state(scenario, actual)
