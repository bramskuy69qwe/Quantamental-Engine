"""Every Dashboard pane's foot must cover EVERY pipe its body reads.

The bug (found by the class sweep during the nav-strip fix, 2026-07-31):
RiskMonitorPane derived its foot from `/api/state` while FOUR of its five
readouts — Net Exposure, Drawdown 30d, Weekly Loss, Positions — come from
`/api/dashboard/snapshot`. A snapshot outage therefore painted four stale risk
gauges under a green `connected [Nms]` foot.

That is a category worse than the two staleness bugs fixed before it. The
service worker and the nav strip showed stale data with NO signal; this showed
stale data with an AFFIRMATIVE HEALTHY one. An operator who learned to trust
the foot is worse off than one who never had it.

WHY THIS FILE PINS A PROPERTY, NOT A PANE. "Does this pane pass the right key?"
is a fact about one line that the next pane will get wrong again — and no
existing test could catch it, because every foot WAS present and every foot DID
derive through qeFootState. The invariant that actually holds is:

    foot_sources(pane) ⊇ pipes_read_by(pane_body)

so this file derives both sides from the source and asserts containment for
EVERY pane. A new pane that reads a source it does not report fails here
without anyone remembering this bug. The field→pipe map is itself checked
against the store's loaders, and an unknown field is a hard error rather than a
silent skip — otherwise the pin goes blind exactly when the store grows.

Run: pytest tests/test_dash_foot_covers_its_sources.py -v
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
_DASH = _code((_ROOT / "frontend" / "src" / "dash-tiled.jsx").read_text(encoding="utf-8"))
_DESIGN = (_ROOT / "frontend" / "DESIGN.md").read_text(encoding="utf-8")

# state field → the loader (pipe) that writes it. Verified against the loaders
# themselves by TestTheFieldMapMatchesTheStore below, so it cannot silently rot.
_FIELD_PIPE = {
    "equity": "snapshot", "risk": "snapshot", "journal": "snapshot",
    "regime": "snapshot", "positions": "snapshot", "loaded": "snapshot",
    "st": "st",
    "macro": "macro",
    "log": "log",
}
# Fields that are not fetched from anywhere: local UI state, the net-tracking
# map itself, and the log's paging cursor.
_NOT_A_PIPE = {"ui", "net", "logCursor"}


def _components() -> dict[str, str]:
    """Every top-level `const X = () => {...}` component body, by name.

    Each body ends at the NEXT top-level declaration of any kind, not at the
    next arrow-component: the tile registry that follows EngineLogPane is a
    plain `const`, and slicing past it made that pane appear to render every
    other pane as a child (its registry entries are `<RiskMonitorPane/>` etc.),
    which reported a bogus missing-coverage failure.
    """
    # `(...)` not `()`: the positions table's leaves take props
    # (`const PosMark = ({ r }) => {…}`) and a `()`-only regex skips them, so a
    # prop-taking leaf reading an unreported pipe would never be checked.
    starts = [(m.group(1), m.start()) for m in
              re.finditer(r"^const (\w+) = \(([^)]*)\) => \{", _DASH, re.M)]
    assert starts, "no components parsed — the file shape changed"
    bounds = [m.start() for m in
              re.finditer(r"^(?:const|function|let|var|class)\s", _DASH, re.M)]
    out = {}
    for name, pos in starts:
        later = [b for b in bounds if b > pos]
        out[name] = _DASH[pos:(min(later) if later else len(_DASH))]
    return out


def _panes() -> dict[str, str]:
    return {n: b for n, b in _components().items() if "<Pane " in b or "foot=" in b}


def _foot_sources(body: str) -> str | None:
    """The raw source-list text of a pane's foot call, or None if it has none."""
    m = re.search(r"_dashFootWorst\(d, \[(.*?)\]\)", body, re.S)
    if m:
        return m.group(1)
    m = re.search(r"_dashFoot\(d, '[^']+',", body)
    if m:
        seg = body[m.start():]
        return seg[:seg.index("\n")]
    return None


def _foot_pipes(body: str) -> set[str] | None:
    """The STORE pipes a pane's foot reports, or None if it has no derived foot.

    A source list may also carry a raw {err, ms} for a pipe the pane owns
    itself (EquityCurvePane's chart child) — those are not store keys and are
    deliberately not returned; coverage below only reasons about store pipes.
    """
    m = re.search(r"_dashFootWorst\(d, \[(.*?)\]\)", body, re.S)
    if m:
        return set(re.findall(r"src: '([^']+)'", m.group(1)))
    m = re.search(r"_dashFoot\(d, '([^']+)'", body)
    return {m.group(1)} if m else None


