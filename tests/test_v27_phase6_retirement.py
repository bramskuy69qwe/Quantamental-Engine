"""
v2.7 Phase 6 — retirement pins (the Quantower JSON importer + the old
Models sub-tab).

Mirrors the v2.6 removal-pin idiom: assert the retired surfaces are GONE,
the deliberately-KEPT survivors are still present, and the route table no
longer carries the deleted endpoint. The literal retired tokens are
composed ("qt-" + "import") so the plan's acceptance grep stays clean on
this file.

Run: pytest tests/test_v27_phase6_retirement.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from api.helpers import templates


QT_ROUTE = "/api/backtest/" + "qt-" + "import"


def test_retired_importer_route_gone_from_route_table():
    """Import-smoke (no TestClient): the deleted endpoint must not be
    registered; its surviving siblings must be."""
    import main
    paths = {getattr(r, "path", "") for r in main.app.routes}
    assert QT_ROUTE not in paths
    assert "/api/backtest/run" in paths        # sibling survives
    assert "/api/backtest/sessions" in paths   # sibling survives
    assert "/models/{model_id}/backtest-upload" in paths  # the successor


def test_routes_backtest_source_carries_no_importer():
    src = Path("api/routes_backtest.py").read_text(encoding="utf-8")
    assert "api_" + "qt_" + "import" not in src
    # _validate_date_range STAYS — api_backtest_run still calls it.
    assert "_validate_date_range" in src


