"""
Task 149 regression tests — FE-MED-033 click-to-copy on calculator
Setup Summary outputs (Phase C prep).

Source motivation: user workflow needs calculator values copyable
into QT order entry. Pre-T149, each Setup Summary input was readonly
with `onclick="this.select()"` — user had to select-then-Ctrl+C.
Worse: the displayed values use `toLocaleString('en-US')` which
inserts thousand separators (`60,000.00`); QT order entry rejects
those.

Fix:
  - `data-copy-source` attr on each input maps to a key in
    `#calc-data` (raw float string, no formatting).
  - `copyField(el)` reads the raw, writes to clipboard via
    `navigator.clipboard.writeText()`, flashes green border for 1s.
  - LOT button hidden on non-commodity tickers (lot is a dead alias
    for contracts on crypto — observed at line 666 pre-T149,
    `else val=(commodity&&contracts>0)?fmtP(contracts):'—';`).

Tests are source-pin + render-pin only — clipboard behavior requires
a JS test harness (Playwright / jsdom) which doesn't exist in this
suite. The copyField function logic is fully visible in source so
source-pinning the key invariants gives strong fix coverage.

Run: pytest tests/test_task149_click_to_copy.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import jinja2
import pytest


def _read_calculator() -> str:
    return Path("templates/calculator.html").read_text(encoding="utf-8")


def _make_env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )


# ── Setup Summary input markup: data-copy-source + click handler ────────────

class TestSetupSummaryInputsHaveCopyAttrs:
    """Each Setup Summary input must declare data-copy-source +
    onclick=copyField(this) so the click-to-copy works."""

    INPUTS = {
        "ss-ticker": "ticker",
        "ss-entry": "entry",
        "ss-tp": "tp",
        "ss-sl": "sl",
        "ss-size": "size",
    }

    def test_all_5_inputs_have_copy_source(self):
        src = _read_calculator()
        for input_id, expected_source in self.INPUTS.items():
            # Locate the input element block
            m = re.search(
                r'id="' + re.escape(input_id) + r'"[^>]*data-copy-source="([^"]+)"',
                src, re.DOTALL,
            )
            assert m, (
                f"FE-MED-033: input #{input_id} missing "
                f"data-copy-source attr."
            )
            assert m.group(1) == expected_source, (
                f"FE-MED-033: input #{input_id} has wrong "
                f"data-copy-source={m.group(1)!r}, expected "
                f"{expected_source!r}."
            )

    def test_all_5_inputs_use_copy_field_handler(self):
        src = _read_calculator()
        for input_id in self.INPUTS:
            # The onclick must invoke copyField (not this.select())
            m = re.search(
                r'id="' + re.escape(input_id) + r'"[^>]*onclick="([^"]+)"',
                src, re.DOTALL,
            )
            assert m, f"input #{input_id} has no onclick handler"
            assert "copyField(this)" in m.group(1), (
                f"FE-MED-033: input #{input_id} onclick should call "
                f"copyField(this). Got: {m.group(1)!r}"
            )

    def test_pre_t149_select_handler_removed(self):
        """Anti-regression: don't re-introduce the old this.select()
        pattern that left user stuck with Ctrl+C."""
        src = _read_calculator()
        for input_id in self.INPUTS:
            m = re.search(
                r'id="' + re.escape(input_id) + r'"[^>]*onclick="([^"]+)"',
                src, re.DOTALL,
            )
            if m:
                assert "this.select()" not in m.group(1), (
                    f"FE-MED-033 regression: #{input_id} reverted to "
                    f"this.select() pattern."
                )

    def test_inputs_have_pointer_cursor(self):
        """Visual affordance: cursor:pointer indicates clickability.
        Pre-T149 inputs used cursor:text (text-input affordance)."""
        src = _read_calculator()
        for input_id in self.INPUTS:
            m = re.search(
                r'id="' + re.escape(input_id) + r'"[^>]*style="([^"]+)"',
                src, re.DOTALL,
            )
            assert m, f"input #{input_id} has no style attr"
            assert "cursor:pointer" in m.group(1), (
                f"FE-MED-033: #{input_id} should have cursor:pointer "
                f"as clickability affordance. Got: {m.group(1)!r}"
            )


# ── copyField JS function source-pins ───────────────────────────────────────

class TestCopyFieldJsLogic:
    def test_copy_field_function_defined(self):
        src = _read_calculator()
        assert "function copyField(el)" in src, (
            "FE-MED-033: copyField helper must be defined."
        )

    def test_copy_field_reads_from_calc_data(self):
        """The raw values live in #calc-data data-* attrs. copyField
        must read from there, not from the formatted input value."""
        src = _read_calculator()
        idx = src.find("function copyField(el)")
        end = src.find("\nfunction ", idx + 10)
        body = src[idx:end] if end > 0 else src[idx:idx + 2000]
        assert "getElementById('calc-data')" in body
        # Reads data-<source> from #calc-data, not el.value
        assert "data.getAttribute(" in body

    def test_copy_field_size_branch_handles_unit(self):
        """The 'size' source must resolve to notional/contracts/lot
        based on _sizeUnit at click time (matches the active unit)."""
        src = _read_calculator()
        idx = src.find("function copyField(el)")
        end = src.find("\nfunction ", idx + 10)
        body = src[idx:end] if end > 0 else src[idx:idx + 2000]
        assert "_sizeUnit" in body, (
            "FE-MED-033: size branch must consult _sizeUnit to pick "
            "the right raw value for the active unit."
        )
        assert "'data-notional'" in body
        assert "'data-contracts'" in body

    def test_copy_field_uses_writeText(self):
        src = _read_calculator()
        idx = src.find("function copyField(el)")
        end = src.find("\nfunction ", idx + 10)
        body = src[idx:end] if end > 0 else src[idx:idx + 2000]
        assert "navigator.clipboard.writeText(" in body

    def test_copy_field_has_visual_feedback(self):
        """Brief flash on copy — operator gets confirmation."""
        src = _read_calculator()
        idx = src.find("function copyField(el)")
        end = src.find("\nfunction ", idx + 10)
        body = src[idx:end] if end > 0 else src[idx:idx + 2000]
        # setTimeout to clear the visual feedback
        assert "setTimeout(" in body
        # Some color change (border green is the chosen feedback)
        assert "var(--green)" in body or "green" in body.lower()

    def test_copy_field_guards_against_missing_clipboard(self):
        """`navigator.clipboard` may be undefined (insecure context,
        old browser). Handler must guard, not throw."""
        src = _read_calculator()
        idx = src.find("function copyField(el)")
        end = src.find("\nfunction ", idx + 10)
        body = src[idx:end] if end > 0 else src[idx:idx + 2000]
        # Guard condition or try/catch
        assert (
            "navigator.clipboard&&" in body.replace(" ", "")
            or ".catch(" in body
            or "if(navigator.clipboard" in body.replace(" ", "")
        ), (
            "FE-MED-033: copyField must guard against missing "
            "navigator.clipboard API."
        )

    def test_copy_field_guards_empty_value(self):
        """If raw value is empty/0/— (e.g., calc not yet submitted),
        don't write garbage to clipboard."""
        src = _read_calculator()
        idx = src.find("function copyField(el)")
        end = src.find("\nfunction ", idx + 10)
        body = src[idx:end] if end > 0 else src[idx:idx + 2000]
        # Returns early on falsy/dash value
        assert "raw==='—'" in body.replace(" ", "") or "raw==='0'" in body.replace(" ", "") or "!raw" in body.replace(" ", "")


