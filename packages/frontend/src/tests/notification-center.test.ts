import { render, screen, fireEvent, cleanup } from '@testing-library/svelte';
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import {
	notifications,
	unreadCount,
	notificationsWithReadState,
	markAsRead,
	markAllAsRead,
	getNotificationIcon,
	type AppNotification
} from '$stores/notifications';
import { get } from 'svelte/store';

// Mock $app/environment
vi.mock('$app/environment', () => ({ browser: true }));

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
const localStorageMock = (() => {
	let store: Record<string, string> = {};
	return {
		getItem: vi.fn((key: string) => store[key] ?? null),
		setItem: vi.fn((key: string, value: string) => {
			store[key] = value;
		}),
		removeItem: vi.fn((key: string) => {
			delete store[key];
		}),
		clear: vi.fn(() => {
			store = {};
		})
	};
})();

vi.stubGlobal('localStorage', localStorageMock);

function makeNotification(overrides: Partial<AppNotification> = {}): AppNotification {
	return {
		id: `notif-${Date.now()}-${Math.random()}`,
		type: 'injection',
		title: 'Test',
		description: 'Test description',
		timestamp: new Date().toISOString(),
		read: false,
		data: {},
		...overrides
	};
}

beforeEach(() => {
	localStorageMock.clear();
	notifications.set([]);
	unreadCount.set(0);
});

afterEach(() => {
	cleanup();
});

// ─── Notification Store Tests ───

describe('Notification store', () => {
	it('starts with empty notifications', () => {
		expect(get(notifications)).toEqual([]);
	});

	it('starts with zero unread count', () => {
		expect(get(unreadCount)).toBe(0);
	});

	it('unreadCount reflects the store value', () => {
		unreadCount.set(5);
		expect(get(unreadCount)).toBe(5);
	});

	it('markAsRead reduces unread count optimistically', async () => {
		const n = makeNotification({ id: 'n1' });
		notifications.set([n]);
		unreadCount.set(1);
		await markAsRead('n1');
		expect(get(unreadCount)).toBe(0);
		expect(get(notifications)[0].read).toBe(true);
	});

	it('markAllAsRead marks all notifications as read optimistically', async () => {
		notifications.set([
			makeNotification({ id: 'n1' }),
			makeNotification({ id: 'n2' }),
			makeNotification({ id: 'n3' })
		]);
		unreadCount.set(3);
		await markAllAsRead();
		expect(get(unreadCount)).toBe(0);
		get(notifications).forEach((n) => expect(n.read).toBe(true));
	});

	it('getNotificationIcon returns correct icon names', () => {
		expect(getNotificationIcon('injection')).toBe('message-circle');
		expect(getNotificationIcon('mention')).toBe('at-sign');
		expect(getNotificationIcon('agent_completed')).toBe('check-circle');
		expect(getNotificationIcon('invitation')).toBe('mail');
		expect(getNotificationIcon('share')).toBe('share-2');
	});

	it('notificationsWithReadState derives from notifications', () => {
		const items = [makeNotification({ id: 'n1', read: true })];
		notifications.set(items);
		expect(get(notificationsWithReadState)).toEqual(items);
	});
});

// ─── NotificationCenter Component Tests ───

vi.mock('$stores/conversations', () => ({
	formatRelativeTime: vi.fn((dateStr: string) => {
		const date = new Date(dateStr);
		const now = new Date();
		const diffMs = now.getTime() - date.getTime();
		const diffMins = Math.floor(diffMs / 60000);
		if (diffMins < 1) return 'Just now';
		if (diffMins < 60) return `${diffMins}m ago`;
		return `${Math.floor(diffMs / 3600000)}h ago`;
	})
}));

import NotificationCenter from '$components/layout/NotificationCenter.svelte';

