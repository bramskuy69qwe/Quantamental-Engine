"""Operator directive 2026-07-25: EVERY pane whose main component is a DataList
must offer all three tools — search, sort and filter.

The sweep that satisfied it is mostly NOT "turn tools on". Three distinct defect
shapes were found across 24 call sites (21 with a gap):

  1. tools={false} / {search:false}  — the obvious one, and the rarest.
  2. A column declaring a `key` that NO ROW CARRIES. render() ignores the key so
     the cell looks fine, but presentKeys and _dlDeriveFacets both skip the
     column: the header sorts on undefined and the column can never facet.
     Found on mer / impact / tpsl / dev / cd / vix / hy / rvol / funding /
     status / plan / pct / mr / heat / summary / exec / file / window.
  3. showFilter TRUE but ZERO facets derived, because _dlDeriveFacets rejects
     every column (>=70% numeric, <2 distinct, >6 distinct, high cardinality,
     values >16 chars). The fix is a FORCED facet on a genuinely categorical
     column, often bucketing a number via filterVal.

These are shape pins. They cannot prove a dropdown renders, but they fail loudly
if a later edit reintroduces a suppression or drops an accessor.
"""
from __future__ import annotations

import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "frontend", "src")

# Every module that renders a DataList as a pane's main component.
DATALIST_FILES = [
    "pages-analytics.jsx", "pages-history.jsx", "pages-linkage.jsx",
    "pages-regime.jsx", "pages-models-report.jsx", "pages-models-detail.jsx",
    "pages-models-overview.jsx", "pages-config.jsx", "dash-tiled.jsx",
]


def _src(name: str) -> str:
    with open(os.path.join(SRC, name), encoding="utf-8") as fh:
        return fh.read()


def _cols(src: str, key: str):
    """Every column literal declaring `key: '<key>'`, brace-balanced.

    A naive `.*?\\},\\n` regex stops at the FIRST closing brace, which is the
    inner `filter: { label: ... }` object — so it truncates the column right
    before filterVal and the pin passes/fails for the wrong reason. Balance.
    """
    out = []
    for m in re.finditer(rf"\{{\s*key:\s*'{re.escape(key)}'", src):
        i = m.start()
        depth = 0
        for j in range(i, min(len(src), i + 4000)):
            if src[j] == "{":
                depth += 1
            elif src[j] == "}":
                depth -= 1
                if depth == 0:
                    out.append(src[i:j + 1])
                    break
    return out


