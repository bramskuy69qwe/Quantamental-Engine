"""H6 — operator attribution wired into the React shell (the seat store).

THE DEFECT (wiring inventory 2026-07-30, fixed 2026-08-03): seat registration
only ever existed in templates/base.html's IIFE, and the Jinja retirement
removed those pages from the app's serving path — so the `operator_id`
columns P9.T3 added (`pre_trade_log`, `orders`, `order_amendments`) recorded
NOTHING for any action taken through the React UI. Attribution is resolved
SERVER-side (core/auth_state.current_operator_id + the on-duty cache that
routes_auth's doors write through), so no per-write client change is needed —
the fix is a store that registers the seat, keeps it alive, and follows the
account: frontend/src/operator-seat.js (`.js`, NOT `.jsx` — a *.jsx-only grep
misses it, the standing sse-adapter lesson).

Parity with base.html, plus the two lanes a full-page-reload world never
needed, both EXECUTED below rather than reasoned about:

  · RE-REGISTER ON ACCOUNT SWITCH — all three doors bind
    app_state.active_account_id server-side; the Jinja page re-registered by
    reloading, the React app switches without one (H1/H2). On switch the
    store also RESETS to idle first: the executed probe caught keep-last
    holding the PREVIOUS account's `foreign` through an engine-down switch —
    a stale banner, the stale-shown-as-live family again.
  · REGISTER-RETRY — base.html registered once at load; boot with the engine
    down and the seat never existed (heartbeat deliberately claims nothing).
    The 60 s tick registers until one result applies, then heartbeats.

Run: pytest tests/test_operator_seat_react.py -v
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
_SEAT_RAW = (_ROOT / "frontend" / "src" / "operator-seat.js").read_text(encoding="utf-8")
_SEAT = _code(_SEAT_RAW)
_NAV = _code((_ROOT / "frontend" / "src" / "nav-and-data.jsx").read_text(encoding="utf-8"))
_PRIM = _code((_ROOT / "frontend" / "src" / "primitives.jsx").read_text(encoding="utf-8"))
_BASE = (_ROOT / "templates" / "base.html").read_text(encoding="utf-8")


# ── 0. the stripper is not vacuous on the new file ──────────────────────────

def test_stripped_source_is_substantial():
    assert "/*" not in _SEAT and "//" not in _SEAT
    assert "QE_SEAT" in _SEAT and "register" in _SEAT


# ── 1. the two-UI identity contract ─────────────────────────────────────────

class TestSeatIdentityContract:
    """One browser profile = ONE seat across BOTH UIs. If the two surfaces
    mint under different keys, an operator using the legacy /config page and
    the React app reads as two operators fighting over the account — a
    permanent self-takeover banner."""

    def test_both_surfaces_use_the_same_storage_key(self):
        """FULL-SET equality on both sides, not membership: the mutation
        check caught `'op_seat' in base_keys` surviving a rename of one of
        base.html's two accessors — a half-renamed surface mints under one
        key and reads under another, which is the two-seat fight with extra
        steps. base.html's only localStorage use IS the seat, verified."""
        seat_keys = set(re.findall(r"localStorage\.(?:getItem|setItem)\('([^']+)'", _SEAT))
        base_keys = set(re.findall(r"localStorage\.(?:getItem|setItem)\('([^']+)'", _BASE))
        assert seat_keys == {"op_seat"}, seat_keys
        assert base_keys == {"op_seat"}, (
            f"base.html's seat storage keys changed to {sorted(base_keys)} — "
            f"if the key is being renamed, rename it in BOTH surfaces in the "
            f"same commit or each browser profile becomes two operators"
        )

    def test_both_surfaces_heartbeat_on_the_same_cadence(self):
        assert re.search(r"\}, 60_?000\);", _SEAT), "seat heartbeat cadence changed"
        assert re.search(r"heartbeat'\); \}, 60000\);", _BASE), (
            "base.html heartbeat cadence changed — keep the reaper's two "
            "feeders in step or one surface's sessions look idler than the other"
        )

    def test_the_doors_are_called_with_the_form_shape_they_take(self):
        """routes_auth takes `operator_id: str = Form(...)` — a JSON body
        would 422 all three doors silently (every failure is swallowed)."""
        assert "'operator_id=' + encodeURIComponent(seat)" in _SEAT
        assert "'Content-Type': 'application/x-www-form-urlencoded'" in _SEAT

    def test_the_module_is_in_the_build_after_its_dependency(self):
        order = (_ROOT / "frontend" / "build.mjs").read_text(encoding="utf-8")
        assert "'operator-seat.js'" in order, "the module is not in JSX_ORDER at all"
        assert order.index("'chrome-live.js'") < order.index("'operator-seat.js'"), (
            "operator-seat evaluates QE_CHROME.onAccountChange at module eval "
            "— it must load after chrome-live"
        )