def _leaf_children(body: str) -> set[str]:
    """Component names this pane renders as JSX children.

    dash-tiled's whole architecture is leaf subscription — TiledGrid is memoized
    and renders once, so live values flow through LEAF components that call
    useDash() themselves. A pane whose CHILD reads an unreported pipe has the
    same defect as one that reads it directly, and scanning only the pane's own
    text misses it entirely (proven: that mutation survived the first draft of
    this file).
    """
    return set(re.findall(r"<(\w[\w]*)\b", body))


def _direct_pipes(body: str) -> set[str]:
    """Pipes read in this component's own text, via `d.<field>`."""
    pipes = set()
    for field in set(re.findall(r"\bd\.(\w+)", body)):
        if field in _NOT_A_PIPE:
            continue
        assert field in _FIELD_PIPE, (
            f"unmapped QE_DASH field `d.{field}` — add it to _FIELD_PIPE (with "
            f"its owning loader) or to _NOT_A_PIPE. Left unmapped, every "
            f"coverage assertion below silently stops covering it."
        )
        pipes.add(_FIELD_PIPE[field])
    return pipes


def _read_pipes(body: str) -> set[str]:
    """Every pipe a pane surfaces — its own reads UNION its leaf children's.

    Transitive by one level, which is what this file's architecture actually
    uses (panes render leaves; leaves subscribe). Deeper nesting would need a
    real graph walk; if that appears, extend this rather than trusting it.
    """
    comps = _components()
    pipes = _direct_pipes(body)
    for child in _leaf_children(body):
        if child in comps and comps[child] is not body:
            pipes |= _direct_pipes(comps[child])
    return pipes


# ── 0. the stripper is not vacuous ──────────────────────────────────────────

def test_stripped_source_is_substantial():
    """C1's lesson: an unterminated `/*` inside a `//` comment truncates
    `_code()` to nothing and every assertion here would pass against it."""
    assert len([ln for ln in _DASH.splitlines() if ln.strip()]) > 300
    assert "//" not in _DASH and "/*" not in _DASH


# ── 1. the map this file reasons with matches the store ─────────────────────

class TestTheFieldMapMatchesTheStore:
    """If the loaders and _FIELD_PIPE disagree, every coverage assertion below
    is reasoning about a store that no longer exists."""

    @pytest.mark.parametrize("loader,pipe", [
        ("loadSnapshot", "snapshot"), ("loadState", "st"),
        ("loadMacro", "macro"), ("loadLog", "log"),
    ])
    def test_each_loader_writes_exactly_the_fields_mapped_to_it(self, loader, pipe):
        i = _DASH.index(f"async function {loader}(")
        body = _DASH[i:_DASH.index("\n  }", i)]
        written = set(re.findall(r"state\.(\w+) =", body))
        written -= _NOT_A_PIPE
        expected = {f for f, p in _FIELD_PIPE.items() if p == pipe}
        assert written == expected, (
            f"{loader} writes {sorted(written)} but _FIELD_PIPE maps "
            f"{sorted(expected)} to '{pipe}'"
        )

    def test_every_pipe_is_tracked_for_foot_state(self):
        """Slice the net map's own LINE — `_DASH.index('}')` from the start of
        `net: {` lands on the first inner `{}` and would report only the first
        pipe, making this pass while proving nothing."""
        line = next(ln for ln in _DASH.splitlines() if "net: {" in ln)
        tracked = set(re.findall(r"(\w+): \{\}", line))
        assert tracked == set(_FIELD_PIPE.values()), (
            f"net tracks {sorted(tracked)} but the field map names pipes "
            f"{sorted(set(_FIELD_PIPE.values()))}"
        )


# ── 2. THE INVARIANT ────────────────────────────────────────────────────────

