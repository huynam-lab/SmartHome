const APP_CACHE = "smart-home-app-v3";
const RUNTIME_CACHE = "smart-home-runtime-v3";
const APP_SHELL_URLS = [
    "/",
    "/offline",
    "/manifest.webmanifest",
    "/static/style.css",
    "/static/app.js",
    "/static/app/api.js",
    "/static/app/auth.js",
    "/static/app/chat.js",
    "/static/app/core.js",
    "/static/app/devices.js",
    "/static/app/main.js",
    "/static/app/realtime.js",
    "/static/app/ui.js",
    "/static/app/utils.js",
    "/static/pwa/icon-192.png",
    "/static/pwa/icon-512.png",
    "/static/pwa/icon.svg",
    "/static/pwa/icon-maskable.svg",
    "/static/pwa/apple-touch-icon.png",
    "/static/pwa/apple-touch-icon.svg",
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(APP_CACHE).then((cache) => cache.addAll(APP_SHELL_URLS))
    );
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((keys) => Promise.all(
            keys
                .filter((key) => ![APP_CACHE, RUNTIME_CACHE].includes(key))
                .map((key) => caches.delete(key))
        ))
    );
    self.clients.claim();
});

function shouldBypassRequest(requestUrl, requestMethod) {
    if (requestMethod !== "GET") {
        return true;
    }

    if (requestUrl.origin !== self.location.origin) {
        return true;
    }

    return requestUrl.pathname.startsWith("/api/") || requestUrl.pathname.startsWith("/socket.io/");
}

self.addEventListener("fetch", (event) => {
    const requestUrl = new URL(event.request.url);

    if (shouldBypassRequest(requestUrl, event.request.method)) {
        return;
    }

    if (event.request.mode === "navigate") {
        event.respondWith(
            fetch(event.request)
                .then((response) => {
                    const responseClone = response.clone();
                    caches.open(RUNTIME_CACHE).then((cache) => cache.put(event.request, responseClone));
                    return response;
                })
                .catch(async () => {
                    const runtimeMatch = await caches.match(event.request);
                    return runtimeMatch || caches.match("/offline");
                })
        );
        return;
    }

    event.respondWith(
        caches.match(event.request).then((cachedResponse) => {
            if (cachedResponse) {
                return cachedResponse;
            }

            return fetch(event.request).then((response) => {
                if (!response || response.status !== 200 || response.type !== "basic") {
                    return response;
                }

                const responseClone = response.clone();
                caches.open(RUNTIME_CACHE).then((cache) => cache.put(event.request, responseClone));
                return response;
            });
        })
    );
});
