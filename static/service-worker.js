/**
 * Service Worker
 * (Deliberately brand-free: this file is served as a raw static asset
 * — FileResponse in main.py — so it cannot read config.PROJECT_NAME.)
 *
 * DEFAULT-DENY. This worker participates in exactly two things:
 *
 *   1. immutable assets (see isImmutableAsset) → cache-first
 *   2. page navigations                        → network, offline notice on failure
 *
 * EVERYTHING else — every API door, fragment, poll and event stream — is left
 * entirely to the browser. The fetch handler simply returns without calling
 * respondWith, so those requests never touch a cache and never receive a
 * response this worker made up.
 *
 * WHY DEFAULT-DENY (2026-07-31). The previous rule named the dynamic prefixes
 * it meant to keep fresh, then cached every 200 anyway and replayed the cache
 * whenever the network failed. On a dead engine the dashboard painted fully
 * populated, with green "connected" indicators, off cache. Two things make the
 * inversion the only safe shape:
 *
 *   · That prefix list was DECORATIVE. Both arms of the branch called the same
 *     networkFirst, so naming a path changed nothing about how it was treated —
 *     the file merely LOOKED like it distinguished live data from assets. Ten
 *     more live doors (accounts, notification polls, context lookups, order
 *     review, calculator prefill and link-window status, the event stream, the
 *     spreadsheet export) were not on the list and were handled identically,
 *     which is the tell. Under default-deny an unlisted path fails SAFE —
 *     network-only — instead of inheriting the caching arm by default.
 *   · A synthesized failure response is not equivalent to a network failure.
 *     Returning a 503 to an EventSource makes the browser fail the connection
 *     and stop reconnecting, so the old code permanently killed the live
 *     channel during exactly the outage it was needed for. Not answering at
 *     all preserves the browser's own error semantics for every caller.
 *
 * This restores the contract the file's original header already claimed
 * ("live data must be fresh") but never implemented.
 */

// Bumping this name is the only mechanism that repairs an ALREADY-POISONED
// browser: `activate` deletes every cache whose name is not this one. The bump
// is load-bearing, not cosmetic — it evicts the API and fragment bodies the old
// rule stored, plus one accumulated entry per cursor-carrying poll (the log and
// notification polls each wrote a fresh entry every few seconds, forever).
// Keep this token free of dotted version numbers: tests/test_project_meta.py
// rejects any v-digit-dot-digit substring anywhere in this file.
const CACHE_NAME = 'qre-v3';

// Static assets to pre-cache on install.
// NB the manifest is served by a ROUTE (/manifest.json — main.py), not from
// the static dir: the old entry pointed at the deleted static copy and
// 404'd, and because cache.addAll is atomic that single dead URL silently
// voided the WHOLE pre-cache (the .catch below swallowed it). Fixed in the
// naming-hygiene task; pinned by tests/test_project_meta.py.
const PRECACHE_URLS = [
  '/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png',
];

// ── Install: pre-cache static shell ─────────────────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_URLS).catch(() => {
        // Non-fatal: icons may not exist yet during development
      });
    })
  );
  self.skipWaiting();
});

// ── Activate: purge old caches ──────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      )
    )
  );
  self.clients.claim();
});

