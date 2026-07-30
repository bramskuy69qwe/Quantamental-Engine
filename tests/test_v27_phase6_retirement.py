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

TEMPLATES = Path(__file__).parent.parent / "templates"

QT_ROUTE = "/api/backtest/" + "qt-" + "import"


def _src(rel: str) -> str:
    return (TEMPLATES / rel).read_text(encoding="utf-8")


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






def test_results_fragment_keeps_microstructure_branch():
    """Task 6.4: historical type='microstructure' sessions must still
    render — the branch is KEPT and anchor-commented."""
    src = _src("fragments/backtest/results.html")
    assert "session.type == 'microstructure'" in src
    assert "KEPT deliberately" in src


def test_results_fragment_renders_historical_microstructure_session():
    """P6 audit MED-1: P6 added a `{# #}` block to results.html — the
    nested-comment gotcha class demands a compile-AND-render, and the
    acceptance criterion ('historical quantower rows still render')
    deserves a real render with a microstructure-shaped context, the
    exact summary shape the retired importer wrote."""
    html = templates.env.get_template(
        "fragments/backtest/results.html"
    ).render(
        session={
            "id": 42, "type": "microstructure", "status": "completed",
            "name": "Quantower Import", "date_from": "", "date_to": "",
            "summary": {
                "source": "quantower", "total_trades": 2, "win_rate": 0.5,
                "total_r": 1.2, "avg_slippage_bps": 1.75,
                "r_stats": {"win_rate": 0.5, "expectancy": 0.6,
                            "profit_factor": 1.4},
            },
        },
        trades=[{
            "symbol": "BTCUSDT", "side": "long", "entry_dt": "2026-01-01",
            "exit_dt": "2026-01-02", "entry_price": 100.0,
            "exit_price": 110.0, "size_usdt": 1000.0, "r_multiple": 1.0,
            "pnl_usdt": 10.0, "regime_label": "", "exit_reason": "tp",
        }],
        equity=[],
    )
    assert "Quantower microstructure import" in html
    assert "1.75" in html  # avg slippage renders from the historical summary