describe('NotificationCenter component', () => {
	beforeEach(() => {
		notifications.set([]);
		unreadCount.set(0);
	});

	it('renders bell button', () => {
		render(NotificationCenter);
		expect(screen.getByLabelText('Notifications')).toBeInTheDocument();
	});

	it('does not show badge when no unread notifications', () => {
		render(NotificationCenter);
		expect(screen.queryByTestId('notification-badge')).not.toBeInTheDocument();
	});

	it('shows unread count badge when there are unread notifications', () => {
		notifications.set([makeNotification()]);
		unreadCount.set(1);
		render(NotificationCenter);
		const badge = screen.getByTestId('notification-badge');
		expect(badge).toBeInTheDocument();
		expect(badge.textContent?.trim()).toBe('1');
	});

	it('shows 99+ for many unread notifications', () => {
		const items = Array.from({ length: 100 }, (_, i) =>
			makeNotification({ id: `n-${i}`, title: `Notification ${i}` })
		);
		notifications.set(items);
		unreadCount.set(100);
		render(NotificationCenter);
		const badge = screen.getByTestId('notification-badge');
		expect(badge.textContent?.trim()).toBe('99+');
	});

	it('opens dropdown on bell click', async () => {
		render(NotificationCenter);
		await fireEvent.click(screen.getByLabelText('Notifications'));
		expect(screen.getByRole('dialog')).toBeInTheDocument();
	});

	it('shows empty state when no notifications', async () => {
		render(NotificationCenter);
		await fireEvent.click(screen.getByLabelText('Notifications'));
		expect(screen.getByText('No notifications yet')).toBeInTheDocument();
	});

	it('shows notification items in dropdown', async () => {
		notifications.set([
			makeNotification({ title: 'New Feature', description: 'Check it out' }),
			makeNotification({
				title: 'Task Done',
				description: 'Your task finished',
				type: 'agent_completed'
			})
		]);
		unreadCount.set(2);
		render(NotificationCenter);
		await fireEvent.click(screen.getByLabelText('Notifications'));
		expect(screen.getByText('New Feature')).toBeInTheDocument();
		expect(screen.getByText('Task Done')).toBeInTheDocument();
	});

	it('shows "Mark all as read" when there are unread notifications', async () => {
		notifications.set([makeNotification()]);
		unreadCount.set(1);
		render(NotificationCenter);
		await fireEvent.click(screen.getByLabelText('Notifications'));
		expect(screen.getByText('Mark all as read')).toBeInTheDocument();
	});

	it('marks all as read when clicking "Mark all as read"', async () => {
		notifications.set([makeNotification({ id: 'n1' }), makeNotification({ id: 'n2' })]);
		unreadCount.set(2);
		render(NotificationCenter);
		await fireEvent.click(screen.getByLabelText('Notifications'));
		await fireEvent.click(screen.getByText('Mark all as read'));
		expect(get(unreadCount)).toBe(0);
	});

	it('shows unread indicator bar for unread notifications', async () => {
		notifications.set([makeNotification({ title: 'Unread' })]);
		unreadCount.set(1);
		render(NotificationCenter);
		await fireEvent.click(screen.getByLabelText('Notifications'));
		const indicator = screen.getByTestId('unread-indicator');
		expect(indicator).toBeInTheDocument();
	});

	it('closes dropdown on escape key', async () => {
		notifications.set([makeNotification({ title: 'Test' })]);
		unreadCount.set(1);
		render(NotificationCenter);
		await fireEvent.click(screen.getByLabelText('Notifications'));
		expect(screen.getByText('Test')).toBeInTheDocument();
		const dialog = screen.getByRole('dialog');
		await fireEvent.keyDown(dialog, { key: 'Escape' });
		expect(screen.queryByText('Test')).not.toBeInTheDocument();
	});

	it('bell button has correct aria attributes when open', async () => {
		render(NotificationCenter);
		const bell = screen.getByLabelText('Notifications');
		expect(bell).toHaveAttribute('aria-expanded', 'false');
		await fireEvent.click(bell);
		expect(bell).toHaveAttribute('aria-expanded', 'true');
	});

	it('shows correct badge variants for different notification types', async () => {
		notifications.set([
			makeNotification({ type: 'agent_completed', title: 'Done' }),
			makeNotification({ type: 'invitation', title: 'Invite' }),
			makeNotification({ type: 'share', title: 'Shared item' }),
			makeNotification({ type: 'mention', title: 'You were mentioned' })
		]);
		unreadCount.set(4);
		render(NotificationCenter);
		await fireEvent.click(screen.getByLabelText('Notifications'));
		expect(screen.getByText('Completed')).toBeInTheDocument();
		expect(screen.getByText('Invitation')).toBeInTheDocument();
		expect(screen.getByText('Shared')).toBeInTheDocument();
		expect(screen.getByText('Mention')).toBeInTheDocument();
	});

	it('notification items have data-testid', async () => {
		notifications.set([makeNotification()]);
		unreadCount.set(1);
		render(NotificationCenter);
		await fireEvent.click(screen.getByLabelText('Notifications'));
		expect(screen.getByTestId('notification-item')).toBeInTheDocument();
	});

	it('notification with href renders as link', async () => {
		notifications.set([makeNotification({ href: '/chat/123', title: 'Payment' })]);
		unreadCount.set(1);
		render(NotificationCenter);
		await fireEvent.click(screen.getByLabelText('Notifications'));
		const link = screen.getByTestId('notification-item');
		expect(link).toHaveAttribute('href', '/chat/123');
	});

	it('notification without href renders with # href', async () => {
		notifications.set([makeNotification({ title: 'News' })]);
		unreadCount.set(1);
		render(NotificationCenter);
		await fireEvent.click(screen.getByLabelText('Notifications'));
		const link = screen.getByTestId('notification-item');
		expect(link).toHaveAttribute('href', '#');
	});
});