# ── 2. the store's own shape ────────────────────────────────────────────────

class TestSeatStoreShape:
    def test_register_fires_at_module_eval(self):
        i = _SEAT.index("register();")
        assert i < _SEAT.index("setInterval("), "boot register is gone"

    def test_the_tick_registers_until_applied_or_while_foreign(self):
        m = re.search(
            r"if \(!applied \|\| st\.state === 'foreign'\) \{ register\(\); return; \}",
            _SEAT)
        assert m, (
            "the retry/foreign lane is gone — boot with the engine down and "
            "this seat never exists, and a foreign banner outlives its cause "
            "forever (a foreign seat's heartbeat is a documented server no-op)"
        )

    def test_a_lost_heartbeat_triggers_a_reregister(self):
        """`bumped: false` is the server saying this seat no longer owns the
        session (taken over, or reaped while frozen). Discarding it — the
        first draft did, and so does base.html — leaves the page heartbeating
        a session that is not its own, with attribution silently dead."""
        assert re.search(r"d\.bumped === false\) register\(\)", _SEAT)

    def test_every_async_answer_is_epoch_guarded(self):
        """THE RACE (audit HIGH, proven by execution): these writes carry no
        deadline, so a register from account A can land AFTER the switch
        reset. Unguarded, it stamped A's answer over B's reset AND latched
        `applied`, so B was never registered — H6 restored by its own fix.
        Every .then that can touch state must check its minted epoch."""
        assert "let epoch = 0;" in _SEAT
        assert "epoch += 1;" in _SEAT, "the switch no longer invalidates in-flight answers"
        thens = re.findall(r"\.then\(\(d\) => \{ (.*?) \}\)", _SEAT)
        assert len(thens) >= 3, "the promise chains changed shape — re-derive this pin"
        for body in thens:
            assert "e === epoch" in body, (
                f"an async answer is applied without the epoch check: {body!r}"
            )

    def test_apply_only_trusts_a_shaped_answer(self):
        assert "if (!d || !d.state) return;" in _SEAT, (
            "a null/garbage response can now clobber confirmed state"
        )

    def test_account_switch_resets_before_reregistering(self):
        i = _SEAT.index("onAccountChange(() => {")
        body = _SEAT[i:_SEAT.index("});", i)]
        for frag in ("st.state = 'idle';", "st.foreign = null;",
                     "st.dismissed = false;", "applied = false;", "register();"):
            assert frag in body, (
                f"`{frag}` missing from the switch handler — the executed "
                f"probe showed keep-last holding the PREVIOUS account's "
                f"foreign state through an engine-down switch (stale banner)"
            )

    def test_failures_never_claim_anything(self):
        """Advisory subsystem: swallowed failures are fine, INVENTED states
        are not. Region-based, not a single-field regex: the audit planted a
        dismiss() that also wrote `st.state = "owner"` — client-side invented
        ownership — and the first draft's single-quote st.state-only regex
        stayed green. So: cut out the three regions ALLOWED to write state
        (apply, the switch reset, dismiss) and assert the remainder of the
        file contains no `st.<field> =` assignment at all; then bound what
        dismiss itself may touch."""
        assert _SEAT.count(".catch(() => {})") >= 3
        allowed = []
        i = _SEAT.index("const apply = (d) => {")
        allowed.append((i, _SEAT.index("};", i)))
        i = _SEAT.index("onAccountChange(() => {")
        allowed.append((i, _SEAT.index("});", i)))
        i = _SEAT.index("dismiss:")
        allowed.append((i, _SEAT.index("\n", i)))
        rest = "".join(
            ch for n, ch in enumerate(_SEAT)
            if not any(a <= n < b for a, b in allowed))
        stray = re.findall(r"st\.\w+ *=[^=]", rest)
        assert not stray, (
            f"state is written outside apply()/the switch reset/dismiss(): "
            f"{stray} — a swallowed failure or helper is inventing a state"
        )
        dismiss_line = _SEAT[_SEAT.index("dismiss:"):]
        dismiss_line = dismiss_line[:dismiss_line.index("\n")]
        writes = re.findall(r"st\.(\w+) *=", dismiss_line)
        assert writes == ["dismissed"], (
            f"dismiss() writes {writes} — waving the banner away must never "
            f"change what the store believes about the session"
        )


