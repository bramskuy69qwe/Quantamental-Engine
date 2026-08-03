"""Three small truthfulness opens, filed with the warm hang, closed 2026-08-04.

1 · The Risk Monitor Positions gauge printed a confident fabricated `0/20` on
    an empty snapshot (`${positions_open || 0}/${positions_max || 20}`) — an
    affirmative readout with no data behind it. The class grep found a second
    member: the Open Positions summary fabricated its CAP the same way.
    Fix: READOUTS dash until the snapshot delivers; the numeric fallbacks
    survive only as bar GEOMETRY (a gauge cannot draw without a max, and an
    empty bar over a dashed readout is honest). A REAL zero still reads
    `0/20` — `!= null`, not truthiness, or zero open positions dashes too.

2 · Pre-Trade's Regime·ATR pane was the multi-pipe rule's known open
    violation: its Volatility half is entirely CALC-fed while the foot named
    the REGIME pipe alone — a failing calc pipe painted stale ATR under a
    green regime `connected`. Fix: `_ptWorstFoot` reduces two ALREADY-DERIVED
    feet by the ratified severity order (hand-applied per DESIGN.md's own
    interim instruction; the primitives lift stays open). The calc entry
    participates only once that pipe EXISTS — in flight, on screen, or a
    manual error — never off the bare auto flag, whose idle `no calc yet`
    must not outrank a healthy regime pipe.

3 · WatchlistTape rendered mark prices with NO staleness signal. Marks are
    snapshot-enriched only (the SSE merge keeps them as static fields), so
    when the snapshot pipe errs they are frozen. Nav-strip discipline for a
    footless strip: READINGS dash out, cause on the title (_navStaleDash
    shape). uPnL%% keeps rendering — its dominant writer is SSE, a different
    pipe with its own app-wide surface (the WS dot).

The derivers are EXECUTED under node — the pane-foot arc's standing lesson.

Run: pytest tests/test_truthful_readouts.py -v
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
_DASH_RAW = (_ROOT / "frontend" / "src" / "dash-tiled.jsx").read_text(encoding="utf-8")
_DASH = _code(_DASH_RAW)
_PT_RAW = (_ROOT / "frontend" / "src" / "pages-pretrade.jsx").read_text(encoding="utf-8")
_PT = _code(_PT_RAW)
_DESIGN = (_ROOT / "frontend" / "DESIGN.md").read_text(encoding="utf-8")


def test_stripped_sources_are_substantial():
    assert "/*" not in _DASH and "//" not in _DASH
    assert "_ptWorstFoot" in _PT and "markStale" in _DASH


# ── 1 · the fabricated readouts ─────────────────────────────────────────────

class TestPositionsReadoutsDash:
    def _gauge(self) -> str:
        i = _DASH.index('<Gauge label="Positions"')
        return _DASH[i:_DASH.index("/>", i)]

    def test_the_current_readout_is_presence_gated(self):
        g = self._gauge()
        assert "current={rk.positions_open != null ?" in g, (
            "the Positions readout fabricates again — an empty snapshot "
            "prints a confident `0/20`"
        )
        assert "rk.positions_max != null ? rk.positions_max : '—'" in g, (
            "the cap half of the readout fabricates 20 when the snapshot "
            "never delivered a cap"
        )

    def test_geometry_fallbacks_survive_deliberately(self):
        """value/max keep numeric fallbacks — they draw the (empty) bar, and
        a gauge cannot draw without a max. Removing them breaks the render
        for a reason unrelated to truth; the READOUT is the contract."""
        g = self._gauge()
        assert "value={rk.positions_open || 0}" in g
        assert "max={rk.positions_max || 20}" in g

    def test_the_summary_cap_is_presence_gated_too(self):
        """The class's second member, found by grep not filing."""
        assert re.search(
            r"\{rows\.length\} / \{d\.risk\.positions_max != null \? "
            r"d\.risk\.positions_max : '—'\} positions", _DASH), (
            "the Open Positions summary fabricates its cap again"
        )
        assert "/ {d.risk.positions_max || 20} positions" not in _DASH


