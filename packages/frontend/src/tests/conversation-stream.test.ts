import { describe, it, expect, beforeEach, vi, type Mock, afterEach } from 'vitest';
import { get } from 'svelte/store';
import type { Conversation } from '$api/types';

// Mock $app/environment
vi.mock('$app/environment', () => ({
	browser: true
}));

// Mock sessionStorage (for auth store)
vi.stubGlobal('sessionStorage', {
	getItem: vi.fn(() => null),
	setItem: vi.fn(),
	removeItem: vi.fn(),
	clear: vi.fn(),
	length: 0,
	key: vi.fn()
});

// Mock localStorage (for conversations store)
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
const mockFetch = vi.fn() as Mock;
vi.stubGlobal('fetch', mockFetch);

// Mock $app/navigation
vi.mock('$app/navigation', () => ({
	goto: vi.fn()
}));

function makeConversation(overrides: Partial<Conversation> & { id: string }): Conversation {
	return {
		title: 'Untitled',
		summary: null,
		error: null,
		status: 'completed',
		date_created: '2026-01-01T00:00:00Z',
		date_updated: '2026-01-01T00:00:00Z',
		metadata: {},
		...overrides
	};
}

function sseMessage(eventType: string, data: unknown): string {
	return `event: ${eventType}\ndata: ${JSON.stringify(data)}\n\n`;
}

function createSSEStream(chunks: string[]) {
	const encoder = new TextEncoder();
	let index = 0;
	return new ReadableStream({
		pull(controller) {
			if (index < chunks.length) {
				controller.enqueue(encoder.encode(chunks[index]));
				index++;
			} else {
				controller.close();
			}
		}
	});
}

