"""The v3 LOW/cosmetic tier batch (2026-08-05).

The tenth-block wiring inventory's Tier 3 was filed as "stubs presented as
controls + dead code — batch or drop whole". A 10-agent verification pass ran
each filed root to the line first, and the filing turned out to be wrong in
BOTH directions:

- Two filed items are NOT DEFECTS and must stay untouched: the ⊞ Pane / ⤢ Pop
  buttons are bare-`disabled` with honest titles, and the Desktop-notifications
  switch is the *outcome* of a prior audit + a recorded 2026-07-25 operator
  decision. Pinned here so a future "cleanup" cannot quietly delete a ratified
  planned-feature signal.
- The sweeps found real defects the filing never named — the ones fixed here
  are the toast/banner offset bug and the missing `.qe-btn:disabled` rule.

Shipped in the first pass: 2 fixes + 3 deletions (each with the doc/comment
truth edit the deletion makes mandatory). Then the operator took three of the
four lane-choices, shipped in a second pass and pinned below: the notification
CTA now really navigates, the workspace `+` is honestly disabled, and the demo
panel went — taking the whole client-side halt subsystem it was the last writer
of.

Deliberately NOT shipped: `asciiSpark` (present in the vendored Meridian
reference — removing it would widen the very port divergence the pending
reference audit exists to measure), and the `···` pane-overflow dots, which the
operator DEFERRED while deciding. Do not "clean up" the dots as part of a sweep.

The strongest pin here is the LAST one: it scans the EMITTED bundle (comments
stripped by esbuild) for the deleted identifiers, so a surviving caller is
caught even though a call to a missing name parses fine. That is not
hypothetical — deleting `nextHaltRelease` as "NotifBanner's helper" left a live
ReferenceError in pushEvent's halt branch during this very batch.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests._srcpin import code as _code  # noqa: E402

_ROOT = Path(__file__).parent.parent
_SRC = _ROOT / "frontend" / "src"


def _raw(name: str) -> str:
    return (_SRC / name).read_text(encoding="utf-8")


def _stripped(name: str) -> str:
    return _code(_raw(name))


_NOTIF = _stripped("notifications.jsx")
_SHELL = _stripped("app-shell.jsx")
_SSE = _stripped("sse-adapter.js")
_PRIM = _stripped("primitives.jsx")
_NAV = _stripped("nav-and-data.jsx")
_TOKENS = (_SRC / "tokens.css").read_text(encoding="utf-8")
_DESIGN = (_ROOT / "frontend" / "DESIGN.md").read_text(encoding="utf-8")


def test_strippers_are_not_vacuous():
    """C1's lesson: a truncated _code() makes every negative assertion below
    pass against an empty string. `/*` surviving the strip is the phantom-block
    tell; a POSITIVE marker per file proves we stripped the intended source and
    not something else. (No `//` assertion — several of these files carry `//`
    inside string literals, e.g. URLs, which the stripper correctly keeps.)"""
    # floors are per-file: sse-adapter.js is genuinely small (~60 lines of code
    # once the registry came out), so a shared 80 would fail honestly.
    # floors sit just under the real counts (audit #12: a floor of 200 let
    # app-shell lose 360 lines and still pass). None of these five files is
    # covered by test_react_port_dd_notes' string-delimiter guard, so a future
    # `'https://…'` literal could truncate a line here and quietly hollow out
    # the negative pins below — the markers are the backstop for that.
    for name, src, marker, floor in (
        ("notifications", _NOTIF, "NotificationProvider", 225),
        ("app-shell", _SHELL, "QE_PAGES", 520),
        ("sse-adapter", _SSE, "EventSource", 55),
        ("primitives", _PRIM, "const LiveValue", 1000),
        ("nav-and-data", _NAV, "ChromeHaltBanner", 350),
    ):
        assert len([ln for ln in src.splitlines() if ln.strip()]) > floor, name
        assert "/*" not in src, name
        assert marker in src, name


# ── FIX 1 — the .qe-btn:disabled rule ───────────────────────────────────────

class TestDisabledButtonsLookDisabled:
    """`.qe-btn` sets `cursor:pointer` + a background and had NO :disabled rule.
    CSS :hover matches disabled elements, so a disabled button LIT UP under the
    cursor and then swallowed the click — full-brightness Delete Account."""

    def test_the_rule_exists_and_kills_pointer_and_hover(self):
        m = re.search(r"\.qe-btn:disabled[^{]*\{([^}]*)\}", _TOKENS)
        assert m, ".qe-btn:disabled rule is gone"
        body = m.group(1)
        assert "cursor: not-allowed" in body
        assert "opacity: 0.45" in body

    def test_it_also_covers_the_hover_and_active_lanes(self):
        """Naming only `.qe-btn:disabled` leaves `.qe-btn:hover` free to repaint
        the background on a disabled button (equal specificity, later source)."""
        sel = _TOKENS[_TOKENS.index(".qe-btn:disabled"):_TOKENS.index(".qe-btn:disabled") + 200]
        assert ".qe-btn:disabled:hover" in sel
        assert ".qe-btn:disabled:active" in sel

    def test_it_is_declared_AFTER_hover_and_active(self):
        """Equal specificity (0,2,0 vs 0,2,0) → source order decides. Declared
        before :hover, the fix silently does nothing on hover. (The VARIANT
        hovers — .qe-btn-ghost:hover, .qe-btn-primary:hover — are declared
        after, and lose on specificity instead: :disabled:hover is (0,3,0).)"""
        assert _TOKENS.index(".qe-btn:hover") < _TOKENS.index(".qe-btn:disabled")
        assert _TOKENS.index(".qe-btn:active") < _TOKENS.index(".qe-btn:disabled")

    def test_ghost_buttons_stay_chromeless_when_disabled(self):
        """audit #8: the base rule is (0,2,0) and beats `.qe-btn-ghost`
        (0,1,0), so it painted a filled box onto ~16 disabled ghost buttons
        that are chromeless by design — a regression the fix introduced."""
        m = re.search(r"\.qe-btn-ghost:disabled[^{]*\{([^}]*)\}", _TOKENS)
        assert m, "the ghost carve-out is gone"
        assert "background: transparent" in m.group(1)
        assert "border-color: transparent" in m.group(1)
        assert _TOKENS.index(".qe-btn:disabled") < _TOKENS.index(".qe-btn-ghost:disabled")

    def test_the_rule_reaches_the_EMITTED_stylesheet(self):
        """audit #5: the JS half scans the emitted bundle precisely because
        source != shipped; the CSS half had no such pin, so "source fixed, not
        rebuilt" was green."""
        man = json.loads((_ROOT / "static" / "v3" / "manifest.json").read_text(encoding="utf-8"))
        css = (_ROOT / "static" / "v3" / man["tokens"]).read_text(encoding="utf-8")
        assert len(css) > 10_000, "emitted stylesheet looks truncated"
        # SELECTOR-BOUNDARY, not substring: `.qe-btn:disabled:active` contains
        # `.qe-btn:disabled`, so the plain `in` form stayed green while two of
        # the three selector lines were renamed away (mutation L28).
        assert re.search(r"\.qe-btn:disabled\s*[,{]", css)
        assert re.search(r"\.qe-btn:disabled:hover\s*[,{]", css)
        assert re.search(r"\.qe-btn-ghost:disabled\s*[,{]", css)