@pytest.fixture(scope="module")
def bundle() -> str:
    with open(os.path.join(ROOT, "static", "v3", "manifest.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    with open(os.path.join(ROOT, "static", "v3", man["app"]), encoding="utf-8") as fh:
        return fh.read()


class TestNoToolSuppression:
    def test_no_datalist_disables_tools_outright(self):
        """tools={false} turned off all three at once."""
        for f in DATALIST_FILES + ["app-shell.jsx"]:
            assert "tools={false}" not in _src(f), f"{f} re-suppressed DataList tools"

    def test_no_granular_false_in_tools_object(self):
        """tools={{search:false}} is the partial form of the same suppression."""
        pat = re.compile(r"tools=\{\{[^}]*(search|sort|filter)\s*:\s*false", re.S)
        for f in DATALIST_FILES:
            m = pat.search(_src(f))
            assert m is None, f"{f} disables {m.group(1)} in its tools object"

    def test_history_search_is_on(self):
        """History's search was the one deliberate granular suppression (paging is
        server-side). The operator lifted it; the server box above the tabs stays
        as the cross-page search — the two are complementary."""
        s = _src("pages-history.jsx")
        assert "tools={{ search: true, sort: true, filter: true }}" in s


class TestDerivedColumnsAreSortable:
    """Shape 2 — a column whose key is absent from the row must supply sortVal,
    or its header is a control that silently does nothing."""

    # (file, column key, the accessor that must now exist)
    CASES = [
        ("pages-analytics.jsx", "mer", "sortVal"),
        ("pages-analytics.jsx", "impact", "sortVal"),
        ("pages-analytics.jsx", "link_status", "sortVal"),
        ("pages-regime.jsx", "vix", "sortVal"),
        ("pages-regime.jsx", "hy", "sortVal"),
        ("pages-regime.jsx", "rvol", "sortVal"),
        ("pages-regime.jsx", "funding", "sortVal"),
        ("pages-linkage.jsx", "dev", "sortVal"),
        ("pages-linkage.jsx", "cd", "sortVal"),
        ("pages-history.jsx", "plan", "sortVal"),
        ("pages-history.jsx", "pct", "sortVal"),
        ("pages-history.jsx", "mr", "sortVal"),
        ("pages-history.jsx", "heat", "sortVal"),
        ("pages-history.jsx", "summary", "sortVal"),
        ("pages-models-detail.jsx", "file", "sortVal"),
        ("pages-models-detail.jsx", "window", "sortVal"),
        ("pages-config.jsx", "status", "sortVal"),
        ("dash-tiled.jsx", "age", "sortVal"),
        ("dash-tiled.jsx", "pnl", "sortVal"),
    ]

    @pytest.mark.parametrize("fname,key,accessor", CASES)
    def test_derived_column_has_accessor(self, fname, key, accessor):
        cols = _cols(_src(fname), key)
        assert cols, f"{fname}: column '{key}' not found"
        # A key can appear in more than one table per file; EVERY derived
        # occurrence must carry the accessor or one table keeps a dead header.
        bad = [c for c in cols if accessor not in c]
        assert not bad, (
            f"{fname}: {len(bad)}/{len(cols)} '{key}' column(s) lack {accessor} — "
            f"that header sorts on row['{key}'], which no row carries"
        )

    def test_no_derived_column_still_opts_out_of_sort(self):
        """sort:false survives ONLY on columns that are not data: action buttons,
        a row-ordinal, and TP/SL (two independent prices, no single sort key)."""
        allowed = {"act", "rank", "tpsl", "order", "exec"}
        pat = re.compile(r"\{\s*key:\s*'([a-z_0-9]+)'[^\n]{0,200}?sort:\s*false")
        for f in DATALIST_FILES:
            for key in pat.findall(_src(f)):
                assert key in allowed, (
                    f"{f}: column '{key}' opts out of sort — give it sortVal "
                    f"instead, or add it to the allow-list with a reason"
                )


class TestEveryPaneCanFacet:
    """Shape 3 — each DataList-main module must force at least one categorical
    facet, otherwise showFilter is true and no dropdown ever renders."""

    @pytest.mark.parametrize("fname", DATALIST_FILES)
    def test_module_forces_a_facet(self, fname):
        s = _src(fname)
        assert re.search(r"filter:\s*(true|\{)", s), (
            f"{fname}: no forced facet anywhere — every column would have to pass "
            f"_dlDeriveFacets' auto heuristics, which is exactly the failure this "
            f"sweep fixed"
        )

    @pytest.mark.parametrize("fname", DATALIST_FILES)
    def test_forced_facets_are_categorical(self, fname):
        """A forced facet on a raw continuous number would produce a dropdown with
        one option per row. Every forced facet must either supply filterVal (the
        bucket-a-number pattern) or sit on a column whose raw value is already a
        small enum — pinned here by requiring filterVal wherever we forced one on
        a numeric-looking key."""
        s = _src(fname)
        numericish = ("net", "pnl", "pnl_total", "income", "profit", "per_8h",
                      "per_day", "per_week", "net_pnl", "pnl_usdt")
        for key in numericish:
            for col in _cols(s, key):
                if not re.search(r"filter:\s*(true|\{)", col):
                    continue
                assert "filterVal" in col, (
                    f"{fname}: '{key}' forces a facet on a continuous number "
                    f"without filterVal — that yields one option per row"
                )


class TestPrimitiveAllowsForcedFacetOnHomogeneousData:
    """The <2-distinct bail used to sit BEFORE the forced branch, so a forced
    facet could never render on a homogeneous table — which is the normal live
    shape (one open position, one regime). That made the filter vanish exactly
    when the table was small."""

    def test_forced_facet_survives_single_value(self):
        s = _src("primitives.jsx")
        assert "if (distinct.length < 2 && !forced) return;" in s

    def test_auto_facet_still_bails_on_single_value(self):
        """AUTO must keep bailing — a one-option dropdown derived by heuristic is
        noise, not a tool."""
        s = _src("primitives.jsx")
        assert "distinct.length < 2" in s and "!forced" in s


class TestReachesTheBundle:
    """A source edit that never reaches the emitted bundle ships nothing."""

    def test_accessors_are_in_the_bundle(self, bundle):
        for token in ("filterVal", "sortVal", "searchVal"):
            assert token in bundle, f"{token} never reached the emitted bundle"

    def test_no_tools_false_in_the_bundle(self, bundle):
        assert "tools:!1" not in bundle, "a tools={false} survived into the bundle"
