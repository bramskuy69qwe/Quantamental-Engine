"""The WorkspaceBar strip must not paint risk numbers off a dead source.

Found by the adversarial review of the service-worker CRIT (C1) as the SAME
operator-visible symptom reached by a completely different root: with the
service worker entirely innocent, killing the engine left the top-of-screen
strip showing `DD 2.41% · EXP 3.10× · OPEN 4/6` and three P&L cells as current,
indefinitely. Only LAT degraded, because LAT alone routed through `_navFeed`.

Mechanism: `chrome-live.js:37-38` deliberately keeps the last-good payload on a
failed poll and raises only a per-source err flag — "the flags carry the
degradation" (chrome-live.js:15-18). Two consumers already honour that contract
and say so in their own comments (`_navFeed` "Checked FIRST, before the
last-good payload is read"; `_navUserWs` "Same stateErr-first rule"). The strip
and the footer's uptime cell read the payload directly instead.

The rule these pins encode, stated once so it stops being re-derived per
consumer: ANY consumer of QE_CHROME must consult its source's err flag BEFORE
reading that source's last-good payload.

DELIBERATE ASYMMETRY, pinned below so a future sweep does not "fix" it:
READINGS dash out, WARNINGS do not. `ChromeHaltBanner` and `ClockDriftBanner`
keep rendering off last-good state on purpose — a halt banner is a warning, not
a reading, and hiding it because its source went quiet is precisely the failure
`shell-chrome-1` refuses ("an entry gate the operator cannot see is the failure
mode this exists to prevent"). So a dead engine blanks the numbers while any
standing halt stays on screen.

Run: pytest tests/test_nav_strip_stale_guard.py -v
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
_NAV = _code((_ROOT / "frontend" / "src" / "nav-and-data.jsx").read_text(encoding="utf-8"))
_CHROME = _code((_ROOT / "frontend" / "src" / "chrome-live.js").read_text(encoding="utf-8"))


def _strip_items() -> str:
    """The WorkspaceBar strip's item-builder IIFE.

    Ends at the IIFE's own closing token, not at the label of the unrelated
    disabled button that used to follow it — renaming that button must not
    silently move this boundary (and a cell placed after it must not escape
    every pin in the file).
    """
    start = _NAV.index("<Strip dense items={(() => {")
    end = _NAV.index("})()} />", start)
    seg = _NAV[start:end]
    assert "return [" in seg and "label: 'DD'" in seg, "strip slice lost its body"
    return seg


def _status_footer() -> str:
    start = _NAV.index("const StatusFooter")
    seg = _NAV[start:_NAV.index("● sse", start)]
    assert "uptime" in seg and "engineTone" in seg, "footer slice lost its body"
    return seg


def _payload_read(seg: str, source: str) -> int:
    """Position of a read of ch.<source> that is NOT the err flag.

    `ch.stateErr` CONTAINS `ch.state`, so a plain .index() for the payload finds
    the GUARD and every ordering assertion compares a position with itself. That
    is not hypothetical — the first draft of this file did exactly that and
    passed on 128 < 128.
    """
    m = re.search(rf"ch\.{source}(?!Err)", seg)
    assert m, f"no read of ch.{source} found in this region"
    return m.start()


def _guard_shape(seg: str, source: str) -> re.Match | None:
    """The exact `const <name> = ch.<x>Err ? null : ch.<x>;` BINDING.

    Ordering alone does NOT encode the fix: an INVERTED guard
    (`ch.stateErr ? ch.state : null` — blank when healthy, stale when erred,
    i.e. the reported bug reversed) satisfies every ordering assertion. The
    adversarial review proved that by mutation.

    Anchored to the whole assignment, not just the ternary, because a ternary
    match alone still passes when the guard is smothered by an always-true
    condition in front of it (`const st = true ? null : ch.stateErr ? null :
    ch.state`) — a permanently blank strip. Found by mutation on the first
    strengthened draft of this helper.
    """
    return re.search(
        rf"const \w+ = ch\.{source}Err \? null : ch\.{source};", seg)


# ── 0. the stripper is not vacuous (C1's lesson, applied here) ──────────────

class TestStripperIsNotVacuous:
    """Both files are read through `_srcpin.code()`, and a single unterminated
    `/*` inside a `//` comment truncates it to nothing — which would make every
    negative pin below pass against an empty string. C1 shipped exactly that
    bug in static/service-worker.js; guard the precondition, don't assume it."""

    @pytest.mark.parametrize("name,text", [("nav-and-data", _NAV), ("chrome-live", _CHROME)])
    def test_stripped_source_is_substantial(self, name, text):
        assert len([ln for ln in text.splitlines() if ln.strip()]) > 40, name

    @pytest.mark.parametrize("name,text", [("nav-and-data", _NAV), ("chrome-live", _CHROME)])
    def test_no_comment_residue(self, name, text):
        assert "//" not in text and "/*" not in text, name