# ── 3. the banner ───────────────────────────────────────────────────────────

class TestSeatBanner:
    def _banner(self) -> str:
        i = _NAV.index("const OperatorSeatBanner")
        return _NAV[i:_NAV.index("const ClockDriftBanner")]

    def test_it_renders_only_on_confirmed_foreign_and_not_dismissed(self):
        assert "if (s.state !== 'foreign' || s.dismissed) return null;" in self._banner()

    def test_it_mounts_in_the_under_nav_slot_after_the_enforcement_banners(self):
        i = _NAV.index("<ClockDriftBanner/>")
        j = _NAV.index("<ChromeHaltBanner/>")
        k = _NAV.index("<OperatorSeatBanner/>")
        assert i < j < k, (
            "banner stack order changed — system alerts first, the advisory "
            "seat banner last (it is the only dismissable one)"
        )

    def test_take_over_and_dismiss_are_wired_to_the_store(self):
        b = self._banner()
        assert 'actionLabel="TAKE OVER" onAction={() => QE_SEAT.takeover()}' in b
        assert "onDismiss={() => QE_SEAT.dismiss()}" in b

    def test_the_banner_primitive_gained_dismiss_additively(self):
        """`onDismiss` must default null so the halt/clock banners — which
        must NOT be dismissable — render exactly as before."""
        i = _PRIM.index("const Banner = ")
        body = _PRIM[i:_PRIM.index("const _TOASTC")]
        assert "onDismiss=null}" in body, (
            "onDismiss lost its null default — every existing Banner caller "
            "(halt, clock, at-cap) now renders an unintended dismiss button"
        )
        assert "{onDismiss && <button" in body, "the dismiss button render is gone"
        # BOTH enforcement banners, wherever they are defined in the file —
        # the first draft sliced ChromeHaltBanner→OperatorSeatBanner, and
        # ClockDriftBanner (defined AFTER the seat banner) fell outside the
        # window: the audit's onDismiss-on-ClockDrift mutation survived.
        for comp in ("ChromeHaltBanner", "ClockDriftBanner"):
            i = _NAV.index(f"const {comp}")
            body_c = _NAV[i:_NAV.index("\n};", i)]
            assert "onDismiss" not in body_c, (
                f"{comp} became dismissable — halt and clock are enforcement "
                f"banners; only the advisory seat banner takes onDismiss"
            )


# ── 4. BEHAVIOUR — execute the real store, don't reason about it ────────────

_NODE = shutil.which("node")

