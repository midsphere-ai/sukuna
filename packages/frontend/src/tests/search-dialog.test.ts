import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/svelte';
import { get } from 'svelte/store';

// Mock $app/environment
vi.mock('$app/environment', () => ({
	browser: true
}));

// Mock $app/navigation
const mockGoto = vi.fn();
vi.mock('$app/navigation', () => ({
	goto: (...args: unknown[]) => mockGoto(...args)
}));

// Mock API
const mockSearchConversations = vi.fn();
vi.mock('$api/conversations', () => ({
	searchConversations: (...args: unknown[]) => mockSearchConversations(...args),
	getConversations: vi.fn().mockResolvedValue({ items: [], count: 0 })
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

import SearchDialog from '$components/layout/SearchDialog.svelte';
import { searchOpen, openSearch, closeSearch } from '$stores/search';

// localStorage mock
const localStorageMock: Record<string, string> = {};
const localStorageImpl = {
	getItem: vi.fn((key: string) => localStorageMock[key] ?? null),
	setItem: vi.fn((key: string, value: string) => {
		localStorageMock[key] = value;
	}),
	removeItem: vi.fn((key: string) => {
		delete localStorageMock[key];
	}),
	clear: vi.fn(() => {
		for (const key of Object.keys(localStorageMock)) {
			delete localStorageMock[key];
		}
	}),
	length: 0,
	key: vi.fn()
};

beforeEach(() => {
	vi.useFakeTimers();
	vi.stubGlobal('localStorage', localStorageImpl);

	// Polyfill HTMLDialogElement for jsdom
	if (!HTMLDialogElement.prototype.showModal) {
		HTMLDialogElement.prototype.showModal = function () {
			this.setAttribute('open', '');
		};
	}
	if (!HTMLDialogElement.prototype.close) {
		HTMLDialogElement.prototype.close = function () {
			this.removeAttribute('open');
		};
	}

	mockSearchConversations.mockReset();
	mockGoto.mockReset();
	localStorageImpl.getItem.mockClear();
	localStorageImpl.setItem.mockClear();
	localStorageImpl.removeItem.mockClear();

	// Clear localStorage mock data
	for (const key of Object.keys(localStorageMock)) {
		delete localStorageMock[key];
	}

	searchOpen.set(false);
});

afterEach(() => {
	cleanup();
	vi.useRealTimers();
	vi.unstubAllGlobals();
	vi.stubGlobal('localStorage', localStorageImpl);
});

/** Advance past debounce and flush all pending microtasks/promises */
async function flushDebounceAndPromises(): Promise<void> {
	// Advance past the 300ms debounce
	await vi.advanceTimersByTimeAsync(300);
	// Flush microtasks for promise resolution
	await vi.advanceTimersByTimeAsync(0);
	await vi.advanceTimersByTimeAsync(0);
}

// --- Store tests ---

describe('search store', () => {
	it('initializes as closed', () => {
		expect(get(searchOpen)).toBe(false);
	});

	it('openSearch sets open to true', () => {
		openSearch();
		expect(get(searchOpen)).toBe(true);
	});

	it('closeSearch sets open to false', () => {
		openSearch();
		closeSearch();
		expect(get(searchOpen)).toBe(false);
	});
});

// --- Component tests ---

describe('SearchDialog component', () => {
	it('renders dialog element when open', () => {
		render(SearchDialog, { props: { open: true } });
		const dialog = document.querySelector('dialog');
		expect(dialog).toBeTruthy();
	});

	it('shows search input when open', () => {
		render(SearchDialog, { props: { open: true } });
		const input = screen.getByPlaceholderText('Search conversations...');
		expect(input).toBeTruthy();
	});

	it('shows empty state when no query and no recent searches', () => {
		render(SearchDialog, { props: { open: true } });
		expect(screen.getByText('Search your conversations')).toBeTruthy();
		expect(screen.getByText('Type to search by title or content')).toBeTruthy();
	});

	it('shows recent searches when available', () => {
		localStorageMock['midsphere-recent-searches'] = JSON.stringify(['test query', 'hello']);
		render(SearchDialog, { props: { open: true } });
		expect(screen.getByText('Recent searches')).toBeTruthy();
		expect(screen.getByText('test query')).toBeTruthy();
		expect(screen.getByText('hello')).toBeTruthy();
	});

	it('clears recent searches when Clear button clicked', async () => {
		localStorageMock['midsphere-recent-searches'] = JSON.stringify(['test query']);
		render(SearchDialog, { props: { open: true } });

		const clearButton = screen.getByText('Clear');
		await fireEvent.click(clearButton);

		expect(localStorageImpl.removeItem).toHaveBeenCalledWith('midsphere-recent-searches');
	});

	it('shows Esc keyboard hint', () => {
		render(SearchDialog, { props: { open: true } });
		expect(screen.getByText('Esc')).toBeTruthy();
	});

	it('shows navigation hints in footer', () => {
		render(SearchDialog, { props: { open: true } });
		expect(screen.getByText('navigate')).toBeTruthy();
		expect(screen.getByText('select')).toBeTruthy();
		expect(screen.getByText('close')).toBeTruthy();
	});

	it('shows clear button when query has text', async () => {
		render(SearchDialog, { props: { open: true } });
		const input = screen.getByPlaceholderText('Search conversations...');
		await fireEvent.input(input, { target: { value: 'hello' } });
		expect(screen.getByLabelText('Clear search')).toBeTruthy();
	});

	it('debounces search by 300ms', async () => {
		mockSearchConversations.mockResolvedValue({ items: [], count: 0 });
		render(SearchDialog, { props: { open: true } });
		const input = screen.getByPlaceholderText('Search conversations...');

		await fireEvent.input(input, { target: { value: 'test' } });

		// Search should not have been called yet
		expect(mockSearchConversations).not.toHaveBeenCalled();

		// Advance timer past debounce
		await vi.advanceTimersByTimeAsync(300);

		expect(mockSearchConversations).toHaveBeenCalledWith('test');
	});

	it('displays search results', async () => {
		mockSearchConversations.mockResolvedValue({
			items: [
				{
					id: 'conv-1',
					title: 'Test Conversation',
					status: 'completed',
					date_created: new Date().toISOString(),
					date_updated: new Date().toISOString(),
					metadata: {}
				}
			],
			count: 1
		});

		render(SearchDialog, { props: { open: true } });
		const input = screen.getByPlaceholderText('Search conversations...');
		await fireEvent.input(input, { target: { value: 'test' } });

		await flushDebounceAndPromises();

		// Check result is rendered via role attribute
		const options = screen.getAllByRole('option');
		expect(options.length).toBe(1);
		// Check the result button exists inside
		const button = options[0].querySelector('button');
		expect(button).toBeTruthy();
		expect(button?.textContent).toContain('Test Conversation');
	});

	it('shows no results message when search returns empty', async () => {
		mockSearchConversations.mockResolvedValue({
			items: [],
			count: 0
		});

		render(SearchDialog, { props: { open: true } });
		const input = screen.getByPlaceholderText('Search conversations...');
		await fireEvent.input(input, { target: { value: 'nonexistent' } });

		await flushDebounceAndPromises();

		expect(screen.getByText(/No results for/)).toBeTruthy();
	});

	it('navigates to conversation on result click', async () => {
		mockSearchConversations.mockResolvedValue({
			items: [
				{
					id: 'conv-123',
					title: 'My Chat',
					status: 'completed',
					date_created: new Date().toISOString(),
					date_updated: new Date().toISOString(),
					metadata: {}
				}
			],
			count: 1
		});

		render(SearchDialog, { props: { open: true } });
		const input = screen.getByPlaceholderText('Search conversations...');
		await fireEvent.input(input, { target: { value: 'my' } });

		await flushDebounceAndPromises();

		const options = screen.getAllByRole('option');
		const resultButton = options[0].querySelector('button');
		expect(resultButton).toBeTruthy();
		if (resultButton) {
			await fireEvent.click(resultButton);
		}

		expect(mockGoto).toHaveBeenCalledWith('/chat/conv-123');
	});

	it('closes on Escape key', async () => {
		render(SearchDialog, { props: { open: true } });
		const dialog = document.querySelector('dialog');
		if (dialog) {
			await fireEvent.keyDown(dialog, { key: 'Escape' });
		}
		expect(dialog?.hasAttribute('open')).toBe(false);
	});

	it('does not render content when closed', () => {
		render(SearchDialog, { props: { open: false } });
		expect(screen.queryByPlaceholderText('Search conversations...')).toBeNull();
	});

	it('shows loading spinner during search', async () => {
		// Never resolve the search to keep loading state
		mockSearchConversations.mockReturnValue(new Promise(() => {}));

		render(SearchDialog, { props: { open: true } });
		const input = screen.getByPlaceholderText('Search conversations...');
		await fireEvent.input(input, { target: { value: 'test' } });

		await vi.advanceTimersByTimeAsync(300);

		const spinner = document.querySelector('.animate-spin');
		expect(spinner).toBeTruthy();
	});

	it('handles search API errors gracefully', async () => {
		mockSearchConversations.mockRejectedValue(new Error('Network error'));

		render(SearchDialog, { props: { open: true } });
		const input = screen.getByPlaceholderText('Search conversations...');
		await fireEvent.input(input, { target: { value: 'test' } });

		await flushDebounceAndPromises();

		// Should show no results (empty state), not crash
		expect(screen.getByText(/No results for/)).toBeTruthy();
	});

	it('shows status colors for different conversation statuses', async () => {
		mockSearchConversations.mockResolvedValue({
			items: [
				{
					id: 'conv-1',
					title: 'Completed Chat',
					status: 'completed',
					date_created: new Date().toISOString(),
					date_updated: new Date().toISOString(),
					metadata: {}
				}
			],
			count: 1
		});

		render(SearchDialog, { props: { open: true } });
		const input = screen.getByPlaceholderText('Search conversations...');
		await fireEvent.input(input, { target: { value: 'chat' } });

		await flushDebounceAndPromises();

		const statusEl = screen.getByText('completed');
		expect(statusEl.classList.contains('text-green')).toBe(true);
	});
});
