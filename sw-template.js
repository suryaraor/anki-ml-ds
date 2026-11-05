// Service worker for the flashcards (generated into flashcards/sw.js by build.py; edit sw-template.js).
// Every build gets a new VERSION only when the cards or images change. A new version downloads all
// files in the background, then the page offers a "Refresh" button; old caches are deleted on switch.
const VERSION = '__VERSION__';
const PREFIX = 'ml-ds-flashcards-';          // CacheStorage is shared by every repo on *.github.io
const CACHE = PREFIX + VERSION;
const FILES = /*FILES*/[];
const url = f => new URL(f, self.registration.scope).href;

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(cache => Promise.all(FILES.map(f =>
    // ?v= skips stale copies in the browser and CDN caches; stored under the clean URL.
    fetch(url(f) + (f.includes('?') ? '&' : '?') + 'v=' + VERSION, {cache: 'no-cache'}).then(res => {
      if (!res.ok) throw new Error(f + ': HTTP ' + res.status);
      return cache.put(url(f), res);
    })))));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k.startsWith(PREFIX) && k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('message', e => { if (e.data === 'skipWaiting') self.skipWaiting(); });

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET' || !req.url.startsWith(self.registration.scope)) return;
  const u = new URL(req.url);
  if (u.searchParams.has('v')) return;       // our own versioned install requests
  const page = req.mode === 'navigate' && /\/(index\.html)?$/.test(u.pathname);
  const key = page ? url('index.html') : u.origin + u.pathname;
  e.respondWith(caches.open(CACHE).then(cache => cache.match(key).then(hit => hit || fetch(req).then(res => {
    // An image that wasn't precached is cached the first time it loads.
    if (res.ok && res.type === 'basic' && /\/media\/[^/]+$/.test(u.pathname)) cache.put(key, res.clone());
    return res;
  }))));
});
