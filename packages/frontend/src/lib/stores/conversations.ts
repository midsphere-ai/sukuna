import { writable, derived, get } from 'svelte/store';
import { browser } from '$app/environment';
import { getConversations } from '$api/conversations';
import { createFreshnessTracker } from '$stores/freshness';
import { activeProjectId } from '$stores/projects';
import { debounce } from '$utils/debounce';
import type { Conversation } from '$api/types';

export interface ConversationGroup {
	label: string;
	conversations: Conversation[];
}

export type ConversationFilter = 'all' | 'favourites' | 'scheduled' | 'shared';

const FAVOURITES_KEY = 'midsphere-favourite-conversations';
const CONVERSATIONS_CACHE_KEY = 'midsphere-conversations';

function loadFavourites(): Set<string> {
	if (!browser) return new Set();
	try {
		const raw = localStorage.getItem(FAVOURITES_KEY);
		if (raw) return new Set(JSON.parse(raw) as string[]);
	} catch {
		// ignore
	}
	return new Set();
}

function saveFavourites(ids: Set<string>): void {
	if (!browser) return;
	try {
		localStorage.setItem(FAVOURITES_KEY, JSON.stringify([...ids]));
	} catch {
		// ignore
	}
}

function loadCachedConversations(): Conversation[] {
	if (!browser) return [];
	try {
		const raw = localStorage.getItem(CONVERSATIONS_CACHE_KEY);
		if (raw) return JSON.parse(raw) as Conversation[];
	} catch {
		// ignore
	}
	return [];
}

function cacheConversations(items: Conversation[]): void {
	if (!browser) return;
	try {
		// Only cache top 50 to keep localStorage lean
		localStorage.setItem(CONVERSATIONS_CACHE_KEY, JSON.stringify(items.slice(0, 50)));
	} catch {
		// ignore
	}
}

const conversationsFreshness = createFreshnessTracker(60_000);

export const conversations = writable<Conversation[]>(loadCachedConversations());
export const conversationsLoading = writable(false);
export const conversationsError = writable<string | null>(null);
export const conversationsPage = writable(1);
export const conversationsHasMore = writable(true);
export const activeConversationId = writable<string | null>(null);
export const conversationFilter = writable<ConversationFilter>('all');
export const favouriteIds = writable<Set<string>>(loadFavourites());

// Sync favourites to localStorage (debounced)
if (browser) {
	favouriteIds.subscribe(
		debounce((ids: Set<string>) => {
			saveFavourites(ids);
		}, 500)
	);
}

// Sync conversations to localStorage cache (debounced)
if (browser) {
	conversations.subscribe(
		debounce((items: Conversation[]) => {
			cacheConversations(items);
		}, 1000)
	);
}

export function toggleFavourite(conversationId: string): void {
	favouriteIds.update((ids) => {
		const next = new Set(ids);
		if (next.has(conversationId)) {
			next.delete(conversationId);
		} else {
			next.add(conversationId);
		}
		return next;
	});
}

export function isFavourite(conversationId: string, favs: Set<string>): boolean {
	return favs.has(conversationId);
}

function getTimeGroup(dateStr: string): string {
	const date = new Date(dateStr);
	const now = new Date();
	const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
	const yesterdayStart = new Date(todayStart.getTime() - 86400000);

	const weekStart = new Date(todayStart);
	weekStart.setDate(todayStart.getDate() - todayStart.getDay());

	const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);

	if (date >= todayStart) return 'Today';
	if (date >= yesterdayStart) return 'Yesterday';
	if (date >= weekStart) return 'This Week';
	if (date >= monthStart) return 'This Month';
	return 'Older';
}

const GROUP_ORDER = ['Today', 'Yesterday', 'This Week', 'This Month', 'Older'];

export const filteredConversations = derived(
	[conversations, conversationFilter, favouriteIds, activeProjectId],
	([$conversations, $filter, $favouriteIds, $activeProjectId]) => {
		const scoped = $activeProjectId
			? $conversations.filter((c) => c.project_id === $activeProjectId)
			: $conversations;
		switch ($filter) {
			case 'favourites':
				return scoped.filter((c) => $favouriteIds.has(c.id));
			case 'scheduled':
				return scoped.filter(
					(c) => c.metadata && (c.metadata as Record<string, unknown>).scheduled === true
				);
			case 'shared':
				return scoped.filter(
					(c) => c.metadata && (c.metadata as Record<string, unknown>).shared === true
				);
			default:
				return scoped;
		}
	}
);

