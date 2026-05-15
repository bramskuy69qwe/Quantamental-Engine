/**
 * QUANTAMENTAL ENGINE v2.4 — Service Worker
 *
 * Strategy:
 *   /api/*, /fragments/*, /ws/* → Network-first (live data must be fresh)
 *   /static/*                   → Cache-first  (assets change rarely)
 *   HTML pages (/, /calculator) → Network-first with offline fallback
 */

const CACHE_NAME = 'qre-v1';

// Static assets to pre-cache on install
const PRECACHE_URLS = [
  '/static/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png',
];

// ── Install: pre-cache static shell ─────────────���───────────────────────────
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

// ── Activate: purge old caches ───────────────────────────���──────────────────
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

// ── Fetch: route-based strategy ─────────────────────────────────────���───────
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Skip non-GET requests (POST to calculator, form submissions, etc.)
  if (event.request.method !== 'GET') return;

  // Skip WebSocket upgrade requests
  if (event.request.headers.get('Upgrade') === 'websocket') return;

  // API and dynamic fragments: network-first
  if (
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/fragments/') ||
    url.pathname.startsWith('/ws')
  ) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // Static assets: cache-first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  // External CDN resources (htmx, echarts, fonts): cache-first
  if (
    url.hostname === 'unpkg.com' ||
    url.hostname === 'cdn.jsdelivr.net' ||
    url.hostname === 'fonts.googleapis.com' ||
    url.hostname === 'fonts.gstatic.com'
  ) {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  // HTML pages: network-first with offline fallback
  event.respondWith(networkFirst(event.request));
});

// ── Strategy: network-first ────────────────────────────���────────────────────
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    // Cache successful HTML/JSON responses for offline use
    if (response.ok && response.status === 200) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) return cached;
    // No cache available — return minimal offline page
    if (request.headers.get('Accept')?.includes('text/html')) {
      return new Response(
        '<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Offline</title>' +
        '<style>body{background:#07080f;color:#e8f2ff;font-family:sans-serif;' +
        'display:flex;align-items:center;justify-content:center;height:100vh;' +
        'flex-direction:column}h1{font-size:1.5rem;margin-bottom:.5rem}' +
        'p{color:#96b4d0;font-size:.9rem}</style></head><body>' +
        '<h1>Offline</h1><p>Quantamental Engine is not reachable. ' +
        'Check that uvicorn is running.</p></body></html>',
        { headers: { 'Content-Type': 'text/html' } }
      );
    }
    return new Response('Network unavailable', { status: 503 });
  }
}

// ── Strategy: cache-first ─────────────────��─────────────────────────────────
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    return new Response('', { status: 503 });
  }
}