class TestEveryFootCoversEverySourceItsPaneReads:
    def test_at_least_the_known_panes_are_discovered(self):
        """Guards the parser: if _panes() silently returned {}, the
        parametrized invariant below would vacuously pass with zero cases."""
        found = set(_panes())
        for name in ("RiskMonitorPane", "EquityStatsPane", "OpenPositionsPane",
                     "MacroSignalsPane", "MonthlyPane", "ActiveParamsPane",
                     "EngineLogPane", "EquityCurvePane"):
            assert name in found, f"{name} not discovered by the parser"

    def test_no_pane_declared_in_the_file_escapes_the_parser(self):
        """A pane the parser misses is UNCOVERED and invisible — the whole
        invariant silently stops applying to it. Compare against every
        `*Pane` declaration in the raw source."""
        declared = set(re.findall(r"^const (\w+Pane) = ", _DASH, re.M))
        assert declared, "no *Pane declarations found — file shape changed"
        assert declared <= set(_components()), (
            f"parser missed {sorted(declared - set(_components()))}"
        )

    @pytest.mark.parametrize("pane", sorted(_panes()))
    def test_a_pane_that_reads_a_pipe_must_have_a_foot(self, pane):
        """Dropping a foot entirely is a WORSE regression than mis-keying one —
        it is the stale-data-with-no-signal class the service-worker and
        nav-strip fixes just closed. Skipping footless panes made the file's
        invariant vacuously satisfiable by removing the foot, so this asserts
        first."""
        body = _panes()[pane]
        if _read_pipes(body):
            assert _foot_pipes(body) is not None, (
                f"{pane} renders live data with no derived foot — the operator "
                f"gets stale values with no signal at all"
            )

    @pytest.mark.parametrize("pane", sorted(_panes()))
    def test_foot_reports_every_pipe_the_body_reads(self, pane):
        body = _panes()[pane]
        declared = _foot_pipes(body)
        if declared is None:
            pytest.skip(f"{pane} has no derived foot")
        read = _read_pipes(body)
        missing = read - declared
        assert not missing, (
            f"{pane} reads {sorted(missing)} but its foot reports only "
            f"{sorted(declared)}. An outage on {sorted(missing)} would paint "
            f"stale values under a healthy foot — an affirmative WRONG signal, "
            f"which is worse than no signal (DESIGN.md multi-pipe rule)."
        )

    @pytest.mark.parametrize("pane", sorted(_panes()))
    def test_foot_does_not_claim_pipes_the_body_never_reads(self, pane):
        """The mirror failure: over-declaring makes a pane go red for an outage
        that cannot affect anything it shows."""
        body = _panes()[pane]
        declared = _foot_pipes(body)
        if declared is None:
            pytest.skip(f"{pane} has no derived foot")
        assert not (declared - _read_pipes(body)), pane


# ── 3. the specific regression ──────────────────────────────────────────────

class TestRiskMonitorReportsBothPipes:
    """The site that motivated the rule. Pinned by name as well as by the
    invariant, so the failure message names THIS bug if it ever returns."""

    def test_it_reports_snapshot_and_state(self):
        assert _foot_pipes(_panes()["RiskMonitorPane"]) == {"snapshot", "st"}

    def test_its_gauges_really_are_snapshot_fed(self):
        """The premise. If these moved to /api/state the fix would be wrong."""
        body = _panes()["RiskMonitorPane"]
        assert "const rk = d.risk" in body
        for gauge in ("Net Exposure", "Drawdown 30d", "Weekly Loss", "Positions"):
            assert gauge in body, gauge
        assert "rk.exposure_pct" in body and "rk.drawdown_pct" in body
        assert "rk.positions_open" in body and "d.equity.weekly_pnl_pct" in body

    def test_each_pipe_carries_its_own_hasdata(self):
        """The correction the adversarial review forced. One OR'd hasData
        judges every pipe by another pipe's data, and `qeFootState` pivots BOTH
        its tier-4 gate and its 2-vs-3 split on it — so an OR'd flag made a
        never-answered pipe render green off its healthy sibling."""
        srcs = _foot_sources(_panes()["RiskMonitorPane"])
        assert "{ src: 'snapshot', hasData: d.loaded }" in srcs, srcs
        assert re.search(r"\{ src: 'st', hasData: d\.st && d\.st\.dd_state != null \}", srcs), srcs

    def test_the_snapshot_pipe_is_not_judged_by_the_state_pipe(self):
        """Guards the specific inversion: no `||` joining the two hasData
        expressions, which is exactly how the broken draft read."""
        srcs = _foot_sources(_panes()["RiskMonitorPane"])
        for entry in re.findall(r"hasData: ([^,}]+)", srcs):
            assert "||" not in entry, (
                f"hasData `{entry.strip()}` ORs across pipes — each pipe must "
                f"be judged on its own data"
            )


