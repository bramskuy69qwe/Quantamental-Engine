"""
v2.7 Phase 4 — model-library page shell + nav wiring.

The full-render coverage of GET /models rides tests/test_routes.py's
PAGE_ROUTES smoke (the real app render through _ctx — LOW-023: one
TestClient per process). This file pins the pieces that smoke can't
express:
- model_library.html compiles (Jinja syntax, MED-047 class)
- the shell defines the EXACT container ids the Phase-3 htmx contract
  targets (#model-list loading /fragments/models/list, #model-detail)
- base.html carries the nav_items tuple + page_meta entry for 'models'
- the detail fragment's Phase-4 actions (Load into Calculator carrying
  ?model_id=, the run-list refresh hook) render with their wiring

Run: pytest tests/test_v27_phase4_model_library_page.py -v
"""
from __future__ import annotations

from pathlib import Path

from api.helpers import templates

TEMPLATES = Path(__file__).parent.parent / "templates"


def test_model_library_template_compiles():
    """Syntax-level pin: get_template compiles the page (render happens
    in the test_routes smoke through the real _ctx)."""
    templates.env.get_template("model_library.html")


def test_shell_defines_the_phase3_htmx_contract_ids():
    src = (TEMPLATES / "model_library.html").read_text(encoding="utf-8")
    assert 'id="model-list"' in src, "oob target #model-list missing"
    assert 'hx-get="/fragments/models/list"' in src
    assert 'id="model-detail"' in src, "fragment target #model-detail missing"


def test_base_html_nav_and_page_meta_carry_models():
    """Whitespace-tolerant pins (P4 audit NIT: don't break on a harmless
    column re-alignment of the nav literal)."""
    import re
    src = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert re.search(r"\('models',\s*'/models'\)", src), "nav_items entry missing"
    assert re.search(r"'models':\s*\('Model Library'", src), "page_meta entry missing"


def test_detail_fragment_phase4_actions_render():
    html = templates.env.get_template("fragments/model_detail.html").render(
        model={
            "id": 5, "name": "T", "type": "both", "description": "",
            "created_at": "2026-07-16", "updated_at": None,
            "risk_preset": {}, "strategy": {},
        },
        runs=[],
        adapters=[{"app_id": "multicharts", "display_name": "MultiCharts",
                   "accepted_extensions": [".xlsx"]}],
    )
    assert 'href="/calculator?model_id=5"' in html
    assert "Load into Calculator" in html
    assert 'hx-get="/fragments/models/backtests/5"' in html  # refresh hook
