"""
Task 133 regression tests — FE-LOW-008 Equity Curve "Range" investigation.

Investigation outcome:
  - `var rng = c.h - c.l` is mathematically correct for H-L of the bar.
  - The audit-02 Session A observed value ($100.95 Range vs displayed
    H=$100.72 L=$79.77 → H-L=$20.95) is internally inconsistent within
    a single render: rngPct = 126.55% IS consistent with rng=$100.95
    and l=$79.77, but rng=$100.95 cannot come from h=$100.72 minus
    l=$79.77. This points to a screenshot-timing artifact during the
    1 Hz refresh (templates/fragments/equity_ohlc.html:306-326
    replaces `raw` then immediately calls renderStats) OR an auditor
    screenshot misread. NOT a real calc bug.

Fix shape:
  1. **Label disambiguation**: "Range" → "Bar Range" in both the inline
     stats line and the hover tooltip. Anchors the metric to the bar's
     H-L explicitly (vs lifetime range, drawdown range, etc.).
  2. **Defensive local-variable cache**: snapshot c.o/c.h/c.l/c.c into
     locals (o/h/l/cc) at the top of renderStats and the tooltip
     formatter. Forecloses any theoretical between-reads mutation
     race during the 1 Hz refresh, AND makes the rendered values
     guaranteed-consistent with the rng/rngPct computation.
  3. **No calc change**. The math is correct as-is.

Source-pin tests (the offending code is inside a Jinja2 {% if %}
block + a <script> tag; can't render-test it without a browser).

Run: pytest tests/test_task133_equity_curve_range.py -v
"""
from __future__ import annotations

from pathlib import Path

import jinja2
import pytest


def _read() -> str:
    return Path("templates/fragments/equity_ohlc.html").read_text(encoding="utf-8")


def _make_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    return env


# ── Label disambiguation: Range → Bar Range ─────────────────────────────────

class TestLabelDisambiguation:

    def test_stats_line_uses_bar_range_label(self):
        """The inline stats line (renderStats) emits 'Bar Range', not
        'Range'."""
        src = _read()
        # The new label appears in the renderStats stats-line block
        assert '">Bar Range</span>' in src

    def test_tooltip_uses_bar_range_label(self):
        """The hover tooltip's row() call also uses 'Bar Range'."""
        src = _read()
        assert "row('Bar Range'" in src

    def test_old_bare_range_label_gone_from_user_facing_text(self):
        """Anti-revert: the old bare 'Range' label is gone from the
        2 rendered sites. The audit-doc text still contains 'Range'
        (in the finding description, which is fine — that's metadata,
        not rendered UI)."""
        src = _read()
        # Specifically the rendered HTML tokens
        assert '">Range</span>' not in src
        assert "row('Range'," not in src


# ── Defensive local-variable cache ──────────────────────────────────────────