# ── 2 · the ATR pane joins the multi-pipe rule ──────────────────────────────

class TestAtrPaneMultiPipe:
    def _pane(self) -> str:
        i = _PT.index('<Pane title="Regime · ATR Volatility"')
        return _PT[i:i + 900]

    def test_the_foot_reduces_both_pipes(self):
        p = self._pane()
        assert "_ptWorstFoot([" in p, (
            "the ATR pane foots one pipe again — a failing calc pipe paints "
            "stale ATR under a green regime `connected` (the multi-pipe "
            "rule's formerly-known violation, reopened)"
        )
        assert "failed: !!netRegime.err" in p
        assert "failed: !!(calcErr || autoErr)" in p, (
            "the calc entry lost its own failed flag — tone alone conflates "
            "errored-with-data with merely-delayed"
        )

    def test_the_calc_entry_participates_only_once_the_pipe_exists(self):
        p = self._pane()
        assert "foot={(busy || calc != null || calcErr != null)" in p, (
            "the participation gate changed — with no calc on screen "
            "_ptCalcFoot reads idle `no calc yet`, which must not outrank a "
            "healthy regime pipe (and the bare auto flag must not resurrect "
            "it either)"
        )

    def test_the_pre_calc_lane_keeps_the_plain_regime_foot(self):
        assert ": qeFootState({ loading: netRegime.ms == null && !netRegime.err" in self._pane()


# ── 3 · the tape's marks ────────────────────────────────────────────────────

class TestTapeMarkStaleness:
    def _tape(self) -> str:
        i = _DASH.index("const WatchlistTape")
        return _DASH[i:_DASH.index("const DashTiled")]

    def test_staleness_derives_from_the_marks_own_pipe(self):
        t = self._tape()
        assert "const markStale = !!(d.net.snapshot && d.net.snapshot.err);" in t, (
            "the tape lost its staleness derivation — frozen marks render "
            "as live again"
        )

    def test_stale_marks_dash_in_both_value_and_format(self):
        """LiveValue renders through BOTH props; dashing one leaves the other
        painting the frozen number on the next morph."""
        t = self._tape()
        assert "value={markStale || r.mark == null ? '—' : r.mark}" in t
        assert "format={(x) => (markStale || r.mark == null ? '—' : _loc(x, 2))}" in t

    def test_the_dash_carries_its_cause(self):
        """The _navStaleDash shape: a footless strip's tier-3 blank names the
        dead endpoint on the title."""
        assert "title={markStale ? 'mark stale — /api/dashboard/snapshot failing' : undefined}" in self._tape()

    def test_the_pct_keeps_rendering(self):
        """uPnL%'s dominant writer is SSE — a different pipe. Gating it on the
        snapshot flag would dash a live reading."""
        t = self._tape()
        m = re.search(r"value=\{r\.pct != null \? r\.pct : 0\}", t)
        assert m, "the pct LiveValue changed shape — re-check it is NOT markStale-gated"
        assert "markStale" not in t[m.start() - 80:m.start()], (
            "the pct reading is gated on the MARK's pipe"
        )


# ── 4 · BEHAVIOUR — execute the derivers ────────────────────────────────────

_NODE = shutil.which("node")

