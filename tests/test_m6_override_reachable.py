"""M6 — the Override control is reachable in the fail-closed halt lane.

THE DEFECT (wiring inventory 2026-07-30, fixed 2026-08-04): when dd_gate
fails closed because account settings are unreadable, the engine is hard-
halted and the Pre-Trade banner says "override via Dashboard" — but the
Dashboard hid the Override button in exactly that lane.

★ THE FILED MECHANISM WAS WRONG (re-investigation discipline; the wrong
version also lived in dash-tiled's own comment). Filed: "the fail-closed
lane halts with dd_state != 'limit'; the route would reject it, so no
button." Investigated, each at the line and EXECUTED below:

  · dd_gate fail-closes only INSIDE dd_state == 'limit' — the settings read
    sits after the `!= limit → allowed` early-return.
  · the override check sits BEFORE the settings read, so an override
    genuinely un-halts the fail-closed lane.
  · the route's only state guard is `dd_state != 'limit'` — it ACCEPTS the
    fail-closed lane. It reads no enforcement mode at all.
  · what actually hid the button: /api/state deliberately reports
    dd_enforcement_mode 'unknown' when settings are unreadable ('advisory'
    would contradict the halt — its own P1 audit note), and the UI gate was
    `enforced` alone.

FIX: `canOverride = limit && st.halted` — keyed on THE TRUE BLOCK, not a
mode sentinel. The first shape (`enforced || modeUnknown`) was corrected by
the audit's second pass: /api/state makes TWO independent settings reads
which can disagree under exactly this lane's DB stress, and the sentinel arm
was wrong in both disagreement cells. Known-advisory keeps NO button for
free (dd_gate allows entries there, so halted is false). Same lane, same
pane: the DD badge keys HALTED on st.halted (old `enforced && limit` showed
LIMIT during a fail-closed halt and kept HALTED after an override), and the
mode chip gained a MODE UNKNOWN arm (it rendered ADVISORY there).

NOT frontend-only after the audit: the fallback DD lane in core/data_cache
never cleared `dd_manually_unblocked` on recovery — the discard lived only
in the rolling branch, unreachable exactly when settings are unreadable —
so an override taken in this lane would have outlived recovery and silently
bypassed the NEXT readable+enforced limit episode. Plugged; and the internal
`dd_gate_settings_unreadable` token is now translated at both Pre-Trade
render sites instead of shown verbatim.

Run: pytest tests/test_m6_override_reachable.py -v
"""
from __future__ import annotations

import inspect
import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests._srcpin import code as _code  # noqa: E402

_ROOT = Path(__file__).parent.parent
_DASH = _code((_ROOT / "frontend" / "src" / "dash-tiled.jsx").read_text(encoding="utf-8"))
_PT = _code((_ROOT / "frontend" / "src" / "pages-pretrade.jsx").read_text(encoding="utf-8"))


# ── the backend premises, EXECUTED ──────────────────────────────────────────

