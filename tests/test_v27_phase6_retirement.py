"""
v2.7 Phase 6 — retirement pins (the Quantower JSON importer + the old
Models sub-tab), EXTENDED 2026-08-04 with the BACKTEST-RUNNER retirement
(operator decision, closing the wiring inventory's M11 remainder).

Mirrors the v2.6 removal-pin idiom: assert the retired surfaces are GONE,
the deliberately-KEPT survivors are still present, and the route table no
longer carries the deleted endpoints. The literal retired tokens are
composed ("qt-" + "import") so the plan's acceptance grep stays clean on
this file.

THE RUNNER RETIREMENT'S SHAPE (verify-first, caller-by-caller — the
ninth-block retirement discipline):
  GONE   · api/routes_backtest.py (all six /api/backtest/* routes),
           core/backtest_runner.py, the api/router.py registration, the
           runner's own pins (test_task97_1_wiring_pins whole file,
           TestBacktestDateRangeValidation, two taskd 400-shape tests,
           two smoke entries).
  KEPT   · core/ohlcv_fetcher.py as CLI-ONLY ingestion — it is the SOLE
           writer of ohlcv_cache, which the live btc_rvol_ratio regime
           signal reads (deleting a route must not starve a live
           signal's feed — the rehomed-guard precedent);
         · core/db_backtest.py whole (six of nine methods are the LIVE
           import lane's write/read path via db_models; route-orphaned
           GET/LIST stay as the import-lane tests' fixtures, DELETE has
           zero callers of any kind and stays purely on the
           table-level-API convention);
         · every backtest_* table + row (NO DROP/DELETE). Recorded
           consequence: engine-run ('macro') and historical Quantower
           ('microstructure') rows are UNREADABLE through any door until
           a reader is added — data preserved, surface removed.
  LANE   · /models/{id}/backtest-upload + core/backtest_adapters/* (the
           ratified external-import workflow) — untouched, pinned below.

Run: pytest tests/test_v27_phase6_retirement.py -v
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


QT_ROUTE = "/api/backtest/" + "qt-" + "import"


def _route_paths():
    import main

    return {getattr(r, "path", "") for r in main.app.routes}


def test_retired_importer_route_gone_from_route_table():
    """Import-smoke (no TestClient): the Quantower importer endpoint must
    not be registered. (Its two runner siblings were pinned here as
    SURVIVORS until 2026-08-04 — those assertions inverted deliberately
    with the runner retirement, see the class below.)"""
    assert QT_ROUTE not in _route_paths()


class TestBacktestRunnerRetired:
    def test_no_api_backtest_route_survives(self):
        """The whole /api/backtest/* family is gone — fetch-ohlcv jobs,
        fetch-status, run, sessions CRUD. Prefix-scanned so a single
        forgotten (or re-added) route fails loudly by name."""
        stale = sorted(p for p in _route_paths()
                       if p.startswith("/api/backtest"))
        assert stale == [], (
            f"retired runner routes still registered: {stale} — the "
            "backtest runner was DELETED by operator decision 2026-08-04; "
            "re-adding one is a subsystem revival, not a patch"
        )

    def test_the_successor_lane_survives(self):
        assert "/models/{model_id}/backtest-upload" in _route_paths()

    def test_runner_files_gone_survivors_present(self):
        assert not Path("api/routes_backtest.py").exists()
        assert not Path("core/backtest_runner.py").exists()
        assert "routes_backtest" not in Path("api/router.py").read_text(
            encoding="utf-8").replace("# (routes_backtest retired", "")
        # the deliberate survivors
        assert Path("core/ohlcv_fetcher.py").exists()
        assert Path("core/db_backtest.py").exists()

    def test_the_regime_feed_chain_still_holds(self):
        """The reason ohlcv_fetcher survived, pinned as a CHAIN so either
        end dying turns this red: the fetcher still WRITES ohlcv_cache
        (db.upsert_ohlcv call) and compute_btc_rvol_ratio ITSELF still
        READS it (db.get_ohlcv INSIDE that function — audit LOW: the
        first draft accepted any get_ohlcv call anywhere in the file,
        so a refactor moving the signal off the table could have passed
        vacuously)."""
        def db_calls(path, within=None):
            tree = ast.parse(Path(path).read_text(encoding="utf-8"))
            roots = [tree]
            if within is not None:
                roots = [
                    n for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == within
                ]
                assert roots, f"{within} not found in {path}"
            return {
                n.func.attr
                for root in roots
                for n in ast.walk(root)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "db"
            }

        assert "upsert_ohlcv" in db_calls("core/ohlcv_fetcher.py"), (
            "ohlcv_cache lost its only writer — the CLI-only survival "
            "rationale is void; re-decide, don't just re-pin"
        )
        assert "get_ohlcv" in db_calls(
            "core/regime_fetcher.py", within="compute_btc_rvol_ratio"
        ), (
            "compute_btc_rvol_ratio no longer reads ohlcv_cache — if the "
            "signal moved off the table, the fetcher's survival rationale "
            "needs re-deciding"
        )

    def test_the_import_lane_never_touched_the_runner(self):
        """The lane that survives must be provably independent: no import
        of the deleted modules anywhere in api/ or core/."""
        hits = []
        for base in ("api", "core"):
            for f in sorted(Path(base).rglob("*.py")):
                tree = ast.parse(f.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    mods = []
                    if isinstance(node, ast.Import):
                        mods = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        mods = [node.module or ""]
                        # `from core import backtest_runner` carries the
                        # retired name in .names, not .module — the first
                        # draft's blind lane (audit LOW)
                        if (node.module or "") in ("core", "api"):
                            mods += [f"{node.module}.{a.name}"
                                     for a in node.names]
                    if any(m.startswith(("core.backtest_runner",
                                         "api.routes_backtest"))
                           for m in mods):
                        hits.append(str(f))
        assert hits == [], f"deleted runner modules still imported: {hits}"
