const CACHE_NAME = "rest-autoroute-v2";
const APP_SHELL = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // Routing/geocoding must always hit the network live -- never serve these from cache.
  if (url.hostname.indexOf("nominatim.openstreetmap.org") !== -1 ||
      url.hostname.indexOf("project-osrm.org") !== -1) {
    return;
  }
  if (event.request.method !== "GET") return;
  if (url.origin !== self.location.origin) return;

  // Network-first for our own app files: the app is actively changing, so a
  // visitor should always see the latest deployed version when online. The
  // cache only kicks in as a fallback when there's no network (offline use),
  // not as the default source -- a cache-first strategy here is exactly what
  // caused an old version to keep showing after an update.
  event.respondWith(
    fetch(event.request)
      .then((resp) => {
        if (resp.ok) {
          const copy = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        }
        return resp;
      })
      .catch(() => caches.match(event.request).then((cached) => cached || caches.match("./index.html")))
  );
});