# ── FIX 2 — the toast offset follows the live banner count ──────────────────

class TestToastOffsetTracksLiveBanners:
    def test_toasts_use_navh_not_the_dead_banner_pair(self):
        # word-boundary, not prefix: `top: navH + 8` is a PREFIX of
        # `top: navH + 80`, and the audit defeated the substring form with
        # exactly that mutation while all 39 pins stayed green.
        assert re.search(r"top:\s*navH \+ 8\b", _NOTIF)
        assert "banner ? 92 : 62" not in _NOTIF

    def test_the_dead_banner_flag_is_gone_from_code_and_context(self):
        assert "const banner = haltUntil > now" not in _NOTIF
        ctx = re.search(r"const ctx = \{([^}]*)\}", _NOTIF)
        assert ctx and "banner" not in ctx.group(1)

    def test_the_banner_counter_covers_EVERY_banner_that_renders(self):
        """audit #1 — the fix's own defect: three Banner primitives render in
        the under-nav slot but qeChromeBannerCount summed only two, so with a
        foreign seat up the scrim dimmed (and the toast covered) the bottom
        31px of the seat banner — exactly where TAKE OVER and ✕ sit.
        Derived, not hardcoded: the render block and the counter are compared
        against each other, so adding a fourth banner without a counter arm
        fails here."""
        rendered = set(re.findall(r"<(\w+Banner)\s*/>", _NAV))
        assert rendered == {"ClockDriftBanner", "ChromeHaltBanner", "OperatorSeatBanner"}, rendered
        body = _NAV[_NAV.index("const qeChromeBannerCount"):]
        body = body[:body.index("\n};")]
        assert body.count("k += 1") == len(rendered), (
            f"{len(rendered)} banners render but the counter has "
            f"{body.count('k += 1')} arms")
        # each arm must mirror its banner's OWN render guard
        assert "clock_severity" in body and "st.halted || st.blocked" in body
        assert "seat.state === 'foreign' && !seat.dismissed" in body
        seat_guard = _NAV[_NAV.index("const OperatorSeatBanner"):]
        assert "s.state !== 'foreign' || s.dismissed" in seat_guard[:400]

    def test_navh_is_still_the_single_shared_source(self):
        """The scrim, the drawer and now the toasts must all read the SAME
        expression — a second offset constant is how they diverged before."""
        assert "const navH = 54 + 31 * (typeof qeChromeBannerCount === 'function' ? qeChromeBannerCount() : 0)" in _NOTIF
        assert _NOTIF.count("top:navH") + _NOTIF.count("top: navH") >= 3


