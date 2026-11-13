import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';

// Mock $app/environment
vi.mock('$app/environment', () => ({
	browser: true
}));

// Mock the API module
vi.mock('$api/notifications', () => ({
	listNotifications: vi.fn(() => Promise.resolve({ notifications: [], total: 0, unread_count: 0 })),
	markNotificationRead: vi.fn((id: string) =>
		Promise.resolve({
			id,
			type: 'injection',
			title: '',
			body: '',
			data: {},
			is_read: true,
			created_at: ''
		})
	),
	markAllNotificationsRead: vi.fn(() =>
		Promise.resolve({ detail: 'Marked 0 notifications as read.' })
	)
}));

// Mock localStorage
const mockStorage: Record<string, string> = {};
vi.stubGlobal('localStorage', {
	getItem: vi.fn((key: string) => mockStorage[key] ?? null),
	setItem: vi.fn((key: string, value: string) => {
		mockStorage[key] = value;
	}),
	removeItem: vi.fn((key: string) => {
		delete mockStorage[key];
	}),
	clear: vi.fn(),
	length: 0,
	key: vi.fn()
});

describe('notifications store', () => {
	beforeEach(() => {
		vi.resetModules();
		Object.keys(mockStorage).forEach((key) => delete mockStorage[key]);
	});

	it('starts empty', async () => {
		const { notifications, unreadCount } = await import('$stores/notifications');
		expect(get(notifications)).toEqual([]);
		expect(get(unreadCount)).toBe(0);
	});

	it('addNotificationFromSSE adds a notification', async () => {
		const { notifications, addNotificationFromSSE } = await import('$stores/notifications');
		addNotificationFromSSE({
			id: 'n1',
			type: 'injection',
			title: 'Title',
			body: 'Description',
			data: {},
			is_read: false,
			created_at: new Date().toISOString()
		});
		const items = get(notifications);
		expect(items).toHaveLength(1);
		expect(items[0].type).toBe('injection');
		expect(items[0].title).toBe('Title');
		expect(items[0].description).toBe('Description');
	});

	it('addNotificationFromSSE avoids duplicates', async () => {
		const { notifications, addNotificationFromSSE } = await import('$stores/notifications');
		const notif = {
			id: 'n1',
			type: 'injection' as const,
			title: 'Title',
			body: 'Description',
			data: {},
			is_read: false,
			created_at: new Date().toISOString()
		};
		addNotificationFromSSE(notif);
		addNotificationFromSSE(notif);
		expect(get(notifications)).toHaveLength(1);
	});

	it('markAsRead marks one notification as read', async () => {
		const { notifications, unreadCount, markAsRead } = await import('$stores/notifications');
		notifications.set([
			{
				id: 'n1',
				type: 'injection',
				title: 'Title',
				description: 'Desc',
				timestamp: new Date().toISOString(),
				read: false,
				data: {}
			}
		]);
		unreadCount.set(1);
		await markAsRead('n1');
		expect(get(unreadCount)).toBe(0);
		expect(get(notifications)[0].read).toBe(true);
	});

	it('markAllAsRead marks all as read', async () => {
		const { notifications, unreadCount, markAllAsRead } = await import('$stores/notifications');
		notifications.set([
			{
				id: 'n1',
				type: 'injection',
				title: 'A',
				description: 'Desc',
				timestamp: new Date().toISOString(),
				read: false,
				data: {}
			},
			{
				id: 'n2',
				type: 'agent_completed',
				title: 'B',
				description: 'Desc',
				timestamp: new Date().toISOString(),
				read: false,
				data: {}
			}
		]);
		unreadCount.set(2);
		await markAllAsRead();
		expect(get(unreadCount)).toBe(0);
	});

	it('getNotificationIcon returns correct icons', async () => {
		const { getNotificationIcon } = await import('$stores/notifications');
		expect(getNotificationIcon('injection')).toBe('message-circle');
		expect(getNotificationIcon('mention')).toBe('at-sign');
		expect(getNotificationIcon('agent_completed')).toBe('check-circle');
		expect(getNotificationIcon('invitation')).toBe('mail');
		expect(getNotificationIcon('share')).toBe('share-2');
	});

	it('notificationsWithReadState derives from notifications', async () => {
		const { notifications, notificationsWithReadState } = await import('$stores/notifications');
		const items = [
			{
				id: 'n1',
				type: 'injection' as const,
				title: 'A',
				description: 'Desc',
				timestamp: new Date().toISOString(),
				read: true,
				data: {}
			}
		];
		notifications.set(items);
		expect(get(notificationsWithReadState)).toEqual(items);
	});
});
