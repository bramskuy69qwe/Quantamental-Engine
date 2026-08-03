"""H7 — the calculator auto-refresh surfaces its failures.

THE DEFECT (wiring inventory 2026-07-30, fixed 2026-08-03): every failure
branch in `doCalculate` was `if (!auto)`-gated, so the AUTO lane (1 s in
MARKET mode / 30 s in LIMIT) dropped server refusals, non-JSON bodies and
network throws on the floor. The three result panes' foot went on reading
`calc ok` over sizing numbers that had stopped tracking the market — a stale
calc presented as current, on the pane that feeds order entry.

Fix, two halves:

  · SURFACE — `autoErr`, the auto pipe's own flag. Failures land in it (the
    manual lane keeps `calcErr`), any successful compute clears it, and
    `_ptCalcFoot` renders the tier-2 idiom over the kept last calc:
    `auto-refresh failing · showing last calc · retrying`. Precedence: busy >
    manual error > auto staleness > ok. The deriver is EXECUTED under node —
    the pane-foot arc's standing lesson is that reasoning about a foot
    deriver ships wrong (four rounds, once).
  · DEADLINE ON THE AUTO LANE ONLY (found tracing the filed defect): the
    auto POST had no deadline and `inFlight` releases only in the finally,
    so ONE hung request froze every later auto tick AND the queued manual
    re-fire — the calculator silently bricked until page reload. The write
    exemption does not apply: `auto_refresh=1` NEVER WRITES A DURABLE ROW
    (the pre_trade_log insert rides the gated risk:risk_calculated publish
    — the P3 HIGH-1 pin; the handler is not literally side-effect-free,
    but its set_calculator_symbol/cache touches are synchronous or
    idempotent before the first await, so an abort cannot half-apply them).
    The MANUAL lane is a real row-writing mutation and stays unbounded by
    doctrine; its stuck state is at least visible (the latched spinner).
    ★ The deadline is FLOORED AT THE UPSTREAM BUDGET (audit H-1): the
    handler awaits fetch_orderbook on every call — the third exchange-backed
    polled request in the app — and the bare 5 s poll floor would have
    aborted healthy 6-10 s exchange responses forever, freezing the calc
    harder than the bug this fixes.

Run: pytest tests/test_calc_autorefresh_surface.py -v
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
from tests._srcpin import code as _code  # noqa: E402

_ROOT = Path(__file__).parent.parent
_PT_RAW = (_ROOT / "frontend" / "src" / "pages-pretrade.jsx").read_text(encoding="utf-8")
_PT = _code(_PT_RAW)


def _do_calc(stripped: bool = True) -> str:
    src = _PT if stripped else _PT_RAW
    i = src.index("const doCalculate")
    return src[i:src.index("React.useEffect(() => { autoRateRef.current", i)]


# ── 0. stripper sanity ──────────────────────────────────────────────────────

def test_stripped_source_is_substantial():
    assert "/*" not in _PT and "//" not in _PT
    assert "_ptCalcFoot" in _PT and "autoErr" in _PT


# ── 1. the failure routing ──────────────────────────────────────────────────

class TestAutoFailuresLandSomewhere:
    def test_the_non_ok_branch_routes_by_lane(self):
        body = _do_calc()
        m = re.search(
            r"if \(auto\) setAutoErr\(_ptStrip\(text\) \|\| \('calc failed \(' \+ r\.status \+ '\)'\)\);\s*"
            r"else setCalcErr\(_ptStrip\(text\) \|\| \('calc failed \(' \+ r\.status \+ '\)'\)\);", body)
        assert m, (
            "the non-ok branch no longer routes auto failures into autoErr — "
            "auto refusals are dropped on the floor again (the H7 mechanism)"
        )

    def test_the_catch_routes_by_lane_and_names_a_timeout(self):
        body = _do_calc()
        assert "if (auto) setAutoErr(e && e.timeoutMs != null ? 'deadline' : 'unreachable');" in body
        assert "else setCalcErr('calc failed — engine unreachable?');" in body

    def test_any_successful_compute_clears_BOTH_flags(self):
        """The shared success section clears autoErr AND calcErr (audit L-1:
        a manual refusal followed by an auto success left `calc failed ·
        showing last result` over a result that IS fresh — the mirror of the
        H7 lie). Both clears must sit with setCalc, not inside `if (!auto)`."""
        body = _do_calc()
        i = body.index("setCalc(data);")
        shared = body[i:body.index("calcTickerRef.current = t;", i)]
        assert "setAutoErr(null);" in shared
        assert "setCalcErr(null);" in shared, (
            "calcErr is no longer cleared by a successful auto compute — a "
            "stale manual-failure foot survives a fresh result"
        )
        manual_block = body[body.index("if (!auto) {", i):body.index("_ptWriteJSON(sessionStorage", i)]
        assert "setCalcErr(null)" not in manual_block, (
            "a redundant lane-gated clear is back — the shared one is the "
            "load-bearing site; two copies is how one silently becomes zero"
        )

    def test_no_failure_setter_is_still_manual_gated(self):
        """The mechanism verbatim: `if (!auto) set*Err` in the RESPONSE part
        of the function (the early VALIDATION guards keep it — a half-edited
        form must not error on an auto tick, and the cross-ticker/halt
        returns are by design)."""
        body = _do_calc()
        tail = body[body.index("inFlight.current = true;"):]
        assert "if (!auto) setCalcErr" not in tail, (
            "a response-path failure is manual-gated again — the auto lane "
            "swallows it and the foot reads `calc ok` over a stale calc"
        )


# ── 2. the deadline, auto lane only ─────────────────────────────────────────

class TestTheAutoDeadline:
    def test_the_auto_lane_rides_ptfetch_with_its_own_cadence(self):
        body = _do_calc()
        m = re.search(
            r"const got = await _ptFetch\('/calculator/calculate\?format=json', init,\s*"
            r"Math\.max\(qePollDeadline\(autoRateRef\.current \* 1000\),\s*"
            r"QE_UPSTREAM_READ_DEADLINE_MS\)\);", body)
        assert m, (
            "the auto deadline lost its shape. It must exist (one hung "
            "request re-bricks the calculator: inFlight releases only in the "
            "finally) AND be floored at QE_UPSTREAM_READ_DEADLINE_MS — the "
            "handler awaits fetch_orderbook (ccxt, 10 s default) on every "
            "call, so the bare 5 s poll floor would abort healthy 6-10 s "
            "exchange responses forever (the audit caught this fix violating "
            "the upstream-budget rule written two commits above it)"
        )

    def test_the_manual_lane_stays_a_bare_fetch(self):
        """DELIBERATE asymmetry (doctrine): the manual POST inserts a
        pre_trade_log row — aborting it trades a visibly stuck spinner for
        did-my-write-land ambiguity. If this changes it must be a decision."""
        body = _do_calc()
        assert re.search(
            r"\} else \{\s*r = await fetch\('/calculator/calculate\?format=json', init\);", body)

    def test_the_deadline_timer_is_cleared_after_the_body_read(self):
        """The signal covers r.text() too (a stalled body is a hang); the
        timer must be cleared however the read ends."""
        body = _do_calc()
        assert re.search(
            r"try \{ text = await r\.text\(\); \} finally \{ clearTimeout\(deadline\); \}", body)

    def test_the_cadence_ref_tracks_the_state(self):
        assert "React.useEffect(() => { autoRateRef.current = autoRate; }, [autoRate]);" in _PT, (
            "autoRateRef is no longer synced — the deadline derives from a "
            "frozen cadence after the operator retunes the selector"
        )

    def test_the_unbrick_premise_holds(self):
        """The finally must release inFlight and re-fire a queued manual —
        that is WHY the deadline un-bricks: the rejection reaches a finally
        that puts the machine back."""
        body = _do_calc()
        i = body.index("} finally {")
        tail = body[i:]
        assert "inFlight.current = false;" in tail
        assert "pendingManual.current = false;" in tail
        assert "setTimeout(() => doCalculate(false), 0);" in tail

    def test_the_no_durable_row_premise_still_holds(self):
        """The write-exemption carve-out rests on auto_refresh=1 never
        writing a durable row: the pre_trade_log insert rides the
        `risk:risk_calculated` publish, and the handler gates that publish
        off for auto. STRUCTURAL, not substring — the audit deleted the
        entire gate and the first draft's `"auto_refresh" in src` stayed
        green off the Form() signature. (Precision, also audit-forced: the
        handler is NOT side-effect-free — set_calculator_symbol and the
        market caches are touched — but those are synchronous/idempotent
        before the first await; the durable-row gate is the load-bearing
        half.)"""
        src = (_ROOT / "api" / "routes_calculator.py").read_text(encoding="utf-8")
        m = re.search(
            r'if auto_refresh != "1":\s+await event_bus\.publish\(\s*"risk:risk_calculated"',
            src)
        assert m, (
            "the auto gate around the risk:risk_calculated publish (the "
            "pre_trade_log insert path) changed shape — every 1 s auto tick "
            "may now be writing rows, and the auto deadline is then a "
            "deadline on a WRITE: re-decide it, don't just re-green this"
        )

    def test_the_upstream_budget_premise_still_holds(self):
        """The Math.max floor exists because the handler awaits
        fetch_orderbook before answering. If that call leaves the handler,
        the floor is slack (harmless); if a RETRY LOOP or adapter timeout
        appears around it, re-derive the budget — same premise class as
        test_net_deadline's TestTheUpstreamBudget."""
        src = (_ROOT / "api" / "routes_calculator.py").read_text(encoding="utf-8")
        i = src.index('def calculate_risk')
        body = src[i:src.index("\n@router", i)]
        assert "await fetch_orderbook(ticker)" in body, (
            "calculate_risk no longer awaits fetch_orderbook — the upstream "
            "floor on the auto deadline is now unexplained; re-derive or "
            "annotate"
        )