# ── DELETION 1 — NotifBanner, and the helper that had to SURVIVE it ─────────

class TestNotifBannerClusterDeleted:
    @pytest.mark.parametrize("sym", ["NotifBanner", "HALT_GRASS", "fmtHaltLeft", "fmtHaltAt"])
    def test_symbol_is_gone(self, sym):
        assert sym not in _NOTIF

    def test_next_halt_release_went_WITH_its_caller_not_before_it(self):
        """The near-miss this batch made, recorded: `nextHaltRelease` LOOKS like
        one of NotifBanner's helpers, so the first pass deleted it — while
        pushEvent's halt branch still called it, leaving a ReferenceError the
        build cannot see (a call to a missing name parses fine). It was
        restored, then removed for real once item 4 deleted that caller. The
        repo's own precedent: remove a symbol WITH or AFTER its last consumer,
        never before. Both sides must now be absent together."""
        assert "nextHaltRelease" not in _NOTIF
        assert "pushEvent" not in _NOTIF

    def test_the_window_export_dropped_it(self):
        m = re.search(r"Object\.assign\(window, \{([^}]*)\}\)", _NOTIF)
        assert m and "NotifBanner" not in m.group(1)
        assert "NotificationProvider" in m.group(1)  # the live ones stay

    def test_the_stale_comment_naming_it_as_the_live_banner_is_corrected(self):
        """nav-and-data's clock-drift comment claimed NotifBanner was the halt
        banner sharing its slot — git-stale since 2026-07-25. A comment naming
        a deleted component sends the next author to the wrong banner."""
        raw = _raw("nav-and-data.jsx")
        i = raw.index("OS-clock-drift banner")
        seg = raw[i:i + 700]
        assert "ChromeHaltBanner" in seg
        assert "const ChromeHaltBanner" in raw  # the real one still exists


# ── DELETION 2 — the P0 page-placeholder factory ────────────────────────────

