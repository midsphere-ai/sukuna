import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';
import type { Conversation } from '$api/types';

// Mock $app/environment
vi.mock('$app/environment', () => ({
	browser: true
}));

// Mock $app/navigation
vi.mock('$app/navigation', () => ({
	goto: vi.fn()
}));

// Mock sessionStorage
vi.stubGlobal('sessionStorage', {
	getItem: vi.fn(() => null),
	setItem: vi.fn(),
	removeItem: vi.fn(),
	clear: vi.fn(),
	length: 0,
	key: vi.fn()
});

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

// Mock fetch
vi.stubGlobal('fetch', vi.fn());

// Mock the SSE services
vi.mock('$services/sse', () => ({
	disconnect: vi.fn(),
	resetStores: vi.fn()
}));

vi.mock('$services/conversationStream', () => ({
	disconnect: vi.fn()
}));

// Mock API
vi.mock('$api/cms', () => ({
	getInfoTutorials: vi.fn().mockResolvedValue([])
}));

describe('resetAllStores', () => {
	beforeEach(() => {
		vi.resetModules();
		Object.keys(mockStorage).forEach((key) => delete mockStorage[key]);
	});

	it('resets conversation stores', async () => {
		const { conversations, conversationsPage, activeConversationId, conversationFilter } =
			await import('$stores/conversations');
		const { resetAllUserStores } = await import('$stores/resetAllStores');

		// Set some state
		conversations.set([
			{
				id: '1',
				title: 'Test',
				summary: null,
				error: null,
				status: 'completed',
				date_created: '',
				date_updated: '',
				metadata: {}
			} as Conversation
		]);
		conversationsPage.set(3);
		activeConversationId.set('1');
		conversationFilter.set('favourites');

		resetAllUserStores();

		expect(get(conversations)).toEqual([]);
		expect(get(conversationsPage)).toBe(1);
		expect(get(activeConversationId)).toBeNull();
		expect(get(conversationFilter)).toBe('all');
	});

	it('resets branch map', async () => {
		const { branchMap } = await import('$stores/branches');
		const { resetAllUserStores } = await import('$stores/resetAllStores');

		branchMap.set({
			'parent-1': [{ branchConversationId: 'b1', fromMessageIndex: 0, createdAt: '' }]
		});
		resetAllUserStores();
		expect(get(branchMap)).toEqual({});
	});

	it('calls disconnect on SSE services', async () => {
		const sse = await import('$services/sse');
		const convStream = await import('$services/conversationStream');
		const { resetAllUserStores } = await import('$stores/resetAllStores');

		resetAllUserStores();
		expect(sse.disconnect).toHaveBeenCalled();
		expect(convStream.disconnect).toHaveBeenCalled();
		expect(sse.resetStores).toHaveBeenCalled();
	});
});
