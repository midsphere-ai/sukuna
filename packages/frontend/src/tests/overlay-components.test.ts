import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { Toast, Dialog, Drawer } from '$components/ui';
import { toasts } from '$stores/toast';
import type { Snippet } from 'svelte';

// Helper to create a simple text snippet for Svelte 5
function createSnippet(text: string): Snippet {
	return ((anchor: ChildNode) => {
		const node = document.createTextNode(text);
		anchor.before(node);
		return { anchor: node };
	}) as unknown as Snippet;
}

describe('Toast store', () => {
	beforeEach(() => {
		// Reset the store by removing all toasts
		const current = get(toasts);
		current.forEach((t) => toasts.remove(t.id));
	});

	it('adds a success toast', () => {
		toasts.success('Operation completed');
		const current = get(toasts);
		expect(current).toHaveLength(1);
		expect(current[0].type).toBe('success');
		expect(current[0].message).toBe('Operation completed');
	});

	it('adds an error toast', () => {
		toasts.error('Something failed');
		const current = get(toasts);
		expect(current).toHaveLength(1);
		expect(current[0].type).toBe('error');
	});

	it('adds a warning toast', () => {
		toasts.warning('Be careful');
		const current = get(toasts);
		expect(current).toHaveLength(1);
		expect(current[0].type).toBe('warning');
	});

	it('adds an info toast', () => {
		toasts.info('FYI');
		const current = get(toasts);
		expect(current).toHaveLength(1);
		expect(current[0].type).toBe('info');
	});

	it('removes a toast by id', () => {
		const id = toasts.success('Will be removed');
		expect(get(toasts)).toHaveLength(1);
		toasts.remove(id);
		expect(get(toasts)).toHaveLength(0);
	});

	it('stacks multiple toasts', () => {
		toasts.success('First');
		toasts.error('Second');
		toasts.info('Third');
		expect(get(toasts)).toHaveLength(3);
	});

	it('auto-dismisses after duration', () => {
		vi.useFakeTimers();
		toasts.success('Auto dismiss', 1000);
		expect(get(toasts)).toHaveLength(1);
		vi.advanceTimersByTime(1000);
		expect(get(toasts)).toHaveLength(0);
		vi.useRealTimers();
	});
});

describe('Toast component', () => {
	beforeEach(() => {
		const current = get(toasts);
		current.forEach((t) => toasts.remove(t.id));
	});

	it('renders nothing when no toasts', () => {
		const { container } = render(Toast);
		expect(container.querySelector('[role="region"]')).toBeNull();
	});

	it('renders toasts when present', () => {
		toasts.success('Hello world');
		render(Toast);
		expect(screen.getByText('Hello world')).toBeInTheDocument();
	});

	it('renders dismiss button', () => {
		toasts.info('Dismissable');
		render(Toast);
		expect(screen.getByLabelText('Dismiss notification')).toBeInTheDocument();
	});
});

describe('Dialog', () => {
	beforeEach(() => {
		// jsdom doesn't implement HTMLDialogElement.showModal/close
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
	});

	it('renders closed by default', () => {
		const { container } = render(Dialog, {
			props: { open: false, children: createSnippet('Dialog content') }
		});
		const dialog = container.querySelector('dialog');
		expect(dialog).toBeInTheDocument();
	});

	it('renders children when open', () => {
		render(Dialog, {
			props: { open: true, children: createSnippet('Dialog content') }
		});
		expect(screen.getByText('Dialog content')).toBeInTheDocument();
	});

	it('applies custom class', () => {
		const { container } = render(Dialog, {
			props: { open: true, class: 'custom-dialog', children: createSnippet('Content') }
		});
		const dialog = container.querySelector('dialog');
		expect(dialog?.className).toContain('custom-dialog');
	});

	it('calls onclose on Escape key when closeOnEscape is true', async () => {
		const onclose = vi.fn();
		const { container } = render(Dialog, {
			props: { open: true, onclose, closeOnEscape: true, children: createSnippet('Content') }
		});
		const dialog = container.querySelector('dialog')!;
		await fireEvent.keyDown(dialog, { key: 'Escape' });
		expect(onclose).toHaveBeenCalledOnce();
	});

	it('does not close on Escape when closeOnEscape is false', async () => {
		const onclose = vi.fn();
		const { container } = render(Dialog, {
			props: { open: true, onclose, closeOnEscape: false, children: createSnippet('Content') }
		});
		const dialog = container.querySelector('dialog')!;
		await fireEvent.keyDown(dialog, { key: 'Escape' });
		expect(onclose).not.toHaveBeenCalled();
	});

	it('supports aria-label', () => {
		const { container } = render(Dialog, {
			props: { open: true, 'aria-label': 'Settings dialog', children: createSnippet('Content') }
		});
		const dialog = container.querySelector('dialog');
		expect(dialog).toHaveAttribute('aria-label', 'Settings dialog');
	});

	it('supports aria-labelledby', () => {
		const { container } = render(Dialog, {
			props: {
				open: true,
				'aria-labelledby': 'dialog-title',
				children: createSnippet('Content')
			}
		});
		const dialog = container.querySelector('dialog');
		expect(dialog).toHaveAttribute('aria-labelledby', 'dialog-title');
	});
});

describe('Drawer', () => {
	it('renders nothing when closed', () => {
		const { container } = render(Drawer, {
			props: { open: false, children: createSnippet('Drawer content') }
		});
		expect(container.querySelector('[role="dialog"]')).toBeNull();
	});

	it('renders content when open', () => {
		render(Drawer, {
			props: { open: true, children: createSnippet('Drawer content') }
		});
		expect(screen.getByText('Drawer content')).toBeInTheDocument();
	});

	it('renders drag handle when open', () => {
		const { container } = render(Drawer, {
			props: { open: true, children: createSnippet('Content') }
		});
		const dialog = container.querySelector('[role="dialog"]');
		expect(dialog).toBeInTheDocument();
	});

	it('renders backdrop when open', () => {
		const { container } = render(Drawer, {
			props: { open: true, children: createSnippet('Content') }
		});
		const backdrop = container.querySelector('[role="presentation"]');
		expect(backdrop).toBeInTheDocument();
	});

	it('has aria-modal attribute', () => {
		render(Drawer, {
			props: { open: true, children: createSnippet('Content') }
		});
		const dialog = screen.getByRole('dialog');
		expect(dialog).toHaveAttribute('aria-modal', 'true');
	});

	it('applies half height by default', () => {
		const { container } = render(Drawer, {
			props: { open: true, children: createSnippet('Content') }
		});
		const dialog = container.querySelector('[role="dialog"]');
		expect(dialog?.className).toContain('max-h-[50vh]');
	});

	it('applies custom initial state', () => {
		const { container } = render(Drawer, {
			props: { open: true, initialState: 'full', children: createSnippet('Content') }
		});
		const dialog = container.querySelector('[role="dialog"]');
		expect(dialog?.className).toContain('max-h-[90vh]');
	});

	it('applies peek initial state', () => {
		const { container } = render(Drawer, {
			props: { open: true, initialState: 'peek', children: createSnippet('Content') }
		});
		const dialog = container.querySelector('[role="dialog"]');
		expect(dialog?.className).toContain('max-h-[25vh]');
	});

	it('supports aria-label', () => {
		render(Drawer, {
			props: { open: true, 'aria-label': 'Navigation', children: createSnippet('Content') }
		});
		const dialog = screen.getByRole('dialog');
		expect(dialog).toHaveAttribute('aria-label', 'Navigation');
	});
});