class TestPagePlaceholderDeleted:
    def test_the_factory_is_gone(self):
        assert "_PagePlaceholder" not in _SHELL
        assert "REACT PORT ·" not in _SHELL

    def test_every_route_binds_a_real_page_module(self):
        """The premise of the deletion. If this ever fails, a page regressed to
        a placeholder — a much bigger finding than dead code."""
        m = re.search(r"const QE_PAGES = \{(.*?)\n\};", _SHELL, re.S)
        assert m
        body = m.group(1)
        # audit #14: asserting the KEY appears would pass on `Dashboard:
        # undefined`. Pin the key→component BINDING, and that the component is
        # a real declared identifier in the bundle's scope.
        for page, comp in (("Dashboard", "DashTiled"), ("'Pre-Trade'", "PreTradePage"),
                           ("Linkage", "LinkagePage"), ("History", "HistoryPage"),
                           ("Analytics", "AnalyticsPage"), ("Models", "ModelsPage"),
                           ("Regime", "RegimePage"), ("Config", "ConfigPage"),
                           ("Primitives", "PrimitivesPage")):
            assert re.search(re.escape(page) + r":\s*" + comp + r"\b", body), page
        assert "Placeholder" not in body


# ── DELETION 3 — the never-written live-value registry ──────────────────────

class TestLiveValueRegistryDeleted:
    @pytest.mark.parametrize("sym", ["useLiveId", "useSSEChannel", "valSubs",
                                     "QE_SSE.getValue", "QE_SSE.onValue"])
    def test_registry_symbol_is_gone(self, sym):
        assert sym not in _SSE

    @pytest.mark.parametrize("sym", ["setValue", "getValue", "onValue", "values"])
    def test_the_registrys_CORE_symbols_are_gone(self, sym):
        """audit #3: `setValue` (the registry's only writer) and the `values`
        Map were in NO pin list — the audit re-added a working registry to
        sse-adapter.js and all 39 pins stayed green. Word-boundary + call/decl
        shape, because bare `setValue` also matches `gain.setValueAtTime`."""
        assert not re.search(r"\b" + sym + r"\s*[(:]", _SSE), f"{sym} is back"
        assert not re.search(r"\bconst " + sym + r"\b", _SSE)

    def test_the_real_binding_mechanism_survives(self):
        assert "onChannel(channel, fn)" in _SSE
        m = re.search(r"Object\.assign\(window, \{([^}]*)\}\)", _SSE)
        assert m and m.group(1).strip() == "QE_SSE"

    def test_the_LiveValue_PRIMITIVE_is_untouched(self):
        """Half (b) is very much alive (~30 call sites) and takes its value as a
        PROP — the data-live-id attribute is an htmx/OOB swap target, not a
        lookup into the deleted registry. Deleting it would have been the real
        damage."""
        assert "const LiveValue = ({id, value, format=String" in _PRIM
        assert "data-live-id={id}" in _PRIM
        dash = _stripped("dash-tiled.jsx")
        assert dash.count("<LiveValue") >= 5

    def test_design_md_no_longer_prescribes_the_deleted_hook(self):
        """A ratified rule instructing authors to call a deleted symbol is
        worse than the dead code it described."""
        assert "`window.QE_SSE` / `useLiveId`" not in _DESIGN
        assert "QE_SSE.onChannel" in _DESIGN


# ── THE NOT-DEFECTS — verified at the line, pinned so nobody "fixes" them ───

class TestVerifiedNotDefectsStayUntouched:
    def test_pane_and_pop_stay_disabled_and_honest(self):
        """Filed as "stubs presented as controls"; refuted at the line. They are
        bare-`disabled`, handler-less, honestly titled, and no underlying
        capability exists. primitives.jsx ratifies preserving the
        planned-feature signal, so deleting them is the defect. (Their inline
        dim was later removed — `.qe-btn:disabled` owns that now.)"""
        # STRIPPED source: the glyphs also appear in a prose comment above the
        # bar, and matching that one proved nothing about the rendered button.
        for glyph in ("⊞ Pane", "⤢ Pop"):
            i = _NAV.index(glyph)
            btn = _NAV[_NAV.rindex("<button", 0, i):i]
            assert "disabled" in btn, glyph
            assert "title=" in btn, glyph
            assert "onClick" not in btn, glyph

    def test_desktop_switch_stays_disabled_with_its_recorded_rationale(self):
        raw = _raw("notifications.jsx")
        i = raw.index('NotifSwitch label="Desktop"')
        seg = raw[i:i + 200]
        assert "on={false} disabled" in seg
        assert "deferred" in seg
        assert "2026-07-25" in raw  # the operator decision is still recorded

    def test_ascii_spark_is_deliberately_kept(self):
        """Swept up as dead, but it is a catalogued atom of the vendored
        Meridian reference — deleting it widens the port divergence the pending
        reference audit exists to measure. Resolve there, not as cleanup."""
        # anchored through the param list: a bare `const asciiSpark` prefix is
        # satisfied by `const asciiSparkGONE` (substring-contains-mutant class —
        # this pin survived exactly that mutation on the first harness run).
        assert "const asciiSpark = (vals) =>" in _PRIM
        assert re.search(r"\basciiSpark,\s*ASCII_SPARK\b", _PRIM), "dropped from the window export"
        ref = _ROOT / "docs" / "design" / "meridian_v3" / "v25" / "src" / "primitives.jsx"
        assert "asciiSpark" in ref.read_text(encoding="utf-8")