class TestEquityCurveReportsBothPipes:
    """The half of the fix that closes both round-1 HIGHs, pinned by name.

    The invariant above CANNOT see this pane: its chart pipe is a raw
    `{err, ms}` owned by the component (not a QE_DASH net key), so it is
    invisible to `_foot_pipes` and to `_direct_pipes` alike — declaring
    {snapshot} alone satisfies containment in both directions. Verified by
    mutation: deleting the chart source, or collapsing the pane back to
    `_dashFoot(d, 'snapshot', …)`, left the whole file green. Both restore
    filed defects (a green foot over a body reading "Loading equity…", and a
    tier-3 → tier-2 downgrade over a chart showing nothing).
    """

    def _srcs(self) -> str:
        return _foot_sources(_panes()["EquityCurvePane"])

    def test_it_reports_the_snapshot_pipe(self):
        assert "{ src: 'snapshot', hasData: c != null }" in self._srcs(), self._srcs()

    def test_it_still_reports_its_own_chart_pipe(self):
        assert re.search(r"\{ src: net, hasData: net\.ms != null \}", self._srcs()), (
            "the chart's own pipe was dropped from the foot — a failed or "
            "never-answered equity_ohlc fetch would be reported as healthy off "
            "the snapshot pipe"
        )

    def test_the_chart_hasdata_is_not_ORd_with_the_snapshot(self):
        """Its hasData must stay exactly what it was before this change; OR'ing
        in `c != null` is the round-1 CRIT mechanism at the one pane the
        invariant cannot police."""
        for entry in re.findall(r"hasData: ([^,}]+)", self._srcs()):
            assert "||" not in entry, entry


# ── 4. the worst-of derivation ──────────────────────────────────────────────

class TestWorstOfSemantics:
    def _helper(self) -> str:
        i = _DASH.index("const _dashFootWorst")
        return _DASH[i:_DASH.index("const _dashFoot =", i)]

    def test_severity_splits_the_two_warn_flavours_around_sub(self):
        """Ranking on TONE alone is wrong: `warn` covers both "errored ·
        showing last data" and a merely slow "delayed [Nms]", and a
        never-answered pipe belongs BETWEEN them. Tone-ranking let any >500ms
        sibling mask a hung pipe with `delayed`, an affirmative claim that data
        arrived."""
        i = _DASH.index("const _FOOT_SEVERITY")
        body = _DASH[i:_DASH.index("const _dashFootWorst")]
        order = [
            body.index("'err' ? 0"),
            body.index("'sub' ? 1"),
            body.index("&& failed ? 2"),
            body.index("'warn' ? 3"),
        ]
        assert order == sorted(order), (
            "severity order changed. Both `warn` flavours assert data is on "
            "screen, so a never-answered pipe must outrank BOTH: "
            "err > sub > errored-with-data > delayed > ok"
        )
        assert "_FOOT_RANK" not in _DASH, "the tone-only ranking is back"

    def test_an_empty_source_list_cannot_throw(self):
        """The foot is computed in the PANE's render, outside Pane's
        PaneErrorBoundary, so a throw takes down the whole grid subtree rather
        than one tile."""
        h = self._helper()
        assert "if (!sources || !sources.length)" in h
        assert h.index("if (!sources") < h.index(".map(")

    def test_the_foot_is_derived_PER_PIPE_then_reduced(self):
        """The shape correction: qeFootState must be called once per source,
        inside the map, not once over merged inputs."""
        h = self._helper()
        assert "sources.map(({ src, hasData })" in h
        # exactly one derivation INSIDE the map — the other qeFootState call in
        # this helper is the empty-source-list guard, which never sees a pipe
        mapped = h[h.index("sources.map("):h.index("derived.reduce(")]
        assert mapped.count("qeFootState(") == 1, "derived once per pipe"
        assert "hasData: answered && !!hasData" in mapped
        assert "derived.reduce(" in h

    def test_hasdata_is_void_until_the_pipe_has_answered(self):
        """The callers' hasData are PROXIES with a second writer (SSE writes
        st.dd_state and equity.total_equity straight into the store), so taking
        them at face value let a hung poll satisfy qeFootState's tier-4 gate."""
        h = self._helper()
        assert "const answered = n.ms != null || !!n.err;" in h
        assert "loading: !answered" in h
        assert "hasData: answered && !!hasData" in h

    def test_severity_is_compared_before_the_ms_tie_break(self):
        h = self._helper()
        assert "_FOOT_SEVERITY(a) - _FOOT_SEVERITY(b)" in h
        assert h.index("_FOOT_SEVERITY(a)") < h.index("a.ms >= b.ms")

    def test_ties_then_break_to_the_slower_pipe(self):
        """A fast pipe must not flatter `connected [Nms]`. (A slow pipe already
        surfaces on its own — >500ms is a warn — so no max() is needed.)"""
        assert "a.ms >= b.ms ? a : b" in self._helper()

    def test_single_pipe_panes_share_the_same_derivation_path(self):
        """One code path, so the six single-pipe panes cannot drift from the
        multi-pipe semantics."""
        i = _DASH.index("const _dashFoot =")
        assert "_dashFootWorst(d, [{ src: key, hasData }])" in _DASH[i:i + 200]

    def test_no_pane_derives_a_foot_outside_these_helpers(self):
        """A hand-rolled qeFootState call in a pane would bypass the rule."""
        for name, body in _panes().items():
            assert "qeFootState(" not in body, (
                f"{name} builds a foot by hand; route it through _dashFoot / "
                f"_dashFootWorst so the multi-pipe rule applies"
            )