_DRIVER = """
const store = new Map();
globalThis.localStorage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
globalThis.window = globalThis;
let responder = () => null; const calls = [];
globalThis.fetch = (url, init) => { calls.push({ url, body: init.body });
  const d = responder(url); return Promise.resolve({ ok: d != null, json: () => Promise.resolve(d) }); };
let accountCb = null;
globalThis.QE_CHROME = { onAccountChange: (f) => { accountCb = f; } };
let tick = null;
globalThis.setInterval = (fn, ms) => { tick = { fn, ms }; return 0; };
const settle = () => new Promise((r) => setTimeout(r, 5));
const out = {};
(async () => {
  // boot with the engine DOWN
  responder = () => null;
  %SRC%
  await settle();
  out.bootDownState = QE_SEAT.get().state;
  out.seatPersisted = localStorage.getItem('op_seat');
  out.tickMs = tick.ms;
  // engine up: the tick must RE-REGISTER, not heartbeat
  responder = (u) => u.includes('register') ? { state: 'owner', account_id: 1 } : { bumped: true };
  calls.length = 0; tick.fn(); await settle();
  out.retryCalls = calls.map(c => c.url);
  out.retryBody = calls[0] && calls[0].body;
  out.afterRetry = QE_SEAT.get().state;
  // then it heartbeats
  calls.length = 0; tick.fn(); await settle();
  out.steadyCalls = calls.map(c => c.url);
  // switch -> foreign
  responder = (u) => u.includes('register')
    ? { state: 'foreign', foreign_operator_id: 'other-xyz', since_ms: 42, account_id: 2 } : null;
  QE_SEAT.dismiss();
  calls.length = 0; accountCb(2); await settle();
  const s4 = QE_SEAT.get();
  out.switchCalls = calls.map(c => c.url);
  out.switchState = [s4.state, s4.foreign, s4.sinceMs, s4.dismissed, s4.accountId];
  // takeover flips to owner
  responder = (u) => u.includes('takeover') ? { state: 'owner', account_id: 2 } : null;
  await QE_SEAT.takeover(); await settle();
  out.afterTakeover = QE_SEAT.get().state;
  // engine-down switch must RESET, never keep the old account's answer
  responder = (u) => u.includes('register')
    ? { state: 'foreign', foreign_operator_id: 'zzz', since_ms: 1, account_id: 2 } : null;
  accountCb(2); await settle();           // now foreign again
  responder = () => null;                 // engine dies
  accountCb(3); await settle();
  const s6 = QE_SEAT.get();
  out.deadSwitchState = [s6.state, s6.foreign, s6.sinceMs];
  // THE RACE (audit HIGH): a register in flight across the switch reset must
  // be dropped, and the tick must still RE-REGISTER for the new account.
  let hang = null;
  responder = () => null;
  globalThis.fetch = (url, init) => new Promise((resolve) => { hang = { url,
    ok: (d) => resolve({ ok: true, json: () => Promise.resolve(d) }) }; });
  accountCb(4); await settle();           // fires a register that HANGS
  const inflight = hang; hang = null;
  globalThis.fetch = (url, init) => { calls.push({ url, body: init.body });
    const d = responder(url); return Promise.resolve({ ok: d != null, json: () => Promise.resolve(d) }); };
  accountCb(5); await settle();           // switch AGAIN — epoch bumps
  inflight.ok({ state: 'foreign', foreign_operator_id: 'stale4', since_ms: 7, account_id: 4 });
  await settle();
  const s7 = QE_SEAT.get();
  out.staleAnswerState = [s7.state, s7.foreign];        // must stay idle/null
  responder = (u) => u.includes('register') ? { state: 'owner', account_id: 5 } : null;
  calls.length = 0; tick.fn(); await settle();
  out.staleThenTick = [calls.map(c => c.url), QE_SEAT.get().state];
  // while FOREIGN the tick re-registers (a foreign heartbeat is a no-op) —
  // when the foreign owner is reaped, the seat is claimed with no click
  responder = (u) => u.includes('register')
    ? { state: 'foreign', foreign_operator_id: 'ww', since_ms: 2, account_id: 5 } : null;
  accountCb(5); await settle();
  responder = (u) => u.includes('register') ? { state: 'owner', account_id: 5 } : null;
  calls.length = 0; tick.fn(); await settle();
  out.foreignTick = [calls.map(c => c.url), QE_SEAT.get().state];
  // owner heartbeat answering bumped:false = lost the seat -> re-register
  responder = (u) => u.includes('heartbeat') ? { ok: true, bumped: false }
    : { state: 'foreign', foreign_operator_id: 'thief', since_ms: 3, account_id: 5 };
  calls.length = 0; tick.fn(); await settle();
  out.lostSeatTick = [calls.map(c => c.url), QE_SEAT.get().state, QE_SEAT.get().foreign];
  // a REJECTED fetch (network throw, not non-ok) never claims and never crashes
  globalThis.fetch = () => Promise.reject(new TypeError('Failed to fetch'));
  accountCb(6); await settle();
  out.rejectedState = QE_SEAT.get().state;
  console.log(JSON.stringify(out));
})();
"""