# ── ITEM 2 — the notification CTA actually navigates ────────────────────────

class TestNotificationCtaNavigates:
    """It used to mark read, close the drawer, fire a toast reading
    "→ Review risk / risk panel" — and then go NOWHERE. On a risk console a
    control that REPORTS success it did not achieve is worse than one that
    visibly does nothing."""

    _PAGES = {"Dashboard", "Pre-Trade", "Linkage", "History", "Analytics",
              "Models", "Regime", "Config", "Primitives"}

    def test_every_action_target_is_a_REAL_page(self):
        """Derived against app-shell's router, not a hardcoded list: a typo or
        a renamed page turns the CTA back into a no-op (qeNav silently ignores
        an unknown key — `if (QE_PAGES[p]) setPage(p)`)."""
        m = re.search(r"const N_ACTIONS = \{(.*?)\n\};", _NOTIF, re.S)
        assert m, "N_ACTIONS is gone"
        targets = re.findall(r"\[\s*'[^']+',\s*'([^']+)'\s*\]", m.group(1))
        assert len(targets) == 4, targets
        routes = set(re.findall(r"^\s*'?([\w-]+)'?:\s*\w+Page\b|^\s*(\w+):\s*DashTiled\b",
                                _SHELL[_SHELL.index("const QE_PAGES"):], re.M))
        declared = {a or b for a, b in routes}
        for t in targets:
            assert t in self._PAGES, f"{t} is not a page"
            assert t in declared, f"{t} is not bound in QE_PAGES"

    def test_the_handler_calls_qenav_and_claims_nothing_otherwise(self):
        i = _NOTIF.index("const handleAction")
        body = _NOTIF[i:_NOTIF.index("\n  const markAll", i)]
        assert "window.qeNav(entry[1])" in body
        assert "if (!entry) return;" in body      # no destination → no action
        assert "actionToast" not in _NOTIF         # the fake confirmation is gone

    def test_a_channel_without_a_destination_renders_no_button(self):
        """The old `(N_ACTIONS[ev.ch]||['View'])[0]` armed a button for ANY
        channel, including ones with nowhere to go."""
        i = _NOTIF.index("const NotifRow")
        row = _NOTIF[i:_NOTIF.index("\nconst ", i + 10)]
        assert "onAction && N_ACTIONS[ev.ch] &&" in row
        assert "||['View']" not in row and "|| ['View']" not in row


# ── ITEM 3 — the workspace + tells the truth ────────────────────────────────

