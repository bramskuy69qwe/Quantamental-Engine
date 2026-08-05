"""Every READ pipe in the v3 UI carries a deadline, so a hang cannot read green.

THE BUG (filed 2026-07-31 as "the WARM HANG", closed 2026-08-01). `fetch` has
no default timeout, and a promise that never settles runs NEITHER the resolve
nor the catch branch. A pipe that answered once and then went dark therefore
kept its `{err: null, ms}` net entry unchanged forever, and its pane foot read
`ok · connected [12ms]` indefinitely — Net Exposure, Drawdown, Weekly Loss and
Positions frozen at hours-old values under an affirmative healthy signal, on a
risk console. Executed before the fix: 24 h / ~17k outstanding polls, still
green.

Three siblings died with the same change, each verified at the line first:
  · Pre-Trade's price / orderbook / link-window pollers reschedule with
    setTimeout AFTER their await, so one hang stopped them PERMANENTLY while
    their foots went on promising `· retrying`. In MARKET mode the price pipe
    is the sizing input, so that one sized off a frozen number.
  · the notification poll's `inFlight` latch is released in a `finally` a hang
    never reaches — one hang killed the alert feed for the session, silently.
  · hung requests held their connections; Chrome's ~6-per-origin cap then
    queued every other same-origin poll behind them.

WHAT THIS FILE PINS, AND WHY IN THIS SHAPE.

1. STRUCTURE cannot carry this one alone. The predecessor file
   (test_dash_foot_covers_its_sources.py) learned that the hard way: four
   drafts of `_dashFootWorst` passed every structural pin and were wrong. So
   the load-bearing class here EXECUTES the real `_ptJson` — sliced verbatim
   out of primitives.jsx — against a fetch that never settles, and asserts on
   what actually comes back.
2. COVERAGE is derived, not listed. `TestEveryPolledReadIsBounded` finds the
   poll cadences and the read calls in source and asserts every polled read
   passes a deadline. A new poller that forgets one fails here without anyone
   remembering this bug.
3. DRIFT is the real long-term risk. The deadline is only truthful while it
   tracks the cadence it was derived from, so the interval literal and the
   deadline argument must be the SAME NAMED CONSTANT — asserted, not assumed.

Run: pytest tests/test_net_deadline.py -v
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests._srcpin import (  # noqa: E402
    code as _code, args as _args, phantom_openers as _phantom_openers,
    scheduled_delays as _scheduled_delays, const as _const,
)

_ROOT = Path(__file__).parent.parent
_SRC = _ROOT / "frontend" / "src"
_DESIGN = (_ROOT / "frontend" / "DESIGN.md").read_text(encoding="utf-8")


def _raw(name: str) -> str:
    return (_SRC / name).read_text(encoding="utf-8")


def _src(name: str) -> str:
    return _code(_raw(name))


_PRIM = _src("primitives.jsx")












# Every module that owns a POLLED read, and the cadence constants it declares.
# The constants exist SO THAT the interval and the deadline cannot drift apart,
# which is the property the drift class below asserts.
_POLLED = {
    "dash-tiled.jsx": ["EQUITY_OHLC_MS", "NEWS_FEED_MS"],   # + the _POLL map
    "chrome-live.js": [],          # derives per-poll from its own `ms` argument
    "notifications.jsx": ["N_POLL_MS"],
    # PT_PRICE_MS / PT_BOOK_MS schedule but do NOT derive their deadline —
    # both are exchange-backed, see TestTheUpstreamBudget.
    "pages-pretrade.jsx": ["PT_STATE_MS", "PT_REGIME_MS", "PT_LINKWIN_MS",
                           "PT_LINKWIN_FAST_MS"],
    "pages-history.jsx": ["H_REFRESH_MS"],
    "pages-linkage.jsx": ["LK_FAST_MS", "LK_SLOW_MS"],
    "pages-regime.jsx": ["RG_BACKFILL_MS"],
    "pages-analytics.jsx": [],     # useAnaJson derives from its intervalMs arg
}

# Reads that legitimately ride the ONE-SHOT default: fired on mount, on a
# selection, or on an explicit operator action, with no successor coming. They
# cannot go stale behind a green foot the way a poll can — their symptom is a
# spinner that never resolves, which the 30 s default now ends. Enumerated
# rather than pattern-matched so that a NEW read must be a deliberate entry
# here or carry its own deadline; "it looked like a one-shot" is not a default.
# A poller with TWO cadences (fast lane while a job is pending, slow after)
# needs ONE deadline, sized from the SLOWER one. Map secondary -> primary; the
# drift pin asserts the ordering rather than exempting the constant.
_SECONDARY_CADENCES = {
    "pages-pretrade.jsx": {"PT_LINKWIN_FAST_MS": "PT_LINKWIN_MS"},
}

_ONE_SHOT_READS = {
    "pages-history.jsx": [
        "per_page: '1'",                     # the per-tab count badges
        "/fragments/history/position_fills", # drilldown leg 1 (row click)
        "/context/position/",                # drilldown leg 2 (row click)
    ],
    "pages-pretrade.jsx": [
        "/calculator/prefill/",              # model prefill (picker change)
    ],
}


# ── 0. the stripper is not vacuous ──────────────────────────────────────────

@pytest.mark.parametrize("name", sorted(_POLLED) + ["primitives.jsx"])
def test_stripped_source_is_substantial(name):
    """C1's lesson: one stray `/*` truncates `_code()` and every assertion in
    this file would then pass against a shorter string.

    Necessary but NOT sufficient — see the class below, which is what actually
    caught it here. This bulk check passed on `pages-linkage.jsx` while the
    stripper was eating the very region this file pins."""
    stripped = _src(name)
    assert "/*" not in stripped and "//" not in stripped
    # A LOOSE floor on purpose. These modules are 20-60% prose by design
    # (chrome-live.js is the densest), so a tight ratio would be a style pin,
    # not a correctness one — and the ratio was never what caught the real
    # trap anyway. TestTheCommentStripperTrap is the detector; this only
    # catches a total collapse.
    assert len(stripped) > 0.25 * len(_raw(name)), (
        f"{name}: the comment stripper ate {100 - 100 * len(stripped) // len(_raw(name))}% "
        f"of the file — suspect an unterminated block comment"
    )


class TestTheCommentStripperTrap:
    """`/*` inside a `//` comment opens a PHANTOM block comment.

    `_srcpin.code()` strips block comments FIRST, so a line comment mentioning
    a glob path (`/orders/*`, `/static/vendor/*`) opens a block that runs to
    the next `*/` — usually the end of some later doc block — and silently
    deletes every line between. Source pins over that region then pass
    vacuously, which is the one way a pin can be worse than absent.

    This has now bitten twice: the service worker (C1, 2026-07-31; `code()`
    returned 13 of 4924 chars) and `pages-linkage.jsx:344`
    (`// /orders/* vs /api/linkage/*`), where it ate lines 344-389 — the
    `nets` state, the `load` callback holding the module's ONLY read, and
    `lkFoot`'s `qeFootState` call. The bulk-size check above did not see it:
    2323 of 47623 chars is a 5% loss.

    So detect the CAUSE app-wide rather than the symptom per file.
    """

    _FILES = sorted(p.name for p in _SRC.glob("*.js") for _ in [0]) + \
             sorted(p.name for p in _SRC.glob("*.jsx"))

    def test_the_file_list_is_not_empty(self):
        assert len(self._FILES) > 15, self._FILES

    @pytest.mark.parametrize("name", _FILES)
    def test_no_line_comment_opens_a_phantom_block(self, name):
        for n in _phantom_openers(_raw(name)):
            line = _raw(name).splitlines()[n - 1]
            assert False, (
                f"{name}:{n} — a `//` comment contains `/*`, which opens a "
                f"phantom block comment for tests/_srcpin.py and silently "
                f"deletes every line up to the next `*/`. Every source pin "
                f"over that region passes vacuously. Write the path without "
                f"the glob star.\n    {line.strip()}"
            )

    def test_the_detector_actually_detects(self):
        """Mutation-check, inline. It must run the SAME function the
        parametrized test runs — the draft re-implemented the two lines against
        a local literal, so neutering the real assertion left this green while
        claiming to prove it could not be."""
        clean = "const a = 1;\n// a normal comment\n/* a normal block */\n"
        assert _phantom_openers(clean) == [], _phantom_openers(clean)
        # the exact shape that ate pages-linkage.jsx:344-389
        bad = "const a = 1;\n  // /orders/* vs /api/linkage/* — routers\n"
        assert _phantom_openers(bad) == [2], _phantom_openers(bad)

    def test_the_region_the_phantom_ate_is_pinnable_again(self):
        """The specific regression, named. If the glob comes back, this file's
        linkage coverage silently stops covering anything."""
        src = _src("pages-linkage.jsx")
        for token in ("const [nets, setNets]", "_ptJson(", "qeFootState("):
            assert token in src, (
                f"`{token}` vanished from the stripped linkage source — the "
                f"phantom block comment is back"
            )


# ── 1. the rule itself ──────────────────────────────────────────────────────

class TestTheDeadlineRule:
    def test_the_poll_deadline_is_the_interval_floored(self):
        """Not a flat constant: a flat one is either too slack for a 1 s poll
        or too tight for a 60 s one. Executed in TestExecutedBehaviour."""
        assert re.search(
            r"const qePollDeadline = \(intervalMs\) => Math\.max\(intervalMs \|\| 0, 5_?000\)",
            _PRIM,
        ), "qePollDeadline is no longer `max(interval, 5s)`"

    def test_one_shot_reads_have_their_own_budget(self):
        assert re.search(r"const QE_READ_DEADLINE_MS = 30_?000", _PRIM)

    def test_ptjson_defaults_to_the_one_shot_budget(self):
        """A caller that forgets must still be bounded — an un-defaulted
        parameter would restore the whole bug for every one-shot read."""
        assert "const _ptJson = async (url, deadlineMs = QE_READ_DEADLINE_MS)" in _PRIM

    def test_the_abort_is_wired_to_the_actual_request(self):
        m = re.search(r"const _ptFetch = async \(url, init, deadlineMs\) => \{(.*?)\n\};",
                      _PRIM, re.S)
        assert m, "_ptFetch is gone — every read is unbounded again"
        body = m.group(1)
        assert "new AbortController()" in body
        assert "signal: ac.signal" in body, "a signal that never reaches fetch is decoration"
        assert "ac.abort(_ptDeadlineErr(url, deadlineMs))" in body

    def test_the_deadline_timer_is_always_cleared(self):
        """Left armed, each read leaks a live timer for its whole budget — the
        1 Hz price poll would hold 30 of them at once."""
        i = _PRIM.index("const _ptJson = async")
        body = _PRIM[i:_PRIM.index("const qeFootCause")]
        assert body.count("clearTimeout(t)") >= 2, body
        assert "finally {" in body, "the body-read path must clear in a finally"
        assert "clearTimeout(t)" in _PRIM[_PRIM.index("const _ptFetch"):i], (
            "_ptFetch must clear its own timer when the fetch itself rejects"
        )

    def test_a_timeout_is_not_reported_as_no_network(self):
        """A deadline error carries status 0 (the network sentinel), so both
        deriving branches must test `timeoutMs` BEFORE the status branch or
        they name a cause that is false: the socket connected fine, the ENGINE
        did not answer on it."""
        cause = _PRIM[_PRIM.index("const qeFootCause"):_PRIM.index("const qeFootState")]
        assert cause.index("err.timeoutMs") < cause.index("s == null || s === 0"), (
            "qeFootCause tests status before timeoutMs — a timeout now reports "
            "`no network — engine unreachable`, which is a false diagnosis"
        )
        # `const PaneFoot =`, not the `// PaneFoot —` comment above it: _code()
        # strips comments, so the comment marker is not in this string at all.
        state = _PRIM[_PRIM.index("const qeFootState"):_PRIM.index("const PaneFoot =")]
        assert state.index("e.timeoutMs") < state.index("e.status == null || e.status === 0")
        assert "timeoutMs: err ? err.timeoutMs : undefined" in state, (
            "the descriptor drops timeoutMs, so the branch above can never fire"
        )

    def test_the_numeric_tag_is_tested_for_PRESENCE_not_truthiness(self):
        """`timeoutMs` is a DURATION, so `if (err.timeoutMs)` treats 0 as
        absent. A zero deadline then falls through to the network sentinel and
        the foot renders `no network · showing last data` — the exact false
        diagnosis this change exists to remove, reached from inside it.

        Unreachable today (the floor is 5 s, the default 30 s, and the three
        conditional call sites pass `undefined`, never 0), which is precisely
        why it needs a pin rather than a comment: nothing else in the suite
        would notice the guard being loosened. Found by adversarial review;
        the first draft used truthiness at all three sites."""
        # Target the DECIDING positions only — an `if (…)` condition and the
        # ternary test. Reading the value (`${_qeSecs(err.timeoutMs)}`, the
        # descriptor copy) is fine and must not be flagged; the draft of this
        # pin used a fixed character window and did flag them.
        for pattern, where in (
            (r"if \(\w+\.timeoutMs\)", "an `if` condition"),
            (r"\w+\.timeoutMs \?", "a ternary test"),
        ):
            m = re.search(pattern, _PRIM)
            assert m is None, (
                f"`{m.group(0)}` tests a DURATION for truthiness in {where} — "
                f"a 0 ms deadline reads as 'no timeout' and the foot then "
                f"reports `no network`, the false diagnosis this change removes"
            )
        assert _PRIM.count("timeoutMs != null") == 3, (
            "expected the null-check at all three deciding sites "
            "(_ptDeadlineHit, qeFootCause, qeFootState's tier-2 branch)"
        )

    def test_writes_are_exempt_on_purpose(self):
        """Scope pin. Aborting a mutation cannot un-do what the server already
        did, so it trades a stuck spinner for `did my save land?`. If this ever
        changes it must be a decision, not a sweep."""
        for name, helper in (
            ("pages-config.jsx", "_cfgPostForm"), ("pages-config.jsx", "_cfgPostJson"),
            ("pages-linkage.jsx", "_lkForm"), ("pages-regime.jsx", "_rgPost"),
            ("pages-models-data.jsx", "_mdlSend"), ("dash-tiled.jsx", "_dashPostJson"),
        ):
            src = _src(name)
            i = src.index(f"const {helper} = ")
            body = src[i:i + 700]
            assert "_ptFetch(" not in body, (
                f"{helper} was given a deadline — see DESIGN.md; if intended, "
                f"update the rule and this pin together"
            )


# ── 2. COVERAGE — derived from source, so a new poller cannot slip through ──

class TestEveryPolledReadIsBounded:
    """A polled read without a deadline is the original bug, re-created."""

    def test_the_call_parser_is_not_blind(self):
        """Guards every assertion below. A parser that finds nothing makes
        them all pass while proving nothing — and the regex draft of this file
        did exactly that in two modules."""
        calls = _args(_src("pages-linkage.jsx"), "_ptJson")
        assert calls == [["url", "qePollDeadline(everyMs)"]], calls
        assert len(_args(_src("pages-pretrade.jsx"), "_ptJson")) >= 5
        assert _scheduled_delays(_src("pages-linkage.jsx")).count("LK_FAST_MS") == 1

    @pytest.mark.parametrize("name", sorted(_POLLED))
    def test_every_read_either_names_a_deadline_or_is_a_declared_one_shot(self, name):
        """THE COVERAGE PIN. Derived from source, so a poller added next year
        cannot quietly skip it: the read must pass a deadline argument, or its
        URL must be listed in _ONE_SHOT_READS above with the reason."""
        allowed = _ONE_SHOT_READS.get(name, [])
        for call in _args(_src(name), "_ptJson"):
            if len(call) >= 2:
                assert ("qePollDeadline" in call[1] or "QE_READ_DEADLINE_MS" in call[1]
                        or "QE_UPSTREAM_READ_DEADLINE_MS" in call[1]
                        or "deadlineMs" in call[1]), (
                    f"{name}: _ptJson({call[0][:60]}…) passes `{call[1]}` as its "
                    f"deadline — not derived from a cadence or the one-shot budget"
                )
                continue
            assert any(frag in call[0] for frag in allowed), (
                f"{name}: _ptJson({call[0][:80]}) rides the one-shot default but "
                f"is not declared in _ONE_SHOT_READS. If it is polled it needs "
                f"qePollDeadline(itsCadence); if it really is a one-shot, add it "
                f"there with the reason."
            )

    @pytest.mark.parametrize("name,consts", sorted(_POLLED.items()))
    def test_each_cadence_constant_feeds_both_its_scheduler_and_its_deadline(self, name, consts):
        """THE DRIFT PIN, and the reason the constants exist at all. A deadline
        is only truthful while it tracks the cadence it was derived from. If
        someone retunes a poll to 30 s and the deadline stays a hardcoded 5 s,
        every healthy cycle aborts; if the reverse, the lie comes back.

        Two modules reach the deadline through a named parameter rather than
        the constant itself (Pre-Trade's `load(url, fn, netFn, everyMs)` and
        Linkage's `get(url, fn, pick, key, everyMs)`), so the constant is
        checked as an ARGUMENT to that loader, not as literal text inside
        qePollDeadline(...). Asserting the literal form was the draft's error
        and it flagged both modules as unbounded when they are not."""
        src = _src(name)
        derivers = {a[0] for a in _args(src, "qePollDeadline")}
        forwarded = {a[-1] for fn in ("load", "get")
                     for a in _args(src, fn) if len(a) >= 4}
        secondary = _SECONDARY_CADENCES.get(name, {})
        for c in consts:
            if c in secondary:
                # One poller, two cadences (the countdown polls fast while
                # PENDING, slow after). It needs ONE deadline, and it must
                # cover the LARGER cadence — which is the real invariant, so
                # assert that rather than waving the constant through.
                primary = secondary[c]
                assert primary in derivers, f"{name}: {primary} derives no deadline"
                assert _const(src, c) <= _const(src, primary), (
                    f"{name}: {c} ({_const(src, c)} ms) is now SLOWER than "
                    f"{primary} ({_const(src, primary)} ms), which is what the "
                    f"shared deadline is sized from — the fast lane would abort "
                    f"healthy responses"
                )
            else:
                assert c in derivers or c in forwarded, (
                    f"{name}: {c} reaches no read deadline — neither "
                    f"qePollDeadline({c}) nor a loader call forwarding it"
                )
            assert c in _scheduled_delays(src), (
                f"{name}: {c} does not feed a setInterval/setTimeout, so it is "
                f"not the cadence it claims to be"
            )

    @pytest.mark.parametrize("name", sorted(_POLLED))
    def test_no_deadline_is_derived_from_a_bare_literal(self, name):
        """The drift pin's other half. A deadline computed from a number typed
        at the call site tracks nothing — retuning the poll leaves it behind,
        and the direction of the damage depends on which way it moved.

        Scoped to qePollDeadline's OWN argument rather than to every scheduler
        in the file: the first draft asserted the latter and flagged five
        unrelated timers (a 1 s clock, a 60 s re-render tick, toast dismissal),
        none of which fetch anything."""
        for call in _args(_src(name), "qePollDeadline"):
            assert not re.fullmatch(r"[0-9_]+", call[0]), (
                f"{name}: qePollDeadline({call[0]}) is derived from a bare "
                f"literal — name the cadence and use it for both the schedule "
                f"and the deadline"
            )

    def test_the_dashboard_store_derives_every_pipe_from_one_map(self):
        """dash-tiled reaches its deadline through the net KEY (`_POLL[key]`),
        so the constants are the map's own entries."""
        src = _src("dash-tiled.jsx")
        m = re.search(r"const _POLL = \{([^}]*)\}", src)
        assert m, "the _POLL cadence map is gone"
        keys = set(re.findall(r"(\w+):", m.group(1)))
        assert keys == {"st", "log", "macro", "snapshot"}, keys
        assert "_ptJson(url, qePollDeadline(_POLL[key]))" in src
        delays = _scheduled_delays(src)
        for k in keys:
            assert f"_POLL.{k}" in delays, (
                f"_POLL.{k} is a deadline source but schedules nothing — the "
                f"two sides of the map have drifted"
            )

    def test_chrome_derives_its_deadline_from_the_polls_own_interval(self):
        """This store polls three endpoints at three cadences through ONE
        helper, so the derivation has to happen inside it."""
        src = _src("chrome-live.js")
        # Sliced from the `poll` declaration to its closing `};`, not to the
        # first `_runState` — the account watcher now sits between the two, and
        # anchoring on a neighbouring declaration makes the pin break whenever
        # the file grows rather than when its subject changes.
        i = src.index("const poll = (url, key, errKey, ms")
        body = src[i:src.index("\n  };", i)]
        assert "const deadlineMs = qePollDeadline(ms);" in body
        assert "j(url, deadlineMs)" in body
        assert "setInterval(run, ms)" in body, "the same `ms` must drive both"

    def test_analytics_derives_its_deadline_from_the_hooks_interval(self):
        src = _src("pages-analytics.jsx")
        i = src.index("const useAnaJson")
        body = src[i:src.index("const useAnaLabel")]
        assert "_ptJson(url, intervalMs ? qePollDeadline(intervalMs) : undefined)" in body
        assert re.search(r"\}, \[url, intervalMs\]\);", body), (
            "intervalMs is read inside the useCallback but missing from its "
            "deps — a stale closure would derive the OLD cadence's deadline"
        )


# ── 3. the siblings that died with it ───────────────────────────────────────

class TestTheSiblingDefects:
    def test_the_notification_latch_is_released_after_a_hang(self):
        """`inFlight` is cleared in a `finally` that an unsettled promise never
        reaches, so one hang muted the alert feed for the session."""
        src = _src("notifications.jsx")
        i = src.index("const poll = async () => {")
        body = src[i:src.index("const t = setInterval(poll", i)]
        assert "inFlight = true" in body
        assert "_ptFetch(" in body, "the poll is unbounded again — the latch can stick"
        assert "qePollDeadline(N_POLL_MS)" in body
        assert re.search(r"finally \{ clearTimeout\(deadline\); inFlight = false; \}", body)

    @pytest.mark.parametrize("deadline,url_frag", [
        ("QE_UPSTREAM_READ_DEADLINE_MS", "/api/price/"),
        ("QE_UPSTREAM_READ_DEADLINE_MS", "/api/calculator/orderbook/"),
        ("qePollDeadline(PT_LINKWIN_MS)", "/calculator/link-window-status/"),
    ])
    def test_the_self_rescheduling_pretrade_pollers_are_bounded(self, deadline, url_frag):
        """These reschedule AFTER the await, so a hang stopped them for good —
        a dead pipe that never retried, under a foot promising `· retrying`.
        (The same shape is why a longer deadline costs them nothing: at most
        one request is ever outstanding.)"""
        src = _src("pages-pretrade.jsx")
        call = next(a for a in _args(src, "_ptJson") if url_frag in a[0])
        assert len(call) == 2 and call[1] == deadline, call

    def test_the_pretrade_price_foot_still_promises_retrying(self):
        """The promise is only honest because the deadline restores the retry.
        If the deadline goes, this claim becomes a lie again.

        Asserted on the netPx foot's OWN call, not on two floating substrings:
        `retrying: true` appears three times in this module, so the draft of
        this test stayed green when the price foot's own flag was flipped."""
        src = _src("pages-pretrade.jsx")
        calls = [a for a in _args(src, "qeFootState") if "netPx" in " ".join(a)]
        assert len(calls) == 1, f"expected exactly one netPx foot, got {len(calls)}"
        fields = " ".join(calls[0])
        assert "err: netPx.err" in fields, fields
        assert "retrying: true" in fields, (
            "the price foot no longer promises `· retrying` — either restore it "
            "or remove the promise; it is only true because the deadline makes "
            "the chained-setTimeout poller resume after a hang"
        )


class TestTheUpstreamBudget:
    """A client deadline tighter than the ENGINE's own upstream budget kills
    requests the server was about to answer — and then the pane never loads at
    all, which is the same class of lie pointing the other way.

    Two polled reads have a handler that awaits a third-party call:
    `/api/price/{ticker}` and `/api/calculator/orderbook/{ticker}` both await
    `fetch_orderbook` → `core.exchange_market` → the ccxt adapter, whose
    default timeout is 10 s with no override and no retry in this codebase.
    Under exchange latency a healthy 6-10 s response is normal there, and the
    5 s poll floor would have aborted every one of them, forever. (Found by an
    adversarial review of the first draft; the floor was 5 s for these too.)

    The BACKEND half is pinned as well, because the frontend constant is only
    correct as long as the backend fact holds — and a third such endpoint would
    otherwise inherit the tight floor silently.
    """

    _POLLED_HANDLERS = {
        "/api/price/": "routes_dashboard",
        "/api/state": "routes_dashboard",
        "/api/dashboard/snapshot": "routes_dashboard",
        "/api/engine/log/live": "routes_dashboard",
        "/api/system": "routes_dashboard",
        "/api/dashboard/equity_ohlc": "routes_dashboard",
        "/api/calculator/orderbook/": "routes_calculator",
        "/api/regime/signals/latest": "routes_regime",
        "/api/regime/current": "routes_regime",
        "/api/regime/backfill-status": "routes_regime",
        "/api/news/feed": "routes_news",
        "/notifications/poll": "routes_notifications",
        "/api/linkage/positions": "routes_cockpit",
    }
    # Anything that leaves the process on the request path.
    _OUTBOUND = re.compile(
        r"fetch_orderbook|fetch_mark_price|fetch_ohlcv|fetch_ticker"
        r"|adapter\.\w*fetch|_get_adapter\(\)|httpx\.|aiohttp\.|requests\.")

    def _handler_body(self, endpoint: str, module: str) -> str:
        src = (_ROOT / "api" / f"{module}.py").read_text(encoding="utf-8")
        m = re.search(r'@router\.get\(["\']' + re.escape(endpoint)
                      + r'[^)]*\)\s*\n(?:async )?def (\w+)', src)
        assert m, f"handler for {endpoint} not found in api/{module}.py"
        nxt = src.find("\n@router.", m.end())
        return src[m.end():nxt if nxt > 0 else len(src)]

    def test_exactly_two_polled_endpoints_call_out_of_process(self):
        """The premise. If a third appears it must ALSO take the upstream
        budget, or its pane will hard-fail under normal exchange latency."""
        outbound = {ep for ep, mod in self._POLLED_HANDLERS.items()
                    if self._OUTBOUND.search(self._handler_body(ep, mod))}
        assert outbound == {"/api/price/", "/api/calculator/orderbook/"}, (
            f"the set of polled reads whose handler makes a synchronous "
            f"outbound call changed to {sorted(outbound)}. Give any new one "
            f"QE_UPSTREAM_READ_DEADLINE_MS in the frontend — the 5 s poll "
            f"floor is tighter than ccxt's 10 s default and would abort every "
            f"healthy slow response."
        )

    def test_the_budget_exceeds_the_engines_own_upstream_timeout(self):
        m = re.search(r"const QE_UPSTREAM_READ_DEADLINE_MS = ([0-9_]+);", _PRIM)
        assert m, "the upstream budget constant is gone"
        budget = int(m.group(1).replace("_", ""))
        import ccxt  # the engine's actual client, not a remembered number
        ccxt_default = ccxt.binance().timeout
        assert budget > ccxt_default, (
            f"the client deadline ({budget} ms) is not longer than ccxt's own "
            f"timeout ({ccxt_default} ms), so the browser aborts requests the "
            f"engine was about to answer"
        )

    def test_no_adapter_overrides_or_retries_that_timeout(self):
        """The budget is sized against ccxt's default; a retry loop or a raised
        adapter timeout would invalidate it."""
        for path in (_ROOT / "core" / "adapters").rglob("rest_adapter.py"):
            body = path.read_text(encoding="utf-8")
            assert "timeout" not in body.lower() or "fetch_orderbook" not in body, (
                f"{path.name} now mentions a timeout — re-check "
                f"QE_UPSTREAM_READ_DEADLINE_MS against it"
            )


# ── 4. the half a deadline cannot reach ─────────────────────────────────────

class TestThrottledPollerRefresh:
    """A hidden page's timers are throttled to ~1/min (a frozen page's stop),
    so NO request is outstanding to time out and the last frame keeps its
    `connected` foot over minute-old numbers. The stores re-poll on return.
    A timestamp-and-threshold scheme could not cover this either — its clock is
    throttled by exactly the same rule."""

    def test_the_helper_fires_only_on_becoming_visible_and_rate_limits(self):
        """ONE implementation, in primitives, because it has two easy-to-get-
        wrong parts: firing on the HIDE transition too (backwards), and firing
        once per transition (rapid alt-tabbing then bursts one request per pipe
        per toggle against the same ~6-connection cap this change cites as the
        hang's aggravator — an audit finding on the first draft)."""
        i = _PRIM.index("const qeOnVisible")
        body = _PRIM[i:_PRIM.index("const _ptDeadlineErr")]
        assert "if (document.hidden) return;" in body, "fires on hide too"
        assert "if (now - last < minGapMs) return;" in body, "no rate limit"
        assert "return () => document.removeEventListener" in body, (
            "no unsubscribe, so a store with a lifecycle cannot unhook"
        )

    def test_the_chrome_store_repolls_all_three_pipes_on_return(self):
        src = _src("chrome-live.js")
        assert "qeOnVisible(() => { _runState(); _runSnap(); _runSys(); });" in src, (
            "the app-wide strip does not refresh on return, or refreshes only "
            "some of its pipes"
        )
        assert "document.addEventListener" not in src, "hand-rolled listener is back"

    def test_the_dashboard_store_does_the_same_and_unhooks_on_stop(self):
        src = _src("dash-tiled.jsx")
        start = src[src.index("function start()"):src.index("function stop()")]
        stop = src[src.index("function stop()"):src.index("function setUi(")]
        assert "_unVisible = qeOnVisible(refreshAll);" in start
        assert "if (_unVisible) { _unVisible(); _unVisible = null; }" in stop, (
            "the listener outlives the Dashboard, so leaving the page keeps "
            "polling four endpoints on every tab focus forever"
        )
        assert "document.addEventListener" not in src, "hand-rolled listener is back"

    def test_the_first_load_and_the_refresh_are_the_same_call(self):
        """Two lists of loaders drift; one goes stale silently."""
        src = _src("dash-tiled.jsx")
        assert "function refreshAll() { loadSnapshot(); loadState(); loadMacro(); loadLog(); }" in src
        start = src[src.index("function start()"):src.index("function stop()")]
        assert "refreshAll();" in start
        assert "loadSnapshot(); loadState(); loadMacro(); loadLog();" not in start


# ── 5. BEHAVIOUR: execute the real thing against a real hang ───────────────

_NODE = shutil.which("node")

_JS_DRIVER = """
const out = {};
const hang = () => { globalThis.fetch = (url, init) =>
  new Promise((_r, rej) => init.signal.addEventListener('abort', () => rej(init.signal.reason))); };
const stallBody = () => { globalThis.fetch = (url, init) => Promise.resolve({ ok: true,
  json: () => new Promise((_r, rej) => init.signal.addEventListener('abort', () => rej(init.signal.reason))) }); };
const bareAbort = () => { globalThis.fetch = (url, init) =>
  new Promise((_r, rej) => init.signal.addEventListener('abort', () => {
    const e = new Error('aborted'); e.name = 'AbortError'; rej(e); })); };
// `=== undefined ? null` and NOT a bare read: JSON.stringify DROPS undefined
// properties, so `notFound` arrived with no timeoutMs key and `corrupt` with
// no status key — the assertions then died on KeyError instead of comparing.
const nn = (v) => (v === undefined ? null : v);
const shape = (e) => ({ status: nn(e.status), timeoutMs: nn(e.timeoutMs),
                        corrupt: !!e.corrupt, cause: qeFootCause(e) });

const grab = async (fn) => { try { await fn(); return null; } catch (e) { return e; } };

(async () => {
  hang();
  const t0 = Date.now();
  const e1 = await grab(() => _ptJson('/api/state', 250));
  out.hang = e1 ? { ...shape(e1), settledMs: Date.now() - t0 } : null;
  out.hangFootWithData = e1 ? qeFootState({ loading: false, err: e1, hasData: true, ms: 12, retrying: true }) : null;
  out.hangFootNoData = e1 ? qeFootState({ loading: false, err: e1, hasData: false, ms: null, retrying: true }) : null;

  stallBody();
  const e2 = await grab(() => _ptJson('/api/state', 250));
  out.stalledBody = e2 ? shape(e2) : null;

  bareAbort();
  const e3 = await grab(() => _ptJson('/api/state', 200));
  out.bareAbort = e3 ? shape(e3) : null;

  globalThis.fetch = () => Promise.resolve({ ok: true, json: async () => ({ v: 1 }) });
  out.healthy = await _ptJson('/api/state', 5000);
  out.healthyFoot = qeFootState({ loading: false, err: null, hasData: true, ms: 12 });

  globalThis.fetch = () => Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
  out.notFound = shape(await grab(() => _ptJson('/x', 5000)));
  globalThis.fetch = () => Promise.reject(new TypeError('Failed to fetch'));
  out.netFail = shape(await grab(() => _ptJson('/x', 5000)));
  globalThis.fetch = () => Promise.resolve({ ok: true, json: async () => { throw new SyntaxError('x'); } });
  out.corrupt = shape(await grab(() => _ptJson('/x', 5000)));

  out.deadlines = [1000, 2000, 4000, 5000, 15000, 30000, 60000].map(qePollDeadline);
  out.oneShot = QE_READ_DEADLINE_MS;
  console.log(JSON.stringify(out));
})();
"""


@pytest.mark.skipif(_NODE is None, reason="node not on PATH")
class TestExecutedBehaviour:
    """The class that would have caught a plausible-but-wrong implementation.

    Every structural pin above passes against a `_ptFetch` that builds an
    AbortController and never arms the timer, or arms it and drops the reason,
    or arms it only around the header fetch. Execute it instead: point the real
    `_ptJson` at a fetch that never settles and read what comes back.
    """

    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory):
        raw = _raw("primitives.jsx")
        sliced = raw[raw.index("const QE_READ_DEADLINE_MS"):raw.index("// PaneFoot —")]
        assert len(sliced) > 2000, "the source slice collapsed — check the markers"
        f = tmp_path_factory.mktemp("deadline") / "harness.mjs"
        f.write_text(sliced + _JS_DRIVER, encoding="utf-8")
        # encoding="utf-8" is load-bearing: these messages carry `—` and `·`,
        # and Windows decodes a subprocess pipe as cp1252 by default, which
        # turns every assertion on them into a mojibake mismatch.
        r = subprocess.run([_NODE, str(f)], capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    def test_a_hang_terminates_at_all(self, result):
        """THE defect. Before the deadline this returned null: the promise never
        settled, so neither branch ran and the net entry kept its last-good
        `{err:null, ms}` — 24 h and ~17k outstanding polls later, still green."""
        assert result["hang"] is not None, (
            "a fetch that never settles STILL never rejects — the warm hang is "
            "back and every foot in the app will read `connected` through it"
        )

    def test_it_terminates_within_its_own_budget(self, result):
        """A deadline that fires late is a shorter lie, not a closed one."""
        assert result["hang"]["settledMs"] < 250 + 400, result["hang"]

    def test_the_hang_is_tagged_so_the_cause_can_be_named(self, result):
        assert result["hang"]["timeoutMs"] == 250
        assert result["hang"]["status"] == 0, (
            "status 0 is this codebase's network sentinel; dropping it silently "
            "re-routes every consumer that branches on it"
        )
        assert result["hang"]["cause"] == "no response in 250ms — engine not answering"

    def test_the_foot_over_a_hung_pipe_says_so(self, result):
        """Both tiers, because the 2-vs-3 rule turns on whether the pane has
        anything on screen — and BOTH used to read `ok · connected [12ms]`."""
        with_data = result["hangFootWithData"]
        assert with_data["tone"] == "warn", with_data
        assert with_data["msg"] == "no response in 250ms · showing last data · retrying"
        no_data = result["hangFootNoData"]
        assert no_data["tone"] == "err", no_data
        assert "engine not answering" in no_data["msg"]
        assert "no network" not in no_data["msg"], (
            "a timeout is being reported as an unreachable engine — false: the "
            "socket connected, the engine went quiet on it"
        )

    def test_a_stalled_body_is_a_timeout_not_a_corrupt_response(self, result):
        """Headers sent then a stalled stream hangs exactly like a dead socket.
        Mapping it to `corrupt` names the wrong cause AND, because `corrupt`
        wins the tier-2 branch, hides that the engine went quiet."""
        assert result["stalledBody"] is not None, "the body read is unbounded"
        assert result["stalledBody"]["timeoutMs"] == 250
        assert result["stalledBody"]["corrupt"] is False

    def test_a_runtime_that_drops_the_abort_reason_still_names_it(self, result):
        assert result["bareAbort"]["timeoutMs"] == 200
        assert "engine not answering" in result["bareAbort"]["cause"]

    def test_the_healthy_path_is_untouched(self, result):
        assert result["healthy"] == {"v": 1}
        assert result["healthyFoot"] == {"tone": "ok", "msg": "connected [12ms]"}

    @pytest.mark.parametrize("key,status,corrupt,cause", [
        ("notFound", 404, False, "endpoint not found (404)"),
        ("netFail", 0, False, "no network — engine unreachable"),
        ("corrupt", None, True, "corrupt response"),
    ])
    def test_the_pre_existing_error_shapes_are_unchanged(self, result, key, status,
                                                         corrupt, cause):
        """The deadline is ADDITIVE. A real 404 must not start reporting as a
        timeout, and a real network failure must keep its own wording."""
        row = result[key]
        assert row["status"] == status
        assert row["corrupt"] is corrupt
        assert row["cause"] == cause
        assert row["timeoutMs"] is None, f"{key} was mis-tagged as a timeout"

    def test_the_deadline_curve(self, result):
        """Floored below 5 s, identity above it — so a 1 Hz poll is not
        cancelling healthy responses and a 60 s poll is not lying for two
        minutes."""
        assert result["deadlines"] == [5000, 5000, 5000, 5000, 15000, 30000, 60000]
        assert result["oneShot"] == 30000


# ── 6. the rule is written down where the next author will look ────────────

class TestTheRuleIsRecorded:
    def test_design_md_carries_the_deadline_rule(self):
        """Convention-drift discipline: a rule that lives only in a commit
        message gets re-derived, wrongly, by the next poller."""
        assert "THE READ DEADLINE" in _DESIGN
        seg = _DESIGN[_DESIGN.index("THE READ DEADLINE"):]
        seg = seg[:seg.index("\n- **`PageHeader`")]
        assert "qePollDeadline" in seg and "QE_READ_DEADLINE_MS" in seg
        assert "SAME literal" in seg, "the drift rule is the one that rots first"
        assert "WRITES ARE DELIBERATELY EXEMPT" in seg

    def test_design_md_records_why_the_filed_shape_was_not_taken(self):
        """House rule: when the investigated mechanism diverges from the filed
        one, the divergence and its reason are recorded, not just the fix."""
        seg = _DESIGN[_DESIGN.index("THE READ DEADLINE"):]
        assert "WHY AT THE REQUEST AND NOT AT THE FOOT" in seg
        assert "throttled" in seg

    def test_design_md_no_longer_advertises_the_warm_hang_as_open(self):
        assert "OPEN — the WARM HANG" not in _DESIGN

    def test_the_severity_order_is_stated_once_and_consistently(self):
        """Found while reading the doctrine for this fix: the multi-pipe rule
        stated the severity order TWICE, in opposite orders — the summary line
        had never-answered BELOW errored-with-data, contradicting both the
        numbered rule beneath it and `_FOOT_SEVERITY` itself. A doctrine that
        contradicts itself is re-derived from whichever half is read first."""
        # Whitespace-normalised: the doctrine wraps at 72 columns, so both
        # statements of the order straddle a newline + indent and a raw-source
        # regex matched neither (it reported ZERO orders and passed nothing).
        flat = re.sub(r"\s+", " ", _DESIGN)
        orders = re.findall(
            r"`err` > ([a-z-]+) > ([a-z-]+) > ([a-z-]+) > `ok`", flat)
        assert len(orders) >= 2, (
            "the multi-pipe rule states its severity order twice (summary line "
            "+ numbered rule); this pin exists because the two disagreed"
        )
        # Compare the ORDER, not the wording: the summary and the detailed rule
        # legitimately use different registers for the same tier.
        synonym = {
            "errored-showing-last-data": "errored-with-data",
            "merely-delayed": "delayed",
        }
        norm = {tuple(synonym.get(w, w) for w in o) for o in orders}
        assert norm == {("never-answered", "errored-with-data", "delayed")}, (
            f"DESIGN.md states more than one severity order: {norm}. A "
            f"never-answered pipe has NOTHING on screen, so it must outrank "
            f"both `warn` flavours — which both assert data arrived."
        )


# ── 7. it reaches the shipped bundle ───────────────────────────────────────

def test_the_fix_reaches_the_emitted_bundle():
    """Source is not what runs. The bundle is committed; a stale one ships the
    whole bug with a green suite."""
    man = json.loads((_ROOT / "static" / "v3" / "manifest.json").read_text(encoding="utf-8"))
    flat = re.sub(r"\s+", "", (_ROOT / "static" / "v3" / man["app"]).read_text(encoding="utf-8"))
    for token in (
        "constqePollDeadline=(intervalMs)=>Math.max(intervalMs||0,5e3)",
        "signal:ac.signal",
        "err.timeoutMs=ms",
        "qePollDeadline(_POLL[key])",          # the Dashboard store
        "constdeadlineMs=qePollDeadline(ms)",  # the app-wide chrome store
        "QE_UPSTREAM_READ_DEADLINE_MS)",       # the exchange-backed reads
        "qeOnVisible(",                        # the return-to-visible refresh
        "qePollDeadline(N_POLL_MS)",           # the notification latch
    ):
        assert token in flat, (
            f"`{token}` exists in source but not in the emitted bundle — "
            f"rebuild frontend/ (node build.mjs)"
        )
