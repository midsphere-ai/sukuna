/// <reference types="@sveltejs/kit" />
/// <reference no-default-lib="true"/>
/// <reference lib="esnext" />
/// <reference lib="webworker" />

import { build, files, version } from '$service-worker';

declare const self: ServiceWorkerGlobalScope;

const CACHE_NAME = `midsphere-cache-${version}`;

// App shell: built assets (JS, CSS, etc.)
const APP_SHELL = build;

// Static files (fonts, icons, etc.)
const STATIC_ASSETS = files;

// All assets to precache
const PRECACHE_ASSETS = [...APP_SHELL, ...STATIC_ASSETS];

// Routes that should always go to network (API, SSE, auth)
const NETWORK_ONLY_PATTERNS = ['/api/', '/authentication/'];

self.addEventListener('install', (event: ExtendableEvent) => {
	event.waitUntil(
		(PRECACHE_ASSETS.length > 0
			? caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_ASSETS))
			: Promise.resolve()
		).then(() => self.skipWaiting())
	);
});

self.addEventListener('activate', (event: ExtendableEvent) => {
	event.waitUntil(
		caches
			.keys()
			.then((keys) =>
				Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
			)
			.then(() => self.clients.claim())
	);
});

self.addEventListener('fetch', (event: FetchEvent) => {
	const url = new URL(event.request.url);

	// Skip non-GET requests
	if (event.request.method !== 'GET') return;

	// Skip cross-origin requests
	if (url.origin !== self.location.origin) return;

	// Network-only for API routes
	if (NETWORK_ONLY_PATTERNS.some((pattern) => url.pathname.startsWith(pattern))) return;

	// Navigation requests: network-first, offline fallback only
	if (event.request.mode === 'navigate') {
		event.respondWith(
			fetch(event.request).catch(() => {
				return caches.match('/offline') || new Response('Offline', { status: 503 });
			})
		);
		return;
	}

	// Static assets: cache-first
	event.respondWith(
		caches.match(event.request).then((cached) => {
			if (cached) return cached;
			return fetch(event.request);
		})
	);
});

// Handle push notifications
self.addEventListener('push', (event: PushEvent) => {
	const data = event.data?.json() ?? { title: 'Jatayu AI', body: 'You have a new notification.' };

	event.waitUntil(
		self.registration.showNotification(data.title ?? 'Jatayu AI', {
			body: data.body,
			icon: '/icons/icon-192.png',
			badge: '/icons/icon-192.png',
			tag: data.tag ?? 'midsphere-notification',
			data: data.url ? { url: data.url } : undefined
		})
	);
});

self.addEventListener('notificationclick', (event: NotificationEvent) => {
	event.notification.close();

	const url = event.notification.data?.url ?? '/';

	event.waitUntil(
		self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
			// Focus existing window if available
			for (const client of clients) {
				if (client.url === url && 'focus' in client) {
					return client.focus();
				}
			}
			// Open new window
			return self.clients.openWindow(url);
		})
	);
});
