"""MED-tail batch (wiring inventory M5/M7/M9/M11/M12/M13; operator go
2026-08-04 "do remaining meds").

Each class documents its fix in the commit that lands it — an unshipped
sibling must not have a class here (the dead-settings batch's
fabricated-provenance lesson). Companion file:
tests/test_dead_settings_batch.py holds the M1-M4+M8 pins.

Shipped so far (in commit order):
  M13 · the Primitives page badge said "NOT IN PRODUCTION NAV" while the
        page IS in production nav (kept there by a recorded operator
        decision — the inventory's third NOT-DEFECT). The badge now says
        what the page is (design-system reference, demo data) instead of
        where it isn't.
  M12 · CLOSED WITHOUT CODE — investigated, already resolved: the
        WorkspaceBar's workspace controls off-Dashboard have been dimmed
        + pointer-inert + captioned "· dashboard only" since P0
        (git-verified, 1221b16), which IS the honest-disable contract
        (FE-MED-018: a dead control must look dead). Making them WORK
        off-Dashboard is DEFERRED by the ratified plan's own defer list
        — docs/design/v3.0_ui_rebuild_plan.md §7: "gates Save/Load to
        the Dashboard; ship one persisted default layout per page,
        defer per-page named presets" (audit-corrected citation: the
        UI-rebuild close's decision #3 defers ACCOUNT-namespacing, a
        different axis). The pins below keep the honest-disable from
        silently regressing; the ⊞ Pane / ⤢ Pop stubs are the LOW
        tier's, not M12's.
  M5  · OrderManager.check_dd_gate_for_order REMOVED — added by v2.4
        Priority 1c for an engine-side order-placement lane and never
        called by prod code ever (git -S: exactly two CODE commits — its
        introduction 5391042 and its tests b63e06b; the third -S hit is
        the inventory's own doc filing e6c7bde — audit-corrected count;
        no caller was ever added or removed, verified on every branch
        incl. the quantower archive). The premise died with the v2.6
        Quantower removal: the observe-only engine has no order to gate.
        core/dd_gate stays THE gate (calculator lane + /api/state).

  M9  · the History table's DataList tools (search/sort/filter — all ON
        by the operator's 2026-07-25 directive) refine only the LOADED
        PAGE of a server-paged set, and nothing on screen said so — the
        scope lived in a source comment. The DataList primitive gained
        tools.scope; History passes 'loaded page only' and the toolbar
        carries the caption beside the count, title-expanded ("the
        server-side controls above the table span the full set").
  M7  · the Models upload lanes parse with the SELECTED Source app's
        adapter instead of hardcoding 'multicharts' four times. An app
        without a registered parser is REFUSED before uploading (named
        message listing what IS supported) rather than mis-parsed; the
        ImportModal's decorative one-option select became the real,
        controlled parser choice, its options exactly the registry.
        MDL_ADAPTERS (display → app_id) is a compile-time map pinned
        1:1 against core.backtest_adapters.list_backtest_adapters —
        mapping-with-parity-pin instead of a live endpoint because
        adapters are compiled-in (a new one ships in a release, and the
        parity pin fails that release's gate until the map learns it).
        The registry's list_backtest_adapters docstring says it was
        "shaped for the upload dropdown (task 3.4)" — the consumer that
        never came, until now.
  M11 · two of the three UI-less subsystems got their doors: the
        per-position SIGNED AUDIT EXPORT (JSON + PDF buttons on the
        History drilldown — restoring the parity the fragments
        slim-down deleted with the Jinja Export-Audit button) and the
        userTrades OFFLINE-TRADE RECOVERY (confirm-gated button on
        Config ▸ System, 180s deadline as a named deviation — a
        deliberate long job, not a poll). NAMED REMAINDERS, not
        oversights: the batch-ZIP export door stays UI-less; the
        BACKTEST RUNNER was parked here for the operator's call and
        RETIRED by their decision the same day (2026-08-04) — pins in
        tests/test_v27_phase6_retirement.

Run: pytest tests/test_med_tail_batch.py -v
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests._srcpin import code as _code  # noqa: E402

_ROOT = Path(__file__).parent.parent


def _src(name: str) -> str:
    return _code((_ROOT / "frontend" / "src" / name).read_text(encoding="utf-8"))


# ── M13: the Primitives badge stops denying the nav ─────────────────────────


class TestM13PrimitivesBadgeTruthful:
    def test_the_badge_no_longer_denies_the_nav(self):
        """Two-sided: NAV_ITEMS asserts Primitives IS in production nav
        (parsed, not assumed), so no executing string in app-shell may
        claim otherwise."""
        nav = _src("nav-and-data.jsx")
        m = re.search(r"const NAV_ITEMS = \[([^\]]*)\];", nav)
        assert m, "NAV_ITEMS literal not found"
        items = [s.strip().strip("'\"") for s in m.group(1).split(",")]
        assert "Primitives" in items, (
            "Primitives left production nav — if that was a deliberate "
            "reversal of the recorded keep-the-DEV-chip decision, the badge "
            "copy AND this pin change together"
        )
        assert "NOT IN PRODUCTION NAV" not in _src("app-shell.jsx")

    def test_the_badge_says_what_the_page_is(self):
        assert "DEV · DESIGN-SYSTEM REFERENCE · DEMO DATA" in _src("app-shell.jsx")


# ── M12: WorkspaceBar honest-disable, pinned (closed without code) ──────────


class TestM12WorkspaceBarHonestlyScoped:
    """The M12 filing ("WorkspaceBar is inert off the Dashboard") describes
    a state that is deliberate and already honestly labeled — see the
    module docstring. These pins hold the three legs of the honest
    disable together: the guard, the caption, and the single truthful
    interactive grant."""

    def test_controls_are_guarded_captioned_and_dashboard_granted(self):
        nav = _src("nav-and-data.jsx")
        assert nav.count("pointerEvents: interactive ? 'auto' : 'none'") == 2, (
            "the preset row + action row both carry the pointer guard"
        )
        assert ">· dashboard only</span>" in nav, (
            "the caption is the operator-visible half of the honest "
            "disable — dimming alone does not say WHY"
        )
        assert "interactive={page === 'Dashboard'}" in nav


# ── M5: the order-placement dd gate is gone; the real gate stays ────────────


class TestM5OrderGateRemoved:
    def test_the_dead_method_is_gone(self):
        """Executed + AST: no OrderManager attribute named
        check_dd_gate_for_order, and no call to it anywhere in executing
        prod code (api/ core/ main.py — comments excluded via AST)."""
        import ast

        from core.order_manager import OrderManager

        assert not hasattr(OrderManager, "check_dd_gate_for_order")
        hits = []
        for base in ("api", "core", "main.py"):
            p = _ROOT / base
            files = [p] if p.is_file() else sorted(p.rglob("*.py"))
            for f in files:
                tree = ast.parse(f.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if (isinstance(node, ast.Attribute)
                            and node.attr == "check_dd_gate_for_order") or (
                            isinstance(node, (ast.FunctionDef,
                                              ast.AsyncFunctionDef))
                            and node.name == "check_dd_gate_for_order"):
                        hits.append(str(f.relative_to(_ROOT)))
        assert hits == [], f"check_dd_gate_for_order reappeared: {hits}"

    def test_the_real_gate_is_still_consumed(self):
        """M5's justification must stay true: core/dd_gate remains THE
        gate — dd_gate_allows_new_entry is CALLED (AST) by the /api/state
        surface. If this dies, the removal's premise needs re-deciding,
        not re-pinning."""
        import ast

        src = (_ROOT / "api" / "routes_dashboard.py").read_text(
            encoding="utf-8")
        called = {
            node.func.attr if isinstance(node.func, ast.Attribute)
            else getattr(node.func, "id", None)
            for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.Call)
        }
        assert "dd_gate_allows_new_entry" in called


# ── M9: the page-scope of client-side table tools is SAID, not implied ──────


class TestM9PageScopeCaption:
    """History's table is server-paged; its DataList tools act on the rows
    in hand. That is the operator-ratified shape (tools LIFTED,
    2026-07-25) — the M9 defect was the SILENCE: the scope lived in a
    source comment while the operator saw a filter that 'found no
    matches' on rows sitting one page away. Both halves pinned: the
    primitive renders the caption, and the one server-paged caller
    passes it."""

    def test_the_primitive_renders_a_passed_scope(self):
        p = _src("primitives.jsx")
        # anchored on the JSX expression's OPENING BRACE — this pin's first
        # draft matched a substring that a `{false && toolsObj && …}` mutant
        # still contained (mutation-sweep finding, the recurring
        # substring-contains-mutant class)
        assert "{toolsObj && toolsObj.scope && (" in p
        assert "{false && toolsObj" not in p
        assert ">· {toolsObj.scope}</span>" in p
        # the caption's title carries a full-sentence explanation: the
        # caller-agnostic default, overridable per host via scopeTitle
        # (audit LOW: the first draft baked History's "controls above the
        # table" geography into the generic primitive)
        i = p.index("{toolsObj && toolsObj.scope && (")
        vicinity = p[i:i + 600]
        assert "toolsObj.scopeTitle" in vicinity
        assert ("Search, sort and filter here act only on the rows "
                "currently loaded.") in vicinity

    def test_history_passes_the_scope_on_its_paged_table(self):
        h = _src("pages-history.jsx")
        assert "scope: 'loaded page only'" in h
        # …with its host-specific hover sentence naming BOTH full-set
        # controls (the server filters above AND the pager below)
        assert "the pager below walks it." in h
        # …and the page-level summary strip carries the same qualifier
        # (audit LOW: the filing named the strip's silence too — a
        # page-level NET reads as period-level without it)
        assert "{ label: 'SCOPE', value: 'loaded page'" in h

    def test_no_other_paged_caller_is_silent(self):
        """Class sweep, DERIVED not enumerated: every module in
        frontend/src that renders the server-pager idiom must pass a
        tools.scope. (This pin's first draft hard-coded 4 files while the
        sibling completeness test maintains 9 DataList hosts — the
        audit-inventory-undercounts class, caught by the M9 audit. A glob
        cannot under-count.)"""
        hosts = []
        for f in sorted((_ROOT / "frontend" / "src").glob("*.jsx")):
            src = _code(f.read_text(encoding="utf-8"))
            if "page {page}/{totalPages}" in src:
                hosts.append(f.name)
                assert "scope: 'loaded page only'" in src, (
                    f"{f.name} renders a server pager without a DataList "
                    "scope caption (M9 / DESIGN.md usage rule)"
                )
        assert hosts == ["pages-history.jsx"], (
            f"server-pager hosts changed ({hosts}) — extend the M9 scope "
            "convention deliberately, don't just re-pin"
        )

    def test_the_caption_reaches_the_emitted_bundle(self):
        """Source is not what runs (the house stale-build guard — the M1
        audit filed the same gap on the bridge pin; the M9 audit filed it
        here)."""
        import json as _json

        man = _json.loads((_ROOT / "static" / "v3" / "manifest.json")
                          .read_text(encoding="utf-8"))
        bundle = (_ROOT / "static" / "v3" / man["app"]).read_text(
            encoding="utf-8")
        assert "qe-dl-scope" in bundle
        assert "loaded page only" in bundle
        tokens = (_ROOT / "static" / "v3" / man["tokens"]).read_text(
            encoding="utf-8")
        # selector + brace, not the bare name — a renamed `.qe-dl-scopex`
        # still CONTAINS the bare name (the session's recurring
        # substring-contains-mutant class, third instance)
        assert ".qe-dl-scope {" in tokens


# ── M7: uploads parse with the SELECTED app's adapter ───────────────────────


class TestM7AdapterWiring:
    """Four upload lanes hardcoded app_id='multicharts' whatever the
    operator's Source-app select said — a foreign report got chewed by
    the wrong parser while the model recorded the foreign source. Now
    every lane derives the adapter from the selection via MDL_ADAPTERS
    and REFUSES (named message) when none exists. The map is pinned 1:1
    against the live registry — both sides derived, neither assumed."""

    def _models(self):
        return _src("pages-models.jsx")

    def test_map_matches_the_registry_exactly(self):
        """Executed on the python side (the real registry, decorators
        fired), parsed on the JS side: same app_ids, same display names.
        A registered adapter the UI doesn't offer — or a UI offer no
        adapter backs — fails here by construction."""
        from core.backtest_adapters import list_backtest_adapters

        rows = list_backtest_adapters()
        registry = {r["display_name"]: r["app_id"] for r in rows}
        m = re.search(r"const MDL_ADAPTERS = \{([^}]*)\};", self._models())
        assert m, "MDL_ADAPTERS literal not found"
        js = dict(re.findall(r"'([^']+)':\s*'([^']+)'", m.group(1)))
        assert js == registry, (
            f"UI adapter map {js} != registry {registry} — a new adapter "
            "ships with its UI entry in the same release (M7 doctrine)"
        )

    def test_no_lane_hardcodes_the_parser(self):
        s = self._models()
        assert "fd.append('app_id', 'multicharts')" not in s, (
            "an upload lane hardcodes the parser again — the Source-app "
            "select is decoration on that lane (M7)"
        )
        assert s.count("fd.append('app_id', adapter)") == 4, (
            "expected exactly 4 derived-adapter upload lanes (form parse, "
            "form submit, import preview, import confirm)"
        )
        # the HELPER body too: `_mdlAdapterFor = () => 'multicharts'` would
        # re-create the defect while every wiring pin above stays green
        # (found while designing this class's own mutation sweep)
        assert ("const _mdlAdapterFor = (app) => "
                "MDL_ADAPTERS[(app || '').trim()] || null;") in s

    def test_every_lane_refuses_an_unparsable_app(self):
        """The guard precedes the upload in all four lanes: derive →
        refuse-with-named-message → only then busy/FormData."""
        s = self._models()
        assert s.count("const adapter = _mdlAdapterFor(") == 4
        # exactly the 4 refusal CALL sites (the definition is an arrow
        # assignment — `_mdlNoParserErr = (app)` — and doesn't match)
        assert s.count("_mdlNoParserErr(") == 4
        # the message names what IS supported, not just what isn't
        assert "imports currently support: " in s

    def test_import_modal_select_is_the_registry(self):
        """The one-option decorative select became a controlled choice
        whose options are exactly the adapter map's keys."""
        s = self._models()
        assert "{Object.keys(MDL_ADAPTERS).map((a) => <option key={a}>{a}</option>)}" in s
        assert "<option>MultiCharts</option>" not in s
        assert "value={srcApp} onChange={(e) => setSrcApp(e.target.value)}" in s

    def test_refusal_renders_locally_and_in_full(self):
        """Audit MED on this fix's first draft: the refusal Error fell
        through qeFootCause's transport checks to 'no network — engine
        unreachable' (false diagnosis) and the foot's 60-char slice cut
        the supported-apps remedy to 'Mult'. The refusal now carries
        `.local` and the foot renders local errors whole, transport
        errors through the cause channel."""
        s = self._models()
        assert "e.local = true;" in s
        # brace-anchored: `? (false && subErr.local` must not satisfy it
        assert "? (subErr.local" in s
        assert ("? { tone: 'err', msg: String(subErr.message || '') }"
                ) in s

    def test_lane_copy_names_every_supported_app(self):
        """Audit LOW: the form's import-section subtitle is hardcoded
        copy — pinned to the map so a second adapter fails this gate
        until the copy learns it (the registry-parity doctrine applied
        to prose)."""
        s = self._models()
        m = re.search(r"const MDL_ADAPTERS = \{([^}]*)\};", s)
        keys = re.findall(r"'([^']+)':", m.group(1))
        sub = re.search(r'title="Import Backtest Report" sub="([^"]*)"', s)
        assert sub, "import-section subtitle not found"
        for k in keys:
            assert k in sub.group(1), (
                f"the import subtitle no longer names {k} — hardcoded "
                "lane copy drifted from the adapter map"
            )

    def test_guard_precedes_the_upload_in_every_lane(self):
        """Audit LOW: order, not just count — a guard moved AFTER the
        FormData build would pass a count pin while uploading before
        refusing. Executed index math per lane slice."""
        s = self._models()
        lanes = [
            ("const doParse", "const errors"),
            ("} else if (parsed) {", "onSave({ kind: 'created+imported'"),
            ("const doPreview", "const doConfirm"),
            ("const doConfirm", "const foot"),
        ]
        for start, end in lanes:
            i = s.index(start)
            seg = s[i:s.index(end, i)]
            assert seg.index("_mdlNoParserErr(") < seg.index("new FormData()"), (
                f"lane starting {start!r}: the refusal guard no longer "
                "precedes the upload construction"
            )

    def test_the_wiring_reaches_the_emitted_bundle(self):
        import json as _json

        man = _json.loads((_ROOT / "static" / "v3" / "manifest.json")
                          .read_text(encoding="utf-8"))
        bundle = (_ROOT / "static" / "v3" / man["app"]).read_text(
            encoding="utf-8")
        assert 'fd.append("app_id", adapter)' in bundle
        assert 'fd.append("app_id", "multicharts")' not in bundle