describe('conversationStream service', () => {
	beforeEach(() => {
		vi.resetModules();
		vi.useFakeTimers();
		mockFetch.mockReset();
		Object.keys(mockStorage).forEach((key) => delete mockStorage[key]);
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it('connect does nothing without auth token', async () => {
		const { connect } = await import('$services/conversationStream');
		connect();
		expect(mockFetch).not.toHaveBeenCalled();
	});

	it('connect fetches SSE stream with auth header', async () => {
		const { authToken } = await import('$stores/auth');
		authToken.set('test-token');

		const stream = createSSEStream([
			sseMessage('sync_complete', { type: 'sync_complete', count: 0 })
		]);
		mockFetch.mockResolvedValue({
			ok: true,
			body: stream,
			status: 200
		});

		const { connect } = await import('$services/conversationStream');
		connect();

		// Wait for the fetch to be called
		await vi.advanceTimersByTimeAsync(0);
		expect(mockFetch).toHaveBeenCalled();
		const [url, options] = mockFetch.mock.calls[0];
		expect(url).toContain('/api/v1/memory/conversations/stream/');
		expect(options.headers.Authorization).toBe('Bearer test-token');
	});

	it('handles conversation_updated event for existing conversation', async () => {
		const { authToken } = await import('$stores/auth');
		authToken.set('test-token');

		const { conversations } = await import('$stores/conversations');
		conversations.set([makeConversation({ id: 'conv-1', title: 'Old title' })]);

		const stream = createSSEStream([
			sseMessage('conversation_updated', {
				type: 'conversation_updated',
				conversation: {
					id: 'conv-1',
					title: 'New title',
					summary: 'A summary',
					status: 'running',
					requires_user_input: false,
					date_updated: '2026-01-02T00:00:00Z'
				}
			})
		]);
		mockFetch.mockResolvedValue({ ok: true, body: stream, status: 200 });

		const { connect } = await import('$services/conversationStream');
		connect();
		await vi.advanceTimersByTimeAsync(100);

		const convs = get(conversations);
		expect(convs[0].title).toBe('New title');
		expect(convs[0].status).toBe('running');
	});

	it('handles conversation_updated event for new conversation', async () => {
		const { authToken } = await import('$stores/auth');
		authToken.set('test-token');

		const { conversations } = await import('$stores/conversations');
		conversations.set([]);

		const stream = createSSEStream([
			sseMessage('conversation_updated', {
				type: 'conversation_updated',
				is_new: true,
				conversation: {
					id: 'conv-new',
					title: 'New chat',
					summary: null,
					status: 'idle',
					requires_user_input: false,
					date_updated: '2026-01-01T00:00:00Z'
				}
			})
		]);
		mockFetch.mockResolvedValue({ ok: true, body: stream, status: 200 });

		const { connect } = await import('$services/conversationStream');
		connect();
		await vi.advanceTimersByTimeAsync(100);

		const convs = get(conversations);
		expect(convs).toHaveLength(1);
		expect(convs[0].id).toBe('conv-new');
	});

	it('handles conversation_deleted event', async () => {
		const { authToken } = await import('$stores/auth');
		authToken.set('test-token');

		const { conversations } = await import('$stores/conversations');
		conversations.set([makeConversation({ id: 'conv-1', title: 'Test' })]);

		const stream = createSSEStream([
			sseMessage('conversation_deleted', {
				type: 'conversation_deleted',
				conversation_id: 'conv-1'
			})
		]);
		mockFetch.mockResolvedValue({ ok: true, body: stream, status: 200 });

		const { connect } = await import('$services/conversationStream');
		connect();
		await vi.advanceTimersByTimeAsync(100);

		expect(get(conversations)).toHaveLength(0);
	});

	it('disconnect aborts connection', async () => {
		const { authToken } = await import('$stores/auth');
		authToken.set('test-token');

		// Never-ending stream
		const stream = new ReadableStream({
			pull() {
				return new Promise(() => {}); // never resolves
			}
		});
		mockFetch.mockResolvedValue({ ok: true, body: stream, status: 200 });

		const { connect, disconnect, getIsConnected } = await import('$services/conversationStream');
		connect();
		await vi.advanceTimersByTimeAsync(0);

		disconnect();
		expect(getIsConnected()).toBe(false);
	});

	it('maps pending status to queued', async () => {
		const { authToken } = await import('$stores/auth');
		authToken.set('test-token');

		const { conversations } = await import('$stores/conversations');
		conversations.set([makeConversation({ id: 'conv-1', title: 'Test' })]);

		const stream = createSSEStream([
			sseMessage('conversation_updated', {
				type: 'conversation_updated',
				conversation: {
					id: 'conv-1',
					title: 'Test',
					summary: null,
					status: 'pending',
					requires_user_input: false,
					date_updated: '2026-01-02T00:00:00Z'
				}
			})
		]);
		mockFetch.mockResolvedValue({ ok: true, body: stream, status: 200 });

		const { connect } = await import('$services/conversationStream');
		connect();
		await vi.advanceTimersByTimeAsync(100);

		expect(get(conversations)[0].status).toBe('queued');
	});

	it('falls back to legacy boolean fields for status', async () => {
		const { authToken } = await import('$stores/auth');
		authToken.set('test-token');

		const { conversations } = await import('$stores/conversations');
		conversations.set([makeConversation({ id: 'conv-1', title: 'Test' })]);

		const stream = createSSEStream([
			sseMessage('conversation_updated', {
				type: 'conversation_updated',
				conversation: {
					id: 'conv-1',
					title: 'Test',
					summary: null,
					on_going: true,
					requires_user_input: false,
					date_updated: '2026-01-02T00:00:00Z'
				}
			})
		]);
		mockFetch.mockResolvedValue({ ok: true, body: stream, status: 200 });

		const { connect } = await import('$services/conversationStream');
		connect();
		await vi.advanceTimersByTimeAsync(100);

		expect(get(conversations)[0].status).toBe('running');
	});

	it('retries on connection failure', async () => {
		const { authToken } = await import('$stores/auth');
		authToken.set('test-token');

		// First call fails
		mockFetch.mockRejectedValueOnce(new Error('Network error'));

		// Second call succeeds
		const stream = createSSEStream([
			sseMessage('sync_complete', { type: 'sync_complete', count: 0 })
		]);
		mockFetch.mockResolvedValueOnce({ ok: true, body: stream, status: 200 });

		const { connect } = await import('$services/conversationStream');
		connect();

		await vi.advanceTimersByTimeAsync(0);
		expect(mockFetch).toHaveBeenCalledTimes(1);

		// Advance past retry delay (2s base + up to 1s jitter)
		await vi.advanceTimersByTimeAsync(4000);
		expect(mockFetch).toHaveBeenCalledTimes(2);
	});
});
