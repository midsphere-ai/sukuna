import type { Message, PaginationCursor } from '$services/sse';

export interface CachedChat {
	messages: Message[];
	hasMore: boolean;
	cursor: PaginationCursor | null;
}

const MAX_SIZE = 10;
const cache = new Map<string, CachedChat>();
const accessOrder: string[] = [];

export function getCachedChat(id: string): CachedChat | null {
	const entry = cache.get(id);
	if (!entry) return null;
	// Move to end of access order
	const idx = accessOrder.indexOf(id);
	if (idx !== -1) accessOrder.splice(idx, 1);
	accessOrder.push(id);
	return entry;
}

export function setCachedChat(id: string, data: CachedChat): void {
	if (cache.has(id)) {
		const idx = accessOrder.indexOf(id);
		if (idx !== -1) accessOrder.splice(idx, 1);
	}
	cache.set(id, data);
	accessOrder.push(id);
	// Evict LRU if over limit
	while (accessOrder.length > MAX_SIZE) {
		const oldest = accessOrder.shift();
		if (oldest) cache.delete(oldest);
	}
}

export function invalidateCachedChat(id: string): void {
	cache.delete(id);
	const idx = accessOrder.indexOf(id);
	if (idx !== -1) accessOrder.splice(idx, 1);
}

export function clearChatCache(): void {
	cache.clear();
	accessOrder.length = 0;
}
