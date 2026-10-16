/* FRC Open Scout service worker: makes visited pages and the scouting form work offline. */
const VERSION = "__VERSION__";
const STATIC_CACHE = "static-" + VERSION;
const PAGE_CACHE = "pages-" + VERSION;
const PRECACHE = __PRECACHE__;
const NEVER_CACHE = ["/accounts/", "/admin/", "/api/", "/i18n/", "/staff/"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(STATIC_CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== STATIC_CACHE && k !== PAGE_CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "clear-pages") caches.delete(PAGE_CACHE);
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (NEVER_CACHE.some((p) => url.pathname.startsWith(p))) return;

  // Static files: cache first (they are versioned by the SW version).
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((resp) => {
        const copy = resp.clone();
        caches.open(STATIC_CACHE).then((c) => c.put(req, copy));
        return resp;
      }))
    );
    return;
  }

  // Pages: try the network, fall back to the last copy we saw, then to /offline/.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).then((resp) => {
        if (resp.ok && !resp.redirected) {
          const copy = resp.clone();
          caches.open(PAGE_CACHE).then((c) => c.put(req, copy));
        }
        return resp;
      }).catch(() => caches.match(req).then((hit) => hit || caches.match("/offline/")))
    );
  }
});