_JS = """
// stub for the empty-entries guard's fallback (the real one lives in
// primitives; only its shape matters here)
const qeFootState = (o) => ({ tone: 'sub', busy: true, msg: 'loading…' });
%RANK%
const F = (tone, busy) => ({ tone, busy: !!busy, msg: tone });
const CASES = [
  // [regime entry, calc entry] -> which wins
  { n: 'calc_err_beats_regime_ok',
    e: [{ foot: F('ok'), failed: false }, { foot: F('err'), failed: true }] },
  { n: 'regime_err_beats_calc_warn',
    e: [{ foot: F('err'), failed: true }, { foot: F('warn'), failed: true }] },
  { n: 'cold_busy_beats_warn_failed',
    e: [{ foot: F('warn'), failed: true }, { foot: F('sub', true), failed: false }] },
  // busy WITH data = a refresh over a shown result. It must NOT mask a
  // degraded sibling (audit F1: a manual recalc hid a failing regime pipe
  // for the POST's duration — a masking window the single-pipe foot never
  // had), but still surfaces over a merely-healthy one.
  { n: 'warn_failed_beats_refresh_busy',
    e: [{ foot: { tone: 'sub', busy: true, msg: 'calculating…', hasData: true }, failed: false },
        { foot: { tone: 'warn', msg: 'regime-degraded' }, failed: true }] },
  { n: 'refresh_busy_beats_ok',
    e: [{ foot: F('ok'), failed: false },
        { foot: { tone: 'sub', busy: true, msg: 'calculating…', hasData: true }, failed: false }] },
  { n: 'warn_failed_beats_warn_plain',
    e: [{ foot: { tone: 'warn', msg: 'delayed' }, failed: false },
        { foot: { tone: 'warn', msg: 'errored-with-data' }, failed: true }] },
  { n: 'warn_beats_ok',
    e: [{ foot: F('ok'), failed: false }, { foot: F('warn'), failed: false }] },
  { n: 'idle_sub_beats_ok',
    e: [{ foot: F('ok'), failed: false }, { foot: F('sub'), failed: false }] },
  { n: 'tie_keeps_first',
    e: [{ foot: { tone: 'ok', msg: 'first' }, failed: false },
        { foot: { tone: 'ok', msg: 'second' }, failed: false }] },
];
const out = CASES.map(c => ({ n: c.n, r: _ptWorstFoot(c.e) }));
// the empty-entries guard: this runs in a pane's render OUTSIDE
// PaneErrorBoundary — a throw takes down the whole workspace subtree
try { out.push({ n: 'empty_entries', r: _ptWorstFoot([]) }); }
catch (e) { out.push({ n: 'empty_entries', r: { tone: 'THREW', msg: String(e).slice(0, 60) } }); }
console.log(JSON.stringify(out));
"""

_JS_READOUT = """
const CASES = [
  { n: 'empty',       rk: {} },
  { n: 'real_zero',   rk: { positions_open: 0, positions_max: 20 } },
  { n: 'normal',      rk: { positions_open: 2, positions_max: 20 } },
  { n: 'cap_missing', rk: { positions_open: 2 } },
];
console.log(JSON.stringify(CASES.map(({ n, rk }) => ({ n, r: %EXPR% }))));
"""


