"""HA-4 — the session-scoped sink-dir floor has an asserting observer.

The floor (tests/conftest.py::_corr_log_session_floor) guards the PROVEN
T0b live-dir leak: module-scoped TestClient lifespans run BEFORE any
function-scoped patch, so without the floor the writer thread captures
the LIVE data/logs/correlation dir (and prunes it). Deleting the floor
fixture previously left the suite green — this module fails instead.

The probe fixture is MODULE-scoped: pytest instantiates it before the
function-scoped `_isolate_correlation_log_dir`, i.e. in exactly the
window the floor owns.
"""

import config
import core.correlation_log as cl
import pytest


@pytest.fixture(scope="module")
def resolver_at_module_setup():
    # captured BEFORE any function-scoped per-test patch exists
    return cl._resolve_sink_dir()


def test_session_floor_covers_higher_scoped_fixtures(resolver_at_module_setup):
    live = str(config.CORR_LOG_DIR)
    assert resolver_at_module_setup != live, (
        "the session floor is gone — module-scoped lifespans would write to "
        "(and prune!) the LIVE correlation dir"
    )
    assert "corr-floor" in resolver_at_module_setup
