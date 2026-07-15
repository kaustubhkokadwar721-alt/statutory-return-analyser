"use strict";

// Runtime cache for the Pyodide runtime, wheels, and fonts (large, immutable
// files) plus a network-first fallback for everything else, so repeat
// launches are instant and the app keeps working with no network at all
// once one full load has succeeded. No precache manifest on purpose — the
// asset list here would drift from the ~45 bundled files; caching happens
// lazily as the app requests each file.

// Bump this whenever the vendored Pyodide runtime, wheels, or fonts change.
const CACHE = "sre-pyodide-0.26.4-ocr-20260714";
const IMMUTABLE = ["/pyodide/", "/wheels/", "/fonts/", "/ocr/"];

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  const isImmutable = IMMUTABLE.some((seg) => url.pathname.includes(seg));

  if (isImmutable) {
    // Cache-first: CACHE is bumped with every vendored runtime update.
    event.respondWith(
      caches.match(req).then((cached) => {
        if (cached) return cached;
        return fetch(req).then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy));
          }
          return res;
        });
      })
    );
    return;
  }

  // Network-first for app shell/engine so deploys reach users immediately;
  // fall back to the last cached copy when offline.
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req))
  );
});