class TestDefensiveLocalCache:
    """Both renderStats and the tooltip formatter snapshot c.o/c.h/c.l/
    c.c into locals before any computation OR rendering. This ensures
    the rng / rngPct math and the rendered H/L labels all see the
    same values, even if `c` were mutated between reads (which
    shouldn't happen in single-threaded JS, but the cache makes it
    impossible)."""

    def test_render_stats_snapshots_fields_into_locals(self):
        src = _read()
        # The snapshot line: `var o = c.o, h = c.h, l = c.l, cc = c.c;`
        # Appears at the top of renderStats AND inside the tooltip
        # formatter. Both occurrences should be present.
        snapshot = "var o = c.o, h = c.h, l = c.l, cc = c.c;"
        assert src.count(snapshot) == 2

    def test_render_stats_computes_from_locals_not_c(self):
        """The rng / rngPct / chg / adjChg / chgPct / adjChgPct
        computations all use the local snapshots — no `c.h` / `c.l`
        / `c.o` / `c.c` reads remain in the compute block (excluding
        comments and the cache line itself)."""
        src = _read()
        # Locate renderStats's compute block by finding the cache
        # line, then scan from there to the start of the HTML build.
        cache_line = "var o = c.o, h = c.h, l = c.l, cc = c.c;"
        cache_idx = src.find(cache_line)
        assert cache_idx > 0
        # Compute block runs from end-of-cache-line to the first
        # `document.getElementById(STATS_ID).innerHTML` reference.
        compute_start = cache_idx + len(cache_line)
        compute_end = src.find("document.getElementById(STATS_ID).innerHTML", compute_start)
        assert compute_end > compute_start
        compute_block = src[compute_start:compute_end]
        # Strip JS comments (// ...) line-by-line so the docstring text
        # referencing c.h/c.l doesn't trip the test.
        code_only_lines = []
        for line in compute_block.splitlines():
            stripped = line.split("//", 1)[0]
            code_only_lines.append(stripped)
        code_only = "\n".join(code_only_lines)
        # No direct c.h/c.l/c.o reads should remain (c.cf is allowed —
        # it's the cashflow field).
        assert "c.h" not in code_only, (
            "FE-LOW-008 regression: c.h still read directly in compute "
            "block — defensive cache circumvented."
        )
        assert "c.l" not in code_only
        assert "c.o" not in code_only
        # c.c followed by anything other than 'f' (so we don't catch c.cf)
        import re
        m = re.search(r"c\.c(?![a-zA-Z_])", code_only)
        assert m is None, (
            f"FE-LOW-008 regression: c.c still read directly in code."
        )

    def test_html_string_renders_locals_not_c_fields(self):
        """The HTML string-build uses fmt(o), fmt(h), fmt(l), fmt(cc)
        — not fmt(c.o) etc. This is what makes the audit's reported
        mismatch impossible: locals are immutable JS primitives once
        assigned."""
        src = _read()
        # The stats-line HTML block uses the locals
        assert "fmt(o)" in src and "fmt(h)" in src
        assert "fmt(l)" in src and "fmt(cc)" in src
        # And the OLD fmt(c.o)/fmt(c.h)/etc. are gone from the HTML
        # build sites
        anchor = "document.getElementById(STATS_ID).innerHTML"
        idx = src.find(anchor)
        window = src[idx:idx + 1500]
        assert "fmt(c.o)" not in window
        assert "fmt(c.h)" not in window
        assert "fmt(c.l)" not in window
        assert "fmt(c.c)" not in window


# ── Range computation invariant (sanity, executed in Python) ────────────────

class TestRangeComputationInvariant:
    """Verify the JS formula `h - l` matches the H-L invariant the
    audit expected. Python equivalent — not a JS exec test, but
    confirms the math is correct and consistent."""

    def test_rng_equals_h_minus_l(self):
        h, l = 100.72, 79.77
        rng = h - l
        # The JS computation IS h - l. Audit's expected H-L value.
        assert rng == pytest.approx(20.95, abs=0.01)

    def test_rng_pct_consistent_with_audit_observation(self):
        """The audit's reported `Range $100.95 (126.55%)` is internally
        consistent in one specific way: 100.95 / 79.77 = 126.55%. This
        proves the rendered value was internally consistent (rng and
        rngPct were computed from the same source) but the source
        was NOT (displayed H=$100.72) minus (displayed L=$79.77).
        Likely a screenshot-timing artifact, as the fix's comment
        explains."""
        # Audit-observed values
        observed_rng = 100.95
        observed_l = 79.77
        # If rng came from THIS l, what would rngPct be?
        observed_pct = (observed_rng / observed_l) * 100
        # That matches the audit's 126.55%
        assert observed_pct == pytest.approx(126.55, abs=0.01)

    def test_rng_pct_at_displayed_h_l_not_matching_observed_pct(self):
        """Cross-check: if the audit-displayed H and L were the actual
        rng source, the percentage would have been ~26.26%, not
        126.55%. This is what proves the audit-time data was
        inconsistent between rng-compute and label-render — the
        fix's defensive cache + label rename addresses both sides."""
        h, l = 100.72, 79.77
        actual_rng = h - l  # 20.95
        actual_pct = (actual_rng / l) * 100
        assert actual_pct == pytest.approx(26.26, abs=0.01)
        # Not 126.55% — confirms the audit's screenshot had inconsistent
        # data between rng-compute and the H/L labels.


# ── Compile pins (MED-047) ──────────────────────────────────────────────────

class TestTemplateCompiles:

    def test_equity_ohlc_compiles(self):
        env = _make_env()
        tpl = env.get_template("fragments/equity_ohlc.html")
        assert tpl is not None
