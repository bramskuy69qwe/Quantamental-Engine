"""Everything account-scoped follows the ACTIVE account, not the page-load one.

THE BUG (filed 2026-07-30 as H1 + H2 + open-item #4; closed 2026-08-01).
`QE_BOOTSTRAP.activeAccountId` is baked into the page at render time and has no
way to change afterwards. Two routes switch the engine's account:

  · the nav picker      → `window.location.reload()`, so bootstrap is re-baked
                          and every consumer is correct. This HID the bug.
  · Config ▸ Activate   → refetches data WITHOUT reloading.

Down the second route every consumer holding the page-load id silently kept
targeting the account the operator had just LEFT:

  H1  the SSE stream stayed subscribed to it — `connect()` early-returns while
      a `source` exists and was only ever called once at load — so the
      Dashboard's live equity / position_update / dd_state events belonged to
      another book, with nothing on screen saying so. On a risk console that is
      the same class as the stale-shown-as-live seam closed the day before.
  H2  Pre-Trade read `individual_risk_per_trade` for it, so the sizing panel
      disagreed with what the engine would actually size — two numbers, both
      presented as the truth, on the page whose whole job is position size.
  #4  the chrome store's `accounts` list was fetched ONCE and `reloadAccounts`
      had ZERO callers, so the nav picker and the WorkspaceBar EXCH cell went
      on NAMING the old account beside numbers that were already the new one's.

THE FIX is one live source (`QE_CHROME.accountId` / `onAccountChange` /
`useQeAccount`), seeded from bootstrap for the cold start and kept current from
`/api/state.account_id` — the same door the DD-override write already reads for
exactly this reason. Consumers subscribe; nothing reads bootstrap.

WHAT THIS FILE PINS. The coverage class is derived from source, so a page added
later that reads the page-load id fails here without anyone remembering this
bug. The behaviour class EXECUTES the real QE_CHROME and QE_SSE through a
switch — including the two cases that are easy to get wrong by reading:
re-targeting off an ERRORED poll (which would tear down a healthy stream using
an id the engine may have moved on from), and whether channel subscribers
survive the reconnect (asserted by DISPATCHING through it, not by counting).

Run: pytest tests/test_account_switch_follows.py -v
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
from tests._srcpin import code as _code, args as _args  # noqa: E402

_ROOT = Path(__file__).parent.parent
_SRC = _ROOT / "frontend" / "src"


def _raw(name: str) -> str:
    return (_SRC / name).read_text(encoding="utf-8")


def _src(name: str) -> str:
    return _code(_raw(name))


_CHROME = _src("chrome-live.js")
_SSE = _src("sse-adapter.js")

# The ONLY two places allowed to name the page-load id, each with its reason.
_BOOTSTRAP_ALLOWED = {
    "chrome-live.js": "seeds the live source, so the cold start is unchanged",
    "sse-adapter.js": "documented fallback for loading this module standalone",
}


# ── 0. the stripper is not vacuous ──────────────────────────────────────────

@pytest.mark.parametrize("name", ["chrome-live.js", "sse-adapter.js",
                                  "pages-pretrade.jsx", "pages-config.jsx"])
def test_stripped_source_is_substantial(name):
    # Only the length floor is load-bearing: asserting the stripped text has
    # no comment delimiters is a TAUTOLOGY (code() truncates at each one), and
    # a tautology beside a real check reads as two checks.
    assert len(_src(name)) > 0.25 * len(_raw(name))


# ── 1. COVERAGE — nobody reads the page-load id ─────────────────────────────

class TestNothingConsumesThePageLoadAccountId:
    """Derived app-wide, because the failure is silent and the next page to do
    it will look exactly as reasonable as these two did."""

    def test_only_the_declared_seed_and_fallback_name_it(self):
        offenders = {}
        for path in sorted(_SRC.glob("*.js")) + sorted(_SRC.glob("*.jsx")):
            hits = _src(path.name).count("activeAccountId")
            if hits:
                offenders[path.name] = hits
        assert set(offenders) <= set(_BOOTSTRAP_ALLOWED), (
            f"{sorted(set(offenders) - set(_BOOTSTRAP_ALLOWED))} read "
            f"QE_BOOTSTRAP.activeAccountId, which is baked at page load and "
            f"goes stale the moment an account is activated from Config (that "
            f"path does not reload). Use QE_CHROME.accountId() / "
            f"useQeAccount() instead — see this file's header."
        )
        for name, reason in _BOOTSTRAP_ALLOWED.items():
            assert offenders.get(name) == 1, (
                f"{name} names activeAccountId {offenders.get(name)}x; exactly "
                f"one is expected ({reason})"
            )

    def test_the_coverage_above_really_catches_the_pre_fix_shape(self):
        """A URL-shape regex was tried here first and was VACUOUS: the pre-fix
        line it existed to police —
        `load('/api/config/account/' + window.QE_BOOTSTRAP.activeAccountId)` —
        produced zero matches, because a concatenation closes the string
        literal before the id ever appears in it. It is gone; the symbol count
        above carries the coverage instead, and unlike the regex it is
        mutation-proven (restoring the pre-fix read in pages-pretrade.jsx turns
        `test_only_the_declared_seed_and_fallback_name_it` RED).

        This asserts the premise that makes that true: the id can only be
        reached through the symbol, so counting the symbol IS counting the
        consumers."""
        bootstrap = (_ROOT / "templates" / "v3.html").read_text(encoding="utf-8")
        assert "activeAccountId:" in bootstrap, (
            "the bootstrap key was renamed — the coverage pin above is now "
            "counting a symbol nothing uses and passes vacuously"
        )


# ── 2. the live source ──────────────────────────────────────────────────────

class TestTheLiveAccountSource:
    def test_it_is_seeded_from_bootstrap_so_the_cold_start_is_unchanged(self):
        assert "let _acctId = (window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.activeAccountId);" in _CHROME
        assert "if (_acctId === undefined) _acctId = null;" in _CHROME, (
            "an undefined seed would make the first /api/state read look like a "
            "CHANGE and fire every subscriber on a page that never switched"
        )

    def test_it_is_kept_live_from_api_state(self):
        body = _CHROME[_CHROME.index("const _noteAccount"):_CHROME.index("const _runState")]
        assert "st.state.account_id" in body

    def test_it_refuses_to_act_on_an_ERRORED_poll(self):
        """The rule the nav strip and the pane foots already follow. This store
        KEEPS the last-good payload and raises only the flag, so without the
        guard a failed poll would re-derive the account from a stale body —
        and acting on that is worse than not acting, because it tears down a
        healthy SSE stream and re-points it at an id the engine may have moved
        on from. Executed in TestExecutedSwitch."""
        body = _CHROME[_CHROME.index("const _noteAccount"):_CHROME.index("const _runState")]
        assert "if (st.stateErr || !st.state) return;" in body
        assert body.index("st.stateErr") < body.index("st.state.account_id"), (
            "the error flag must be checked BEFORE the payload is read"
        )

    def test_it_compares_as_strings(self):
        """DEFENSIVE, not load-bearing — and said so rather than inventing a
        reason. Both sides are numbers today (`activeAccountId` is rendered by
        `{{ active_account_id | tojson }}`, and /api/state returns the same
        number), so `===` would work. The guard exists because a type change on
        either side would make this unequal on EVERY poll, churning the SSE
        connection six times a minute — a failure invisible without a network
        panel. Pinned so the guard is not "simplified" away."""
        body = _CHROME[_CHROME.index("const _noteAccount"):_CHROME.index("const _runState")]
        assert "String(id) === String(_acctId)" in body

    def test_a_switch_reloads_the_accounts_list(self):
        """#4: the picker and the EXCH cell must not go on naming the account
        the operator just left."""
        body = _CHROME[_CHROME.index("const _noteAccount"):_CHROME.index("const _runState")]
        assert "loadAccounts();" in body

    def test_the_watcher_is_wired_to_the_state_poll_only(self):
        """Not to the snapshot or system polls — only /api/state carries
        account_id, and hanging it off another pipe would read undefined."""
        assert "poll('/api/state', 'state', 'stateErr', 10_000, _noteAccount)" in _CHROME
        for other in ("'snap'", "'sys'"):
            line = next(l for l in _CHROME.splitlines() if other in l and "poll(" in l)
            assert "_noteAccount" not in line, line

    def test_the_poll_applies_the_newest_response_not_the_last_to_arrive(self):
        """The generation guard. Executed in
        `test_a_stale_in_flight_poll_cannot_revert_the_account`; pinned here
        too so the failure names the mechanism rather than a truth table."""
        body = _CHROME[_CHROME.index("const poll = (url"):_CHROME.index("const loadAccounts")]
        assert "let issued = 0, applied = 0;" in body
        assert "const mine = ++issued;" in body
        assert "if (mine < applied) return;" in body, (
            "a superseded response can overwrite a newer one — for /api/state "
            "that runs the whole account switch backwards"
        )
        assert body.index("if (mine < applied) return;") < body.index("st[errKey] = true"), (
            "the guard must precede EVERY write, the error flag included: a "
            "stale failure landing after a healthy answer would flag a pipe "
            "that has just demonstrably succeeded"
        )

    def test_the_hook_re_reads_on_commit_before_subscribing(self):
        """`useState`'s initializer runs during RENDER and the subscription is
        installed on COMMIT, so a switch landing between the two would never be
        delivered and the component would hold the stale id for its whole
        life — the exact failure the hook exists to prevent."""
        body = _CHROME[_CHROME.index("const useQeAccount"):]
        assert "setId(QE_CHROME.accountId());" in body
        assert body.index("setId(QE_CHROME.accountId());") < body.index("onAccountChange(setId)")

    def test_the_public_api_is_the_three_consumers_need(self):
        for member in ("accountId: () => _acctId,", "onAccountChange:", "refreshAccount:"):
            assert member in _CHROME, member
        assert "const useQeAccount = () =>" in _CHROME
        assert "useQeAccount" in _CHROME[_CHROME.index("Object.assign(window"):], (
            "the hook is not exported, so pages cannot use it"
        )


# ── 3. H1 — the stream follows ──────────────────────────────────────────────

class TestTheSseStreamFollows:
    def test_it_reads_the_live_id_not_the_baked_one(self):
        body = _SSE[_SSE.index("const accountId ="):_SSE.index("function fanout")]
        assert "window.QE_CHROME.accountId()" in body
        assert body.index("QE_CHROME") < body.index("QE_BOOTSTRAP"), (
            "the bootstrap value must be the FALLBACK, not the primary"
        )

    def test_the_open_stream_records_which_account_it_is_for(self):
        """Without this, `retarget` cannot tell a real switch from a repeat and
        would either churn the connection on every poll or never fire."""
        assert "streamId = id;" in _SSE
        assert "streamId = null;" in _SSE[_SSE.index("function disconnect"):], (
            "disconnect must clear it, or a later connect looks like a no-op"
        )

    def test_retarget_is_idempotent_and_tears_down_first(self):
        body = _SSE[_SSE.index("function retarget"):_SSE.index("return {")]
        assert "if (id == null || String(id) === String(streamId)) return status;" in body
        assert body.index("disconnect()") < body.index("connect()"), (
            "connect() early-returns while a source exists, so re-pointing "
            "without disconnecting first is a silent no-op — the bug itself"
        )

    def test_it_is_subscribed_to_the_account_change(self):
        assert "window.QE_CHROME.onAccountChange(QE_SSE.retarget)" in _SSE
        # NOT pinning the order of connect() vs the subscription: both are
        # synchronous in the same module-eval tick, so nothing can fire between
        # them and either order behaves identically. The draft pinned it with a
        # rationale ("or the first change could race the cold start") that does
        # not describe anything real — a pin on a non-property teaches the next
        # author a constraint that is not there.


# ── 4. H2 — Pre-Trade follows ───────────────────────────────────────────────

class TestPreTradeFollows:
    def test_it_takes_the_live_id_from_the_hook(self):
        src = _src("pages-pretrade.jsx")
        assert "const acctId = useQeAccount();" in src

    def test_the_account_is_a_DEPENDENCY_of_the_context_effect(self):
        """The whole effect is account-scoped — risk %, calculator context,
        /api/state — so a switch re-runs all of it, not only the one URL that
        happens to embed the id."""
        src = _src("pages-pretrade.jsx")
        i = src.index("const acctId = useQeAccount();")
        effect = src[i:src.index("}, [acctId]);", i) + 13]
        assert "'/api/config/account/' + acctId" in effect
        assert "/api/calculator/context" in effect, (
            "the context read left this effect, so it no longer re-runs on a "
            "switch and would show the previous account's match window"
        )
        assert effect.rstrip().endswith("}, [acctId]);")

    def test_the_risk_read_is_guarded_against_a_null_id(self):
        """`accountId()` is null until the first /api/state answers on a page
        rendered without a bootstrap id; `/api/config/account/null` is a 404
        that would paint a red foot through normal warm-up."""
        src = _src("pages-pretrade.jsx")
        assert "if (acctId != null) load('/api/config/account/' + acctId" in src


# ── 5. #4 — the cached list follows too ─────────────────────────────────────

class TestTheAccountsListFollows:
    def test_reloadAccounts_finally_has_a_caller(self):
        """It was filed with ZERO callers. Config's loadAccounts is the ONE
        funnel every accounts-list write on that page already goes through —
        create, activate, an env/exchange edit, the manual reload — so it is
        also the one place that can keep the chrome copy honest."""
        cfg = _src("pages-config.jsx")
        assert "window.QE_CHROME.reloadAccounts();" in cfg
        i = cfg.index("const loadAccounts = React.useCallback")
        assert "window.QE_CHROME.reloadAccounts();" in cfg[i:cfg.index("}, []);", i)], (
            "the call is not inside Config's loadAccounts funnel, so only some "
            "of the writes that change the list will refresh the picker"
        )

    def test_activate_pushes_the_switch_instead_of_waiting_out_the_poll(self):
        cfg = _src("pages-config.jsx")
        body = cfg[cfg.index("const doActivate"):cfg.index("const envTone")]
        assert "window.QE_CHROME.refreshAccount();" in body
        assert body.index("refreshAccount") < body.index("onReload(true)")

    def test_the_poll_remains_the_backstop(self):
        """The push covers the Config route; the watcher covers every other
        one (another tab, the engine itself). Neither alone is enough."""
        assert "poll('/api/state', 'state', 'stateErr', 10_000, _noteAccount)" in _CHROME


# ── 6. BEHAVIOUR: run the real stores through a switch ─────────────────────

_NODE = shutil.which("node")

_JS_DRIVER = r"""
const out = {};
const record = (k) => { out[k] = { id: QE_CHROME.accountId(), stream: QE_SSE.streamAccountId(),
                                   notes: NOTES.slice(), accountsFetches: ACCOUNTS_FETCHES,
                                   liveSources: FakeES.live.length, log: LOG.slice() }; };
