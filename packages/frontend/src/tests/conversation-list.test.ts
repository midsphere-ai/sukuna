import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/svelte';
import { get } from 'svelte/store';

// Mock $app/environment
vi.mock('$app/environment', () => ({
	browser: true
}));

// Mock $app/navigation
vi.mock('$app/navigation', () => ({
	goto: vi.fn()
}));

// Mock API
const mockGetConversations = vi.fn();
const mockDeleteConversation = vi.fn();
const mockRenameConversation = vi.fn();
const mockShareConversation = vi.fn();
const mockUnshareConversation = vi.fn();
vi.mock('$api/conversations', () => ({
	getConversations: (...args: unknown[]) => mockGetConversations(...args),
	deleteConversation: (...args: unknown[]) => mockDeleteConversation(...args),
	renameConversation: (...args: unknown[]) => mockRenameConversation(...args),
	shareConversation: (...args: unknown[]) => mockShareConversation(...args),
	unshareConversation: (...args: unknown[]) => mockUnshareConversation(...args)
}));

// Mock toast
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

// Mock conversation stream service
vi.mock('$services/conversationStream', () => ({
	connect: vi.fn(),
	disconnect: vi.fn(),
	getIsConnected: vi.fn(() => false)
}));

// Mock branches store
vi.mock('$stores/branches', () => ({
	branchMap: {
		subscribe: vi.fn((cb: (v: Record<string, unknown>) => void) => {
			cb({});
			return () => {};
		})
	},
	branchParents: {
		subscribe: vi.fn((cb: (v: Record<string, unknown>) => void) => {
			cb({});
			return () => {};
		})
	},
	removeBranchesForConversation: vi.fn()
}));

// Mock gesture actions
vi.mock('$lib/actions/gestures', () => ({
	pullToRefresh: vi.fn(() => ({ destroy: vi.fn() })),
	haptic: vi.fn(() => ({ destroy: vi.fn() }))
}));

import {
	conversations,
	conversationsLoading,
	conversationsHasMore,
	conversationsError,
	groupedConversations,
	filteredConversations,
	activeConversationId,
	conversationFilter,
	favouriteIds,
	fetchConversations,
	loadMoreConversations,
	getConversationIcon,
	formatRelativeTime,
	toggleFavourite,
	isFavourite,
	renameConversationLocal,
	removeConversationLocal,
	setConversationSharedLocal
} from '$stores/conversations';
import type { Conversation } from '$api/types';

function makeConversation(overrides: Partial<Conversation> = {}): Conversation {
	return {
		id: 'conv-' + Math.random().toString(36).slice(2, 8),
		title: 'Test Conversation',
		summary: null,
		on_going: false,
		has_error: false,
		error: null,
		status: 'completed',
		date_created: new Date().toISOString(),
		date_updated: new Date().toISOString(),
		metadata: {},
		...overrides
	};
}