# ── 1. the contract this file defends still holds upstream ──────────────────

class TestStoreStillKeepsLastGood:
    """These pins are only necessary because the store keeps last-good data. If
    that ever changes to null-on-error, the consumer guards become belt-and-
    braces rather than load-bearing — and this file should be revisited, not
    silently left asserting a rule with no teeth."""

    def test_the_three_err_flags_exist(self):
        for flag in ("stateErr", "snapErr", "sysErr"):
            assert flag in _CHROME, flag

    def test_a_failed_poll_flags_without_clearing_the_payload(self):
        i = _CHROME.index("const poll =")
        body = _CHROME[i:_CHROME.index("poll('/api/state'", i)]
        catch = body[body.index("catch"):]
        assert "st[errKey] = true" in catch
        assert "st[key] = null" not in catch, (
            "the store now clears the payload on error — re-evaluate whether "
            "the consumer-side guards in this file are still the mechanism"
        )


# ── 2. the strip: err flag before payload, for BOTH sources ─────────────────

class TestWorkspaceStripDegrades:
    @pytest.mark.parametrize("source", ["state", "snap"])
    def test_the_guard_has_the_right_SHAPE_not_just_the_right_order(self, source):
        """The load-bearing pin. Ordering assertions alone are satisfied by an
        INVERTED guard — `ch.stateErr ? ch.state : null`, blank when healthy and
        stale when erred — which is the reported bug reversed. Mutation-proven
        by the adversarial review: that inversion passed all six of this file's
        original source pins, leaving one literal bundle substring as the whole
        semantic guarantee."""
        assert _guard_shape(_strip_items(), source), (
            f"the ch.{source}Err guard is missing or has the wrong shape; it "
            f"must be exactly `ch.{source}Err ? null : ch.{source}` — an "
            f"inverted or weakened ternary satisfies every ordering pin"
        )

    @pytest.mark.parametrize("source", ["state", "snap"])
    def test_guard_precedes_the_payload_read(self, source):
        """Mirrors test_meridian_med_fixes' _navFeed pin."""
        seg = _strip_items()
        assert f"ch.{source}Err" in seg, f"the strip never consults {source}Err"
        assert seg.index(f"ch.{source}Err") < _payload_read(seg, source), (
            "the err branch must precede reading the last-good payload "
            "(the _navFeed / _navUserWs rule)"
        )

    @pytest.mark.parametrize("source", ["state", "snap"])
    def test_the_payload_is_read_EXACTLY_ONCE(self, source):
        """The pins above only constrain the FIRST read. A second raw
        `ch.state` taken anywhere below the guarded binding reintroduces the
        exact reported bug with every other pin green — so pin the count, which
        makes 'derives from the guarded binding' true by construction rather
        than by inspection of the cells alone."""
        seg = _strip_items()
        reads = re.findall(rf"ch\.{source}(?!Err)", seg)
        assert len(reads) == 1, (
            f"ch.{source} is read {len(reads)} times in the strip; exactly one "
            f"read — the guarded binding — is allowed, everything else must "
            f"derive from it"
        )

    def test_the_ordering_helper_is_not_self_satisfying(self):
        """Guards the guard: prove `_payload_read` finds the PAYLOAD and not the
        err-flag that shares its prefix, or the pins above are tautologies."""
        probe = "if (ch.stateErr) {} const st = ch.state;"
        assert _payload_read(probe, "state") > probe.index("ch.stateErr")
        assert _payload_read(probe, "state") == probe.rindex("ch.state")
        with pytest.raises(AssertionError):
            _payload_read("if (ch.stateErr) {}", "state")

    def test_the_shape_helper_rejects_every_near_miss(self):
        """Guards the guard, part 2 — _guard_shape must actually discriminate.
        Each rejection below is a mutant that survived an earlier draft."""
        assert _guard_shape("const st = ch.stateErr ? null : ch.state;", "state")
        # inverted: stale when erred, blank when healthy
        assert not _guard_shape("const st = ch.stateErr ? ch.state : null;", "state")
        # guard removed entirely
        assert not _guard_shape("const st = ch.state;", "state")
        # guard smothered by an always-true condition — permanently blank
        assert not _guard_shape(
            "const st = true ? null : ch.stateErr ? null : ch.state;", "state")

    def test_healthy_sources_still_render_real_values(self):
        """No pin previously asserted the TRUTHY branch produces anything, so a
        permanently-blank strip (`const st = null`) passed. Assert each risk
        cell still formats a live value."""
        cells = _strip_items()[_strip_items().index("return ["):]
        assert "st.position_count" in cells, "OPEN lost its live value"
        assert "st.total_exposure" in cells, "EXP lost its live value"
        assert "st.drawdown" in cells, "DD lost its live value"
        for pct in ("dPct", "wPct", "mPct"):
            assert pct in cells, f"a P&L cell lost its live value ({pct})"

    @pytest.mark.parametrize("label", ["OPEN", "EXP", "DD", "P&L·D", "P&L·W", "P&L·M"])
    def test_every_risk_cell_is_still_rendered(self, label):
        """Guard against 'fixing' staleness by deleting the readout."""
        assert label in _strip_items(), label

    def test_dd_limit_colouring_keys_off_the_guarded_binding(self):
        """The DD cell paints red at limit and amber at warning. Keyed off a
        stale dd_state it would keep flying a limit colour on a dead engine —
        louder than a stale number, and the same lie."""
        seg = _strip_items()
        dd = seg[seg.index("label: 'DD'"):]
        dd = dd[:dd.index("},")]
        assert "dd_state" in dd, dd
        # The whole cell sits in the truthy branch of the guarded binding, so
        # the limit/warning colours are unreachable once the source is dead.
        gate = dd.index("value: st ?")
        assert gate < dd.index("dd_state"), dd
        assert dd.rstrip().endswith("stDash"), dd
        assert "ch.state" not in dd, dd

    def test_lat_still_routes_through_the_reducer(self):
        """LAT was the one cell that already degraded; it must keep doing so
        through _navFeed rather than being folded into the new guard."""
        seg = _strip_items()
        assert "_navFeed(ch)" in seg, (
            "_navFeed takes the WHOLE store (it does its own stateErr check) — "
            "passing it the guarded binding would break it"
        )


