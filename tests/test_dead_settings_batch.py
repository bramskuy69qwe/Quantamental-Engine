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
  M2a · Config's weekly threshold rows show the EFFECTIVE values the
        engine derives (account_params max_w_loss_percent × warn/limit
        ratio); the dead account_settings weekly columns are no longer
        rendered or served to the form (data stays).
  M2b · weekly enforcement rendered as the constant ADVISORY-ONLY — no
        gate consumes the stored mode (advisory by design; /api/state's
        G-O2 comment is the backend statement of the same fact).
  M3  · week_start_dow gains its writer: Config form select (ISO 1-7)
        → POST /accounts/{id}/update with hoisted 1-7 validation → the
        settings writer. The reader (routes_analytics weekly bucketing
        via period_resolver) was real the whole time. Validation lanes
        live in tests/test_false_success_class.py::TestM3* (that file
        owns the handler's false-success/validation harness).
  M8  · analytics_default_period gains its reader: the Analytics page
        seeds its initial period from the account's saved value (once
        per mount, discarded after the operator touches the selector or
        when the value isn't one the selector offers), and — a NAMED
        ADDITION beyond the filed recommendation — a direct Config
        editor beside the other two preferences (the only remaining
        writer was preset Apply, which couples the period to a whole
        risk posture; the endpoint already validated the field).

Run: pytest tests/test_dead_settings_batch.py -v
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests._srcpin import code as _code  # noqa: E402

_ROOT = Path(__file__).parent.parent
_NODE = shutil.which("node")


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


# ── M2a + M2b: the weekly posture rows tell the truth ───────────────────────


class TestM2aM2bWeeklyPostureHonest:
    """account_settings.weekly_pnl_{warning,limit}_threshold and
    weekly_pnl_enforcement_mode are DEAD as inputs: the engine's weekly
    state machine reads account_params ratios only (core/data_cache), and
    no gate consumes a weekly enforcement mode. The Config form used to
    render all three as if live (and claimed presets write them — presets
    never carried weekly keys). Post-M2a/M2b the form derives the
    EFFECTIVE thresholds from params and states ADVISORY-ONLY."""

    def test_api_no_longer_serves_the_dead_weekly_fields(self, monkeypatch):
        """Executed against the real endpoint handler: a settings row that
        UNMISTAKABLY carries the dead fields must come back without them,
        while the live DD posture + prefs still flow."""
        import asyncio

        import core.db_account_settings as smod
        from api.routes_config import api_config_account
        from core.account_registry import account_registry
        from core.db_account_settings import AccountSettings

        stub = AccountSettings(
            account_id=999,
            weekly_pnl_warning_threshold=0.04,
            weekly_pnl_limit_threshold=0.0475,
            weekly_pnl_enforcement_mode="enforced",
            strategy_preset="scalping",
        )
        monkeypatch.setattr(smod, "get_account_settings", lambda aid: stub)
        monkeypatch.setattr(account_registry, "get_account_params",
                            lambda aid: {"max_w_loss_percent": 0.05})

        payload = json.loads(asyncio.run(api_config_account(999)).body)
        settings = payload["settings"]
        for dead in ("weekly_pnl_warning_threshold",
                     "weekly_pnl_limit_threshold",
                     "weekly_pnl_enforcement_mode"):
            assert dead not in settings, (
                f"M2a/M2b regression: /api/config/account serves {dead} "
                "again — the one consumer renders whatever arrives here."
            )
        for live in ("dd_rolling_window_days", "dd_warning_threshold",
                     "dd_limit_threshold", "dd_recovery_threshold",
                     "dd_enforcement_mode", "strategy_preset", "timezone"):
            assert live in settings, f"live field {live} vanished"

    def test_form_no_longer_reads_the_dead_columns(self):
        """Comment-stripped absence pin over the whole module: no executing
        reference to any of the three dead fields survives in
        pages-config.jsx (the M2a explainer comment there names them —
        raw-source grep would false-fail)."""
        stripped = _code((_ROOT / "frontend" / "src" / "pages-config.jsx")
                         .read_text(encoding="utf-8"))
        for dead in ("weekly_pnl_warning_threshold",
                     "weekly_pnl_limit_threshold",
                     "weekly_pnl_enforcement_mode"):
            assert dead not in stripped

    def test_the_enforcement_row_is_the_honest_constant(self):
        """M2b: the row's value is the CONSTANT 'ADVISORY-ONLY', not a
        read of any store — structural: the label and the constant share
        one object literal."""
        import re

        stripped = _code((_ROOT / "frontend" / "src" / "pages-config.jsx")
                         .read_text(encoding="utf-8"))
        m = re.search(
            r"\{\s*label:\s*'Weekly enforcement',\s*value:\s*'ADVISORY-ONLY'\s*\}",
            stripped,
        )
        assert m, (
            "the Weekly-enforcement row no longer renders the honest "
            "ADVISORY-ONLY constant (M2b)"
        )

    def test_derivation_reads_the_two_live_param_fields(self):
        """The effective rows must derive from the SAME params fields the
        form edits: _cfgEffWeekly reads max_w_loss_percent × the passed
        ratio key, and both weekly rows call it with the two ratio keys."""
        stripped = _code((_ROOT / "frontend" / "src" / "pages-config.jsx")
                         .read_text(encoding="utf-8"))
        assert "_cfgEffWeekly(p, 'weekly_loss_warning_pct')" in stripped
        assert "_cfgEffWeekly(p, 'weekly_loss_limit_pct')" in stripped


# ── M3: week_start_dow finally has a writer ─────────────────────────────────


class TestM3WeekStartDowWriter:
    """The reader (routes_analytics.py weekly bucketing) was always real;
    nothing ever wrote the column, so every account bucketed weeks from
    Monday forever. The writer chain: Config select → /accounts/{id}/update
    (1-7-validated, see test_false_success_class.TestM3*) → settings row.
    This class pins the two ends this chain newly grew."""

    def test_api_serves_the_stored_value(self, monkeypatch):
        """Executed: the Config form can only render the current value if
        /api/config/account serves it."""
        import asyncio

        import core.db_account_settings as smod
        from api.routes_config import api_config_account
        from core.account_registry import account_registry
        from core.db_account_settings import AccountSettings

        monkeypatch.setattr(
            smod, "get_account_settings",
            lambda aid: AccountSettings(account_id=999, week_start_dow=3),
        )
        monkeypatch.setattr(account_registry, "get_account_params",
                            lambda aid: {})
        payload = json.loads(asyncio.run(api_config_account(999)).body)
        assert payload["settings"].get("week_start_dow") == 3

    def test_form_seeds_posts_and_offers_exactly_iso_1_to_7(self):
        """Comment-stripped structural pins over pages-config.jsx: the form
        state seeds from settings, doSave posts the field (blank keeps
        stored), and the select offers exactly the values the endpoint
        accepts — both sides of that range parsed and compared (the server
        side from its own validation expression)."""
        import re

        stripped = _code((_ROOT / "frontend" / "src" / "pages-config.jsx")
                         .read_text(encoding="utf-8"))
        assert re.search(
            r"week_start_dow:\s*s\.week_start_dow != null "
            r"\? String\(s\.week_start_dow\) : ''", stripped)
        assert "week_start_dow: form.week_start_dow || null" in stripped
        # the select maps CFG_DOW_NAMES with value=String(i + 1) → values
        # are exactly 1..len(CFG_DOW_NAMES)
        m = re.search(r"const CFG_DOW_NAMES = \[([^\]]*)\];", stripped)
        assert m, "CFG_DOW_NAMES literal not found"
        names = [n.strip().strip("'\"") for n in m.group(1).split(",")]
        # the FULL ISO sequence, not just count + endpoints — a swapped
        # middle pair passed the first draft (audit LOW on this pin)
        assert names == ["Monday", "Tuesday", "Wednesday", "Thursday",
                         "Friday", "Saturday", "Sunday"]
        assert "CFG_DOW_NAMES.map((d, i) =>" in stripped
        assert "value={String(i + 1)}" in stripped
        # server side: PARSE the update handler's own range expression and
        # compare option count against it — both sides derived, neither
        # hardcoded twice
        handler = (_ROOT / "api" / "routes_accounts.py").read_text(
            encoding="utf-8")
        sm = re.search(
            r"not \((\d+) <= week_start_dow <= (\d+)\)", handler)
        assert sm, "the handler's 1-7 range expression is gone"
        lo, hi = int(sm.group(1)), int(sm.group(2))
        assert (lo, hi) == (1, 7), "ISO weekday range drifted"
        assert hi - lo + 1 == len(names), (
            "the form offers a different number of days than the server "
            "accepts"
        )

    def test_the_reader_still_reads_it(self):
        """M3's whole premise: the reader is real. TWO AST pins on
        routes_analytics, because the chain has two severable halves the
        first draft covered only one of (audit LOW: dropping the
        `week_start_dow=week_dow` kwarg from the resolve_period call —
        which silently reinstates permanent-Monday — left the read-only
        pin green): (a) the settings attribute is read, (b) a
        resolve_period CALL actually carries a week_start_dow keyword."""
        src = (_ROOT / "api" / "routes_analytics.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        reads = [
            node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Load)
        ]
        assert "week_start_dow" in reads, (
            "routes_analytics no longer reads week_start_dow — if the "
            "reader died, M3's writer is decoration; re-decide, don't "
            "just re-pin"
        )
        rp_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and (
                (isinstance(node.func, ast.Name)
                 and node.func.id == "resolve_period")
                or (isinstance(node.func, ast.Attribute)
                    and node.func.attr == "resolve_period")
            )
        ]
        assert rp_calls, "no resolve_period call found in routes_analytics"
        assert any(
            kw.arg == "week_start_dow"
            for call in rp_calls for kw in call.keywords
        ), (
            "resolve_period is called WITHOUT week_start_dow — the "
            "setting no longer influences weekly bucketing (permanent "
            "Monday is back)"
        )


