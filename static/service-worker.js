// 花札こいこい - service worker
//
// Shell cache for fast launch + offline shell render.
// Note: SW registration requires HTTPS (or localhost). Accessed over
// plain HTTP on a LAN IP, the browser silently refuses to register
// this file; the app still works, it just falls back to regular fetch.

const CACHE_NAME = "hanafuda-shell-v1";

const SHELL_URLS = [
  "/",
  "/index.html",
  "/game.js",
  "/style.css",
  "/manifest.webmanifest",
  "/icon.svg",
  "/icon-192.png",
  "/icon-512.png",
  "/apple-touch-icon.png",
  "/cards/back.svg",
];
for (let i = 0; i < 48; i++) SHELL_URLS.push(`/cards/${i}.svg`);

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((c) => c.addAll(SHELL_URLS))
      .catch(() => {}) // tolerate partial cache failures
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);

  // API calls: always network (game state is live).
  if (url.pathname.startsWith("/api/")) return;

  // Static assets: cache-first with background update.
  event.respondWith(
    caches.match(request).then((cached) => {
      const fetchPromise = fetch(request).then((resp) => {
        if (resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then((c) => c.put(request, clone)).catch(() => {});
        }
        return resp;
      }).catch(() => cached);
      return cached || fetchPromise;
    })
  );
});