# ── 2b. tier 3 owes the CAUSE, not just the blank ──────────────────────────

class TestTheBlankNamesItsCause:
    """DESIGN.md:266 — "no data → tier 3 (err, cause DISPLAYED)". Tier 2
    ("· showing last data") is not reachable from this strip: it lives in a
    pane FOOT and the strip has none, which is why _navFeed and _navUserWs are
    tier 3 as well. So the blank must say why, exactly as they do.

    Without this, a dead engine is indistinguishable from a flat account: '—'
    already means "no reading yet" everywhere in this app
    (chrome-live.js:15-18). The first draft of this fix blanked without a cause
    and the adversarial review caught it against this very rule.
    """

    def test_the_helper_exists_and_names_the_failing_source(self):
        i = _NAV.index("const _navStaleDash")
        body = _NAV[i:i + 400]
        assert "title=" in body, "a tier-3 blank must carry its cause"
        assert "${source}" in body or "source" in body, (
            "the cause must name WHICH source is down, not just say 'error'"
        )

    def test_both_strip_sources_get_a_named_blank(self):
        seg = _strip_items()
        assert "_navStaleDash('/api/state')" in seg
        assert "_navStaleDash('/api/dashboard/snapshot')" in seg

    def test_the_cause_is_only_stamped_when_the_flag_is_raised(self):
        """A first-load '—' must stay unexplained — claiming the engine is
        unreachable before the first poll has returned would be its own lie."""
        seg = _strip_items()
        for src, flag in (("stDash", "ch.stateErr"), ("snapDash", "ch.snapErr")):
            m = re.search(rf"const {src} = ([^;]+);", seg)
            assert m, src
            assert m.group(1).strip().startswith(flag + " ?"), m.group(1)

    @pytest.mark.parametrize("label", ["REGIME", "P&L·D", "P&L·W", "P&L·M", "OPEN", "EXP", "DD"])
    def test_every_blankable_cell_routes_through_a_named_blank(self, label):
        seg = _strip_items()
        cell = seg[seg.index(f"label: '{label}'"):]
        cell = cell[:cell.index("},")]
        assert "Dash" in cell, (
            f"the {label} cell still falls back to a bare '—' with no cause"
        )


# ── 3. the footer's uptime cell — same class, found by re-grepping ──────────