// ── The allow-list: the ONLY responses this worker may store ────────────────
// Everything here is either content-hashed by the build, or a file whose bytes
// do not change for a given URL. If you cannot say which of those two a path
// is, it does not belong here.
function isImmutableAsset(url) {
  // Cross-origin assets (fonts, CDN libraries used by the legacy server-rendered
  // pages) are left to the browser's own HTTP cache. Those pages cannot render
  // offline anyway — the navigation itself fails — so caching their subresources
  // bought nothing.
  if (url.origin !== self.location.origin) return false;

  const path = url.pathname;

  // App identity + install assets. Trade-off, stated deliberately: a product
  // version bump does not reach an already-installed client until CACHE_NAME is
  // bumped too. Identity metadata, not live data — acceptable at that price.
  if (path === '/manifest.json') return true;
  if (path === '/static/icon-192.png') return true;
  if (path === '/static/icon-512.png') return true;
  // NOT /favicon.ico — main.py serves it as a REDIRECT to / when the icon file
  // is missing, so a 200 full of app HTML would be stored under an asset URL
  // and served forever. An allow-list entry has to be immutable in every branch
  // its route can take, not just the happy one.

  // Build output is content-hashed (app.HASH.js, tokens.HASH.css), so a rebuild
  // produces new URLs and old entries simply go unreferenced. The build MANIFEST
  // is the one exception: it is rewritten in place on every build, and serving a
  // stale copy would pin a stale bundle hash.
  if (path.startsWith('/static/v3/')) return path !== '/static/v3/manifest.json';

  // Vendored libraries are pinned by path rather than by hash, so refreshing
  // that directory requires a CACHE_NAME bump — there is no hash to invalidate
  // them. Note this deliberately does NOT match /static/service-worker.js.
  if (path.startsWith('/static/vendor/')) return true;

  return false;
}

// ── Fetch: default-deny ─────────────────────────────────────────────────────
self.addEventListener('fetch', (event) => {
  // Writes are never this worker's business.
  if (event.request.method !== 'GET') return;

  const url = new URL(event.request.url);

  if (isImmutableAsset(url)) {
    event.respondWith(cacheFirst(event.request, event));
    return;
  }

  // Page navigations: network only, with an offline notice when it fails.
  // Deliberately no cache read and no cache write. A cached shell would boot
  // the app against stale data AND pin the hashed bundle name it was built
  // with — content hashing only protects you if the document naming the hash
  // is always fresh.
  if (event.request.mode === 'navigate') {
    event.respondWith(navigateOrOffline(event.request));
    return;
  }

  // Everything else: DO NOT PARTICIPATE.
  //
  // This bare return is the load-bearing line of the file. No respondWith means
  // the browser issues the request itself, so nothing is stored, nothing is
  // replayed, and a failure reaches the caller as a genuine network error —
  // which is what makes the UI degrade honestly and what lets EventSource keep
  // reconnecting. Do not "improve" this into a fetch-with-fallback.
});

// ── Strategy: cache-first (immutable assets only) ───────────────────────────
async function cacheFirst(request, event) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  if (cached) return cached;
  // A network failure here propagates: respondWith rejects and the browser
  // reports a failed subresource, which is the truthful outcome. The old code
  // answered with an empty 503, turning a missing script into a silent one.
  const response = await fetch(request);
  // Exactly 200, not response.ok: Cache.put REJECTS on a 206 partial, and with
  // the rejection swallowed below that would look like a cache that quietly
  // never fills. Redirects are excluded for the same reason /favicon.ico is.
  if (response.status === 200) {
    // Handed to waitUntil rather than awaited: the response must not wait on
    // disk, but the worker must not be terminated before the entry lands
    // either. Caught so a quota failure cannot become an unhandled rejection.
    event.waitUntil(cache.put(request, response.clone()).catch(() => {}));
  }
  return response;
}

// ── Strategy: navigation ────────────────────────────────────────────────────
async function navigateOrOffline(request) {
  try {
    return await fetch(request);
  } catch (err) {
    // Status 200, deliberately, and NOT the 503 that reads as more honest.
    // Chrome's PWA installability check navigates start_url (main.py's manifest
    // sets it to /) with the network disabled and wants a valid 200 back; a 503
    // can forfeit installability. Nothing caches this response, so the only
    // thing a truthful status would buy is aesthetics — not worth trading an
    // install for. Reverted after the adversarial review flagged it.
    return new Response(
      '<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Offline</title>' +
      '<style>body{background:#07080f;color:#e8f2ff;font-family:sans-serif;' +
      'display:flex;align-items:center;justify-content:center;height:100vh;' +
      'flex-direction:column}h1{font-size:1.5rem;margin-bottom:.5rem}' +
      'p{color:#96b4d0;font-size:.9rem}</style></head><body>' +
      '<h1>Offline</h1><p>The engine is not reachable. ' +
      'Check that uvicorn is running.</p></body></html>',
      { headers: { 'Content-Type': 'text/html' } }
    );
  }
}