@pytest.mark.skipif(_NODE is None, reason="node not on PATH")
class TestSeatBehaviourExecuted:
    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory):
        src = _SEAT_RAW[:_SEAT_RAW.index("/* React hook")]
        js = _DRIVER.replace("%SRC%", src)
        f = tmp_path_factory.mktemp("seat") / "harness.mjs"
        f.write_text(js, encoding="utf-8")
        r = subprocess.run([_NODE, str(f)], capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    def test_boot_with_engine_down_claims_nothing(self, result):
        assert result["bootDownState"] == "idle"

    def test_the_seat_is_minted_once_and_persisted(self, result):
        assert result["seatPersisted"], "no seat in localStorage after boot"
        assert result["retryBody"] == "operator_id=" + result["seatPersisted"]

    def test_the_tick_retries_register_then_settles_into_heartbeat(self, result):
        assert result["tickMs"] == 60000
        assert result["retryCalls"] == ["/operator/session/register"], (
            "the first tick after an engine-down boot did not re-register — "
            "the seat never exists and attribution stays structurally dead, "
            "which is the H6 defect with extra steps"
        )
        assert result["afterRetry"] == "owner"
        assert result["steadyCalls"] == ["/operator/session/heartbeat"]

    def test_an_account_switch_reregisters_and_resets_dismissal(self, result):
        assert result["switchCalls"] == ["/operator/session/register"]
        state, foreign, since, dismissed, account = result["switchState"]
        assert (state, foreign, since) == ("foreign", "other-xyz", 42)
        assert dismissed is False, (
            "a dismissal on account A silenced the banner for account B"
        )
        assert account == 2, "accountId does not follow the door's answer"

    def test_takeover_clears_the_foreign_state(self, result):
        assert result["afterTakeover"] == "owner"

    def test_an_engine_down_switch_resets_rather_than_keeps(self, result):
        """The executed-probe finding, pinned: keep-last across a switch held
        the PREVIOUS account's `foreign` — a stale banner making a claim
        about an account nobody asked about."""
        assert result["deadSwitchState"] == ["idle", None, None], result["deadSwitchState"]

    def test_a_stale_inflight_answer_is_dropped_and_the_tick_recovers(self, result):
        """THE RACE (audit HIGH). Unguarded, the account-4 register landing
        after the switch to 5 stamped 4's `foreign` over the reset AND
        latched `applied` — so the banner lied about the wrong account and
        account 5 was NEVER registered (attribution dead: H6 restored by its
        own fix). The epoch guard drops the stale answer; the next tick
        re-registers and the fresh answer applies."""
        assert result["staleAnswerState"] == ["idle", None], result["staleAnswerState"]
        assert result["staleThenTick"] == [["/operator/session/register"], "owner"]

    def test_the_foreign_tick_reregisters_and_claims_after_the_reap(self, result):
        calls, state = result["foreignTick"]
        assert calls == ["/operator/session/register"], (
            "the tick heartbeats while foreign — a documented server no-op, "
            "so the banner outlives its cause and the seat is never claimed"
        )
        assert state == "owner"

    def test_a_lost_seat_is_learned_within_a_tick(self, result):
        calls, state, foreign = result["lostSeatTick"]
        assert calls == ["/operator/session/heartbeat", "/operator/session/register"]
        assert (state, foreign) == ("foreign", "thief"), (
            "bumped:false was discarded — the page keeps believing it owns a "
            "session another seat took over"
        )

    def test_a_rejected_fetch_never_claims(self, result):
        """The driver's engine-down was previously modelled only as a non-ok
        RESPONSE; the .catch arms were never executed (audit LOW). A real
        network throw must leave the store idle, not crash or invent."""
        assert result["rejectedState"] == "idle"


# ── 5. backend premises (untouched — pinned so drift is loud) ───────────────

class TestBackendPremises:
    def test_the_three_doors_take_form_operator_id(self):
        src = (_ROOT / "api" / "routes_auth.py").read_text(encoding="utf-8")
        for door in ("register", "takeover", "heartbeat"):
            assert f'@router.post("/operator/session/{door}")' in src, door
        assert src.count("operator_id: str = Form(...)") == 3, (
            "a door changed its parameter shape — the store posts urlencoded "
            "form bodies and every failure is swallowed, so a 422 is SILENT"
        )

    def test_register_binds_the_live_active_account(self):
        src = (_ROOT / "api" / "routes_auth.py").read_text(encoding="utf-8")
        assert src.count("app_state.active_account_id") >= 3, (
            "the doors no longer bind the live active account — the "
            "re-register-on-switch lane is then aimed at the wrong premise"
        )

    def test_the_attribution_cache_is_fed_by_each_door(self):
        """The whole point: registering must feed the on-duty cache the
        P9.T3 write sites read, or the seat exists and attribution is still
        dead. PER-DOOR, not a total count — `>= 2` survived deleting the
        REGISTER door's feed (the critical one: it is the door the store
        hits at every boot and switch), because takeover + heartbeat still
        summed to two."""
        src = (_ROOT / "api" / "routes_auth.py").read_text(encoding="utf-8")
        for door in ("register", "takeover", "heartbeat"):
            i = src.index(f'@router.post("/operator/session/{door}")')
            j = src.find("@router.post", i + 1)
            body = src[i:j if j > 0 else len(src)]
            assert "app_state.operator_id_by_account[aid] = seat" in body, (
                f"the {door} door no longer feeds the on-duty cache — "
                f"pre_trade_log/orders/order_amendments stamp from that cache"
            )

    def test_the_seat_fits_the_servers_length_bound(self):
        """Client mints a UUID (36 chars); the server rejects > 64 silently
        (every client failure is swallowed), so this contract can only rot
        invisibly."""
        src = (_ROOT / "api" / "routes_auth.py").read_text(encoding="utf-8")
        m = re.search(r"_MAX_SEAT_LEN = (\d+)", src)
        assert m and int(m.group(1)) >= 36


# ── 6. it reaches the shipped bundle ────────────────────────────────────────

def test_the_fix_reaches_the_emitted_bundle():
    man = json.loads((_ROOT / "static" / "v3" / "manifest.json").read_text(encoding="utf-8"))
    flat = re.sub(r"\s+", "", (_ROOT / "static" / "v3" / man["app"]).read_text(encoding="utf-8"))
    for token in (
        "operator-seat.js",                      # the module marker comment
        '"op_seat"',                             # the shared identity key
        "/operator/session/register",
        "/operator/session/heartbeat",
        "OperatorSeatBanner",
    ):
        assert token in flat.replace("\\", ""), (
            f"`{token}` exists in source but not in the emitted bundle — "
            f"rebuild frontend/ (node build.mjs)"
        )