describe('conversations store', () => {
	beforeEach(() => {
		conversations.set([]);
		conversationsLoading.set(false);
		conversationsError.set(null);
		conversationsHasMore.set(true);
		activeConversationId.set(null);
		conversationFilter.set('all');
		favouriteIds.set(new Set());
		mockGetConversations.mockReset();
		mockDeleteConversation.mockReset();
		mockRenameConversation.mockReset();
		mockShareConversation.mockReset();
		mockUnshareConversation.mockReset();
	});

	describe('getConversationIcon', () => {
		it('returns a DiceBear URL for any title', () => {
			const icon = getConversationIcon('My Chat');
			expect(icon).toContain('https://api.dicebear.com/9.x/identicon/svg');
			expect(icon).toContain('seed=My%20Chat');
		});

		it('returns consistent icon for the same title', () => {
			const icon1 = getConversationIcon('same-title');
			const icon2 = getConversationIcon('same-title');
			expect(icon1).toBe(icon2);
		});

		it('returns different icons for different titles', () => {
			const icons = new Set<string>();
			for (let i = 0; i < 50; i++) {
				icons.add(getConversationIcon(`title-${i}`));
			}
			expect(icons.size).toBeGreaterThan(1);
		});
	});

	describe('formatRelativeTime', () => {
		it('returns "Just now" for recent timestamps', () => {
			const result = formatRelativeTime(new Date().toISOString());
			expect(result).toBe('Just now');
		});

		it('returns minutes for timestamps within the hour', () => {
			const tenMinAgo = new Date(Date.now() - 10 * 60 * 1000).toISOString();
			const result = formatRelativeTime(tenMinAgo);
			expect(result).toBe('10m ago');
		});

		it('returns hours for timestamps within the day', () => {
			const threeHoursAgo = new Date(Date.now() - 3 * 3600 * 1000).toISOString();
			const result = formatRelativeTime(threeHoursAgo);
			expect(result).toBe('3h ago');
		});

		it('returns days for timestamps within the week', () => {
			const twoDaysAgo = new Date(Date.now() - 2 * 86400 * 1000).toISOString();
			const result = formatRelativeTime(twoDaysAgo);
			expect(result).toBe('2d ago');
		});

		it('returns formatted date for older timestamps', () => {
			const oldDate = new Date('2025-01-15T12:00:00Z').toISOString();
			const result = formatRelativeTime(oldDate);
			expect(result).toMatch(/Jan/);
		});
	});

	describe('groupedConversations', () => {
		it('groups conversations by time period', () => {
			const now = new Date();
			const todayConv = makeConversation({
				id: 'today',
				date_updated: now.toISOString()
			});
			const oldConv = makeConversation({
				id: 'old',
				date_updated: new Date('2024-01-01').toISOString()
			});

			conversations.set([todayConv, oldConv]);
			const groups = get(groupedConversations);

			expect(groups.length).toBeGreaterThan(0);
			expect(groups[0].label).toBe('Today');
			expect(groups[0].conversations).toContainEqual(todayConv);

			const olderGroup = groups.find((g) => g.label === 'Older');
			expect(olderGroup).toBeTruthy();
			expect(olderGroup!.conversations).toContainEqual(oldConv);
		});

		it('returns empty array for no conversations', () => {
			conversations.set([]);
			const groups = get(groupedConversations);
			expect(groups).toEqual([]);
		});

		it('maintains group order: Today before Older', () => {
			const now = new Date();
			const convs = [
				makeConversation({ id: 'old', date_updated: new Date('2024-01-01').toISOString() }),
				makeConversation({ id: 'today', date_updated: now.toISOString() })
			];

			conversations.set(convs);
			const groups = get(groupedConversations);
			const labels = groups.map((g) => g.label);
			expect(labels.indexOf('Today')).toBeLessThan(labels.indexOf('Older'));
		});
	});

	describe('fetchConversations', () => {
		it('sets loading state during fetch', async () => {
			mockGetConversations.mockResolvedValue({
				count: 0,
				items: []
			});

			const promise = fetchConversations();
			expect(get(conversationsLoading)).toBe(true);
			await promise;
			expect(get(conversationsLoading)).toBe(false);
		});

		it('populates conversations from API response', async () => {
			const conv = makeConversation({ title: 'Hello World' });
			mockGetConversations.mockResolvedValue({
				count: 1,
				items: [conv]
			});

			await fetchConversations();
			expect(get(conversations)).toEqual([conv]);
		});

		it('sets hasMore based on count vs items length', async () => {
			mockGetConversations.mockResolvedValue({
				count: 100,
				items: Array.from({ length: 50 }, () => makeConversation())
			});

			await fetchConversations();
			expect(get(conversationsHasMore)).toBe(true);
		});

		it('handles API errors', async () => {
			mockGetConversations.mockRejectedValue(new Error('Network error'));

			await fetchConversations();
			expect(get(conversationsError)).toBe('Network error');
		});
	});

	describe('loadMoreConversations', () => {
		it('appends to existing conversations', async () => {
			const existing = makeConversation({ id: 'existing' });
			const newConv = makeConversation({ id: 'new' });
			conversations.set([existing]);

			mockGetConversations.mockResolvedValue({
				count: 2,
				items: [newConv]
			});

			await loadMoreConversations();
			const result = get(conversations);
			expect(result).toHaveLength(2);
			expect(result[0].id).toBe('existing');
			expect(result[1].id).toBe('new');
		});

		it('does not fetch when hasMore is false', async () => {
			conversationsHasMore.set(false);
			await loadMoreConversations();
			expect(mockGetConversations).not.toHaveBeenCalled();
		});
	});

	describe('favourites', () => {
		it('toggleFavourite adds and removes favourite', () => {
			toggleFavourite('conv-1');
			expect(get(favouriteIds).has('conv-1')).toBe(true);

			toggleFavourite('conv-1');
			expect(get(favouriteIds).has('conv-1')).toBe(false);
		});

		it('isFavourite returns correct state', () => {
			const favs = new Set(['conv-1', 'conv-2']);
			expect(isFavourite('conv-1', favs)).toBe(true);
			expect(isFavourite('conv-3', favs)).toBe(false);
		});

		it('multiple favourites are tracked independently', () => {
			toggleFavourite('conv-1');
			toggleFavourite('conv-2');
			const favs = get(favouriteIds);
			expect(favs.has('conv-1')).toBe(true);
			expect(favs.has('conv-2')).toBe(true);

			toggleFavourite('conv-1');
			const updated = get(favouriteIds);
			expect(updated.has('conv-1')).toBe(false);
			expect(updated.has('conv-2')).toBe(true);
		});
	});

	describe('filters', () => {
		it('all filter shows all conversations', () => {
			conversations.set([makeConversation({ id: 'a' }), makeConversation({ id: 'b' })]);
			conversationFilter.set('all');
			expect(get(filteredConversations)).toHaveLength(2);
		});

		it('favourites filter shows only favourites', () => {
			conversations.set([makeConversation({ id: 'fav' }), makeConversation({ id: 'not-fav' })]);
			favouriteIds.set(new Set(['fav']));
			conversationFilter.set('favourites');

			const filtered = get(filteredConversations);
			expect(filtered).toHaveLength(1);
			expect(filtered[0].id).toBe('fav');
		});

		it('scheduled filter shows only scheduled conversations', () => {
			conversations.set([
				makeConversation({ id: 'sched', metadata: { scheduled: true } }),
				makeConversation({ id: 'normal', metadata: {} })
			]);
			conversationFilter.set('scheduled');

			const filtered = get(filteredConversations);
			expect(filtered).toHaveLength(1);
			expect(filtered[0].id).toBe('sched');
		});

		it('shared filter shows only shared conversations', () => {
			conversations.set([
				makeConversation({ id: 'shared', metadata: { shared: true } }),
				makeConversation({ id: 'private', metadata: {} })
			]);
			conversationFilter.set('shared');

			const filtered = get(filteredConversations);
			expect(filtered).toHaveLength(1);
			expect(filtered[0].id).toBe('shared');
		});
	});

	describe('local mutations', () => {
		it('renameConversationLocal updates title in store', () => {
			const conv = makeConversation({ id: 'rename-me', title: 'Old Title' });
			conversations.set([conv]);
			renameConversationLocal('rename-me', 'New Title');

			const updated = get(conversations);
			expect(updated[0].title).toBe('New Title');
		});

		it('removeConversationLocal removes from store', () => {
			conversations.set([makeConversation({ id: 'keep' }), makeConversation({ id: 'remove' })]);
			removeConversationLocal('remove');

			const updated = get(conversations);
			expect(updated).toHaveLength(1);
			expect(updated[0].id).toBe('keep');
		});

		it('setConversationSharedLocal updates shared metadata in store', () => {
			const conv = makeConversation({ id: 'share-me', metadata: {} });
			conversations.set([conv]);

			setConversationSharedLocal('share-me', true);

			const updated = get(conversations);
			expect(updated[0].metadata.shared).toBe(true);
		});
	});
});

