import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import {
	LoadingSpinner,
	NetworkError,
	PageHeader,
	SearchInput,
	StatusBadge,
	ConfirmationDialog
} from '$components/ui';
import ContextMenu from '$components/ui/ContextMenu.svelte';
import type { Snippet } from 'svelte';

// Helper to create a simple text snippet for Svelte 5
function createSnippet(text: string): Snippet {
	return ((anchor: ChildNode) => {
		const node = document.createTextNode(text);
		anchor.before(node);
		return { anchor: node };
	}) as unknown as Snippet;
}

// Polyfill dialog methods for jsdom
beforeEach(() => {
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

describe('LoadingSpinner', () => {
	it('renders an SVG with animate-spin', () => {
		const { container } = render(LoadingSpinner);
		const svg = container.querySelector('svg');
		expect(svg).toBeInTheDocument();
		expect(svg?.className.baseVal).toContain('animate-spin');
	});

	it('renders with default sm size', () => {
		const { container } = render(LoadingSpinner);
		const svg = container.querySelector('svg');
		expect(svg?.className.baseVal).toContain('h-4');
		expect(svg?.className.baseVal).toContain('w-4');
	});

	it('renders with xs size', () => {
		const { container } = render(LoadingSpinner, { props: { size: 'xs' } });
		const svg = container.querySelector('svg');
		expect(svg?.className.baseVal).toContain('h-3');
		expect(svg?.className.baseVal).toContain('w-3');
	});

	it('renders with md size', () => {
		const { container } = render(LoadingSpinner, { props: { size: 'md' } });
		const svg = container.querySelector('svg');
		expect(svg?.className.baseVal).toContain('h-5');
		expect(svg?.className.baseVal).toContain('w-5');
	});

	it('renders with lg size', () => {
		const { container } = render(LoadingSpinner, { props: { size: 'lg' } });
		const svg = container.querySelector('svg');
		expect(svg?.className.baseVal).toContain('h-6');
		expect(svg?.className.baseVal).toContain('w-6');
	});

	it('is hidden from screen readers', () => {
		const { container } = render(LoadingSpinner);
		const svg = container.querySelector('svg');
		expect(svg).toHaveAttribute('aria-hidden', 'true');
	});

	it('applies custom class', () => {
		const { container } = render(LoadingSpinner, { props: { class: 'text-accent' } });
		const svg = container.querySelector('svg');
		expect(svg?.className.baseVal).toContain('text-accent');
	});
});

describe('NetworkError', () => {
	it('renders default error message', () => {
		render(NetworkError);
		expect(
			screen.getByText('Unable to load data. Check your connection and try again.')
		).toBeInTheDocument();
	});

	it('renders custom error message', () => {
		render(NetworkError, { props: { message: 'Server error' } });
		expect(screen.getByText('Server error')).toBeInTheDocument();
	});

	it('has alert role for accessibility', () => {
		render(NetworkError);
		expect(screen.getByRole('alert')).toBeInTheDocument();
	});

	it('shows retry button when onretry provided', () => {
		const onretry = vi.fn();
		render(NetworkError, { props: { onretry } });
		expect(screen.getByText('Retry')).toBeInTheDocument();
	});

	it('does not show retry button when no onretry', () => {
		render(NetworkError);
		expect(screen.queryByText('Retry')).not.toBeInTheDocument();
	});

	it('calls onretry when retry clicked', async () => {
		const onretry = vi.fn();
		render(NetworkError, { props: { onretry } });
		await fireEvent.click(screen.getByText('Retry'));
		expect(onretry).toHaveBeenCalledOnce();
	});

	it('applies custom class', () => {
		const { container } = render(NetworkError, { props: { class: 'mt-4' } });
		const el = container.querySelector('[role="alert"]');
		expect(el?.className).toContain('mt-4');
	});
});

describe('PageHeader', () => {
	it('renders title', () => {
		render(PageHeader, { props: { title: 'Dashboard' } });
		expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Dashboard');
	});

	it('renders description when provided', () => {
		render(PageHeader, {
			props: { title: 'Settings', description: 'Manage your preferences' }
		});
		expect(screen.getByText('Manage your preferences')).toBeInTheDocument();
	});

	it('does not render description when not provided', () => {
		const { container } = render(PageHeader, { props: { title: 'Home' } });
		expect(container.querySelectorAll('p')).toHaveLength(0);
	});

	it('renders actions snippet', () => {
		render(PageHeader, {
			props: { title: 'Projects', actions: createSnippet('Action Button') }
		});
		expect(screen.getByText('Action Button')).toBeInTheDocument();
	});

	it('applies sm size classes', () => {
		render(PageHeader, { props: { title: 'Small', size: 'sm' } });
		const h1 = screen.getByRole('heading', { level: 1 });
		expect(h1.className).toContain('text-xl');
	});

	it('applies lg size classes', () => {
		render(PageHeader, { props: { title: 'Large', size: 'lg' } });
		const h1 = screen.getByRole('heading', { level: 1 });
		expect(h1.className).toContain('text-2xl');
	});

	it('applies custom class', () => {
		const { container } = render(PageHeader, { props: { title: 'Test', class: 'mb-8' } });
		expect(container.firstElementChild?.className).toContain('mb-8');
	});
});

describe('SearchInput', () => {
	it('renders search input with role', () => {
		const { container } = render(SearchInput, { props: { value: '' } });
		expect(container.querySelector('[role="search"]')).toBeInTheDocument();
	});

	it('renders with default placeholder', () => {
		render(SearchInput, { props: { value: '' } });
		expect(screen.getByPlaceholderText('Search...')).toBeInTheDocument();
	});

	it('renders with custom placeholder', () => {
		render(SearchInput, { props: { value: '', placeholder: 'Find users...' } });
		expect(screen.getByPlaceholderText('Find users...')).toBeInTheDocument();
	});

	it('renders search icon', () => {
		const { container } = render(SearchInput, { props: { value: '' } });
		expect(container.querySelector('svg')).toBeInTheDocument();
	});

	it('does not show cancel button when showCancel is false', () => {
		render(SearchInput, { props: { value: 'test', showCancel: false } });
		expect(screen.queryByText('Cancel')).not.toBeInTheDocument();
	});

	it('shows cancel button when showCancel is true and value exists', () => {
		render(SearchInput, { props: { value: 'test', showCancel: true } });
		expect(screen.getByText('Cancel')).toBeInTheDocument();
	});

	it('does not show cancel button when showCancel is true but value is empty', () => {
		render(SearchInput, { props: { value: '', showCancel: true } });
		expect(screen.queryByText('Cancel')).not.toBeInTheDocument();
	});

	it('calls onclear when cancel clicked', async () => {
		const onclear = vi.fn();
		render(SearchInput, { props: { value: 'test', showCancel: true, onclear } });
		await fireEvent.click(screen.getByText('Cancel'));
		expect(onclear).toHaveBeenCalledOnce();
	});

	it('fires oninput event', async () => {
		const oninput = vi.fn();
		render(SearchInput, { props: { value: '', oninput } });
		const input = screen.getByRole('searchbox');
		await fireEvent.input(input, { target: { value: 'hello' } });
		expect(oninput).toHaveBeenCalled();
	});

	it('has aria-label derived from placeholder', () => {
		render(SearchInput, { props: { value: '', placeholder: 'Search...' } });
		const input = screen.getByRole('searchbox');
		expect(input).toHaveAttribute('aria-label', 'Search');
	});
});

describe('StatusBadge', () => {
	it('renders label text', () => {
		render(StatusBadge, { props: { label: 'Active' } });
		expect(screen.getByText('Active')).toBeInTheDocument();
	});

	it('applies default variant classes', () => {
		render(StatusBadge, { props: { label: 'Default' } });
		const badge = screen.getByText('Default');
		expect(badge.className).toContain('rounded-full');
		expect(badge.className).toContain('text-xs');
	});

	it('applies green variant', () => {
		render(StatusBadge, { props: { label: 'Online', variant: 'green' } });
		const badge = screen.getByText('Online');
		expect(badge.className).toContain('text-success');
	});

	it('applies coral variant', () => {
		render(StatusBadge, { props: { label: 'Error', variant: 'coral' } });
		const badge = screen.getByText('Error');
		expect(badge.className).toContain('text-accent');
	});

	it('applies warning variant', () => {
		render(StatusBadge, { props: { label: 'Warning', variant: 'warning' } });
		const badge = screen.getByText('Warning');
		expect(badge.className).toContain('text-amber-600');
	});

	it('applies muted variant', () => {
		render(StatusBadge, { props: { label: 'Inactive', variant: 'muted' } });
		const badge = screen.getByText('Inactive');
		expect(badge.className).toContain('text-foreground/50');
	});

	it('applies blue variant', () => {
		render(StatusBadge, { props: { label: 'Info', variant: 'blue' } });
		const badge = screen.getByText('Info');
		expect(badge.className).toContain('text-accent');
	});

	it('applies custom class', () => {
		render(StatusBadge, { props: { label: 'Custom', class: 'ml-2' } });
		const badge = screen.getByText('Custom');
		expect(badge.className).toContain('ml-2');
	});
});

describe('ConfirmationDialog', () => {
	it('renders title and message when open', () => {
		render(ConfirmationDialog, {
			props: {
				open: true,
				title: 'Delete item?',
				message: 'This action cannot be undone.',
				onconfirm: vi.fn(),
				oncancel: vi.fn()
			}
		});
		expect(screen.getByText('Delete item?')).toBeInTheDocument();
		expect(screen.getByText('This action cannot be undone.')).toBeInTheDocument();
	});

	it('renders default button labels', () => {
		render(ConfirmationDialog, {
			props: {
				open: true,
				title: 'Action required',
				message: 'Are you sure?',
				onconfirm: vi.fn(),
				oncancel: vi.fn()
			}
		});
		expect(screen.getByText('Cancel')).toBeInTheDocument();
		expect(screen.getByText('Confirm')).toBeInTheDocument();
	});

	it('renders custom button labels', () => {
		render(ConfirmationDialog, {
			props: {
				open: true,
				title: 'Remove',
				message: 'Remove this?',
				confirmLabel: 'Yes, remove',
				cancelLabel: 'No, keep',
				onconfirm: vi.fn(),
				oncancel: vi.fn()
			}
		});
		expect(screen.getByText('Yes, remove')).toBeInTheDocument();
		expect(screen.getByText('No, keep')).toBeInTheDocument();
	});

	it('calls onconfirm when confirm button clicked', async () => {
		const onconfirm = vi.fn();
		render(ConfirmationDialog, {
			props: {
				open: true,
				title: 'Delete?',
				message: 'Sure?',
				onconfirm,
				oncancel: vi.fn()
			}
		});
		await fireEvent.click(screen.getByText('Confirm'));
		expect(onconfirm).toHaveBeenCalledOnce();
	});

	it('calls oncancel when cancel button clicked', async () => {
		const oncancel = vi.fn();
		render(ConfirmationDialog, {
			props: {
				open: true,
				title: 'Delete?',
				message: 'Sure?',
				onconfirm: vi.fn(),
				oncancel
			}
		});
		await fireEvent.click(screen.getByText('Cancel'));
		expect(oncancel).toHaveBeenCalledOnce();
	});

	it('calls oncancel on Escape key', async () => {
		const oncancel = vi.fn();
		const { container } = render(ConfirmationDialog, {
			props: {
				open: true,
				title: 'Delete?',
				message: 'Sure?',
				onconfirm: vi.fn(),
				oncancel
			}
		});
		const dialog = container.querySelector('dialog')!;
		await fireEvent.keyDown(dialog, { key: 'Escape' });
		expect(oncancel).toHaveBeenCalledOnce();
	});

	it('applies destructive styling to confirm button', () => {
		render(ConfirmationDialog, {
			props: {
				open: true,
				title: 'Delete',
				message: 'Permanent',
				destructive: true,
				onconfirm: vi.fn(),
				oncancel: vi.fn()
			}
		});
		const confirmBtn = screen.getByText('Confirm');
		expect(confirmBtn.className).toContain('bg-red-500');
	});

	it('applies non-destructive styling by default', () => {
		render(ConfirmationDialog, {
			props: {
				open: true,
				title: 'Save',
				message: 'Save changes?',
				onconfirm: vi.fn(),
				oncancel: vi.fn()
			}
		});
		const confirmBtn = screen.getByText('Confirm');
		expect(confirmBtn.className).toContain('bg-accent');
	});

	it('has proper aria attributes', () => {
		const { container } = render(ConfirmationDialog, {
			props: {
				open: true,
				title: 'Test',
				message: 'Message',
				onconfirm: vi.fn(),
				oncancel: vi.fn()
			}
		});
		const dialog = container.querySelector('dialog');
		expect(dialog).toHaveAttribute('aria-labelledby', 'confirm-dialog-title');
		expect(dialog).toHaveAttribute('aria-describedby', 'confirm-dialog-message');
	});

	it('does not render content when closed', () => {
		render(ConfirmationDialog, {
			props: {
				open: false,
				title: 'Hidden',
				message: 'Not visible',
				onconfirm: vi.fn(),
				oncancel: vi.fn()
			}
		});
		expect(screen.queryByText('Hidden')).not.toBeInTheDocument();
	});
});

describe('ContextMenu', () => {
	const defaultItems = [
		{ label: 'Edit', action: vi.fn() },
		{ label: 'Delete', danger: true, action: vi.fn() }
	];

	it('renders children content', () => {
		render(ContextMenu, {
			props: { items: defaultItems, children: createSnippet('Right click me') }
		});
		expect(screen.getByText('Right click me')).toBeInTheDocument();
	});

	it('does not show menu initially', () => {
		render(ContextMenu, {
			props: { items: defaultItems, children: createSnippet('Content') }
		});
		expect(screen.queryByRole('menu')).not.toBeInTheDocument();
	});

	it('shows menu on right click', async () => {
		const { container } = render(ContextMenu, {
			props: { items: defaultItems, children: createSnippet('Content') }
		});
		const wrapper = container.firstElementChild!;
		await fireEvent.contextMenu(wrapper, { clientX: 100, clientY: 200 });
		expect(screen.getByRole('menu')).toBeInTheDocument();
		expect(screen.getByText('Edit')).toBeInTheDocument();
		expect(screen.getByText('Delete')).toBeInTheDocument();
	});

	it('renders menu items with menuitem role', async () => {
		const { container } = render(ContextMenu, {
			props: { items: defaultItems, children: createSnippet('Content') }
		});
		await fireEvent.contextMenu(container.firstElementChild!, { clientX: 100, clientY: 200 });
		const menuItems = screen.getAllByRole('menuitem');
		expect(menuItems).toHaveLength(2);
	});

	it('applies danger styling for danger items', async () => {
		const { container } = render(ContextMenu, {
			props: { items: defaultItems, children: createSnippet('Content') }
		});
		await fireEvent.contextMenu(container.firstElementChild!, { clientX: 100, clientY: 200 });
		const deleteBtn = screen.getByText('Delete');
		expect(deleteBtn.className).toContain('text-red-500');
	});

	it('calls item action and closes menu on click', async () => {
		const editAction = vi.fn();
		const items = [
			{ label: 'Edit', action: editAction },
			{ label: 'Delete', danger: true, action: vi.fn() }
		];
		const { container } = render(ContextMenu, {
			props: { items, children: createSnippet('Content') }
		});
		await fireEvent.contextMenu(container.firstElementChild!, { clientX: 100, clientY: 200 });
		await fireEvent.click(screen.getByText('Edit'));
		expect(editAction).toHaveBeenCalledOnce();
		expect(screen.queryByRole('menu')).not.toBeInTheDocument();
	});

	it('closes menu on Escape key', async () => {
		const { container } = render(ContextMenu, {
			props: { items: defaultItems, children: createSnippet('Content') }
		});
		await fireEvent.contextMenu(container.firstElementChild!, { clientX: 100, clientY: 200 });
		expect(screen.getByRole('menu')).toBeInTheDocument();
		await fireEvent.keyDown(window, { key: 'Escape' });
		expect(screen.queryByRole('menu')).not.toBeInTheDocument();
	});

	it('renders item with icon', async () => {
		const items = [{ label: 'Copy', icon: '📋', action: vi.fn() }];
		const { container } = render(ContextMenu, {
			props: { items, children: createSnippet('Content') }
		});
		await fireEvent.contextMenu(container.firstElementChild!, { clientX: 100, clientY: 200 });
		expect(screen.getByText('📋')).toBeInTheDocument();
	});
});