# ── M8: analytics_default_period finally has readers ────────────────────────


class TestM8DefaultPeriodReader:
    """Write-no-reader closed from the read side: Analytics seeds its
    initial period from the saved setting; the Config form gains a direct
    editor (named addition — see the module docstring). The seed decision
    is the PURE _anaSeedPeriod so the node test below executes it."""

    def test_api_serves_the_stored_value(self, monkeypatch):
        import asyncio

        import core.db_account_settings as smod
        from api.routes_config import api_config_account
        from core.account_registry import account_registry
        from core.db_account_settings import AccountSettings

        monkeypatch.setattr(
            smod, "get_account_settings",
            lambda aid: AccountSettings(account_id=999,
                                        analytics_default_period="weekly"),
        )
        monkeypatch.setattr(account_registry, "get_account_params",
                            lambda aid: {})
        payload = json.loads(asyncio.run(api_config_account(999)).body)
        assert payload["settings"].get("analytics_default_period") == "weekly"

    def test_analytics_wires_the_seed(self):
        """Comment-stripped structural pins: the mount effect fetches the
        config-account door for the LIVE account id, routes the answer
        through _anaSeedPeriod, and the selector's own setter marks
        touched FIRST (so a late fetch can never stomp a human choice)."""
        stripped = _code((_ROOT / "frontend" / "src" / "pages-analytics.jsx")
                         .read_text(encoding="utf-8"))
        assert "_ptJson('/api/config/account/' + aid, QE_READ_DEADLINE_MS)" in stripped
        assert "_anaSeedPeriod(touchedRef.current," in stripped
        assert "const setP = (p) => { touchedRef.current = true; setPeriod(p);" in stripped
        # ‹ › marks touched TOO (audit MED: an un-marked offset click let a
        # late seed flip the period under a navigated offset — "weekly @
        # -1", unreachable by any user path). This also guarantees the
        # seed's bare setPeriod only ever lands at offset 0.
        assert "const nav = (d) => { touchedRef.current = true; setOffset((o) => o + d);" in stripped
        # the nav renders the SAME module-level list the seed validates
        # against — one vocabulary, two uses
        assert "<PeriodSelector options={ANA_PERIODS}" in stripped
        assert "const ANA_PERIOD_IDS = new Set(ANA_PERIODS.map(([id]) => id));" in stripped

    def _ids_from(self, src_name, const_name):
        import re

        stripped = _code((_ROOT / "frontend" / "src" / src_name)
                         .read_text(encoding="utf-8"))
        m = re.search(r"const %s = \[(.*?)\];" % const_name, stripped,
                      re.DOTALL)
        assert m, f"{const_name} literal not found in {src_name}"
        return set(re.findall(r"\['([a-z_0-9]+)',", m.group(1)))

    def test_both_selectors_offer_exactly_the_valid_periods(self):
        """Three-way parity, every side PARSED: the Analytics selector
        (ANA_PERIODS), the Config editor (CFG_ANA_PERIODS), and the
        backend's period_resolver.VALID_PERIODS must be the same set —
        an option the server rejects (or a server period no selector
        offers) is a silent dead end."""
        from core.period_resolver import VALID_PERIODS

        ana = self._ids_from("pages-analytics.jsx", "ANA_PERIODS")
        cfg = self._ids_from("pages-config.jsx", "CFG_ANA_PERIODS")
        assert ana == set(VALID_PERIODS), f"Analytics drift: {ana ^ set(VALID_PERIODS)}"
        assert cfg == set(VALID_PERIODS), f"Config drift: {cfg ^ set(VALID_PERIODS)}"

    def test_config_form_seeds_and_posts_it(self):
        stripped = _code((_ROOT / "frontend" / "src" / "pages-config.jsx")
                         .read_text(encoding="utf-8"))
        assert "analytics_default_period:  s.analytics_default_period || ''" in stripped
        assert "analytics_default_period: form.analytics_default_period || null" in stripped


