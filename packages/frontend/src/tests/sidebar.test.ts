import { render, screen, fireEvent, cleanup } from '@testing-library/svelte';
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { get } from 'svelte/store';

vi.mock('$app/environment', () => ({
	browser: true,
	dev: false,
	version: '0.0.1'
}));

vi.mock('$stores/settings', async () => {
	const { writable } = await import('svelte/store');
	const settingsOpen = writable(false);
	return {
		theme: {
			subscribe: vi.fn((cb: (v: string) => void) => {
				cb('light');
				return () => {};
			})
		},
		fontSize: {
			subscribe: vi.fn((cb: (v: number) => void) => {
				cb(14);
				return () => {};
			})
		},
		resolvedTheme: {
			subscribe: vi.fn((cb: (v: string) => void) => {
				cb('light');
				return () => {};
			})
		},
		settingsOpen,
		openSettings: vi.fn(() => settingsOpen.set(true)),
		closeSettings: vi.fn(() => settingsOpen.set(false))
	};
});

vi.mock('$app/navigation', () => ({
	goto: vi.fn()
}));

vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	return {
		page: writable({ url: { pathname: '/' } })
	};
});

vi.mock('$api/conversations', () => ({
	getConversations: vi.fn().mockResolvedValue({
		count: 0,
		items: []
	}),
	deleteConversation: vi.fn().mockResolvedValue({ message: 'deleted', deleted_count: 1 }),
	renameConversation: vi.fn().mockResolvedValue({ id: 'test', title: 'renamed' })
}));

vi.mock('$stores/toast', () => ({
	toasts: {
		success: vi.fn(),
		error: vi.fn(),
		warning: vi.fn(),
		info: vi.fn(),
		remove: vi.fn(),
		subscribe: vi.fn((cb: (v: unknown[]) => void) => {
			cb([]);
			return () => {};
		})
	}
}));

vi.mock('$services/conversationStream', () => ({
	connect: vi.fn(),
	disconnect: vi.fn(),
	getIsConnected: vi.fn(() => false)
}));

import Sidebar from '$components/layout/Sidebar.svelte';
import {
	sidebarHidden,
	sidebarMobileOpen,
	toggleSidebar,
	openMobileSidebar,
	closeMobileSidebar
} from '$stores/sidebar';

let mockLocalStorage: Record<string, string>;

beforeEach(() => {
	mockLocalStorage = {};
	vi.stubGlobal('localStorage', {
		getItem: (key: string) => mockLocalStorage[key] ?? null,
		setItem: (key: string, value: string) => {
			mockLocalStorage[key] = value;
		},
		removeItem: (key: string) => {
			delete mockLocalStorage[key];
		}
	});
	vi.stubGlobal('sessionStorage', {
		getItem: () => null,
		setItem: () => {},
		removeItem: () => {}
	});
});

afterEach(() => {
	cleanup();
	sidebarHidden.set(false);
	sidebarMobileOpen.set(false);
	vi.unstubAllGlobals();
});

describe('sidebar store', () => {
	it('starts with hidden = false', () => {
		expect(get(sidebarHidden)).toBe(false);
	});

	it('starts with mobileOpen = false', () => {
		expect(get(sidebarMobileOpen)).toBe(false);
	});

	it('toggleSidebar flips hidden state', () => {
		toggleSidebar();
		expect(get(sidebarHidden)).toBe(true);
		toggleSidebar();
		expect(get(sidebarHidden)).toBe(false);
	});

	it('openMobileSidebar sets mobileOpen to true', () => {
		openMobileSidebar();
		expect(get(sidebarMobileOpen)).toBe(true);
	});

	it('closeMobileSidebar sets mobileOpen to false', () => {
		openMobileSidebar();
		closeMobileSidebar();
		expect(get(sidebarMobileOpen)).toBe(false);
	});
});

describe('Sidebar component', () => {
	it('renders sidebar navigation landmark', () => {
		render(Sidebar);
		expect(screen.getByLabelText('Sidebar navigation')).toBeInTheDocument();
	});

	it('renders logo image', () => {
		render(Sidebar);
		expect(screen.getAllByAltText('Jatayu AI').length).toBeGreaterThan(0);
	});

	it('renders nav items', () => {
		render(Sidebar);
		expect(screen.getByText('Create')).toBeInTheDocument();
		expect(screen.getByText('Search')).toBeInTheDocument();
		expect(screen.getByText('Library')).toBeInTheDocument();
	});

	it('renders bottom nav items', () => {
		render(Sidebar);
		expect(screen.getByText('Connectors')).toBeInTheDocument();
		expect(screen.getByText('Settings')).toBeInTheDocument();
	});

	it('renders conversation list area', () => {
		render(Sidebar);
		expect(screen.getByLabelText('Conversations')).toBeInTheDocument();
	});

	it('renders hide sidebar button', () => {
		render(Sidebar);
		expect(screen.getByLabelText('Hide sidebar')).toBeInTheDocument();
	});

	it('renders close button for mobile', () => {
		render(Sidebar);
		expect(screen.getByLabelText('Close sidebar')).toBeInTheDocument();
	});

	it('shows backdrop when mobile sidebar is open', () => {
		sidebarMobileOpen.set(true);
		const { container } = render(Sidebar);
		const backdrop = container.querySelector('[role="presentation"]');
		expect(backdrop).toBeInTheDocument();
	});

	it('hides backdrop when mobile sidebar is closed', () => {
		sidebarMobileOpen.set(false);
		const { container } = render(Sidebar);
		const backdrop = container.querySelector('[role="presentation"]');
		expect(backdrop).not.toBeInTheDocument();
	});

	it('closes mobile sidebar on backdrop click', async () => {
		sidebarMobileOpen.set(true);
		const { container } = render(Sidebar);
		const backdrop = container.querySelector('[role="presentation"]');
		expect(backdrop).toBeInTheDocument();
		await fireEvent.click(backdrop!);
		expect(get(sidebarMobileOpen)).toBe(false);
	});

	it('has correct nav links', () => {
		render(Sidebar);
		const createLink = screen.getByText('Create').closest('a');
		expect(createLink).toHaveAttribute('href', '/');

		const libraryLink = screen.getByText('Library').closest('a');
		expect(libraryLink).toHaveAttribute('href', '/library');

		const connectorsLink = screen.getByText('Connectors').closest('a');
		expect(connectorsLink).toHaveAttribute('href', '/connectors');

		// Settings opens a dialog (not a link)
		const settingsBtn = screen.getByText('Settings').closest('button');
		expect(settingsBtn).toBeTruthy();
	});
});
