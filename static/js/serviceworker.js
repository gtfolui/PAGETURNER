var CACHE_NAME = 'pageturner-cache-v2';
var urlsToCache = [
    '/static/img/icon-192.png',
    '/static/img/icon-512.png',
];

// Install
self.addEventListener('install', function(e) {
    self.skipWaiting();
    e.waitUntil(
        caches.open(CACHE_NAME).then(function(cache) {
            return cache.addAll(urlsToCache);
        })
    );
});

// Activate - clean up old caches immediately
self.addEventListener('activate', function(e) {
    e.waitUntil(
        caches.keys().then(function(cacheNames) {
            return Promise.all(
                cacheNames.filter(function(name) {
                    return name !== CACHE_NAME;
                }).map(function(name) {
                    return caches.delete(name);
                })
            );
        }).then(function() {
            return self.clients.claim();
        })
    );
});

// Fetch - network first, fallback to cache (only for static assets)
self.addEventListener('fetch', function(e) {
    var url = new URL(e.request.url);

    // Always go to network for HTML pages and auth routes
    if (e.request.mode === 'navigate' ||
        url.pathname.startsWith('/accounts/') ||
        url.pathname.startsWith('/admin/')) {
        e.respondWith(fetch(e.request));
        return;
    }

    // Network first for everything else
    e.respondWith(
        fetch(e.request).then(function(response) {
            return response;
        }).catch(function() {
            return caches.match(e.request);
        })
    );
});