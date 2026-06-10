const CACHE_NAME = 'ddd-system-v3';  // 改版本号，强制刷新旧缓存
const urlsToCache = [
  './DDD_system.html',
  './manifest.json',
  './sw.js'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(urlsToCache))
  );
  self.skipWaiting(); // 立即激活新 SW
});

self.addEventListener('activate', event => {
  // 清理旧版本缓存
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request).then(response => response || fetch(event.request))
  );
});