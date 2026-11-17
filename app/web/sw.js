/* 家庭积分 v1.25 · app shell 缓存
   只缓存静态壳，API 永远走网络；导航离线时回 index.html。 */
const CACHE = 'fp-1.25';
const CORE = [
  '/', '/index.html',
  '/style.css?v=1.25', '/login.css?v=1.25', '/theme-sky.css?v=1.25',
  '/icons.js?v=1.25', '/avatars.js?v=1.25', '/app.js?v=1.25',
  '/icon-192.png', '/icon-512.png', '/site.webmanifest',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE)
      .then(cache => Promise.allSettled(CORE.map(url => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/')) return;

  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(() => caches.match('/index.html')));
    return;
  }

  event.respondWith(
    caches.match(req).then(hit => {
      if (hit) return hit;
      return fetch(req).then(resp => {
        if (resp && resp.status === 200 && resp.type === 'basic') {
          const copy = resp.clone();
          caches.open(CACHE).then(cache => cache.put(req, copy));
        }
        return resp;
      });
    })
  );
});
