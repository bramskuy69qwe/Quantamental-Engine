"""Dead-settings batch (wiring inventory M1-M4 + M8; operator go 2026-08-04).

Seven knobs, one seam: settings that render as live while nothing reads
them, or are read while nothing writes them. The decision table lives in
HANDOFF.md's twelfth block; the operator approved the recommendations on
2026-08-04 and the batch ships ONE TASK PER COMMIT. This file grows with
it — each class below documents its fix in the commit that lands it, and
a class for an unshipped sibling must not exist yet (first audit of this
very file caught its docstring claiming all seven as fixed while only
M2c was in the tree — the fabricated-provenance class).

Shipped so far (in commit order):
  M2c · EXCHANGE_REFRESH_HZ — REMOVED (zero consumers ever; git-verified
        back to its v2.4 introduction — it shipped without wiring).
  M4  · position_changes — the per-refresh write retired (19,151 live
        rows, zero prod readers ever); the table, its rows and the
        db_snapshots API all stay (forensics + kept-API convention).

Run: pytest tests/test_dead_settings_batch.py -v
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

_ROOT = Path(__file__).parent.parent


# ── M2c: EXCHANGE_REFRESH_HZ is gone and stays gone ─────────────────────────


class TestM2cExchangeRefreshHzRemoved:
    def test_config_module_has_no_attribute(self):
        """Executed pin: the module object itself, not the source text."""
        import config
        assert not hasattr(config, "EXCHANGE_REFRESH_HZ"), (
            "M2c regression: EXCHANGE_REFRESH_HZ reappeared in config.py. "
            "It had ZERO consumers for its whole life (v2.4→v3.1) — wire a "
            "consumer first if the knob is ever actually needed."
        )

    def test_no_assignment_in_config_source(self):
        """AST pin, not a substring scan: the removal note in config.py
        legitimately mentions the name in a comment, so a text grep would
        either false-fail or have to be written vacuously. Harvests
        Assign AND AnnAssign targets, including tuple unpacks (the first
        draft took plain Assign/Name only and an annotated
        `EXCHANGE_REFRESH_HZ: float = 1.0` walked straight through it —
        audit finding on this pin). The hasattr sibling above remains the
        backstop for any shape that actually executes."""
        tree = ast.parse((_ROOT / "config.py").read_text(encoding="utf-8"))

        def _names(t):
            if isinstance(t, ast.Name):
                yield t.id
            elif isinstance(t, (ast.Tuple, ast.List)):
                for e in t.elts:
                    yield from _names(e)

        targets = [
            name
            for node in ast.walk(tree)
            for t in (
                node.targets if isinstance(node, ast.Assign)
                else [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign))
                else []
            )
            for name in _names(t)
        ]
        assert "EXCHANGE_REFRESH_HZ" not in targets

    def test_no_prod_consumer_ever_appeared(self):
        """The removal's justification, kept true: no executing code under
        api/ core/ or main.py may reference the name. Known scan lanes,
        accepted deliberately (audit-reviewed): the per-line '#'-tail strip
        also truncates a '#' inside a string literal (a consumer hiding the
        name AFTER one is invisible here — contrived, and the hasattr pin
        catches anything that executes); multi-line strings are scanned as
        code (fail-LOUD lane only); templates/ static/ scripts/ are out of
        scope (root executing modules are main.py + config.py — verified)."""
        hits = []
        for base in ("api", "core", "main.py"):
            p = _ROOT / base
            files = [p] if p.is_file() else sorted(p.rglob("*.py"))
            for f in files:
                for i, line in enumerate(
                    f.read_text(encoding="utf-8").splitlines(), 1
                ):
                    code_part = line.split("#", 1)[0]
                    if "EXCHANGE_REFRESH_HZ" in code_part:
                        hits.append(f"{f.relative_to(_ROOT)}:{i}")
        assert hits == [], (
            "EXCHANGE_REFRESH_HZ is referenced in executing code — it was "
            f"removed as consumer-less (M2c). Sites: {hits}"
        )


# ── M4: the position_changes write is retired; table + API + data stay ──────


class TestM4PositionChangesWriteRetired:
    @pytest.mark.asyncio
    async def test_handler_writes_snapshot_but_not_position_changes(
        self, monkeypatch
    ):
        """Executed against the real handler: a positions refresh with a
        NON-EMPTY book persists the account snapshot and never touches
        position_changes. (Non-empty matters: insert_position_changes
        no-ops on [], so an empty-book run could pass vacuously even
        pre-fix. The symbol set is pre-seeded equal so the ws_manager
        restart branch stays cold — this test is about the writes.)"""
        from types import SimpleNamespace

        from core import handlers
        from core.state import app_state

        calls = {"pos": 0, "snap": 0}

        async def pos_stub(*a, **kw):
            calls["pos"] += 1

        async def snap_stub(*a, **kw):
            calls["snap"] += 1

        monkeypatch.setattr(handlers.db, "insert_position_changes", pos_stub,
                            raising=False)
        monkeypatch.setattr(handlers.db, "insert_account_snapshot", snap_stub,
                            raising=False)
        monkeypatch.setattr(app_state, "_data_cache", None, raising=False)
        monkeypatch.setattr(
            app_state, "_positions_legacy",
            [SimpleNamespace(ticker="BTCUSDT", direction="LONG",
                             contract_amount=0.1, average=80000.0,
                             fair_price=80000.0, position_value_usdt=8000.0,
                             individual_unrealized=0.0,
                             individual_margin_used=400.0,
                             sector="big_two_crypto")],
            raising=False,
        )
        # monkeypatch, not direct assignment — a bare set here leaks the
        # sentinel symbol set into every later handler test in the session
        # (audit LOW on this test's first draft).
        monkeypatch.setattr(handlers.handle_positions_refreshed,
                            "_prev_syms", {"BTCUSDT"}, raising=False)

        await handlers.handle_positions_refreshed({"trigger": "m4-test"})

        assert calls["snap"] == 1, "the account-snapshot write must survive M4"
        assert calls["pos"] == 0, (
            "M4 regression: handle_positions_refreshed wrote "
            "position_changes again — the write was retired 2026-08-04 "
            "(19k rows, zero prod readers ever)."
        )

    def test_no_call_site_in_handlers_source(self):
        """AST pin: no `<anything>.insert_position_changes(...)` call left
        in core/handlers.py. AST, because the retirement's anchor comment
        there names the method — a text grep would false-fail (or be
        written to skip comments and rot)."""
        tree = ast.parse(
            (_ROOT / "core" / "handlers.py").read_text(encoding="utf-8")
        )
        called = [
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        ]
        assert "insert_position_changes" not in called

    def test_the_api_and_the_table_stay(self):
        """The retirement is the WRITE only. Deleting the DB-layer method
        or the CREATE TABLE is a data-affecting decision this batch
        explicitly did NOT take (HANDOFF decision table: 'Stop the write,
        keep table + data') — a later dead-code sweep must meet this pin
        and read that reasoning first.

        The table check EXECUTES the base schema into :memory: and asks
        sqlite_master — this pin's first draft was a substring match that
        its own mutation sweep walked through (a renamed
        `position_changes_x` still contained the asserted prefix)."""
        import sqlite3

        import core.database as dbmod
        from core.db_snapshots import SnapshotsMixin

        assert hasattr(SnapshotsMixin, "insert_position_changes")
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(dbmod._CREATE_STATEMENTS)
            row = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='position_changes'"
            ).fetchone()
        finally:
            conn.close()
        assert row, "position_changes is no longer created by the base schema"