export const groupedConversations = derived(filteredConversations, ($filtered) => {
	const groups = new Map<string, Conversation[]>();

	for (const conv of $filtered) {
		const label = getTimeGroup(conv.date_updated || conv.date_created);
		const existing = groups.get(label);
		if (existing) {
			existing.push(conv);
		} else {
			groups.set(label, [conv]);
		}
	}

	const result: ConversationGroup[] = [];
	for (const label of GROUP_ORDER) {
		const items = groups.get(label);
		if (items && items.length > 0) {
			result.push({ label, conversations: items });
		}
	}
	return result;
});

export async function fetchConversations(): Promise<void> {
	if (!browser) return;

	// Only show loading spinner when store is empty (cold start).
	// When cached data exists, this becomes a silent background revalidation.
	const isEmpty = get(conversations).length === 0;
	if (isEmpty) conversationsLoading.set(true);
	conversationsError.set(null);

	try {
		const response = await getConversations(1);
		conversations.update((existing) => {
			const map = new Map(existing.map((c) => [c.id, c]));
			for (const item of response.items) {
				const existingConv = map.get(item.id);
				if (!existingConv || new Date(item.date_updated) >= new Date(existingConv.date_updated)) {
					map.set(item.id, item);
				}
			}
			return Array.from(map.values()).sort(
				(a, b) => new Date(b.date_updated).getTime() - new Date(a.date_updated).getTime()
			);
		});
		conversationsPage.set(1);
		conversationsHasMore.set(response.items.length < response.count);
		conversationsFreshness.markFetched();
	} catch (err) {
		conversationsError.set(err instanceof Error ? err.message : 'Failed to load conversations');
	} finally {
		conversationsLoading.set(false);
	}
}

export async function loadMoreConversations(): Promise<void> {
	if (!browser) return;

	const currentPage = get(conversationsPage);
	const hasMore = get(conversationsHasMore);

	if (!hasMore) return;

	conversationsLoading.set(true);
	conversationsError.set(null);

	try {
		const nextPage = currentPage + 1;
		const response = await getConversations(nextPage);
		conversations.update((existing) => {
			const map = new Map(existing.map((c) => [c.id, c]));
			for (const item of response.items) {
				if (!map.has(item.id)) {
					map.set(item.id, item);
				}
			}
			const updated = Array.from(map.values());
			conversationsHasMore.set(updated.length < response.count);
			return updated;
		});
		conversationsPage.set(nextPage);
	} catch (err) {
		conversationsError.set(
			err instanceof Error ? err.message : 'Failed to load more conversations'
		);
	} finally {
		conversationsLoading.set(false);
	}
}

export function renameConversationLocal(conversationId: string, newTitle: string): void {
	conversations.update((existing) =>
		existing.map((c) => (c.id === conversationId ? { ...c, title: newTitle } : c))
	);
}

export function removeConversationLocal(conversationId: string): void {
	conversations.update((existing) => existing.filter((c) => c.id !== conversationId));
}

export function setConversationSharedLocal(conversationId: string, shared: boolean): void {
	conversations.update((existing) =>
		existing.map((c) => {
			if (c.id !== conversationId) return c;
			const metadata = (c.metadata ?? {}) as Record<string, unknown>;
			return {
				...c,
				metadata: {
					...metadata,
					shared
				}
			};
		})
	);
}

export function getConversationIcon(title: string): string {
	return `https://api.dicebear.com/9.x/identicon/svg?seed=${encodeURIComponent(title)}&rowColor=888888&backgroundColor=transparent`;
}

export function formatRelativeTime(dateStr: string): string {
	const date = new Date(dateStr);
	const now = new Date();
	const diffMs = now.getTime() - date.getTime();
	const diffMins = Math.floor(diffMs / 60000);
	const diffHours = Math.floor(diffMs / 3600000);
	const diffDays = Math.floor(diffMs / 86400000);

	if (diffMins < 1) return 'Just now';
	if (diffMins < 60) return `${diffMins}m ago`;
	if (diffHours < 24) return `${diffHours}h ago`;
	if (diffDays < 7) return `${diffDays}d ago`;
	return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function ensureConversations(): Promise<void> {
	return conversationsFreshness.ensureFresh(fetchConversations);
}

export function invalidateConversations(): void {
	conversationsFreshness.invalidate();
}
