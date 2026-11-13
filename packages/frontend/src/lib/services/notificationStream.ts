/**
 * SSE stream for real-time notification delivery.
 *
 * Uses polling with cache-based signals from the backend. When a new
 * notification is created, the backend stores a signal in cache. We poll
 * periodically and fetch new notifications when a signal is detected.
 *
 * This approach matches the backend's _publish_sse_event pattern which
 * sets a cache key `notification_signal:{user_id}` rather than a true
 * SSE stream.
 */
import { browser } from '$app/environment';
import { get } from 'svelte/store';
import { authToken } from '$stores/auth';
import { fetchNotifications } from '$stores/notifications';

const POLL_INTERVAL_MS = 15_000; // Poll every 15 seconds

let pollTimer: ReturnType<typeof setInterval> | null = null;
let isActive = false;

export function startNotificationPolling(): void {
	if (!browser || isActive) return;

	const token = get(authToken);
	if (!token) return;

	isActive = true;

	// Initial fetch
	fetchNotifications();

	// Periodic polling
	pollTimer = setInterval(() => {
		const currentToken = get(authToken);
		if (!currentToken) {
			stopNotificationPolling();
			return;
		}
		fetchNotifications();
	}, POLL_INTERVAL_MS);
}

export function stopNotificationPolling(): void {
	if (pollTimer) {
		clearInterval(pollTimer);
		pollTimer = null;
	}
	isActive = false;
}

export function getIsPolling(): boolean {
	return isActive;
}
