"""Pins for the 5 MED findings of the 2026-07-25 Meridian design-consistency
audit (docs/audits/2026-07-25-v3.0-meridian-design-consistency-audit.md).

Frontend fixes are pinned at BOTH layers on purpose:

  * SOURCE  — `frontend/src/*.jsx`, the thing a maintainer edits.
  * EMITTED — `static/v3/app.<hash>.js`, the thing the browser actually runs.

The source/emitted split is the house lesson from the PaneFoot arc: a source
edit that never reaches the bundle ships nothing, and the esbuild `vm.Script`
guard is PARSE-only — it has twice failed to catch unbound identifiers. These
are shape pins, not behavioural ones; they exist so a later refactor cannot
silently undo a fix without a red test naming the finding.

The backend half of shell-chrome-3 (`/api/state.exchange_ws`) is pinned in
tests/test_routes.py, which owns the isolated TestClient.
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


def _cols_block(src: str, key: str) -> str:
    """Slice one `key: [ ... ]` entry out of pages-history's COLS map.

    Anchored on the 4-space indent deliberately: a bare `"fills: ["` also
    matches the `{ fills: [] }` catch-fallback at the top of the file, which
    silently produced an EMPTY slice and made these pins vacuous.
    """
    m = re.search(rf"\n    {key}: \[", src)
    assert m, f"COLS.{key} not found"
    start = m.end()
    nxt = re.search(r"\n    \w+: \[", src[start:])
    return src[start:start + nxt.start()] if nxt else src[start:]


@pytest.fixture(scope="module")
def bundle() -> str:
    """The EMITTED bundle named by the manifest — not a glob, so a stale
    left-over app.*.js can never satisfy these pins."""
    with open(os.path.join(ROOT, "static", "v3", "manifest.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    with open(os.path.join(ROOT, "static", "v3", man["app"]), encoding="utf-8") as fh:
        return fh.read()


# ── config-1 — warn / hard-stop ratios editable again ────────────────────────

_RATIOS = ("weekly_loss_warning_pct", "weekly_loss_limit_pct",
           "max_dd_warning_pct", "max_dd_limit_pct")


class TestConfig1ThresholdsEditable:
    """The four ratios were editable in the design and editable NOWHERE in the
    v3 build, despite POST /accounts/{id}/update already accepting them."""

    def test_form_state_seeds_all_four(self):
        s = _src("pages-config.jsx")
        for k in _RATIOS:
            assert re.search(rf"{k}:\s*p\.{k}", s), f"{k} not seeded from params"

    def test_dosave_posts_the_ratios_pairwise(self):
        """THE fix-review HIGH on this surface. validate_params gates its
        warn<limit check on BOTH keys being present in the SUPPLIED subset, so
        posting one member alone skips the cross-check and the merged store can
        end up inverted while the endpoint still answers 200 'Saved.'. An
        inversion is not cosmetic — the weekly pair is consumed unconditionally
        and the limit branch is evaluated first, so it deletes the warning tier.
        """
        s = _src("pages-config.jsx")
        body = s[s.index("const doSave"):s.index("const doTest")]
        assert "cfgRatioPairs(form, p)" in body, "ratios must be sent pairwise"
        # and the helper must backfill the blank half rather than omit it
        h = s[s.index("const cfgRatioPairs"):s.index("const cfgRatioError")]
        assert "if (!w && !l) continue" in h, "an untouched pair must stay omitted"
        assert "fallback(warnKey)" in h and "fallback(limitKey)" in h

    def test_inverted_pair_is_rejected_before_the_endpoint(self):
        """The endpoint writes params field-by-field BEFORE validating, so a
        server-side rejection can still have moved other fields. Keep the
        rejection class unreachable rather than widening that window."""
        s = _src("pages-config.jsx")
        assert "const cfgRatioError" in s
        save = s[s.index("const doSave"):s.index("const doTest")]
        assert "cfgRatioError(form)" in save
        assert save.index("cfgRatioError") < save.index("_cfgPostForm"), \
            "the pre-check must run BEFORE the POST"

    def test_dd_ratio_copy_does_not_overclaim(self):
        """core/data_cache reads the DD ratios ONLY in the except-fallback of the
        rolling-DD path (the primary path uses the absolute account_settings
        thresholds), while the WEEKLY pair is consumed unconditionally. Copy that
        says both 'drive the state machine' is false for DD."""
        s = _src("pages-config.jsx")
        assert "FALLBACK only" in s
        assert "These drive the DD / weekly state machine." not in s

    def test_preset_claim_is_accurate(self):
        """PRESET_PARAMS carries only the 6 sizing knobs — no ratios."""
        s = _src("pages-config.jsx")
        assert "a preset rewrites both" not in s
        with open(os.path.join(ROOT, "core", "strategy_presets.py"), encoding="utf-8") as fh:
            p = fh.read()
        block = p[p.index("PRESET_PARAMS"):p.index("PRESET_PARAMS") + 1200]
        for k in _RATIOS:
            assert k not in block, f"PRESET_PARAMS now carries {k} — update the copy"

    def test_inputs_are_rendered_and_bound(self):
        s = _src("pages-config.jsx")
        for k in _RATIOS:
            assert f"set('{k}')" in s, f"no bound input for {k}"

    def test_endpoint_still_accepts_them(self):
        """The write path this fix depends on. If someone drops these Form
        fields the inputs silently become no-ops, so pin the server side too."""
        with open(os.path.join(ROOT, "api", "routes_accounts.py"), encoding="utf-8") as fh:
            r = fh.read()
        for k in _RATIOS:
            assert re.search(rf"{k}:\s*Optional\[float\]\s*=\s*Form\(", r), \
                f"POST /accounts/{{id}}/update no longer accepts {k}"

    def test_bounds_and_pair_validation_intact(self):
        """validate_params enforces warn < limit; the UI copy promises it."""
        with open(os.path.join(ROOT, "core", "state.py"), encoding="utf-8") as fh:
            st = fh.read()
        for k in _RATIOS:
            assert f'"{k}"' in st, f"{k} missing from core/state.py"
        assert '("max_dd_warning_pct", "max_dd_limit_pct")' in st
        assert '("weekly_loss_warning_pct", "weekly_loss_limit_pct")' in st

    def test_readonly_block_still_labelled_readonly(self):
        """The account_settings block below stays read-only — the two stores are
        disjoint and conflating them was the audit's own confusion risk.
        (Chip text updated 2026-08-04, dead-settings M2a: the block's weekly
        rows became params-DERIVED display, so the chip now says which half
        is preset-written and which is derived — the READ-ONLY property this
        pin protects is unchanged.)"""
        s = _src("pages-config.jsx")
        assert "READ-ONLY · DD set via Presets tab · weekly derived from the ratios above" in s

    def test_reaches_the_bundle(self, bundle):
        for k in _RATIOS:
            assert k in bundle, f"{k} never reached the emitted bundle"


# ── history-1 — order trigger levels ─────────────────────────────────────────

class TestHistory1TriggerColumn:
    """109 of 258 live order rows are stop/TP with price=0; they rendered
    'PRICE 0.000000' and showed the defining level nowhere."""

    def test_block_extraction_is_not_vacuous(self):
        """Guard the guard: an empty slice would make every pin below pass."""
        assert "key: 'symbol'" in _cols_block(_src("pages-history.jsx"), "orders")

    def test_orders_has_trigger_column(self):
        block = _cols_block(_src("pages-history.jsx"), "orders")
        assert "'TRIGGER'" in block or '"TRIGGER"' in block
        assert "stop_price" in block

    def test_trigger_does_NOT_fall_back_to_plan_levels(self):
        """REVERTED in fix-review: a tp/sl fallback printed an ENTRY order's
        take-profit PLAN level as though it were that order's trigger, dropped
        the SL half silently, and desynced the column from its own sort (DataList
        sorts row[col.key] — raw stop_price, which is 0 on exactly those rows).
        The plan levels are a different fact and belong to the plan surface."""
        block = _cols_block(_src("pages-history.jsx"), "orders")
        render = block[block.index("key: 'stop_price'"):]
        render = render[:render.index("key: 'avg_fill_price'")]
        for f in ("tp_trigger_price", "sl_trigger_price"):
            assert f not in render, f"TRIGGER must not source {f} — see the anchor comment"

    def test_trigger_sorts_on_what_it_renders(self):
        """No sortVal is supplied, so the rendered field MUST equal col.key."""
        block = _cols_block(_src("pages-history.jsx"), "orders")
        render = block[block.index("key: 'stop_price'"):]
        render = render[:render.index("key: 'avg_fill_price'")]
        assert "sortVal" in render or render.count("r.stop_price") >= 1
        assert "r.tp_trigger_price" not in render

    def test_zero_price_no_longer_renders_as_a_level(self):
        """lpPx(0) formats '0.000000', which reads as a real price."""
        block = _cols_block(_src("pages-history.jsx"), "orders")
        price_cell = block[block.index("key: 'price'"):block.index("key: 'stop_price'")]
        assert "+r.price === 0" in price_cell, "PRICE must blank on 0, not print 0.000000"

    def test_trigger_key_is_server_sortable(self):
        """Defence-in-depth only. The React history table sorts CLIENT-side over
        the fetched page and sends no sort_by (see this file's own load()), so
        this is not on the live path today — but stop_price being in the server
        whitelist is what keeps it safe to wire server sort later."""
        with open(os.path.join(ROOT, "core", "db_orders.py"), encoding="utf-8") as fh:
            d = fh.read()
        cols = d[d.index("_ORDERS_SORT_COLS"):d.index("_ORDERS_SORT_COLS") + 400]
        assert '"stop_price"' in cols

    def test_reaches_the_bundle(self, bundle):
        assert "TRIGGER" in bundle


# ── pretrade-4 — the price poll's real state ─────────────────────────────────

class TestPretrade4PricePollState:
    """The foot asserted a static ok/'local' while the pane hosted a 1 Hz poll
    whose failures were swallowed — and that price is the market-order sizing
    entry."""

    def test_poll_records_errors(self):
        s = _src("pages-pretrade.jsx")
        assert "setNetPx" in s, "price poll must track a net-state"
        assert not re.search(r"catch \(e\) \{ /\* keep last \*/ \}", s), \
            "the silent catch is back — poll failures are invisible again"

    def test_order_inputs_foot_is_derived_not_asserted(self):
        s = _src("pages-pretrade.jsx")
        i = s.index('title="Order Inputs"')
        head = s[i:i + 1200]
        assert "qeFootState" in head, "Order Inputs foot must derive from the pipe"
        assert "netPx" in head
        assert "{ tone: 'ok', msg: 'local' }" not in head, \
            "Order Inputs is back to asserting a static ok/'local'"

    def test_price_absent_after_a_latch_is_degraded_not_ok(self):
        """A 200 carrying no price after one was latched is feed death: livePrice
        keeps its last value and in MARKET mode that latched value still drives
        sizing, so reporting ok paints health over a stale sizing input. Before
        the FIRST price nothing is latched and Entry Price honestly reads '—', so
        that case stays ok — flagging it would fire a red foot through warm-up."""
        s = _src("pages-pretrade.jsx")
        assert "hadPrice" in s
        assert "!d.price && hadPrice" in s
        assert "corrupt: true" in s

    def test_recent_setups_foot_left_alone(self):
        """Recent Setups IS local (localStorage recall) — it must keep its
        honest static foot; the fix was surgical, not a sweep."""
        s = _src("pages-pretrade.jsx")
        i = s.index('title="Recent Setups"')
        assert "{ tone: 'ok', msg: 'local' }" in s[i:i + 400]

    def test_reaches_the_bundle(self, bundle):
        assert "netPx" in bundle


# ── shell-chrome-2 — the inert Desktop switch ────────────────────────────────

class TestShellChrome2DesktopSwitchHonest:
    """Deferred by plan §7; operator decision 2026-07-25 was to KEEP the
    deferral and make the control honest rather than wire it."""

    def test_switch_primitive_supports_disabled(self):
        s = _src("primitives.jsx")
        assert re.search(r"const Switch = \(\{[^}]*disabled=false", s, re.S)

    def test_disabled_switch_swallows_onchange(self):
        """A disabled control must not call the caller's handler at all."""
        s = _src("primitives.jsx")
        sw = s[s.index("const Switch = ({"):]
        sw = sw[:sw.index("</div>")]
        assert "disabled ? undefined : onChange" in sw

    def test_disabled_switch_does_not_reuse_the_muted_idiom(self):
        """line-through is Chip's `muted` visual and reads as 'the user silenced
        this', not 'not shipped yet' — fix-review LOW."""
        s = _src("primitives.jsx")
        sw = s[s.index("const Switch = ({"):]
        sw = sw[:sw.index("</div>")]
        # assert on the STYLE, not on prose — the anchor comment names the
        # rejected idiom and would otherwise trip a bare substring check.
        assert "textDecoration" not in sw

    def test_desktop_switch_is_disabled_and_off(self):
        s = _src("notifications.jsx")
        i = s.index('label="Desktop"')
        decl = s[i:i + 260]
        assert "disabled" in decl
        assert "on={false}" in decl
        assert "deferred" in decl.lower()

    def test_desktop_no_longer_claims_push_notifications(self):
        s = _src("notifications.jsx")
        assert 'title="Browser push notifications"' not in s, \
            "the switch is inert — it must not promise out-of-focus reachability"

    def test_sibling_controls_still_live(self):
        """Sound and DND DO act on real polled events — the fix must not have
        disabled the whole row."""
        s = _src("notifications.jsx")
        for lbl in ('label="Sound"', 'label="DND"'):
            i = s.index(lbl)
            assert "disabled" not in s[i:i + 160], f"{lbl} was disabled by mistake"

    def test_reaches_the_bundle(self, bundle):
        assert "deferred (plan" in bundle


# ── shell-chrome-3 — exchange feed health in the chrome ──────────────────────

class TestShellChrome3FeedHealth:
    """SSE state and exchange-feed state are independent pipes; the chrome
    carried only the former, so a dead market feed showed an all-green chrome."""

    def test_helper_exists_and_reads_the_endpoint_field(self):
        s = _src("nav-and-data.jsx")
        assert "const _navFeed" in s
        assert "exchange_ws" in s

    def test_all_three_chrome_positions_carry_it(self):
        """The design had the signal in the nav dot, the workspace Strip and the
        footer. Pin all three — a partial restore is the half-closed-MED class."""
        s = _src("nav-and-data.jsx")
        assert 'label="FEED"' in s, "top-nav dot missing"
        assert "label: 'LAT'" in s, "workspace Strip LAT cell missing"
        assert "● feed" in s, "status-footer dot missing"

    def test_disconnected_is_distinguishable_from_unknown(self):
        """'down' (connected=false) and '—' (no reading yet) are different
        operator facts and must not collapse into one rendering."""
        s = _src("nav-and-data.jsx")
        fn = s[s.index("const _navFeed"):]
        fn = fn[:fn.index("\n};")]
        assert "'down'" in fn and "'—'" in fn
        assert "stale_s" in fn, "a connected-but-silent feed must degrade to warn"

    def test_false_no_latency_justification_is_gone(self):
        """The old comment claimed no per-message latency source existed. It was
        false — core/ws_manager stamps it — and it was the stated reason the LAT
        cell was dropped.

        Whitespace-normalised on purpose: the phrase was line-wrapped in the
        source, so a raw substring check passed VACUOUSLY even while the claim
        was still present. Caught in fix-review."""
        flat = re.sub(r"\s+", " ", _src("nav-and-data.jsx"))
        assert "no real per-message latency source exists" not in flat

    def test_feed_reads_the_market_socket_not_the_user_socket(self):
        """THE fix-review HIGH. ws.connected / ws.last_update belong to the
        USER-DATA socket (ws_manager writes `connected` only in _user_data_loop),
        and last_update is additionally floored by the 30s REST account refresh.
        Wiring the feed indicator to them made it lie BOTH ways: red 'prices
        frozen' on a user-socket blip, and green through a real market outage."""
        with open(os.path.join(ROOT, "api", "routes_dashboard.py"), encoding="utf-8") as fh:
            r = fh.read()
        blk = r[r.index('"exchange_ws"'):]
        blk = blk[:blk.index("}")]
        assert "ws.market_connected" in blk
        assert "ws.market_seconds_since_update" in blk
        assert "ws.market_latency_ms" in blk
        assert "ws.connected" not in blk, "feed health must not read the user socket"
        assert "ws.seconds_since_update" not in blk

    def test_market_flags_are_actually_written(self):
        """A field nothing writes would leave the dot permanently red."""
        with open(os.path.join(ROOT, "core", "ws_manager.py"), encoding="utf-8") as fh:
            w = fh.read()
        assert "ws.market_connected = True" in w, "market loop never marks connected"
        assert "ws.market_connected = False" in w, "market loop never marks disconnected"
        assert "ws.market_last_update" in w
        assert "ws.market_latency_ms" in w

    def test_latency_never_fabricates_zero(self):
        """latency_ms defaults to 0.0 and is only stamped inside an `if evt_ms`
        guard, so 'connected but never measured' must emit None — not a perfect
        0 ms. templates/fragments/ws_status.html has always used this guard."""
        with open(os.path.join(ROOT, "api", "routes_dashboard.py"), encoding="utf-8") as fh:
            r = fh.read()
        blk = r[r.index('"exchange_ws"'):]
        blk = blk[:blk.index("}")]
        assert "and ws.market_latency_ms" in blk

    def test_dead_endpoint_does_not_read_green(self):
        """chrome-live keeps the last-good /api/state payload and only raises
        stateErr, so without an explicit branch the dot shows stale 'ok' forever
        after the engine dies."""
        s = _src("nav-and-data.jsx")
        fn = s[s.index("const _navFeed"):]
        fn = fn[:fn.index("\n};")]
        assert "stateErr" in fn
        assert fn.index("stateErr") < fn.index("exchange_ws"), \
            "the stateErr branch must precede reading the last-good payload"

    def test_rest_fallback_does_not_report_a_frozen_latency(self):
        """On REST fallback the websocket is not delivering, so latency_ms is
        frozen at the last live frame — printing it presents stale as current."""
        s = _src("nav-and-data.jsx")
        fn = s[s.index("const _navFeed"):]
        fn = fn[:fn.index("\n};")]
        assert "'REST'" in fn

    def test_latency_source_still_exists(self):
        with open(os.path.join(ROOT, "core", "ws_manager.py"), encoding="utf-8") as fh:
            assert "latency_ms" in fh.read()

    def test_reaches_the_bundle(self, bundle):
        for token in ("_navFeed", "exchange_ws", "FEED"):
            assert token in bundle, f"{token} never reached the emitted bundle"