# ── 4b. BEHAVIOUR: run the real derivation, do not reason about it ─────────

_NODE = shutil.which("node")

_JS_DRIVER = """
const CASES = %s;
const out = CASES.map((c) => {
  const d = { net: c.net };
  const worst = _dashFootWorst(d, c.sources);
  const single = c.sources.length === 1
    ? qeFootState({
        loading: (c.net[c.sources[0].src] || {}).ms == null
                 && !(c.net[c.sources[0].src] || {}).err,
        err: (c.net[c.sources[0].src] || {}).err,
        hasData: !!c.sources[0].hasData,
        ms: (c.net[c.sources[0].src] || {}).ms, retrying: true })
    : null;
  return { name: c.name, tone: worst.tone, msg: worst.msg,
           busy: !!worst.busy, single };
});
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(_NODE is None, reason="node not on PATH")
class TestFootBehaviourExecuted:
    """The pin that would have caught the bug this file's first draft shipped.

    That draft passed ONE OR'd hasData for N pipes. Every structural pin was
    green, the reasoning in the comment read correctly, and the behaviour was
    wrong: `qeFootState` gates tier 4 behind `loading && !hasData`, so a pipe
    that had never answered was judged by its healthy sibling's data and
    rendered green `connected [Nms]` — the exact failure the helper exists to
    prevent, with the ms measured on the wrong pipe.

    Structure pins cannot catch that. So extract the REAL qeFootState and the
    REAL _dashFootWorst from source and execute them.
    """

    @staticmethod
    def _run(cases, tmp_path):
        prim = (_ROOT / "frontend" / "src" / "primitives.jsx").read_text(encoding="utf-8")
        dash_raw = (_ROOT / "frontend" / "src" / "dash-tiled.jsx").read_text(encoding="utf-8")
        js = (
            prim[prim.index("const qeFootCause"):prim.index("// PaneFoot —")]
            + dash_raw[dash_raw.index("const _FOOT_SEVERITY"):dash_raw.index("const _dashFoot =")]
            + _JS_DRIVER % json.dumps(cases)
        )
        f = tmp_path / "foot_harness.mjs"
        f.write_text(js, encoding="utf-8")
        r = subprocess.run([_NODE, str(f)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return {row["name"]: row for row in json.loads(r.stdout)}

    def test_the_truth_table(self, tmp_path):
        NET_OK, NET_SLOW = {"ms": 20}, {"ms": 640}
        NEVER = {}
        ERR_NET = {"err": {"status": 0}}
        cases = [
            # THE CRIT: a pipe that never answered, beside a healthy one.
            {"name": "never+healthy", "net": {"a": NEVER, "b": NET_OK},
             "sources": [{"src": "a", "hasData": False}, {"src": "b", "hasData": True}]},
            # errored with nothing to show → tier 3, cause named
            {"name": "err_nodata+healthy", "net": {"a": ERR_NET, "b": NET_OK},
             "sources": [{"src": "a", "hasData": False}, {"src": "b", "hasData": True}]},
            # errored but its own data still on screen → tier 2
            {"name": "err_withdata+healthy", "net": {"a": ERR_NET, "b": NET_OK},
             "sources": [{"src": "a", "hasData": True}, {"src": "b", "hasData": True}]},
            # a slow pipe must surface even beside a fast one
            {"name": "slow+fast", "net": {"a": NET_SLOW, "b": NET_OK},
             "sources": [{"src": "a", "hasData": True}, {"src": "b", "hasData": True}]},
            # both healthy → report the slower reading, never the flattering one
            {"name": "fast+faster", "net": {"a": {"ms": 30}, "b": {"ms": 5}},
             "sources": [{"src": "a", "hasData": True}, {"src": "b", "hasData": True}]},
            # ── the second CRIT route: hasData TRUE on a pipe that never
            # answered. Every never-answered case above carries hasData False,
            # which is precisely why the first executed truth table was blind
            # to it. The callers' hasData are PROXIES with a second writer —
            # SSE sets st.dd_state and equity.total_equity directly — so a hung
            # poll still satisfies them.
            {"name": "never_but_hasdata+healthy",
             "net": {"a": NEVER, "b": NET_OK},
             "sources": [{"src": "a", "hasData": True}, {"src": "b", "hasData": True}]},
            # ── a FAILING pipe must not be masked by a merely SLOW one: both
            # derive `warn`, and ranking on ms alone printed `delayed [640ms]`
            # while dropping the outage entirely.
            {"name": "failing+slow",
             "net": {"a": {"ms": 30, "err": {"status": 0}}, "b": NET_SLOW},
             "sources": [{"src": "a", "hasData": True}, {"src": "b", "hasData": True}]},
            # ── a never-answered pipe beside a merely SLOW one. No case above
            # pairs those two, which is how a tone-only ranking shipped: `warn`
            # outranked `sub`, so a >500ms sibling masked a hung pipe and the
            # foot printed `delayed [640ms]` — an affirmative claim that data
            # ARRIVED. `_ptJson` has no timeout, so the hang is not transient.
            {"name": "never+slow", "net": {"a": NEVER, "b": NET_SLOW},
             "sources": [{"src": "a", "hasData": True}, {"src": "b", "hasData": True}]},
            # ── a never-answered pipe beside one that ERRORED but still has
            # data on screen. `… · showing last data` is a STRONGER affirmative
            # claim than `delayed`, so it must not win over a pipe with no data
            # at all — the body beneath is meanwhile rendering a fabricated
            # `0/20` for Positions and the literal string "Loading equity…".
            # Follows the doctrine's own tiering: 3 and 4 alike have nothing
            # usable to show, 2 does.
            {"name": "never+failing_withdata",
             "net": {"a": NEVER, "b": {"ms": 30, "err": {"status": 500}}},
             "sources": [{"src": "a", "hasData": False}, {"src": "b", "hasData": True}]},
            # but a pipe with NOTHING and a named cause still outranks it
            {"name": "never+errored_cold",
             "net": {"a": NEVER, "b": {"err": {"status": 404}}},
             "sources": [{"src": "a", "hasData": False}, {"src": "b", "hasData": False}]},
        ]
        r = self._run(cases, tmp_path)

        assert r["never_but_hasdata+healthy"]["tone"] == "sub", (
            "a pipe that has NEVER answered reports "
            f"{r['never_but_hasdata+healthy']['tone']}/"
            f"{r['never_but_hasdata+healthy']['msg']} once something else "
            "(SSE) has painted a value its hasData proxy reads — the CRIT via "
            "its second route"
        )
        assert "20ms" not in r["never_but_hasdata+healthy"]["msg"], (
            "the foot is carrying the SIBLING's latency for a pipe that has "
            "never reported one"
        )

        assert r["failing+slow"]["tone"] == "warn"
        assert "showing last data" in r["failing+slow"]["msg"], (
            f"a real failure was masked by a slow sibling: "
            f"{r['failing+slow']['msg']}"
        )

        assert r["never+slow"]["tone"] == "sub", (
            f"a hung pipe was masked by a merely slow sibling and reported "
            f"{r['never+slow']['msg']!r} — an affirmative claim that data "
            f"arrived, over a pipe that has never reported"
        )
        assert "640" not in r["never+slow"]["msg"]

        assert r["never+failing_withdata"]["tone"] == "sub", (
            f"a pipe with NO data lost to one asserting `showing last data`: "
            f"{r['never+failing_withdata']['msg']!r}"
        )
        assert r["never+errored_cold"]["tone"] == "err"
        assert "endpoint not found (404)" in r["never+errored_cold"]["msg"]

        assert r["never+healthy"]["tone"] == "sub", (
            "a pipe that has never answered reports GREEN beside a healthy "
            "sibling — the CRIT this class exists for is back"
        )
        assert r["never+healthy"]["busy"] is True
        assert "loading" in r["never+healthy"]["msg"]

        assert r["err_nodata+healthy"]["tone"] == "err"
        assert "unreachable" in r["err_nodata+healthy"]["msg"]

        assert r["err_withdata+healthy"]["tone"] == "warn"
        assert "showing last data" in r["err_withdata+healthy"]["msg"]

        assert r["slow+fast"]["tone"] == "warn"
        assert "delayed [640ms]" in r["slow+fast"]["msg"]

        assert r["fast+faster"]["tone"] == "ok"
        assert "[30ms]" in r["fast+faster"]["msg"], "reported the faster pipe"

    @pytest.mark.parametrize("net,has", [
        ({}, False), ({"ms": 12}, True), ({"ms": 12}, False),
        ({"ms": 900}, True), ({"ms": 900}, False),
        ({"err": {"status": 500}}, True), ({"err": {"status": 500}}, False),
        ({"err": {"status": 0}}, True), ({"err": {"corrupt": True}}, True),
    ])
    def test_single_pipe_behaviour_is_otherwise_unchanged(self, net, has, tmp_path):
        """Six panes were already correct; delegating them through the new
        helper must not alter their feet — EXCEPT in the one case below, which
        is the fix itself."""
        case = [{"name": "one", "net": {"a": net},
                 "sources": [{"src": "a", "hasData": has}]}]
        row = self._run(case, tmp_path)["one"]
        assert {"tone": row["tone"], "msg": row["msg"], "busy": row["busy"]} == {
            "tone": row["single"]["tone"], "msg": row["single"]["msg"],
            "busy": bool(row["single"].get("busy")),
        }

    def test_the_one_intended_single_pipe_divergence(self, tmp_path):
        """A pipe that has NEVER answered while its hasData proxy reads true.

        Old: `loading && !hasData` failed its gate and fell through to tier 1
        `connected`. New: tier 4 `loading…`. This is the CRIT's second route,
        and it is a real behaviour change for exactly one single-pipe pane —
        EquityStatsPane, whose hasData is `eq.total_equity != null`, a field SSE
        writes directly (dash-tiled.jsx equity_update). A hung
        /api/dashboard/snapshot there used to read green off an SSE-painted
        number; it now reads `loading…`, which is the truth about that pipe.
        The other five single-pipe panes gate on `d.loaded` or on their own
        loader's array, neither of which any other writer can set, so they are
        unaffected.
        """
        case = [{"name": "one", "net": {"a": {}},
                 "sources": [{"src": "a", "hasData": True}]}]
        row = self._run(case, tmp_path)["one"]
        assert row["tone"] == "sub" and row["busy"] is True
        assert row["single"]["tone"] == "ok", (
            "the OLD derivation no longer reports green here, so this test has "
            "stopped documenting a divergence — re-check why"
        )


# ── 5. the rule is written down where the next author will look ────────────

def test_the_multi_pipe_rule_is_in_design_md():
    """Convention-drift discipline: a usage rule that lives only in a commit
    message gets re-derived (wrongly) by the next pane."""
    i = _DESIGN.index("MULTI-PIPE RULE")
    seg = _DESIGN[i:i + 1200]
    assert "WORST" in seg
    assert "_dashFootWorst" in seg


# ── 6. it reaches the shipped bundle ───────────────────────────────────────

def test_the_fix_reaches_the_emitted_bundle():
    man = json.loads((_ROOT / "static" / "v3" / "manifest.json").read_text(encoding="utf-8"))
    flat = re.sub(r"\s+", "", (_ROOT / "static" / "v3" / man["app"]).read_text(encoding="utf-8"))
    for token in (
        '_dashFootWorst(d,[{src:"snapshot",hasData:d.loaded}',   # Risk Monitor
        'src:"st",hasData:d.st&&d.st.dd_state!=null',            # its second pipe
        '_dashFootWorst(d,[{src:key,hasData}])',                 # the delegation
    ):
        assert token in flat, (
            f"`{token}` exists in source but not in the emitted bundle — "
            f"rebuild frontend/ (node build.mjs)"
        )
