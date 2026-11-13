import { writable, derived, get } from 'svelte/store';
import { browser } from '$app/environment';
import {
	listNotifications,
	markNotificationRead,
	markAllNotificationsRead,
	type BackendNotification,
	type BackendNotificationType
} from '$api/notifications';

export type NotificationType = BackendNotificationType;

export interface AppNotification {
	id: string;
	type: NotificationType;
	title: string;
	description: string;
	timestamp: string;
	read: boolean;
	href?: string;
	data: Record<string, unknown>;
}

/** Raw backend notifications */
export const notifications = writable<AppNotification[]>([]);

/** Total notifications on server */
export const notificationTotal = writable(0);

/** Unread count from server */
export const unreadCount = writable(0);

/** Whether the initial load has completed */
export const notificationsLoaded = writable(false);

/** Derived: same as notifications (read state is already baked in) */
export const notificationsWithReadState = derived(notifications, ($n) => $n);

// ── Backend sync ────────────────────────────────────────────────────────────

function toAppNotification(n: BackendNotification): AppNotification {
	// Build an href from notification data
	let href: string | undefined;
	const conversationId = n.data?.conversation_id as string | undefined;
	const projectId = n.data?.project_id as string | undefined;
	if (conversationId) {
		href = `/chat/${conversationId}`;
	} else if (projectId) {
		href = `/projects/${projectId}`;
	}

	return {
		id: n.id,
		type: n.type,
		title: n.title,
		description: n.body,
		timestamp: n.created_at,
		read: n.is_read,
		href,
		data: n.data
	};
}

let fetchInFlight = false;

export async function fetchNotifications(): Promise<void> {
	if (!browser || fetchInFlight) return;
	fetchInFlight = true;
	try {
		const resp = await listNotifications(0, 50);
		notifications.set(resp.notifications.map(toAppNotification));
		notificationTotal.set(resp.total);
		unreadCount.set(resp.unread_count);
		notificationsLoaded.set(true);
	} catch {
		// Silently fail — user might not be authenticated yet
	} finally {
		fetchInFlight = false;
	}
}

export async function markAsRead(id: string): Promise<void> {
	// Optimistic update
	notifications.update((items) => items.map((n) => (n.id === id ? { ...n, read: true } : n)));
	unreadCount.update((c) => Math.max(0, c - 1));
	try {
		await markNotificationRead(id, true);
	} catch {
		// Revert on failure
		await fetchNotifications();
	}
}

export async function markAllAsRead(): Promise<void> {
	// Optimistic update
	notifications.update((items) => items.map((n) => ({ ...n, read: true })));
	const prevCount = get(unreadCount);
	unreadCount.set(0);
	try {
		await markAllNotificationsRead();
	} catch {
		unreadCount.set(prevCount);
		await fetchNotifications();
	}
}

export function addNotificationFromSSE(n: BackendNotification): void {
	const appNotif = toAppNotification(n);
	notifications.update((items) => {
		// Avoid duplicates
		if (items.some((existing) => existing.id === n.id)) return items;
		return [appNotif, ...items];
	});
	unreadCount.update((c) => c + 1);
	notificationTotal.update((t) => t + 1);
}

// ── Icon helpers ────────────────────────────────────────────────────────────

const NOTIFICATION_TYPE_ICONS: Record<NotificationType, string> = {
	injection: 'message-circle',
	mention: 'at-sign',
	agent_completed: 'check-circle',
	invitation: 'mail',
	share: 'share-2'
};

export function getNotificationIcon(type: NotificationType): string {
	return NOTIFICATION_TYPE_ICONS[type] || 'bell';
}