class TestWorkspacePlusIsHonest:
    def test_it_is_disabled_and_says_why(self):
        """It called the SAME reset as the `Default` preset while labelled
        "New workspace from default" — a misleading label AND a duplicate."""
        i = _NAV.index(">+<")
        btn = _NAV[_NAV.rindex("<button", 0, i):i]
        assert "disabled" in btn
        assert "not implemented" in btn
        assert "onClick" not in btn

    def test_the_misleading_handler_is_gone(self):
        assert "onCreate" not in _NAV
        # the reset it duplicated is still reachable, correctly labelled
        assert "if (p === 'Default') { window.qeWorkspaceReset(persistId)" in _NAV

    def test_disabled_buttons_use_ONE_CURSOR_convention_repo_wide(self):
        """audit #9 + #6: ⊞ Pane / ⤢ Pop carried inline `cursor:'default'`
        while every other disabled .qe-btn shows `not-allowed`.

        Scoped honestly to the CURSOR, which IS uniform. Two lanes exist and
        both are correct: `.qe-btn:disabled { cursor: not-allowed }` for
        buttons, and an explicit `disabled?'not-allowed':'pointer'` on the
        non-button controls (Switch is a <div>). The banned value is the third
        one — a hardcoded `'default'`, which reads as "inert decoration" on a
        control that is merely temporarily off.

        (Opacity is NOT uniform — five buttons in analytics/linkage carry an
        inline opacity overriding the rule's .45. Harmless, since it cannot
        touch the cursor, and out of this batch's scope; asserting uniformity
        there would be a false claim. NB a `<button…>` regex is unreliable in
        JSX — attribute expressions contain `>` — so this scans for the banned
        VALUE, not for tag boundaries.)"""
        for name in ("nav-and-data.jsx", "notifications.jsx", "app-shell.jsx",
                     "pages-analytics.jsx", "pages-linkage.jsx", "pages-config.jsx",
                     "pages-history.jsx", "pages-models.jsx", "dash-tiled.jsx",
                     "primitives.jsx"):
            src = _stripped(name)
            assert not re.search(r"cursor:\s*'default'", src), f"{name}: 'default' cursor"
        # the non-button lane is intact
        assert "cursor: disabled?'not-allowed':'pointer'" in _PRIM

    def test_the_two_placeholder_buttons_carry_no_inline_style_at_all(self):
        """The half of the change the cursor scan alone does not pin: the
        audit restored `style={{opacity: 0.4}}` on ⊞ Pane and all 86 pins
        stayed green."""
        for glyph in ("⊞ Pane", "⤢ Pop"):
            i = _NAV.index(glyph)
            btn = _NAV[_NAV.rindex("<button", 0, i):i]
            assert "style=" not in btn, glyph


# ── ITEM 4 — the demo panel and the halt subsystem it stranded ──────────────

class TestDemoAndClientHaltSubsystemDeleted:
    @pytest.mark.parametrize("sym", [
        "NotifDemo", "pushEvent", "autostream", "demoOpen", "N_SCENARIOS",
        "N_STREAM", "nextHaltRelease", "readHaltUntil", "readHaltAt",
        "haltUntil", "haltAt", "HALT_KEY", "HALT_AT_KEY", "toggleDesktop",
        "idRef",   # the client id minter — audit #1, missed by my own sweep
    ])
    def test_symbol_is_gone(self, sym):
        assert sym not in _NOTIF

    def test_no_client_side_halt_copy_survives_even_on_the_DEV_page(self):
        """The Primitives Banner swatch rendered the SAME fabricated hard-stop
        wording item 4 deleted. Dev-only, so not an operator-facing lie — but
        the page is the design system's spec sheet, and it was advertising copy
        the architecture has ruled out."""
        assert not re.search(r"CALCULATOR\s+BLOCKED", _SHELL, re.I)
        assert "hard-stop 5.04%" not in _SHELL
        assert "EXAMPLE · halt banner" in _SHELL

    def test_the_provider_takes_no_demo_prop(self):
        assert "function NotificationProvider({ children })" in _NOTIF

    def test_no_fabricated_risk_or_halt_payload_survives(self):
        """The halt template read 'CALCULATOR BLOCKED — hard-stop breached'.
        Fabricated RISK/HALT copy in a shipped risk console is a liability even
        behind a flag — it is exactly what an operator screenshots in a panic.

        STRUCTURAL, not exact-copy: the audit defeated the first draft by
        re-adding the same fabrication with one hyphen dropped
        ('hard stop breached'), and `Math.random()` was simultaneously
        over-broad (a future poll jitter/backoff would false-red) and
        under-broad (a hardcoded fabrication needs no RNG). Pin the SHAPE
        instead: no event-like literal may carry halt/risk copy, and no
        module-level template table may exist."""
        assert not re.search(r"hard[\s\-—]?stop\s+breached", _NOTIF, re.I)
        assert not re.search(r"CALCULATOR\s+BLOCKED", _NOTIF, re.I)
        # no object literal in this file may mint an event with a priority —
        # only the server-fed poll() builds events now, from `n.pri`
        for m in re.finditer(r"pri:\s*'(\w+)'", _NOTIF):
            assert m.group(1) not in ("halt", "risk"), m.group(0)
        assert "Math.random" not in _NOTIF   # no RNG feeds the feed at all

    def test_halt_is_server_state_only(self):
        """The client can no longer decide, persist, or disagree about halt."""
        assert "localStorage" not in _NOTIF
        assert "const ChromeHaltBanner" in _NAV
        assert "st.halted" in _NAV

    def test_the_deferred_desktop_switch_still_stands(self):
        """Deleting the demo removed `desktop`'s only reader — but the SWITCH
        is a recorded operator decision and must survive the cleanup."""
        raw = _raw("notifications.jsx")
        i = raw.index('NotifSwitch label="Desktop"')
        assert "on={false} disabled" in raw[i:i + 200]
        assert "2026-07-25" in raw

    def test_the_real_feed_is_untouched(self):
        """The whole point: the demo went, the live poll stayed."""
        assert "'/notifications/poll?since='" in _NOTIF
        assert "nBeep(ev.pri)" in _NOTIF


