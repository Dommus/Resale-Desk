// Service worker: lets the app be installed on a phone and shows a simple
// page when there is no connection. Pages are never cached, so data is
// always live. Served from /sw.js (see app.py) so it covers the whole site.
const CACHE = "resale-desk-v1";
const OFFLINE_URL = "/offline";

self.addEventListener("install", (event) => {
    event.waitUntil(caches.open(CACHE).then((cache) => cache.add(OFFLINE_URL)));
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    // Drop caches left by older versions of this file
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))
        )
    );
    self.clients.claim();
});

self.addEventListener("fetch", (event) => {
    if (event.request.mode !== "navigate") {
        return;
    }
    event.respondWith(
        fetch(event.request).catch(() => caches.match(OFFLINE_URL))
    );
});
