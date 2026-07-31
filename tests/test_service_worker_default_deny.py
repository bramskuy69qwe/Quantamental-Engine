"""C1 — the service worker must never replay live data as if it were fresh.

The defect (filed 2026-07-30, fixed 2026-07-31): `networkFirst` cached every
200 — including every API door and fragment — and replayed the cached copy
whenever the network failed. A DEAD engine therefore painted a fully populated
dashboard with green "connected" indicators. `chrome-live.js` only treats
`!response.ok` as failure, and a cached 200 is indistinguishable from a live
one, so nothing downstream could tell.

Before this file the whole behaviour of static/service-worker.js was UNPINNED:
deleting the entire fetch listener left the suite green, and the e2e program
runs with `serviceWorkers: 'block'` so it could never catch a regression here.

Two structural properties are what actually keep the bug dead. Both are pinned
below, and both are easy to undo by accident:

  1. DEFAULT-DENY. The worker must not carry a list of dynamic prefixes. The
     old rule had one and it was already missing ten live doors (/accounts,
     /notifications/poll, /context/, /orders/needs_review, /calculator/prefill,
     /calculator/link-window-status, /stream/, /export ...). Any such list is a
     list somebody forgets to extend; a forgotten path must fail SAFE.

  2. NO SYNTHESIZED FAILURE RESPONSES off the dynamic lane. This is subtler
     than "don't cache". Per the SSE spec a response that is not 200 with
     Content-Type text/event-stream makes the browser FAIL THE CONNECTION —
     readyState CLOSED, no reconnect. The old code answered a failed SSE fetch
     with `new Response('Network unavailable', {status: 503})`, so it
     permanently killed the live channel during exactly the outage the operator
     needed it for (sse-adapter.js:46 explicitly relies on auto-reconnect).
     A "network-only" rewrite built from fetch()+catch would re-create this.
     The only correct shape is to not call respondWith at all.

Run: pytest tests/test_service_worker_default_deny.py -v
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests._srcpin import code as _code  # noqa: E402

# Hard read, no exists-skip — matching the launcher-pin precedent in
# tests/test_project_meta.py:117-121. If the worker vanishes, say so.
_SW_PATH = Path(__file__).parent.parent / "static" / "service-worker.js"
_RAW = _SW_PATH.read_text(encoding="utf-8")
_SW = _code(_RAW)


# ── slicing helpers ─────────────────────────────────────────────────────────
# Every pin below asserts over a NAMED REGION, not over the whole file, so a
# token appearing in an unrelated function cannot satisfy (or falsify) it.

def _between(text: str, start_anchor: str, end_anchor: str | None) -> str:
    start = text.index(start_anchor)
    end = len(text) if end_anchor is None else text.index(end_anchor)
    assert end > start, f"anchors out of order: {start_anchor!r} .. {end_anchor!r}"
    return text[start:end]


def _lifecycle(text: str) -> str:
    """CACHE_NAME, the precache list, and the install/activate listeners."""
    return _between(text, "const CACHE_NAME", "function isImmutableAsset")


def _fetch_listener(text: str) -> str:
    # `self.` included so this region abuts _allow_list exactly and no line
    # falls between the two (pinned by test_every_executable_line_...)
    return _between(text, "self.addEventListener('fetch'", "async function cacheFirst")


def _allow_list(text: str) -> str:
    # end anchor includes `self.` so the region closes on isImmutableAsset's
    # own brace rather than trailing into the next statement
    return _between(text, "function isImmutableAsset", "self.addEventListener('fetch'")


def _cache_first(text: str) -> str:
    return _between(text, "async function cacheFirst", "async function navigateOrOffline")


def _navigate(text: str) -> str:
    return _between(text, "async function navigateOrOffline", None)


# ── the allow-list, PARSED AND EVALUATED ────────────────────────────────────
# isImmutableAsset is the only lane that writes to a cache, so it is the only
# place the original CRIT can come back. Grepping it for forbidden lines is not
# enough — the adversarial review proved that moving `/api/` and `/fragments/`
# INTO this function restored the bug (worse: cache-first serves stale bodies
# even while the engine is healthy) with every line-based pin still green.
#
# So parse the rules and RUN them against a table of real URLs. A rule added
# anywhere in the function, in any order, changes an OUTCOME rather than sliding
# past a substring check. Any rule shape the parser does not recognise is a hard
# error, so the simulator cannot silently stop covering the function.

_RULE_ORIGIN = re.compile(r"^if \(url\.origin !== self\.location\.origin\) return false;$")
_RULE_EQ = re.compile(r"^if \(path === '([^']+)'\) return true;$")
_RULE_PREFIX_EXCEPT = re.compile(
    r"^if \(path\.startsWith\('([^']+)'\)\) return path !== '([^']+)';$")
_RULE_PREFIX = re.compile(r"^if \(path\.startsWith\('([^']+)'\)\) return true;$")


def _allow_rules(text: str):
    body = _allow_list(text)
    body = body[body.index("{") + 1:body.rindex("}")]
    rules = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line == "const path = url.pathname;":
            continue
        if line == "return false;":
            rules.append(("default", None, None))
            continue
        if _RULE_ORIGIN.match(line):
            rules.append(("origin", None, None))
            continue
        for pattern, kind in (
            (_RULE_EQ, "eq"),
            (_RULE_PREFIX_EXCEPT, "prefix_except"),
            (_RULE_PREFIX, "prefix"),
        ):
            m = pattern.match(line)
            if m:
                groups = m.groups()
                rules.append((kind, groups[0], groups[1] if len(groups) > 1 else None))
                break
        else:
            raise AssertionError(
                f"unrecognised rule in isImmutableAsset: {line!r}\n"
                f"The simulator cannot evaluate it, so the behaviour pins below "
                f"would silently stop covering this function. Teach the parser "
                f"this shape before shipping the rule."
            )
    return rules


def _is_immutable(path: str, text: str = _SW, same_origin: bool = True) -> bool:
    for kind, a, b in _allow_rules(text):
        if kind == "origin":
            if not same_origin:
                return False
        elif kind == "eq":
            if path == a:
                return True
        elif kind == "prefix_except":
            if path.startswith(a):
                return path != b
        elif kind == "prefix":
            if path.startswith(a):
                return True
        elif kind == "default":
            return False
    return False


# Live doors and mutable files. A True for ANY of these is the CRIT, back.
_MUST_NOT_CACHE = [
    "/api/state", "/api/dashboard/snapshot", "/api/ready", "/api/engine/log",
    "/fragments/ws_status", "/fragments/needs_link_count",
    "/stream/account/1", "/notifications/poll", "/accounts",
    "/context/position/7", "/orders/needs_review", "/orders/needs_link",
    "/calculator/prefill/3", "/calculator/link-window-status/9",
    "/export", "/params", "/config", "/admin/trade_events",
    "/",                            # the shell: naming a bundle hash
    "/static/v3/manifest.json",     # rewritten in place on every build
    "/favicon.ico",                 # redirects to / when the icon is absent
    "/static/service-worker.js",    # reachable through the /static mount
]

# Content-hashed build output, vendored libraries, install assets.
_MAY_CACHE = [
    "/static/v3/app.7268075fd2.js",
    "/static/v3/tokens.7268075fd2.css",
    "/static/v3/shell.7268075fd2.css",
    "/static/vendor/react.production.min.js",
    "/static/vendor/fonts/fonts.css",
    "/static/icon-192.png",
    "/static/icon-512.png",
    "/manifest.json",
]


# ── 0. the stripper self-check ──────────────────────────────────────────────

class TestStripperIsNotVacuous:
    """THE most important test in this file.

    Every negative pin below is a lie if `_code()` returns nothing. That is not
    hypothetical: before this fix the file's line 14 read
    `// ... unhashed /static/vendor/* the old cache-first rule`, whose `/*`
    opened a phantom block comment inside a LINE comment (tests/_srcpin.py
    strips block comments FIRST). No `*/` ever followed, the strip loop hit
    `break` without appending the tail, and `code()` returned 13 characters out
    of 4924 — so `assert 'cache.put' not in code` would have passed against an
    empty string and been deletion-proof.

    Guard the precondition explicitly rather than trusting it.
    """

    def test_stripped_source_is_substantial(self):
        nonblank = [ln for ln in _SW.splitlines() if ln.strip()]
        assert len(nonblank) > 40, (
            f"_code() yielded only {len(nonblank)} non-blank lines from "
            f"{len(_RAW)} raw chars — an unterminated /* in a // comment "
            f"probably swallowed the file. Every negative pin here is void "
            f"until this passes."
        )

    def test_no_comment_residue_survives(self):
        assert "//" not in _SW and "/*" not in _SW

    def test_the_unterminated_block_hazard_stays_fixed(self):
        """A path glob ending in `*` must never appear inside a // comment."""
        for i, line in enumerate(_RAW.splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith("//"):
                continue
            assert "/*" not in stripped, (
                f"line {i} opens a phantom block comment inside a line "
                f"comment, which silently truncates _code(): {stripped!r}"
            )

    def test_no_comment_marker_hides_inside_a_string_literal(self):
        """The second way _code() can go blind. `_srcpin` is purely textual —
        it has no string-literal awareness — so a `//` inside a quoted string
        truncates the REST OF THAT LINE. A whole cache-first branch written on
        one line after such a string (its prefix literal AND its respondWith)
        would be invisible to every negative pin here, and to the respondWith
        COUNT pin as well."""
        for i, line in enumerate(_RAW.splitlines(), 1):
            for literal in re.findall(r"'[^']*'", line):
                assert "//" not in literal and "/*" not in literal, (
                    f"line {i} hides a comment marker in a string literal, "
                    f"which truncates _code() from that point: {literal!r}"
                )

    def test_every_executable_line_lives_in_a_pinned_region(self):
        """Region coverage. Each pin slices a named region; a line in NO region
        is unpinned by construction, and that is invisible unless asserted.
        The install/activate listeners are covered by their own class below."""
        regions = (
            _fetch_listener(_SW) + _allow_list(_SW)
            + _cache_first(_SW) + _navigate(_SW) + _lifecycle(_SW)
        )
        uncovered = [
            ln.strip() for ln in _SW.splitlines()
            if ln.strip() and ln.strip() not in regions
        ]
        assert not uncovered, f"executable lines in no pinned region: {uncovered}"


# ── 1. default-deny: the fetch listener owns exactly two lanes ──────────────

class TestDefaultDeny:
    def test_there_is_exactly_one_fetch_listener(self):
        """A service worker may register SEVERAL fetch listeners, and the bare
        return in this one is precisely what lets a second listener's
        respondWith win. Without this pin the default-deny guarantee can be
        reintroduced-AROUND rather than edited, with every other pin here green
        because they all slice the first listener's region."""
        assert _SW.count("addEventListener('fetch'") == 1, (
            "a second fetch listener exists — the region every other pin in "
            "this file slices is no longer the whole story"
        )

    def test_exactly_two_respond_with_lanes(self):
        """Structure, not substrings: `respondWith` alone proves nothing (the
        old file had three). The COUNT is the property — a third lane is how a
        dynamic path gets adopted back into the worker."""
        listener = _fetch_listener(_SW)
        assert listener.count("event.respondWith(") == 2, listener

    def test_the_two_lanes_are_immutable_assets_and_navigation(self):
        listener = _fetch_listener(_SW)
        asset = listener.index("respondWith(cacheFirst(")
        nav = listener.index("respondWith(navigateOrOffline(")
        # asset lane must be gated by the allow-list, nav lane by request mode
        assert listener.index("isImmutableAsset(url)") < asset
        assert listener.index("request.mode === 'navigate'") < nav

    def test_no_dynamic_prefix_list_exists(self):
        """The deny-list shape is what CAUSED the bug. Its return is the
        regression to catch, so pin the absence of every prefix the old rule
        named plus the ones it missed."""
        listener = _fetch_listener(_SW)
        for prefix in (
            "/api", "/fragments", "/stream", "/ws",
            "/accounts", "/notifications", "/context",
            "/calculator", "/orders", "/export",
        ):
            assert prefix not in listener, (
                f"{prefix!r} is named in the fetch listener — the worker has "
                f"re-acquired a dynamic prefix list. Dynamic paths must reach "
                f"the bare return, not a branch."
            )

    def test_writes_return_before_any_lane(self):
        listener = _fetch_listener(_SW)
        guard = listener.index("method !== 'GET'")
        assert guard < listener.index("event.respondWith("), (
            "the non-GET early return must precede every respondWith"
        )

    def test_listener_ends_on_a_bare_return_not_a_fallback(self):
        """After the two lanes there must be NO trailing respondWith. The tail
        of the listener is where a well-meaning `networkFirst` fallback would
        be reintroduced."""
        listener = _fetch_listener(_SW)
        tail = listener[listener.rindex("respondWith(navigateOrOffline("):]
        assert "respondWith" not in tail[len("respondWith(navigateOrOffline("):]
        assert "fetch(" not in tail


# ── 2. no synthesized response can reach a dynamic caller (the SSE pin) ─────

class TestNoSynthesizedFailureOffTheDynamicLane:
    """Returning any Response to an EventSource that is not a 200 event-stream
    makes the browser stop reconnecting. Only the navigation lane may fabricate
    a Response at all."""

    def test_exactly_one_fabricated_response_in_the_file(self):
        assert _SW.count("new Response(") == 1, (
            "a second fabricated Response has appeared — if it is reachable "
            "from a non-navigation request it will permanently kill "
            "EventSource on the first outage"
        )

    def test_that_response_lives_in_the_navigation_lane(self):
        nav = _navigate(_SW)
        assert "new Response(" in nav
        assert "new Response(" not in _fetch_listener(_SW)
        assert "new Response(" not in _cache_first(_SW)

    def test_the_offline_notice_is_html_and_keeps_the_default_200(self):
        """Deliberate, and NOT the 503 that reads as more honest: Chrome's PWA
        installability check navigates start_url with the network disabled and
        wants a 200 back. Nothing caches this response, so a truthful status
        would buy aesthetics at the price of installability. Pinned so the
        'obvious improvement' is not made twice — it was made once, in the
        first draft of this fix, and the adversarial review caught it."""
        nav = _navigate(_SW)
        assert "'Content-Type': 'text/html'" in nav
        assert "status:" not in nav


# ── 3. cache writes are confined to the immutable-asset lane ────────────────

class TestCacheWritesAreConfined:
    def test_only_one_cache_put_and_it_is_in_cache_first(self):
        assert _SW.count("cache.put(") == 1
        assert "cache.put(" in _cache_first(_SW)

    def test_no_cachestorage_wide_lookup_anywhere(self):
        """`caches.match(x)` searches EVERY cache in the origin, including ones
        this version never wrote. Lookups must be scoped to the opened
        CACHE_NAME so a stale generation cannot answer."""
        assert "caches.match(" not in _SW
        assert "cache.match(" in _cache_first(_SW)

    def test_writes_are_guarded_to_exactly_200(self):
        """Not `response.ok`: Cache.put REJECTS on a 206 partial, and with the
        rejection swallowed that reads as a cache which quietly never fills.
        Redirects are excluded for the same reason /favicon.ico is."""
        cf = _cache_first(_SW)
        assert "response.status === 200" in cf
        assert "response.ok" not in cf

    def test_the_write_is_held_open_by_waituntil(self):
        """An un-awaited put can be cut short when the worker is terminated
        after respondWith settles — the entry silently never lands."""
        cf = _cache_first(_SW)
        assert "event.waitUntil(cache.put(" in cf

    def test_navigation_lane_has_no_cache_access_at_all(self):
        """Reordering the offline page ahead of a cache lookup is NOT enough —
        a cached shell boots the whole app against stale data and pins the
        hashed bundle name it shipped with. The lane must not touch a cache."""
        nav = _navigate(_SW)
        assert "cache" not in nav.lower()


# ── 4. the allow-list is narrow and correct ─────────────────────────────────

class TestImmutableAllowList:
    """Behaviour pins, not line pins. See the simulator above for why."""

    @pytest.mark.parametrize("path", _MUST_NOT_CACHE)
    def test_live_and_mutable_paths_are_never_cacheable(self, path):
        assert _is_immutable(path) is False, (
            f"{path} is allow-listed for cache-first. Live data served from "
            f"cache is the CRIT this file exists to prevent — and from this "
            f"lane it is worse than the original, because cache-first answers "
            f"from cache even while the engine is healthy."
        )

    @pytest.mark.parametrize("path", _MAY_CACHE)
    def test_immutable_assets_stay_cacheable(self, path):
        assert _is_immutable(path) is True, (
            f"{path} stopped being cacheable — that is a performance "
            f"regression, not a safety one, but it was not intended"
        )

    def test_cross_origin_is_never_cacheable(self):
        """Checked as an OUTCOME: a presence-only grep for the origin guard
        survives another rule being placed ahead of it."""
        for path in _MAY_CACHE:
            assert _is_immutable(path, same_origin=False) is False, path

    def test_every_rule_shape_is_understood(self):
        """Guards the simulator itself: an unparsed rule raises rather than
        being skipped, so this failing means the pins above went blind."""
        assert _allow_rules(_SW), "no rules parsed at all"

    def test_allow_list_defaults_to_false(self):
        assert _allow_rules(_SW)[-1][0] == "default", (
            "isImmutableAsset must fall through to `return false;` — the "
            "default-deny half of the fix lives in that last line"
        )


# ── 5. the cache generation was bumped ──────────────────────────────────────

class TestCacheGenerationBump:
    """`activate` purges by NAME only, so a same-named cache is never cleared.
    Without a bump every API body the old rule stored survives the upgrade
    forever — there is no TTL and no size cap in this file."""

    def test_cache_name_moved_past_the_poisoned_generation(self):
        name = re.search(r"CACHE_NAME = '([^']+)'", _SW).group(1)
        assert name != "qre-v2", (
            "still on the poisoned generation — existing browsers keep every "
            "cached /api and /fragments body"
        )
        assert re.fullmatch(r"qre-v\d+", name), name

    def test_cache_name_carries_no_dotted_version(self):
        """tests/test_project_meta.py rejects any v-digit-dot-digit substring
        anywhere in this file, so 'qre-v3.0' would turn the gate red."""
        assert not re.search(r"v\d+\.\d+", _RAW)

    def test_activate_actually_purges_every_other_generation(self):
        """This class's whole premise is that bumping the name repairs an
        already-poisoned browser. That is only true if `activate` still deletes
        the other caches — otherwise the bump is decorative and the old /api
        bodies survive. Pin the mechanism, not just the constant."""
        life = _lifecycle(_SW)
        purge = _between(life, "addEventListener('activate'", "self.clients.claim();")
        assert "caches.keys()" in purge
        assert "name !== CACHE_NAME" in purge
        assert "caches.delete(name)" in purge

    def test_precache_is_installed_and_survives_a_missing_icon(self):
        life = _lifecycle(_SW)
        install = _between(life, "addEventListener('install'", "addEventListener('activate'")
        assert "cache.addAll(PRECACHE_URLS)" in install
        assert "self.skipWaiting();" in install

    def test_precache_holds_only_paths_the_allow_list_also_permits(self):
        """A precached URL that is NOT cache-first eligible is dead weight —
        stored on install and never served. Keeping the two lists consistent is
        what stops the precache quietly rotting."""
        entries = re.findall(r"'(/[^']*)'", _between(_SW, "PRECACHE_URLS", "self.addEventListener"))
        assert entries, "precache list did not parse"
        for path in entries:
            assert _is_immutable(path) is True, (
                f"{path} is precached but not allow-listed, so it is stored on "
                f"install and never served"
            )


# ── 6. mutation harness — every pin above must BITE ─────────────────────────

class TestPinsAreDeletionProof:
    """House rule (tests/_srcpin.py:12-16): a source pin that survives deletion
    of its own subject is worse than no pin. Encoded here rather than only
    performed by hand, in the style of
    tests/test_react_port_dd_notes.py::test_stripper_defeats_a_deleted_call.
    """

    @staticmethod
    def _without(pattern: str) -> str:
        mutated = "\n".join(ln for ln in _RAW.splitlines() if pattern not in ln)
        assert mutated != _RAW, f"mutation no-op: {pattern!r} matched nothing"
        return _code(mutated)

    @staticmethod
    def _with_extra(anchor: str, injected: str) -> str:
        out = []
        for ln in _RAW.splitlines():
            out.append(ln)
            if anchor in ln:
                out.append(injected)
        mutated = "\n".join(out)
        assert mutated != _RAW, f"mutation no-op: anchor {anchor!r} not found"
        return _code(mutated)

    def test_deny_list_pin_bites(self):
        """Re-introducing a dynamic prefix branch must go red."""
        mutated = self._with_extra(
            "const url = new URL(event.request.url);",
            "  if (url.pathname.startsWith('/api/')) "
            "{ event.respondWith(cacheFirst(event.request)); return; }",
        )
        listener = _fetch_listener(mutated)
        assert "/api" in listener          # the pin's condition now trips
        assert listener.count("event.respondWith(") == 3

    def test_synthesized_response_pin_bites(self):
        """A second fabricated Response — the EventSource killer — must go red."""
        mutated = self._with_extra(
            "  const url = new URL(event.request.url);",
            "  event.respondWith(fetch(event.request).catch("
            "() => new Response('', { status: 503 })));",
        )
        assert mutated.count("new Response(") == 2

    def test_cache_put_confinement_pin_bites(self):
        mutated = self._with_extra(
            "  const cache = await caches.open(CACHE_NAME);",
            "  cache.put(request, new Response(''));",
        )
        assert mutated.count("cache.put(") == 2

    def test_navigation_cache_fallback_pin_bites(self):
        mutated = self._with_extra(
            "  } catch (err) {",
            "    const cached = await caches.match(request); if (cached) return cached;",
        )
        assert "cache" in _navigate(mutated).lower()
        assert "caches.match(" in mutated

    def test_allow_list_default_deny_pin_bites(self):
        mutated = self._without("  return false;")
        allow = _allow_list(mutated)
        assert not allow.rstrip().rstrip("}").rstrip().endswith("return false;")

    def test_get_guard_pin_bites(self):
        mutated = self._without("method !== 'GET'")
        with pytest.raises(ValueError):
            _fetch_listener(mutated).index("method !== 'GET'")

    def test_build_manifest_exclusion_pin_bites(self):
        """An EARLIER rule re-admitting the build manifest must flip the
        behaviour pin. The previous version of this test only checked the one
        line it happened to know about, so a rule placed ahead of it stayed
        green — the exact gap the adversarial review found."""
        mutated = self._with_extra(
            "  const path = url.pathname;",
            "  if (path.startsWith('/static/v3/')) return true;",
        )
        assert _is_immutable("/static/v3/manifest.json", mutated) is True

    # ── mutations for the gaps the adversarial review found ────────────────

    def test_allow_list_prefix_injection_pin_bites(self):
        """THE finding: moving the dynamic prefix list into isImmutableAsset
        restored the CRIT with all 27 original pins green. The behaviour pins
        must catch it."""
        mutated = self._with_extra(
            "  const path = url.pathname;",
            "  if (path.startsWith('/api/')) return true;",
        )
        assert _is_immutable("/api/state", mutated) is True
        assert _is_immutable("/fragments/ws_status", mutated) is False  # scoped

    def test_cross_origin_outcome_pin_bites(self):
        """Deleting the origin guard must re-admit cross-origin caching."""
        mutated = self._without("url.origin !== self.location.origin")
        assert _is_immutable("/static/vendor/react.production.min.js",
                             mutated, same_origin=False) is True

    def test_unparsed_rule_shape_raises_instead_of_passing(self):
        """The simulator must fail loudly on a rule it cannot evaluate, or the
        behaviour pins go blind without anything turning red."""
        mutated = self._with_extra(
            "  const path = url.pathname;",
            "  if (/^\\/api\\//.test(path)) return true;",
        )
        with pytest.raises(AssertionError, match="unrecognised rule"):
            _allow_rules(mutated)

    def test_second_fetch_listener_pin_bites(self):
        mutated = self._with_extra(
            "async function cacheFirst(request, event) {",
            "self.addEventListener('fetch', (e) => "
            "{ e.respondWith(caches.match(e.request)); });",
        )
        assert mutated.count("addEventListener('fetch'") == 2

    def test_activate_purge_pin_bites(self):
        mutated = self._without("caches.delete(name)")
        life = _lifecycle(mutated)
        purge = _between(life, "addEventListener('activate'", "self.clients.claim();")
        assert "caches.delete(name)" not in purge

    def test_write_guard_pin_bites(self):
        mutated = _RAW.replace("response.status === 200", "response.ok")
        assert mutated != _RAW
        assert "response.ok" in _cache_first(_code(mutated))

    def test_string_literal_hazard_pin_bites(self):
        """Prove the stripper self-check catches a hidden comment marker."""
        hazard = "  const note = 'see // the rules';"
        assert re.findall(r"'[^']*'", hazard)
        assert any("//" in lit for lit in re.findall(r"'[^']*'", hazard))
        assert "//" not in _code(hazard)  # the tail really is swallowed