# ── THE EXECUTED PIN — no dangling reference survives in the SHIPPED bundle ──

class TestNoDanglingReferencesInTheEmittedBundle:
    """esbuild strips comments, so a hit in the bundle is REAL CODE. This is the
    pin that would have caught the nextHaltRelease near-miss: a call to a
    deleted name parses fine and only explodes at runtime."""

    # audit #4: bare `getValue`/`onValue` over a 712 KB bundle would fail on any
    # unrelated future `getValue()` in any of the 23 modules. Each entry is a
    # word-boundary REGEX, and the registry members carry their call/property
    # shape so `gain.setValueAtTime` cannot be mistaken for `setValue`.
    _DELETED = [r"\buseLiveId\b", r"\buseSSEChannel\b", r"\bNotifBanner\b",
                r"\b_?PagePlaceholder\b", r"\bHALT_GRASS\b", r"\bfmtHaltLeft\b",
                r"\bfmtHaltAt\b", r"\bvalSubs\b",
                r"\bsetValue\s*\(", r"\bgetValue\s*\(", r"\bonValue\s*\(",
                # items 2-4
                r"\bNotifDemo\b", r"\bpushEvent\b", r"\bautostream\b",
                r"\bdemoOpen\b", r"\bN_SCENARIOS\b", r"\bN_STREAM\b",
                r"\bnextHaltRelease\b", r"\breadHaltUntil\b", r"\breadHaltAt\b",
                r"\bhaltUntil\b", r"\bhaltAt\b", r"\bHALT_KEY\b",
                r"\btoggleDesktop\b", r"\bactionToast\b", r"\bonCreate\b",
                r"\bidRef\b"]

    @pytest.fixture(scope="class")
    def bundle(self):
        man = json.loads((_ROOT / "static" / "v3" / "manifest.json").read_text(encoding="utf-8"))
        text = (_ROOT / "static" / "v3" / man["app"]).read_text(encoding="utf-8")
        assert len(text) > 100_000, "bundle looks truncated — every pin below would pass vacuously"
        assert "LOW batch" not in text, "comments are NOT stripped; these pins would read comments as code"
        return text

    @pytest.mark.parametrize("sym", _DELETED)
    def test_deleted_symbol_has_zero_code_references(self, bundle, sym):
        hits = re.findall(sym, bundle)
        assert hits == [], f"{sym} still referenced in the shipped bundle"

    def test_surviving_symbols_are_actually_in_the_bundle(self, bundle):
        """Guards the pin itself: if the bundle were some unrelated file, every
        assertion above would pass for the wrong reason."""
        # (`nextHaltRelease` was pinned here at exactly 2 — declaration + its
        #  live caller — until item 4 deleted the demo panel that called it and
        #  the whole client halt subsystem with it; it is now in _DELETED.)
        assert "onChannel" in bundle
        assert "LiveValue" in bundle
        assert "qeNav" in bundle          # the CTA's real destination (item 2)
        assert "N_ACTIONS" in bundle
        assert "nBeep" in bundle          # the real feed's cue survived item 4
