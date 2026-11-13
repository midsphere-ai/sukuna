import { api } from './client';

// ── Types ───────────────────────────────────────────────────────────────────

export type BackendNotificationType =
	'injection' | 'mention' | 'agent_completed' | 'invitation' | 'share';

export interface BackendNotification {
	id: string;
	type: BackendNotificationType;
	title: string;
	body: string;
	data: Record<string, unknown>;
	is_read: boolean;
	created_at: string;
}

export interface NotificationListResponse {
	notifications: BackendNotification[];
	total: number;
	unread_count: number;
}

export interface PreferenceItem {
	notification_type: BackendNotificationType;
	in_app: boolean;
	email: boolean;
	push: boolean;
	slack: boolean;
	discord: boolean;
	muted_project_ids: string[];
}

export interface PreferencesResponse {
	preferences: PreferenceItem[];
}

export interface PreferenceUpdate {
	notification_type: string;
	in_app?: boolean;
	email?: boolean;
	push?: boolean;
	slack?: boolean;
	discord?: boolean;
	muted_project_ids?: string[];
}

// ── API calls ───────────────────────────────────────────────────────────────

const BASE = '/notifications';

export function listNotifications(offset = 0, limit = 50): Promise<NotificationListResponse> {
	return api.get<NotificationListResponse>(`${BASE}/?offset=${offset}&limit=${limit}`);
}

export function markNotificationRead(
	notificationId: string,
	isRead = true
): Promise<BackendNotification> {
	return api.patch<BackendNotification>(`${BASE}/${notificationId}`, { is_read: isRead });
}

export function markAllNotificationsRead(): Promise<{ detail: string }> {
	return api.patch<{ detail: string }>(`${BASE}/read-all`);
}

export function getNotificationPreferences(): Promise<PreferencesResponse> {
	return api.get<PreferencesResponse>(`${BASE}/preferences`);
}

export function updateNotificationPreferences(
	preferences: PreferenceUpdate[]
): Promise<PreferencesResponse> {
	return api.patch<PreferencesResponse>(`${BASE}/preferences`, { preferences });
}
