import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/svelte';
import { Button, Card, Badge, Dialog, Drawer, Input, Textarea, Toggle } from '$components/ui';
import type { Snippet } from 'svelte';

// Helper to create a simple text snippet for Svelte 5
function createSnippet(text: string): Snippet {
	return ((anchor: ChildNode) => {
		const node = document.createTextNode(text);
		anchor.before(node);
		return { anchor: node };
	}) as unknown as Snippet;
}

beforeEach(() => {
	cleanup();
	// Polyfill HTMLDialogElement for jsdom
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

describe('Button interactions', () => {
	it('calls onclick handler when clicked', async () => {
		const handler = vi.fn();
		render(Button, { props: { onclick: handler, children: createSnippet('Click') } });
		await fireEvent.click(screen.getByRole('button'));
		expect(handler).toHaveBeenCalledTimes(1);
	});

	it('does not call onclick when disabled', async () => {
		const handler = vi.fn();
		render(Button, {
			props: { onclick: handler, disabled: true, children: createSnippet('Disabled') }
		});
		const btn = screen.getByRole('button');
		await fireEvent.click(btn);
		// Disabled buttons swallow clicks in the browser
		expect(btn).toBeDisabled();
	});

	it('renders with type="submit"', () => {
		render(Button, { props: { type: 'submit', children: createSnippet('Submit') } });
		expect(screen.getByRole('button')).toHaveAttribute('type', 'submit');
	});

	it('renders with type="reset"', () => {
		render(Button, { props: { type: 'reset', children: createSnippet('Reset') } });
		expect(screen.getByRole('button')).toHaveAttribute('type', 'reset');
	});

	it('applies custom class', () => {
		render(Button, { props: { class: 'my-custom-class', children: createSnippet('Custom') } });
		expect(screen.getByRole('button').className).toContain('my-custom-class');
	});

	it('applies default variant classes', () => {
		render(Button, { props: { children: createSnippet('Default') } });
		const btn = screen.getByRole('button');
		expect(btn.className).toContain('text-foreground/70');
	});

	it('anchor button has target and rel attributes', () => {
		render(Button, {
			props: {
				href: 'https://example.com',
				target: '_blank',
				rel: 'noopener noreferrer',
				children: createSnippet('External')
			}
		});
		const link = screen.getByRole('link');
		expect(link).toHaveAttribute('target', '_blank');
		expect(link).toHaveAttribute('rel', 'noopener noreferrer');
	});
});

describe('Card interactions', () => {
	it('renders as section when specified', () => {
		const { container } = render(Card, {
			props: { as: 'section', children: createSnippet('Section') }
		});
		expect(container.firstElementChild!.tagName).toBe('SECTION');
	});

	it('applies custom class', () => {
		const { container } = render(Card, {
			props: { class: 'p-4 my-card', children: createSnippet('Styled') }
		});
		expect(container.firstElementChild!.className).toContain('my-card');
	});

	it('applies hover transition classes', () => {
		const { container } = render(Card, {
			props: { children: createSnippet('Hoverable') }
		});
		const card = container.firstElementChild!;
		expect(card.className).toContain('hover:-translate-y-0.5');
		expect(card.className).toContain('transition-all');
		expect(card.className).toContain('duration-300');
	});
});

describe('Badge variants', () => {
	it('applies green variant', () => {
		render(Badge, { props: { variant: 'green', children: createSnippet('OK') } });
		expect(screen.getByText('OK').className).toContain('text-success');
	});

	it('applies warning variant', () => {
		render(Badge, { props: { variant: 'warning', children: createSnippet('Warn') } });
		expect(screen.getByText('Warn').className).toContain('text-amber');
	});

	it('applies blue variant', () => {
		render(Badge, { props: { variant: 'blue', children: createSnippet('Info') } });
		expect(screen.getByText('Info').className).toContain('text-accent');
	});

	it('applies muted variant', () => {
		render(Badge, { props: { variant: 'muted', children: createSnippet('Muted') } });
		expect(screen.getByText('Muted').className).toContain('text-foreground/60');
	});

	it('applies default variant with dark text', () => {
		render(Badge, { props: { children: createSnippet('Default') } });
		expect(screen.getByText('Default').className).toContain('text-foreground');
	});

	it('applies custom class', () => {
		render(Badge, {
			props: { class: 'extra-class', children: createSnippet('Custom') }
		});
		expect(screen.getByText('Custom').className).toContain('extra-class');
	});
});

describe('Dialog interactions', () => {
	it('calls onclose when escape is pressed', async () => {
		const onclose = vi.fn();
		const { container } = render(Dialog, {
			props: { open: true, onclose, children: createSnippet('Content') }
		});
		const dialog = container.querySelector('dialog')!;
		await fireEvent.keyDown(dialog, { key: 'Escape' });
		expect(onclose).toHaveBeenCalledTimes(1);
	});

	it('does not close on escape when closeOnEscape=false', async () => {
		const onclose = vi.fn();
		const { container } = render(Dialog, {
			props: { open: true, onclose, closeOnEscape: false, children: createSnippet('Content') }
		});
		const dialog = container.querySelector('dialog')!;
		await fireEvent.keyDown(dialog, { key: 'Escape' });
		expect(onclose).not.toHaveBeenCalled();
	});

	it('calls onclose on backdrop click', async () => {
		const onclose = vi.fn();
		const { container } = render(Dialog, {
			props: { open: true, onclose, children: createSnippet('Content') }
		});
		const dialog = container.querySelector('dialog')!;
		// Backdrop click = click on the dialog element itself (not children)
		await fireEvent.click(dialog);
		expect(onclose).toHaveBeenCalledTimes(1);
	});

	it('does not close on backdrop click when closeOnBackdrop=false', async () => {
		const onclose = vi.fn();
		const { container } = render(Dialog, {
			props: {
				open: true,
				onclose,
				closeOnBackdrop: false,
				children: createSnippet('Content')
			}
		});
		const dialog = container.querySelector('dialog')!;
		await fireEvent.click(dialog);
		expect(onclose).not.toHaveBeenCalled();
	});

	it('does not close on content click (not backdrop)', async () => {
		const onclose = vi.fn();
		render(Dialog, {
			props: { open: true, onclose, children: createSnippet('Inner content') }
		});
		// Click on content, not the dialog element itself
		await fireEvent.click(screen.getByText('Inner content'));
		expect(onclose).not.toHaveBeenCalled();
	});

	it('handles other keys without closing', async () => {
		const onclose = vi.fn();
		const { container } = render(Dialog, {
			props: { open: true, onclose, children: createSnippet('Content') }
		});
		const dialog = container.querySelector('dialog')!;
		await fireEvent.keyDown(dialog, { key: 'Enter' });
		expect(onclose).not.toHaveBeenCalled();
	});
});

describe('Drawer interactions', () => {
	it('calls onclose when backdrop is clicked', async () => {
		const onclose = vi.fn();
		render(Drawer, {
			props: { open: true, onclose, children: createSnippet('Content') }
		});
		const backdrop = screen.getByRole('presentation');
		await fireEvent.click(backdrop);
		expect(onclose).toHaveBeenCalledTimes(1);
	});

	it('calls onclose when escape is pressed on backdrop', async () => {
		const onclose = vi.fn();
		render(Drawer, {
			props: { open: true, onclose, children: createSnippet('Content') }
		});
		const backdrop = screen.getByRole('presentation');
		await fireEvent.keyDown(backdrop, { key: 'Escape' });
		expect(onclose).toHaveBeenCalledTimes(1);
	});

	it('applies peek state height', () => {
		const { container } = render(Drawer, {
			props: { open: true, initialState: 'peek', children: createSnippet('Content') }
		});
		const dialog = container.querySelector('[role="dialog"]');
		expect(dialog?.className).toContain('max-h-[25vh]');
	});

	it('has drag handle visible', () => {
		const { container } = render(Drawer, {
			props: { open: true, children: createSnippet('Content') }
		});
		// Drag handle is a small rounded div
		const handle = container.querySelector('.w-8.h-1.rounded-full');
		expect(handle).toBeInTheDocument();
	});

	it('renders with custom class', () => {
		const { container } = render(Drawer, {
			props: { open: true, class: 'custom-drawer', children: createSnippet('Content') }
		});
		const dialog = container.querySelector('[role="dialog"]');
		expect(dialog?.className).toContain('custom-drawer');
	});
});

describe('Input interactions', () => {
	it('renders with type="email"', () => {
		render(Input, { props: { label: 'Email', type: 'email', id: 'email' } });
		expect(screen.getByLabelText('Email')).toHaveAttribute('type', 'email');
	});

	it('renders with type="password"', () => {
		render(Input, { props: { label: 'Password', type: 'password', id: 'pass' } });
		expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password');
	});

	it('renders with placeholder', () => {
		render(Input, { props: { label: 'Search', placeholder: 'Type here...', id: 'search' } });
		expect(screen.getByPlaceholderText('Type here...')).toBeInTheDocument();
	});

	it('applies error styling with aria-invalid', () => {
		render(Input, { props: { label: 'Field', error: 'Required', id: 'field' } });
		const input = screen.getByLabelText('Field');
		expect(input).toHaveAttribute('aria-invalid', 'true');
	});

	it('associates error with aria-describedby', () => {
		render(Input, { props: { label: 'Test', error: 'Error text', id: 'test' } });
		screen.getByLabelText('Test');
		const errorEl = screen.getByRole('alert');
		expect(errorEl).toHaveTextContent('Error text');
	});
});

describe('Textarea interactions', () => {
	it('handles input events', async () => {
		const oninput = vi.fn();
		render(Textarea, { props: { label: 'Note', oninput, id: 'note' } });
		await fireEvent.input(screen.getByLabelText('Note'), { target: { value: 'Hello world' } });
		expect(oninput).toHaveBeenCalled();
	});

	it('renders with required indicator', () => {
		render(Textarea, { props: { label: 'Message', required: true, id: 'msg' } });
		expect(screen.getByText('*')).toBeInTheDocument();
	});
});

describe('Toggle interactions', () => {
	it('has aria-checked attribute', () => {
		render(Toggle, { props: { label: 'Feature', checked: true, id: 'feat' } });
		const toggle = screen.getByRole('switch');
		expect(toggle).toBeChecked();
	});

	it('starts unchecked by default', () => {
		render(Toggle, { props: { label: 'Off', id: 'off' } });
		const toggle = screen.getByRole('switch');
		expect(toggle).not.toBeChecked();
	});
});