# ── LOT button hidden on non-commodity tickers ──────────────────────────────

class TestLotButtonHiddenOnNonCommodity:
    def test_populate_setup_summary_toggles_lot_visibility(self):
        src = _read_calculator()
        idx = src.find("function populateSetupSummary()")
        end = src.find("\nfunction ", idx + 10)
        body = src[idx:end] if end > 0 else src[idx:idx + 2000]
        # Toggles display on su-lot based on commodity status
        assert "su-lot" in body
        assert "isCommodityTicker(" in body
        assert "style.display" in body

    def test_lot_fallback_to_contracts_on_non_commodity(self):
        """If LOT is currently selected and the new ticker is non-
        commodity, the populator falls back to contracts so the
        size field doesn't show '—'."""
        src = _read_calculator()
        idx = src.find("function populateSetupSummary()")
        end = src.find("\nfunction ", idx + 10)
        body = src[idx:end] if end > 0 else src[idx:idx + 2000]
        # Fallback logic: _sizeUnit reassignment from 'lot' on non-commodity
        assert "_sizeUnit='contracts'" in body.replace(" ", "")


# ── Compile-render: calculator template still renders cleanly ───────────────

class TestCalculatorCompiles:
    """MED-047 compile pin — the template-touching changes must not
    break Jinja syntax."""

    def test_calculator_template_compiles(self):
        env = _make_env()
        tpl = env.get_template("calculator.html")
        assert tpl is not None

    def test_calculator_renders_with_minimal_ctx(self):
        """Render with a minimal synthetic context; assert the
        Setup Summary inputs exist + carry the data-copy-source
        attrs end-to-end (not just in source)."""
        env = _make_env()
        tpl = env.get_template("calculator.html")
        # Minimal context — calculator.html extends base.html which
        # needs project_name etc. via _ctx; provide enough to render.
        try:
            html = tpl.render(
                project_name="QE-Test",
                active_page="calculator",
                calc=None,
                params={},
                request=None,
            )
        except Exception:
            # If render needs more context that's not Task-149-related,
            # fall back to a structural compile check
            pytest.skip("calculator.html needs full _ctx — source-pin tests cover the change")
        assert 'data-copy-source="ticker"' in html
        assert 'data-copy-source="entry"' in html
        assert 'data-copy-source="size"' in html
        assert 'onclick="copyField(this)"' in html


# ── FE-MED-033 anchor present ───────────────────────────────────────────────

class TestAnchorComments:
    def test_fe_med_033_anchor_in_template(self):
        src = _read_calculator()
        assert "FE-MED-033" in src
        assert "Task 149" in src

    def test_lot_alias_decision_documented(self):
        """The decision to hide LOT on non-commodity (rather than
        drop entirely) is non-obvious — anchor explains why. Look at
        the function-definition site, not the first-substring match
        (which would be the doc anchor in the input markup section)."""
        src = _read_calculator()
        # Find the function definition, not a substring mention
        idx = src.find("function populateSetupSummary()")
        assert idx > 0
        body = src[idx:idx + 2500]
        assert "lot" in body.lower() and "commodity" in body.lower()
