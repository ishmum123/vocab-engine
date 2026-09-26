// Service worker for a built trainer page. build.sh writes it as sw.js next to the page,
// filling in 1483185227-1572384 (cksum of the built page before its marker line) and zh.html
// (its file name), so every rebuild that changes the page also changes sw.js and the
// browser installs it. build.sh ends the page with the marker <!--ve-build:<id>-->.
//
// - Cache-first for the page only (packs are inlined into it).
// - A page is only ever cached when it carries this build's marker. A CDN edge can still
//   serve the previous index.html after a publish (Fastly ignores ?v= busting and no-cache);
//   caching that under the new build id would pin the old page until the next publish.
//   Install fails instead, and the browser retries it on a later navigation.
// - The cache name carries the build hash; activate deletes this site's caches with any
//   other hash. All language sites share one origin (github.io), so cache names are also
//   keyed by scope and a site only ever deletes its own caches.
// - Only same-origin requests inside this worker's scope are handled (SCOPE includes the
//   origin). Cross-origin requests (Google Fonts, tatoeba.org audio) are never intercepted.
// - Other in-scope navigations try the network and fall back to the cached page offline.
// - Any cache failure falls back to the plain network, so the worker never breaks a load.
// - skipWaiting + claim: a new build takes over at once. The open page keeps running on
//   what it already loaded (the page is self-contained); the next load gets the new build.
// - Recorded clips under audio/ (docs/AUDIO.md) are never precached. A clip is cached the
//   first time it plays, in its own cache AUDIO_CACHE (named by pack.json audio.version,
//   0), capped at AUDIO_CAP clips with the oldest-stored evicted. activate
//   keeps it across page builds and deletes audio caches of other versions. Offline, a
//   cached clip plays and an uncached one fails (the page then says so or uses TTS).
//   Media elements send Range requests (Chrome: bytes=0-), so the whole clip is fetched
//   and cached, and a Range request is answered with a 206 slice of it. iOS Safari's
//   range behaviour is untested until the phase 3 live check (docs/AUDIO.md).
// Kill switch / rollback: README "Offline and repeat loads"; never delete a published sw.js.
"use strict";
const BUILD = "1483185227-1572384";
const PAGE = "zh.html";
const MARK = "<!--ve-build:" + BUILD + "-->";
const SCOPE = self.registration ? self.registration.scope : new URL("./", self.location.href).href;
const PREFIX = "ve:" + new URL(SCOPE).pathname + ":";
const CACHE = PREFIX + BUILD;
const PAGE_URL = new URL(PAGE, SCOPE).href;
const AUDIO_CACHE = PREFIX + "audio:v" + "0";
const AUDIO_CAP = 800;

// true when res is a direct 200 whose body carries this build's marker. Reads a clone.
function isThisBuild(res){
  if(!res.ok || res.redirected) return Promise.resolve(false);
  return res.clone().text().then(t => t.indexOf(MARK) >= 0);
}

self.addEventListener("install", e => {
  // cache:"reload" bypasses the browser's HTTP cache (Pages sends max-age=600).
  e.waitUntil(caches.open(CACHE)
    .then(c => fetch(new Request(PAGE_URL, { cache: "reload" })).then(res => isThisBuild(res).then(ok => {
      if(!ok) throw new Error("sw: " + PAGE_URL + " is not build " + BUILD + " (status " + res.status + "); retry later");
      return c.put(PAGE_URL, res);
    })))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k.indexOf(PREFIX) === 0 && k !== CACHE && k !== AUDIO_CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

// Cached page, else the network (stored only if it is this build). A cache error of any
// kind falls back to a plain network fetch.
function pageResponse(req){
  return caches.open(CACHE).then(c => c.match(PAGE_URL).then(hit => hit || fetch(req).then(res => {
    if(!res.ok || res.redirected) return res;
    const copy = res.clone();
    return isThisBuild(copy).then(ok => ok ? c.put(PAGE_URL, copy) : null).catch(() => null).then(() => res);
  }))).catch(() => fetch(req));
}

// A recorded clip: the cached copy, else the network (a 200 is stored, then the cache is
// trimmed to AUDIO_CAP). A Range request gets a 206 slice of the full clip. Any cache
// error falls back to the plain network; offline with no copy the request fails.
function audioResponse(req, href){
  const range = req.headers.get("range");
  return caches.open(AUDIO_CACHE).then(c => c.match(href).then(hit => hit || fetch(href).then(res => {
    if(res.status !== 200 || res.redirected) return res;
    return c.put(href, res.clone()).then(() => trimAudio(c)).catch(() => null).then(() => res);
  }))).then(res => range && res.status === 200 ? sliceRange(res, range) : res)
    .catch(() => fetch(req));
}
// Cache keys come back in insertion order, so the oldest-stored clips go first.
function trimAudio(c){
  return c.keys().then(keys => Promise.all(keys.slice(0, Math.max(0, keys.length - AUDIO_CAP)).map(k => c.delete(k))));
}
function sliceRange(res, range){
  const type = res.headers.get("content-type") || "audio/ogg";
  return res.arrayBuffer().then(buf => {
    const n = buf.byteLength, m = /^bytes=(\d*)-(\d*)$/.exec(String(range).trim());
    if(!m || (m[1] === "" && m[2] === "")) return new Response(buf, { status: 200, headers: { "Content-Type": type } });
    let a, b;
    if(m[1] === ""){ a = Math.max(0, n - Number(m[2])); b = n - 1; }
    else { a = Number(m[1]); b = m[2] === "" ? n - 1 : Math.min(Number(m[2]), n - 1); }
    if(a >= n || a > b) return new Response(null, { status: 416, headers: { "Content-Range": "bytes */" + n } });
    return new Response(buf.slice(a, b + 1), { status: 206, headers: { "Content-Type": type,
      "Content-Range": "bytes " + a + "-" + b + "/" + n, "Content-Length": String(b - a + 1), "Accept-Ranges": "bytes" } });
  });
}

self.addEventListener("fetch", e => {
  const req = e.request;
  if(req.method !== "GET") return;
  const url = new URL(req.url);
  if(url.href.indexOf(SCOPE) !== 0) return; // other origins and other sites: network only
  const rel = url.pathname.slice(new URL(SCOPE).pathname.length);
  if(rel === "" || rel === PAGE){ e.respondWith(pageResponse(req)); return; }
  // Keyed by the full URL: clip names are content-addressed (<id>.<sha8>.opus, docs/AUDIO.md),
  // so a re-rendered clip is a new URL and a cached one is never stale.
  if(rel.indexOf("audio/") === 0){ e.respondWith(audioResponse(req, url.href)); return; }
  if(req.mode === "navigate"){
    e.respondWith(fetch(req).catch(() => caches.open(CACHE).then(c => c.match(PAGE_URL)).then(hit => hit || Response.error(), () => Response.error())));
  }
});
