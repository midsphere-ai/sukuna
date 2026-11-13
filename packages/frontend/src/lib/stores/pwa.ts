import { writable } from 'svelte/store';
import { browser } from '$app/environment';
import { isTauri } from '$utils/platform';

interface BeforeInstallPromptEvent extends Event {
	prompt(): Promise<void>;
	userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

/** Whether the PWA install prompt can be shown */
export const canInstall = writable(false);

/** Whether push notifications are supported and granted */
export const pushEnabled = writable(false);

/** Whether the app is running in standalone (installed) mode */
export const isInstalled = writable(false);

let deferredPrompt: BeforeInstallPromptEvent | null = null;

const VISIT_COUNT_KEY = 'midsphere-visit-count';
const INSTALL_DISMISSED_KEY = 'midsphere-install-dismissed';
const MIN_VISITS_FOR_PROMPT = 2;

/**
 * Register the service worker and set up PWA event listeners.
 * Call this once from the root layout on mount.
 */
export async function initPWA(): Promise<void> {
	if (!browser || isTauri()) return;

	// Track installed state
	const isStandalone =
		window.matchMedia('(display-mode: standalone)').matches ||
		('standalone' in navigator && (navigator as { standalone?: boolean }).standalone === true);
	isInstalled.set(isStandalone);

	// Track visit count for install prompt
	try {
		const count = parseInt(localStorage.getItem(VISIT_COUNT_KEY) ?? '0', 10) + 1;
		localStorage.setItem(VISIT_COUNT_KEY, String(count));
	} catch {
		// localStorage unavailable
	}

	// Listen for beforeinstallprompt
	window.addEventListener('beforeinstallprompt', (e) => {
		e.preventDefault();
		deferredPrompt = e as BeforeInstallPromptEvent;

		// Only show prompt after enough visits and if not previously dismissed
		try {
			const count = parseInt(localStorage.getItem(VISIT_COUNT_KEY) ?? '0', 10);
			const dismissed = localStorage.getItem(INSTALL_DISMISSED_KEY) === 'true';
			if (count >= MIN_VISITS_FOR_PROMPT && !dismissed) {
				canInstall.set(true);
			}
		} catch {
			canInstall.set(true);
		}
	});

	// Detect install
	window.addEventListener('appinstalled', () => {
		canInstall.set(false);
		isInstalled.set(true);
		deferredPrompt = null;
	});

	// Register service worker
	if ('serviceWorker' in navigator) {
		try {
			const registration = await navigator.serviceWorker.register('/service-worker.js', {
				scope: '/'
			});

			// Check push notification permission state
			if ('PushManager' in window && registration.pushManager) {
				const subscription = await registration.pushManager.getSubscription();
				pushEnabled.set(subscription !== null);
			}
		} catch {
			// Service worker registration failed — not critical
		}
	}
}

/**
 * Trigger the native install prompt.
 * Returns true if the user accepted.
 */
export async function promptInstall(): Promise<boolean> {
	if (!deferredPrompt) return false;

	await deferredPrompt.prompt();
	const { outcome } = await deferredPrompt.userChoice;

	if (outcome === 'dismissed') {
		try {
			localStorage.setItem(INSTALL_DISMISSED_KEY, 'true');
		} catch {
			// localStorage unavailable
		}
	}

	deferredPrompt = null;
	canInstall.set(false);

	return outcome === 'accepted';
}

/**
 * Request push notification permission and subscribe.
 * Returns the PushSubscription if successful, null otherwise.
 */
export async function subscribeToPush(vapidPublicKey?: string): Promise<PushSubscription | null> {
	if (!browser || !('serviceWorker' in navigator) || !('PushManager' in window)) {
		return null;
	}

	const permission = await Notification.requestPermission();
	if (permission !== 'granted') {
		pushEnabled.set(false);
		return null;
	}

	try {
		const registration = await navigator.serviceWorker.ready;

		const subscribeOptions: PushSubscriptionOptionsInit = {
			userVisibleOnly: true
		};

		if (vapidPublicKey) {
			subscribeOptions.applicationServerKey = urlBase64ToUint8Array(vapidPublicKey)
				.buffer as ArrayBuffer;
		}

		const subscription = await registration.pushManager.subscribe(subscribeOptions);
		pushEnabled.set(true);

		return subscription;
	} catch {
		pushEnabled.set(false);
		return null;
	}
}

/**
 * Unsubscribe from push notifications.
 */
export async function unsubscribeFromPush(): Promise<boolean> {
	if (!browser || !('serviceWorker' in navigator)) return false;

	try {
		const registration = await navigator.serviceWorker.ready;
		const subscription = await registration.pushManager.getSubscription();
		if (subscription) {
			await subscription.unsubscribe();
			pushEnabled.set(false);
			return true;
		}
		return false;
	} catch {
		return false;
	}
}

/** Convert a base64-encoded VAPID key to Uint8Array for PushManager.subscribe */
function urlBase64ToUint8Array(base64String: string): Uint8Array {
	const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
	const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
	const rawData = atob(base64);
	const outputArray = new Uint8Array(rawData.length);
	for (let i = 0; i < rawData.length; i++) {
		outputArray[i] = rawData.charCodeAt(i);
	}
	return outputArray;
}