@pytest.mark.skipif(_NODE is None, reason="node not on PATH")
class TestM8SeedDecisionExecuted:
    """The pure seed decision under node: adopt only untouched+valid."""

    def test_seed_semantics(self, tmp_path):
        src = (_ROOT / "frontend" / "src" / "pages-analytics.jsx").read_text(
            encoding="utf-8")
        block = src[src.index("const ANA_PERIODS"):src.index("const _anaPnl")]
        js = block + (
            "const CASES = [\n"
            "  { n: 'untouched_valid',   t: false, f: 'weekly' },\n"
            "  { n: 'touched_valid',     t: true,  f: 'weekly' },\n"
            "  { n: 'untouched_invalid', t: false, f: 'fortnightly' },\n"
            "  { n: 'untouched_missing', t: false, f: undefined },\n"
            "  { n: 'untouched_empty',   t: false, f: '' },\n"
            "  { n: 'untouched_default', t: false, f: 'monthly' },\n"
            "];\n"
            "console.log(JSON.stringify(CASES.map(c => ({ n: c.n, r: _anaSeedPeriod(c.t, c.f) }))));\n"
        )
        f = tmp_path / "seed.mjs"
        f.write_text(js, encoding="utf-8")
        r = subprocess.run([_NODE, str(f)], capture_output=True, text=True,
                           encoding="utf-8", timeout=30)
        assert r.returncode == 0, r.stderr
        rows = {row["n"]: row["r"] for row in json.loads(r.stdout)}
        assert rows["untouched_valid"] == "weekly"
        assert rows["touched_valid"] is None, (
            "a late fetch stomped the operator's own selection"
        )
        assert rows["untouched_invalid"] is None, (
            "an unknown stored period leaked into the selector state"
        )
        assert rows["untouched_missing"] is None
        assert rows["untouched_empty"] is None
        # adopting the value that EQUALS the fallback is a harmless no-op
        # setState — allowed, pinned so a 'skip if monthly' optimization
        # is a deliberate change
        assert rows["untouched_default"] == "monthly"