# ── M11: the audit-export and offline-recovery doors ────────────────────────


class TestM11AuditExportDoor:
    """The signed per-position bundle (P7.4-7.6) lost its only UI when
    the slim-down deleted the Jinja Export-Audit button. Both sides
    pinned: the React drilldown POSTs the real door for both formats,
    and the door itself still answers (executed with the builder
    stubbed — no live DB)."""

    def test_drilldown_offers_both_formats_and_threads_fmt(self):
        h = _src("pages-history.jsx")
        assert "exportAudit('json')" in h
        assert "exportAudit('pdf')" in h
        # fmt is THREADED, not frozen — both buttons ride one lane
        assert "`/export/closed_position/${dp.id}?format=${fmt}`" in h
        assert ("`audit_closed_position_${dp.id}.${fmt === 'pdf' "
                "? 'pdf' : 'json'}`") in h
        # a failed export is SAID (the drilldown's own red line)…
        assert "audit export failed" in h
        # …with the TRUE cause: the thrown error is status-tagged like
        # _ptJson's, so a 404/500 the engine ANSWERED cannot render as
        # "no network — engine unreachable" (audit MED); and a stale
        # error never follows the operator to another position — both
        # exit paths clear it (audit LOW)
        assert "err.status = res.r.status" in h
        assert h.count("setExpErr(null)") >= 3  # export start + openDrill + ✕

    @pytest.mark.asyncio
    async def test_the_door_still_answers(self, monkeypatch):
        """Executed: 404 on a missing row; JSON attachment on a hit —
        the exact contract the React lane's r.ok + blob flow needs."""
        import api.routes_export as rex

        async def none_builder(db, cid):
            return None

        monkeypatch.setattr(rex, "build_closed_position_export", none_builder)
        r = await rex.export_closed_position(4242, fmt="json")
        assert r.status_code == 404

        async def stub_builder(db, cid):
            return {"closed_position_id": cid, "signature": "sig"}

        monkeypatch.setattr(rex, "build_closed_position_export", stub_builder)
        r = await rex.export_closed_position(7, fmt="json")
        assert r.status_code == 200
        assert "attachment" in r.headers.get("content-disposition", "")
        assert "audit_closed_position_7.json" in r.headers["content-disposition"]