# ── 3. the surface ──────────────────────────────────────────────────────────

class TestTheFootSurface:
    def test_all_three_result_panes_thread_the_flag(self):
        assert _PT.count("_ptCalcFoot(busy, calcErr, calc, autoErr, autoLive)") == 3
        assert "_ptCalcFoot(busy, calcErr, calc)" not in _PT, (
            "a result pane still derives its foot without the auto flag — "
            "that pane reads `calc ok` over a stale calc"
        )

    def test_clear_resets_the_flag(self):
        i = _PT.index("const doClear")
        body = _PT[i:_PT.index("};", i)]
        assert "setAutoErr(null);" in body


# ── 4. BEHAVIOUR — execute the deriver, don't reason about it ───────────────

_NODE = shutil.which("node")

_JS = """
%SRC%
const CASES = [
  { n: 'busy',            a: [true,  null,  {x:1}, 'boom', true] },
  { n: 'manual_with_last',a: [false, 'err', {x:1}, 'boom', true] },
  { n: 'manual_no_last',  a: [false, 'Ticker is required.', null, null, true] },
  { n: 'auto_stale_live', a: [false, null,  {x:1}, 'deadline', true] },
  { n: 'auto_stale_dormant', a: [false, null, {x:1}, 'deadline', false] },
  { n: 'ok',              a: [false, null,  {x:1}, null, true] },
  { n: 'nothing',         a: [false, null,  null,  null, true] },
  { n: 'autoerr_no_calc', a: [false, null,  null,  'boom', true] },
];
console.log(JSON.stringify(CASES.map(c => ({ n: c.n, r: _ptCalcFoot(...c.a) }))));
"""


