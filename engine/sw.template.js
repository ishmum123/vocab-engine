// Service worker for a built trainer page. build.sh writes it as sw.js next to the page,
// filling in __VE_BUILD__ (cksum of the built page) and __VE_PAGE__ (its file name), so
// every rebuild that changes the page also changes sw.js and the browser installs it.
//
// - Cache-first for the page and same-origin pack/*.js inside this worker's scope.
// - The cache name carries the build hash; activate deletes this site's caches with any
//   other hash. All language sites share one origin (github.io), so cache names are also
//   keyed by scope and a site only ever deletes its own caches.
// - Cross-origin requests (Google Fonts, tatoeba.org audio) are never intercepted: they go
//   straight to the network and fail as they would without a worker.
// - Navigations to the page are served from cache; other in-scope navigations try the
//   network and fall back to the cached page when offline.
// - skipWaiting + claim: a new build takes over at once. The open page keeps running on
//   what it already loaded (the page is self-contained); the next load gets the new build.
"use strict";
const BUILD = "__VE_BUILD__";
const PAGE = "__VE_PAGE__";
const SCOPE = self.registration ? self.registration.scope : new URL("./", self.location.href).href;
const PREFIX = "ve:" + new URL(SCOPE).pathname + ":";
const CACHE = PREFIX + BUILD;
const PAGE_URL = new URL(PAGE, SCOPE).href;

self.addEventListener("install", e => {
  // cache:"reload" bypasses the HTTP cache (Pages sends max-age=600), so the new cache
  // never starts with the previous build's page.
  e.waitUntil(caches.open(CACHE)
    .then(c => fetch(new Request(PAGE_URL, { cache: "reload" })).then(res => {
      if(!res.ok) throw new Error("sw: precache " + PAGE_URL + " -> " + res.status);
      return c.put(PAGE_URL, res);
    }))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k.indexOf(PREFIX) === 0 && k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

function fromCacheOrNetwork(req, key){
  return caches.open(CACHE).then(c => c.match(key).then(hit => hit || fetch(req).then(res => {
    if(res.ok && !res.redirected) c.put(key, res.clone());
    return res;
  })));
}

self.addEventListener("fetch", e => {
  const req = e.request;
  if(req.method !== "GET") return;
  const url = new URL(req.url);
  if(url.origin !== self.location.origin || url.href.indexOf(SCOPE) !== 0) return;
  const rel = url.pathname.slice(new URL(SCOPE).pathname.length);
  if(rel === "" || rel === PAGE){ e.respondWith(fromCacheOrNetwork(req, PAGE_URL)); return; }
  if(/^pack\/[^/]+\.js$/.test(rel)){ e.respondWith(fromCacheOrNetwork(req, url.origin + url.pathname)); return; }
  if(req.mode === "navigate"){
    e.respondWith(fetch(req).catch(() => caches.open(CACHE).then(c => c.match(PAGE_URL)).then(hit => hit || Response.error())));
  }
});