@pytest.mark.skipif(_NODE is None, reason="node not on PATH")
class TestM2aEffectiveThresholdParity:
    """BOTH sides executed: the JSX derivation under node, and the REAL
    engine weekly state machine (DataCache._do_recalculate_portfolio,
    called unbound on a stub app_state). The displayed effective
    threshold must be exactly the loss fraction where the engine flips —
    that is the entire claim of the word 'effective'."""

    CAP, WARN_R, LIMIT_R = 0.05, 0.8, 0.95

    def _js(self, tmp_path):
        src = (_ROOT / "frontend" / "src" / "pages-config.jsx").read_text(
            encoding="utf-8")
        fn = src[src.index("const _cfgEffWeekly"):src.index("const _cfgUptime")]
        js = fn + (
            "const p = { max_w_loss_percent: %s, weekly_loss_warning_pct: %s,"
            " weekly_loss_limit_pct: %s };\n"
            "console.log(JSON.stringify({\n"
            "  warn: _cfgEffWeekly(p, 'weekly_loss_warning_pct'),\n"
            "  limit: _cfgEffWeekly(p, 'weekly_loss_limit_pct'),\n"
            "  null_cap: _cfgEffWeekly({ weekly_loss_warning_pct: 0.8 }, 'weekly_loss_warning_pct'),\n"
            "  null_p: _cfgEffWeekly(null, 'weekly_loss_warning_pct'),\n"
            "  nan: _cfgEffWeekly({ max_w_loss_percent: 'x', weekly_loss_warning_pct: 0.8 }, 'weekly_loss_warning_pct'),\n"
            # The replacer maps NaN → the STRING 'NaN': bare JSON.stringify
            # serializes NaN as null, which made the nan-lane assertion
            # below unable to tell the guard from its absence (this pin's
            # first draft SURVIVED deletion of the isNaN guard — mutation
            # sweep finding).
            "}, (k, v) => (typeof v === 'number' && Number.isNaN(v)) ? 'NaN' : v));\n"
            % (self.CAP, self.WARN_R, self.LIMIT_R)
        )
        f = tmp_path / "eff.mjs"
        f.write_text(js, encoding="utf-8")
        r = subprocess.run([_NODE, str(f)], capture_output=True, text=True,
                           encoding="utf-8", timeout=30)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    def _engine_state(self, loss_frac):
        """pf.weekly_pnl_state after the REAL recalc at `loss_frac` weekly
        loss. The stub account id resolves no settings row, so the
        rolling-DD block takes its legacy fallback — the weekly branch
        above it is unconditional either way."""
        from types import SimpleNamespace

        from core.data_cache import DataCache

        sow = 10_000.0
        eq = sow * (1.0 - loss_frac)
        acc = SimpleNamespace(
            total_equity=eq, bod_equity=sow, sow_equity=sow,
            max_total_equity=sow, min_total_equity=eq,
            total_tp_usdt=0.0, total_sl_usdt=0.0,
            daily_pnl=0.0, daily_pnl_percent=0.0,
            available_margin=eq, total_unrealized=0.0,
        )
        pf = SimpleNamespace(
            total_exposure=0.0, total_correlated_exposure={},
            total_weekly_pnl=0.0, total_weekly_pnl_percent=0.0,
            drawdown=0.0, weekly_pnl_state="ok", dd_state="ok",
            dd_degraded=False,
        )
        prm = {
            "max_w_loss_percent": self.CAP,
            "weekly_loss_warning_pct": self.WARN_R,
            "weekly_loss_limit_pct": self.LIMIT_R,
            "max_dd_percent": 0.10, "max_dd_warning_pct": 0.8,
            "max_dd_limit_pct": 0.95,
        }
        st = SimpleNamespace(
            account_state=acc, params=prm, portfolio=pf,
            active_account_id=999_999_999,
            dd_previous_states={}, dd_episode_peaks={},
            dd_would_have_blocked_logged=set(),
            dd_manually_unblocked=set(),
        )
        DataCache._do_recalculate_portfolio(
            SimpleNamespace(_positions=[]), st)
        return pf.weekly_pnl_state

    def test_displayed_thresholds_are_where_the_engine_flips(self, tmp_path):
        eff = self._js(tmp_path)
        assert eff["warn"] == pytest.approx(self.CAP * self.WARN_R)
        assert eff["limit"] == pytest.approx(self.CAP * self.LIMIT_R)
        # null lanes: a missing cap, missing params object, or non-numeric
        # cap must all render '—', never 0% (0% would read as "always at
        # limit")
        assert eff["null_cap"] is None
        assert eff["null_p"] is None
        assert eff["nan"] is None, (
            "non-numeric cap leaked through as NaN — the isNaN guard is "
            "gone (NaN arrives here as the string 'NaN' via the replacer)"
        )
        # the engine, 0.1% either side of each displayed number
        assert self._engine_state(eff["warn"] * 0.999) == "ok"
        assert self._engine_state(eff["warn"] * 1.001) == "warning"
        assert self._engine_state(eff["limit"] * 1.001) == "limit"