@pytest.mark.skipif(_NODE is None, reason="node not on PATH")
class TestFootDerivationExecuted:
    """The pane-foot arc's standing lesson (four wrong rounds, once):
    execute the deriver. Every structural pin above was green through a
    draft whose precedence order put the auto flag above a manual error."""

    @pytest.fixture(scope="class")
    def rows(self, tmp_path_factory):
        i = _PT_RAW.index("const _ptCalcFoot")
        src = _PT_RAW[i:_PT_RAW.index("\n};", i) + 3]
        f = tmp_path_factory.mktemp("calcfoot") / "harness.mjs"
        f.write_text(_JS.replace("%SRC%", src), encoding="utf-8")
        r = subprocess.run([_NODE, str(f)], capture_output=True, text=True,
                           encoding="utf-8", timeout=30)
        assert r.returncode == 0, r.stderr
        return {row["n"]: row["r"] for row in json.loads(r.stdout)}

    def test_the_truth_table(self, rows):
        assert rows["busy"] == {"tone": "sub", "busy": True, "msg": "calculating…"}
        # a MANUAL error outranks the auto flag — it answers the operator's
        # own click, and painting the generic staleness warning over it would
        # bury the specific refusal they just triggered
        assert rows["manual_with_last"] == {"tone": "warn", "msg": "calc failed · showing last result"}
        assert rows["manual_no_last"]["tone"] == "err"
        assert rows["auto_stale_live"] == {"tone": "warn",
                                           "msg": "auto-refresh failing · showing last calc · retrying"}
        assert rows["ok"] == {"tone": "ok", "msg": "calc ok"}
        assert rows["nothing"] == {"tone": "sub", "msg": "no calc yet"}
        # no calc on screen -> nothing is stale; the flag alone must not err
        assert rows["autoerr_no_calc"] == {"tone": "sub", "msg": "no calc yet"}

    def test_a_dormant_lane_keeps_the_staleness_but_drops_the_promise(self, rows):
        """Audit H-2: `· retrying` was a false promise on three reachable
        paths — cadence paused, ticker edited away from the calc'd one, DD
        hard-stop — all of which silently no-op the auto ticks while the
        flag persists. The staleness half must SURVIVE (the calc genuinely
        failed to refresh); only the promise goes."""
        assert rows["auto_stale_dormant"] == {"tone": "warn",
                                              "msg": "auto-refresh failing · showing last calc"}

    def test_the_stale_warning_is_the_tier2_idiom(self, rows):
        msg = rows["auto_stale_live"]["msg"]
        assert "showing last" in msg and "retrying" in msg, (
            "the auto-staleness foot dropped the keep-last-good idiom "
            "(DESIGN.md §5 tier 2: name the failure, say the data is kept, "
            "promise the retry only when the interval really keeps running)"
        )

    def test_autoLive_mirrors_the_auto_lanes_own_guards(self):
        """The suffix's gate must track the SAME conditions that no-op the
        ticks inside doCalculate — cadence, calc'd ticker, halt — or the
        promise drifts from the machine it describes."""
        m = re.search(
            r"const autoLive = !!autoRate && hasCalc\s*"
            r"&& tickerNorm === calcTickerRef\.current && !\(st && st\.halted\);", _PT)
        assert m, "autoLive no longer mirrors the auto lane's own guards"


# ── 5. it reaches the shipped bundle ────────────────────────────────────────

def test_the_fix_reaches_the_emitted_bundle():
    man = json.loads((_ROOT / "static" / "v3" / "manifest.json").read_text(encoding="utf-8"))
    flat = re.sub(r"\s+", "", (_ROOT / "static" / "v3" / man["app"]).read_text(encoding="utf-8"))
    for token in (
        'msg:"auto-refreshfailing\\xB7showinglastcalc"+(autoLive?"\\xB7retrying":"")',
        "Math.max(qePollDeadline(autoRateRef.current*1e3),QE_UPSTREAM_READ_DEADLINE_MS)",
        "_ptCalcFoot(busy,calcErr,calc,autoErr,autoLive)",
    ):
        assert token in flat, (
            f"`{token}` exists in source but not in the emitted bundle — "
            f"rebuild frontend/ (node build.mjs)"
        )
