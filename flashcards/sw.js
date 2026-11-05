// Service worker for the flashcards (generated into flashcards/sw.js by build.py; edit sw-template.js).
// Every build gets a new VERSION only when the cards or images change. A new version downloads all
// files in the background, then the page offers a "Refresh" button; old caches are deleted on switch.
const VERSION = '233516c154bc';
const PREFIX = 'ml-ds-flashcards-';          // CacheStorage is shared by every repo on *.github.io
const CACHE = PREFIX + VERSION;
const FILES = ["index.html", "media/paste-564b105c5e15e5322403f52e18203d4d395c19df.jpg", "media/paste-590648a629258f351032192b5d43360e03efc06f.jpg", "media/paste-6252ba5390a5439c8d9aae9adc120f1604e65950.jpg", "media/paste-77361644ec8220b127b812f84d816937bef00266.jpg", "media/paste-9bca3656e72b9607b7ed707921cf6b7d4af2c2f2.jpg", "media/paste-acff2f0ed0a7f3db1333c6ec69a06bb0988c08bc.jpg", "media/paste-c1a025d3d76a38243f9c2bcc5d7a87db35ff24ed.jpg", "media/paste-cd71ebbc561bf2c24a5c2e4816b5ad952eff1d5e.jpg", "media/paste-d219be8b71c6a527375335139e2474bf752d8649.jpg", "media/paste-d33dac366ee933af5eefafcef0e711a542379225.jpg", "media/paste-fc4b013badf94d0449eb60fd901f19c0bd8fa3d5.jpg"];
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