class TestM11BackfillDoor:
    """POST /api/orders/backfill (the gap-scoped userTrades recovery that
    REPLACED the fee-inflating income reconstruction) had no door.
    Confirm-gated Config ▸ System button; the days window threads all
    the way to core.exchange_income."""

    def test_config_offers_the_confirm_gated_button(self):
        c = _src("pages-config.jsx")
        assert "`/api/orders/backfill?days=${bfDays}`" in c
        assert "Recover offline trades" in c
        # the confirm PRECEDES the busy/POST — executed index math, and the
        # guard's exact form (`if (!window.confirm(`) so a `false &&`
        # neutering can't keep the substring alive (the session's
        # substring-contains-mutant class)
        i = c.index("const doBackfill = async () => {")
        seg = c[i:c.index("setBfBusy(false);", i)]
        assert "if (!window.confirm(" in seg
        assert seg.index("window.confirm(") < seg.index("setBfBusy(true)")
        assert seg.index("setBfBusy(true)") < seg.index("_ptFetch(")
        # the result line counts ACTUAL recovered activity — the route
        # returns every error-free symbol in `recovered`, zeros included,
        # so a raw key-count always equals `symbols` and claims recovery
        # that never happened (audit MED)
        assert "typeof n === 'number' && n > 0" in seg
        assert "${active} with recovered rows" in seg
        # a 180s abort must not read as "engine not answering" — the
        # server job keeps running and that message invites a restart
        # mid-write (audit LOW)
        assert "may STILL be running" in seg
        # ternary-head anchored (`text: e && …`) — a `false &&` neutering
        # keeps the bare condition substring alive
        assert "text: e && e.timeoutMs != null" in seg

    @pytest.mark.asyncio
    async def test_the_door_threads_days_and_account(self, monkeypatch):
        """Executed against the real route handler with the recovery
        stubbed at its module (the handler imports it inside the body —
        the call-time-import seam)."""
        import core.exchange_income as xi
        from api.routes_orders import backfill_from_exchange_history
        from core.state import app_state

        seen = {}

        async def stub(*, account_id, days):
            seen["account_id"] = account_id
            seen["days"] = days
            return {"symbols": 0, "recovered": {}, "errors": {}}

        monkeypatch.setattr(xi, "recover_offline_trades", stub)
        r = await backfill_from_exchange_history(days=7)
        assert r.status_code == 200
        assert seen["days"] == 7, (
            "the days window no longer threads through — the UI select "
            "is decoration"
        )
        assert seen["account_id"] == app_state.active_account_id