class TestDdGatePremises:
    """The button in the 'unknown' lane is only honest because of two facts
    about dd_gate. Both executed against the real function with the real
    app_state (monkeypatch-restored), not grepped."""

    @pytest.fixture
    def limit_state(self, monkeypatch):
        from core.state import app_state
        monkeypatch.setattr(app_state.portfolio, "dd_state", "limit")
        return app_state

    def test_fail_closed_blocks_inside_limit(self, limit_state, monkeypatch):
        """The fail-closed lane EXISTS and carries dd_state == 'limit' — the
        filed claim that it halts with dd_state != 'limit' is disproven by
        running it."""
        import core.db_account_settings as s
        import core.dd_gate as g

        def boom(_aid):
            raise RuntimeError("settings unreadable")

        monkeypatch.setattr(s, "get_account_settings", boom)
        monkeypatch.setattr(limit_state, "dd_manually_unblocked", set())
        allowed, reason = g.dd_gate_allows_new_entry(1)
        assert allowed is False
        assert reason == "dd_gate_settings_unreadable"

    def test_the_override_cures_the_fail_closed_lane(self, limit_state, monkeypatch):
        """THE load-bearing premise: the override check precedes the settings
        read, so the button the fix un-hides actually DOES something. If this
        ordering ever flips, the button becomes a lie — the operator types a
        reason, gets a 200, and stays halted."""
        import core.db_account_settings as s
        import core.dd_gate as g

        def boom(_aid):
            raise RuntimeError("settings unreadable")

        monkeypatch.setattr(s, "get_account_settings", boom)
        monkeypatch.setattr(limit_state, "dd_manually_unblocked", {1})
        allowed, reason = g.dd_gate_allows_new_entry(1)
        assert (allowed, reason) == (True, None), (
            "dd_gate no longer honours the override before the settings read "
            "— the fail-closed lane cannot be un-halted and the Dashboard "
            "button (plus the Pre-Trade 'override via Dashboard' copy) lies"
        )

    def test_outside_limit_the_settings_are_never_read(self, monkeypatch):
        """The other half of the mechanism correction: no fail-closed halt can
        exist outside dd_state == 'limit', because the read never happens."""
        from core.state import app_state
        import core.db_account_settings as s
        import core.dd_gate as g
        monkeypatch.setattr(app_state.portfolio, "dd_state", "ok")
        calls = []

        def spy(aid):
            calls.append(aid)
            raise RuntimeError("should never be reached")

        monkeypatch.setattr(s, "get_account_settings", spy)
        assert g.dd_gate_allows_new_entry(1) == (True, None)
        assert calls == [], "the settings read moved above the limit gate"


class TestRoutePremises:
    def _route(self) -> str:
        from api.routes_accounts import dd_override
        return inspect.getsource(dd_override)

    def test_the_route_accepts_the_fail_closed_lane(self):
        """Its only state guard is dd_state != 'limit', which the fail-closed
        lane satisfies. It must NOT grow an enforcement-mode guard — that
        would silently strand the 'unknown' lane's button behind 400s (every
        dialog failure is shown, but the operator can do nothing about it)."""
        src = self._route()
        assert 'if pf.dd_state != "limit":' in src
        assert "dd_enforcement_mode" not in src, (
            "the override route now reads the enforcement mode — re-decide "
            "the 'unknown'-lane button in the same commit"
        )

    def test_state_reports_unknown_when_settings_unreadable(self):
        """The UI's modeUnknown arm keys on this exact sentinel."""
        src = (_ROOT / "api" / "routes_dashboard.py").read_text(encoding="utf-8")
        assert re.search(r'dd_mode = wk_mode = "unknown"', src), (
            "/api/state no longer reports 'unknown' for unreadable settings — "
            "the Dashboard's modeUnknown arm went blind; find the new "
            "sentinel and rewire canOverride with it"
        )


# ── the UI ──────────────────────────────────────────────────────────────────