// REAL_SET_TIMEOUT, not setInterval: a repeating timer here keeps node's
// event loop alive forever and the harness never prints (it hung the first
// run; the standalone probe had masked it with process.exit).
const tick = () => new Promise((r) => REAL_SET_TIMEOUT(r, 5));
const statePoll = () => INTERVALS.find((i) => i.ms === 10000).fn;

// Subscribe BEFORE anything runs, or `notes` is an empty array that every
// "fired exactly once" assertion below reads as a pass on the wrong side.
QE_CHROME.onAccountChange((id) => NOTES.push(id));

(async () => {
  await tick();                              record('boot');
  await statePoll()(); await tick();         record('samePoll');
  FAIL = true; ACCOUNT = 7;
  await statePoll()(); await tick();         record('erroredWhileChanged');
  FAIL = false;
  await statePoll()(); await tick();         record('switched');
  await statePoll()(); await tick();         record('switchedAgain');

  // subscribers must SURVIVE the reconnect — dispatch through it
  const seen = [];
  QE_SSE.onChannel('equity_update', (p) => seen.push(p.v));
  FakeES.live[0].emit('equity_update', { v: 'before' });
  ACCOUNT = 3;
  await statePoll()(); await tick();
  FakeES.live[0].emit('equity_update', { v: 'after' });
  out.subscriberSaw = seen;
  record('switchedBack');

  // ── THE OVERLAP. Everything above drives polls serially, which is exactly
  // why the first version of this harness could not see the race that shipped
  // in the first draft of the fix: refreshAccount() fires a SECOND concurrent
  // /api/state, and without a generation guard the older response wins simply
  // by resolving last — reverting the account and tearing the SSE stream off
  // the new one. Hold the responses and release them out of order.
  ACCOUNT = 3; HOLD = true;
  statePoll()(); await tick();          // a scheduled poll goes out, sees 3
  ACCOUNT = 7;                          // operator hits Config > Activate
  QE_CHROME.refreshAccount(); await tick();   // the push goes out, sees 7
  PENDING.pop()(); await tick();        // the PUSH answers first  -> 7
  record('pushLanded');
  PENDING.shift()(); await tick();      // the STALE one answers second -> 3
  record('staleLanded');

  console.log(JSON.stringify(out));
})();
"""

_JS_ENV = r"""
let ACCOUNT = 3, FAIL = false;
const LOG = [], INTERVALS = [], NOTES = [];
let ACCOUNTS_FETCHES = 0;
const REAL_SET_TIMEOUT = setTimeout;   // captured BEFORE the stub below
globalThis.window = globalThis;
globalThis.React = { useState: () => [null, () => {}], useEffect: () => {}, useReducer: () => [0, () => {}] };
globalThis.document = { hidden: false, addEventListener() {}, removeEventListener() {} };
globalThis.QE_BOOTSTRAP = { activeAccountId: 3 };
globalThis.setInterval = (fn, ms) => { INTERVALS.push({ fn, ms }); return INTERVALS.length; };
globalThis.setTimeout = () => 0;
globalThis.clearTimeout = () => {};
const PENDING = [];    // held /api/state responses, released by hand
let HOLD = false;
globalThis.fetch = async (url) => {
  if (url === '/accounts') {
    ACCOUNTS_FETCHES++;
    return { ok: true, json: async () => [{ id: 3, is_active: ACCOUNT === 3 },
                                          { id: 7, is_active: ACCOUNT === 7 }] };
  }
  if (url === '/api/state') {
    if (FAIL) return { ok: false, status: 503, json: async () => ({}) };
    const at = ACCOUNT;                    // the id AS OF request time
    if (!HOLD) return { ok: true, json: async () => ({ account_id: at }) };
    return new Promise((res) => PENDING.push(() =>
      res({ ok: true, json: async () => ({ account_id: at }) })));
  }
  return { ok: true, json: async () => ({}) };
};
class FakeES {
  constructor(u) { this.url = u; this.ls = new Map(); LOG.push('OPEN ' + u); FakeES.live.push(this); }
  addEventListener(ev, fn) { this.ls.set(ev, fn); }
  close() { LOG.push('CLOSE ' + this.url); FakeES.live = FakeES.live.filter((x) => x !== this); }
  emit(ev, o) { const f = this.ls.get(ev); if (f) f({ data: JSON.stringify(o) }); }
}
FakeES.live = [];
globalThis.EventSource = FakeES;
"""


@pytest.mark.skipif(_NODE is None, reason="node not on PATH")
class TestExecutedSwitch:
    """Structure cannot carry this one. Every pin above passes against a
    `_noteAccount` that notifies on the FIRST read, or a `retarget` that opens
    a second EventSource without closing the first, or a guard that reads the
    error flag and then acts anyway. Run the real stores instead."""

    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory):
        prim = _raw("primitives.jsx")
        plumbing = prim[prim.index("const QE_READ_DEADLINE_MS"):prim.index("const qeFootCause")]
        assert len(plumbing) > 2000, "the primitives slice collapsed"
        js = (_JS_ENV + plumbing + "\n" + _raw("chrome-live.js") + "\n"
              + _raw("sse-adapter.js") + "\n" + _JS_DRIVER)
        f = tmp_path_factory.mktemp("acct") / "harness.mjs"
        f.write_text(js, encoding="utf-8")
        r = subprocess.run([_NODE, str(f)], capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    def test_the_cold_start_is_unchanged(self, result):
        b = result["boot"]
        assert b["id"] == 3 and b["stream"] == 3
        assert b["liveSources"] == 1
        assert b["notes"] == [], "a page that never switched fired a change event"

    def test_a_repeat_poll_does_not_churn_the_connection(self, result):
        """A re-target on every 10 s poll would drop and re-open the SSE stream
        six times a minute, losing whatever the engine published in between."""
        s = result["samePoll"]
        assert s["notes"] == [] and s["accountsFetches"] == 1
        assert s["log"] == ["OPEN /stream/account/3"]

    def test_an_ERRORED_poll_never_retargets(self, result):
        """THE guard. The account really had changed underneath, but the poll
        that would have told us failed — so this store keeps its last-good
        payload, and re-deriving the account from it would tear down a healthy
        stream and re-point it using whatever the stale body said."""
        e = result["erroredWhileChanged"]
        assert e["id"] == 3, "the account was re-derived from a stale payload"
        assert e["stream"] == 3
        assert e["notes"] == []
        assert e["log"] == ["OPEN /stream/account/3"], (
            "the stream was torn down on a failed poll"
        )

    def test_a_real_switch_moves_everything(self, result):
        s = result["switched"]
        assert s["id"] == 7
        assert s["stream"] == 7, "H1: the SSE stream is still on the old account"
        assert s["notes"] == [7], "subscribers were not told exactly once"
        assert s["accountsFetches"] == 2, "#4: the picker's list did not follow"
        assert s["log"] == ["OPEN /stream/account/3", "CLOSE /stream/account/3",
                            "OPEN /stream/account/7"]

    def test_exactly_one_stream_stays_open(self, result):
        """A retarget that forgot to disconnect leaks an EventSource per switch
        — and both keep delivering, so the Dashboard would merge two accounts."""
        for key in ("switched", "switchedAgain", "switchedBack"):
            assert result[key]["liveSources"] == 1, key

    def test_the_switch_is_not_re_announced(self, result):
        a = result["switchedAgain"]
        assert a["notes"] == [7] and a["stream"] == 7
        assert a["log"].count("OPEN /stream/account/7") == 1

    def test_a_stale_in_flight_poll_cannot_revert_the_account(self, result):
        """THE race the first draft of this fix shipped, and the reason `poll`
        carries a generation guard.

        `refreshAccount()` deliberately fires a second concurrent /api/state so
        a switch lands without waiting out the 10 s tick. Without the guard the
        last response to RESOLVE wins rather than the last to ISSUE — so a poll
        issued moments before Config ▸ Activate answers afterwards with the OLD
        account, and the app walks backwards: _acctId reverts, the SSE stream
        is torn off the account the operator just switched TO and re-pointed at
        the one they left, and Pre-Trade reloads the previous account's risk %.
        It self-heals on the next tick, so the damage is bounded at one poll
        interval of a risk console on the wrong book — which is precisely what
        the stateErr guard exists to prevent, arriving by a route it cannot
        see. (Executed against the pre-guard code: id 3 → 7 → 3.)"""
        assert result["pushLanded"]["id"] == 7
        assert result["pushLanded"]["stream"] == 7
        stale = result["staleLanded"]
        assert stale["id"] == 7, (
            f"a superseded /api/state response reverted the account to "
            f"{stale['id']} — the generation guard in `poll` is gone"
        )
        assert stale["stream"] == 7, "the SSE stream was re-pointed backwards"
        assert stale["notes"] == [7, 3, 7], (
            f"subscribers were told the account changed back: {stale['notes']}"
        )
        assert stale["liveSources"] == 1

    def test_channel_subscribers_survive_the_reconnect(self, result):
        """Asserted by DISPATCHING through the re-target, not by counting: the
        subscriptions live outside the EventSource, so connect() must re-bind
        them to the new one. A subscriber silently dropped here is a Dashboard
        that stops updating after any account switch."""
        assert result["subscriberSaw"] == ["before", "after"], result["subscriberSaw"]
        assert result["switchedBack"]["stream"] == 3


# ── 7. it reaches the shipped bundle ───────────────────────────────────────

def test_the_fix_reaches_the_emitted_bundle():
    man = json.loads((_ROOT / "static" / "v3" / "manifest.json").read_text(encoding="utf-8"))
    flat = re.sub(r"\s+", "", (_ROOT / "static" / "v3" / man["app"]).read_text(encoding="utf-8"))
    for token in (
        "onAccountChange:",
        "accountId:()=>_acctId",
        "QE_CHROME.onAccountChange(QE_SSE.retarget)",
        "constacctId=useQeAccount()",
        "window.QE_CHROME.reloadAccounts()",
        "window.QE_CHROME.refreshAccount()",
    ):
        assert token in flat, (
            f"`{token}` exists in source but not in the emitted bundle — "
            f"rebuild frontend/ (node build.mjs)"
        )