class TestFooterUptimeDegrades:
    """Not in the original report. Found by sweeping every reader of the store
    rather than fixing only the cell that was named — the house
    'audit lists under-count' rule."""

    def test_the_sys_guard_has_the_right_shape(self):
        """Same inversion hazard as the strip's two guards."""
        assert _guard_shape(_status_footer(), "sys"), (
            "the sysErr guard is missing or inverted; it must be exactly "
            "`ch.sysErr ? null : ch.sys`"
        )

    def test_sys_guard_precedes_the_payload_read(self):
        """Compared against the PAYLOAD read, not against the label text
        'uptime' — the original version of this pin compared the flag to a
        string that has nothing to do with the binding, so it never tied the
        two together at all."""
        seg = _status_footer()
        assert seg.index("ch.sysErr") < _payload_read(seg, "sys")

    def test_the_sys_payload_is_read_exactly_once(self):
        """`ch.sysErr` CONTAINS `ch.sys`, so the earlier bare-substring version
        of this pin could never have failed."""
        seg = _status_footer()
        assert len(re.findall(r"ch\.sys(?!Err)", seg)) == 1, (
            "the uptime cell reads ch.sys directly, bypassing the guard"
        )

    def test_engine_dot_still_keys_on_stateerr(self):
        assert "ch.stateErr ? 'var(--qe-red)'" in _status_footer()


# ── 4. warnings deliberately do NOT degrade ────────────────────────────────

class TestWarningsSurviveADeadSource:
    """The asymmetry is intentional. Pinned so a future 'consistency' sweep has
    to read this rationale before flattening it."""

    def test_halt_banner_is_not_SUPPRESSED_by_a_dead_source(self):
        """Pins the behaviour (the banner still appears), NOT the absence of the
        token — so marking a stale halt as stale, which is strictly better than
        either extreme, stays available. What must never return is an early-out
        that hides the banner because /api/state went quiet."""
        i = _NAV.index("const ChromeHaltBanner")
        body = _NAV[i:_NAV.index("const ClockDriftBanner")]
        assert "st.halted" in body and "st.blocked" in body
        assert not re.search(r"if \([^)]*stateErr[^)]*\) return null", body), (
            "the halt banner now hides itself when /api/state stops responding. "
            "A halt is a WARNING, not a reading — suppressing it because the "
            "source went quiet is the failure shell-chrome-1 refuses ('an entry "
            "gate the operator cannot see'). Marking it stale is fine; hiding "
            "it is not."
        )

    def test_clock_drift_banner_is_not_suppressed_by_a_dead_source(self):
        i = _NAV.index("const ClockDriftBanner")
        body = _NAV[i:_NAV.index("const TopNavStd")]
        assert "clock_severity" in body
        assert not re.search(r"if \([^)]*stateErr[^)]*\) return null", body)

    def test_banner_count_agrees_with_the_banners_it_counts(self):
        """The scrim offset is derived from this count, so count and render must
        agree about staleness or the drawer covers a visible banner — the exact
        bug shell-chrome-4 records fixing.

        Asserted as AGREEMENT between the two, not as a bare absence over an
        unvalidated slice: the earlier version passed vacuously if a
        declaration reorder emptied the slice, and passed even when the desync
        it is named for was present.
        """
        i = _NAV.index("const qeChromeBannerCount")
        count_body = _NAV[i:_NAV.index("const ChromeHaltBanner")]
        assert "clock_severity" in count_body and "halted" in count_body, (
            "the banner-count slice lost its body — this pin would otherwise "
            "pass against nothing"
        )
        halt_body = _NAV[_NAV.index("const ChromeHaltBanner"):_NAV.index("const TopNavStd")]
        assert ("stateErr" in count_body) == ("stateErr" in halt_body), (
            "banner COUNT and banner RENDER disagree about staleness — the "
            "layout offset will desync from what is on screen"
        )


# ── 5. it reaches the shipped bundle ───────────────────────────────────────

class TestReachesTheBundle:
    """House idiom (tests/test_p5r2_user_ws.py:256-263): a source-only pin goes
    green on a stale build, and the operator runs the BUNDLE."""

    def test_guards_are_present_in_the_emitted_bundle(self):
        man = json.loads((_ROOT / "static" / "v3" / "manifest.json").read_text(encoding="utf-8"))
        bundle = (_ROOT / "static" / "v3" / man["app"]).read_text(encoding="utf-8")
        # esbuild may reformat spacing; normalise before matching.
        flat = re.sub(r"\s+", "", bundle)
        for guard in ("ch.stateErr?null:ch.state",
                      "ch.snapErr?null:ch.snap",
                      "ch.sysErr?null:ch.sys"):
            assert guard.replace(" ", "") in flat, (
                f"{guard} exists in source but not in the emitted bundle — "
                f"rebuild frontend/ (npm run build)"
            )
