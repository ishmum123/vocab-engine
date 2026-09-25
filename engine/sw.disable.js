// Kill switch for the offline cache. To turn it off on a published site, copy this file
// over sw.js (after build.sh, which rewrites sw.js) and publish. Never just delete sw.js:
// a 404 on the update check leaves the installed worker serving its cached page forever.
// Browsers that load the page next fetch this worker; it installs at once, deletes this
// site's ve:<scope path>: caches (never another language site's) and unregisters itself.
// It has no fetch handler, so from then on every request goes to the network. The page
// still calls register("sw.js") on each load; this worker just unregisters again.
// To re-enable, rebuild (build.sh writes the real sw.js again) and publish.
"use strict";
const PREFIX = "ve:" + new URL(self.registration.scope).pathname + ":";
self.addEventListener("install", () => { self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k.indexOf(PREFIX) === 0).map(k => caches.delete(k))))
    .then(() => self.registration.unregister()));
});
