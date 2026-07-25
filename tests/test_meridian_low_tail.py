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


# ═══════════════════════════════════════════════════════════════════════════
# SLICE 2 — the remaining frontend LOW/NIT: analytics · dashboard · models ·
# pretrade · shell-chrome. Same rule as slice 1: restore what the design had
# where the data already exists. One backend field was needed (dashboard-4's
# strategy_preset) and is pinned on the route.
# ═══════════════════════════════════════════════════════════════════════════

class TestAnalytics:
    def test_analytics_1_daily_avg_pct_restores_the_pairing(self):
        """The pane pairs each absolute with its percent; Daily Avg PnL stood
        alone in dollars. pnlPct/days — both already in scope."""
        s = _src("pages-analytics.jsx")
        assert "'Daily Avg PnL %'" in s
        assert "(pnlPct / days)" in s

    def test_analytics_1_under_chart_strip(self):
        s = _src("pages-analytics.jsx")
        assert "start $" in s and "end $" in s

    def test_analytics_2_adj_chg(self):
        """Chg includes deposits; on a bar carrying one it overstates
        performance by exactly cf with nothing labelling it."""
        s = _src("pages-analytics.jsx")
        assert "Adj Chg" in s
        assert "chg - (+last.cf || 0)" in s

    def test_analytics_3_dispersion(self):
        """A mean near zero with a wide spread is a different situation from a
        mean near zero with a tight one — only the spread separates them."""
        s = _src("pages-analytics.jsx")
        assert "const _anaStd" in s and "_anaStd(entryCosts)" in s

    def test_analytics_3_std_is_population_not_sample(self):
        """It describes the window on screen, not an inference about a wider
        population — and an empty sample must be '—', never 0."""
        s = _src("pages-analytics.jsx")
        fn = s[s.index("const _anaStd"):]
        fn = fn[:fn.index("\n};")]
        assert "/ a.length)" in fn and "a.length - 1" not in fn
        assert "return null" in fn


class TestDashboard:
    def test_dashboard_2_monthly_replaces_the_duplicate(self):
        """The 2x2 is a period LADDER. One prime slot rendered Available, which
        is already the FieldList's first row two lines below."""
        s = _src("dash-tiled.jsx")
        i = s.index("const EquityStatsPane")
        grid = s[i:i + 2600]
        assert "<Lbl>Monthly</Lbl>" in grid
        assert grid.count("<Lbl>Available</Lbl>") == 0, "Available is still duplicated in the 2x2"

    def test_dashboard_3_funding_line_is_labelled(self):
        """A bare 'SYM ±0.01%' list gives no cue it is the 8h funding rate."""
        s = _src("dash-tiled.jsx")
        i = s.index("funding_lines")
        assert "FUNDING " in s[i - 400:i + 500]

    def test_dashboard_3_does_not_fabricate_state_badges(self):
        """No sector_state / funding_state is computed anywhere in the backend,
        so the design's IN CAP / +0.02-8h badges could only be fabricated."""
        s = _src("dash-tiled.jsx")
        assert "IN CAP" not in s

    def test_dashboard_4_preset_badge_and_backend_field(self):
        s = _src("dash-tiled.jsx")
        assert "PRESET: " in s
        assert "p.strategy_preset" in s
        with open(os.path.join(ROOT, "api", "routes_dashboard.py"), encoding="utf-8") as fh:
            r = fh.read()
        assert 'params_view["strategy_preset"]' in r

    def test_dashboard_4_absent_preset_hides_the_badge(self):
        """An unreadable setting must not assert a preset the operator never
        chose — the route emits None and the tile renders nothing."""
        s = _src("dash-tiled.jsx")
        assert "{preset ? (" in s

    def test_dashboard_5_cash_flow_lifted_through_onbar(self):
        """cf was already IN the payload and dropped during the row map — the
        field was unread, not unbacked."""
        s = _src("dash-tiled.jsx")
        assert "cf: last.cf" in s
        assert "Cash Flow" in s


class TestModelsAndPretrade:
    def test_models_2_import_confirm_shows_the_window(self):
        s = _src("pages-models.jsx")
        assert "period_start" in s and "period_end" in s

    def test_models_3_no_spec_jargon_in_rendered_copy(self):
        """'§3' resolves to nothing the operator can open."""
        s = _src("pages-models.jsx")
        assert "§3" not in s

    def test_pretrade_1_controlled_stepper_exists(self):
        """The existing StepperInput is UNCONTROLLED and would fight a form that
        owns its values — programmatic changes (prefill, Clear, recall) would
        never reach the input."""
        s = _src("primitives.jsx")
        assert "const StepperNumber" in s
        fn = s[s.index("const StepperNumber"):s.index("const StepperInput")]
        assert "React.useState" not in fn, "a controlled input must hold no value state"
        assert "ArrowUp" in fn and "ArrowDown" in fn

    def test_pretrade_1_all_four_tp_sl_fields_use_it(self):
        s = _src("pages-pretrade.jsx")
        assert s.count("<StepperNumber id=") == 4

    def test_pretrade_2_regime_is_tone_coded(self):
        """The 'no engine feed' rationale was false — NAV_REGIME_TONE ships in
        the build and the workspace strip already renders a live badge from it."""
        s = _src("pages-pretrade.jsx")
        assert "NAV_REGIME_TONE" in s
        assert s.count("<RegimeBadge tone={regTone}") == 2

    def test_pretrade_2_unknown_label_does_not_guess(self):
        s = _src("pages-pretrade.jsx")
        assert "|| null;" in s[s.index("const regTone"):s.index("const regTone") + 120]

    def test_pretrade_5_no_duplicate_exposure_row(self):
        """The Position sub-pane printed the After-Costs portfolio figure under a
        Position-scoped label; est_exposure IS portfolio-level."""
        s = _src("pages-pretrade.jsx")
        assert s.count("_ptFmtN(c.est_exposure, 2)") == 1


class TestShellChrome:
    def test_shell_chrome_1_real_halt_banner(self):
        """The slot rendered an inert NotifBanner whose source is hardcoded 0,
        so halt state reached only 2 of 9 pages."""
        s = _src("nav-and-data.jsx")
        assert "const ChromeHaltBanner" in s
        assert "<ChromeHaltBanner/>" in s
        assert "<NotifBanner/>" not in s, "the inert banner is back in the chrome slot"

    def test_shell_chrome_1_driven_by_api_state(self):
        s = _src("nav-and-data.jsx")
        fn = s[s.index("const ChromeHaltBanner"):]
        fn = fn[:fn.index("\n};")]
        assert "st.halted" in fn and "st.blocked" in fn
        assert "localStorage" not in fn, "the halt authority must not return to localStorage"

    def test_shell_chrome_4_navh_counts_visible_banners(self):
        """It used to derive from the permanently-false halt flag while the build
        had added a SECOND under-nav banner the constant knew nothing about."""
        s = _src("notifications.jsx")
        assert "qeChromeBannerCount" in s
        assert "const navH = banner ? 84 : 54;" not in s

    def test_shell_chrome_4_counter_covers_both_banners(self):
        s = _src("nav-and-data.jsx")
        fn = s[s.index("const qeChromeBannerCount"):]
        fn = fn[:fn.index("\n};")]
        assert "clock_severity" in fn
        assert "halted" in fn and "blocked" in fn
