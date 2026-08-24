/* Service worker della PWA.
 *
 * Regola d'oro: NON toccare mai le API. Tutto cio' che sta sotto /api
 * (analisi, download, cancellazioni e soprattutto lo stream SSE /api/events)
 * deve andare sempre in rete, senza cache, altrimenti la UI mostrerebbe dati
 * vecchi. Qui mettiamo in cache SOLO il guscio statico (HTML/CSS/JS/icone),
 * per avvio rapido e per un fallback offline della pagina. */
const CACHE = "jmi-shell-v1";
const SHELL = [
  "/",
  "/index.html",
  "/style.css",
  "/app.js",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Mai intercettare API/SSE o richieste non-GET o cross-origin (es. font).
  if (req.method !== "GET") return;
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api")) return;

  // Navigazioni: prima la rete (dati freschi), fallback alla shell se offline.
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match("/index.html")));
    return;
  }

  // Asset statici: cache-first, con aggiornamento in background (stale-while-revalidate).
  event.respondWith(
    caches.match(req).then((cached) => {
      const network = fetch(req)
        .then((res) => {
          if (res && res.ok && res.type === "basic") {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy));
          }
          return res;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
