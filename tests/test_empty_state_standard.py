"""The no-data standard (operator directive 2026-07-25).

  "the dotted lines offset from pane wall is twice the standardized space
   between each panes. the dotted lines are surrounding entire main pane, with
   the information correlated to the pane are in the center both vertical and
   horizontal."

Geometry: the standard inter-pane space IS --qe-pane-gap. GridWorkspace insets
each tile by GAP/2 per edge, so the visible gap BETWEEN two panes is the full
token; twice that is calc(var(--qe-pane-gap) * 2).

Mechanism (and why it is not a margin): the pane body carries its own padding —
'5px 7px' by default and overridden per call site — so a margin would land at a
different offset on every pane, the exact inconsistency the directive removes.
An absolutely-positioned box resolves `inset` against its ancestor's PADDING
BOX, whose edge is the pane's inner border, so the offset is exactly 2x the gap
whatever the body padding is. Measured in a browser at 8/8/8/8 against three
body paddings (default, 0, and 18px 24px) before this was committed.

Scoping: the rule REQUIRES a .qe-pane-body ancestor and the `fill` prop is
opt-in. Both guards matter and are pinned below — without the ancestor
requirement an EmptyState in a modal would escape and cover the dialog chrome;
without opt-in, a zero-state rendered ALONGSIDE siblings in a pane body would
cover them.
"""
from __future__ import annotations

import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "frontend", "src")


def _src(name: str) -> str:
    with open(os.path.join(SRC, name), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def emitted():
    with open(os.path.join(ROOT, "static", "v3", "manifest.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    out = {}
    for key in ("app", "tokens"):
        with open(os.path.join(ROOT, "static", "v3", man[key]), encoding="utf-8") as fh:
            out[key] = fh.read()
    return out


class TestGeometry:
    def test_offset_is_twice_the_pane_gap(self):
        css = _src("tokens.css")
        m = re.search(r"\.qe-pane-body \.qe-empty\.fill \{(.*?)\}", css, re.S)
        assert m, "the no-data fill rule is gone"
        body = m.group(1)
        assert "position: absolute" in body
        assert "inset: calc(var(--qe-pane-gap) * 2)" in body, (
            "offset must be expressed as 2x the pane-gap TOKEN — a hardcoded px "
            "would silently desynchronise if the gap is ever retuned"
        )
        assert "margin: 0" in body, "a residual margin would add to the inset"

    def test_overflow_is_scrollable(self):
        """An absolute box cannot grow its parent: a long hint (the error
        boundary passes a raw exception message) must scroll rather than clip
        its Reload CTA out of reach."""
        css = _src("tokens.css")
        body = re.search(r"\.qe-pane-body \.qe-empty\.fill \{(.*?)\}", css, re.S).group(1)
        assert "overflow: auto" in body

    def test_content_stays_centred_both_axes(self):
        """The centring lives on the base .qe-empty and must not be lost."""
        css = _src("tokens.css")
        base = re.search(r"\n\.qe-empty \{(.*?)\}", css, re.S).group(1)
        assert "align-items: center" in base
        assert "justify-content: center" in base
        assert "flex-direction: column" in base

    def test_pane_gap_token_still_exists(self):
        assert "--qe-pane-gap:" in _src("tokens.css")


class TestScoping:
    def test_rule_requires_a_pane_body_ancestor(self):
        """Without this, an EmptyState inside a modal would position against the
        dialog panel and cover its head and footer."""
        css = _src("tokens.css")
        assert ".qe-pane-body .qe-empty.fill" in css
        # ...and the rule must never appear UNSCOPED, i.e. as the start of a
        # selector. Checked line-initially (and after a comma) rather than with a
        # lookbehind: the scoped form is preceded by a space, so a naive
        # non-word lookbehind matches the good rule too.
        assert not re.search(r"^\s*\.qe-empty\.fill\s*[,{]", css, re.M), \
            "an unscoped .qe-empty.fill rule would escape its pane"
        assert not re.search(r",\s*\.qe-empty\.fill\s*[,{]", css), \
            "an unscoped .qe-empty.fill selector alternative would escape its pane"

    def test_pane_body_is_the_positioning_anchor(self):
        s = _src("primitives.jsx")
        i = s.index('className="qe-pane-body"')
        decl = s[i:i + 260]
        assert "position:'relative'" in decl or "position: 'relative'" in decl

    def test_fill_is_opt_in(self):
        """Default false: a zero-state rendered alongside siblings inside a pane
        body must stay in flow or it would cover them."""
        s = _src("primitives.jsx")
        m = re.search(r"const EmptyState = \(\{([^}]*)\}\)", s)
        assert m, "EmptyState signature not found"
        assert "fill=false" in m.group(1).replace(" ", "")

    def test_fill_prop_reaches_the_class(self):
        s = _src("primitives.jsx")
        assert "fill?' fill':''" in s.replace(" ", "").replace("'", "'") or \
               re.search(r"fill\s*\?\s*' fill'\s*:\s*''", s), \
               "the fill prop must append the class"


class TestCentralSitesOptIn:
    """The two primitive sites carry the standard for most of the app."""

    def test_datalist_empty_branch_fills(self):
        """This ONE line is the no-data state of every table pane (21 call
        sites). The branch returns only the EmptyState — no toolbar, no table —
        so it is the pane body's sole content."""
        s = _src("primitives.jsx")
        m = re.search(r"if \(!allRows\.length\) \{(.*?)\}", s, re.S)
        assert m, "DataList truly-empty short-circuit not found"
        assert "<EmptyState fill" in m.group(1)

    def test_pane_error_boundary_fills(self):
        s = _src("primitives.jsx")
        i = s.index("failed to render")
        assert "<EmptyState fill" in s[max(0, i - 300):i]

    def test_filtered_to_zero_does_NOT_fill(self):
        """The one hard exclusion. When rows exist but the search/facets exclude
        them all, the sticky toolbar is still rendered ABOVE and is the only way
        out of that state. An absolute inset box would paint over it and trap
        the operator with no way to clear the filter."""
        s = _src("primitives.jsx")
        i = s.index('className="qe-dl-empty"')
        seg = s[max(0, i - 400):i + 200]
        assert "EmptyState fill" not in seg


class TestReachesTheBundle:
    def test_rule_is_emitted(self, emitted):
        assert ".qe-pane-body .qe-empty.fill" in emitted["tokens"]
        assert "calc(var(--qe-pane-gap) * 2)" in emitted["tokens"]

    def test_class_is_emitted(self, emitted):
        assert "qe-pane-body" in emitted["app"]
