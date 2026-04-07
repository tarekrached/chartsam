/* Service Worker — SF Bay Nautical Chart PWA
 *
 * Strategy:
 *   - index.html / app.js → network-first (always pick up updates)
 *   - Leaflet, manifest.json → cache-first (stable, versioned)
 *   - Tiles → cache-first (all pre-cached on install)
 *   - bounds.json / tile-manifest.json → network-first (allow updates)
 */

const CACHE_VERSION = 'v6';
const SHELL_CACHE   = `shell-${CACHE_VERSION}`;
const TILE_CACHE    = `tiles-${CACHE_VERSION}`;

const SHELL_ASSETS = [
  './',
  './index.html',
  './app.js',
  './bounds.json',
  './manifest.json',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
];

// ── Install: cache app shell + all tiles ──────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil((async () => {
    // 1. Cache app shell
    const shellCache = await caches.open(SHELL_CACHE);
    await shellCache.addAll(SHELL_ASSETS);

    // 2. Pre-cache all tiles from the manifest
    const tileManifest = await fetch('./tile-manifest.json').then(r => r.json());
    const tileCache = await caches.open(TILE_CACHE);

    // Batch cache in chunks to avoid overwhelming memory
    const CHUNK = 50;
    for (let i = 0; i < tileManifest.length; i += CHUNK) {
      const chunk = tileManifest.slice(i, i + CHUNK);
      await Promise.allSettled(
        chunk.map(path => tileCache.add('./' + path).catch(() => {}))
      );
    }

    await self.skipWaiting();
  })());
});

// ── Activate: delete old caches ───────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys
        .filter(k => k !== SHELL_CACHE && k !== TILE_CACHE)
        .map(k => caches.delete(k))
    );
    await self.clients.claim();
  })());
});

// ── Fetch: serve from cache ───────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Tiles: cache-first, no network fallback needed (blank on miss)
  if (url.pathname.includes('/tiles/')) {
    event.respondWith(
      caches.match(event.request).then(r => r || fetch(event.request))
    );
    return;
  }

  // index.html, app.js, bounds.json, tile-manifest.json: network-first
  // so updates are picked up without manual cache clearing
  if (
    url.pathname.endsWith('/') ||
    url.pathname.endsWith('index.html') ||
    url.pathname.endsWith('app.js') ||
    url.pathname.endsWith('bounds.json') ||
    url.pathname.endsWith('tile-manifest.json')
  ) {
    event.respondWith(
      fetch(event.request)
        .then(r => {
          const clone = r.clone();
          caches.open(SHELL_CACHE).then(c => c.put(event.request, clone));
          return r;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Everything else (leaflet, icons, manifest.json): cache-first
  event.respondWith(
    caches.match(event.request).then(r => r || fetch(event.request))
  );
});
