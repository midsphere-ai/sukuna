import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import ShareAccessDialog from '$components/chat/ShareAccessDialog.svelte';

const { mockShareConversation, mockUnshareConversation, mockToasts } = vi.hoisted(() => ({
	mockShareConversation: vi.fn(),
	mockUnshareConversation: vi.fn(),
	mockToasts: {
		success: vi.fn(),
		error: vi.fn(),
		warning: vi.fn(),
		info: vi.fn()
	}
}));

vi.mock('$api/conversations', () => ({
	shareConversation: (...args: unknown[]) => mockShareConversation(...args),
	unshareConversation: (...args: unknown[]) => mockUnshareConversation(...args)
}));

vi.mock('$stores/toast', () => ({
	toasts: mockToasts
}));

describe('ShareAccessDialog', () => {
	beforeEach(() => {
		mockShareConversation.mockReset();
		mockUnshareConversation.mockReset();
		mockToasts.success.mockReset();
		mockToasts.error.mockReset();
		mockToasts.warning.mockReset();
		mockToasts.info.mockReset();

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

		Object.defineProperty(window.navigator, 'clipboard', {
			value: {
				writeText: vi.fn().mockResolvedValue(undefined)
			},
			configurable: true
		});
	});

	it('shows private state when not shared', () => {
		render(ShareAccessDialog, {
			props: {
				open: true,
				conversationId: 'conv-private',
				isShared: false
			}
		});

		expect(screen.getByText('Private')).toBeInTheDocument();
		expect(screen.getByText('Only you can access')).toBeInTheDocument();
		expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false');
	});

	it('makes conversation public via toggle and emits shared state change', async () => {
		const onsharedchange = vi.fn();
		mockShareConversation.mockResolvedValue({
			id: 'conv-public'
		});

		render(ShareAccessDialog, {
			props: {
				open: true,
				conversationId: 'conv-public',
				isShared: false,
				onsharedchange
			}
		});

		await fireEvent.click(screen.getByRole('switch'));

		await waitFor(() => {
			expect(mockShareConversation).toHaveBeenCalledWith('conv-public');
			expect(onsharedchange).toHaveBeenCalledWith(true);
			expect(screen.getByText('Public')).toBeInTheDocument();
		});
	});

	it('makes conversation private via toggle and emits shared state change', async () => {
		const onsharedchange = vi.fn();
		mockUnshareConversation.mockResolvedValue({
			id: 'conv-shared'
		});

		render(ShareAccessDialog, {
			props: {
				open: true,
				conversationId: 'conv-shared',
				isShared: true,
				onsharedchange
			}
		});

		await fireEvent.click(screen.getByRole('switch'));

		await waitFor(() => {
			expect(mockUnshareConversation).toHaveBeenCalledWith('conv-shared');
			expect(onsharedchange).toHaveBeenCalledWith(false);
			expect(screen.getByText('Private')).toBeInTheDocument();
		});
	});

	it('copies link when conversation is shared', async () => {
		const writeText = vi.fn().mockResolvedValue(undefined);
		Object.defineProperty(window.navigator, 'clipboard', {
			value: { writeText },
			configurable: true
		});

		render(ShareAccessDialog, {
			props: {
				open: true,
				conversationId: 'conv-copy',
				isShared: true
			}
		});

		// When shared, Copy button and share link should be visible
		const copyBtn = screen.getByRole('button', { name: /copy/i });
		await fireEvent.click(copyBtn);

		expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/shared/conv-copy`);
	});
});