@pytest.mark.skipif(_NODE is None, reason="node not on PATH")
class TestExecuted:
    def test_worst_of_semantics(self, tmp_path):
        i = _PT_RAW.index("const _ptFootRank")
        rank = _PT_RAW[i:_PT_RAW.index("const PT_STATE_MS")]
        f = tmp_path / "rank.mjs"
        f.write_text(_JS.replace("%RANK%", rank), encoding="utf-8")
        r = subprocess.run([_NODE, str(f)], capture_output=True, text=True,
                           encoding="utf-8", timeout=30)
        assert r.returncode == 0, r.stderr
        rows = {row["n"]: row["r"] for row in json.loads(r.stdout)}
        assert rows["calc_err_beats_regime_ok"]["tone"] == "err"
        assert rows["regime_err_beats_calc_warn"]["tone"] == "err"
        assert rows["cold_busy_beats_warn_failed"]["tone"] == "sub", (
            "a pipe still TRYING (nothing usable yet) lost to one showing "
            "last data — the ratified order puts never-answered above "
            "errored-with-data"
        )
        assert rows["warn_failed_beats_refresh_busy"]["msg"] == "regime-degraded", (
            "a refresh over a SHOWN result masks a degraded sibling again — "
            "audit F1's masking window is back"
        )
        assert rows["refresh_busy_beats_ok"]["msg"] == "calculating…", (
            "a refresh no longer surfaces over a merely-healthy sibling"
        )
        # asserted by MSG, not tone — both entries are warn, so a flattened
        # ranking ties them and the reduce keeps the first (the plain one).
        # The first draft asserted tone only, plus a literal `or True`; the
        # mutation sweep caught it surviving a dead `&& failed` branch.
        assert rows["warn_failed_beats_warn_plain"]["msg"] == "errored-with-data", (
            "the two warn flavours rank equal — `X · showing last data` no "
            "longer outranks `delayed [Nms]`, so a merely slow sibling masks "
            "a failing pipe (the pane-foot arc's R3 mistake, back again)"
        )
        assert rows["warn_beats_ok"]["tone"] == "warn"
        assert rows["idle_sub_beats_ok"]["tone"] == "sub"
        assert rows["tie_keeps_first"]["msg"] == "first", (
            "ties no longer keep the FIRST entry — the regime pipe is listed "
            "first on purpose (its ms-bearing foot beats a bare 'calc ok')"
        )
        assert rows["empty_entries"]["tone"] == "sub", (
            f"_ptWorstFoot([]) -> {rows['empty_entries']} — it runs in the "
            f"pane's render OUTSIDE PaneErrorBoundary, so a throw takes down "
            f"the whole workspace subtree, not one tile"
        )

    def test_the_positions_readout_expression(self, tmp_path):
        """Execute the EXACT current-expression from source. The load-bearing
        case is real_zero: `!= null` prints an honest 0/20 where truthiness
        would dash a real reading."""
        i = _DASH_RAW.index('current={rk.positions_open != null ?')
        expr = _DASH_RAW[i + len("current={"):_DASH_RAW.index("} maxLabel", i)]
        f = tmp_path / "readout.mjs"
        f.write_text(_JS_READOUT.replace("%EXPR%", expr), encoding="utf-8")
        r = subprocess.run([_NODE, str(f)], capture_output=True, text=True,
                           encoding="utf-8", timeout=30)
        assert r.returncode == 0, r.stderr
        rows = {row["n"]: row["r"] for row in json.loads(r.stdout)}
        assert rows["empty"] == "—", "an empty snapshot fabricates a readout again"
        assert rows["real_zero"] == "0/20", (
            "a REAL zero dashes — the gate went truthy instead of != null, "
            "hiding an honest reading"
        )
        assert rows["normal"] == "2/20"
        assert rows["cap_missing"] == "2/—"


# ── 5 · the doctrine reflects the closures ──────────────────────────────────

def test_design_md_no_longer_lists_the_atr_pane_as_open():
    assert "is a known open violation" not in _DESIGN
    seg = _DESIGN[_DESIGN.index("Scope caveat"):]
    assert "closed 2026-08-04" in seg[:800]


def test_design_md_no_longer_lists_the_fabrications_as_open():
    assert "so an empty\n  snapshot shows a confident" not in _DESIGN
    i = _DESIGN.index("THE READ DEADLINE")
    seg = _DESIGN[i:i + 6000]
    assert "fabrications filed alongside it were closed" in seg


# ── 6 · it reaches the shipped bundle ───────────────────────────────────────

def test_the_fix_reaches_the_emitted_bundle():
    man = json.loads((_ROOT / "static" / "v3" / "manifest.json").read_text(encoding="utf-8"))
    flat = re.sub(r"\s+", "", (_ROOT / "static" / "v3" / man["app"]).read_text(encoding="utf-8"))
    for token in (
        "_ptWorstFoot([",
        "constmarkStale=!!(d.net.snapshot&&d.net.snapshot.err)",
        # the readout expression's core — prop order is esbuild's business
        "rk.positions_open!=null?`${rk.positions_open}/${rk.positions_max!=null?rk.positions_max:",
        'hasData:calc!=null',   # the busy foot's cold-vs-refresh split (audit F1)
    ):
        assert token in flat, (
            f"`{token}` exists in source but not in the emitted bundle — "
            f"rebuild frontend/ (node build.mjs)"
        )
