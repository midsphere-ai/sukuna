import { render, screen, fireEvent, cleanup } from '@testing-library/svelte';
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import Header from '$components/layout/Header.svelte';
import { pageTitle } from '$stores/page';
import { currentUser } from '$stores/auth';
import { notifications, unreadCount } from '$stores/notifications';

// Mock $app/environment
vi.mock('$app/environment', () => ({ browser: true }));

// Mock $stores/conversations (used by NotificationCenter)
vi.mock('$stores/conversations', () => ({
	formatRelativeTime: vi.fn(() => 'Just now')
}));

// Mock $api/billing
vi.mock('$api/billing', () => ({
	getUserSubscription: vi.fn(() =>
		Promise.resolve({
			id: 'sub-1',
			plan: { id: 'plan-1', name: 'Free', tier: 'free', price: 0, features: {}, is_active: true },
			status: 'active',
			start_date: null,
			end_date: null,
			auto_renew: true,
			dodo_subscription_id: null,
			usage_schema: {
				tasks_remaining_week: { limit: 10, used: 0, label: 'Tasks' },
				sandbox_time_remaining_month: { limit: 100, used: 0, label: 'Sandbox' },
				addons_used: { limit: 5, used: 0, label: 'Addons' },
				mcp_servers_added: { limit: 3, used: 0, label: 'MCP' },
				concurrent_tasks: { limit: 2, used: 0, label: 'Concurrent' }
			}
		})
	)
}));

// Mock $api/auth
vi.mock('$api/auth', () => ({
	logout: vi.fn(() => Promise.resolve())
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

beforeEach(() => {
	localStorageMock.clear();
	notifications.set([]);
	unreadCount.set(0);
	currentUser.set({
		id: '1',
		name: 'Test User',
		email: 'test@example.com',
		avatar: '',
		is_active: true,
		date_joined: '',
		last_login: '',
		enterprise_mode: false
	});
});

afterEach(() => {
	cleanup();
	pageTitle.set('Home');
	currentUser.set(null);
});

describe('Header component', () => {
	it('renders with default title', () => {
		render(Header);
		expect(screen.getByText('Home')).toBeInTheDocument();
	});

	it('renders title from page store', () => {
		pageTitle.set('Settings');
		render(Header);
		expect(screen.getByText('Settings')).toBeInTheDocument();
	});

	it('shows weekly tasks remaining count after billing loads', async () => {
		render(Header);
		// Wait for the onMount billing API call to resolve
		await vi.waitFor(() => {
			expect(screen.getByText(/tasks left/)).toBeInTheDocument();
		});
	});

	it('renders notification bell button', () => {
		render(Header);
		expect(screen.getByLabelText('Notifications')).toBeInTheDocument();
	});

	it('shows unread dot indicator when notifications exist', () => {
		notifications.set([
			{
				id: '1',
				type: 'injection',
				title: 'Test',
				description: 'Test description',
				timestamp: new Date().toISOString(),
				read: false,
				data: {}
			},
			{
				id: '2',
				type: 'agent_completed',
				title: 'Task done',
				description: 'Your task finished',
				timestamp: new Date().toISOString(),
				read: false,
				data: {}
			}
		]);
		unreadCount.set(2);
		render(Header);
		const bell = screen.getByLabelText('Notifications');
		const dot = bell.querySelector('.rounded-full.bg-accent');
		expect(dot).toBeInTheDocument();
	});

	it('does not show badge when no notifications', () => {
		render(Header);
		// No coral badge visible in the notification area
		const bellButton = screen.getByLabelText('Notifications');
		const badge = bellButton.querySelector('.bg-accent');
		expect(badge).not.toBeInTheDocument();
	});

	it('renders user menu button', () => {
		render(Header);
		expect(screen.getByLabelText('User menu')).toBeInTheDocument();
	});

	it('user menu button has aria-expanded=false initially', () => {
		render(Header);
		const button = screen.getByLabelText('User menu');
		expect(button).toHaveAttribute('aria-expanded', 'false');
	});

	it('opens popover on avatar click', async () => {
		render(Header);
		const button = screen.getByLabelText('User menu');
		await fireEvent.click(button);
		expect(button).toHaveAttribute('aria-expanded', 'true');
		expect(screen.getByText('Test User')).toBeInTheDocument();
		expect(screen.getByText('test@example.com')).toBeInTheDocument();
	});

	it('shows plan badge in popover', async () => {
		render(Header);
		await fireEvent.click(screen.getByLabelText('User menu'));
		expect(screen.getByText('Free')).toBeInTheDocument();
	});

	it('shows logout button in popover', async () => {
		render(Header);
		await fireEvent.click(screen.getByLabelText('User menu'));
		expect(screen.getByText('Log out')).toBeInTheDocument();
	});

	it('closes popover on logout click', async () => {
		render(Header);
		await fireEvent.click(screen.getByLabelText('User menu'));
		expect(screen.getByText('Log out')).toBeInTheDocument();
		await fireEvent.click(screen.getByText('Log out'));
		expect(screen.queryByText('test@example.com')).not.toBeInTheDocument();
	});

	it('closes popover on outside click', async () => {
		render(Header);
		await fireEvent.click(screen.getByLabelText('User menu'));
		expect(screen.getByText('test@example.com')).toBeInTheDocument();
		// Click outside the popover area
		await fireEvent.click(document.body);
		expect(screen.queryByText('test@example.com')).not.toBeInTheDocument();
	});

	it('popover menu has correct role', async () => {
		render(Header);
		await fireEvent.click(screen.getByLabelText('User menu'));
		expect(screen.getByRole('menu')).toBeInTheDocument();
	});

	it('logout button has menuitem role', async () => {
		render(Header);
		await fireEvent.click(screen.getByLabelText('User menu'));
		expect(screen.getByRole('menuitem')).toBeInTheDocument();
	});

	it('renders a divider between tasks count and notification center', async () => {
		const { container } = render(Header);
		// Wait for billing API to load
		await vi.waitFor(() => {
			const divider = container.querySelector('.h-4.w-px');
			expect(divider).toBeInTheDocument();
		});
	});
});
