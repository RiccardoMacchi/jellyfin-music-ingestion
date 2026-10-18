/* Service worker della PWA.
 *
 * Regola d'oro: NON toccare mai le API. Tutto cio' che sta sotto /api
 * (analisi, download, cancellazioni e soprattutto lo stream SSE /api/events)
 * deve andare sempre in rete, senza cache, altrimenti la UI mostrerebbe dati
 * vecchi. Qui mettiamo in cache SOLO il guscio statico (HTML/CSS/JS/icone),
 * come fallback offline della pagina.
 *
 * Strategia NETWORK-FIRST per tutto il guscio: HTML, JS e CSS devono sempre
 * arrivare dalla stessa versione dell'app. Con il vecchio cache-first per
 * JS/CSS, dopo un aggiornamento l'HTML era nuovo ma app.js vecchio: campi e
 * pulsanti nuovi visibili ma senza alcun effetto. La cache serve solo se la
 * rete non risponde. */
const CACHE = "jmi-shell-v3";
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
    caches
      .open(CACHE)
      // cache: "reload" -> scavalca la cache HTTP del browser, mai file vecchi
      .then((c) => c.addAll(SHELL.map((u) => new Request(u, { cache: "reload" }))))
      .then(() => self.skipWaiting())
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

  // Prima la rete (rivalidata col server: "no-cache" usa ETag -> 304 se il
  // file non e' cambiato), poi la cache solo se offline.
  event.respondWith(
    fetch(req, { cache: "no-cache" })
      .then((res) => {
        if (res && res.ok && res.type === "basic") {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() =>
        caches.match(req).then((cached) => cached || (req.mode === "navigate" ? caches.match("/index.html") : undefined))
      )
  );
});
