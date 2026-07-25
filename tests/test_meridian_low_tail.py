"""Meridian audit LOW/NIT tail — History + Linkage slice.

Closes 10 of the 29 LOW/NIT findings in
docs/audits/2026-07-25-v3.0-meridian-design-consistency-audit.md:
  history-3 -4 -5 -6 -7 -8 · linkage-1 -2 -3 -4

Every one restores something the DESIGN had, whose data was ALREADY in the
payload the pane fetches — none of them needed a backend change. That is the
common thread and the reason this slice was taken first: the four findings that
DO need backend work (config-2 preset targeting, config-3 timezone, history-2
server-side id search, pretrade-3 sector cap) are deliberately not in it.

One half of history-5 is deliberately NOT implemented: the design's AVG R.
The verify pass refuted it — sl_price is non-null on 6 of 335 live rows, so an
R-multiple would render '—' on 98% of the window. Pinned below so nobody
"finishes" it later.
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
def bundle() -> str:
    with open(os.path.join(ROOT, "static", "v3", "manifest.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    with open(os.path.join(ROOT, "static", "v3", man["app"]), encoding="utf-8") as fh:
        return fh.read()


class TestHistoryDetailPane:
    def test_history_3_labelled_heat_bar_restored(self):
        """The detail pane's only excursion surface was two raw numbers; where
        the exit landed between them — the capture ratio — was shown nowhere."""
        s = _src("pages-history.jsx")
        assert "<HeatBarLabelled" in s
        assert "mfe={dp.mfe} mae={dp.mae} pnl={dp.net_pnl}" in s, \
            "the bar needs the realized pnl or it loses its third channel"

    def test_history_7_size_and_all_in_fee_are_back(self):
        s = _src("pages-history.jsx")
        assert '<KV l="Size"' in s
        assert '<KV l="Fee · all-in"' in s

    def test_history_7_net_carries_its_percent(self):
        s = _src("pages-history.jsx")
        i = s.index('<KV l="Net"')
        assert "_hNetPct" in s[i:i + 220]

    def test_percent_has_ONE_definition(self):
        """The table column and the detail pane must not compute the same figure
        twice — they drifted apart in the design's own port."""
        s = _src("pages-history.jsx")
        assert s.count("const _hNetPct") == 1
        # the arithmetic appears exactly ONCE — inside the helper. (Asserting
        # zero would be wrong: the helper is where it legitimately lives.)
        assert s.count("(r.net_pnl / den) * 100") == 1
        fn = s[s.index("const _hNetPct"):]
        assert "(r.net_pnl / den) * 100" in fn[:fn.index("\n};")]
        # ...and the pct COLUMN delegates rather than recomputing
        col = s[s.index("key: 'pct'"):]
        col = col[:col.index("} },")]
        assert "_hNetPct(r)" in col
        assert "entry_price" not in col, "the pct column recomputes the figure again"

    def test_history_4_drilldown_has_fee_and_role(self):
        """Per-fill cost forensics is what the drilldown exists for; both fields
        ride the same SELECT * payload and the Fills TAB already renders them."""
        s = _src("pages-history.jsx")
        i = s.index("drilldown fills")
        block = s[i:i + 2200]
        assert "key: 'fee'" in block and "fee_asset" in block
        assert "key: 'role'" in block


class TestHistoryStripAndCounts:
    def test_history_5_gross_added(self):
        s = _src("pages-history.jsx")
        assert "label: 'GROSS'" in s
        assert "realized_pnl || 0" in s, "GROSS must sum realized_pnl, the gross leg"

    def test_history_5_avg_r_deliberately_absent(self):
        """REFUTED half: sl_price is non-null on 6 of 335 live rows, so an
        R-multiple would read '—' on 98% of the window."""
        s = _src("pages-history.jsx")
        assert "AVG R" not in s

    def test_history_6_event_tone_is_derived(self):
        s = _src("pages-history.jsx")
        assert "const _hEvtTone" in s
        assert 'tone={_hEvtTone(r.event_type)}' in s
        assert 'tone="info">{r.event_type}' not in s, "tone is hardcoded again"

    def test_history_6_unknown_types_do_not_guess_a_severity(self):
        s = _src("pages-history.jsx")
        fn = s[s.index("const _hEvtTone"):]
        fn = fn[:fn.index("\n};")]
        assert "return 'info';" in fn

    def test_history_8_counts_share_one_meaning(self):
        """The badge row mixed two: active tab filtered, inactive tabs not."""
        s = _src("pages-history.jsx")
        fn = s[s.index("const loadCounts"):s.index("setCounts(out)")]
        assert "search: q.trim()" in fn, "count fetch must apply the same search"
        assert "[period, q]" in s[s.index("const loadCounts"):s.index("const loadCounts") + 1400]

    def test_history_8_count_fanout_is_debounced(self):
        """q changes per keystroke and this fans out one request per tab."""
        s = _src("pages-history.jsx")
        i = s.index("loadCounts, 250")
        assert i > 0, "the per-tab count fan-out must be debounced"


class TestLinkage:
    def test_linkage_1_time_and_hold_restored(self):
        s = _src("pages-linkage.jsx")
        block = s[s.index("const closeCols"):s.index("const closeCols") + 2600]
        assert "key: 'exit_time_ms', label: 'Time'" in block
        assert "key: 'hold_time_ms', label: 'Hold'" in block

    def test_linkage_1_pnl_states_its_percent(self):
        s = _src("pages-linkage.jsx")
        block = s[s.index("const closeCols"):s.index("const closeCols") + 2600]
        i = block.index("key: 'net_pnl'")
        assert "lpPct(pct)" in block[i:i + 900]

    def test_linkage_2_cumulative_and_absolute_settle_time(self):
        s = _src("pages-linkage.jsx")
        assert "net_cum" in s, "cumulative funding decides whether carry is worth holding"
        assert "const _lkSettleAt" in s
        assert "next_funding_time_ms" in s

    def test_linkage_2_settle_time_degrades_not_disappears(self):
        s = _src("pages-linkage.jsx")
        fn = s[s.index("const _lkSettleAt"):]
        fn = fn[:fn.index("\n};")]
        assert "countdown_s" in fn, "fall back to a derived time rather than nothing"

    def test_linkage_3_r_column_restored(self):
        s = _src("pages-linkage.jsx")
        block = s[s.index("const calcCols"):s.index("const fundCols")]
        assert "key: 'est_r', label: 'R'" in block

    def test_linkage_4_link_window_dot_restored(self):
        s = _src("pages-linkage.jsx")
        assert 'label="LINK"' in s
        assert "window_seconds" in s

    def test_stale_trims_note_updated(self):
        """A named-trims block that still lists closed items is the doc-truth
        (F13) class — the next reader trusts it and re-files."""
        s = _src("pages-linkage.jsx")
        head = s[:s.index("/* live uPnL deltas")]
        assert "Recent Closes omits Time / Hold / % columns" not in head
        assert 'the PageHeader omits the design\'s "LINK · 5m window" dot' not in head
        assert "CLOSED 2026-07-25" in head


class TestReachesTheBundle:
    def test_new_symbols_are_emitted(self, bundle):
        for token in ("HeatBarLabelled", "_hEvtTone", "_hNetPct", "_lkSettleAt", "est_r"):
            assert token in bundle, f"{token} never reached the emitted bundle"
