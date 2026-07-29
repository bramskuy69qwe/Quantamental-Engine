"""E2E-P6-003 pins — link/unplanned confirm uses ModelDialog, not window.confirm.

Operator report (2026-07-29, Phase-6 L2 re-run): "i can click link (manual link
pane) but i cant accept it cause the dialog glitches very fast. also its not
standardized as it should like in the primitives."

Both halves were right:
 * a NATIVE `window.confirm` is intercepted by any browser-automation layer, so
   it vanished before it could be accepted — the manual-link flow was
   undrivable end-to-end;
 * the sibling calc-cancel flow already used the shipped `ModelDialog`
   primitive, so link/unplanned were off-standard (unstyleable, no scrim, no ✕,
   none of the dialog conventions in DESIGN.md).

Also pinned here: E2E-P6-002's DISPLAY half. A Binance MARKET order carries
price = 0, so the resolver rendered "MARKET @ 0.000000", a 0 notional, and an
empty ORDER cell in MatchDiff's Entry row. `_lkEntryPx` resolves price-first
with avg_fill_price as the fallback, mirroring the backend finder.

Source-level pins (the emitted bundle is asserted too, so a stale build fails).
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LINKAGE = (ROOT / "frontend" / "src" / "pages-linkage.jsx").read_text(encoding="utf-8")
PRIMS = (ROOT / "frontend" / "src" / "link-primitives.jsx").read_text(encoding="utf-8")


def _emitted_bundle() -> str:
    manifest = json.loads((ROOT / "static" / "v3" / "manifest.json").read_text(encoding="utf-8"))
    app = next(v for k, v in manifest.items() if str(v).endswith(".js") or k == "app")
    name = app if isinstance(app, str) else app.get("file", "")
    return (ROOT / "static" / "v3" / Path(name).name).read_text(encoding="utf-8", errors="replace")


class TestConfirmDialogIsThePrimitive:
    def test_no_window_confirm_in_linkage(self):
        # Match the CALL, not the word: the source comments name window.confirm
        # to explain what was replaced, which a bare substring check would flag.
        assert "window.confirm(" not in LINKAGE, (
            "native confirm is off-standard AND undrivable under automation — "
            "use the ModelDialog primitive like the calc-cancel flow"
        )

    def test_confirm_state_drives_a_modeldialog(self):
        assert "confirmKind" in LINKAGE, "the confirm is a rendered dialog, not a blocking call"
        # the dialog block must reference the primitive and both actions
        assert re.search(r"confirmKind\s*&&\s*\(\s*<ModelDialog", LINKAGE), \
            "confirmKind must render a ModelDialog"
        assert "Mark UNPLANNED" in LINKAGE and "Link calc" in LINKAGE

    def test_dialog_is_dismissable_without_acting(self):
        assert "Keep as is" in LINKAGE, "needs a non-destructive dismiss, like 'Keep calc'"
        assert "onClose={() => { if (!busy) setConfirmKind(null); }}" in LINKAGE

    def test_action_runs_only_from_the_dialog(self):
        """`act` opens the dialog; `runAct` performs the mutation."""
        assert "const act = (kind) => setConfirmKind(kind);" in LINKAGE
        assert "const runAct = async (kind)" in LINKAGE
        assert "manual_link" in LINKAGE and "mark_unplanned" in LINKAGE


class TestMarketEntryPriceDisplay:
    def test_helper_is_price_first_with_fill_fallback(self):
        assert "_lkEntryPx" in PRIMS
        assert "(o && (o.price || o.avg_fill_price)) || null" in PRIMS, (
            "limit orders keep their own price; the fill is the fallback"
        )

    @pytest.mark.parametrize("site", ["MatchDiff Entry row", "resolver KV", "inbox strip"])
    def test_no_raw_price_render_remains(self, site):
        assert "lpPx(order.price)" not in PRIMS, "MatchDiff must use the resolved entry"
        assert "lpPx(item.price)" not in LINKAGE, "strip/KV must use the resolved entry"


class TestEmittedBundleCarriesTheFix:
    def test_bundle_has_the_dialog_and_helper(self):
        js = _emitted_bundle()
        assert "_lkEntryPx" in js, "stale build — rebuild frontend (npm run build)"
        assert "Keep as is" in js
        assert "window.confirm" not in js or "confirmKind" in js