class TestOverrideReachable:
    def test_the_gate_keys_on_the_true_block(self):
        """The audit's second pass: /api/state makes TWO independent settings
        reads (dd_gate's + the mode read) which can disagree under exactly
        this lane's DB stress. A mode-sentinel arm was wrong in both
        disagreement cells (no button while hard-halted / a button while
        nothing gates); `st.halted` derives from dd_gate itself and is right
        in every cell — the same key-on-the-true-block principle as the
        badge."""
        assert "const canOverride = ddState === 'limit' && !!st.halted;" in _DASH, (
            "the override gate no longer keys on the true block — re-check "
            "every cell of the (dd_state × two-settings-reads × overridden) "
            "matrix before shipping whatever replaced it"
        )

    def test_known_advisory_still_offers_no_button(self):
        """The deliberate half survives the halted key for free: in
        known-advisory dd_gate allows entries, so halted is false and no
        button renders — an override would persist an approval for nothing."""
        assert "&& !!st.halted;" in _DASH
        assert "st.dd_enforcement_mode !== 'advisory'" not in _DASH

    def test_the_corrected_mechanism_is_recorded_at_the_site(self):
        """Re-investigation discipline: the WRONG filed mechanism lived in
        this very comment block; the correction must too, or the next reader
        re-derives the filing."""
        assert "THE FILED MECHANISM WAS WRONG" in _code(
            (_ROOT / "frontend" / "src" / "dash-tiled.jsx").read_text(encoding="utf-8")
        ) or "FILED MECHANISM WAS WRONG" in (
            (_ROOT / "frontend" / "src" / "dash-tiled.jsx").read_text(encoding="utf-8")
        )

    def test_the_mode_chip_has_a_third_arm(self):
        """Audit: mode 'unknown' rendered as ADVISORY (info tone) beside a red
        HALTED badge and a live Override button — in the one lane where the
        mode is genuinely unreadable."""
        assert "modeUnknown ? 'warn' : 'info'" in _DASH
        assert "modeUnknown ? 'MODE UNKNOWN' : 'ADVISORY'" in _DASH

    def test_the_override_leak_is_plugged_in_the_fallback_lane(self):
        """Audit MED-HIGH: the discard lived only in the rolling branch —
        unreachable exactly when settings are unreadable — so an override
        taken in the M6 lane survived recovery and leaked into a later
        readable+enforced episode: a silent gate bypass. The fallback now
        mirrors the leaving-limit clearing and keeps dd_previous_states."""
        src = (_ROOT / "core" / "data_cache.py").read_text(encoding="utf-8")
        i = src.index("# Fallback: legacy intraday logic")
        seg = src[i:i + 2400]
        for frag in ('if _prev == "limit" and pf.dd_state != "limit":',
                     "app_state.dd_manually_unblocked.discard(_aid)",
                     "app_state.dd_previous_states[_aid] = pf.dd_state"):
            assert frag in seg, (
                f"`{frag}` left the fallback lane — an override taken during "
                f"a fail-closed halt outlives recovery and bypasses the NEXT "
                f"enforced episode"
            )

    def test_the_internal_halt_token_is_translated_for_the_operator(self):
        """Audit LOW: the fail-closed banner read the literal
        `dd_gate_settings_unreadable`. Both render sites route through the
        map; every other dd_gate reason is already a sentence."""
        assert "const _ptHaltReason = (st) => (" in _PT
        assert "risk settings unreadable — engine failed closed" in _PT
        assert _PT.count("_ptHaltReason(st)") >= 2
        assert "(st.halt_reason || 'drawdown limit breached')" not in _PT

    def test_the_badge_keys_on_the_true_block(self):
        m = re.search(
            r"<Badge tone=\{st\.halted \? 'err' : _stateTone\(ddState\)\}>"
            r"\{st\.halted \? 'HALTED' : _stateLabel\(ddState\)\}</Badge>", _DASH)
        assert m, (
            "the DD badge no longer keys HALTED on st.halted — the old "
            "`enforced && limit` derivation showed LIMIT during a fail-closed "
            "halt and kept HALTED after an override un-blocked entries"
        )

    def test_the_pretrade_pointer_still_points_here(self):
        """The two sides of M6: the banner copy that sends the operator to the
        Dashboard, and the button that must exist when they arrive."""
        assert "override via Dashboard" in _PT
        assert "a manual override lives on the Dashboard" in _PT


# ── it reaches the shipped bundle ───────────────────────────────────────────

def test_the_fix_reaches_the_emitted_bundle():
    man = json.loads((_ROOT / "static" / "v3" / "manifest.json").read_text(encoding="utf-8"))
    flat = re.sub(r"\s+", "", (_ROOT / "static" / "v3" / man["app"]).read_text(encoding="utf-8"))
    for token in (
        'constmodeUnknown=st.dd_enforcement_mode==="unknown"',
        'ddState==="limit"&&!!st.halted',
        'st.halted?"HALTED":_stateLabel(ddState)',
        'modeUnknown?"MODEUNKNOWN":"ADVISORY"',
        "risksettingsunreadable",   # the operator translation (whitespace-flattened)
    ):
        assert token in flat, (
            f"`{token}` exists in source but not in the emitted bundle — "
            f"rebuild frontend/ (node build.mjs)"
        )