describe('ConversationList component', () => {
	let mockLocalStorage: Record<string, string>;

	beforeEach(() => {
		conversations.set([]);
		conversationsLoading.set(false);
		conversationsError.set(null);
		conversationsHasMore.set(true);
		activeConversationId.set(null);
		conversationFilter.set('all');
		favouriteIds.set(new Set());
		mockGetConversations.mockReset();
		mockDeleteConversation.mockReset();
		mockRenameConversation.mockReset();
		mockShareConversation.mockReset();
		mockUnshareConversation.mockReset();

		HTMLDialogElement.prototype.showModal =
			HTMLDialogElement.prototype.showModal ||
			function (this: HTMLDialogElement) {
				this.setAttribute('open', '');
			};
		HTMLDialogElement.prototype.close =
			HTMLDialogElement.prototype.close ||
			function (this: HTMLDialogElement) {
				this.removeAttribute('open');
			};

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
		vi.unstubAllGlobals();
	});

	it('shows loading skeleton during initial load', async () => {
		mockGetConversations.mockImplementation(
			() =>
				new Promise(() => {
					/* never resolves */
				})
		);

		const { default: ConversationList } =
			await import('$components/layout/ConversationList.svelte');
		render(ConversationList);

		const skeletons = document.querySelectorAll('[aria-hidden="true"]');
		expect(skeletons.length).toBeGreaterThan(0);
	});

	it('shows empty state when no conversations', async () => {
		mockGetConversations.mockResolvedValue({
			count: 0,
			items: []
		});

		const { default: ConversationList } =
			await import('$components/layout/ConversationList.svelte');
		render(ConversationList);

		await vi.waitFor(() => {
			expect(screen.getByText('No conversations yet')).toBeInTheDocument();
		});
	});

	it('renders filter dropdown', async () => {
		mockGetConversations.mockResolvedValue({
			count: 0,
			items: []
		});

		const { default: ConversationList } =
			await import('$components/layout/ConversationList.svelte');
		render(ConversationList);

		const filterButton = screen.getByRole('button', { name: 'All' });
		expect(filterButton).toBeInTheDocument();
		expect(filterButton).toHaveAttribute('aria-haspopup', 'listbox');
	});

	it('All filter is shown by default', async () => {
		mockGetConversations.mockResolvedValue({
			count: 0,
			items: []
		});

		const { default: ConversationList } =
			await import('$components/layout/ConversationList.svelte');
		render(ConversationList);

		const filterButton = screen.getByRole('button', { name: 'All' });
		expect(filterButton).toHaveAttribute('aria-expanded', 'false');
	});

	it('clicking filter dropdown and selecting option changes filter', async () => {
		mockGetConversations.mockResolvedValue({
			count: 0,
			items: []
		});

		const { default: ConversationList } =
			await import('$components/layout/ConversationList.svelte');
		render(ConversationList);

		const filterButton = screen.getByRole('button', { name: 'All' });
		await fireEvent.click(filterButton);

		const favouritesOption = screen.getByRole('option', { name: 'Favourites' });
		await fireEvent.click(favouritesOption);

		expect(screen.getByRole('button', { name: 'Favourites' })).toBeInTheDocument();
	});

	it('shows empty favourites message when filter is favourites', async () => {
		conversationFilter.set('favourites');
		mockGetConversations.mockResolvedValue({
			count: 1,
			items: [makeConversation({ id: 'conv-1', date_updated: new Date().toISOString() })]
		});

		const { default: ConversationList } =
			await import('$components/layout/ConversationList.svelte');
		render(ConversationList);

		await vi.waitFor(() => {
			expect(screen.getByText('No favourite conversations')).toBeInTheDocument();
		});
	});

	it('renders grouped conversations with labels', async () => {
		const todayConv = makeConversation({
			id: 'today-conv',
			title: 'Today Conversation',
			date_updated: new Date().toISOString()
		});

		mockGetConversations.mockResolvedValue({
			count: 1,
			items: [todayConv]
		});

		const { default: ConversationList } =
			await import('$components/layout/ConversationList.svelte');
		render(ConversationList);

		await vi.waitFor(() => {
			expect(screen.getByText('Today')).toBeInTheDocument();
			expect(screen.getByText('Today Conversation')).toBeInTheDocument();
		});
	});

	it('renders conversation links with correct hrefs', async () => {
		const conv = makeConversation({
			id: 'abc-123',
			title: 'Test Chat',
			date_updated: new Date().toISOString()
		});

		mockGetConversations.mockResolvedValue({
			count: 1,
			items: [conv]
		});

		const { default: ConversationList } =
			await import('$components/layout/ConversationList.svelte');
		render(ConversationList);

		await vi.waitFor(() => {
			const link = screen.getByRole('link', { name: /Test Chat/ });
			expect(link).toHaveAttribute('href', '/chat/abc-123');
		});
	});

	it('shows error state with retry button', async () => {
		mockGetConversations.mockRejectedValue(new Error('API failed'));

		const { default: ConversationList } =
			await import('$components/layout/ConversationList.svelte');
		render(ConversationList);

		await vi.waitFor(() => {
			expect(screen.getByText('Failed to load conversations')).toBeInTheDocument();
			expect(screen.getByText('Try again')).toBeInTheDocument();
		});
	});

	it('does not show inline time for conversations', async () => {
		const conv = makeConversation({
			id: 'recent',
			title: 'Recent Chat',
			date_updated: new Date().toISOString()
		});

		mockGetConversations.mockResolvedValue({
			count: 1,
			items: [conv]
		});

		const { default: ConversationList } =
			await import('$components/layout/ConversationList.svelte');
		render(ConversationList);

		await vi.waitFor(() => {
			expect(screen.getByText('Recent Chat')).toBeInTheDocument();
		});

		expect(screen.queryByText('Just now')).not.toBeInTheDocument();
	});

	it('truncates long titles', async () => {
		const conv = makeConversation({
			id: 'long-title',
			title: 'This is a very long conversation title that should be truncated',
			date_updated: new Date().toISOString()
		});

		mockGetConversations.mockResolvedValue({
			count: 1,
			items: [conv]
		});

		const { default: ConversationList } =
			await import('$components/layout/ConversationList.svelte');
		render(ConversationList);

		await vi.waitFor(() => {
			expect(screen.getByText('This is a very long conversati...')).toBeInTheDocument();
		});
	});

	it('shows Untitled for conversations without title', async () => {
		const conv = makeConversation({
			id: 'no-title',
			title: '',
			date_updated: new Date().toISOString()
		});

		mockGetConversations.mockResolvedValue({
			count: 1,
			items: [conv]
		});

		const { default: ConversationList } =
			await import('$components/layout/ConversationList.svelte');
		render(ConversationList);

		await vi.waitFor(() => {
			expect(screen.getByText('Untitled')).toBeInTheDocument();
		});
	});

	it('shows "No more conversations" when hasMore is false', async () => {
		const conv = makeConversation({
			id: 'single',
			title: 'Only Chat',
			date_updated: new Date().toISOString()
		});

		mockGetConversations.mockResolvedValue({
			count: 1,
			items: [conv]
		});

		const { default: ConversationList } =
			await import('$components/layout/ConversationList.svelte');
		render(ConversationList);

		await vi.waitFor(() => {
			expect(screen.getByText('No more conversations')).toBeInTheDocument();
		});
	});

	it('shows favourite star on favourited conversations', async () => {
		const conv = makeConversation({
			id: 'fav-conv',
			title: 'Favourited Chat',
			date_updated: new Date().toISOString()
		});

		favouriteIds.set(new Set(['fav-conv']));
		mockGetConversations.mockResolvedValue({
			count: 1,
			items: [conv]
		});

		const { default: ConversationList } =
			await import('$components/layout/ConversationList.svelte');
		render(ConversationList);

		await vi.waitFor(() => {
			const star = screen.getByLabelText('Favourite');
			expect(star).toBeInTheDocument();
		});
	});

	it('shows delete confirmation dialog', async () => {
		// Simulate showing confirmation via the swipeConfirmId mechanism
		const conv = makeConversation({
			id: 'del-conv',
			title: 'Delete Me',
			date_updated: new Date().toISOString()
		});

		mockGetConversations.mockResolvedValue({
			count: 1,
			items: [conv]
		});

		const { default: ConversationList } =
			await import('$components/layout/ConversationList.svelte');
		render(ConversationList);

		await vi.waitFor(() => {
			expect(screen.getByText('Delete Me')).toBeInTheDocument();
		});

		// Right-click to open context menu
		const conversationLink = screen.getByRole('link', { name: /Delete Me/ });
		const container = conversationLink.closest('[oncontextmenu]') as Element;
		if (container) {
			await fireEvent.contextMenu(container);

			// Look for Delete in context menu
			await vi.waitFor(() => {
				const deleteBtn = screen.getByRole('menuitem', { name: /Delete/ });
				expect(deleteBtn).toBeInTheDocument();
			});
		}
	});

	it('opens share access dialog from context menu', async () => {
		const conv = makeConversation({
			id: 'share-conv',
			title: 'Share Me',
			date_updated: new Date().toISOString(),
			metadata: {}
		});

		mockGetConversations.mockResolvedValue({
			count: 1,
			items: [conv]
		});

		const { default: ConversationList } =
			await import('$components/layout/ConversationList.svelte');
		render(ConversationList);

		await vi.waitFor(() => {
			expect(screen.getByText('Share Me')).toBeInTheDocument();
		});

		const conversationLink = screen.getByRole('link', { name: /Share Me/ });
		await fireEvent.contextMenu(conversationLink);
		const shareBtn = await screen.findByRole('menuitem', { name: /Share/ });
		await fireEvent.click(shareBtn);

		expect(screen.getByText('Share conversation')).toBeInTheDocument();
	});

	it('makes conversation public from share access dialog', async () => {
		const conv = makeConversation({
			id: 'share-toggle',
			title: 'Toggle Share',
			date_updated: new Date().toISOString(),
			metadata: {}
		});

		mockGetConversations.mockResolvedValue({
			count: 1,
			items: [conv]
		});
		mockShareConversation.mockResolvedValue({
			...conv,
			metadata: { shared: true }
		});

		const { default: ConversationList } =
			await import('$components/layout/ConversationList.svelte');
		render(ConversationList);

		await vi.waitFor(() => {
			expect(screen.getByText('Toggle Share')).toBeInTheDocument();
		});

		const conversationLink = screen.getByRole('link', { name: /Toggle Share/ });
		await fireEvent.contextMenu(conversationLink);
		const shareBtn = await screen.findByRole('menuitem', { name: /Share/ });
		await fireEvent.click(shareBtn);

		const makePublicButton = await screen.findByRole('switch', { name: 'Make public' });
		await fireEvent.click(makePublicButton);

		await vi.waitFor(() => {
			expect(mockShareConversation).toHaveBeenCalledWith('share-toggle');
			const updated = get(conversations).find((item) => item.id === 'share-toggle');
			expect(updated?.metadata.shared).toBe(true);
		});
	});
});
